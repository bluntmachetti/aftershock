"""Aftershock CLI: run | verify | replay | bench | smoke-llm.

aftershock run    --seed 42 --ticks 60 --arm scripted|solo|swarm|society [--out runs]
                  [--quiet] [--timeout S]
aftershock bench  [--manifest bench/default.yaml] [--arms a,b] [--seeds 1,2] [--ticks N]
                  [--out DIR] [--fresh]
aftershock verify --seed 42 --ticks 60
aftershock replay <run_dir>
aftershock smoke-llm [--model qwen3.5-flash]
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


def _run_id(seed: int, arm: str) -> str:
    return f"seed{seed}-{arm}"


def cmd_run(args: argparse.Namespace) -> int:
    seed: int = args.seed
    ticks: int = args.ticks
    arm: str = args.arm
    out_dir = Path(args.out)
    quiet: bool = args.quiet

    # Determine default timeout based on arm
    _ARM_DEFAULT_TIMEOUT = {"scripted": 5.0, "solo": 90.0, "swarm": 45.0, "society": 45.0}
    timeout_s: float = (
        args.timeout if args.timeout is not None else _ARM_DEFAULT_TIMEOUT.get(arm, 30.0)
    )

    # Key check before any work (exits 2 with hint if key missing for LLM arms)
    provider = _provider_for_arm(arm, timeout_s)

    run_id = _run_id(seed, arm)
    setup = build_arm(arm, seed, provider)

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "seed": seed,
        "ticks": ticks,
        "arm": arm,
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

    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    """Run the benchmark suite from a manifest with optional flag overrides."""
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

    # --fresh: wipe each cell directory before running
    if args.fresh:
        for arm in requested_arms:
            for seed in manifest.get("seeds", []):
                cell_dir = out_dir / f"{arm}-seed{seed}"
                if cell_dir.exists():
                    shutil.rmtree(cell_dir)

    cells = run_bench(manifest, provider=provider, out_dir=out_dir)
    agg = aggregate(cells)
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
    seed: int = args.seed
    ticks: int = args.ticks

    async def _run_into(tmp: Path, tag: str) -> list[str]:
        run_id = f"verify-{tag}"
        setup = build_arm("scripted", seed, None)
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
        _, records = load_run(tmp / run_id)
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

    manifest, records = load_run(run_dir)
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="aftershock")
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="Run a simulation")
    p_run.add_argument("--seed", type=int, required=True)
    p_run.add_argument("--ticks", type=int, required=True)
    p_run.add_argument("--arm", default="scripted", choices=list(ARMS))
    p_run.add_argument("--out", default="runs")
    p_run.add_argument("--quiet", action="store_true")
    p_run.add_argument("--timeout", type=float, default=None,
                       help="Agent timeout in seconds (default: arm-specific default)")

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

    # verify
    p_verify = sub.add_parser("verify", help="Verify determinism")
    p_verify.add_argument("--seed", type=int, required=True)
    p_verify.add_argument("--ticks", type=int, required=True)

    # replay
    p_replay = sub.add_parser("replay", help="Print scoreboard from a run dir")
    p_replay.add_argument("run_dir")

    # smoke-llm
    p_smoke = sub.add_parser("smoke-llm", help="Make one test LLM call and print results")
    p_smoke.add_argument("--model", default="qwen3.5-flash")

    args = parser.parse_args()

    if args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "bench":
        sys.exit(cmd_bench(args))
    elif args.command == "verify":
        sys.exit(cmd_verify(args))
    elif args.command == "replay":
        sys.exit(cmd_replay(args))
    elif args.command == "smoke-llm":
        sys.exit(cmd_smoke_llm(args))
