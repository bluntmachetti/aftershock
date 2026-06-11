"""Tests for the scenario-pack web API (web.py, task #4 additive surface).

Uses FastAPI TestClient against a tiny temp ``scenarios/`` fixture dir injected via
``create_app(..., scenarios_root=...)`` — these tests NEVER depend on the real SF/NYC
packs existing yet, and never touch the network (load_scenario is pure validation).

Covers:
  - GET /api/scenarios            list shape (id/name/hazard/tick_minutes/window/
                                  missions/sampling/source); compact source fields
  - GET /api/scenarios/{id}       full pack incl. reference; pack_digest stamped
  - GET /api/scenarios/{id}       404 for unknown id
  - path-traversal probes on the scenario id (../, encoded, absolute) -> 404, never 200
  - GET /api/scenarios            empty list when scenarios_root is missing/empty
  - POST /api/live                unknown scenario -> 404
  - POST /api/live                path-traversal scenario id -> 404
  - POST /api/live                valid scenario -> manifest scenario block + ticks
                                  default from the timeline when omitted
  - POST /api/live                explicit under/over ticks honored / capped
  - GET /api/runs + /api/runs/{id}   scenario block passthrough (compact / full)
  - existing endpoints unchanged when no scenario is involved
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aftershock.web import create_app

# ---------------------------------------------------------------------------
# Fixture pack builder (valid, minimal — never the real SF/NYC packs)
# ---------------------------------------------------------------------------


def _valid_pack(
    scenario_id: str = "fixture-pack", *, with_reference: bool = True
) -> dict[str, Any]:
    """A minimal pack that passes every ScenarioPack validator.

    Two mission timeline entries (last mission tick well under 104) + one blockage.
    ``with_reference`` toggles the dispatch-vs-hazard-only caveat path.
    """
    pack: dict[str, Any] = {
        "format_version": 1,
        "id": scenario_id,
        "name": "Fixture Disaster",
        "hazard": "hurricane_flood",
        "adapter": "fixture",
        "compiler_version": "deadbeef",
        "config_sha256": "0" * 64,
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
            "ambulance": {"size": 4, "basis": "calibrated", "note": "n/a"},
            "rescue_crew": {"size": 3, "basis": "calibrated", "note": "n/a"},
            "fire_engine": {"size": 3, "basis": "observed", "note": "n/a"},
            "repair_crew": {"size": 3, "basis": "calibrated", "note": "n/a"},
            "supply_truck": {"size": 3, "basis": "calibrated", "note": "n/a"},
        },
        "timeline": [
            {
                "tick": 5,
                "kind": "mission",
                "mission_kind": "medical_surge",
                "district_id": "residential_north",
                "severity": 4,
                "lives_at_risk": 16,
            },
            {
                "tick": 7,
                "kind": "mission",
                "mission_kind": "fire",
                "district_id": "harbor",
                "severity": 3,
                "lives_at_risk": 8,
            },
            {"tick": 9, "kind": "blockage", "district_id": "residential_north"},
        ],
        "field_provenance": {
            "tick": "real",
            "district_id": "real",
            "mission_kind": "mapped",
            "severity": "mapped",
            "lives_at_risk": "inferred",
            "blockage": "synthetic",
        },
        "mapping": {
            "version": "fixture-v1",
            "mission_kind": {"EMS medical": "medical_surge"},
            "severity_rule": "code 1-2 -> 5",
            "lives_rule": "lookup table",
        },
        "sampling": {
            "method": "stratified",
            "sample_seed": 4636,
            "kept": 2,
            "total": 200,
            "filter": "boroughs only",
        },
        "source": [
            {
                "dataset": "EMS Incident Dispatch Data",
                "provider": "FDNY via NYC Open Data",
                "dataset_id": "76xm-jjuj",
                "query_url": "https://example.test/resource/76xm-jjuj.json",
                "fetched_at": "2026-06-11",
                "rows_fetched": 2003,
                "license": "NYC Open Data terms",
                "license_url": "https://example.test/overview",
                "attribution": "FDNY via NYC Open Data",
            }
        ],
    }
    if with_reference:
        pack["reference"] = {
            "missions": {
                "0": {
                    "received": "2026-01-01T01:00:00-00:00",
                    "first_on_scene": "2026-01-01T01:15:42-00:00",
                    "latency_s": 942,
                }
            },
            "aggregates": {
                "mean_latency_s": 948,
                "median_latency_s": 900,
                "held_rate": 0.165,
            },
        }
    return pack


def _write_pack(scenarios_root: Path, scenario_id: str, **kwargs: Any) -> Path:
    """Write a valid pack into scenarios_root/<id>/scenario.json and return the dir."""
    scenario_dir = scenarios_root / scenario_id
    scenario_dir.mkdir(parents=True, exist_ok=True)
    pack = _valid_pack(scenario_id, **kwargs)
    (scenario_dir / "scenario.json").write_text(json.dumps(pack), encoding="utf-8")
    return scenario_dir


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runs_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture()
def scenarios_root(tmp_path: Path) -> Path:
    root = tmp_path / "scenarios"
    root.mkdir()
    return root


@pytest.fixture()
def app_with_pack(runs_root: Path, scenarios_root: Path) -> Any:
    """create_app wired to a temp scenarios dir holding one valid 'fixture-pack'."""
    _write_pack(scenarios_root, "fixture-pack")
    return create_app(runs_root, scenarios_root=scenarios_root)


# ---------------------------------------------------------------------------
# GET /api/scenarios — list
# ---------------------------------------------------------------------------


def test_list_scenarios_shape(app_with_pack: Any) -> None:
    with TestClient(app_with_pack) as client:
        resp = client.get("/api/scenarios")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    entry = body[0]
    assert entry["id"] == "fixture-pack"
    assert entry["name"] == "Fixture Disaster"
    assert entry["hazard"] == "hurricane_flood"
    assert entry["tick_minutes"] == 12
    assert entry["window"] == {
        "start": "2026-01-01T00:00:00-00:00",
        "end": "2026-01-01T12:00:00-00:00",
    }
    # two mission entries (the blockage is not a mission)
    assert entry["missions"] == 2
    assert entry["sampling"] == {"kept": 2, "total": 200}
    # source is compact: exactly dataset/provider/license/attribution
    assert len(entry["source"]) == 1
    src = entry["source"][0]
    assert set(src.keys()) == {"dataset", "provider", "license", "attribution"}
    assert src["provider"] == "FDNY via NYC Open Data"
    assert src["attribution"] == "FDNY via NYC Open Data"


def test_list_scenarios_empty_when_root_missing(runs_root: Path, tmp_path: Path) -> None:
    missing = tmp_path / "no-such-scenarios"
    app = create_app(runs_root, scenarios_root=missing)
    with TestClient(app) as client:
        resp = client.get("/api/scenarios")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_scenarios_empty_dir(runs_root: Path, scenarios_root: Path) -> None:
    app = create_app(runs_root, scenarios_root=scenarios_root)
    with TestClient(app) as client:
        resp = client.get("/api/scenarios")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_scenarios_skips_malformed(
    runs_root: Path, scenarios_root: Path
) -> None:
    _write_pack(scenarios_root, "good-pack")
    bad_dir = scenarios_root / "bad-pack"
    bad_dir.mkdir()
    (bad_dir / "scenario.json").write_text("{ not valid json", encoding="utf-8")
    app = create_app(runs_root, scenarios_root=scenarios_root)
    with TestClient(app) as client:
        resp = client.get("/api/scenarios")
    assert resp.status_code == 200
    ids = [e["id"] for e in resp.json()]
    assert ids == ["good-pack"]


# ---------------------------------------------------------------------------
# GET /api/scenarios/{id} — detail
# ---------------------------------------------------------------------------


def test_scenario_detail_full_pack(app_with_pack: Any) -> None:
    with TestClient(app_with_pack) as client:
        resp = client.get("/api/scenarios/fixture-pack")
    assert resp.status_code == 200
    pack = resp.json()
    assert pack["id"] == "fixture-pack"
    # full pack includes reference (RealityStrip data source)
    assert "reference" in pack
    assert pack["reference"]["missions"]["0"]["latency_s"] == 942
    assert pack["reference"]["aggregates"]["mean_latency_s"] == 948
    # pack_digest is stamped at load (64-hex sha256 of raw bytes)
    assert isinstance(pack["pack_digest"], str)
    assert len(pack["pack_digest"]) == 64
    # full pack carries mapping + field_provenance
    assert pack["mapping"]["version"] == "fixture-v1"
    assert pack["field_provenance"]["lives_at_risk"] == "inferred"


def test_scenario_detail_unknown_404(app_with_pack: Any) -> None:
    with TestClient(app_with_pack) as client:
        resp = client.get("/api/scenarios/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Path-traversal probes on the scenario id -> 404, NEVER 200
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_id",
    [
        "../etc",
        "../../etc/passwd",
        "..%2f..%2fetc",
        "%2e%2e%2f",
        "foo/../../bar",
        "..",
        "UPPER",  # uppercase violates ^[a-z0-9][a-z0-9-]*$
        "with space",
        "_leading-underscore",
        "trailing/",
    ],
)
def test_scenario_detail_traversal_404(app_with_pack: Any, raw_id: str) -> None:
    with TestClient(app_with_pack) as client:
        resp = client.get(f"/api/scenarios/{raw_id}")
    assert resp.status_code in (404, 422)
    assert resp.status_code != 200


def test_scenario_detail_dot_never_leaks_pack(app_with_pack: Any) -> None:
    """``GET /api/scenarios/.`` is normalized by the HTTP layer to the LIST endpoint
    (``/api/scenarios/``); it must never resolve to a pack DETAIL (a dict with ``id``).
    The security property is "no pack content escapes via a single-dot id", not a
    specific status code (the normalized list returns 200)."""
    with TestClient(app_with_pack) as client:
        resp = client.get("/api/scenarios/.")
    body = resp.json()
    # a list == the LIST endpoint (safe); a dict == a leaked pack detail (forbidden)
    assert not isinstance(body, dict), "scenario id '.' must not resolve to a pack detail"


def test_scenario_detail_sibling_dir_not_reachable(
    runs_root: Path, scenarios_root: Path, tmp_path: Path
) -> None:
    """A real scenario.json OUTSIDE scenarios_root must not be reachable via traversal."""
    _write_pack(scenarios_root, "fixture-pack")
    # a sibling 'secret' dir at the tmp_path level (outside scenarios_root)
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "scenario.json").write_text(json.dumps(_valid_pack("secret")), encoding="utf-8")
    app = create_app(runs_root, scenarios_root=scenarios_root)
    with TestClient(app) as client:
        # even URL-encoded traversal must not escape scenarios_root
        for probe in ("..%2fsecret", "../secret"):
            resp = client.get(f"/api/scenarios/{probe}")
            assert resp.status_code != 200


# ---------------------------------------------------------------------------
# POST /api/live — scenario id resolution
# ---------------------------------------------------------------------------


def test_live_unknown_scenario_404(app_with_pack: Any) -> None:
    with TestClient(app_with_pack) as client:
        resp = client.post(
            "/api/live", json={"arm": "scripted", "seed": 1, "scenario": "nope"}
        )
    assert resp.status_code == 404


@pytest.mark.parametrize("probe", ["../etc", "..%2f..", "UPPER", ".", ".."])
def test_live_traversal_scenario_404(app_with_pack: Any, probe: str) -> None:
    with TestClient(app_with_pack) as client:
        resp = client.post(
            "/api/live", json={"arm": "scripted", "seed": 1, "scenario": probe}
        )
    assert resp.status_code != 200
    assert resp.status_code in (404, 422)


def test_live_scenario_default_ticks_and_manifest(
    runs_root: Path, scenarios_root: Path
) -> None:
    """Valid scenario, ticks omitted -> server default min(last tick + 20, 120), and the
    run manifest carries the full scenario block."""
    _write_pack(scenarios_root, "fixture-pack")
    app = create_app(runs_root, scenarios_root=scenarios_root)
    with TestClient(app) as client:
        resp = client.post(
            "/api/live", json={"arm": "scripted", "seed": 5, "scenario": "fixture-pack"}
        )
        assert resp.status_code == 200, resp.text
        # let the background task finish (scripted is fast)
        time.sleep(0.6)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            status = client.get("/api/live").json()
            if not status["running"]:
                break
            time.sleep(0.1)

    # the run.json manifest carries the scenario block + the computed ticks default
    run_dirs = [d for d in runs_root.iterdir() if d.is_dir() and (d / "run.json").exists()]
    assert run_dirs, "no run dir written"
    manifest = json.loads((run_dirs[0] / "run.json").read_text(encoding="utf-8"))
    # last_timeline_tick is the max across ALL entries (the blockage at tick 9),
    # margin 20 -> 29 (DESIGN.md: "min(last timeline tick + 20, 120)").
    assert manifest["ticks"] == 29
    block = manifest["scenario"]
    assert block["id"] == "fixture-pack"
    assert block["name"] == "Fixture Disaster"
    assert block["hazard"] == "hurricane_flood"
    assert block["tick_minutes"] == 12
    assert len(block["pack_digest"]) == 64
    assert block["config_sha256"] == "0" * 64
    # dispatch pack (has reference.missions) -> the real-latency caveat line
    assert block["caveat_line"] == (
        "Demand: real · Latency baseline: real · Lives & outcomes: simulated model."
    )
    assert block["field_provenance"]["lives_at_risk"] == "inferred"
    assert block["reference_aggregates"]["mean_latency_s"] == 948
    assert block["source"][0]["dataset_id"] == "76xm-jjuj"


def test_live_scenario_hazard_only_caveat(
    runs_root: Path, scenarios_root: Path
) -> None:
    """A pack with no reference.missions gets the hazard-timing-only caveat line."""
    _write_pack(scenarios_root, "hazard-pack", with_reference=False)
    app = create_app(runs_root, scenarios_root=scenarios_root)
    with TestClient(app) as client:
        resp = client.post(
            "/api/live", json={"arm": "scripted", "seed": 9, "scenario": "hazard-pack"}
        )
        assert resp.status_code == 200, resp.text
        time.sleep(0.6)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if not client.get("/api/live").json()["running"]:
                break
            time.sleep(0.1)
    run_dirs = [d for d in runs_root.iterdir() if d.is_dir() and (d / "run.json").exists()]
    manifest = json.loads((run_dirs[0] / "run.json").read_text(encoding="utf-8"))
    assert manifest["scenario"]["caveat_line"] == (
        "Hazard timing: real · Demand & outcomes: simulated model."
    )


def test_live_scenario_explicit_under_budget_ticks_honored(
    runs_root: Path, scenarios_root: Path
) -> None:
    """An explicit ticks value is honored verbatim (not auto-prefilled)."""
    _write_pack(scenarios_root, "fixture-pack")
    app = create_app(runs_root, scenarios_root=scenarios_root)
    with TestClient(app) as client:
        resp = client.post(
            "/api/live",
            json={"arm": "scripted", "seed": 3, "scenario": "fixture-pack", "ticks": 30},
        )
        assert resp.status_code == 200, resp.text
        time.sleep(0.6)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if not client.get("/api/live").json()["running"]:
                break
            time.sleep(0.1)
    run_dirs = [d for d in runs_root.iterdir() if d.is_dir() and (d / "run.json").exists()]
    manifest = json.loads((run_dirs[0] / "run.json").read_text(encoding="utf-8"))
    assert manifest["ticks"] == 30


def test_live_explicit_ticks_over_cap_422(app_with_pack: Any) -> None:
    with TestClient(app_with_pack) as client:
        resp = client.post(
            "/api/live",
            json={"arm": "scripted", "seed": 1, "scenario": "fixture-pack", "ticks": 121},
        )
    assert resp.status_code == 422


def test_live_scenario_explicit_under_budget_ticks_422(app_with_pack: Any) -> None:
    """An explicit under-budget ticks value for a scenario run is a 422 (would
    silently truncate the real timeline). The fixture-pack budget is
    min(last timeline tick 9 + 20, 120) = 29, so ticks=5 is under budget."""
    with TestClient(app_with_pack) as client:
        resp = client.post(
            "/api/live",
            json={"arm": "scripted", "seed": 1, "scenario": "fixture-pack", "ticks": 5},
        )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "under the scenario budget" in detail
    assert "29" in detail


# ---------------------------------------------------------------------------
# /api/runs + /api/runs/{id} scenario passthrough
# ---------------------------------------------------------------------------


def test_runs_scenario_passthrough(runs_root: Path, scenarios_root: Path) -> None:
    """After a scenario live run, /api/runs carries the compact block and
    /api/runs/{id} carries the full block."""
    _write_pack(scenarios_root, "fixture-pack")
    app = create_app(runs_root, scenarios_root=scenarios_root)
    with TestClient(app) as client:
        resp = client.post(
            "/api/live", json={"arm": "scripted", "seed": 11, "scenario": "fixture-pack"}
        )
        assert resp.status_code == 200, resp.text
        time.sleep(0.6)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if not client.get("/api/live").json()["running"]:
                break
            time.sleep(0.1)

        runs = client.get("/api/runs").json()
        assert runs, "no runs listed"
        compact = runs[0]["scenario"]
        assert compact == {
            "id": "fixture-pack",
            "name": "Fixture Disaster",
            "hazard": "hurricane_flood",
        }

        run_id = runs[0]["run_id"]
        detail = client.get(f"/api/runs/{run_id}").json()
        full = detail["scenario"]
        # full block has the provenance fields the compact view drops
        assert full["caveat_line"]
        assert full["pack_digest"]
        assert full["config_sha256"] == "0" * 64
        assert "field_provenance" in full


# ---------------------------------------------------------------------------
# Existing endpoints unchanged when no scenario is involved
# ---------------------------------------------------------------------------


def test_synthetic_run_has_null_scenario(runs_root: Path, scenarios_root: Path) -> None:
    """A synthetic live run (no scenario) -> run rows + detail report scenario: null,
    and ticks defaults to 30."""
    app = create_app(runs_root, scenarios_root=scenarios_root)
    with TestClient(app) as client:
        resp = client.post("/api/live", json={"arm": "scripted", "seed": 2})
        assert resp.status_code == 200, resp.text
        time.sleep(0.6)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if not client.get("/api/live").json()["running"]:
                break
            time.sleep(0.1)

        runs = client.get("/api/runs").json()
        assert runs
        assert runs[0]["scenario"] is None
        run_id = runs[0]["run_id"]
        detail = client.get(f"/api/runs/{run_id}").json()
        assert detail["scenario"] is None

    run_dirs = [d for d in runs_root.iterdir() if d.is_dir() and (d / "run.json").exists()]
    manifest = json.loads((run_dirs[0] / "run.json").read_text(encoding="utf-8"))
    assert manifest["ticks"] == 30
    assert "scenario" not in manifest


def test_synthetic_explicit_ticks_still_honored(runs_root: Path) -> None:
    """The 'ticks: 30' explicit case is distinguishable from omitted (both -> 30 here,
    but an explicit small value must not be overridden)."""
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.post("/api/live", json={"arm": "scripted", "seed": 4, "ticks": 6})
        assert resp.status_code == 200, resp.text
        time.sleep(0.6)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if not client.get("/api/live").json()["running"]:
                break
            time.sleep(0.1)
    run_dirs = [d for d in runs_root.iterdir() if d.is_dir() and (d / "run.json").exists()]
    manifest = json.loads((run_dirs[0] / "run.json").read_text(encoding="utf-8"))
    assert manifest["ticks"] == 6
