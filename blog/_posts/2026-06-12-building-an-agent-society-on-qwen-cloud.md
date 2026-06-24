---
layout: post
title: "When does a society of small Qwen models beat one big model? Building Aftershock."
date: 2026-06-12 09:00:00 -0700
description: "The build journey of Aftershock — cost-tiered cognition on Qwen Cloud: six small models out-delivering one big one at ~65% better lives-per-dollar, doctrine conformance credible at p=0.031, the honest negative results, and a real NYC Hurricane Ida scenario. (The early +28-lives coordination figure was later firmed to a suggestive +8.9 — see Log 007 and Log 008.)"
log: "001"
read: "9 min"
summary: "The founding question and the architecture behind it — splitting a disaster response across six specialized agents that negotiate scarce resources, and the seeded-world harness that decides whether the society actually pays for itself."
flags:
  - text: Architecture
    kind: ok
  - text: Benchmark
    kind: warn
  - text: Foundations
---

Most multi-agent demos are theater. Agents take turns talking, politely agree with each
other, duplicate half the work, and somewhere off-camera a single strong model with a decent
prompt quietly does the whole task better and cheaper. I've built enough of these to find the
genre uncomfortable. So when I started [**Aftershock**](https://github.com/bluntmachetti/aftershock)
for the Qwen Cloud hackathon, I didn't want to ask *can* agents collaborate. I wanted to ask the
harder, more falsifiable question:

> **When is a society of small models actually better than one big model — and can you prove it?**

This post is the build journey: the bet, why Qwen Cloud's model line-up made the architecture
possible, what the numbers said (including the parts that didn't flatter the idea), and what I'd
tell anyone building agent societies next.

Live demo: **<https://aftershock.redoubtlabs.dev>** · Code: **<https://github.com/bluntmachetti/aftershock>**

## The bet: disaster response, scored on lives

To make "better" mean something, you need a task where coordination failures have a cost. So
Aftershock is a disaster-response simulator. An earthquake (or, in real-data mode, a hurricane)
hits a city. Missions appear on a map — a collapsed school with people trapped, a hospital down
to its last hours of generator fuel, flooded neighborhoods. Six agents with distinct roles —
incident commander, medical, fire & rescue, logistics, infrastructure, public comms — have to
divide the work and fight over a fixed pool of ambulances, rescue crews, fire engines, and fuel
before deadlines expire.

Crucially, every run is **scored**: lives saved, response latency, missions failed, and cost.
Not vibes. Numbers.

## Why Qwen Cloud made the architecture possible

The whole thesis depends on small models being cheap enough that you can afford *many* of them.
Qwen Cloud's tiered line-up is what made the design economical, so I leaned into a structure I
think of as **cost-tiered cognition**:

- **`qwen3.5-flash`** runs the five worker roles — fast, cheap, good enough for a typed role
  decision every tick.
- **`qwen3.5-plus`** is the incident commander and arbitrator — a little more capable, sitting
  at the one position where judgment under contention actually matters.
- **`qwen3-max`** plays two parts: the *solo baseline* (one big model doing everything) and the
  *after-action analyst* that writes the post-run report.

Every agent talks to Qwen Cloud through the OpenAI-compatible chat-completions endpoint on
DashScope-International and is required to return strict JSON. The simulator validates every
decision *before* it touches the world, and rejected decisions are fed back to the agent on its
next turn with a named reason. A per-tick token/cost ledger means Qwen usage is visible in the
results, not hidden behind the demo — you can read the exact dollars-per-run in the benchmark
tables.

This is the part I want to underline for anyone else building on Qwen Cloud: the price gap
between flash and max is the entire reason a "team of cheap specialists vs. one expensive
generalist" comparison is even interesting. Five flash workers + a plus commander cost about
**$0.042 a run**; one qwen3-max doing everything costs **$0.065**. The architecture question only
exists because the cheap tier is genuinely cheap.

## Making it measurable, not impressive

The thing that kills most agent benchmarks is that every run sees a different world, so the
result is just a story. Aftershock is built around three properties that turn anecdotes into
evidence:

1. **Determinism.** All randomness flows from one seeded RNG; IDs come from counters; the engine
   never calls `time.now()` or `random` in the simulation path. Same seed + same agent decisions
   = byte-identical run, replayable forever. Every arm faces *exactly* the same disasters.
2. **A typed negotiation protocol.** Agents don't free-text at each other. They emit typed
   proposals — resource requests, task handoffs, escalations, information shares — and an auction
   resolves contention atomically every tick. Coordination is a *mechanic*, not a chat transcript.
3. **Validation with rejection feedback.** Small models love to invent entity IDs and repeat
   invalid actions. Engine-side validation plus a short rejection memory in the next observation
   fixed far more than extra prompting ever did.

Then I ran the same seeded disasters four ways — scripted heuristics, one qwen3-max solo, a flat
swarm of five flash agents with *no* protocol, and the structured society — and let the numbers
talk.

## The result that mattered

| arm | models | lives saved (mean±sd) | missions failed | cost/run |
|---|---|---|---|---|
| **society** | flash ×5 + plus commander | **103.2 ± 23.6** | 0.4 | $0.042 |
| solo | qwen3-max | 104.2 ± 13.6 | 0.4 | $0.065 |
| swarm | flash ×5 (no protocol) | 75.6 ± 15.4 | 3.0 | $0.016 |
| scripted | heuristics ($0) | 106.8 ± 18.0 | 0.2 | $0.00 |

Two findings, both *causal* because every arm faced byte-identical worlds:

- **The coordination protocol is worth +28 lives a run.** The same five `qwen3.5-flash` models,
  with vs. without the negotiation protocol, went from 75.6 to 103.2 lives saved and from 3.0 to
  0.4 missions failed. The run records show why: the protocol-less swarm burned ~160 decisions
  racing each other for empty resource pools; the society resolved that contention in the auction
  *before* acting.
- **The society matches the flagship for a third less money.** A team of cheap `qwen3.5-flash`
  workers under a `qwen3.5-plus` commander saved as many lives as one `qwen3-max` doing
  everything (103.2 vs 104.2 — inside the noise), at ~35% lower cost and over 1.5× faster, because
  five small parallel calls beat one big sequential one.

That's the headline: **with the right coordination structure, small Qwen models reach big-model
outcomes at lower cost.**

## The honest part (the bit I'm proudest of)

Here's what a hype demo would hide and I put on the front page instead: a well-tuned **scripted**
baseline, using the exact same negotiation protocol, stays competitive with every LLM arm. In
other words, *the protocol carries more of the result than the LLMs do*.

That's not a failure of the project. It **is** the project. Agent societies don't need more agents
talking — they need institutions: roles, contracts, arbitration, validation, measurement. The
LLMs are the easy part; the mechanism is the hard part.

I logged every behavioral finding, including the negative ones, in
[`docs/FIELD-NOTES.md`](https://github.com/bluntmachetti/aftershock/blob/main/docs/FIELD-NOTES.md).
My favorite is the **memory paradox**: my first naive after-action-report memory loop (let the
qwen3-max analyst write free-text "lessons" and feed them into the next briefing) made outcomes
*worse* on paired controls. Lessons expressed outside the agents' actual action space are just
noise. Memory has to live in the action space or it hurts.

## Grounding it in reality

Synthetic seeds prove the comparison, but I wanted the demo grounded. So Aftershock can compile
scenarios **offline from real open incident data** and show that incident stream's *real*
first-on-scene latency on screen as the baseline. The flagship pack is **Hurricane Ida over New
York, the night of 2021-09-01**, built from FDNY EMS and Fire dispatch records via NYC Open Data:
2,003 real EMS incidents, ~16.5% of calls held, a 948-second mean response time vs. ~524 s on a
calm night two weeks earlier.

And it never overclaims. Every field on screen is labeled **REAL / MAPPED / INFERRED /
SYNTHETIC**: the demand arrival and the latency baseline are real; mission severity is mapped;
lives-at-risk is inferred; outcomes are a simulated model. I do not claim agents beat real
responders on lives saved — only that they face the *real demand the world actually produced*.
The compiler runs offline, so a real scenario is still byte-deterministic.

## Shipping it on Alibaba Cloud

The observatory — a React + FastAPI app where you can scrub any run tick-by-tick, inspect each
agent's decisions, compare arms side by side, and start live runs — is deployed on an Alibaba
Cloud ECS instance with Docker Compose behind a Caddy HTTPS front door. The deployment is
reproducible straight from the public repo: clone, drop in your `DASHSCOPE_API_KEY`,
`docker compose up`. Run records stream over WebSockets, and an MCP spectator server exposes the
same data to any MCP client.

## What I'd tell the next person building an agent society

1. **Decide what "better" means before you build, and make it a number.** Lives, latency, cost —
   on byte-identical worlds. Without that, you have a story, not a result.
2. **Spend your model budget where judgment lives.** Cost-tiered cognition (flash workers, a plus
   arbitrator, a max analyst) got big-model outcomes at small-model prices on Qwen Cloud.
3. **Coordination is a mechanic, not a conversation.** A typed protocol + an auction beat more
   prompting and more agents, by a wide margin.
4. **Validate and give feedback.** Reject invalid actions with reasons and remember them for one
   tick; small models recover instead of corrupting the run.
5. **Publish your negative results.** The scripted-is-competitive finding and the memory paradox
   are the most credible things in the whole project.

The larger goal is to make multi-agent systems *falsifiable*: not "look how many agents are
talking," but "here is the coordination mechanism, here is the baseline, and here is the measured
gain." Qwen Cloud's cheap-enough small models are what make that experiment affordable to run.

**Try it live:** <https://aftershock.redoubtlabs.dev> · **Read the code:** <https://github.com/bluntmachetti/aftershock>

*Built with Qwen Cloud (`qwen3.5-flash` / `qwen3.5-plus` / `qwen3-max` via DashScope) and Alibaba
Cloud ECS, for the Qwen Cloud Global AI Hackathon.*
