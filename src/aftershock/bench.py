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
import time
from pathlib import Path
from typing import Any

from aftershock import stats
from aftershock.kernel.engine import Engine
from aftershock.kernel.recorder import Recorder
from aftershock.town.arms import build_arm


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
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build + run one (arm, seed) cell and write its summary.json.

    Shared by run_bench and run_repeat_seeds. ``run_id`` is the cell directory
    name (``{arm}-seed{seed}`` for bench, ``...-r{k}`` for repeats). Conformance
    failure is logged but never blocks summary.json from being written.
    """
    setup = build_arm(
        arm, seed, provider, society_tools=society_tools, seed_sampler=seed_sampler,
        pool_sizes=pool_sizes,
    )
    manifest_rec: dict[str, Any] = {
        "arm": arm,
        "seed": seed,
        "ticks": ticks,
        "run_id": run_id,
    }
    recorder = Recorder(out_dir, run_id, manifest_rec)

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


def run_bench(
    manifest: dict[str, Any],
    provider: Any | None,
    out_dir: Path,
    society_tools: bool = False,
    seed_sampler: bool = False,
    pool_sizes: dict[str, int] | None = None,
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
            cell_dir = _cell_dir(out_dir, arm, seed)
            summary_path = cell_dir / "summary.json"

            # Resume: skip cells that already have a completed summary, but
            # only if the recorded ticks_requested matches the current manifest.
            # A mismatch (e.g. resume with ticks=60 into a ticks=8 run) forces
            # a re-run so cells from different tick budgets are never mixed.
            if summary_path.exists():
                try:
                    with summary_path.open(encoding="utf-8") as fh:
                        cached = json.load(fh)
                except (json.JSONDecodeError, OSError):
                    # Corrupt or truncated summary — treat as not-yet-run
                    print(
                        f"warning: corrupt summary at {summary_path}; re-running cell",
                        flush=True,
                    )
                    cached = None

                if cached is not None:
                    if cached.get("ticks_requested") == ticks:
                        cells.append(cached)
                        continue
                    # Tick budget changed — force re-run
                    print(
                        f"warning: ticks mismatch for {arm}-seed{seed} "
                        f"(cached={cached.get('ticks_requested')}, requested={ticks}); "
                        "re-running cell",
                        flush=True,
                    )

            # Run this cell
            cell_summary = _execute_cell(
                out_dir,
                arm,
                seed,
                ticks,
                provider,
                run_id=f"{arm}-seed{seed}",
                society_tools=society_tools,
                seed_sampler=seed_sampler,
                pool_sizes=pool_sizes,
            )
            cells.append(cell_summary)

    return cells


def aggregate(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute per-arm statistics from a list of per-cell summary dicts.

    Per arm computes n, mean, and sample standard deviation (ddof=1) for:
      lives_saved, lives_lost, missions_resolved, missions_failed,
      cost_usd, wall_s

    lives_per_dollar = mean_lives_saved / mean_cost_usd is included only for
    arms whose mean_cost_usd > 0 (zero-cost arms like 'scripted' are omitted).

    Also produces the per-seed paired table: arm x seed -> lives_saved.
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

    return {"arms": arm_stats, "paired": paired}


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


def _lives_by_seed(cells: list[dict[str, Any]], arm: str) -> dict[int, float]:
    """Map seed -> lives_saved for one arm (last cell wins on duplicate seeds)."""
    out: dict[int, float] = {}
    for c in cells:
        if c.get("arm") == arm:
            out[int(c["seed"])] = float(c.get("scores", {}).get("lives_saved", 0.0))
    return out


def analyze_ablation(
    cells: list[dict[str, Any]],
    control: str,
    treatment: str,
    *,
    effect_grid: tuple[float, ...] = DEFAULT_EFFECT_GRID,
    power_target: float = 0.8,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Paired control-vs-treatment analysis over their common seeds (pure).

    Pairing per seed removes the world variance that dominates the raw ±, so a
    small but consistent effect becomes visible. Reports the paired Δ, an exact
    sign test, a bootstrap CI, and a power curve (required seeds per effect size).
    """
    ctrl = _lives_by_seed(cells, control)
    treat = _lives_by_seed(cells, treatment)
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

    ci = stats.bootstrap_ci(
        diffs, confidence=1.0 - alpha, rng_seed=_ABLATION_BOOTSTRAP_SEED
    )
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
    # it printed "credible" at n=5 twice on effects that were noise). Exposed as a
    # structured field so callers (e.g. an autoresearch loop) can gate on it.
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
        "control": control,
        "treatment": treatment,
        "n": n,
        "seeds": common,
        "per_seed": per_seed,
        "mean_control": stats.mean([ctrl[s] for s in common]),
        "mean_treatment": stats.mean([treat[s] for s in common]),
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
        "power_target": power_target,
        "alpha": alpha,
        "power_curve": power_curve,
    }


def run_ablation(
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
    """Run (or resume) control + treatment over ``seeds`` and analyze the pair.

    Reuses run_bench, so completed cells are skipped — re-running the analysis on
    existing cells costs $0. Returns the analyze_ablation result dict.
    """
    arms = [control] if control == treatment else [control, treatment]
    manifest: dict[str, Any] = {"ticks": ticks, "seeds": list(seeds), "arms": arms}
    cells = run_bench(
        manifest, provider=provider, out_dir=out_dir,
        society_tools=society_tools, seed_sampler=seed_sampler, pool_sizes=pool_sizes,
    )
    return analyze_ablation(
        cells, control, treatment,
        effect_grid=effect_grid, power_target=power_target, alpha=alpha,
    )


def render_ablation_markdown(result: dict[str, Any]) -> str:
    """Render an ABLATION.md from an analyze_ablation result."""
    lines: list[str] = []
    ctrl = result["control"]
    treat = result["treatment"]
    lines.append(f"# Ablation — {treat} vs {ctrl} (paired)")
    lines.append("")
    lines.append(
        f"**n={result['n']} paired seeds** · "
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
            f"Observed power to detect this Δ at n={result['n']}: **{op:.2f}** "
            f"(α={result['alpha']})."
        )

    # Verdict line — the bootstrap CI and the sign test must AGREE before an effect
    # is called "credible" (FIELD-NOTES §16–17: a CI-only verdict over-claimed at n=5).
    p = result["sign_test_p"]
    alpha = result["alpha"]
    power_str = f"{op:.2f}" if op is not None else "n/a"
    lines.append("")
    if result["verdict"] == "noise":
        lines.append(
            f"> Verdict: **not distinguishable from noise** — the {conf_pct}% CI includes 0 "
            f"(sign test p={p:.3f}). Add seeds (see the power curve) before claiming an effect."
        )
    elif result["verdict"] == "suggestive":
        lines.append(
            f"> Verdict: **suggestive but unconfirmed** — the {conf_pct}% CI excludes 0, but "
            f"the sign test is not significant (p={p:.3f} ≥ {alpha}) and power is {power_str}. "
            "The percentile bootstrap is optimistic on small, skewed samples; treat this as a "
            "lead and add seeds (see the power curve) until the sign test agrees."
        )
    else:
        direction = "improvement" if result["mean_delta"] > 0 else "regression"
        lines.append(
            f"> Verdict: **credible {direction}** — the {conf_pct}% CI excludes 0 *and* the "
            f"sign test is significant (p={p:.3f} < {alpha})."
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
                        pool_sizes=pool_sizes, extra_fields={"repeat": k},
                    )
                )
    return cells


def analyze_repeats(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-arm variance decomposition from repeat cells (pure).

    Splits total lives_saved variance into within-seed (LLM sampling) and
    between-seed (world) components via a one-way random-effects model.
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
        s = result[arm]
        lines.append(
            f"| {arm} | {s['n_seeds']} | {s['repeats']} | {s['grand_mean']:.2f} "
            f"| {s['sd_within']:.2f} | {s['sd_between']:.2f} | {s['sd_total']:.2f} "
            f"| {s['icc']:.3f} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"
