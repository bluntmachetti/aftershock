"""Tests for town/scenario.py: pydantic validation + town_from_scenario factory.

All fixtures are built inline (no network, no committed real packs). The base
fixture is a minimal-but-valid pack; rejection tests mutate one field at a time.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from aftershock.town.scenario import (
    CANONICAL_DISTRICT_IDS,
    MAX_DEADLINE_TICKS,
    RESOURCE_KIND_VALUES,
    ScenarioPack,
    last_timeline_tick,
    load_scenario,
    town_from_scenario,
)
from aftershock.town.state import ResourcePool, TimelineEntry

# ---------------------------------------------------------------------------
# Base fixture (valid pack as a plain dict)
# ---------------------------------------------------------------------------


def _base_pack_dict() -> dict:
    """A minimal valid pack dict. Tests deep-copy and mutate one field."""
    return {
        "format_version": 1,
        "id": "test-pack",
        "name": "Test Pack",
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
            {"tick": 2, "kind": "mission", "mission_kind": "medical_surge",
             "district_id": "residential_north", "severity": 4, "lives_at_risk": 16},
            {"tick": 5, "kind": "blockage", "district_id": "residential_north"},
            {"tick": 7, "kind": "mission", "mission_kind": "fire",
             "district_id": "old_town", "severity": 3, "lives_at_risk": 10},
        ],
        "field_provenance": {
            "tick": "real", "district_id": "real", "mission_kind": "mapped",
            "severity": "mapped", "lives_at_risk": "inferred", "blockage": "synthetic",
        },
        "mapping": {
            "version": "test-v1",
            "mission_kind": {"x": "fire"},
            "severity_rule": "rule",
            "lives_rule": "rule",
        },
        "sampling": {
            "method": "stratified",
            "sample_seed": 4636,
            "kept": 2,
            "total": 100,
            "filter": "f",
        },
        "source": [
            {"dataset": "D", "provider": "P", "dataset_id": "id",
             "query_url": "http://x", "fetched_at": "2026-01-01", "rows_fetched": 10,
             "license": "L", "license_url": "http://l", "attribution": "A"},
        ],
        "reference": {
            "missions": {
                "0": {"received": "2026-01-01T00:24:00-00:00",
                      "first_on_scene": "2026-01-01T00:40:00-00:00",
                      "latency_s": 942},
                "1": {"received": "2026-01-01T01:24:00-00:00",
                      "first_on_scene": None, "latency_s": None},
            },
            "aggregates": {"mean_latency_s": 948, "held_rate": 0.165},
        },
    }


def _validate(d: dict) -> ScenarioPack:
    return ScenarioPack.model_validate(d)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_base_pack_validates() -> None:
    pack = _validate(_base_pack_dict())
    assert pack.id == "test-pack"
    assert len(pack.districts) == 6
    assert set(pack.pools.keys()) == set(RESOURCE_KIND_VALUES)
    assert len(pack.timeline) == 3


def test_max_deadline_is_16() -> None:
    """Sanity: the engine-derived deadline ceiling is 16 (infra_repair)."""
    assert MAX_DEADLINE_TICKS == 16


# ---------------------------------------------------------------------------
# Rejection: bad district id
# ---------------------------------------------------------------------------


def test_reject_bad_district_id() -> None:
    d = _base_pack_dict()
    d["districts"][0]["id"] = "not_a_real_district"
    with pytest.raises(ValidationError):
        _validate(d)


def test_reject_district_set_not_exactly_six() -> None:
    """Replacing a canonical id with a duplicate of another breaks the exact-six set."""
    d = _base_pack_dict()
    d["districts"][0]["id"] = "harbor"  # now two harbors, missing old_town
    with pytest.raises(ValidationError):
        _validate(d)


def test_reject_missing_a_district() -> None:
    d = _base_pack_dict()
    d["districts"] = d["districts"][:5]  # only five
    with pytest.raises(ValidationError):
        _validate(d)


# ---------------------------------------------------------------------------
# Rejection: severity 0 / 6
# ---------------------------------------------------------------------------


def test_reject_severity_zero() -> None:
    d = _base_pack_dict()
    d["timeline"][0]["severity"] = 0
    with pytest.raises(ValidationError):
        _validate(d)


def test_reject_severity_six() -> None:
    d = _base_pack_dict()
    d["timeline"][0]["severity"] = 6
    with pytest.raises(ValidationError):
        _validate(d)


# ---------------------------------------------------------------------------
# Rejection: lives_at_risk out of [1, 64]
# ---------------------------------------------------------------------------


def test_reject_lives_at_risk_zero() -> None:
    d = _base_pack_dict()
    d["timeline"][0]["lives_at_risk"] = 0
    with pytest.raises(ValidationError):
        _validate(d)


def test_reject_lives_at_risk_over_64() -> None:
    d = _base_pack_dict()
    d["timeline"][0]["lives_at_risk"] = 65
    with pytest.raises(ValidationError):
        _validate(d)


# ---------------------------------------------------------------------------
# Rejection: unsorted timeline
# ---------------------------------------------------------------------------


def test_reject_unsorted_timeline() -> None:
    d = _base_pack_dict()
    # Swap so ticks go 7, 5, 2 (descending)
    d["timeline"] = [
        {"tick": 7, "kind": "mission", "mission_kind": "fire",
         "district_id": "old_town", "severity": 3, "lives_at_risk": 10},
        {"tick": 5, "kind": "blockage", "district_id": "residential_north"},
        {"tick": 2, "kind": "mission", "mission_kind": "medical_surge",
         "district_id": "residential_north", "severity": 4, "lives_at_risk": 16},
    ]
    with pytest.raises(ValidationError):
        _validate(d)


# ---------------------------------------------------------------------------
# Rejection: unknown pool kind / wrong pool set
# ---------------------------------------------------------------------------


def test_reject_unknown_pool_kind() -> None:
    d = _base_pack_dict()
    d["pools"]["helicopter"] = {"size": 2, "basis": "calibrated", "note": ""}
    with pytest.raises(ValidationError):
        _validate(d)


def test_reject_missing_pool_kind() -> None:
    d = _base_pack_dict()
    del d["pools"]["supply_truck"]
    with pytest.raises(ValidationError):
        _validate(d)


def test_reject_pool_size_zero() -> None:
    d = _base_pack_dict()
    d["pools"]["ambulance"]["size"] = 0
    with pytest.raises(ValidationError):
        _validate(d)


def test_reject_pool_size_over_12() -> None:
    d = _base_pack_dict()
    d["pools"]["ambulance"]["size"] = 13
    with pytest.raises(ValidationError):
        _validate(d)


# ---------------------------------------------------------------------------
# Rejection: bad mission kind
# ---------------------------------------------------------------------------


def test_reject_unknown_mission_kind() -> None:
    d = _base_pack_dict()
    d["timeline"][0]["mission_kind"] = "alien_invasion"
    with pytest.raises(ValidationError):
        _validate(d)


# ---------------------------------------------------------------------------
# Rejection: reference key out of range / not integer
# ---------------------------------------------------------------------------


def test_reject_reference_key_out_of_range() -> None:
    d = _base_pack_dict()
    # only 2 mission entries (indices 0,1); 5 is out of range
    d["reference"]["missions"]["5"] = {"received": None, "first_on_scene": None,
                                       "latency_s": None}
    with pytest.raises(ValidationError):
        _validate(d)


def test_reject_reference_key_non_integer() -> None:
    d = _base_pack_dict()
    d["reference"]["missions"]["abc"] = {"received": None, "first_on_scene": None,
                                         "latency_s": None}
    with pytest.raises(ValidationError):
        _validate(d)


# ---------------------------------------------------------------------------
# Rejection: last mission tick + 16 > 120
# ---------------------------------------------------------------------------


def test_reject_last_mission_tick_plus_16_over_120() -> None:
    d = _base_pack_dict()
    # 105 + 16 = 121 > 120
    d["timeline"] = [
        {"tick": 105, "kind": "mission", "mission_kind": "fire",
         "district_id": "old_town", "severity": 3, "lives_at_risk": 10},
    ]
    d["reference"]["missions"] = {}
    with pytest.raises(ValidationError):
        _validate(d)


def test_accept_last_mission_tick_exactly_104() -> None:
    """104 + 16 = 120 is exactly at the ceiling and must be accepted."""
    d = _base_pack_dict()
    d["timeline"] = [
        {"tick": 104, "kind": "mission", "mission_kind": "fire",
         "district_id": "old_town", "severity": 3, "lives_at_risk": 10},
    ]
    d["reference"]["missions"] = {}
    pack = _validate(d)
    assert last_timeline_tick(pack) == 104


# ---------------------------------------------------------------------------
# town_from_scenario factory
# ---------------------------------------------------------------------------


def test_town_from_scenario_names_and_pools() -> None:
    pack = _validate(_base_pack_dict())
    world = town_from_scenario(pack, seed=42)

    # District display names come from the pack; geometry keys off canonical ids.
    assert set(world.districts.keys()) == set(CANONICAL_DISTRICT_IDS)
    assert world.districts["old_town"].name == "Manhattan"
    assert world.districts["harbor"].name == "Staten Island"
    assert world.districts["residential_north"].name == "Queens"
    # ids preserved (canonical)
    assert world.districts["old_town"].id == "old_town"

    # Pools come from the pack (total == available == size).
    assert set(world.pools.keys()) == set(RESOURCE_KIND_VALUES)
    amb: ResourcePool = world.pools["ambulance"]
    assert amb.total == 4 and amb.available == 4
    assert world.pools["fire_engine"].total == 3


def test_town_from_scenario_timeline_verbatim() -> None:
    pack = _validate(_base_pack_dict())
    world = town_from_scenario(pack, seed=7)
    assert len(world.timeline) == 3
    e0: TimelineEntry = world.timeline[0]
    assert e0.tick == 2
    assert e0.kind == "mission"
    assert e0.mission_kind == "medical_surge"
    assert e0.district_id == "residential_north"
    assert e0.severity == 4
    assert e0.lives_at_risk == 16
    # blockage entry
    assert world.timeline[1].kind == "blockage"
    assert world.timeline[1].district_id == "residential_north"


def test_town_from_scenario_counters_zeroed_and_seed() -> None:
    pack = _validate(_base_pack_dict())
    world = town_from_scenario(pack, seed=99)
    assert world.tick == 0
    assert world.seed == 99
    assert world.missions == {}
    assert world.pending == []
    assert world.panic == 0.0
    assert world.lives_saved == 0
    assert world.lives_lost == 0
    assert world.next_mission_no == 1


def test_last_timeline_tick() -> None:
    pack = _validate(_base_pack_dict())
    assert last_timeline_tick(pack) == 7


# ---------------------------------------------------------------------------
# load_scenario: reads file, validates, stamps pack_digest
# ---------------------------------------------------------------------------


def test_load_scenario_stamps_digest(tmp_path: Path) -> None:
    import hashlib

    pack_path = tmp_path / "scenario.json"
    raw = json.dumps(_base_pack_dict()).encode("utf-8")
    pack_path.write_bytes(raw)

    pack = load_scenario(pack_path)
    expected = hashlib.sha256(raw).hexdigest()
    assert pack.pack_digest == expected
    assert len(pack.pack_digest) == 64
    assert pack.id == "test-pack"


def test_load_scenario_ignores_ondisk_pack_digest(tmp_path: Path) -> None:
    """A pack_digest already present on disk must be recomputed, not trusted."""
    d = _base_pack_dict()
    d["pack_digest"] = "0" * 64  # lie on disk
    pack_path = tmp_path / "scenario.json"
    pack_path.write_text(json.dumps(d), encoding="utf-8")

    pack = load_scenario(pack_path)
    assert pack.pack_digest != "0" * 64


def test_load_scenario_invalid_pack_raises(tmp_path: Path) -> None:
    d = _base_pack_dict()
    d["timeline"][0]["severity"] = 9  # invalid
    pack_path = tmp_path / "scenario.json"
    pack_path.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_scenario(pack_path)


def test_load_scenario_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_scenario(tmp_path / "does-not-exist.json")


# ---------------------------------------------------------------------------
# extra-key rejection (extra='forbid' on the top model)
# ---------------------------------------------------------------------------


def test_reject_unknown_top_level_key() -> None:
    d = _base_pack_dict()
    d["mystery_field"] = 1
    with pytest.raises(ValidationError):
        _validate(d)


def test_deepcopy_isolation() -> None:
    """Guard: the base fixture helper returns a fresh dict each call."""
    a = _base_pack_dict()
    b = _base_pack_dict()
    a["timeline"][0]["severity"] = 1
    assert b["timeline"][0]["severity"] == 4
    _ = copy.deepcopy(a)
