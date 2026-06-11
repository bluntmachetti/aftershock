"""Tests for the NYC Ida scenario compiler (aftershock.data) — NO NETWORK.

Everything runs against committed fixture slices under tests/fixtures/data/nyc/:
  rows.json     — a small JOINED {ems, fire} slice of the real Ida extract
                  (11 EMS + 10 Fire per-incident rows)
  manifest.json — frozen fetch metadata (mirrors raw/manifest.json)
  config.yaml   — fixture adapter config (real config, id=nyc-fixture, target=8)
  golden_scenario.json — the expected byte-identical compiler output

Covers: EMS+Fire join (two sources), EMS severity 1-8 -> 1-5 rebinning, Fire
severity from engines-assigned quantiles (never highest_alarm_level),
validity-flag filtering (valid_*_indc), the borough -> six-slot map incl. the
Brooklyn West/East split, the FULL-EMS-window reality baseline (held-rate +
mean/median latency, not the mission subset), the named Ida-adjacent baseline
window, golden byte-identity, and that the emitted pack loads via load_scenario.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aftershock.data import compile_scenario, config_sha256, load_config
from aftershock.data.adapters.nyc import NYCAdapter
from aftershock.town.scenario import load_scenario, town_from_scenario

_FIX = Path(__file__).parent / "fixtures" / "data" / "nyc"
_PINNED_COMPILER_VERSION = "test-nyc-fixture"

_CANON = {
    "old_town", "harbor", "hospital_district",
    "market", "residential_north", "industrial",
}


def _fixture_rows() -> dict:
    return json.loads((_FIX / "rows.json").read_text(encoding="utf-8"))


def _fixture_config() -> dict:
    return load_config(_FIX / "config.yaml")


def _fixture_manifest() -> dict:
    return json.loads((_FIX / "manifest.json").read_text(encoding="utf-8"))


def _seed_raw(tmp_path: Path) -> Path:
    """Stage the fixture as a raw/ cache so compile_scenario(fetch=False) runs."""
    out = tmp_path / "nyc-fixture"
    raw = out / "raw"
    raw.mkdir(parents=True)
    (raw / "rows.json").write_text(
        (_FIX / "rows.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (raw / "manifest.json").write_text(
        (_FIX / "manifest.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return out


def _compile(tmp_path: Path):
    out = _seed_raw(tmp_path)
    return compile_scenario(
        adapter_name="nyc",
        config_path=_FIX / "config.yaml",
        out_dir=out,
        fetch=False,
        compiler_version_override=_PINNED_COMPILER_VERSION,
    )


# ---------------------------------------------------------------------------
# Aggregate: the EMS + Fire join + borough slots (no network)
# ---------------------------------------------------------------------------


def test_aggregate_joins_ems_and_fire():
    """Both per-incident datasets are folded into one Incident stream."""
    adapter = NYCAdapter()
    rows = _fixture_rows()
    agg = adapter.aggregate(rows, _fixture_config())
    groups = {i.call_type_group for i in agg.incidents}
    assert "EMS" in groups, "EMS incidents must be present"
    assert "FIRE" in groups, "Fire incidents must be present"
    # raw_unit_rows counts both upstream slices.
    assert agg.raw_unit_rows == len(rows["ems"]) + len(rows["fire"])


def test_aggregate_all_districts_are_canonical():
    adapter = NYCAdapter()
    agg = adapter.aggregate(_fixture_rows(), _fixture_config())
    for inc in agg.incidents:
        assert inc.district_id in _CANON


def test_aggregate_brooklyn_split_west_and_east():
    """Brooklyn splits across two canonical slots (market / industrial)."""
    adapter = NYCAdapter()
    cfg = _fixture_config()
    agg = adapter.aggregate(_fixture_rows(), cfg)
    # EMS Brooklyn rows: K1-K4 -> market (west), K5-K7 -> industrial (east).
    ems = {r["incident_id"]: r for r in _fixture_rows()["ems"]}
    for inc in agg.incidents:
        if inc.call_type_group != "EMS":
            continue
        r = ems.get(inc.call_number)
        if r is None or (r.get("borough") or "").upper() != "BROOKLYN":
            continue
        area = (r.get("incident_dispatch_area") or "").upper()
        if area in {"K1", "K2", "K3", "K4"}:
            assert inc.district_id == "market"
        else:
            assert inc.district_id == "industrial"
    # The fixture must actually contain both a west and an east Brooklyn EMS row.
    bk_slots = {
        inc.district_id
        for inc in agg.incidents
        if inc.call_type_group == "EMS"
        and (ems.get(inc.call_number, {}).get("borough") or "").upper() == "BROOKLYN"
    }
    assert {"market", "industrial"} <= bk_slots


def test_aggregate_borough_display_names():
    """The six slots render with NYC borough display names."""
    pack = _compile_pack_via_adapter()
    name_by_id = {d["id"]: d["name"] for d in pack["districts"]}
    assert name_by_id["old_town"] == "Manhattan"
    assert name_by_id["harbor"] == "Staten Island"
    assert name_by_id["hospital_district"] == "Bronx"
    assert name_by_id["market"] == "Brooklyn West"
    assert name_by_id["residential_north"] == "Queens"
    assert name_by_id["industrial"] == "Brooklyn East"


def _compile_pack_via_adapter() -> dict:
    adapter = NYCAdapter()
    cfg = _fixture_config()
    agg = adapter.aggregate(_fixture_rows(), cfg)
    disc = adapter.discretize(agg, cfg, _fixture_manifest())
    return {"districts": disc.districts}


# ---------------------------------------------------------------------------
# Discretize: severity rebinning, validity filtering, kind mapping
# ---------------------------------------------------------------------------


def test_ems_severity_rebin_1_8_to_1_5(tmp_path):
    """EMS codes 1-2 -> 5, 3 -> 4; codes 4-8 are excluded by the filter."""
    pack = _compile(tmp_path).pack
    ems_missions = [
        e for e in pack["timeline"]
        if e["kind"] == "mission" and e["mission_kind"] == "medical_surge"
    ]
    assert ems_missions, "fixture must yield EMS (medical_surge) missions"
    for e in ems_missions:
        # rebinned EMS severity is always 4 or 5 (codes 1-3 only).
        assert e["severity"] in (4, 5)


def test_ems_low_acuity_codes_excluded_from_missions():
    """Severity codes 4-8 never become missions (only the high-acuity tail does)."""
    adapter = NYCAdapter()
    cfg = _fixture_config()
    agg = adapter.aggregate(_fixture_rows(), cfg)
    disc = adapter.discretize(agg, cfg, _fixture_manifest())
    ems = {r["incident_id"]: r for r in _fixture_rows()["ems"]}
    # Build the set of EMS incident_ids that became missions (medical_surge).
    # The fixture contains severity-4 and severity-6 EMS rows; none may appear.
    low_acuity_ids = {
        r["incident_id"]
        for r in _fixture_rows()["ems"]
        if (r.get("initial_severity_level_code") or "") not in {"1", "2", "3"}
    }
    assert low_acuity_ids, "fixture must contain low-acuity EMS rows"
    # No timeline mission can come from a low-acuity EMS row. We can only verify
    # indirectly: every medical_surge mission's severity is 4/5 (checked above),
    # and the count of medical_surge missions <= count of high-acuity EMS rows.
    high_acuity = sum(
        1 for r in _fixture_rows()["ems"]
        if (r.get("initial_severity_level_code") or "") in {"1", "2", "3"}
    )
    n_med = sum(
        1 for e in disc.timeline
        if e["mission_kind"] == "medical_surge"
    )
    assert n_med <= high_acuity
    assert len(ems) == len(_fixture_rows()["ems"])  # join sanity


def test_fire_severity_from_engines_not_alarm_level(tmp_path):
    """Fire severity comes from engines-assigned quantiles, never alarm level."""
    pack = _compile(tmp_path).pack
    rule = pack["mapping"]["severity_rule"].lower()
    assert "engines" in rule
    assert "highest_alarm_level" in rule  # explicitly says NEVER use it
    assert "never" in rule
    fire_missions = [
        e for e in pack["timeline"]
        if e["mission_kind"] in ("fire", "infra_repair")
    ]
    for e in fire_missions:
        assert 1 <= e["severity"] <= 5


def test_validity_flag_filters_latency():
    """Response latency is only taken when valid_incident_rspns_time_indc=Y."""
    adapter = NYCAdapter()
    cfg = _fixture_config()
    agg = adapter.aggregate(_fixture_rows(), cfg)
    # number_of_alarms carries latency (>=0) or -1 when invalid/missing.
    by_call = {i.call_number: i for i in agg.incidents}
    for r in _fixture_rows()["ems"]:
        inc = by_call.get(r["incident_id"])
        if inc is None:
            continue
        valid = (r.get("valid_incident_rspns_time_indc") or "").upper() == "Y"
        if not valid:
            assert inc.number_of_alarms == -1, (
                "invalid-response EMS row must not contribute a latency"
            )


def test_no_collapse_rescue_kind_in_nyc(tmp_path):
    """NYC datasets feed only medical_surge/fire/infra_repair (honest mapping)."""
    pack = _compile(tmp_path).pack
    kinds = {e["mission_kind"] for e in pack["timeline"] if e["kind"] == "mission"}
    assert kinds <= {"medical_surge", "fire", "infra_repair"}


# ---------------------------------------------------------------------------
# Reality baseline (full EMS window) + named Ida-adjacent baseline window
# ---------------------------------------------------------------------------


def test_reference_aggregates_full_ems_window(tmp_path):
    """held_rate + mean/median latency are over the FULL EMS window, not sample."""
    pack = _compile(tmp_path).pack
    agg = pack["reference"]["aggregates"]
    assert agg["mean_latency_s"] is not None
    assert agg["median_latency_s"] is not None
    # n_ems_window = every EMS row in the window (>= the sampled mission count).
    assert agg["n_ems_window"] == len(_fixture_rows()["ems"])
    assert agg["n_ems_window"] >= pack["sampling"]["kept"]
    # held_rate is computed over the EMS window.
    ems_rows = _fixture_rows()["ems"]
    held = sum(
        1 for r in ems_rows if (r.get("held_indicator") or "").upper() == "Y"
    )
    assert agg["held_rate"] == round(held / len(ems_rows), 4)


def test_baseline_window_is_named_and_not_pre_sandy(tmp_path):
    """The baseline is an Ida-adjacent calm window, NOT the 538s/6.9% pre-Sandy."""
    pack = _compile(tmp_path).pack
    agg = pack["reference"]["aggregates"]
    note = agg["baseline_note"]
    assert "2021-08-18" in note, "baseline window must be named (Ida-adjacent)"
    assert "2012" not in note, "must not reuse the pre-Sandy 2012 baseline"
    # baseline figures emitted (mean AND median), and distinct from 538/6.9%.
    assert agg["baseline_mean_latency_s"] is not None
    assert agg["baseline_median_latency_s"] is not None
    assert agg["baseline_mean_latency_s"] != 538
    assert agg["baseline_held_rate"] is not None


def test_mean_and_median_both_emitted(tmp_path):
    pack = _compile(tmp_path).pack
    agg = pack["reference"]["aggregates"]
    assert "mean_latency_s" in agg and "median_latency_s" in agg
    assert agg["mean_latency_s"] is not None
    assert agg["median_latency_s"] is not None


# ---------------------------------------------------------------------------
# Pools: fire_engine observed, ambulance calibrated against held saturation
# ---------------------------------------------------------------------------


def test_pools_fire_observed_ambulance_calibrated(tmp_path):
    pack = _compile(tmp_path).pack
    pools = pack["pools"]
    assert set(pools) == {
        "ambulance", "rescue_crew", "fire_engine", "repair_crew", "supply_truck",
    }
    assert pools["fire_engine"]["basis"] == "observed"
    assert "engines_assigned" in pools["fire_engine"]["note"]
    assert pools["ambulance"]["basis"] == "calibrated"
    assert "held" in pools["ambulance"]["note"].lower()
    for p in pools.values():
        assert 1 <= p["size"] <= 12


# ---------------------------------------------------------------------------
# Sources, sampling, provenance
# ---------------------------------------------------------------------------


def test_two_sources_ems_and_fire(tmp_path):
    pack = _compile(tmp_path).pack
    src_ids = {s["dataset_id"] for s in pack["source"]}
    assert src_ids == {"76xm-jjuj", "8m42-w767"}
    for s in pack["source"]:
        assert s["provider"] == "FDNY via NYC Open Data"
        assert s["attribution"] == "FDNY via NYC Open Data"
        assert "NYC Open Data" in s["license"]
        assert s["rows_fetched"] > 0
        assert s["query_url"].startswith("https://data.cityofnewyork.us/")


def test_field_provenance_dispatch_pack(tmp_path):
    pack = _compile(tmp_path).pack
    fp = pack["field_provenance"]
    assert fp["tick"] == "real"
    assert fp["district_id"] == "real"
    assert fp["mission_kind"] == "mapped"
    assert fp["severity"] == "mapped"
    assert fp["lives_at_risk"] == "inferred"
    assert fp["blockage"] == "synthetic"


def test_sampling_recorded(tmp_path):
    pack = _compile(tmp_path).pack
    samp = pack["sampling"]
    assert samp["sample_seed"] == 4636
    assert samp["kept"] == min(samp["total"], 8)
    assert samp["kept"] == len(pack["timeline"])


def test_sampling_deterministic_same_seed(tmp_path):
    pack_a = _compile(tmp_path / "a").pack
    pack_b = _compile(tmp_path / "b").pack
    sig_a = [
        (e["tick"], e["mission_kind"], e["district_id"], e["severity"])
        for e in pack_a["timeline"]
    ]
    sig_b = [
        (e["tick"], e["mission_kind"], e["district_id"], e["severity"])
        for e in pack_b["timeline"]
    ]
    assert sig_a == sig_b


def test_discretize_tick_budget_holds(tmp_path):
    pack = _compile(tmp_path).pack
    mission_ticks = [
        e["tick"] for e in pack["timeline"] if e["kind"] == "mission"
    ]
    if mission_ticks:
        assert max(mission_ticks) + 16 <= 120


# ---------------------------------------------------------------------------
# Golden byte-identity
# ---------------------------------------------------------------------------


def test_golden_byte_identity(tmp_path):
    """Recompiling from identical raw + config yields byte-identical JSON."""
    result = _compile(tmp_path)
    golden = (_FIX / "golden_scenario.json").read_bytes()
    assert result.scenario_json_bytes == golden, (
        "compiler output drifted from the committed golden scenario.json; "
        "if the change is intentional, regenerate the golden fixture"
    )


def test_golden_config_sha_stable():
    golden = json.loads(
        (_FIX / "golden_scenario.json").read_text(encoding="utf-8")
    )
    assert golden["config_sha256"] == config_sha256(_FIX / "config.yaml")


# ---------------------------------------------------------------------------
# Emitted pack loads through the engine-side loader
# ---------------------------------------------------------------------------


def test_emitted_pack_loads_via_load_scenario(tmp_path):
    _compile(tmp_path)
    scenario_path = tmp_path / "nyc-fixture" / "scenario.json"
    pack = load_scenario(scenario_path)
    assert pack.id == "nyc-fixture"
    assert pack.adapter == "nyc"
    assert len(pack.pack_digest) == 64
    assert len(pack.source) == 2
    town = town_from_scenario(pack, seed=7)
    assert town.seed == 7
    assert len(town.districts) == 6
    assert all(p.total == p.available for p in town.pools.values())
    assert len(town.timeline) == len(pack.timeline)
    # reference mission keys index mission entries (injection-safe map).
    n_missions = sum(1 for e in pack.timeline if e.kind == "mission")
    for key in pack.reference.missions:
        assert 0 <= int(key) < n_missions


def test_committed_pack_loads_and_is_real():
    """The shipped scenarios/nyc-ida-2021 pack loads and is built from real
    fetched rows (EMS 2003 + Fire 2022, the verified Ida window)."""
    repo_root = Path(__file__).parent.parent
    pack_path = repo_root / "scenarios" / "nyc-ida-2021" / "scenario.json"
    if not pack_path.is_file():
        pytest.skip("committed pack not present in this checkout")
    pack = load_scenario(pack_path)
    assert pack.id == "nyc-ida-2021"
    assert pack.adapter == "nyc"
    assert pack.hazard == "hurricane_flood"
    src_ids = {s.dataset_id for s in pack.source}
    assert src_ids == {"76xm-jjuj", "8m42-w767"}
    for s in pack.source:
        assert s.provider == "FDNY via NYC Open Data"
        assert s.rows_fetched > 0
    # The headline reality baseline reproduces the verified Ida figures.
    agg = pack.reference.aggregates
    assert agg["n_ems_window"] == 2003
    assert agg["mean_latency_s"] == 948
    assert agg["held_rate"] == pytest.approx(0.165, abs=0.002)
    assert "2021-08-18" in agg["baseline_note"]
    n_missions = sum(1 for e in pack.timeline if e.kind == "mission")
    assert n_missions == pack.sampling.kept
