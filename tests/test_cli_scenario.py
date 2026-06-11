"""CLI tests for --scenario: tick-budget default, under-budget hard error,
bench rejection, scenario resolution, and a full offline scripted run on a
fixture pack.

The fixture pack is written into a UNIQUE ephemeral directory under the repo's
real `scenarios/` dir (the CLI resolves `scenarios/<id>/scenario.json` relative
to the package root) and removed in a finally/fixture teardown. No committed
pack is touched; no network is used.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

_AFTERSHOCK_BIN = str(Path(sys.executable).parent / "aftershock")

# scenarios/ lives at the repo root (package_root.parent.parent / "scenarios").
# tests/ is a sibling of src/, so repo root is two levels up from this file's
# parent is not reliable — derive from the installed package instead.
import aftershock  # noqa: E402

_PKG_ROOT = Path(aftershock.__file__).parent  # .../src/aftershock
_SCENARIOS_DIR = _PKG_ROOT.parent.parent / "scenarios"


def _run_aftershock(*args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    cmd_env = env if env is not None else dict(os.environ)
    return subprocess.run(
        [_AFTERSHOCK_BIN, *args],
        capture_output=True,
        text=True,
        env=cmd_env,
    )


def _env_without_key() -> dict[str, str]:
    e = dict(os.environ)
    e.pop("DASHSCOPE_API_KEY", None)
    return e


def _fixture_pack_dict() -> dict:
    """A small valid pack. Last mission tick = 6, so the scenario tick budget
    default is min(6 + 20, 120) = 26."""
    return {
        "format_version": 1,
        "id": "PLACEHOLDER",  # overwritten by the fixture
        "name": "CLI Fixture Pack",
        "hazard": "earthquake",
        "adapter": "test",
        "compiler_version": "abc123",
        "config_sha256": "deadbeef",
        "tick_minutes": 12,
        "window": {"start": "2026-01-01T00:00:00-00:00", "end": "2026-01-01T12:00:00-00:00"},
        "districts": [
            {"id": "old_town", "name": "Manhattan", "members": ["M1"]},
            {"id": "harbor", "name": "Staten Island", "members": ["S1"]},
            {"id": "hospital_district", "name": "Bronx", "members": ["B1"]},
            {"id": "market", "name": "Brooklyn West", "members": ["K1"]},
            {"id": "residential_north", "name": "Queens", "members": ["Q1"]},
            {"id": "industrial", "name": "Brooklyn East", "members": ["K3"]},
        ],
        "pools": {
            "ambulance": {"size": 4, "basis": "calibrated", "note": "x"},
            "rescue_crew": {"size": 3, "basis": "calibrated", "note": "x"},
            "fire_engine": {"size": 3, "basis": "observed", "note": "x"},
            "repair_crew": {"size": 3, "basis": "calibrated", "note": "x"},
            "supply_truck": {"size": 3, "basis": "calibrated", "note": "x"},
        },
        "timeline": [
            {"tick": 0, "kind": "mission", "mission_kind": "collapse_rescue",
             "district_id": "old_town", "severity": 3, "lives_at_risk": 12},
            {"tick": 0, "kind": "blockage", "district_id": "harbor"},
            {"tick": 3, "kind": "mission", "mission_kind": "medical_surge",
             "district_id": "residential_north", "severity": 2, "lives_at_risk": 8},
            {"tick": 6, "kind": "mission", "mission_kind": "fire",
             "district_id": "industrial", "severity": 4, "lives_at_risk": 16},
        ],
        "field_provenance": {
            "tick": "real", "district_id": "real", "mission_kind": "mapped",
            "severity": "mapped", "lives_at_risk": "inferred", "blockage": "synthetic",
        },
        "mapping": {"version": "test-v1", "mission_kind": {"x": "fire"},
                    "severity_rule": "r", "lives_rule": "r"},
        "sampling": {"method": "stratified", "sample_seed": 4636,
                     "kept": 3, "total": 100, "filter": "f"},
        "source": [
            {"dataset": "D", "provider": "P", "dataset_id": "id",
             "query_url": "http://x", "fetched_at": "2026-01-01", "rows_fetched": 10,
             "license": "L", "license_url": "http://l", "attribution": "A"},
        ],
        "reference": {
            "missions": {
                "0": {"received": "2026-01-01T00:00:00-00:00",
                      "first_on_scene": "2026-01-01T00:16:00-00:00", "latency_s": 960},
            },
            "aggregates": {"mean_latency_s": 948, "median_latency_s": 900,
                           "held_rate": 0.16},
        },
    }


# Scenario tick budget for the fixture: min(6 + 20, 120) = 26.
_FIXTURE_DEFAULT_TICKS = 26


@pytest.fixture()
def scenario_pack() -> Iterator[str]:
    """Write the fixture pack under scenarios/<unique-id>/scenario.json; yield the
    id; clean up afterwards."""
    sid = f"test-cli-{uuid.uuid4().hex[:8]}"
    pack_dir = _SCENARIOS_DIR / sid
    pack_dir.mkdir(parents=True, exist_ok=True)
    d = _fixture_pack_dict()
    d["id"] = sid
    (pack_dir / "scenario.json").write_text(json.dumps(d), encoding="utf-8")
    try:
        yield sid
    finally:
        shutil.rmtree(pack_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# run --scenario: default tick budget, offline scripted run succeeds
# ---------------------------------------------------------------------------


def test_run_scenario_scripted_succeeds(scenario_pack: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        result = _run_aftershock(
            "run", "--seed", "42", "--arm", "scripted",
            "--scenario", scenario_pack, "--out", td,
            env=_env_without_key(),
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, f"expected 0, got {result.returncode}\n{combined}"
        # manifest must carry the scenario block
        run_dir = Path(td) / "seed42-scripted"
        manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8")) \
            if (run_dir / "run.json").exists() else None
        # The run.json filename may differ; locate any manifest under the run dir.
        if manifest is None:
            candidates = list(run_dir.glob("*.json"))
            assert candidates, f"no manifest json under {run_dir}: {list(run_dir.iterdir())}"


def test_run_scenario_manifest_has_scenario_block(scenario_pack: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        result = _run_aftershock(
            "run", "--seed", "42", "--arm", "scripted",
            "--scenario", scenario_pack, "--out", td, "--quiet",
            env=_env_without_key(),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        run_dir = Path(td) / "seed42-scripted"
        # Find the manifest that contains "scenario".
        found = False
        for jf in run_dir.glob("*.json"):
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if isinstance(data, dict) and "scenario" in data:
                assert data["scenario"]["id"] == scenario_pack
                assert data["scenario"]["hazard"] == "earthquake"
                assert len(data["scenario"]["pack_digest"]) == 64
                found = True
                break
        assert found, f"no manifest with a scenario block under {run_dir}"


# ---------------------------------------------------------------------------
# under-budget explicit --ticks is a hard error
# ---------------------------------------------------------------------------


def test_run_scenario_under_budget_ticks_errors(scenario_pack: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        result = _run_aftershock(
            "run", "--seed", "42", "--arm", "scripted",
            "--scenario", scenario_pack, "--ticks", "5", "--out", td,
            env=_env_without_key(),
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 1, f"expected 1, got {result.returncode}\n{combined}"
        assert "under" in combined.lower() or "budget" in combined.lower(), combined
        assert "Traceback" not in combined, combined


def test_run_scenario_at_budget_ticks_ok(scenario_pack: str) -> None:
    """Explicit --ticks exactly equal to the budget is accepted."""
    with tempfile.TemporaryDirectory() as td:
        result = _run_aftershock(
            "run", "--seed", "42", "--arm", "scripted",
            "--scenario", scenario_pack, "--ticks", str(_FIXTURE_DEFAULT_TICKS),
            "--out", td, "--quiet",
            env=_env_without_key(),
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_run_scenario_over_budget_ticks_ok(scenario_pack: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        result = _run_aftershock(
            "run", "--seed", "42", "--arm", "scripted",
            "--scenario", scenario_pack, "--ticks", "40", "--out", td, "--quiet",
            env=_env_without_key(),
        )
        assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# unknown scenario id -> error 1
# ---------------------------------------------------------------------------


def test_run_unknown_scenario_errors() -> None:
    with tempfile.TemporaryDirectory() as td:
        result = _run_aftershock(
            "run", "--seed", "1", "--arm", "scripted",
            "--scenario", "no-such-pack-xyz", "--out", td,
            env=_env_without_key(),
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 1, f"expected 1, got {result.returncode}\n{combined}"
        assert "not found" in combined.lower(), combined
        assert "Traceback" not in combined, combined


def test_run_malformed_scenario_id_errors() -> None:
    with tempfile.TemporaryDirectory() as td:
        result = _run_aftershock(
            "run", "--seed", "1", "--arm", "scripted",
            "--scenario", "../etc/passwd", "--out", td,
            env=_env_without_key(),
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 1, combined
        assert "invalid scenario id" in combined.lower(), combined


# ---------------------------------------------------------------------------
# verify --scenario: two-run digest check passes
# ---------------------------------------------------------------------------


def test_verify_scenario_passes(scenario_pack: str) -> None:
    result = _run_aftershock(
        "verify", "--seed", "42", "--scenario", scenario_pack,
        env=_env_without_key(),
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"expected 0, got {result.returncode}\n{combined}"
    assert "PASS" in combined, combined


def test_verify_scenario_under_budget_errors(scenario_pack: str) -> None:
    result = _run_aftershock(
        "verify", "--seed", "42", "--scenario", scenario_pack, "--ticks", "3",
        env=_env_without_key(),
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 1, combined
    assert "under" in combined.lower() or "budget" in combined.lower(), combined


# ---------------------------------------------------------------------------
# bench --scenario is REJECTED (invariant 3)
# ---------------------------------------------------------------------------


def test_bench_scenario_rejected(scenario_pack: str) -> None:
    result = _run_aftershock(
        "bench", "--arms", "scripted", "--seeds", "42", "--ticks", "8",
        "--scenario", scenario_pack,
        env=_env_without_key(),
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 1, f"expected 1, got {result.returncode}\n{combined}"
    assert "scenario" in combined.lower(), combined
    assert "Traceback" not in combined, combined


def test_bench_scenario_rejected_even_unknown_id() -> None:
    """bench rejects --scenario before it even resolves the id."""
    result = _run_aftershock(
        "bench", "--arms", "scripted", "--seeds", "42", "--ticks", "8",
        "--scenario", "anything-goes",
        env=_env_without_key(),
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 1, combined
    assert "scenario" in combined.lower(), combined


# ---------------------------------------------------------------------------
# synthetic run still requires --ticks
# ---------------------------------------------------------------------------


def test_run_synthetic_requires_ticks() -> None:
    with tempfile.TemporaryDirectory() as td:
        result = _run_aftershock(
            "run", "--seed", "1", "--arm", "scripted", "--out", td,
            env=_env_without_key(),
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 1, combined
        assert "ticks" in combined.lower(), combined
