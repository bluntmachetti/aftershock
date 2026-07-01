---
layout: post
title: "We only ever tested Qwen. So we ran the headline against eleven other models — and had to correct how we say it"
date: 2026-07-01 09:00:00 -0700
description: "Every claim in this log rides on Qwen models, so the fair critique is: is 'a cheap coordinated society beats one big model' just a Qwen artifact? To answer it I built a family-agnostic provider path (one OpenRouter endpoint, any family, Qwen-only request fields kept off the non-Qwen hosts) and ran the solo arm — one model runs the whole town — on twelve models from ten families: GPT-5, Gemini 3.1 Pro, Claude Opus 4.8, Grok 4.3, DeepSeek V4 Pro/Flash, Kimi K2.7, GLM 5.2, Qwen3-235B, Llama-3.3-70B, Mistral Large, and a Llama-3.1-8B floor. Result: no single model's solo beats the cheap six-flash Qwen society on lives — but the eight frontier models (US and Chinese) TIE it, at 3-14x the cost. That forced an honest correction: earlier, on Qwen-only data, a big Qwen solo sat at the swarm's anarchy floor, which made 'coordination beats a big model' sound like a lives claim. Cross-family it isn't — a genuine frontier solo reaches the outcome ceiling. The society's win is on cost-efficiency, and it holds across ten families. Plus the honest dent (a cheap DeepSeek V4 Flash that ties on lives and beats on cost) and a clean cross-family capability floor."
log: "011"
read: "8 min"
summary: "A reader's fair critique: every result in this log uses Qwen, so maybe 'a cheap coordinated society beats one big model' is a Qwen artifact. I built a family-agnostic provider (one OpenRouter endpoint; Qwen-only request fields stay off the non-Qwen hosts so the DashScope path is byte-identical) and ran the solo arm on twelve models from ten families. Verdict: no model's solo BEATS the cheap all-flash Qwen society on lives — but the eight frontier models (GPT-5, Gemini 3.1 Pro, Claude Opus 4.8, Grok, DeepSeek V4 Pro/Flash, Kimi K2.7, GLM 5.2) TIE it, every paired sign test p>=0.29, at 3-14x the cost. That's an honest correction to how I'd been phrasing it: on Qwen-only data a big Qwen solo sat at the swarm floor, so 'coordination beats a big model' read like a lives claim; cross-family a frontier solo reaches the outcome ceiling, and the society's win is on cost-efficiency (~12x on lives-per-dollar), holding across ten families. The honest dent: DeepSeek V4 Flash ties on lives at 4x better cost. And a clean cross-family capability floor: below the frontier solos fall off and an 8B model collapses. Spend ~$14.5."
flags:
  - text: "12 models, 10 families"
    kind: ok
  - text: "No solo beats the cheap society"
    kind: ok
  - text: "Frontier ties on lives (a walk-back)"
    kind: warn
  - text: "Society wins ~12x on cost"
    kind: ok
---

In the last two logs I wrote that six cheap Qwen models with a protocol out-deliver one big model
(Log 009), and — last log — that paying 10× for a bigger model buys nothing the outcome can see
(Log 010). A reader asked the obvious, fair question: **every model you've ever run is a Qwen. How do
you know this isn't a Qwen thing?**

They're right that it's the load-bearing objection. If the only "big model" you ever test is
`qwen3-max`, "a society beats a big model" could just mean "our society beats one *particular family's*
flagship." The honest way to find out is to run the claim against the actual frontier — every family
you can reach — and see what survives. So that's what I did. This entry is that test, and the small
correction it forced on how I say the result.

## Getting to the other families

[Aftershock](https://github.com/bluntmachetti/aftershock) talks to models through a single provider
chokepoint that was wired only for Alibaba's DashScope (Qwen). The fix was small and additive: point
the whole stack at any OpenAI-compatible endpoint via one environment variable, and route through
**OpenRouter**, which serves every family behind one API. The one subtlety worth naming — because it's
exactly the kind of thing that silently corrupts a benchmark — is that a couple of request fields we
send are **Qwen-specific** (`enable_thinking`, and a self-hosted reasoning toggle). Send those to a
strict router in front of GPT-5 and it can reject the call. So the new path keeps those fields *off*
the non-Qwen hosts, and the DashScope request body stays **byte-identical** to what it was. I also
smoke-tested every model against the JSON decision contract before spending a cent, and made the cost
ledger read real per-model prices so lives-per-dollar stays honest across families.

Then the experiment: the **`solo` arm** — one model runs the entire town, no protocol — on twelve
models from ten families, ten paired seeds each, against the same cheap all-flash Qwen **society**
(six `qwen3.5-flash` workers + the auction + doctrine) that has anchored this whole log:
**106.0 lives saved, $0.025 a run, 4272 lives per dollar.**

## What the twelve models did

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>solo arm, 10 paired seeds, vs the cheap Qwen society (106.0 lives · $0.025 · 4272 lives/$)</div>
  <table class="rt">
    <thead><tr><th>Model (solo)</th><th>Family</th><th>Lives</th><th>Cost</th><th>Lives/$</th><th>Δ vs society</th></tr></thead>
    <tbody>
      <tr><td>GPT-5</td><td>US frontier</td><td>107.6</td><td>$0.340</td><td>317</td><td>+1.6 <span class="muted">(p=1.00)</span></td></tr>
      <tr><td>Gemini 3.1 Pro</td><td>US frontier</td><td>109.0</td><td>$0.356</td><td>306</td><td>+3.0 <span class="muted">(p=0.51)</span></td></tr>
      <tr><td>Claude Opus 4.8</td><td>US frontier</td><td>108.0</td><td>$0.313</td><td>345</td><td>+2.0 <span class="muted">(p=0.29)</span></td></tr>
      <tr><td>Grok 4.3</td><td>US frontier</td><td>106.0</td><td>$0.075</td><td>1408</td><td>+0.0 <span class="muted">(p=0.75)</span></td></tr>
      <tr><td>DeepSeek V4 Pro</td><td>CN frontier</td><td>104.0</td><td>$0.029</td><td>3551</td><td>−2.0 <span class="muted">(p=0.75)</span></td></tr>
      <tr><td>DeepSeek V4 Flash</td><td>CN frontier</td><td>103.4</td><td>$0.006</td><td><strong>17782</strong></td><td>−2.6 <span class="muted">(p=0.51)</span></td></tr>
      <tr><td>Kimi K2.7</td><td>CN frontier</td><td>101.6</td><td>$0.076</td><td>1345</td><td>−4.4 <span class="muted">(p=1.00)</span></td></tr>
      <tr><td>GLM 5.2</td><td>CN frontier</td><td>105.4</td><td>$0.066</td><td>1595</td><td>−0.6 <span class="muted">(p=0.51)</span></td></tr>
      <tr class="win"><td><strong>cheap Qwen society</strong></td><td>—</td><td><strong>106.0</strong></td><td><strong>$0.025</strong></td><td><strong>4272</strong></td><td>—</td></tr>
      <tr class="lose"><td>Mistral Large</td><td>open-weight</td><td>95.1</td><td>$0.023</td><td>4114</td><td>−10.9 <span class="muted">(p=0.002)</span></td></tr>
      <tr class="lose"><td>Llama 3.3 70B</td><td>open-weight</td><td>97.7</td><td>$0.004</td><td>28141</td><td>−8.3 <span class="muted">(p=0.29)</span></td></tr>
      <tr class="lose"><td>Qwen3 235B</td><td>open-weight</td><td>79.7</td><td>$0.003</td><td>27638</td><td>−26.3 <span class="muted">(p=0.002)</span></td></tr>
      <tr class="lose"><td>Llama 3.1 8B</td><td>floor</td><td>24.6</td><td>$0.001</td><td>32958</td><td>−81.4 <span class="muted">(p=0.002)</span></td></tr>
    </tbody>
  </table>
</div>

The headline is the top block. **No single model's solo beats the cheap six-flash society on lives.**
The eight frontier-class models — four American, four Chinese — land at 102–109 lives, every paired
sign test at p ≥ 0.29, which at ten seeds with a standard deviation near sixteen is
*indistinguishable from the society*. And they pay for the tie: 3–14× the cost, 306–1595 lives per
dollar against the society's 4272.

## The correction I owe

Here's the part I have to be straight about, because the cross-family run doesn't just confirm the old
story — it *corrects* it. When the only big model I'd tested was `qwen3-max`, its solo sat down at the
swarm's anarchy floor (a finding from a few logs back). That made it easy — too easy — to say
"coordination beats a big model," and to let that sound like a claim about *lives*.

Cross-family, that phrasing is too strong. A genuine frontier solo — GPT-5, Gemini 3.1 Pro, Opus 4.8,
Grok, and DeepSeek V4 and GLM behind them — **does reach the coordination ceiling on the outcome.** It
ties the society on lives. So the honest version isn't "coordination beats a big model." It's: **a
big-enough model's solo matches the cheap coordinated society on the outcome, and the society's win is
on cost — up to ~14× on lives-per-dollar against the flagship frontiers (a slimmer margin against the
cheaper ones) — and it holds, in direction, across ten families.** That's a narrower
claim than I'd been implying, and it's the true one.

And there's one honest dent I won't bury: **DeepSeek V4 Flash** ties the society on lives *and* beats
it on cost — 103.4 lives at $0.006 a run, four times the society's lives-per-dollar. A cheap enough,
good enough single model can win the cost argument too. It's one model out of twelve, and the society's
edge is robust across the whole board, but "coordination always wins on cost" would be an overclaim, so:
it doesn't, quite.

## What didn't tie

Below the frontier, the picture is exactly the capability story you'd hope a good ruler shows. Mistral
Large lands 11 lives short (p=0.002), Qwen3-235B twenty-six short (p=0.002), and the **Llama-3.1-8B
floor collapses** to 24.6 lives — losing every one of the ten seeds — echoing the 1.7B collapse I found
self-hosting earlier. There's a real competence threshold to *operate the town at all*, and it sits
somewhere above 8B and below the frontier, consistently, across families. That's the other half of the
robustness result: the substrate cleanly separates models that can do the job from models that can't,
and it does it the same way regardless of who trained them.

## The honest bounds

Three, as ever. **The runs aren't byte-reproducible** — the LLM layer never was (the provider ignores
our sampling seed), so this is independent-seed inference, and I pair every model against the society by
seed to cancel the world draw. **The prompts are Qwen-tuned** — they were written and iterated against
Qwen, so a non-Qwen model that scores a little lower is partly being judged on prompt fit, not raw
capability; the mitigation is that all twelve parsed the JSON contract cleanly, and the *frontier tie*
(the load-bearing result) doesn't depend on it. And **the prices drift** — these are OpenRouter list
prices on the day, so read lives-per-dollar as an order-of-magnitude, not a decimal. One model-choice
note: the only Kimi 2.7 on the router was the *code-specialized* build, which is a worse fit for a
decision task and ran ~10× slower — but it still tied within noise, so it doesn't move the verdict.

The whole thing cost about **$14.50**. That number is itself a small argument for the finding: I
stress-tested the central claim of the project against every frontier model I could reach — GPT-5 to
DeepSeek V4 — for the price of a sandwich, because the honest outcome metric is cheap to measure and the
society it's being compared against runs on models that cost fractions of a cent.

So: the reader was right to push, and the claim is better for it. **Six cheap coordinated models match
any single frontier model's outcome — at up to a tenth of the flagship's cost — and that holds across
ten families, not one.** It's not the flashier "the small society beats the big model." It's the true
one, and now it's the one I'll say.

Live demo: **<https://aftershock.redoubtlabs.dev>** · Code: **<https://github.com/bluntmachetti/aftershock>**
(method + verdict in `docs/FIELD-NOTES.md` §28; data under `bench/results/2026-07-01-panelA-solo/`)
