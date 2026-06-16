# Aftershock

**A disaster-struck town run by a society of Qwen agents that split tasks, negotiate scarce
rescue resources, and measurably beat a single big model on lives saved per dollar.**

A disaster hits a simulated city. Missions appear — flooded neighborhoods, a collapsed school
with people trapped, a hospital running on generator fuel. A society of AI agents with distinct
capabilities (incident commander, medical, fire & rescue, logistics, infrastructure, public
comms) must divide the work, negotiate over scarce resources, and save as many lives as possible
before deadlines expire. Synthetic disasters drive the benchmark; committed real-data scenario
packs let the observatory replay real incident demand while keeping outcomes explicitly simulated.

Aftershock is two things:

1. **A small agent-society kernel** — a deterministic tick engine, a typed decision registry
   with validation and rejection feedback, a typed negotiation protocol (resource requests,
   handoffs, escalations, info shares) with atomic per-tick resolution, roles-as-YAML, a
   per-tick token/cost ledger, and replayable NDJSON run records. Same seed + same decisions
   = same outcome, byte for byte.
2. **A benchmark** — identical seeded scenarios run four ways: scripted bots ($0 baseline),
   one big model doing everything, a flat swarm of small models, and a structured society of
   small models with a negotiation protocol. Scored on lives saved, response latency, and
   cost per run.

Built for the Qwen Cloud Global AI Hackathon (Agent Society track).

## Current status

Aftershock is a working end-to-end prototype:

- Deterministic Python simulation kernel and four-arm benchmark: `scripted`, `solo`, `swarm`,
  `society`.
- Qwen-backed agent society using DashScope models, with token/cost accounting and after-action
  reporting.
- React observatory served by FastAPI — a "Mission Control / EOC" command map with a live
  **contention overlay** that draws the resource auction on the map (contested districts linked,
  losing/winning incidents flagged) plus a deadline/severity/panic-driven condition state,
  alongside run replay, live runs, benchmark comparison, scenario provenance, and real-vs-sim
  latency strips.
- MCP spectator server for browsing run records and injecting live events.
- Real-data scenario packs committed under `scenarios/`, including the headline NYC Hurricane Ida
  pack.
- Docker deployment with a Caddy HTTPS front door (see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)). The
  current public deployment is: <https://aftershock.redoubtlabs.dev>

The public deployment requires an observatory token for mutating live-run endpoints; read-only
surfaces such as recorded runs and scenario metadata are public.

## Results (live benchmark, 2026-06-11)

Four arms, identical seeded worlds (5 paired seeds × 60-tick budget), real Qwen Cloud
calls. Full tables in [bench/results/2026-06-11/](bench/results/2026-06-11/RESULTS.md);
reproduce with `aftershock bench`.

*Note: the society arm runs in JSON-contract mode by default — the cost-optimal path these
numbers reflect. Native Qwen function calling (`tools`/`tool_choice`) is implemented and
benchmarked as an opt-in (`--society-tools`); see
[Native Qwen function calling](#native-qwen-function-calling-measured-ablation) below for the
measured cost tradeoff.*

| arm | coordination | models | lives saved (mean±sd) | missions failed | cost/run | lives per $ |
|---|---|---|---|---|---|---|
| **society** | negotiation protocol | flash ×5 + plus commander | 103.2 ± 23.6 | 0.4 | $0.042 | **2441** |
| solo | none (one agent) | qwen3-max | 104.2 ± 13.6 | 0.4 | $0.065 | 1606 |
| swarm | none (5 agents) | flash ×5 | 75.6 ± 15.4 | 3.0 | $0.016 | 4710* |
| scripted | negotiation protocol | heuristics ($0) | 106.8 ± 18.0 | 0.2 | $0.00 | — |

Two findings, both causal because every arm faces byte-identical worlds:

1. **The protocol is worth ~+28 lives per run.** Same five cheap models, with vs without
   the negotiation protocol: 103.2 vs 75.6 lives saved, 0.4 vs 3.0 missions failed.
   The run records show why — the swarm wasted 160 decisions racing for empty resource
   pools; the society resolved contention in the auction *before* acting.
   (*swarm's high lives-per-$ is efficiency at a much worse outcome.)
   *(Caveat: +28 is an n=5 paired mean — society ≥ swarm on all five seeds (robust
   direction), but the magnitude is soft: sign test p=0.125, power 0.42, leveraged by one
   seed; a tight bound needs ~25 seeds. See [FIELD-NOTES §17](docs/FIELD-NOTES.md).)*
2. **The society matches the flagship at 65% of the cost.** A coordinated team of
   qwen3.5-flash workers under a qwen3.5-plus commander saves as many lives as one
   qwen3-max doing everything (103.2 vs 104.2 — within noise), for 52% more lives per
   dollar, and runs over 1.5× faster (parallel small calls beat sequential big ones).

Honest caveat: well-tuned scripted heuristics using the same protocol remain competitive
with all LLM arms on this scenario — the protocol, not raw model intelligence, carries
most of the outcome. That is the point of the project.

Everything we've learned about agent behavior along the way — including the negative
results — is logged with evidence in [docs/FIELD-NOTES.md](docs/FIELD-NOTES.md).

### Native Qwen function calling (measured ablation)

The society also speaks Qwen Cloud **native function calling** — per-role `tools`, `tool_choice`,
`parallel_tool_calls`, and a `no_op` idle tool — as an opt-in:
`aftershock run --arm society --society-tools` (or `aftershock bench --society-tools`). We
benchmarked it on the same 5 paired seeds
([bench/results/2026-06-13-tool-ablation/](bench/results/2026-06-13-tool-ablation/RESULTS.md)):

| society mode | lives saved (mean±sd) | missions failed | cost/run | latency/run | lives per $ |
|---|---|---|---|---|---|
| **JSON contracts (default)** | 103.2 ± 23.6 | 0.4 | **$0.042** | 120 s | **2441** |
| native function calling | 98.2 ± 23.2 | 0.8 | $0.083 | 297 s | 1188 |

**Finding:** native tool calling held decision quality within noise (98.2 vs 103.2 lives —
well inside ±23 SD) but cost ~2× more and ran ~2.5× slower. The cause is structural, not
tuning: the ~1k-token tool schema is re-sent on *every* one of ~240 agent calls per run, and
trimming schemas/descriptions to the bone still only reaches ~$0.069/run — above the JSON path.
So Aftershock's cost-optimal default is JSON contracts, with function calling implemented,
benchmarked, and available behind `--society-tools`. Full write-up in
[docs/FIELD-NOTES.md](docs/FIELD-NOTES.md).

## Real-data scenarios (sim vs reality)

Beyond the synthetic benchmark, the society can run on scenarios compiled **offline from real
open incident data**, with that incident stream's real first-on-scene latency shown on screen as
the baseline. This is *sim-vs-reality*, not a claim about real outcomes: the demand arrival and
the response-latency baseline are real; lives saved and outcomes are a simulated model. Every
scenario surface carries `REAL / MAPPED / INFERRED / SYNTHETIC` provenance and a caveat line, and
the compiler runs offline so determinism is preserved (same pack + seed = byte-identical run).
Run one with `aftershock run --scenario nyc-ida-2021` and watch the observatory's reality strip.

The flagship real-data pack is **NYC Hurricane Ida, night of 2021-09-01**:

- Source data: FDNY EMS Incident Dispatch Data (`76xm-jjuj`) and Fire Incident Dispatch Data
  (`8m42-w767`) via NYC Open Data.
- Window: `2021-09-01T18:00:00-04:00` to `2021-09-02T06:00:00-04:00`.
- Real demand sample: 16 scenario missions stratified from 2,212 filtered EMS/fire incidents.
- Real surge signal: 2,003 EMS rows in the Ida window, ~16.5% held, 948 s mean first-on-scene.
- Calm comparison window: 2021-08-18 18:00 to 2021-08-19 06:00 EDT, 524 s mean first-on-scene,
  4.2% held.
- Honesty contract: demand and latency baseline are real; mission kinds/severity are mapped;
  lives at risk are inferred; blockages and outcomes are simulated.

Shipped packs (see each pack's `README.md` and `docs/DESIGN.md` §"Real-data scenario packs"):

- **`nyc-ida-2021`** — Hurricane Ida over NYC, night of 2021-09-01 (the real surge: ~16.5% of EMS
  calls held, ~948 s mean first-on-scene). Source: **FDNY EMS Incident Dispatch Data
  (`76xm-jjuj`) + Fire Incident Dispatch Data (`8m42-w767`) via NYC Open Data** — attribution:
  *FDNY via NYC Open Data* (NYC Open Data terms).
- **`sf-routine-2018`** — routine emergency demand, San Francisco. Source: **DataSF Fire
  Department and EMS Dispatched Calls for Service (`nuek-vuh3`)** — license: **PDDL (public
  domain)**; attribution: *DataSF*.

Scenario packs are demo/observatory surfaces only; the published 4-arm benchmark above stays
synthetic-seed (`aftershock bench` refuses `--scenario`).

## Future work

Aftershock is meant to become a broader benchmark harness for agent societies, not just a single
disaster demo. Planned directions:

- **More real-data scenario packs:** add other cities, hazards, and operating conditions while
  preserving the same provenance contract (`REAL / MAPPED / INFERRED / SYNTHETIC`).
- **Architecture leaderboard:** compare society designs against solo and swarm baselines under
  paired deterministic seeds, with public run records and cost accounting.
- **Better memory loops:** turn after-action lessons into doctrine-grounded, action-space rules
  agents can actually use; naive free-text memory made outcomes worse in early experiments.
- **Human-in-the-loop operations:** expand the MCP spectator and live-injection tools so external
  users can stress-test the society during a run.
- **Community role packs:** make it easier to contribute new role definitions, doctrine files, and
  negotiation policies on top of the same kernel.
- **Richer real-data honesty:** add more baseline measurements where source data supports them,
  while keeping simulated outcomes clearly separated from real-world claims.

## Quickstart

```bash
uv sync
uv run aftershock run --seed 42 --ticks 60 --arm scripted
uv run aftershock verify --seed 42   # determinism self-check: two runs, identical digests
uv run pytest
```

Run the NYC Ida scenario locally:

```bash
uv run aftershock run --scenario nyc-ida-2021 --arm society --seed 4636
uv run aftershock serve --runs-dir runs --port 8788
```

For a local no-LLM smoke test, use `--arm scripted` instead of `--arm society`.

## License

MIT — see [LICENSE](LICENSE).
