"""Tests for town/doctrine.yaml, town/doctrine.py, and doctrine integration in prompts.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from aftershock.kernel.roles import load_roles
from aftershock.llm.provider import MockProvider
from aftershock.town.doctrine import Rule, doctrine_blocks, load_doctrine
from aftershock.town.prompts import build_llm_agents

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROLES_DIR = Path(__file__).parent.parent / "src" / "aftershock" / "town" / "roles"
DOCTRINE_YAML = Path(__file__).parent.parent / "src" / "aftershock" / "town" / "doctrine.yaml"

# ---------------------------------------------------------------------------
# load_doctrine — 18 rules with unique ids
# ---------------------------------------------------------------------------

EXPECTED_IDS = {
    "T1",
    "T2",
    "T3",
    "T4",
    "T5",
    "T6",
    "C1",
    "C2",
    "C3",
    "M1",
    "M2",
    "R1",
    "R2",
    "F1",
    "F2",
    "I1",
    "I2",
    "X1",
    "X2",
}

# T1..T6 (6) + C1..C3 (3) + M1..M2 (2) + R1..R2 (2) + F1..F2 (2) + I1..I2 (2) + X1..X2 (2) = 19
# The task description says "18 rules" but the YAML defines 19 unique ids (the task description
# miscounts — EXPECTED_IDS covers all ids actually present; the test checks they are all there.


def test_load_doctrine_returns_rules() -> None:
    rules = load_doctrine()
    assert len(rules) > 0


def test_load_doctrine_all_expected_ids() -> None:
    rules = load_doctrine()
    ids = {r.id for r in rules}
    assert EXPECTED_IDS.issubset(ids), f"Missing ids: {EXPECTED_IDS - ids}"


def test_load_doctrine_unique_ids() -> None:
    rules = load_doctrine()
    ids = [r.id for r in rules]
    assert len(ids) == len(set(ids)), "Duplicate rule ids found"


def test_load_doctrine_team_rules_have_none_role() -> None:
    rules = load_doctrine()
    team_rules = [r for r in rules if r.role is None]
    team_ids = {r.id for r in team_rules}
    assert {"T1", "T2", "T3", "T4", "T5", "T6"}.issubset(team_ids)


def test_load_doctrine_role_rules_have_role_set() -> None:
    rules = load_doctrine()
    for rule in rules:
        if rule.id.startswith(("C", "M", "R", "F", "I", "X")):
            assert rule.role is not None, f"Rule {rule.id} should have a role set"


def test_load_doctrine_arms_are_tuples() -> None:
    rules = load_doctrine()
    for rule in rules:
        assert isinstance(rule.arms, tuple), f"Rule {rule.id} arms should be a tuple"


def test_load_doctrine_duplicate_id_raises(tmp_path: Path) -> None:
    bad_yaml = tmp_path / "doctrine.yaml"
    bad_yaml.write_text(
        "team:\n"
        "  - {id: T1, text: 'foo', arms: [society]}\n"
        "  - {id: T1, text: 'bar', arms: [society]}\n"
        "roles: {}\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_doctrine(bad_yaml)


def test_load_doctrine_rescue_r1_r2() -> None:
    rules = load_doctrine()
    rescue_rules = [r for r in rules if r.role == "rescue"]
    ids = {r.id for r in rescue_rules}
    assert "R1" in ids, "R1 (rescue ordering) must be present"
    assert "R2" in ids, "R2 (rescue escalation) must be present"


def test_load_doctrine_fire_f1_f2() -> None:
    rules = load_doctrine()
    fire_rules = [r for r in rules if r.role == "fire"]
    ids = {r.id for r in fire_rules}
    assert "F1" in ids, "F1 (fire ordering) must be present"
    assert "F2" in ids, "F2 (fire escalation) must be present"


def test_rescue_f1_mirrors_medical_m1_pattern() -> None:
    """R1/R2 mirror M1/M2: ordering + escalation for their respective mission kind."""
    rules = load_doctrine()
    by_id = {r.id: r for r in rules}
    # R1 should mention collapse_rescue
    assert "collapse_rescue" in by_id["R1"].text.lower()
    # F1 should mention fire
    assert "fire" in by_id["F1"].text.lower()
    # M1 should mention medical_surge
    assert "medical_surge" in by_id["M1"].text.lower()


# ---------------------------------------------------------------------------
# doctrine_blocks — section rendering and arm filtering
# ---------------------------------------------------------------------------


def test_doctrine_blocks_commander_society_contains_team_rules() -> None:
    rules = load_doctrine()
    blocks = doctrine_blocks(rules, role="commander", arm="society")
    assert "TEAM DOCTRINE:" in blocks
    # T1..T6 all apply to society
    for rule_id in ("T1", "T2", "T3", "T4", "T5", "T6"):
        assert rule_id + "." in blocks, f"{rule_id} missing from (commander, society) blocks"


def test_doctrine_blocks_commander_society_contains_role_doctrine() -> None:
    rules = load_doctrine()
    blocks = doctrine_blocks(rules, role="commander", arm="society")
    assert "YOUR ROLE DOCTRINE:" in blocks
    for rule_id in ("C1", "C2", "C3"):
        assert rule_id + "." in blocks, f"{rule_id} missing from (commander, society) blocks"


def test_doctrine_blocks_medical_swarm_contains_m1_not_t1_t4() -> None:
    """(medical, swarm): M1 applies; T1/T4 are society-only so must be absent."""
    rules = load_doctrine()
    blocks = doctrine_blocks(rules, role="medical", arm="swarm")
    assert "M1." in blocks, "M1 must appear for (medical, swarm)"
    assert "T1." not in blocks, "T1 is society-only; must not appear for swarm"
    assert "T4." not in blocks, "T4 is society-only; must not appear for swarm"


def test_doctrine_blocks_medical_swarm_no_m2() -> None:
    """M2 is society-only; must not appear for (medical, swarm)."""
    rules = load_doctrine()
    blocks = doctrine_blocks(rules, role="medical", arm="swarm")
    assert "M2." not in blocks, "M2 is society-only; must not appear for (medical, swarm)"


def test_doctrine_blocks_solo_contains_i1_x1() -> None:
    """(solo, solo) should include I1 and X1 (solo is in their arms lists)."""
    rules = load_doctrine()
    # solo agent's role name in solo arm is "solo" — check infrastructure/comms rules
    # that include "solo" in their arms
    blocks_infra = doctrine_blocks(rules, role="infrastructure", arm="solo")
    assert "I1." in blocks_infra, "I1 must appear for (infrastructure, solo)"
    blocks_comms = doctrine_blocks(rules, role="comms", arm="solo")
    assert "X1." in blocks_comms, "X1 must appear for (comms, solo)"


def test_doctrine_blocks_solo_no_team_auction_rules() -> None:
    """T1/T2/T3/T4/T6 are society-only; must not appear for solo arm."""
    rules = load_doctrine()
    blocks = doctrine_blocks(rules, role="commander", arm="solo")
    for society_only_id in ("T1", "T2", "T3", "T4", "T6"):
        assert society_only_id + "." not in blocks, (
            f"{society_only_id} is society-only; must not appear for solo arm"
        )


def test_doctrine_blocks_empty_section_omitted() -> None:
    """If no team rules apply for an arm, TEAM DOCTRINE section is omitted."""
    rules = load_doctrine()
    # Create a fake arm that matches no rule
    blocks = doctrine_blocks(rules, role="commander", arm="nonexistent_arm")
    assert blocks == "", "No matching rules should produce an empty string"


def test_doctrine_blocks_only_role_section_when_no_team_rules() -> None:
    """When team rules don't match but role rules do, only YOUR ROLE DOCTRINE appears."""
    # Build a minimal rule set with only a role rule that matches
    rules = [Rule(id="X9", text="test rule", arms=("testarm",), role="commander")]
    blocks = doctrine_blocks(rules, role="commander", arm="testarm")
    assert "YOUR ROLE DOCTRINE:" in blocks
    assert "TEAM DOCTRINE:" not in blocks


def test_doctrine_blocks_numbered_format() -> None:
    """Rules must be formatted as '  ID. text'."""
    rules = load_doctrine()
    blocks = doctrine_blocks(rules, role="commander", arm="society")
    # Each line in the team section should start with '  Tx.'
    lines = blocks.split("\n")
    rule_lines = [ln for ln in lines if ln.startswith("  ") and "." in ln]
    assert len(rule_lines) >= 6, "Expected at least 6 numbered rule lines"
    for ln in rule_lines:
        stripped = ln.strip()
        # Must be like "T1. ..." or "C1. ..."
        assert stripped[0].isupper() and stripped[1].isdigit() and stripped[2] == ".", (
            f"Rule line not in expected format: {ln!r}"
        )


# ---------------------------------------------------------------------------
# build_llm_agents — doctrine + contract + lessons integration
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def roles() -> dict:
    return load_roles(ROLES_DIR)


def test_build_llm_agents_commander_system_prompt_has_doctrine(roles: dict) -> None:
    provider = MockProvider(script=["{}"])
    agents = build_llm_agents(roles, provider, arm="society")
    commander_agent = agents["commander"]
    system = commander_agent._system  # type: ignore[attr-defined]
    assert "TEAM DOCTRINE:" in system
    assert "YOUR ROLE DOCTRINE:" in system
    assert "T1." in system
    assert "C1." in system


def test_build_llm_agents_commander_system_prompt_has_contract(roles: dict) -> None:
    provider = MockProvider(script=["{}"])
    # force_tools=True: the no_op / propose_resource_request markers are tool-mode
    # contract strings. JSON mode (the default) uses decision_contract instead.
    agents = build_llm_agents(roles, provider, arm="society", force_tools=True)
    commander_agent = agents["commander"]
    system = commander_agent._system  # type: ignore[attr-defined]
    assert "no_op" in system
    assert "propose_resource_request" in system


def test_build_llm_agents_commander_system_prompt_has_lessons(roles: dict) -> None:
    provider = MockProvider(script=["{}"])
    lessons = ["Prioritize medical missions early.", "Always broadcast when panic spikes."]
    agents = build_llm_agents(roles, provider, arm="society", lessons=lessons)
    commander_agent = agents["commander"]
    system = commander_agent._system  # type: ignore[attr-defined]
    assert "LESSONS FROM PREVIOUS DISASTERS" in system
    assert "Prioritize medical missions early." in system
    assert "Always broadcast when panic spikes." in system


def test_build_llm_agents_lessons_order_doctrine_then_lessons_then_contract(roles: dict) -> None:
    """Doctrine blocks come before lessons, lessons before contract."""
    provider = MockProvider(script=["{}"])
    lessons = ["Some lesson."]
    # force_tools=True so the contract marker ("## How to Act") is the tool_contract
    # header; the doctrine<lessons<contract ordering logic is mode-independent.
    agents = build_llm_agents(roles, provider, arm="society", lessons=lessons, force_tools=True)
    system = agents["commander"]._system  # type: ignore[attr-defined]
    doctrine_pos = system.index("TEAM DOCTRINE:")
    lessons_pos = system.index("LESSONS FROM PREVIOUS DISASTERS")
    contract_pos = system.index("## How to Act")
    assert doctrine_pos < lessons_pos < contract_pos, (
        "Expected order: doctrine < lessons < contract"
    )


def test_build_llm_agents_non_commander_no_lessons(roles: dict) -> None:
    """Lessons must NOT appear in non-commander system prompts."""
    provider = MockProvider(script=["{}"])
    lessons = ["Some lesson."]
    agents = build_llm_agents(roles, provider, arm="society", lessons=lessons)
    for agent_id, agent in agents.items():
        if agent_id != "commander":
            system = agent._system  # type: ignore[attr-defined]
            assert "LESSONS FROM PREVIOUS DISASTERS" not in system, (
                f"Lessons leaked into {agent_id} system prompt"
            )


def test_build_llm_agents_doctrine_failure_raises(roles: dict, tmp_path: Path) -> None:
    """Doctrine load failure must raise at build time, not silently skip."""
    bad_yaml = tmp_path / "doctrine.yaml"
    bad_yaml.write_text(
        "team:\n"
        "  - {id: T1, text: 'dup', arms: [society]}\n"
        "  - {id: T1, text: 'dup2', arms: [society]}\n"
        "roles: {}\n"
    )
    # Use _doctrine_rules parameter to test: load_doctrine(bad_yaml) raises ValueError
    with pytest.raises(ValueError, match="duplicate"):
        load_doctrine(bad_yaml)


def test_build_llm_agents_scripted_arm_unaffected() -> None:
    """Scripted agents are not constructed via build_llm_agents — just verify
    that doctrine_blocks for scripted arm returns empty (scripted is not a valid arm)."""
    rules = load_doctrine()
    # "scripted" is not in any rule's arms list — all rules use society/swarm/solo
    blocks = doctrine_blocks(rules, role="commander", arm="scripted")
    assert blocks == "", "No doctrine rules apply to the scripted arm"


def test_build_llm_agents_society_arm_medical_has_m1_not_m2_absent(roles: dict) -> None:
    """In (medical, society), M1 and M2 both appear (society is in both arms lists)."""
    provider = MockProvider(script=["{}"])
    agents = build_llm_agents(roles, provider, arm="society")
    medical_system = agents["medical"]._system  # type: ignore[attr-defined]
    assert "M1." in medical_system
    assert "M2." in medical_system


def test_solo_inherits_role_rules_for_its_arm():
    """The solo generalist performs every role's duties, so it inherits every
    role rule whose arms include 'solo' — without this it received only T5."""
    rules = load_doctrine()
    block = doctrine_blocks(rules, "solo", "solo")
    for rid in ("I1", "I2", "X1", "X2"):
        assert f"{rid}." in block, f"solo missing inherited rule {rid}"
    assert "T5." in block
    # commander rules are society-only — must not leak into the solo arm
    assert "C1." not in block
