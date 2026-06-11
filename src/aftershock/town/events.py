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

# Fire spread triggers after this many open ticks
FIRE_SPREAD_TICKS = 6


def _next_event_id(state: TownState, events: list[WorldEvent]) -> str:
    return f"ev-{state.tick}-{len(events)}"


def scheduled_events(state: TownState, tick: int, rng: random.Random) -> list[WorldEvent]:
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
        else:
            # Dispatch arrival: assign resources to mission.
            # Pool was already decremented at dispatch time (resources are "in transit"),
            # so we just assign to the mission here.
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

        # Casualties: each open mission loses lives per tick
        casualty_count = round(0.1 * mission.severity * (1 + state.panic))
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
            state.lives_saved += mission.lives_at_risk
            mission.lives_at_risk = 0
            mission.status = MissionStatus.resolved
            mission.resolved_tick = tick
            _return_resources(state, mission)
            events.append(WorldEvent(
                event_id=_next_event_id(state, events),
                tick=tick,
                kind="mission_resolved",
                payload={"mission_id": mid, "resolved_tick": tick},
            ))
        elif tick >= mission.deadline_tick:
            # Failed: lose remaining lives, return resources
            state.lives_lost += mission.lives_at_risk
            mission.lives_at_risk = 0
            mission.status = MissionStatus.failed
            state.panic = min(1.0, state.panic + PANIC_PER_FAILURE)
            _return_resources(state, mission)
            events.append(WorldEvent(
                event_id=_next_event_id(state, events),
                tick=tick,
                kind="mission_failed",
                payload={"mission_id": mid},
            ))
            events.append(WorldEvent(
                event_id=_next_event_id(state, events),
                tick=tick,
                kind="panic_changed",
                payload={"panic": state.panic, "reason": "mission_failed"},
            ))

    # ------------------------------------------------------------------
    # Step 3: Timeline — spawn this tick's missions/blockages
    # ------------------------------------------------------------------
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
    # Step 4: Fire spread — fire open >= 6 ticks gets severity+1 (max 5)
    # ------------------------------------------------------------------
    for mid in sorted(state.missions):
        mission = state.missions[mid]
        if mission.status != MissionStatus.open:
            continue
        if mission.kind != MissionKind.fire:
            continue
        open_ticks = tick - mission.spawned_tick
        if open_ticks >= FIRE_SPREAD_TICKS and mission.severity < 5:
            mission.severity = min(5, mission.severity + 1)
            mission.lives_at_risk += 5
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
            pool.available = min(pool.total, pool.available + qty)
    mission.assigned = {}
