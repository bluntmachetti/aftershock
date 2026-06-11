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
