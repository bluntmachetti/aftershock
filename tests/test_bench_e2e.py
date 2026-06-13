"""Offline LLM-arm benchmark e2e tests.

Uses MockProvider (regex-driven, same approach as test_llm_agent.py) to run
run_bench with arms=[scripted, society], seeds=[42], ticks=12.

Assertions:
- Both cells complete (summary.json written)
- society cell cost_usd > 0
- aggregate + render_markdown include both arms
- Resume: second invocation skips cells (build_arm not called again)
"""

from __future__ import annotations

import contextlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any

import pytest

from aftershock.bench import aggregate, render_markdown, run_bench
from aftershock.llm.provider import MockProvider  # noqa: F401 — used via _patched_build_arm

# ---------------------------------------------------------------------------
# Regex-driven mock response (same logic as test_llm_agent.py _build_mock_response)
# ---------------------------------------------------------------------------


def _parse_missions_from_text(text: str) -> list[dict[str, Any]]:
    """Parse mission rows from the rendered observation text."""
    missions: list[dict[str, Any]] = []
    row_re = re.compile(r"^\s+(m\d+)\s+(\S+)\s+\S+\s+(\d+)\s+\d+\s+(-?\d+)\s+(\d+)\s+(.*?)$")
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
            missions.append(
                {
                    "id": mid,
                    "kind": kind,
                    "deadline_in": dl_in,
                    "priority": pri,
                    "assigned": assigned,
                    "required": required,
                }
            )
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

    Mirrors the same heuristic logic as test_llm_agent.py so the society arm
    actually makes progress (auction grants, decisions applied, lives saved).
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
                        responses.append(
                            {
                                "proposal_id": pid,
                                "accept": True,
                                "note": "acknowledged",
                            }
                        )

        for m in missions:
            if m["priority"] == 0:
                dl_in = m["deadline_in"]
                urgency_bonus = 2 if dl_in <= 6 else 0
                priority = min(10, 4 + urgency_bonus)
                decisions.append(
                    {
                        "decision_type": "set_priority",
                        "params": {"mission_id": m["id"], "priority": priority},
                        "rationale": "initial triage",
                    }
                )

    elif agent_role == "comms":
        if panic > 0.4:
            decisions.append(
                {
                    "decision_type": "broadcast",
                    "params": {
                        "message": (
                            "Emergency services are responding. "
                            "Please remain calm and follow instructions."
                        ),
                    },
                    "rationale": "reduce panic",
                }
            )

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
                    proposals.append(
                        {
                            "kind": "resource_request",
                            "recipient": None,
                            "body": {
                                "mission_id": m["id"],
                                "resource": res,
                                "qty": qty,
                                "urgency": urgency,
                            },
                        }
                    )
        repair_avail = pools.get("repair_crew", 0)
        for district in sorted(blocked):
            if repair_avail > 0:
                decisions.append(
                    {
                        "decision_type": "repair_road",
                        "params": {"district_id": district},
                        "rationale": "unblock road",
                    }
                )
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
                    proposals.append(
                        {
                            "kind": "resource_request",
                            "recipient": None,
                            "body": {
                                "mission_id": m["id"],
                                "resource": res,
                                "qty": qty,
                                "urgency": urgency,
                            },
                        }
                    )

    for pid in inbox_ids:
        if not any(r["proposal_id"] == pid for r in responses):
            responses.append(
                {
                    "proposal_id": pid,
                    "accept": True,
                    "note": "acknowledged",
                }
            )

    tool_calls: list[dict[str, Any]] = []

    for decision in decisions:
        tool_calls.append(
            {
                "function": {
                    "name": decision["decision_type"],
                    "arguments": json.dumps(
                        {
                            **decision["params"],
                            "rationale": decision.get("rationale", ""),
                        }
                    ),
                }
            }
        )

    for proposal in proposals:
        tool_calls.append(
            {
                "function": {
                    "name": f"propose_{proposal['kind']}",
                    "arguments": json.dumps(proposal["body"]),
                }
            }
        )

    for response in responses:
        tool_calls.append(
            {
                "function": {
                    "name": "accept_proposal",
                    "arguments": json.dumps(
                        {
                            "proposal_id": response["proposal_id"],
                            "note": response.get("note", ""),
                        }
                    ),
                }
            }
        )

    if not tool_calls:
        tool_calls.append(
            {
                "function": {
                    "name": "no_op",
                    "arguments": json.dumps({"rationale": "nothing to do"}),
                }
            }
        )

    return {"tool_calls": tool_calls}


# ---------------------------------------------------------------------------
# The main e2e test
# ---------------------------------------------------------------------------


def test_bench_e2e_offline_llm_arm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Offline benchmark: arms=[scripted, society], seeds=[42], ticks=12.

    Monkeypatches build_arm for the society cell so that the LLMAgents use
    MockProvider instead of a live QwenProvider.

    Assertions:
    - Both cells complete; summary.json written for each
    - society cell cost_usd > 0
    - aggregate and render_markdown include both arms
    - Resume: second run_bench call skips all cells (build_arm not called)
    """
    import aftershock.bench as bench_mod
    from aftershock.town.arms import build_arm as real_build_arm

    # Track build_arm call count for resume assertion
    build_arm_calls: list[str] = []

    def _patched_build_arm(arm: str, seed: int, provider: Any) -> Any:
        build_arm_calls.append(arm)
        if arm == "society":
            # Build with a MockProvider instead of the passed provider
            mock_provider = MockProvider(script=_build_mock_response)
            return real_build_arm(arm, seed, mock_provider)
        # scripted: provider is None, pass through
        return real_build_arm(arm, seed, provider)

    monkeypatch.setattr(bench_mod, "build_arm", _patched_build_arm)

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        manifest: dict[str, Any] = {
            "ticks": 12,
            "seeds": [42],
            "arms": ["scripted", "society"],
        }

        # First run: both cells should execute
        cells = run_bench(manifest, provider=None, out_dir=out_dir)

        assert len(cells) == 2, f"Expected 2 cells, got {len(cells)}: {cells}"

        # Verify cell keys
        arm_to_cell = {c["arm"]: c for c in cells}
        assert "scripted" in arm_to_cell
        assert "society" in arm_to_cell

        # scripted: cost is 0
        scripted_cell = arm_to_cell["scripted"]
        assert scripted_cell["cost"]["cost_usd"] == 0.0

        # society: cost_usd > 0 (MockProvider fabricates plausible token usage)
        society_cell = arm_to_cell["society"]
        assert society_cell["cost"]["cost_usd"] > 0.0, (
            f"society cell cost_usd should be > 0, got {society_cell['cost']['cost_usd']}"
        )

        # society agents run through the native-tool path (use_tools=true); assert the
        # whole tool-mode bench cell produced zero agent errors, mirroring the
        # zero-error contract in test_llm_agent.test_e2e_mock_society_run. Without this
        # a regression in map_tool_calls (e.g. spurious "none recognized" errors) would
        # still leave cost_usd > 0 and slip through.
        from aftershock.kernel.recorder import load_run

        _, society_records, _worlds = load_run(out_dir / "society-seed42")
        society_errors = [
            (record.tick, resp.agent_id, resp.error)
            for record in society_records
            for resp in record.responses
            if resp.error
        ]
        assert society_errors == [], f"society tool-mode agent errors: {society_errors[:5]}"

        # summary.json written for both cells
        for arm in ("scripted", "society"):
            summary_path = out_dir / f"{arm}-seed42" / "summary.json"
            assert summary_path.exists(), f"summary.json missing for {arm}"

        # aggregate includes both arms
        agg = aggregate(cells)
        assert "scripted" in agg["arms"]
        assert "society" in agg["arms"]

        # render_markdown includes both arms
        md = render_markdown(agg)
        assert "scripted" in md
        assert "society" in md

        # Resume: second run_bench must skip all cells
        calls_before_resume = len(build_arm_calls)
        cells2 = run_bench(manifest, provider=None, out_dir=out_dir)
        calls_after_resume = len(build_arm_calls)

        assert calls_after_resume == calls_before_resume, (
            "build_arm was called during resume — cells were not skipped"
        )
        assert len(cells2) == 2, "Resume should return same 2 cells"
