---
layout: post
title: "The fix that would have only fooled the scoreboard — and the one tuning that actually paid."
date: 2026-06-16 14:00:00 -0700
description: "With the measurement harness built, I finally tuned Aftershock's Qwen agent society. The ruler kept saying a new kind of no: not 'that's noise' but 'that would work and still change nothing real.' I almost shipped a fix whose only effect was to make a conformance metric look better. A field report on outcome-neutral metrics — and the one lever (a −14% cost trim) that survived the bar."
log: "005"
read: "9 min"
summary: "I used the harness to tune the society across four levers. Doctrine buys conformance at no lives cost (resolving an old n=1 scare). The infra agent's worst rule is a model-capability floor, not a prompt bug — so it shipped as an opt-in mode, not the default. And I nearly built a 'guard' whose only job was to game a metric the system already handles for free. The one unambiguous win: trimming the re-sent prompt cut cost 14% for +21% lives-per-dollar."
flags:
  - text: Outcome-neutral trap
    kind: crit
  - text: −14% cost
    kind: ok
  - text: Capability floor
    kind: warn
  - text: Conformance
---

In the [last post](/aftershock/2026/06/15/build-the-ruler-first.html) I built a *ruler* for
[**Aftershock**](https://github.com/bluntmachetti/aftershock) — paired ablations, a sign test, a
power curve — before tuning the Qwen agent society at all. This post is what happened when I finally
used it: a session of four levers, each gated by the ruler.

I expected the ruler to catch *noise* — a win that's really a coin flip. It did that. But it also kept
catching something subtler and, honestly, more embarrassing: levers that would **work** — move the
exact number I aimed them at — and **change nothing that matters.** I came within one code edit of
shipping a "fix" whose entire effect would have been to make a metric look better while the system
behaved identically.

This is a post about *outcome-neutral* metrics, and the discipline of asking, before you optimize a
number, whether the number does anything.

## The setup: the society's real story is cost and discipline, not lives

A quick recap of where the measurement left me. On Aftershock's task, **well-tuned scripted bots
match every LLM arm on lives saved** — the negotiation *protocol*, not model IQ, carries the result.
And under genuine triage there's [no detectable lives edge](/aftershock/2026/06/15/build-the-ruler-first.html)
of the society over an uncoordinated swarm. So the society's honest, defensible value isn't *more
lives* — it's **cost-efficiency** (small models, coordinated, at a fraction of a big model's price)
and **conformance** (a deterministic measure of whether agents actually follow their doctrine).

That reframing matters for everything below: it means a "win" on lives is usually noise, and a win
worth shipping is one that moves **cost** or **conformance** — *without quietly costing the other.*

## Lever 1 — does discipline cost lives? (an old scare, resolved)

Early on I'd given every agent a two-tier playbook — a "doctrine" — and a checker that scores how
well they follow it. Writing the doctrine clearly *raised* conformance. But a single-seed run had a
worrying side effect: the doctrine run saved **fewer** lives (96 vs 113). Discipline isn't free —
every instruction you add to a prompt is more to read and obey. I'd left it flagged as *outcomes
TBD.*

n=1 is not a result, so I built a same-arm ablation: run the society **with and without** doctrine on
the same five seeds, and — because conformance is the deterministic, low-variance signal — make the
report **lead with conformance** and treat lives as the noisy secondary.

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>Doctrine on vs off — paired, 5 seeds</div>
  <table class="rt">
    <thead>
      <tr><th>Signal</th><th>Off</th><th>On</th><th>Δ</th></tr>
    </thead>
    <tbody>
      <tr class="win"><td>team conformance</td><td>0.696</td><td>0.852</td><td><strong>+0.156</strong> &nbsp;(all 5 seeds)</td></tr>
      <tr><td>lives saved</td><td>100.4</td><td>104.2</td><td>+3.8 &nbsp;(within noise)</td></tr>
    </tbody>
  </table>
</div>

The scare was a small-sample artifact. Doctrine raises conformance on **every** seed, and lives are
flat-to-slightly-*up* — the n=1 "−17 lives" was noise. Discipline here is not paid for in lives. That
clears doctrine as a real, free conformance lever and tells me where the rest of the session should
aim: at the one role that still won't follow it.

## Lever 2 — the agent that won't follow the rules, and the guard I almost built to cheat

That role is the infrastructure agent. Even with doctrine, it's the one specialist that stays below
0.70 conformance. The diagnostic showed *why* — three distinct failures, not one:

- **Urgency inflation:** it marks every request urgency 9, even low-severity ones with a distant
  deadline.
- **Resubmitting rejected work:** it re-issues a decision the engine just rejected.
- **Impossible repairs:** it calls `repair_road` on districts that aren't blocked, or when there's no
  repair crew free.

First I did the obvious thing: rewrote its prompt to tie each rule to the exact fields it already sees
in its observation. That **cleanly fixed urgency** (0.35 → 1.00 conformance on that rule) — a numeric
threshold the model can apply. But the *impossible-repairs* rule barely moved. Telling the flash model
"only repair a district on the BLOCKED line, and only if crew ≥ 1" just… didn't take. Precondition
*gating* is harder to prompt than scalar *calibration.*

So I reached for the backlog idea: a **deterministic guard** — enforce the precondition in code so an
invalid repair can never happen. And then, tracing the code to place it, I stopped.

**The engine already rejects those repairs.** An invalid `repair_road` is validated and declined
*before* it consumes anything — zero resources, no effect on the world. And the conformance metric
counts the agent's *attempt*. So a guard that intercepted the attempt would do exactly one thing:
make the conformance number go up by **hiding the agent's behavior from the record.** The world would
play out identically — same lives, same cost — and the scoreboard would look better.

That is the cleanest example I've hit of an **outcome-neutral metric**: a number you can move without
changing anything real. Building the guard would have been *reward-hacking my own benchmark.* I didn't
build it. The honest version of the question isn't "how do I make the number go up" — it's "is the
behavior actually fixable, and does fixing it matter?"

So I tested that instead: I gave just the infra agent a **stronger model** (`qwen3.5-plus` instead of
`flash`) and measured, changing nothing else.

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>Infra agent: flash vs plus (model isolated, 5 seeds)</div>
  <table class="rt">
    <thead>
      <tr><th>Signal</th><th>flash</th><th>plus</th><th>Δ</th></tr>
    </thead>
    <tbody>
      <tr class="win"><td>impossible-repair rule</td><td>0.560</td><td>0.957</td><td><strong>+0.40</strong></td></tr>
      <tr class="win"><td>infra conformance</td><td>0.863</td><td>0.986</td><td>+0.123 &nbsp;(all 5 seeds)</td></tr>
      <tr><td>lives saved</td><td>103.6</td><td>103.8</td><td>flat &nbsp;(p = 1.0)</td></tr>
      <tr class="lose"><td>cost / run</td><td>$0.041</td><td>$0.054</td><td><strong>+33%</strong></td></tr>
    </tbody>
  </table>
</div>

So the stickiness was a **model-capability floor**, not a prompt bug: the bigger model gates the
preconditions the smaller one ignores. A real finding — but look at the trade. It buys near-perfect
conformance on an *outcome-neutral* rule (the bad repairs cost no lives to begin with) for **+33%
cost.** Paying a third more to perfect a metric that doesn't move lives, on an arm whose whole pitch
is cost-efficiency, is the wrong default.

So it ships as an **opt-in operating mode** — one flag, `--role-model infrastructure=qwen3.5-plus` —
not the published default. Flip it when discipline matters more than dollars; leave it off for the
lives-per-dollar story. The *finding* (it's a capability floor) is the durable result, independent of
which default you choose.

## Lever 3 — the one that actually paid: stop re-sending the prompt

With lives ruled out and conformance either free (doctrine) or expensive (infra model), I turned to
the axis the society can actually win on: **cost.** And here the harness did its best work as a
*profiler* before it did anything as a judge.

Where does the money go? The commander sends **31,900 prompt tokens per run but only 2,300 of
completion.** Decomposing one call: a **941-token system prompt re-sent on every single tick**, plus
only ~160 tokens of actual world observation. Across all six agents, **~85% of a run's prompt tokens
are the same static prefixes, re-sent every tick** — roughly **60% of total cost** is the model
re-reading instructions it already read last tick.

The obvious fix is *caching* — most providers bill a repeated prefix at a discount. So I probed it: a
~1,600-token stable prefix, sent three times in a row, on both Qwen models. The response told me
plainly:

> `prompt_tokens_details: { text_tokens: 1589 }` — **no `cached_tokens` field, no discount, full price
> every call.**

DashScope's international compatible-mode endpoint doesn't cache our prompts. That's a *clean negative
result* worth knowing: it means our cost ledger is **accurate, not pessimistic** — there's no free
accounting win hiding in cache hits. The only way to cut a re-sent prompt is to **make it shorter.**

Doctrine is off-limits (it's the conformance lever from Lever 1) and the role instructions are
behavioral, so the target was the **output contract** — the JSON-format boilerplate every agent
carries. I compacted the multi-line schema to one line, deduplicated rules that were stated twice, and
tightened the proposal descriptions — keeping every capability and field name, just terser. Commander
prefix: **941 → 835 tokens.** Then the paired A/B, against an identical baseline where *only the
contract differs:*

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>Trimmed contract vs full — paired, 5 seeds</div>
  <table class="rt">
    <thead>
      <tr><th>Signal</th><th>full</th><th>trimmed</th><th>Δ</th></tr>
    </thead>
    <tbody>
      <tr class="win"><td>cost / run</td><td>$0.0411</td><td>$0.0353</td><td><strong>−14.0%</strong></td></tr>
      <tr class="win"><td>lives per dollar</td><td>2,522</td><td>3,046</td><td><strong>+21%</strong></td></tr>
      <tr><td>lives saved</td><td>103.6</td><td>107.6</td><td>+4.0 &nbsp;(up, not significant)</td></tr>
      <tr><td>conformance</td><td>0.916</td><td>0.879</td><td>−0.037 &nbsp;(p = 0.375, n.s.)</td></tr>
    </tbody>
  </table>
</div>

A real, largely *deterministic* **14% cost cut** — the token reduction is fixed; only the small
completion varies — for a **21% gain in lives-per-dollar**, the headline efficiency number. Lives even
drifted up. The one thing to respect: conformance ticked down 0.037, but the sign test says that's not
a credible effect (p=0.375), and it sits inside the run-to-run band conformance has always wandered in
(0.85–0.92). By the same bar I used to *reject* the +16-life ghost last post, I can't *claim* this
conformance dip either — so I kept the trim and logged the dip as a watch-item, not a regression.

The deeper lesson hid in the disappointment: the pure-redundancy trim was tiny (~16 tokens). Most of
that 941-token prefix is **irreducible** — doctrine the agents need, decision vocabulary they act on,
a schema that keeps the JSON valid. The society's ~$0.04/run is *mostly structural.* −14% is close to
the safe ceiling without touching doctrine or model tier. Worth banking; not a bottomless well.

## The pattern: four levers, one bar

Before chasing each lever I made a workflow of read-only agents scope it against one question — *does
moving this metric change a real outcome?* It skipped four backlog ideas outright (a deadline-sort for
a failure mode that's already near zero; reducing "redundant" bids the auction ignores for free; a
temperature sweep premised on a cost number that turned out wrong). Each was an outcome-neutral
mirage, the I1-guard pattern again: a number you can move that moves nothing else.

What *survived* the bar is exactly the society's honest story:

1. **Doctrine** raises conformance on every seed, free of lives cost.
2. **Conformance has a price ceiling** — the last stubborn role needs a bigger model, which costs
   more than the (outcome-neutral) metric is worth as a default, so it's a switch.
3. **Cost is real and movable** — −14% by not re-sending what the model already read, the cap set by
   how much of the prompt is genuinely load-bearing.

No grand lives breakthrough. But three claims I can defend in front of a judge, and a fistful of
features I *didn't* ship because the measurement said they'd only flatter the scoreboard.

## The takeaway

Last post's lesson was *a single measurement is a coin flip wearing a lab coat* — pair it, test it,
know when to stop. This session added the sharper one:

**Before you optimize a metric, prove the metric does something.** The most seductive failure isn't a
noisy win — it's a *clean* win on a number that's decoupled from reality. I could have made my
conformance score jump by intercepting decisions the engine already discards; it would have demoed
beautifully and meant nothing. The guard against that isn't more statistics. It's tracing the metric
back to an outcome — lives, dollars, missions — and refusing to celebrate a move that doesn't reach
one.

Make it measurable. Believe only what survives the measurement. And check that the thing you're
measuring is connected to the thing you actually care about.

**Try it live:** <https://aftershock.redoubtlabs.dev> · **Read the code:** <https://github.com/bluntmachetti/aftershock>
(the levers are in
[`docs/FIELD-NOTES.md`](https://github.com/bluntmachetti/aftershock/blob/main/docs/FIELD-NOTES.md)
§18–21; the cost trim is `--role-model` / the output contract)

*Built with Qwen Cloud (`qwen3.5-flash` / `qwen3.5-plus` / `qwen3-max` via DashScope) and Alibaba
Cloud ECS, for the Qwen Cloud Global AI Hackathon.*
