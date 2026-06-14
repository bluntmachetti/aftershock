# Hackathon Submission Draft

Use this as the source of truth for Devpost copy and the demo-video script.

## Project Overview

### Project name

Aftershock

### Elevator pitch

A disaster-response society of Qwen agents that negotiates scarce resources and proves when small coordinated models beat one big model.

### Try it out links

- Live demo: https://aftershock.redoubtlabs.dev
- GitHub repo: https://github.com/bluntmachetti/aftershock
- Benchmark results: https://github.com/bluntmachetti/aftershock/tree/main/bench/results/2026-06-11
- NYC Ida scenario pack: https://github.com/bluntmachetti/aftershock/tree/main/scenarios/nyc-ida-2021

### Built with

`python`, `fastapi`, `qwen-cloud`, `dashscope`, `alibaba-cloud-ecs`, `react`, `typescript`,
`vite`, `websockets`, `docker`, `caddy`, `mcp`, `pydantic`, `pytest`

## Project Story

### Inspiration

Months of experimenting with long-running multi-agent simulations taught me an uncomfortable
lesson: many "agent teams" are theater. Agents chat, agree with each other, duplicate work, and a
single strong model with a good prompt quietly outperforms them.

The interesting question is not *can* agents collaborate. It is *when is a society of small models
actually better than one big model, and can you prove it?*

Aftershock answers that question in an unforgiving setting: disaster response, where coordination
failures cost lives. It asks a concrete question: can a structured society of Qwen agents split
work, negotiate over scarce resources, and save as many simulated lives as a flagship solo model at
lower cost?

### What it does

Aftershock is a deterministic disaster-response simulator and live observatory for Qwen agent
societies.

A disaster hits a simulated city. Missions appear on the map: flooded neighborhoods, a collapsed
school with people trapped, a hospital running on generator fuel. A society of Qwen agents with
distinct roles must respond: incident commander, medical, fire and rescue, logistics,
infrastructure, and public communications.

The project has three core pieces:

- **Task division:** the commander decomposes each mission into typed work and assigns it by role.
  Agents can accept, reject, sub-delegate, or escalate with structured reasons.
- **Negotiation under scarcity:** ambulances, rescue crews, fire engines, fuel, and generators are
  limited. Agents compete for them through a typed proposal protocol: resource requests, task
  handoffs, escalations, and information shares. The engine resolves conflicts atomically every
  tick, so coordination is a mechanic rather than a chat transcript.
- **Measurement:** the benchmark runs identical seeded disasters four ways: scripted bots, one
  qwen3-max solo agent, a flat swarm of qwen3.5-flash agents without the protocol, and the structured
  society using qwen3.5-flash workers with a qwen3.5-plus commander. It scores lives saved, response
  latency, missions failed, wall time, and cost.

The headline result: with the same five qwen3.5-flash workers, adding the negotiation protocol raised
mean lives saved from 75.6 to 103.2 and cut failed missions from 3.0 to 0.4. The structured society
matched the qwen3-max solo agent's outcome within noise while costing about 35% less per run.

Every run is replayable. Same seed plus same decisions gives the same outcome, byte for byte. The
web observatory lets judges scrub through ticks, inspect agent decisions, compare arms, start live
runs, and view an honest real-data scenario based on NYC Hurricane Ida.

### How we built it

Aftershock is built around a small reusable agent-society kernel in Python.

The kernel provides a deterministic tick loop, typed decision validation, a negotiation protocol,
atomic per-tick resolution, role definitions in YAML, a token/cost ledger, and replayable NDJSON run
records. The disaster town is the flagship society built on top of that kernel.

The Qwen layer uses cost-tiered cognition:

- qwen3.5-flash handles routine role decisions.
- qwen3.5-plus acts as the structured commander/arbitrator.
- qwen3-max writes after-action reports and higher-level analysis.

Agents output strict JSON through Qwen Cloud compatible chat completions. The simulator validates
every decision before it touches the world, and rejected decisions are fed back to agents so they
can recover instead of silently corrupting the run.

The observatory is a React and TypeScript frontend served by a FastAPI backend. It streams live
runs over WebSockets, replays recorded runs, compares benchmark arms, and surfaces scenario
provenance. The same backend exposes an MCP spectator server so an MCP client can inspect runs or
inject live events.

The public deployment runs on Alibaba Cloud ECS using Docker Compose. Caddy terminates HTTPS at
`aftershock.redoubtlabs.dev` and proxies to the FastAPI app.

### Real-data scenario: NYC Hurricane Ida

The benchmark is synthetic so every arm faces byte-identical worlds. But Aftershock also ships
offline-compiled real-data scenario packs for demonstration.

The headline pack is `nyc-ida-2021`, built from FDNY EMS Incident Dispatch Data and Fire Incident
Dispatch Data via NYC Open Data for the night of Hurricane Ida, 2021-09-01 18:00 to 2021-09-02
06:00 EDT.

The pack uses real incident demand and real first-on-scene latency as the baseline:

- 2,003 EMS rows in the Ida window.
- 16.5% held rate.
- 948 seconds mean first-on-scene.
- Calm comparison window two weeks earlier: 524 seconds mean first-on-scene and 4.2% held.

The honesty contract is explicit everywhere in the UI: demand and latency are real; mission kinds
and severity are mapped; lives at risk are inferred; blockages and outcomes are simulated. The
project does not claim to reproduce real casualty outcomes.

### Challenges we ran into

The hardest part was making the system measurable instead of merely impressive.

Small models will invent entity IDs, repeat invalid actions, and miss one-tick feedback. The fix was
not more prompting alone. We needed engine-side validation, named rejection reasons, and short-term
rejection memory in the next observations.

The second challenge was proving the society mattered. If every arm sees a different world, the
benchmark is just a story. Aftershock therefore uses paired deterministic seeds: the solo agent, the
swarm, the scripted baseline, and the society all face byte-identical disasters.

The third challenge was honesty around real data. NYC Open Data gives real incident timing and
response latency, but not real "lives saved" for our simulated missions. The UI had to show that
boundary clearly instead of hiding it in a footnote.

### Accomplishments that we're proud of

- A full multi-agent society that is not just a chat room: it has typed roles, typed proposals,
  validation, auctions, rejection feedback, and measurable outcomes.
- A benchmark that compares architecture choices under identical seeded worlds.
- A public observatory where judges can inspect the actual run records instead of trusting a
  summary.
- A real-data NYC Hurricane Ida scenario with visible provenance and caveats.
- A deployed Alibaba Cloud demo using Qwen Cloud models end to end.
- Negative results published alongside positive ones, including the finding that scripted
  heuristics with the same protocol remain highly competitive.

### What we learned

The strongest result is that coordination structure matters more than agent count.

Five qwen3.5-flash agents without a protocol saved 75.6 lives on average. The same five cheap models
inside a structured society saved 103.2. The difference was not model intelligence; it was the
mechanism that turned resource contention into explicit information before agents wasted actions.

We also learned that a society of small models can match a flagship solo model when the task is
decomposable. The structured society saved 103.2 lives per run versus 104.2 for qwen3-max solo, but
ran cheaper.

The uncomfortable lesson is that the protocol carries more of the result than the LLMs do.
Well-tuned scripted agents using the same coordination protocol remain competitive. That is not a
failure of the project; it is the point. Agent societies need institutions, contracts, and
measurement, not just more agents talking.

### What's next for Aftershock

Next we want to turn Aftershock into a general benchmark harness for agent societies:

- More real-data scenario packs from different hazards and cities.
- A public leaderboard comparing society architectures against solo and swarm baselines.
- Better memory loops where lessons are expressed in the agents' actual action space.
- More MCP tools for external spectators and human-in-the-loop incident injection.
- Community-contributed role packs and doctrine files.

The larger goal is to make multi-agent systems falsifiable: not "look how many agents are talking,"
but "here is the coordination mechanism, here is the baseline, and here is the measured gain."

## Additional Info

### Qwen Cloud API usage

Aftershock uses Qwen Cloud compatible chat completions for the LLM arms:

- `qwen3.5-flash` for worker role agents.
- `qwen3.5-plus` for the commander/arbitrator.
- `qwen3-max` for the solo baseline and after-action analysis.

The benchmark reports token usage and cost per run, so Qwen usage is visible in the results rather
than hidden behind the demo.

**Native function calling — implemented and measured.** Beyond strict-JSON contracts, the society
also speaks Qwen Cloud **native function calling**: per-role `tools`, `tool_choice="auto"`,
`parallel_tool_calls`, and a `no_op` idle tool (`aftershock run --arm society --society-tools`).
We didn't just bolt it on — we benchmarked it on the same paired seeds and found native tools held
lives saved within noise (98.2 vs 103.2) but cost ~2× more and ran ~2.5× slower, because the
~1k-token tool schema is re-sent on every one of ~240 agent calls per run. So the cost-optimal
**default** is JSON contracts, with function calling available and measured as an ablation
([bench/results/2026-06-13-tool-ablation/](../bench/results/2026-06-13-tool-ablation/RESULTS.md),
[docs/FIELD-NOTES.md §12](FIELD-NOTES.md)). The point isn't to chase the fanciest API — it's to
measure when it actually pays.

### Alibaba Cloud deployment

The live demo runs on Alibaba Cloud ECS:

- Docker Compose application stack.
- FastAPI backend serving the React observatory.
- Caddy HTTPS reverse proxy.
- Public URL: https://aftershock.redoubtlabs.dev

### GitHub repository

https://github.com/bluntmachetti/aftershock

## Demo Video Script (target 2:50 · hard cap 3:00)

Seven beats, ~2:50 of narration. VO lines below are final and feed the TTS pass verbatim; the
"SHOW" line is the captured UI footage cut under each line. Numbers match
[the README results table](../README.md#results-live-benchmark-2026-06-11).

### 1 · Hook (0:00–0:18)

VO: "Most multi-agent demos are theater — agents chat, agree, and a single big model quietly wins.
Aftershock asks a harder question: when does a society of *small* models actually save more lives
than one big model — and can you prove it?"

SHOW: title card → live map at `aftershock.redoubtlabs.dev`, missions appearing.

### 2 · The mechanism (0:18–0:48)

VO: "It's a disaster-response simulator. Six Qwen agents — commander, medical, fire, rescue,
logistics, comms — don't just talk. They emit typed decisions and negotiate over scarce ambulances
and crews through a proposal protocol. The engine validates every action, rejects bad ones with a
reason, and resolves contention in an auction every single tick."

SHOW: map with mission markers, negotiation feed scrolling, resource-pool sidebar draining, agent
inspector.

### 3 · The proof (0:48–1:22)

VO: "Same disaster, run four ways on byte-identical seeds. Here's the comparison that matters: five
cheap flash agents with *no* protocol save 75.6 lives. The *same* five models inside the structured
society save 103.2 — and fail seven times fewer missions. Same models, same world. The coordination
protocol alone is worth twenty-eight lives a run."

SHOW: Bench tab; the four-arm table; highlight swarm (75.6) vs society (103.2) and missions-failed
(3.0 → 0.4).

### 4 · Matches the flagship (1:22–1:42)

VO: "And the society matches a single qwen3-max doing everything — 103 lives versus 104 — at about a
third lower cost. Small coordinated models, big-model outcome, cheaper."

SHOW: Bench cost / lives-per-dollar columns; brief Compare tab (society vs solo, same seed).

### 5 · Real data, honest labels (1:42–2:18)

VO: "Synthetic seeds prove the comparison. Real data makes it grounded. This is Hurricane Ida over
New York, compiled offline from FDNY dispatch records: real demand, a real 948-second response
baseline, sixteen percent of calls held. And the interface never overclaims — every field is labeled
real, mapped, inferred, or simulated. We don't claim real lives saved. Only real demand."

SHOW: NYC Ida run — real borough names on the map, the RealityStrip (real vs sim latency + held),
the DATA provenance panel with the badge grid.

### 6 · Qwen + Alibaba (2:18–2:38)

VO: "Qwen Cloud runs all of it — flash workers, a plus commander, a max analyst — deployed on
Alibaba Cloud behind HTTPS, with every run inspectable through an MCP spectator server."

SHOW: architecture diagram (`docs/assets/aftershock-architecture.png`) → live HTTPS URL in the bar.

### 7 · Why it matters (2:38–2:52)

VO: "The lesson isn't *more agents*. It's that agent societies need institutions — roles, contracts,
arbitration, measurement. Aftershock makes that claim testable. It's live; go break it."

SHOW: final scoreboard / map, then the live URL card.

## Production pipeline

`media/` is gitignored scratch. Build order:

1. **VO first** (qwencloud-audio-tts): one clip per beat → real durations drive the edit. Keep a
   consistent voice; measured, documentary pace.
2. **Footage** (node Playwright `recordVideo`, 1920×1080, deployed URL): one clip per beat scripted
   to the matching VO length; replay/scrub recorded runs (no live-LLM latency on camera). The NYC
   beat uses the `seed7-scripted` Ida run; the society beats use a `seed42-society` run.
3. **Title/section cards**: optional qwencloud-image-generation poster; lower-thirds for the key
   numbers (+28 lives, 103.2 vs 75.6, 948 s, 16% held) via ffmpeg drawtext.
4. **Assemble** (ffmpeg): concat clips, lay VO per beat, hold the Bench table long enough to read,
   normalize loudness, export ≤ 3:00 H.264 1080p.

## Recording checklist

- Deployed URL `https://aftershock.redoubtlabs.dev`; 1080p; read-only surfaces only (no token in
  the address bar — open once with `?token=…`, let the SPA scrub it).
- Hold the Bench numbers and the provenance caveat on screen long enough to read.
- Start from recorded runs; never wait on live LLM latency on camera.
