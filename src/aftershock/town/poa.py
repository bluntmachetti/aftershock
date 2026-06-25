"""Price-of-anarchy ruler — the fraction of imperiled lives each arm saves.

This operationalizes the "society beats swarm" hypothesis as a bounded *efficiency* metric
grounded in the sim's own exact life accounting, rather than a raw lives count. By
construction every life that becomes at-risk is eventually saved, lost, or still-open, so:

    total_at_risk = lives_saved + lives_lost + open_remaining        (an exact identity)
    efficiency    = lives_saved / total_at_risk                      (in [0, 1])

The uncoordinated arms (swarm, solo) sit at a lower efficiency than the coordinated ones
(society + the scripted central heuristic); that gap is the price of anarchy — the welfare
a protocol-free resource scramble leaves on the table.

Honesty bounds (read before quoting a number):
  * The denominator is the **rigorous save-everyone ceiling** (efficiency = 1.0 means every
    imperiled life saved). It is NOT a tight *achievable* optimum: the true optimum is a
    multi-tick resource-scheduling problem over the deterministic world and is intractable
    to compute exactly, so we deliberately do not claim "fraction of optimal." We report
    absolute efficiency and the paired society-vs-swarm gap, judged by the same bootstrap-CI
    + sign-test verdict the benchmark uses (FIELD-NOTES §16-17).
  * ``total_at_risk`` is a per-run quantity (it depends on which missions had spawned by the
    time the run ended); we therefore pair society vs swarm *within a batch* (same code, seed,
    tick budget) and never mix arms across code versions.

Pure analysis over recorded runs: deterministic, no network, no DASHSCOPE spend.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aftershock import stats

# Fixed bootstrap seed so the reported CI is byte-stable across re-runs (matches bench.py).
_PAIRED_BOOTSTRAP_SEED = 0xA17E5
_ALPHA = 0.05


def at_risk_breakdown(state: dict[str, Any]) -> dict[str, int]:
    """Exact life accounting for a final world-state dict.

    ``total_at_risk`` is the identity ``lives_saved + lives_lost + open_remaining`` — every
    spawned life is in exactly one of those buckets, so this is the true denominator for the
    fraction-saved efficiency (no modelling assumptions).
    """
    saved = int(state.get("lives_saved", 0))
    lost = int(state.get("lives_lost", 0))
    missions = state.get("missions", {})
    open_remaining = sum(
        int(m.get("lives_at_risk", 0))
        for m in missions.values()
        if m.get("status") == "open"
    )
    total = saved + lost + open_remaining
    return {
        "lives_saved": saved,
        "lives_lost": lost,
        "open_remaining": open_remaining,
        "total_at_risk": total,
    }


def efficiency(state: dict[str, Any]) -> float:
    """Fraction of imperiled lives saved, in [0, 1]. 0 when nothing was ever at risk."""
    b = at_risk_breakdown(state)
    total = b["total_at_risk"]
    return b["lives_saved"] / total if total > 0 else 0.0


def _last_world_state(run_dir: Path) -> dict[str, Any] | None:
    """Return the final world-state dict from a run's world.ndjson (None if absent)."""
    world_path = run_dir / "world.ndjson"
    if not world_path.exists():
        return None
    last: str | None = None
    with world_path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                last = line
    if last is None:
        return None
    try:
        rec = json.loads(last)
    except json.JSONDecodeError:
        return None
    # Records are stored as {tick, state} — unwrap to the flat WorldState.
    return rec.get("state", rec) if isinstance(rec, dict) else None


def run_efficiency(run_dir: Path) -> dict[str, Any] | None:
    """Efficiency + breakdown for one ``{arm}-seed{N}`` run dir (None if no world record)."""
    state = _last_world_state(run_dir)
    if state is None:
        return None
    b = at_risk_breakdown(state)
    arm, seed = _parse_arm_seed(run_dir.name)
    return {
        "run_id": run_dir.name,
        "arm": arm,
        "seed": seed,
        "efficiency": (b["lives_saved"] / b["total_at_risk"]) if b["total_at_risk"] else 0.0,
        **b,
    }


def _parse_arm_seed(name: str) -> tuple[str, int | None]:
    """``society-nodoctrine-seed42`` -> ("society-nodoctrine", 42). Arm may contain hyphens."""
    if "-seed" not in name:
        return name, None
    arm, _, seed_str = name.rpartition("-seed")
    try:
        return arm, int(seed_str)
    except ValueError:
        return arm, None


def batch_cells(batch_dir: Path) -> dict[tuple[str, int], dict[str, Any]]:
    """Map (arm, seed) -> efficiency cell for every recorded run in a bench batch dir."""
    cells: dict[tuple[str, int], dict[str, Any]] = {}
    if not batch_dir.is_dir():
        return cells
    for child in sorted(batch_dir.iterdir()):
        if not child.is_dir() or "-seed" not in child.name:
            continue
        cell = run_efficiency(child)
        if cell is None or cell["seed"] is None:
            continue
        cells[(cell["arm"], cell["seed"])] = cell
    return cells


def arm_means(cells: dict[tuple[str, int], dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-arm mean efficiency over the cells in one batch (so code/tick-budget is uniform)."""
    by_arm: dict[str, list[dict[str, Any]]] = {}
    for (arm, _seed), cell in cells.items():
        by_arm.setdefault(arm, []).append(cell)
    out: dict[str, dict[str, Any]] = {}
    for arm, arm_cells in by_arm.items():
        effs = [c["efficiency"] for c in arm_cells]
        out[arm] = {
            "mean_efficiency": stats.mean(effs),
            "n": len(effs),
            "seeds": sorted(c["seed"] for c in arm_cells),
            "mean_lives_saved": stats.mean([c["lives_saved"] for c in arm_cells]),
            "mean_total_at_risk": stats.mean([c["total_at_risk"] for c in arm_cells]),
        }
    return out


def discover_batches(results_root: Path) -> list[Path]:
    """Bench batch dirs that contain at least one ``{arm}-seed{N}`` run with a world record."""
    out: list[Path] = []
    if not results_root.is_dir():
        return out
    for child in sorted(results_root.iterdir()):
        if child.is_dir() and batch_cells(child):
            out.append(child)
    return out


def format_report(
    results_root: Path,
    control: str = "swarm",
    treatment: str = "society",
) -> str:
    """Human-readable price-of-anarchy report over every batch with recorded runs."""
    batches = discover_batches(results_root)
    lines: list[str] = []
    lines.append("PRICE OF ANARCHY — fraction of imperiled lives saved")
    lines.append("(efficiency = lives_saved / total_at_risk; total = saved+lost+open)")
    lines.append("")

    # Full arm table from the richest batch (most distinct arms), so the 4-arm read is uniform.
    richest = max(
        batches,
        key=lambda b: len({a for (a, _s) in batch_cells(b)}),
        default=None,
    )
    if richest is not None:
        means = arm_means(batch_cells(richest))
        lines.append(f"Per-arm efficiency  [{richest.name}, n={next(iter(means.values()))['n']}]")
        for arm in sorted(means, key=lambda a: -means[a]["mean_efficiency"]):
            m = means[arm]
            lines.append(
                f"  {arm:<20} {100 * m['mean_efficiency']:>5.1f}%   "
                f"(saved {m['mean_lives_saved']:.1f} / at-risk {m['mean_total_at_risk']:.1f})"
            )
        lines.append("")

    v = paired_efficiency_verdict(batches, control=control, treatment=treatment)
    if v is not None:
        lines.append(f"{treatment} vs {control}  (paired within-batch, pooled n={v['n']})")
        lines.append(
            f"  efficiency: {100 * v['mean_treatment_efficiency']:.1f}% vs "
            f"{100 * v['mean_control_efficiency']:.1f}%  "
            f"(price of anarchy {v['poa_ratio']:.2f}x)"
        )
        lines.append(
            f"  mean delta {100 * v['mean_delta']:+.1f} pts | "
            f"wins {v['n_positive']}/{v['n']} | "
            f"CI [{100 * v['ci']['lower']:+.1f}, {100 * v['ci']['upper']:+.1f}] pts | "
            f"sign-test p={v['sign_test_p']:.3f}"
        )
        lines.append(f"  VERDICT: {v['verdict']}")
    else:
        lines.append(f"(no paired {treatment}/{control} runs with world records found)")
    return "\n".join(lines)


def paired_efficiency_verdict(
    batch_dirs: list[Path],
    control: str = "swarm",
    treatment: str = "society",
    alpha: float = _ALPHA,
) -> dict[str, Any] | None:
    """Pool paired (treatment - control) efficiency deltas *within* each batch and judge them.

    Pairs are formed per (batch, seed) where both arms ran, so each delta compares same-code,
    same-world runs. Returns the same verdict shape the bench uses (credible/suggestive/noise),
    or None if no paired seeds exist.
    """
    diffs: list[float] = []
    pairs: list[dict[str, Any]] = []
    for batch_dir in batch_dirs:
        cells = batch_cells(batch_dir)
        seeds = sorted(
            {s for (a, s) in cells if a == control} & {s for (a, s) in cells if a == treatment}
        )
        for seed in seeds:
            t = cells[(treatment, seed)]["efficiency"]
            c = cells[(control, seed)]["efficiency"]
            diffs.append(t - c)
            pairs.append({
                "batch": batch_dir.name,
                "seed": seed,
                f"{treatment}_eff": t,
                f"{control}_eff": c,
                "delta": t - c,
            })
    if not diffs:
        return None
    n = len(diffs)
    mean_delta = stats.mean(diffs)
    sd_delta = stats.sample_sd(diffs)
    mean_treatment = stats.mean([p[f"{treatment}_eff"] for p in pairs])
    mean_control = stats.mean([p[f"{control}_eff"] for p in pairs])
    ci = stats.bootstrap_ci(diffs, confidence=1.0 - alpha, rng_seed=_PAIRED_BOOTSTRAP_SEED)
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
        "treatment": treatment,
        "control": control,
        "n": n,
        "mean_delta": mean_delta,
        "sd_delta": sd_delta,
        "mean_treatment_efficiency": mean_treatment,
        "mean_control_efficiency": mean_control,
        # Price of anarchy: how much more of the saveable lives the coordinated arm captures.
        "poa_ratio": (mean_treatment / mean_control) if mean_control > 0 else None,
        "n_positive": sum(1 for d in diffs if d > 0),
        "n_negative": sum(1 for d in diffs if d < 0),
        "n_tied": sum(1 for d in diffs if d == 0),
        "sign_test_p": sign_p,
        "ci": {"lower": ci.lower, "upper": ci.upper, "confidence": ci.confidence},
        "ci_excludes_zero": ci_excludes_zero,
        "sign_significant": sign_significant,
        "verdict": verdict,
        "pairs": pairs,
    }
