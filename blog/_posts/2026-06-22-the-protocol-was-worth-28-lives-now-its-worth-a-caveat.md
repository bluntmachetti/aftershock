---
layout: post
title: "The protocol was 'worth 28 lives.' At fifteen seeds it's worth a caveat."
date: 2026-06-22 12:00:00 -0700
description: "Three logs ago I caveated Aftershock's flagship claim — that a coordinated Qwen agent society saves ~28 more lives than an uncoordinated swarm — as an n=5 mean leaning on one lucky seed, and promised to firm it. My Alibaba Cloud credits arrived; before spending them on new experiments I built a thin experiment tracker and used it to keep that promise. Firming the +28 to fifteen paired seeds collapsed it to a suggestive +8.9 lives — the CI excludes 0 but the sign test doesn't clear significance. A field report on building the audit trail before you generate the data, watching the tool catch a flaw in itself, and publishing the honest number when your headline doesn't survive."
log: "007"
read: "8 min"
summary: "I had hackathon credits and a backlog of experiments. Instead of burning them, I built a thin experiment tracker — a provenance stamp on every result plus one queryable index — and on its first real use it labeled a credible conformance result as 'noise' because it was reading the wrong metric, so I fixed it. Then it firmed a real win (doctrine conformance, now credible at p=0.031) and demoted our marquee one: the '+28 lives' society-vs-swarm headline, firmed from five paired seeds to fifteen, collapsed to a suggestive +8.9 lives — the CI excludes 0 but the sign test doesn't clear significance — one seed had carried the original. We rewrote the README, the submission, and the evidence pack to the honest figure. The cost trim's conformance dip turned out small-but-real. Firm your proudest number first; the tracker earns its keep by demoting you."
flags:
  - text: "+28 → +8.9 (n=15)"
    kind: crit
  - text: Doctrine now credible
    kind: ok
  - text: Tracker caught itself
    kind: warn
  - text: Firm your headline
---

Three logs ago I [put a caveat on our own flagship number](/aftershock/2026/06/15/build-the-ruler-first.html)
and made a promise. The claim that's been on [**Aftershock**](https://github.com/bluntmachetti/aftershock)'s
front page since Log 001 — that a *coordinated* society of small Qwen models saves **+28 more lives** than the
same five models with no protocol — was an n=5 paired mean leaning hard on a single lucky seed. I wrote, in
plain text: *the headline figure is an n=5 mean with a wide interval; to put a tight bound on the number you'd
want ~25 seeds.* I said I'd firm it.

My Alibaba Cloud hackathon credits landed this week. The obvious move was to spend them on new experiments. I
spent the first of them keeping that promise instead — and the number didn't survive.

## Build the audit trail before you generate the data

I had credits and a backlog. The temptation is to start running. But I'd already learned (Log 004, Log 006)
that the expensive mistakes in this project aren't bad runs — they're *believing* runs I shouldn't. So before
spending a token, I built the thing that makes belief cheap and honest: an experiment tracker.

Not a big one. A sibling project of mine has a proper one — a database, schema-pinned ledgers, a hash-chained
research log, viability certificates. I read all of it and then deliberately *didn't* port it. Aftershock is a
two-week hackathon repo with one model family; that machinery is paper-grade over-build here. What it actually
lacked was small and specific: none of the ~dozen result folders carried the commit they were run on, the
JSON had quietly drifted across versions, and there was no way to ask "which of my experiments are *credible*?"
across the whole set.

So the tracker is three thin things: a **provenance stamp** on every result file (schema version, git SHA,
which endpoint — cloud DashScope vs a local model — and a digest of the deterministic scripted baseline so a
silent regression in the control is detectable); a **one-file index** built by a read-only script that walks
every run and emits one queryable row each; and a link from a result to the field note it backs. About 350
lines, pure standard library, no new dependencies. The point of building it *first* is the same as building a
ruler before you cut: you want the measurement in place before the thing you're measuring exists.

## The tool's first job was catching itself

The first real experiment I pointed it at was a cheap, important one. An earlier finding (Log 002 territory)
showed that *written doctrine* — a two-tier playbook the agents are scored against — raises how often the
society follows its own protocol. At five seeds that effect was real on every seed but sat just shy of
significance (a sign-test floor of p=0.0625, because five-for-five is as strong as five coin flips get). One
more seed would tip it. So I ran a sixth.

The conformance lifted, six-for-six positive, sign test now p=0.031 — **credible**. I went to read it back out
of the new index, and the index said the experiment's verdict was: **noise.**

It wasn't wrong about a number. It was reading the *wrong* number. The tracker computed its one headline
verdict from the *lives* delta — which for a doctrine change is pure noise, by design, because doctrine buys
*conformance*, not lives. The credible result was sitting right there in the data and the tool I'd built to
keep me honest was filing it under "nothing to see." The honesty layer was mislabeling on day one.

That's the recurring lesson of this whole project wearing a new hat: a dashboard that intends to be honest
isn't honest until you audit what it actually surfaces. I taught the tracker to compute a **separate
conformance verdict** with the same statistics, and *then* the doctrine result read credible. The fix paid
off twice in one afternoon — because the very next experiment was the one I'd been avoiding.

## The headline, firmed: +28 → a question mark

The promise from Log 004 was ~25 seeds. I went and got them. The society-vs-swarm contrast, re-run on the
*current* code, across three batches, pooled into one paired test:

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>Society vs swarm — the "+28" firmed from five seeds to fifteen</div>
  <table class="rt">
    <thead>
      <tr><th>Batch</th><th>Δ lives</th><th>Society wins</th><th>Sign test / CI</th></tr>
    </thead>
    <tbody>
      <tr class="lose"><td>2026-06-11 · n = 5 (the published number)</td><td><strong>+27.6</strong></td><td>4 / 5</td><td>p = 0.125</td></tr>
      <tr class="lose"><td>2026-06-22 · same 5 seeds, current code</td><td><strong>+14.6</strong></td><td>4 / 5</td><td>—</td></tr>
      <tr class="lose"><td>2026-06-22 · 10 fresh seeds</td><td><strong>+6.0</strong></td><td>7 / 10</td><td>—</td></tr>
      <tr class="win"><td><strong>pooled · n = 15</strong></td><td><strong>+8.9</strong></td><td>11 / 15</td><td>p = 0.118 · CI [+2.3, +15.4] <em>excludes 0</em></td></tr>
    </tbody>
  </table>
</div>

Read top to bottom, that's a number deflating in real time. The same five seeds that gave +27.6 in June gave
+14.6 on today's code. Ten brand-new seeds came back at +6.0. Pool all fifteen and you get **+8.9 lives, with
a confidence interval [+2.3, +15.4] that just clears zero but a sign test (p=0.118) that doesn't clear
significance.** The tracker calls that *suggestive* — exactly one of its two bars met, not both.

The culprit is the one Log 004 already named: a single seed. In the original five, seed 11 was a +88-life
blowout that dragged the mean up; the other four averaged about +12. Once the sample is big enough that no one
lucky draw can carry it, the magnitude regresses to a small, not-significant edge. The *direction* still holds
— the society wins 11 of 15 seeds, it does beat the uncoordinated swarm more often than not — but the **number**
on the homepage does not survive being firmed.

So I did the unglamorous thing. I rewrote the README, the submission writeup, and the judge-facing evidence
pack to lead with what's true: society-vs-swarm is *suggestive, not statistically significant (+8.9 at n=15,
CI [+2.3, +15.4] excludes 0 but the sign test p=0.118 doesn't clear significance)*, and the earlier +28 was a
small-sample overestimate. The blog posts that reported +28 at the
time stay exactly as they were — they were honest about what we knew *then*, and rewriting history would be
its own dishonesty. This is the next chapter, not a retcon.

## And the cost trim, kept honest

While the tracker was on, I closed one more open question. A while back I trimmed the static prompt every agent
re-sends each tick and cut run cost ~14% in a clean A/B ($0.0411→$0.0353, Log 005) — about ~16% cumulatively
since the 2026-06-11 launch ($0.0423→$0.0353), a different baseline. I'd flagged a small conformance dip from
that trim as a
"watch-item — could be noise." Now that conformance is the part of the story that *survived*, I owed it a real
answer, so I built a clean A/B toggle and ran it at ten seeds.

The dip is **real but tiny: −0.019 team-alignment**, with a confidence interval that just clears zero but a
sign test that doesn't (the tracker calls it *suggestive*) — and **zero** lives cost. So the −14% cost cut is
*nearly* free, not perfectly free. Worth knowing, not worth reversing. The point is that I now know which it
is, instead of guessing.

## What survives

Here's the honest scoreboard after a session spent measuring instead of adding:

- **Cost-efficiency — robust.** Six `qwen3.5-flash` workers under a `qwen3.5-plus` commander match well-tuned
  expert heuristics (108 vs 107 lives) and a single big model (108 vs 96 for solo `qwen3-max`) at **~$0.035 a
  run** — over 50% better lives-per-dollar than the big model. That's the claim I'd stake the submission on.
- **Conformance — now credible.** Written doctrine lifts protocol-following by a verdict that finally clears
  significance (p=0.031, six-for-six).
- **Society vs swarm on lives — a question mark.** Suggestive (11/15, CI [+2.3, +15.4] excludes 0) but not
  significant (sign test p=0.118). The marquee magnitude was the weakest claim, and it's the one that didn't
  hold.

Losing your headline number is supposed to feel bad. It mostly feels like relief, because the alternative was a
judge running `aftershock bench` and finding +9 where the slide said +28. The tracker earned its entire
existence in one session by demoting me, on purpose, before anyone else could.

If there's a takeaway sharper than Log 004's "build the ruler first," it's this: **firm your *proudest* number
first.** The figure you most want to be true is the one most likely to be a small-sample flatter, and it's the
one with the most riding on being wrong. Point the audit trail at it on day one. The best day a measurement
tool has is the day it tells you the thing you were about to brag about isn't there.

**Try it live:** <https://aftershock.redoubtlabs.dev> · **Read the code:** <https://github.com/bluntmachetti/aftershock>
(the firming lives in `aftershock ablation`; every number above traces to a file in the
[judge evidence pack](https://github.com/bluntmachetti/aftershock/blob/main/docs/EVIDENCE.md))

*Built with Qwen Cloud (`qwen3.5-flash` / `qwen3.5-plus` / `qwen3-max` via DashScope) and Alibaba Cloud ECS,
for the Qwen Cloud Global AI Hackathon.*
