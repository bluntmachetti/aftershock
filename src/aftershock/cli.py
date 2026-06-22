"""Aftershock CLI: run | verify | replay | bench | smoke-llm | aar | episodes.

aftershock run    --seed 42 --ticks 60 --arm scripted|solo|swarm|society [--out runs]
                  [--quiet] [--timeout S] [--memory]
aftershock bench  [--manifest bench/default.yaml] [--arms a,b] [--seeds 1,2] [--ticks N]
                  [--out DIR] [--fresh]
aftershock verify --seed 42 --ticks 60
aftershock replay <run_dir>
aftershock smoke-llm [--model qwen3.5-flash]
aftershock aar <run_dir> [--show]
aftershock episodes --n 5 --seed-base 100 [--ticks 60] [--out runs/episodes]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from aftershock.kernel.engine import Engine
from aftershock.kernel.recorder import Recorder, load_run
from aftershock.town.arms import ARMS, build_arm

_BENCH_DEFAULT_MANIFEST = Path(__file__).parent.parent.parent / "bench" / "default.yaml"

# Friendly exit-2 hint printed when a key is required but absent
_KEY_HINT = (
    "No DASHSCOPE_API_KEY set. Please export DASHSCOPE_API_KEY=<your-key>\n"
    "Get a key at https://dashscope.aliyuncs.com — then re-run this command."
)

_LLM_ARMS = {"society", "solo", "swarm"}


def _provider_for_arm(arm: str, timeout_s: float) -> Any | None:
    """Return a live QwenProvider for LLM arms, None for scripted.

    Prints the friendly exit-2 hint and exits with code 2 when the key is missing.
    """
    if arm not in _LLM_ARMS:
        return None
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print(_KEY_HINT)
        sys.exit(2)
    from aftershock.llm.provider import QwenProvider
    return QwenProvider(api_key=api_key, timeout_s=timeout_s)


def _endpoint_label_for_provider(provider: Any | None) -> str:
    """Provenance endpoint label for a (possibly None) provider.

    None -> "scripted" (LLM-free run). Otherwise reuse the provider's resolved
    base_url through llm.provider.endpoint_label, which mirrors the provider's own
    DashScope-vs-local detection ("dashscope" in base_url -> "dashscope-intl").
    """
    if provider is None:
        return "scripted"
    base_url = getattr(provider, "base_url", None)
    if base_url is None:
        return "scripted"
    from aftershock.llm.provider import endpoint_label

    return endpoint_label(base_url)


def _run_id(seed: int, arm: str) -> str:
    return f"seed{seed}-{arm}"


def _parse_pools(spec: str | None) -> dict[str, int] | None:
    """Parse --pools: a preset name (e.g. 'tight') or a 'kind=N,kind=N' override.

    Returns None when spec is None (the canonical world). Exits 1 with a friendly
    message on a bad preset, unknown resource kind, or non-positive/non-integer value.
    """
    if spec is None:
        return None
    from aftershock.town.state import POOL_SIZES, SCARCITY_PRESETS

    spec = spec.strip()
    if spec in SCARCITY_PRESETS:
        return dict(SCARCITY_PRESETS[spec])
    override: dict[str, int] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            print(
                f"error: --pools entry {part!r} must be 'kind=N' or a preset name "
                f"({sorted(SCARCITY_PRESETS)})",
                file=sys.stderr,
            )
            raise SystemExit(1)
        k, v = (s.strip() for s in part.split("=", 1))
        if k not in POOL_SIZES:
            print(f"error: unknown pool kind {k!r}; valid: {sorted(POOL_SIZES)}", file=sys.stderr)
            raise SystemExit(1)
        try:
            n = int(v)
        except ValueError:
            print(f"error: --pools value for {k!r} must be an integer, got {v!r}", file=sys.stderr)
            raise SystemExit(1) from None
        if n < 1:
            print(f"error: --pools value for {k!r} must be >= 1, got {n}", file=sys.stderr)
            raise SystemExit(1)
        override[k] = n
    return override or None


# Town roles a --role-model override may target (society + swarm + solo rosters).
_ROLE_MODEL_ROLES = frozenset(
    {"commander", "comms", "fire", "infrastructure", "medical", "rescue", "solo"}
)


def _parse_role_models(spec: str | None) -> dict[str, str] | None:
    """Parse --role-model: a 'role=model,role=model' per-role model override.

    Enables operating modes like the §20 high-conformance infra bump
    (``infrastructure=qwen3.5-plus``). Returns None when spec is None (the
    cost-optimal YAML mix). Exits 1 on a malformed entry, unknown role, or a model
    not in the price table (an unpriced model would silently cost $0).
    """
    if spec is None:
        return None
    from aftershock.llm.provider import MODEL_PRICES_USD_PER_MTOK

    override: dict[str, str] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            print(f"error: --role-model entry {part!r} must be 'role=model'", file=sys.stderr)
            raise SystemExit(1)
        role, model = (s.strip() for s in part.split("=", 1))
        if role not in _ROLE_MODEL_ROLES:
            print(
                f"error: unknown role {role!r}; valid: {sorted(_ROLE_MODEL_ROLES)}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if model not in MODEL_PRICES_USD_PER_MTOK:
            print(
                f"error: unknown model {model!r}; priced models: "
                f"{sorted(MODEL_PRICES_USD_PER_MTOK)}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        override[role] = model
    return override or None


def _resolve_role_models(args: argparse.Namespace) -> dict[str, str] | None:
    """Per-role model overrides, merging the DASHSCOPE_MODEL global env with --role-model.

    DASHSCOPE_MODEL (when set) applies to *every* role — convenient for pointing the
    whole society at one self-hosted model (e.g. a local Ollama `qwen3.5:9b`) without
    a six-part --role-model string. Explicit --role-model entries win per role. The
    global env path skips the priced-model check (a self-hosted model is unpriced →
    cost logs $0, which is honest), so it works with any Ollama tag.
    """
    rm = _parse_role_models(getattr(args, "role_model", None)) or {}
    global_model = os.environ.get("DASHSCOPE_MODEL")
    if global_model:
        rm = {**{role: global_model for role in _ROLE_MODEL_ROLES}, **rm}
    return rm or None


# Default extra ticks past the last timeline tick, and the engine ceiling.
_SCENARIO_TICK_PADDING = 20
_SCENARIO_TICK_CEILING = 120

# Scenario id grammar (dir name == id; same traversal guard as the web layer).
import re as _re  # noqa: E402

_SCENARIO_ID_RE = _re.compile(r"^[a-z0-9][a-z0-9-]*$")

_SCENARIOS_DIR = Path(__file__).parent.parent.parent / "scenarios"


def _resolve_scenario(scenario_id: str) -> Any:
    """Resolve and load scenarios/<id>/scenario.json.

    Returns the validated ScenarioPack, or prints a friendly error and raises
    SystemExit(1) when the id is malformed or the pack is missing/invalid.
    """
    from aftershock.town.scenario import load_scenario

    if not _SCENARIO_ID_RE.match(scenario_id):
        print(
            f"error: invalid scenario id {scenario_id!r} "
            "(must match ^[a-z0-9][a-z0-9-]*$)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    pack_path = _SCENARIOS_DIR / scenario_id / "scenario.json"
    if not pack_path.is_file():
        print(f"error: scenario not found: {pack_path}", file=sys.stderr)
        raise SystemExit(1)
    try:
        return load_scenario(pack_path)
    except Exception as exc:  # noqa: BLE001 — surface a friendly one-liner
        print(f"error: failed to load scenario {scenario_id!r}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _scenario_ticks(pack: Any, requested_ticks: int | None) -> int:
    """Compute the tick budget for a scenario run.

    Default (ticks omitted): min(last timeline tick + 20, 120). An explicit
    under-budget --ticks is a HARD ERROR (never silent truncation). The budget
    itself comes from the shared ``scenario_tick_budget`` helper so the CLI and
    the live API (web.py) never disagree.
    """
    from aftershock.town.scenario import scenario_tick_budget

    default_ticks = scenario_tick_budget(pack)
    if requested_ticks is None:
        return default_ticks
    if requested_ticks < default_ticks:
        print(
            f"error: --ticks {requested_ticks} is under the scenario budget "
            f"({default_ticks} = min(last timeline tick + {_SCENARIO_TICK_PADDING}, "
            f"{_SCENARIO_TICK_CEILING})); refusing to silently truncate. "
            f"Omit --ticks or pass >= {default_ticks}.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return requested_ticks


def cmd_run(args: argparse.Namespace) -> int:
    arm: str = args.arm
    out_dir = Path(args.out)
    quiet: bool = args.quiet
    memory: bool = getattr(args, "memory", False)
    scenario_id: str | None = getattr(args, "scenario", None)
    requested_ticks: int | None = args.ticks
    requested_seed: int | None = args.seed

    # Resolve scenario pack (if any) and compute the tick budget.
    scenario = None
    if scenario_id is not None:
        # Scenario mode: the pack drives the timeline; seed defaults to a fixed
        # value so a presenter can `run --scenario <id>` with no extra flags. The
        # seed still governs every other rng_for stream and replay.
        seed: int = requested_seed if requested_seed is not None else 42
        scenario = _resolve_scenario(scenario_id)
        ticks: int = _scenario_ticks(scenario, requested_ticks)
    else:
        if requested_seed is None:
            print(
                "error: --seed is required for synthetic runs (or use --scenario)",
                file=sys.stderr,
            )
            return 1
        seed = requested_seed
        if requested_ticks is None:
            print("error: --ticks is required (or use --scenario)", file=sys.stderr)
            return 1
        ticks = requested_ticks

    # --memory is only meaningful for society arm; require provider
    if memory and arm != "society":
        print(
            f"error: --memory is only supported for --arm society (got {arm!r})",
            file=sys.stderr,
        )
        return 1

    # Determine default timeout based on arm
    _ARM_DEFAULT_TIMEOUT = {"scripted": 5.0, "solo": 90.0, "swarm": 45.0, "society": 45.0}
    timeout_s: float = (
        args.timeout if args.timeout is not None else _ARM_DEFAULT_TIMEOUT.get(arm, 30.0)
    )

    # Key check before any work (exits 2 with hint if key missing for LLM arms)
    provider = _provider_for_arm(arm, timeout_s)

    # Load lessons from memory when requested
    lessons: list[str] | None = None
    if memory and arm == "society":
        from aftershock.llm.aar import load_lessons
        memory_path = out_dir / "memory.json"
        lessons = load_lessons(memory_path) or None  # keep None when empty

    run_id = _run_id(seed, arm)
    pool_sizes = _parse_pools(getattr(args, "pools", None))
    if pool_sizes is not None and scenario is not None:
        print(
            "warning: --pools is ignored with --scenario (a pack defines its own pools)",
            file=sys.stderr,
        )
    setup = build_arm(
        arm, seed, provider, lessons=lessons, scenario=scenario,
        society_tools=getattr(args, "society_tools", False),
        seed_sampler=getattr(args, "seed_sampler", False),
        pool_sizes=pool_sizes,
        role_models=_resolve_role_models(args),
    )

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "seed": seed,
        "ticks": ticks,
        "arm": arm,
    }
    if scenario is not None:
        # Emit the full provenance block (source, field_provenance, caveat_line,
        # reference_aggregates) so the UI can render provenance from run.json
        # without a second fetch (DESIGN.md engine integration). Reuse the single
        # web serializer so the CLI and live-run manifests never drift.
        from aftershock.web import _scenario_manifest_block

        manifest["scenario"] = _scenario_manifest_block(scenario)
    recorder = Recorder(out_dir, run_id, manifest)
    engine = Engine(
        world=setup.world,
        society=setup.society,
        agents=setup.agents,
        registry=setup.registry,
        roles=setup.roles,
        resolver=setup.resolver,
        recorder=recorder,
        seed=seed,
        max_ticks=ticks,
        agent_timeout_s=timeout_s,
    )

    summary = asyncio.run(engine.run())

    if not quiet:
        print(f"Run {summary.run_id}  seed={summary.seed}  ticks={summary.ticks_run}")
        print("-" * 60)
        s = summary.final_scores
        print(f"  Lives saved:  {int(s.get('lives_saved', 0))}")
        print(f"  Lives lost:   {int(s.get('lives_lost', 0))}")
        print(f"  Missions resolved: {int(s.get('missions_resolved', 0))}")
        print(f"  Missions failed:   {int(s.get('missions_failed', 0))}")
        print(f"  Missions open:     {int(s.get('missions_open', 0))}")
        print(f"  Panic:        {s.get('panic', 0.0):.3f}")
        print(f"  Cost USD:     {summary.cost.get('cost_usd', 0.0):.4f}")
        print(f"  Run dir:      {summary.run_dir}")

    # Memory loop: generate AAR and append lessons after a society run with --memory
    if memory and arm == "society":
        from aftershock.llm.aar import append_lessons, generate_aar
        if not quiet:
            print("  Generating AAR…")
        run_dir = Path(summary.run_dir)
        aar = asyncio.run(generate_aar(run_dir, provider))
        if not quiet:
            print(f"  AAR grade: {aar.get('grade', '?')}  — {aar.get('headline', '')}")
        memory_path = out_dir / "memory.json"
        append_lessons(memory_path, run_id, aar.get("lessons", []))
        if not quiet:
            print(f"  Lessons appended to {memory_path}")

    return 0


def cmd_counterfactual(args: argparse.Namespace) -> int:
    """Run a counterfactual branch: re-run a seed with one intervention at tick N.

    The intervention runs from tick N onward; the run shares a byte-identical prefix
    with the equivalent baseline (same seed) and diverges only at N. The branch is
    written to a distinct run_id (so it never overwrites a baseline run) and is
    replayable by every observatory surface.
    """
    from aftershock.town.counterfactual import Intervention, run_counterfactual

    arm: str = args.arm
    out_dir = Path(args.out)
    quiet: bool = args.quiet
    seed: int = args.seed
    ticks: int = args.ticks
    at_tick: int = args.at
    kind: str = args.kind

    if at_tick < 0 or at_tick >= ticks:
        print(
            f"error: --at must be in [0, {ticks}) (got {at_tick})", file=sys.stderr
        )
        return 1

    params: dict[str, Any] = {}
    if kind == "inject_event":
        if not args.target:
            print("error: --target <district> is required for inject_event", file=sys.stderr)
            return 1
        params["event"] = args.event
    if kind == "kill_agent" and not args.target:
        print("error: --target <agent_id> is required for kill_agent", file=sys.stderr)
        return 1

    try:
        intervention = Intervention(
            at_tick=at_tick, kind=kind, target=args.target or "", params=params
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _ARM_DEFAULT_TIMEOUT = {"scripted": 5.0, "solo": 90.0, "swarm": 45.0, "society": 45.0}
    timeout_s = _ARM_DEFAULT_TIMEOUT.get(arm, 30.0)
    provider = _provider_for_arm(arm, timeout_s)

    baseline_run_id = _run_id(seed, arm)
    # "-at{N}" (not "@{N}") so the run id stays loadable via /api/runs/{id}
    # (web's _RUN_ID_RE forbids "@").
    tag = kind if kind == "none" else f"{kind}-at{at_tick}"
    run_id = f"{baseline_run_id}-cf-{tag}"

    try:
        summary = asyncio.run(
            run_counterfactual(
                arm=arm,
                seed=seed,
                ticks=ticks,
                intervention=intervention,
                runs_root=out_dir,
                run_id=run_id,
                provider=provider,
                baseline_run_id=baseline_run_id,
            )
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not quiet:
        s = summary.final_scores
        print(f"Counterfactual {summary.run_id}  ({kind} @ tick {at_tick})")
        print("-" * 60)
        print(f"  Branch of:    {baseline_run_id}")
        print(f"  Lives saved:  {int(s.get('lives_saved', 0))}")
        print(f"  Lives lost:   {int(s.get('lives_lost', 0))}")
        print(f"  Missions failed:   {int(s.get('missions_failed', 0))}")
        print(f"  Run dir:      {summary.run_dir}")

    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    """Run the benchmark suite from a manifest with optional flag overrides."""
    # Invariant 3 (bench fairness): scenario packs are demo/observatory surfaces
    # only. Published benchmark results stay synthetic-seed.
    if getattr(args, "scenario", None) is not None:
        print(
            "error: bench does not accept --scenario. Scenario packs are "
            "demo/observatory surfaces only; benchmark results stay synthetic-seed "
            "(invariant 3). Use 'aftershock run --scenario' or 'verify --scenario'.",
            file=sys.stderr,
        )
        return 1

    import yaml  # type: ignore[import-untyped]

    from aftershock.bench import aggregate, render_markdown, run_bench

    # Load manifest
    manifest_path = Path(args.manifest) if args.manifest else _BENCH_DEFAULT_MANIFEST
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as fh:
            manifest: dict[str, Any] = yaml.safe_load(fh) or {}
    else:
        # Sensible fallback when no manifest file exists
        manifest = {
            "ticks": 60,
            "seeds": [42],
            "arms": ["scripted"],
            "out": "runs/bench",
        }

    # Apply flag overrides
    if args.arms:
        arm_list = [a.strip() for a in args.arms.split(",") if a.strip()]
        for a in arm_list:
            if a not in ARMS:
                print(f"error: unknown arm {a!r}; valid: {ARMS}", file=sys.stderr)
                return 1
        manifest["arms"] = arm_list
    if args.seeds:
        try:
            manifest["seeds"] = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
        except ValueError:
            print("error: --seeds must be comma-separated integers (e.g. 42,57)", file=sys.stderr)
            return 1
    if args.ticks is not None:
        manifest["ticks"] = args.ticks

    out_dir = Path(args.out) if args.out else Path(manifest.get("out", "runs/bench"))

    # Key check: if any LLM arm is requested, ensure the key is present first
    requested_arms: list[str] = manifest.get("arms", ["scripted"])
    needs_llm = any(a in _LLM_ARMS for a in requested_arms)
    provider: Any = None
    if needs_llm:
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        if not api_key:
            print(_KEY_HINT)
            return 2
        from aftershock.llm.provider import QwenProvider
        provider = QwenProvider(api_key=api_key)

    seed_sampler = getattr(args, "seed_sampler", False)
    society_tools = getattr(args, "society_tools", False)
    pool_sizes = _parse_pools(getattr(args, "pools", None))
    role_models = _resolve_role_models(args)
    repeat = getattr(args, "repeat_seeds", 1) or 1

    # M2: --repeat-seeds N runs each (arm, seed) N times into ...-r{k} cells and
    # reports a within-seed (LLM) vs between-seed (world) variance decomposition.
    if repeat > 1:
        if seed_sampler:
            # M1 (--seed-sampler) sends an identical per-tick seed to every repeat,
            # so it removes the exact within-seed LLM variance that M2 measures.
            print(
                "error: --repeat-seeds and --seed-sampler are contradictory. "
                "--repeat-seeds measures within-seed LLM sampling variance, which "
                "--seed-sampler (M1) is designed to remove (every repeat would get "
                "the same provider seed → artificially ~0 within-seed variance). "
                "Use one or the other.",
                file=sys.stderr,
            )
            return 1
        from aftershock.bench import (
            analyze_repeats,
            render_repeats_markdown,
            run_repeat_seeds,
        )

        seeds_list = manifest.get("seeds", [])
        if args.fresh:
            for arm in requested_arms:
                for seed in seeds_list:
                    for k in range(repeat):
                        cell_dir = out_dir / f"{arm}-seed{seed}-r{k}"
                        if cell_dir.exists():
                            shutil.rmtree(cell_dir)
        cells = run_repeat_seeds(
            requested_arms, seeds_list, repeat, manifest["ticks"],
            provider, out_dir, society_tools=society_tools, seed_sampler=seed_sampler,
            pool_sizes=pool_sizes, role_models=role_models,
        )
        rep = analyze_repeats(cells, model_endpoint=_endpoint_label_for_provider(provider))
        md = render_repeats_markdown(rep)
        print(md)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "repeats.json").write_text(
            json.dumps(rep, indent=2, sort_keys=True), encoding="utf-8"
        )
        (out_dir / "REPEATS.md").write_text(md, encoding="utf-8")
        return 0

    # --fresh: wipe each cell directory before running
    if args.fresh:
        for arm in requested_arms:
            for seed in manifest.get("seeds", []):
                cell_dir = out_dir / f"{arm}-seed{seed}"
                if cell_dir.exists():
                    shutil.rmtree(cell_dir)

    cells = run_bench(
        manifest, provider=provider, out_dir=out_dir,
        society_tools=society_tools, seed_sampler=seed_sampler, pool_sizes=pool_sizes,
        role_models=role_models,
    )
    agg = aggregate(cells, model_endpoint=_endpoint_label_for_provider(provider))
    md = render_markdown(agg)

    # Print the markdown table to stdout
    print(md)

    # Write results.json and RESULTS.md
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps(agg, indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "RESULTS.md").write_text(md, encoding="utf-8")

    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    scenario_id: str | None = getattr(args, "scenario", None)
    requested_ticks: int | None = args.ticks
    requested_seed: int | None = args.seed

    scenario = None
    if scenario_id is not None:
        # Scenario mode: the pack drives the timeline. A seed is still part of
        # the determinism contract (same pack + same seed = byte-identical), but
        # it is optional on the CLI and defaults to a fixed value so a presenter
        # can run `verify --scenario <id>` with no extra flags.
        seed: int = requested_seed if requested_seed is not None else 42
        scenario = _resolve_scenario(scenario_id)
        ticks: int = _scenario_ticks(scenario, requested_ticks)
    else:
        if requested_seed is None:
            print(
                "error: --seed is required for synthetic verification "
                "(or use --scenario)",
                file=sys.stderr,
            )
            return 1
        seed = requested_seed
        if requested_ticks is None:
            print("error: --ticks is required (or use --scenario)", file=sys.stderr)
            return 1
        ticks = requested_ticks

    async def _run_into(tmp: Path, tag: str) -> list[str]:
        run_id = f"verify-{tag}"
        setup = build_arm("scripted", seed, None, scenario=scenario)
        manifest: dict[str, Any] = {
            "run_id": run_id, "seed": seed, "ticks": ticks, "arm": "scripted",
        }
        recorder = Recorder(tmp, run_id, manifest)
        engine = Engine(
            world=setup.world,
            society=setup.society,
            agents=setup.agents,
            registry=setup.registry,
            roles=setup.roles,
            resolver=setup.resolver,
            recorder=recorder,
            seed=seed,
            max_ticks=ticks,
            agent_timeout_s=setup.default_timeout_s,
        )
        await engine.run()
        _, records, _worlds = load_run(tmp / run_id)
        return [r.world_digest for r in records]

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        async def _both() -> tuple[list[str], list[str]]:
            a = await _run_into(tmp / "a", "a")
            b = await _run_into(tmp / "b", "b")
            return a, b

        digests_a, digests_b = asyncio.run(_both())

    if digests_a == digests_b:
        print("PASS — both runs produced identical world-digest sequences")
        return 0
    else:
        print("FAIL — digest mismatch")
        for i, (da, db) in enumerate(zip(digests_a, digests_b, strict=False)):
            if da != db:
                print(f"  tick {i}: run1={da[:16]}… run2={db[:16]}…")
        return 1


def cmd_replay(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"error: run directory not found: {run_dir}", file=sys.stderr)
        return 1

    manifest, records, _worlds = load_run(run_dir)
    print(f"Replay: {run_dir.name}  seed={manifest.get('seed')}  arm={manifest.get('arm')}")
    print(f"{'Tick':>5}  {'Saved':>6}  {'Lost':>6}  {'Open':>5}  {'Res':>5}  {'Fail':>5}  {'Panic':>7}")  # noqa: E501
    print("-" * 50)

    for record in records:
        s = record.scores
        tick = record.tick
        saved = int(s.get("lives_saved", 0))
        lost = int(s.get("lives_lost", 0))
        open_m = int(s.get("missions_open", 0))
        res = int(s.get("missions_resolved", 0))
        fail = int(s.get("missions_failed", 0))
        panic = s.get("panic", 0.0)
        print(f"{tick:>5}  {saved:>6}  {lost:>6}  {open_m:>5}  {res:>5}  {fail:>5}  {panic:>7.3f}")

    if records:
        s = records[-1].scores
        print("-" * 50)
        print(f"Final: lives_saved={int(s.get('lives_saved', 0))}  "
              f"lives_lost={int(s.get('lives_lost', 0))}  "
              f"panic={s.get('panic', 0.0):.3f}")

    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the FastAPI observatory server via uvicorn."""
    try:
        import uvicorn
    except ImportError:
        print(
            "error: uvicorn is required for 'serve'. Install it with: pip install uvicorn",
            file=sys.stderr,
        )
        return 1

    from aftershock.web import create_app

    runs_dir = Path(args.runs_dir)
    host: str = args.host
    port: int = args.port

    app = create_app(runs_root=runs_dir, host=host)
    uvicorn.run(app, host=host, port=port)
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    """Start the MCP spectator server (stdio transport)."""
    from aftershock.mcp_server import create_server

    runs_dir = Path(args.runs_dir)
    server = create_server(runs_root=runs_dir)
    server.run(transport="stdio")
    return 0


def cmd_smoke_llm(args: argparse.Namespace) -> int:
    """Make one tiny JSON-mode call and print reply, token counts, and cost."""
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print(_KEY_HINT)
        return 2

    model: str = args.model

    from aftershock.llm.provider import QwenProvider

    provider = QwenProvider(api_key=api_key)

    system = (
        "You are a test assistant. Respond with ONLY a JSON object. "
        'Example: {"status": "ok", "message": "hello"}'
    )
    user = (
        'Respond with a tiny JSON object containing exactly two fields: '
        '"status" (value "ok") and "tick" (value 1). '
        "Output only valid JSON, no markdown."
    )

    async def _call() -> None:
        result = await provider.chat(
            model=model,
            system=system,
            user=user,
            temperature=0.0,
            json_mode=True,
        )
        print(f"Reply:             {result.text}")
        print(f"Prompt tokens:     {result.usage.prompt_tokens}")
        print(f"Completion tokens: {result.usage.completion_tokens}")
        print(f"Cost USD:          {result.usage.cost_usd:.6f}")

    asyncio.run(_call())
    return 0


def cmd_aar(args: argparse.Namespace) -> int:
    """Generate (or display) an after-action report for a completed run."""
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"error: run directory not found: {run_dir}", file=sys.stderr)
        return 1

    from aftershock.llm.aar import generate_aar

    aar_path = run_dir / "aar.json"

    if getattr(args, "show", False):
        # --show: display existing AAR without regenerating
        if not aar_path.exists():
            print(f"error: no aar.json in {run_dir}", file=sys.stderr)
            return 1
        aar = json.loads(aar_path.read_text(encoding="utf-8"))
        print(json.dumps(aar, indent=2))
        return 0

    # Generate: require a provider
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print(_KEY_HINT)
        return 2

    from aftershock.llm.provider import QwenProvider

    provider = QwenProvider(api_key=api_key)
    aar = asyncio.run(generate_aar(run_dir, provider))
    print(json.dumps(aar, indent=2))
    return 0


def cmd_conformance(args: argparse.Namespace) -> int:
    """Check a completed run against all 18 doctrine rules."""
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"error: run directory not found: {run_dir}", file=sys.stderr)
        return 1

    from aftershock.town.conformance import check_run, render_markdown

    report = check_run(run_dir)

    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_markdown(report))

    return 0


def cmd_ablation(args: argparse.Namespace) -> int:
    """Paired control-vs-treatment ablation with sign test, CI, and power curve (M3)."""
    from aftershock.bench import render_ablation_markdown, run_ablation

    control: str = args.control
    treatment: str = args.treatment
    ablate: str | None = getattr(args, "ablate", None)
    for a in (control, treatment):
        if a not in ARMS:
            print(f"error: unknown arm {a!r}; valid: {ARMS}", file=sys.stderr)
            return 1
    if ablate == "doctrine":
        if control != treatment:
            print(
                "error: --ablate doctrine requires --control == --treatment "
                f"(the arm to ablate); got control={control!r}, treatment={treatment!r}",
                file=sys.stderr,
            )
            return 1
        if control == "scripted":
            print(
                "error: the scripted arm carries no doctrine prompts — "
                "ablate an LLM arm (society/swarm/solo)",
                file=sys.stderr,
            )
            return 1

    try:
        seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
    except ValueError:
        print("error: --seeds must be comma-separated integers (e.g. 11,23,37)",
              file=sys.stderr)
        return 1
    if not seeds:
        print("error: --seeds is required (e.g. --seeds 11,23,37,42,57)", file=sys.stderr)
        return 1

    out_dir = Path(args.out)

    # Key check: wire a provider only if either arm is LLM-backed.
    needs_llm = any(a in _LLM_ARMS for a in (control, treatment))
    provider: Any = None
    if needs_llm:
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        if not api_key:
            print(_KEY_HINT)
            return 2
        from aftershock.llm.provider import QwenProvider
        provider = QwenProvider(api_key=api_key)

    result = run_ablation(
        control, treatment, seeds, args.ticks, provider, out_dir,
        ablate=ablate,
        society_tools=getattr(args, "society_tools", False),
        seed_sampler=getattr(args, "seed_sampler", False),
        pool_sizes=_parse_pools(getattr(args, "pools", None)),
        power_target=args.power, alpha=args.alpha,
    )
    md = render_ablation_markdown(result)
    print(md)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ablation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "ABLATION.md").write_text(md, encoding="utf-8")
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    """Free diagnostics over completed runs: auction losses, latency, calibration (M5)."""
    from aftershock.town.diagnostics import (
        conformance_calibration,
        diagnose_run,
        render_calibration_markdown,
        render_diagnostics_markdown,
    )

    run_dirs = [Path(d) for d in args.run_dirs]
    for rd in run_dirs:
        if not rd.exists():
            print(f"error: run directory not found: {rd}", file=sys.stderr)
            return 1

    reports = {str(rd): diagnose_run(rd) for rd in run_dirs}
    calibration = conformance_calibration(run_dirs)

    if getattr(args, "json", False):
        print(json.dumps(
            {"runs": reports, "calibration": calibration}, indent=2, sort_keys=True
        ))
        return 0

    for rd in run_dirs:
        print(render_diagnostics_markdown(reports[str(rd)]))
    print(render_calibration_markdown(calibration))
    return 0


def cmd_episodes(args: argparse.Namespace) -> int:
    """Run N sequential society runs with AAR+memory between them.

    Episode 1 runs memoryless; each subsequent episode loads lessons from the
    previous run. Writes per-episode run dirs + episodes.json + a markdown table.
    """
    n: int = args.n
    seed_base: int = args.seed_base
    ticks: int = args.ticks
    out_dir = Path(args.out)

    # Require a provider for society runs
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print(_KEY_HINT)
        return 2

    from aftershock.llm.aar import append_lessons, generate_aar, load_lessons
    from aftershock.llm.provider import QwenProvider

    provider = QwenProvider(api_key=api_key)
    out_dir.mkdir(parents=True, exist_ok=True)
    memory_path = out_dir / "memory.json"

    episode_results: list[dict[str, Any]] = []

    for ep in range(n):
        seed = seed_base + ep
        lessons: list[str] | None = None
        if ep > 0:
            loaded = load_lessons(memory_path)
            lessons = loaded if loaded else None

        run_id = f"ep{ep + 1}-seed{seed}-society"
        setup = build_arm("society", seed, provider, lessons=lessons)

        manifest: dict[str, Any] = {
            "run_id": run_id,
            "seed": seed,
            "ticks": ticks,
            "arm": "society",
            "episode": ep + 1,
        }
        recorder = Recorder(out_dir, run_id, manifest)
        engine = Engine(
            world=setup.world,
            society=setup.society,
            agents=setup.agents,
            registry=setup.registry,
            roles=setup.roles,
            resolver=setup.resolver,
            recorder=recorder,
            seed=seed,
            max_ticks=ticks,
            agent_timeout_s=45.0,
        )

        summary = asyncio.run(engine.run())
        run_dir = Path(summary.run_dir)

        # Generate AAR and append lessons after every episode
        aar = asyncio.run(generate_aar(run_dir, provider))
        append_lessons(memory_path, run_id, aar.get("lessons", []))

        s = summary.final_scores
        episode_results.append({
            "episode": ep + 1,
            "seed": seed,
            "run_id": run_id,
            "lives_saved": s.get("lives_saved", 0),
            "lives_lost": s.get("lives_lost", 0),
            "missions_resolved": s.get("missions_resolved", 0),
            "missions_failed": s.get("missions_failed", 0),
            "cost_usd": summary.cost.get("cost_usd", 0.0),
            "aar_grade": aar.get("grade", "?"),
        })

        print(
            f"Episode {ep + 1}/{n}  seed={seed}  "
            f"lives_saved={int(s.get('lives_saved', 0))}  "
            f"grade={aar.get('grade', '?')}"
        )

    # Write episodes.json
    episodes_json_path = out_dir / "episodes.json"
    episodes_json_path.write_text(
        json.dumps(episode_results, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    # Write markdown trajectory table
    md_lines = [
        "# Episodes Trajectory",
        "",
        "| Episode | Seed | Lives Saved | Lives Lost | Missions Res | Missions Fail"
        " | Cost USD | AAR Grade |",
        "|---------|------|-------------|------------|--------------|--------------|"
        "----------|-----------|",
    ]
    for ep_r in episode_results:
        md_lines.append(
            f"| {ep_r['episode']} | {ep_r['seed']} | {int(ep_r['lives_saved'])} |"
            f" {int(ep_r['lives_lost'])} | {int(ep_r['missions_resolved'])} |"
            f" {int(ep_r['missions_failed'])} | {ep_r['cost_usd']:.4f} | {ep_r['aar_grade']} |"
        )
    md_text = "\n".join(md_lines) + "\n"

    episodes_md_path = out_dir / "episodes.md"
    episodes_md_path.write_text(md_text, encoding="utf-8")

    print(md_text)
    print(f"Written: {episodes_json_path}  {episodes_md_path}")
    return 0


def cmd_compile_scenario(args: argparse.Namespace) -> int:
    """OFFLINE compiler: real open incident dataset -> committed scenario.json.

    Runs Extract (live fetch, unless --no-fetch uses the cached raw/) ->
    Aggregate -> Discretize -> Emit. Writes scenarios/<id>/scenario.json (sorted
    keys) + README.md + raw/ cache. The engine never imports this path.
    """
    from aftershock.data import compile_scenario

    adapter: str = args.adapter
    config_path = Path(args.config)
    out_dir = Path(args.out)
    do_fetch: bool = not args.no_fetch

    if not config_path.is_file():
        print(f"error: config not found: {config_path}", file=sys.stderr)
        return 1

    try:
        result = compile_scenario(
            adapter_name=adapter,
            config_path=config_path,
            out_dir=out_dir,
            fetch=do_fetch,
            compiler_version_override=args.compiler_version,
        )
    except Exception as exc:  # noqa: BLE001 — surface a friendly one-liner
        print(f"error: compile failed: {exc}", file=sys.stderr)
        return 1

    # Re-load the emitted pack through the engine-side loader to prove validity.
    from aftershock.town.scenario import last_timeline_tick, load_scenario

    pack = load_scenario(out_dir / "scenario.json")
    fm = result.fetch_manifest
    n_missions = sum(1 for e in pack.timeline if e.kind == "mission")
    print(f"Compiled scenario {pack.id!r}")
    print(f"  adapter:        {pack.adapter}")
    print(f"  window:         {pack.window.start} -> {pack.window.end}")
    print(f"  fetched:        {fm.get('rows_fetched')} unit rows ({fm.get('fetched_at')})")
    print(f"  sampling:       {pack.sampling.kept} of {pack.sampling.total} incidents "
          f"(seed {pack.sampling.sample_seed})")
    print(f"  missions:       {n_missions}  ·  last tick {last_timeline_tick(pack)}")
    print(f"  config_sha256:  {pack.config_sha256[:16]}…")
    print(f"  pack_digest:    {pack.pack_digest[:16]}…")
    print(f"  written:        {out_dir / 'scenario.json'}")
    print(f"                  {out_dir / 'README.md'}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="aftershock")
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="Run a simulation")
    p_run.add_argument(
        "--seed", type=int, default=None,
        help=(
            "Engine seed. Required for synthetic runs; with --scenario it "
            "defaults to a fixed seed (the pack drives the timeline; seed still "
            "governs every other rng_for stream and replay)."
        ),
    )
    p_run.add_argument(
        "--ticks", type=int, default=None,
        help=(
            "Tick budget. Required for synthetic runs; with --scenario it defaults "
            "to min(last timeline tick + 20, 120). An explicit under-budget value "
            "with --scenario is a hard error."
        ),
    )
    p_run.add_argument(
        "--scenario", default=None,
        help="Run a real-data scenario pack (resolves scenarios/<id>/scenario.json)",
    )
    p_run.add_argument("--arm", default="scripted", choices=list(ARMS))
    p_run.add_argument("--out", default="runs")
    p_run.add_argument("--quiet", action="store_true")
    p_run.add_argument("--timeout", type=float, default=None,
                       help="Agent timeout in seconds (default: arm-specific default)")
    p_run.add_argument(
        "--memory",
        action="store_true",
        help=(
            "Load lessons from <out>/memory.json before the run (society arm only) "
            "and generate AAR + append lessons afterwards."
        ),
    )
    p_run.add_argument(
        "--society-tools",
        action="store_true",
        help=(
            "Society arm only: use native Qwen function calling (tools/tool_choice) "
            "instead of JSON-mode prompting. Opt-in; default is JSON mode (the "
            "cost-optimal path the published benchmark uses)."
        ),
    )
    p_run.add_argument(
        "--seed-sampler",
        action="store_true",
        help=(
            "M1 opt-in: send a deterministic per-tick provider seed (derived from "
            "the engine seed) on every LLM call, to test whether DashScope makes "
            "sampling reproducible. No effect on the scripted arm."
        ),
    )
    p_run.add_argument(
        "--pools", default=None,
        help=(
            "D2: harden the synthetic world. A preset ('tight', 'scarce') or an "
            "override like 'ambulance=3,rescue_crew=2'. Ignored with --scenario."
        ),
    )
    p_run.add_argument(
        "--role-model", default=None,
        help=(
            "Operating-mode per-role model override 'role=model,...' (LLM arms only). "
            "E.g. 'infrastructure=qwen3.5-plus' (§20 high-conformance mode). "
            "Default keeps the cost-optimal YAML mix."
        ),
    )

    # counterfactual
    p_cf = sub.add_parser(
        "counterfactual",
        help="Re-run a seed with one intervention at tick N (branch + compare)",
    )
    p_cf.add_argument("--seed", type=int, required=True, help="Engine seed (matches the baseline)")
    p_cf.add_argument("--ticks", type=int, required=True, help="Tick budget")
    p_cf.add_argument("--arm", default="scripted", choices=list(ARMS))
    p_cf.add_argument("--at", type=int, required=True, help="Intervention tick N")
    p_cf.add_argument(
        "--kind",
        required=True,
        choices=["drop_protocol", "kill_agent", "inject_event", "none"],
        help="Intervention kind",
    )
    p_cf.add_argument(
        "--target", default="",
        help="agent_id (kill_agent) or district_id (inject_event)",
    )
    p_cf.add_argument(
        "--event", default="fire", choices=["fire", "aftershock", "road_block"],
        help="Event kind for inject_event (default: fire)",
    )
    p_cf.add_argument("--out", default="runs")
    p_cf.add_argument("--quiet", action="store_true")

    # bench
    p_bench = sub.add_parser("bench", help="Run the benchmark suite")
    p_bench.add_argument("--manifest", default=None,
                         help="Path to manifest YAML (default: bench/default.yaml)")
    p_bench.add_argument("--arms", default=None,
                         help="Comma-separated arm list to override manifest")
    p_bench.add_argument("--seeds", default=None,
                         help="Comma-separated seed list to override manifest")
    p_bench.add_argument("--ticks", type=int, default=None,
                         help="Tick count override")
    p_bench.add_argument("--out", default=None,
                         help="Output directory override")
    p_bench.add_argument("--fresh", action="store_true",
                         help="Wipe cell dirs before running (force re-run)")
    p_bench.add_argument(
        "--society-tools",
        action="store_true",
        help=(
            "Run the society arm with native Qwen function calling (tools) instead "
            "of JSON-mode prompting. Opt-in ablation; default JSON. Write to a "
            "distinct --out so it never overwrites the JSON-mode benchmark."
        ),
    )
    p_bench.add_argument(
        "--scenario", default=None,
        help="REJECTED — bench refuses scenario packs (invariant 3)",
    )
    p_bench.add_argument(
        "--seed-sampler", action="store_true",
        help="M1 opt-in: send a deterministic per-tick provider seed on LLM calls.",
    )
    p_bench.add_argument(
        "--repeat-seeds", type=int, default=1,
        help=(
            "M2: run each (arm, seed) cell this many times into ...-r{k} dirs and "
            "report a within-seed (LLM) vs between-seed (world) variance split "
            "instead of the headline table. Default 1 (off)."
        ),
    )
    p_bench.add_argument(
        "--pools", default=None,
        help=(
            "D2: harden the synthetic world for every cell. A preset ('tight', "
            "'scarce') or 'ambulance=3,rescue_crew=2'. Write to a distinct --out so "
            "it never overwrites the default-world benchmark."
        ),
    )
    p_bench.add_argument(
        "--role-model", default=None,
        help=(
            "Operating-mode per-role model override 'role=model,...' (LLM arms only). "
            "E.g. 'infrastructure=qwen3.5-plus' (§20). Write to a distinct --out so it "
            "never overwrites the cost-optimal default benchmark."
        ),
    )

    # ablation
    p_ablation = sub.add_parser(
        "ablation",
        help="Paired control-vs-treatment ablation (sign test + CI + power curve)",
    )
    p_ablation.add_argument("--control", required=True, choices=list(ARMS),
                            help="Baseline arm (for --ablate, the arm to test, == --treatment)")
    p_ablation.add_argument("--treatment", required=True, choices=list(ARMS),
                            help="Arm under test")
    p_ablation.add_argument("--ablate", default=None, choices=["doctrine"],
                            help="Same-arm knob ablation: 'doctrine' flips doctrine "
                                 "off (control) vs on (treatment); requires control==treatment")
    p_ablation.add_argument("--seeds", required=True,
                            help="Comma-separated seeds shared by both arms (e.g. 11,23,37)")
    p_ablation.add_argument("--ticks", type=int, default=60, help="Tick budget (default 60)")
    p_ablation.add_argument("--out", default="runs/ablation", help="Output directory")
    p_ablation.add_argument("--society-tools", action="store_true",
                            help="Run society cells with native function calling")
    p_ablation.add_argument("--seed-sampler", action="store_true",
                            help="M1 opt-in: deterministic per-tick provider seed")
    p_ablation.add_argument("--pools", default=None,
                            help="D2: harden the world ('tight'/'scarce' or 'ambulance=3,...')")
    p_ablation.add_argument("--power", type=float, default=0.8,
                            help="Target power for the seeds-needed curve (default 0.8)")
    p_ablation.add_argument("--alpha", type=float, default=0.05,
                            help="Significance level (default 0.05)")

    # diagnose
    p_diagnose = sub.add_parser(
        "diagnose",
        help="Free diagnostics over completed runs (auction losses, latency, calibration)",
    )
    p_diagnose.add_argument("run_dirs", nargs="+", help="One or more run directories")
    p_diagnose.add_argument("--json", action="store_true",
                            help="Output raw JSON instead of markdown")

    # verify
    p_verify = sub.add_parser("verify", help="Verify determinism")
    p_verify.add_argument(
        "--seed", type=int, default=None,
        help=(
            "Engine seed. Required for synthetic verification; with --scenario "
            "it defaults to a fixed seed (the pack drives the timeline, and a "
            "scenario digest must be byte-identical for the same pack + seed)."
        ),
    )
    p_verify.add_argument(
        "--ticks", type=int, default=None,
        help=(
            "Tick budget. Required for synthetic runs; with --scenario it defaults "
            "to min(last timeline tick + 20, 120). An explicit under-budget value "
            "with --scenario is a hard error."
        ),
    )
    p_verify.add_argument(
        "--scenario", default=None,
        help="Verify a real-data scenario pack (two-run digest check)",
    )

    # replay
    p_replay = sub.add_parser("replay", help="Print scoreboard from a run dir")
    p_replay.add_argument("run_dir")

    # smoke-llm
    p_smoke = sub.add_parser("smoke-llm", help="Make one test LLM call and print results")
    p_smoke.add_argument("--model", default="qwen3.5-flash")

    # serve
    p_serve = sub.add_parser(
        "serve",
        help="Start the FastAPI observatory server",
    )
    p_serve.add_argument(
        "--runs-dir",
        default="runs",
        help="Directory containing run directories (default: runs)",
    )
    p_serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    p_serve.add_argument(
        "--port",
        type=int,
        default=8788,
        help="Port to listen on (default: 8788)",
    )

    # mcp
    p_mcp = sub.add_parser(
        "mcp",
        help="Start the MCP spectator server (stdio transport)",
    )
    p_mcp.add_argument(
        "--runs-dir",
        default="runs",
        help="Directory containing run directories (default: runs)",
    )

    # aar
    p_aar = sub.add_parser(
        "aar",
        help="Generate (or display) an after-action report for a completed run",
    )
    p_aar.add_argument("run_dir", help="Path to the run directory")
    p_aar.add_argument(
        "--show",
        action="store_true",
        help="Display an existing aar.json without regenerating (no API key required)",
    )

    # conformance
    p_conformance = sub.add_parser(
        "conformance",
        help="Check a completed run against all 18 doctrine rules",
    )
    p_conformance.add_argument("run_dir", help="Path to the run directory")
    p_conformance.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of markdown",
    )

    # episodes
    p_episodes = sub.add_parser(
        "episodes",
        help="Run N sequential society runs with AAR+memory between runs",
    )
    p_episodes.add_argument("--n", type=int, required=True, help="Number of episodes")
    p_episodes.add_argument(
        "--seed-base", type=int, required=True,
        help="Starting seed; episode k uses seed base+k-1",
    )
    p_episodes.add_argument(
        "--ticks", type=int, default=60,
        help="Ticks per episode (default: 60)",
    )
    p_episodes.add_argument(
        "--out", default="runs/episodes",
        help="Output directory for episode run dirs and summary files (default: runs/episodes)",
    )

    # compile-scenario (OFFLINE compiler — appended subcommand, S2)
    p_compile = sub.add_parser(
        "compile-scenario",
        help="OFFLINE: compile a real open dataset into scenarios/<id>/scenario.json",
    )
    p_compile.add_argument(
        "--adapter", required=True,
        help="Compiler adapter id (e.g. sf)",
    )
    p_compile.add_argument(
        "--config", required=True,
        help="Path to the adapter config YAML (its sha256 is stamped into the pack)",
    )
    p_compile.add_argument(
        "--out", required=True,
        help="Output directory for the pack (e.g. scenarios/sf-routine-2018)",
    )
    p_compile.add_argument(
        "--no-fetch", action="store_true",
        help="Skip the live fetch; recompile from the cached raw/ (offline, deterministic)",
    )
    p_compile.add_argument(
        "--compiler-version", default=None,
        help="Override the compiler_version field (default: git short rev at emit time)",
    )

    args = parser.parse_args()

    if args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "counterfactual":
        sys.exit(cmd_counterfactual(args))
    elif args.command == "bench":
        sys.exit(cmd_bench(args))
    elif args.command == "verify":
        sys.exit(cmd_verify(args))
    elif args.command == "replay":
        sys.exit(cmd_replay(args))
    elif args.command == "smoke-llm":
        sys.exit(cmd_smoke_llm(args))
    elif args.command == "serve":
        sys.exit(cmd_serve(args))
    elif args.command == "mcp":
        sys.exit(cmd_mcp(args))
    elif args.command == "aar":
        sys.exit(cmd_aar(args))
    elif args.command == "episodes":
        sys.exit(cmd_episodes(args))
    elif args.command == "conformance":
        sys.exit(cmd_conformance(args))
    elif args.command == "ablation":
        sys.exit(cmd_ablation(args))
    elif args.command == "diagnose":
        sys.exit(cmd_diagnose(args))
    elif args.command == "compile-scenario":
        sys.exit(cmd_compile_scenario(args))
