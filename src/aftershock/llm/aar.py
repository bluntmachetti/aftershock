"""After-action report engine and memory loop.

AAR_MODEL          — the flagship model used for analysis.
build_run_digest   — deterministic, bounded text summary of a run.
generate_aar       — load run, generate report, write aar.json.
load_lessons       — read most-recent lessons from memory.json, sanitized.
append_lessons     — append a run's lessons to memory.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from aftershock.kernel.protocol import TickRecord
from aftershock.kernel.recorder import canonical_json, load_run
from aftershock.llm.digest import sanitize
from aftershock.llm.provider import Provider

AAR_MODEL = "qwen3-max"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

GRADE_VALUES = ("A", "B", "C", "D", "F")


class KeyMoment(BaseModel):
    tick: int
    description: str


class AAR_SCHEMA(BaseModel):
    """Pydantic model for the LLM-generated after-action report."""

    headline: str
    grade: str
    what_worked: list[str] = Field(default_factory=list)
    coordination_failures: list[str] = Field(default_factory=list)
    key_moments: list[KeyMoment] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list, max_length=5)
    doctrine_notes: list[str] = Field(default_factory=list)

    @field_validator("grade")
    @classmethod
    def _valid_grade(cls, v: str) -> str:
        if v not in GRADE_VALUES:
            raise ValueError(f"grade must be one of {GRADE_VALUES}, got {v!r}")
        return v

    @field_validator("lessons")
    @classmethod
    def _validate_lessons(cls, v: list[str]) -> list[str]:
        if len(v) > 5:
            raise ValueError(f"lessons must have at most 5 entries, got {len(v)}")
        for i, lesson in enumerate(v):
            if len(lesson) > 140:
                raise ValueError(
                    f"lessons[{i}] exceeds 140 chars (len={len(lesson)}): {lesson[:60]!r}..."
                )
        return v

    @field_validator("doctrine_notes")
    @classmethod
    def _validate_doctrine_notes(cls, v: list[str]) -> list[str]:
        return v[:3]


# ---------------------------------------------------------------------------
# Digest builder
# ---------------------------------------------------------------------------


def build_run_digest(manifest: dict[str, Any], ticks: list[TickRecord]) -> str:
    """Build a deterministic, bounded text summary of a run for the AAR prompt.

    Sections:
    1. Run metadata (seed, arm, ticks run)
    2. Final scores
    3. Per-mission outcomes
    4. Negotiation stats
    5. Per-agent rejection patterns
    6. Injected events
    """
    lines: list[str] = []

    # --- Section 1: Run metadata ---
    lines.append("=== RUN METADATA ===")
    lines.append(f"seed={manifest.get('seed', '?')}  arm={manifest.get('arm', '?')}")
    lines.append(f"ticks_run={len(ticks)}")
    lines.append("")

    # --- Section 2: Final scores ---
    lines.append("=== FINAL SCORES ===")
    if ticks:
        scores = ticks[-1].scores
        for key in sorted(scores):
            val = scores[key]
            if isinstance(val, float):
                lines.append(f"  {key}: {val:.3f}")
            else:
                lines.append(f"  {key}: {val}")
    lines.append("")

    # --- Section 3: Per-mission outcomes ---
    # Track missions through events
    mission_data: dict[str, dict[str, Any]] = {}
    for record in ticks:
        for evt in record.events:
            kind = evt.kind
            payload = evt.payload
            mid = payload.get("mission_id") or payload.get("id")
            if not mid:
                continue
            if mid not in mission_data:
                mission_data[mid] = {
                    "kind": payload.get("mission_kind", payload.get("kind", "?")),
                    "district": payload.get("district_id", "?"),
                    "severity": payload.get("severity", "?"),
                    "spawned_tick": None,
                    "resolved_tick": None,
                    "failed_tick": None,
                    "lives_saved": 0,
                    "lives_lost": 0,
                }
            if kind == "mission_spawned":
                mission_data[mid]["spawned_tick"] = record.tick
                # events.py uses "mission_kind"; fall back to "kind" for other sources
                mission_data[mid]["kind"] = payload.get(
                    "mission_kind", payload.get("kind", mission_data[mid]["kind"])
                )
                mission_data[mid]["district"] = payload.get(
                    "district_id", mission_data[mid]["district"]
                )
                mission_data[mid]["severity"] = payload.get(
                    "severity", mission_data[mid]["severity"]
                )
            elif kind == "mission_resolved":
                mission_data[mid]["resolved_tick"] = record.tick
                # events.py emits lives_saved on mission_resolved; recordings made
                # before 2026-06-11 lack the key and fall back to 0.
                mission_data[mid]["lives_saved"] += payload.get("lives_saved", 0)
            elif kind == "mission_failed":
                mission_data[mid]["failed_tick"] = record.tick
                mission_data[mid]["lives_lost"] += payload.get("lives_lost", 0)
            elif kind == "casualties":
                # events.py uses "count", not "lives_lost"
                mission_data[mid]["lives_lost"] += payload.get("count", 0)

    lines.append("=== MISSION OUTCOMES ===")
    for mid in sorted(mission_data):
        m = mission_data[mid]
        outcome = (
            f"resolved@t{m['resolved_tick']}"
            if m["resolved_tick"] is not None
            else f"failed@t{m['failed_tick']}"
            if m["failed_tick"] is not None
            else "open"
        )
        lines.append(
            f"  {mid}: {m['kind']} {m['district']} sev={m['severity']}"
            f" spawned@t{m['spawned_tick']} {outcome}"
            f" saved={m['lives_saved']} lost={m['lives_lost']}"
        )
    lines.append("")

    # --- Section 4: Negotiation stats ---
    # Count only auction rulings (decided_by == 'kernel:auction') for resource stats.
    # Grants = accepted auction rulings. Requests = all auction rulings (accepted + declined).
    total_requests = 0
    total_grants = 0
    pool_exhausted: dict[str, int] = {}  # resource -> count of exhausted declines

    for record in ticks:
        for ruling in record.rulings:
            if ruling.decided_by != "kernel:auction":
                continue
            total_requests += 1
            if ruling.accepted:
                total_grants += 1
            elif "pool exhausted" in ruling.reason.lower():
                reason = ruling.reason
                resource = reason.split(":")[1].strip().split()[0] if ":" in reason else "?"
                pool_exhausted[resource] = pool_exhausted.get(resource, 0) + 1

    lines.append("=== NEGOTIATION STATS ===")
    lines.append(f"  resource_requests={total_requests}  grants={total_grants}")
    if pool_exhausted:
        exhausted_parts = [f"{r}:{n}" for r, n in sorted(pool_exhausted.items())]
        lines.append(f"  pool_exhausted: {', '.join(exhausted_parts)}")
    lines.append("")

    # --- Section 5: Per-agent rejection patterns ---
    agent_rejections: dict[str, dict[str, int]] = {}  # agent -> decision_type -> count
    for record in ticks:
        for rej in record.rejected:
            aid = rej.agent_id
            dtype = rej.decision_type
            if aid not in agent_rejections:
                agent_rejections[aid] = {}
            agent_rejections[aid][dtype] = agent_rejections[aid].get(dtype, 0) + 1

    lines.append("=== REJECTION PATTERNS ===")
    if agent_rejections:
        for aid in sorted(agent_rejections):
            parts = [f"{dtype}:{cnt}" for dtype, cnt in sorted(agent_rejections[aid].items())]
            lines.append(f"  {aid}: {', '.join(parts)}")
    else:
        lines.append("  (none)")
    lines.append("")

    # --- Section 6: Injected events ---
    # events.py tags injected spawns with payload key "injected": True (not "provenance")
    injected = []
    for record in ticks:
        for evt in record.events:
            if evt.payload.get("injected") is True:
                injected.append(f"t{record.tick}:{evt.kind}")

    lines.append("=== INJECTED EVENTS ===")
    if injected:
        # Cap at 20 to bound size
        display = injected[:20]
        lines.append("  " + ", ".join(display))
        if len(injected) > 20:
            lines.append(f"  (+{len(injected) - 20} more)")
    else:
        lines.append("  (none)")

    result = "\n".join(lines)
    # Bound to < ~4500 chars (raised from 3500 to accommodate doctrine section)
    if len(result) > 4500:
        result = result[:4500]
    return result


def _build_doctrine_section(run_dir: Path) -> str:
    """Build the =====DOCTRINE===== digest section from conformance.json if present.

    Returns an empty string when conformance.json is absent.

    Section content:
    - Team alignment rate
    - Per-rule violation counts with rule text (from doctrine.yaml)
    - Top 5 concrete violations (tick + detail)
    """
    conf_path = run_dir / "conformance.json"
    if not conf_path.exists():
        return ""

    try:
        report = json.loads(conf_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""

    from aftershock.town.doctrine import load_doctrine

    try:
        rules = load_doctrine()
        rule_text_map = {r.id: r.text for r in rules}
    except Exception:  # noqa: BLE001
        rule_text_map = {}

    lines: list[str] = []
    lines.append("=== DOCTRINE ===")

    ta = report.get("team_alignment", 1.0)
    lines.append(f"  team_alignment={ta:.3f}")
    lines.append("")

    # Per-rule violation counts with rule text
    rules_report = report.get("rules", {})
    rule_summary_lines: list[str] = []
    for rule_id in sorted(rules_report.keys()):
        agent_data = rules_report[rule_id]
        total_violations = sum(len(d.get("violations", [])) for d in agent_data.values())
        if total_violations == 0:
            continue
        rule_text = rule_text_map.get(rule_id, "")
        short_text = rule_text[:80] + "..." if len(rule_text) > 80 else rule_text
        rule_summary_lines.append(
            f"  {rule_id}: {total_violations} violation(s) — {short_text}"
        )

    if rule_summary_lines:
        lines.append("Rule violations:")
        lines.extend(rule_summary_lines)
        lines.append("")

    # Top 5 concrete violations across all rules/agents
    all_violations: list[tuple[int, str, str, str]] = []  # (tick, rule_id, agent_id, detail)
    for rule_id, agent_data in rules_report.items():
        for agent_id, data in agent_data.items():
            for v in data.get("violations", []):
                all_violations.append((v["tick"], rule_id, agent_id, v["detail"]))

    all_violations.sort(key=lambda x: x[0])
    top5 = all_violations[:5]

    if top5:
        lines.append("Top violations:")
        for tick, rule_id, agent_id, detail in top5:
            lines.append(f"  t={tick} [{rule_id}] {agent_id}: {detail[:100]}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# generate_aar
# ---------------------------------------------------------------------------

_AAR_SYSTEM = (
    "You are an expert incident commander writing an after-action report for a "
    "disaster-response simulation. Analyze the run data provided and output ONLY a "
    "JSON object matching the exact schema. "
    "grade: one of A/B/C/D/F. "
    "lessons: at most 5 short imperative sentences, each at most 140 characters. "
    "Output ONLY valid JSON."
)

_AAR_USER_TEMPLATE = (
    "Write an after-action report for the following disaster-response simulation run.\n\n"
    "{digest}\n\n"
    'Output a JSON object with these fields: "headline" (str), "grade" (A/B/C/D/F), '
    '"what_worked" (list[str]), "coordination_failures" (list[str]), '
    '"key_moments" (list of {{tick: int, description: str}}), '
    '"lessons" (list of at most 5 imperative strings, each at most 140 chars), '
    '"doctrine_notes" (optional list of at most 3 strings referencing doctrine rule ids '
    'from the DOCTRINE section, e.g. "T5 violated 3 times — agents repeated rejected decisions"). '
    "Output ONLY valid JSON."
)


async def generate_aar(
    run_dir: Path,
    provider: Provider,
    model: str = AAR_MODEL,
) -> dict[str, Any]:
    """Generate an after-action report for a completed run.

    Steps:
    1. Run check_run to produce/update conformance.json.
    2. Load the run (manifest + tick records).
    3. Build the run digest (includes DOCTRINE section when conformance.json exists).
    4. Call the LLM with the digest.
    5. Validate against AAR_SCHEMA.
    6. Write aar.json with usage/cost included.
    7. Return the report dict.
    """
    # Step 1: run conformance check first so the doctrine section is available
    import contextlib

    from aftershock.town.conformance import check_run as _check_run

    with contextlib.suppress(Exception):
        _check_run(run_dir)

    manifest, ticks, _worlds = load_run(run_dir)
    base_digest = build_run_digest(manifest, ticks)
    doctrine_section = _build_doctrine_section(run_dir)
    digest_text = base_digest + "\n\n" + doctrine_section if doctrine_section else base_digest

    user = _AAR_USER_TEMPLATE.format(digest=digest_text)
    result = await provider.chat(
        model=model,
        system=_AAR_SYSTEM,
        user=user,
        temperature=0.3,
        json_mode=True,
    )

    # Parse and validate
    raw = json.loads(result.text)
    report_obj = AAR_SCHEMA.model_validate(raw)
    report_dict = report_obj.model_dump()

    # Attach usage/cost
    report_dict["usage"] = {
        "prompt_tokens": result.usage.prompt_tokens,
        "completion_tokens": result.usage.completion_tokens,
        "cost_usd": result.usage.cost_usd,
        "model": result.usage.model,
    }

    # Write canonical JSON
    aar_path = run_dir / "aar.json"
    aar_path.write_text(canonical_json(report_dict), encoding="utf-8")

    return report_dict


# ---------------------------------------------------------------------------
# Memory: load_lessons / append_lessons
# ---------------------------------------------------------------------------


def load_lessons(memory_path: Path, max_lessons: int = 5) -> list[str]:
    """Load the most recent lessons from memory.json, sanitized.

    memory.json format: list of {"run_id": str, "lessons": list[str]}
    Returns the most-recent max_lessons individual lessons (most recent first),
    each passed through sanitize().
    """
    if not memory_path.exists():
        return []

    try:
        entries: list[dict[str, Any]] = json.loads(
            memory_path.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, ValueError):
        return []

    if not isinstance(entries, list):
        return []

    # Collect lessons from newest to oldest (entries are in append order)
    collected: list[str] = []
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            continue
        raw_lessons = entry.get("lessons", [])
        if not isinstance(raw_lessons, list):
            continue
        for lesson in raw_lessons:
            if not isinstance(lesson, str):
                continue
            sanitized = sanitize(lesson, cap=140)
            if sanitized:
                collected.append(sanitized)
            if len(collected) >= max_lessons:
                break
        if len(collected) >= max_lessons:
            break

    return collected


_MEMORY_MAX_ENTRIES = 100


def append_lessons(memory_path: Path, run_id: str, lessons: list[str]) -> None:
    """Append a run's lessons to memory.json (append-only).

    memory.json is a JSON array of {"run_id": str, "lessons": list[str]}.
    Creates the file if it does not exist.
    Writes atomically via a sibling .tmp file to avoid data loss on crash.
    Caps stored entries at _MEMORY_MAX_ENTRIES (keeps most recent).
    """
    if memory_path.exists():
        try:
            entries: list[dict[str, Any]] = json.loads(
                memory_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, ValueError):
            entries = []
    else:
        entries = []

    if not isinstance(entries, list):
        entries = []

    entries.append({"run_id": run_id, "lessons": lessons})

    # Cap to most-recent entries to bound on-disk growth
    if len(entries) > _MEMORY_MAX_ENTRIES:
        entries = entries[-_MEMORY_MAX_ENTRIES:]

    serialized = json.dumps(entries, indent=2, sort_keys=True, ensure_ascii=True)

    # Atomic write: write to .tmp then os.replace to avoid partial-write corruption
    tmp_path = memory_path.with_suffix(".json.tmp")
    tmp_path.write_text(serialized, encoding="utf-8")
    os.replace(tmp_path, memory_path)
