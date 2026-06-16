"""World dynamics for the town society.

`scheduled_events` is called by the engine in phase 6 (WORLD).
Steps are applied in strict order per DESIGN.md:
  1. Arrivals
  2. Progress & decay (missions in sorted id order)
  3. Timeline spawns
  4. Fire spread
  5. Panic decay
"""

from __future__ import annotations

import random

from aftershock.kernel.protocol import WorldEvent
from aftershock.town.state import (
    DEADLINE_TICKS,
    PANIC_DECAY,
    PANIC_PER_FAILURE,
    PANIC_PER_SPAWN,
    PROGRESS_PER_TICK,
    Mission,
    MissionKind,
    MissionStatus,
    PendingArrival,
    TownState,
    _make_required,
)

# Fire spread triggers after this many open ticks.
# Set to 5: a fully-staffed fire resolves in 4 ticks (PROGRESS_PER_TICK=0.25),
# so spread is unreachable for fast response but activates for neglected fires.
FIRE_SPREAD_TICKS = 5


def _next_event_id(state: TownState, events: list[WorldEvent]) -> str:
    return f"ev-{state.tick}-{len(events)}"


def scheduled_events(
    state: TownState,
    tick: int,
    rng: random.Random,
    injections: list[tuple[str, str, str]] | None = None,
) -> list[WorldEvent]:
    """Apply all world dynamics for this tick, return accumulated WorldEvents."""
    events: list[WorldEvent] = []

    # ------------------------------------------------------------------
    # Step 1: Arrivals — pending entries with due_tick <= tick land
    # ------------------------------------------------------------------
    still_pending: list[PendingArrival] = []
    # Sort for determinism
    due = sorted(
        (pa for pa in state.pending if pa.due_tick <= tick),
        key=lambda pa: (pa.due_tick, pa.mission_id, pa.resource),
    )
    for pa in due:
        if pa.resource == "road_unblock":
            dist = state.districts.get(pa.district_id)
            if dist is not None and dist.road_blocked:
                dist.road_blocked = False
                events.append(WorldEvent(
                    event_id=_next_event_id(state, events),
                    tick=tick,
                    kind="road_unblocked",
                    payload={"district_id": pa.district_id},
                ))
        elif pa.mission_id == "" and pa.resource != "road_unblock":
            # Pool-return arrival: a consumed resource (e.g. repair_crew) returning
            # after its job is done.  mission_id is empty — credit the pool directly.
            pool = state.pools.get(pa.resource)
            if pool is not None:
                pool.available += pa.qty
                events.append(WorldEvent(
                    event_id=_next_event_id(state, events),
                    tick=tick,
                    kind="arrival",
                    payload={
                        "resource": pa.resource,
                        "qty": pa.qty,
                        "direction": "pool_return",
                    },
                ))
        else:
            # Dispatch arrival: assign resources to mission.
            # Pool was already decremented at dispatch time (resources are "in transit"),
            # so we just assign to the mission here.
            # If the mission is no longer open (resolved or failed before arrival landed),
            # return the reserved qty to the pool instead of dropping it.
            mission = state.missions.get(pa.mission_id)
            if mission is not None and mission.status == MissionStatus.open:
                mission.assigned[pa.resource] = (
                    mission.assigned.get(pa.resource, 0) + pa.qty
                )
                events.append(WorldEvent(
                    event_id=_next_event_id(state, events),
                    tick=tick,
                    kind="arrival",
                    payload={
                        "mission_id": pa.mission_id,
                        "resource": pa.resource,
                        "qty": pa.qty,
                    },
                ))
            else:
                # Mission gone — return reserved units to pool (prevents leak)
                pool = state.pools.get(pa.resource)
                if pool is not None:
                    pool.available += pa.qty
                    events.append(WorldEvent(
                        event_id=_next_event_id(state, events),
                        tick=tick,
                        kind="arrival",
                        payload={
                            "mission_id": pa.mission_id,
                            "resource": pa.resource,
                            "qty": pa.qty,
                            "direction": "pool_return_mission_closed",
                        },
                    ))

    # Keep entries that are not yet due
    for pa in state.pending:
        if pa.due_tick > tick:
            still_pending.append(pa)
    state.pending = still_pending

    # ------------------------------------------------------------------
    # Step 2: Progress & decay (sorted mission id order)
    # ------------------------------------------------------------------
    for mid in sorted(state.missions):
        mission = state.missions[mid]
        if mission.status != MissionStatus.open:
            continue

        # Staffing ratio = min over required kinds of assigned/required
        ratios: list[float] = []
        for res, req_qty in mission.required.items():
            assigned_qty = mission.assigned.get(res, 0)
            ratios.append(assigned_qty / req_qty)
        ratio = min(ratios) if ratios else 0.0

        # Progress
        progress_gain = PROGRESS_PER_TICK * ratio
        mission.progress += progress_gain
        if progress_gain > 0:
            events.append(WorldEvent(
                event_id=_next_event_id(state, events),
                tick=tick,
                kind="mission_progress",
                payload={
                    "mission_id": mid,
                    "progress": mission.progress,
                    "ratio": ratio,
                },
            ))

        # Casualties: each open mission loses lives per tick.
        # Rate 0.25 ensures severity>=2 missions drip ~1 life/tick, making
        # slow response visibly costly rather than zero for most seeds.
        casualty_count = round(0.25 * mission.severity * (1 + state.panic))
        casualty_count = max(0, min(casualty_count, mission.lives_at_risk))
        if casualty_count > 0:
            mission.lives_at_risk -= casualty_count
            mission.lives_at_risk = max(0, mission.lives_at_risk)
            state.lives_lost += casualty_count
            events.append(WorldEvent(
                event_id=_next_event_id(state, events),
                tick=tick,
                kind="casualties",
                payload={"mission_id": mid, "count": casualty_count},
            ))

        # Check resolution — must re-read after possible casualty update
        if mission.progress >= 1.0:
            # Resolved: save remaining lives, return resources
            saved = mission.lives_at_risk
            state.lives_saved += saved
            mission.lives_at_risk = 0
            mission.status = MissionStatus.resolved
            mission.resolved_tick = tick
            _reclaim_pending_for_mission(state, mission)
            _return_resources(state, mission)
            events.append(WorldEvent(
                event_id=_next_event_id(state, events),
                tick=tick,
                kind="mission_resolved",
                payload={"mission_id": mid, "resolved_tick": tick, "lives_saved": saved},
            ))
        elif tick >= mission.deadline_tick:
            # Failed: lose remaining lives, return resources
            lost_at_failure = mission.lives_at_risk
            state.lives_lost += lost_at_failure
            mission.lives_at_risk = 0
            mission.status = MissionStatus.failed
            state.panic = min(1.0, state.panic + PANIC_PER_FAILURE)
            _reclaim_pending_for_mission(state, mission)
            _return_resources(state, mission)
            events.append(WorldEvent(
                event_id=_next_event_id(state, events),
                tick=tick,
                kind="mission_failed",
                payload={"mission_id": mid, "lives_lost": lost_at_failure},
            ))
            events.append(WorldEvent(
                event_id=_next_event_id(state, events),
                tick=tick,
                kind="panic_changed",
                payload={"panic": state.panic, "reason": "mission_failed"},
            ))

    # ------------------------------------------------------------------
    # Step 3: Timeline — drain injections first, then spawn this tick's entries
    # ------------------------------------------------------------------
    if injections:
        for inj_kind, inj_district_id, _inj_event_id in injections:
            if inj_kind == "road_block":
                dist = state.districts.get(inj_district_id)
                if dist is not None and not dist.road_blocked:
                    dist.road_blocked = True
                    state.panic = min(1.0, state.panic + PANIC_PER_SPAWN)
                    events.append(WorldEvent(
                        event_id=_next_event_id(state, events),
                        tick=tick,
                        kind="road_blocked",
                        payload={"district_id": inj_district_id, "injected": True},
                    ))
                    events.append(WorldEvent(
                        event_id=_next_event_id(state, events),
                        tick=tick,
                        kind="panic_changed",
                        payload={"panic": state.panic, "reason": "road_blocked"},
                    ))
            else:
                # "fire" spawns a fire mission; "aftershock" spawns a collapse_rescue mission
                if inj_kind == "fire":
                    mission_kind = MissionKind.fire
                else:
                    mission_kind = MissionKind.collapse_rescue
                severity = 2
                lives = severity * 5
                mid = f"m{state.next_mission_no}"
                state.next_mission_no += 1
                deadline = tick + DEADLINE_TICKS[mission_kind]
                required = _make_required(mission_kind, severity)
                mission = Mission(
                    id=mid,
                    kind=mission_kind,
                    district_id=inj_district_id,
                    severity=severity,
                    lives_at_risk=lives,
                    spawned_tick=tick,
                    deadline_tick=deadline,
                    required=required,
                    assigned={},
                    progress=0.0,
                    status=MissionStatus.open,
                )
                state.missions[mid] = mission
                state.panic = min(1.0, state.panic + PANIC_PER_SPAWN)
                events.append(WorldEvent(
                    event_id=_next_event_id(state, events),
                    tick=tick,
                    kind="mission_spawned",
                    payload={
                        "mission_id": mid,
                        "mission_kind": mission_kind,
                        "district_id": inj_district_id,
                        "severity": severity,
                        "lives_at_risk": lives,
                        "deadline_tick": deadline,
                        "injected": True,
                        "inject_kind": inj_kind,
                    },
                ))
                events.append(WorldEvent(
                    event_id=_next_event_id(state, events),
                    tick=tick,
                    kind="panic_changed",
                    payload={"panic": state.panic, "reason": "mission_spawned"},
                ))

    for entry in state.timeline:
        if entry.tick != tick:
            continue
        if entry.kind == "mission":
            mid = f"m{state.next_mission_no}"
            state.next_mission_no += 1
            deadline = tick + DEADLINE_TICKS[entry.mission_kind]
            required = _make_required(entry.mission_kind, entry.severity)
            mission = Mission(
                id=mid,
                kind=entry.mission_kind,
                district_id=entry.district_id,
                severity=entry.severity,
                lives_at_risk=entry.lives_at_risk,
                spawned_tick=tick,
                deadline_tick=deadline,
                required=required,
                assigned={},
                progress=0.0,
                status=MissionStatus.open,
            )
            state.missions[mid] = mission
            state.panic = min(1.0, state.panic + PANIC_PER_SPAWN)
            events.append(WorldEvent(
                event_id=_next_event_id(state, events),
                tick=tick,
                kind="mission_spawned",
                payload={
                    "mission_id": mid,
                    "mission_kind": entry.mission_kind,
                    "district_id": entry.district_id,
                    "severity": entry.severity,
                    "lives_at_risk": entry.lives_at_risk,
                    "deadline_tick": deadline,
                },
            ))
            events.append(WorldEvent(
                event_id=_next_event_id(state, events),
                tick=tick,
                kind="panic_changed",
                payload={"panic": state.panic, "reason": "mission_spawned"},
            ))
        elif entry.kind == "blockage":
            dist = state.districts.get(entry.district_id)
            if dist is not None and not dist.road_blocked:
                dist.road_blocked = True
                state.panic = min(1.0, state.panic + PANIC_PER_SPAWN)
                events.append(WorldEvent(
                    event_id=_next_event_id(state, events),
                    tick=tick,
                    kind="road_blocked",
                    payload={"district_id": entry.district_id},
                ))
                events.append(WorldEvent(
                    event_id=_next_event_id(state, events),
                    tick=tick,
                    kind="panic_changed",
                    payload={"panic": state.panic, "reason": "road_blocked"},
                ))

    # ------------------------------------------------------------------
    # Step 4: Fire spread — fire open >= FIRE_SPREAD_TICKS gets severity+1
    #         once per mission (spread_applied guards the one-shot)
    # ------------------------------------------------------------------
    for mid in sorted(state.missions):
        mission = state.missions[mid]
        if mission.status != MissionStatus.open:
            continue
        if mission.kind != MissionKind.fire:
            continue
        if mission.spread_applied:
            continue
        open_ticks = tick - mission.spawned_tick
        if open_ticks >= FIRE_SPREAD_TICKS and mission.severity < 5:
            mission.severity = min(5, mission.severity + 1)
            mission.lives_at_risk += 5
            mission.spread_applied = True
            events.append(WorldEvent(
                event_id=_next_event_id(state, events),
                tick=tick,
                kind="fire_spread",
                payload={
                    "mission_id": mid,
                    "new_severity": mission.severity,
                    "lives_at_risk": mission.lives_at_risk,
                },
            ))

    # ------------------------------------------------------------------
    # Step 5: Panic decay
    # ------------------------------------------------------------------
    old_panic = state.panic
    state.panic = max(0.0, state.panic - PANIC_DECAY)
    if abs(state.panic - old_panic) > 1e-9:
        events.append(WorldEvent(
            event_id=_next_event_id(state, events),
            tick=tick,
            kind="panic_changed",
            payload={"panic": state.panic, "reason": "decay"},
        ))

    return events


def _return_resources(state: TownState, mission: Mission) -> None:
    """Return all assigned resources from a completed/failed mission back to pools."""
    for resource, qty in mission.assigned.items():
        pool = state.pools.get(resource)
        if pool is not None and qty > 0:
            pool.available += qty
    mission.assigned = {}


def _reclaim_pending_for_mission(state: TownState, mission: Mission) -> None:
    """Return any still-pending (in-transit) reserved units for a closed mission."""
    kept: list[PendingArrival] = []
    for pa in state.pending:
        if pa.mission_id == mission.id and pa.resource != "road_unblock":
            # Units were reserved at dispatch time; return them now
            pool = state.pools.get(pa.resource)
            if pool is not None:
                pool.available += pa.qty
        else:
            kept.append(pa)
    state.pending = kept
