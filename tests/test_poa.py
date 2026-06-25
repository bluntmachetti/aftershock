"""Tests for the price-of-anarchy ruler (town/poa.py).

The metric rests on one exact identity — every imperiled life is saved, lost, or still-open —
so the tests pin that accounting, the [0,1] bound, the within-batch pairing, and that the
committed 4-arm batch shows coordinated arms (society) above uncoordinated (swarm).
"""

from __future__ import annotations

import json
from pathlib import Path

from aftershock.town import poa


def _state(saved: int, lost: int, open_missions: list[int]) -> dict:
    """A world-state dict with `open_missions` open missions of the given lives_at_risk."""
    missions = {
        f"m{i}": {"status": "open", "lives_at_risk": v} for i, v in enumerate(open_missions)
    }
    # A couple of terminal missions (their lives are already folded into saved/lost).
    missions["mr"] = {"status": "resolved", "lives_at_risk": 0}
    missions["mf"] = {"status": "failed", "lives_at_risk": 0}
    return {"lives_saved": saved, "lives_lost": lost, "missions": missions}


def _write_run(
    batch: Path, arm: str, seed: int, saved: int, lost: int, open_lives: list[int]
) -> None:
    run = batch / f"{arm}-seed{seed}"
    run.mkdir(parents=True, exist_ok=True)
    rec = {"tick": 1, "state": _state(saved, lost, open_lives)}
    (run / "world.ndjson").write_text(json.dumps({"tick": 0, "state": _state(0, 0, [])}) + "\n"
                                      + json.dumps(rec) + "\n", encoding="utf-8")
    (run / "run.json").write_text(json.dumps({"arm": arm, "seed": seed}), encoding="utf-8")


def test_at_risk_breakdown_is_the_exact_identity() -> None:
    b = poa.at_risk_breakdown(_state(saved=30, lost=20, open_missions=[5, 5]))
    assert b == {"lives_saved": 30, "lives_lost": 20, "open_remaining": 10, "total_at_risk": 60}


def test_efficiency_bounds() -> None:
    assert poa.efficiency(_state(60, 0, [])) == 1.0           # everyone saved -> ceiling
    assert poa.efficiency(_state(0, 60, [])) == 0.0           # everyone lost
    assert poa.efficiency(_state(0, 0, [])) == 0.0            # nothing at risk -> 0, no div-by-zero
    assert abs(poa.efficiency(_state(30, 20, [10])) - 0.5) < 1e-9


def test_parse_arm_seed_handles_hyphenated_arms() -> None:
    assert poa._parse_arm_seed("society-seed42") == ("society", 42)
    assert poa._parse_arm_seed("society-nodoctrine-seed11") == ("society-nodoctrine", 11)
    assert poa._parse_arm_seed("nope") == ("nope", None)


def test_run_and_batch_efficiency(tmp_path: Path) -> None:
    batch = tmp_path / "batch"
    _write_run(batch, "society", 42, saved=70, lost=20, open_lives=[10])  # 70/100 = 0.70
    _write_run(batch, "swarm", 42, saved=50, lost=40, open_lives=[10])    # 50/100 = 0.50
    cells = poa.batch_cells(batch)
    assert abs(cells[("society", 42)]["efficiency"] - 0.70) < 1e-9
    assert abs(cells[("swarm", 42)]["efficiency"] - 0.50) < 1e-9
    means = poa.arm_means(cells)
    assert abs(means["society"]["mean_efficiency"] - 0.70) < 1e-9


def test_paired_verdict_pairs_within_batch(tmp_path: Path) -> None:
    b1, b2 = tmp_path / "b1", tmp_path / "b2"
    for seed in (11, 23):
        _write_run(b1, "society", seed, saved=70, lost=30, open_lives=[])  # 0.70
        _write_run(b1, "swarm", seed, saved=55, lost=45, open_lives=[])    # 0.55
    for seed in (60, 61):
        _write_run(b2, "society", seed, saved=66, lost=34, open_lives=[])  # 0.66
        _write_run(b2, "swarm", seed, saved=60, lost=40, open_lives=[])    # 0.60
    v = poa.paired_efficiency_verdict([b1, b2], control="swarm", treatment="society")
    assert v is not None
    assert v["n"] == 4                       # 2 seeds x 2 batches
    assert v["n_positive"] == 4              # society > swarm every pair
    assert v["mean_delta"] > 0
    assert v["poa_ratio"] > 1.0
    assert v["verdict"] in {"credible", "suggestive", "noise"}


def test_paired_verdict_none_without_pairs(tmp_path: Path) -> None:
    batch = tmp_path / "solo_only"
    _write_run(batch, "society", 42, saved=70, lost=30, open_lives=[])
    assert poa.paired_efficiency_verdict([batch], control="swarm", treatment="society") is None


def test_committed_batch_shows_coordination_gap() -> None:
    """Integration guard over the committed canonical batch: society (coordinated) outsaves
    swarm (uncoordinated) as a fraction of imperiled lives. Tolerant to data regeneration."""
    batch = Path("bench/results/2026-06-22-4arm-refresh")
    if not batch.is_dir():
        return  # batch not present in this checkout — skip silently
    means = poa.arm_means(poa.batch_cells(batch))
    if "society" not in means or "swarm" not in means:
        return
    for arm, m in means.items():
        assert 0.0 <= m["mean_efficiency"] <= 1.0, arm
    assert means["society"]["mean_efficiency"] > means["swarm"]["mean_efficiency"]
