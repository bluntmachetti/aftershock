"""Cross-experiment index <-> FIELD-NOTES parity, and reindex honesty.

The link from a stamped index row to a FIELD-NOTES finding must be DIRECTIONAL:
every NEW stamped row that *cites* a section must reference a REAL section number.
We do NOT require every section to own a run dir — §13/§14 are methodology-only and
§22 is an uncommitted local-k12 sweep, so those legitimately have no committed
experiment dir. Pre-stamp historical dirs are skip-listed (they predate the stamp).

Also asserts the honesty contract the reindex must preserve:
  * the two pre-hardening ablations stay verdict=null (never coerced);
  * verdict is always the literal enum or null;
  * cloud (dashscope-intl) and local (ollama-k12) endpoints are never merged;
  * a referenced row whose records are uncommitted is flagged, not dropped.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIELD_NOTES = _REPO_ROOT / "docs" / "FIELD-NOTES.md"
_INDEX_PATH = _REPO_ROOT / "bench" / "results" / "index.json"
_REINDEX_SCRIPT = _REPO_ROOT / "scripts" / "reindex_experiments.py"

# FIELD-NOTES section header grammar: "## N. Title (date)". Parse "## N." only.
_SECTION_RE = re.compile(r"^## (\d+)\.", re.MULTILINE)

# The literal, hardened verdict enum (plus null). Nothing else is allowed.
_VALID_VERDICTS = {"noise", "suggestive", "credible", None}

# Dirs that predate the provenance stamp (schema_version is None) — skipped by the
# directionality assertion that targets NEW stamped rows.
_PRE_STAMP_DIRS = {
    "2026-06-11",
    "2026-06-13-tool-ablation",
    "2026-06-14-tier0-verification",
    "2026-06-15-d2-tight",
    "2026-06-15-harsh-ablation",
    "2026-06-15-plus28-recheck",
    "2026-06-16-cost-contract-trim",
    "2026-06-16-doctrine-ablation",
    "2026-06-16-s1-infra-fix",
    "2026-06-16-s1-infra-model",
}

# The two pre-hardening ablations that MUST stay verdict=null.
_PRE_HARDENING_ABLATIONS = {
    "2026-06-15-harsh-ablation",
    "2026-06-15-plus28-recheck",
}

_VALID_ENDPOINTS = {"dashscope-intl", "ollama-k12", "scripted", "none", "unknown"}


def _load_reindex_module():
    """Import scripts/reindex_experiments.py as a module (it is not a package)."""
    spec = importlib.util.spec_from_file_location("reindex_experiments", _REINDEX_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _field_notes_sections() -> set[int]:
    text = _FIELD_NOTES.read_text(encoding="utf-8")
    return {int(m.group(1)) for m in _SECTION_RE.finditer(text)}


def _index_rows() -> list[dict]:
    if not _INDEX_PATH.is_file():
        pytest.skip("bench/results/index.json not present (run scripts/reindex_experiments.py)")
    data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    rows = data.get("experiments")
    assert isinstance(rows, list)
    return rows


# ---------------------------------------------------------------------------
# FIELD-NOTES parsing
# ---------------------------------------------------------------------------


def test_field_notes_has_expected_section_count() -> None:
    """The header regex must find the ~22 numbered sections (sanity on the parser)."""
    sections = _field_notes_sections()
    assert len(sections) >= 20, f"expected ~22 sections, parsed {len(sections)}: {sorted(sections)}"
    # Sections are 1..N contiguous.
    assert min(sections) == 1
    assert sorted(sections) == list(range(1, max(sections) + 1))


def test_section_regex_parses_dot_form_not_section_sign() -> None:
    """Critic fix #3: parse '## N.' headers, not inline '§N' references."""
    # A line like "see §16" must NOT be picked up as a section header.
    sample = "## 16. A real header (2026-06-15)\nbody mentions §16 and §99 inline\n"
    found = {int(m.group(1)) for m in _SECTION_RE.finditer(sample)}
    assert found == {16}


# ---------------------------------------------------------------------------
# Directional parity: every cited section is real (methodology-only OK)
# ---------------------------------------------------------------------------


def test_index_citations_are_directional() -> None:
    """Every row that cites a section references a REAL FIELD-NOTES section.

    Directional only: a section without a run dir (methodology-only §13/§14, local
    §22) is fine — we never assert the reverse.
    """
    sections = _field_notes_sections()
    for row in _index_rows():
        sec = row.get("field_notes_section")
        if sec is None:
            continue  # a row may legitimately cite no section
        assert sec in sections, (
            f"index row {row.get('dir')!r} cites FIELD-NOTES §{sec}, "
            f"which is not a real section (real: {sorted(sections)})"
        )


def test_new_stamped_rows_cite_real_sections() -> None:
    """Critic fix #3 (directional): NEW stamped rows must cite a real section.

    A 'new stamped' row is one carrying a provenance schema_version and not in the
    pre-stamp skip-list. Today there are none (all committed dirs predate the stamp),
    so this guards future rows without false-failing on methodology-only findings.
    """
    sections = _field_notes_sections()
    for row in _index_rows():
        if row.get("dir") in _PRE_STAMP_DIRS:
            continue
        if row.get("schema_version") is None:
            continue  # not a stamped row
        sec = row.get("field_notes_section")
        if sec is None:
            continue  # stamped rows may still cite no section
        assert sec in sections, (
            f"new stamped row {row.get('dir')!r} cites §{sec}, not a real section"
        )


# ---------------------------------------------------------------------------
# Honesty contract
# ---------------------------------------------------------------------------


def test_verdict_is_literal_enum_or_null() -> None:
    """Verdict is always one of the literal enum values or null — never coerced."""
    for row in _index_rows():
        assert row.get("verdict") in _VALID_VERDICTS, (
            f"row {row.get('dir')!r} has illegal verdict {row.get('verdict')!r}"
        )


def test_pre_hardening_ablations_stay_null() -> None:
    """The two pre-hardening ablations MUST keep verdict=null with the note."""
    rows = {r["dir"]: r for r in _index_rows()}
    for name in _PRE_HARDENING_ABLATIONS:
        assert name in rows, f"expected {name!r} in the index"
        row = rows[name]
        assert row["verdict"] is None, (
            f"{name!r} verdict was coerced to {row['verdict']!r}; must stay null"
        )
        assert row.get("verdict_note") == "pre-2026-06-16-hardening", (
            f"{name!r} must carry the pre-hardening note, got {row.get('verdict_note')!r}"
        )


def test_endpoints_are_valid_and_separable() -> None:
    """Every row has a known model_endpoint, so cloud and local never merge."""
    for row in _index_rows():
        ep = row.get("model_endpoint")
        assert ep in _VALID_ENDPOINTS, f"row {row.get('dir')!r} has endpoint {ep!r}"


def test_conformance_and_lives_are_separate_fields() -> None:
    """Conformance (mean_team_alignment) and lives are distinct keys, never collapsed."""
    for row in _index_rows():
        assert "mean_team_alignment" in row
        assert "lives_saved" in row
        # When both exist they are not silently the same number by construction.
        ta = row.get("mean_team_alignment")
        lives = row.get("lives_saved")
        if ta is not None and lives is not None:
            assert not (ta == lives and ta > 1.0), "conformance and lives look collapsed"


def test_records_committed_is_bool_and_flags_uncommitted() -> None:
    """records_committed is a bool; pre-stamp summary-only dirs read False."""
    rows = {r["dir"]: r for r in _index_rows()}
    for row in rows.values():
        assert isinstance(row.get("records_committed"), bool)
    # A dir whose tick records are not committed must be flagged False, not dropped.
    assert rows["2026-06-11"]["records_committed"] is False
    # A dir whose cells are committed reads True.
    assert rows["2026-06-16-doctrine-ablation"]["records_committed"] is True


# ---------------------------------------------------------------------------
# Reindex defensiveness (older files lack keys; uncommitted dirs)
# ---------------------------------------------------------------------------


def test_reindex_is_deterministic_and_complete() -> None:
    """Re-running build_index reproduces the committed index rows (read-only walk)."""
    mod = _load_reindex_module()
    fresh = mod.build_index()
    committed = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    # The committed sha may differ (working tree vs HEAD); compare the experiment rows.
    assert fresh["n_experiments"] == committed["n_experiments"]
    fresh_dirs = {r["dir"] for r in fresh["experiments"]}
    committed_dirs = {r["dir"] for r in committed["experiments"]}
    assert fresh_dirs == committed_dirs


def test_reindex_handles_missing_keys_without_crashing(tmp_path: Path) -> None:
    """An older result JSON missing verdict/ablate/etc. yields a row, never a crash."""
    mod = _load_reindex_module()
    exp = tmp_path / "2099-01-01-legacy"
    exp.mkdir()
    # Minimal pre-stamp results.json: no provenance, no verdict, no team_alignment.
    (exp / "results.json").write_text(
        json.dumps({"arms": {"scripted": {"mean_lives_saved": 5.0}}, "paired": {}}),
        encoding="utf-8",
    )
    row = mod.build_row(exp)
    assert row["dir"] == "2099-01-01-legacy"
    assert row["kind"] == "results"
    assert row["verdict"] is None
    assert row["schema_version"] is None
    # No LLM cost -> scripted endpoint inferred (never crashes, never guesses cloud).
    assert row["model_endpoint"] == "scripted"


def test_reindex_tolerates_uncommitted_local_dir(tmp_path: Path) -> None:
    """Critic fix #4: a dir whose records are not committed -> records_committed False."""
    mod = _load_reindex_module()
    exp = tmp_path / "run-9b"  # echoes the FIELD-NOTES §22 local-k12 dirs
    exp.mkdir()
    (exp / "results.json").write_text(
        json.dumps({"arms": {"society": {"mean_lives_saved": 1.0, "mean_cost_usd": 0.0}}}),
        encoding="utf-8",
    )
    row = mod.build_row(exp)
    # No ticks.ndjson present -> flagged uncommitted, not dropped/crashed.
    assert row["records_committed"] is False
    assert row["dir"] == "run-9b"
