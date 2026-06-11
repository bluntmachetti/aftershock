"""Per-tick scoring for the town society.

Returns a dict with exactly:
  lives_saved, lives_lost, missions_open, missions_resolved, missions_failed,
  panic, resource_utilization, avg_response_ticks
All values are floats.
"""

from __future__ import annotations

from aftershock.town.state import MissionStatus, TownState


def score(state: TownState, tick: int) -> dict[str, float]:
    """Compute the score dict from the current world state."""
    missions_open = 0
    missions_resolved = 0
    missions_failed = 0
    response_ticks: list[float] = []

    for mission in state.missions.values():
        if mission.status == MissionStatus.open:
            missions_open += 1
        elif mission.status == MissionStatus.resolved:
            missions_resolved += 1
            if mission.resolved_tick is not None:
                response_ticks.append(float(mission.resolved_tick - mission.spawned_tick))
        elif mission.status == MissionStatus.failed:
            missions_failed += 1

    # Resource utilization: fraction of total capacity in use across all pools
    total_capacity = sum(p.total for p in state.pools.values())
    total_available = sum(p.available for p in state.pools.values())
    total_in_use = total_capacity - total_available
    resource_utilization = total_in_use / total_capacity if total_capacity > 0 else 0.0

    avg_response_ticks = (
        sum(response_ticks) / len(response_ticks) if response_ticks else 0.0
    )

    return {
        "lives_saved": float(state.lives_saved),
        "lives_lost": float(state.lives_lost),
        "missions_open": float(missions_open),
        "missions_resolved": float(missions_resolved),
        "missions_failed": float(missions_failed),
        "panic": float(state.panic),
        "resource_utilization": float(resource_utilization),
        "avg_response_ticks": float(avg_response_ticks),
    }
