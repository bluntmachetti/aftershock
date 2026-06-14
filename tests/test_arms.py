"""Tests for town/arms.py: build_arm wiring, rosters, envelopes, contracts, determinism."""

from __future__ import annotations

import pytest

from aftershock.llm.provider import MockProvider
from aftershock.town.arms import ARMS, ArmSetup, build_arm
from aftershock.town.heuristics import (
    CommanderScripted,
    CommsScripted,
    FireScripted,
    InfraScripted,
    MedicalScripted,
    RescueScripted,
)
from aftershock.town.society import TownResolver, TownSociety

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEED = 42


def _mock() -> MockProvider:
    return MockProvider(script=['{"decisions": []}'])


# ---------------------------------------------------------------------------
# ARMS tuple
# ---------------------------------------------------------------------------


def test_arms_tuple_values() -> None:
    assert set(ARMS) == {"scripted", "solo", "swarm", "society"}


# ---------------------------------------------------------------------------
# build_arm("scripted", seed) — provider=None is fine
# ---------------------------------------------------------------------------


def test_scripted_builds_without_provider() -> None:
    setup = build_arm("scripted", _SEED, None)
    assert isinstance(setup, ArmSetup)


def test_scripted_six_agents() -> None:
    setup = build_arm("scripted", _SEED, None)
    assert len(setup.agents) == 6


def test_scripted_agent_types() -> None:
    setup = build_arm("scripted", _SEED, None)
    assert isinstance(setup.agents["commander"], CommanderScripted)
    assert isinstance(setup.agents["medical"], MedicalScripted)
    assert isinstance(setup.agents["rescue"], RescueScripted)
    assert isinstance(setup.agents["fire"], FireScripted)
    assert isinstance(setup.agents["infrastructure"], InfraScripted)
    assert isinstance(setup.agents["comms"], CommsScripted)


def test_scripted_uses_town_resolver() -> None:
    setup = build_arm("scripted", _SEED, None)
    assert isinstance(setup.resolver, TownResolver)


def test_scripted_timeout() -> None:
    setup = build_arm("scripted", _SEED, None)
    assert setup.default_timeout_s == pytest.approx(5.0)


def test_scripted_roles_no_dispatch_in_envelope() -> None:
    """Society/scripted roles must NOT include dispatch in their envelopes."""
    setup = build_arm("scripted", _SEED, None)
    for role in setup.roles.values():
        assert "dispatch" not in role.allowed_decisions, (
            f"role {role.name!r} must not have dispatch in allowed_decisions"
        )


def test_scripted_determinism() -> None:
    """Two build_arm('scripted', seed) calls produce byte-identical world to_dict."""
    setup_a = build_arm("scripted", _SEED, None)
    setup_b = build_arm("scripted", _SEED, None)
    assert setup_a.world.to_dict() == setup_b.world.to_dict()


# ---------------------------------------------------------------------------
# build_arm with provider=None for LLM arms raises ValueError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("arm", ["society", "swarm", "solo"])
def test_llm_arm_provider_none_raises(arm: str) -> None:
    with pytest.raises(ValueError, match="requires a Provider"):
        build_arm(arm, _SEED, None)


# ---------------------------------------------------------------------------
# build_arm("swarm", ...) — five agents, dispatch in envelopes, decisions-only contract
# ---------------------------------------------------------------------------


def test_swarm_five_agents() -> None:
    setup = build_arm("swarm", _SEED, _mock())
    assert len(setup.agents) == 5


def test_swarm_no_commander() -> None:
    setup = build_arm("swarm", _SEED, _mock())
    assert "commander" not in setup.agents


def test_swarm_agent_ids() -> None:
    setup = build_arm("swarm", _SEED, _mock())
    assert set(setup.agents) == {"comms", "fire", "infrastructure", "medical", "rescue"}


def test_swarm_all_roles_have_dispatch() -> None:
    setup = build_arm("swarm", _SEED, _mock())
    for role in setup.roles.values():
        assert "dispatch" in role.allowed_decisions, (
            f"swarm role {role.name!r} must include dispatch in allowed_decisions"
        )


def test_swarm_all_roles_have_recall() -> None:
    setup = build_arm("swarm", _SEED, _mock())
    for role in setup.roles.values():
        assert "recall" in role.allowed_decisions, (
            f"swarm role {role.name!r} must include recall in allowed_decisions"
        )


def test_swarm_infrastructure_has_repair_road() -> None:
    setup = build_arm("swarm", _SEED, _mock())
    assert "repair_road" in setup.roles["infrastructure"].allowed_decisions


def test_swarm_comms_has_broadcast() -> None:
    setup = build_arm("swarm", _SEED, _mock())
    assert "broadcast" in setup.roles["comms"].allowed_decisions


def test_swarm_models_are_flash() -> None:
    setup = build_arm("swarm", _SEED, _mock())
    for role in setup.roles.values():
        assert role.model == "qwen3.5-flash", f"swarm role {role.name!r} should use qwen3.5-flash"


def test_swarm_temperatures() -> None:
    setup = build_arm("swarm", _SEED, _mock())
    for role in setup.roles.values():
        assert role.temperature == pytest.approx(0.3)


def test_swarm_uses_default_resolver() -> None:
    from aftershock.kernel.negotiation import DefaultResolver

    setup = build_arm("swarm", _SEED, _mock())
    assert isinstance(setup.resolver, DefaultResolver)


def test_swarm_timeout() -> None:
    setup = build_arm("swarm", _SEED, _mock())
    assert setup.default_timeout_s == pytest.approx(45.0)


def test_swarm_society_uses_town_society() -> None:
    setup = build_arm("swarm", _SEED, _mock())
    assert isinstance(setup.society, TownSociety)


def test_swarm_contracts_no_proposals_schema() -> None:
    """Swarm contracts must not contain proposals or responses schema fields."""
    from aftershock.llm.agent import LLMAgent

    setup = build_arm("swarm", _SEED, _mock())
    for agent_id, agent in setup.agents.items():
        assert isinstance(agent, LLMAgent)
        contract = agent._system
        # decisions-only schema: no proposals/responses keys in the schema block
        assert '"proposals"' not in contract, (
            f"swarm agent {agent_id!r} contract must not contain proposals schema"
        )
        assert '"responses"' not in contract, (
            f"swarm agent {agent_id!r} contract must not contain responses schema"
        )


def test_swarm_contracts_no_proposals_rule() -> None:
    """Swarm contracts must contain the no-proposals hard rule."""
    from aftershock.llm.agent import LLMAgent

    setup = build_arm("swarm", _SEED, _mock())
    for agent_id, agent in setup.agents.items():
        assert isinstance(agent, LLMAgent)
        contract = agent._system
        assert "do not emit proposals" in contract.lower(), (
            f"swarm agent {agent_id!r} contract must contain 'do not emit proposals' rule"
        )


# ---------------------------------------------------------------------------
# build_arm("solo", ...) — one agent, all five decisions, decisions-only contract
# ---------------------------------------------------------------------------


def test_solo_one_agent() -> None:
    setup = build_arm("solo", _SEED, _mock())
    assert len(setup.agents) == 1


def test_solo_agent_id() -> None:
    setup = build_arm("solo", _SEED, _mock())
    assert "solo" in setup.agents


def test_solo_all_five_decisions() -> None:
    setup = build_arm("solo", _SEED, _mock())
    role = setup.roles["solo"]
    assert set(role.allowed_decisions) == {
        "dispatch",
        "recall",
        "set_priority",
        "repair_road",
        "broadcast",
    }


def test_solo_model_is_qwen3_max() -> None:
    setup = build_arm("solo", _SEED, _mock())
    assert setup.roles["solo"].model == "qwen3-max"


def test_solo_temperature() -> None:
    setup = build_arm("solo", _SEED, _mock())
    assert setup.roles["solo"].temperature == pytest.approx(0.3)


def test_solo_uses_default_resolver() -> None:
    from aftershock.kernel.negotiation import DefaultResolver

    setup = build_arm("solo", _SEED, _mock())
    assert isinstance(setup.resolver, DefaultResolver)


def test_solo_timeout() -> None:
    setup = build_arm("solo", _SEED, _mock())
    assert setup.default_timeout_s == pytest.approx(90.0)


def test_solo_contract_no_proposals_schema() -> None:
    """Solo contract must not contain proposals or responses schema fields."""
    from aftershock.llm.agent import LLMAgent

    setup = build_arm("solo", _SEED, _mock())
    agent = setup.agents["solo"]
    assert isinstance(agent, LLMAgent)
    contract = agent._system
    assert '"proposals"' not in contract
    assert '"responses"' not in contract


def test_solo_contract_no_proposals_rule() -> None:
    """Solo contract must contain the no-proposals hard rule."""
    from aftershock.llm.agent import LLMAgent

    setup = build_arm("solo", _SEED, _mock())
    agent = setup.agents["solo"]
    assert isinstance(agent, LLMAgent)
    contract = agent._system
    assert "do not emit proposals" in contract.lower()


def test_solo_society_uses_town_society() -> None:
    setup = build_arm("solo", _SEED, _mock())
    assert isinstance(setup.society, TownSociety)


# ---------------------------------------------------------------------------
# build_arm("society", ...) — six agents, no dispatch in envelopes, full contract
# ---------------------------------------------------------------------------


def test_society_six_agents() -> None:
    setup = build_arm("society", _SEED, _mock())
    assert len(setup.agents) == 6


def test_society_agent_ids() -> None:
    setup = build_arm("society", _SEED, _mock())
    assert set(setup.agents) == {
        "commander",
        "comms",
        "fire",
        "infrastructure",
        "medical",
        "rescue",
    }


def test_society_no_dispatch_in_envelope() -> None:
    setup = build_arm("society", _SEED, _mock())
    for role in setup.roles.values():
        assert "dispatch" not in role.allowed_decisions, (
            f"society role {role.name!r} must not have dispatch in allowed_decisions"
        )


def test_society_uses_town_resolver() -> None:
    setup = build_arm("society", _SEED, _mock())
    assert isinstance(setup.resolver, TownResolver)


def test_society_contracts_include_proposals_schema() -> None:
    """With the function-calling opt-in (society_tools=True), every society agent's
    system prompt carries the tool-mode contract: the no_op idle tool, proposal
    tools, and inbox-response tools."""
    from aftershock.llm.agent import LLMAgent

    setup = build_arm("society", _SEED, _mock(), society_tools=True)
    for agent_id, agent in setup.agents.items():
        assert isinstance(agent, LLMAgent)
        contract = agent._system
        assert "no_op" in contract, (
            f"society agent {agent_id!r} contract must mention no_op idle tool"
        )
        assert "propose_resource_request" in contract, (
            f"society agent {agent_id!r} contract must mention proposal tools"
        )
        assert "accept_proposal" in contract, (
            f"society agent {agent_id!r} contract must mention inbox response tools"
        )


def test_society_default_is_json_mode() -> None:
    """build_arm society default (society_tools=False) builds JSON-mode agents:
    no tool defs, and the tool-mode no_op marker is absent from the contract."""
    from aftershock.llm.agent import LLMAgent

    setup = build_arm("society", _SEED, _mock())
    for agent in setup.agents.values():
        assert isinstance(agent, LLMAgent)
        assert agent._role.use_tools is False
        assert agent._tool_defs is None
        assert "no_op" not in agent._system


def test_society_tools_opt_in_builds_tool_mode() -> None:
    """build_arm society with society_tools=True flips every agent into native
    function-calling mode: tool defs present and the tool_mapper is wired."""
    from aftershock.llm.agent import LLMAgent

    setup = build_arm("society", _SEED, _mock(), society_tools=True)
    for agent in setup.agents.values():
        assert isinstance(agent, LLMAgent)
        assert agent._role.use_tools is True
        assert agent._tool_defs is not None and len(agent._tool_defs) > 0
        assert agent._tool_mapper is not None


def test_society_timeout() -> None:
    setup = build_arm("society", _SEED, _mock())
    assert setup.default_timeout_s == pytest.approx(45.0)


# ---------------------------------------------------------------------------
# M1: seed_sampler threads the engine seed into the LLM agents (all arms)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("arm", ["society", "swarm", "solo"])
def test_seed_sampler_threads_engine_seed(arm: str) -> None:
    """build_arm(seed_sampler=True) gives every LLM agent engine_seed == seed.

    Covers arms.py's `engine_seed = seed if seed_sampler else None` AND the
    per-builder engine_seed= wiring for society/swarm/solo — a regression that
    dropped it (or gated on the wrong flag) would leave the arm unseeded.
    """
    from aftershock.llm.agent import LLMAgent

    setup = build_arm(arm, _SEED, _mock(), seed_sampler=True)
    for agent in setup.agents.values():
        assert isinstance(agent, LLMAgent)
        assert agent._engine_seed == _SEED


@pytest.mark.parametrize("arm", ["society", "swarm", "solo"])
def test_seed_sampler_off_leaves_engine_seed_none(arm: str) -> None:
    from aftershock.llm.agent import LLMAgent

    setup = build_arm(arm, _SEED, _mock())  # default seed_sampler=False
    for agent in setup.agents.values():
        assert isinstance(agent, LLMAgent)
        assert agent._engine_seed is None


def test_seed_sampler_reaches_provider_through_engine() -> None:
    """End-to-end: build_arm(seed_sampler=True) -> Engine tick -> provider gets the
    correct non-None sample_seed(seed, agent_id, tick) on every call."""
    import asyncio

    from aftershock.kernel.engine import Engine
    from aftershock.kernel.recorder import Recorder
    from aftershock.llm.agent import sample_seed

    provider = MockProvider(script=lambda m, s, u: '{"decisions": []}')
    setup = build_arm("society", _SEED, provider, seed_sampler=True)

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        recorder = Recorder(Path(td), "m1", {"seed": _SEED, "arm": "society"})
        engine = Engine(
            world=setup.world, society=setup.society, agents=setup.agents,
            registry=setup.registry, roles=setup.roles, resolver=setup.resolver,
            recorder=recorder, seed=_SEED, max_ticks=1, agent_timeout_s=30.0,
        )
        asyncio.run(engine.run())

    assert provider.seed_calls, "provider was never called"
    assert all(s is not None for s in provider.seed_calls)
    # Tick 0: each of the six agents sent sample_seed(seed, agent_id, 0).
    expected = {sample_seed(_SEED, aid, 0) for aid in setup.agents}
    assert set(provider.seed_calls) == expected


# ---------------------------------------------------------------------------
# Unknown arm
# ---------------------------------------------------------------------------


def test_unknown_arm_raises() -> None:
    with pytest.raises(ValueError, match="unknown arm"):
        build_arm("unknown_arm", _SEED, None)


# ---------------------------------------------------------------------------
# Cross-arm world identity: all arms must produce the same seeded world
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("arm", ["scripted", "swarm", "solo", "society"])
def test_cross_arm_world_identity_same_as_scripted(arm: str) -> None:
    """build_arm(arm, seed) must produce a world identical to build_arm('scripted', seed).

    This is the benchmark's load-bearing fairness invariant: all arms run
    identical seeded starting conditions so results are directly comparable.
    """
    provider = _mock()
    scripted_world = build_arm("scripted", _SEED, None).world.to_dict()
    arm_world = build_arm(arm, _SEED, provider if arm != "scripted" else None).world.to_dict()
    assert arm_world == scripted_world, (
        f"arm {arm!r} produced a different world than 'scripted' for seed {_SEED}"
    )


def test_cross_arm_world_identity_different_seed_differs() -> None:
    """Different seeds must produce different worlds (sanity check for the identity test)."""
    world_42 = build_arm("scripted", 42, None).world.to_dict()
    world_11 = build_arm("scripted", 11, None).world.to_dict()
    assert world_42 != world_11, "seed 42 and seed 11 must produce different worlds"
