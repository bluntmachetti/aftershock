"""Counterfactual intervention replay.

A counterfactual run re-runs a scenario from tick 0 with a single *intervention*
scheduled at a chosen tick N. Because the engine derives per-tick randomness purely
from ``rng_for(seed, "tick", tick)`` (state-independent), a re-run with the same seed
reproduces the baseline tick-for-tick until the intervention fires — so the baseline
and counterfactual share a byte-identical prefix and diverge only at N. That shared
prefix is the causal proof the feature rests on; it needs no ``TownState`` rehydration
and never touches the determinism contract (``aftershock verify``).

Intervention kinds:
  drop_protocol  — swap the auction resolver for DefaultResolver from tick N onward
  kill_agent     — a named agent emits an empty response from tick N onward
  inject_event   — queue a fire / aftershock / road_block landing at tick N
  none           — control (byte-identical to the baseline)

drop_protocol / kill_agent / inject_event are fully deterministic and run on the
scripted arm with no API key. downgrade_role (mid-run model swap on an LLM arm) is
out of scope for v1; see docs/plans/counterfactual-replay.md.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aftershock.kernel.agents import Agent
from aftershock.kernel.engine import Engine, RunSummary
from aftershock.kernel.negotiation import DefaultResolver, Resolver
from aftershock.kernel.protocol import (
    AgentResponse,
    Decision,
    Observation,
    Proposal,
    ProposalResponse,
    ProposalRuling,
    TickRecord,
)
from aftershock.kernel.recorder import Recorder

if TYPE_CHECKING:
    from aftershock.town.scenario import ScenarioPack

INTERVENTION_KINDS = frozenset(
    {"drop_protocol", "kill_agent", "inject_event", "none"}
)


@dataclass(frozen=True)
class Intervention:
    """A single declarative change applied at the start of tick ``at_tick``.

    target/params meaning by kind:
      kill_agent    — target = agent_id to silence
      inject_event  — target = district_id; params["event"] = fire|aftershock|road_block
      drop_protocol — target/params unused
      none          — control
    """

    at_tick: int
    kind: str
    target: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in INTERVENTION_KINDS:
            raise ValueError(
                f"unknown intervention kind {self.kind!r}; valid: {sorted(INTERVENTION_KINDS)}"
            )
        if self.at_tick < 0:
            raise ValueError(f"at_tick must be >= 0, got {self.at_tick}")


class SwitchingResolver:
    """Delegate to ``base`` while ``tick < at_tick``, then to DefaultResolver.

    Implements the kernel Resolver protocol. Used by the ``drop_protocol``
    intervention so a run uses the real auction up to N and a no-arbiter resolver
    thereafter — isolating the protocol's contribution after the branch point.
    """

    _fallback = DefaultResolver()

    def __init__(self, base: Resolver, at_tick: int) -> None:
        self._base = base
        self._at_tick = at_tick
        self.name = f"{getattr(base, 'name', 'base')}->default@{at_tick}"

    def resolve(
        self,
        world: Any,
        tick: int,
        arbiter: list[Proposal],
        answered: list[tuple[Proposal, ProposalResponse]],
        expired: list[Proposal],
        rng: random.Random,
    ) -> tuple[list[ProposalRuling], list[Decision]]:
        active = self._base if tick < self._at_tick else self._fallback
        return active.resolve(world, tick, arbiter, answered, expired, rng)


class GatedAgent(Agent):
    """Wrap an agent so it emits an empty response from ``at_tick`` onward.

    Used by ``kill_agent``: before the branch the wrapped agent acts normally;
    at and after ``at_tick`` it returns an empty AgentResponse with an explanatory
    error (mirroring how the kernel substitutes a timed-out agent), so the run
    shows the cost of losing that role partway through.
    """

    def __init__(self, base: Agent, at_tick: int) -> None:
        super().__init__(base.agent_id, base.role)
        self._base = base
        self._at_tick = at_tick

    async def act(self, observation: Observation) -> AgentResponse:
        if observation.tick >= self._at_tick:
            return AgentResponse(
                agent_id=self.agent_id, error=f"killed@{self._at_tick}"
            )
        return await self._base.act(observation)


async def run_counterfactual(
    *,
    arm: str,
    seed: int,
    ticks: int,
    intervention: Intervention,
    runs_root: Path,
    run_id: str,
    provider: Any | None = None,
    scenario: ScenarioPack | None = None,
    baseline_run_id: str | None = None,
    tick_listener: Callable[[TickRecord, dict[str, Any]], None] | None = None,
    inter_tick_delay_s: float = 0.0,
    extra_manifest: dict[str, Any] | None = None,
) -> RunSummary:
    """Run one counterfactual: re-run from tick 0 with the intervention scheduled at N.

    Mirrors the CLI/live run wiring. The recorded manifest carries the intervention
    spec and (optionally) the baseline run id it branches from, so the observatory can
    label the branch and pin it against its baseline in Compare. Returns a normal
    RunSummary; the run lands in ``runs/<run_id>/`` and is replayable by every surface.
    """
    # Import here to avoid a circular import (arms imports this module).
    from aftershock.town.arms import build_arm

    setup = build_arm(
        arm, seed, provider, scenario=scenario, intervention=intervention
    )

    # Validate an inject_event target up front — BEFORE the recorder exists — so a
    # bad district/kind aborts loudly instead of being silently swallowed. (For
    # at_tick > 0 the injection runs inside a tick_listener, which the engine fires
    # under contextlib.suppress(Exception); without this eager check a bad target
    # would no-op and the branch would masquerade as a valid intervention.)
    if intervention.kind == "inject_event":
        from aftershock.town.society import _INJECT_KINDS

        event_kind = intervention.params.get("event", "fire")
        district = intervention.target
        valid_districts = set(setup.world.districts)
        if event_kind not in _INJECT_KINDS:
            raise ValueError(
                f"unknown inject event {event_kind!r}; valid: {sorted(_INJECT_KINDS)}"
            )
        if district not in valid_districts:
            raise ValueError(
                f"unknown district {district!r}; valid: {sorted(valid_districts)}"
            )

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "seed": seed,
        "ticks": ticks,
        "arm": arm,
        "counterfactual": {
            "at_tick": intervention.at_tick,
            "kind": intervention.kind,
            "target": intervention.target,
            "params": dict(intervention.params),
            "branch_of": baseline_run_id,
        },
    }
    # Caller-supplied manifest extras (e.g. the scenario provenance block, so a
    # scenario-backed branch is honestly labelled REAL and its prefix is byte-
    # identical to the scenario baseline). Never override the keys set above.
    if extra_manifest:
        for key, value in extra_manifest.items():
            manifest.setdefault(key, value)

    runs_root.mkdir(parents=True, exist_ok=True)
    recorder = Recorder(runs_root, run_id, manifest)
    try:
        # inject_event: queue the injection so it drains in at_tick's scheduled_events.
        # The society drains its queue on the NEXT scheduled_events call, so queue it at
        # the end of tick at_tick-1 (or immediately, before the loop, when at_tick == 0).
        listener = tick_listener
        if intervention.kind == "inject_event":
            event_kind = intervention.params.get("event", "fire")
            district = intervention.target
            society = setup.society

            if intervention.at_tick == 0:
                society.inject_event(event_kind, district)
            else:
                queue_after = intervention.at_tick - 1

                def _inject_listener(
                    record: TickRecord, world_state: dict[str, Any]
                ) -> None:
                    if record.tick == queue_after:
                        society.inject_event(event_kind, district)
                    if tick_listener is not None:
                        tick_listener(record, world_state)

                listener = _inject_listener

        engine = Engine(
            world=setup.world,
            society=setup.society,
            agents=setup.agents,
            registry=setup.registry,
            roles=setup.roles,
            resolver=setup.resolver,
            recorder=recorder,
            seed=seed,
            max_ticks=ticks,
            agent_timeout_s=setup.default_timeout_s,
            tick_listener=listener,
        )
        return await engine.run(inter_tick_delay_s=inter_tick_delay_s)
    finally:
        # engine.run() closes the recorder on its happy path; this finally guards the
        # error path so a mid-run failure can't leak file handles or leave an
        # unfinalized run.json (Recorder.close is idempotent).
        recorder.close()
