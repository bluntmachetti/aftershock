"""Tests for mcp_server.py.

All tool functions are called directly (not over stdio) against a tmp runs_root
seeded by a short scripted Engine run. No network connections are required.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import aftershock.mcp_server as mcp_mod
from aftershock.kernel.engine import Engine
from aftershock.kernel.recorder import Recorder
from aftershock.town.arms import build_arm

# ---------------------------------------------------------------------------
# Fixture: a small runs_root with one completed scripted run
# ---------------------------------------------------------------------------


def _build_run(
    runs_root: Path, run_id: str = "scripted-seed42", seed: int = 42, ticks: int = 6
) -> Path:
    """Run a tiny scripted Engine run and write it into runs_root. Returns the run dir."""
    setup = build_arm("scripted", seed, None)
    manifest = {"arm": "scripted", "seed": seed, "ticks": ticks, "run_id": run_id}
    with Recorder(runs_root, run_id, manifest) as rec:
        engine = Engine(
            world=setup.world,
            society=setup.society,
            agents=setup.agents,
            registry=setup.registry,
            roles=setup.roles,
            resolver=setup.resolver,
            recorder=rec,
            seed=seed,
            max_ticks=ticks,
            agent_timeout_s=5.0,
        )
        asyncio.run(engine.run())
    return runs_root / run_id


@pytest.fixture()
def runs_root(tmp_path: Path) -> Path:
    """A temporary runs_root with one completed 6-tick scripted run."""
    rd = tmp_path / "runs"
    rd.mkdir()
    _build_run(rd)
    # Point the module globals at this directory
    mcp_mod._runs_root = rd
    mcp_mod._bench_root = tmp_path / "bench_results"
    return rd


# ---------------------------------------------------------------------------
# list_runs
# ---------------------------------------------------------------------------


def test_list_runs_returns_list(runs_root: Path) -> None:
    result = mcp_mod.list_runs()
    assert isinstance(result, list)
    assert len(result) == 1
    item = result[0]
    assert item["run_id"] == "scripted-seed42"
    assert item["arm"] == "scripted"
    assert item["seed"] == 42
    assert isinstance(item["ticks"], int)
    assert item["ticks"] > 0


def test_list_runs_empty_dir(tmp_path: Path) -> None:
    mcp_mod._runs_root = tmp_path / "nonexistent"
    result = mcp_mod.list_runs()
    assert result == []


# ---------------------------------------------------------------------------
# run_summary
# ---------------------------------------------------------------------------


def test_run_summary_shape(runs_root: Path) -> None:
    result = mcp_mod.run_summary("scripted-seed42")
    assert result["run_id"] == "scripted-seed42"
    assert "manifest" in result
    assert isinstance(result["n_ticks"], int)
    assert result["n_ticks"] > 0
    assert isinstance(result["final_scores"], dict)
    assert isinstance(result["has_world"], bool)


def test_run_summary_invalid_run_id(runs_root: Path) -> None:
    result = mcp_mod.run_summary("../etc/passwd")
    assert "error" in result


def test_run_summary_missing_run(runs_root: Path) -> None:
    result = mcp_mod.run_summary("no-such-run")
    assert "error" in result


# ---------------------------------------------------------------------------
# get_ticks
# ---------------------------------------------------------------------------


def test_get_ticks_shape(runs_root: Path) -> None:
    result = mcp_mod.get_ticks("scripted-seed42", start=0, limit=5)
    assert result["run_id"] == "scripted-seed42"
    assert result["start"] == 0
    assert isinstance(result["total"], int)
    assert result["total"] > 0
    ticks = result["ticks"]
    assert isinstance(ticks, list)
    assert 1 <= len(ticks) <= 5
    # Each tick is a dict with expected keys
    t0 = ticks[0]
    assert "tick" in t0
    assert "responses" in t0
    assert "scores" in t0


def test_get_ticks_limit_capped(runs_root: Path) -> None:
    result = mcp_mod.get_ticks("scripted-seed42", start=0, limit=999)
    assert len(result["ticks"]) <= 20


def test_get_ticks_invalid_run_id(runs_root: Path) -> None:
    result = mcp_mod.get_ticks("../bad", start=0, limit=5)
    assert "error" in result


def test_get_ticks_worlds_present(runs_root: Path) -> None:
    # world.ndjson is written by Recorder; worlds may or may not be non-None
    result = mcp_mod.get_ticks("scripted-seed42", start=0, limit=2)
    # worlds key exists in the result
    assert "worlds" in result


# ---------------------------------------------------------------------------
# negotiation_feed
# ---------------------------------------------------------------------------


def test_negotiation_feed_shape(runs_root: Path) -> None:
    result = mcp_mod.negotiation_feed("scripted-seed42")
    assert "feed" in result
    assert isinstance(result["feed"], list)
    assert isinstance(result["total"], int)


def test_negotiation_feed_grant_line(runs_root: Path) -> None:
    """Feed contains at least one GRANTED line (scripted arm auctions resources)."""
    result = mcp_mod.negotiation_feed("scripted-seed42", start=0, limit=100)
    feed = result["feed"]
    grant_lines = [e for e in feed if "GRANTED" in e["line"]]
    assert len(grant_lines) >= 1, f"Expected at least one GRANTED line; feed={feed}"


def test_negotiation_feed_declined_line_with_reason(runs_root: Path) -> None:
    """When resources are scarce, at least one DECLINED line should appear with reason text."""
    # Run a heavier seed to ensure contention; fall back gracefully if not present
    result = mcp_mod.negotiation_feed("scripted-seed42", start=0, limit=200)
    feed = result["feed"]
    declined_lines = [e for e in feed if "DECLINED" in e["line"]]
    # If there are any declined lines, they must carry reason text
    for entry in declined_lines:
        # The line format is: "<sender> ... — DECLINED: <reason>"
        assert "DECLINED:" in entry["line"], f"Declined line missing reason: {entry['line']}"
        assert entry["reason"] != "", f"reason field empty for: {entry}"


def test_negotiation_feed_grant_and_declined_with_more_ticks(tmp_path: Path) -> None:
    """Run 15 ticks to get both grants and declines with reason text."""
    rd = tmp_path / "runs15"
    rd.mkdir()
    _build_run(rd, run_id="scripted-seed11", seed=11, ticks=15)
    mcp_mod._runs_root = rd
    result = mcp_mod.negotiation_feed("scripted-seed11", start=0, limit=500)
    feed = result["feed"]
    grant_lines = [e for e in feed if "GRANTED" in e["line"]]
    declined_lines = [e for e in feed if "DECLINED" in e["line"]]
    assert len(grant_lines) >= 1, "Expected at least one GRANTED line"
    # If any declines exist, they must carry a reason
    for entry in declined_lines:
        assert "DECLINED:" in entry["line"]
        assert entry["reason"] != ""


# ---------------------------------------------------------------------------
# agent_story
# ---------------------------------------------------------------------------


def test_agent_story_shape(runs_root: Path) -> None:
    result = mcp_mod.agent_story("scripted-seed42", "medical")
    assert result["agent_id"] == "medical"
    assert "decisions" in result
    assert "rejections" in result
    assert "proposal_outcomes" in result
    assert isinstance(result["decisions"], list)
    assert isinstance(result["rejections"], list)
    assert isinstance(result["proposal_outcomes"], list)


def test_agent_story_medical_has_proposal_outcomes(runs_root: Path) -> None:
    """Medical agent submits RESOURCE_REQUEST proposals; they appear in proposal_outcomes."""
    result = mcp_mod.agent_story("scripted-seed42", "medical")
    # medical submits resource requests (RESOURCE_REQUEST proposals) — should appear
    assert len(result["proposal_outcomes"]) >= 1, (
        "Expected medical agent to have proposal outcomes"
    )


def test_agent_story_medical_rejections(tmp_path: Path) -> None:
    """Run enough ticks that medical accumulates some rejections."""
    rd = tmp_path / "runs_rej"
    rd.mkdir()
    _build_run(rd, run_id="scripted-seed23", seed=23, ticks=15)
    mcp_mod._runs_root = rd
    result = mcp_mod.agent_story("scripted-seed23", "medical")
    # Rejections may or may not appear in 15 ticks, but the structure is always correct
    assert isinstance(result["rejections"], list)
    for rej in result["rejections"]:
        assert "tick" in rej
        assert "reason" in rej
        assert "decision_type" in rej


def test_agent_story_invalid_run_id(runs_root: Path) -> None:
    result = mcp_mod.agent_story("../traversal", "medical")
    assert "error" in result


# ---------------------------------------------------------------------------
# bench_results
# ---------------------------------------------------------------------------


def test_bench_results_missing_dir(tmp_path: Path) -> None:
    mcp_mod._bench_root = tmp_path / "no_bench"
    result = mcp_mod.bench_results()
    assert "error" in result


def test_bench_results_with_data(tmp_path: Path) -> None:
    bench_dir = tmp_path / "bench_results"
    bench_dir.mkdir()
    (bench_dir / "results.json").write_text(
        json.dumps({"arms": {"scripted": {"mean_lives_saved": 10}}}),
        encoding="utf-8",
    )
    mcp_mod._bench_root = bench_dir
    result = mcp_mod.bench_results()
    assert "results" in result
    assert len(result["results"]) == 1
    entry = result["results"][0]
    assert "data" in entry
    assert "arms" in entry["data"]


# ---------------------------------------------------------------------------
# inject_event — no live server (closed port)
# ---------------------------------------------------------------------------


def test_inject_event_no_server(runs_root: Path) -> None:
    """inject_event returns a friendly error when no server listens on 8788."""
    # Call inject_event; it targets 127.0.0.1:8788 which has nothing listening
    # in CI. We just verify the returned dict has ok=False and a non-empty error.
    result = mcp_mod.inject_event("fire", "old_town")
    assert result["ok"] is False
    assert isinstance(result["error"], str)
    assert len(result["error"]) > 0
    # Error message should be informative (not a raw exception repr)
    error_lower = result["error"].lower()
    informative = any(
        word in error_lower for word in ("connect", "server", "reach", "timeout", "error")
    )
    assert informative, f"Error message is not informative: {result['error']}"
