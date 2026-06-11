"""LLM-backed agent: calls a Provider, parses the output, maps it to protocol types.

System prompt = role.system_prompt + "\\n\\n" + contract
User prompt   = render_observation(obs)
IDs           = f"{agent_id}-t{tick}-{i}" (decisions) / f"{agent_id}-t{tick}-p{i}" (proposals)
Identity      = forced on every decision/proposal/response produced
Inbox filter  = ProposalResponse entries whose proposal_id is not in inbox are dropped
Errors        = AgentResponse(error=...) with usage attached when available — never raises
"""

from __future__ import annotations

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


class LLMAgent(Agent):
    """An agent driven by a language model via a Provider."""

    def __init__(
        self,
        agent_id: str,
        role: RoleSpec,
        provider: Provider,
        contract: str,
    ) -> None:
        super().__init__(agent_id, role.name)
        self._role = role
        self._provider = provider
        self._system = role.system_prompt + "\n\n" + contract

    async def act(self, observation: Observation) -> AgentResponse:
        """Call the provider, parse output, return a fully typed AgentResponse.

        Never raises. Provider or parse failure returns AgentResponse(error=...).
        Usage is attached when the provider call succeeded but parsing failed.
        """
        tick = observation.tick
        user = render_observation(observation)

        # --- Provider call ---
        usage: TokenUsage | None = None
        try:
            result = await self._provider.chat(
                model=self._role.model,
                system=self._system,
                user=user,
                temperature=self._role.temperature,
                json_mode=True,
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

        # --- Build the inbox proposal_id set for inbox filtering ---
        inbox_ids: frozenset[str] = frozenset(p.proposal_id for p in observation.inbox)

        # --- Map LLMOutput -> protocol types ---
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
