"""LLM-backed agent: calls a Provider, parses the output, maps it to protocol types.

System prompt = role.system_prompt + "\\n\\n" + contract
User prompt   = render_observation(obs)
IDs           = f"{agent_id}-t{tick}-{i}" (decisions) / f"{agent_id}-t{tick}-p{i}" (proposals)
Identity      = forced on every decision/proposal/response produced
Inbox filter  = ProposalResponse entries whose proposal_id is not in inbox are dropped
Errors        = AgentResponse(error=...) with usage attached when available — never raises
Tool mode     = when role.use_tools, calls provider with tools, maps via tool_mapper
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from aftershock.kernel.agents import Agent
from aftershock.kernel.protocol import (
    AgentResponse,
    Decision,
    Observation,
    Proposal,
    ProposalKind,
    ProposalResponse,
    TokenUsage,
)
from aftershock.kernel.roles import RoleSpec
from aftershock.llm.digest import render_observation
from aftershock.llm.parse import LLMParseError, parse_llm_output
from aftershock.llm.provider import Provider


def sample_seed(engine_seed: int, agent_id: str, tick: int) -> int:
    """Deterministic per-(engine_seed, agent, tick) sampling seed for M1.

    Uses SHA-256, NOT Python's built-in ``hash()`` — string hashing is salted
    per process (PYTHONHASHSEED), so ``hash()`` would give different seeds on
    every run and silently defeat reproducibility. Returns a 31-bit non-negative
    int, comfortably inside the OpenAI/DashScope ``seed`` integer range.
    """
    h = hashlib.sha256(f"{engine_seed}:{agent_id}:{tick}".encode()).digest()
    return int.from_bytes(h[:4], "big") & 0x7FFFFFFF


class LLMAgent(Agent):
    """An agent driven by a language model via a Provider."""

    def __init__(
        self,
        agent_id: str,
        role: RoleSpec,
        provider: Provider,
        contract: str,
        tool_defs: list[dict] | None = None,
        tool_mapper: Callable[..., AgentResponse] | None = None,
        engine_seed: int | None = None,
    ) -> None:
        super().__init__(agent_id, role.name)
        self._role = role
        self._provider = provider
        self._system = role.system_prompt + "\n\n" + contract
        self._tool_defs = tool_defs
        self._tool_mapper = tool_mapper
        # M1: when set (the --seed-sampler opt-in), each provider call gets a
        # deterministic per-tick seed. None ⇒ no seed sent (the legacy default).
        self._engine_seed = engine_seed

    async def act(self, observation: Observation) -> AgentResponse:
        """Call the provider, parse output, return a fully typed AgentResponse.

        Never raises. Provider or parse failure returns AgentResponse(error=...).
        Usage is attached when the provider call succeeded but parsing failed.
        """
        tick = observation.tick
        user = render_observation(observation)
        inbox_ids: frozenset[str] = frozenset(p.proposal_id for p in observation.inbox)
        seed: int | None = (
            sample_seed(self._engine_seed, self.agent_id, tick)
            if self._engine_seed is not None
            else None
        )

        usage: TokenUsage | None = None
        try:
            if self._role.use_tools:
                if not self._tool_defs or not self._tool_mapper:
                    return AgentResponse(
                        agent_id=self.agent_id,
                        error="tool mode: role configured for tools but no "
                        "tool_defs or tool_mapper provided",
                    )
                result = await self._provider.chat(
                    model=self._role.model,
                    system=self._system,
                    user=user,
                    temperature=self._role.temperature,
                    json_mode=False,
                    tools=self._tool_defs,
                    tool_choice="auto",
                    seed=seed,
                )
                usage = result.usage
                response = self._tool_mapper(
                    result.tool_calls or [], self.agent_id, tick, inbox_ids
                )
                return response.model_copy(update={"usage": usage})
            else:
                result = await self._provider.chat(
                    model=self._role.model,
                    system=self._system,
                    user=user,
                    temperature=self._role.temperature,
                    json_mode=True,
                    seed=seed,
                )
                usage = result.usage
                text = result.text
        except Exception as exc:  # spec: act() must never raise (DESIGN.md:450)
            return AgentResponse(
                agent_id=self.agent_id,
                error=f"provider error: {exc!s:.200}",
            )

        # --- Parse ---
        try:
            llm_out = parse_llm_output(text)
        except LLMParseError as exc:
            return AgentResponse(
                agent_id=self.agent_id,
                usage=usage,
                error=f"parse error: {exc!s:.200}",
            )

        # --- Map LLMOutput -> protocol types ---
        # (inbox_ids computed once at the top of act(), reused here for inbox filtering)
        decisions: list[Decision] = []
        proposals: list[Proposal] = []
        responses: list[ProposalResponse] = []

        for i, llm_dec in enumerate(llm_out.decisions):
            decisions.append(
                Decision(
                    decision_id=f"{self.agent_id}-t{tick}-{i}",
                    agent_id=self.agent_id,  # force identity
                    decision_type=llm_dec.decision_type,
                    params=llm_dec.params,
                    rationale=llm_dec.rationale,
                )
            )

        for i, llm_prop in enumerate(llm_out.proposals):
            # Validate kind: unknown strings are silently dropped — Proposal.kind is a
            # frozen StrEnum field that re-validates on construction, so passing a raw
            # unknown str would raise pydantic ValidationError and violate the never-raises
            # contract. The spec's pass-through intent (DESIGN.md:396) applies to decisions
            # (free str field); for proposals, dropping the unknown-kind entry individually
            # preserves all valid proposals while avoiding the crash.
            try:
                kind = ProposalKind(llm_prop.kind)
            except ValueError:
                continue  # unknown kind: drop this proposal, keep the rest
            proposals.append(
                Proposal(
                    proposal_id=f"{self.agent_id}-t{tick}-p{i}",
                    sender=self.agent_id,  # force identity
                    recipient=llm_prop.recipient,
                    kind=kind,
                    body=llm_prop.body,
                )
            )

        for llm_resp in llm_out.responses:
            # Drop responses whose proposal_id is not in the inbox
            if llm_resp.proposal_id not in inbox_ids:
                continue
            responses.append(
                ProposalResponse(
                    proposal_id=llm_resp.proposal_id,
                    responder=self.agent_id,  # force identity
                    accept=llm_resp.accept,
                    note=llm_resp.note,
                )
            )

        return AgentResponse(
            agent_id=self.agent_id,
            decisions=tuple(decisions),
            proposals=tuple(proposals),
            responses=tuple(responses),
            usage=usage,
        )
