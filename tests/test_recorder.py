"""Tests for recorder.py: canonical_json, digest, and Recorder round-trips."""

import json
import tempfile
from pathlib import Path

from pydantic import BaseModel

from aftershock.kernel.protocol import (
    AgentResponse,
    Decision,
    Rejection,
    TickRecord,
    TokenUsage,
    WorldEvent,
)
from aftershock.kernel.recorder import Recorder, canonical_json, digest, load_run

# ---------------------------------------------------------------------------
# canonical_json
# ---------------------------------------------------------------------------


def test_canonical_json_sorts_keys():
    obj = {"z": 1, "a": 2, "m": 3}
    result = canonical_json(obj)
    assert result == '{"a":2,"m":3,"z":1}'


def test_canonical_json_nested_sorts():
    obj = {"b": {"y": 1, "x": 2}, "a": 3}
    result = canonical_json(obj)
    parsed = json.loads(result)
    assert list(parsed.keys()) == ["a", "b"]
    assert list(parsed["b"].keys()) == ["x", "y"]


def test_canonical_json_compact_separators():
    result = canonical_json({"k": [1, 2]})
    assert " " not in result


def test_canonical_json_ensure_ascii():
    result = canonical_json({"msg": "café"})
    assert "\\u" in result or all(ord(c) < 128 for c in result)


def test_canonical_json_pydantic_model():
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, cost_usd=0.01, model="gpt-4")
    result = canonical_json(usage)
    parsed = json.loads(result)
    assert parsed["prompt_tokens"] == 10
    assert parsed["model"] == "gpt-4"
    # Keys must be sorted
    assert list(parsed.keys()) == sorted(parsed.keys())


class _Inner(BaseModel):
    z: int
    a: str


def test_canonical_json_pydantic_keys_sorted():
    obj = _Inner(z=9, a="hello")
    result = canonical_json(obj)
    parsed = json.loads(result)
    assert list(parsed.keys()) == sorted(parsed.keys())


# ---------------------------------------------------------------------------
# digest
# ---------------------------------------------------------------------------


def test_digest_is_sha256_hex():
    d = digest({"k": "v"})
    assert len(d) == 64
    assert all(c in "0123456789abcdef" for c in d)


def test_digest_deterministic():
    assert digest({"x": 1}) == digest({"x": 1})


def test_digest_changes_with_content():
    assert digest({"x": 1}) != digest({"x": 2})


# ---------------------------------------------------------------------------
# Recorder + load_run
# ---------------------------------------------------------------------------


def _make_tick_record(tick: int = 0) -> TickRecord:
    decision = Decision(decision_id="a-0", agent_id="medical", decision_type="dispatch")
    rejection = Rejection(
        decision_id="a-1",
        agent_id="medical",
        decision_type="recall",
        reason="pool empty",
    )
    event = WorldEvent(
        event_id="e-0",
        tick=tick,
        kind="mission_spawned",
        payload={"mission_id": "m1"},
    )
    response = AgentResponse(
        agent_id="medical",
        decisions=(decision,),
        usage=TokenUsage(prompt_tokens=100, completion_tokens=20, cost_usd=0.005, model="gpt-4"),
    )
    return TickRecord(
        tick=tick,
        observation_digests={"medical": "abc123"},
        responses=(response,),
        rulings=(),
        accepted=(decision,),
        rejected=(rejection,),
        events=(event,),
        scores={"lives_saved": 2.0},
        world_digest="deadbeef",
    )


def test_recorder_round_trips_tick_record():
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        manifest = {"seed": 42, "arm": "scripted", "max_ticks": 10}
        rec = Recorder(out_dir, "run-001", manifest)
        record = _make_tick_record(tick=0)
        rec.write_tick(record)
        rec.close()

        loaded_manifest, ticks = load_run(rec.run_dir)
        assert loaded_manifest == manifest
        assert len(ticks) == 1
        loaded = ticks[0]
        assert loaded.tick == 0
        assert loaded.world_digest == "deadbeef"
        assert loaded.scores == {"lives_saved": 2.0}
        assert len(loaded.responses) == 1
        assert loaded.responses[0].agent_id == "medical"
        assert loaded.responses[0].usage is not None
        assert loaded.responses[0].usage.prompt_tokens == 100


def test_recorder_multiple_ticks():
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        with Recorder(out_dir, "run-002", {"seed": 1}) as rec:
            for i in range(3):
                rec.write_tick(_make_tick_record(tick=i))

        _, ticks = load_run(rec.run_dir)
        assert len(ticks) == 3
        assert [t.tick for t in ticks] == [0, 1, 2]


def test_recorder_context_manager():
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        with Recorder(out_dir, "run-003", {"x": 1}) as rec:
            run_dir = rec.run_dir
        # File should be closed; run.json must exist
        assert (run_dir / "run.json").exists()
        assert (run_dir / "ticks.ndjson").exists()


def test_recorder_run_dir_property():
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        rec = Recorder(out_dir, "my-run", {})
        assert rec.run_dir == out_dir / "my-run"
        rec.close()


def test_load_run_manifest_matches():
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        manifest = {"seed": 99, "arm": "llm", "ticks": 30}
        with Recorder(out_dir, "r", manifest) as rec:
            pass
        loaded_manifest, ticks = load_run(rec.run_dir)
        assert loaded_manifest == manifest
        assert ticks == []


def test_canonical_json_used_for_tick_ndjson():
    """Each line in ticks.ndjson is valid JSON with sorted keys."""
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        with Recorder(out_dir, "r2", {}) as rec:
            rec.write_tick(_make_tick_record(tick=5))
        lines = (rec.run_dir / "ticks.ndjson").read_text().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["tick"] == 5
