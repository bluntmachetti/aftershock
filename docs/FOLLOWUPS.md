# Follow-ups

Short list of known project tasks that are not part of the current deployment path.

## ▶ NEXT SESSION — resume here: Tier-0 measurement (society/swarm improvement program)

**Goal:** build the measurement foundation that makes every later agent-tuning experiment
*believable*, before tuning anything. **Full backlog (44 experiments, 5 tiers, all grounded against
`docs/FIELD-NOTES.md`):** `.omc/research/improvement-experiments.md` — read it first.

**Why measurement first (the framing):** the *engine* is byte-deterministic, but the *LLM arms are
not* — `llm/provider.py` sends `temperature` (0.3 for all roles) but **no `seed`** to DashScope, so
`society`/`solo`/`swarm` vary run-to-run (the published `103.2 ± 23.6` is an n=5 mean; that ± *is*
the sampling noise — scripted's `± 18` is pure world variance). With σ≈24 and n=5, power to detect a
**+10-life** effect is only ~35% — you currently can't tell a real +5 from noise. Also: scripted
(106.8) ≈ every LLM arm, so agent tweaks are bounded to ~10–15 lives *until* the world is made harder
(Tier 4). So Tier 0 = make a +5 statistically visible.

**Do these (exact knobs in the backlog doc):**
1. **M3 — ablation harness + power curve** (`src/aftershock/bench.py`): `run_ablation(control,
   treatment, common_seeds)` → paired per-seed Δ, sign/bootstrap test, "to detect +X lives need N
   seeds" curve. **Build this first — no LLM cost**, codifies the tool-ablation pattern (note 12) so
   every later result is paired + credible.
2. **M5 — free diagnostics** (post-process existing `runs/*/ticks.ndjson`, $0): auction loss-reason
   classification (priority-inversion vs pure shortage), proposal→ruling→arrival latency,
   cross-arm conformance calibration (scripted must read 1.0). Likely shows *where* lives leak.
3. **M1 — seed the DashScope sampler** (`llm/provider.py:111` chat body): add
   `seed = hash(engine_seed, agent_id, tick)`; thread the engine seed through `llm/agent.py`. If
   DashScope honors it → society/swarm become *reproducible* (collapses the variance problem, and is
   a strong honest story). **Verify** with two re-runs of `society-seed42` → byte-identical decision
   records; risk: DashScope may ignore `seed` (test on `MockProvider` first, gate behind a flag).
4. **M2 — K-repeats-per-seed** (`bench.py --repeat-seeds`): split within-seed (LLM) vs between-seed
   (world) variance; tells you how many seeds you actually need.

**Then** (next tiers, only once the harness exists): S1 fix the infra agent (only role <0.85
conformance), S2 partial-grant auction (hypothesised +10–15, the big lever), W1 swarm `INFO_SHARE`,
D2 tighter pools to separate the arms, then memory-v2 + an autoresearch loop (optimise *conformance*
not lives, gate on held-out seeds).

**Constraints (do not violate):** `kernel/protocol.py` + `tests/test_protocol_snapshot.py` are
FROZEN (no new proposal kinds — tune the auction *policy* in `town/society.py` only); `bench` rejects
`--scenario` (published 4-arm results stay synthetic-seed); the **scripted arm must stay
byte-identical** (`aftershock verify` + the determinism invariant); don't re-propose the known
failures — naive cross-run memory (note 8, −9 lives) and native function calling (note 12, ~2× cost).
LLM-arm runs need `DASHSCOPE_API_KEY` (~$0.01/seed; a 10-iteration autoresearch loop ≈ $0.30).

**Also pending from this session (not blockers):** Field Log **003 blog draft is written but
UNCOMMITTED** (`blog/_posts/2026-06-15-we-drew-the-auction-on-the-map.md`) — awaiting Kenny's voice
pass before publishing (do NOT push; Pages auto-deploys on push). Optionally promote the experiment
backlog from `.omc/research/` into committed `docs/`. Optionally add a FIELD-NOTES/README note making
the engine-vs-LLM determinism distinction explicit.

## Mission Control observatory redesign — MERGED + DEPLOYED (staging + prod, live)

**PR #3 squash-merged** (commit `11e99ab`; Codex P2 on contention-link attribution resolved in-PR)
and **deployed through the full promotion gate: k12 staging (.153) → Alicloud prod
(43.98.166.22) → live at <https://aftershock.redoubtlabs.dev>** (HTTP 200, identical bundle
`index-B_zrmfmx.js` local→staging→prod; contention overlay confirmed rendering on the live
society run). All 3 open questions answered: **Tiles + contention
overlay committed · Map-tab only · Ida stays on Map with provenance.** Contract: `docs/DESIGN.md`
§"Mission Control map". Plan/prototype: `.omc/plans/mission-control-redesign.md`,
`.omc/mission-control-prototype/` (live result shots in `rendered/live/`).

- **Built (frontend-only):** `MissionControlShell` (EOC header band — CONDITION + saved/lost/active/
  at-risk + op clock), `MissionControlMap` (schematic tile backdrop + the existing rich markers +
  contention overlay from `lib/contention.ts`), `lib/{condition,resources}.ts`, `mapShared.tsx`
  (extracted markers/popover — `TownMap` untouched ⇒ Compare unaffected). Palette frozen; additive
  `CONTENTION_COLOR` + `CONDITION_COLORS` only.
- **Verified:** tsc · vitest 123/123 (7 new) · build · grep-gate · `aftershock verify` determinism
  PASS · 1080p shots of Map (overlay on `seed42-society`), Compare (unaffected), and the **NYC-Ida
  provenance path** (`seed91-scripted`: borough names + DataChip + RealityStrip + REAL·NYC IDA
  badges + caveat). 6-agent adversarial review: 4 APPROVE / 2 COMMENT, 2 real defects fixed.
- **Deployed 2026-06-14:** staging (`.153:~/aftershock-deploy`, rsync + compose up) and prod
  (`43.98.166.22:/root/aftershock-deploy`, git pull + compose up) — both verified.
  Note: the society arm on Ida (`seed91-society`) shows the shortage *textually* in the negotiation
  feed but draws no map contention links — NYC-Ida demand mass-exhausts pools (no winner-vs-loser
  contest); the winner/loser overlay is demoed on synthetic `seed42-society`.
- **Deferred follow-ups surfaced:** adopt the prototype's refined GLOBAL palette (deeper surfaces +
  tuned signals incl. society→#46b6f0) across all tabs; denser per-prototype rail restyle.
- **Server papercut observed (pre-existing, not this PR):** `aftershock serve` snapshots the runs
  list at startup, so a scenario run generated while the server is up shows `scenario=null` until
  restart — restart `serve` to surface a freshly-generated pack's provenance.

## Shipped this session (2026-06-14)

- **Function calling (PRs #1 + #2, merged + deployed to k12 staging + Alicloud prod):** native Qwen
  function calling is now an opt-in (`--society-tools` / `build_llm_agents(force_tools=True)`); the
  society arm **default is JSON-contract mode** (cost-optimal — restores the "matches solo cheaper"
  headline). Benchmark showed tool mode ~2× cost / ~2.5× latency for statistically-equal lives
  (structural per-call schema overhead). Ablation published: `bench/results/2026-06-13-tool-ablation/`;
  finding in `docs/FIELD-NOTES.md` §12; README "Native Qwen function calling (measured ablation)".
- **Build blog reskin (live):** dropped minima for the custom "Field Log" mission-control theme
  (`blog/_layouts/*`, `blog/assets/css/blog.css`); markdown posts render natively; new post
  "We added native function calling. The benchmark told us to turn it off." Author byline set to
  **Kenny Ademolu** (GitHub/Pages handle stays bluntmachetti). Live: <https://bluntmachetti.github.io/aftershock/>.
- **README refresh** (committed `bdaf21e`): observatory feature line now notes the Mission Control
  command map + live contention overlay + condition state. Numbers/benchmarks unchanged.
- **Improvement-experiment program scoped** (this session, not yet executed): repo-wide lever map →
  `.omc/research/improvement-experiments.md` (44 experiments, 5 tiers). Resume target = Tier 0
  (see the "▶ NEXT SESSION" section at the top).

## Observatory

- Fix Compare-tab provenance: the header `DATA` chip is currently driven by the single Map
  timeline, so Compare can show no chip or stale Map-run provenance while the Compare view is
  showing a shared real scenario.
- Decide whether scenario CLI run ids should include scenario identity. Current ids remain
  `seed{N}-{arm}`, so scenario runs can overwrite synthetic runs with the same seed/arm.
- Refresh stale UI copy: `LiveTab` says its synthetic tick default matches the server default even
  though the UI passes 60 explicitly while the omitted server default is 30.

## Deferred Scope

- `tur-2023` scenario pack remains deferred.
