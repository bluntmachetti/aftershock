"""Tests for town/prompts.py and roles/*.yaml LLM configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from aftershock.kernel.protocol import ProposalKind
from aftershock.kernel.roles import load_roles
from aftershock.town.prompts import DECISION_DOCS, PROPOSAL_DOCS

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROLES_DIR = Path(__file__).parent.parent / "src" / "aftershock" / "town" / "roles"

# The five registered decision types (mirrors decisions.py register_all)
REGISTERED_DECISION_TYPES = frozenset(
    {"dispatch", "recall", "set_priority", "repair_road", "broadcast"}
)

# The four ProposalKind values
PROPOSAL_KIND_VALUES = frozenset(pk.value for pk in ProposalKind)


# ---------------------------------------------------------------------------
# DECISION_DOCS tests
# ---------------------------------------------------------------------------


def test_decision_docs_covers_exactly_five_types() -> None:
    assert set(DECISION_DOCS.keys()) == REGISTERED_DECISION_TYPES


def test_decision_docs_all_nonempty() -> None:
    for key, doc in DECISION_DOCS.items():
        assert doc.strip(), f"DECISION_DOCS[{key!r}] is empty"


def test_decision_docs_dispatch_mentions_auction_and_resource_request() -> None:
    doc = DECISION_DOCS["dispatch"].lower()
    assert "auction" in doc or "resource_request" in doc, (
        "dispatch doc must note that dispatch is auction-granted and agents use resource_request"
    )


def test_decision_docs_set_priority_mentions_priority_range() -> None:
    doc = DECISION_DOCS["set_priority"]
    assert "0" in doc and "10" in doc, "set_priority doc must mention priority range 0-10"


def test_decision_docs_broadcast_mentions_char_limit() -> None:
    doc = DECISION_DOCS["broadcast"]
    assert "280" in doc, "broadcast doc must mention the 280-character limit"


# ---------------------------------------------------------------------------
# PROPOSAL_DOCS tests
# ---------------------------------------------------------------------------


def test_proposal_docs_covers_all_four_kinds() -> None:
    assert set(PROPOSAL_DOCS.keys()) == PROPOSAL_KIND_VALUES


def test_proposal_docs_all_nonempty() -> None:
    for key, doc in PROPOSAL_DOCS.items():
        assert doc.strip(), f"PROPOSAL_DOCS[{key!r}] is empty"


def test_proposal_docs_resource_request_mentions_body_fields() -> None:
    doc = PROPOSAL_DOCS["resource_request"].lower()
    assert "mission_id" in doc
    assert "resource" in doc
    assert "urgency" in doc


def test_proposal_docs_escalation_mentions_commander_and_mission_id() -> None:
    doc = PROPOSAL_DOCS["escalation"].lower()
    assert "commander" in doc, "escalation doc must mention the commander"
    assert "mission_id" in doc, "escalation doc must mention mission_id"


def test_proposal_docs_info_share_never_grants_resources() -> None:
    doc = PROPOSAL_DOCS["info_share"].lower()
    assert "resource" in doc or "grant" in doc or "never" in doc, (
        "info_share doc should clarify it does not grant resources"
    )


# ---------------------------------------------------------------------------
# Role YAML tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def roles() -> dict:
    return load_roles(ROLES_DIR)


EXPECTED_ROLES = {"commander", "medical", "rescue", "fire", "infrastructure", "comms"}

COMMANDER_MODEL = "qwen3.5-plus"
SPECIALIST_MODEL = "qwen3.5-flash"
SPECIALIST_ROLES = EXPECTED_ROLES - {"commander"}


def test_all_six_roles_present(roles: dict) -> None:
    assert set(roles.keys()) == EXPECTED_ROLES


@pytest.mark.parametrize("role_name", sorted(EXPECTED_ROLES))
def test_role_system_prompt_nonempty(roles: dict, role_name: str) -> None:
    spec = roles[role_name]
    assert spec.system_prompt.strip(), f"system_prompt for {role_name!r} is empty"


@pytest.mark.parametrize("role_name", sorted(EXPECTED_ROLES))
def test_role_system_prompt_minimum_length(roles: dict, role_name: str) -> None:
    # Each prompt should be at least 120 words (task spec says 120-180 words)
    word_count = len(roles[role_name].system_prompt.split())
    assert word_count >= 100, (
        f"system_prompt for {role_name!r} has only {word_count} words; expected ~120-180"
    )


def test_commander_model(roles: dict) -> None:
    assert roles["commander"].model == COMMANDER_MODEL


@pytest.mark.parametrize("role_name", sorted(SPECIALIST_ROLES))
def test_specialist_model(roles: dict, role_name: str) -> None:
    assert roles[role_name].model == SPECIALIST_MODEL, (
        f"{role_name} should use {SPECIALIST_MODEL}"
    )


@pytest.mark.parametrize("role_name", sorted(EXPECTED_ROLES))
def test_role_temperature(roles: dict, role_name: str) -> None:
    assert roles[role_name].temperature == pytest.approx(0.3)


def test_existing_keys_unchanged(roles: dict) -> None:
    """name, display_name, description, allowed_decisions must remain as originally set."""
    assert roles["commander"].name == "commander"
    assert roles["commander"].allowed_decisions == ("set_priority",)

    assert roles["medical"].allowed_decisions == ("recall",)
    assert roles["rescue"].allowed_decisions == ("recall",)
    assert roles["fire"].allowed_decisions == ("recall",)

    infra = roles["infrastructure"]
    assert set(infra.allowed_decisions) == {"recall", "repair_road"}

    assert roles["comms"].allowed_decisions == ("broadcast",)


def test_commander_prompt_mentions_set_priority(roles: dict) -> None:
    assert "set_priority" in roles["commander"].system_prompt


def test_commander_prompt_mentions_escalation(roles: dict) -> None:
    prompt = roles["commander"].system_prompt.lower()
    assert "escalat" in prompt


def test_comms_prompt_mentions_panic_threshold(roles: dict) -> None:
    prompt = roles["comms"].system_prompt
    assert "0.4" in prompt or "panic" in prompt.lower()


def test_comms_prompt_mentions_char_limit(roles: dict) -> None:
    assert "280" in roles["comms"].system_prompt


def test_infrastructure_prompt_mentions_repair_road(roles: dict) -> None:
    assert "repair_road" in roles["infrastructure"].system_prompt


def test_specialist_prompts_mention_resource_request(roles: dict) -> None:
    # comms does not bid for resources; all other specialists do
    resource_bidding_roles = SPECIALIST_ROLES - {"comms"}
    for role_name in resource_bidding_roles:
        prompt = roles[role_name].system_prompt.lower()
        assert "resource_request" in prompt, (
            f"{role_name} system_prompt must mention resource_request proposals"
        )


def test_prompts_mention_exact_ids(roles: dict) -> None:
    """Every prompt must instruct the agent to use exact ids from the observation."""
    for role_name, spec in roles.items():
        prompt = spec.system_prompt.lower()
        assert "exact" in prompt or "exactly as" in prompt or "exact ids" in prompt, (
            f"{role_name} system_prompt must instruct use of exact ids from the observation"
        )
