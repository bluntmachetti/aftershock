"""The agent-society protocol: every message that crosses the agent/kernel boundary.

All models are frozen. The kernel, societies, and agents communicate exclusively
through these types; a snapshot test pins their shape, so additive evolution only
(new fields must be optional with defaults).

Rationale strings are stored for replay and never affect simulation outcomes.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProposalKind(StrEnum):
    """The four ways agents talk to each other."""

    RESOURCE_REQUEST = "resource_request"  # ask the arbiter/auction for contested resources
    TASK_HANDOFF = "task_handoff"  # transfer responsibility for a task to another agent
    ESCALATION = "escalation"  # flag a situation the sender cannot handle alone
    INFO_SHARE = "info_share"  # broadcast knowledge; never grants resources


class TokenUsage(Frozen):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""


class Decision(Frozen):
    """An action an agent wants taken on the world. Validated against the
    decision registry and the agent's role envelope before it is applied."""

    decision_id: str  # unique within a tick, e.g. "medical-0"
    agent_id: str
    decision_type: str  # key into the DecisionRegistry
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""  # replay-only; simulation-inert


class Proposal(Frozen):
    """A typed negotiation message. recipient=None routes to the resolver
    (e.g. the contested-resource auction); otherwise it lands in the named
    agent's inbox next tick for a bilateral accept/decline."""

    proposal_id: str  # unique within a tick, e.g. "medical-p0"
    sender: str
    recipient: str | None = None
    kind: ProposalKind
    body: dict[str, Any] = Field(default_factory=dict)


class ProposalResponse(Frozen):
    """An agent's accept/decline of a proposal that was in its inbox."""

    proposal_id: str
    responder: str
    accept: bool
    note: str = ""


class ProposalRuling(Frozen):
    """The kernel-recorded outcome of a proposal: who decided, and why."""

    proposal_id: str
    accepted: bool
    decided_by: str  # an agent_id, or "kernel:<resolver-name>"
    reason: str = ""


class Rejection(Frozen):
    """A decision the kernel refused, with the reason. Fed back into the
    issuing agent's next observation so it can adapt instead of retrying."""

    decision_id: str
    agent_id: str
    decision_type: str
    reason: str


class Observation(Frozen):
    """Everything an agent is allowed to see this tick."""

    tick: int
    agent_id: str
    role: str
    view: dict[str, Any]  # role-scoped world view, built by the society
    inbox: tuple[Proposal, ...] = ()  # proposals addressed to this agent
    rulings: tuple[ProposalRuling, ...] = ()  # outcomes of this agent's past proposals
    rejections: tuple[Rejection, ...] = ()  # this agent's rejected decisions last tick
    allowed_decisions: tuple[str, ...] = ()


class AgentResponse(Frozen):
    """Everything an agent emits in one tick. An agent that times out or
    crashes contributes an empty response; the world never blocks on it."""

    agent_id: str
    decisions: tuple[Decision, ...] = ()
    proposals: tuple[Proposal, ...] = ()
    responses: tuple[ProposalResponse, ...] = ()
    usage: TokenUsage | None = None
    error: str = ""  # non-empty when the kernel substituted an empty response


class WorldEvent(Frozen):
    """Something that happened to the world: a decision's effect or a
    scheduled/scenario event. Pure data; the record of cause and effect."""

    event_id: str
    tick: int
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class TickRecord(Frozen):
    """Per-tick provenance: enough to replay, audit, or visualise any run.
    Written append-only as NDJSON by the recorder."""

    tick: int
    observation_digests: dict[str, str]  # agent_id -> sha256 of canonical observation
    responses: tuple[AgentResponse, ...]  # sorted by agent_id
    rulings: tuple[ProposalRuling, ...]
    accepted: tuple[Decision, ...]
    rejected: tuple[Rejection, ...]
    events: tuple[WorldEvent, ...]
    scores: dict[str, float]
    world_digest: str  # sha256 of canonical world state after the tick
