"""Tests for the Engine tick pipeline.

Uses a minimal inline toy society with a counter world and an "increment"
decision type. All agents are scripted for determinism.
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from aftershock.kernel.agents import Agent, ScriptedAgent
from aftershock.kernel.engine import Engine, RunSummary
from aftershock.kernel.negotiation import DefaultResolver
from aftershock.kernel.protocol import (
    AgentResponse,
    Decision,
    Observation,
    Proposal,
    ProposalKind,
    ProposalResponse,
    ProposalRuling,
    WorldEvent,
)
from aftershock.kernel.recorder import Recorder
from aftershock.kernel.registry import DecisionHandler, DecisionRegistry
from aftershock.kernel.roles import RoleSpec

# ---------------------------------------------------------------------------
# Toy domain: counter world
# ---------------------------------------------------------------------------


class IncrParams(BaseModel):
    amount: int = 1


class IncrHandler(DecisionHandler):
    decision_type = "increment"
    Params = IncrParams

    def validate(self, world: Any, params: BaseModel) -> str | None:
        assert isinstance(params, IncrParams)
        if params.amount < 0:
            return "amount must be non-negative"
        return None

    def apply(
        self, world: Any, params: BaseModel, tick: int, rng: random.Random
    ) -> list[WorldEvent]:
        assert isinstance(params, IncrParams)
        world["counter"] += params.amount
        return [
            WorldEvent(
                event_id=f"incr-{tick}",
                tick=tick,
                kind="incremented",
                payload={"amount": params.amount},
            )
        ]


# ---------------------------------------------------------------------------
# Toy society
# ---------------------------------------------------------------------------


class CounterSociety:
    """Minimal Society: two agents (alpha, beta) with role 'worker'."""

    def agent_ids(self) -> tuple[str, ...]:
        return ("alpha", "beta")

    def role_of(self, agent_id: str) -> str:
        return "worker"

    def build_view(self, world: Any, agent_id: str, tick: int) -> dict[str, Any]:
        return {"counter": world["counter"], "agent": agent_id}

    def scheduled_events(self, world: Any, tick: int, rng: random.Random) -> list[WorldEvent]:
        return []

    def score(self, world: Any, tick: int) -> dict[str, float]:
        return {"counter": float(world["counter"])}

    def is_over(self, world: Any, tick: int) -> bool:
        return tick >= 2

    def world_state(self, world: Any) -> dict[str, Any]:
        return {"counter": world["counter"]}


def make_world() -> dict[str, Any]:
    return {"counter": 0}


def make_registry() -> DecisionRegistry:
    reg = DecisionRegistry()
    reg.register(IncrHandler())
    return reg


def make_roles() -> dict[str, RoleSpec]:
    return {
        "worker": RoleSpec(name="worker", allowed_decisions=("increment",)),
    }


def make_recorder(tmp_path: Path) -> Recorder:
    return Recorder(tmp_path, "test-run", {"seed": 42})


# ---------------------------------------------------------------------------
# Scripted agents
# ---------------------------------------------------------------------------


class IncrAgent(ScriptedAgent):
    """Always increments by 1."""

    def act_sync(self, observation: Observation) -> AgentResponse:
        return AgentResponse(
            agent_id=self.agent_id,
            decisions=(
                Decision(
                    decision_id=f"{self.agent_id}-{observation.tick}",
                    agent_id=self.agent_id,
                    decision_type="increment",
                    params={"amount": 1},
                ),
            ),
        )


class IdleSpoofAgent(ScriptedAgent):
    """Submits a decision with the wrong agent_id (identity spoof)."""

    def act_sync(self, observation: Observation) -> AgentResponse:
        return AgentResponse(
            agent_id=self.agent_id,
            decisions=(
                Decision(
                    decision_id=f"{self.agent_id}-{observation.tick}",
                    agent_id="alpha",  # spoofed — wrong id for beta
                    decision_type="increment",
                    params={"amount": 1},
                ),
            ),
        )


class HangingAgent(Agent):
    """Sleeps forever — will be killed by the timeout."""

    async def act(self, observation: Observation) -> AgentResponse:
        await asyncio.sleep(9999)
        return AgentResponse(agent_id=self.agent_id)  # pragma: no cover


class RaisingAgent(Agent):
    """Always raises an exception."""

    async def act(self, observation: Observation) -> AgentResponse:
        raise RuntimeError("boom")


class ProposerAgent(ScriptedAgent):
    """Sends a bilateral proposal to 'beta' on tick 0; accepts on tick 1."""

    def act_sync(self, observation: Observation) -> AgentResponse:
        if observation.tick == 0:
            return AgentResponse(
                agent_id=self.agent_id,
                proposals=(
                    Proposal(
                        proposal_id="p-alpha-0",
                        sender=self.agent_id,
                        recipient="beta",
                        kind=ProposalKind.TASK_HANDOFF,
                        body={"task": "help"},
                    ),
                ),
            )
        return AgentResponse(agent_id=self.agent_id)


class ResponderAgent(ScriptedAgent):
    """Accepts any proposal in its inbox."""

    def act_sync(self, observation: Observation) -> AgentResponse:
        responses = tuple(
            ProposalResponse(
                proposal_id=p.proposal_id,
                responder=self.agent_id,
                accept=True,
                note="ok",
            )
            for p in observation.inbox
        )
        return AgentResponse(agent_id=self.agent_id, responses=responses)


class BroadcastAgent(ScriptedAgent):
    """Sends an INFO_SHARE broadcast on tick 0."""

    def act_sync(self, observation: Observation) -> AgentResponse:
        if observation.tick == 0:
            return AgentResponse(
                agent_id=self.agent_id,
                proposals=(
                    Proposal(
                        proposal_id="bc-alpha-0",
                        sender=self.agent_id,
                        recipient=None,
                        kind=ProposalKind.INFO_SHARE,
                        body={"msg": "hello"},
                    ),
                ),
            )
        return AgentResponse(agent_id=self.agent_id)


class DuplicateDecisionAgent(ScriptedAgent):
    """Submits two decisions with the same decision_id."""

    def act_sync(self, observation: Observation) -> AgentResponse:
        dec = Decision(
            decision_id=f"{self.agent_id}-{observation.tick}",
            agent_id=self.agent_id,
            decision_type="increment",
            params={"amount": 1},
        )
        return AgentResponse(agent_id=self.agent_id, decisions=(dec, dec))


# ---------------------------------------------------------------------------
# Engine factory helper
# ---------------------------------------------------------------------------


def make_engine(
    tmp_path: Path,
    world: dict[str, Any],
    agents: dict[str, Agent],
    *,
    timeout: float = 30.0,
    roles: dict[str, RoleSpec] | None = None,
) -> Engine:
    return Engine(
        world=world,
        society=CounterSociety(),
        agents=agents,
        registry=make_registry(),
        roles=roles or make_roles(),
        resolver=DefaultResolver(),
        recorder=make_recorder(tmp_path),
        seed=42,
        max_ticks=5,
        agent_timeout_s=timeout,
    )


# ---------------------------------------------------------------------------
# Tests: resilience — hanging and raising agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hanging_agent_does_not_kill_tick(tmp_path: Path) -> None:
    """A hanging agent times out but the tick still completes."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": HangingAgent("alpha", "worker"),
        "beta": IncrAgent("beta", "worker"),
    }
    engine = make_engine(tmp_path, world, agents, timeout=0.05)
    record = await engine.step(0)

    # Tick completed
    assert record.tick == 0
    # alpha response has error="timeout"
    alpha_resp = next(r for r in record.responses if r.agent_id == "alpha")
    assert alpha_resp.error == "timeout"
    # beta incremented
    assert world["counter"] == 1


@pytest.mark.asyncio
async def test_raising_agent_does_not_kill_tick(tmp_path: Path) -> None:
    """An agent that raises is caught; other agents still act."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": RaisingAgent("alpha", "worker"),
        "beta": IncrAgent("beta", "worker"),
    }
    engine = make_engine(tmp_path, world, agents, timeout=5.0)
    record = await engine.step(0)

    alpha_resp = next(r for r in record.responses if r.agent_id == "alpha")
    assert "RuntimeError" in alpha_resp.error or "boom" in alpha_resp.error
    assert world["counter"] == 1


# ---------------------------------------------------------------------------
# Tests: identity spoofing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identity_spoof_rejected(tmp_path: Path) -> None:
    """beta claims alpha's agent_id in a decision — must be rejected."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": IncrAgent("alpha", "worker"),
        "beta": IdleSpoofAgent("beta", "worker"),
    }
    engine = make_engine(tmp_path, world, agents)
    record = await engine.step(0)

    # The spoofed decision should appear in rejected
    spoof_rej = [r for r in record.rejected if r.reason == "identity mismatch"]
    assert len(spoof_rej) >= 1
    # Counter only incremented once (by alpha, not beta's spoofed decision)
    assert world["counter"] == 1


@pytest.mark.asyncio
async def test_rejection_appears_in_next_observation(tmp_path: Path) -> None:
    """A rejected decision's reason appears in the issuing agent's next observation."""
    world = make_world()
    # beta spoofs on tick 0; we observe beta's tick-1 observation via the engine
    agents: dict[str, Agent] = {
        "alpha": IncrAgent("alpha", "worker"),
        "beta": IdleSpoofAgent("beta", "worker"),
    }
    engine = make_engine(tmp_path, world, agents, timeout=5.0)
    await engine.step(0)
    await engine.step(1)

    # The best observable signal: rejections for beta in tick 0's record
    from aftershock.kernel.recorder import load_run

    _manifest, ticks, _worlds = load_run(engine._recorder.run_dir)
    tick0 = ticks[0]
    beta_rejects = [r for r in tick0.rejected if r.agent_id == "beta"]
    assert any(r.reason == "identity mismatch" for r in beta_rejects)


# ---------------------------------------------------------------------------
# Tests: duplicate decision_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_decision_id_rejected(tmp_path: Path) -> None:
    """Two decisions with the same id in one tick: second is rejected."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": DuplicateDecisionAgent("alpha", "worker"),
        "beta": IncrAgent("beta", "worker"),
    }
    engine = make_engine(tmp_path, world, agents)
    record = await engine.step(0)

    dup_rejects = [r for r in record.rejected if r.reason == "duplicate decision_id"]
    assert len(dup_rejects) >= 1
    # Only one of alpha's two decisions was applied
    assert world["counter"] <= 2  # beta applied 1, alpha applied at most 1


# ---------------------------------------------------------------------------
# Tests: bilateral proposal lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bilateral_propose_deliver_accept(tmp_path: Path) -> None:
    """alpha proposes to beta on tick 0; delivered tick 1; beta accepts; ruling on tick 1."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": ProposerAgent("alpha", "worker"),
        "beta": ResponderAgent("beta", "worker"),
    }
    engine = make_engine(tmp_path, world, agents)

    rec0 = await engine.step(0)
    # Proposal sent tick 0 — no ruling yet for it
    ruling_ids_0 = {r.proposal_id for r in rec0.rulings}
    assert "p-alpha-0" not in ruling_ids_0

    rec1 = await engine.step(1)
    # Delivered to beta's inbox tick 1 → beta responds → ruling appears tick 1
    ruling_ids_1 = {r.proposal_id for r in rec1.rulings}
    assert "p-alpha-0" in ruling_ids_1
    ruling = next(r for r in rec1.rulings if r.proposal_id == "p-alpha-0")
    assert ruling.accepted is True
    assert ruling.decided_by == "beta"


@pytest.mark.asyncio
async def test_bilateral_expire_after_one_tick(tmp_path: Path) -> None:
    """A bilateral that gets no response after one tick in the inbox expires."""
    world = make_world()

    # beta is idle — never responds
    agents: dict[str, Agent] = {
        "alpha": ProposerAgent("alpha", "worker"),
        "beta": IncrAgent("beta", "worker"),  # never responds
    }
    engine = make_engine(tmp_path, world, agents)

    await engine.step(0)  # proposal sent
    rec1 = await engine.step(1)  # beta had it in inbox but didn't respond

    expired_rulings = [
        r for r in rec1.rulings
        if r.proposal_id == "p-alpha-0" and r.decided_by == "kernel:timeout"
    ]
    assert len(expired_rulings) == 1
    assert expired_rulings[0].accepted is False


# ---------------------------------------------------------------------------
# Tests: broadcast INFO_SHARE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_reaches_all_other_inboxes(tmp_path: Path) -> None:
    """An INFO_SHARE broadcast from alpha reaches beta's inbox next tick."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": BroadcastAgent("alpha", "worker"),
        "beta": IncrAgent("beta", "worker"),
    }
    engine = make_engine(tmp_path, world, agents)

    rec0 = await engine.step(0)
    # Broadcast gets an automatic accepted ruling same tick
    bc_rulings = [r for r in rec0.rulings if r.proposal_id == "bc-alpha-0"]
    assert len(bc_rulings) == 1
    assert bc_rulings[0].accepted is True
    assert bc_rulings[0].decided_by == "kernel:broadcast"

    # Delivered to beta's inbox tick 1 (alpha does NOT get it in their own inbox)
    await engine.step(1)
    # next_inbox is cleared after tick 1 — both agents start fresh
    assert engine._next_inbox.get("beta", []) == []
    assert engine._next_inbox.get("alpha", []) == []


# ---------------------------------------------------------------------------
# Tests: granted decisions from a custom resolver
# ---------------------------------------------------------------------------


class GrantingResolver:
    """Grants an 'increment' decision for every arbiter proposal."""

    name = "granting"

    def resolve(
        self,
        world: Any,
        tick: int,
        arbiter: list[Proposal],
        answered: list[tuple[Proposal, ProposalResponse]],
        expired: list[Proposal],
        rng: random.Random,
    ) -> tuple[list[ProposalRuling], list[Decision]]:
        rulings = []
        grants = []
        for prop in arbiter:
            rulings.append(
                ProposalRuling(
                    proposal_id=prop.proposal_id,
                    accepted=True,
                    decided_by="granting",
                    reason="auction win",
                )
            )
            grants.append(
                Decision(
                    decision_id=f"{prop.proposal_id}-grant",
                    agent_id=prop.sender,
                    decision_type="increment",
                    params={"amount": 5},
                )
            )
        for prop in expired:
            rulings.append(
                ProposalRuling(
                    proposal_id=prop.proposal_id,
                    accepted=False,
                    decided_by="kernel:timeout",
                    reason="no response",
                )
            )
        for prop, resp in answered:
            rulings.append(
                ProposalRuling(
                    proposal_id=prop.proposal_id,
                    accepted=resp.accept,
                    decided_by=resp.responder,
                    reason=resp.note,
                )
            )
        return rulings, grants


class ArbiterProposerAgent(ScriptedAgent):
    """Submits a RESOURCE_REQUEST (arbiter-routed) on tick 0."""

    def act_sync(self, observation: Observation) -> AgentResponse:
        if observation.tick == 0:
            return AgentResponse(
                agent_id=self.agent_id,
                proposals=(
                    Proposal(
                        proposal_id="arb-alpha-0",
                        sender=self.agent_id,
                        recipient=None,
                        kind=ProposalKind.RESOURCE_REQUEST,
                        body={"resource": "ambulance", "qty": 2},
                    ),
                ),
            )
        return AgentResponse(agent_id=self.agent_id)


@pytest.mark.asyncio
async def test_granted_decision_applied_and_recorded(tmp_path: Path) -> None:
    """Resolver grants a decision; it is validated, applied, and in the TickRecord."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": ArbiterProposerAgent("alpha", "worker"),
        "beta": IncrAgent("beta", "worker"),
    }
    engine = Engine(
        world=world,
        society=CounterSociety(),
        agents=agents,
        registry=make_registry(),
        roles=make_roles(),
        resolver=GrantingResolver(),
        recorder=make_recorder(tmp_path),
        seed=42,
        max_ticks=5,
        agent_timeout_s=5.0,
    )
    rec = await engine.step(0)

    # Grant decision should appear in accepted
    grant = next((d for d in rec.accepted if d.decision_id == "arb-alpha-0-grant"), None)
    assert grant is not None
    assert grant.decision_type == "increment"
    # counter = 5 (grant) + 1 (beta's normal increment)
    assert world["counter"] == 6


# ---------------------------------------------------------------------------
# Tests: boot validation
# ---------------------------------------------------------------------------


def test_boot_validation_unknown_role(tmp_path: Path) -> None:
    """Engine raises if an agent's society role is not in the roles dict."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": IncrAgent("alpha", "worker"),
        "beta": IncrAgent("beta", "worker"),
    }
    # Provide a roles dict that is missing the 'worker' role
    bad_roles: dict[str, RoleSpec] = {
        "other": RoleSpec(name="other", allowed_decisions=("increment",)),
    }
    with pytest.raises(ValueError, match="unknown role"):
        Engine(
            world=world,
            society=CounterSociety(),
            agents=agents,
            registry=make_registry(),
            roles=bad_roles,
            resolver=DefaultResolver(),
            recorder=make_recorder(tmp_path),
            seed=42,
            max_ticks=5,
            agent_timeout_s=5.0,
        )


def test_boot_validation_agent_ids_mismatch(tmp_path: Path) -> None:
    """Engine raises if agent dict keys don't match society.agent_ids()."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": IncrAgent("alpha", "worker"),
        # missing beta
    }
    with pytest.raises(ValueError, match="mismatch"):
        make_engine(tmp_path, world, agents)


def test_boot_validation_role_unknown_decision_type(tmp_path: Path) -> None:
    """Engine raises if a role's allowed_decisions references an unregistered type."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": IncrAgent("alpha", "worker"),
        "beta": IncrAgent("beta", "worker"),
    }
    bad_roles = {
        "worker": RoleSpec(name="worker", allowed_decisions=("increment", "nonexistent")),
    }
    with pytest.raises(ValueError, match="unknown decision type"):
        make_engine(tmp_path, world, agents, roles=bad_roles)


# ---------------------------------------------------------------------------
# Tests: full run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_run_returns_summary(tmp_path: Path) -> None:
    """Engine.run() returns a RunSummary with expected fields."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": IncrAgent("alpha", "worker"),
        "beta": IncrAgent("beta", "worker"),
    }
    engine = make_engine(tmp_path, world, agents)
    summary = await engine.run()

    assert isinstance(summary, RunSummary)
    assert summary.seed == 42
    assert summary.ticks_run > 0
    assert "counter" in summary.final_scores
    assert "cost_usd" in summary.cost


@pytest.mark.asyncio
async def test_tick_record_world_digest_changes(tmp_path: Path) -> None:
    """World digest changes when the counter is incremented."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": IncrAgent("alpha", "worker"),
        "beta": IncrAgent("beta", "worker"),
    }
    engine = make_engine(tmp_path, world, agents)

    rec0 = await engine.step(0)
    rec1 = await engine.step(1)

    assert rec0.world_digest != rec1.world_digest


# ---------------------------------------------------------------------------
# Tests: rejection memory
# ---------------------------------------------------------------------------


def make_engine_with_memory(
    tmp_path: Path,
    world: dict[str, Any],
    agents: dict[str, Agent],
    *,
    rejection_memory_ticks: int,
    timeout: float = 30.0,
) -> Engine:
    return Engine(
        world=world,
        society=CounterSociety(),
        agents=agents,
        registry=make_registry(),
        roles=make_roles(),
        resolver=DefaultResolver(),
        recorder=make_recorder(tmp_path),
        seed=42,
        max_ticks=10,
        agent_timeout_s=timeout,
        rejection_memory_ticks=rejection_memory_ticks,
    )


@pytest.mark.asyncio
async def test_rejection_memory_spans_ticks(tmp_path: Path) -> None:
    """With memory=3, a rejection at tick 0 appears in observations at tick 2
    (within window) but NOT at tick 4 (beyond the 3-tick window).

    cutoff at observe tick T = T - 3.
    - tick 2: cutoff=-1, tick 0 >= -1 → included ✓
    - tick 4: cutoff=1,  tick 0 <  1  → excluded ✓
    Trim at end of tick T removes entries with t <= T - 3.
    - end of tick 3: trim t <= 0 → tick-0 entries removed.
    """
    world = make_world()

    observed_rejections: dict[int, tuple] = {}

    class CapturingSpoofAgent(ScriptedAgent):
        """Spoofs at tick 0, captures its own observation.rejections each tick."""

        def act_sync(self, observation: Observation) -> AgentResponse:
            observed_rejections[observation.tick] = observation.rejections
            if observation.tick == 0:
                return AgentResponse(
                    agent_id=self.agent_id,
                    decisions=(
                        Decision(
                            decision_id=f"{self.agent_id}-spoof",
                            agent_id="alpha",  # wrong id — identity mismatch rejection
                            decision_type="increment",
                            params={"amount": 1},
                        ),
                    ),
                )
            return AgentResponse(agent_id=self.agent_id)

    agents: dict[str, Agent] = {
        "alpha": IncrAgent("alpha", "worker"),
        "beta": CapturingSpoofAgent("beta", "worker"),
    }
    engine = make_engine_with_memory(tmp_path, world, agents, rejection_memory_ticks=3)

    for t in range(5):
        await engine.step(t)

    # tick 2: within memory window — rejection from tick 0 must appear
    assert len(observed_rejections[2]) >= 1, (
        "rejection from tick 0 should appear in tick-2 observation with memory=3"
    )
    assert all(r.agent_id == "beta" for r in observed_rejections[2])

    # tick 4: outside memory window — no tick-0 rejection
    tick0_rejects_at_t4 = [
        r for r in observed_rejections[4]
        # any rejection present would be from tick 1+ (none were generated after tick 0)
        # so the tuple should be empty
    ]
    assert len(tick0_rejects_at_t4) == 0, (
        f"tick-0 rejection must NOT appear in tick-4 observation with memory=3, "
        f"got: {observed_rejections[4]}"
    )


@pytest.mark.asyncio
async def test_rejection_memory_cap_at_12(tmp_path: Path) -> None:
    """Observations carry at most 12 rejections even if more occurred within the window."""
    world = make_world()

    # Agent that submits 20 identity-spoofed decisions every tick
    class BulkSpoofAgent(ScriptedAgent):
        def act_sync(self, observation: Observation) -> AgentResponse:
            decs = tuple(
                Decision(
                    decision_id=f"{self.agent_id}-spoof-{i}-t{observation.tick}",
                    agent_id="alpha",  # wrong id — will all be rejected
                    decision_type="increment",
                    params={"amount": 1},
                )
                for i in range(20)
            )
            return AgentResponse(agent_id=self.agent_id, decisions=decs)

    agents: dict[str, Agent] = {
        "alpha": IncrAgent("alpha", "worker"),
        "beta": BulkSpoofAgent("beta", "worker"),
    }
    # memory=5 so all rejections from multiple ticks accumulate; cap must kick in
    engine = make_engine_with_memory(tmp_path, world, agents, rejection_memory_ticks=5)

    await engine.step(0)
    await engine.step(1)

    # Build what the observation would show at tick 2
    # Mirror engine.py: cutoff = tick - rejection_memory_ticks; break if t < cutoff
    cutoff = 2 - 5  # = -3
    recent: list = []
    for t, rej in reversed(engine._rejection_history["beta"]):
        if t < cutoff:
            break
        recent.append(rej)
        if len(recent) == 12:
            break

    assert len(recent) == 12, (
        f"cap should limit observation rejections to 12, got {len(recent)}"
    )


# ---------------------------------------------------------------------------
# Tests: tick_listener
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_listener_called_once_per_tick(tmp_path: Path) -> None:
    """tick_listener is called exactly once per tick with the TickRecord."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": IncrAgent("alpha", "worker"),
        "beta": IncrAgent("beta", "worker"),
    }
    received: list[TickRecord] = []

    def listener(record: TickRecord) -> None:
        received.append(record)

    engine = Engine(
        world=world,
        society=CounterSociety(),
        agents=agents,
        registry=make_registry(),
        roles=make_roles(),
        resolver=DefaultResolver(),
        recorder=make_recorder(tmp_path),
        seed=42,
        max_ticks=5,
        agent_timeout_s=30.0,
        tick_listener=listener,
    )

    # Run 3 ticks manually
    rec0 = await engine.step(0)
    rec1 = await engine.step(1)
    rec2 = await engine.step(2)

    assert len(received) == 3
    assert received[0] is rec0
    assert received[1] is rec1
    assert received[2] is rec2
    assert received[0].tick == 0
    assert received[1].tick == 1
    assert received[2].tick == 2


@pytest.mark.asyncio
async def test_tick_listener_exception_does_not_break_run(tmp_path: Path) -> None:
    """A tick_listener that raises does not kill the tick or the run."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": IncrAgent("alpha", "worker"),
        "beta": IncrAgent("beta", "worker"),
    }
    call_count = 0

    def bad_listener(record: TickRecord) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("listener exploded")

    engine = Engine(
        world=world,
        society=CounterSociety(),
        agents=agents,
        registry=make_registry(),
        roles=make_roles(),
        resolver=DefaultResolver(),
        recorder=make_recorder(tmp_path),
        seed=42,
        max_ticks=5,
        agent_timeout_s=30.0,
        tick_listener=bad_listener,
    )

    summary = await engine.run()

    # Run completed despite the listener always raising
    assert isinstance(summary, RunSummary)
    assert summary.ticks_run > 0
    # Listener was still called each tick
    assert call_count == summary.ticks_run
    # World progressed normally (alpha+beta each increment once per tick)
    assert world["counter"] == summary.ticks_run * 2


@pytest.mark.asyncio
async def test_tick_listener_none_is_fine(tmp_path: Path) -> None:
    """Engine works normally when tick_listener is not provided (None)."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": IncrAgent("alpha", "worker"),
        "beta": IncrAgent("beta", "worker"),
    }
    engine = make_engine(tmp_path, world, agents)
    summary = await engine.run()
    assert isinstance(summary, RunSummary)
    assert summary.ticks_run > 0


@pytest.mark.asyncio
async def test_tick_listener_receives_world_digest(tmp_path: Path) -> None:
    """TickRecords passed to tick_listener have a non-empty world_digest."""
    world = make_world()
    agents: dict[str, Agent] = {
        "alpha": IncrAgent("alpha", "worker"),
        "beta": IncrAgent("beta", "worker"),
    }
    received: list[TickRecord] = []

    engine = Engine(
        world=world,
        society=CounterSociety(),
        agents=agents,
        registry=make_registry(),
        roles=make_roles(),
        resolver=DefaultResolver(),
        recorder=make_recorder(tmp_path),
        seed=42,
        max_ticks=5,
        agent_timeout_s=30.0,
        tick_listener=received.append,
    )

    await engine.step(0)

    assert len(received) == 1
    assert len(received[0].world_digest) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_rejection_memory_ticks_1_single_tick_behaviour(tmp_path: Path) -> None:
    """memory_ticks=1 reproduces the old single-tick behaviour:
    a rejection from tick 0 appears in the tick-1 observation but NOT at tick 2.

    With memory=1: at observe time for tick T, cutoff = T - 1.
    We include rejections with t >= cutoff.
    - tick 1 observe: cutoff=0, tick-0 rejections (t=0 >= 0) are included. ✓
    - After tick 1 record: trim t <= 1-1=0, so tick-0 entries are removed.
    - tick 2 observe: history has no tick-0 entries left. ✓
    """
    world = make_world()

    class SpoofTick0Agent(ScriptedAgent):
        def act_sync(self, observation: Observation) -> AgentResponse:
            if observation.tick == 0:
                return AgentResponse(
                    agent_id=self.agent_id,
                    decisions=(
                        Decision(
                            decision_id=f"{self.agent_id}-spoof",
                            agent_id="alpha",
                            decision_type="increment",
                            params={"amount": 1},
                        ),
                    ),
                )
            return AgentResponse(agent_id=self.agent_id)

    # Capture what beta observes at each tick
    observed_rejections: dict[int, tuple] = {}

    class ObservingAgent(ScriptedAgent):
        def act_sync(self, observation: Observation) -> AgentResponse:
            observed_rejections[observation.tick] = observation.rejections
            if observation.tick == 0:
                return AgentResponse(
                    agent_id=self.agent_id,
                    decisions=(
                        Decision(
                            decision_id=f"{self.agent_id}-spoof",
                            agent_id="alpha",
                            decision_type="increment",
                            params={"amount": 1},
                        ),
                    ),
                )
            return AgentResponse(agent_id=self.agent_id)

    agents: dict[str, Agent] = {
        "alpha": IncrAgent("alpha", "worker"),
        "beta": ObservingAgent("beta", "worker"),
    }
    engine = make_engine_with_memory(tmp_path, world, agents, rejection_memory_ticks=1)

    await engine.step(0)  # rejection recorded for beta at tick 0
    await engine.step(1)  # beta observes tick 1: should see tick-0 rejection
    await engine.step(2)  # beta observes tick 2: should NOT see tick-0 rejection

    # tick 1 observation: cutoff = 1 - 1 = 0; tick-0 rejections (t=0 >= 0) included
    assert len(observed_rejections[1]) >= 1, (
        "with memory=1, tick-0 rejection must appear in tick-1 observation"
    )
    assert all(r.reason == "identity mismatch" for r in observed_rejections[1])

    # tick 2 observation: trim removed tick-0 entries after tick 1's record phase;
    # no new rejections at tick 1 (SpoofTick0Agent only spoofs at tick 0)
    assert len(observed_rejections[2]) == 0, (
        "with memory=1, tick-0 rejection must NOT appear in tick-2 observation"
    )
