---
layout: post
title: "We built a proof pack so judges could check our numbers. Auditing it ourselves found a wrong p-value, a fabricated source, and a cherry-picked run."
date: 2026-06-19 16:00:00 -0700
description: "With the deadline close, the right move for Aftershock wasn't more features — it was making the proof legible. So I built a one-page evidence pack where every number traces to a file, the judge's dream fact-check target. Then I fact-checked it. The artifact built specifically to be honest had a wrong p-value, a digest sourced from a field that doesn't exist, and a flagship run quietly cited at 95% conformance while it saved 8 of 90 lives. A field report on the difference between intending to be honest and auditing your honesty."
log: "006"
read: "8 min"
summary: "Near the deadline I stopped adding features and built the proof layer instead — a Decision Receipt for any ruling, confidence intervals and significance on the bench, and a one-page Evidence Pack that ties every headline number to a source file. Then a multi-agent adversarial pass re-derived every figure from source. 42 of 47 traced exactly; five did not — including a swarm p-value cross-contaminated from another row (0.375 vs 0.0625), a pack_digest cited as a JSON field that doesn't exist, and a 'flagship' NYC-Ida run shown at 0.95 conformance with no mention that it saved 8 of 90 lives. The honesty surfaces I built to impress judges were all overclaiming until I audited them. Intending to be honest isn't enough; you have to check your own receipts."
flags:
  - text: Wrong p-value
    kind: crit
  - text: Cherry-pick caught
    kind: crit
  - text: 42 / 47 traced
    kind: ok
  - text: Audit your honesty
    kind: warn
---

In the [last post](/aftershock/2026/06/16/the-fix-that-would-have-only-fooled-the-scoreboard.html)
the lesson was *prove the metric does something before you optimize it.* This one is the same
discipline pointed somewhere more uncomfortable: at the artifact I built **to be honest.**

With the hackathon deadline close, the temptation was to bolt on a flashy feature. The measurement
from the earlier logs said otherwise. [**Aftershock**](https://github.com/bluntmachetti/aftershock)
was already feature-complete; what it lacked wasn't capability, it was **legibility** — a judge
couldn't quickly check that the numbers were real. So the final push wasn't features. It was *proof*:
a **Decision Receipt** that chains any contested ruling (kernel decision → the agent's own stated
rationale → cost → recorded outcome), confidence intervals and a sign test on the benchmark, and the
capstone — a one-page **Evidence Pack** whose entire promise is: *every number here traces to a file
in the repo. Go check.*

It's the judge's dream fact-check target. So before I shipped it, I did the judge's job. I ran a
multi-agent adversarial pass that re-derived **every figure** in the pack from its source — the
`results.json`, the run manifests, the scenario JSON — and asked one question per number: *does this
actually trace?*

The honest headline: **42 of 47 figures matched exactly.** The mean lives (society 103.2, swarm
75.6), the costs, the lives-per-dollar, the NYC-Ida demand and latency baseline (948s, 16.5% held) —
all clean. But the five that *didn't* trace are the whole point of this post, because the document
that failed them was the one I wrote specifically so it couldn't.

## The artifact that dares you to check it

The Evidence Pack opens with a line I was proud of: *"Every number below traces to a file in this
repo — no figure is asserted without a source path."* Each claim sits next to its source: a results
file, a `run.json` field, a path inside `scenario.json`. That framing is a commitment. It also means
a single wrong source citation doesn't just look sloppy — it detonates the whole document, because a
judge who runs `jq` on the cited field and gets back `null` will stop trusting *every other number on
the page.*

So that's exactly what the audit checked: not "is the value plausible," but "if a skeptic runs the
command next to this number, do they get this number back?"

## So I checked it — and three citations lied

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>Evidence Pack — what it claimed vs what the source said</div>
  <table class="rt">
    <thead>
      <tr><th>Claim</th><th>The pack cited</th><th>The source actually says</th></tr>
    </thead>
    <tbody>
      <tr class="lose"><td>swarm vs scripted — significance</td><td>p = 0.375</td><td><strong>p = 0.0625</strong> (swarm loses 5/5; 0.375 was the <em>society</em> row, copy-pasted)</td></tr>
      <tr class="lose"><td>NYC-Ida <code>pack_digest</code></td><td>"in <code>scenario.json</code>"</td><td>not a field there — <code>jq .pack_digest</code> → <strong>null</strong> (it's a sha256 computed at load)</td></tr>
      <tr class="lose"><td>the "demand real, outcomes simulated" caveat line</td><td>emitted by the loader</td><td>a constant in <code>web.py</code>, chosen per-pack at serve time</td></tr>
      <tr><td>real incident count path</td><td><code>reference.n_incidents</code></td><td><code>reference.<strong>aggregates</strong>.n_incidents</code> (value 2,212 correct)</td></tr>
    </tbody>
  </table>
</div>

None of these *flattered* the project — the wrong p-value actually **understated** how cleanly the
swarm loses (0.0625 is the strongest verdict five seeds can give; 0.375 was a number that wandered in
from the adjacent row). The `pack_digest` value was even *correct* — it just pointed at the wrong
place to find it. But that's the trap with a proof artifact: *honest intent plus a wrong pointer reads
exactly like a lie to someone checking.* A judge running `jq .pack_digest scenario.json`, getting
`null`, and concluding the whole pack is hand-waved would be **right to.** Every one of these got a
corrected source — the digest now cites the code that computes it and the `run.json` field that
stores it; the p-value reads 0.0625.

A small, sharp aside: the AI reviewers I'd used to pressure-test the plan made the *same class* of
error. One confidently recommended I "ship the scenario pipeline" — a thing already shipped weeks
earlier (caught by checking the disk). Another quoted a flattering conformance figure of **0.915**;
the real number is **0.759** — it had been unable to read the gitignored file and filled the gap with
something plausible. Models hallucinate sources too. The defense is identical: trace it.

## The one that stung: a flagship at 95% conformance that saved 8 of 90 lives

The traceability misses were fixable typos. This one was a judgment failure, and it's the reason the
post exists.

The pack showcased `seed91-society` — the society running the real NYC Hurricane Ida scenario — as the
flagship demo, headlined by its **doctrine conformance of 0.95**: "Qwen follows the structured
doctrine 95% of the time over a full scenario." True number. Real signal. And next to it, the pack
said **nothing** about how the run actually went.

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>seed91-society — the flagship, fully stated</div>
  <table class="rt">
    <thead>
      <tr><th>Signal</th><th>Value</th></tr>
    </thead>
    <tbody>
      <tr class="win"><td>doctrine conformance</td><td>0.952 (cited)</td></tr>
      <tr class="lose"><td>lives saved / lost</td><td><strong>8 / 82</strong> (8 of ~90 — <em>not</em> cited)</td></tr>
      <tr class="lose"><td>missions failed</td><td>3 (not cited)</td></tr>
    </tbody>
  </table>
</div>

Conformance measures whether agents *follow their playbook.* It says nothing about whether they
*win.* Under Ida's real overwhelming demand, this run followed doctrine almost perfectly and still
lost 82 of 90 lives. Both facts are true and they don't conflict — but putting "95% disciplined" in
the spotlight and leaving "saved 8 of 90" off the page **implies success the run never had.** A sharp
judge who opened the `run.json` would find 8/82 and, fairly, distrust the rest.

This is the cherry-pick failure mode, and it's seductive precisely *because every individual number is
real.* You don't have to fabricate anything to mislead — you just have to be selective about which
true number gets the headline. The fix wasn't to bury the run; it was to state it whole: a caveat now
sits directly beside it — *"conformance measures instruction-following, not lives; this run scored
0.95 but saved only 8 of 90 under heavy Ida demand."* That sentence makes the pack stronger, not
weaker, because it's the sentence a skeptic was going to write for me.

## It wasn't only the pack

Once I started auditing, the pattern repeated across *every* honesty surface I'd built that week:

- The **Decision Receipt** labeled the *commander's* rulings "decided by kernel." The commander is an
  LLM arbiter, not the deterministic engine — calling its calls "kernel" decisions is exactly the kind
  of authority-laundering the receipt exists to *prevent.*
- It showed a ruling as **GRANTED** when the auction had accepted the bid but the kernel then *rejected
  the dispatch downstream* — implying a resource reached a mission it never reached.
- It printed a **town-wide** lives-saved delta inside a card scoped to a *single* ruling, so opening
  the receipt for a *declined* call could show it next to "+1 saved."

Three honesty bugs in the component whose entire job is honesty. All caught the same way: an
independent pass that didn't trust the summary and went to the source. All fixed before any of it
reached a judge.

## The takeaway

Aftershock's thesis, from Log 001, has been one sentence: *don't trust the summary — check the
receipts.* It's the argument for the whole project: typed decisions over chat transcripts, paired
seeds over a single triumphant run, provenance labels over a confident demo.

This week that argument turned around and pointed at me. I built the most honest artifact I could —
a pack that *invites* fact-checking — and it still shipped a wrong p-value, a citation to a field that
doesn't exist, and a flagship that omitted its own outcome. Not from bad faith. From the ordinary
gravity that pulls every summary toward looking better than the thing it summarizes.

The lesson is narrow and, I think, the most useful one of the whole build:

**Intending to be honest is not the same as being honest. A proof artifact is itself a claim, and
claims need an adversary.** The Evidence Pack only became trustworthy *after* something tried to break
it — and the thing that broke it wasn't more good intentions, it was the same boring discipline as the
ruler in Log 004: re-derive the number from the source, and believe only what survives.

If you build a system to keep agents honest, point it at yourself last. That's where it finds the most.

**Try it live:** <https://aftershock.redoubtlabs.dev> · **Read the code:** <https://github.com/bluntmachetti/aftershock>
(the corrected proof bundle is
[`docs/EVIDENCE.md`](https://github.com/bluntmachetti/aftershock/blob/main/docs/EVIDENCE.md);
the receipt is `web/src/components/DecisionReceipt.tsx`)

*Built with Qwen Cloud (`qwen3.5-flash` / `qwen3.5-plus` / `qwen3-max` via DashScope) and Alibaba
Cloud ECS, for the Qwen Cloud Global AI Hackathon.*
