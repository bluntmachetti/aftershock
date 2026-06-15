"""Arm factory for the benchmark harness.

Four arms run identical seeded worlds so results are directly comparable:
  scripted — six heuristic agents + TownResolver  ($0, the baseline)
  solo     — one qwen3-max LLMAgent + DefaultResolver
  swarm    — five qwen3.5-flash LLMAgents + DefaultResolver (direct dispatch)
  society  — six qwen3.5-flash/plus LLMAgents + TownResolver (auction protocol)

build_arm is the single entry point used by bench.py and the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aftershock.kernel.agents import Agent
from aftershock.kernel.negotiation import DefaultResolver
from aftershock.kernel.registry import DecisionRegistry
from aftershock.kernel.roles import RoleSpec, load_roles
from aftershock.llm.agent import LLMAgent
from aftershock.llm.contract import decision_contract
from aftershock.town.decisions import register_all
from aftershock.town.doctrine import doctrine_blocks, load_doctrine
from aftershock.town.heuristics import (
    CommanderScripted,
    CommsScripted,
    FireScripted,
    InfraScripted,
    MedicalScripted,
    RescueScripted,
)
from aftershock.town.prompts import DECISION_DOCS_DIRECT, build_llm_agents  # noqa: E402
from aftershock.town.scenario import ScenarioPack, town_from_scenario
from aftershock.town.society import TownResolver, TownSociety
from aftershock.town.state import TownState, new_town

ARMS = ("scripted", "solo", "swarm", "society")

_TOWN_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# ArmSetup dataclass
# ---------------------------------------------------------------------------


@dataclass
class ArmSetup:
    world: TownState
    society: Any  # Society protocol
    agents: dict[str, Agent]
    registry: DecisionRegistry
    roles: dict[str, RoleSpec]
    resolver: Any  # Resolver protocol
    default_timeout_s: float


# ---------------------------------------------------------------------------
# build_arm
# ---------------------------------------------------------------------------


def build_arm(
    arm: str,
    seed: int,
    provider: Any | None,
    lessons: list[str] | None = None,
    scenario: ScenarioPack | None = None,
    society_tools: bool = False,
    seed_sampler: bool = False,
    pool_sizes: dict[str, int] | None = None,
) -> ArmSetup:
    """Build all components for one (arm, seed) benchmark cell.

    Args:
        arm:      one of ARMS ("scripted", "solo", "swarm", "society")
        seed:     the scenario seed passed to new_town and Engine
        provider: a Provider instance for LLM arms; None for scripted.
                  Passing None for an LLM arm raises ValueError.
        lessons:  optional lesson strings from a prior AAR memory loop.
                  Only accepted for the society arm; all other arms raise
                  ValueError to enforce the bench fairness invariant (benchmark
                  arms must run memory-free so comparisons measure architecture,
                  not accumulated hints).
        scenario: optional validated ScenarioPack. When given, the world is built
                  from the pack (districts/pools/timeline from real data) via
                  town_from_scenario(scenario, seed); otherwise new_town(seed).
                  `seed` keeps its meaning for every other rng_for stream + replay.
        seed_sampler: M1 opt-in (CLI --seed-sampler). When True, LLM arms thread
                  the engine seed into a deterministic per-tick provider seed
                  (see llm.agent.sample_seed). No effect on the scripted arm.
        pool_sizes: D2 opt-in (CLI --pools). An override merged onto POOL_SIZES to
                  harden the synthetic world. Ignored on the scenario path (a pack
                  defines its own pools). None reproduces the canonical world.

    Returns:
        ArmSetup with fully wired world, society, agents, registry, roles,
        resolver, and default_timeout_s.
    """
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; valid: {ARMS}")

    if lessons is not None and arm != "society":
        raise ValueError(
            f"lessons are only accepted for arm 'society'; got arm={arm!r}. "
            "The bench fairness invariant requires all other arms to run memory-free."
        )

    if arm != "scripted" and provider is None:
        raise ValueError(
            f"arm {arm!r} requires a Provider — set DASHSCOPE_API_KEY and pass a provider"
        )

    world = (
        town_from_scenario(scenario, seed)
        if scenario
        else new_town(seed, pool_sizes=pool_sizes)
    )
    registry = DecisionRegistry()
    register_all(registry)

    # M1: the engine seed only flows to the LLM agents when the sampler is on.
    engine_seed = seed if seed_sampler else None

    if arm == "scripted":
        return _build_scripted(world, registry, seed)
    if arm == "society":
        return _build_society(
            world, registry, seed, provider, lessons=lessons, use_tools=society_tools,
            engine_seed=engine_seed,
        )
    if arm == "swarm":
        return _build_swarm(world, registry, seed, provider, engine_seed=engine_seed)
    if arm == "solo":
        return _build_solo(world, registry, seed, provider, engine_seed=engine_seed)

    raise ValueError(f"unhandled arm {arm!r}")  # unreachable


# ---------------------------------------------------------------------------
# Per-arm builders
# ---------------------------------------------------------------------------


def _build_scripted(
    world: TownState,
    registry: DecisionRegistry,
    seed: int,  # noqa: ARG001 — kept for uniform signature
) -> ArmSetup:
    roles = load_roles(_TOWN_DIR / "roles")
    # Default six-role roster: role name == agent id
    _six = ("commander", "comms", "fire", "infrastructure", "medical", "rescue")
    roster = {aid: aid for aid in _six}
    # max_ticks is intentionally omitted: the engine loop (`while tick < max_ticks`)
    # is the sole tick-budget bound. TownSociety.is_over() is checked by the engine
    # for mission-complete early exits only; it does not need the tick budget here.
    society = TownSociety(roster=roster)
    agents: dict[str, Agent] = {
        "commander": CommanderScripted("commander", "commander"),
        "medical": MedicalScripted("medical", "medical"),
        "rescue": RescueScripted("rescue", "rescue"),
        "fire": FireScripted("fire", "fire"),
        "infrastructure": InfraScripted("infrastructure", "infrastructure"),
        "comms": CommsScripted("comms", "comms"),
    }
    return ArmSetup(
        world=world,
        society=society,
        agents=agents,
        registry=registry,
        roles=roles,
        resolver=TownResolver(),
        default_timeout_s=5.0,
    )


def _build_society(
    world: TownState,
    registry: DecisionRegistry,
    seed: int,  # noqa: ARG001
    provider: Any,
    lessons: list[str] | None = None,
    use_tools: bool = False,
    engine_seed: int | None = None,
) -> ArmSetup:
    roles = load_roles(_TOWN_DIR / "roles")
    _six = ("commander", "comms", "fire", "infrastructure", "medical", "rescue")
    roster = {aid: aid for aid in _six}
    society = TownSociety(roster=roster)
    agents = build_llm_agents(
        roles, provider, lessons=lessons, arm="society", force_tools=use_tools,
        engine_seed=engine_seed,
    )
    return ArmSetup(
        world=world,
        society=society,
        agents=agents,
        registry=registry,
        roles=roles,
        resolver=TownResolver(),
        default_timeout_s=45.0,
    )


def _build_swarm(
    world: TownState,
    registry: DecisionRegistry,
    seed: int,  # noqa: ARG001
    provider: Any,
    engine_seed: int | None = None,
) -> ArmSetup:
    roles = load_roles(_TOWN_DIR / "roles_swarm")
    # Roster: agent_id == role name for the five swarm roles
    roster = {name: name for name in roles}
    society = TownSociety(roster=roster)
    # Load doctrine once; failure raises at build time
    rules = load_doctrine()
    agents: dict[str, Agent] = {}
    for agent_id, role in roles.items():
        blocks = doctrine_blocks(rules, role=agent_id, arm="swarm")
        if blocks:
            role = role.model_copy(
                update={"system_prompt": role.system_prompt + "\n\n" + blocks}
            )
        contract = decision_contract(
            allowed=role.allowed_decisions,
            decision_docs=DECISION_DOCS_DIRECT,
            proposal_docs={},  # swarm has no proposals — decisions-only contract
        )
        agents[agent_id] = LLMAgent(
            agent_id=agent_id,
            role=role,
            provider=provider,
            contract=contract,
            engine_seed=engine_seed,
        )
    return ArmSetup(
        world=world,
        society=society,
        agents=agents,
        registry=registry,
        roles=roles,
        resolver=DefaultResolver(),
        default_timeout_s=45.0,
    )


def _build_solo(
    world: TownState,
    registry: DecisionRegistry,
    seed: int,  # noqa: ARG001
    provider: Any,
    engine_seed: int | None = None,
) -> ArmSetup:
    roles = load_roles(_TOWN_DIR / "roles_solo")
    solo_role = roles["solo"]
    roster = {"solo": "solo"}
    society = TownSociety(roster=roster)
    # Load doctrine once; failure raises at build time
    rules = load_doctrine()
    blocks = doctrine_blocks(rules, role="solo", arm="solo")
    if blocks:
        solo_role = solo_role.model_copy(
            update={"system_prompt": solo_role.system_prompt + "\n\n" + blocks}
        )
    contract = decision_contract(
        allowed=solo_role.allowed_decisions,
        decision_docs=DECISION_DOCS_DIRECT,
        proposal_docs={},  # solo has no proposals — decisions-only contract
    )
    agents: dict[str, Agent] = {
        "solo": LLMAgent(
            agent_id="solo",
            role=solo_role,
            provider=provider,
            contract=contract,
            engine_seed=engine_seed,
        )
    }
    return ArmSetup(
        world=world,
        society=society,
        agents=agents,
        registry=registry,
        roles=roles,
        resolver=DefaultResolver(),
        default_timeout_s=90.0,
    )
