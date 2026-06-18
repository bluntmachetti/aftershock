"""Counterfactual intervention-replay tests.

Covers:
  - Intervention validation.
  - SwitchingResolver delegates across the at_tick boundary.
  - GatedAgent silences only from at_tick onward.
  - End-to-end determinism: the headline correctness guarantee — a baseline run and
    a counterfactual run with the same seed share a byte-identical world-digest prefix
    and diverge only at the intervention tick.
"""

from __future__ import annotations

import random
import tempfile
from pathlib import Path
from typing import Any

import pytest

from aftershock.kernel.protocol import AgentResponse, Observation, Proposal, ProposalKind
from aftershock.town.counterfactual import (
    GatedAgent,
    Intervention,
    SwitchingResolver,
    run_counterfactual,
)

# ---------------------------------------------------------------------------
# Intervention validation
# ---------------------------------------------------------------------------


def test_intervention_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown intervention kind"):
        Intervention(at_tick=5, kind="teleport")


def test_intervention_rejects_negative_tick() -> None:
    with pytest.raises(ValueError, match="at_tick must be >= 0"):
        Intervention(at_tick=-1, kind="none")


def test_intervention_accepts_valid() -> None:
    iv = Intervention(at_tick=20, kind="drop_protocol")
    assert iv.at_tick == 20
    assert iv.kind == "drop_protocol"


# ---------------------------------------------------------------------------
# SwitchingResolver
# ---------------------------------------------------------------------------


class _RecordingResolver:
    name = "recording"

    def __init__(self) -> None:
        self.calls: list[int] = []

    def resolve(
        self,
        world: Any,
        tick: int,
        arbiter: list[Proposal],
        answered: list[Any],
        expired: list[Proposal],
        rng: random.Random,
    ) -> tuple[list[Any], list[Any]]:
        self.calls.append(tick)
        return [], []


def _arbiter_proposal() -> Proposal:
    return Proposal(
        proposal_id="p1",
        sender="commander",
        recipient=None,
        kind=ProposalKind.RESOURCE_REQUEST,
        body={"resource": "ambulance", "mission_id": "m1", "qty": 1},
    )


def test_switching_resolver_uses_base_before_at_tick() -> None:
    base = _RecordingResolver()
    sw = SwitchingResolver(base, at_tick=10)
    rng = random.Random(0)
    sw.resolve(None, 5, [_arbiter_proposal()], [], [], rng)
    assert base.calls == [5]


def test_switching_resolver_falls_back_at_and_after_at_tick() -> None:
    base = _RecordingResolver()
    sw = SwitchingResolver(base, at_tick=10)
    rng = random.Random(0)
    # At the boundary tick, the base resolver must NOT be called; the fallback
    # (DefaultResolver) declines the arbiter proposal instead.
    rulings, grants = sw.resolve(None, 10, [_arbiter_proposal()], [], [], rng)
    assert base.calls == []
    assert grants == []
    assert len(rulings) == 1
    assert rulings[0].accepted is False
    assert rulings[0].decided_by == "kernel:default"


def test_switching_resolver_name_encodes_branch() -> None:
    sw = SwitchingResolver(_RecordingResolver(), at_tick=30)
    assert sw.name == "recording->default@30"


# ---------------------------------------------------------------------------
# GatedAgent
# ---------------------------------------------------------------------------


class _AliveAgent:
    def __init__(self) -> None:
        self.agent_id = "rescue"
        self.role = "rescue"

    async def act(self, observation: Observation) -> AgentResponse:
        return AgentResponse(
            agent_id="rescue",
            decisions=(),
            error="",
        )


def _obs(tick: int) -> Observation:
    return Observation(tick=tick, agent_id="rescue", role="rescue", view={})


@pytest.mark.asyncio
async def test_gated_agent_alive_before_at_tick() -> None:
    gated = GatedAgent(_AliveAgent(), at_tick=10)
    resp = await gated.act(_obs(9))
    assert resp.error == ""


@pytest.mark.asyncio
async def test_gated_agent_silenced_at_and_after_at_tick() -> None:
    gated = GatedAgent(_AliveAgent(), at_tick=10)
    resp_boundary = await gated.act(_obs(10))
    resp_after = await gated.act(_obs(15))
    assert resp_boundary.error == "killed@10"
    assert resp_boundary.decisions == ()
    assert resp_after.error == "killed@10"


def test_gated_agent_preserves_identity() -> None:
    gated = GatedAgent(_AliveAgent(), at_tick=10)
    assert gated.agent_id == "rescue"
    assert gated.role == "rescue"


# ---------------------------------------------------------------------------
# End-to-end determinism — the headline correctness guarantee
# ---------------------------------------------------------------------------

_SEED = 42
_TICKS = 60
_AT = 20


def _world_digests(run_dir: Path) -> list[str]:
    from aftershock.kernel.recorder import load_run

    _manifest, ticks, _worlds = load_run(run_dir)
    return [t.world_digest for t in ticks]


async def _baseline(tmp: Path) -> list[str]:
    iv = Intervention(at_tick=0, kind="none")
    summary = await run_counterfactual(
        arm="scripted",
        seed=_SEED,
        ticks=_TICKS,
        intervention=iv,
        runs_root=tmp,
        run_id="baseline",
    )
    return _world_digests(Path(summary.run_dir))


async def _counterfactual(tmp: Path, iv: Intervention, run_id: str) -> list[str]:
    summary = await run_counterfactual(
        arm="scripted",
        seed=_SEED,
        ticks=_TICKS,
        intervention=iv,
        runs_root=tmp,
        run_id=run_id,
    )
    return _world_digests(Path(summary.run_dir))


async def test_none_intervention_is_byte_identical_to_baseline() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        base = await _baseline(tmp)
        cf = await _counterfactual(tmp, Intervention(at_tick=_AT, kind="none"), "cf-none")
    assert base == cf, "none-intervention run must reproduce the baseline byte-for-byte"


async def test_drop_protocol_shares_prefix_then_diverges() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        base = await _baseline(tmp)
        cf = await _counterfactual(
            tmp, Intervention(at_tick=_AT, kind="drop_protocol"), "cf-drop"
        )
    # Identical prefix up to the branch tick — the causal-proof guarantee. Run
    # lengths may differ after the branch (dropping the auction leaves missions
    # unresolved, so the run does not early-exit at the same tick).
    assert base[:_AT] == cf[:_AT]
    # And the runs must differ after the branch (dropping the auction changes
    # outcomes) — either in length or in the world digests they share.
    diverged = len(base) != len(cf) or base[_AT:] != cf[_AT:]
    assert diverged


async def test_inject_event_lands_in_target_tick() -> None:
    from aftershock.kernel.recorder import load_run

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        base = await _baseline(tmp)
        iv = Intervention(
            at_tick=_AT, kind="inject_event", target="market", params={"event": "fire"}
        )
        summary = await run_counterfactual(
            arm="scripted",
            seed=_SEED,
            ticks=_TICKS,
            intervention=iv,
            runs_root=tmp,
            run_id="cf-inject",
        )
        cf = _world_digests(Path(summary.run_dir))
        _manifest, ticks, _worlds = load_run(Path(summary.run_dir))

    # Prefix identical up to the injection tick.
    assert base[:_AT] == cf[:_AT]
    # The injected fire mission spawns in exactly the target tick's events.
    injected = [
        e
        for e in ticks[_AT].events
        if e.payload.get("injected") is True
    ]
    assert injected, "injected event must appear in the target tick's events"
    # And nothing injected before it.
    earlier = [
        e for t in ticks[:_AT] for e in t.events if e.payload.get("injected") is True
    ]
    assert not earlier


async def test_kill_agent_shares_prefix_then_diverges() -> None:
    """End-to-end kill_agent: silencing the commander at N keeps the prefix byte-
    identical, then diverges — the same causal-proof guarantee as drop_protocol."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        base = await _baseline(tmp)
        cf = await _counterfactual(
            tmp,
            Intervention(at_tick=_AT, kind="kill_agent", target="commander"),
            "cf-kill",
        )
    assert base[:_AT] == cf[:_AT], "prefix before the kill must be byte-identical"
    diverged = len(base) != len(cf) or base[_AT:] != cf[_AT:]
    assert diverged, "silencing a role must change the run after the branch"


async def test_kill_agent_unknown_target_raises() -> None:
    """A kill_agent target absent from the roster aborts loudly (no silent run)."""
    with tempfile.TemporaryDirectory() as td, pytest.raises(ValueError, match="not in roster"):
        await run_counterfactual(
            arm="scripted",
            seed=_SEED,
            ticks=_TICKS,
            intervention=Intervention(at_tick=_AT, kind="kill_agent", target="nobody"),
            runs_root=Path(td),
            run_id="cf-kill-bad",
        )


@pytest.mark.parametrize("at_tick", [0, 2])
async def test_inject_event_unknown_district_raises_not_silent(at_tick: int) -> None:
    """A bad inject district must raise BEFORE the run (was silently swallowed for
    at_tick > 0 because the injection ran inside the engine's suppressed listener)."""
    with tempfile.TemporaryDirectory() as td, pytest.raises(ValueError, match="unknown district"):
        await run_counterfactual(
            arm="scripted",
            seed=_SEED,
            ticks=_TICKS,
            intervention=Intervention(
                at_tick=at_tick,
                kind="inject_event",
                target="NOT_A_DISTRICT",
                params={"event": "fire"},
            ),
            runs_root=Path(td),
            run_id=f"cf-inject-bad-{at_tick}",
        )


async def test_inject_event_unknown_event_kind_raises() -> None:
    with tempfile.TemporaryDirectory() as td, pytest.raises(ValueError, match="unknown inject"):
        await run_counterfactual(
            arm="scripted",
            seed=_SEED,
            ticks=_TICKS,
            intervention=Intervention(
                at_tick=_AT,
                kind="inject_event",
                target="market",
                params={"event": "meteor"},
            ),
            runs_root=Path(td),
            run_id="cf-inject-bad-kind",
        )


@pytest.mark.parametrize("at_tick", [0, 1])
async def test_inject_event_lands_at_boundary_ticks(at_tick: int) -> None:
    """The off-by-one queueing is correct at the boundaries: at_tick=0 (the special
    pre-loop direct inject) and at_tick=1 (queue_after=0) both land in the right tick."""
    from aftershock.kernel.recorder import load_run

    with tempfile.TemporaryDirectory() as td:
        summary = await run_counterfactual(
            arm="scripted",
            seed=_SEED,
            ticks=_TICKS,
            intervention=Intervention(
                at_tick=at_tick, kind="inject_event", target="market", params={"event": "fire"}
            ),
            runs_root=Path(td),
            run_id=f"cf-inject-t{at_tick}",
        )
        _manifest, ticks, _worlds = load_run(Path(summary.run_dir))

    injected = [e for e in ticks[at_tick].events if e.payload.get("injected") is True]
    assert injected, f"injected event must appear in tick {at_tick}"
    earlier = [
        e for t in ticks[:at_tick] for e in t.events if e.payload.get("injected") is True
    ]
    assert not earlier


# ---------------------------------------------------------------------------
# Scenario-backed branch — the prefix must be byte-identical to a scenario baseline
# (regression: the web path used to drop the pack and branch into a synthetic world)
# ---------------------------------------------------------------------------

_SCENARIO_PATH = Path("scenarios/nyc-ida-2021/scenario.json")


@pytest.mark.skipif(not _SCENARIO_PATH.is_file(), reason="scenario pack not present")
async def test_scenario_baseline_branch_shares_byte_identical_prefix() -> None:
    """Threading the scenario pack into the branch rebuilds the SAME real-data world,
    so a scenario baseline and its branch share a byte-identical prefix (the honesty
    contract). Without the pack the branch would diverge from tick 0."""
    from aftershock.town.scenario import load_scenario

    pack = load_scenario(_SCENARIO_PATH)
    at = 4
    ticks = 12
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        base = await run_counterfactual(
            arm="scripted",
            seed=_SEED,
            ticks=ticks,
            intervention=Intervention(at_tick=0, kind="none"),
            runs_root=tmp,
            run_id="scn-baseline",
            scenario=pack,
        )
        cf = await run_counterfactual(
            arm="scripted",
            seed=_SEED,
            ticks=ticks,
            intervention=Intervention(at_tick=at, kind="drop_protocol"),
            runs_root=tmp,
            run_id="scn-drop",
            scenario=pack,
        )
        base_d = _world_digests(Path(base.run_dir))
        cf_d = _world_digests(Path(cf.run_dir))
    assert base_d[:at] == cf_d[:at], "scenario branch must share the baseline's prefix"


# ---------------------------------------------------------------------------
# Recorder lifecycle — a mid-run engine error must not leak file handles
# ---------------------------------------------------------------------------


async def test_run_counterfactual_closes_recorder_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aftershock.town.counterfactual as cf_mod

    closed = {"v": False}
    real_close = cf_mod.Recorder.close

    def tracking_close(self: Any) -> None:
        closed["v"] = True
        real_close(self)

    monkeypatch.setattr(cf_mod.Recorder, "close", tracking_close)

    class _BoomEngine:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def run(self, *, inter_tick_delay_s: float = 0.0) -> Any:
            raise RuntimeError("boom")

    monkeypatch.setattr(cf_mod, "Engine", _BoomEngine)

    with tempfile.TemporaryDirectory() as td, pytest.raises(RuntimeError, match="boom"):
        await run_counterfactual(
            arm="scripted",
            seed=_SEED,
            ticks=10,
            intervention=Intervention(at_tick=3, kind="none"),
            runs_root=Path(td),
            run_id="cf-boom",
        )
    assert closed["v"], "recorder must be closed even when the engine errors mid-run"
