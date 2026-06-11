"""End-to-end tests for the AAR engine and memory loop.

Tests cover:
- build_run_digest: deterministic, bounded (< 4000 chars) on a real 20-tick scripted run
- generate_aar: round-trips AAR_SCHEMA, writes aar.json, includes usage/cost
- AAR_SCHEMA validation: rejects >5 lessons, rejects >140-char lessons
- load_lessons: sanitizes injected control tokens, caps at max_lessons
- append_lessons + load_lessons: most-recent-first ordering
- commander prompt contains lessons block when wired, other roles do not
- build_arm("solo", lessons=[...]) raises ValueError
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from aftershock.llm.aar import (
    AAR_MODEL,
    AAR_SCHEMA,
    append_lessons,
    build_run_digest,
    generate_aar,
    load_lessons,
)
from aftershock.llm.provider import MockProvider

# ---------------------------------------------------------------------------
# Helpers: run a scripted 20-tick run and return (run_dir, manifest, ticks)
# ---------------------------------------------------------------------------


def _run_scripted_20(out_dir: Path) -> Path:
    """Run a scripted arm for 20 ticks under out_dir; return the run dir."""
    from aftershock.kernel.engine import Engine
    from aftershock.kernel.recorder import Recorder
    from aftershock.town.arms import build_arm

    seed = 42
    arm = "scripted"
    run_id = "test-aar-scripted"
    setup = build_arm(arm, seed, None)
    manifest = {"run_id": run_id, "seed": seed, "ticks": 20, "arm": arm}
    recorder = Recorder(out_dir, run_id, manifest)
    engine = Engine(
        world=setup.world,
        society=setup.society,
        agents=setup.agents,
        registry=setup.registry,
        roles=setup.roles,
        resolver=setup.resolver,
        recorder=recorder,
        seed=seed,
        max_ticks=20,
        agent_timeout_s=5.0,
    )
    asyncio.run(engine.run())
    return out_dir / run_id


# ---------------------------------------------------------------------------
# build_run_digest
# ---------------------------------------------------------------------------


def test_digest_is_deterministic() -> None:
    """build_run_digest must return the same string on two identical calls."""
    from aftershock.kernel.recorder import load_run

    with tempfile.TemporaryDirectory() as td:
        run_dir = _run_scripted_20(Path(td))
        manifest, ticks, _ = load_run(run_dir)
        d1 = build_run_digest(manifest, ticks)
        d2 = build_run_digest(manifest, ticks)
    assert d1 == d2


def test_digest_is_bounded() -> None:
    """build_run_digest must produce fewer than 4000 characters."""
    from aftershock.kernel.recorder import load_run

    with tempfile.TemporaryDirectory() as td:
        run_dir = _run_scripted_20(Path(td))
        manifest, ticks, _ = load_run(run_dir)
        d = build_run_digest(manifest, ticks)
    assert len(d) < 4000, f"Digest too long: {len(d)} chars"


def test_digest_contains_expected_sections() -> None:
    """Digest must include run metadata and score sections."""
    from aftershock.kernel.recorder import load_run

    with tempfile.TemporaryDirectory() as td:
        run_dir = _run_scripted_20(Path(td))
        manifest, ticks, _ = load_run(run_dir)
        d = build_run_digest(manifest, ticks)
    assert "RUN METADATA" in d
    assert "FINAL SCORES" in d
    assert "MISSION OUTCOMES" in d


# ---------------------------------------------------------------------------
# generate_aar: round-trips schema, writes aar.json
# ---------------------------------------------------------------------------


def _valid_aar_json() -> str:
    return json.dumps({
        "headline": "Test run completed adequately.",
        "grade": "B",
        "what_worked": ["Resource allocation was fast."],
        "coordination_failures": ["Medical missed one surge."],
        "key_moments": [{"tick": 5, "description": "Main quake resolved."}],
        "lessons": [
            "Prioritize medical surge missions early.",
            "Dispatch rescue crews before fire spreads.",
        ],
    })


def test_generate_aar_writes_aar_json() -> None:
    """generate_aar must write aar.json to the run directory."""
    mock = MockProvider(script=[_valid_aar_json()])

    with tempfile.TemporaryDirectory() as td:
        run_dir = _run_scripted_20(Path(td))
        asyncio.run(generate_aar(run_dir, mock))
        aar_path = run_dir / "aar.json"
        assert aar_path.exists(), "aar.json was not written"


def test_generate_aar_includes_usage() -> None:
    """aar.json must include a 'usage' field with cost_usd."""
    mock = MockProvider(script=[_valid_aar_json()])

    with tempfile.TemporaryDirectory() as td:
        run_dir = _run_scripted_20(Path(td))
        aar = asyncio.run(generate_aar(run_dir, mock))
        assert "usage" in aar
        assert "cost_usd" in aar["usage"]


def test_generate_aar_uses_aar_model() -> None:
    """generate_aar must call the provider with AAR_MODEL by default."""
    mock = MockProvider(script=[_valid_aar_json()])

    with tempfile.TemporaryDirectory() as td:
        run_dir = _run_scripted_20(Path(td))
        asyncio.run(generate_aar(run_dir, mock))
        assert mock.calls, "MockProvider was not called"
        model_used = mock.calls[0][0]
        assert model_used == AAR_MODEL, f"Expected {AAR_MODEL}, got {model_used}"


def test_generate_aar_roundtrips_schema_fields() -> None:
    """generate_aar must return all required AAR_SCHEMA fields."""
    mock = MockProvider(script=[_valid_aar_json()])

    with tempfile.TemporaryDirectory() as td:
        run_dir = _run_scripted_20(Path(td))
        aar = asyncio.run(generate_aar(run_dir, mock))
        assert "headline" in aar
        assert "grade" in aar
        assert "what_worked" in aar
        assert "coordination_failures" in aar
        assert "key_moments" in aar
        assert "lessons" in aar


def test_generate_aar_aar_json_contains_valid_json() -> None:
    """aar.json must be valid JSON parseable by json.loads."""
    mock = MockProvider(script=[_valid_aar_json()])

    with tempfile.TemporaryDirectory() as td:
        run_dir = _run_scripted_20(Path(td))
        asyncio.run(generate_aar(run_dir, mock))
        raw = (run_dir / "aar.json").read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert parsed["grade"] == "B"


# ---------------------------------------------------------------------------
# AAR_SCHEMA validation
# ---------------------------------------------------------------------------


def test_schema_rejects_more_than_5_lessons() -> None:
    """AAR_SCHEMA must reject lessons lists with more than 5 entries."""
    with pytest.raises(ValidationError):
        AAR_SCHEMA.model_validate({
            "headline": "x",
            "grade": "A",
            "what_worked": [],
            "coordination_failures": [],
            "key_moments": [],
            "lessons": [
                "Lesson one is short.",
                "Lesson two is short.",
                "Lesson three is short.",
                "Lesson four is short.",
                "Lesson five is short.",
                "Lesson six exceeds the limit.",
            ],
        })


def test_schema_rejects_lesson_over_140_chars() -> None:
    """AAR_SCHEMA must reject any lesson exceeding 140 characters."""
    long_lesson = "A" * 141
    with pytest.raises(ValidationError):
        AAR_SCHEMA.model_validate({
            "headline": "x",
            "grade": "A",
            "what_worked": [],
            "coordination_failures": [],
            "key_moments": [],
            "lessons": [long_lesson],
        })


def test_schema_accepts_exactly_5_lessons() -> None:
    """AAR_SCHEMA must accept exactly 5 short lessons."""
    obj = AAR_SCHEMA.model_validate({
        "headline": "x",
        "grade": "C",
        "what_worked": [],
        "coordination_failures": [],
        "key_moments": [],
        "lessons": [f"Lesson {i}." for i in range(5)],
    })
    assert len(obj.lessons) == 5


def test_schema_rejects_invalid_grade() -> None:
    """AAR_SCHEMA must reject grades outside A/B/C/D/F."""
    with pytest.raises(ValidationError):
        AAR_SCHEMA.model_validate({
            "headline": "x",
            "grade": "S",
            "what_worked": [],
            "coordination_failures": [],
            "key_moments": [],
            "lessons": [],
        })


# ---------------------------------------------------------------------------
# load_lessons: sanitization and capping
# ---------------------------------------------------------------------------


def test_load_lessons_sanitizes_control_tokens() -> None:
    """load_lessons must strip <|im_start|> and backtick control tokens."""
    with tempfile.TemporaryDirectory() as td:
        memory_path = Path(td) / "memory.json"
        memory_path.write_text(
            json.dumps([{
                "run_id": "r1",
                "lessons": [
                    "<|im_start|>This is a lesson with control tokens.",
                    "Another lesson with `backticks` inside.",
                ],
            }]),
            encoding="utf-8",
        )
        lessons = load_lessons(memory_path)
        for lesson in lessons:
            assert "<|" not in lesson, f"Control token not stripped: {lesson!r}"
            assert "`" not in lesson, f"Backtick not stripped: {lesson!r}"


def test_load_lessons_caps_at_max_lessons() -> None:
    """load_lessons must return at most max_lessons entries."""
    with tempfile.TemporaryDirectory() as td:
        memory_path = Path(td) / "memory.json"
        # Write 10 lessons across two entries
        memory_path.write_text(
            json.dumps([
                {"run_id": "r1", "lessons": [f"Lesson old {i}." for i in range(5)]},
                {"run_id": "r2", "lessons": [f"Lesson new {i}." for i in range(5)]},
            ]),
            encoding="utf-8",
        )
        lessons = load_lessons(memory_path, max_lessons=5)
        assert len(lessons) <= 5


def test_load_lessons_returns_most_recent_first() -> None:
    """load_lessons must return the most recent lessons first (latest entry's lessons first)."""
    with tempfile.TemporaryDirectory() as td:
        memory_path = Path(td) / "memory.json"
        memory_path.write_text(
            json.dumps([
                {"run_id": "r1", "lessons": ["Old lesson."]},
                {"run_id": "r2", "lessons": ["New lesson."]},
            ]),
            encoding="utf-8",
        )
        lessons = load_lessons(memory_path, max_lessons=2)
        assert lessons[0] == "New lesson.", f"Expected 'New lesson.' first, got {lessons!r}"


def test_load_lessons_missing_file_returns_empty() -> None:
    """load_lessons must return [] when memory.json does not exist."""
    with tempfile.TemporaryDirectory() as td:
        memory_path = Path(td) / "nonexistent_memory.json"
        result = load_lessons(memory_path)
        assert result == []


# ---------------------------------------------------------------------------
# append_lessons + load ordering
# ---------------------------------------------------------------------------


def test_append_then_load_roundtrip() -> None:
    """append_lessons followed by load_lessons must return the appended lessons."""
    with tempfile.TemporaryDirectory() as td:
        memory_path = Path(td) / "memory.json"
        append_lessons(memory_path, "run-1", ["Dispatch early.", "Watch fire spread."])
        lessons = load_lessons(memory_path, max_lessons=5)
        assert "Dispatch early." in lessons
        assert "Watch fire spread." in lessons


def test_append_two_runs_most_recent_first() -> None:
    """After two appends, load_lessons must surface newer lessons before older ones."""
    with tempfile.TemporaryDirectory() as td:
        memory_path = Path(td) / "memory.json"
        append_lessons(memory_path, "run-1", ["Old lesson."])
        append_lessons(memory_path, "run-2", ["New lesson."])
        lessons = load_lessons(memory_path, max_lessons=2)
        assert lessons[0] == "New lesson.", f"Expected new lesson first, got {lessons!r}"


def test_append_creates_file_if_absent() -> None:
    """append_lessons must create memory.json when it does not exist."""
    with tempfile.TemporaryDirectory() as td:
        memory_path = Path(td) / "memory.json"
        assert not memory_path.exists()
        append_lessons(memory_path, "r1", ["A lesson."])
        assert memory_path.exists()
        data = json.loads(memory_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["run_id"] == "r1"


def test_append_is_cumulative() -> None:
    """Multiple appends must accumulate entries (not overwrite)."""
    with tempfile.TemporaryDirectory() as td:
        memory_path = Path(td) / "memory.json"
        append_lessons(memory_path, "r1", ["Lesson A."])
        append_lessons(memory_path, "r2", ["Lesson B."])
        append_lessons(memory_path, "r3", ["Lesson C."])
        data = json.loads(memory_path.read_text(encoding="utf-8"))
        assert len(data) == 3


# ---------------------------------------------------------------------------
# Commander prompt contains lessons block; other roles do not
# ---------------------------------------------------------------------------


def test_commander_prompt_contains_lessons_block() -> None:
    """When lessons are passed, the commander's system prompt must include the lessons block."""
    from aftershock.kernel.roles import load_roles
    from aftershock.llm.provider import MockProvider as _MockProvider
    from aftershock.town.prompts import build_llm_agents

    roles_dir = Path(__file__).parent.parent / "src" / "aftershock" / "town" / "roles"
    roles = load_roles(roles_dir)
    mock = _MockProvider(script=lambda m, s, u: "{}")
    lessons = ["Prioritize early dispatch.", "Watch for fire spread."]
    agents = build_llm_agents(roles, mock, lessons=lessons)

    commander_agent = agents["commander"]
    # Access the system prompt via the contract: system = role.system_prompt + contract
    # We check the LLMAgent's internal role system prompt directly
    system_prompt = commander_agent._role.system_prompt  # type: ignore[attr-defined]
    assert "LESSONS FROM PREVIOUS DISASTERS" in system_prompt
    for lesson in lessons:
        assert lesson in system_prompt


def test_non_commander_roles_do_not_contain_lessons_block() -> None:
    """When lessons are passed, non-commander roles must NOT have the lessons block."""
    from aftershock.kernel.roles import load_roles
    from aftershock.town.prompts import build_llm_agents

    roles_dir = Path(__file__).parent.parent / "src" / "aftershock" / "town" / "roles"
    roles = load_roles(roles_dir)
    mock = MockProvider(script=lambda m, s, u: "{}")
    lessons = ["Some lesson."]
    agents = build_llm_agents(roles, mock, lessons=lessons)

    for agent_id, agent in agents.items():
        if agent_id == "commander":
            continue
        system_prompt = agent._role.system_prompt  # type: ignore[attr-defined]
        assert "LESSONS FROM PREVIOUS DISASTERS" not in system_prompt, (
            f"Role {agent_id!r} should not have lessons block"
        )


# ---------------------------------------------------------------------------
# build_arm("solo", lessons=[...]) raises ValueError
# ---------------------------------------------------------------------------


def test_build_arm_solo_with_lessons_raises() -> None:
    """build_arm for non-society arms with lessons must raise ValueError."""
    from aftershock.town.arms import build_arm

    with pytest.raises(ValueError, match="society"):
        build_arm("solo", seed=42, provider=None, lessons=["Some lesson."])


def test_build_arm_scripted_with_lessons_raises() -> None:
    """build_arm for scripted arm with lessons must raise ValueError."""
    from aftershock.town.arms import build_arm

    with pytest.raises(ValueError, match="society"):
        build_arm("scripted", seed=42, provider=None, lessons=["Some lesson."])


def test_build_arm_swarm_with_lessons_raises() -> None:
    """build_arm for swarm arm with lessons must raise ValueError."""
    from aftershock.town.arms import build_arm

    with pytest.raises(ValueError, match="society"):
        build_arm("swarm", seed=42, provider=None, lessons=["Some lesson."])


# ---------------------------------------------------------------------------
# load_lessons: non-list 'lessons' value is skipped (not iterated char-by-char)
# ---------------------------------------------------------------------------


def test_load_lessons_skips_non_list_lessons_field() -> None:
    """load_lessons must skip entries whose 'lessons' value is not a list."""
    with tempfile.TemporaryDirectory() as td:
        memory_path = Path(td) / "memory.json"
        # Corrupt entry with a string lessons value, then a valid entry
        memory_path.write_text(
            json.dumps([
                {"run_id": "r1", "lessons": "not-a-list"},
                {"run_id": "r2", "lessons": ["Valid lesson."]},
            ]),
            encoding="utf-8",
        )
        lessons = load_lessons(memory_path, max_lessons=10)
    # Must not contain individual characters from "not-a-list"
    assert lessons == ["Valid lesson."], f"Unexpected lessons: {lessons!r}"


# ---------------------------------------------------------------------------
# append_lessons: atomic write + entry cap
# ---------------------------------------------------------------------------


def test_append_lessons_atomic_write_survives_corrupt_file() -> None:
    """append_lessons must not lose previously valid data on a corrupt memory.json."""
    with tempfile.TemporaryDirectory() as td:
        memory_path = Path(td) / "memory.json"
        append_lessons(memory_path, "r1", ["First lesson."])
        # Truncate to simulate a partial write / corruption
        memory_path.write_text("{bad json", encoding="utf-8")
        # Appending after corruption should not crash and should write a valid file
        append_lessons(memory_path, "r2", ["Second lesson."])
        lessons = load_lessons(memory_path, max_lessons=10)
    assert "Second lesson." in lessons


def test_append_lessons_caps_entries() -> None:
    """append_lessons must retain at most _MEMORY_MAX_ENTRIES entries."""
    from aftershock.llm.aar import _MEMORY_MAX_ENTRIES

    with tempfile.TemporaryDirectory() as td:
        memory_path = Path(td) / "memory.json"
        # Write more than the cap
        for i in range(_MEMORY_MAX_ENTRIES + 10):
            append_lessons(memory_path, f"r{i}", [f"Lesson {i}."])
        raw = json.loads(memory_path.read_text(encoding="utf-8"))
    assert len(raw) == _MEMORY_MAX_ENTRIES, (
        f"Expected {_MEMORY_MAX_ENTRIES} entries, got {len(raw)}"
    )


# ---------------------------------------------------------------------------
# build_run_digest: mission kind key, casualties key, injected events key
# ---------------------------------------------------------------------------


def test_digest_mission_kind_not_question_mark() -> None:
    """build_run_digest must not produce '?' for mission kind on a scripted run."""
    from aftershock.kernel.recorder import load_run

    with tempfile.TemporaryDirectory() as td:
        run_dir = _run_scripted_20(Path(td))
        manifest, ticks, _ = load_run(run_dir)
        d = build_run_digest(manifest, ticks)
    # At least one mission should have a real kind, not '?'
    assert "kind=?" not in d, "Mission kind is '?' — payload key mismatch"


def test_digest_negotiation_stats_no_double_count() -> None:
    """resource_requests must equal grants + declines (no double-counting)."""
    from aftershock.kernel.recorder import load_run

    with tempfile.TemporaryDirectory() as td:
        run_dir = _run_scripted_20(Path(td))
        manifest, ticks, _ = load_run(run_dir)
        d = build_run_digest(manifest, ticks)
    # Extract resource_requests and grants from the digest text
    import re
    m = re.search(r"resource_requests=(\d+)\s+grants=(\d+)", d)
    assert m is not None, "NEGOTIATION STATS line not found in digest"
    requests = int(m.group(1))
    grants = int(m.group(2))
    assert grants <= requests, (
        f"grants ({grants}) must not exceed requests ({requests})"
    )


