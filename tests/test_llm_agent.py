"""Tests for LLMAgent: unit tests and a full e2e Engine run with MockProvider."""

from __future__ import annotations

import contextlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any

import pytest

from aftershock.kernel.agents import Agent
from aftershock.kernel.protocol import (
    Observation,
    Proposal,
    ProposalKind,
    TokenUsage,
)
from aftershock.kernel.roles import RoleSpec
from aftershock.llm.agent import LLMAgent
from aftershock.llm.provider import MockProvider, ProviderError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROLES_DIR = Path(__file__).parent.parent / "src" / "aftershock" / "town" / "roles"


def _make_role(
    name: str = "medical",
    allowed_decisions: tuple[str, ...] = ("recall",),
    model: str = "qwen3.5-flash",
    temperature: float = 0.3,
    system_prompt: str = "You are a test agent.",
) -> RoleSpec:
    return RoleSpec(
        name=name,
        display_name=name,
        description="",
        allowed_decisions=allowed_decisions,
        system_prompt=system_prompt,
        model=model,
        temperature=temperature,
    )


def _make_obs(
    tick: int = 1,
    agent_id: str = "medical",
    role: str = "medical",
    inbox: tuple[Proposal, ...] = (),
) -> Observation:
    return Observation(
        tick=tick,
        agent_id=agent_id,
        role=role,
        view={
            "tick": tick,
            "panic": 0.1,
            "open_missions": [],
            "pool_availability": {"ambulance": 2, "supply_truck": 1},
            "blocked_districts": [],
            "totals": {
                "missions_open": 0,
                "missions_resolved": 0,
                "missions_failed": 0,
                "lives_saved": 0,
                "lives_lost": 0,
            },
        },
        inbox=inbox,
        allowed_decisions=("recall",),
    )


def _valid_json_response(**extra: Any) -> str:
    payload: dict[str, Any] = {
        "decisions": [],
        "proposals": [],
        "responses": [],
    }
    payload.update(extra)
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Unit: valid mock JSON -> correctly mapped AgentResponse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_response_decisions_mapped() -> None:
    """LLMAgent maps decisions with correct ids and forced agent_id."""
    response_json = json.dumps({
        "decisions": [
            {
                "decision_type": "recall",
                "params": {"mission_id": "m1", "resource": "ambulance", "qty": 1},
                "rationale": "no longer needed",
            },
        ],
        "proposals": [],
        "responses": [],
    })
    provider = MockProvider(script=[response_json])
    role = _make_role()
    agent = LLMAgent("medical", role, provider, "")
    obs = _make_obs(tick=3)

    result = await agent.act(obs)

    assert result.error == ""
    assert len(result.decisions) == 1
    dec = result.decisions[0]
    assert dec.decision_id == "medical-t3-0"
    assert dec.agent_id == "medical"
    assert dec.decision_type == "recall"
    assert dec.params == {"mission_id": "m1", "resource": "ambulance", "qty": 1}
    assert dec.rationale == "no longer needed"


@pytest.mark.asyncio
async def test_valid_response_proposals_mapped() -> None:
    """LLMAgent maps proposals with correct ids and forced sender."""
    response_json = json.dumps({
        "decisions": [],
        "proposals": [
            {
                "kind": "resource_request",
                "recipient": None,
                "body": {"mission_id": "m2", "resource": "ambulance", "qty": 1, "urgency": 7},
            },
        ],
        "responses": [],
    })
    provider = MockProvider(script=[response_json])
    role = _make_role()
    agent = LLMAgent("medical", role, provider, "")
    obs = _make_obs(tick=5)

    result = await agent.act(obs)

    assert result.error == ""
    assert len(result.proposals) == 1
    prop = result.proposals[0]
    assert prop.proposal_id == "medical-t5-p0"
    assert prop.sender == "medical"
    assert prop.kind == ProposalKind.RESOURCE_REQUEST
    assert prop.body["mission_id"] == "m2"


@pytest.mark.asyncio
async def test_inbox_filtering_drops_unknown_proposal_ids() -> None:
    """Responses whose proposal_id is not in inbox are dropped."""
    inbox_prop = Proposal(
        proposal_id="commander-t1-p0",
        sender="commander",
        recipient="medical",
        kind=ProposalKind.ESCALATION,
        body={"mission_id": "m1", "why": "urgent"},
    )
    response_json = json.dumps({
        "decisions": [],
        "proposals": [],
        "responses": [
            {"proposal_id": "commander-t1-p0", "accept": True, "note": "ok"},
            {"proposal_id": "invented-id-99", "accept": False, "note": "bad"},
        ],
    })
    provider = MockProvider(script=[response_json])
    role = _make_role()
    agent = LLMAgent("medical", role, provider, "")
    obs = _make_obs(tick=2, inbox=(inbox_prop,))

    result = await agent.act(obs)

    assert result.error == ""
    assert len(result.responses) == 1
    assert result.responses[0].proposal_id == "commander-t1-p0"
    assert result.responses[0].responder == "medical"
    assert result.responses[0].accept is True


@pytest.mark.asyncio
async def test_identity_forced_on_decisions() -> None:
    """agent_id is forced on decisions regardless of what LLM emits."""
    response_json = json.dumps({
        "decisions": [
            {
                "decision_type": "recall",
                "params": {"mission_id": "m1", "resource": "ambulance", "qty": 1},
            },
        ],
        "proposals": [],
        "responses": [],
    })
    provider = MockProvider(script=[response_json])
    role = _make_role()
    agent = LLMAgent("medical", role, provider, "")
    obs = _make_obs(tick=1)

    result = await agent.act(obs)

    assert result.decisions[0].agent_id == "medical"


@pytest.mark.asyncio
async def test_identity_forced_on_proposals() -> None:
    """sender is forced on proposals regardless of what LLM emits."""
    response_json = json.dumps({
        "decisions": [],
        "proposals": [
            {
                "kind": "resource_request",
                "recipient": None,
                "body": {"mission_id": "m1", "resource": "ambulance", "qty": 1, "urgency": 5},
            },
        ],
        "responses": [],
    })
    provider = MockProvider(script=[response_json])
    role = _make_role()
    agent = LLMAgent("medical", role, provider, "")
    obs = _make_obs(tick=2)

    result = await agent.act(obs)

    assert result.proposals[0].sender == "medical"


@pytest.mark.asyncio
async def test_usage_attached_on_success() -> None:
    """usage is attached to the response on success."""
    response_json = _valid_json_response()
    provider = MockProvider(script=[response_json])
    role = _make_role()
    agent = LLMAgent("medical", role, provider, "")

    result = await agent.act(_make_obs())

    assert result.usage is not None
    assert isinstance(result.usage, TokenUsage)
    assert result.usage.cost_usd >= 0.0


# ---------------------------------------------------------------------------
# Unit: parse failure -> error response with usage attached
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_failure_returns_error_with_usage() -> None:
    """When parse fails, error response is returned and usage is attached."""
    provider = MockProvider(script=["not valid json at all !!"])
    role = _make_role()
    agent = LLMAgent("medical", role, provider, "")

    result = await agent.act(_make_obs())

    assert result.error != ""
    assert "parse error" in result.error
    assert result.usage is not None
    assert result.decisions == ()
    assert result.proposals == ()


@pytest.mark.asyncio
async def test_parse_failure_empty_collections() -> None:
    """Parse failure produces empty decisions/proposals/responses."""
    provider = MockProvider(script=["{ this is not json }"])
    role = _make_role()
    agent = LLMAgent("medical", role, provider, "")

    result = await agent.act(_make_obs())

    assert result.error != ""
    assert result.decisions == ()
    assert result.proposals == ()
    assert result.responses == ()


# ---------------------------------------------------------------------------
# Unit: provider error -> error response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_error_returns_error_response() -> None:
    """Provider failure returns AgentResponse with error, no usage."""
    def _always_raise(model: str, system: str, user: str) -> str:
        raise ProviderError("connection refused")

    provider = MockProvider(script=_always_raise)
    role = _make_role()
    agent = LLMAgent("medical", role, provider, "")

    result = await agent.act(_make_obs())

    assert result.error != ""
    assert "provider error" in result.error
    assert result.usage is None


@pytest.mark.asyncio
async def test_provider_error_never_raises() -> None:
    """LLMAgent.act must never raise, even on provider errors."""
    def _explode(model: str, system: str, user: str) -> str:
        raise RuntimeError("unexpected crash")

    provider = MockProvider(script=_explode)
    role = _make_role()
    agent = LLMAgent("medical", role, provider, "")

    result = await agent.act(_make_obs())
    assert result.error != ""


# ---------------------------------------------------------------------------
# Unit: unknown proposal kind — never-raises + valid proposals preserved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_proposal_kind_never_raises() -> None:
    """act() must not raise when the LLM emits a proposal with an unknown kind.

    Regression for the pydantic ValidationError that escaped the mapping section
    (Proposal.kind is a frozen StrEnum — constructing Proposal(kind='bogus') raises).
    """
    response_json = json.dumps({
        "decisions": [],
        "proposals": [{"kind": "not_a_kind", "recipient": "fire", "body": {}}],
        "responses": [],
    })
    provider = MockProvider(script=[response_json])
    role = _make_role()
    agent = LLMAgent("medical", role, provider, "")

    # Must not raise
    result = await agent.act(_make_obs())
    assert result.error == ""


@pytest.mark.asyncio
async def test_unknown_proposal_kind_dropped_valid_kept() -> None:
    """Unknown-kind proposals are dropped individually; valid proposals in the same
    response are preserved (the whole turn must not be discarded)."""
    response_json = json.dumps({
        "decisions": [],
        "proposals": [
            {"kind": "not_a_kind", "recipient": "fire", "body": {}},
            {
                "kind": "resource_request",
                "recipient": None,
                "body": {"mission_id": "m1", "resource": "ambulance", "qty": 1, "urgency": 5},
            },
        ],
        "responses": [],
    })
    provider = MockProvider(script=[response_json])
    role = _make_role()
    agent = LLMAgent("medical", role, provider, "")

    result = await agent.act(_make_obs())

    assert result.error == ""
    # The bad proposal is dropped; the good one survives
    assert len(result.proposals) == 1
    assert result.proposals[0].kind == ProposalKind.RESOURCE_REQUEST


@pytest.mark.asyncio
async def test_unknown_proposal_kind_all_bad_returns_empty() -> None:
    """When every proposal has an unknown kind the response is empty but no error."""
    response_json = json.dumps({
        "decisions": [{"decision_type": "recall",
                       "params": {"mission_id": "m1", "resource": "ambulance", "qty": 1}}],
        "proposals": [
            {"kind": "bad_kind_1", "recipient": None, "body": {}},
            {"kind": "bad_kind_2", "recipient": None, "body": {}},
        ],
        "responses": [],
    })
    provider = MockProvider(script=[response_json])
    role = _make_role()
    agent = LLMAgent("medical", role, provider, "")

    result = await agent.act(_make_obs())

    assert result.error == ""
    assert result.proposals == ()
    # Decisions are unaffected
    assert len(result.decisions) == 1


# ---------------------------------------------------------------------------
# E2E: Full Engine run with MockProvider
# ---------------------------------------------------------------------------


def _parse_missions_from_text(text: str) -> list[dict[str, Any]]:
    """Parse mission rows from the rendered observation text."""
    missions: list[dict[str, Any]] = []
    row_re = re.compile(
        r"^\s+(m\d+)\s+(\S+)\s+\S+\s+(\d+)\s+\d+\s+(-?\d+)\s+(\d+)\s+(.*?)$"
    )
    for line in text.splitlines():
        m = row_re.match(line)
        if m:
            mid = m.group(1)
            kind = m.group(2)
            dl_in = int(m.group(4))
            pri = int(m.group(5))
            staffing_str = m.group(6).strip()
            assigned: dict[str, int] = {}
            required: dict[str, int] = {}
            for part in staffing_str.split():
                if ":" in part and "/" in part:
                    res, counts = part.split(":", 1)
                    got_s, need_s = counts.split("/", 1)
                    with contextlib.suppress(ValueError):
                        assigned[res] = int(got_s)
                        required[res] = int(need_s)
            missions.append({
                "id": mid,
                "kind": kind,
                "deadline_in": dl_in,
                "priority": pri,
                "assigned": assigned,
                "required": required,
            })
    return missions


def _parse_inbox_ids(text: str) -> list[str]:
    """Extract proposal ids from 'YOUR INBOX' section."""
    ids: list[str] = []
    in_inbox = False
    for line in text.splitlines():
        if "YOUR INBOX" in line:
            in_inbox = True
            continue
        if in_inbox:
            stripped = line.strip()
            if stripped == "" or (line and not line.startswith(" ") and stripped != "(empty)"):
                break
            m = re.search(r"\[([^\]]+)\]", line)
            if m:
                ids.append(m.group(1))
    return ids


def _build_mock_response(model: str, system: str, user: str) -> str:  # noqa: ARG001
    """Build a valid JSON response by parsing the observation text.

    Logic:
    - commander: set_priority for unprioritised missions; accept all escalations
    - specialists (medical/rescue/fire/infra): resource_request for their mission kind
    - comms: broadcast when PANIC > 0.4
    - infrastructure: also repair_road for blocked districts
    """
    agent_role = "unknown"
    for role in ("commander", "medical", "rescue", "fire", "infrastructure", "comms"):
        if role in system.lower()[:200]:
            agent_role = role
            break

    decisions: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []

    missions = _parse_missions_from_text(user)
    inbox_ids = _parse_inbox_ids(user)

    panic = 0.0
    panic_m = re.search(r"PANIC\s+([\d.]+)", user)
    if panic_m:
        with contextlib.suppress(ValueError):
            panic = float(panic_m.group(1))

    pools: dict[str, int] = {}
    pool_m = re.search(r"POOLS\s+(.*)", user)
    if pool_m:
        for part in pool_m.group(1).split():
            if ":" in part:
                k, v = part.split(":", 1)
                with contextlib.suppress(ValueError):
                    pools[k.strip()] = int(v.strip())

    blocked: list[str] = []
    blocked_m = re.search(r"BLOCKED\s+(.*)", user)
    if blocked_m:
        blocked = blocked_m.group(1).split()

    if agent_role == "commander":
        in_inbox_section = False
        for line in user.splitlines():
            if "YOUR INBOX" in line:
                in_inbox_section = True
                continue
            if in_inbox_section:
                if re.match(r"^[A-Z]", line.strip()) and "INBOX" not in line:
                    break
                prop_m = re.search(r"\[([^\]]+)\]\s+from=\S+\s+kind=(\S+)", line)
                if prop_m:
                    pid = prop_m.group(1)
                    kind_str = prop_m.group(2)
                    if "escalation" in kind_str.lower():
                        responses.append({
                            "proposal_id": pid,
                            "accept": True,
                            "note": "acknowledged",
                        })

        for m in missions:
            if m["priority"] == 0:
                dl_in = m["deadline_in"]
                urgency_bonus = 2 if dl_in <= 6 else 0
                priority = min(10, 4 + urgency_bonus)
                decisions.append({
                    "decision_type": "set_priority",
                    "params": {"mission_id": m["id"], "priority": priority},
                    "rationale": "initial triage",
                })

    elif agent_role == "comms":
        if panic > 0.4:
            decisions.append({
                "decision_type": "broadcast",
                "params": {
                    "message": (
                        "Emergency services are responding. "
                        "Please remain calm and follow instructions."
                    ),
                },
                "rationale": "reduce panic",
            })

    elif agent_role == "infrastructure":
        for m in missions:
            if m["kind"] != "infra_repair":
                continue
            for res in ["repair_crew"]:
                needed = m["required"].get(res, 0) - m["assigned"].get(res, 0)
                avail = pools.get(res, 0)
                if needed > 0 and avail > 0:
                    qty = min(needed, avail)
                    dl_in = m["deadline_in"]
                    urgency = 10 if dl_in <= 2 else (8 if dl_in <= 4 else 5)
                    proposals.append({
                        "kind": "resource_request",
                        "recipient": None,
                        "body": {
                            "mission_id": m["id"],
                            "resource": res,
                            "qty": qty,
                            "urgency": urgency,
                        },
                    })
        repair_avail = pools.get("repair_crew", 0)
        for district in sorted(blocked):
            if repair_avail > 0:
                decisions.append({
                    "decision_type": "repair_road",
                    "params": {"district_id": district},
                    "rationale": "unblock road",
                })
                repair_avail -= 1

    else:
        kind_map = {
            "medical": "medical_surge",
            "rescue": "collapse_rescue",
            "fire": "fire",
        }
        target_kind = kind_map.get(agent_role, "")
        resource_map: dict[str, list[str]] = {
            "medical_surge": ["ambulance", "supply_truck"],
            "collapse_rescue": ["rescue_crew", "ambulance"],
            "fire": ["fire_engine"],
        }
        target_resources = resource_map.get(target_kind, [])

        for m in missions:
            if m["kind"] != target_kind:
                continue
            for res in target_resources:
                needed = m["required"].get(res, 0) - m["assigned"].get(res, 0)
                avail = pools.get(res, 0)
                if needed > 0 and avail > 0:
                    qty = min(needed, avail)
                    dl_in = m["deadline_in"]
                    urgency = 10 if dl_in <= 2 else (8 if dl_in <= 4 else 5)
                    proposals.append({
                        "kind": "resource_request",
                        "recipient": None,
                        "body": {
                            "mission_id": m["id"],
                            "resource": res,
                            "qty": qty,
                            "urgency": urgency,
                        },
                    })

    for pid in inbox_ids:
        if not any(r["proposal_id"] == pid for r in responses):
            responses.append({
                "proposal_id": pid,
                "accept": True,
                "note": "acknowledged",
            })

    return json.dumps({
        "decisions": decisions,
        "proposals": proposals,
        "responses": responses,
    })


@pytest.mark.asyncio
async def test_e2e_mock_society_run() -> None:
    """Full Engine run: 25+ ticks, all LLMAgents, MockProvider, zero errors."""
    from aftershock.kernel.engine import Engine
    from aftershock.kernel.recorder import Recorder, load_run
    from aftershock.kernel.registry import DecisionRegistry
    from aftershock.kernel.roles import load_roles
    from aftershock.town.decisions import register_all
    from aftershock.town.prompts import build_llm_agents
    from aftershock.town.society import TownResolver, TownSociety
    from aftershock.town.state import new_town

    seed = 42
    ticks = 35

    provider = MockProvider(script=_build_mock_response)
    roles = load_roles(_ROLES_DIR)
    agents: dict[str, Agent] = build_llm_agents(roles, provider)

    expected_ids = {"commander", "comms", "fire", "infrastructure", "medical", "rescue"}
    assert set(agents.keys()) == expected_ids
    for agent_id, agent in agents.items():
        assert isinstance(agent, LLMAgent), f"{agent_id} should be LLMAgent"

    world = new_town(seed)
    society = TownSociety(max_ticks=ticks)
    registry = DecisionRegistry()
    register_all(registry)
    resolver = TownResolver()

    with tempfile.TemporaryDirectory() as td:
        recorder = Recorder(Path(td), "test-e2e", {"seed": seed, "arm": "society"})
        engine = Engine(
            world=world,
            society=society,
            agents=agents,
            registry=registry,
            roles=roles,
            resolver=resolver,
            recorder=recorder,
            seed=seed,
            max_ticks=ticks,
            agent_timeout_s=30.0,
        )
        summary = await engine.run()

    assert summary.ticks_run >= 25, f"Expected >= 25 ticks, got {summary.ticks_run}"

    # Second run to collect tick records for assertions
    provider2 = MockProvider(script=_build_mock_response)
    roles2 = load_roles(_ROLES_DIR)
    agents2: dict[str, Agent] = build_llm_agents(roles2, provider2)
    world2 = new_town(seed)
    society2 = TownSociety(max_ticks=ticks)
    registry2 = DecisionRegistry()
    register_all(registry2)

    with tempfile.TemporaryDirectory() as td2:
        recorder2 = Recorder(Path(td2), "test-e2e-check", {"seed": seed, "arm": "society"})
        engine2 = Engine(
            world=world2,
            society=society2,
            agents=agents2,
            registry=registry2,
            roles=roles2,
            resolver=resolver,
            recorder=recorder2,
            seed=seed,
            max_ticks=ticks,
            agent_timeout_s=30.0,
        )
        summary2 = await engine2.run()
        _, records = load_run(Path(td2) / "test-e2e-check")

    # Zero errors
    all_errors = [
        (record.tick, resp.agent_id, resp.error)
        for record in records
        for resp in record.responses
        if resp.error
    ]
    assert all_errors == [], f"Unexpected agent errors: {all_errors[:5]}"

    # At least 1 auction grant
    total_grants = sum(
        1 for record in records
        for ruling in record.rulings
        if ruling.accepted and ruling.decided_by == "kernel:auction"
    )
    assert total_grants >= 1, "Expected at least 1 auction grant"

    # Ledger total cost_usd > 0
    cost = summary2.cost
    assert cost.get("cost_usd", 0.0) > 0.0, f"Expected cost_usd > 0, got {cost}"

    # lives_saved > 0
    lives_saved = summary2.final_scores.get("lives_saved", 0)
    assert lives_saved > 0, f"Expected lives_saved > 0, got {lives_saved}"
