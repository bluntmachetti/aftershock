"""Tests for the disaster-response town society.

Covers:
- new_town determinism (same seed twice -> identical to_dict)
- timeline spawns missions at tick 0
- auction contention (two requests, one unit left -> winner by priority, loser reason names winner)
- road-block dispatch lands after 2 ticks
- mission resolves with full staffing and lives are saved
- deadline failure loses remaining lives and returns resources
- fire spread after 6 open ticks
- scripted society can save lives (short Engine run)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aftershock.kernel.registry import DecisionRegistry
from aftershock.kernel.roles import load_roles
from aftershock.town.decisions import register_all
from aftershock.town.events import scheduled_events
from aftershock.town.heuristics import (
    CommanderScripted,
    CommsScripted,
    FireScripted,
    InfraScripted,
    MedicalScripted,
    RescueScripted,
)
from aftershock.town.scoring import score
from aftershock.town.society import TownResolver, TownSociety
from aftershock.town.state import (
    MissionKind,
    MissionStatus,
    PendingArrival,
    TownState,
    new_town,
)

ROLES_DIR = Path(__file__).parent.parent / "src" / "aftershock" / "town" / "roles"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_registry() -> DecisionRegistry:
    reg = DecisionRegistry()
    register_all(reg)
    return reg


def make_minimal_state(seed: int = 42) -> TownState:
    """Return a fresh town with no timeline entries (clean slate for unit tests)."""
    state = new_town(seed)
    state.timeline = []
    return state


def dummy_rng():
    import random
    return random.Random(42)


def _add_open_mission(
    state: TownState,
    mid: str,
    kind: str,
    district_id: str = "old_town",
    severity: int = 2,
    lives: int = 10,
    spawned_tick: int = 0,
    deadline_tick: int = 20,
    required: dict | None = None,
    assigned: dict | None = None,
    priority: int = 0,
) -> None:
    from aftershock.town.state import Mission
    state.missions[mid] = Mission(
        id=mid,
        kind=kind,
        district_id=district_id,
        severity=severity,
        lives_at_risk=lives,
        spawned_tick=spawned_tick,
        deadline_tick=deadline_tick,
        required=required or {"rescue_crew": 1, "ambulance": 1},
        assigned=assigned or {},
        progress=0.0,
        status=MissionStatus.open,
        priority=priority,
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_new_town_determinism():
    """Same seed twice produces byte-identical to_dict."""
    s1 = new_town(42)
    s2 = new_town(42)
    assert s1.to_dict() == s2.to_dict()


def test_new_town_different_seeds_differ():
    """Different seeds produce different states."""
    s1 = new_town(42)
    s2 = new_town(99)
    assert s1.to_dict() != s2.to_dict()


# ---------------------------------------------------------------------------
# Timeline spawns missions at tick 0
# ---------------------------------------------------------------------------


def test_timeline_spawns_at_tick_0():
    """scheduled_events at tick 0 spawns the quake missions and adds them to state."""
    state = new_town(42)
    rng = dummy_rng()
    events = scheduled_events(state, 0, rng)

    spawned = [e for e in events if e.kind == "mission_spawned"]
    assert len(spawned) >= 4, f"Expected >= 4 missions at tick 0, got {len(spawned)}"
    assert len(state.missions) >= 4
    # All spawned missions should be open
    for m in state.missions.values():
        assert m.status == MissionStatus.open


# ---------------------------------------------------------------------------
# Auction contention
# ---------------------------------------------------------------------------


def test_auction_contention_winner_and_loser():
    """Two requests for same resource, one unit left -> winner by priority, loser names winner."""
    from aftershock.kernel.protocol import Proposal, ProposalKind

    state = make_minimal_state()
    # One ambulance remaining
    state.pools["ambulance"].available = 1

    # Add two open missions with different priorities
    _add_open_mission(
        state, "m1", MissionKind.medical_surge,
        required={"ambulance": 1, "supply_truck": 1},
        priority=8,
        deadline_tick=15,
    )
    _add_open_mission(
        state, "m2", MissionKind.medical_surge,
        required={"ambulance": 1, "supply_truck": 1},
        priority=3,
        deadline_tick=15,
    )

    # Two RESOURCE_REQUEST proposals
    prop1 = Proposal(
        proposal_id="medical-p0",
        sender="medical",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m1", "resource": "ambulance", "qty": 1, "urgency": 8},
    )
    prop2 = Proposal(
        proposal_id="rescue-p0",
        sender="rescue",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"mission_id": "m2", "resource": "ambulance", "qty": 1, "urgency": 5},
    )

    resolver = TownResolver()
    rulings, grants = resolver.resolve(state, 0, [prop1, prop2], [], [], dummy_rng())

    # Should be one winner (m1 has higher priority) and one loser
    accepted = [r for r in rulings if r.accepted]
    declined = [r for r in rulings if not r.accepted]
    assert len(accepted) == 1
    assert len(declined) == 1

    # Winner should be m1's proposal (higher priority)
    assert accepted[0].proposal_id == "medical-p0"

    # Loser's reason should name the winner mission
    assert "m1" in declined[0].reason, f"Expected 'm1' in loser reason: {declined[0].reason!r}"

    # One dispatch grant issued
    assert len(grants) == 1
    assert grants[0].params["mission_id"] == "m1"


# ---------------------------------------------------------------------------
# Road-block dispatch delay
# ---------------------------------------------------------------------------


def test_road_block_dispatch_pending_2_ticks():
    """Dispatching to a blocked-road district creates a pending arrival due in +2 ticks."""
    import random

    from aftershock.town.decisions import DispatchHandler

    state = make_minimal_state()
    state.districts["old_town"].road_blocked = True
    state.pools["ambulance"].available = 2

    _add_open_mission(
        state, "m1", MissionKind.medical_surge,
        district_id="old_town",
        required={"ambulance": 1, "supply_truck": 1},
    )

    handler = DispatchHandler()
    from aftershock.town.decisions import DispatchParams
    params = DispatchParams(mission_id="m1", resource="ambulance", qty=1)

    events = handler.apply(state, params, tick=5, rng=random.Random(0))

    # Should have created a pending arrival
    assert len(state.pending) == 1
    arrival = state.pending[0]
    assert arrival.due_tick == 7  # tick 5 + 2
    assert arrival.mission_id == "m1"
    assert arrival.resource == "ambulance"

    # Pool should be immediately reserved (available decremented)
    assert state.pools["ambulance"].available == 1

    # Arrival event emitted
    arrival_events = [e for e in events if e.kind == "arrival"]
    assert len(arrival_events) == 1
    assert arrival_events[0].payload["road_blocked"] is True


def test_road_block_arrival_lands_at_due_tick():
    """The pending arrival from a road-blocked dispatch lands at the correct tick."""
    state = make_minimal_state()
    state.districts["old_town"].road_blocked = False  # unblocked by tick 7
    state.pools["ambulance"].available = 1  # already reserved

    _add_open_mission(
        state, "m1", MissionKind.medical_surge,
        district_id="old_town",
        required={"ambulance": 1, "supply_truck": 1},
    )

    # Simulate pending arrival due at tick 7
    state.pending.append(PendingArrival(
        due_tick=7,
        mission_id="m1",
        resource="ambulance",
        qty=1,
    ))
    # Manually keep pool consistent (already "reserved" so available is 1 but we need 1 for arrival)
    # Reset to simulate pool deducted at dispatch time
    state.pools["ambulance"].available = 0

    events = scheduled_events(state, 7, dummy_rng())
    arrival_events = [e for e in events if e.kind == "arrival"]
    assert any(e.payload.get("mission_id") == "m1" for e in arrival_events)


# ---------------------------------------------------------------------------
# Mission resolves with full staffing
# ---------------------------------------------------------------------------


def test_mission_resolves_with_full_staffing():
    """A fully-staffed mission advances 0.25 per tick and resolves in 4 ticks."""
    state = make_minimal_state()
    state.pools["rescue_crew"].available = 1
    state.pools["ambulance"].available = 1

    _add_open_mission(
        state, "m1", MissionKind.collapse_rescue,
        required={"rescue_crew": 1, "ambulance": 1},
        assigned={"rescue_crew": 1, "ambulance": 1},
        lives=10,
        deadline_tick=20,
    )
    # Deduct from pools (as dispatch would have done)
    state.pools["rescue_crew"].available = 0
    state.pools["ambulance"].available = 0

    rng = dummy_rng()
    # Run 4 ticks; expect resolution
    for tick in range(4):
        events = scheduled_events(state, tick, rng)
        resolved_events = [e for e in events if e.kind == "mission_resolved"]
        if resolved_events:
            break

    assert state.missions["m1"].status == MissionStatus.resolved
    # Lives at risk (minus casualties) added to lives_saved
    assert state.lives_saved > 0
    # Resources returned to pools
    assert state.pools["rescue_crew"].available == 1
    assert state.pools["ambulance"].available == 1


# ---------------------------------------------------------------------------
# Deadline failure
# ---------------------------------------------------------------------------


def test_deadline_failure_loses_lives_and_returns_resources():
    """A mission past its deadline fails, loses remaining lives, and resources return."""
    state = make_minimal_state()
    _add_open_mission(
        state, "m1", MissionKind.collapse_rescue,
        required={"rescue_crew": 1, "ambulance": 1},
        assigned={"rescue_crew": 1, "ambulance": 1},
        lives=8,
        spawned_tick=0,
        deadline_tick=3,  # will fail at tick 3
    )
    state.pools["rescue_crew"].available = 0
    state.pools["ambulance"].available = 0

    rng = dummy_rng()
    # Tick 3 is deadline — should fail
    events = scheduled_events(state, 3, rng)

    failed_events = [e for e in events if e.kind == "mission_failed"]
    assert len(failed_events) >= 1
    assert state.missions["m1"].status == MissionStatus.failed

    # Resources returned
    assert state.pools["rescue_crew"].available == 1
    assert state.pools["ambulance"].available == 1

    # Panic increased due to failure
    assert state.panic > 0.0


# ---------------------------------------------------------------------------
# Fire spread after 6 open ticks
# ---------------------------------------------------------------------------


def test_fire_spread_after_6_ticks():
    """A fire mission open for 6 ticks gets severity+1 and lives_at_risk+5."""
    from aftershock.town.state import Mission

    state = make_minimal_state()
    state.missions["m1"] = Mission(
        id="m1",
        kind=MissionKind.fire,
        district_id="old_town",
        severity=2,
        lives_at_risk=10,
        spawned_tick=0,
        deadline_tick=30,
        required={"fire_engine": 1},
        assigned={},
        progress=0.0,
        status=MissionStatus.open,
        priority=0,
    )

    rng = dummy_rng()
    # At tick 6: open_ticks = 6 - 0 = 6 >= 6 -> should spread
    events = scheduled_events(state, 6, rng)

    spread_events = [e for e in events if e.kind == "fire_spread"]
    assert len(spread_events) == 1
    assert state.missions["m1"].severity == 3
    assert state.missions["m1"].lives_at_risk >= 15  # was 10, added 5 (minus casualties)


def test_fire_spread_only_once():
    """Fire spread only triggers once per mission (severity must be < 5)."""
    from aftershock.town.state import Mission

    state = make_minimal_state()
    state.missions["m1"] = Mission(
        id="m1",
        kind=MissionKind.fire,
        district_id="old_town",
        severity=4,
        lives_at_risk=20,
        spawned_tick=0,
        deadline_tick=30,
        required={"fire_engine": 1},
        assigned={},
        progress=0.0,
        status=MissionStatus.open,
    )

    rng = dummy_rng()
    events = scheduled_events(state, 6, rng)
    spread_events = [e for e in events if e.kind == "fire_spread"]
    assert len(spread_events) == 1
    assert state.missions["m1"].severity == 5

    # Second run at tick 7 — severity already at max (5), no more spread
    events2 = scheduled_events(state, 7, rng)
    spread_events2 = [e for e in events2 if e.kind == "fire_spread"]
    assert len(spread_events2) == 0


# ---------------------------------------------------------------------------
# Scripted society saves lives — end-to-end Engine run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scripted_society_saves_lives(tmp_path: Path):
    """The scripted society as a whole CAN save lives in a short Engine run."""
    from aftershock.kernel.engine import Engine
    from aftershock.kernel.recorder import Recorder

    roles = load_roles(ROLES_DIR)
    registry = make_registry()
    state = new_town(42)

    society = TownSociety()
    resolver = TownResolver()

    agents = {
        "commander": CommanderScripted("commander", "commander"),
        "medical": MedicalScripted("medical", "medical"),
        "rescue": RescueScripted("rescue", "rescue"),
        "fire": FireScripted("fire", "fire"),
        "infrastructure": InfraScripted("infrastructure", "infrastructure"),
        "comms": CommsScripted("comms", "comms"),
    }

    recorder = Recorder(tmp_path, "test-scripted", {"seed": 42})

    engine = Engine(
        world=state,
        society=society,
        agents=agents,
        registry=registry,
        roles=roles,
        resolver=resolver,
        recorder=recorder,
        seed=42,
        max_ticks=40,
        agent_timeout_s=10.0,
    )

    summary = await engine.run()

    assert summary.ticks_run > 0
    assert summary.final_scores["lives_saved"] > 0, (
        f"Expected > 0 lives saved, got {summary.final_scores['lives_saved']}. "
        f"Lives lost: {summary.final_scores['lives_lost']}"
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_score_all_keys_present():
    """score() returns all required float keys."""
    state = make_minimal_state()
    s = score(state, 0)
    expected_keys = {
        "lives_saved", "lives_lost", "missions_open", "missions_resolved",
        "missions_failed", "panic", "resource_utilization", "avg_response_ticks",
    }
    assert set(s.keys()) == expected_keys
    for k, v in s.items():
        assert isinstance(v, float), f"{k} should be float, got {type(v)}"


# ---------------------------------------------------------------------------
# Society protocol compliance
# ---------------------------------------------------------------------------


def test_town_society_agent_ids():
    society = TownSociety()
    ids = society.agent_ids()
    assert set(ids) == {"commander", "medical", "rescue", "fire", "infrastructure", "comms"}


def test_town_society_role_of():
    society = TownSociety()
    for agent_id in society.agent_ids():
        assert society.role_of(agent_id) == agent_id


def test_town_society_world_state_sorted():
    """world_state returns the canonical sorted dict."""
    state = new_town(42)
    ws = TownSociety().world_state(state)
    assert "tick" in ws
    assert "missions" in ws
    assert "pools" in ws
    assert "districts" in ws


def test_town_society_is_over_when_no_open_missions():
    """is_over returns True when timeline is exhausted and no open missions."""
    state = make_minimal_state()  # no timeline, no missions
    society = TownSociety()
    assert society.is_over(state, 50)


def test_town_society_not_over_with_open_mission():
    state = make_minimal_state()
    _add_open_mission(state, "m1", MissionKind.fire)
    society = TownSociety()
    assert not society.is_over(state, 1)


# ---------------------------------------------------------------------------
# Roles load correctly
# ---------------------------------------------------------------------------


def test_roles_load():
    """All 6 role YAML files load and have correct names and decision envelopes."""
    roles = load_roles(ROLES_DIR)
    assert set(roles.keys()) == {
        "commander", "medical", "rescue", "fire", "infrastructure", "comms"
    }
    assert "set_priority" in roles["commander"].allowed_decisions
    assert "broadcast" in roles["comms"].allowed_decisions
    assert "repair_road" in roles["infrastructure"].allowed_decisions
    # dispatch must NOT appear in any role envelope
    for role_name, role_spec in roles.items():
        assert "dispatch" not in role_spec.allowed_decisions, (
            f"dispatch must not be in role envelope: {role_name}"
        )
