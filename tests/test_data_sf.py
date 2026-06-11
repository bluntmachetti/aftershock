"""Tests for the SF scenario compiler (aftershock.data) — NO NETWORK.

Everything runs against committed fixture slices under tests/fixtures/data/sf/:
  rows.json     — a small (26-row) slice of the real nuek-vuh3 extract
  manifest.json — frozen fetch metadata (mirrors raw/manifest.json)
  config.yaml   — fixture adapter config (real config, id=sf-fixture, target=8)
  golden_scenario.json — the expected byte-identical compiler output

Covers: aggregate gotchas (junk battalion drop, MIN on_scene with null-drop,
multi-unit roster, original_priority), golden byte-identity (recompile from
identical raw + config -> identical scenario.json), sampling determinism (same
sample_seed -> same kept set), and that the emitted pack loads via load_scenario.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aftershock.data import compile_scenario, config_sha256, load_config
from aftershock.data.adapters.sf import SFAdapter
from aftershock.town.scenario import load_scenario, town_from_scenario

_FIX = Path(__file__).parent / "fixtures" / "data" / "sf"
_PINNED_COMPILER_VERSION = "test-sf-fixture"


def _fixture_rows() -> list[dict]:
    return json.loads((_FIX / "rows.json").read_text(encoding="utf-8"))


def _fixture_config() -> dict:
    return load_config(_FIX / "config.yaml")


def _fixture_manifest() -> dict:
    return json.loads((_FIX / "manifest.json").read_text(encoding="utf-8"))


def _seed_raw(tmp_path: Path) -> Path:
    """Stage the fixture as a raw/ cache so compile_scenario(fetch=False) runs."""
    out = tmp_path / "sf-fixture"
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
        adapter_name="sf",
        config_path=_FIX / "config.yaml",
        out_dir=out,
        fetch=False,
        compiler_version_override=_PINNED_COMPILER_VERSION,
    )


# ---------------------------------------------------------------------------
# Aggregate gotchas (no network)
# ---------------------------------------------------------------------------


def test_aggregate_drops_junk_battalions():
    adapter = SFAdapter()
    rows = _fixture_rows()
    agg = adapter.aggregate(rows, _fixture_config())
    # The fixture contains B99 junk rows; they must be dropped, not aggregated.
    assert agg.dropped_junk_battalion >= 1
    assert agg.raw_unit_rows == len(rows)
    # No incident may carry a junk battalion district.
    for inc in agg.incidents:
        assert inc.district_id in {
            "old_town", "harbor", "hospital_district",
            "market", "residential_north", "industrial",
        }


def test_aggregate_first_on_scene_is_min_nulls_dropped():
    adapter = SFAdapter()
    agg = adapter.aggregate(_fixture_rows(), _fixture_config())
    by_call = {inc.call_number: inc for inc in agg.incidents}

    # Recompute expected first_on_scene independently from the raw rows.
    raw_by_call: dict[str, list[dict]] = {}
    for r in _fixture_rows():
        raw_by_call.setdefault(r["call_number"], []).append(r)

    for call_number, inc in by_call.items():
        scenes = [
            r.get("on_scene_dttm")
            for r in raw_by_call[call_number]
            if r.get("on_scene_dttm")
        ]
        if scenes:
            expected = min(scenes)
            # adapter stores with .%f format; compare on the second-resolution prefix
            assert inc.first_on_scene is not None
            assert inc.first_on_scene[:19] == expected[:19]
        else:
            assert inc.first_on_scene is None


def test_aggregate_all_null_on_scene_yields_none():
    """An incident whose every unit lacks on_scene_dttm has no arrival."""
    adapter = SFAdapter()
    agg = adapter.aggregate(_fixture_rows(), _fixture_config())
    null_incidents = [i for i in agg.incidents if i.first_on_scene is None]
    assert null_incidents, "fixture should contain an all-null-on_scene incident"


def test_aggregate_multi_unit_roster():
    """Multi-unit calls collapse to one incident with the full unit_type set."""
    adapter = SFAdapter()
    agg = adapter.aggregate(_fixture_rows(), _fixture_config())
    multi = [i for i in agg.incidents if len(i.units) > 1]
    assert multi, "fixture should contain a multi-unit incident"
    for inc in multi:
        # roster is a sorted, deduped tuple of unit types
        assert list(inc.units) == sorted(set(inc.units))


def test_aggregate_uses_original_priority_not_final():
    """original_priority carries the {1,2,3,A,B,C,E,I,T} grammar (severity input)."""
    adapter = SFAdapter()
    agg = adapter.aggregate(_fixture_rows(), _fixture_config())
    priorities = {i.original_priority for i in agg.incidents}
    # final_priority collapses to {2,3}; original keeps a richer set.
    assert priorities - {"2", "3"}, (
        "expected at least one non-{2,3} original_priority in the fixture"
    )


# ---------------------------------------------------------------------------
# Discretize: kind mapping, severity, lives, budget
# ---------------------------------------------------------------------------


def test_discretize_all_kinds_and_districts_present(tmp_path):
    pack = _compile(tmp_path).pack
    kinds = {e["mission_kind"] for e in pack["timeline"]}
    assert kinds == {"collapse_rescue", "fire", "medical_surge", "infra_repair"}
    districts = {e["district_id"] for e in pack["timeline"]}
    assert districts <= {
        "old_town", "harbor", "hospital_district",
        "market", "residential_north", "industrial",
    }


def test_discretize_severity_and_lives_in_range(tmp_path):
    pack = _compile(tmp_path).pack
    for e in pack["timeline"]:
        assert 1 <= e["severity"] <= 5
        assert 1 <= e["lives_at_risk"] <= 64


def test_discretize_tick_budget_holds(tmp_path):
    pack = _compile(tmp_path).pack
    mission_ticks = [e["tick"] for e in pack["timeline"] if e["kind"] == "mission"]
    if mission_ticks:
        # last mission tick + max(DEADLINE_TICKS)=16 <= 120
        assert max(mission_ticks) + 16 <= 120


def test_reference_aggregates_over_full_window(tmp_path):
    """mean AND median latency emitted, computed over the full filtered window."""
    pack = _compile(tmp_path).pack
    agg = pack["reference"]["aggregates"]
    assert agg["mean_latency_s"] is not None
    assert agg["median_latency_s"] is not None
    # n_incidents (full window) must exceed the sampled mission count.
    assert agg["n_incidents"] >= pack["sampling"]["kept"]
    # SF is the routine pack: held_rate is null (nuek-vuh3 has no held signal),
    # and it declares NO baseline comparison (no baseline_window / baseline_note).
    assert agg["held_rate"] is None
    assert "baseline_window" not in agg
    assert "baseline_note" not in agg
    assert agg["baseline_mean_latency_s"] is None
    assert agg["baseline_held_rate"] is None


def test_pools_all_calibrated_for_sf(tmp_path):
    pack = _compile(tmp_path).pack
    pools = pack["pools"]
    assert set(pools) == {
        "ambulance", "rescue_crew", "fire_engine", "repair_crew", "supply_truck",
    }
    # SF pool sizes all collapse to clamped constants (the 0.08 sampling ratio is
    # never applied), so NONE are genuinely observed -> every SF pool is calibrated.
    for rk, p in pools.items():
        assert p["basis"] == "calibrated", f"{rk} should be calibrated, not observed"
        assert "0.08" not in p["note"], f"{rk} note must not advertise the unused ratio"
        assert 1 <= p["size"] <= 12


# ---------------------------------------------------------------------------
# Sampling determinism
# ---------------------------------------------------------------------------


def test_sampling_deterministic_same_seed(tmp_path):
    """Same sample_seed -> identical kept set (by district/kind/tick signature)."""
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


def test_sampling_keeps_target_count(tmp_path):
    pack = _compile(tmp_path).pack
    cfg = _fixture_config()
    target = cfg["sampling"]["target_missions"]
    # kept == min(target, total mapped incidents)
    assert pack["sampling"]["kept"] == min(target, pack["sampling"]["total"])
    assert pack["sampling"]["kept"] == len(pack["timeline"])


def test_sampling_seed_change_changes_set():
    """A different seed selects a different (or differently-ordered) kept set."""
    adapter = SFAdapter()
    cfg = load_config(_FIX / "config.yaml")
    agg = adapter.aggregate(_fixture_rows(), cfg)
    disc1 = adapter.discretize(agg, cfg, _fixture_manifest())
    cfg2 = load_config(_FIX / "config.yaml")
    cfg2["sampling"]["sample_seed"] = cfg["sampling"]["sample_seed"] + 1
    disc2 = adapter.discretize(agg, cfg2, _fixture_manifest())
    sig1 = [(e["tick"], e["mission_kind"], e["district_id"]) for e in disc1.timeline]
    sig2 = [(e["tick"], e["mission_kind"], e["district_id"]) for e in disc2.timeline]
    # Both keep the same count; the selected set differs for at least one seed.
    assert len(sig1) == len(sig2)
    # (Not a hard guarantee for every pair, but holds for these two seeds.)
    assert sig1 != sig2


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
    """The fixture config's sha256 is what the golden pack records."""
    golden = json.loads((_FIX / "golden_scenario.json").read_text(encoding="utf-8"))
    assert golden["config_sha256"] == config_sha256(_FIX / "config.yaml")


# ---------------------------------------------------------------------------
# Emitted pack loads through the engine-side loader
# ---------------------------------------------------------------------------


def test_emitted_pack_loads_via_load_scenario(tmp_path):
    _compile(tmp_path)
    scenario_path = (tmp_path / "sf-fixture" / "scenario.json")
    pack = load_scenario(scenario_path)
    assert pack.id == "sf-fixture"
    assert pack.adapter == "sf"
    assert len(pack.pack_digest) == 64
    # town factory builds a valid TownState with pack display names.
    town = town_from_scenario(pack, seed=7)
    assert town.seed == 7
    assert len(town.districts) == 6
    assert all(p.total == p.available for p in town.pools.values())
    assert len(town.timeline) == len(pack.timeline)


def test_committed_pack_loads_and_is_real():
    """The shipped scenarios/sf-routine-2018 pack loads and is built from real
    fetched rows (rows_fetched matches the source provenance)."""
    repo_root = Path(__file__).parent.parent
    pack_path = repo_root / "scenarios" / "sf-routine-2018" / "scenario.json"
    if not pack_path.is_file():
        pytest.skip("committed pack not present in this checkout")
    pack = load_scenario(pack_path)
    assert pack.id == "sf-routine-2018"
    assert pack.adapter == "sf"
    assert pack.source[0].provider.startswith("DataSF")
    assert pack.source[0].rows_fetched > 0
    assert "pddl" in pack.source[0].license.lower()
    n_missions = sum(1 for e in pack.timeline if e.kind == "mission")
    assert n_missions == pack.sampling.kept
