"""Tool definitions and tool-call mapping for Qwen Cloud function calling.

Three exports:
  build_role_tools   — builds OpenAI-format tool definitions filtered by role
  map_tool_calls     — maps tool_call response array → AgentResponse
  tool_contract       — behavioral-only system-prompt contract for tool-mode agents
"""

from __future__ import annotations

import json
from typing import Any

from aftershock.kernel.protocol import (
    AgentResponse,
    Decision,
    Proposal,
    ProposalKind,
    ProposalResponse,
)

_DECISION_TOOLS = frozenset({"set_priority", "recall", "repair_road", "broadcast"})
_PROPOSAL_KINDS = frozenset({"resource_request", "task_handoff", "escalation", "info_share"})
_DISPATCH = "dispatch"


def build_role_tools(
    allowed: tuple[str, ...],
    decision_docs: dict[str, str],
    proposal_docs: dict[str, str],
    decision_param_schemas: dict[str, dict[str, Any]],
    proposal_param_schemas: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []

    for dtype in allowed:
        if dtype == _DISPATCH:
            continue
        if dtype not in decision_docs or dtype not in decision_param_schemas:
            continue
        tools.append(
            _make_decision_tool(
                name=dtype,
                description=decision_docs[dtype],
                params_schema=decision_param_schemas[dtype],
            )
        )

    for kind in sorted(_PROPOSAL_KINDS):
        if kind in proposal_docs:
            tools.append(
                _make_proposal_tool(
                    kind=kind,
                    description=proposal_docs[kind],
                    params_schema=proposal_param_schemas.get(kind, _proposal_default_params(kind)),
                )
            )

    tools.append(
        {
            "type": "function",
            "function": {
                "name": "accept_proposal",
                "description": (
                    "Accept a proposal from your inbox. Use exact proposal_id from the inbox."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "proposal_id": {
                            "type": "string",
                            "description": "The proposal ID from your inbox",
                        },
                        "note": {
                            "type": "string",
                            "description": "Optional acknowledgment note",
                        },
                    },
                    "required": ["proposal_id"],
                },
            },
        }
    )
    tools.append(
        {
            "type": "function",
            "function": {
                "name": "decline_proposal",
                "description": "Decline a proposal from your inbox.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "proposal_id": {
                            "type": "string",
                            "description": "The proposal ID from your inbox",
                        },
                        "note": {
                            "type": "string",
                            "description": "Optional reason for declining",
                        },
                    },
                    "required": ["proposal_id"],
                },
            },
        }
    )

    tools.append(
        {
            "type": "function",
            "function": {
                "name": "no_op",
                "description": (
                    "Take no action this tick — call when you have nothing to contribute."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "rationale": {
                            "type": "string",
                            "description": "Why no action this tick",
                        },
                    },
                },
            },
        }
    )

    return tools


def _make_decision_tool(
    name: str, description: str, params_schema: dict[str, Any]
) -> dict[str, Any]:
    """Build a single decision tool definition with rationale field added."""
    params = dict(params_schema)
    props = params.setdefault("properties", {})
    props["rationale"] = {"type": "string", "description": "Under 25 words, why this decision"}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": params,
        },
    }


def _make_proposal_tool(
    kind: str, description: str, params_schema: dict[str, Any]
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": f"propose_{kind}",
            "description": description,
            "parameters": params_schema,
        },
    }


def _proposal_default_params(kind: str) -> dict[str, Any]:
    """Minimal params schema for proposal kinds when no explicit schema is provided."""
    base: dict[str, Any] = {
        "type": "object",
        "properties": {
            "recipient": {
                "type": "string",
                "description": "Target agent_id, or null for auction-routed proposals",
            },
        },
    }
    if kind == "resource_request":
        base["properties"].update(
            {
                "mission_id": {"type": "string"},
                "resource": {"type": "string"},
                "qty": {"type": "integer", "minimum": 1},
                "urgency": {"type": "integer", "minimum": 1, "maximum": 10},
            }
        )
        base["required"] = ["mission_id", "resource", "qty", "urgency"]
    elif kind in ("escalation", "task_handoff"):
        base["properties"].update(
            {
                "mission_id": {
                    "type": "string",
                    "description": "Mission ID from the observation",
                },
                "why": {
                    "type": "string",
                    "description": "Reason for escalation or handoff",
                },
            }
        )
        base["required"] = ["mission_id", "why"]
    elif kind == "info_share":
        base["properties"].update(
            {
                "message": {
                    "type": "string",
                    "description": "Concise factual information to share",
                },
            }
        )
        base["required"] = ["message"]
    return base


# ---------------------------------------------------------------------------
# map_tool_calls — always returns AgentResponse
# ---------------------------------------------------------------------------


def map_tool_calls(
    tool_calls: list[dict[str, Any]],
    agent_id: str,
    tick: int,
    inbox_ids: frozenset[str],
) -> AgentResponse:
    if not tool_calls:
        return AgentResponse(
            agent_id=agent_id,
            error="tool mode: no tool_calls returned",
        )

    decisions: list[Decision] = []
    proposals: list[Proposal] = []
    responses: list[ProposalResponse] = []

    for i, tc in enumerate(tool_calls):
        fn = tc.get("function", {})
        name = fn.get("name", "")
        args_str = fn.get("arguments", "{}")

        try:
            args: dict[str, Any] = json.loads(args_str)
        except (json.JSONDecodeError, TypeError):
            continue

        if name in _DECISION_TOOLS:
            decisions.append(
                Decision(
                    decision_id=f"{agent_id}-t{tick}-d{i}",
                    agent_id=agent_id,
                    decision_type=name,
                    params={k: v for k, v in args.items() if k != "rationale"},
                    rationale=str(args.get("rationale", "")),
                )
            )
        elif name.startswith("propose_"):
            kind_str = name[len("propose_") :]
            try:
                kind = ProposalKind(kind_str)
            except ValueError:
                continue
            proposals.append(
                Proposal(
                    proposal_id=f"{agent_id}-t{tick}-p{i}",
                    sender=agent_id,
                    recipient=args.get("recipient"),
                    kind=kind,
                    body={k: v for k, v in args.items() if k != "recipient"},
                )
            )
        elif name == "accept_proposal":
            pid = args.get("proposal_id", "")
            if pid not in inbox_ids:
                continue
            responses.append(
                ProposalResponse(
                    proposal_id=pid,
                    responder=agent_id,
                    accept=True,
                    note=str(args.get("note", "")),
                )
            )
        elif name == "decline_proposal":
            pid = args.get("proposal_id", "")
            if pid not in inbox_ids:
                continue
            responses.append(
                ProposalResponse(
                    proposal_id=pid,
                    responder=agent_id,
                    accept=False,
                    note=str(args.get("note", "")),
                )
            )
        elif name == "no_op":
            pass
        else:
            continue

    return AgentResponse(
        agent_id=agent_id,
        decisions=tuple(decisions),
        proposals=tuple(proposals),
        responses=tuple(responses),
    )


# ---------------------------------------------------------------------------
# tool_contract — behavioral-only system-prompt contract for tool-mode agents
# ---------------------------------------------------------------------------


def tool_contract(has_proposals: bool) -> str:
    lines = [
        "## How to Act",
        "",
        "You have function tools available. Call them to make decisions and propose actions.",
        "Call no_op if you have nothing to contribute this tick.",
        "",
        "- Use EXACT ids from the observation. Never invent mission or proposal ids.",
        "- Keep rationales under 25 words.",
    ]
    if has_proposals:
        lines.extend(
            [
                "- Respond to inbox messages via accept_proposal or decline_proposal.",
                "- Resources come only through propose_resource_request — never dispatch",
                "  decisions.",
                "- Answer every proposal in your inbox via accept_proposal or decline_proposal.",
                "- Escalate critical missions to the commander via propose_escalation.",
            ]
        )
    return "\n".join(lines)
