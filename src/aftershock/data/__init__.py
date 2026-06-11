"""aftershock.data — the OFFLINE scenario compiler.

This package turns real open incident datasets into committed ``scenario.json``
artifacts. It runs OFFLINE (network only at Extract time) and is NEVER imported
by the engine — ``town/scenario.py`` only ever reads the committed JSON.

Determinism contract (DESIGN.md task #4, invariant 2): recompiling from an
identical ``raw/`` cache + identical config hash yields a byte-identical
``scenario.json`` (golden test). Re-*fetching* is never byte-stable (the upstream
dataset refreshes daily), which is why fetch metadata is frozen into
``raw/manifest.json`` at Extract time and copied verbatim at Emit time.

Pipeline stages (shared skeleton, one adapter per dataset):

    Extract   -> raw unit rows cached to scenarios/<id>/raw/ + raw/manifest.json
    Aggregate -> group unit rows to per-incident records (adapter gotchas here)
    Discretize-> ticks, district lookup, kind mapping, severity, lives, sampling
    Emit      -> scenario.json (sorted keys) + README.md (source/license/caveat)

The engine vocabulary (MissionKind / ResourceKind / district ids / scoring) is
FROZEN — real incident types are mapped onto the four mission kinds HERE.
"""

from __future__ import annotations

from aftershock.data.adapters.base import (
    Adapter,
    AggregateResult,
    DiscretizeResult,
    Incident,
    fetch_metadata_sha256,
)
from aftershock.data.pipeline import (
    CompileResult,
    compile_scenario,
    config_sha256,
    load_config,
)

__all__ = [
    "Adapter",
    "AggregateResult",
    "CompileResult",
    "DiscretizeResult",
    "Incident",
    "compile_scenario",
    "config_sha256",
    "fetch_metadata_sha256",
    "load_config",
]
