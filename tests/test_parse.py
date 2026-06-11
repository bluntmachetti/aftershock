"""Tests for aftershock.llm.parse — offline only."""

from __future__ import annotations

import json

import pytest

from aftershock.llm.parse import (
    LLMParseError,
    parse_llm_output,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_json(**kwargs) -> str:
    return json.dumps(kwargs)


# ---------------------------------------------------------------------------
# Basic happy-path parsing
# ---------------------------------------------------------------------------

def test_empty_object_returns_defaults() -> None:
    result = parse_llm_output("{}")
    assert result.decisions == []
    assert result.proposals == []
    assert result.responses == []


def test_fenced_json_block_parsed() -> None:
    text = '```json\n{"decisions": [{"decision_type": "broadcast", "params": {}}]}\n```'
    result = parse_llm_output(text)
    assert len(result.decisions) == 1
    assert result.decisions[0].decision_type == "broadcast"


def test_fenced_block_without_language_tag() -> None:
    text = '```\n{"proposals": []}\n```'
    result = parse_llm_output(text)
    assert result.proposals == []


def test_leading_prose_and_trailing_junk() -> None:
    text = (
        "Here is my response for this tick.\n"
        '{"decisions": [{"decision_type": "set_priority",'
        ' "params": {"mission_id": "m1", "priority": 8}}]}\n'
        "I hope that is useful!"
    )
    result = parse_llm_output(text)
    assert len(result.decisions) == 1
    assert result.decisions[0].decision_type == "set_priority"
    assert result.decisions[0].params == {"mission_id": "m1", "priority": 8}


def test_trailing_junk_after_closing_brace() -> None:
    text = '{"decisions": []} some extra text after'
    result = parse_llm_output(text)
    assert result.decisions == []


# ---------------------------------------------------------------------------
# Empty arrays default
# ---------------------------------------------------------------------------

def test_missing_decisions_defaults_to_empty_list() -> None:
    result = parse_llm_output('{"proposals": [], "responses": []}')
    assert result.decisions == []


def test_missing_proposals_defaults_to_empty_list() -> None:
    result = parse_llm_output('{"decisions": []}')
    assert result.proposals == []


def test_missing_responses_defaults_to_empty_list() -> None:
    result = parse_llm_output('{"decisions": []}')
    assert result.responses == []


# ---------------------------------------------------------------------------
# Unknown decision_type passes through
# ---------------------------------------------------------------------------

def test_unknown_decision_type_passes_through() -> None:
    """Unknown decision types are NOT rejected by the parser; the registry does that."""
    text = '{"decisions": [{"decision_type": "totally_unknown_action", "params": {}}]}'
    result = parse_llm_output(text)
    assert result.decisions[0].decision_type == "totally_unknown_action"


def test_unknown_proposal_kind_passes_through() -> None:
    text = '{"proposals": [{"kind": "mystery_kind"}]}'
    result = parse_llm_output(text)
    assert result.proposals[0].kind == "mystery_kind"


# ---------------------------------------------------------------------------
# Extra fields ignored (extra="ignore")
# ---------------------------------------------------------------------------

def test_extra_fields_on_llm_output_ignored() -> None:
    text = '{"decisions": [], "unknown_field": "should be ignored"}'
    result = parse_llm_output(text)
    assert result.decisions == []


def test_extra_fields_on_llm_decision_ignored() -> None:
    text = '{"decisions": [{"decision_type": "broadcast", "surprise": 42}]}'
    result = parse_llm_output(text)
    assert result.decisions[0].decision_type == "broadcast"


def test_extra_fields_on_llm_proposal_ignored() -> None:
    text = '{"proposals": [{"kind": "info_share", "extra_key": "val"}]}'
    result = parse_llm_output(text)
    assert result.proposals[0].kind == "info_share"


def test_extra_fields_on_llm_response_ignored() -> None:
    text = '{"responses": [{"proposal_id": "p1", "accept": true, "mood": "happy"}]}'
    result = parse_llm_output(text)
    assert result.responses[0].proposal_id == "p1"


# ---------------------------------------------------------------------------
# Field defaults on sub-models
# ---------------------------------------------------------------------------

def test_llm_decision_params_default_empty_dict() -> None:
    result = parse_llm_output('{"decisions": [{"decision_type": "recall"}]}')
    assert result.decisions[0].params == {}


def test_llm_decision_rationale_default_empty_string() -> None:
    result = parse_llm_output('{"decisions": [{"decision_type": "recall"}]}')
    assert result.decisions[0].rationale == ""


def test_llm_proposal_recipient_default_none() -> None:
    result = parse_llm_output('{"proposals": [{"kind": "resource_request"}]}')
    assert result.proposals[0].recipient is None


def test_llm_proposal_body_default_empty_dict() -> None:
    result = parse_llm_output('{"proposals": [{"kind": "resource_request"}]}')
    assert result.proposals[0].body == {}


def test_llm_response_note_default_empty_string() -> None:
    text = '{"responses": [{"proposal_id": "p99", "accept": false}]}'
    result = parse_llm_output(text)
    assert result.responses[0].note == ""


# ---------------------------------------------------------------------------
# Malformed JSON raises LLMParseError
# ---------------------------------------------------------------------------

def test_malformed_json_raises_llm_parse_error() -> None:
    with pytest.raises(LLMParseError, match="invalid JSON"):
        parse_llm_output('{"decisions": [}')


def test_no_json_object_raises_llm_parse_error() -> None:
    with pytest.raises(LLMParseError, match="no JSON object"):
        parse_llm_output("just some plain text with no braces")


def test_unbalanced_braces_raises_llm_parse_error() -> None:
    with pytest.raises(LLMParseError, match="unbalanced"):
        parse_llm_output('{"decisions": [{"decision_type": "x"')


def test_empty_string_raises_llm_parse_error() -> None:
    with pytest.raises(LLMParseError):
        parse_llm_output("")


# ---------------------------------------------------------------------------
# Schema-invalid input raises LLMParseError
# ---------------------------------------------------------------------------

def test_decisions_not_a_list_raises_llm_parse_error() -> None:
    with pytest.raises(LLMParseError, match="schema validation failed"):
        parse_llm_output('{"decisions": "not-a-list"}')


def test_response_missing_required_field_raises() -> None:
    # LLMResponse requires proposal_id and accept
    with pytest.raises(LLMParseError, match="schema validation failed"):
        parse_llm_output('{"responses": [{"note": "missing required fields"}]}')


def test_response_accept_wrong_type_raises() -> None:
    # A dict is not coercible to bool — Pydantic v2 strict validation fails it
    with pytest.raises(LLMParseError, match="schema validation failed"):
        parse_llm_output('{"responses": [{"proposal_id": "p1", "accept": {"nested": 1}}]}')


def test_decision_missing_decision_type_raises() -> None:
    with pytest.raises(LLMParseError, match="schema validation failed"):
        parse_llm_output('{"decisions": [{"params": {}}]}')


# ---------------------------------------------------------------------------
# Full round-trip: all three lists populated
# ---------------------------------------------------------------------------

def test_full_output_round_trip() -> None:
    payload = {
        "decisions": [
            {
                "decision_type": "set_priority",
                "params": {"mission_id": "m3", "priority": 9},
                "rationale": "high urgency",
            },
        ],
        "proposals": [
            {
                "kind": "resource_request",
                "recipient": None,
                "body": {"mission_id": "m3", "resource": "ambulance", "qty": 2, "urgency": 8},
            },
        ],
        "responses": [
            {"proposal_id": "rescue-p0", "accept": True, "note": "agreed"},
        ],
    }
    result = parse_llm_output(json.dumps(payload))

    assert len(result.decisions) == 1
    assert result.decisions[0].decision_type == "set_priority"
    assert result.decisions[0].params["priority"] == 9
    assert result.decisions[0].rationale == "high urgency"

    assert len(result.proposals) == 1
    assert result.proposals[0].kind == "resource_request"
    assert result.proposals[0].body["qty"] == 2

    assert len(result.responses) == 1
    assert result.responses[0].proposal_id == "rescue-p0"
    assert result.responses[0].accept is True


# ---------------------------------------------------------------------------
# String-aware brace extraction: braces inside string values must not confuse extractor
# ---------------------------------------------------------------------------

def test_closing_brace_in_string_value_parsed() -> None:
    """A literal '}' inside a string value must not truncate extraction prematurely."""
    payload = json.dumps({
        "decisions": [
            {
                "decision_type": "broadcast",
                "params": {"message": "use } to close"},
                "rationale": "",
            }
        ],
        "proposals": [],
        "responses": [],
    })
    result = parse_llm_output(payload)
    assert len(result.decisions) == 1
    assert result.decisions[0].params["message"] == "use } to close"


def test_opening_brace_in_string_value_parsed() -> None:
    """A literal '{' inside a string value must not increase depth erroneously."""
    payload = json.dumps({
        "decisions": [
            {
                "decision_type": "broadcast",
                "params": {"message": "format: {value}"},
                "rationale": "",
            }
        ],
        "proposals": [],
        "responses": [],
    })
    result = parse_llm_output(payload)
    assert result.decisions[0].params["message"] == "format: {value}"


def test_escaped_quote_in_string_value_parsed() -> None:
    """Escaped quotes inside a string value must not toggle in_string prematurely."""
    payload = json.dumps({
        "decisions": [
            {"decision_type": "broadcast", "params": {"message": 'say "hello" now'}}
        ]
    })
    result = parse_llm_output(payload)
    assert result.decisions[0].params["message"] == 'say "hello" now'


def test_unbalanced_close_brace_in_string_not_early_termination() -> None:
    """The first balanced block is correctly extracted even with } in a string key."""
    payload = json.dumps({"a": "}", "decisions": []})
    result = parse_llm_output(payload)
    assert result.decisions == []


def test_braces_in_rationale_string() -> None:
    """Braces in rationale text do not break extraction."""
    payload = json.dumps({
        "decisions": [
            {
                "decision_type": "set_priority",
                "params": {"mission_id": "m1", "priority": 8},
                "rationale": "deadline {in 2 ticks} => max priority",
            }
        ]
    })
    result = parse_llm_output(payload)
    assert "deadline {in 2 ticks} => max priority" in result.decisions[0].rationale


# ---------------------------------------------------------------------------
# LLMParseError carries a short reason
# ---------------------------------------------------------------------------

def test_llm_parse_error_has_reason() -> None:
    try:
        parse_llm_output("no json here at all")
    except LLMParseError as exc:
        assert str(exc)  # non-empty reason
    else:
        pytest.fail("expected LLMParseError")
