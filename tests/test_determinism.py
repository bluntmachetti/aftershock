"""End-to-end determinism tests.

- Two full Engine runs with seed 42 produce identical world-digest sequences
  AND identical canonical TickRecord lines.
- Two runs with seed 43 also match each other (same determinism guarantee).
- Seed 42 and seed 43 produce different digest sequences.
- The scripted arm saves > 0 lives over 60 ticks.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from aftershock.kernel.engine import Engine
from aftershock.kernel.recorder import Recorder, canonical_json, load_run
from aftershock.kernel.registry import DecisionRegistry
from aftershock.kernel.roles import load_roles
from aftershock.town.decisions import register_all
from aftershock.town.heuristics import (
    CommanderScripted,
    CommsScripted,
    FireScripted,
    InfraScripted,
    MedicalScripted,
    RescueScripted,
)
from aftershock.town.society import TownResolver, TownSociety
from aftershock.town.state import new_town

_ROLES_DIR = Path(__file__).parent.parent / "src" / "aftershock" / "town" / "roles"
_TICKS = 60


def _build_engine(seed: int, out_dir: Path, run_id: str) -> Engine:
    world = new_town(seed)
    society = TownSociety(max_ticks=_TICKS)
    registry = DecisionRegistry()
    register_all(registry)
    roles = load_roles(_ROLES_DIR)
    agents: dict[str, Any] = {
        "commander": CommanderScripted("commander", "commander"),
        "medical": MedicalScripted("medical", "medical"),
        "rescue": RescueScripted("rescue", "rescue"),
        "fire": FireScripted("fire", "fire"),
        "infrastructure": InfraScripted("infrastructure", "infrastructure"),
        "comms": CommsScripted("comms", "comms"),
    }
    resolver = TownResolver()
    manifest: dict[str, Any] = {"run_id": run_id, "seed": seed, "ticks": _TICKS}
    recorder = Recorder(out_dir, run_id, manifest)
    return Engine(
        world=world,
        society=society,
        agents=agents,
        registry=registry,
        roles=roles,
        resolver=resolver,
        recorder=recorder,
        seed=seed,
        max_ticks=_TICKS,
    )


async def _run_seed(seed: int, tmp: Path, tag: str) -> tuple[list[str], list[str]]:
    """Run engine; return (world_digests, canonical_tick_lines)."""
    run_id = f"seed{seed}-{tag}"
    engine = _build_engine(seed, tmp, run_id)
    await engine.run()
    _, records = load_run(tmp / run_id)
    digests = [r.world_digest for r in records]
    lines = [canonical_json(r) for r in records]
    return digests, lines


@pytest.mark.asyncio
async def test_determinism_seed42_identical_digests() -> None:
    """Two runs with seed 42 produce identical world-digest sequences."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        digests_a, _ = await _run_seed(42, tmp, "a")
        digests_b, _ = await _run_seed(42, tmp, "b")
    assert digests_a == digests_b, "seed 42 runs differ in world digests"


@pytest.mark.asyncio
async def test_determinism_seed42_identical_tick_lines() -> None:
    """Two runs with seed 42 produce identical canonical TickRecord lines."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _, lines_a = await _run_seed(42, tmp, "a")
        _, lines_b = await _run_seed(42, tmp, "b")
    assert lines_a == lines_b, "seed 42 runs differ in canonical tick lines"


@pytest.mark.asyncio
async def test_determinism_seed43_identical() -> None:
    """Two runs with seed 43 also produce identical digest sequences."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        digests_a, _ = await _run_seed(43, tmp, "a")
        digests_b, _ = await _run_seed(43, tmp, "b")
    assert digests_a == digests_b, "seed 43 runs differ"


@pytest.mark.asyncio
async def test_different_seeds_differ() -> None:
    """Seed 42 and seed 43 produce different digest sequences."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        digests_42, _ = await _run_seed(42, tmp, "x")
        digests_43, _ = await _run_seed(43, tmp, "y")
    assert digests_42 != digests_43, "seed 42 and seed 43 produced identical digests"


@pytest.mark.asyncio
async def test_scripted_arm_saves_lives() -> None:
    """The scripted arm saves > 0 lives over 60 ticks with seed 42."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        digests, _ = await _run_seed(42, tmp, "lives")
        _, records = load_run(tmp / "seed42-lives")
    assert records, "no tick records produced"
    final_scores = records[-1].scores
    lives_saved = final_scores.get("lives_saved", 0.0)
    assert lives_saved > 0, f"scripted arm saved 0 lives (scores={final_scores})"
