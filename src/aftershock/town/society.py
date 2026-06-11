"""TownSociety and TownResolver.

TownSociety implements the kernel Society protocol.
TownResolver implements the auction for RESOURCE_REQUEST proposals.
"""

from __future__ import annotations

import random
from typing import Any

from aftershock.kernel.negotiation import DefaultResolver
from aftershock.kernel.protocol import (
    Decision,
    Proposal,
    ProposalKind,
    ProposalResponse,
    ProposalRuling,
    WorldEvent,
)
from aftershock.town.events import scheduled_events as _scheduled_events
from aftershock.town.scoring import score as _score
from aftershock.town.state import MissionStatus, TownState

# Valid injectable event kinds and their mapping to timeline entry kinds
_INJECT_KINDS = frozenset({"fire", "aftershock", "road_block"})

# Default six-role mapping: role name == agent id (scripted / society arms)
_DEFAULT_ROSTER: dict[str, str] = {
    "commander": "commander",
    "comms": "comms",
    "fire": "fire",
    "infrastructure": "infrastructure",
    "medical": "medical",
    "rescue": "rescue",
}


class TownSociety:
    """Society implementation for the disaster-response town.

    Args:
        max_ticks:  Optional tick budget; ``is_over`` returns True once reached.
        roster:     Explicit ``{agent_id: role_name}`` mapping.  Defaults to the
                    canonical six-role mapping (role name == agent id) so the
                    scripted-arm determinism tests remain byte-identical.
    """

    def __init__(
        self,
        max_ticks: int | None = None,
        roster: dict[str, str] | None = None,
    ) -> None:
        self._max_ticks = max_ticks
        # Use the supplied roster or fall back to the six-agent default.
        self._roster: dict[str, str] = dict(roster) if roster is not None else dict(_DEFAULT_ROSTER)
        # Pre-compute a stable sorted tuple for agent_ids()
        self._agent_ids: tuple[str, ...] = tuple(sorted(self._roster))
        # Queue of pending injections: list of (kind, district_id, event_id)
        self._injection_queue: list[tuple[str, str, str]] = []
        self._next_inject_no: int = 0

    def agent_ids(self) -> tuple[str, ...]:
        return self._agent_ids

    def role_of(self, agent_id: str) -> str:
        return self._roster[agent_id]

    def build_view(self, world: Any, agent_id: str, tick: int) -> dict[str, Any]:
        """Return a compact world view (everyone sees the same coarse state)."""
        state: TownState = world

        open_missions = []
        for mid in sorted(state.missions):
            m = state.missions[mid]
            if m.status != MissionStatus.open:
                continue
            deadline_in = m.deadline_tick - tick
            open_missions.append({
                "id": m.id,
                "kind": m.kind,
                "district": m.district_id,
                "severity": m.severity,
                "lives_at_risk": m.lives_at_risk,
                "deadline_in": deadline_in,
                "required": dict(sorted(m.required.items())),
                "assigned": dict(sorted(m.assigned.items())),
                "progress": m.progress,
                "priority": m.priority,
            })

        pool_availability = {
            pk: p.available
            for pk, p in sorted(state.pools.items())
        }

        blocked_districts = sorted(
            did for did, d in state.districts.items() if d.road_blocked
        )

        # Totals for context
        totals = {
            "missions_open": sum(
                1 for m in state.missions.values() if m.status == MissionStatus.open
            ),
            "missions_resolved": sum(
                1 for m in state.missions.values() if m.status == MissionStatus.resolved
            ),
            "missions_failed": sum(
                1 for m in state.missions.values() if m.status == MissionStatus.failed
            ),
            "lives_saved": state.lives_saved,
            "lives_lost": state.lives_lost,
        }

        return {
            "tick": tick,
            "panic": state.panic,
            "open_missions": open_missions,
            "pool_availability": pool_availability,
            "blocked_districts": blocked_districts,
            "totals": totals,
        }

    def inject_event(self, kind: str, district_id: str) -> str:
        """Queue an external event to be spawned at the start of the next timeline step.

        Args:
            kind: One of "fire", "aftershock", "road_block".
            district_id: A valid district id in the town state.

        Returns:
            A unique event-id string for this injection.

        Raises:
            ValueError: If kind or district_id are not valid.
        """
        from aftershock.town.state import DISTRICTS

        valid_districts = {did for did, _ in DISTRICTS}
        if kind not in _INJECT_KINDS:
            raise ValueError(
                f"unknown inject kind {kind!r}; valid: {sorted(_INJECT_KINDS)}"
            )
        if district_id not in valid_districts:
            raise ValueError(
                f"unknown district_id {district_id!r}; valid: {sorted(valid_districts)}"
            )
        event_id = f"inject-{self._next_inject_no}"
        self._next_inject_no += 1
        self._injection_queue.append((kind, district_id, event_id))
        return event_id

    def scheduled_events(self, world: Any, tick: int, rng: random.Random) -> list[WorldEvent]:
        state: TownState = world
        state.tick = tick
        # Drain the injection queue and pass it through; events.py will process it
        injections = self._injection_queue[:]
        self._injection_queue.clear()
        return _scheduled_events(state, tick, rng, injections=injections)

    def score(self, world: Any, tick: int) -> dict[str, float]:
        return _score(world, tick)

    def is_over(self, world: Any, tick: int) -> bool:
        state: TownState = world
        # Short-circuit: tick budget exhausted (matches DESIGN.md:298 second disjunct)
        if self._max_ticks is not None and tick >= self._max_ticks:
            return True
        # Timeline exhausted and no open missions
        timeline_ticks = {e.tick for e in state.timeline}
        timeline_exhausted = all(t <= tick for t in timeline_ticks) if timeline_ticks else True
        has_open = any(m.status == MissionStatus.open for m in state.missions.values())
        return timeline_exhausted and not has_open

    def world_state(self, world: Any) -> dict[str, Any]:
        state: TownState = world
        return state.to_dict()


class TownResolver:
    """Auction resolver for RESOURCE_REQUEST proposals.

    Sort key: (mission.priority desc, severity desc, deadline asc, urgency desc, sender asc)
    Winners get a granted dispatch decision; losers get a reason naming the winner.
    Non-RESOURCE_REQUEST proposals fall through to DefaultResolver behaviour.
    """

    name = "auction"
    _default = DefaultResolver()

    def resolve(
        self,
        world: Any,
        tick: int,
        arbiter: list[Proposal],
        answered: list[tuple[Proposal, ProposalResponse]],
        expired: list[Proposal],
        rng: random.Random,
    ) -> tuple[list[ProposalRuling], list[Decision]]:
        state: TownState = world

        # Separate RESOURCE_REQUEST from other arbiter proposals
        resource_requests: list[Proposal] = []
        other_arbiter: list[Proposal] = []
        for prop in arbiter:
            if prop.kind == ProposalKind.RESOURCE_REQUEST:
                resource_requests.append(prop)
            else:
                other_arbiter.append(prop)

        rulings: list[ProposalRuling] = []
        grants: list[Decision] = []

        # --- Auction for RESOURCE_REQUEST ---
        # Group by resource kind
        by_resource: dict[str, list[Proposal]] = {}
        for prop in resource_requests:
            res = prop.body.get("resource", "")
            by_resource.setdefault(res, []).append(prop)

        for resource in sorted(by_resource):
            proposals = by_resource[resource]
            pool = state.pools.get(resource)
            if pool is None:
                for prop in proposals:
                    rulings.append(ProposalRuling(
                        proposal_id=prop.proposal_id,
                        accepted=False,
                        decided_by="kernel:auction",
                        reason=f"unknown resource {resource!r}",
                    ))
                continue

            # Sort: priority desc, severity desc, deadline asc, urgency desc, sender asc
            def sort_key(prop: Proposal) -> tuple[int, int, int, int, str]:
                mission_id = prop.body.get("mission_id", "")
                mission = state.missions.get(mission_id)
                priority = mission.priority if mission else 0
                severity = mission.severity if mission else 0
                deadline = mission.deadline_tick if mission else 9999
                urgency = prop.body.get("urgency", 1)
                return (-priority, -severity, deadline, -urgency, prop.sender)

            sorted_props = sorted(proposals, key=sort_key)
            remaining = pool.available
            # Track how much has already been granted to each mission this tick
            # to avoid over-committing the same mission.
            granted_to_mission: dict[str, int] = {}

            for prop in sorted_props:
                mission_id = prop.body.get("mission_id", "")
                qty = prop.body.get("qty", 1)

                # Cap qty by how much the mission still needs beyond already-granted
                mission = state.missions.get(mission_id)
                already_assigned = (
                    mission.assigned.get(resource, 0) if mission else 0
                )
                already_granted = granted_to_mission.get(mission_id, 0)
                required = mission.required.get(resource, 0) if mission else 0
                still_needed = max(0, required - already_assigned - already_granted)
                effective_qty = min(qty, still_needed)

                if effective_qty <= 0:
                    # Mission already satisfied — decline as redundant
                    rulings.append(ProposalRuling(
                        proposal_id=prop.proposal_id,
                        accepted=False,
                        decided_by="kernel:auction",
                        reason=f"mission {mission_id!r} already has sufficient {resource!r}",
                    ))
                    continue

                if remaining >= effective_qty:
                    # Winner
                    remaining -= effective_qty
                    granted_to_mission[mission_id] = already_granted + effective_qty
                    rulings.append(ProposalRuling(
                        proposal_id=prop.proposal_id,
                        accepted=True,
                        decided_by="kernel:auction",
                        reason="",
                    ))
                    grants.append(Decision(
                        decision_id=f"{prop.proposal_id}-grant",
                        agent_id=prop.sender,
                        decision_type="dispatch",
                        params={
                            "mission_id": mission_id,
                            "resource": resource,
                            "qty": effective_qty,
                        },
                    ))
                else:
                    # Loser — find winner to name in reason
                    winner_mission_id = _find_winner_mission(rulings, grants, resource)
                    winner_priority = 0
                    winner_mission = None
                    if winner_mission_id:
                        winner_mission = state.missions.get(winner_mission_id)
                        winner_priority = winner_mission.priority if winner_mission else 0

                    if winner_mission_id:
                        reason = (
                            f"pool exhausted: {resource} granted to {winner_mission_id} "
                            f"(priority {winner_priority})"
                        )
                    else:
                        avail = pool.available
                        reason = (
                            f"pool exhausted: {resource} has {avail} available, need {qty}"
                        )
                    rulings.append(ProposalRuling(
                        proposal_id=prop.proposal_id,
                        accepted=False,
                        decided_by="kernel:auction",
                        reason=reason,
                    ))

        # --- Fall through non-RESOURCE_REQUEST to DefaultResolver ---
        if other_arbiter or answered or expired:
            default_rulings, default_grants = self._default.resolve(
                world, tick, other_arbiter, answered, expired, rng
            )
            rulings.extend(default_rulings)
            grants.extend(default_grants)

        return rulings, grants


def _find_winner_mission(
    rulings: list[ProposalRuling],
    grants: list[Decision],
    resource: str,
) -> str:
    """Find the last accepted mission id for this resource from granted decisions."""
    for dec in reversed(grants):
        if dec.decision_type == "dispatch" and dec.params.get("resource") == resource:
            return dec.params.get("mission_id", "")
    return ""
