# Follow-ups

Short list of known project tasks that are not part of the current deployment path.

## ▶▶ LATEST SESSION (2026-06-17) — live demo + onboarding SHIPPED to prod; local-Qwen §22 landed

**Shipped + LIVE this session** (all merged to `main` + deployed through the gate to k12 staging + Alicloud
prod, verified at <https://aftershock.redoubtlabs.dev>):
- **Judge-facing live demo + cold-start onboarding** (the `feature/live-negotiation-dashboard` "Feature 2"
  thread): B1 = a paced scripted live stream + Stop/take-control; then a **server-side ambient demo loop**
  (`AFTERSHOCK_DEMO_MODE=1` → looping scripted run over the read-only WS, read-only-by-default UI,
  token-gated operator controls that pre-empt + resume the loop) (**PR #14**); a committed **`OBSERVATORY_BIND`**
  knob (compose default loopback; staging sets `0.0.0.0` for LAN access); and **cold-start onboarding** — an
  analyst "what's happening now" ticker, a dismissible per-audience briefing banner, and a `?` help drawer
  (focus-trap/Esc) (**PR #16**, CCG + Claude PR-reviewed, 4 findings fixed). Honesty kept: the public ambient
  stream is the **scripted** arm (not live LLM agents). Architecture/state in memory
  `aftershock-live-ambient-demo`; the onboarding spec is `.omc/research/live-onboarding-plan.md`.
- **Local-Qwen enablers + FIELD-NOTES §22** (**PR #15**): the 3 cloud-safe enablers (`DASHSCOPE_BASE_URL`,
  `reasoning_effort:"none"` on non-DashScope, `DASHSCOPE_MODEL`) + the size-sweep writeup + 8 tests — this
  CLOSED the prior handoff's "DECIDED NEXT STEP" (now merged, no longer uncommitted).
- `main` green (vitest 150, ruff, `aftershock verify` PASS). Optional follow-ups: delete the merged remote
  branches (`feature/live-negotiation-dashboard`, `local-qwen-endpoint`, `feat/live-onboarding`); a `blog/`
  post (Blog Post Prize, ~17 commits since the last entry). The older S1/§18–21 work + Field Log 005 stay
  done/live (history further below).

**▶ RESUME HERE — local-Qwen experiments backlog (free, on k12).** The enablers are MERGED and the path WORKS;
the **size sweep is DONE (§22)**. Remaining open experiments: **(b) reproducibility measurement** (2× same-seed
local runs → quantify digest drift; determinism is marginal — greedy temp0+seed flips on near-ties) and
**(c) free high-n re-tests of §18 (doctrine) / §21 (contract-trim)** on a 2nd (local) model. k12 setup to resume:

- **k12 = `kademolu@192.168.4.153`** (Fedora; Ryzen 7 + **Radeon 780M iGPU**, 88 GB RAM, no NVIDIA/CUDA).
  ROCm/iGPU inference works (~11.5 tok/s).
- **Ollama** = profile-gated service in `~/Projects/infra/k12-staging/compose.yaml`
  (`docker compose --profile gpu up -d ollama`; container `k12-staging-ollama-1`, port `192.168.4.153:11434`,
  weights on `/srv/bulk/models`, caps 10G/6cpu, **`OLLAMA_NUM_PARALLEL=1`** so 6 agents/tick serialize).
- **Models:** `qwen3.5:9b` (real 9.7B Q4_K_M) + `qwen3:1.7b`. **Both are Qwen3 *thinking* models.**
- **KEY FINDING + FIX:** Ollama's `/v1` endpoint **ignores** DashScope's `enable_thinking:false` → models
  burn ~300 reasoning tokens/call (~12–40 s) → timeouts. **Fix: send `reasoning_effort:"none"`** on
  non-DashScope endpoints → ~20× faster, real negotiation, 0 timeouts. (`/no_think` and `/v1` `think:false`
  do NOT work; native `/api/chat` `think:false` works but returns md-fenced JSON.)
- **3 code enablers — MERGED (PR #15)** (cloud-safe; 8 enabler tests; cloud request stays byte-identical):
  1. `llm/provider.py`: `base_url` honors `DASHSCOPE_BASE_URL` env (+ `self._is_dashscope` detection).
  2. `llm/provider.py`: adds `reasoning_effort:"none"` to the body when `not self._is_dashscope`.
  3. `cli.py`: `_resolve_role_models()` folds a `DASHSCOPE_MODEL` env (global model for all roles) into
     `role_models`; explicit `--role-model` still wins per role. Unknown (local) model names → cost $0.
- **Run recipe (on k12):** `cd ~/aftershock-exp` then
  `DASHSCOPE_BASE_URL=http://192.168.4.153:11434/v1 DASHSCOPE_MODEL=qwen3:1.7b DASHSCOPE_API_KEY=ollama
  uv run --no-sync aftershock bench --arms society --seeds 42 --ticks 60 --out runs/<name>`. Pin warm first:
  `curl …/api/generate -d '{"model":"qwen3:1.7b","prompt":"hi","keep_alive":-1}'`. Launch detached:
  `setsid nohup bash script.sh > log 2>&1 &` (a plain backgrounded SSH session dies — use setsid+nohup + poll the log).
- **Speed:** 1.7b ~1.5 min/tick (~1 h/60-tick run); **9b ~4 h serialized**. To speed 9b: set
  `OLLAMA_NUM_PARALLEL` >1 (one-line env on the ollama service + restart — touches their infra compose; flag first).
- **Determinism: MARGINAL** — greedy (temp 0 + seed) is *usually* byte-identical but **flips on near-ties**,
  so a full ~180-call run is unlikely to be perfectly reproducible. The "reproducibility" experiment is a
  *measurement* (quantify drift), not a guaranteed win.
- **RESULT — 1.7b collapses (size-sweep low end, DONE):** `runs/bench-1.7b/society-seed42/summary.json` —
  **0 lives saved, 162 lost, 0/11 missions resolved, team_alignment 0.258** (vs cloud ~0.85–0.92);
  per-role medical 0.0, rescue 0.0, fire 0.20, commander 0.25, comms 0.31, infra 0.515. Early-exit tick 37
  (all missions terminal), ~22 min, $0, thinking-off (not a timeout artifact). **Finding: the protocol does
  NOT hold at 1.7B** — the model can't sustain the contract/auction/doctrine.
- **RESULT — 9b carries the protocol (size-sweep contrast, DONE):** `runs/run-9b/seed42-society/` on k12 —
  **81 lives saved, 71 lost, 10/1 missions resolved/failed, team_alignment 0.787** (per-role: commander/
  comms/fire/rescue 1.0, medical 0.667, **infra 0.5 — weakest, same as §19/§20**). Early-exit tick 31, ~35 min,
  2 timeouts, $0. (`run --timeout 300`, not `bench` — the 45 s bench timeout can't absorb 6 serialized 9b
  agents under `OLLAMA_NUM_PARALLEL=1`; conformance computed via `conformance.check_run`, the metric `bench`
  uses → apples-to-apples with 1.7b.)
- **SIZE-SWEEP VERDICT: the protocol has a capability floor between 1.7B and 9B.** 1.7b collapses
  (0 lives, 0.258 conf) → 9b works (81 lives, 0.787 conf ≈ cloud ~0.85). So "the protocol carries the result"
  holds only *above* a model-capability threshold. n=1 per model (lives noisy; conformance reliable).
- **The prior handoff's "DECIDED NEXT STEP" = DONE** (PR #15: enablers committed + §22 written + tests, all
  merged to main; size sweep (a) complete). The remaining open experiments are **(b) reproducibility** and
  **(c) high-n §18/§21 re-tests**, summarised at the top of this section.
- **HONESTY CAVEAT (still applies to any local run):** local open-weight `qwen3.5:9b` ≠ DashScope's hosted
  `qwen3.5-flash/plus` (same family, different size/serving/tune) → a **separate, clearly-labelled**
  robustness/methodology study, NOT a re-run of the published cloud numbers.
- **Resuming runs:** the enablers are merged, so a normal `uv run aftershock run …` (with the `DASHSCOPE_*`
  env from the recipe above) works from any clean checkout — no more `~/aftershock-exp --no-sync`. Before new
  runs, `pgrep -af aftershock` on k12 may show a **stray run/bench process** — kill leftovers first. Raw runs
  stay on k12 (not committed).

## (COMPLETED 2026-06-16 — history) Tier-1 bid-discipline / S1 — the infra agent was THE lever

**Status (2026-06-16): Tier-0 done; Tier-1 questions answered; the doctrine on/off ablation (§11) is now
resolved.** The harness (M1/M2/M3/M5) + D2 were built, paid-verified, used to kill/qualify levers, and
hardened. Full suite green (**853 tests**), ruff clean, `aftershock verify` PASS, frozen
`kernel/protocol.py` untouched. **On main:** PR #4 (Tier-0 harness + D2), PR #5 (+28 re-check), PR #6
(Field Logs 003+004, live at <https://bluntmachetti.github.io/aftershock/>), PR #7 (ablation verdict
hardening). **UNCOMMITTED on main:** the doctrine on/off ablation work (see next paragraph). **Full
backlog:** `.omc/research/improvement-experiments.md`.

**▶ Doctrine on/off ablation — DONE 2026-06-16 (FIELD-NOTES §18, resolves §11; UNCOMMITTED, ready to
commit/PR).** Built the missing mechanism — a `doctrine: bool` knob on `build_arm`/`build_llm_agents`
(default on = byte-identical to the published behaviour; scripted unaffected) and a same-arm ablation
path `aftershock ablation --ablate doctrine --control society --treatment society` that pairs on a
synthetic label, **leads with the deterministic conformance Δ** (the §11 primary signal), demotes the
noisy lives Δ to a clearly-labelled secondary verdict, and warns when conformance is missing/partial.
+26 tests, ruff clean, `verify` PASS; passed a 4-dimension adversarial review (3 clean; the one real
finding — a silent over-claim when conformance is absent — was fixed + tested). **Paid run** (society,
seeds 11/23/37/42/57, 60t, **$0.41, 19 min**, `bench/results/2026-06-16-doctrine-ablation/`):
- **Conformance (primary, deterministic):** 0.696 → 0.852, **Δ +0.156, all 5 seeds positive** — the
  confident finding (n=5 exact sign test floors at p=0.0625, so add a 6th seed for a formal "credible").
  Per-role: comms +0.219, rescue +0.169, medical +0.160, fire +0.103, **infra +0.094 still chronic at
  0.667**, commander flat (ceiling).
- **Lives (secondary, noisy):** 100.4 → 104.2, Δ +3.8, CI [+0.2,+8.6] but sign p=0.375 → "suggestive".
  So the §11 n=1 "−17 lives cost" was a **small-sample artifact**: doctrine buys conformance at **no
  detectable lives cost**. (Absolute conformance ≠ §11's 0.759/0.904 — the checker was hardened since;
  compare the ~+0.15 effect, not the levels.)
- **Files (uncommitted):** `src/aftershock/town/{prompts,arms}.py`, `src/aftershock/{bench,cli}.py`,
  `tests/test_{arms,doctrine,bench,bench_e2e,cli_arms}.py`, `docs/FIELD-NOTES.md` (§18 + §11 pointer),
  results dir. **Commit it** (branch off main first), then optionally PR.

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
- **Not done (optional):** M4 full 60-tick × 5-seed σ≈23.6 re-validation (more $); M2 on the swarm arm.
  (A society-vs-swarm ablation *was* run on the harsh world — see Tier 1 below — and the published
  default-world pair was re-analysed in the +28 re-check.)

**Tier 1 (2026-06-15) — three results:**
- **S2 (partial-grant auction) is KILLED by measurement** — the backlog's "single biggest lever".
  0 priority inversions in the default (9 runs) and `--pools tight` (6 runs) worlds; even on the
  harshest world (all pools=2) only 6 of 794 losses are inversions (<1%, dwarfed by 443 pure-shortage).
  The auction's arbitration is sound. **Do not build S2.** (FIELD-NOTES §15–16.)
- **D2 (configurable pools) is BUILT** — `--pools tight|scarce|kind=N` on run/bench/ablation; default
  world byte-identical. Pool sweep (scripted): default 98% resolved → tight 92 → scarce 87 →
  harsh(all=2) 80 → brutal 54. "harsh" = genuine triage (lives saved ≈ lost).
- **No harsh-world lives advantage (a caught false positive)** — society-vs-swarm ablation looked like
  **Δ +16** at n=5 (CI excluded 0) but **collapsed to +4.7 at n=11** (CI [−4.0,+14.7] includes 0, sign
  test p=1.0, power 0.15). The n=5 "win" + "robustness" story were small-sample artifacts (two lucky
  seeds). **No detectable society-vs-swarm lives edge under scarcity.** The harness did its job — it
  stopped a plausible wrong headline. (FIELD-NOTES §16; `bench/results/2026-06-15-harsh-ablation/`.)

**The bottom line for next session:** the auction is *not* the bottleneck (S2 dead, 0 inversions), and
the arms do *not* separate on lives even under triage (the +16 was noise). The society's honest story is
**cost-efficiency + conformance** — and the doctrine ablation (§18) now *confirms* doctrine as a
conformance lever (+0.156, 5/5 seeds) at no lives cost. So **stop chasing a harsh-world lives lever** and
aim at the conformance story — specifically the one role still leaking it: **infra (S1)**.

**Resume here (in order):**
1. **Commit the doctrine ablation + README/Devpost caveat work** (§18 + the +28 caveats; uncommitted on
   main — branch off first). Optionally PR.
2. **DONE (2026-06-16): caveated the "+28" in README.md + docs/SUBMISSION.md** (Devpost/video script) —
   "light caveat, keep the number" framing: kept ≈+28 as the headline, appended a one-line honesty note
   (n=5 paired mean; directionally robust — society ≥ swarm on all 5 seeds; magnitude soft — sign test
   p=0.125, power 0.42, one seed dominates; §17). Video beat-3 spoken line kept, with a not-spoken
   director's note to render any lower-third as "≈+28 (n=5)". SUBMISSION "what we learned" also now points
   at §18 as the most robust number. (Source: `bench/results/2026-06-15-plus28-recheck/`, FIELD-NOTES §17.)
3. **DONE (2026-06-16): S1 infra prompt fix (FIELD-NOTES §19, branch `s1-infra-fix`).** Rewrote
   `roles/infrastructure.yaml` to tie each rule to the agent's observation labels → **infra conformance
   0.667 → 0.863 (+0.196, 5/5 seeds), team alignment +0.064, lives flat (−0.6, no regression — gate
   passes), infra violations 61 → 24.** But a partial win: **T3 urgency fully fixed (calibration prompts
   well); I1 repair-preconditions STAYED STICKY (0.627 → 0.560) — precondition-gating resists prompting.**
   (`bench/results/2026-06-16-s1-infra-fix/ANALYSIS.md`.)
4. **DONE (2026-06-16): I1 investigated → guard killed; model bump shipped as an operating mode
   (FIELD-NOTES §20, branch `s1-infra-model`).** The "deterministic I1 guard" is a **metric-gaming trap**:
   the world already rejects invalid `repair_road` (`RepairRoadHandler.validate`, before `apply()` — zero
   resource cost, outcome-neutral) and conformance I1 counts the *attempt*, so a drop-filter would only hide
   LLM behaviour. **Not built.** Instead proved I1 is a **model-capability floor**: infra flash→plus lifts
   **I1 0.560 → 0.957** (infra conf 0.863 → 0.986, 5/5 seeds) — but lives flat, **cost +33%, lives-per-$
   −24%**. Shipped as an **opt-in operating mode**, not the default: a general `--role-model
   infrastructure=qwen3.5-plus` override (default stays flash → headline numbers untouched).
   `bench/results/2026-06-16-s1-infra-model/ANALYSIS.md`.
5. **DONE (2026-06-16): next-lever scoping (workflow) + cost lever (FIELD-NOTES §21, branch
   `cost-contract-trim`).** A scoping workflow scored S3/W1/redundant/S4 against the §20 outcome-neutrality
   gate — **all four SKIP** (S3: missions_failed in {0,1}, no headroom, failed missions WON their grants;
   redundant bids never decrement `remaining` = $0.0001/run; S4: premise wrong — commander is 45.5% of cost
   not 59%, and 72% of cost is INPUT tokens temp can't touch; W1: only one with real headroom but can't reach
   it + contaminates the +28 control). That surfaced the real lever — **static-prompt cost**: ~60% of run
   cost is a 941-tok system prompt re-sent every tick. **Caching is a dead end** (~$0.01 probe: DashScope-Intl
   returns no `cached_tokens` → our full-rate ledger is accurate). **Contract trim** (compact JSON skeleton +
   dedup Hard Rules + compress proposal docs; doctrine/role untouched) → paired A/B vs s1-infra-fix:
   **cost −14%, lives-per-$ +21%**, lives +4 (p=0.125, up), conformance −0.037 (p=0.375 NOT significant —
   watch-item). **KEPT.** Society ~$0.04/run is mostly structural; −14% ≈ the safe ceiling.
6. **▶ Open follow-ups:** (a) refresh README/SUBMISSION society cost **downward** (~−14%, lives-per-$ up) in
   a later pass — needs a fresh 4-arm bench for a consistent table; (b) watch conformance if more contract
   trims are tried (§21 dip); (c) cheap: a 6th seed on the §18 doctrine ablation tips its conformance verdict
   from the n=5 sign-test floor (p=0.0625) to a formal "credible". **Avoid:** metric-gaming guards (§20),
   auction policy (S2 dead §15), harsh-world lives (§16), the four scoped-and-skipped levers.
7. **memory-v2 / autoresearch on conformance** (Tier 3) — now that the harness can say "credible"
   honestly, an autoresearch loop can optimise conformance and gate on `verdict == "credible"`.
8. **Optional, paid:** M4 full 60-tick × 5-seed σ re-validation; a properly-powered (~25-seed)
   society-vs-swarm ablation if a lives claim ever needs firming.

**Harness hardened (PR #7):** the `aftershock ablation` verdict now requires the bootstrap CI **and** the
sign test to agree before reading "credible" — three tiers (`noise` / `suggestive` / `credible`) exposed
as a structured `verdict` field for programmatic gating. The +28 and the n=5 harsh result now read
"suggestive", not "credible" (closing the over-claim from FIELD-NOTES §16–17).

**Constraints (do not violate):** `kernel/protocol.py` + `tests/test_protocol_snapshot.py` are
FROZEN (no new proposal kinds — tune the auction *policy* in `town/society.py` only); `bench` rejects
`--scenario` (published 4-arm results stay synthetic-seed); the **scripted arm must stay
byte-identical** (`aftershock verify` + the determinism invariant); don't re-propose the known
failures — naive cross-run memory (note 8, −9 lives) and native function calling (note 12, ~2× cost).
LLM-arm runs need `DASHSCOPE_API_KEY` (~$0.01/seed; a 10-iteration autoresearch loop ≈ $0.30).

**Also pending (not blockers):** Field Logs **003 + 004 + 005 are PUBLISHED and live**
(<https://bluntmachetti.github.io/aftershock/>; 003/004 = PR #6, **005 = PR #12, merged to main
2026-06-16** — "the fix that would have only fooled the scoreboard", the §18–21 tuning arc + the
outcome-neutrality lesson). The engine-vs-LLM determinism distinction is explicit (FIELD-NOTES §13).
Still optional: promote the experiment backlog from `.omc/research/` into committed `docs/`.

**▶ Parked, waiting on hackathon credits (later 2026-06-16):**
1. **README/SUBMISSION cost refresh** — the §21 contract trim cut society cost ~14% (lives-per-$
   ~2,440 → ~2,800+). The published numbers should be refreshed *downward*; do it via a fresh,
   consistent **4-arm bench** (not a hand-edit), then update the headline table + finding #2 ratios.
2. **(Optional) firm the §21 conformance dip** — the trim's −0.037 team-alignment is non-significant
   at n=5 (p=0.375); ~5 more paired seeds would resolve whether it's real or noise.

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
