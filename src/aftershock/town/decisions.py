"""Registered decision handlers for the town society.

Handlers:
  - dispatch      pool -> mission (or pending with +2 ticks if road blocked)
  - recall        mission -> pool
  - set_priority  commander only (0-10)
  - repair_road   consumes repair_crew for ROAD_REPAIR_TICKS ticks
  - broadcast     comms; panic -0.1

Note: dispatch has NO role envelope — it enters the world only as an
auction-granted decision (allowed=None path in the registry).
"""

from __future__ import annotations

import random
from typing import Any

from pydantic import BaseModel, Field

from aftershock.kernel.protocol import WorldEvent
from aftershock.kernel.registry import DecisionHandler
from aftershock.town.state import (
    ROAD_REPAIR_TICKS,
    MissionStatus,
    PendingArrival,
    ResourceKind,
    TownState,
)

# Dispatch delay (ticks) added when the district road is blocked
BLOCKED_DISPATCH_DELAY = 2

# Broadcast max length
BROADCAST_MAX_LEN = 280

# Panic reduction for broadcast
BROADCAST_PANIC_REDUCTION = 0.1


# ---------------------------------------------------------------------------
# Params models
# ---------------------------------------------------------------------------


class DispatchParams(BaseModel):
    mission_id: str
    resource: str
    qty: int = Field(ge=1)


class RecallParams(BaseModel):
    mission_id: str
    resource: str
    qty: int = Field(ge=1)


class SetPriorityParams(BaseModel):
    mission_id: str
    priority: int = Field(ge=0, le=10)


class RepairRoadParams(BaseModel):
    district_id: str


class BroadcastParams(BaseModel):
    message: str = Field(max_length=BROADCAST_MAX_LEN)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


class DispatchHandler(DecisionHandler):
    """Move resources from pool to mission (or queue as pending if road blocked)."""

    decision_type = "dispatch"
    Params = DispatchParams

    def validate(self, world: Any, params: BaseModel) -> str | None:
        assert isinstance(params, DispatchParams)
        state: TownState = world
        mission = state.missions.get(params.mission_id)
        if mission is None:
            return f"mission {params.mission_id!r} not found"
        if mission.status != MissionStatus.open:
            return f"mission {params.mission_id!r} is not open"
        if params.resource not in mission.required:
            return f"resource {params.resource!r} not required by mission {params.mission_id!r}"
        pool = state.pools.get(params.resource)
        if pool is None:
            return f"unknown resource kind {params.resource!r}"
        if pool.available < params.qty:
            return f"pool {params.resource!r} has {pool.available} available, need {params.qty}"
        return None

    def apply(
        self,
        world: Any,
        params: BaseModel,
        tick: int,
        rng: random.Random,
    ) -> list[WorldEvent]:
        assert isinstance(params, DispatchParams)
        state: TownState = world
        mission = state.missions[params.mission_id]
        district = state.districts.get(mission.district_id)
        pool = state.pools[params.resource]

        # Apply-time guard: re-check pool availability in case another decision
        # (e.g. repair_road) already consumed units since auction validation.
        if pool.available < params.qty:
            return []

        if district is not None and district.road_blocked:
            # Queue as pending arrival
            due_tick = tick + BLOCKED_DISPATCH_DELAY
            state.pending.append(PendingArrival(
                due_tick=due_tick,
                mission_id=params.mission_id,
                resource=params.resource,
                qty=params.qty,
            ))
            # Reserve from pool immediately
            pool.available -= params.qty
            return [
                WorldEvent(
                    event_id=f"dispatch-pending-{tick}-{params.mission_id}-{params.resource}",
                    tick=tick,
                    kind="arrival",
                    payload={
                        "mission_id": params.mission_id,
                        "resource": params.resource,
                        "qty": params.qty,
                        "pending_due": due_tick,
                        "road_blocked": True,
                    },
                )
            ]
        else:
            # Immediate dispatch
            pool.available -= params.qty
            mission.assigned[params.resource] = (
                mission.assigned.get(params.resource, 0) + params.qty
            )
            return [
                WorldEvent(
                    event_id=f"dispatch-{tick}-{params.mission_id}-{params.resource}",
                    tick=tick,
                    kind="arrival",
                    payload={
                        "mission_id": params.mission_id,
                        "resource": params.resource,
                        "qty": params.qty,
                        "road_blocked": False,
                    },
                )
            ]


class RecallHandler(DecisionHandler):
    """Return resources from a mission back to the pool."""

    decision_type = "recall"
    Params = RecallParams

    def validate(self, world: Any, params: BaseModel) -> str | None:
        assert isinstance(params, RecallParams)
        state: TownState = world
        mission = state.missions.get(params.mission_id)
        if mission is None:
            return f"mission {params.mission_id!r} not found"
        if mission.status != MissionStatus.open:
            return f"mission {params.mission_id!r} is not open"
        assigned_qty = mission.assigned.get(params.resource, 0)
        if assigned_qty < params.qty:
            return (
                f"mission {params.mission_id!r} has {assigned_qty} "
                f"{params.resource!r} assigned, cannot recall {params.qty}"
            )
        return None

    def apply(
        self,
        world: Any,
        params: BaseModel,
        tick: int,
        rng: random.Random,
    ) -> list[WorldEvent]:
        assert isinstance(params, RecallParams)
        state: TownState = world
        mission = state.missions[params.mission_id]
        pool = state.pools[params.resource]

        mission.assigned[params.resource] -= params.qty
        pool.available += params.qty

        return [
            WorldEvent(
                event_id=f"recall-{tick}-{params.mission_id}-{params.resource}",
                tick=tick,
                kind="arrival",
                payload={
                    "mission_id": params.mission_id,
                    "resource": params.resource,
                    "qty": params.qty,
                    "direction": "recall",
                },
            )
        ]


class SetPriorityHandler(DecisionHandler):
    """Set mission priority (0-10). Commander only — enforced by role envelope."""

    decision_type = "set_priority"
    Params = SetPriorityParams

    def validate(self, world: Any, params: BaseModel) -> str | None:
        assert isinstance(params, SetPriorityParams)
        state: TownState = world
        mission = state.missions.get(params.mission_id)
        if mission is None:
            return f"mission {params.mission_id!r} not found"
        return None

    def apply(
        self,
        world: Any,
        params: BaseModel,
        tick: int,
        rng: random.Random,
    ) -> list[WorldEvent]:
        assert isinstance(params, SetPriorityParams)
        state: TownState = world
        mission = state.missions[params.mission_id]
        old_priority = mission.priority
        mission.priority = params.priority
        return [
            WorldEvent(
                event_id=f"set_priority-{tick}-{params.mission_id}",
                tick=tick,
                kind="mission_progress",
                payload={
                    "mission_id": params.mission_id,
                    "old_priority": old_priority,
                    "new_priority": params.priority,
                    "action": "set_priority",
                },
            )
        ]


class RepairRoadHandler(DecisionHandler):
    """Consume a repair_crew for ROAD_REPAIR_TICKS ticks then unblock the road."""

    decision_type = "repair_road"
    Params = RepairRoadParams

    def validate(self, world: Any, params: BaseModel) -> str | None:
        assert isinstance(params, RepairRoadParams)
        state: TownState = world
        district = state.districts.get(params.district_id)
        if district is None:
            return f"district {params.district_id!r} not found"
        if not district.road_blocked:
            return f"road in district {params.district_id!r} is not blocked"
        pool = state.pools.get(ResourceKind.repair_crew)
        if pool is None or pool.available < 1:
            return "no repair_crew available"
        return None

    def apply(
        self,
        world: Any,
        params: BaseModel,
        tick: int,
        rng: random.Random,
    ) -> list[WorldEvent]:
        assert isinstance(params, RepairRoadParams)
        state: TownState = world
        pool = state.pools[ResourceKind.repair_crew]
        pool.available -= 1

        due_tick = tick + ROAD_REPAIR_TICKS
        state.pending.append(PendingArrival(
            due_tick=due_tick,
            mission_id="",
            resource="road_unblock",
            qty=1,
            district_id=params.district_id,
        ))
        # Return the repair_crew unit to the pool when the road is unblocked
        state.pending.append(PendingArrival(
            due_tick=due_tick,
            mission_id="",
            resource=ResourceKind.repair_crew,
            qty=1,
            district_id="",
        ))

        return [
            WorldEvent(
                event_id=f"repair_road-{tick}-{params.district_id}",
                tick=tick,
                kind="road_blocked",
                payload={
                    "district_id": params.district_id,
                    "repair_started": True,
                    "due_tick": due_tick,
                },
            )
        ]


class BroadcastHandler(DecisionHandler):
    """Send a broadcast message; reduces panic by 0.1."""

    decision_type = "broadcast"
    Params = BroadcastParams

    def validate(self, world: Any, params: BaseModel) -> str | None:
        assert isinstance(params, BroadcastParams)
        if len(params.message) > BROADCAST_MAX_LEN:
            return f"message exceeds {BROADCAST_MAX_LEN} characters"
        return None

    def apply(
        self,
        world: Any,
        params: BaseModel,
        tick: int,
        rng: random.Random,
    ) -> list[WorldEvent]:
        assert isinstance(params, BroadcastParams)
        state: TownState = world
        state.panic = max(0.0, state.panic - BROADCAST_PANIC_REDUCTION)
        return [
            WorldEvent(
                event_id=f"broadcast-{tick}",
                tick=tick,
                kind="panic_changed",
                payload={
                    "panic": state.panic,
                    "reason": "broadcast",
                    "message": params.message,
                },
            )
        ]


def make_registry_with_town_handlers() -> None:
    """Register all town decision handlers into a DecisionRegistry.

    Caller imports this and uses it to build the registry.
    """


def register_all(registry: Any) -> None:
    """Register all town handlers into the given DecisionRegistry."""
    registry.register(DispatchHandler())
    registry.register(RecallHandler())
    registry.register(SetPriorityHandler())
    registry.register(RepairRoadHandler())
    registry.register(BroadcastHandler())
