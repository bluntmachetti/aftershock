---
layout: post
title: "We added native function calling. The benchmark told us to turn it off."
date: 2026-06-14 09:00:00 -0700
description: "An honest ablation: we added Qwen Cloud native function calling to the Aftershock agent society, benchmarked it on identical seeded worlds, and found it cost ~2× for no lives benefit. Why per-call tool-schema overhead dominates in high-frequency multi-agent systems — and why JSON contracts stayed the default."
---

A confession about hackathon incentives. The Qwen Cloud judging rubric weights *"sophisticated
use of Qwen Cloud APIs"* at about 30%, and [**Aftershock**](https://github.com/bluntmachetti/aftershock)'s
agent society had, until last week, been talking to Qwen the unglamorous way: every agent returns
strict JSON, the engine parses and validates it. Functional, but it doesn't *look* like you're
using the platform's fanciest toy. So I did the obvious thing and wired up **native function
calling** — per-role `tools`, `tool_choice`, `parallel_tool_calls`, a dedicated `no_op` idle tool,
the works.

Then I did the thing I keep telling everyone else to do, and which is the entire point of this
project: I benchmarked it before believing in it.

The benchmark told me to turn it off.

This post is that result — because a negative result you measured honestly is worth more than a
feature you shipped on faith.

## What "native function calling" replaced

In JSON mode, each agent's system prompt carries a compact prose contract — *here are your
actions, here are the fields, return JSON* — and the model returns a JSON object the engine
validates. In tool mode, that same action vocabulary becomes a set of OpenAI-style `tools`
definitions sent on every request, and the model emits structured `tool_calls` instead. Same
decisions, same auction, same negotiation protocol underneath. The *only* thing that changed is
how the action space is described to the model and how the model hands its choices back.

I kept the change behind a flag (`--society-tools`) and a `force_tools` switch, so I could run the
*exact* same five paired seeds both ways and let the numbers decide. Same disasters, byte for
byte. Only the calling convention differs.

## The numbers

| society mode | lives saved (mean ± sd) | missions failed | cost/run | latency/run |
|---|---|---|---|---|
| **JSON contracts (default)** | **103.2 ± 23.6** | **0.4** | **$0.042** | 120 s |
| native function calling | 98.2 ± 23.2 | 0.8 | $0.083 | 297 s |

Read that top to bottom. Tool calling held lives saved **within the noise** — 98.2 vs 103.2 sits
comfortably inside one standard deviation (±23) — while **cost roughly doubled and latency rose
~2.5×**. The one place it moved measurably in the *wrong* direction was missions failed: 0.8 vs
0.4, twice as many lapsed deadlines, plausibly downstream of the higher latency (the
`qwen3.5-plus` commander even hit a couple of request timeouts under the heavier payloads).

If you're tempted to read the 5-life dip as a real regression, the paired-seed view talks you out
of it — tool mode was lower on four seeds, higher on one:

| seed | 11 | 23 | 37 | 42 | 57 |
|---|---|---|---|---|---|
| JSON lives | 140 | 86 | 81 | 98 | 111 |
| tool lives | 138 | 79 | 90 | 87 | 97 |

That's noise with a faint downward lean, not a signal. So the honest summary is brutal in its
simplicity: **native function calling cost twice as much to do the same job, slightly worse.**

## Why — and why no amount of prompting saves it

The cause isn't a bad implementation or an untuned prompt. It's structural, and it's worth
internalizing if you build multi-agent systems.

A society run makes roughly **240 model calls** — six agents, dozens of ticks. In JSON mode the
action vocabulary rides along as a ~450-token prose contract. In tool mode the equivalent `tools`
schema is **~1,000 tokens**, and — this is the load-bearing sentence — **it is re-sent on every
single one of those 240 calls.** The schema is pure repeated input tokens. The most expensive
seat in the house, the `qwen3.5-plus` commander, ate 59% of the run's cost on its own; the five
flash workers split the rest, their prompts dominated by that resent schema.

I genuinely tried to schema-trim my way out of it. I projected every option: strip the
auto-generated pydantic `title`/`default` noise, compact the descriptions, even gut them to empty
strings. The floor — descriptions deleted entirely — is about **$0.069/run**. Still above the JSON
path's $0.042, and still above the single-`qwen3-max`-does-everything baseline (~$0.06). You can't
trim a per-call tax down to nothing when you pay it 240 times.

## The decision: default off, available and measured

So Aftershock ships with **JSON contracts as the default** — the cost-optimal path, and the one
the published headline ("a society of small models matches a `qwen3-max` solo agent at ~35% lower
cost") actually reflects. Native function calling stays **implemented, tested, and benchmarked**,
one flag away (`aftershock run --arm society --society-tools`), with its full ablation published in
the repo and in [`docs/FIELD-NOTES.md`](https://github.com/bluntmachetti/aftershock/blob/main/docs/FIELD-NOTES.md).

I'll defend that as the *more* sophisticated use of the API, not the less. Shipping the fancy
feature by default because the rubric rewards fancy features is cargo-culting. Wiring it up,
measuring it against a real baseline on identical worlds, discovering it doesn't pay for itself in
*your* regime, and making that an informed, reversible default — that's engineering judgment.
"We used native function calling and measured exactly what it costs" is a stronger sentence than
"we used native function calling."

## The transferable lesson (with the scope caveat that matters)

The general rule: **in a high-frequency multi-agent system, per-call overhead dominates — measure
it before you adopt it.** Anything you attach to *every* request (tool schemas, verbose system
prompts, retrieved context, elaborate output formats) gets multiplied by your call count, and in a
society that number is large. The fancier API is not free; it's free *per call* and you make
hundreds of calls.

And the caveat that keeps this honest: this is **not** "function calling is bad." For a
single-agent assistant, or any app that makes a handful of calls per task, a 1,000-token schema is
a rounding error and the reliability and ergonomics of structured tool calls are well worth it —
the math flips entirely. Function calling earns its keep at low call counts. It just gets taxed to
death at high ones. Know which regime you're in.

That's the whole ethos of Aftershock in miniature: don't ask whether the shiny thing *can* work —
measure when it *actually* pays, on worlds identical enough that the answer means something. This
time the shiny thing didn't pay, and saying so out loud is the result.

**Try it live:** <https://aftershock.redoubtlabs.dev> · **Read the code:** <https://github.com/bluntmachetti/aftershock>

*Built with Qwen Cloud (`qwen3.5-flash` / `qwen3.5-plus` / `qwen3-max` via DashScope) and Alibaba
Cloud ECS, for the Qwen Cloud Global AI Hackathon.*
