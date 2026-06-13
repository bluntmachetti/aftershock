from __future__ import annotations

import json

from aftershock.kernel.protocol import AgentResponse, ProposalKind
from aftershock.town.tool_contract import (
    build_role_tools,
    map_tool_calls,
    tool_contract,
)


def _make_tool_call(name: str, args: dict) -> dict:
    return {"function": {"name": name, "arguments": json.dumps(args)}}


class TestBuildRoleTools:
    def test_filters_by_allowed_decisions(self) -> None:
        tools = build_role_tools(
            allowed=("recall",),
            decision_docs={"recall": "recall desc"},
            proposal_docs={},
            decision_param_schemas={
                "recall": {
                    "type": "object",
                    "properties": {
                        "mission_id": {"type": "string"},
                        "resource": {"type": "string"},
                        "qty": {"type": "integer", "minimum": 1},
                    },
                    "required": ["mission_id", "resource", "qty"],
                }
            },
            proposal_param_schemas={},
        )
        names = {t["function"]["name"] for t in tools}
        assert "recall" in names
        assert "set_priority" not in names
        assert "no_op" in names

    def test_no_dispatch_tool_built(self) -> None:
        tools = build_role_tools(
            allowed=("dispatch",),
            decision_docs={"dispatch": "dispatch desc"},
            proposal_docs={},
            decision_param_schemas={"dispatch": {"type": "object", "properties": {}}},
            proposal_param_schemas={},
        )
        names = {t["function"]["name"] for t in tools}
        assert "dispatch" not in names

    def test_proposal_tools_have_propose_prefix(self) -> None:
        tools = build_role_tools(
            allowed=(),
            decision_docs={},
            proposal_docs={
                "resource_request": "bid in auction",
                "escalation": "alert commander",
            },
            decision_param_schemas={},
            proposal_param_schemas={},
        )
        names = {t["function"]["name"] for t in tools}
        assert "propose_resource_request" in names
        assert "propose_escalation" in names
        assert "resource_request" not in names

    def test_response_tools_present(self) -> None:
        tools = build_role_tools(
            allowed=(),
            decision_docs={},
            proposal_docs={},
            decision_param_schemas={},
            proposal_param_schemas={},
        )
        names = {t["function"]["name"] for t in tools}
        assert "accept_proposal" in names
        assert "decline_proposal" in names

    def test_no_op_tool_always_present(self) -> None:
        tools = build_role_tools(
            allowed=(),
            decision_docs={},
            proposal_docs={},
            decision_param_schemas={},
            proposal_param_schemas={},
        )
        names = {t["function"]["name"] for t in tools}
        assert "no_op" in names

    def test_rationale_only_on_decision_tools(self) -> None:
        tools = build_role_tools(
            allowed=("broadcast",),
            decision_docs={"broadcast": "broadcast desc"},
            proposal_docs={"info_share": "share info"},
            decision_param_schemas={
                "broadcast": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                }
            },
            proposal_param_schemas={},
        )
        for t in tools:
            name = t["function"]["name"]
            props = t["function"]["parameters"].get("properties", {})
            if name in ("broadcast", "set_priority", "recall", "repair_road"):
                assert "rationale" in props, f"{name} missing rationale"
            elif name.startswith("propose_") or name in ("accept_proposal", "decline_proposal"):
                assert "rationale" not in props, f"{name} has rationale"


class TestToolContract:
    def test_has_no_json_schema(self) -> None:
        contract = tool_contract(has_proposals=True)
        assert '"decisions"' not in contract
        assert "```json" not in contract
        assert "```" not in contract
        assert "{" not in contract

    def test_mentions_no_op(self) -> None:
        contract = tool_contract(has_proposals=True)
        assert "no_op" in contract

    def test_no_proposals_variant(self) -> None:
        contract = tool_contract(has_proposals=False)
        assert "propose_resource_request" not in contract
        assert "inbox" not in contract.lower()


class TestMapToolCalls:
    def test_no_op_returns_empty_agent_response(self) -> None:
        result = map_tool_calls(
            tool_calls=[_make_tool_call("no_op", {})],
            agent_id="medical",
            tick=1,
            inbox_ids=frozenset(),
        )
        assert isinstance(result, AgentResponse)
        assert result.error == ""
        assert result.decisions == ()
        assert result.proposals == ()
        assert result.responses == ()

    def test_empty_tool_calls_returns_error(self) -> None:
        result = map_tool_calls(tool_calls=[], agent_id="medical", tick=1, inbox_ids=frozenset())
        assert result.error != ""
        assert "no tool_calls" in result.error

    def test_maps_decision_tool(self) -> None:
        result = map_tool_calls(
            tool_calls=[
                _make_tool_call(
                    "set_priority",
                    {
                        "mission_id": "m1",
                        "priority": 8,
                        "rationale": "urgent",
                    },
                )
            ],
            agent_id="commander",
            tick=3,
            inbox_ids=frozenset(),
        )
        assert result.error == ""
        assert len(result.decisions) == 1
        d = result.decisions[0]
        assert d.decision_type == "set_priority"
        assert d.agent_id == "commander"
        assert d.decision_id == "commander-t3-d0"
        assert d.params == {"mission_id": "m1", "priority": 8}
        assert d.rationale == "urgent"

    def test_maps_proposal_tool(self) -> None:
        result = map_tool_calls(
            tool_calls=[
                _make_tool_call(
                    "propose_resource_request",
                    {
                        "mission_id": "m2",
                        "resource": "ambulance",
                        "qty": 1,
                        "urgency": 7,
                        "recipient": None,
                    },
                )
            ],
            agent_id="medical",
            tick=5,
            inbox_ids=frozenset(),
        )
        assert len(result.proposals) == 1
        p = result.proposals[0]
        assert p.sender == "medical"
        assert p.kind == ProposalKind.RESOURCE_REQUEST
        assert p.body["mission_id"] == "m2"

    def test_maps_accept_proposal(self) -> None:
        inbox_id = "commander-t1-p0"
        result = map_tool_calls(
            tool_calls=[
                _make_tool_call(
                    "accept_proposal",
                    {"proposal_id": inbox_id, "note": "ok"},
                )
            ],
            agent_id="medical",
            tick=2,
            inbox_ids=frozenset({inbox_id}),
        )
        assert len(result.responses) == 1
        r = result.responses[0]
        assert r.proposal_id == inbox_id
        assert r.responder == "medical"
        assert r.accept is True

    def test_maps_decline_proposal(self) -> None:
        inbox_id = "commander-t1-p0"
        result = map_tool_calls(
            tool_calls=[
                _make_tool_call(
                    "decline_proposal",
                    {"proposal_id": inbox_id},
                )
            ],
            agent_id="medical",
            tick=2,
            inbox_ids=frozenset({inbox_id}),
        )
        assert len(result.responses) == 1
        assert result.responses[0].accept is False

    def test_inbox_filtering_drops_unknown_ids(self) -> None:
        result = map_tool_calls(
            tool_calls=[
                _make_tool_call(
                    "accept_proposal",
                    {"proposal_id": "not-in-inbox"},
                )
            ],
            agent_id="medical",
            tick=2,
            inbox_ids=frozenset({"real-id"}),
        )
        assert result.responses == ()
        # A recognized-but-inbox-filtered call is NOT a model failure: the model
        # emitted a valid accept_proposal; the engine dropped it. No error.
        assert result.error == ""

    def test_all_unrecognized_calls_returns_error(self) -> None:
        # Non-empty tool_calls where every call is garbage (unknown name + unparsable
        # args + invalid proposal kind) must surface an error, not masquerade as a
        # clean no_op idle.
        result = map_tool_calls(
            tool_calls=[
                _make_tool_call("bogus_tool", {"x": 1}),
                {"function": {"name": "set_priority", "arguments": "not json!!"}},
                _make_tool_call("propose_nonsense", {"foo": "bar"}),
            ],
            agent_id="medical",
            tick=4,
            inbox_ids=frozenset(),
        )
        assert result.error != ""
        assert "none recognized" in result.error
        assert result.decisions == ()
        assert result.proposals == ()
        assert result.responses == ()

    def test_no_op_suppresses_unrecognized_error(self) -> None:
        # An explicit no_op alongside garbage is a deliberate idle, not a failure.
        result = map_tool_calls(
            tool_calls=[
                _make_tool_call("bogus_tool", {"x": 1}),
                _make_tool_call("no_op", {"rationale": "nothing to do"}),
            ],
            agent_id="medical",
            tick=4,
            inbox_ids=frozenset(),
        )
        assert result.error == ""
        assert result.decisions == ()

    def test_invalid_json_dropped_individually(self) -> None:
        result = map_tool_calls(
            tool_calls=[
                {"function": {"name": "set_priority", "arguments": "not json!!"}},
                _make_tool_call(
                    "recall",
                    {
                        "mission_id": "m1",
                        "resource": "ambulance",
                        "qty": 1,
                    },
                ),
            ],
            agent_id="medical",
            tick=1,
            inbox_ids=frozenset(),
        )
        assert result.error == ""
        assert len(result.decisions) == 1
        assert result.decisions[0].decision_type == "recall"

    def test_unknown_tool_dropped_individually(self) -> None:
        result = map_tool_calls(
            tool_calls=[
                _make_tool_call("bogus_tool", {"x": 1}),
                _make_tool_call(
                    "broadcast",
                    {"message": "stay calm", "rationale": "reduce panic"},
                ),
            ],
            agent_id="comms",
            tick=1,
            inbox_ids=frozenset(),
        )
        assert result.error == ""
        assert len(result.decisions) == 1
        assert result.decisions[0].decision_type == "broadcast"

    def test_always_returns_agent_response(self) -> None:
        result = map_tool_calls(
            tool_calls=[_make_tool_call("no_op", {})],
            agent_id="test",
            tick=0,
            inbox_ids=frozenset(),
        )
        assert isinstance(result, AgentResponse)

    def test_identity_forced(self) -> None:
        result = map_tool_calls(
            tool_calls=[
                _make_tool_call(
                    "set_priority",
                    {"mission_id": "m1", "priority": 5},
                ),
                _make_tool_call(
                    "propose_resource_request",
                    {
                        "mission_id": "m1",
                        "resource": "ambulance",
                        "qty": 1,
                        "urgency": 3,
                    },
                ),
            ],
            agent_id="fire",
            tick=1,
            inbox_ids=frozenset(),
        )
        for d in result.decisions:
            assert d.agent_id == "fire"
        for p in result.proposals:
            assert p.sender == "fire"


class TestRealSchemaToolDefs:
    """Exercise build_role_tools with the SAME real pydantic schemas and docs that
    prompts.build_llm_agents feeds it — the synthetic-schema unit tests above never
    touch the real model_json_schema() output that ships to the provider."""

    def _real_tools(self) -> list[dict]:
        from aftershock.town.decisions import (
            BroadcastParams,
            RecallParams,
            RepairRoadParams,
            SetPriorityParams,
        )
        from aftershock.town.prompts import DECISION_DOCS, PROPOSAL_DOCS

        return build_role_tools(
            allowed=("set_priority", "recall", "repair_road", "broadcast", "dispatch"),
            decision_docs=DECISION_DOCS,
            proposal_docs=PROPOSAL_DOCS,
            decision_param_schemas={
                "recall": RecallParams.model_json_schema(),
                "set_priority": SetPriorityParams.model_json_schema(),
                "repair_road": RepairRoadParams.model_json_schema(),
                "broadcast": BroadcastParams.model_json_schema(),
            },
            proposal_param_schemas={},
        )

    def test_real_tools_are_well_formed_openai_function_specs(self) -> None:
        tools = self._real_tools()
        assert tools, "expected non-empty tool list from real schemas"
        for t in tools:
            assert t["type"] == "function"
            fn = t["function"]
            assert isinstance(fn["name"], str) and fn["name"]
            assert isinstance(fn["description"], str)
            params = fn["parameters"]
            assert params["type"] == "object"
            assert isinstance(params["properties"], dict)

    def test_real_schema_dispatch_excluded_and_rationale_added(self) -> None:
        tools = self._real_tools()
        by_name = {t["function"]["name"]: t for t in tools}
        # dispatch is allowed but must never be emitted as a tool (auction-only).
        assert "dispatch" not in by_name
        assert "no_op" in by_name
        # rationale is injected onto decision tools without mutating the source schema.
        assert "rationale" in by_name["broadcast"]["function"]["parameters"]["properties"]

    def test_real_decision_schema_not_mutated_by_build(self) -> None:
        # Building tools must not leak the injected "rationale" field back into the
        # shared pydantic schema (deepcopy guard in _make_decision_tool).
        from aftershock.town.decisions import BroadcastParams

        before = BroadcastParams.model_json_schema()
        self._real_tools()
        after = BroadcastParams.model_json_schema()
        assert "rationale" not in before.get("properties", {})
        assert before == after
