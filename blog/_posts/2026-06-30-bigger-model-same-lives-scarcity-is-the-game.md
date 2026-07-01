---
layout: post
title: "We paid 10× for a bigger model and saved zero extra lives — then watched coordination backfire when nothing was scarce"
date: 2026-06-30 09:00:00 -0700
description: "Two open questions I'd been carrying from a larger agent-organisation project, run on Aftershock because it has something that project lacks: a conserved, subsidy-free outcome (lives saved). First: does a bigger C-suite model decide better? Swapping the whole six-role society from cheap qwen3.5-flash up through plus to qwen3-max over ten paired seeds, lives stay flat (106.0 → 107.5 → 107.0, every pairwise sign test p>0.45) while cost rises 9.7× and lives-per-dollar collapses 9.6×. Above the capability floor, model tier is outcome-neutral — a clean GPU-capex KILL. Second: when does coordination actually matter? Sweeping resource scarcity from abundance to famine, the society-vs-swarm advantage is an inverted-U gated by friction: at abundance coordination is net-HARMFUL (the uncoordinated swarm wins 79.3% vs 73.7%, society loses all 8 seeds, p=0.008), it peaks at moderate scarcity (price of anarchy 1.18×), and vanishes at the collapse floor. The through-line: scripted ≈ society at every tier and every scarcity level — the lever is coordination structure under contention, not model size."
log: "010"
read: "9 min"
summary: "I borrowed two open questions about agent societies and answered them on Aftershock, whose conserved lives-saved metric lets you separate 'the agent is good' from 'the substrate carried it.' (1) Does a bigger model decide better? Swapping the whole society roster flash → plus → max over 10 paired seeds: lives flat (106/107.5/107, all sign tests p>0.45), cost 9.7×, lives-per-dollar collapses 9.6×. Above the capability floor, model size buys nothing — a GPU-capex KILL; the cheap discipline lever (doctrine, +0.125 conformance at $0) moves what model scaling doesn't. (2) When does coordination matter? Sweeping pools from abundance to famine, the society-vs-swarm edge is an inverted-U: at abundance the auction is pure overhead and the swarm wins (p=0.008, the strongest cell in the study); it peaks at moderate scarcity (PoA 1.18×, suggestive p=0.289); it disappears at the floor where everything fails. scripted ≈ society at every level → the lever is coordination structure under contention, not model quality. Honest about what stays suggestive at n=8."
flags:
  - text: "10× model spend → +0 lives"
    kind: warn
  - text: "lives-per-$ collapses 9.6×"
    kind: warn
  - text: "Coordination is friction-gated"
    kind: ok
  - text: "At abundance, coordination backfires (p=0.008)"
    kind: warn
---

Most of these logs report one experiment. This one reports two, because they turned out to be the
same finding wearing two costumes — and because they came from the same place: a pair of open
questions I'd been carrying around from a larger project on agent-run *organisations*. That project
has a frustrating property — its main outcome signal is swamped by background noise, so it struggles
to tell *"the agent made a good call"* apart from *"the environment would have carried any agent."*
[**Aftershock**](https://github.com/bluntmachetti/aftershock) has the opposite property, and it's the
whole reason it exists: its outcome is **lives saved**, a conserved quantity with no hidden subsidy.
Every imperiled life is saved, lost, or still-open — an identity, not a model. So I brought the two
questions here, where the substrate can't do the agent's job for it.

## Question 1: does a bigger model decide better?

This is the question that gates real money. If a larger C-suite model makes materially better
decisions, you rent GPUs. If it doesn't, you don't. So you want to answer it *before* the hardware
PO, on cheap hosted inference.

Aftershock's society runs six role agents — a commander plus medical, rescue, fire, infrastructure,
comms. The default roster is mostly cheap `qwen3.5-flash` workers. I held everything byte-fixed — the
seeded world, the auction, the doctrine — and swapped **all six roles** across three price tiers via
a single flag (`bench --role-model`), ten paired seeds, sixty ticks each:

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>Whole-roster model-tier sweep (society arm, 10 paired seeds)</div>
  <table class="rt">
    <thead><tr><th>Tier (all six roles)</th><th>Lives saved</th><th>Conformance</th><th>Cost / run</th><th>Lives per $</th></tr></thead>
    <tbody>
      <tr class="win"><td><strong>qwen3.5-flash</strong> (0.10 / 0.40)</td><td>106.0 ±16.9</td><td>0.872</td><td>$0.0248</td><td><strong>4272</strong></td></tr>
      <tr><td>qwen3.5-plus (0.40 / 2.40)</td><td>107.5 ±17.0</td><td>0.890</td><td>$0.0892</td><td>1205</td></tr>
      <tr class="lose"><td>qwen3-max (1.20 / 6.00)</td><td>107.0 ±16.6</td><td>0.879</td><td>$0.2404</td><td><strong>445</strong></td></tr>
    </tbody>
  </table>
</div>

**Lives are flat.** Every pairwise paired delta is statistical noise: plus over flash is +1.5 (sign
test p=0.754), max over flash is +1.0 (p=1.000), max over plus is −0.5 (p=0.453) — all dwarfed by a
per-seed standard deviation of ~17. Conformance barely moves (0.872 → 0.890 → 0.879). Meanwhile cost
rises **9.7×** and lives-per-dollar **collapses 9.6×**.

The tell is in the per-seed rows. On seed 11 the three tiers saved 140 / 136 / 136 lives; on seed
127, 83 / 82 / 82; on seed 73, 126 / 131 / 130. The model you pick barely shifts the outcome — the
**world you draw** sets it. (That matches what we measured back in Log 004: the world accounts for
~79% of the variance between runs. The model tier is rounding error against it.)

This isn't "models don't matter." An earlier self-hosted size sweep (recorded in
`docs/FIELD-NOTES.md` §22) had a *too-small* model — 1.7B — collapse to zero lives saved: there's a
**capability floor**, and below it model size is everything. The finding is
that **once your roster clears that floor, paying more buys nothing the outcome can see.** And the
cheap lever we already shipped — *written doctrine*, which lifts protocol conformance by a credible
+0.125 (p=0.031) at **zero** extra cost — moves exactly what a 10× model spend couldn't. The verdict
is a clean **KILL**: no GPU capex is justified for this task; spend the budget on the harness, not the
model.

## Question 2: when does coordination actually matter?

The running theme of this whole log is *a coordinated society of small models versus an uncoordinated
swarm*, scored last week as a [price of anarchy](https://bluntmachetti.github.io/aftershock/) — the
efficiency a resource scramble leaves on the table. But I'd only ever measured it at **one** level of
scarcity. The open question is whether the coordination advantage is a constant, or whether it
*depends on the friction*. Theory has a strong prior here: with no congestion there's no externality,
so there should be nothing for a coordination mechanism to fix.

So I swept it. Same seeded world, same arms, varying only the resource abundance — a uniform pool
ladder from **12 of each unit (abundance)** down to **1 (famine)** — running the coordinated arms
(`scripted` central heuristic, `society` auction) against the uncoordinated `swarm`. Eight paired
seeds per level. Efficiency = fraction of imperiled lives saved:

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>Coordination efficiency vs resource scarcity (8 paired seeds/level)</div>
  <table class="rt">
    <thead><tr><th>Pool / unit</th><th>scripted</th><th>society</th><th>swarm</th><th>society − swarm</th><th>Price of anarchy</th><th>sign test</th></tr></thead>
    <tbody>
      <tr class="lose"><td><strong>12 — abundance</strong></td><td>73.9%</td><td>73.7%</td><td><strong>79.3%</strong></td><td><strong>−5.6 pt</strong></td><td>0.93</td><td><strong>0/8, p=0.008</strong></td></tr>
      <tr><td>6</td><td>72.4%</td><td>72.1%</td><td>72.3%</td><td>−0.1 pt</td><td>1.00</td><td>3/8, p=0.727</td></tr>
      <tr class="win"><td>4 — ≈ default</td><td>69.2%</td><td>68.0%</td><td>61.9%</td><td>+6.1 pt</td><td>1.10</td><td>6/8, p=0.289</td></tr>
      <tr class="win"><td><strong>2</strong></td><td>50.7%</td><td>47.1%</td><td>39.7%</td><td><strong>+7.3 pt</strong></td><td><strong>1.18</strong></td><td>6/8, p=0.289</td></tr>
      <tr><td>1 — famine</td><td>23.6%</td><td>20.1%</td><td>19.9%</td><td>+0.2 pt</td><td>1.01</td><td>4/8, p=1.000</td></tr>
    </tbody>
  </table>
</div>

The coordination advantage is an **inverted-U, gated entirely by friction** — and the surprising end
is the *top* of the table. **At abundance, coordinating is net-harmful.** With units lying around
unused, the auction is pure overhead: the uncoordinated swarm just grabs what it needs and saves
*more* lives (79.3% vs the society's 73.7%), winning on **all 8 seeds, p=0.008** — the single
strongest result in the whole sweep. Coordination only starts paying once contention appears: it
pulls ahead through moderate scarcity, peaking at pool=2 (+7.3 points, a 1.18× price of anarchy).
Then at the famine floor everyone collapses to ~20% and the gap vanishes — when nothing can be saved,
there's nothing to arbitrate.

The diagnostics confirm the mechanism rather than just the outcome. Contested resource losses climb
monotonically as pools tighten — 12 → 222 → 612 → 1424 — and **priority inversions stay at exactly
zero until the famine level** (then 26), which is its own small corroboration of Log 004: the auction
allocates soundly right up to the point where the problem becomes unwinnable.

## The two costumes, same body

Put the two experiments side by side and they say one thing. In Question 1, across a 10× span of
model price, **`scripted` and `society` track each other** — the hand-tuned heuristic and the LLM
society are within noise. In Question 2, across the entire scarcity ladder, they track each other
*again*: 73.9/73.7, 72.4/72.1, 69.2/68.0, 50.7/47.1, 23.6/20.1. Whether the deciders are heuristics
or a six-model society, and whether those models are cheap or expensive, barely registers.

What registers is **the coordination mechanism, and only when the world is contended enough to need
it.** The lever isn't model quality and it isn't even "LLM vs hand-tuned" — it's *structure under
scarcity*. Spend your effort there.

## What stays suggestive, and what doesn't

The honest bookkeeping, because over-claiming is the fastest way to lose a reader's trust (Log 006
taught us that the hard way).

The **abundance reversal is significant** — society loses all eight seeds, p=0.008. But the
**coordination *wins* in the middle of the curve are suggestive, not significant**: +6 to +7 points
is real-looking, but at eight seeds the sign test sits at p=0.289. That's the same caveat the raw
society-vs-swarm edge has carried for three logs now, and a uniform pool ladder doesn't dissolve it —
it would take more seeds at the pool=2 sweet spot to firm it. And Question 1's flat result is a
*null* at n=10 with σ≈17, so it rules out a large model-tier effect on lives, not a tiny one — but a
flat line across a 10× price span, with no tier ordering, is itself the finding.

Two clean, reproducible results, then, with their uncertainty stated: bigger models don't decide
better above the floor, and coordination is worth nothing — sometimes worse than nothing — until the
resources get scarce. Both point the same way, and both came from asking a sister project's question
on a substrate honest enough to answer it.

Build the ruler first, as ever. Then let it tell you where the money *isn't* worth spending.

Live demo: **<https://aftershock.redoubtlabs.dev>** · Code: **<https://github.com/bluntmachetti/aftershock>**
(method + verdicts in `docs/FIELD-NOTES.md` §26–§27; data under `bench/results/2026-06-30-*`)

---

### Related work

*Checked before publishing (Log 006's lesson). The game-theory framing under Question 2 is the same
literature Log 009 drew on; included here for the friction-necessity argument specifically.*

- Hardin, G. (1968). *The Tragedy of the Commons.* Science, 162(3859), 1243–1248. <https://doi.org/10.1126/science.162.3859.1243> — no friction, no externality; the abundance row is the boundary case where the commons problem disappears.
- Rosenthal, R. W. (1973). *A class of games possessing pure-strategy Nash equilibria.* International Journal of Game Theory, 2, 65–67. <https://doi.org/10.1007/BF01737559> — congestion games: the inefficiency is a function of the congestion.
- Koutsoupias, E. & Papadimitriou, C. (1999). *Worst-Case Equilibria.* STACS '99, LNCS 1563, 404–413. <https://doi.org/10.1007/3-540-49116-3_38> — the price-of-anarchy ratio used as the y-axis above.
- Roughgarden, T. & Tardos, É. (2002). *How Bad Is Selfish Routing?* Journal of the ACM, 49(2), 236–259. <https://doi.org/10.1145/506147.506153> — the canonical result that uncoordinated play wastes a *bounded* factor, which the famine floor echoes (the gap re-compresses).
