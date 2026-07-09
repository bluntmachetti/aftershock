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

> **Superseded/qualified by §23 (2026-06-22):** firming this comparison to n=15 paired
> seeds collapsed the "+28" magnitude to **+8.9 lives, suggestive but not statistically
> significant** (bootstrap 95% CI [+2.3, +15.4] excludes 0, but sign-test p=0.118 does not
> clear significance). The qualitative direction (society ≥ swarm) survives; the *number*
> below is an n=5 small-sample overestimate dominated by one seed. Do not quote "+28" as a
> current-state lives claim — see §23.

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

## 11. Written doctrine raises conformance — outcomes TBD → resolved in §18 (2026-06-11)

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
**→ Now run (§18, paired n=5): the conformance effect holds (+0.156, 5/5 seeds) and the
n=1 lives "cost" was an artifact — doctrine does not cost lives.**

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

## 18. Doctrine on/off, paired across seeds — it buys conformance, not lives (resolves §11) (2026-06-16)

**Setup:** the §11 tension was an n=1 anecdote (doctrine raised conformance 0.759→0.904 but *lost* lives,
96 vs 113). We finally ran the queued paired comparison: `aftershock ablation --ablate doctrine --control
society --treatment society --seeds 11,23,37,42,57 --ticks 60` — the same society arm twice per seed,
doctrine **off** (control) vs **on** (treatment), everything else (world seed, JSON-mode, default pools)
held constant. 10 LLM runs, **$0.41, 19 min**
([bench/results/2026-06-16-doctrine-ablation](../bench/results/2026-06-16-doctrine-ablation/ABLATION.md)).
This required new tooling: a `doctrine: bool` knob on `build_arm`/`build_llm_agents` (default on =
byte-identical to the published behaviour) and a same-arm ablation path that pairs on a synthetic label
and **leads with the deterministic conformance Δ** (the primary signal), demoting the noisy lives Δ to a
clearly-labelled secondary verdict.

**Conformance (primary, deterministic) — confirmed across seeds.** Team alignment **0.696 (off) → 0.852
(on), Δ = +0.156**, and *every one of the 5 seeds is positive* (per-seed Δ +0.073…+0.220). Per-role, the
gains land where §11 said they would: comms +0.219 (0.773→0.992), rescue +0.169, medical +0.160, fire
+0.103, infrastructure +0.094 — still the chronic offender at 0.667 (it keeps attempting repairs with no
crew; that's the S1 lever). Commander is flat (−0.013) because it's already near the ceiling (0.95). The
exact sign test floors at p=0.0625 at n=5 (5/5 positive can't reach <0.05 — same n=5 floor §16–17
flagged), so the auto-verdict won't print "credible" without a 6th seed; but conformance is *deterministic
and low-variance*, and a clean 5/5 with a tight, consistent magnitude band is the confident finding here,
not the lives number. (Absolute values differ from §11's 0.759/0.904 because the conformance checker was
hardened since — §11 "Also" — so compare the **effect** (~+0.15), not the levels.)

**Lives (secondary, noisy) — the §11 "cost" was an artifact.** Mean **100.4 (off) → 104.2 (on), Δ =
+3.8** (per-seed [+13, +1, −1, +5, +1]). 95% CI [+0.2, +8.6] excludes 0, but sign test p=0.375 (4+/1−)
and power 0.33 → verdict **"suggestive but unconfirmed."** So doctrine does **not** cost lives: the n=1
−17 was small-sample noise, and if anything the paired lean is *slightly positive* (within noise).

**Resolution of §11:** discipline here is not paid for in lives. Doctrine earns its keep on the signal it
was built for — coordination conformance (+0.156, 5/5 seeds, deterministic) — at **no detectable lives
cost**. This is the society's honest story in miniature: the value of the written protocol shows up as
*conformance and cost-efficiency*, not as out-saving on lives (cf. §15–17). Next: the infra role (S1) is
the one place conformance is still leaking (0.667), and it's a cheap deterministic lever.

**n=6 re-test (seeds 11,23,37,42,57,73, 2026-06-22):** conformance 0.763→0.888, Δ +0.125, 6/6 seeds
positive, sign-test p=0.03125, bootstrap CI [0.088,0.164] excludes 0 → now **CREDIBLE** (clears the n=5
sign-test floor of 0.0625). Lives Δ +6.0 remains **noise** (CI includes 0, sign p=0.375). The conformance
verdict crossing into "credible" only restates the same finding — doctrine buys conformance, not lives —
now that the 6th seed lets the deterministic signal clear the exact sign-test gate that §16–17 hardened.
Source: [bench/results/2026-06-22-doctrine-6seed](../bench/results/2026-06-22-doctrine-6seed/).

## 19. S1 — fixing the infra prompt: urgency calibrates, preconditions don't (2026-06-16)

**Setup:** §18 left infra as the lone role still leaking conformance (0.667). The diagnostic (per-rule,
over the 5 doctrine-ON runs) showed three distinct failures, not one: **T3** urgency honesty 0.350 (it set
urgency=9 with sev=3, deadline far), **T5** never-resubmit 0.000 (17/17 — it re-issued rejected repairs
every tick), and **I1** repair preconditions 0.627 (28/75 — repairing non-blocked districts *and* with no
crew). The scripted infra agent (the 1.0 anchor) gets all three right by construction. The fix was
prompt-only and deterministic-safe: rewrite `roles/infrastructure.yaml` to tie each rule to the exact
labels the agent already sees in its observation — repair_road only for a district on the **BLOCKED** line
and only while **POOLS** shows `repair_crew ≥ 1` (≤ available); urgency > 8 only when `sev ≥ 4` or
`dl_in ≤ 4`; and never reissue a decision shown under **RECENTLY REJECTED**. Re-ran 5 society cells
(doctrine on, same seeds/ticks — only the infra prompt changed), **$0.21, 8 min**, paired by seed against
the §18 doctrine-ON cells
([bench/results/2026-06-16-s1-infra-fix](../bench/results/2026-06-16-s1-infra-fix/ANALYSIS.md)).

**Result — a partial, honest win.** Infra role conformance **0.667 → 0.863, Δ +0.196, all 5 seeds
positive**; team alignment +0.064 (5/5); **lives flat: 104.2 → 103.6, Δ −0.6** (per-seed [−4,+8,−1,0,−6],
sign test p=0.625 — no regression, the gate passes). Total infra rule-violations fell **61 → 24 (−61%)**.
But the per-rule split is the real lesson:
- **T3 (urgency): 0.350 → 1.000** (13 → 0 violations). A concrete threshold the model could apply at
  decision time — cleanly fixed. T2 also went 2 → 0.
- **T5 (no-resubmit): rate still 0.000, but absolute violations 17 → 2.** It improved *upstream*, not
  because the model learned the rule: fewer invalid repairs ⇒ fewer rejections ⇒ almost nothing to
  resubmit. (When it *did* get a rejection it still resubmitted, 2/2 — so the rate metric is misleading
  here; absolute count is the honest read.)
- **I1 (repair preconditions): 0.627 → 0.560** by rate (28 → 22 absolute). **Sticky.** Even told exactly
  which observation fields to check, the flash model still attempts some repairs on non-blocked districts /
  with no crew. Precondition-*gating* is harder to prompt than scalar *calibration*.

**Takeaway:** prompt discipline reliably fixes a numeric calibration (urgency) and removes most downstream
waste, but a hard precondition check (only-if-blocked-and-crew) resists prompting — that's a candidate for
a deterministic guard at the registry/heuristic layer (frozen-protocol-safe), not more prompt text. Net:
the conformance story (the society's defensible value, §18) is now stronger and the change costs no lives,
so it ships; I1 is the honest open edge.

## 20. I1 is a model-capability floor, not a prompt or guard problem — shipped as an operating mode (2026-06-16)

**The guard that wasn't.** §19 floated "a deterministic I1 guard." Tracing the path killed that idea before
building it: `RepairRoadHandler.validate` already rejects an invalid repair (`not blocked` / `no crew`)
**before `apply()` runs**, so it consumes nothing — an invalid repair is *outcome-neutral*. And conformance
I1 counts the agent's *attempt*. So a registry/agent-layer guard that dropped the attempt would only **game
the metric** (hide the LLM's behaviour) for zero outcome gain — the exact dishonesty the conformance
contract exists to prevent. We did not build it.

**The honest lever — a stronger model.** Instead we tested whether I1's stickiness is a *capability* limit.
Re-ran the 5 society cells with **only the infra model changed**, flash → `qwen3.5-plus` (everything else =
§19), paired by seed against the §19 cells
([bench/results/2026-06-16-s1-infra-model/ANALYSIS.md](../bench/results/2026-06-16-s1-infra-model/ANALYSIS.md)):
- **I1 0.560 → 0.957** (22/50 → 1/23 violations) — the rule prompting *couldn't* move. Infra role
  conformance **0.863 → 0.986** (Δ +0.123, all 5 seeds). T5 falls to 0/0 (no invalid repairs ⇒ nothing to
  resubmit). So infra's stickiness was a **model-capability floor**: flash won't gate `repair_road` on
  (blocked ∩ crew) reliably; plus does.
- **But lives are flat** (103.6 → 103.8, sign p=1.0 — I1 was outcome-neutral) and **cost is +33%**
  ($0.041 → $0.054/run) → **lives-per-$ −24%**.

**Decision — ship it as an opt-in operating mode, not the default.** Paying +33% to perfect an
outcome-neutral discipline metric would trade away the society's headline cost-efficiency (lives-per-$ is
the README's lead number). So the cost-optimal **default stays flash** (published numbers unchanged), and
the bump is a documented operating mode: `--role-model infrastructure=qwen3.5-plus` (a general per-role
override threaded through `build_arm`/`build_llm_agents`). Flip it when conformance/discipline matters more
than cost; leave it off for the lives-per-$ story. Two honest readings of "fix I1," and the switch keeps
both — the scientific finding (it's a capability floor) is the durable result, independent of which
default ships.

## 21. Where the society's cost actually goes — and a −14% contract trim (2026-06-16)

With lives levers exhausted (§15–16) and the story pinned to cost-efficiency + conformance (§18–20), we
went after **cost** directly. A $0 profile of the records first: the commander sends **31.9k prompt tokens
but only 2.3k completion**, and its prompt mass is **45.9% of run cost** (the plus model). Decomposing one
call (~1.1k tok): a **941-token static system prompt re-sent every tick** (~29×) + only ~160 tok of
observation. The static prompt = role (289) + doctrine (~200) + **contract/format boilerplate (~452)**.
Extrapolated across all six agents, **~85% of the run's 193k prompt tokens are re-sent static prefixes**,
and since ~72% of cost is input tokens, **~60% of total run cost is the same prompts re-sent every tick.**

**Caching is a dead end here (a clean ~$0.01 negative result).** The obvious fix — context caching — does
not apply: probing the DashScope-International compatible-mode endpoint (a 958- and a 1,589-token stable
prefix, sent 3× rapidly, on both qwen3.5-plus and qwen3.5-flash) returned **no `prompt_tokens_details.
cached_tokens` and no discount** — every call bills the full prompt. So our cost ledger (full-rate
`prompt_tokens`) is **accurate, not pessimistic**; there is no free accounting win.

**The deterministic lever — trim the re-sent prefix.** Doctrine is off-limits (§18) and the role prompt is
behavioral, so the target is the contract. Profiling showed pure redundancy is small (~16 tok), so we went
aggressive: compact the multi-line JSON skeleton to one line, dedup the Hard Rules (the "JSON-only" line
duplicated the Output Format header; "≤25 words" lives in the schema), and compress the four proposal-doc
descriptions — keeping every capability + the contract's tested vocabulary. Result: commander prefix
**941 → 835 tok (−11%)**; 861 tests green, ruff clean, `aftershock verify` byte-identical.

**Paired A/B (trimmed vs full contract, 5 seeds, only `contract.py`/`PROPOSAL_DOCS` differ;
[bench/results/2026-06-16-cost-contract-trim/ANALYSIS.md](../bench/results/2026-06-16-cost-contract-trim/ANALYSIS.md)):**
- **Cost $0.0411 → $0.0353 (−14.0%)**, prompt tokens −11.2% — credible and largely deterministic.
- **Lives-per-$ 2,522 → 3,046 (+21%)** — the headline metric. **Lives 103.6 → 107.6** (Δ +4, p=0.125, up).
- **Conformance 0.916 → 0.879** (Δ −0.037, sign p=0.375) — **not** significant, within the §18–20 band
  (~0.85–0.92); a watch-item (likely the proposal-doc compression), not a credible regression. Actions
  emitted −3.3% (no parse collapse).

**Decision: KEEP.** By the same significance bar we've held all session (§16–17 — don't bless a p>α effect),
a deterministic −14% cost / +21% lives-per-$ at no *credible* lives or conformance regression is the
cost-efficiency win the program is about. The conformance dip is logged as a watch-item; the published
README/SUBMISSION cost figures can be refreshed downward in a later pass. (And the honest meta-result of
the whole cost arc: the society's ~$0.04/run is *mostly structural* — re-sent semantic prompts the agents
need — so −14% is near the safe ceiling without touching doctrine or model tier.)

## 22. The protocol has a capability floor: a self-hosted size sweep (1.7B collapses, 9B carries it) (2026-06-16)

§5 says "the protocol carries more than the models do." That holds only *above* a capability threshold — and
this is where we found the floor. While waiting on cloud credits we stood the whole society up on a **self-hosted
Qwen** (Ollama on a local box: Ryzen 7 + Radeon 780M iGPU, ROCm, ~11.5 tok/s, `OLLAMA_NUM_PARALLEL=1` so the six
agents/tick serialize) and ran the same `society` arm at two sizes. **This is a separate, clearly-labelled
robustness study, not a re-run of the published cloud numbers** — local open-weight `qwen3.5:9b` is *not*
DashScope's hosted `qwen3.5-flash`/`-plus` (same family; different size, serving, and tune). The point isn't the
absolute lives; it's where the protocol stops holding. Both runs cost **$0** (unpriced local tags → an honest $0
in the ledger).

**`qwen3:1.7b` collapses — the protocol does not hold** (`runs/bench-1.7b/society-seed42`, 60t, ~22 min,
thinking-off so not a timeout artifact): **0 lives saved, 162 lost, 0 of 11 missions resolved**, team_alignment
**0.258** (vs cloud ~0.85–0.92). Early-exit at tick 37 (all missions terminal). Per-role conformance is a
near-total collapse — medical 0.0, rescue 0.0, fire 0.20, commander 0.25, comms 0.31 — with **infra (0.515) the
*least* bad**, the only role still half-following the contract.

**`qwen3.5:9b` (real 9.7B Q4_K_M) carries it** (`runs/run-9b/seed42-society`, 60t, ~35 min, 2 timeouts):
**81 lives saved, 71 lost, 10 missions resolved / 1 failed**, team_alignment **0.787** — within reach of the cloud
~0.85. Roles recover to ceiling (commander/comms/fire/rescue 1.0, medical 0.667) with **infra (0.5) now the
*weakest*** — the same chronic infra ceiling we hit at full scale in §19–20, reproduced on a different model. (Run
via `run --timeout 300`, not `bench`: the 45 s bench timeout can't absorb six serialized 9b agents under
`NUM_PARALLEL=1`. Conformance is computed with `conformance.check_run` — the exact metric `bench` reports — so it
stays apples-to-apples with the 1.7b cell.)

**Verdict — there is a capability floor between 1.7B and 9B.** Below it the contract/auction/doctrine machinery
produces noise (0 lives, 0.258 conf); above it the society works (81 lives, 0.787 conf ≈ cloud). So §5's "the
protocol carries the result" is real but *conditional*: it needs a model good enough to sustain the protocol, and
1.7B isn't. Two caveats keep this honest: **n=1 per model** (lives are noisy at one seed; conformance is the
reliable signal), and **determinism is marginal** on a local greedy decode (temp 0 + seed is usually byte-identical
but flips on near-ties) — so, like the cloud arms which ignore the seed outright (§13), these runs aren't perfectly
reproducible; conformance, not any single record, is the stable signal.

**Reproduce** (raw records live on a local box, not committed): warm the model first
(`curl …:11434/api/generate -d '{"model":"qwen3:1.7b","prompt":"hi","keep_alive":-1}'`), then
`DASHSCOPE_BASE_URL=http://<STAGING_HOST>:11434/v1 DASHSCOPE_MODEL=qwen3:1.7b DASHSCOPE_API_KEY=ollama uv run
--no-sync aftershock run --arm society --seed 42 --ticks 60 --timeout 300 --out runs/<name>`. The three cloud-safe
enablers that make this work — `DASHSCOPE_BASE_URL`, `reasoning_effort:"none"` on non-DashScope endpoints (Ollama's
`/v1` ignores `enable_thinking`, so a Qwen3 *thinking* model otherwise burns ~300 reasoning tokens/call → ~20×
slower → timeouts), and a `DASHSCOPE_MODEL` global override — ship in `llm/provider.py` + `cli.py` and leave the
cloud request body byte-identical.

## 23. Firming the +28: it collapses to +9 at n=15 — suggestive, not significant (2026-06-22)

**Setup:** §17 left the published "+28 society vs swarm" (note 3) flagged as *directionally
robust but magnitude-soft* — an n=5 paired mean, sign-test non-significant (p=0.125), leveraged
by a single seed (seed 11 = +88). The honest next step was to firm the magnitude by adding seeds,
exactly as §17 said it would take (~25 seeds for a tight CI). We re-ran the society-vs-swarm
contrast on the **current code** across three batches and pooled them as one 15-seed paired test.

**The three runs tell the collapse story:**
- **2026-06-11, n=5** (original published, seeds {11,23,37,42,57}, 60t, default world): **Δ = +27.6**
  — the headline figure, dominated by seed 11.
- **2026-06-22, n=5** (same seeds, current code; `bench/results/2026-06-22-4arm-refresh` +
  `2026-06-22-swarm-firm`): **Δ = +14.6** — the same seeds, re-measured on current code, already
  roughly half the original.
- **2026-06-22, fresh seeds 60–69, n=10**: **Δ = +6.0** — independent draws, smaller still.

**The combined 15-seed paired test** (seeds {11,23,37,42,57} + {60..69}): **mean Δ = +8.9 lives,
society wins 11/15, bootstrap 95% CI [+2.3, +15.4] — excludes 0, but sign-test p=0.118 does not clear
significance ⇒ SUGGESTIVE, not statistically significant** (verified 3 ways: project `bootstrap_ci`
at rng_seed 20260619 and 20260614, SE-normal, and a t-interval — all exclude 0; by the harness's
3-tier rule, CI-excludes-0 XOR sign-significant = suggestive). Seed 11 (the +88 in the original n=5)
still dominates the spread; once the sample is large enough to drown a single lucky draw, the
magnitude regresses toward a small, suggestive edge. This is the same arc as the harsh-world +16
(§16), one tier milder: the direction holds (society ≥ swarm on most seeds), but the *number* does
not survive firming into significance.

**Meanwhile, the cost picture got better and the conformance finding got stronger.** The current
4-arm benchmark (n=5 seeds {11,23,37,42,57}, 60t; `bench/results/2026-06-22-4arm-refresh`):
scripted **106.8 lives / $0** (the deterministic control — byte-identical to the 2026-06-11
baseline, so the harness is still sound), society **108.4 lives / $0.0353/run / 3,069 lives-per-$**,
solo **95.6 / $0.0515 / 1,855**, swarm **93.8 / $0.0132 / 7,133**. Society cost fell from $0.0423
(2026-06-11) to $0.0353 = **−16%**, and lives-per-$ rose 2,441 → 3,069 (the §21 trim, now reflected
in the headline). Separately, the doctrine-conformance effect crossed into **credible** at n=6 (§18
n=6 update: Δ +0.125, sign-test p=0.03125, CI [0.088, 0.164]).

**Decision — reframe the submission around the robust findings, not a lives-vs-swarm magnitude.**
The defensible, firmed claims are: (1) **cost-efficiency** — six cheap qwen3.5-flash workers under
a plus commander *match* expert heuristics (scripted 106.8) and the single big model (solo 95.6) on
lives at ~$0.035/run (~16% cheaper than the first benchmark, ~3,070 lives-per-$, ~50%+ better
lives-per-dollar than the solo big model); (2) **conformance** — written doctrine raises team
alignment, now credible (n=6, p=0.031); (3) **society ≈ scripted on lives**. The society-vs-swarm
*lives* gap is presented as **suggestive, not significant** — bootstrap 95% CI [+2.3, +15.4] excludes
0, but sign-test p=0.118 does not clear significance — a small, directionally-consistent edge (+8.9
at n=15, 11/15 wins) we will not headline as a magnitude.

**Why this is a strength, not a retraction.** This is the same self-correcting harness paying for
itself a third time (cf. §16 the harsh-world ghost, §17 the first re-check): the paired-power
discipline caught our own overclaim before a judge could. The "+28" was never fraud — it was a
real n=5 paired mean with a wide CI we always labelled as soft (§17). Firming it to n=15 is the
honest follow-through, and the project's whole FIELD-NOTES habit of cataloging caught overclaims
(§7, §8, §11, §16, §17) is exactly why we trust the findings that *did* survive.

## 24. Firming the §21 contract-trim conformance dip: small, suggestive, not free (2026-06-22)

§21's −14% cost trim left a conformance **watch-item**: team_alignment 0.916 → 0.879 (Δ −0.037) at
n=5, sign p=0.375 — "could be noise." To resolve it cleanly we built a runtime A/B toggle —
`aftershock ablation --ablate contract`, mirroring the doctrine knob: a `trim` param on
`decision_contract` + `PROPOSAL_DOCS_VERBOSE` recovered byte-for-byte from `33fe876^`, with
`contract_trim` threaded through `build_arm`/`build_llm_agents`. Control = untrimmed, treatment =
trimmed, Δ = trimmed − untrimmed. (Default stays trim=on, byte-identical to main — verified across
all agents via a `33fe876^` worktree; scripted unaffected.)

**Result (n=10 paired, `bench/results/2026-06-22-contract-ablation/`):** conformance 0.898 → 0.880,
**Δ −0.019, 8/10 seeds negative, sign-test p=0.109, bootstrap 95% CI [−0.033, −0.005]**. The
`conformance_verdict` (the §18/§23-era feature) reads **suggestive** — the CI excludes 0 (the dip
leans real) but the sign test doesn't confirm. **Lives: noise** (Δ −0.9, CI [−4.4, +2.0], p=1.0).
Per-role: rescue −0.048 / medical −0.021 / comms −0.018 took most of it; infrastructure +0.057
(the verbose docs may have *over*-prompted it).

**Verdict: the dip is half the n=5 scare (~−0.019), directionally real but not credible, at zero
lives cost, inside the healthy 0.85–0.90 band → KEEP the trim.** The −16% cost win is **nearly free,
not perfectly free.** Not worth more seeds to resolve credible-vs-suggestive on a −0.019 effect.
This updates §21's watch-item. New reusable surface: `aftershock ablation --ablate contract`.

## 25. Price of anarchy: the protocol recovers ~9 pts of the lives a resource scramble leaves behind (2026-06-25)

A game-theory reframe of "society beats swarm." The town is a **common-pool resource game** —
roles claim from finite shared pools (ambulances, crews, engines, fuel) toward missions with
severity/deadline, and one claim is a negative externality on the others. Classic setting where
the *uncoordinated* outcome is inefficient (the **price of anarchy**) and a mechanism recovers
welfare. The arms line up on exactly that axis: `swarm`/`solo` have no arbitration (`DefaultResolver`,
direct dispatch) = uncoordinated; `society` adds the per-tick auction (`TownResolver`) + doctrine =
mechanism + correlation device.

Rather than raw lives, measure a bounded **efficiency** grounded in the sim's own exact accounting:
every imperiled life is saved, lost, or still-open, so `total_at_risk = lives_saved + lives_lost +
open_remaining` (an identity, no model) and `efficiency = lives_saved / total_at_risk ∈ [0,1]`.

**4-arm efficiency** (`bench/results/2026-06-22-4arm-refresh`, n=5, computed by `town/poa.py`):

| arm | efficiency | coordinated? |
|---|---|---|
| **society** | **67.3%** | yes (auction + doctrine) |
| scripted | 66.2% | yes (central heuristic) |
| solo | 58.9% | no |
| swarm | 58.1% | no |

The structural separation is the real result: **both coordinated arms (~66–67%) sit above both
uncoordinated ones (~58%)**, and the *expensive single big model (solo) lands at the swarm's anarchy
level* — coordination beats raw model size for this allocation problem. *(Refined in §28: the "big
solo sits at the anarchy floor" reading is Qwen-specific — a genuine frontier solo reaches the
outcome ceiling; the durable claim is coordination beats model size on **cost**, not lives.)*

**society vs swarm, paired within-batch, pooled to n=15** (refresh seeds {11,23,37,42,57} +
`2026-06-22-swarm-firm` {60..69}): **mean +6.7 efficiency pts**, society wins **11/15**, bootstrap
95% CI **[+2.6, +10.8] excludes 0**, sign-test **p=0.118**, **price of anarchy 1.11×** → **suggestive,
not significant** — the *same* statistical strength as the raw-lives §23 result. The reframe is more
*interpretable* (bounded, structural) but does **not** manufacture significance.

**Honesty bound:** the denominator is the rigorous **save-everyone ceiling** (efficiency=1.0), NOT a
tight *achievable* optimum — the true optimum is a multi-tick resource-scheduling problem over the
deterministic world and is intractable to compute exactly, so we report "fraction of saveable," never
"fraction of optimal." **Real-scenario caveat:** on the brutal NYC-Ida pack (`seed91`) the order
*flips* — scripted saves 32.2% vs society's 8.9%; the coordination edge is a synthetic-benchmark
finding, and the LLM society is not magic on a hard real scenario.

**Verdict:** the coordinated-vs-uncoordinated efficiency gap is a clean *structural* pattern (and
`solo ≈ swarm` is the sharp honest point); the pairwise society-vs-swarm edge stays **suggestive**
(p=0.118), consistent with §23. New reusable surface: `aftershock poa` / `town/poa.py`.

## 26. Bigger model, same outcome: a whole-roster tier sweep says harness beats model size (2026-06-30)

§20 found a **model-capability floor** by swapping *one* role (infra) flash→plus. This generalises
it to the **whole roster**: hold the society arm, the auction, the doctrine, and the seeded world
byte-fixed, and swap **all six** roles across three price tiers — `flash` (0.10/0.40 \$/Mtok),
`plus` (0.40/2.40), `max` (1.20/6.00) — via `aftershock bench --role-model "commander=…,…"`. 10
paired synthetic seeds {11,23,37,42,57,73,89,101,113,127} × 60 ticks. Motivated by an external
question (does a bigger C-suite model decide better, i.e. is GPU capex justified?) — the answer is
meant to gate hardware spend *before* it happens.

| tier | lives saved (sd) | team-align | cost / run | lives-per-\$ | wall |
|---|---|---|---|---|---|
| **flash** (all six) | 106.0 (±16.9) | 0.872 | \$0.0248 | **4272** | 55 s |
| **plus** (all six) | 107.5 (±17.0) | 0.890 | \$0.0892 | 1205 | 88 s |
| **max** (all six) | 107.0 (±16.6) | 0.879 | \$0.2404 | **445** | 92 s |

**Lives are flat.** Every pairwise paired delta is noise: plus−flash **+1.5** (sign p=0.754, 4+/6−),
max−flash **+1.0** (p=1.000, 5+/5−), max−plus **−0.5** (p=0.453) — all dwarfed by the per-seed sd
≈17. The seed-paired rows are nearly identical across tiers (seed 11: 140/136/136; seed 127:
83/82/82; seed 73: 126/131/130): the **world draw sets the outcome, not the model tier** — §14's
"world = 79 % of variance" showing through directly. Conformance (team-alignment) is also flat
(0.872 / 0.890 / 0.879), while **cost rises 9.7×** and **lives-per-\$ collapses 9.6×** flash→max.

**Harness beats model size.** Put this next to the cheap levers: doctrine on/off buys a **credible**
team-alignment **+0.125** (§18, p=0.031) at **\$0** extra; the §21 contract trim *cuts* cost −14 %
for +21 % lives-per-\$. A 10× whole-roster model spend buys **neither lives nor conformance** above
the §22 capability floor. So once the roster clears that floor, the lever that moves the outcome is
the *harness* (doctrine, contract, prompt — §18/§19/§21), not the model tier.

**Verdict (the GPU-capex gate): KILL.** The (bigger − smaller) decision-quality delta is inside
control noise on every axis, so no GPU capex is justified for this allocation task — the cheapest
roster that clears the §22 floor stands, and discretionary spend should go to harness/doctrine, not
a larger model. **Caveats:** this is *above-floor* (the §22 1.7B-collapse is the real boundary;
below it model size is everything); lives sd≈17 means small per-tier lives effects (<~3) stay
underpowered at n=10 — but a *flat* result across a 10× tier span is itself the finding, and it is
monotone-null (no tier ordering on lives). Reusable surface: `bench --role-model "<six roles>"`.
Data: `bench/results/2026-06-30-mtier-{flash,plus,max}`.

## 27. The coordination advantage is friction-gated: a price-of-anarchy curve across pool scarcity (2026-06-30)

§25 measured the price of anarchy at *one* scarcity level. This sweeps it. Hold the seeded world
and the arms fixed and vary only the resource abundance — a clean uniform pool ladder
`ambulance=…=supply_truck = {12, 6, 4, 2, 1}` via `bench --pools` — running the coordinated arms
(`scripted` central heuristic, `society` LLM+auction) against the uncoordinated `swarm`
(`DefaultResolver`, direct dispatch). 8 paired seeds × 60 ticks per level. Efficiency =
`lives_saved / (saved+lost+open)` ∈ [0,1] via `town/poa.py`. This answers an external open question
(arena `econ-theory-partial-equilibrium-agents-matter`: *which frictions are load-bearing for agent
strategy to matter?*) on the abstract structural claim.

| pool / kind | contested losses† | scripted eff | society eff | swarm eff | society − swarm | PoA | sign(soc>swarm) |
|---|---|---|---|---|---|---|---|
| **12 (abundance)** | 12 | 73.9 % | 73.7 % | **79.3 %** | **−5.6 pt** | 0.93 | **0/8, p=0.008** |
| 6 | — | 72.4 % | 72.1 % | 72.3 % | −0.1 pt | 1.00 | 3/8, p=0.727 |
| 4 (≈default) | 222 | 69.2 % | 68.0 % | 61.9 % | +6.1 pt | 1.10 | 6/8, p=0.289 |
| **2** | 612 | 50.7 % | 47.1 % | 39.7 % | **+7.3 pt** | **1.18** | 6/8, p=0.289 |
| 1 (extreme) | 1424 | 23.6 % | 20.1 % | 19.9 % | +0.2 pt | 1.01 | 4/8, p=1.000 |

†`pure_shortage` contested-loss count from `aftershock diagnose` (3-seed society sample) — friction
bites monotonically as pools tighten (12 → 222 → 612 → 1424), and **priority inversions stay 0 until
pool=1** (then 26), corroborating §15 (the auction is arbitration-sound except at the brutal floor).

**The coordination advantage is an inverted-U, gated by friction.** At **abundance** there is no
contention, so the auction is *pure overhead*: the uncoordinated swarm wins (79.3 % vs 73.7 %, PoA
**0.93**, society loses **8/8 seeds, p=0.008** — the statistically *strongest* cell). At **moderate
scarcity** (pool 2–4) coordination pulls ahead (+6–7 pt, PoA up to **1.18**), though the win is
**suggestive not significant** at n=8 (p=0.289 — the same strength as §23/§25). At the **extreme
floor** (pool=1) everyone collapses to ~20 % and the gap vanishes (p=1.0) — nothing left to arbitrate.

**Two durable reads.** (1) **Friction is necessary for coordination to matter — and its absence makes
coordination net-harmful**, so any "agents/structure beat the baseline" claim must declare its
scarcity regime or it is unfalsifiable (directly the arena methodological point). (2) **`scripted` ≈
`society` at every single level** (73.9/73.7, 72.4/72.1, 69.2/68.0, 50.7/47.1, 23.6/20.1) → the lever
is the *coordination mechanism*, not LLM-vs-heuristic — the same conclusion as §26 (model tier inert)
and §25 (`solo ≈ swarm`). **Honesty bound:** the abundance reversal is significant (p=0.008); the
mid-scarcity coordination wins are suggestive (p=0.289, n=8) — add seeds before quoting the +7 pt as
real. Reusable surface: `bench --pools` + `aftershock poa` / `diagnose`. Data:
`bench/results/2026-06-30-fric-{p12,p6,p4,p2,p1}` (lean — summaries only).

## 28. Is it just Qwen? A 12-model cross-family panel says the claim holds (2026-07-01)

Every claim so far rides on Qwen models, so the fair critique is: *is "coordination beats model size"
a Qwen artifact?* This tests it across **12 models from ~9 families** on the substrate's honest,
subsidy-free outcome. Each model powers the **`solo` arm** (one model runs the whole town) over the
same 10 paired seeds × 60 ticks, served via OpenRouter (the new family-agnostic provider path), priced
from a committed list. Comparator = the cheap all-flash Qwen **society** (§26): **106.0 lives,
$0.025/run, 4272 lives/$**.

| solo model | lives (sd) | cost | lives/$ | Δ vs society | sign test |
|---|---|---|---|---|---|
| gpt-5 · gemini-3.1-pro · opus-4.8 · grok-4.3 (US frontier) | 106–109 | $0.08–0.36 | 306–1408 | +0 … +3 | all p ≥ 0.29 |
| deepseek-v4-pro/flash · kimi-k2.7 · glm-5.2 (CN frontier) | 102–105 | $0.006–0.076 | 1345–**17782** | −0.6 … −4.4 | all p ≥ 0.5 |
| **cheap Qwen society** | **106.0** | **$0.025** | **4272** | — | — |
| mistral-large / llama-3.3-70b / qwen3-235b (open-weight) | 80–98 | $0.003–0.023 | 4114–28k | −8 … −26 | 2 of 3 p=0.002 |
| llama-3.1-8b (floor) | 24.6 (±22.3) | $0.001 | 32958 | −81.4 | p=0.002 |

**Three durable reads.** (1) **No model's solo beats the cheap six-flash coordinated society on
lives.** The eight frontier-class models — US *and* Chinese — only **tie** it (Δ ∈ [−4.4, +3.0], every
sign test p ≥ 0.29 → indistinguishable at n=10, sd≈16). So the claim *survives* cross-family, but with
an honest refinement of the Qwen-only §4 result: a genuine frontier solo *reaches* the coordination
ceiling on the outcome (a big *Qwen* solo did not). (2) **The frontiers pay 3–14× for that tie** —
lives-per-$ 306–1595 vs the society's 4272 — so the win is decisively on **cost-efficiency**, family-
wide. The one honest dent: `deepseek-v4-flash` ties on lives at **4× better** cost-efficiency
($17782/life), a genuinely strong cheap solo. (3) **Below the frontier, solos fall off** (mistral
−10.9, qwen3-235b −26.3, both p=0.002) and the **8B floor collapses** (24.6 lives, p=0.002) — a clean
cross-family capability floor, echoing §22's 1.7B.

**Caveats:** independent-seed (LLM layer non-deterministic, §13); the prompts/contract are Qwen-tuned,
so a weaker cross-family score is partly prompt-fit — but all 12 parsed the JSON contract cleanly, and
the *frontier* tie is the load-bearing result. External list prices drift (as-of 2026-07-01). Spend
~$14.5. New reusable surface: family-agnostic provider (`DASHSCOPE_BASE_URL` → OpenRouter/Featherless)
+ `AFTERSHOCK_MODEL_PRICES`. Data: `bench/results/2026-07-01-panelA-solo/` (12 model cells + comparator).
