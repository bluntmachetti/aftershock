"""Tests for town.diagnostics (M5 free diagnostics).

Records are crafted via the real protocol models + canonical_json so they load
through the same load_run path the checker uses — exercising priority-inversion
detection, latency bucketing, and the scripted-anchor calibration.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from aftershock.kernel.protocol import (
    AgentResponse,
    Decision,
    Proposal,
    ProposalKind,
    ProposalRuling,
    TickRecord,
)
from aftershock.kernel.recorder import canonical_json
from aftershock.town.diagnostics import (
    classify_auction_losses,
    conformance_calibration,
    pipeline_latency,
)


def _rr(proposal_id: str, sender: str, mission_id: str, resource: str = "ambulance",
        qty: int = 1) -> Proposal:
    return Proposal(
        proposal_id=proposal_id, sender=sender, recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": mission_id, "resource": resource, "qty": qty, "urgency": 5},
    )


def _ruling(pid: str, accepted: bool, reason: str = "") -> ProposalRuling:
    return ProposalRuling(
        proposal_id=pid, accepted=accepted, decided_by="kernel:auction", reason=reason
    )


def _grant(pid: str, mission_id: str, resource: str = "ambulance", qty: int = 1) -> Decision:
    """An accepted auction dispatch grant, exactly as TownResolver issues it."""
    return Decision(
        decision_id=f"{pid}-grant", agent_id="medical", decision_type="dispatch",
        params={"mission_id": mission_id, "resource": resource, "qty": qty},
    )


# Real resolver reason strings (town/society.py) for the two pool-exhausted forms.
def _shortage(resource: str = "ambulance", avail: int = 0, need: int = 1) -> str:
    return f"pool exhausted: {resource} has {avail} available, need {need}"


def _record(tick: int, *, proposals: list[Proposal] | None = None,
            rulings: list[ProposalRuling] | None = None,
            accepted: list[Decision] | None = None,
            scores: dict[str, float] | None = None) -> TickRecord:
    resp = AgentResponse(agent_id="medical", proposals=tuple(proposals or ()))
    return TickRecord(
        tick=tick,
        observation_digests={},
        responses=(resp,),
        rulings=tuple(rulings or ()),
        accepted=tuple(accepted or ()),
        rejected=(),
        events=(),
        scores=scores or {},
        world_digest="x",
    )


def _mission(mid: str, *, priority: int, status: str = "open",
             assigned: dict[str, int] | None = None,
             required: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "id": mid, "kind": "medical_surge", "district_id": "d1", "severity": 2,
        "lives_at_risk": 10, "spawned_tick": 0, "deadline_tick": 12,
        "required": required or {"ambulance": 1}, "assigned": assigned or {},
        "progress": 0.0, "status": status, "priority": priority,
        "resolved_tick": None, "spread_applied": False,
    }


def _write_run(tmp: Path, records: list[TickRecord],
               worlds: list[tuple[int, dict[str, Any]]] | None,
               manifest: dict[str, Any]) -> Path:
    run_dir = tmp / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(canonical_json(manifest), encoding="utf-8")
    with (run_dir / "ticks.ndjson").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(canonical_json(r) + "\n")
    if worlds is not None:
        with (run_dir / "world.ndjson").open("w", encoding="utf-8") as f:
            for t, state in worlds:
                f.write(canonical_json({"tick": t, "state": state}) + "\n")
    return run_dir


# ---------------------------------------------------------------------------
# classify_auction_losses
# ---------------------------------------------------------------------------


def test_priority_inversion_detected() -> None:
    """The real S2 pathology: a high-priority bid loses (via the *shortage* reason,
    no winner named) while a lower-priority mission wins the pool that tick."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # world[0]: m_high prio 8, m_low prio 2 (state the tick-1 auction observed)
        world0 = {"missions": {
            "m_high": _mission("m_high", priority=8),
            "m_low": _mission("m_low", priority=2),
        }}
        records = [
            _record(0),
            _record(
                1,
                proposals=[_rr("p_high", "medical", "m_high"),
                           _rr("p_low", "medical", "m_low")],
                # m_low WON the pool (accepted grant); m_high lost with the bare
                # shortage reason — exactly how TownResolver emits an inversion.
                accepted=[_grant("p_low", "m_low")],
                rulings=[
                    _ruling("p_low", True),
                    _ruling("p_high", False, _shortage()),
                ],
            ),
        ]
        run_dir = _write_run(tmp, records, [(0, world0), (1, world0)],
                             {"arm": "society", "seed": 1})
        report = classify_auction_losses(run_dir)

    assert report["categories"]["priority_inversion"] == 1
    assert report["categories"]["pure_shortage"] == 0  # not mislabeled as shortage
    assert report["categories"]["displacement"] == 0
    assert report["losses"] == 1
    assert report["accepted"] == 1
    assert report["by_resource"]["ambulance"]["priority_inversion"] == 1


def test_displacement_when_loser_lower_priority() -> None:
    """Loser priority <= winner priority is legitimate displacement, not inversion."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        world0 = {"missions": {
            "m_a": _mission("m_a", priority=2),
            "m_b": _mission("m_b", priority=5),
        }}
        records = [
            _record(0),
            _record(
                1,
                proposals=[_rr("p_a", "medical", "m_a"), _rr("p_b", "medical", "m_b")],
                accepted=[_grant("p_b", "m_b")],  # higher-priority m_b won
                rulings=[_ruling("p_b", True), _ruling("p_a", False, _shortage())],
            ),
        ]
        run_dir = _write_run(tmp, records, [(0, world0), (1, world0)],
                             {"arm": "society", "seed": 1})
        report = classify_auction_losses(run_dir)

    assert report["categories"]["displacement"] == 1
    assert report["categories"]["priority_inversion"] == 0


def test_pure_shortage_when_no_winner_that_tick() -> None:
    """A pool-exhausted loss with NO contemporaneous grant = the pool was empty."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        records = [
            _record(
                0,
                proposals=[_rr("p1", "medical", "m1")],
                rulings=[
                    _ruling("p1", False, _shortage()),
                    _ruling("p2", False, "some unexpected reason text"),
                ],
            ),
        ]
        run_dir = _write_run(tmp, records, [(0, {"missions": {}})],
                             {"arm": "society", "seed": 1})
        report = classify_auction_losses(run_dir)

    assert report["categories"]["pure_shortage"] == 1
    assert report["categories"]["priority_inversion"] == 0
    assert report["categories"]["unparsed"] == 1  # never silently dropped
    assert report["examples"]["unparsed"][0]["detail"] == "some unexpected reason text"


def test_redundant_resource_key_unquoted() -> None:
    """society.py emits the redundant reason with {resource!r} (quoted); the
    by_resource key must still be the unquoted resource name."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        records = [
            _record(
                0,
                rulings=[
                    # Exact society.py string: mission {id!r} already has sufficient {res!r}
                    _ruling("p1", False, "mission 'm1' already has sufficient 'ambulance'"),
                    _ruling("p2", False, "unknown resource 'gremlin'"),
                ],
            ),
        ]
        run_dir = _write_run(tmp, records, [(0, {"missions": {}})],
                             {"arm": "society", "seed": 1})
        report = classify_auction_losses(run_dir)

    assert report["categories"]["redundant"] == 1
    assert report["categories"]["unknown_resource"] == 1
    # Key is the unquoted resource, aggregating with the other categories.
    assert "ambulance" in report["by_resource"]
    assert "'ambulance'" not in report["by_resource"]
    assert report["by_resource"]["ambulance"]["redundant"] == 1


def test_no_world_folds_inversion_into_displacement() -> None:
    """Without world.ndjson priorities are unknown -> displacement (not inversion)."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        records = [
            _record(
                1,
                proposals=[_rr("p_high", "medical", "m_high"),
                           _rr("p_low", "medical", "m_low")],
                accepted=[_grant("p_low", "m_low")],
                rulings=[_ruling("p_low", True), _ruling("p_high", False, _shortage())],
            ),
        ]
        run_dir = _write_run(tmp, records, None, {"arm": "society", "seed": 1})
        report = classify_auction_losses(run_dir)

    assert report["has_world"] is False
    assert report["categories"]["displacement"] == 1
    assert report["categories"]["priority_inversion"] == 0


# ---------------------------------------------------------------------------
# pipeline_latency
# ---------------------------------------------------------------------------


def test_latency_resolved_mission_gaps() -> None:
    """Mission spawns t0, requested t1, arrives t1, resolves t3."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        worlds = [
            (0, {"missions": {"m1": _mission("m1", priority=4)}}),
            (1, {"missions": {"m1": _mission("m1", priority=4,
                                             assigned={"ambulance": 1})}}),
            (2, {"missions": {"m1": _mission("m1", priority=4,
                                             assigned={"ambulance": 1})}}),
            (3, {"missions": {"m1": _mission("m1", priority=4, status="resolved",
                                             assigned={"ambulance": 1})}}),
        ]
        records = [
            _record(0),
            _record(1, proposals=[_rr("p1", "medical", "m1")]),
            _record(2),
            _record(3),
        ]
        run_dir = _write_run(tmp, records, worlds, {"arm": "society", "seed": 1})
        report = pipeline_latency(run_dir)

    res = report["by_outcome"]["resolved"]
    assert res["n_missions"] == 1
    assert res["ask"]["mean"] == 1.0  # req(1) - spawn(0)
    assert res["deliver"]["mean"] == 0.0  # arrival(1) - req(1)
    assert res["resolve"]["mean"] == 3.0  # end(3) - spawn(0)


def test_latency_failed_no_arrival_noted() -> None:
    """A failed mission that never received a resource is flagged as starvation."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        worlds = [
            (0, {"missions": {"m1": _mission("m1", priority=4)}}),
            (1, {"missions": {"m1": _mission("m1", priority=4, status="failed")}}),
        ]
        records = [_record(0), _record(1)]
        run_dir = _write_run(tmp, records, worlds, {"arm": "society", "seed": 1})
        report = pipeline_latency(run_dir)

    assert report["by_outcome"]["failed"]["n_missions"] == 1
    assert any("never received any resource" in n for n in report["notes"])


def test_latency_no_world_returns_empty() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        run_dir = _write_run(tmp, [_record(0)], None, {"arm": "society", "seed": 1})
        report = pipeline_latency(run_dir)
    assert report["missions"] == 0
    assert any("absent" in n for n in report["notes"])


# ---------------------------------------------------------------------------
# conformance_calibration (real scripted run via run_bench)
# ---------------------------------------------------------------------------


def test_calibration_scripted_anchor_passes() -> None:
    """A real scripted run must read team_alignment ~1.0 (the anchor check)."""
    from aftershock.bench import run_bench

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        run_bench({"ticks": 8, "seeds": [42], "arms": ["scripted"]},
                  provider=None, out_dir=out_dir)
        report = conformance_calibration([out_dir / "scripted-seed42"])

    assert report["scripted_anchor"]["present"] is True
    assert report["scripted_anchor"]["all_ok"] is True
    assert report["scripted_anchor"]["min_team_alignment"] >= 0.999
    assert report["warnings"] == []
