"""Tests for the benchmark harness (bench.py).

Coverage:
- aggregate: hand-computed mean/sd on a small fixture, including a zero-cost arm
  that omits lives_per_dollar.
- render_markdown: expected rows and columns present.
- resume: pre-write a summary.json; assert that cell is skipped (build_arm not called).
- manifest load + flag-style overrides.
- end-to-end: one real cell with arm=scripted, seed=42, ticks=8 producing
  summary.json with correct keys and scores.
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any

import pytest

from aftershock.bench import aggregate, render_markdown, run_bench

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cell(
    arm: str,
    seed: int,
    lives_saved: float,
    lives_lost: float,
    missions_resolved: float,
    missions_failed: float,
    cost_usd: float,
    wall_s: float,
) -> dict[str, Any]:
    return {
        "arm": arm,
        "seed": seed,
        "ticks_run": 8,
        "scores": {
            "lives_saved": lives_saved,
            "lives_lost": lives_lost,
            "missions_resolved": missions_resolved,
            "missions_failed": missions_failed,
            "panic": 0.0,
            "resource_utilization": 0.0,
            "avg_response_ticks": 0.0,
        },
        "cost": {"cost_usd": cost_usd, "prompt_tokens": 0, "completion_tokens": 0,
                 "by_agent": {}, "by_model": {}},
        "wall_s": wall_s,
        "models": [],
    }


# ---------------------------------------------------------------------------
# aggregate tests
# ---------------------------------------------------------------------------


def test_aggregate_mean_and_sd() -> None:
    """Hand-verify mean and sample-sd for a two-cell arm."""
    # arm "a" with two seeds: lives_saved=[10, 20] -> mean=15, sd=sqrt(50)=7.071...
    cells = [
        _make_cell("a", 1, lives_saved=10.0, lives_lost=2.0,
                   missions_resolved=3.0, missions_failed=1.0,
                   cost_usd=0.05, wall_s=1.0),
        _make_cell("a", 2, lives_saved=20.0, lives_lost=4.0,
                   missions_resolved=5.0, missions_failed=0.0,
                   cost_usd=0.15, wall_s=2.0),
    ]
    agg = aggregate(cells)
    arm = agg["arms"]["a"]

    assert arm["n"] == 2
    assert math.isclose(arm["mean_lives_saved"], 15.0, rel_tol=1e-9)
    expected_sd = math.sqrt(((10 - 15) ** 2 + (20 - 15) ** 2) / 1)  # sample sd ddof=1
    assert math.isclose(arm["sd_lives_saved"], expected_sd, rel_tol=1e-9)

    # mean_cost = (0.05 + 0.15) / 2 = 0.10; lives_per_dollar = 15.0 / 0.10 = 150.0
    assert math.isclose(arm["mean_cost_usd"], 0.10, rel_tol=1e-9)
    assert "lives_per_dollar" in arm
    assert math.isclose(arm["lives_per_dollar"], 150.0, rel_tol=1e-6)

    # wall_s mean = 1.5
    assert math.isclose(arm["mean_wall_s"], 1.5, rel_tol=1e-9)


def test_aggregate_zero_cost_omits_lives_per_dollar() -> None:
    """Zero-cost arms (scripted) must not include lives_per_dollar."""
    cells = [
        _make_cell("scripted", 1, lives_saved=5.0, lives_lost=1.0,
                   missions_resolved=2.0, missions_failed=0.0,
                   cost_usd=0.0, wall_s=0.5),
        _make_cell("scripted", 2, lives_saved=7.0, lives_lost=2.0,
                   missions_resolved=3.0, missions_failed=1.0,
                   cost_usd=0.0, wall_s=0.6),
    ]
    agg = aggregate(cells)
    arm = agg["arms"]["scripted"]

    assert arm["mean_cost_usd"] == 0.0
    assert "lives_per_dollar" not in arm


def test_aggregate_sd_single_cell_is_zero() -> None:
    """Single-cell arm: sample sd is 0.0 (n < 2 guard)."""
    cells = [
        _make_cell("b", 1, lives_saved=8.0, lives_lost=1.0,
                   missions_resolved=2.0, missions_failed=0.0,
                   cost_usd=0.02, wall_s=1.0),
    ]
    agg = aggregate(cells)
    arm = agg["arms"]["b"]
    assert arm["sd_lives_saved"] == 0.0


def test_aggregate_paired_table() -> None:
    """Paired table contains arm x seed -> lives_saved."""
    cells = [
        _make_cell("x", 10, lives_saved=3.0, lives_lost=0.0,
                   missions_resolved=1.0, missions_failed=0.0,
                   cost_usd=0.0, wall_s=1.0),
        _make_cell("x", 20, lives_saved=9.0, lives_lost=1.0,
                   missions_resolved=2.0, missions_failed=0.0,
                   cost_usd=0.0, wall_s=1.0),
        _make_cell("y", 10, lives_saved=12.0, lives_lost=0.0,
                   missions_resolved=3.0, missions_failed=0.0,
                   cost_usd=0.01, wall_s=2.0),
    ]
    agg = aggregate(cells)
    paired = agg["paired"]
    assert paired["x"][10] == 3.0
    assert paired["x"][20] == 9.0
    assert paired["y"][10] == 12.0


# ---------------------------------------------------------------------------
# render_markdown tests
# ---------------------------------------------------------------------------


def test_render_markdown_headline_columns() -> None:
    """Headline table contains all required column headers."""
    cells = [
        _make_cell("society", 1, 10.0, 2.0, 3.0, 1.0, 0.10, 5.0),
        _make_cell("scripted", 1, 8.0, 3.0, 2.0, 2.0, 0.0, 1.0),
    ]
    agg = aggregate(cells)
    md = render_markdown(agg)

    for col in [
        "arm", "n", "mean_lives_saved", "mean_lives_lost",
        "mean_missions_resolved", "mean_missions_failed",
        "mean_cost_usd", "mean_wall_s", "lives_per_dollar",
    ]:
        assert col in md, f"column {col!r} missing from markdown"


def test_render_markdown_society_row_first() -> None:
    """society arm appears before other arms in the headline table."""
    cells = [
        _make_cell("society", 1, 10.0, 2.0, 3.0, 1.0, 0.10, 5.0),
        _make_cell("scripted", 1, 8.0, 3.0, 2.0, 2.0, 0.0, 1.0),
        _make_cell("swarm", 1, 9.0, 2.0, 3.0, 0.0, 0.05, 3.0),
    ]
    agg = aggregate(cells)
    md = render_markdown(agg)

    society_pos = md.index("| society ")
    scripted_pos = md.index("| scripted ")
    swarm_pos = md.index("| swarm ")
    assert society_pos < scripted_pos
    assert society_pos < swarm_pos


def test_render_markdown_paired_table_present() -> None:
    """Paired lives_saved table is included in markdown output."""
    cells = [
        _make_cell("society", 42, 10.0, 2.0, 3.0, 1.0, 0.10, 5.0),
        _make_cell("scripted", 42, 8.0, 3.0, 2.0, 2.0, 0.0, 1.0),
    ]
    agg = aggregate(cells)
    md = render_markdown(agg)

    assert "Paired" in md or "paired" in md.lower()
    # Seed 42 should appear as a column header
    assert "42" in md


def test_render_markdown_zero_cost_dash() -> None:
    """Zero-cost arm shows — for lives_per_dollar in the table."""
    cells = [
        _make_cell("scripted", 1, 5.0, 1.0, 2.0, 0.0, 0.0, 0.5),
    ]
    agg = aggregate(cells)
    md = render_markdown(agg)
    assert "—" in md


# ---------------------------------------------------------------------------
# resume test
# ---------------------------------------------------------------------------


def test_resume_skips_existing_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cell whose summary.json exists is skipped; build_arm is not called."""
    import aftershock.bench as bench_mod

    call_count = {"n": 0}

    def _fake_build_arm(arm: str, seed: int, provider: Any) -> Any:
        call_count["n"] += 1
        raise AssertionError("build_arm should not be called for a resumed cell")

    monkeypatch.setattr(bench_mod, "build_arm", _fake_build_arm)

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)

        # Pre-write the summary.json for the only cell in the manifest
        cell_dir = out_dir / "scripted-seed42"
        cell_dir.mkdir(parents=True)
        pre_summary: dict[str, Any] = {
            "arm": "scripted",
            "seed": 42,
            "ticks_requested": 8,
            "ticks_run": 8,
            "scores": {"lives_saved": 5.0, "lives_lost": 1.0,
                       "missions_resolved": 2.0, "missions_failed": 0.0,
                       "panic": 0.0, "resource_utilization": 0.0,
                       "avg_response_ticks": 0.0},
            "cost": {"cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0,
                     "by_agent": {}, "by_model": {}},
            "wall_s": 0.5,
            "models": [],
        }
        (cell_dir / "summary.json").write_text(
            json.dumps(pre_summary), encoding="utf-8"
        )

        manifest = {"ticks": 8, "seeds": [42], "arms": ["scripted"]}
        cells = run_bench(manifest, provider=None, out_dir=out_dir)

    assert call_count["n"] == 0, "build_arm was called despite summary.json existing"
    assert len(cells) == 1
    assert cells[0]["arm"] == "scripted"
    assert cells[0]["seed"] == 42


# ---------------------------------------------------------------------------
# Manifest load + flag-style overrides
# ---------------------------------------------------------------------------


def test_manifest_load_and_override() -> None:
    """Manifest fields are correctly read; overrides replace them for the run."""
    import yaml

    with tempfile.TemporaryDirectory() as td:
        manifest_path = Path(td) / "custom.yaml"
        base_manifest = {
            "ticks": 60,
            "seeds": [11, 23],
            "arms": ["scripted", "solo"],
            "out": "runs/bench",
        }
        manifest_path.write_text(yaml.dump(base_manifest), encoding="utf-8")

        loaded: dict[str, Any] = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    # Verify base fields
    assert loaded["ticks"] == 60
    assert loaded["seeds"] == [11, 23]
    assert loaded["arms"] == ["scripted", "solo"]
    assert loaded["out"] == "runs/bench"

    # Apply flag-style overrides (as bench CLI would)
    overrides = {"ticks": 8, "seeds": [42], "arms": ["scripted"]}
    effective = {**loaded, **overrides}

    assert effective["ticks"] == 8
    assert effective["seeds"] == [42]
    assert effective["arms"] == ["scripted"]
    # Unchanged field preserved
    assert effective["out"] == "runs/bench"


# ---------------------------------------------------------------------------
# End-to-end: one real scripted cell
# ---------------------------------------------------------------------------


def test_end_to_end_scripted_cell_produces_summary() -> None:
    """run_bench with arm=scripted, seed=42, ticks=8 writes a valid summary.json."""
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        manifest: dict[str, Any] = {
            "ticks": 8,
            "seeds": [42],
            "arms": ["scripted"],
        }

        cells = run_bench(manifest, provider=None, out_dir=out_dir)

        assert len(cells) == 1
        cell = cells[0]

        # Required keys in summary
        assert cell["arm"] == "scripted"
        assert cell["seed"] == 42
        assert "ticks_run" in cell
        assert "scores" in cell
        assert "cost" in cell
        assert "wall_s" in cell
        assert "models" in cell

        # scores dict contains the expected keys
        scores = cell["scores"]
        for key in ("lives_saved", "lives_lost", "missions_resolved",
                    "missions_failed", "panic"):
            assert key in scores, f"scores missing key {key!r}"

        # cost dict is well-formed
        cost = cell["cost"]
        assert "cost_usd" in cost
        assert cost["cost_usd"] == 0.0  # scripted uses no LLM

        # wall_s is a non-negative float
        assert isinstance(cell["wall_s"], float)
        assert cell["wall_s"] >= 0.0

        # summary.json was written to disk with correct content
        summary_path = out_dir / "scripted-seed42" / "summary.json"
        assert summary_path.exists(), "summary.json not written to disk"
        on_disk = json.loads(summary_path.read_text(encoding="utf-8"))
        assert on_disk["arm"] == "scripted"
        assert on_disk["seed"] == 42
        assert "scores" in on_disk

        # ticks.ndjson exists (produced by Recorder)
        ndjson_path = out_dir / "scripted-seed42" / "ticks.ndjson"
        assert ndjson_path.exists(), "ticks.ndjson not written"
        lines = [ln for ln in ndjson_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) > 0, "ticks.ndjson is empty"

        # summary.json records ticks_requested
        assert on_disk.get("ticks_requested") == 8


# ---------------------------------------------------------------------------
# Resume config-mismatch tests (ticks_requested guard)
# ---------------------------------------------------------------------------


def test_resume_reruns_on_tick_budget_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cached cell with a different ticks_requested is re-run, not reused."""
    import aftershock.bench as bench_mod

    call_count = {"n": 0}

    def _fake_build_arm(arm: str, seed: int, provider: Any) -> Any:
        call_count["n"] += 1
        # Return a minimal fake setup that never actually runs
        raise RuntimeError("build_arm called (expected in re-run path)")

    monkeypatch.setattr(bench_mod, "build_arm", _fake_build_arm)

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        cell_dir = out_dir / "scripted-seed42"
        cell_dir.mkdir(parents=True)
        # Write a summary that was for ticks=8, but we will request ticks=60
        stale_summary: dict[str, Any] = {
            "arm": "scripted",
            "seed": 42,
            "ticks_requested": 8,   # different from manifest ticks below
            "ticks_run": 8,
            "scores": {"lives_saved": 5.0, "lives_lost": 0.0,
                       "missions_resolved": 1.0, "missions_failed": 0.0,
                       "panic": 0.0, "resource_utilization": 0.0,
                       "avg_response_ticks": 0.0},
            "cost": {"cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0,
                     "by_agent": {}, "by_model": {}},
            "wall_s": 0.1,
            "models": [],
        }
        (cell_dir / "summary.json").write_text(json.dumps(stale_summary), encoding="utf-8")

        # Request ticks=60 — mismatch should force re-run (which hits our fake)
        manifest = {"ticks": 60, "seeds": [42], "arms": ["scripted"]}
        with pytest.raises(RuntimeError, match="build_arm called"):
            bench_mod.run_bench(manifest, provider=None, out_dir=out_dir)

    assert call_count["n"] == 1, "build_arm should have been called once for the re-run"


def test_resume_skips_when_ticks_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cached cell with matching ticks_requested is skipped."""
    import aftershock.bench as bench_mod

    def _fake_build_arm(arm: str, seed: int, provider: Any) -> Any:
        raise AssertionError("build_arm must not be called when ticks match")

    monkeypatch.setattr(bench_mod, "build_arm", _fake_build_arm)

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        cell_dir = out_dir / "scripted-seed42"
        cell_dir.mkdir(parents=True)
        summary: dict[str, Any] = {
            "arm": "scripted",
            "seed": 42,
            "ticks_requested": 8,
            "ticks_run": 8,
            "scores": {"lives_saved": 5.0, "lives_lost": 0.0,
                       "missions_resolved": 1.0, "missions_failed": 0.0,
                       "panic": 0.0, "resource_utilization": 0.0,
                       "avg_response_ticks": 0.0},
            "cost": {"cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0,
                     "by_agent": {}, "by_model": {}},
            "wall_s": 0.1,
            "models": [],
        }
        (cell_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

        manifest = {"ticks": 8, "seeds": [42], "arms": ["scripted"]}
        cells = bench_mod.run_bench(manifest, provider=None, out_dir=out_dir)

    assert len(cells) == 1
    assert cells[0]["ticks_requested"] == 8


def test_resume_reruns_on_corrupt_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """A corrupt summary.json triggers a re-run instead of crashing."""
    import aftershock.bench as bench_mod

    call_count = {"n": 0}

    def _fake_build_arm(arm: str, seed: int, provider: Any) -> Any:
        call_count["n"] += 1
        raise RuntimeError("re-run triggered")

    monkeypatch.setattr(bench_mod, "build_arm", _fake_build_arm)

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        cell_dir = out_dir / "scripted-seed42"
        cell_dir.mkdir(parents=True)
        # Truncated JSON
        (cell_dir / "summary.json").write_text('{ "arm": "scripted", TRUNC', encoding="utf-8")

        manifest = {"ticks": 8, "seeds": [42], "arms": ["scripted"]}
        with pytest.raises(RuntimeError, match="re-run triggered"):
            bench_mod.run_bench(manifest, provider=None, out_dir=out_dir)

    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# aggregate robustness tests
# ---------------------------------------------------------------------------


def test_aggregate_raises_on_missing_arm_key() -> None:
    """aggregate raises KeyError when a cell is missing 'arm'."""
    cells = [{"seed": 42, "ticks_run": 8, "scores": {}, "cost": {}, "wall_s": 0.0}]
    with pytest.raises(KeyError, match="'arm'"):
        aggregate(cells)


def test_aggregate_raises_on_missing_seed_key() -> None:
    """aggregate raises KeyError when a cell is missing 'seed'."""
    cells = [{"arm": "scripted", "ticks_run": 8, "scores": {}, "cost": {}, "wall_s": 0.0}]
    with pytest.raises(KeyError, match="'seed'"):
        aggregate(cells)


def test_aggregate_raises_on_missing_metric_key() -> None:
    """_extract raises KeyError for an unexpected missing score metric key."""
    # 'missions_resolved' present in all real cells; omitting it triggers the raise
    cells = [
        {
            "arm": "x",
            "seed": 1,
            "ticks_run": 8,
            "scores": {
                "lives_saved": 5.0,
                "lives_lost": 1.0,
                # missing missions_resolved intentionally
                "missions_failed": 0.0,
            },
            "cost": {"cost_usd": 0.0},
            "wall_s": 1.0,
        }
    ]
    with pytest.raises(KeyError, match="missions_resolved"):
        aggregate(cells)


# ---------------------------------------------------------------------------
# Paired table: missing cell rendered as '·', not '0'
# ---------------------------------------------------------------------------


def test_render_markdown_missing_paired_cell_shown_as_dot() -> None:
    """A missing (arm, seed) paired cell must render as '·', not '0'."""
    # arm 'x' has seed 10 and 20; arm 'y' has only seed 10
    cells = [
        _make_cell("x", 10, lives_saved=5.0, lives_lost=0.0,
                   missions_resolved=1.0, missions_failed=0.0,
                   cost_usd=0.0, wall_s=1.0),
        _make_cell("x", 20, lives_saved=7.0, lives_lost=0.0,
                   missions_resolved=1.0, missions_failed=0.0,
                   cost_usd=0.0, wall_s=1.0),
        _make_cell("y", 10, lives_saved=3.0, lives_lost=0.0,
                   missions_resolved=1.0, missions_failed=0.0,
                   cost_usd=0.0, wall_s=1.0),
    ]
    agg = aggregate(cells)
    md = render_markdown(agg)

    # The '·' marker must appear (arm 'y' is missing seed 20)
    assert "·" in md, "missing paired cell must be rendered as '·'"

    # The row for 'y' must not read '0' in the seed-20 position
    # Find the y row in the paired table
    paired_section = md.split("## Paired")[1] if "## Paired" in md else ""
    y_row = next((ln for ln in paired_section.splitlines() if ln.startswith("| y ")), "")
    assert y_row, "arm 'y' row not found in paired table"
    assert "·" in y_row, f"arm 'y' seed-20 slot must be '·', got: {y_row!r}"


# ---------------------------------------------------------------------------
# lives_per_dollar methodology disclosed in header
# ---------------------------------------------------------------------------


def test_render_markdown_lives_per_dollar_formula_in_header() -> None:
    """Header must disclose the ratio-of-means formula for lives_per_dollar."""
    cells = [_make_cell("society", 1, 10.0, 2.0, 3.0, 1.0, 0.10, 5.0)]
    agg = aggregate(cells)
    md = render_markdown(agg)
    assert "mean lives / mean cost" in md, (
        "lives_per_dollar column header must disclose ratio-of-means formula"
    )


# ---------------------------------------------------------------------------
# team_alignment in cell summary, aggregate, and markdown table
# ---------------------------------------------------------------------------


def _make_cell_with_ta(
    arm: str,
    seed: int,
    lives_saved: float,
    team_alignment: float | None,
) -> dict[str, Any]:
    cell = _make_cell(arm, seed, lives_saved, 0.0, 1.0, 0.0, 0.0, 1.0)
    if team_alignment is not None:
        cell["team_alignment"] = team_alignment
    return cell


def test_aggregate_team_alignment_mean() -> None:
    """aggregate must compute mean_team_alignment across cells that have the key."""
    cells = [
        _make_cell_with_ta("society", 1, 10.0, 0.8),
        _make_cell_with_ta("society", 2, 12.0, 0.6),
    ]
    agg = aggregate(cells)
    arm = agg["arms"]["society"]
    assert "mean_team_alignment" in arm
    assert math.isclose(arm["mean_team_alignment"], 0.7, rel_tol=1e-9)


def test_aggregate_team_alignment_null_when_all_missing() -> None:
    """aggregate must set mean_team_alignment=None when no cells have the key."""
    cells = [
        _make_cell_with_ta("scripted", 1, 5.0, None),
        _make_cell_with_ta("scripted", 2, 7.0, None),
    ]
    agg = aggregate(cells)
    arm = agg["arms"]["scripted"]
    assert "mean_team_alignment" in arm
    assert arm["mean_team_alignment"] is None


def test_aggregate_team_alignment_partial_null_uses_present_cells() -> None:
    """When only some cells have team_alignment, aggregate uses only those values.

    An older cell without the key must not be treated as 0.
    """
    cells = [
        _make_cell_with_ta("swarm", 1, 10.0, 0.9),
        _make_cell_with_ta("swarm", 2, 12.0, None),  # older cell, key absent
    ]
    agg = aggregate(cells)
    arm = agg["arms"]["swarm"]
    # Only one value (0.9) contributes; result should be 0.9, not 0.45
    assert arm["mean_team_alignment"] is not None
    assert math.isclose(arm["mean_team_alignment"], 0.9, rel_tol=1e-9)


def test_render_markdown_team_alignment_column_present() -> None:
    """render_markdown must include 'mean_team_alignment' column header."""
    cells = [_make_cell_with_ta("society", 1, 10.0, 0.85)]
    agg = aggregate(cells)
    md = render_markdown(agg)
    assert "mean_team_alignment" in md, (
        "'mean_team_alignment' column missing from benchmark table"
    )


def test_render_markdown_team_alignment_dash_when_null() -> None:
    """Arms with no team_alignment data must show '—' in the table."""
    cells = [_make_cell_with_ta("scripted", 1, 5.0, None)]
    agg = aggregate(cells)
    md = render_markdown(agg)
    assert "—" in md


def test_render_markdown_team_alignment_value_shown() -> None:
    """render_markdown must show the numeric team_alignment value for arms that have it."""
    cells = [_make_cell_with_ta("society", 1, 10.0, 0.920)]
    agg = aggregate(cells)
    md = render_markdown(agg)
    # 0.920 formatted to 3 decimal places
    assert "0.920" in md


def test_end_to_end_scripted_cell_has_team_alignment() -> None:
    """run_bench on a scripted cell must produce team_alignment in summary.json."""
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        manifest: dict[str, Any] = {
            "ticks": 8,
            "seeds": [42],
            "arms": ["scripted"],
        }
        cells = run_bench(manifest, provider=None, out_dir=out_dir)
        assert len(cells) == 1
        cell = cells[0]
        assert "team_alignment" in cell, (
            "summary.json must include 'team_alignment' after run_bench"
        )
        ta = cell["team_alignment"]
        assert ta is None or isinstance(ta, float), (
            f"team_alignment must be a float or None, got {ta!r}"
        )

        # Verify it is also in the written summary.json
        summary_path = out_dir / "scripted-seed42" / "summary.json"
        on_disk = json.loads(summary_path.read_text(encoding="utf-8"))
        assert "team_alignment" in on_disk
