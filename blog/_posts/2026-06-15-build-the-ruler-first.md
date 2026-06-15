---
layout: post
title: "Build the ruler first. It killed our biggest feature — and a +16-life win that wasn't real."
date: 2026-06-15 15:00:00 -0700
description: "Before tuning Aftershock's Qwen agent society, I built the measurement: paired ablations, a power curve, and free diagnostics over the run records. Then the measurement did its job — it killed the backlog's biggest planned feature before I wrote a line of it, caught a +16-life 'win' that evaporated when I added seeds, and made me caveat my own headline number. A field report on not fooling yourself."
log: "004"
read: "8 min"
summary: "I built the measurement harness before tuning the agents. It killed the backlog's biggest planned lever (a pathology that doesn't occur), caught a +16-life society-vs-swarm 'win' that collapsed to noise at 11 seeds, and forced an honest caveat on our own +28 headline. Three 'don'ts' worth more than a feature."
flags:
  - text: Measure first
    kind: ok
  - text: Negative result
    kind: crit
  - text: False positive caught
    kind: warn
  - text: Statistics
---

My backlog for [**Aftershock**](https://github.com/bluntmachetti/aftershock) had a clear headliner.
Of ~44 ideas for making the Qwen agent society save more lives, one was marked *the single biggest
lever*: a smarter resource auction (partial grants instead of all-or-nothing), hypothesized at
**+10–15 lives a run**. The obvious move was to build it.

I didn't build it. I built a *ruler* first — the boring statistical plumbing that tells you whether
a change actually did anything. And the ruler earned its keep three times over in one sitting: it
**killed the headliner** before I wrote a line of it, it **caught a +16-life win that wasn't real**,
and it made me **put a caveat on my own flagship number**.

This is a post about the least glamorous part of the project — measurement — and why it turned out
to be the most valuable.

## Why a ruler, before any tuning

Aftershock's engine is byte-deterministic: same seed, same disaster, same outcome. But the *agents*
are not. The published society result — `103.2 ± 23.6` lives — has a `±` for a reason, and the first
thing the ruler did was tell me exactly what that `±` is made of.

Two cheap experiments:

- **Does Qwen Cloud honor a sampling `seed`?** I threaded a deterministic per-call seed through every
  request and ran the same world twice. The two runs diverged on the first tick, exactly like two
  un-seeded runs. **DashScope accepts `seed` but doesn't make sampling reproducible** — so the LLM
  arms are irreducibly stochastic, and that `±` really is sampling noise, not measurement slop.
- **How much of the noise is the *model*, and how much is the *world*?** Running each seed three
  times and decomposing the variance: **79% of it is which disaster you drew** (between-seed), only
  **21% is the model's run-to-run wobble** (within-seed).

That second number is the whole game. If most of your variance is the scenario, then comparing a
*mean* against a *mean* is mostly comparing coin flips — unless you **pair**: run the control and the
treatment on the *same* seeds and difference out the world. Concretely, to detect a +10-life effect
at decent power you need **~10 paired seeds, versus ~45 unpaired**. Same data, a quarter of the runs,
because pairing deletes the 79%.

So the ruler is: run both arms on identical seeds, take the per-seed difference, and judge it with a
sign test, a bootstrap confidence interval, and a power curve — `aftershock ablation`. Nothing fancy.
Just enough to stop me believing a number I shouldn't.

## Episode 1 — the diagnostic killed the headliner

The "biggest lever" exists to fix a specific pathology: a **priority inversion**. Under all-or-nothing
granting, a high-priority incident that needs three ambulances can lose the whole pool to a
later, lower-priority incident that happens to fit the two that are left. Partial grants would fix
that. Worth +10–15 lives — *if it happens.*

So before building the fix, I built a diagnostic that reads the recorded auction outcomes and counts
how often it actually happens. The answer, across nine society runs:

**Zero.**

Then I made the world harder — I added a knob to tighten the resource pools — figuring scarcity would
surely manufacture the contention. Still zero. I cranked it to the harshest setting the sim allows
(every pool at 2, where a *fifth* of all incidents fail outright):

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>Priority inversions found — the pathology the "biggest lever" fixes</div>
  <table class="rt">
    <thead>
      <tr><th>World</th><th>Society runs</th><th>Priority inversions</th></tr>
    </thead>
    <tbody>
      <tr class="win"><td>default</td><td>9</td><td><strong>0</strong> &nbsp;(of 59 contested losses)</td></tr>
      <tr class="win"><td>tight pools</td><td>6</td><td><strong>0</strong> &nbsp;(of 74 contested)</td></tr>
      <tr class="lose"><td>harshest (all pools = 2)</td><td>5</td><td><strong>6</strong> &nbsp;(of 794 losses — &lt;1%)</td></tr>
    </tbody>
  </table>
</div>

Across the default and tight worlds: **133 contested auction losses, every single one legitimate** —
the loser always had lower-or-equal priority than the winner. The auction's arbitration is just
*correct*: it serves the highest-priority incident first, and the agents don't over-request in the
way that would let a low-priority bid steal the remainder. Only at brutal scarcity do a handful of
inversions appear, and even then they're dwarfed 70-to-1 by plain shortage (the pool is simply empty
— there's nothing for a partial grant to split).

The verdict wrote itself: **don't build the lever.** It optimizes a problem this system doesn't have.
That's the harness paying for itself before it cost a thing — a feature un-built is a feature you
don't have to maintain, document, or quietly regret.

(A humbling footnote: the *first* version of that inversion detector was dead code — by the
resolver's ordering it could never actually fire — and an adversarial code review caught it. Even the
ruler needed measuring. I rebuilt it to reconstruct winners-versus-losers from the recorded grants,
and *then* trusted the zeros.)

## Episode 2 — the +16 that wasn't

Fine: the auction isn't the bottleneck on the easy task. But the easy task is *easy* — ~96% of
incidents get resolved, so there's barely any room for any change to move lives. The honest next
question: under genuine triage — a world where you *can't* save everyone and the order you serve
people in decides who lives — does the society's coordination actually beat the uncoordinated swarm
by more?

I dialed in that world (the harshest setting: lives saved ≈ lives lost) and ran a paired
society-vs-swarm ablation. Five seeds. The result looked *great*:

> **Δ = +16.2 lives**, 95% CI **[+3.2, +29.6]** — excludes zero. Society stable at 63–72 lives across
> every seed; swarm volatile (32–66), collapsing on the two hard draws (39 and 32 lives).

A clean story practically wrote itself: *coordination buys graceful degradation under stress.* The
harness's own auto-verdict even printed **"credible improvement."** I wanted to believe it.

But the same readout had two warnings I'd built in precisely so I couldn't ignore them: the **sign
test was non-significant** (p=0.375) and the **statistical power was 0.57**. The confidence interval
said yes; the more conservative tests said *not yet.* The honest move with a disagreement like that
is not to pick the answer you like — it's to add seeds. So I added six more (the harness resumes the
runs it already has, so only the new ones cost anything) and re-ran at eleven.

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>Society vs swarm, harsh world — the same effect at n=5 and n=11</div>
  <table class="rt">
    <thead>
      <tr><th>Seeds</th><th>Δ lives</th><th>95% CI</th><th>Sign test</th><th>Power</th></tr>
    </thead>
    <tbody>
      <tr class="lose"><td>n = 5</td><td><strong>+16.2</strong></td><td>[+3.2, +29.6] — excludes 0</td><td>p = 0.375</td><td>0.57</td></tr>
      <tr class="win"><td>n = 11</td><td><strong>+4.7</strong></td><td>[−4.0, +14.7] — <em>includes 0</em></td><td>p = 1.0</td><td>0.15</td></tr>
    </tbody>
  </table>
</div>

The effect **evaporated.** Four of the six new seeds came back with the *swarm beating the society*. The
entire +16 had been carried by two lucky draws where the swarm happened to faceplant; the "society is
rock-stable" story was the same small-sample mirage (at eleven seeds the society's range is 32–80,
not the tidy 63–72 I'd seen at five). There is **no detectable lives advantage** here. The power
curve says confirming even the residual +4.7 would take ~88 seeds — which is the harness's polite way
of saying *stop.*

This is the single most important thing the ruler did. A +16-life result with a confidence interval
that excludes zero is *exactly* the kind of finding you screenshot, put in a slide, and ship. It was
noise. I caught it because I'd committed in advance to a test I couldn't argue with after the fact.

## Episode 3 — turning the ruler on my own headline

If a +16 can be a ghost, what about the project's flagship claim — that the coordination protocol is
worth **+28 lives**? I owed it the same scrutiny, so I ran the *already-published* numbers through the
same paired test. The result, to my relief, held up where the +16 didn't — but not cleanly:

- **Directionally solid:** society ≥ swarm on **all five** seeds (four wins, one tie, zero losses).
  Unlike the harsh-world ghost that went both ways, this gap is real in sign. The qualitative claim —
  *the auction helps* — survives.
- **Magnitude soft:** the precise "+28" is leaned on hard by a single seed (+88 there; the other four
  average +12.5), the sign test is p=0.125, and the power is 0.42. To put a tight interval on the
  *number* you'd want ~25 seeds.

So I'm keeping the claim and adding a caveat I can defend: *the coordination protocol reliably helps;
the headline figure is an n=5 mean with a wide interval.* That's a weaker sentence than "+28 lives,"
and it's the true one.

## What the ruler cost, and what it bought

The whole measurement campaign — 41 paired runs across every world — cost **\$1.41** in Qwen Cloud
tokens, tallied from the run ledgers. For that, I got three results I'd have paid far more for in
wasted effort and overconfidence:

1. **Don't build the "biggest lever."** It fixes a pathology that occurs <1% of the time.
2. **There's no lives edge under triage.** The +16 was a false positive; the honest story for the
   society is cost-efficiency and discipline, not out-saving the swarm under scarcity.
3. **Caveat the +28.** Real in direction, soft in magnitude.

None of those are features. Two are flat "don'ts" and one is a hedge. And they're the most valuable
output of the session — because the alternative was building a feature against a problem that isn't
there, and believing a win that wasn't real, in a slide deck, in front of judges.

## The takeaway

In a stochastic system, **a single measurement is a coin flip wearing a lab coat.** The plumbing
that protects you from it — pair to kill the variance you don't care about, judge with a test you
picked *before* you saw the answer, and let a power curve tell you when to stop — isn't bureaucracy.
It's the difference between knowing and hoping. Build that ruler before you build the thing you're
itching to build, because the ruler's best days are the ones where it tells you *no.*

And hold your own dashboard to the same bar: my ablation tool's auto-verdict cheerfully called the
+16 "credible," and the sign test is the only reason I didn't believe it. The tool that keeps you
honest still needs you to read all of it.

Make it measurable. Then believe only the part that survives the measurement.

**Try it live:** <https://aftershock.redoubtlabs.dev> · **Read the code:** <https://github.com/bluntmachetti/aftershock>
(the harness is `aftershock ablation` / `aftershock diagnose`; the findings are in
[`docs/FIELD-NOTES.md`](https://github.com/bluntmachetti/aftershock/blob/main/docs/FIELD-NOTES.md) §13–17)

*Built with Qwen Cloud (`qwen3.5-flash` / `qwen3.5-plus` / `qwen3-max` via DashScope) and Alibaba
Cloud ECS, for the Qwen Cloud Global AI Hackathon.*
