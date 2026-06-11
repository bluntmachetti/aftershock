"""Pins the shape of the agent/kernel protocol.

If this test fails you changed the portability boundary. New fields must be
optional with defaults (additive evolution); renames and removals break every
agent, society, and recorded run.
"""

from aftershock.kernel import protocol

EXPECTED_FIELDS = {
    "TokenUsage": {"prompt_tokens", "completion_tokens", "cost_usd", "model"},
    "Decision": {"decision_id", "agent_id", "decision_type", "params", "rationale"},
    "Proposal": {"proposal_id", "sender", "recipient", "kind", "body"},
    "ProposalResponse": {"proposal_id", "responder", "accept", "note"},
    "ProposalRuling": {"proposal_id", "accepted", "decided_by", "reason"},
    "Rejection": {"decision_id", "agent_id", "decision_type", "reason"},
    "Observation": {
        "tick",
        "agent_id",
        "role",
        "view",
        "inbox",
        "rulings",
        "rejections",
        "allowed_decisions",
    },
    "AgentResponse": {"agent_id", "decisions", "proposals", "responses", "usage", "error"},
    "WorldEvent": {"event_id", "tick", "kind", "payload"},
    "TickRecord": {
        "tick",
        "observation_digests",
        "responses",
        "rulings",
        "accepted",
        "rejected",
        "events",
        "scores",
        "world_digest",
    },
}

EXPECTED_PROPOSAL_KINDS = {"resource_request", "task_handoff", "escalation", "info_share"}


def test_model_fields_are_pinned():
    for model_name, expected in EXPECTED_FIELDS.items():
        model = getattr(protocol, model_name)
        assert set(model.model_fields) == expected, f"{model_name} shape changed"


def test_proposal_kinds_are_pinned():
    assert {k.value for k in protocol.ProposalKind} == EXPECTED_PROPOSAL_KINDS


def test_models_are_frozen():
    decision = protocol.Decision(decision_id="a-0", agent_id="a", decision_type="noop")
    try:
        decision.agent_id = "b"
        raise AssertionError("Decision should be frozen")
    except Exception:
        pass
