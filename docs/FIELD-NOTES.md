# Field notes: what the town taught us about agent behavior

A running log of empirical findings from building and operating Aftershock —
specifically about how LLM agents behave in a multi-agent society. Every entry is
backed by recorded runs in this repository; where a finding changed the design, the
change is noted. Newest entries last.

---

## 1. Small models don't learn from one-tick feedback (2026-06-11)

**Observed:** in the first live society run, the infrastructure agent attempted the
same invalid `repair_road` decision seven ticks in a row. Every attempt was rejected
with a clear reason ("road in district 'market' is not blocked"), and the rejection
was shown in the agent's next observation — once.

**Interpretation:** a single-tick feedback window is below the attention threshold of
small models in long contexts. Showing a rejection once is not teaching; it's a
footnote the model skims past while re-deriving the same plan from the same world view.

**Change:** rejection feedback now persists for 3 ticks in every observation
(`Engine(rejection_memory_ticks=3)`), labelled "RECENTLY REJECTED — do not repeat."

## 2. Agents invent entity IDs unless validation pushes back (2026-06-11)

**Observed:** agents referenced districts that don't exist (`d1`, `harbor industrial`)
despite the observation listing the real IDs. The decision registry rejected each with
a reason naming the failure.

**Interpretation:** models pattern-complete plausible identifiers under generation
pressure. Prompt-side discipline ("use exact IDs from the observation") reduces but
does not eliminate it; engine-side validation with *specific, named* rejection reasons
is the actual guardrail — and doubles as the training signal (see note 1).

## 3. A coordination protocol is worth 28 lives per run (2026-06-11)

**Observed:** five identical seeded disasters, two arms with the *same* five
qwen3.5-flash models: with the negotiation protocol, 103.2 lives saved (0.4 missions
failed); without it, 75.6 (3.0 failed). The run records show the mechanism — the
protocol-less swarm wasted 160 decisions racing each other for already-empty resource
pools, while the society's auction resolved contention *before* anyone acted, with
losers told exactly what outbid them.

**Interpretation:** uncoordinated capable agents don't degrade gracefully; they
collide. Conflict resolution as a mechanic (typed proposals, atomic rulings, reasons)
converts contention from wasted actions into information.

Full tables: [bench/results/2026-06-11](../bench/results/2026-06-11/RESULTS.md).

## 4. A society of cheap models matches a flagship at 65% of the cost (2026-06-11)

**Observed:** coordinated qwen3.5-flash workers under a qwen3.5-plus commander saved
103.2 lives per run; one qwen3-max doing every role alone saved 104.2 — statistically
indistinguishable — at $0.065/run vs the society's $0.042, and 1.6× slower (sequential
big calls lose to parallel small ones).

**Interpretation:** for decomposable real-time work, architecture substitutes for
model scale. Spend intelligence where decisions concentrate (arbitration), not
uniformly.

## 5. The honest caveat: the protocol carries more than the models do (2026-06-11)

**Observed:** scripted heuristic agents using the same negotiation protocol scored
106.8 lives — competitive with every LLM arm — at $0.

**Interpretation:** on a legible, well-structured task, doctrine embodied in simple
rules rivals LLM reasoning. The interesting LLM contributions appear at the edges:
handling injected surprises, prose rationales, and analysis. We publish this rather
than hide it; it is the strongest argument that *coordination structure* is the
load-bearing component of an agent society.

## 6. Format contracts work: zero malformed outputs in 174+ live calls (2026-06-11)

**Observed:** across every live run to date, no agent response failed JSON parsing or
schema validation — including under injected mid-run surprises.

**Interpretation:** a single shared output contract (exact JSON schema, allowed
decisions with usage lines, hard rules) appended to every system prompt, plus JSON
mode, removes an entire failure class that multi-agent systems are assumed to suffer.
The failures that remain are *semantic* (notes 1, 2) — which is where attention should
go.

## 7. An LLM analyst will confidently narrate wrong data (2026-06-11)

**Observed:** a data bug fed the after-action analyst per-mission "saved=0" for every
mission while the final score line directly above said `lives_saved: 96`. qwen3-max
wrote a fluent, internally consistent report concluding the response "saved zero
lives" — trusting the granular detail over the contradicting total, and never flagging
the inconsistency.

**Interpretation:** analyst models do not audit their inputs; they harmonize them.
Plausible narration is not evidence the underlying data is right. We now pin the data
pipeline with a reconciliation test (per-mission outcomes must sum to the final
score) — the analyst gets numbers that have already been forced to agree.

## 8. The memory paradox: naive cross-run memory made the society worse (2026-06-11)

**Observed:** five sequential disasters with after-action lessons fed to the
commander's next briefing, against a paired memoryless control on identical seeds:
flat while lessons were few, then **−7 to −10 lives on every seed** once two or more
lessons accumulated (mean −9). The accumulated lessons were strategically plausible
but mechanically unactionable ("pre-position crews before disaster onset" — the
disaster *starts* at tick 0).

**Interpretation:** advice an agent cannot act on is not neutral — it is a distractor
tax on its context. Memory loops need lessons expressed in the agent's actual action
space, or they subtract value. (n=5, sign test p≈0.125 — direction uniform, treated
as a strong hypothesis, not a proof; v2 of this experiment is planned with
doctrine-grounded lessons.)

Data: [bench/results/2026-06-11/episodes-v1](../bench/results/2026-06-11/episodes-v1/ANALYSIS.md).

## 9. Don't trust a model's self-report — even about its own name (2026-06-11)

**Observed:** in a smoke test, `qwen3-max` introduced itself as "Llama."

**Interpretation:** trivially harmless here, but a useful reminder with teeth:
self-descriptions (identity, confidence, claimed reasoning) are generated text, not
introspection. Everything we measure about agents in this project is measured from
their *recorded actions*, never their claims — that principle is why the provenance
log exists.

## 10. Methodology notes that earned their keep (2026-06-11)

- **Identical seeded worlds per arm** turn anecdotes into paired comparisons (notes
  3, 4, 8 are only claimable because of this).
- **A $0 scripted baseline** catches a silent failure mode: if bots score like LLM
  agents, your decisions may be decorative. It also calibrates the conformance
  checker (scripted agents embody the doctrine; flagging them means the checker is
  wrong).
- **Per-entity outcomes over aggregates**: "all missions resolved" can coexist with
  heavy casualties; we report both.
- **Negative results get published** (notes 5, 8). They are the reason to believe
  the positive ones.

## 11. Written doctrine raises conformance — outcomes TBD (2026-06-11)

**Observed:** we gave every agent a two-tier playbook (six shared coordination rules,
two-three role rules each) and built a deterministic conformance checker over the run
records (no LLM judging; scripted agents calibrate it at 1.0 team alignment). On the
same seed: doctrine-naive agents scored **0.759** team alignment; with the doctrine in
their prompts, **0.904** — five of six roles improved (comms 0.83→1.00, rescue
0.63→0.84), infrastructure improved but remains the chronic offender (0.56→0.69, still
attempting repairs with no crew available).

**Tension to resolve:** the doctrine run saved *fewer* lives (96 vs 113, n=1). Possibly
noise — but it rhymes with note 8: every instruction added to a prompt has a cost, and
discipline is not automatically performance. A paired doctrine-on/off comparison across
seeds is queued; until then we claim the conformance effect, not an outcome effect.

**Also:** verifying the checkers was its own lesson. Of twelve review findings against
the conformance engine, the confirmed ones were almost all *measurement* bugs —
degenerate denominators (rules whose "applicable" count only incremented on violation,
making rates 0-or-1), rules applied to arms whose protocol makes them impossible, and a
calibration test that passed vacuously because 16 of 19 rules never occurred in the
calibration scenario. Measuring agent behavior is as bug-prone as the behavior itself;
our anti-vacuity guard now asserts the calibration actually exercises its rules.

## 12. Native function calling cost ~2× for statistically-equal lives (2026-06-14)

**Observed:** we re-ran the full 4-arm benchmark with the society arm switched from
JSON-contract prompting to Qwen Cloud native function calling (per-role `tools`,
`tool_choice="auto"`, `parallel_tool_calls`, a `no_op` idle tool). On the same 5 paired
seeds the society held lives saved within noise (98.2 ± 23.2 vs 103.2 ± 23.6) and missions
failed near-flat (0.8 vs 0.4), but **cost roughly doubled ($0.042 → $0.083/run) and latency
rose ~2.5× (120 s → 297 s/run)**. The control arm `scripted` reproduced byte-identically
across both runs, so the harness — not sampling — is sound; the LLM-arm drift (solo 104→110,
swarm 76→77) is ordinary run-to-run variance. Cost breakdown for `society-seed42`: the
qwen3.5-plus commander was 59% of cost (55.5k prompt + 10.2k completion tokens), the five
flash workers 41% (290.8k prompt tokens — schema-dominated).

**Interpretation:** the premium is structural, not a tuning miss. A role's tool schema is
~1,000 tokens and is re-sent on *every* one of ~240 agent calls per run; in JSON mode the
equivalent action vocabulary lives in a ~450-token prose contract. We projected every trim
strategy — stripping pydantic `title`/`default` noise, compacting descriptions, even gutting
them to empty — and the floor is ~$0.069/run, still above both the JSON society ($0.042) and
the qwen3-max solo baseline ($0.061). For a high-frequency multi-agent society, per-call
schema overhead dominates; you cannot schema-trim your way under the JSON path.

**Decision:** JSON contracts stay the cost-optimal **default** (and the path the published
benchmark headline reflects). Native function calling is kept implemented, tested, and
benchmarked as an opt-in behind `--society-tools` / `build_llm_agents(force_tools=True)`,
with its numbers published as an ablation
([bench/results/2026-06-13-tool-ablation/](../bench/results/2026-06-13-tool-ablation/RESULTS.md)).
The lesson generalizes: "use the fancier API" is not free — for societies that call the model
hundreds of times per run, measure the per-call overhead before adopting it by default.

## 13. DashScope ignores the sampling seed — the LLM arms can't be made reproducible (2026-06-14)

**Observed:** Tier-0 experiment M1 added an opt-in `--seed-sampler` that sends a deterministic
per-`(engine_seed, agent_id, tick)` `seed` on every DashScope call (the OpenAI-compatible endpoint
accepts a top-level `seed`). We ran `society` seed 42 × 30 ticks **twice with** the sampler and
**twice without**, then compared the recorded decision streams. All four runs diverge at **tick 1**
in decision content (and tick 6 in the world trajectory); the seeded pair landed 96 vs 99 lives, the
unseeded pair 90 vs 98 — **the seeded pair is no more alike than the unseeded baseline.** DashScope
accepts `seed` in the request body but does not honor it for reproducibility (at temperature 0.3).

**Interpretation:** the LLM arms are irreducibly stochastic run-to-run on this provider, so the
published `±` genuinely *is* sampling noise (confirmed, not assumed). Note the trajectory holds
identical for ~5 ticks after the decisions first differ: early divergences are rationale/free-text or
proposals that resolve to the same grants — simulation-inert until they accumulate into a different
world by tick 6. Reproducibility-by-seed is off the table for Qwen Cloud.

**Decision:** keep `--seed-sampler` as a documented **no-op opt-in** (harmless; it would activate for
free if a future provider honors `seed`) and lean on the measurement levers that *don't* need
reproducibility — paired ablations (M3, which difference out the world variance), K-repeats variance
decomposition (M2), and deterministic conformance as the low-variance optimization target. The
engine stays byte-deterministic (the scripted anchor reproduces exactly); **only the model layer is
stochastic** — a distinction now made explicit rather than assumed.

## 14. The world, not the model, is most of the variance — so pair (2026-06-14)

**Observed:** Tier-0 experiment M2 ran the society arm at 3 seeds × 3 repeats (30 ticks, 9 runs) and
decomposed lives-saved variance with a one-way random-effects model (`bench --repeat-seeds`). Result:
mean 110.7, **σ_within (LLM sampling) = 7.75, σ_between (world) = 14.87, σ_total = 16.76, ICC = 0.79.**
Per-seed means spread 95.7 / 109.7 / 126.7 — the seeds differ far more than the repeats do. (Cross-check:
the four seed-42 runs from M1, which are i.i.d. since the seed is ignored, give a within-seed σ of 4.0,
consistent with the pooled 7.75.)

**Interpretation:** ~**79% of run-to-run variance is the scenario, only ~21% is model stochasticity.**
That reframes the whole measurement problem: throwing repeats at a fixed seed buys down only the small
LLM component; the dominant term is *which world you drew*. The high-leverage move is **pairing** — run
control and treatment on the *same* seeds so the world variance cancels, leaving only the arms' LLM
noise. Concretely, the paired-difference SD is √2·σ_within ≈ 11.0, versus an unpaired contrast's
√2·σ_total ≈ 23.7. Seeds needed for 80% power (α=0.05), from `stats.required_n_for_effect`:

| effect | paired (M3) | unpaired |
|---|---|---|
| +5 lives | 38 | 177 |
| +10 lives | 10 | 45 |
| +15 lives | 5 | 20 |

**Decision:** every agent-tuning result goes through the paired ablation harness (M3,
`aftershock ablation`), never a raw mean-vs-mean. ~10 paired seeds make a +10-life effect visible;
chasing a +5 is not worth it until the task is made harder (Tier 4 · D2) to widen the gap. These σ are
at 30 ticks; the published headline σ≈23.6 is 60-tick between-seed spread (variance grows as the
scenario plays out), so it is the same story at larger scale — not re-validated tick-for-tick here.

## 15. The diagnostic killed S2 before we built it — the auction isn't the bottleneck (2026-06-15)

**Observed:** S2 (partial-grant + re-auction, the backlog's "single biggest society lever, +10–15
lives") fixes a *priority inversion* — a high-priority bid losing a pool, under all-or-nothing
granting, to a later low-priority bid that fits the remainder. The M5 diagnostic (`aftershock diagnose`)
looked for it and found **none**. Default world (society, 9 runs): 0 inversions, 59 contested losses
all legitimate (loser priority ≤ winner), 253 pure-shortage, 446 redundant; only 4 missions failed vs
101 resolved. We then built D2 (configurable pools) and re-ran on a deliberately harder world
(`--pools tight`: ambulance 4→3, rescue_crew 3→2; 6 society runs): contention rose across the board
per-run (displacement 6.6→12.3, pure-shortage 28→35, redundant 50→57) and lives dipped 110.7→106.5,
but **priority_inversion stayed 0** — all 74 contested losses legitimate, verified with zero
unknown-priority lookups that could hide one. Across both worlds: **133 contested losses, every single
one legitimate.**

**Interpretation:** the all-or-nothing pathology does not occur in this domain, even under engineered
scarcity. Structural reason: the auction ranks priority-desc and serves the top mission first, and the
agents don't request quantities that exceed the pool in the way that would let a low-priority
remainder-fitter beat a high-priority bid. The auction's arbitration is *sound* — a positive result for
the "the protocol carries the result" claim (note 5). The real binding constraints are (a) **pure
shortage** (the pool is empty — a partial grant has nothing to split) and (b) **redundant bids** (50–57
per run: agents re-requesting already-satisfied resources — a discipline/conformance issue, harmless to
lives since the auction declines them). The task also stays ~93% resolved even on tight pools.

**Decision:** **do not build S2.** Two rounds of measurement refute its premise; implementing it would
optimize a pathology that isn't there. This is the Tier-0 harness paying for itself — it killed the
program's headline lever before a line of it was written. Redirect Tier 1 away from auction policy
(S2/S3) toward bid discipline (the dominant redundant category, a conformance lever) and, if a *lives*
effect is the goal, a much harsher regime that forces genuine triage (can't-save-everyone) where
prioritization quality — not auction mechanics — separates the arms. (Note 16 ran that harsher regime:
inversions do finally appear, but stay negligible — S2's verdict holds.)

## 16. The harness caught a ghost: a +16-life "win" that evaporated at 11 seeds (2026-06-15)

**Observed:** D2's harshest regime (all pools = 2 → 80% of missions resolved, lives saved ≈ lives lost,
a genuine can't-save-everyone task) was meant to let the arms separate on lives. A first paired
society-vs-swarm ablation at **n=5** looked like a hit: society 68.8 vs swarm 52.6, **Δ = +16.2** with a
95% bootstrap CI [+3.2, +29.6] that excludes 0, and society's lives looked *stable* (63–72) while swarm
looked *volatile* (32–66). Tempting story: "coordination buys graceful degradation." But the sign test
was already non-significant (p=0.375, 4+/1−) and power was only 0.57, so we added 6 seeds instead of
believing it. At **n=11 the effect collapsed: Δ = +4.73** (sd 16.66), 95% CI **[−4.0, +14.7] now
includes 0**, sign test **p=1.0 (6+/5−)**, power 0.15. The six new seeds included several where *swarm
beats society* (seeds 5/29/41 → −15/−10/−11). The n=5 result was driven entirely by two lucky draws
(seeds 11, 57) where swarm happened to crater; the "society floor holds" story was the same artifact
(at n=11 society ranges 32–80, not 63–72).

**Interpretation:** there is **no detectable society-vs-swarm lives advantage on the harsh world** — the
+16 was a small-sample false positive, exactly the failure mode the Tier-0 program exists to prevent
(σ≈17 paired, n=5 → power 0.57; you cannot trust a one-shot mean). This is the harness paying for itself
a second time: it stopped us shipping a plausible-but-wrong headline. The power curve at n=11 says a +10
effect would need ~22 seeds and the *observed* +4.7 would need ~88 — i.e. if any lives gap exists here
it is small (<10) and not worth the spend to chase.

**Lesson for the harness itself:** the `aftershock ablation` auto-verdict keys on the bootstrap CI and
printed "credible improvement" at n=5 — over-claiming on a small, skewed sample. The sign test + power
were the guardrail that said "don't believe it yet." Treat the auto-verdict as advisory below ~10 seeds;
the sign test is authoritative. (Now fixed: `analyze_ablation` requires the bootstrap CI **and** the
sign test to agree before it reads "credible", and exposes a structured `verdict` field —
`noise` / `suggestive` / `credible` — so callers gate on the value, not the prose.)

**S2 epilogue:** at this extreme scarcity priority inversions *do* finally appear — but only **6 of 794
auction losses (<1%)**, dwarfed by 443 pure-shortage (pool empty — partial grants have nothing to
split). S2's verdict (note 15: don't build it) stands even on the hardest world we can make.

**Decision:** stop chasing a harsh-world lives lever — it isn't there at any power worth buying. The
honest claims that survive: (a) the auction arbitration is sound (notes 15–16), (b) the society's value
is cost-efficiency + conformance, not a lives edge over swarm under scarcity, and (c) the published
easy-world "+28 society vs swarm" (note 3) deserves the same paired-power re-check with this harness
before it is leaned on further (done — note 17).

## 17. Re-checking the published +28: direction solid, magnitude soft (2026-06-15)

**Observed:** the harsh-world null (note 16) demanded the same scrutiny of the headline easy-world claim
(note 3, "a coordination protocol is worth 28 lives"). Running the *original published* n=5 paired data
(`bench/results/2026-06-11`, 60-tick default world) through the new paired harness: **Δ = +27.6** (sd
35.2), per-seed [+88, +7, 0, +26, +17]. **Every seed is non-negative** — 4 strictly positive, 1 tie,
0 negative. 95% bootstrap CI [+6.2, +58.0] excludes 0; **but** sign test **p=0.125** (the seed-37 tie
drops effective n to 4) and power **0.42**, and the magnitude is dominated by one seed (seed 11 = +88;
the other four average +12.5).

**Interpretation:** unlike the harsh +16 (note 16) — which had seeds going both ways and vanished at
n=11 — the easy-world gap is **directionally robust**: society ≥ swarm on *all five* seeds. So note 3's
*qualitative* claim (the coordination protocol helps on the easy world) survives the re-check. What does
*not* survive cleanly is the precise number: "+28" is underpowered, sign-test-non-significant at n=5,
and leveraged by a single seed. A tight CI on the magnitude would need ~25 seeds (power curve).

**Decision:** keep note 3's direction; when the "+28 lives" figure is *quoted* (README, Devpost),
caveat it as an n=5 paired mean with a wide CI (or add seeds to firm it). Two notes (§16–17) showed the
`aftershock ablation` auto-verdict ("credible — CI excludes 0") disagreeing with a non-significant sign
test at n=5 — so it was hardened: the verdict now requires CI **and** sign-test agreement before reading
"credible". The +28 re-rendered under the new rule reads **"suggestive but unconfirmed"** (CI excludes 0,
sign test p=0.125, power 0.42) — exactly the honest verdict.
