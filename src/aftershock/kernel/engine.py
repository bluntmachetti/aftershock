"""The tick engine: Society Protocol, RunSummary, and Engine.

The 8-phase tick pipeline is deterministic: one rng_for(seed, "tick", tick)
per tick, threaded through phases in order. asyncio.gather results are consumed
in sorted agent order regardless of completion order.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from aftershock.kernel.agents import Agent
from aftershock.kernel.ledger import CostLedger
from aftershock.kernel.negotiation import Resolver
from aftershock.kernel.protocol import (
    AgentResponse,
    Decision,
    Observation,
    Proposal,
    ProposalKind,
    ProposalResponse,
    ProposalRuling,
    Rejection,
    TickRecord,
    WorldEvent,
)
from aftershock.kernel.recorder import Recorder, digest
from aftershock.kernel.registry import DecisionRegistry
from aftershock.kernel.rng import rng_for
from aftershock.kernel.roles import RoleSpec


@runtime_checkable
class Society(Protocol):
    def agent_ids(self) -> tuple[str, ...]: ...
    def role_of(self, agent_id: str) -> str: ...
    def build_view(self, world: Any, agent_id: str, tick: int) -> dict[str, Any]: ...
    def scheduled_events(self, world: Any, tick: int, rng: Any) -> list[WorldEvent]: ...
    def score(self, world: Any, tick: int) -> dict[str, float]: ...
    def is_over(self, world: Any, tick: int) -> bool: ...
    def world_state(self, world: Any) -> dict[str, Any]: ...


@dataclass
class RunSummary:
    run_id: str
    seed: int
    ticks_run: int
    final_scores: dict[str, float]
    cost: dict[str, Any]
    run_dir: str


class Engine:
    def __init__(
        self,
        *,
        world: Any,
        society: Society,
        agents: dict[str, Agent],
        registry: DecisionRegistry,
        roles: dict[str, RoleSpec],
        resolver: Resolver,
        recorder: Recorder,
        seed: int,
        max_ticks: int,
        agent_timeout_s: float = 30.0,
        rejection_memory_ticks: int = 3,
        tick_listener: Callable[[TickRecord, dict[str, Any]], None] | None = None,
    ) -> None:
        # Boot validation
        soc_ids = set(society.agent_ids())
        agent_keys = set(agents.keys())
        if soc_ids != agent_keys:
            raise ValueError(
                f"agent ids mismatch: society={sorted(soc_ids)}, agents={sorted(agent_keys)}"
            )

        for agent_id, _agent in agents.items():
            role_name = society.role_of(agent_id)
            if role_name not in roles:
                raise ValueError(f"agent {agent_id!r} has unknown role {role_name!r}")

        for role_name, role_spec in roles.items():
            for dt in role_spec.allowed_decisions:
                if dt not in registry.decision_types():
                    raise ValueError(
                        f"role {role_name!r} allows unknown decision type {dt!r}"
                    )

        self._world = world
        self._society = society
        self._agents = agents
        self._registry = registry
        self._roles = roles
        self._resolver = resolver
        self._recorder = recorder
        self._seed = seed
        self._max_ticks = max_ticks
        self._agent_timeout_s = agent_timeout_s
        self._rejection_memory_ticks = rejection_memory_ticks
        self._tick_listener = tick_listener
        self._ledger = CostLedger()

        # Feedback buffers filled at end of tick, consumed at start of next
        # inbox: agent_id -> list of Proposal for next tick
        self._next_inbox: dict[str, list[Proposal]] = {aid: [] for aid in soc_ids}
        # rulings: agent_id -> list of ProposalRuling (for proposals that agent sent)
        self._next_rulings: dict[str, list[ProposalRuling]] = {aid: [] for aid in soc_ids}
        # rejection history: agent_id -> deque of (tick, Rejection), oldest first
        # trimmed to rejection_memory_ticks horizon at the end of each tick
        self._rejection_history: dict[str, deque[tuple[int, Rejection]]] = {
            aid: deque() for aid in soc_ids
        }
        # pending bilateral proposals delivered last tick, waiting for responses
        # maps proposal_id -> Proposal
        self._pending_bilateral: dict[str, Proposal] = {}

    async def run(self) -> RunSummary:
        tick = 0
        last_scores: dict[str, float] = {}
        while tick < self._max_ticks:
            record = await self.step(tick)
            last_scores = dict(record.scores)
            if self._society.is_over(self._world, tick):
                break
            tick += 1
        cost = self._ledger.totals()
        self._recorder.write_final_summary(last_scores, cost)
        self._recorder.close()
        return RunSummary(
            run_id=self._recorder.run_dir.name,
            seed=self._seed,
            ticks_run=tick + 1,
            final_scores=last_scores,
            cost=cost,
            run_dir=str(self._recorder.run_dir),
        )

    async def step(self, tick: int) -> TickRecord:
        rng = rng_for(self._seed, "tick", tick)
        sorted_ids = sorted(self._agents.keys())

        # ---------------------------------------------------------------
        # Phase 1: OBSERVE
        # ---------------------------------------------------------------
        observations: dict[str, Observation] = {}
        observation_digests: dict[str, str] = {}

        for agent_id in sorted_ids:
            role_name = self._society.role_of(agent_id)
            role_spec = self._roles[role_name]
            # Build rejections from the last rejection_memory_ticks ticks,
            # most recent first, capped at 12 entries total.
            # Include ticks t where t >= tick - rejection_memory_ticks.
            cutoff = tick - self._rejection_memory_ticks
            recent: list[Rejection] = []
            for t, rej in reversed(self._rejection_history[agent_id]):
                if t < cutoff:
                    break
                recent.append(rej)
                if len(recent) == 12:
                    break
            obs = Observation(
                tick=tick,
                agent_id=agent_id,
                role=role_name,
                view=self._society.build_view(self._world, agent_id, tick),
                inbox=tuple(self._next_inbox[agent_id]),
                rulings=tuple(self._next_rulings[agent_id]),
                rejections=tuple(recent),
                allowed_decisions=role_spec.allowed_decisions,
            )
            observations[agent_id] = obs
            observation_digests[agent_id] = digest(obs)

        # ---------------------------------------------------------------
        # Phase 2: ACT
        # ---------------------------------------------------------------
        async def _act_safe(agent_id: str) -> AgentResponse:
            agent = self._agents[agent_id]
            obs = observations[agent_id]
            try:
                result = await asyncio.wait_for(
                    agent.act(obs), timeout=self._agent_timeout_s
                )
                return result
            except TimeoutError:
                return AgentResponse(agent_id=agent_id, error="timeout")
            except Exception as exc:
                return AgentResponse(agent_id=agent_id, error=repr(exc))

        # Gather in any order, then reassemble in sorted agent order
        raw_results = await asyncio.gather(*[_act_safe(aid) for aid in sorted_ids])
        responses_by_id: dict[str, AgentResponse] = dict(zip(sorted_ids, raw_results, strict=True))

        # Identity check + duplicate decision_id rejection
        tick_decision_ids: set[str] = set()
        cleaned_responses: dict[str, AgentResponse] = {}
        this_tick_rejections: dict[str, list[Rejection]] = {aid: [] for aid in sorted_ids}
        this_tick_proposal_rulings: dict[str, list[ProposalRuling]] = {
            aid: [] for aid in sorted_ids
        }

        for agent_id in sorted_ids:
            raw = responses_by_id[agent_id]

            # Filter decisions: identity + duplicate
            valid_decisions: list[Decision] = []
            for dec in raw.decisions:
                if dec.agent_id != agent_id:
                    this_tick_rejections[agent_id].append(
                        Rejection(
                            decision_id=dec.decision_id,
                            agent_id=agent_id,
                            decision_type=dec.decision_type,
                            reason="identity mismatch",
                        )
                    )
                    continue
                if dec.decision_id in tick_decision_ids:
                    this_tick_rejections[agent_id].append(
                        Rejection(
                            decision_id=dec.decision_id,
                            agent_id=agent_id,
                            decision_type=dec.decision_type,
                            reason="duplicate decision_id",
                        )
                    )
                    continue
                tick_decision_ids.add(dec.decision_id)
                valid_decisions.append(dec)

            # Filter proposals: identity (sender mismatch → declined ruling)
            valid_proposals: list[Proposal] = []
            for prop in raw.proposals:
                if prop.sender != agent_id:
                    this_tick_proposal_rulings[agent_id].append(
                        ProposalRuling(
                            proposal_id=prop.proposal_id,
                            accepted=False,
                            decided_by="kernel:identity",
                            reason="identity mismatch",
                        )
                    )
                    continue
                valid_proposals.append(prop)

            # Filter responses: responder mismatch → declined ruling on the proposal
            valid_responses: list[ProposalResponse] = []
            for resp in raw.responses:
                if resp.responder != agent_id:
                    # Drop silently with declined ruling attributed to kernel
                    this_tick_proposal_rulings[agent_id].append(
                        ProposalRuling(
                            proposal_id=resp.proposal_id,
                            accepted=False,
                            decided_by="kernel:identity",
                            reason="identity mismatch",
                        )
                    )
                    continue
                valid_responses.append(resp)

            cleaned_responses[agent_id] = AgentResponse(
                agent_id=agent_id,
                decisions=tuple(valid_decisions),
                proposals=tuple(valid_proposals),
                responses=tuple(valid_responses),
                usage=raw.usage,
                error=raw.error,
            )

        # ---------------------------------------------------------------
        # Phase 3: RESOLVE — route proposals
        # ---------------------------------------------------------------
        # Collect all valid proposals this tick
        all_proposals: list[Proposal] = []
        for agent_id in sorted_ids:
            all_proposals.extend(cleaned_responses[agent_id].proposals)

        # Collect all responses this tick, keyed by proposal_id
        all_responses_by_proposal: dict[str, ProposalResponse] = {}
        for agent_id in sorted_ids:
            for resp in cleaned_responses[agent_id].responses:
                # Last one wins if duplicate (shouldn't happen after identity filter)
                all_responses_by_proposal[resp.proposal_id] = resp

        # Categorise this tick's proposals
        arbiter_proposals: list[Proposal] = []
        broadcast_proposals: list[Proposal] = []
        new_bilateral: list[Proposal] = []  # bilateral sent this tick → deliver next tick

        for prop in all_proposals:
            if prop.recipient is None and prop.kind == ProposalKind.INFO_SHARE:
                broadcast_proposals.append(prop)
            elif prop.recipient is None:
                arbiter_proposals.append(prop)
            else:
                new_bilateral.append(prop)

        # Pair last tick's pending bilaterals with this tick's responses
        answered: list[tuple[Proposal, ProposalResponse]] = []
        expired: list[Proposal] = []

        for prop_id, prop in sorted(self._pending_bilateral.items()):
            if prop_id in all_responses_by_proposal:
                answered.append((prop, all_responses_by_proposal[prop_id]))
            else:
                expired.append(prop)

        # Call resolver
        resolver_rulings, granted_decisions = self._resolver.resolve(
            self._world, tick, arbiter_proposals, answered, expired, rng
        )

        # Broadcast proposals get automatic accepted rulings
        broadcast_rulings: list[ProposalRuling] = []
        for prop in broadcast_proposals:
            broadcast_rulings.append(
                ProposalRuling(
                    proposal_id=prop.proposal_id,
                    accepted=True,
                    decided_by="kernel:broadcast",
                    reason="",
                )
            )

        all_rulings: list[ProposalRuling] = (
            resolver_rulings
            + broadcast_rulings
            + [r for rlist in this_tick_proposal_rulings.values() for r in rlist]
        )

        # ---------------------------------------------------------------
        # Phase 4: VALIDATE
        # ---------------------------------------------------------------
        # Agent decisions sorted by (agent_id, decision_id)
        agent_decisions_sorted: list[tuple[str, Decision]] = []
        for agent_id in sorted_ids:
            for dec in cleaned_responses[agent_id].decisions:
                agent_decisions_sorted.append((agent_id, dec))
        agent_decisions_sorted.sort(key=lambda x: (x[0], x[1].decision_id))

        accepted_decisions: list[Decision] = []
        accepted_params: list[Any] = []
        rejected_decisions: list[Rejection] = []

        for agent_id, dec in agent_decisions_sorted:
            role_name = self._society.role_of(agent_id)
            allowed = self._roles[role_name].allowed_decisions
            params, reason = self._registry.validate(self._world, dec, allowed=allowed)
            if reason is not None:
                rejected_decisions.append(
                    Rejection(
                        decision_id=dec.decision_id,
                        agent_id=agent_id,
                        decision_type=dec.decision_type,
                        reason=reason,
                    )
                )
                this_tick_rejections[agent_id].append(
                    Rejection(
                        decision_id=dec.decision_id,
                        agent_id=agent_id,
                        decision_type=dec.decision_type,
                        reason=reason,
                    )
                )
            else:
                accepted_decisions.append(dec)
                accepted_params.append(params)

        # Granted decisions (resolver-issued) — validated with allowed=None
        for granted_dec in granted_decisions:
            params, reason = self._registry.validate(self._world, granted_dec, allowed=None)
            if reason is not None:
                rejected_decisions.append(
                    Rejection(
                        decision_id=granted_dec.decision_id,
                        agent_id=granted_dec.agent_id,
                        decision_type=granted_dec.decision_type,
                        reason=reason,
                    )
                )
                if granted_dec.agent_id in this_tick_rejections:
                    this_tick_rejections[granted_dec.agent_id].append(
                        Rejection(
                            decision_id=granted_dec.decision_id,
                            agent_id=granted_dec.agent_id,
                            decision_type=granted_dec.decision_type,
                            reason=reason,
                        )
                    )
            else:
                accepted_decisions.append(granted_dec)
                accepted_params.append(params)

        # Also add identity-check rejections to the rejected list for the record
        for agent_id in sorted_ids:
            for rej in this_tick_rejections[agent_id]:
                # Avoid double-adding registry rejections (already added above)
                if not any(r.decision_id == rej.decision_id for r in rejected_decisions):
                    rejected_decisions.append(rej)

        # ---------------------------------------------------------------
        # Phase 5: APPLY
        # ---------------------------------------------------------------
        all_events: list[WorldEvent] = []
        for dec, params in zip(accepted_decisions, accepted_params, strict=True):
            events = self._registry.apply(self._world, dec, params, tick, rng)
            all_events.extend(events)

        # ---------------------------------------------------------------
        # Phase 6: WORLD — scheduled events
        # ---------------------------------------------------------------
        world_events = self._society.scheduled_events(self._world, tick, rng)
        all_events.extend(world_events)

        # ---------------------------------------------------------------
        # Phase 7: SCORE
        # ---------------------------------------------------------------
        scores = self._society.score(self._world, tick)

        # ---------------------------------------------------------------
        # Phase 8: RECORD — ledger, TickRecord, refill feedback buffers
        # ---------------------------------------------------------------
        for agent_id in sorted_ids:
            agent_resp = cleaned_responses[agent_id]
            if agent_resp.usage is not None:
                self._ledger.record(tick, agent_id, agent_resp.usage)

        world_state_dict = self._society.world_state(self._world)
        world_dig = digest(world_state_dict)

        # Build sorted responses tuple
        sorted_responses = tuple(cleaned_responses[aid] for aid in sorted_ids)

        record = TickRecord(
            tick=tick,
            observation_digests=observation_digests,
            responses=sorted_responses,
            rulings=tuple(all_rulings),
            accepted=tuple(accepted_decisions),
            rejected=tuple(rejected_decisions),
            events=tuple(all_events),
            scores=scores,
            world_digest=world_dig,
        )
        self._recorder.write_tick(record, world_state_dict)

        # Call tick_listener if provided; swallow exceptions so they never kill the tick
        if self._tick_listener is not None:
            with contextlib.suppress(Exception):
                self._tick_listener(record, world_state_dict)

        # Refill feedback buffers for next tick
        # Reset inbox and rulings; rejection history is appended, not reset
        for aid in sorted_ids:
            self._next_inbox[aid] = []
            self._next_rulings[aid] = []

        # Bilateral proposals delivered next tick (to recipient's inbox)
        self._pending_bilateral = {}
        for prop in new_bilateral:
            recipient = prop.recipient
            if recipient is not None and recipient in self._next_inbox:
                self._next_inbox[recipient].append(prop)
                self._pending_bilateral[prop.proposal_id] = prop

        # Broadcast proposals delivered next tick to every OTHER agent's inbox
        for prop in broadcast_proposals:
            for aid in sorted_ids:
                if aid != prop.sender:
                    self._next_inbox[aid].append(prop)

        # Rulings to the senders of proposals
        rulings_by_proposal: dict[str, ProposalRuling] = {
            r.proposal_id: r for r in all_rulings
        }
        for prop in all_proposals:
            ruling = rulings_by_proposal.get(prop.proposal_id)
            if ruling is not None and prop.sender in self._next_rulings:
                self._next_rulings[prop.sender].append(ruling)

        # Append this tick's rejections to each agent's history, then trim
        # entries that fall outside the memory window (tick <= tick - memory_ticks).
        horizon = tick - self._rejection_memory_ticks
        for agent_id in sorted_ids:
            hist = self._rejection_history[agent_id]
            for rej in this_tick_rejections[agent_id]:
                hist.append((tick, rej))
            # Trim from the left: remove entries too old to ever appear again
            while hist and hist[0][0] <= horizon:
                hist.popleft()

        return record
