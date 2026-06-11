"""Scripted (heuristic) agents for the town society.

All agents are pure functions of the observation — deterministic with stable
tie-breaking. Decision IDs use f"{agent_id}-{n}" and proposal IDs use
f"{agent_id}-p{n}" where n is a within-tick counter.

Agents:
  CommanderScripted   — set_priority for unprioritised missions
  MedicalScripted     — RESOURCE_REQUEST for medical_surge missions
  RescueScripted      — RESOURCE_REQUEST for collapse_rescue missions
  FireScripted        — RESOURCE_REQUEST for fire missions
  InfraScripted       — RESOURCE_REQUEST for infra_repair + repair_road
  CommsScripted       — broadcast when panic > 0.4
"""

from __future__ import annotations

from aftershock.kernel.agents import ScriptedAgent
from aftershock.kernel.protocol import (
    AgentResponse,
    Decision,
    Observation,
    Proposal,
    ProposalKind,
)

# Threshold: missions with deadline within this many ticks are "urgent"
URGENT_DEADLINE_TICKS = 6

# Priority multiplier
SEVERITY_PRIORITY_MULT = 2
URGENCY_BONUS = 2

# Escalation: deadline within this many ticks + below half staffing
ESCALATION_DEADLINE = 4
ESCALATION_STAFFING_THRESHOLD = 0.5

# Panic threshold for broadcast
PANIC_BROADCAST_THRESHOLD = 0.4

# Mission kinds each specialist handles
_MEDICAL_KINDS = ("medical_surge",)
_RESCUE_KINDS = ("collapse_rescue",)
_FIRE_KINDS = ("fire",)
_INFRA_KINDS = ("infra_repair",)


def _staffing_ratio(mission: dict) -> float:
    """Minimum ratio of assigned/required across all required resource kinds."""
    required = mission.get("required", {})
    assigned = mission.get("assigned", {})
    if not required:
        return 1.0
    ratios = [assigned.get(r, 0) / max(req, 1) for r, req in required.items()]
    return min(ratios)


def _unmet_resources(mission: dict) -> list[tuple[str, int]]:
    """Return list of (resource, shortfall) for resources below required."""
    required = mission.get("required", {})
    assigned = mission.get("assigned", {})
    result = []
    for r, req in sorted(required.items()):
        got = assigned.get(r, 0)
        if got < req:
            result.append((r, req - got))
    return result


def _sort_key_mission(m: dict) -> tuple[int, int, int]:
    """Sort: highest priority first, then highest severity, then earliest deadline."""
    return (-m.get("priority", 0), -m.get("severity", 0), m.get("deadline_in", 9999))


class CommanderScripted(ScriptedAgent):
    """Assigns priority to unprioritised missions; accepts escalations."""

    def act_sync(self, observation: Observation) -> AgentResponse:
        view = observation.view
        open_missions = view.get("open_missions", [])

        decisions: list[Decision] = []
        n = 0

        for mission in sorted(open_missions, key=lambda m: m["id"]):
            # Assign priority to missions that have none (priority == 0)
            if mission.get("priority", 0) == 0:
                severity = mission.get("severity", 1)
                deadline_in = mission.get("deadline_in", 9999)
                urgency_bonus = URGENCY_BONUS if deadline_in <= URGENT_DEADLINE_TICKS else 0
                priority = min(10, severity * SEVERITY_PRIORITY_MULT + urgency_bonus)
                decisions.append(Decision(
                    decision_id=f"{self.agent_id}-{n}",
                    agent_id=self.agent_id,
                    decision_type="set_priority",
                    params={"mission_id": mission["id"], "priority": priority},
                ))
                n += 1

        return AgentResponse(agent_id=self.agent_id, decisions=tuple(decisions))


class MedicalScripted(ScriptedAgent):
    """Requests ambulance/supply_truck resources for medical_surge missions."""

    def act_sync(self, observation: Observation) -> AgentResponse:
        return _specialist_act(self.agent_id, observation, _MEDICAL_KINDS)


class RescueScripted(ScriptedAgent):
    """Requests rescue_crew/ambulance resources for collapse_rescue missions."""

    def act_sync(self, observation: Observation) -> AgentResponse:
        return _specialist_act(self.agent_id, observation, _RESCUE_KINDS)


class FireScripted(ScriptedAgent):
    """Requests fire_engine resources for fire missions."""

    def act_sync(self, observation: Observation) -> AgentResponse:
        return _specialist_act(self.agent_id, observation, _FIRE_KINDS)


class InfraScripted(ScriptedAgent):
    """Requests repair_crew for infra_repair missions; also initiates road repairs."""

    def act_sync(self, observation: Observation) -> AgentResponse:
        view = observation.view
        open_missions = view.get("open_missions", [])
        blocked_districts = view.get("blocked_districts", [])
        pool_availability = view.get("pool_availability", {})

        proposals: list[Proposal] = []
        decisions: list[Decision] = []
        pn = 0
        dn = 0

        # Resource requests for infra missions
        my_missions = sorted(
            [m for m in open_missions if m.get("kind") in _INFRA_KINDS],
            key=_sort_key_mission,
        )

        for mission in my_missions:
            unmet = _unmet_resources(mission)
            for resource, shortfall in unmet:
                available = pool_availability.get(resource, 0)
                if available > 0:
                    qty = min(shortfall, available)
                    urgency = _mission_urgency(mission)
                    proposals.append(Proposal(
                        proposal_id=f"{self.agent_id}-p{pn}",
                        sender=self.agent_id,
                        recipient=None,
                        kind=ProposalKind.RESOURCE_REQUEST,
                        body={
                            "mission_id": mission["id"],
                            "resource": resource,
                            "qty": qty,
                            "urgency": urgency,
                        },
                    ))
                    pn += 1

            # Escalate if deadline near and understaffed
            if (
                mission.get("deadline_in", 9999) <= ESCALATION_DEADLINE
                and _staffing_ratio(mission) < ESCALATION_STAFFING_THRESHOLD
            ):
                proposals.append(Proposal(
                    proposal_id=f"{self.agent_id}-p{pn}",
                    sender=self.agent_id,
                    recipient="commander",
                    kind=ProposalKind.ESCALATION,
                    body={"mission_id": mission["id"], "reason": "deadline_near_understaffed"},
                ))
                pn += 1

        # Repair blocked roads if repair_crew available
        repair_crew_available = pool_availability.get("repair_crew", 0)
        for district_id in sorted(blocked_districts):
            if repair_crew_available > 0:
                decisions.append(Decision(
                    decision_id=f"{self.agent_id}-{dn}",
                    agent_id=self.agent_id,
                    decision_type="repair_road",
                    params={"district_id": district_id},
                ))
                dn += 1
                repair_crew_available -= 1

        return AgentResponse(
            agent_id=self.agent_id,
            decisions=tuple(decisions),
            proposals=tuple(proposals),
        )


class CommsScripted(ScriptedAgent):
    """Broadcasts a calming message when panic > threshold."""

    def act_sync(self, observation: Observation) -> AgentResponse:
        view = observation.view
        panic = view.get("panic", 0.0)
        decisions: list[Decision] = []

        if panic > PANIC_BROADCAST_THRESHOLD:
            decisions.append(Decision(
                decision_id=f"{self.agent_id}-0",
                agent_id=self.agent_id,
                decision_type="broadcast",
                params={"message": "Emergency services are responding. Please remain calm."},
            ))

        return AgentResponse(agent_id=self.agent_id, decisions=tuple(decisions))


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _specialist_act(
    agent_id: str,
    observation: Observation,
    mission_kinds: tuple[str, ...],
) -> AgentResponse:
    """Generic act for medical/rescue/fire specialists."""
    view = observation.view
    open_missions = view.get("open_missions", [])
    pool_availability = view.get("pool_availability", {})

    proposals: list[Proposal] = []
    pn = 0

    my_missions = sorted(
        [m for m in open_missions if m.get("kind") in mission_kinds],
        key=_sort_key_mission,
    )

    for mission in my_missions:
        unmet = _unmet_resources(mission)
        for resource, shortfall in unmet:
            available = pool_availability.get(resource, 0)
            if available > 0:
                qty = min(shortfall, available)
                urgency = _mission_urgency(mission)
                proposals.append(Proposal(
                    proposal_id=f"{agent_id}-p{pn}",
                    sender=agent_id,
                    recipient=None,
                    kind=ProposalKind.RESOURCE_REQUEST,
                    body={
                        "mission_id": mission["id"],
                        "resource": resource,
                        "qty": qty,
                        "urgency": urgency,
                    },
                ))
                pn += 1

        # Escalate to commander if deadline near and understaffed
        if (
            mission.get("deadline_in", 9999) <= ESCALATION_DEADLINE
            and _staffing_ratio(mission) < ESCALATION_STAFFING_THRESHOLD
        ):
            proposals.append(Proposal(
                proposal_id=f"{agent_id}-p{pn}",
                sender=agent_id,
                recipient="commander",
                kind=ProposalKind.ESCALATION,
                body={"mission_id": mission["id"], "reason": "deadline_near_understaffed"},
            ))
            pn += 1

    return AgentResponse(agent_id=agent_id, proposals=tuple(proposals))


def _mission_urgency(mission: dict) -> int:
    """Compute urgency 1-10 based on deadline_in and severity."""
    deadline_in = mission.get("deadline_in", 9999)
    severity = mission.get("severity", 1)
    if deadline_in <= 2:
        return 10
    if deadline_in <= 4:
        return max(7, severity * 2)
    if deadline_in <= URGENT_DEADLINE_TICKS:
        return max(5, severity + 2)
    return max(1, severity)
