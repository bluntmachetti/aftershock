---
layout: post
title: "We firmed our headline until it broke. Here's the one that didn't."
date: 2026-06-25 09:00:00 -0700
description: "Last log, our flagship claim — a coordinated Qwen society saves '+28 more lives' than an uncoordinated swarm — firmed from five seeds to fifteen and collapsed to a suggestive +8.9 (sign-test p=0.118). Honest, but soft: a judge who knows statistics will discount it. So which claim do you put on the front page when your proudest number is only suggestive? The rule we settled on — lead with what survives scrutiny — and the two results of ours that do: doctrine conformance credible at p=0.031, and ~65% better lives-per-dollar than one big model. Plus the demo fix that finally made the observatory show that evidence on first contact."
log: "008"
read: "7 min"
summary: "Our marquee number didn't survive being firmed (Log 007: +28 → a suggestive +8.9, p=0.118). That forced an honest question: if your flashiest result is only suggestive, what do you headline instead? Answer — the claims a skeptic can't knock down. Written doctrine lifts protocol conformance credibly (+0.125, n=6, p=0.031, positive on all 11 seeds, zero lives cost; 95% on the NYC-Ida demo run), and six cheap Qwen models out-deliver one big model at ~65% better lives-per-dollar while matching hand-tuned expert heuristics on lives. The +8.9 lives edge stays in the story, labeled suggestive — not buried, not inflated. And the observatory, which had been greeting judges with 'No runs found,' now loads that evidence on landing."
flags:
  - text: "Lead with what survives"
    kind: ok
  - text: "Conformance credible · p=0.031"
    kind: ok
  - text: "+8.9 lives stays 'suggestive'"
    kind: warn
  - text: "Observatory shows the evidence now"
    kind: ok
---

Three logs back I put a caveat on our own flagship number, and [last log I firmed it and watched
it collapse](/aftershock/2026/06/22/the-protocol-was-worth-28-lives-now-its-worth-a-caveat.html).
The claim that had been on Aftershock's front page since Log 001 — that a *coordinated* society of
small Qwen models saves **+28 more lives** than the same five models with no protocol — was an n=5
mean leaning on one lucky seed. Re-run from five paired seeds to fifteen, it came out **+8.9 lives**:
directionally right (the society won 11 of 15 seeds; the bootstrap 95% CI **[+2.3, +15.4]** excludes
zero) but a two-sided sign-test **p = 0.118** that doesn't clear significance.

Honest. Also soft. A judge who knows statistics will read "+8.9, p = 0.118" and — correctly —
discount it. Which forced the question I'd been able to dodge while the lives number still looked
big: **if your proudest result is only suggestive, what do you actually put on the front page?**

The rule we landed on is the one that's run through this whole project: **lead with what survives
scrutiny.** Not the flashiest number — the one that's still true after a skeptic checks it. Two of
ours are. So I rewrote the README, the evidence pack, the submission, and the blog's own headline
around them.

## What survives, #1 — written doctrine lifts conformance, *credibly*

Aftershock scores every agent against a two-tier playbook (a role envelope + a decision registry):
how often does each role actually follow the protocol it's given? That rate is `team_alignment`.
The causal test is a paired ablation — same world seeds, same tools, the doctrine layer toggled
**off vs on** — and it's the cleanest result in the project:

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>Doctrine off → on (paired ablation, conformance)</div>
  <table class="rt">
    <thead>
      <tr><th>Batch</th><th>team_alignment Δ</th><th>Seeds positive</th><th>Sign test</th><th>Verdict</th></tr>
    </thead>
    <tbody>
      <tr class="lose"><td>2026-06-16 · n = 5</td><td><strong>+0.156</strong></td><td>5 / 5</td><td>p = 0.0625</td><td>suggestive</td></tr>
      <tr class="win"><td><strong>2026-06-22 · n = 6 (re-test)</strong></td><td><strong>+0.125</strong></td><td>6 / 6</td><td><strong>p = 0.03125</strong></td><td><strong>credible</strong></td></tr>
    </tbody>
  </table>
</div>

The effect is positive on **all 11 seeds across both runs**, and at n=6 it finally clears the
sign-test floor (five-for-five is only p=0.0625 — as strong as five coin flips get; the sixth seed
tips it to p=0.03125). Crucially, doctrine buys this alignment at **no lives cost** — the lives
delta in the same ablation is noise (p=0.375) in both runs. The structure makes the agents *follow
the protocol*, not save more people; we don't conflate the two.

And on the run a judge actually lands on — `seed91-society`, 65 ticks on **real NYC Hurricane Ida**
dispatch demand — the society follows its doctrine **95.2%** of the time (`team_alignment = 0.9517`).
That's the number I'd defend in a room full of Qwen engineers: structured instruction-following,
measured deterministically, reproducible from the committed conformance file.

> **Conformance ≠ outcome.** 95% alignment means the agents obeyed the protocol — it does *not* mean
> they rescued everyone. Outcomes (lives saved/lost) are a fully simulated model; we never claim the
> agents beat real outcomes. The conformance number proves instruction-following, full stop.

## What survives, #2 — the cost-efficiency is real

The other claim a skeptic can't knock down is about money. On the 4-arm benchmark (paired seeds, 60
ticks), six cheap `qwen3.5-flash` workers plus one `qwen3.5-plus` commander:

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>4-arm benchmark — lives, cost, and lives-per-dollar</div>
  <table class="rt">
    <thead>
      <tr><th>Arm</th><th>Mean lives</th><th>Cost / run</th><th>Lives per $</th></tr>
    </thead>
    <tbody>
      <tr><td>scripted (expert heuristics, $0)</td><td>106.8</td><td>$0.0000</td><td>— (free control)</td></tr>
      <tr class="win"><td><strong>society</strong> (6-role, negotiation)</td><td><strong>108.4</strong></td><td><strong>$0.0353</strong></td><td><strong>3,069</strong></td></tr>
      <tr class="lose"><td>solo (one big model)</td><td>95.6</td><td>$0.0515</td><td>1,855</td></tr>
    </tbody>
  </table>
</div>

The society **matches hand-tuned expert heuristics on lives** (108.4 vs 106.8 — a coordinated team
of small models holding its own against domain expertise) and **out-delivers the single big model**
(108.4 vs 95.6) at **31% lower cost** — which is **~65% better lives-per-dollar** (3,069 vs 1,855).
That's the Qwen-track thesis stated in a way that doesn't depend on a fragile p-value: cheap models,
coordinated by a protocol, beat one expensive model for less money. (A later contract trim — Log 005
— cut another ~14% off the society's per-run cost without touching conformance, on top of this.)

## What we're *not* leading with anymore

The +8.9-lives society-vs-swarm edge doesn't get deleted — that would be its own kind of dishonesty.
It's directionally consistent (society wins 11/15), its CI excludes zero, and it's the honest residue
of the number we used to headline. It stays in the evidence pack, **labeled suggestive**:

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>Society vs swarm — kept, but demoted to suggestive</div>
  <table class="rt">
    <thead>
      <tr><th>Stat</th><th>Value</th></tr>
    </thead>
    <tbody>
      <tr><td>Mean Δ lives (society − swarm), n = 15</td><td><strong>+8.9</strong></td></tr>
      <tr><td>Seeds society won</td><td>11 / 15</td></tr>
      <tr><td>Bootstrap 95% CI</td><td>[+2.3, +15.4] (excludes 0)</td></tr>
      <tr class="lose"><td>Sign-test p</td><td>0.118 — <strong>suggestive, not significant</strong></td></tr>
    </tbody>
  </table>
</div>

By the harness's own three-tier rule (credible = CI-excludes-0 **and** sign-significant; suggestive =
exactly one; noise = neither), exactly one condition holds — so it's suggestive, and that's what we
write. The point of the rule is that it demotes *us*, not just other people's claims.

## The evidence is finally visible on landing

There's a postscript that belongs in a build log. While reframing the writing, I checked what a judge
actually sees at <https://aftershock.redoubtlabs.dev> — and it was greeting visitors with **"No runs
found"** everywhere and a Bench tab stuck on "Loading…" forever. All that carefully-firmed evidence
was invisible on first contact.

The cause was almost funny: the public demo runs a back-to-back ambient simulation to keep the Live
tab alive, and over thirteen days it had quietly written **32,709 throwaway run directories**. The
run-list endpoint read *every* one on *every* request; at 32k it took **62 seconds** to answer and
blocked the bench endpoint behind it. The fix was three parts — prune the firehose and cap it so it
self-heals, list every curated run but only the newest handful of ambient ones, and **bundle the
demo arc into the repo itself** so a fresh clone or a fresh box shows real data immediately instead of
an empty panel. `/api/runs` went from 62s to under a second; the observatory now loads `seed91-society`
— that 95%-conformance NYC-Ida run — on landing, no clicks.

It's the same lesson as Log 006, wearing yet another hat: *a system that intends to show its evidence
isn't showing it until you look at what a stranger actually sees.* The blog could describe our
credibility all it wanted; the app needed to put it on screen.

## The honest headline

"Society achieves 0.95 doctrine conformance — credible at p=0.031 — at ~65% better lives-per-dollar
than one big model" is less of a flex than "+28 lives saved." It's also the version that's still true
after you check it. Every figure here traces to a file in the repo
([docs/EVIDENCE.md](https://github.com/bluntmachetti/aftershock/blob/main/docs/EVIDENCE.md)), and the
field log keeps the receipts — including the ghost we chased and the headline we had to walk back. If
there's one thing this project is for, it's that: pick the claim that survives scrutiny, and let the
ruler demote you when it should.

Live demo: **<https://aftershock.redoubtlabs.dev>** · Code: **<https://github.com/bluntmachetti/aftershock>**
