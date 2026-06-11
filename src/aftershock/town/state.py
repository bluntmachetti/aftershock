"""TownState: enums, dataclasses, constants, and factory for new_town().

All randomness flows through rng_for; no module-level random calls.
Mission IDs come from next_mission_no counter ("m1", "m2", ...).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from aftershock.kernel.rng import rng_for

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ResourceKind(StrEnum):
    ambulance = "ambulance"
    rescue_crew = "rescue_crew"
    fire_engine = "fire_engine"
    repair_crew = "repair_crew"
    supply_truck = "supply_truck"


class MissionKind(StrEnum):
    collapse_rescue = "collapse_rescue"
    fire = "fire"
    medical_surge = "medical_surge"
    infra_repair = "infra_repair"


class MissionStatus(StrEnum):
    open = "open"
    resolved = "resolved"
    failed = "failed"


# ---------------------------------------------------------------------------
# Constants (module-level UPPERCASE)
# ---------------------------------------------------------------------------

# Starting pool sizes
POOL_SIZES: dict[str, int] = {
    ResourceKind.ambulance: 6,
    ResourceKind.rescue_crew: 5,
    ResourceKind.fire_engine: 4,
    ResourceKind.repair_crew: 3,
    ResourceKind.supply_truck: 4,
}

# Required resources per mission kind (base, scaled by severity)
# Values here are multipliers per severity level
REQUIRED_BASE: dict[str, dict[str, int]] = {
    MissionKind.collapse_rescue: {
        ResourceKind.rescue_crew: 1,
        ResourceKind.ambulance: 1,
    },
    MissionKind.fire: {
        ResourceKind.fire_engine: 1,
    },
    MissionKind.medical_surge: {
        ResourceKind.ambulance: 1,
        ResourceKind.supply_truck: 1,
    },
    MissionKind.infra_repair: {
        ResourceKind.repair_crew: 1,
    },
}

# Fire missions at severity >= 3 also need ambulance
FIRE_AMBULANCE_THRESHOLD = 3

# Deadline: ticks after spawn until mission fails
DEADLINE_TICKS: dict[str, int] = {
    MissionKind.collapse_rescue: 12,
    MissionKind.fire: 10,
    MissionKind.medical_surge: 8,
    MissionKind.infra_repair: 16,
}

# Progress increment per tick at full staffing
PROGRESS_PER_TICK = 0.25  # resolves in 4 ticks at full staffing

# Repair-road duration in ticks
ROAD_REPAIR_TICKS = 3

# District definitions (id, name)
DISTRICTS: list[tuple[str, str]] = [
    ("old_town", "Old Town"),
    ("harbor", "Harbor"),
    ("hospital_district", "Hospital District"),
    ("market", "Market"),
    ("residential_north", "Residential North"),
    ("industrial", "Industrial"),
]

# Panic thresholds
PANIC_PER_SPAWN = 0.05
PANIC_PER_FAILURE = 0.1
PANIC_DECAY = 0.02


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class District:
    id: str
    name: str
    road_blocked: bool = False


@dataclass
class Mission:
    id: str
    kind: str  # MissionKind value
    district_id: str
    severity: int  # 1-5
    lives_at_risk: int
    spawned_tick: int
    deadline_tick: int
    required: dict[str, int]  # resource_kind -> count
    assigned: dict[str, int]  # resource_kind -> count
    progress: float
    status: str  # MissionStatus value
    priority: int = 0
    resolved_tick: int | None = None


@dataclass
class ResourcePool:
    kind: str  # ResourceKind value
    total: int
    available: int


@dataclass
class PendingArrival:
    """Delayed dispatch or returning crew."""

    due_tick: int
    mission_id: str  # empty string for road-unblock events
    resource: str  # ResourceKind value; "road_unblock" for road repairs
    qty: int
    district_id: str = ""  # used for road_unblock arrivals


@dataclass
class TimelineEntry:
    tick: int
    kind: str  # "mission" or "blockage"
    # For missions:
    mission_kind: str = ""
    district_id: str = ""
    severity: int = 0
    lives_at_risk: int = 0


@dataclass
class TownState:
    tick: int
    seed: int
    districts: dict[str, District]  # district_id -> District
    missions: dict[str, Mission]  # mission_id -> Mission
    pools: dict[str, ResourcePool]  # resource_kind -> ResourcePool
    pending: list[PendingArrival]
    timeline: list[TimelineEntry]
    panic: float
    lives_saved: int
    lives_lost: int
    next_mission_no: int

    def to_dict(self) -> dict[str, Any]:
        """Canonical, sorted dict for hashing."""
        return {
            "tick": self.tick,
            "seed": self.seed,
            "panic": self.panic,
            "lives_saved": self.lives_saved,
            "lives_lost": self.lives_lost,
            "next_mission_no": self.next_mission_no,
            "districts": {
                did: {
                    "id": d.id,
                    "name": d.name,
                    "road_blocked": d.road_blocked,
                }
                for did, d in sorted(self.districts.items())
            },
            "missions": {
                mid: {
                    "id": m.id,
                    "kind": m.kind,
                    "district_id": m.district_id,
                    "severity": m.severity,
                    "lives_at_risk": m.lives_at_risk,
                    "spawned_tick": m.spawned_tick,
                    "deadline_tick": m.deadline_tick,
                    "required": dict(sorted(m.required.items())),
                    "assigned": dict(sorted(m.assigned.items())),
                    "progress": m.progress,
                    "status": m.status,
                    "priority": m.priority,
                    "resolved_tick": m.resolved_tick,
                }
                for mid, m in sorted(self.missions.items())
            },
            "pools": {
                pk: {
                    "kind": p.kind,
                    "total": p.total,
                    "available": p.available,
                }
                for pk, p in sorted(self.pools.items())
            },
            "pending": [
                {
                    "due_tick": pa.due_tick,
                    "mission_id": pa.mission_id,
                    "resource": pa.resource,
                    "qty": pa.qty,
                    "district_id": pa.district_id,
                }
                for pa in self.pending
            ],
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _make_required(kind: str, severity: int) -> dict[str, int]:
    """Compute the required resources for a mission, scaled by severity."""
    base = REQUIRED_BASE[kind]
    result = {r: max(1, qty * (1 + (severity - 1) // 2)) for r, qty in base.items()}
    # Fire missions at severity >= FIRE_AMBULANCE_THRESHOLD also need ambulance
    if kind == MissionKind.fire and severity >= FIRE_AMBULANCE_THRESHOLD:
        result[ResourceKind.ambulance] = max(1, (severity - 1) // 2 + 1)
    return result


def new_town(seed: int) -> TownState:
    """Create a fresh TownState with a precomputed scenario timeline.

    The main quake fires at tick 0 (4-6 missions, 1-2 blockages); aftershocks
    near ticks 8-12 and 20-26 add 2-4 missions each with possible blockages.
    All randomness flows through rng_for(seed, "timeline").
    """
    rng = rng_for(seed, "timeline")

    district_ids = [did for did, _ in DISTRICTS]
    district_objs = {did: District(id=did, name=name) for did, name in DISTRICTS}

    pools = {
        k: ResourcePool(kind=k, total=v, available=v)
        for k, v in POOL_SIZES.items()
    }

    timeline: list[TimelineEntry] = []

    # --- Main quake at tick 0 ---
    num_missions_0 = rng.randint(4, 6)
    quake_districts = rng.sample(district_ids, min(num_missions_0, len(district_ids)))
    kinds_pool = list(MissionKind)
    for i in range(num_missions_0):
        d_id = quake_districts[i % len(quake_districts)]
        mk = rng.choice(kinds_pool)
        severity = rng.randint(2, 4)
        lives = severity * rng.randint(4, 8)
        timeline.append(TimelineEntry(
            tick=0,
            kind="mission",
            mission_kind=mk,
            district_id=d_id,
            severity=severity,
            lives_at_risk=lives,
        ))

    # 1-2 road blockages with quake
    num_blocks_0 = rng.randint(1, 2)
    block_districts = rng.sample(district_ids, min(num_blocks_0, len(district_ids)))
    for bd in block_districts:
        timeline.append(TimelineEntry(tick=0, kind="blockage", district_id=bd))

    # --- First aftershock at tick in 8-12 ---
    tick_as1 = rng.randint(8, 12)
    num_missions_1 = rng.randint(2, 4)
    as1_districts = rng.sample(district_ids, min(num_missions_1, len(district_ids)))
    for i in range(num_missions_1):
        d_id = as1_districts[i % len(as1_districts)]
        mk = rng.choice(kinds_pool)
        severity = rng.randint(1, 3)
        lives = severity * rng.randint(3, 6)
        timeline.append(TimelineEntry(
            tick=tick_as1,
            kind="mission",
            mission_kind=mk,
            district_id=d_id,
            severity=severity,
            lives_at_risk=lives,
        ))
    # possible blockage
    if rng.random() < 0.5:
        bd = rng.choice(district_ids)
        timeline.append(TimelineEntry(tick=tick_as1, kind="blockage", district_id=bd))

    # --- Second aftershock at tick in 20-26 ---
    tick_as2 = rng.randint(20, 26)
    num_missions_2 = rng.randint(2, 4)
    as2_districts = rng.sample(district_ids, min(num_missions_2, len(district_ids)))
    for i in range(num_missions_2):
        d_id = as2_districts[i % len(as2_districts)]
        mk = rng.choice(kinds_pool)
        severity = rng.randint(1, 3)
        lives = severity * rng.randint(3, 6)
        timeline.append(TimelineEntry(
            tick=tick_as2,
            kind="mission",
            mission_kind=mk,
            district_id=d_id,
            severity=severity,
            lives_at_risk=lives,
        ))
    if rng.random() < 0.5:
        bd = rng.choice(district_ids)
        timeline.append(TimelineEntry(tick=tick_as2, kind="blockage", district_id=bd))

    return TownState(
        tick=0,
        seed=seed,
        districts=district_objs,
        missions={},
        pools=pools,
        pending=[],
        timeline=timeline,
        panic=0.0,
        lives_saved=0,
        lives_lost=0,
        next_mission_no=1,
    )
