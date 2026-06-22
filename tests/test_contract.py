"""Tests for llm/contract.py: decision_contract output contract."""

from __future__ import annotations

from aftershock.llm.contract import decision_contract

# ---------------------------------------------------------------------------
# Sample docs matching town/prompts.py style
# ---------------------------------------------------------------------------

DECISION_DOCS: dict[str, str] = {
    "set_priority": (
        "set_priority {mission_id, priority 0-10}: rank a mission for the resource auction"
    ),
    "recall": "recall {mission_id, resource, qty}: return resources from a mission to the pool",
    "repair_road": "repair_road {district_id}: dispatch a repair crew to unblock a road",
    "broadcast": "broadcast {message}: send a public message; reduces panic",
    "dispatch": "dispatch {mission_id, resource, qty}: send resources to a mission",
}

PROPOSAL_DOCS: dict[str, str] = {
    "resource_request": (
        "resource_request {mission_id, resource, qty, urgency 1-10}:"
        " bid for scarce resources at the auction"
    ),
    "task_handoff": (
        "task_handoff {mission_id, note}: transfer responsibility for a mission to another agent"
    ),
    "escalation": (
        "escalation {mission_id, note}: flag a situation requiring command intervention"
    ),
    "info_share": "info_share {message}: broadcast knowledge to all agents",
}

ALLOWED_ALL = ("set_priority", "recall", "repair_road", "broadcast", "dispatch")


# ---------------------------------------------------------------------------
# The word "JSON" must be present (DashScope json_mode requirement)
# ---------------------------------------------------------------------------


def test_contains_word_json():
    """The contract must contain the word 'JSON'."""
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert "JSON" in result


# ---------------------------------------------------------------------------
# Schema field names matching parse.py
# ---------------------------------------------------------------------------


def test_schema_field_decisions():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert '"decisions"' in result


def test_schema_field_proposals():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert '"proposals"' in result


def test_schema_field_responses():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert '"responses"' in result


def test_schema_field_decision_type():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert '"decision_type"' in result


def test_schema_field_params():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert '"params"' in result


def test_schema_field_rationale():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert '"rationale"' in result


def test_schema_field_kind():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert '"kind"' in result


def test_schema_field_recipient():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert '"recipient"' in result


def test_schema_field_body():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert '"body"' in result


def test_schema_field_proposal_id():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert '"proposal_id"' in result


def test_schema_field_accept():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert '"accept"' in result


def test_schema_field_note():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert '"note"' in result


# ---------------------------------------------------------------------------
# Decision type usage lines
# ---------------------------------------------------------------------------


def test_decision_set_priority_usage_line():
    result = decision_contract(("set_priority",), DECISION_DOCS, PROPOSAL_DOCS)
    assert DECISION_DOCS["set_priority"] in result


def test_decision_recall_usage_line():
    result = decision_contract(("recall",), DECISION_DOCS, PROPOSAL_DOCS)
    assert DECISION_DOCS["recall"] in result


def test_decision_repair_road_usage_line():
    result = decision_contract(("repair_road",), DECISION_DOCS, PROPOSAL_DOCS)
    assert DECISION_DOCS["repair_road"] in result


def test_decision_broadcast_usage_line():
    result = decision_contract(("broadcast",), DECISION_DOCS, PROPOSAL_DOCS)
    assert DECISION_DOCS["broadcast"] in result


def test_decision_dispatch_usage_line():
    result = decision_contract(("dispatch",), DECISION_DOCS, PROPOSAL_DOCS)
    assert DECISION_DOCS["dispatch"] in result


def test_only_allowed_decisions_included():
    """Decision types not in allowed must not appear."""
    result = decision_contract(("broadcast",), DECISION_DOCS, PROPOSAL_DOCS)
    # recall is NOT in allowed — its doc line should not appear
    assert DECISION_DOCS["recall"] not in result
    assert DECISION_DOCS["broadcast"] in result


def test_all_allowed_decisions_included():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    for dtype in ALLOWED_ALL:
        assert DECISION_DOCS[dtype] in result


# ---------------------------------------------------------------------------
# Proposal kind lines
# ---------------------------------------------------------------------------


def test_proposal_resource_request_present():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert PROPOSAL_DOCS["resource_request"] in result


def test_proposal_task_handoff_present():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert PROPOSAL_DOCS["task_handoff"] in result


def test_proposal_escalation_present():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert PROPOSAL_DOCS["escalation"] in result


def test_proposal_info_share_present():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert PROPOSAL_DOCS["info_share"] in result


def test_all_proposal_kinds_present():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    for kind, doc in PROPOSAL_DOCS.items():
        assert doc in result, f"proposal kind {kind!r} doc missing from contract"


# ---------------------------------------------------------------------------
# Hard rules
# ---------------------------------------------------------------------------


def test_hard_rule_json_object_only():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert "JSON object" in result


def test_hard_rule_exact_ids():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    # Must mention using exact ids
    assert "exact ids" in result or "exact" in result


def test_hard_rule_answer_inbox_proposals():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert "responses" in result
    assert "YOUR INBOX" in result or "INBOX" in result


def test_hard_rule_resources_via_proposal_not_dispatch():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert "resource_request" in result


def test_hard_rule_rationale_under_25_words():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert "25 words" in result or "25" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_allowed_decisions():
    """No decision section rendered when allowed is empty."""
    result = decision_contract((), DECISION_DOCS, PROPOSAL_DOCS)
    # JSON must still be present
    assert "JSON" in result
    # Schema fields still present
    assert '"decisions"' in result


def test_empty_proposal_docs():
    """No proposal section rendered when proposal_docs is empty."""
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, {})
    assert "JSON" in result
    assert '"decisions"' in result


def test_contract_is_string():
    result = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    assert isinstance(result, str)


def test_contract_non_empty():
    result = decision_contract((), {}, {})
    assert len(result) > 0


# ---------------------------------------------------------------------------
# trim knob (FIELD-NOTES §21) — the contract on/off ablation toggle.
# trim=True (default) renders the §21 cost-trimmed contract; trim=False renders
# the pre-§21 verbose contract (the untrimmed ablation control).
# ---------------------------------------------------------------------------


def test_trim_default_is_true():
    """The default rendering is byte-identical to trim=True (no behaviour drift)."""
    default = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS)
    explicit = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS, trim=True)
    assert default == explicit


def test_trim_false_changes_rendered_contract():
    """trim=False must render a different contract than trim=True (full schema)."""
    trimmed = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS, trim=True)
    untrimmed = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS, trim=False)
    assert trimmed != untrimmed


def test_trim_false_changes_rendered_contract_decisions_only():
    """trim=False also differs for the decisions-only (no-proposals) schema."""
    trimmed = decision_contract(ALLOWED_ALL, DECISION_DOCS, {}, trim=True)
    untrimmed = decision_contract(ALLOWED_ALL, DECISION_DOCS, {}, trim=False)
    assert trimmed != untrimmed


def test_trim_true_uses_compact_single_line_skeleton():
    """The trimmed schema is a single-line JSON object (the §21 compaction)."""
    trimmed = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS, trim=True)
    # Compact form keeps the field vocabulary without the multi-line indentation.
    assert '{"decisions":[{"decision_type":"<type>"' in trimmed
    # The verbose multi-line skeleton marker must be absent.
    assert '  "decisions": [' not in trimmed


def test_trim_false_uses_verbose_multiline_skeleton():
    """The untrimmed schema is the pre-§21 multi-line indented JSON skeleton."""
    untrimmed = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS, trim=False)
    assert '  "decisions": [' in untrimmed
    assert '      "decision_type": "<type>",' in untrimmed
    # The compact single-line form must be absent.
    assert '{"decisions":[{"decision_type":"<type>"' not in untrimmed


def test_trim_false_restores_deduped_hard_rules():
    """The pre-§21 Hard Rules carried two lines the §21 dedup removed."""
    untrimmed = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS, trim=False)
    trimmed = decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS, trim=True)
    # Both lines exist untrimmed and are gone from the trimmed form.
    assert "- Output ONLY a JSON object; no markdown fences, no explanation." in untrimmed
    assert "- Keep each rationale under 25 words." in untrimmed
    assert "- Output ONLY a JSON object; no markdown fences, no explanation." not in trimmed
    assert "- Keep each rationale under 25 words." not in trimmed


def test_trim_both_forms_contain_json_word():
    """Both forms keep the word 'JSON' (DashScope json_mode requirement)."""
    assert "JSON" in decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS, trim=True)
    assert "JSON" in decision_contract(ALLOWED_ALL, DECISION_DOCS, PROPOSAL_DOCS, trim=False)
