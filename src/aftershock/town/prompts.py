"""Prompt documentation and LLM agent factory for the town society.

DECISION_DOCS        — one usage line per registered decision type (auction-framed; for
                       society arm where dispatch is auction-granted only).
DECISION_DOCS_DIRECT — same decision types but dispatch is documented as directly usable;
                       for swarm/solo arms where agents dispatch without an auction.
PROPOSAL_DOCS        — one usage line per ProposalKind value (four total).
build_llm_agents     — constructs six LLMAgents for the town society.
"""

from __future__ import annotations

from aftershock.kernel.agents import Agent
from aftershock.kernel.roles import RoleSpec
from aftershock.llm.agent import LLMAgent
from aftershock.llm.contract import decision_contract
from aftershock.llm.provider import Provider
from aftershock.town.decisions import (
    BroadcastParams,
    RecallParams,
    RepairRoadParams,
    SetPriorityParams,
)
from aftershock.town.doctrine import Rule, doctrine_blocks, load_doctrine
from aftershock.town.tool_contract import (
    build_role_tools,
    map_tool_calls,
    tool_contract,
)

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
# Direct-dispatch decision documentation (swarm / solo arms)
#
# Identical to DECISION_DOCS except dispatch is documented as directly usable
# (move qty of resource from the pool to a mission you can see).  The other
# four lines are shared copy for consistency, but dispatch is the key change.
# ---------------------------------------------------------------------------

DECISION_DOCS_DIRECT: dict[str, str] = {
    "dispatch": (
        "dispatch {mission_id, resource, qty}: move qty of resource from the pool to a "
        "mission you can see — check pool availability first; rejected if pool lacks units"
    ),
    "recall": (
        "recall {mission_id, resource, qty}: return assigned resources from a mission back "
        "to the shared pool when they are no longer needed"
    ),
    "set_priority": (
        "set_priority {mission_id, priority 0-10}: set a mission's priority; "
        "higher priority missions should receive resources first"
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


def build_llm_agents(
    roles: dict[str, RoleSpec],
    provider: Provider,
    lessons: list[str] | None = None,
    arm: str = "society",
    _doctrine_rules: list[Rule] | None = None,
    force_tools: bool = False,
    engine_seed: int | None = None,
    doctrine: bool = True,
) -> dict[str, Agent]:
    """Build one LLMAgent per town role, sharing the same provider instance.

    The contract is built once per role from DECISION_DOCS/PROPOSAL_DOCS filtered
    to the role's allowed_decisions.  Doctrine blocks (from doctrine.yaml) are
    inserted between the role system_prompt and the contract.

    When lessons are provided, the commander's system_prompt gains a final block:
    "LESSONS FROM PREVIOUS DISASTERS (apply where relevant):" + numbered lessons.
    Other roles are unchanged.

    Doctrine load failure raises at build time — a missing or malformed doctrine.yaml
    is a configuration error that must not be silently skipped.

    Args:
        roles: mapping loaded by load_roles() — must contain all six town roles.
        provider: a Provider instance (QwenProvider or MockProvider).
        lessons: optional list of lesson strings from a previous AAR memory loop.
                 Applied to the commander only; other roles are unaffected.
        arm: the benchmark arm name used to filter doctrine rules (default "society").
        _doctrine_rules: pre-loaded rules list; if None, load_doctrine() is called.
                         Exposed for testing only.
        force_tools: opt-in switch (CLI --society-tools). When True, every role is
                     built in native Qwen function-calling mode regardless of its
                     YAML default (which is JSON). Default False keeps JSON mode —
                     the cost-optimal default the published benchmark uses.
        engine_seed: M1 opt-in (CLI --seed-sampler). When set, every agent sends a
                     deterministic per-tick provider seed derived from this value;
                     None (default) sends no seed (legacy behaviour).
        doctrine: when True (default) each role's prompt gains its TEAM/ROLE
                  DOCTRINE blocks (byte-identical to the published behaviour). When
                  False the doctrine layer is omitted entirely (and doctrine.yaml is
                  not even loaded) — the doctrine-naive control for the doctrine
                  on/off ablation (FIELD-NOTES §11).

    Returns:
        dict mapping agent_id -> LLMAgent for all six town agents.

    Raises:
        ValueError: if doctrine.yaml contains duplicate rule ids (only when
                    doctrine is True).
        FileNotFoundError: if doctrine.yaml is missing (only when doctrine is True).
    """
    # Load doctrine once; failure must raise at build time (not silently skipped).
    # With doctrine=False the layer is dropped wholesale: no load, no blocks.
    rules: list[Rule]
    if not doctrine:
        rules = []
    else:
        rules = _doctrine_rules if _doctrine_rules is not None else load_doctrine()

    decision_param_schemas = {
        "recall": RecallParams.model_json_schema(),
        "set_priority": SetPriorityParams.model_json_schema(),
        "repair_road": RepairRoadParams.model_json_schema(),
        "broadcast": BroadcastParams.model_json_schema(),
    }
    proposal_param_schemas: dict[str, dict] = {}

    agents: dict[str, Agent] = {}
    for agent_id in _TOWN_AGENT_IDS:
        role = roles[agent_id]

        blocks = doctrine_blocks(rules, role=agent_id, arm=arm)

        system_prompt = role.system_prompt
        if blocks:
            system_prompt = system_prompt + "\n\n" + blocks

        if lessons and agent_id == "commander":
            numbered = "\n".join(f"{i + 1}. {lesson}" for i, lesson in enumerate(lessons))
            lessons_block = (
                "\n\nLESSONS FROM PREVIOUS DISASTERS (apply where relevant):\n" + numbered
            )
            system_prompt = system_prompt + lessons_block

        updates: dict[str, object] = {}
        if system_prompt != role.system_prompt:
            updates["system_prompt"] = system_prompt
        # force_tools is the opt-in switch (CLI --society-tools): flip every role
        # into native function-calling mode regardless of its YAML default, which
        # is now JSON. The role's YAML use_tools is honored when force_tools is off.
        if force_tools and not role.use_tools:
            updates["use_tools"] = True
        if updates:
            role = role.model_copy(update=updates)

        if role.use_tools:
            contract = tool_contract(has_proposals=True)
            tool_defs = build_role_tools(
                allowed=role.allowed_decisions,
                decision_docs=DECISION_DOCS,
                proposal_docs=PROPOSAL_DOCS,
                decision_param_schemas=decision_param_schemas,
                proposal_param_schemas=proposal_param_schemas,
            )
            agents[agent_id] = LLMAgent(
                agent_id=agent_id,
                role=role,
                provider=provider,
                contract=contract,
                tool_defs=tool_defs,
                tool_mapper=map_tool_calls,
                engine_seed=engine_seed,
            )
        else:
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
                engine_seed=engine_seed,
            )
    return agents
