"""Prompt documentation and LLM agent factory for the town society.

DECISION_DOCS  — one usage line per registered decision type (five total).
PROPOSAL_DOCS  — one usage line per ProposalKind value (four total).
build_llm_agents — constructs six LLMAgents for the town society.
"""

from __future__ import annotations

from aftershock.kernel.agents import Agent
from aftershock.kernel.roles import RoleSpec
from aftershock.llm.agent import LLMAgent
from aftershock.llm.contract import decision_contract
from aftershock.llm.provider import Provider

# ---------------------------------------------------------------------------
# Decision documentation (one line per handler registered in decisions.py)
# ---------------------------------------------------------------------------

DECISION_DOCS: dict[str, str] = {
    # NOTE: 'dispatch' is intentionally documented here but never included in any role's
    # allowed_decisions — dispatch is auction-granted only (decisions.py:10-12) and
    # decision_contract() filters by allowed, so this string never reaches an agent prompt.
    # Do NOT add 'dispatch' to a role's allowed_decisions; that would let agents bypass
    # the auction.  The doc string is kept for completeness (test_prompts.py:33-34 pins the
    # full DECISION_DOCS key set).
    "dispatch": (
        "dispatch {mission_id, resource, qty}: move pool resources to a mission — "
        "auction-granted only; agents must use resource_request proposals instead of issuing "
        "dispatch decisions directly"
    ),
    "recall": (
        "recall {mission_id, resource, qty}: return assigned resources from a mission back "
        "to the shared pool when they are no longer needed"
    ),
    "set_priority": (
        "set_priority {mission_id, priority 0-10}: set a mission's auction priority; "
        "higher priority wins resource_request auctions over lower-priority missions"
    ),
    "repair_road": (
        "repair_road {district_id}: consume one repair_crew for several ticks to unblock "
        "a road, restoring full-speed dispatch to that district"
    ),
    "broadcast": (
        "broadcast {message <= 280 chars}: transmit a public message that reduces panic "
        "by 0.1; keep messages calm and specific"
    ),
}

# ---------------------------------------------------------------------------
# Proposal documentation (one line per ProposalKind value)
# ---------------------------------------------------------------------------

PROPOSAL_DOCS: dict[str, str] = {
    "resource_request": (
        "resource_request body {mission_id, resource, qty, urgency 1-10}: bid in the "
        "contested-resource auction; the auction ranks bids by mission priority, severity, "
        "deadline, and urgency — if outbid the ruling names what won, so adjust urgency or "
        "reassess before re-bidding"
    ),
    "task_handoff": (
        "task_handoff: transfer responsibility for a task to a specific recipient agent; "
        "set recipient to the target agent_id"
    ),
    "escalation": (
        "escalation body {mission_id, why}: alert the commander that a mission needs "
        "command-level attention — use when deadline pressure is high and staffing is "
        "critically below requirements"
    ),
    "info_share": (
        "info_share: broadcast situational information to all other agents; no recipient "
        "needed, automatically accepted by the kernel — never grants resources"
    ),
}


# ---------------------------------------------------------------------------
# LLM agent factory
# ---------------------------------------------------------------------------

# The six agent IDs used by TownSociety (role name == agent id)
_TOWN_AGENT_IDS = ("commander", "comms", "fire", "infrastructure", "medical", "rescue")


def build_llm_agents(roles: dict[str, RoleSpec], provider: Provider) -> dict[str, Agent]:
    """Build one LLMAgent per town role, sharing the same provider instance.

    The contract is built once per role from DECISION_DOCS/PROPOSAL_DOCS filtered
    to the role's allowed_decisions.

    Args:
        roles: mapping loaded by load_roles() — must contain all six town roles.
        provider: a Provider instance (QwenProvider or MockProvider).

    Returns:
        dict mapping agent_id -> LLMAgent for all six town agents.
    """
    agents: dict[str, Agent] = {}
    for agent_id in _TOWN_AGENT_IDS:
        role = roles[agent_id]
        contract = decision_contract(
            allowed=role.allowed_decisions,
            decision_docs=DECISION_DOCS,
            proposal_docs=PROPOSAL_DOCS,
        )
        agents[agent_id] = LLMAgent(
            agent_id=agent_id,
            role=role,
            provider=provider,
            contract=contract,
        )
    return agents
