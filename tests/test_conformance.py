"""Tests for the conformance engine.

(a) Per-rule unit tests: for EVERY rule id, a minimal synthetic run dir that
    triggers exactly one violation, and a clean variant that triggers zero.
(b) Reconstruction tests: inbox derivation from t-1 proposals, worlds[t-1]
    indexing, tick-0 exemption.
(c) THE CALIBRATION TEST: scripted runs (seeds 42 and 7, 60 ticks) must
    produce ZERO violations on every rule and team_alignment == 1.0.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from aftershock.kernel.engine import Engine
from aftershock.kernel.protocol import (
    AgentResponse,
    Decision,
    Proposal,
    ProposalKind,
    ProposalResponse,
    Rejection,
    TickRecord,
    WorldEvent,
)
from aftershock.kernel.recorder import Recorder
from aftershock.kernel.roles import load_roles
from aftershock.town.arms import build_arm
from aftershock.town.conformance import (
    _build_inbox,
    _staffing_ratio_world,
    check_run,
    render_markdown,
)
from aftershock.town.state import (
    Mission,
    MissionKind,
    MissionStatus,
    ResourcePool,
    TownState,
    new_town,
)

ROLES_DIR = Path(__file__).parent.parent / "src" / "aftershock" / "town" / "roles"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_pool(kind: str, total: int, available: int) -> ResourcePool:
    return ResourcePool(kind=kind, total=total, available=available)


def _make_mission(
    mid: str,
    kind: str = MissionKind.medical_surge,
    district_id: str = "old_town",
    severity: int = 2,
    lives: int = 10,
    spawned_tick: int = 0,
    deadline_tick: int = 20,
    required: dict | None = None,
    assigned: dict | None = None,
    priority: int = 4,
    status: str = MissionStatus.open,
) -> Mission:
    return Mission(
        id=mid,
        kind=kind,
        district_id=district_id,
        severity=severity,
        lives_at_risk=lives,
        spawned_tick=spawned_tick,
        deadline_tick=deadline_tick,
        required=required or {"ambulance": 1, "supply_truck": 1},
        assigned=assigned or {},
        progress=0.0,
        status=status,
        priority=priority,
    )


def _minimal_state(seed: int = 42) -> TownState:
    state = new_town(seed)
    state.timeline = []
    return state


def _make_tick_record(
    tick: int,
    responses: list[AgentResponse] | None = None,
    rulings: list | None = None,
    accepted: list[Decision] | None = None,
    rejected: list[Rejection] | None = None,
    events: list[WorldEvent] | None = None,
    scores: dict | None = None,
    world_digest: str = "aabbcc",
    observation_digests: dict | None = None,
) -> TickRecord:
    return TickRecord(
        tick=tick,
        observation_digests=observation_digests or {},
        responses=tuple(responses or []),
        rulings=tuple(rulings or []),
        accepted=tuple(accepted or []),
        rejected=tuple(rejected or []),
        events=tuple(events or []),
        scores=scores or {"panic": 0.0},
        world_digest=world_digest,
    )


def _agent_response(
    agent_id: str,
    decisions: list[Decision] | None = None,
    proposals: list[Proposal] | None = None,
    responses: list[ProposalResponse] | None = None,
) -> AgentResponse:
    return AgentResponse(
        agent_id=agent_id,
        decisions=tuple(decisions or []),
        proposals=tuple(proposals or []),
        responses=tuple(responses or []),
    )


def _write_run(
    tmp_path: Path,
    run_id: str,
    ticks: list[TickRecord],
    worlds: list[dict[str, Any]] | None = None,
    arm: str = "society",
    seed: int = 42,
) -> Path:
    """Write a minimal run directory for testing."""
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"run_id": run_id, "arm": arm, "seed": seed}
    (run_dir / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    with (run_dir / "ticks.ndjson").open("w", encoding="utf-8") as f:
        for r in ticks:
            f.write(r.model_dump_json() + "\n")
    if worlds is not None:
        with (run_dir / "world.ndjson").open("w", encoding="utf-8") as f:
            for entry in worlds:
                f.write(json.dumps(entry) + "\n")
    return run_dir


def _empty_world_state(tick: int = 0) -> dict[str, Any]:
    """Minimal valid world state dict."""
    return {
        "tick": tick,
        "seed": 42,
        "panic": 0.0,
        "lives_saved": 0,
        "lives_lost": 0,
        "next_mission_no": 1,
        "districts": {
            "old_town": {"id": "old_town", "name": "Old Town", "road_blocked": False},
        },
        "missions": {},
        "pools": {
            "ambulance": {"kind": "ambulance", "total": 4, "available": 4},
            "repair_crew": {"kind": "repair_crew", "total": 3, "available": 3},
        },
        "pending": [],
    }


def _world_with_mission(
    tick: int,
    mid: str,
    kind: str = MissionKind.medical_surge,
    priority: int = 4,
    severity: int = 2,
    deadline_tick: int = 20,
    required: dict | None = None,
    assigned: dict | None = None,
    status: str = "open",
    district_id: str = "old_town",
    road_blocked: bool = False,
) -> dict[str, Any]:
    w = _empty_world_state(tick)
    w["missions"][mid] = {
        "id": mid,
        "kind": kind,
        "district_id": district_id,
        "severity": severity,
        "lives_at_risk": 10,
        "spawned_tick": 0,
        "deadline_tick": deadline_tick,
        "required": required or {"ambulance": 1, "supply_truck": 1},
        "assigned": assigned or {},
        "progress": 0.0,
        "status": status,
        "priority": priority,
        "resolved_tick": None,
        "spread_applied": False,
    }
    w["districts"]["old_town"]["road_blocked"] = road_blocked
    return w


# ---------------------------------------------------------------------------
# (b) Reconstruction tests
# ---------------------------------------------------------------------------


def test_inbox_reconstruction_bilateral():
    """Proposals sent at t=0 to agent B land in B's inbox at t=1."""
    prop = Proposal(
        proposal_id="a-t0-p0",
        sender="medical",
        recipient="commander",
        kind=ProposalKind.ESCALATION,
        body={"mission_id": "m1"},
    )
    tick0 = _make_tick_record(
        0, responses=[_agent_response("medical", proposals=[prop])]
    )
    inbox = _build_inbox([tick0])
    assert "commander" in inbox.get(1, {})
    assert any(p["proposal_id"] == "a-t0-p0" for p in inbox[1]["commander"])


def test_inbox_reconstruction_broadcast():
    """INFO_SHARE sent at t=0 lands in every other agent's inbox at t=1."""
    prop = Proposal(
        proposal_id="comms-t0-p0",
        sender="comms",
        recipient=None,
        kind=ProposalKind.INFO_SHARE,
        body={"message": "all clear"},
    )
    tick0 = _make_tick_record(
        0,
        responses=[
            _agent_response("comms", proposals=[prop]),
            _agent_response("medical"),
            _agent_response("rescue"),
        ],
    )
    inbox = _build_inbox([tick0])
    # Everyone except comms should have it at t=1
    for agent_id in ["medical", "rescue"]:
        assert any(
            p["proposal_id"] == "comms-t0-p0" for p in inbox.get(1, {}).get(agent_id, [])
        ), f"{agent_id} should have broadcast in inbox"
    # Sender should NOT receive their own broadcast
    assert not any(
        p["proposal_id"] == "comms-t0-p0" for p in inbox.get(1, {}).get("comms", [])
    )


def test_tick_0_exemption_no_world(tmp_path: Path):
    """At tick 0 with no world state, state-dependent rules have applicable=0."""
    tick0 = _make_tick_record(0, responses=[_agent_response("medical")])
    run_dir = _write_run(tmp_path, "t0-exempt", [tick0], worlds=None)
    report = check_run(run_dir)
    # State-dependent rules should have no applicable entries for tick 0
    for rule_id in ["T2", "T3", "T6", "M1", "M2", "R1", "R2", "F1", "F2", "I2"]:
        agent_data = report["rules"][rule_id]
        for agent_id, data in agent_data.items():
            assert data["applicable"] == 0, (
                f"Rule {rule_id} agent {agent_id} should have 0 applicable at tick 0 "
                f"without world data"
            )


def test_worlds_t_minus_1_indexing(tmp_path: Path):
    """worlds[t-1] is used for state-dependent checks at tick t."""
    # At t=1 with T2 check: agent requests 3 ambulances for m1 which only needs 1
    prop = Proposal(
        proposal_id="medical-t1-p0",
        sender="medical",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "ambulance", "qty": 3, "urgency": 5},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("medical")])
    tick1 = _make_tick_record(1, responses=[_agent_response("medical", proposals=[prop])])

    # world at t=0 (what agent sees at t=1) has m1 requiring 1 ambulance, assigned 0
    w0 = _world_with_mission(0, "m1", required={"ambulance": 1}, assigned={})
    w1 = _world_with_mission(1, "m1", required={"ambulance": 1}, assigned={})
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": w1}]

    run_dir = _write_run(tmp_path, "t-minus-1", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    # T2 violation: requested 3, max is 1
    t2 = report["rules"]["T2"].get("medical", {})
    assert t2.get("applicable", 0) > 0
    assert len(t2.get("violations", [])) > 0


# ---------------------------------------------------------------------------
# (a) Per-rule unit tests — violations
# ---------------------------------------------------------------------------


def test_T1_violation_direct_dispatch(tmp_path: Path):
    """T1: agent-emitted dispatch decision is a violation."""
    dec = Decision(
        decision_id="medical-0",
        agent_id="medical",
        decision_type="dispatch",
        params={"mission_id": "m1", "resource": "ambulance", "qty": 1},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("medical", decisions=[dec])])
    run_dir = _write_run(tmp_path, "t1-viol", [tick0])
    report = check_run(run_dir)
    t1 = report["rules"]["T1"].get("medical", {})
    assert len(t1.get("violations", [])) >= 1


def test_T1_clean_no_dispatch(tmp_path: Path):
    """T1: no dispatch emitted -> no violation."""
    dec = Decision(
        decision_id="medical-0",
        agent_id="medical",
        decision_type="broadcast",
        params={"message": "stay calm"},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("medical", decisions=[dec])])
    run_dir = _write_run(tmp_path, "t1-clean", [tick0])
    report = check_run(run_dir)
    t1 = report["rules"]["T1"].get("medical", {})
    assert len(t1.get("violations", [])) == 0


def test_T1_kernel_grant_not_counted(tmp_path: Path):
    """T1: kernel-granted dispatch (decision_id ending in '-grant') is not a violation."""
    dec = Decision(
        decision_id="medical-t1-p0-grant",
        agent_id="medical",
        decision_type="dispatch",
        params={"mission_id": "m1", "resource": "ambulance", "qty": 1},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("medical", decisions=[dec])])
    run_dir = _write_run(tmp_path, "t1-grant", [tick0])
    report = check_run(run_dir)
    t1 = report["rules"]["T1"].get("medical", {})
    assert len(t1.get("violations", [])) == 0


def test_T2_violation_over_request(tmp_path: Path):
    """T2: requesting more than needed is a violation."""
    prop = Proposal(
        proposal_id="medical-t1-p0",
        sender="medical",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "ambulance", "qty": 5, "urgency": 3},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("medical")])
    tick1 = _make_tick_record(1, responses=[_agent_response("medical", proposals=[prop])])
    w0 = _world_with_mission(0, "m1", required={"ambulance": 1}, assigned={})
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": _empty_world_state(1)}]
    run_dir = _write_run(tmp_path, "t2-viol", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    t2 = report["rules"]["T2"].get("medical", {})
    assert len(t2.get("violations", [])) >= 1


def test_T2_clean_exact_request(tmp_path: Path):
    """T2: requesting exactly what is needed is not a violation."""
    prop = Proposal(
        proposal_id="medical-t1-p0",
        sender="medical",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "ambulance", "qty": 1, "urgency": 3},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("medical")])
    tick1 = _make_tick_record(1, responses=[_agent_response("medical", proposals=[prop])])
    w0 = _world_with_mission(0, "m1", required={"ambulance": 1}, assigned={})
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": _empty_world_state(1)}]
    run_dir = _write_run(tmp_path, "t2-clean", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    t2 = report["rules"]["T2"].get("medical", {})
    assert len(t2.get("violations", [])) == 0


def test_T3_violation_false_urgency(tmp_path: Path):
    """T3: urgency > 8 while severity < 4 and deadline > 4 is a violation."""
    prop = Proposal(
        proposal_id="medical-t1-p0",
        sender="medical",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "ambulance", "qty": 1, "urgency": 9},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("medical")])
    tick1 = _make_tick_record(1, responses=[_agent_response("medical", proposals=[prop])])
    # severity=2 (< 4), deadline_tick=20 so deadline_in=19 (> 4)
    w0 = _world_with_mission(0, "m1", severity=2, deadline_tick=20,
                             required={"ambulance": 1}, assigned={})
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": _empty_world_state(1)}]
    run_dir = _write_run(tmp_path, "t3-viol", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    t3 = report["rules"]["T3"].get("medical", {})
    assert len(t3.get("violations", [])) >= 1


def test_T3_clean_honest_urgency(tmp_path: Path):
    """T3: urgency <= 8 is never a violation."""
    prop = Proposal(
        proposal_id="medical-t1-p0",
        sender="medical",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "ambulance", "qty": 1, "urgency": 8},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("medical")])
    tick1 = _make_tick_record(1, responses=[_agent_response("medical", proposals=[prop])])
    w0 = _world_with_mission(0, "m1", severity=2, deadline_tick=20,
                             required={"ambulance": 1}, assigned={})
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": _empty_world_state(1)}]
    run_dir = _write_run(tmp_path, "t3-clean", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    t3 = report["rules"]["T3"].get("medical", {})
    assert len(t3.get("violations", [])) == 0


def test_T3_clean_high_severity(tmp_path: Path):
    """T3: urgency=9 with severity=4 is not a violation."""
    prop = Proposal(
        proposal_id="medical-t1-p0",
        sender="medical",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "ambulance", "qty": 1, "urgency": 9},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("medical")])
    tick1 = _make_tick_record(1, responses=[_agent_response("medical", proposals=[prop])])
    w0 = _world_with_mission(0, "m1", severity=4, deadline_tick=20,
                             required={"ambulance": 1}, assigned={})
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": _empty_world_state(1)}]
    run_dir = _write_run(tmp_path, "t3-sev4", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    t3 = report["rules"]["T3"].get("medical", {})
    assert len(t3.get("violations", [])) == 0


def test_T4_violation_no_response_to_resource_request(tmp_path: Path):
    """T4: resource_request in inbox with no response is a violation."""
    # Send a resource request at t=0 to medical; medical does not respond at t=1
    prop = Proposal(
        proposal_id="rescue-t0-p0",
        sender="rescue",
        recipient="medical",
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "ambulance", "qty": 1},
    )
    tick0 = _make_tick_record(
        0,
        responses=[
            _agent_response("rescue", proposals=[prop]),
            _agent_response("medical"),
        ],
    )
    tick1 = _make_tick_record(
        1,
        responses=[
            _agent_response("rescue"),
            _agent_response("medical"),  # No response to rescue's proposal
        ],
    )
    run_dir = _write_run(tmp_path, "t4-viol", [tick0, tick1])
    report = check_run(run_dir)
    t4 = report["rules"]["T4"].get("medical", {})
    assert len(t4.get("violations", [])) >= 1


def test_T4_clean_response_given(tmp_path: Path):
    """T4: responding to resource_request is not a violation."""
    prop = Proposal(
        proposal_id="rescue-t0-p0",
        sender="rescue",
        recipient="medical",
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "ambulance", "qty": 1},
    )
    resp = ProposalResponse(
        proposal_id="rescue-t0-p0",
        responder="medical",
        accept=True,
        note="ok",
    )
    tick0 = _make_tick_record(
        0,
        responses=[
            _agent_response("rescue", proposals=[prop]),
            _agent_response("medical"),
        ],
    )
    tick1 = _make_tick_record(
        1,
        responses=[
            _agent_response("rescue"),
            _agent_response("medical", responses=[resp]),
        ],
    )
    run_dir = _write_run(tmp_path, "t4-clean", [tick0, tick1])
    report = check_run(run_dir)
    t4 = report["rules"]["T4"].get("medical", {})
    assert len(t4.get("violations", [])) == 0


def test_T5_violation_resubmit_within_3_ticks(tmp_path: Path):
    """T5: resubmitting rejected (decision_type, params) within 3 ticks is a violation."""
    dec_params = {"mission_id": "m1", "priority": 5}
    dec0 = Decision(
        decision_id="commander-0",
        agent_id="commander",
        decision_type="set_priority",
        params=dec_params,
    )
    rej = Rejection(
        decision_id="commander-0",
        agent_id="commander",
        decision_type="set_priority",
        reason="mission not found",
    )
    tick0 = _make_tick_record(
        0,
        responses=[_agent_response("commander", decisions=[dec0])],
        rejected=[rej],
    )
    # Resubmit the same params at t=2 (within 3 ticks)
    dec2 = Decision(
        decision_id="commander-1",
        agent_id="commander",
        decision_type="set_priority",
        params=dec_params,
    )
    tick1 = _make_tick_record(1, responses=[_agent_response("commander")])
    tick2 = _make_tick_record(
        2,
        responses=[_agent_response("commander", decisions=[dec2])],
    )
    run_dir = _write_run(tmp_path, "t5-viol", [tick0, tick1, tick2])
    report = check_run(run_dir)
    t5 = report["rules"]["T5"].get("commander", {})
    assert len(t5.get("violations", [])) >= 1


def test_T5_clean_resubmit_after_3_ticks(tmp_path: Path):
    """T5: resubmitting after > 3 ticks is not a violation."""
    dec_params = {"mission_id": "m1", "priority": 5}
    dec0 = Decision(
        decision_id="commander-0",
        agent_id="commander",
        decision_type="set_priority",
        params=dec_params,
    )
    rej = Rejection(
        decision_id="commander-0",
        agent_id="commander",
        decision_type="set_priority",
        reason="mission not found",
    )
    tick0 = _make_tick_record(
        0,
        responses=[_agent_response("commander", decisions=[dec0])],
        rejected=[rej],
    )
    # Resubmit at t=4 (4 > 3, so not a violation)
    dec4 = Decision(
        decision_id="commander-1",
        agent_id="commander",
        decision_type="set_priority",
        params=dec_params,
    )
    ticks = [tick0] + [
        _make_tick_record(i, responses=[_agent_response("commander")])
        for i in range(1, 4)
    ] + [
        _make_tick_record(4, responses=[_agent_response("commander", decisions=[dec4])])
    ]
    run_dir = _write_run(tmp_path, "t5-clean", ticks)
    report = check_run(run_dir)
    t5 = report["rules"]["T5"].get("commander", {})
    assert len(t5.get("violations", [])) == 0


def test_T6_violation_re_request_after_grant(tmp_path: Path):
    """T6: re-requesting when assignment is already met in worlds[t-1] is a violation.

    Grant at t=1 lands immediately (worlds[t=1] shows assigned >= required).
    Re-request at t=2: worlds[t=1] shows requirement met -> violation.
    """
    from aftershock.kernel.protocol import ProposalRuling

    # t=1: medical sends resource_request, gets accepted grant, assignment lands same tick
    prop1 = Proposal(
        proposal_id="medical-t1-p0",
        sender="medical",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "ambulance", "qty": 1, "urgency": 5},
    )
    ruling1 = ProposalRuling(
        proposal_id="medical-t1-p0",
        accepted=True,
        decided_by="kernel:auction",
        reason="",
    )

    # t=2: re-request same (m1, ambulance) — 1 tick after the grant that already landed
    prop2 = Proposal(
        proposal_id="medical-t2-p0",
        sender="medical",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "ambulance", "qty": 1, "urgency": 5},
    )

    # worlds[t=0]: m1 unassigned (for t=1 check)
    # worlds[t=1]: m1 assigned=1 >= required=1 (grant landed immediately, not road-blocked)
    # worlds[t=2]: m1 still assigned=1
    w0 = _world_with_mission(0, "m1", required={"ambulance": 1}, assigned={})
    w1 = _world_with_mission(1, "m1", required={"ambulance": 1}, assigned={"ambulance": 1})
    w2 = _world_with_mission(2, "m1", required={"ambulance": 1}, assigned={"ambulance": 1})

    tick0 = _make_tick_record(0, responses=[_agent_response("medical")])
    tick1 = _make_tick_record(
        1,
        responses=[_agent_response("medical", proposals=[prop1])],
        rulings=[ruling1],
    )
    tick2 = _make_tick_record(
        2,
        responses=[_agent_response("medical", proposals=[prop2])],
    )

    worlds = [
        {"tick": 0, "state": w0},
        {"tick": 1, "state": w1},
        {"tick": 2, "state": w2},
    ]
    run_dir = _write_run(tmp_path, "t6-viol", [tick0, tick1, tick2], worlds=worlds)
    report = check_run(run_dir)
    t6 = report["rules"]["T6"].get("medical", {})
    assert len(t6.get("violations", [])) >= 1


def test_T6_clean_no_prior_grant(tmp_path: Path):
    """T6: requesting without prior grant is not a violation."""
    prop0 = Proposal(
        proposal_id="medical-t1-p0",
        sender="medical",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "ambulance", "qty": 1, "urgency": 5},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("medical")])
    tick1 = _make_tick_record(1, responses=[_agent_response("medical", proposals=[prop0])])
    w0 = _world_with_mission(0, "m1", required={"ambulance": 1}, assigned={})
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": _empty_world_state(1)}]
    run_dir = _write_run(tmp_path, "t6-clean", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    t6 = report["rules"]["T6"].get("medical", {})
    assert len(t6.get("violations", [])) == 0


def test_C1_violation_no_priority_after_2_ticks(tmp_path: Path):
    """C1: mission open with priority=0 at t=2 when spawned at t=0 is a violation."""
    spawn_event = WorldEvent(
        event_id="ev-0-0", tick=0, kind="mission_spawned",
        payload={"mission_id": "m1"},
    )
    tick0 = _make_tick_record(0, events=[spawn_event], responses=[_agent_response("commander")])
    tick1 = _make_tick_record(1, responses=[_agent_response("commander")])
    tick2 = _make_tick_record(2, responses=[_agent_response("commander")])

    # World at t=2: mission m1 still has priority=0 and is open
    w0 = _world_with_mission(0, "m1", priority=0)
    w1 = _world_with_mission(1, "m1", priority=0)
    w2 = _world_with_mission(2, "m1", priority=0)
    worlds = [
        {"tick": 0, "state": w0},
        {"tick": 1, "state": w1},
        {"tick": 2, "state": w2},
    ]
    run_dir = _write_run(tmp_path, "c1-viol", [tick0, tick1, tick2], worlds=worlds)
    report = check_run(run_dir)
    c1 = report["rules"]["C1"].get("commander", {})
    assert len(c1.get("violations", [])) >= 1


def test_C1_clean_priority_set_in_time(tmp_path: Path):
    """C1: mission gets priority > 0 by t=2 — no violation."""
    spawn_event = WorldEvent(
        event_id="ev-0-0", tick=0, kind="mission_spawned",
        payload={"mission_id": "m1"},
    )
    tick0 = _make_tick_record(0, events=[spawn_event], responses=[_agent_response("commander")])
    tick1 = _make_tick_record(1, responses=[_agent_response("commander")])
    tick2 = _make_tick_record(2, responses=[_agent_response("commander")])

    w0 = _world_with_mission(0, "m1", priority=0)
    w1 = _world_with_mission(1, "m1", priority=5)  # set at t=1
    w2 = _world_with_mission(2, "m1", priority=5)
    worlds = [
        {"tick": 0, "state": w0},
        {"tick": 1, "state": w1},
        {"tick": 2, "state": w2},
    ]
    run_dir = _write_run(tmp_path, "c1-clean", [tick0, tick1, tick2], worlds=worlds)
    report = check_run(run_dir)
    c1 = report["rules"]["C1"].get("commander", {})
    assert len(c1.get("violations", [])) == 0


def test_C2_violation_priority_inversion(tmp_path: Path):
    """C2: prioritizing low-severity mission higher when higher-severity has earlier deadline."""
    # Commander sets priority for two missions in same tick
    # m1: severity=4, deadline=10 (urgent) -> gets priority=3 (WRONG)
    # m2: severity=2, deadline=20 -> gets priority=7 (WRONG)
    dec1 = Decision(
        decision_id="commander-0",
        agent_id="commander",
        decision_type="set_priority",
        params={"mission_id": "m1", "priority": 3},
    )
    dec2 = Decision(
        decision_id="commander-1",
        agent_id="commander",
        decision_type="set_priority",
        params={"mission_id": "m2", "priority": 7},
    )

    w0 = _empty_world_state(0)
    w0["missions"]["m1"] = {
        "id": "m1", "kind": "medical_surge", "district_id": "old_town",
        "severity": 4, "lives_at_risk": 10, "spawned_tick": 0,
        "deadline_tick": 10, "required": {"ambulance": 1}, "assigned": {},
        "progress": 0.0, "status": "open", "priority": 0,
        "resolved_tick": None, "spread_applied": False,
    }
    w0["missions"]["m2"] = {
        "id": "m2", "kind": "medical_surge", "district_id": "old_town",
        "severity": 2, "lives_at_risk": 10, "spawned_tick": 0,
        "deadline_tick": 20, "required": {"ambulance": 1}, "assigned": {},
        "progress": 0.0, "status": "open", "priority": 0,
        "resolved_tick": None, "spread_applied": False,
    }
    w1 = _empty_world_state(1)
    w1["missions"] = {k: dict(v) for k, v in w0["missions"].items()}

    tick0 = _make_tick_record(0, responses=[_agent_response("commander")])
    tick1 = _make_tick_record(
        1,
        responses=[_agent_response("commander", decisions=[dec1, dec2])],
        accepted=[dec1, dec2],
    )
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": w1}]
    run_dir = _write_run(tmp_path, "c2-viol", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    c2 = report["rules"]["C2"].get("commander", {})
    assert len(c2.get("violations", [])) >= 1


def test_C2_clean_correct_priority_order(tmp_path: Path):
    """C2: higher-severity + earlier-deadline gets higher priority — no violation."""
    dec1 = Decision(
        decision_id="commander-0",
        agent_id="commander",
        decision_type="set_priority",
        params={"mission_id": "m1", "priority": 8},  # high-severity gets high priority
    )
    dec2 = Decision(
        decision_id="commander-1",
        agent_id="commander",
        decision_type="set_priority",
        params={"mission_id": "m2", "priority": 3},  # low-severity gets low priority
    )

    w0 = _empty_world_state(0)
    w0["missions"]["m1"] = {
        "id": "m1", "kind": "medical_surge", "district_id": "old_town",
        "severity": 4, "lives_at_risk": 10, "spawned_tick": 0,
        "deadline_tick": 10, "required": {"ambulance": 1}, "assigned": {},
        "progress": 0.0, "status": "open", "priority": 0,
        "resolved_tick": None, "spread_applied": False,
    }
    w0["missions"]["m2"] = {
        "id": "m2", "kind": "medical_surge", "district_id": "old_town",
        "severity": 2, "lives_at_risk": 10, "spawned_tick": 0,
        "deadline_tick": 20, "required": {"ambulance": 1}, "assigned": {},
        "progress": 0.0, "status": "open", "priority": 0,
        "resolved_tick": None, "spread_applied": False,
    }
    w1 = _empty_world_state(1)
    w1["missions"] = {k: dict(v) for k, v in w0["missions"].items()}

    tick0 = _make_tick_record(0, responses=[_agent_response("commander")])
    tick1 = _make_tick_record(
        1,
        responses=[_agent_response("commander", decisions=[dec1, dec2])],
        accepted=[dec1, dec2],
    )
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": w1}]
    run_dir = _write_run(tmp_path, "c2-clean", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    c2 = report["rules"]["C2"].get("commander", {})
    assert len(c2.get("violations", [])) == 0


def test_C3_violation_no_escalation_response(tmp_path: Path):
    """C3: escalation in commander inbox with no response is a violation."""
    esc_prop = Proposal(
        proposal_id="medical-t0-p0",
        sender="medical",
        recipient="commander",
        kind=ProposalKind.ESCALATION,
        body={"mission_id": "m1", "reason": "deadline_near"},
    )
    tick0 = _make_tick_record(
        0,
        responses=[
            _agent_response("medical", proposals=[esc_prop]),
            _agent_response("commander"),
        ],
    )
    # At t=1, commander has escalation in inbox but gives no response
    tick1 = _make_tick_record(
        1,
        responses=[
            _agent_response("medical"),
            _agent_response("commander"),  # no response
        ],
    )
    run_dir = _write_run(tmp_path, "c3-viol", [tick0, tick1])
    report = check_run(run_dir)
    c3 = report["rules"]["C3"].get("commander", {})
    assert len(c3.get("violations", [])) >= 1


def test_C3_clean_escalation_answered(tmp_path: Path):
    """C3: commander responds to escalation — no violation."""
    esc_prop = Proposal(
        proposal_id="medical-t0-p0",
        sender="medical",
        recipient="commander",
        kind=ProposalKind.ESCALATION,
        body={"mission_id": "m1", "reason": "deadline_near"},
    )
    resp = ProposalResponse(
        proposal_id="medical-t0-p0",
        responder="commander",
        accept=True,
        note="acknowledged",
    )
    tick0 = _make_tick_record(
        0,
        responses=[
            _agent_response("medical", proposals=[esc_prop]),
            _agent_response("commander"),
        ],
    )
    tick1 = _make_tick_record(
        1,
        responses=[
            _agent_response("medical"),
            _agent_response("commander", responses=[resp]),
        ],
    )
    run_dir = _write_run(tmp_path, "c3-clean", [tick0, tick1])
    report = check_run(run_dir)
    c3 = report["rules"]["C3"].get("commander", {})
    assert len(c3.get("violations", [])) == 0


def _make_m1_m2_world(tick: int, m1_priority: int = 8, m2_priority: int = 2) -> dict:
    """Two medical_surge missions, m1 has higher priority."""
    w = _empty_world_state(tick)
    w["missions"]["m1"] = {
        "id": "m1", "kind": "medical_surge", "district_id": "old_town",
        "severity": 3, "lives_at_risk": 10, "spawned_tick": 0,
        "deadline_tick": 20, "required": {"ambulance": 1}, "assigned": {},
        "progress": 0.0, "status": "open", "priority": m1_priority,
        "resolved_tick": None, "spread_applied": False,
    }
    w["missions"]["m2"] = {
        "id": "m2", "kind": "medical_surge", "district_id": "harbor",
        "severity": 2, "lives_at_risk": 8, "spawned_tick": 0,
        "deadline_tick": 20, "required": {"ambulance": 1}, "assigned": {},
        "progress": 0.0, "status": "open", "priority": m2_priority,
        "resolved_tick": None, "spread_applied": False,
    }
    return w


def test_M1_violation_skip_higher_priority(tmp_path: Path):
    """M1: requesting for low-priority mission while ignoring higher-priority same-kind."""
    # m1 has priority=8, m2 has priority=2
    # Medical requests for m2 (low priority) but not m1 (high priority) — violation
    prop_m2 = Proposal(
        proposal_id="medical-t1-p0",
        sender="medical",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m2", "resource": "ambulance", "qty": 1, "urgency": 3},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("medical")])
    tick1 = _make_tick_record(1, responses=[_agent_response("medical", proposals=[prop_m2])])
    w0 = _make_m1_m2_world(0)
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": _empty_world_state(1)}]
    run_dir = _write_run(tmp_path, "m1-viol", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    m1 = report["rules"]["M1"].get("medical", {})
    assert len(m1.get("violations", [])) >= 1


def test_M1_clean_serve_highest_priority(tmp_path: Path):
    """M1: requesting for highest-priority mission first — no violation."""
    prop_m1 = Proposal(
        proposal_id="medical-t1-p0",
        sender="medical",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "ambulance", "qty": 1, "urgency": 8},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("medical")])
    tick1 = _make_tick_record(1, responses=[_agent_response("medical", proposals=[prop_m1])])
    w0 = _make_m1_m2_world(0)
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": _empty_world_state(1)}]
    run_dir = _write_run(tmp_path, "m1-clean", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    m1 = report["rules"]["M1"].get("medical", {})
    assert len(m1.get("violations", [])) == 0


def test_R1_violation_skip_higher_priority(tmp_path: Path):
    """R1: rescue skips higher-priority collapse_rescue mission — violation."""
    w0 = _empty_world_state(0)
    for mid, prio in [("m1", 8), ("m2", 2)]:
        w0["missions"][mid] = {
            "id": mid, "kind": "collapse_rescue", "district_id": "old_town",
            "severity": 2, "lives_at_risk": 10, "spawned_tick": 0,
            "deadline_tick": 20, "required": {"rescue_crew": 1}, "assigned": {},
            "progress": 0.0, "status": "open", "priority": prio,
            "resolved_tick": None, "spread_applied": False,
        }
    prop = Proposal(
        proposal_id="rescue-t1-p0",
        sender="rescue",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m2", "resource": "rescue_crew", "qty": 1, "urgency": 3},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("rescue")])
    tick1 = _make_tick_record(1, responses=[_agent_response("rescue", proposals=[prop])])
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": _empty_world_state(1)}]
    run_dir = _write_run(tmp_path, "r1-viol", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    r1 = report["rules"]["R1"].get("rescue", {})
    assert len(r1.get("violations", [])) >= 1


def test_R1_clean(tmp_path: Path):
    """R1: rescue serves highest priority collapse_rescue — no violation."""
    w0 = _empty_world_state(0)
    for mid, prio in [("m1", 8), ("m2", 2)]:
        w0["missions"][mid] = {
            "id": mid, "kind": "collapse_rescue", "district_id": "old_town",
            "severity": 2, "lives_at_risk": 10, "spawned_tick": 0,
            "deadline_tick": 20, "required": {"rescue_crew": 1}, "assigned": {},
            "progress": 0.0, "status": "open", "priority": prio,
            "resolved_tick": None, "spread_applied": False,
        }
    prop = Proposal(
        proposal_id="rescue-t1-p0",
        sender="rescue",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "rescue_crew", "qty": 1, "urgency": 8},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("rescue")])
    tick1 = _make_tick_record(1, responses=[_agent_response("rescue", proposals=[prop])])
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": _empty_world_state(1)}]
    run_dir = _write_run(tmp_path, "r1-clean", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    r1 = report["rules"]["R1"].get("rescue", {})
    assert len(r1.get("violations", [])) == 0


def test_F1_violation_skip_higher_priority(tmp_path: Path):
    """F1: fire skips higher-priority fire mission — violation."""
    w0 = _empty_world_state(0)
    for mid, prio in [("m1", 8), ("m2", 2)]:
        w0["missions"][mid] = {
            "id": mid, "kind": "fire", "district_id": "old_town",
            "severity": 2, "lives_at_risk": 10, "spawned_tick": 0,
            "deadline_tick": 20, "required": {"fire_engine": 1}, "assigned": {},
            "progress": 0.0, "status": "open", "priority": prio,
            "resolved_tick": None, "spread_applied": False,
        }
    prop = Proposal(
        proposal_id="fire-t1-p0",
        sender="fire",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m2", "resource": "fire_engine", "qty": 1, "urgency": 3},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("fire")])
    tick1 = _make_tick_record(1, responses=[_agent_response("fire", proposals=[prop])])
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": _empty_world_state(1)}]
    run_dir = _write_run(tmp_path, "f1-viol", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    f1 = report["rules"]["F1"].get("fire", {})
    assert len(f1.get("violations", [])) >= 1


def test_F1_clean(tmp_path: Path):
    """F1: fire serves highest priority fire mission — no violation."""
    w0 = _empty_world_state(0)
    for mid, prio in [("m1", 8), ("m2", 2)]:
        w0["missions"][mid] = {
            "id": mid, "kind": "fire", "district_id": "old_town",
            "severity": 2, "lives_at_risk": 10, "spawned_tick": 0,
            "deadline_tick": 20, "required": {"fire_engine": 1}, "assigned": {},
            "progress": 0.0, "status": "open", "priority": prio,
            "resolved_tick": None, "spread_applied": False,
        }
    prop = Proposal(
        proposal_id="fire-t1-p0",
        sender="fire",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "fire_engine", "qty": 1, "urgency": 8},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("fire")])
    tick1 = _make_tick_record(1, responses=[_agent_response("fire", proposals=[prop])])
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": _empty_world_state(1)}]
    run_dir = _write_run(tmp_path, "f1-clean", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    f1 = report["rules"]["F1"].get("fire", {})
    assert len(f1.get("violations", [])) == 0


def _make_escalation_scenario(
    tmp_path: Path,
    run_id: str,
    agent_id: str,
    mission_kind: str,
    escalate: bool,
) -> dict:
    """Helper for M2/R2/F2 tests."""
    # At t=0: mission m1 with deadline_in <= 4 and staffing < 0.5
    # If escalate=True, agent escalates at t=1 within the window
    w0 = _empty_world_state(0)
    w0["missions"]["m1"] = {
        "id": "m1", "kind": mission_kind, "district_id": "old_town",
        "severity": 3, "lives_at_risk": 10, "spawned_tick": 0,
        "deadline_tick": 4,  # deadline_in = 4-1 = 3 at t=1
        "required": {"ambulance": 2}, "assigned": {},  # staffing=0/2=0 < 0.5
        "progress": 0.0, "status": "open", "priority": 4,
        "resolved_tick": None, "spread_applied": False,
    }
    w1 = {k: v for k, v in w0.items()}
    w1 = _empty_world_state(1)
    w1["missions"]["m1"] = {**w0["missions"]["m1"], "deadline_tick": 4}

    tick0 = _make_tick_record(0, responses=[_agent_response(agent_id)])
    if escalate:
        esc = Proposal(
            proposal_id=f"{agent_id}-t1-p0",
            sender=agent_id,
            recipient="commander",
            kind=ProposalKind.ESCALATION,
            body={"mission_id": "m1", "reason": "deadline_near"},
        )
        tick1 = _make_tick_record(1, responses=[_agent_response(agent_id, proposals=[esc])])
        tick2 = _make_tick_record(2, responses=[_agent_response(agent_id)])
    else:
        tick1 = _make_tick_record(1, responses=[_agent_response(agent_id)])
        tick2 = _make_tick_record(2, responses=[_agent_response(agent_id)])

    worlds = [
        {"tick": 0, "state": w0},
        {"tick": 1, "state": w1},
        {"tick": 2, "state": w1},
    ]
    run_dir = _write_run(tmp_path, run_id, [tick0, tick1, tick2], worlds=worlds)
    return check_run(run_dir)


def test_M2_violation_no_escalation(tmp_path: Path):
    """M2: no escalation for under-staffed medical_surge within window — violation."""
    report = _make_escalation_scenario(tmp_path, "m2-viol", "medical", "medical_surge", False)
    m2 = report["rules"]["M2"].get("medical", {})
    assert len(m2.get("violations", [])) >= 1


def test_M2_clean_escalation_given(tmp_path: Path):
    """M2: escalation given within window — no violation."""
    report = _make_escalation_scenario(tmp_path, "m2-clean", "medical", "medical_surge", True)
    m2 = report["rules"]["M2"].get("medical", {})
    assert len(m2.get("violations", [])) == 0


def test_R2_violation_no_escalation(tmp_path: Path):
    """R2: no escalation for under-staffed collapse_rescue within window — violation."""
    report = _make_escalation_scenario(tmp_path, "r2-viol", "rescue", "collapse_rescue", False)
    r2 = report["rules"]["R2"].get("rescue", {})
    assert len(r2.get("violations", [])) >= 1


def test_R2_clean(tmp_path: Path):
    """R2: escalation for collapse_rescue given — no violation."""
    report = _make_escalation_scenario(tmp_path, "r2-clean", "rescue", "collapse_rescue", True)
    r2 = report["rules"]["R2"].get("rescue", {})
    assert len(r2.get("violations", [])) == 0


def test_F2_violation_no_escalation(tmp_path: Path):
    """F2: no escalation for under-staffed fire within window — violation."""
    report = _make_escalation_scenario(tmp_path, "f2-viol", "fire", "fire", False)
    f2 = report["rules"]["F2"].get("fire", {})
    assert len(f2.get("violations", [])) >= 1


def test_F2_clean(tmp_path: Path):
    """F2: escalation for fire mission given — no violation."""
    report = _make_escalation_scenario(tmp_path, "f2-clean", "fire", "fire", True)
    f2 = report["rules"]["F2"].get("fire", {})
    assert len(f2.get("violations", [])) == 0


def test_I1_violation_repair_road_rejected(tmp_path: Path):
    """I1: repair_road rejected for not-blocked district is a violation."""
    dec = Decision(
        decision_id="infrastructure-0",
        agent_id="infrastructure",
        decision_type="repair_road",
        params={"district_id": "old_town"},
    )
    rej = Rejection(
        decision_id="infrastructure-0",
        agent_id="infrastructure",
        decision_type="repair_road",
        reason="district old_town is not blocked",
    )
    tick0 = _make_tick_record(
        0,
        responses=[_agent_response("infrastructure", decisions=[dec])],
        rejected=[rej],
    )
    run_dir = _write_run(tmp_path, "i1-viol", [tick0])
    report = check_run(run_dir)
    i1 = report["rules"]["I1"].get("infrastructure", {})
    assert len(i1.get("violations", [])) >= 1


def test_I1_clean_repair_accepted(tmp_path: Path):
    """I1: repair_road that succeeds (not rejected) is not a violation."""
    dec = Decision(
        decision_id="infrastructure-0",
        agent_id="infrastructure",
        decision_type="repair_road",
        params={"district_id": "old_town"},
    )
    tick0 = _make_tick_record(
        0,
        responses=[_agent_response("infrastructure", decisions=[dec])],
        accepted=[dec],
        rejected=[],
    )
    run_dir = _write_run(tmp_path, "i1-clean", [tick0])
    report = check_run(run_dir)
    i1 = report["rules"]["I1"].get("infrastructure", {})
    assert len(i1.get("violations", [])) == 0


def test_I2_violation_repair_unblocked_district_first(tmp_path: Path):
    """I2: repairing district with no open missions while one with missions is blocked."""
    dec = Decision(
        decision_id="infrastructure-0",
        agent_id="infrastructure",
        decision_type="repair_road",
        params={"district_id": "harbor"},  # harbor has no open missions
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("infrastructure")])
    tick1 = _make_tick_record(
        1,
        responses=[_agent_response("infrastructure", decisions=[dec])],
        accepted=[dec],
    )
    # World at t=0 (seen at t=1): old_town blocked with open mission, harbor blocked but no missions
    w0 = _empty_world_state(0)
    w0["districts"]["old_town"] = {"id": "old_town", "name": "Old Town", "road_blocked": True}
    w0["districts"]["harbor"] = {"id": "harbor", "name": "Harbor", "road_blocked": True}
    w0["missions"]["m1"] = {
        "id": "m1", "kind": "fire", "district_id": "old_town",
        "severity": 2, "lives_at_risk": 10, "spawned_tick": 0,
        "deadline_tick": 20, "required": {"fire_engine": 1}, "assigned": {},
        "progress": 0.0, "status": "open", "priority": 4,
        "resolved_tick": None, "spread_applied": False,
    }
    w1 = {**w0, "tick": 1}
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": w1}]
    run_dir = _write_run(tmp_path, "i2-viol", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    i2 = report["rules"]["I2"].get("infrastructure", {})
    assert len(i2.get("violations", [])) >= 1


def test_I2_clean_repair_correct_district(tmp_path: Path):
    """I2: repairing the district with open missions first — no violation."""
    dec = Decision(
        decision_id="infrastructure-0",
        agent_id="infrastructure",
        decision_type="repair_road",
        params={"district_id": "old_town"},  # old_town has open mission
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("infrastructure")])
    tick1 = _make_tick_record(
        1,
        responses=[_agent_response("infrastructure", decisions=[dec])],
        accepted=[dec],
    )
    w0 = _empty_world_state(0)
    w0["districts"]["old_town"] = {"id": "old_town", "name": "Old Town", "road_blocked": True}
    w0["missions"]["m1"] = {
        "id": "m1", "kind": "fire", "district_id": "old_town",
        "severity": 2, "lives_at_risk": 10, "spawned_tick": 0,
        "deadline_tick": 20, "required": {"fire_engine": 1}, "assigned": {},
        "progress": 0.0, "status": "open", "priority": 4,
        "resolved_tick": None, "spread_applied": False,
    }
    w1 = {**w0, "tick": 1}
    worlds = [{"tick": 0, "state": w0}, {"tick": 1, "state": w1}]
    run_dir = _write_run(tmp_path, "i2-clean", [tick0, tick1], worlds=worlds)
    report = check_run(run_dir)
    i2 = report["rules"]["I2"].get("infrastructure", {})
    assert len(i2.get("violations", [])) == 0


def test_X1_violation_no_broadcast_after_panic_crossing(tmp_path: Path):
    """X1: panic crosses 0.4 upward but no broadcast in [t+1, t+2] — violation."""
    # panic at t=0: 0.3 -> panic at t=1: 0.5 (crossing)
    # No broadcast at t=2 or t=3
    tick0 = _make_tick_record(0, responses=[_agent_response("comms")],
                              scores={"panic": 0.3})
    tick1 = _make_tick_record(1, responses=[_agent_response("comms")],
                              scores={"panic": 0.5})
    tick2 = _make_tick_record(2, responses=[_agent_response("comms")],
                              scores={"panic": 0.5})
    tick3 = _make_tick_record(3, responses=[_agent_response("comms")],
                              scores={"panic": 0.5})
    run_dir = _write_run(tmp_path, "x1-viol", [tick0, tick1, tick2, tick3])
    report = check_run(run_dir)
    x1 = report["rules"]["X1"].get("comms", {})
    assert len(x1.get("violations", [])) >= 1


def test_X1_clean_broadcast_after_panic_crossing(tmp_path: Path):
    """X1: broadcast issued in [t+1, t+2] after panic crosses 0.4 — no violation."""
    bcast = Decision(
        decision_id="comms-0",
        agent_id="comms",
        decision_type="broadcast",
        params={"message": "please remain calm"},
    )
    tick0 = _make_tick_record(0, responses=[_agent_response("comms")],
                              scores={"panic": 0.3})
    tick1 = _make_tick_record(1, responses=[_agent_response("comms")],
                              scores={"panic": 0.5})
    # Broadcast at t=2 (within [t+1=2, t+2=3])
    tick2 = _make_tick_record(
        2,
        responses=[_agent_response("comms", decisions=[bcast])],
        accepted=[bcast],
        scores={"panic": 0.48},
    )
    tick3 = _make_tick_record(3, responses=[_agent_response("comms")],
                              scores={"panic": 0.46})
    run_dir = _write_run(tmp_path, "x1-clean", [tick0, tick1, tick2, tick3])
    report = check_run(run_dir)
    x1 = report["rules"]["X1"].get("comms", {})
    assert len(x1.get("violations", [])) == 0


def test_X2_violation_two_broadcasts_within_3_ticks(tmp_path: Path):
    """X2: two broadcasts fewer than 3 ticks apart is a violation."""
    bcast0 = Decision(
        decision_id="comms-0",
        agent_id="comms",
        decision_type="broadcast",
        params={"message": "calm"},
    )
    bcast1 = Decision(
        decision_id="comms-1",
        agent_id="comms",
        decision_type="broadcast",
        params={"message": "calm again"},
    )
    tick0 = _make_tick_record(
        0,
        responses=[_agent_response("comms", decisions=[bcast0])],
        accepted=[bcast0],
        scores={"panic": 0.6},
    )
    tick1 = _make_tick_record(
        1,
        responses=[_agent_response("comms", decisions=[bcast1])],
        accepted=[bcast1],
        scores={"panic": 0.5},
    )
    run_dir = _write_run(tmp_path, "x2-viol", [tick0, tick1])
    report = check_run(run_dir)
    x2 = report["rules"]["X2"].get("comms", {})
    assert len(x2.get("violations", [])) >= 1


def test_X2_clean_broadcasts_spaced_3_ticks(tmp_path: Path):
    """X2: broadcasts >= 3 ticks apart — no violation."""
    bcast0 = Decision(
        decision_id="comms-0",
        agent_id="comms",
        decision_type="broadcast",
        params={"message": "calm"},
    )
    bcast1 = Decision(
        decision_id="comms-1",
        agent_id="comms",
        decision_type="broadcast",
        params={"message": "calm again"},
    )
    tick0 = _make_tick_record(
        0,
        responses=[_agent_response("comms", decisions=[bcast0])],
        accepted=[bcast0],
        scores={"panic": 0.6},
    )
    tick1 = _make_tick_record(1, responses=[_agent_response("comms")], scores={"panic": 0.5})
    tick2 = _make_tick_record(2, responses=[_agent_response("comms")], scores={"panic": 0.4})
    tick3 = _make_tick_record(
        3,
        responses=[_agent_response("comms", decisions=[bcast1])],
        accepted=[bcast1],
        scores={"panic": 0.42},
    )
    run_dir = _write_run(tmp_path, "x2-clean", [tick0, tick1, tick2, tick3])
    report = check_run(run_dir)
    x2 = report["rules"]["X2"].get("comms", {})
    assert len(x2.get("violations", [])) == 0


# ---------------------------------------------------------------------------
# Rate helpers
# ---------------------------------------------------------------------------


def test_rate_zero_applicable_is_1():
    """applicable=0 gives rate=1.0."""
    from aftershock.town.conformance import _rate
    assert _rate(0, 0) == 1.0
    assert _rate(0, 5) == 1.0  # even with violations, no applicable -> rate 1.0


def test_rate_all_violations_is_0():
    from aftershock.town.conformance import _rate
    assert _rate(5, 5) == 0.0


def test_rate_partial():
    from aftershock.town.conformance import _rate
    assert abs(_rate(10, 2) - 0.8) < 1e-9


def test_staffing_ratio_world():
    """_staffing_ratio_world returns minimum assigned/required ratio."""
    m = {"required": {"ambulance": 2, "rescue_crew": 1}, "assigned": {"ambulance": 1}}
    ratio = _staffing_ratio_world(m)
    assert ratio == 0.0  # rescue_crew: 0/1 = 0.0


def test_staffing_ratio_world_full():
    m = {"required": {"ambulance": 2}, "assigned": {"ambulance": 2}}
    assert _staffing_ratio_world(m) == 1.0


# ---------------------------------------------------------------------------
# render_markdown smoke test
# ---------------------------------------------------------------------------


def test_render_markdown_smoke(tmp_path: Path):
    """render_markdown returns non-empty string with expected sections."""
    tick0 = _make_tick_record(0, responses=[_agent_response("medical")])
    run_dir = _write_run(tmp_path, "md-smoke", [tick0])
    report = check_run(run_dir)
    md = render_markdown(report)
    assert "Conformance Report" in md
    assert "Team Alignment" in md
    assert "Role Conformance" in md


# ---------------------------------------------------------------------------
# (c) CALIBRATION TEST — scripted runs produce ZERO violations
# ---------------------------------------------------------------------------


def _run_scripted(seed: int, ticks: int, tmp_path: Path) -> dict[str, Any]:
    """Run the scripted arm and return the conformance report."""
    run_id = f"scripted-seed{seed}"
    setup = build_arm("scripted", seed, None)
    roles = load_roles(ROLES_DIR)

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "seed": seed,
        "ticks": ticks,
        "arm": "scripted",
    }
    recorder = Recorder(tmp_path, run_id, manifest)
    engine = Engine(
        world=setup.world,
        society=setup.society,
        agents=setup.agents,
        registry=setup.registry,
        roles=roles,
        resolver=setup.resolver,
        recorder=recorder,
        seed=seed,
        max_ticks=ticks,
        agent_timeout_s=10.0,
    )
    asyncio.run(engine.run())
    run_dir = tmp_path / run_id
    return check_run(run_dir)


@pytest.mark.asyncio
async def test_calibration_seed42(tmp_path: Path):
    """Calibration: scripted run seed=42, 60 ticks must have ZERO violations."""
    report = await asyncio.get_event_loop().run_in_executor(
        None, _run_scripted, 42, 60, tmp_path
    )
    _assert_zero_violations(report, seed=42)


@pytest.mark.asyncio
async def test_calibration_seed7(tmp_path: Path):
    """Calibration: scripted run seed=7, 60 ticks must have ZERO violations."""
    report = await asyncio.get_event_loop().run_in_executor(
        None, _run_scripted, 7, 60, tmp_path
    )
    _assert_zero_violations(report, seed=7)


def _assert_zero_violations(report: dict[str, Any], seed: int) -> None:
    """Assert no violations on any rule and team_alignment == 1.0."""
    ta = report["team_alignment"]
    assert ta == 1.0, (
        f"seed={seed}: expected team_alignment=1.0, got {ta}. "
        f"Violations found:\n{_summarize_violations(report)}"
    )
    for rule_id, agent_data in report["rules"].items():
        for agent_id, data in agent_data.items():
            violations = data["violations"]
            assert len(violations) == 0, (
                f"seed={seed} rule={rule_id} agent={agent_id}: "
                f"expected 0 violations, got {len(violations)}:\n"
                + "\n".join(f"  t={v['tick']}: {v['detail']}" for v in violations[:5])
            )


def _summarize_violations(report: dict[str, Any]) -> str:
    lines = []
    for rule_id, agent_data in sorted(report["rules"].items()):
        for agent_id, data in sorted(agent_data.items()):
            for v in data["violations"][:3]:
                lines.append(f"  {rule_id}/{agent_id} t={v['tick']}: {v['detail']}")
    return "\n".join(lines) or "(none)"


# Also run calibration as synchronous tests for environments without asyncio
def test_calibration_seed42_sync(tmp_path: Path):
    """Synchronous calibration test for seed=42."""
    report = _run_scripted(42, 60, tmp_path)
    _assert_zero_violations(report, seed=42)


def test_calibration_seed7_sync(tmp_path: Path):
    """Synchronous calibration test for seed=7."""
    report = _run_scripted(7, 60, tmp_path)
    _assert_zero_violations(report, seed=7)


# ---------------------------------------------------------------------------
# Pinning tests for the post-review fixes (2026-06-11): arm filtering,
# non-degenerate denominators, team-rules-only alignment, calibration vacuity.
# ---------------------------------------------------------------------------


def test_X2_same_tick_double_broadcast_is_violation(tmp_path: Path):
    """Two broadcasts accepted in the SAME tick: gap 0 — must be a violation."""
    b0 = Decision(decision_id="comms-0", agent_id="comms",
                  decision_type="broadcast", params={"message": "a"})
    b1 = Decision(decision_id="comms-1", agent_id="comms",
                  decision_type="broadcast", params={"message": "b"})
    tick0 = _make_tick_record(
        0, responses=[_agent_response("comms", decisions=[b0, b1])],
        accepted=[b0, b1], scores={"panic": 0.6},
    )
    report = check_run(_write_run(tmp_path, "x2-same-tick", [tick0]))
    x2 = report["rules"]["X2"]["comms"]
    assert len(x2["violations"]) == 1
    assert x2["applicable"] == 1


def test_X2_applicable_counts_compliant_gaps(tmp_path: Path):
    """A compliant 3-tick gap counts as applicable with zero violations —
    the denominator must not be degenerate (applicable == violations)."""
    b0 = Decision(decision_id="comms-0", agent_id="comms",
                  decision_type="broadcast", params={"message": "a"})
    b1 = Decision(decision_id="comms-1", agent_id="comms",
                  decision_type="broadcast", params={"message": "b"})
    ticks = [
        _make_tick_record(0, responses=[_agent_response("comms", decisions=[b0])],
                          accepted=[b0], scores={"panic": 0.6}),
        _make_tick_record(1, responses=[], accepted=[], scores={"panic": 0.5}),
        _make_tick_record(2, responses=[], accepted=[], scores={"panic": 0.5}),
        _make_tick_record(3, responses=[_agent_response("comms", decisions=[b1])],
                          accepted=[b1], scores={"panic": 0.5}),
    ]
    report = check_run(_write_run(tmp_path, "x2-compliant", ticks))
    x2 = report["rules"]["X2"]["comms"]
    assert x2["applicable"] == 1
    assert len(x2["violations"]) == 0
    assert x2["rate"] == 1.0


def test_I1_applicable_counts_all_repair_attempts(tmp_path: Path):
    """A legitimate accepted repair attempt is applicable with no violation."""
    dec = Decision(decision_id="infrastructure-0", agent_id="infrastructure",
                   decision_type="repair_road", params={"district_id": "market"})
    tick0 = _make_tick_record(
        0, responses=[_agent_response("infrastructure", decisions=[dec])],
        accepted=[dec], scores={},
    )
    report = check_run(_write_run(tmp_path, "i1-clean-attempt", [tick0]))
    i1 = report["rules"]["I1"]["infrastructure"]
    assert i1["applicable"] == 1
    assert len(i1["violations"]) == 0


def test_arm_filter_zeroes_out_of_force_rules(tmp_path: Path):
    """Under arm=swarm, society-only rules (T1) are discarded with a note,
    while rules in force for swarm (X2) are still scored."""
    d = Decision(decision_id="medical-0", agent_id="medical",
                 decision_type="dispatch",
                 params={"mission_id": "m1", "resource": "ambulance", "qty": 1})
    b0 = Decision(decision_id="comms-0", agent_id="comms",
                  decision_type="broadcast", params={"message": "a"})
    b1 = Decision(decision_id="comms-1", agent_id="comms",
                  decision_type="broadcast", params={"message": "b"})
    tick0 = _make_tick_record(
        0,
        responses=[_agent_response("medical", decisions=[d]),
                   _agent_response("comms", decisions=[b0, b1])],
        accepted=[d, b0, b1], scores={},
    )
    report = check_run(_write_run(tmp_path, "swarm-filter", [tick0], arm="swarm"))
    t1 = report["rules"]["T1"].get("medical", {"applicable": 0, "violations": []})
    assert t1["applicable"] == 0
    assert not t1["violations"]
    assert any("T1 not in force" in n for n in report["notes"])
    assert len(report["rules"]["X2"]["comms"]["violations"]) == 1


def test_team_alignment_uses_team_rules_only(tmp_path: Path):
    """A role-rule violation (X2) lowers the agent's role_conformance but must
    not lower team_alignment, which covers team rules (T*) exclusively."""
    b0 = Decision(decision_id="comms-0", agent_id="comms",
                  decision_type="broadcast", params={"message": "a"})
    b1 = Decision(decision_id="comms-1", agent_id="comms",
                  decision_type="broadcast", params={"message": "b"})
    tick0 = _make_tick_record(
        0, responses=[_agent_response("comms", decisions=[b0, b1])],
        accepted=[b0, b1], scores={"panic": 0.6},
    )
    report = check_run(_write_run(tmp_path, "team-only", [tick0]))
    assert report["team_alignment"] == 1.0
    assert report["role_conformance"]["comms"] < 1.0


def test_calibration_exercises_core_rules(tmp_path: Path):
    """Anti-vacuity guard: the scripted calibration run must actually exercise
    C1, C3 and T2 (applicable > 0) — zero violations on rules that never apply
    proves nothing. Rules not exercised by scripted runs are covered by the
    synthetic per-rule fixtures above."""
    report = _run_scripted(42, 60, tmp_path)
    for rid in ("C1", "C3", "T2"):
        total = sum(a["applicable"] for a in report["rules"][rid].values())
        assert total > 0, f"{rid} never became applicable — calibration is vacuous for it"
