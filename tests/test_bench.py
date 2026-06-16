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

from aftershock.bench import (
    aggregate,
    analyze_ablation,
    analyze_repeats,
    render_ablation_markdown,
    render_markdown,
    render_repeats_markdown,
    run_ablation,
    run_bench,
    run_repeat_seeds,
)

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

    def _fake_build_arm(
        arm: str, seed: int, provider: Any,
        society_tools: bool = False, seed_sampler: bool = False,
        pool_sizes: dict | None = None, doctrine: bool = True,
        **_kwargs: object,  # absorb future build_arm kwargs (e.g. role_models)
    ) -> Any:
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

    def _fake_build_arm(
        arm: str, seed: int, provider: Any,
        society_tools: bool = False, seed_sampler: bool = False,
        pool_sizes: dict | None = None, doctrine: bool = True,
        **_kwargs: object,  # absorb future build_arm kwargs (e.g. role_models)
    ) -> Any:
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

    def _fake_build_arm(
        arm: str, seed: int, provider: Any,
        society_tools: bool = False, seed_sampler: bool = False,
        pool_sizes: dict | None = None, doctrine: bool = True,
        **_kwargs: object,  # absorb future build_arm kwargs (e.g. role_models)
    ) -> Any:
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

    def _fake_build_arm(
        arm: str, seed: int, provider: Any,
        society_tools: bool = False, seed_sampler: bool = False,
        pool_sizes: dict | None = None, doctrine: bool = True,
        **_kwargs: object,  # absorb future build_arm kwargs (e.g. role_models)
    ) -> Any:
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


# ---------------------------------------------------------------------------
# M3: paired ablation harness
# ---------------------------------------------------------------------------


def _ablation_cells() -> list[dict[str, Any]]:
    """Control 'base', treatment 'tuned': Δ = [+5, +5, +5, +5, -5] over seeds."""
    base = {11: 100.0, 23: 100.0, 37: 100.0, 42: 100.0, 57: 100.0}
    tuned = {11: 105.0, 23: 105.0, 37: 105.0, 42: 105.0, 57: 95.0}
    cells: list[dict[str, Any]] = []
    for seed, lives in base.items():
        cells.append(_make_cell("base", seed, lives, 0.0, 1.0, 0.0, 0.0, 1.0))
    for seed, lives in tuned.items():
        cells.append(_make_cell("tuned", seed, lives, 0.0, 1.0, 0.0, 0.0, 1.0))
    return cells


def test_analyze_ablation_paired_delta_and_signtest() -> None:
    result = analyze_ablation(_ablation_cells(), "base", "tuned")
    assert result["n"] == 5
    # mean Δ = (5+5+5+5-5)/5 = 3.0
    assert math.isclose(result["mean_delta"], 3.0, rel_tol=1e-9)
    assert result["n_positive"] == 4
    assert result["n_negative"] == 1
    # sign test: pos=4 neg=1 n=5 k=1 -> 2*(C(5,0)+C(5,1))*0.5^5 = 2*6/32 = 0.375
    assert math.isclose(result["sign_test_p"], 0.375, rel_tol=1e-9)
    assert result["mean_control"] == 100.0
    assert math.isclose(result["mean_treatment"], 103.0, rel_tol=1e-9)


def test_analyze_ablation_power_curve_present() -> None:
    result = analyze_ablation(_ablation_cells(), "base", "tuned")
    effects = [pt["effect"] for pt in result["power_curve"]]
    assert effects == [2.0, 5.0, 10.0, 15.0, 20.0]
    for pt in result["power_curve"]:
        assert pt["required_n"] >= 2
        assert 0.0 <= pt["power_at_current_n"] <= 1.0
    # Larger effects need fewer seeds (monotone non-increasing).
    reqs = [pt["required_n"] for pt in result["power_curve"]]
    assert reqs == sorted(reqs, reverse=True)


def test_analyze_ablation_no_common_seeds_raises() -> None:
    cells = [
        _make_cell("base", 1, 100.0, 0.0, 1.0, 0.0, 0.0, 1.0),
        _make_cell("tuned", 2, 105.0, 0.0, 1.0, 0.0, 0.0, 1.0),
    ]
    with pytest.raises(ValueError, match="no common seeds"):
        analyze_ablation(cells, "base", "tuned")


def test_analyze_ablation_ci_deterministic() -> None:
    a = analyze_ablation(_ablation_cells(), "base", "tuned")
    b = analyze_ablation(_ablation_cells(), "base", "tuned")
    assert a["ci"] == b["ci"]


def test_render_ablation_markdown_has_sections() -> None:
    md = render_ablation_markdown(analyze_ablation(_ablation_cells(), "base", "tuned"))
    assert "Per-seed" in md
    assert "Power curve" in md
    assert "sign test" in md
    assert "Verdict" in md


def test_run_ablation_scripted_self_is_zero_delta() -> None:
    """Self-ablation (scripted vs scripted) is deterministic: Δ=0 on every seed."""
    with tempfile.TemporaryDirectory() as td:
        result = run_ablation(
            "scripted", "scripted", seeds=[42, 57], ticks=8,
            provider=None, out_dir=Path(td),
        )
    assert result["n"] == 2
    assert result["mean_delta"] == 0.0
    assert result["sd_delta"] == 0.0
    assert result["sign_test_p"] == 1.0
    # CI collapses to a point at 0.
    assert result["ci"]["lower"] == 0.0
    assert result["ci"]["upper"] == 0.0


# ---------------------------------------------------------------------------
# M2: repeats-per-seed variance decomposition
# ---------------------------------------------------------------------------


def test_analyze_repeats_pure() -> None:
    # arm 'a': seed 1 replicates [10,10], seed 2 replicates [20,20] -> within=0.
    cells = [
        _make_cell("a", 1, 10.0, 0.0, 1.0, 0.0, 0.0, 1.0),
        _make_cell("a", 1, 10.0, 0.0, 1.0, 0.0, 0.0, 1.0),
        _make_cell("a", 2, 20.0, 0.0, 1.0, 0.0, 0.0, 1.0),
        _make_cell("a", 2, 20.0, 0.0, 1.0, 0.0, 0.0, 1.0),
    ]
    result = analyze_repeats(cells)
    a = result["a"]
    assert a["n_seeds"] == 2
    assert a["repeats"] == 2
    assert math.isclose(a["sd_within"], 0.0, abs_tol=1e-12)
    assert math.isclose(a["sd_between"], math.sqrt(50.0), rel_tol=1e-9)
    assert math.isclose(a["icc"], 1.0, rel_tol=1e-9)


def test_run_repeat_seeds_scripted_zero_within_variance() -> None:
    """Scripted is deterministic: every repeat is identical -> σ_within == 0."""
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        cells = run_repeat_seeds(
            ["scripted"], seeds=[42], repeats=3, ticks=8,
            provider=None, out_dir=out_dir,
        )
        assert len(cells) == 3
        # Distinct repeat cell dirs were written.
        for k in range(3):
            assert (out_dir / f"scripted-seed42-r{k}" / "summary.json").exists()
        result = analyze_repeats(cells)
    assert math.isclose(result["scripted"]["sd_within"], 0.0, abs_tol=1e-9)


def test_run_repeat_seeds_resumes() -> None:
    """A second call with matching ticks reuses the cells (no re-run needed)."""
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        run_repeat_seeds(
            ["scripted"], seeds=[42], repeats=2, ticks=8, provider=None, out_dir=out_dir
        )
        # Re-run: should resume from summary.json (cells still returned).
        cells = run_repeat_seeds(
            ["scripted"], seeds=[42], repeats=2, ticks=8, provider=None, out_dir=out_dir
        )
        assert len(cells) == 2


def test_render_repeats_markdown_has_columns() -> None:
    cells = [
        _make_cell("scripted", 1, 10.0, 0.0, 1.0, 0.0, 0.0, 1.0),
        _make_cell("scripted", 1, 12.0, 0.0, 1.0, 0.0, 0.0, 1.0),
    ]
    md = render_repeats_markdown(analyze_repeats(cells))
    assert "σ_within" in md
    assert "σ_between" in md
    assert "ICC" in md
    assert "scripted" in md


def test_run_repeat_seeds_rejects_seed_sampler() -> None:
    """M1 (seed sampler) and M2 (repeats) are contradictory — must be rejected."""
    with (
        tempfile.TemporaryDirectory() as td,
        pytest.raises(ValueError, match="contradictory"),
    ):
        run_repeat_seeds(
            ["society"], seeds=[42], repeats=3, ticks=8,
            provider=None, out_dir=Path(td), seed_sampler=True,
        )


def test_analyze_repeats_nonzero_within_variance() -> None:
    """Non-zero within-seed spread is captured (the LLM-sampling component M2 exists
    to measure) — not only the scripted within=0 case."""
    # seed 1 replicates [10, 14] (mean 12, within spread), seed 2 [30, 34] (mean 32).
    cells = [
        _make_cell("a", 1, 10.0, 0.0, 1.0, 0.0, 0.0, 1.0),
        _make_cell("a", 1, 14.0, 0.0, 1.0, 0.0, 0.0, 1.0),
        _make_cell("a", 2, 30.0, 0.0, 1.0, 0.0, 0.0, 1.0),
        _make_cell("a", 2, 34.0, 0.0, 1.0, 0.0, 0.0, 1.0),
    ]
    a = analyze_repeats(cells)["a"]
    # within: each seed has sample sd sqrt(((10-12)^2+(14-12)^2)/1)=sqrt(8); pooled MSW
    # = (8+8)/2 = 8 -> sd_within = sqrt(8).
    assert math.isclose(a["sd_within"], math.sqrt(8.0), rel_tol=1e-9)
    assert a["sd_between"] > 0.0
    assert 0.0 < a["icc"] < 1.0


# ---------------------------------------------------------------------------
# Ablation verdict hardening: CI and sign test must AGREE for "credible"
# (regression for FIELD-NOTES §16-17 — a CI-only verdict over-claimed at n=5)
# ---------------------------------------------------------------------------


def _paired_cells(control: str, treatment: str, ctrl: dict[int, float],
                  treat: dict[int, float]) -> list[dict[str, Any]]:
    cells = []
    for s, v in ctrl.items():
        cells.append(_make_cell(control, s, float(v), 0.0, 1.0, 0.0, 0.0, 1.0))
    for s, v in treat.items():
        cells.append(_make_cell(treatment, s, float(v), 0.0, 1.0, 0.0, 0.0, 1.0))
    return cells


def test_verdict_suggestive_when_ci_excludes_zero_but_sign_not_significant() -> None:
    """The published +28 data: CI excludes 0 yet sign test p=0.125 -> 'suggestive',
    NOT 'credible'. This is the exact §16-17 over-claim being guarded against."""
    society = {11: 140, 23: 86, 37: 81, 42: 98, 57: 111}
    swarm = {11: 52, 23: 79, 37: 81, 42: 72, 57: 94}
    res = analyze_ablation(_paired_cells("swarm", "society", swarm, society),
                           "swarm", "society")
    assert res["ci_excludes_zero"] is True
    assert res["sign_significant"] is False
    assert math.isclose(res["sign_test_p"], 0.125, rel_tol=1e-9)
    assert res["verdict"] == "suggestive"
    md = render_ablation_markdown(res)
    assert "suggestive but unconfirmed" in md
    assert "credible improvement" not in md


def test_verdict_credible_when_ci_and_sign_agree() -> None:
    """6 seeds all +10 (sd 0): CI excludes 0 AND sign test significant -> 'credible'."""
    ctrl = {s: 100.0 for s in range(1, 7)}
    treat = {s: 110.0 for s in range(1, 7)}
    res = analyze_ablation(_paired_cells("ctrl", "treat", ctrl, treat), "ctrl", "treat")
    assert res["ci_excludes_zero"] is True
    assert res["sign_significant"] is True
    assert res["verdict"] == "credible"
    assert "credible improvement" in render_ablation_markdown(res)


def test_verdict_noise_when_ci_includes_zero() -> None:
    """Zero effect -> CI includes 0 -> 'noise' regardless of sign test."""
    ctrl = {1: 100.0, 2: 100.0, 3: 100.0}
    treat = {1: 100.0, 2: 100.0, 3: 100.0}
    res = analyze_ablation(_paired_cells("a", "b", ctrl, treat), "a", "b")
    assert res["ci_excludes_zero"] is False
    assert res["verdict"] == "noise"
    assert "not distinguishable from noise" in render_ablation_markdown(res)


def test_verdict_n5_all_positive_cannot_be_credible() -> None:
    """Even a clean 5/5 split can't be 'credible': the sign test floor at n=5 is
    p=0.0625 > 0.05, so the harness correctly demands more seeds."""
    ctrl = {s: 100.0 for s in range(1, 6)}
    treat = {s: 110.0 for s in range(1, 6)}
    res = analyze_ablation(_paired_cells("c", "t", ctrl, treat), "c", "t")
    assert res["ci_excludes_zero"] is True
    assert math.isclose(res["sign_test_p"], 0.0625, rel_tol=1e-9)
    assert res["verdict"] == "suggestive"


# ---------------------------------------------------------------------------
# Doctrine on/off ablation (FIELD-NOTES §11) — same arm, one knob flipped
# ---------------------------------------------------------------------------


def _labeled_cell(label: str, seed: int, lives: float, alignment: float,
                  roles: dict[str, float] | None = None) -> dict[str, Any]:
    cell = _make_cell("society", seed, lives, 0.0, 1.0, 0.0, 0.0, 1.0)
    cell["label"] = label
    cell["team_alignment"] = alignment
    cell["role_conformance"] = roles or {}
    return cell


def test_analyze_ablation_pairs_on_label_not_arm() -> None:
    """With key='label', two same-arm sides pair correctly (the doctrine ablation)."""
    cells = [
        _labeled_cell("society-nodoctrine", 11, 113.0, 0.759),
        _labeled_cell("society-nodoctrine", 23, 100.0, 0.760),
        _labeled_cell("society", 11, 96.0, 0.904),
        _labeled_cell("society", 23, 105.0, 0.900),
    ]
    res = analyze_ablation(cells, "society-nodoctrine", "society", key="label")
    assert res["n"] == 2
    # Δ lives = (96-113) + (105-100) = -17, +5 -> mean -6
    assert math.isclose(res["mean_delta"], -6.0, rel_tol=1e-9)


def test_analyze_ablation_default_key_arm_ignores_label() -> None:
    """The default key='arm' is unchanged: same-arm cells with distinct labels would
    collide on arm (so the doctrine ablation MUST pass key='label')."""
    cells = [
        _labeled_cell("society-nodoctrine", 11, 113.0, 0.759),
        _labeled_cell("society", 11, 96.0, 0.904),
    ]
    # both have arm='society' -> only one seed/side resolvable -> no distinct pair
    with pytest.raises(ValueError, match="no common seeds"):
        analyze_ablation(cells, "society-nodoctrine", "society")  # key='arm'


def test_conformance_block_team_and_per_role() -> None:
    from aftershock.bench import _conformance_block

    cells = [
        _labeled_cell("society-nodoctrine", 11, 113.0, 0.759,
                      {"comms": 0.83, "infrastructure": 0.56}),
        _labeled_cell("society-nodoctrine", 23, 100.0, 0.760,
                      {"comms": 0.85, "infrastructure": 0.58}),
        _labeled_cell("society", 11, 96.0, 0.904,
                      {"comms": 1.00, "infrastructure": 0.69}),
        _labeled_cell("society", 23, 105.0, 0.900,
                      {"comms": 1.00, "infrastructure": 0.71}),
    ]
    block = _conformance_block(cells, "society-nodoctrine", "society")
    assert block["n"] == 2
    assert math.isclose(block["mean_control"], 0.7595, rel_tol=1e-9)
    assert math.isclose(block["mean_treatment"], 0.902, rel_tol=1e-9)
    assert block["mean_delta"] > 0  # doctrine raises alignment
    assert math.isclose(block["by_role"]["comms"]["delta"], 1.00 - 0.84, rel_tol=1e-9)
    assert block["by_role"]["infrastructure"]["delta"] > 0


def test_conformance_block_skips_none_alignment() -> None:
    from aftershock.bench import _conformance_block

    cells = [
        _labeled_cell("society-nodoctrine", 11, 113.0, 0.759),
        _labeled_cell("society", 11, 96.0, 0.904),
    ]
    cells[0]["team_alignment"] = None  # conformance check failed on this side
    block = _conformance_block(cells, "society-nodoctrine", "society")
    assert block["n"] == 0  # the seed has no usable pair
    assert block["mean_delta"] is None


def _doctrine_result(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble a doctrine-ablation result dict the way _run_doctrine_ablation does."""
    from aftershock.bench import _conformance_block

    res = analyze_ablation(cells, "society-nodoctrine", "society", key="label")
    res["ablate"] = "doctrine"
    res["arm"] = "society"
    res["conformance"] = _conformance_block(cells, "society-nodoctrine", "society")
    return res


def test_render_doctrine_leads_with_conformance() -> None:
    """Healthy doctrine ablation: conformance (primary) is rendered BEFORE the demoted
    '## Lives (secondary signal)' section — the §11 honesty ordering."""
    cells = [
        _labeled_cell("society-nodoctrine", 11, 113.0, 0.759, {"comms": 0.83}),
        _labeled_cell("society-nodoctrine", 23, 100.0, 0.760, {"comms": 0.85}),
        _labeled_cell("society", 11, 96.0, 0.904, {"comms": 1.00}),
        _labeled_cell("society", 23, 105.0, 0.900, {"comms": 1.00}),
    ]
    md = render_ablation_markdown(_doctrine_result(cells))
    conf_pos = md.index("## Conformance")
    lives_pos = md.index("## Lives (secondary signal)")
    assert conf_pos < lives_pos, "conformance must lead the lives section"
    assert "Verdict (lives Δ)" in md  # lives verdict is tagged as secondary


def test_render_doctrine_warns_when_conformance_missing() -> None:
    """If conformance failed on every seed (team_alignment=None), the lives verdict must
    NOT be presented as the headline — a prominent 'Primary signal missing' warning fires."""
    cells = [
        _labeled_cell("society-nodoctrine", 11, 113.0, 0.0),
        _labeled_cell("society-nodoctrine", 23, 100.0, 0.0),
        _labeled_cell("society", 11, 140.0, 0.0),
        _labeled_cell("society", 23, 130.0, 0.0),
    ]
    for c in cells:
        c["team_alignment"] = None  # conformance check failed on both sides, all seeds
    res = _doctrine_result(cells)
    assert res["conformance"]["n"] == 0
    md = render_ablation_markdown(res)
    assert "Primary signal missing" in md
    assert "secondary and unconfirmed" in md
    # The conformance section is absent (no data) but the reader is warned, not misled.
    assert "## Conformance" not in md


def test_render_doctrine_warns_on_partial_conformance() -> None:
    """When conformance is present for some but not all lives-paired seeds, a partial
    warning names how many seeds are missing."""
    cells = [
        _labeled_cell("society-nodoctrine", 11, 113.0, 0.759, {"comms": 0.83}),
        _labeled_cell("society-nodoctrine", 23, 100.0, 0.760, {"comms": 0.85}),
        _labeled_cell("society", 11, 96.0, 0.904, {"comms": 1.00}),
        _labeled_cell("society", 23, 105.0, 0.900, {"comms": 1.00}),
    ]
    cells[1]["team_alignment"] = None  # drop conformance on one control seed only
    res = _doctrine_result(cells)
    assert res["n"] == 2  # lives still pairs on both seeds
    assert res["conformance"]["n"] == 1  # but conformance only on one
    md = render_ablation_markdown(res)
    assert "Conformance is missing for 1 of 2 seeds" in md
    assert "## Conformance" in md  # the one usable seed is still reported


def test_run_ablation_doctrine_rejects_mismatched_arms() -> None:
    with tempfile.TemporaryDirectory() as td, pytest.raises(
        ValueError, match="control == treatment"
    ):
        run_ablation("society", "swarm", seeds=[42], ticks=3,
                     provider=None, out_dir=Path(td), ablate="doctrine")


def test_run_ablation_doctrine_rejects_scripted() -> None:
    with tempfile.TemporaryDirectory() as td, pytest.raises(ValueError, match="no doctrine"):
        run_ablation("scripted", "scripted", seeds=[42], ticks=3,
                     provider=None, out_dir=Path(td), ablate="doctrine")


def test_run_ablation_doctrine_unknown_knob_raises() -> None:
    with tempfile.TemporaryDirectory() as td, pytest.raises(
        ValueError, match="unknown ablate knob"
    ):
        run_ablation("society", "society", seeds=[42], ticks=3,
                     provider=None, out_dir=Path(td), ablate="bogus")


def test_run_ablation_doctrine_end_to_end_mock() -> None:
    """Full doctrine ablation through the engine with a MockProvider: distinct
    labeled cells, conformance block present, ablate/arm markers set."""
    from aftershock.llm.provider import MockProvider

    prov = MockProvider(script=lambda m, s, u: '{"decisions": []}')
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        res = run_ablation("society", "society", seeds=[42, 57], ticks=2,
                           provider=prov, out_dir=out, ablate="doctrine")
        assert res["ablate"] == "doctrine"
        assert res["arm"] == "society"
        assert res["control"] == "society-nodoctrine"
        assert res["treatment"] == "society"
        assert res["n"] == 2
        assert "conformance" in res and res["conformance"]["n"] == 2
        # Both sides wrote distinct cell dirs (no collision on the same arm).
        dirs = {p.name for p in out.iterdir() if p.is_dir()}
        assert {"society-seed42", "society-seed57",
                "society-nodoctrine-seed42", "society-nodoctrine-seed57"} <= dirs
        # The rendered markdown carries the doctrine framing + conformance section.
        md = render_ablation_markdown(res)
        assert "doctrine on/off" in md
        assert "## Conformance" in md


def test_run_ablation_doctrine_resumes_both_sides() -> None:
    """Re-running the doctrine ablation reuses both sides' completed cells ($0)."""
    from aftershock.llm.provider import MockProvider

    calls = {"n": 0}

    def script(m, s, u):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return '{"decisions": []}'

    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        run_ablation("society", "society", seeds=[42], ticks=2,
                     provider=MockProvider(script=script), out_dir=out, ablate="doctrine")
        first = calls["n"]
        assert first > 0
        # Second run must skip every cell (no further provider calls).
        run_ablation("society", "society", seeds=[42], ticks=2,
                     provider=MockProvider(script=script), out_dir=out, ablate="doctrine")
        assert calls["n"] == first, "resume must not re-execute completed cells"
