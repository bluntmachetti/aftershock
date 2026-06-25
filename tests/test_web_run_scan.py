"""Unit tests for the run-scan/rotation path in web.py.

These guard the regression that left the public observatory showing "No runs found"
and a hung Bench tab: the AFTERSHOCK_DEMO_MODE ambient loop accumulated tens of
thousands of throwaway ``live-*`` run dirs, and the old _scan_runs read every
ticks.ndjson on every call until /api/runs timed out (and, blocking the event loop,
starved /api/bench too).

The fix has three observable contracts, tested here directly (no engine runs needed):

  1. _scan_runs ALWAYS lists every curated run (any id not prefixed ``live-``) and caps
     the throwaway ``live-*`` firehose to the newest _MAX_LIVE_RUNS_LISTED by mtime.
  2. _prune_ambient_runs keeps the newest _AMBIENT_KEEP live dirs and never touches a
     curated run.
  3. _count_ndjson_lines counts records cheaply and matches the file's line count.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from aftershock.web import (
    _MAX_LIVE_RUNS_LISTED,
    _count_ndjson_lines,
    _prune_ambient_runs,
    _scan_runs,
    seed_demo_runs,
)


def _make_run(
    root: Path,
    run_id: str,
    *,
    seed: int = 1,
    arm: str = "scripted",
    n_ticks: int = 3,
    has_world: bool = True,
    mtime: float | None = None,
) -> Path:
    """Fabricate a minimal-but-valid run dir (run.json + ticks.ndjson [+ world])."""
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": run_id, "seed": seed, "arm": arm}), encoding="utf-8"
    )
    (run_dir / "ticks.ndjson").write_text(
        "".join(f'{{"tick":{i}}}\n' for i in range(n_ticks)), encoding="utf-8"
    )
    if has_world:
        (run_dir / "world.ndjson").write_text(
            "".join(f'{{"tick":{i}}}\n' for i in range(n_ticks)), encoding="utf-8"
        )
    # Stamp mtime LAST so it survives the file writes above (which bump the dir mtime).
    if mtime is not None:
        os.utime(run_dir, (mtime, mtime))
    return run_dir


def test_scan_runs_caps_live_but_keeps_every_curated(tmp_path: Path) -> None:
    # Curated runs (none prefixed "live-"): two top-level + one nested episode.
    _make_run(tmp_path, "seed91-society", arm="society", mtime=1000.0)
    _make_run(tmp_path, "cf-abc-none", mtime=1001.0)
    _make_run(tmp_path / "episodes", "ep1-seed100-society", arm="society", mtime=1002.0)

    # A firehose of ambient live runs, far above the cap, with increasing mtimes so
    # "newest" is unambiguous (live-0 oldest ... live-(N-1) newest).
    n_live = _MAX_LIVE_RUNS_LISTED * 3
    for i in range(n_live):
        _make_run(tmp_path, f"live-{i:05d}", mtime=2000.0 + i)

    rows = _scan_runs(tmp_path)
    ids = {r["run_id"] for r in rows}

    # Every curated run is present regardless of how many ambient runs exist.
    assert {"seed91-society", "cf-abc-none", "ep1-seed100-society"} <= ids

    # The live firehose is capped to the newest N.
    live_ids = sorted(r["run_id"] for r in rows if r["run_id"].startswith("live-"))
    assert len(live_ids) == _MAX_LIVE_RUNS_LISTED
    newest_expected = {f"live-{i:05d}" for i in range(n_live - _MAX_LIVE_RUNS_LISTED, n_live)}
    assert set(live_ids) == newest_expected

    # Result is sorted newest-first by mtime; the newest live run leads.
    assert rows[0]["run_id"] == f"live-{n_live - 1:05d}"


def test_scan_runs_reports_tick_count_and_world_flag(tmp_path: Path) -> None:
    _make_run(tmp_path, "seed42-society", arm="society", n_ticks=29, has_world=True)
    _make_run(tmp_path, "seed7-scripted", arm="scripted", n_ticks=5, has_world=False)

    by_id = {r["run_id"]: r for r in _scan_runs(tmp_path)}
    assert by_id["seed42-society"]["ticks"] == 29
    assert by_id["seed42-society"]["has_world"] is True
    assert by_id["seed7-scripted"]["ticks"] == 5
    assert by_id["seed7-scripted"]["has_world"] is False


def test_prune_ambient_runs_keeps_newest_and_never_touches_curated(tmp_path: Path) -> None:
    # Curated runs must survive any prune.
    curated = ["seed91-society", "seed42-society", "cf-abc-none"]
    for cid in curated:
        _make_run(tmp_path, cid, mtime=1000.0)

    n_live = 50
    for i in range(n_live):
        _make_run(tmp_path, f"live-{i:05d}", mtime=2000.0 + i)

    keep = 10
    removed = _prune_ambient_runs(tmp_path, keep)
    assert removed == n_live - keep

    survivors = {p.name for p in tmp_path.iterdir() if p.is_dir()}
    # All curated runs still present.
    assert set(curated) <= survivors
    # Exactly the newest `keep` live dirs remain on disk.
    live_survivors = {n for n in survivors if n.startswith("live-")}
    assert live_survivors == {f"live-{i:05d}" for i in range(n_live - keep, n_live)}


def test_prune_ambient_runs_noop_below_threshold(tmp_path: Path) -> None:
    for i in range(5):
        _make_run(tmp_path, f"live-{i:05d}", mtime=2000.0 + i)
    assert _prune_ambient_runs(tmp_path, keep=10) == 0
    assert len([p for p in tmp_path.iterdir() if p.is_dir()]) == 5


def test_seed_demo_runs_copies_missing_and_never_overwrites(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    runs = tmp_path / "runs"
    _make_run(seed, "seed91-society", arm="society")
    _make_run(seed, "seed42-scripted")
    _make_run(seed / "episodes", "ep1-seed100-society", arm="society")  # nested -> copied whole
    (seed / "memory.json").write_text("{}", encoding="utf-8")  # loose file -> skipped

    # runs already has its own seed42-scripted; seeding must NOT clobber it.
    _make_run(runs, "seed42-scripted", seed=999)
    preserved = (runs / "seed42-scripted" / "run.json").read_text(encoding="utf-8")

    copied = seed_demo_runs(runs, seed)
    assert copied == 2  # seed91-society + episodes/ ; seed42-scripted skipped, memory.json skipped
    assert (runs / "seed91-society" / "run.json").exists()
    assert (runs / "episodes" / "ep1-seed100-society" / "run.json").exists()
    assert (runs / "seed42-scripted" / "run.json").read_text(encoding="utf-8") == preserved
    # Re-seeding is a no-op.
    assert seed_demo_runs(runs, seed) == 0


def test_seed_demo_runs_missing_source_is_noop(tmp_path: Path) -> None:
    assert seed_demo_runs(tmp_path / "runs", tmp_path / "does-not-exist") == 0


def test_count_ndjson_lines(tmp_path: Path) -> None:
    empty = tmp_path / "empty.ndjson"
    empty.write_text("", encoding="utf-8")
    assert _count_ndjson_lines(empty) == 0

    three = tmp_path / "three.ndjson"
    three.write_text('{"a":1}\n{"a":2}\n{"a":3}\n', encoding="utf-8")
    assert _count_ndjson_lines(three) == 3

    # Missing file -> 0, never raises.
    assert _count_ndjson_lines(tmp_path / "nope.ndjson") == 0
