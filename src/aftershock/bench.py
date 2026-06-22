"""Benchmark harness: run_bench / aggregate / render_markdown.

Runs each (arm, seed) cell sequentially via town.arms.build_arm + kernel Engine.
Resume: a cell whose <out>/<arm>-seed<seed>/summary.json exists is skipped.
Per-cell run dir holds ticks.ndjson + run.json (via Recorder) + summary.json.

Wall-clock timing uses time.monotonic() ONLY for the wall_s measurement field.
It never feeds simulation state, preserving Invariant 1 (determinism).
"""

from __future__ import annotations

import asyncio
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

from aftershock import stats
from aftershock.kernel.engine import Engine
from aftershock.kernel.recorder import Recorder
from aftershock.town.arms import build_arm

# Provenance stamp schema; bump when the stamp's field set changes.
PROVENANCE_SCHEMA_VERSION = 1


def _git_sha() -> str:
    """``git rev-parse HEAD`` at write time; "unknown" outside a git checkout.

    Read-only metadata captured at WRITE time only — never fed into the tick loop,
    so Invariant 1 (determinism) is preserved.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if out.returncode != 0:
        return "unknown"
    return out.stdout.strip() or "unknown"


def _git_dirty() -> bool:
    """True when ``git status --porcelain`` is non-empty at write time.

    Non-git or a git failure conservatively reports False (no dirtiness claimable).
    Metadata only; never feeds the simulation path.
    """
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if out.returncode != 0:
        return False
    return bool(out.stdout.strip())


def _scripted_verify_digest(cells: list[dict[str, Any]]) -> str | None:
    """The scripted cell's FINAL-TICK world_digest, reused from this bench run.

    Pulls the digest captured during the scripted cell's run (no second ``verify``
    invocation). When more than one scripted cell is present (multiple seeds), the
    lowest-seed scripted cell that carries a digest is used, for a stable choice.
    Returns None when there is no scripted arm, or none carried a digest (e.g. the
    pure-function call paths used in tests).
    """
    scripted = sorted(
        (c for c in cells if c.get("arm") == "scripted" and c.get("world_digest")),
        key=lambda c: (c.get("seed", 0)),
    )
    if not scripted:
        return None
    digest = scripted[0].get("world_digest")
    return str(digest) if digest else None


def _provenance_stamp(
    cells: list[dict[str, Any]] | None = None,
    *,
    model_endpoint: str | None = None,
) -> dict[str, Any]:
    """One stamp dict added to every bench result JSON (the thin provenance layer).

    Fields: schema_version, git_sha, dirty, model_endpoint, scripted_verify_digest.
    git_sha/dirty are read via subprocess at WRITE time only (metadata, never fed to
    the tick loop). ``model_endpoint`` is the caller-detected provider endpoint
    ("dashscope-intl"/"ollama-k12"/"scripted"); when omitted it is inferred from the
    cells (an arm with positive LLM cost -> cloud guess "dashscope-intl", else
    "scripted"). scripted_verify_digest reuses the scripted cell's final-tick digest.
    """
    cells = cells or []
    if model_endpoint is None:
        model_endpoint = _infer_endpoint_from_cells(cells)
    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "git_sha": _git_sha(),
        "dirty": _git_dirty(),
        "model_endpoint": model_endpoint,
        "scripted_verify_digest": _scripted_verify_digest(cells),
    }


def _endpoint_from_provider(provider: Any | None) -> str:
    """Provenance endpoint label for a live provider (None -> "scripted").

    Reuses ``llm.provider.endpoint_label`` against the provider's ``base_url`` so the
    bench mirrors the provider's own DashScope-vs-local detection. A provider without
    a ``base_url`` attribute (e.g. a MockProvider in tests) is treated as cloud-less
    and labeled "scripted", which is honest for an offline run.
    """
    if provider is None:
        return "scripted"
    base_url = getattr(provider, "base_url", None)
    if base_url is None:
        return "scripted"
    from aftershock.llm.provider import endpoint_label

    return endpoint_label(base_url)


def _infer_endpoint_from_cells(cells: list[dict[str, Any]]) -> str:
    """Best-effort endpoint when the caller did not pass one (no provider in scope).

    If any cell logged a positive LLM cost there was a live provider; default to the
    cloud label "dashscope-intl" (the published path). With no LLM cost anywhere the
    run was LLM-free -> "scripted". The CLI always passes an explicit endpoint, so
    this only matters for pure-function/test call paths.
    """
    for c in cells:
        cost = c.get("cost") or {}
        if float(cost.get("cost_usd", 0.0) or 0.0) > 0.0:
            return "dashscope-intl"
    return "scripted"


def _cell_dir(out_dir: Path, arm: str, seed: int) -> Path:
    """Canonical per-cell directory name."""
    return out_dir / f"{arm}-seed{seed}"


def _execute_cell(
    out_dir: Path,
    arm: str,
    seed: int,
    ticks: int,
    provider: Any | None,
    run_id: str,
    *,
    society_tools: bool = False,
    seed_sampler: bool = False,
    pool_sizes: dict[str, int] | None = None,
    doctrine: bool = True,
    role_models: dict[str, str] | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build + run one (arm, seed) cell and write its summary.json.

    Shared by run_bench and run_repeat_seeds. ``run_id`` is the cell directory
    name (``{arm}-seed{seed}`` for bench, ``...-r{k}`` for repeats). Conformance
    failure is logged but never blocks summary.json from being written.

    ``doctrine`` (default True) is forwarded to build_arm; the doctrine on/off
    ablation passes False to build the doctrine-naive control (FIELD-NOTES §11).
    ``role_models`` (default None) forwards the --role-model operating-mode override.
    """
    setup = build_arm(
        arm, seed, provider, society_tools=society_tools, seed_sampler=seed_sampler,
        pool_sizes=pool_sizes, doctrine=doctrine, role_models=role_models,
    )
    manifest_rec: dict[str, Any] = {
        "arm": arm,
        "seed": seed,
        "ticks": ticks,
        "run_id": run_id,
    }
    recorder = Recorder(out_dir, run_id, manifest_rec)

    # Capture the final-tick world_digest as it is recorded, so the provenance stamp
    # can reuse the scripted cell's digest WITHOUT a second `verify` run. The listener
    # only reads the record (adds no state to the sim), so determinism is preserved.
    digest_holder: dict[str, str] = {}

    def _capture_digest(record: Any, _world: dict[str, Any]) -> None:
        digest_holder["world_digest"] = record.world_digest

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
        tick_listener=_capture_digest,
    )

    # time.monotonic() is used ONLY for wall_s — it never feeds simulation state,
    # so Invariant 1 (determinism) is preserved.
    t0 = time.monotonic()
    summary_run = asyncio.run(engine.run())
    wall_s = time.monotonic() - t0

    models: list[str] = sorted(summary_run.cost.get("by_model", {}).keys())

    cell_summary: dict[str, Any] = {
        "arm": arm,
        "seed": seed,
        "ticks_requested": ticks,
        "ticks_run": summary_run.ticks_run,
        "scores": summary_run.final_scores,
        "cost": summary_run.cost,
        "wall_s": wall_s,
        "models": models,
        # Final-tick world digest (last recorded tick). Reused by the provenance
        # stamp's scripted_verify_digest — never a second verify invocation.
        "world_digest": digest_holder.get("world_digest"),
    }
    if extra_fields:
        cell_summary.update(extra_fields)

    cell_dir = out_dir / run_id
    # Conformance metrics: attach team_alignment / role_conformance. Failure must
    # never prevent summary.json from being written.
    try:
        from aftershock.town.conformance import check_run as _check_run

        conf = _check_run(cell_dir)
        cell_summary["team_alignment"] = conf.get("team_alignment")
        cell_summary["role_conformance"] = conf.get("role_conformance")
    except Exception as exc:  # noqa: BLE001
        import sys

        print(
            f"warning: conformance check failed for {cell_dir.name}: {exc!r}",
            file=sys.stderr,
        )

    (cell_dir / "summary.json").write_text(
        json.dumps(cell_summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return cell_summary


def _run_or_resume_cell(
    out_dir: Path,
    arm: str,
    seed: int,
    ticks: int,
    provider: Any | None,
    run_id: str,
    *,
    society_tools: bool = False,
    seed_sampler: bool = False,
    pool_sizes: dict[str, int] | None = None,
    doctrine: bool = True,
    role_models: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resume a completed cell from disk, or execute it. ``run_id`` is the cell dir.

    Resume reuses <out_dir>/<run_id>/summary.json only when present AND its
    ticks_requested matches ``ticks``; a missing, corrupt, or tick-mismatched
    summary forces a re-run (so cells from different tick budgets never mix). This
    is the shared resume kernel for run_bench and the doctrine on/off ablation.
    """
    summary_path = out_dir / run_id / "summary.json"
    if summary_path.exists():
        try:
            with summary_path.open(encoding="utf-8") as fh:
                cached = json.load(fh)
        except (json.JSONDecodeError, OSError):
            print(
                f"warning: corrupt summary at {summary_path}; re-running cell",
                flush=True,
            )
            cached = None
        if cached is not None:
            if cached.get("ticks_requested") == ticks:
                return cached
            print(
                f"warning: ticks mismatch for {run_id} "
                f"(cached={cached.get('ticks_requested')}, requested={ticks}); "
                "re-running cell",
                flush=True,
            )
    return _execute_cell(
        out_dir, arm, seed, ticks, provider, run_id=run_id,
        society_tools=society_tools, seed_sampler=seed_sampler,
        pool_sizes=pool_sizes, doctrine=doctrine, role_models=role_models,
    )


def run_bench(
    manifest: dict[str, Any],
    provider: Any | None,
    out_dir: Path,
    society_tools: bool = False,
    seed_sampler: bool = False,
    pool_sizes: dict[str, int] | None = None,
    role_models: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Run all (arm, seed) cells from *manifest*, writing results under *out_dir*.

    Returns a list of per-cell summary dicts (including skipped cells loaded
    from existing summary.json files).

    Resume: if <out_dir>/<arm>-seed<seed>/summary.json already exists the cell
    is skipped (delete the directory to force a re-run).
    """
    ticks: int = manifest["ticks"]
    seeds: list[int] = manifest["seeds"]
    arms: list[str] = manifest["arms"]
    out_dir.mkdir(parents=True, exist_ok=True)

    cells: list[dict[str, Any]] = []

    for arm in arms:
        for seed in seeds:
            # Resume-or-run via the shared kernel (skips completed, tick-matched
            # cells; re-runs missing/corrupt/tick-mismatched ones).
            cell_summary = _run_or_resume_cell(
                out_dir,
                arm,
                seed,
                ticks,
                provider,
                run_id=f"{arm}-seed{seed}",
                society_tools=society_tools,
                seed_sampler=seed_sampler,
                pool_sizes=pool_sizes,
                role_models=role_models,
            )
            cells.append(cell_summary)

    return cells


def aggregate(
    cells: list[dict[str, Any]], *, model_endpoint: str | None = None
) -> dict[str, Any]:
    """Compute per-arm statistics from a list of per-cell summary dicts.

    Per arm computes n, mean, and sample standard deviation (ddof=1) for:
      lives_saved, lives_lost, missions_resolved, missions_failed,
      cost_usd, wall_s

    lives_per_dollar = mean_lives_saved / mean_cost_usd is included only for
    arms whose mean_cost_usd > 0 (zero-cost arms like 'scripted' are omitted).

    Also produces the per-seed paired table: arm x seed -> lives_saved.

    The result carries a ``provenance`` stamp (schema_version, git_sha, dirty,
    model_endpoint, scripted_verify_digest) — the latter reused from the scripted
    cell's final-tick digest in ``cells`` (no second verify run). ``model_endpoint``
    is supplied by the CLI (it knows the provider); when omitted it is inferred.
    """
    # Group cells by arm — validate required keys up front
    by_arm: dict[str, list[dict[str, Any]]] = {}
    for i, cell in enumerate(cells):
        if "arm" not in cell:
            raise KeyError(
                f"cell[{i}] is missing required key 'arm'; "
                "delete the corrupt summary to re-run the cell"
            )
        if "seed" not in cell:
            raise KeyError(
                f"cell[{i}] (arm={cell['arm']!r}) is missing required key 'seed'; "
                "delete the corrupt summary to re-run the cell"
            )
        arm = cell["arm"]
        by_arm.setdefault(arm, [])
        by_arm[arm].append(cell)

    def _mean(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    def _sample_sd(vals: list[float]) -> float:
        n = len(vals)
        if n < 2:
            return 0.0
        m = _mean(vals)
        return math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))

    def _extract(cells: list[dict[str, Any]], key: str) -> list[float]:
        results = []
        for c in cells:
            scores = c.get("scores", {})
            if key in scores:
                results.append(float(scores[key]))
            elif key == "cost_usd":
                results.append(float(c.get("cost", {}).get("cost_usd", 0.0)))
            elif key == "wall_s":
                results.append(float(c.get("wall_s", 0.0)))
            else:
                raise KeyError(
                    f"metric key {key!r} absent from cell scores "
                    f"(arm={c.get('arm')!r}, seed={c.get('seed')}); "
                    "delete the cell dir to re-run it"
                )
        return results

    arm_stats: dict[str, dict[str, Any]] = {}
    for arm, arm_cells in sorted(by_arm.items()):
        n = len(arm_cells)

        metrics = ["lives_saved", "lives_lost", "missions_resolved", "missions_failed"]
        stat: dict[str, Any] = {"n": n}
        for m in metrics:
            vals = _extract(arm_cells, m)
            stat[f"mean_{m}"] = _mean(vals)
            stat[f"sd_{m}"] = _sample_sd(vals)

        cost_vals = _extract(arm_cells, "cost_usd")
        stat["mean_cost_usd"] = _mean(cost_vals)
        stat["sd_cost_usd"] = _sample_sd(cost_vals)

        wall_vals = _extract(arm_cells, "wall_s")
        stat["mean_wall_s"] = _mean(wall_vals)
        stat["sd_wall_s"] = _sample_sd(wall_vals)

        # lives_per_dollar: only for arms with mean cost > 0
        if stat["mean_cost_usd"] > 0:
            stat["lives_per_dollar"] = stat["mean_lives_saved"] / stat["mean_cost_usd"]

        # team_alignment: mean across cells that have the key; null when none do
        ta_vals = [
            float(c["team_alignment"])
            for c in arm_cells
            if c.get("team_alignment") is not None
        ]
        stat["mean_team_alignment"] = _mean(ta_vals) if ta_vals else None

        arm_stats[arm] = stat

    # Per-seed paired lives_saved table: {arm: {seed: lives_saved}}
    paired: dict[str, dict[int, float]] = {}
    for cell in cells:
        arm = cell["arm"]
        seed = cell["seed"]
        paired.setdefault(arm, {})
        paired[arm][seed] = float(cell.get("scores", {}).get("lives_saved", 0.0))

    return {
        "arms": arm_stats,
        "paired": paired,
        "provenance": _provenance_stamp(cells, model_endpoint=model_endpoint),
    }


# Fixed bootstrap seed so the served CI is byte-stable across re-serves of the
# same results.json (deterministic presentation, not a re-roll per request).
_PAIRED_BOOTSTRAP_SEED = 20260619


def paired_comparisons(
    paired: dict[str, dict[int, float]],
    control: str = "scripted",
    *,
    alpha: float = 0.05,
    provenance: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Pure paired control-vs-treatment stats from the ``paired`` table.

    For each non-control arm sharing seeds with ``control``, computes the
    per-seed lives_saved delta and reports: mean_delta, a bootstrap CI, an exact
    two-sided sign-test p-value, observed power, and a structured verdict.

    This is the small pure adapter the BenchTab serves — it does NOT reuse
    ``analyze_ablation`` (which is hard-coded control-vs-treatment and raises on
    no common seeds). Graceful: an arm with no common seeds is omitted (not an
    error), so a single-arm results.json yields an empty list rather than 500.

    Verdict mirrors ``analyze_ablation`` (FIELD-NOTES §16–17): "credible"
    requires the bootstrap CI to exclude 0 AND the sign test to be significant;
    CI-excludes-0 but sign test not significant = "suggestive"; otherwise
    "noise". This stops the percentile CI from over-claiming on small skewed
    samples.

    ``provenance`` (when given) is attached to every emitted verdict row, so a
    served paired-stat row carries the same stamp as its parent results.json. The
    web layer passes the on-disk results.json's ``provenance`` block through; tests
    that call this directly leave it None and the rows simply omit the field.
    """
    ctrl = paired.get(control, {})
    if not ctrl:
        return []
    out: list[dict[str, Any]] = []
    # society first, then the rest alphabetically (matches render_markdown order).
    arms = sorted(
        (a for a in paired if a != control),
        key=lambda a: (0 if a == "society" else 1, a),
    )
    for arm in arms:
        treat = paired[arm]
        common = sorted(set(ctrl) & set(treat))
        if not common:
            continue
        diffs = [treat[s] - ctrl[s] for s in common]
        n = len(diffs)
        mean_delta = stats.mean(diffs)
        sd_delta = stats.sample_sd(diffs)
        ci = stats.bootstrap_ci(
            diffs, confidence=1.0 - alpha, rng_seed=_PAIRED_BOOTSTRAP_SEED
        )
        sign_p = stats.sign_test_p(diffs)
        observed_power = (
            stats.power_for_n(mean_delta, sd_delta, n, alpha)
            if mean_delta != 0.0
            else None
        )
        ci_excludes_zero = not (ci.lower <= 0.0 <= ci.upper)
        sign_significant = sign_p < alpha
        if not ci_excludes_zero:
            verdict = "noise"
        elif not sign_significant:
            verdict = "suggestive"
        else:
            verdict = "credible"
        row: dict[str, Any] = {
            "control": control,
            "treatment": arm,
            "n": n,
            "seeds": common,
            "mean_delta": mean_delta,
            "sd_delta": sd_delta,
            "n_positive": sum(1 for d in diffs if d > 0),
            "n_negative": sum(1 for d in diffs if d < 0),
            "n_tied": sum(1 for d in diffs if d == 0),
            "sign_test_p": sign_p,
            "verdict": verdict,
            "ci_excludes_zero": ci_excludes_zero,
            "sign_significant": sign_significant,
            "ci": {
                "lower": ci.lower,
                "upper": ci.upper,
                "confidence": ci.confidence,
                "n_resamples": ci.n_resamples,
            },
            "observed_power": observed_power,
        }
        if provenance is not None:
            row["provenance"] = provenance
        out.append(row)
    return out


def render_markdown(agg: dict[str, Any]) -> str:
    """Render RESULTS.md content: headline table + paired lives_saved table.

    Headline table columns:
      arm | n | mean_lives_saved | sd | mean_lives_lost | sd |
      mean_missions_resolved | mean_missions_failed | mean_cost_usd | mean_wall_s |
      lives_per_dollar

    Rows sorted society-first, then remaining arms alphabetically.
    """
    arm_stats: dict[str, dict[str, Any]] = agg["arms"]
    paired: dict[str, dict[int, float]] = agg.get("paired", {})

    # Sort: society first, then alphabetical
    def _arm_sort_key(arm: str) -> tuple[int, str]:
        return (0 if arm == "society" else 1, arm)

    sorted_arms = sorted(arm_stats.keys(), key=_arm_sort_key)

    # Headline table
    lines: list[str] = []
    lines.append("## Benchmark Results")
    lines.append("")
    header = (
        "| arm | n | mean_lives_saved | sd | mean_lives_lost | sd |"
        " mean_missions_resolved | mean_missions_failed |"
        " mean_cost_usd | mean_wall_s | lives_per_dollar (= mean lives / mean cost) |"
        " mean_team_alignment |"
    )
    sep = (
        "|---|---|---|---|---|---|---|---|---|---|---|---|"
    )
    lines.append(header)
    lines.append(sep)

    for arm in sorted_arms:
        s = arm_stats[arm]
        lpd = f"{s['lives_per_dollar']:.4f}" if "lives_per_dollar" in s else "—"
        ta = s.get("mean_team_alignment")
        ta_str = f"{ta:.3f}" if ta is not None else "—"
        row = (
            f"| {arm} "
            f"| {s['n']} "
            f"| {s['mean_lives_saved']:.2f} "
            f"| {s['sd_lives_saved']:.2f} "
            f"| {s['mean_lives_lost']:.2f} "
            f"| {s['sd_lives_lost']:.2f} "
            f"| {s['mean_missions_resolved']:.2f} "
            f"| {s['mean_missions_failed']:.2f} "
            f"| {s['mean_cost_usd']:.4f} "
            f"| {s['mean_wall_s']:.2f} "
            f"| {lpd} "
            f"| {ta_str} |"
        )
        lines.append(row)

    lines.append("")

    # Paired lives_saved table
    # Collect all seeds (sorted)
    all_seeds: list[int] = sorted({
        seed
        for arm_seeds in paired.values()
        for seed in arm_seeds
    })

    if all_seeds:
        lines.append("## Paired lives_saved by seed")
        lines.append("")
        seed_header = "| arm | " + " | ".join(str(s) for s in all_seeds) + " |"
        seed_sep = "|---|" + "|".join("---" for _ in all_seeds) + "|"
        lines.append(seed_header)
        lines.append(seed_sep)

        # Warn if arms have different seed coverage (invalid paired comparison)
        arm_seed_sets = {arm: set(paired.get(arm, {}).keys()) for arm in sorted_arms}
        all_seed_set = set(all_seeds)
        for arm in sorted_arms:
            missing = all_seed_set - arm_seed_sets[arm]
            if missing:
                import sys
                print(
                    f"warning: arm {arm!r} missing seeds {sorted(missing)} in paired table "
                    "(paired comparison invalid across unequal seed sets)",
                    file=sys.stderr,
                    flush=True,
                )

        for arm in sorted_arms:
            arm_paired = paired.get(arm, {})
            cells_str = " | ".join(
                f"{arm_paired[seed]:.0f}" if seed in arm_paired else "·"
                for seed in all_seeds
            )
            lines.append(f"| {arm} | {cells_str} |")

        lines.append("")

    return "\n".join(lines) + "\n"


# ===========================================================================
# M3 — Paired ablation harness + power curve
# ===========================================================================

# Effect sizes (lives) the power curve answers "how many seeds do I need?" for.
DEFAULT_EFFECT_GRID: tuple[float, ...] = (2.0, 5.0, 10.0, 15.0, 20.0)
# Fixed bootstrap seed so ABLATION.md is byte-stable across re-runs of the analysis.
_ABLATION_BOOTSTRAP_SEED = 20260614


def _lives_by_seed(
    cells: list[dict[str, Any]], name: str, *, key: str = "arm"
) -> dict[int, float]:
    """Map seed -> lives_saved for one side (last cell wins on duplicate seeds).

    ``key`` selects the field that names the side: "arm" for the normal arm-vs-arm
    ablation, or "label" for the doctrine on/off ablation where both sides share the
    same arm ("society") and are distinguished by a ``label`` field instead.
    """
    out: dict[int, float] = {}
    for c in cells:
        if c.get(key) == name:
            out[int(c["seed"])] = float(c.get("scores", {}).get("lives_saved", 0.0))
    return out


def _verdict_fields(
    diffs: list[float], bootstrap_seed: int, *, alpha: float = 0.05
) -> dict[str, Any]:
    """The 3-tier verdict + its supporting stats for a list of paired diffs.

    The single source of truth for the tiering both the lives verdict
    (analyze_ablation) and the conformance verdict (_conformance_block) use, so they
    can never drift: "credible" iff the bootstrap CI excludes 0 AND the sign test is
    significant; "suggestive" iff exactly one holds; "noise" iff neither
    (FIELD-NOTES §16–17 — keying on the CI alone over-claims on small skewed samples).

    Returns ``verdict``=None and absent supporting fields when ``diffs`` is empty (no
    paired deltas to judge) — callers must not coerce/fabricate a verdict in that case.
    The ``ci``/``sign_test_p`` keys carry the same shape analyze_ablation emits.
    """
    if not diffs:
        return {
            "verdict": None,
            "ci_excludes_zero": None,
            "sign_significant": None,
            "sign_test_p": None,
            "n_positive": 0,
            "ci": None,
        }
    ci = stats.bootstrap_ci(diffs, confidence=1.0 - alpha, rng_seed=bootstrap_seed)
    sign_p = stats.sign_test_p(diffs)
    ci_excludes_zero = not (ci.lower <= 0.0 <= ci.upper)
    sign_significant = sign_p < alpha
    if not ci_excludes_zero:
        verdict = "noise"
    elif not sign_significant:
        verdict = "suggestive"
    else:
        verdict = "credible"
    return {
        "verdict": verdict,
        "ci_excludes_zero": ci_excludes_zero,
        "sign_significant": sign_significant,
        "sign_test_p": sign_p,
        "n_positive": sum(1 for d in diffs if d > 0),
        "ci": {
            "lower": ci.lower,
            "upper": ci.upper,
            "confidence": ci.confidence,
            "n_resamples": ci.n_resamples,
        },
    }


def analyze_ablation(
    cells: list[dict[str, Any]],
    control: str,
    treatment: str,
    *,
    key: str = "arm",
    effect_grid: tuple[float, ...] = DEFAULT_EFFECT_GRID,
    power_target: float = 0.8,
    alpha: float = 0.05,
    model_endpoint: str | None = None,
) -> dict[str, Any]:
    """Paired control-vs-treatment analysis over their common seeds (pure).

    Pairing per seed removes the world variance that dominates the raw ±, so a
    small but consistent effect becomes visible. Reports the paired Δ, an exact
    sign test, a bootstrap CI, and a power curve (required seeds per effect size).

    ``key`` names the cell field that distinguishes the two sides — "arm" (default)
    for arm-vs-arm, or "label" for the doctrine on/off ablation (same arm, one knob).
    """
    ctrl = _lives_by_seed(cells, control, key=key)
    treat = _lives_by_seed(cells, treatment, key=key)
    common = sorted(set(ctrl) & set(treat))
    if not common:
        raise ValueError(
            f"no common seeds between control={control!r} and treatment={treatment!r}"
        )

    per_seed = [
        {"seed": s, "control": ctrl[s], "treatment": treat[s], "delta": treat[s] - ctrl[s]}
        for s in common
    ]
    diffs = [row["delta"] for row in per_seed]
    n = len(diffs)
    mean_delta = stats.mean(diffs)
    sd_delta = stats.sample_sd(diffs)

    observed_power = (
        stats.power_for_n(mean_delta, sd_delta, n, alpha) if mean_delta != 0.0 else None
    )

    power_curve = [
        {
            "effect": eff,
            "required_n": stats.required_n_for_effect(
                eff, sd_delta, power=power_target, alpha=alpha
            ),
            "power_at_current_n": stats.power_for_n(eff, sd_delta, n, alpha),
        }
        for eff in effect_grid
    ]

    # Verdict — "credible" requires the bootstrap CI AND the sign test to AGREE.
    # The percentile CI excludes 0 on small, skewed samples where the conservative
    # sign test does not, so keying on the CI alone over-claims (FIELD-NOTES §16–17:
    # it printed "credible" at n=5 twice on effects that were noise). Computed by the
    # shared _verdict_fields helper so the lives verdict and the conformance verdict
    # use ONE tiering rule that can never drift. ``common`` is non-empty here (we raise
    # above otherwise), so the helper returns a fully-populated verdict.
    vf = _verdict_fields(diffs, _ABLATION_BOOTSTRAP_SEED, alpha=alpha)

    return {
        "control": control,
        "treatment": treatment,
        "n": n,
        "seeds": common,
        "per_seed": per_seed,
        "mean_control": stats.mean([ctrl[s] for s in common]),
        "mean_treatment": stats.mean([treat[s] for s in common]),
        "mean_delta": mean_delta,
        "sd_delta": sd_delta,
        "n_positive": vf["n_positive"],
        "n_negative": sum(1 for d in diffs if d < 0),
        "n_tied": sum(1 for d in diffs if d == 0),
        "sign_test_p": vf["sign_test_p"],
        "verdict": vf["verdict"],
        "ci_excludes_zero": vf["ci_excludes_zero"],
        "sign_significant": vf["sign_significant"],
        "ci": vf["ci"],
        "observed_power": observed_power,
        "power_target": power_target,
        "alpha": alpha,
        "power_curve": power_curve,
        "provenance": _provenance_stamp(cells, model_endpoint=model_endpoint),
    }


# Cell-dir / label suffix for the doctrine-naive (doctrine=False) control side.
_NODOCTRINE_SUFFIX = "-nodoctrine"


def _alignment_by_seed(
    cells: list[dict[str, Any]], name: str, *, key: str = "label"
) -> dict[int, float]:
    """seed -> team_alignment for one labeled side (seeds with None alignment skipped)."""
    out: dict[int, float] = {}
    for c in cells:
        if c.get(key) == name:
            ta = c.get("team_alignment")
            if ta is not None:
                out[int(c["seed"])] = float(ta)
    return out


def _role_conf_by_seed(
    cells: list[dict[str, Any]], name: str, *, key: str = "label"
) -> dict[int, dict[str, float]]:
    """seed -> {role: conformance} for one labeled side (None entries dropped)."""
    out: dict[int, dict[str, float]] = {}
    for c in cells:
        if c.get(key) == name:
            rc = c.get("role_conformance")
            if isinstance(rc, dict):
                out[int(c["seed"])] = {
                    r: float(v) for r, v in rc.items() if v is not None
                }
    return out


def _conformance_block(
    cells: list[dict[str, Any]],
    control_label: str,
    treatment_label: str,
    *,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Paired conformance summary for the doctrine ablation.

    Conformance (team_alignment + per-role) is computed deterministically from the
    run records, so it is the *low-variance* signal this ablation exists to confirm
    (FIELD-NOTES §11). Pairs by seed and reports the team-alignment Δ and a per-role
    mean-alignment table for both sides.
    """
    ctrl = _alignment_by_seed(cells, control_label)
    treat = _alignment_by_seed(cells, treatment_label)
    common = sorted(set(ctrl) & set(treat))
    per_seed = [
        {"seed": s, "control": ctrl[s], "treatment": treat[s], "delta": treat[s] - ctrl[s]}
        for s in common
    ]
    deltas = [row["delta"] for row in per_seed]

    crole = _role_conf_by_seed(cells, control_label)
    trole = _role_conf_by_seed(cells, treatment_label)
    roles_seen = sorted(
        {r for s in common for r in (set(crole.get(s, {})) | set(trole.get(s, {})))}
    )
    by_role: dict[str, dict[str, float]] = {}
    for role in roles_seen:
        cvals = [crole[s][role] for s in common if role in crole.get(s, {})]
        tvals = [trole[s][role] for s in common if role in trole.get(s, {})]
        if cvals and tvals:
            cm = stats.mean(cvals)
            tm = stats.mean(tvals)
            by_role[role] = {"control": cm, "treatment": tm, "delta": tm - cm}

    block: dict[str, Any] = {
        "n": len(common),
        "seeds": common,
        "per_seed": per_seed,
        "mean_control": stats.mean([ctrl[s] for s in common]) if common else None,
        "mean_treatment": stats.mean([treat[s] for s in common]) if common else None,
        "mean_delta": stats.mean(deltas) if deltas else None,
        "sign_test_p": stats.sign_test_p(deltas) if deltas else None,
        "by_role": by_role,
    }
    # conformance_verdict — the SAME 3-tier gate the lives verdict uses (read
    # analyze_ablation / _verdict_fields): "credible" iff the bootstrap CI excludes 0
    # AND the sign test is significant; "suggestive" iff exactly one; "noise" iff
    # neither. Conformance is the doctrine ablation's PRIMARY metric, so it earns a
    # verdict parallel to (and separate from) the secondary lives verdict
    # (FIELD-NOTES §18). Computed only when per-seed deltas exist; otherwise the
    # verdict + supporting fields are None so non-doctrine / conformance-failed paths
    # are never coerced/fabricated. Keys are namespaced "verdict"/"ci"/... INSIDE the
    # conformance block (the index reads conformance.verdict), and sign_test_p here
    # equals the value already set above (same deltas, same helper). ``alpha`` is the
    # caller-threaded significance level (same one analyze_ablation hands the lives
    # verdict) so the two verdicts can never use a different alpha.
    vf = _verdict_fields(deltas, _ABLATION_BOOTSTRAP_SEED, alpha=alpha)
    block["verdict"] = vf["verdict"]
    block["ci"] = vf["ci"]
    block["ci_excludes_zero"] = vf["ci_excludes_zero"]
    block["sign_significant"] = vf["sign_significant"]
    block["sign_test_p"] = vf["sign_test_p"]
    block["n_positive"] = vf["n_positive"]
    return block


def run_ablation(
    control: str,
    treatment: str,
    seeds: list[int],
    ticks: int,
    provider: Any | None,
    out_dir: Path,
    *,
    ablate: str | None = None,
    society_tools: bool = False,
    seed_sampler: bool = False,
    pool_sizes: dict[str, int] | None = None,
    effect_grid: tuple[float, ...] = DEFAULT_EFFECT_GRID,
    power_target: float = 0.8,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Run (or resume) control + treatment over ``seeds`` and analyze the pair.

    Reuses the shared cell kernel, so completed cells are skipped — re-running the
    analysis on existing cells costs $0. Returns the analyze_ablation result dict.

    ``ablate`` selects a *same-arm knob* ablation instead of arm-vs-arm. The only
    supported knob is "doctrine": control and treatment must be the same LLM arm,
    and the harness runs it twice per seed — doctrine OFF (control) vs ON (treatment)
    — pairing on a synthetic ``label`` so both society cells stay distinct. The result
    additionally carries a ``conformance`` block (the primary, low-variance signal —
    FIELD-NOTES §11) and ``ablate``/``arm`` markers.
    """
    if ablate is not None:
        return _run_doctrine_ablation(
            ablate, control, treatment, seeds, ticks, provider, out_dir,
            society_tools=society_tools, seed_sampler=seed_sampler, pool_sizes=pool_sizes,
            effect_grid=effect_grid, power_target=power_target, alpha=alpha,
        )

    arms = [control] if control == treatment else [control, treatment]
    manifest: dict[str, Any] = {"ticks": ticks, "seeds": list(seeds), "arms": arms}
    cells = run_bench(
        manifest, provider=provider, out_dir=out_dir,
        society_tools=society_tools, seed_sampler=seed_sampler, pool_sizes=pool_sizes,
    )
    return analyze_ablation(
        cells, control, treatment,
        effect_grid=effect_grid, power_target=power_target, alpha=alpha,
        model_endpoint=_endpoint_from_provider(provider),
    )


def _run_doctrine_ablation(
    ablate: str,
    control: str,
    treatment: str,
    seeds: list[int],
    ticks: int,
    provider: Any | None,
    out_dir: Path,
    *,
    society_tools: bool = False,
    seed_sampler: bool = False,
    pool_sizes: dict[str, int] | None = None,
    effect_grid: tuple[float, ...] = DEFAULT_EFFECT_GRID,
    power_target: float = 0.8,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Doctrine ON/OFF paired ablation for a single LLM arm (FIELD-NOTES §11).

    Holds everything constant (world seed, tools, pools) and flips only the doctrine
    layer. Both sides are the same arm, so they are tagged with a ``label``
    ("{arm}" = ON, "{arm}-nodoctrine" = OFF) and analyzed key="label". Δ = ON − OFF,
    so a positive Δ means doctrine *adds* lives.
    """
    if ablate != "doctrine":
        raise ValueError(f"unknown ablate knob {ablate!r}; supported: 'doctrine'")
    if control != treatment:
        raise ValueError(
            "doctrine ablation requires control == treatment (the arm to ablate); "
            f"got control={control!r}, treatment={treatment!r}"
        )
    arm = control
    if arm == "scripted":
        raise ValueError(
            "the scripted arm carries no doctrine prompts — ablate an LLM arm "
            "(society/swarm/solo)"
        )

    treatment_label = arm  # doctrine ON (canonical cell dir)
    control_label = f"{arm}{_NODOCTRINE_SUFFIX}"  # doctrine OFF
    out_dir.mkdir(parents=True, exist_ok=True)

    cells: list[dict[str, Any]] = []
    for seed in seeds:
        on = _run_or_resume_cell(
            out_dir, arm, seed, ticks, provider, run_id=f"{arm}-seed{seed}",
            society_tools=society_tools, seed_sampler=seed_sampler,
            pool_sizes=pool_sizes, doctrine=True,
        )
        cells.append({**on, "label": treatment_label})
        off = _run_or_resume_cell(
            out_dir, arm, seed, ticks, provider, run_id=f"{control_label}-seed{seed}",
            society_tools=society_tools, seed_sampler=seed_sampler,
            pool_sizes=pool_sizes, doctrine=False,
        )
        cells.append({**off, "label": control_label})

    result = analyze_ablation(
        cells, control_label, treatment_label, key="label",
        effect_grid=effect_grid, power_target=power_target, alpha=alpha,
        model_endpoint=_endpoint_from_provider(provider),
    )
    result["ablate"] = "doctrine"
    result["arm"] = arm
    result["conformance"] = _conformance_block(
        cells, control_label, treatment_label, alpha=alpha
    )
    return result


def _render_conformance_section(conf: dict[str, Any]) -> list[str]:
    """Render the conformance block (team alignment + per-role) — assumes n>0."""
    lines: list[str] = ["## Conformance (primary signal — deterministic)", ""]
    md = conf["mean_delta"]
    sp = conf["sign_test_p"]
    sp_str = f"{sp:.4f}" if sp is not None else "n/a"
    lines.append(
        f"**Team alignment: {conf['mean_control']:.3f} (off) → "
        f"{conf['mean_treatment']:.3f} (on)** · Δ = {md:+.3f} · "
        f"sign test p={sp_str} · n={conf['n']}"
    )
    lines.append("")

    # Verdict (conformance Δ) — the SAME 3-tier gate the lives section prints, but
    # over the conformance Δ (this ablation's PRIMARY metric). Mirrors the lives
    # "Verdict (lives Δ): ..." line so a reader sees a verdict per signal.
    verdict = conf.get("verdict")
    if verdict is not None:
        ci = conf.get("ci") or {}
        conf_pct = int(round(float(ci.get("confidence", 0.95)) * 100))
        p = conf.get("sign_test_p")
        p_str = f"{p:.3f}" if p is not None else "n/a"
        if verdict == "noise":
            lines.append(
                f"> Verdict (conformance Δ): **not distinguishable from noise** — the "
                f"{conf_pct}% CI includes 0 (sign test p={p_str}). Add seeds before "
                "claiming a conformance effect."
            )
        elif verdict == "suggestive":
            lines.append(
                f"> Verdict (conformance Δ): **suggestive but unconfirmed** — the "
                f"{conf_pct}% CI excludes 0, but the sign test is not significant "
                f"(p={p_str}). Add seeds until the sign test agrees."
            )
        else:
            direction = "improvement" if (md is not None and md > 0) else "regression"
            lines.append(
                f"> Verdict (conformance Δ): **credible {direction}** — the {conf_pct}% "
                f"CI excludes 0 *and* the sign test is significant (p={p_str})."
            )
        lines.append("")

    lines.append("| seed | off | on | Δ |")
    lines.append("|---|---|---|---|")
    for row in conf["per_seed"]:
        lines.append(
            f"| {row['seed']} | {row['control']:.3f} | "
            f"{row['treatment']:.3f} | {row['delta']:+.3f} |"
        )
    lines.append("")
    by_role = conf.get("by_role") or {}
    if by_role:
        lines.append("Per-role mean alignment (off → on):")
        lines.append("")
        lines.append("| role | off | on | Δ |")
        lines.append("|---|---|---|---|")
        for role in sorted(by_role):
            rv = by_role[role]
            lines.append(
                f"| {role} | {rv['control']:.3f} | "
                f"{rv['treatment']:.3f} | {rv['delta']:+.3f} |"
            )
        lines.append("")
    return lines


def render_ablation_markdown(result: dict[str, Any]) -> str:
    """Render an ABLATION.md from an analyze_ablation result.

    For a doctrine ablation the deterministic conformance Δ is the *primary* signal
    (FIELD-NOTES §11), so it is rendered first and the noisy lives verdict is demoted
    to a clearly-labeled secondary section. If conformance is missing or only partial
    (a conformance check failed on some/all seeds), a prominent warning is emitted so
    the lives result cannot be silently read as confirming a doctrine effect — the
    same honesty discipline that hardened the lives verdict in §16–17.
    """
    lines: list[str] = []
    ctrl = result["control"]
    treat = result["treatment"]
    is_doctrine = result.get("ablate") == "doctrine"
    conf = result.get("conformance")
    lives_n = result["n"]
    conf_n = conf.get("n", 0) if conf else 0

    if is_doctrine:
        arm = result.get("arm", treat)
        lines.append(f"# Ablation — doctrine on/off ({arm}, paired)")
        lines.append("")
        lines.append(
            f"Δ = **{treat} (doctrine on)** − **{ctrl} (doctrine off)**, everything else held "
            "constant (world seed, tools, pools). A positive Δ means doctrine adds the metric."
        )
    else:
        lines.append(f"# Ablation — {treat} vs {ctrl} (paired)")
    lines.append("")

    # Doctrine ablation: lead with conformance (primary, deterministic). Warn loudly
    # when it is missing/partial so the secondary lives verdict can't be over-read.
    if is_doctrine:
        if conf_n == 0:
            lines.append(
                f"> ⚠️ **Primary signal missing.** The conformance check produced no usable "
                f"paired seeds (0 of {lives_n}); conformance — not lives — is this ablation's "
                "headline (FIELD-NOTES §11). Treat the lives result below as **secondary and "
                "unconfirmed**: on its own it neither confirms nor denies a doctrine effect."
            )
            lines.append("")
        else:
            if conf_n < lives_n:
                lines.append(
                    f"> ⚠️ Conformance is missing for {lives_n - conf_n} of {lives_n} seeds "
                    f"(a conformance check failed); the figures below cover only the {conf_n} "
                    "seeds where both sides reported alignment."
                )
                lines.append("")
            lines.extend(_render_conformance_section(conf))
        lines.append("## Lives (secondary signal)")
        lines.append("")

    lines.append(
        f"**n={lives_n} paired seeds** · "
        f"mean {ctrl}={result['mean_control']:.2f} · "
        f"mean {treat}={result['mean_treatment']:.2f}"
    )
    lines.append("")
    conf_pct = int(round(result["ci"]["confidence"] * 100))
    lines.append(
        f"**Δ lives = {result['mean_delta']:+.2f}** "
        f"(sd {result['sd_delta']:.2f}) · "
        f"{conf_pct}% bootstrap CI "
        f"[{result['ci']['lower']:+.2f}, {result['ci']['upper']:+.2f}] · "
        f"sign test p={result['sign_test_p']:.4f} "
        f"({result['n_positive']}+/{result['n_negative']}-/{result['n_tied']}=)"
    )
    op = result["observed_power"]
    if op is not None:
        lines.append("")
        lines.append(
            f"Observed power to detect this Δ at n={lives_n}: **{op:.2f}** "
            f"(α={result['alpha']})."
        )

    # Verdict line — the bootstrap CI and the sign test must AGREE before an effect
    # is called "credible" (FIELD-NOTES §16–17: a CI-only verdict over-claimed at n=5).
    # For a doctrine ablation this verdict is about LIVES only (the secondary signal).
    p = result["sign_test_p"]
    alpha = result["alpha"]
    power_str = f"{op:.2f}" if op is not None else "n/a"
    # Non-doctrine output stays byte-identical ("Verdict:"); doctrine tags the verdict
    # as the LIVES (secondary) signal so it can't be mistaken for the headline.
    label = "Verdict (lives Δ)" if is_doctrine else "Verdict"
    metric = "lives " if is_doctrine else ""
    lines.append("")
    if result["verdict"] == "noise":
        lines.append(
            f"> {label}: **not distinguishable from noise** — the {conf_pct}% CI includes 0 "
            f"(sign test p={p:.3f}). Add seeds (see the power curve) before claiming an effect."
        )
    elif result["verdict"] == "suggestive":
        lines.append(
            f"> {label}: **suggestive but unconfirmed** — the {conf_pct}% CI excludes 0, but "
            f"the sign test is not significant (p={p:.3f} ≥ {alpha}) and power is {power_str}. "
            "The percentile bootstrap is optimistic on small, skewed samples; treat this as a "
            "lead and add seeds (see the power curve) until the sign test agrees."
        )
    else:
        direction = "improvement" if result["mean_delta"] > 0 else "regression"
        lines.append(
            f"> {label}: **credible {metric}{direction}** — the {conf_pct}% CI excludes 0 *and* "
            f"the sign test is significant (p={p:.3f} < {alpha})."
        )
    lines.append("")

    # Per-seed paired table
    lines.append("## Per-seed")
    lines.append("")
    lines.append(f"| seed | {ctrl} | {treat} | Δ |")
    lines.append("|---|---|---|---|")
    for row in result["per_seed"]:
        lines.append(
            f"| {row['seed']} | {row['control']:.0f} | "
            f"{row['treatment']:.0f} | {row['delta']:+.0f} |"
        )
    lines.append("")

    # Power curve
    lines.append("## Power curve")
    lines.append("")
    lines.append(
        f"Paired z-approximation; seeds needed for {int(round(result['power_target'] * 100))}% "
        f"power at α={result['alpha']}, given the observed Δ sd={result['sd_delta']:.2f}."
    )
    lines.append("")
    lines.append("| effect (lives) | seeds needed | power at current n |")
    lines.append("|---|---|---|")
    for pt in result["power_curve"]:
        lines.append(
            f"| +{pt['effect']:.0f} | {pt['required_n']} | {pt['power_at_current_n']:.2f} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


# ===========================================================================
# M2 — K-repeats-per-seed variance decomposition
# ===========================================================================


def run_repeat_seeds(
    arms: list[str],
    seeds: list[int],
    repeats: int,
    ticks: int,
    provider: Any | None,
    out_dir: Path,
    *,
    society_tools: bool = False,
    seed_sampler: bool = False,
    pool_sizes: dict[str, int] | None = None,
    role_models: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Run each (arm, seed) ``repeats`` times into ``{arm}-seed{seed}-r{k}`` cells.

    The engine seed is identical across repeats, so the *world* is byte-identical
    and the only variation is LLM sampling — exactly the within-seed component M2
    isolates. Resume-aware (skips cells whose ticks match). For scripted, every
    repeat is identical (within-variance = 0) — a free correctness check.

    ``seed_sampler`` (M1) is rejected: it sends an identical per-tick provider seed
    to every repeat, collapsing the within-seed variance this function measures.
    """
    if seed_sampler:
        raise ValueError(
            "run_repeat_seeds(seed_sampler=True) is contradictory: the seed sampler "
            "(M1) removes the within-seed LLM variance that repeats (M2) measure."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    cells: list[dict[str, Any]] = []
    for arm in arms:
        for seed in seeds:
            for k in range(repeats):
                run_id = f"{arm}-seed{seed}-r{k}"
                summary_path = out_dir / run_id / "summary.json"
                if summary_path.exists():
                    try:
                        cached = json.loads(summary_path.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        cached = None
                    if cached is not None and cached.get("ticks_requested") == ticks:
                        cells.append(cached)
                        continue
                cells.append(
                    _execute_cell(
                        out_dir, arm, seed, ticks, provider, run_id=run_id,
                        society_tools=society_tools, seed_sampler=seed_sampler,
                        pool_sizes=pool_sizes, role_models=role_models,
                        extra_fields={"repeat": k},
                    )
                )
    return cells


def analyze_repeats(
    cells: list[dict[str, Any]], *, model_endpoint: str | None = None
) -> dict[str, Any]:
    """Per-arm variance decomposition from repeat cells (pure).

    Splits total lives_saved variance into within-seed (LLM sampling) and
    between-seed (world) components via a one-way random-effects model.

    The result carries a ``provenance`` stamp under the reserved ``provenance`` key
    (no arm is ever named "provenance"), reusing the scripted cell's final-tick
    digest from ``cells`` (no second verify run). ``model_endpoint`` is supplied by
    the CLI; when omitted it is inferred from the cells.
    """
    by_arm: dict[str, dict[int, list[float]]] = {}
    for c in cells:
        arm = c["arm"]
        seed = int(c["seed"])
        lives = float(c.get("scores", {}).get("lives_saved", 0.0))
        by_arm.setdefault(arm, {}).setdefault(seed, []).append(lives)

    result: dict[str, Any] = {}
    for arm, seedmap in sorted(by_arm.items()):
        groups = [seedmap[s] for s in sorted(seedmap)]
        vc = stats.variance_components(groups)
        result[arm] = {
            "n_seeds": vc.n_seeds,
            "repeats": vc.repeats,
            "grand_mean": vc.grand_mean,
            "sd_within": vc.sd_within,
            "sd_between": vc.sd_between,
            "sd_total": vc.sd_total,
            "icc": vc.icc,
            "per_seed_means": {str(s): stats.mean(seedmap[s]) for s in sorted(seedmap)},
        }
    result["provenance"] = _provenance_stamp(cells, model_endpoint=model_endpoint)
    return result


def render_repeats_markdown(result: dict[str, Any]) -> str:
    """Render a REPEATS.md from an analyze_repeats result."""
    lines: list[str] = []
    lines.append("# Variance decomposition — repeats per seed")
    lines.append("")
    lines.append(
        "Within-seed σ = LLM sampling noise (identical world); "
        "between-seed σ = world variance; ICC = world fraction of total variance."
    )
    lines.append("")
    lines.append(
        "| arm | seeds | repeats | mean | σ_within (LLM) | σ_between (world) "
        "| σ_total | ICC |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for arm in sorted(result):
        if arm == "provenance":  # reserved stamp key — not an arm
            continue
        s = result[arm]
        lines.append(
            f"| {arm} | {s['n_seeds']} | {s['repeats']} | {s['grand_mean']:.2f} "
            f"| {s['sd_within']:.2f} | {s['sd_between']:.2f} | {s['sd_total']:.2f} "
            f"| {s['icc']:.3f} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"
