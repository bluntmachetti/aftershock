"""Scenario packs: pydantic models + loader + TownState factory.

A scenario pack is a self-contained JSON artifact (``scenarios/<id>/scenario.json``)
compiled OFFLINE from real open incident data. The engine never touches the network;
loading a pack is pure validation + digest. ``town_from_scenario`` builds a TownState
from a pack exactly the way ``new_town`` builds a synthetic one, so the engine is
agnostic to where its world came from.

Determinism contract (DESIGN.md task #4, invariant 2): same pack + same seed + same
decisions = byte-identical outcome. The pack provides districts (display names),
pools, and a verbatim timeline; the seed continues to drive every ``rng_for`` stream.

state.py is NOT modified. Engine vocabulary (MissionKind/ResourceKind/district ids/
scoring) is frozen — real incident types are mapped onto the four mission kinds in the
OFFLINE compiler, not here.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aftershock.town.state import (
    DEADLINE_TICKS,
    DISTRICTS,
    District,
    MissionKind,
    ResourceKind,
    ResourcePool,
    TimelineEntry,
    TownState,
)

# ---------------------------------------------------------------------------
# Engine-bound constants (derived from state.py — never hardcoded twice)
# ---------------------------------------------------------------------------

# Canonical district ids, in canonical (positional-slot) order.
CANONICAL_DISTRICT_IDS: tuple[str, ...] = tuple(did for did, _ in DISTRICTS)

# The five resource kinds, as plain string values.
RESOURCE_KIND_VALUES: frozenset[str] = frozenset(k.value for k in ResourceKind)

# The four mission kinds, as plain string values.
MISSION_KIND_VALUES: frozenset[str] = frozenset(k.value for k in MissionKind)

# Engine tick budget ceiling (kernel/engine.py `_MAX_TICKS_LIVE`, web.py
# `_MAX_TICKS_LIVE = 120`). The engine loop is `while tick < max_ticks`.
MAX_TICKS: int = 120

# Largest mission deadline in the model (infra_repair = 16). A mission spawned at the
# last timeline tick must be able to resolve/fail within the budget, so:
#   last_mission_tick + MAX_DEADLINE_TICKS <= MAX_TICKS
MAX_DEADLINE_TICKS: int = max(DEADLINE_TICKS.values())

# Scenario id grammar (matches the dir name; same as the web traversal-guard).
_SCENARIO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Pool sizes are bounded [1, 12] per the loader-validation spec.
_POOL_SIZE_MIN = 1
_POOL_SIZE_MAX = 12

# Field-provenance markers.
ProvenanceLabel = Literal["real", "mapped", "inferred", "synthetic"]


# ---------------------------------------------------------------------------
# Nested models
# ---------------------------------------------------------------------------


class ScenarioDistrict(BaseModel):
    """One district slot. ``id`` is a canonical positional slot; ``name`` is the
    pack's display override; ``members`` documents the real zoning (free-form)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    members: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_canonical(cls, v: str) -> str:
        if v not in CANONICAL_DISTRICT_IDS:
            raise ValueError(
                f"district id {v!r} is not one of the canonical six "
                f"{CANONICAL_DISTRICT_IDS}"
            )
        return v


class ScenarioPool(BaseModel):
    """One resource pool. ``size`` feeds ResourcePool(total=available=size).
    ``basis`` records whether the size was observed in the data or calibrated."""

    model_config = ConfigDict(extra="forbid")

    size: int = Field(ge=_POOL_SIZE_MIN, le=_POOL_SIZE_MAX)
    basis: str = "calibrated"
    note: str = ""


class ScenarioTimelineEntry(BaseModel):
    """One timeline entry — exact TimelineEntry shape. Missions carry mission_kind/
    district_id/severity/lives_at_risk; blockages carry only district_id."""

    model_config = ConfigDict(extra="forbid")

    tick: int = Field(ge=0)
    kind: Literal["mission", "blockage"]
    mission_kind: str = ""
    district_id: str = ""
    severity: int = 0
    lives_at_risk: int = 0

    @model_validator(mode="after")
    def _check_by_kind(self) -> ScenarioTimelineEntry:
        if self.district_id and self.district_id not in CANONICAL_DISTRICT_IDS:
            raise ValueError(
                f"timeline district_id {self.district_id!r} is not canonical"
            )
        if self.kind == "mission":
            if self.mission_kind not in MISSION_KIND_VALUES:
                raise ValueError(
                    f"mission_kind {self.mission_kind!r} is not one of "
                    f"{sorted(MISSION_KIND_VALUES)}"
                )
            if not (1 <= self.severity <= 5):
                raise ValueError(
                    f"severity must be 1-5, got {self.severity}"
                )
            if not (1 <= self.lives_at_risk <= 64):
                raise ValueError(
                    f"lives_at_risk must be 1-64, got {self.lives_at_risk}"
                )
            if not self.district_id:
                raise ValueError("mission timeline entry needs a district_id")
        else:  # blockage
            if not self.district_id:
                raise ValueError("blockage timeline entry needs a district_id")
        return self


class ScenarioWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str
    end: str


class ScenarioFieldProvenance(BaseModel):
    """Drives the REAL/MAPPED/INFERRED/SYNTHETIC badges in the UI."""

    model_config = ConfigDict(extra="forbid")

    tick: ProvenanceLabel
    district_id: ProvenanceLabel
    mission_kind: ProvenanceLabel
    severity: ProvenanceLabel
    lives_at_risk: ProvenanceLabel
    blockage: ProvenanceLabel


class ScenarioMapping(BaseModel):
    """The published semantic decisions (verbatim, for provenance)."""

    model_config = ConfigDict(extra="allow")

    version: str
    mission_kind: dict[str, str] = Field(default_factory=dict)
    severity_rule: str = ""
    lives_rule: str = ""


class ScenarioSampling(BaseModel):
    """How the real window was downscaled — no silent caps."""

    model_config = ConfigDict(extra="allow")

    method: str
    sample_seed: int
    kept: int = Field(ge=0)
    total: int = Field(ge=0)
    filter: str = ""


class ScenarioSource(BaseModel):
    """One upstream dataset, with query + license + attribution."""

    model_config = ConfigDict(extra="allow")

    dataset: str
    provider: str
    dataset_id: str = ""
    query_url: str = ""
    fetched_at: str = ""
    rows_fetched: int = 0
    license: str = ""
    license_url: str = ""
    attribution: str = ""


class ScenarioReferenceMission(BaseModel):
    """Per-mission real baseline. ``first_on_scene``/``latency_s`` are null when no
    unit arrived."""

    model_config = ConfigDict(extra="allow")

    received: str | None = None
    first_on_scene: str | None = None
    latency_s: int | None = None


class ScenarioReference(BaseModel):
    """The reality baseline. ``missions`` keyed by TIMELINE INDEX of the mission entry
    (string keys); ``aggregates`` computed over the full filtered window."""

    model_config = ConfigDict(extra="allow")

    missions: dict[str, ScenarioReferenceMission] = Field(default_factory=dict)
    aggregates: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Top-level pack
# ---------------------------------------------------------------------------


class ScenarioPack(BaseModel):
    """A validated scenario pack. ``pack_digest`` is computed at load time
    (``load_scenario``) and is not part of the on-disk JSON."""

    model_config = ConfigDict(extra="forbid")

    format_version: int
    id: str
    name: str
    hazard: str
    adapter: str
    compiler_version: str
    config_sha256: str
    tick_minutes: int = Field(gt=0)
    window: ScenarioWindow
    districts: list[ScenarioDistrict]
    pools: dict[str, ScenarioPool]
    timeline: list[ScenarioTimelineEntry]
    field_provenance: ScenarioFieldProvenance
    mapping: ScenarioMapping
    sampling: ScenarioSampling
    source: list[ScenarioSource]
    reference: ScenarioReference = Field(default_factory=ScenarioReference)

    # Computed at load; never read from disk.
    pack_digest: str = ""

    @field_validator("id")
    @classmethod
    def _id_grammar(cls, v: str) -> str:
        if not _SCENARIO_ID_RE.match(v):
            raise ValueError(
                f"scenario id {v!r} must match ^[a-z0-9][a-z0-9-]*$"
            )
        return v

    @field_validator("districts")
    @classmethod
    def _districts_exact_six(
        cls, v: list[ScenarioDistrict]
    ) -> list[ScenarioDistrict]:
        ids = [d.id for d in v]
        if sorted(ids) != sorted(CANONICAL_DISTRICT_IDS):
            raise ValueError(
                "districts must be exactly the canonical six "
                f"{sorted(CANONICAL_DISTRICT_IDS)}; got {sorted(ids)}"
            )
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate district id(s) in {ids}")
        return v

    @field_validator("pools")
    @classmethod
    def _pools_exact_five(
        cls, v: dict[str, ScenarioPool]
    ) -> dict[str, ScenarioPool]:
        keys = set(v.keys())
        if keys != set(RESOURCE_KIND_VALUES):
            raise ValueError(
                "pools must be exactly the five ResourceKind keys "
                f"{sorted(RESOURCE_KIND_VALUES)}; got {sorted(keys)}"
            )
        return v

    @model_validator(mode="after")
    def _timeline_and_reference(self) -> ScenarioPack:
        # Timeline must be sorted by tick (non-decreasing).
        ticks = [e.tick for e in self.timeline]
        if ticks != sorted(ticks):
            raise ValueError("timeline must be sorted by tick (non-decreasing)")

        # last mission tick + max(DEADLINE_TICKS) (=16) <= MAX_TICKS (=120).
        mission_ticks = [e.tick for e in self.timeline if e.kind == "mission"]
        if mission_ticks:
            last_mission_tick = max(mission_ticks)
            if last_mission_tick + MAX_DEADLINE_TICKS > MAX_TICKS:
                raise ValueError(
                    f"last mission tick {last_mission_tick} + "
                    f"max(DEADLINE_TICKS)={MAX_DEADLINE_TICKS} = "
                    f"{last_mission_tick + MAX_DEADLINE_TICKS} exceeds "
                    f"MAX_TICKS={MAX_TICKS}"
                )

        # reference mission keys must index valid mission entries (by timeline
        # index of the nth mission entry, per the injection-safe index map).
        mission_count = len(mission_ticks)
        for key in self.reference.missions:
            try:
                idx = int(key)
            except ValueError as exc:
                raise ValueError(
                    f"reference mission key {key!r} is not an integer index"
                ) from exc
            if idx < 0 or idx >= mission_count:
                raise ValueError(
                    f"reference mission key {key!r} (index {idx}) is out of "
                    f"range; there are {mission_count} mission timeline entries"
                )
        return self


# ---------------------------------------------------------------------------
# Loader + factory
# ---------------------------------------------------------------------------


def _compute_digest(raw_bytes: bytes) -> str:
    """SHA-256 of the on-disk scenario.json bytes."""
    return hashlib.sha256(raw_bytes).hexdigest()


def load_scenario(path: str | Path) -> ScenarioPack:
    """Load, validate, and digest a scenario pack from ``scenario.json``.

    Computes the SHA-256 of the raw file bytes and stamps it into
    ``pack_digest`` (used by the run manifest). All loader validation is a
    HARD error: malformed packs raise ``pydantic.ValidationError`` (or
    ``FileNotFoundError`` / ``json.JSONDecodeError`` for IO/parse problems).
    """
    p = Path(path)
    raw_bytes = p.read_bytes()
    data = json.loads(raw_bytes)
    # Never let an on-disk pack pre-seed the computed digest.
    if isinstance(data, dict):
        data.pop("pack_digest", None)
    pack = ScenarioPack.model_validate(data)
    return pack.model_copy(update={"pack_digest": _compute_digest(raw_bytes)})


def town_from_scenario(pack: ScenarioPack, seed: int) -> TownState:
    """Build a fresh TownState from a scenario pack.

    Districts take their display NAMES from the pack (geometry stays keyed by the
    canonical id). Pools come from the pack (total == available == size). The
    timeline is copied verbatim into ``TimelineEntry`` objects. All counters are
    zeroed. ``seed`` is preserved on the state so every downstream ``rng_for``
    stream keeps its meaning and replay identity (DESIGN.md engine integration).
    """
    # Districts in canonical order, with pack display names; geometry keys off id.
    name_by_id = {d.id: d.name for d in pack.districts}
    districts = {
        did: District(id=did, name=name_by_id[did])
        for did in CANONICAL_DISTRICT_IDS
    }

    # Pools: total == available == size, from the pack.
    pools = {
        kind: ResourcePool(kind=kind, total=p.size, available=p.size)
        for kind, p in pack.pools.items()
    }

    # Timeline verbatim, in pack order (already validated sorted by tick).
    timeline = [
        TimelineEntry(
            tick=e.tick,
            kind=e.kind,
            mission_kind=e.mission_kind,
            district_id=e.district_id,
            severity=e.severity,
            lives_at_risk=e.lives_at_risk,
        )
        for e in pack.timeline
    ]

    return TownState(
        tick=0,
        seed=seed,
        districts=districts,
        missions={},
        pools=pools,
        pending=[],
        timeline=timeline,
        panic=0.0,
        lives_saved=0,
        lives_lost=0,
        next_mission_no=1,
    )


def last_timeline_tick(pack: ScenarioPack) -> int:
    """The maximum tick across all timeline entries (0 if empty). Used by the CLI
    to compute the scenario tick budget default."""
    return max((e.tick for e in pack.timeline), default=0)


# Default extra ticks past the last timeline tick when computing the scenario
# tick budget. The ceiling is MAX_TICKS (the engine loop runs while tick < max).
SCENARIO_TICK_PADDING: int = 20


def scenario_tick_budget(pack: ScenarioPack) -> int:
    """The scenario tick budget: ``min(last timeline tick + 20, 120)``.

    Single source of truth for the omitted-ticks default AND the under-budget
    floor, shared by the CLI (``cli.py``) and the live API (``web.py``) so the two
    never drift. A scenario run that asks for fewer ticks than this would silently
    truncate the real timeline, so both callers treat ``budget`` as a hard floor.
    """
    return min(last_timeline_tick(pack) + SCENARIO_TICK_PADDING, MAX_TICKS)
