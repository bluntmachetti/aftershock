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

from aftershock.kernel.engine import Engine
from aftershock.kernel.recorder import Recorder
from aftershock.town.arms import build_arm


def _cell_dir(out_dir: Path, arm: str, seed: int) -> Path:
    """Canonical per-cell directory name."""
    return out_dir / f"{arm}-seed{seed}"


def run_bench(
    manifest: dict[str, Any],
    provider: Any | None,
    out_dir: Path,
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
            setup = build_arm(arm, seed, provider)
            run_id = f"{arm}-seed{seed}"
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

            # time.monotonic() is used ONLY for wall_s — it never feeds simulation
            # state, so Invariant 1 (determinism) is preserved.
            t0 = time.monotonic()
            summary_run = asyncio.run(engine.run())
            wall_s = time.monotonic() - t0

            # Collect model names from cost breakdown
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

            summary_path.write_text(
                json.dumps(cell_summary, indent=2, sort_keys=True),
                encoding="utf-8",
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
    )
    sep = (
        "|---|---|---|---|---|---|---|---|---|---|---|"
    )
    lines.append(header)
    lines.append(sep)

    for arm in sorted_arms:
        s = arm_stats[arm]
        lpd = f"{s['lives_per_dollar']:.4f}" if "lives_per_dollar" in s else "—"
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
            f"| {lpd} |"
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
