# Follow-ups

Short list of known project tasks that are not part of the current deployment path.

## ▶ NEXT SESSION — resume here: Tier-1 levers (Tier-0 measurement is DONE)

**Status: the Tier-0 measurement harness is BUILT and VERIFIED (2026-06-14).** Code + tests for
M1/M2/M3/M5 (committed on branch `tier0-measurement-harness`); full suite green (812 tests), ruff
clean, `aftershock verify` PASS, frozen `kernel/protocol.py` untouched; 6-dimension adversarial review
(5 findings fixed); paid M1/M2 verification run (see below). **Full backlog:**
`.omc/research/improvement-experiments.md`.

**What shipped (new surfaces):**
- **M3 ablation** — `aftershock ablation --control X --treatment Y --seeds 11,23,37,42,57` → paired
  per-seed Δ, exact sign test, deterministic bootstrap CI, "+X lives needs N seeds" power curve.
  Writes `ABLATION.md`/`ablation.json`. Pure stats in **`src/aftershock/stats.py`** (no numpy/scipy:
  hand-rolled norm_cdf/ppf, sign test, bootstrap, power, variance components — all hand-verified).
- **M5 diagnostics** — `aftershock diagnose <run_dir>...` → auction-loss classification
  (**priority_inversion** vs displacement vs pure_shortage vs redundant), spawn→request→arrival
  latency split by outcome, cross-arm conformance calibration (scripted anchor confirmed = 1.000).
  **`src/aftershock/town/diagnostics.py`**. NOTE: inversion is detected by reconstructing winners
  (accepted grants) vs losers per (tick,resource) — NOT from the loser's reason string (the review
  proved the reason-string approach is dead code: real inversions surface as the *shortage* form).
- **M1 seed sampler** — `--seed-sampler` on `run`/`bench` threads a deterministic per-(seed,agent,
  tick) SHA-256 seed into the provider body (gated; scripted untouched).
- **M2 repeats** — `aftershock bench --repeat-seeds N` → within-seed (LLM) vs between-seed (world)
  variance split + ICC. Rejects `--seed-sampler` (the two are contradictory: M1 removes the variance
  M2 measures).

**Paid Tier-0 verification — DONE (2026-06-14, results in `bench/results/2026-06-14-tier0-verification/`,
write-up in `docs/FIELD-NOTES.md` §13–14):**
- **M1: DashScope IGNORES `seed`.** Seeded society runs diverge at tick 1 exactly like the unseeded
  baseline → no reproducibility. `--seed-sampler` kept as a documented no-op. Lean on pairing, not seeds.
- **M2: the world is ~79% of the variance** (society, 3 seeds × 3 repeats, 30 ticks): σ_within(LLM)=7.75,
  σ_between(world)=14.87, ICC=0.79. **So pair, don't repeat** — paired-Δ SD ≈ 11 vs unpaired ≈ 23.7;
  detecting +10 lives at 80% power needs ~10 paired seeds vs ~45 unpaired. Repeats only buy down the 21%.
- **Not done (optional):** M4 full 60-tick × 5-seed σ≈23.6 re-validation (more $); a first real
  `society`-vs-`swarm` ablation; M2 on the swarm arm.

**Tier 1 so far (2026-06-15):**
- **S2 (partial-grant auction) is KILLED by measurement** — the backlog's "single biggest lever". The
  M5 diagnostic found **0 priority inversions** in the default world (9 society runs), and D2's harder
  world (`--pools tight`, 6 runs) still produced **0** — 133 contested losses across both worlds, every
  one legitimate (loser priority ≤ winner). The auction's arbitration is sound; the pathology S2 fixes
  doesn't exist here. **Do not build S2.** (FIELD-NOTES §15; `bench/results/2026-06-15-d2-tight/`.)
- **D2 (configurable pools) is BUILT** — `--pools tight|scarce|kind=N` on run/bench/ablation; default
  world byte-identical. Tightening raised contention but the task stays ~93% resolved.

**Resume here → Tier 1, redirected away from auction policy (gate each behind `aftershock ablation`):**
1. **Bid discipline / S1** — the dominant auction-loss category is `redundant` (50–57/run: agents
   re-requesting already-satisfied resources) and the infra agent is the only role <0.85 conformance.
   A conformance/cost lever (harmless to lives, but cleans up churn) — measure via the conformance
   track, not lives.
2. **For a lives effect, force genuine triage** — the task is still ~93% resolved even on tight pools,
   so no lever moves lives until you can't-save-everyone. Push harder than `tight` (`--pools scarce`,
   or raise mission load via a new harder timeline / D1-style bigger Ida) so *prioritization quality*
   — not auction mechanics — separates the arms. THEN an ablation can show a real Δ.
3. Then memory-v2 + an autoresearch loop (optimise *conformance* not lives, gate on held-out seeds).
   S3 (deadline-sort) and W1 (swarm INFO_SHARE) remain available but are lower priority given the
   auction is not the bottleneck.

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
