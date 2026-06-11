"""Shared adapter base + the per-incident record + stage result containers.

An adapter implements the three data-shaping stages — Extract, Aggregate,
Discretize — for one upstream dataset. The Emit stage and CLI orchestration are
shared (``pipeline.py``). Adapters never write the final ``scenario.json``; they
return plain data the pipeline serializes.

Determinism: every adapter method is a pure function of its inputs (config +
cached rows). Only ``extract`` touches the network, and it caches its result so
Aggregate/Discretize/Emit are reproducible offline.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Incident:
    """One aggregated incident (a group of dispatched-unit rows).

    Times are ISO strings exactly as they appear upstream (no tz munging — the
    window is local and self-consistent). ``first_on_scene`` is None when no unit
    ever arrived (all on-scene timestamps null/cancelled).
    """

    call_number: str
    received: str
    first_on_scene: str | None
    units: tuple[str, ...]          # observed unit_type roster for the incident
    district_id: str                # canonical district id (post battalion lookup)
    call_type: str
    call_type_group: str
    original_priority: str
    number_of_alarms: int


@dataclass(frozen=True)
class AggregateResult:
    """Output of Aggregate: per-incident records + dropped-row accounting."""

    incidents: tuple[Incident, ...]
    dropped_junk_battalion: int
    raw_unit_rows: int


@dataclass
class DiscretizeResult:
    """Output of Discretize: everything the Emit stage needs to build a pack.

    ``timeline`` / ``pools`` / ``reference`` / ``sampling`` are plain JSON-able
    structures matching the ``town.scenario`` contract. ``mapping`` and
    ``field_provenance`` are likewise plain dicts.
    """

    timeline: list[dict[str, Any]]
    pools: dict[str, dict[str, Any]]
    reference: dict[str, Any]
    sampling: dict[str, Any]
    mapping: dict[str, Any]
    field_provenance: dict[str, str]
    districts: list[dict[str, Any]]
    extra: dict[str, Any] = field(default_factory=dict)


def fetch_metadata_sha256(meta: dict[str, Any]) -> str:
    """Stable sha256 of fetch metadata (sorted keys) — for raw-cache identity."""
    payload = json.dumps(meta, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class Adapter:
    """Base class. Subclasses implement extract/aggregate/discretize.

    The pipeline calls them in order, passing the loaded config dict through.
    ``name`` is the adapter id stamped into ``scenario.json`` (``adapter`` field).
    """

    name: str = "base"

    def extract(self, config: dict[str, Any], raw_dir: Path) -> dict[str, Any]:
        """Fetch raw rows into ``raw_dir`` and return the fetch manifest dict.

        Must write ``raw_dir/rows.json`` (the unit rows) and return a manifest
        with at least ``fetched_at``, ``rows_fetched`` (int), ``query_url``.
        NETWORK happens here and only here.
        """
        raise NotImplementedError

    def load_rows(self, raw_dir: Path) -> list[dict[str, Any]]:
        """Read the cached unit rows (no network). Default reads rows.json."""
        rows_path = raw_dir / "rows.json"
        return json.loads(rows_path.read_text(encoding="utf-8"))

    def aggregate(
        self, rows: list[dict[str, Any]], config: dict[str, Any]
    ) -> AggregateResult:
        """Group unit rows into incidents (adapter gotchas live here)."""
        raise NotImplementedError

    def discretize(
        self,
        agg: AggregateResult,
        config: dict[str, Any],
        fetch_manifest: dict[str, Any],
    ) -> DiscretizeResult:
        """Ticks, district lookup, kind mapping, severity, lives, sampling."""
        raise NotImplementedError
