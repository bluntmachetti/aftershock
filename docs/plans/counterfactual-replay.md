# Plan A — Counterfactual "Intervention Replay"

**Goal:** Let a judge pick a recorded (or fresh) run, schedule a single *intervention*
at tick *N* (drop the negotiation protocol, kill the commander, downgrade a role's
model, or inject an event), re-run from tick 0, and watch the two timelines share an
identical prefix and diverge only at *N* — proving causation, live, on the map.

**Why this design:** the engine derives per-tick RNG purely from `rng_for(seed, "tick",
tick)` (`engine.py:156`) — not from accumulated state. So a re-run from tick 0 with the
same seed reproduces the original tick-for-tick *until* the intervention fires. No
`TownState.from_dict()` and no engine-buffer snapshotting required; the determinism
invariant (`aftershock verify`) is untouched. The intervention is the *only* thing that
differs between baseline and counterfactual.

---

## Core mechanism: the Intervention

An intervention is a small declarative object applied at the start of a chosen tick.
Five kinds map onto knobs `build_arm` already exposes plus the society's existing
inject queue:

| kind | effect | applied via |
|---|---|---|
| `drop_protocol` | swap `TownResolver` → `DefaultResolver` from tick N onward | resolver wrapper |
| `kill_agent` | a named agent returns empty `AgentResponse` from tick N | agent wrapper |
| `downgrade_role` | re-point a role to a cheaper/stronger model from tick N | (society/live only) role_models — see note |
| `inject_event` | queue a fire / aftershock / road_block at tick N | `TownSociety.inject_event` (already exists, `society.py:125`) |
| `none` | baseline (control) | — |

`drop_protocol`, `kill_agent`, `inject_event` work with the **scripted** arm — fully
deterministic, no API key. `downgrade_role` only changes behavior on LLM arms (model
swap mid-run is non-trivial; scope it to the live/society path or defer to v2).

---

## Backend

### B1. `Intervention` dataclass + wrappers — `town/counterfactual.py` (new)

```python
@dataclass(frozen=True)
class Intervention:
    at_tick: int
    kind: str            # drop_protocol | kill_agent | downgrade_role | inject_event | none
    target: str = ""     # agent_id (kill), role (downgrade), district (inject)
    params: dict[str, Any] = field(default_factory=dict)  # e.g. {"model": "..."} / {"event": "fire"}
```

Two thin wrappers that delegate until `tick >= at_tick`:

- `class SwitchingResolver` — wraps the real resolver; for `drop_protocol`, delegates to
  the wrapped resolver while `tick < at_tick`, then to a private `DefaultResolver()`
  thereafter. Implements the `Resolver` Protocol (`negotiation.py:16`); `name` reports
  e.g. `"auction→default@N"` so it shows in records.
- `class GatedAgent(Agent)` — wraps an agent; for `kill_agent` where `agent_id == target`,
  returns `AgentResponse(agent_id=..., error="killed@N")` once `tick >= at_tick`. Reads
  tick from the `Observation` passed to `act()` so no extra state. (`engine.py:197` calls
  `agent.act(obs)`; `obs.tick` is available.)

`inject_event` needs no wrapper — schedule it by calling `society.inject_event(event,
district)` exactly once when the engine reaches `at_tick`. Cleanest hook: a tiny
`tick_listener` the runner installs that fires the injection at the start of tick
`at_tick - 1` so it lands in tick `at_tick`'s timeline step (verify off-by-one against
`society.py:154-160`).

### B2. Wire intervention into `build_arm` — `town/arms.py`

Add `intervention: Intervention | None = None` to `build_arm` (`arms.py:65`). After the
normal setup, if an intervention is present:
- `drop_protocol` → wrap `setup.resolver` in `SwitchingResolver`.
- `kill_agent` → wrap the target in `GatedAgent` inside `setup.agents`.
- `downgrade_role` → for LLM arms, build that role's agent with the overridden model
  (reuse the existing `role_models` path) — but only takes effect from `at_tick`, which
  for an LLM arm means rebuilding the agent's provider call mid-run; **defer to v2** unless
  live-society is in scope. Document the limitation.
- `inject_event` → leave agents/resolver alone; return the intervention so the runner can
  schedule the injection.

Keep the default `None` byte-identical to today (no wrapper constructed) so every existing
test and `verify` is unaffected.

### B3. Runner — `town/counterfactual.py`

```python
async def run_counterfactual(
    *, arm, seed, ticks, intervention, runs_root, provider=None, tick_listener=None,
) -> RunSummary
```

Mirror `cli.py:286-322` / `web.py:_run_live`: `build_arm(..., intervention=...)`, new
`Recorder` with manifest carrying `{"counterfactual": {at_tick, kind, target, params},
"branch_of": <baseline_run_id|null>}`, `Engine(...)`, `engine.run()`. If
`intervention.kind == "inject_event"`, install the scheduling listener. Returns a
`RunSummary` exactly like a normal run, so the run lands in `runs/` and is replayable by
every existing surface.

### B4. CLI subcommand — `cli.py`

`aftershock counterfactual --seed 42 --ticks 60 --arm scripted --at 20 --kind drop_protocol`
(+ `--target`, `--event`, `--district`). Thin wrapper over `run_counterfactual`. Lets you
generate branch runs offline for the demo and gives a determinism test target.

### B5. HTTP endpoint — `web.py`

`POST /api/counterfactual` (token-gated, like `/api/live`, `web.py` auth pattern):
body `{baseline_run_id?, arm, seed, ticks?, at_tick, kind, target?, params?}`. Reuse the
`_run_live` streaming machinery (`web.py:393` `_on_tick` → WS broadcast) so the branch
streams to the client identically to a live run. On `done`, the run is in `runs/` and the
client flips Compare to `(baseline_run_id, new_branch_run_id)`.

Determinism guard: the endpoint must reuse the **same seed** as the baseline so the shared
prefix holds. Validate `0 <= at_tick < ticks`.

---

## Frontend

The Compare surface already does same-seed, shared-cursor, two-map replay with a
winner-attributed delta strip (`lib/compare.ts`, `components/CompareTab.tsx`). The
counterfactual reuses it — the right side is the branch run.

### F1. `api.ts`
Add:
```ts
counterfactual: (body: {
  baselineRunId?: string; arm: string; seed: number; ticks?: number;
  atTick: number; kind: string; target?: string; params?: Record<string, unknown>;
}): Promise<{ live_id: string }> => post('/api/counterfactual', { ... })
```

### F2. Intervention picker — new `components/CounterfactualControls.tsx`
A compact form on the Compare tab (gated by `api.hasToken()`): kind dropdown, tick slider
(reusing `Scrubber.tsx` styling), target/event selects. On submit → `api.counterfactual`,
then subscribe to the live WS (same hook `LiveTab` uses) for the branch, and set the
Compare controller `{leftRunId: baseline, rightRunId: branch, cursorTick: atTick}`.

### F3. Divergence marker — `components/Scrubber.tsx` + `CompareTab.tsx`
Draw a vertical rule at `atTick` on the shared scrubber and a "DIVERGES HERE" pill. Before
`atTick` the delta strip is all-ties (proof the prefix is identical); after, the deltas
fan out. No change to `compare.ts` math — it already computes `left − right` per tick.

### F4. Types — `types.ts`
Add the counterfactual manifest block (`{at_tick, kind, target, branch_of}`) to
`RunDetail` so the header can label a branch run.

---

## Tests

1. **Determinism / prefix identity** (the headline correctness test) —
   `tests/test_counterfactual.py`: run baseline `scripted seed=42 ticks=60`; run
   counterfactual `kind=none`; assert **every** `world_digest` is identical
   (intervention=none ⇒ byte-identical run). Then `kind=drop_protocol at_tick=30`: assert
   `world_digest` identical for ticks `0..29` and divergent somewhere in `30..`. This is
   the proof the whole feature rests on.
2. `kill_agent` produces `error="killed@N"` only from `at_tick`; earlier ticks unaffected.
3. `inject_event` lands a mission/blockage in the correct tick's events (off-by-one check).
4. `SwitchingResolver` delegates correctly across the boundary (unit test, no engine).
5. `build_arm(intervention=None)` is byte-identical to today — guard against regressions
   (run an existing determinism test unchanged).
6. Web: `compare.test.ts`-style test that the delta strip is all-ties pre-`atTick`.
7. `aftershock verify --seed 42 --ticks 60` still passes (must, per CLAUDE.md invariant).

---

## Sequencing (est. 1.5–2 days)

1. B1 `Intervention` + `SwitchingResolver` + `GatedAgent` + unit tests (½ day).
2. B2/B3 `build_arm` wiring + `run_counterfactual` + determinism test #1 (½ day) — **the
   feature is provably correct after this step, headless.**
3. B4 CLI subcommand (quick) — generate demo branch runs.
4. B5 endpoint + F1/F2 controls + F3 divergence marker (½ day).
5. F4 + polish + the demo script for the 3-min video (½ day).

## Risks / watch-items
- **Off-by-one on injection tick** — pin with test #3 against `society.scheduled_events`.
- **`downgrade_role` mid-run on LLM arms** is the one hard case; ship scripted-arm
  interventions first (deterministic, key-free) and treat live-society downgrade as v2.
- **Don't touch `kernel/protocol.py` or the snapshot test** (frozen invariant).
- **Scenario run-dir overwrite** (CLAUDE.md invariant #4): branch runs must use a distinct
  run_id; the recorder already namespaces by run_id, but pick branch seeds/ids that won't
  collide with published synthetic runs.
- Keep all `#rrggbb` for the divergence marker in `web/src/lib/palette.ts` (invariant #5).

## Judging-criteria payoff
- **Technical Depth (30%)** — live, manipulable proof of the determinism invariant.
- **Innovation (30%)** — counterfactual replay is the legible way to *prove* the protocol
  causes its effect on outcomes, not just correlate with it.
- **Problem Value (25%)** — generalizes Aftershock toward the "architecture leaderboard"
  in Future Work.
- **Presentation (15%)** — one decision, two diverging timelines: the video's best 30s.
