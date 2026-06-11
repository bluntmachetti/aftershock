# Aftershock

**A disaster-struck town run by a society of Qwen agents that split tasks, negotiate scarce
rescue resources, and measurably beat a single big model on lives saved per dollar.**

An earthquake hits a simulated town. Missions appear — a collapsed school with people trapped,
a hospital running on six hours of generator fuel. A society of AI agents with distinct
capabilities (incident commander, medical, fire & rescue, logistics, infrastructure, public
comms) must divide the work, negotiate over scarce resources, and save as many lives as
possible before deadlines expire.

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

## Results (live benchmark, 2026-06-11)

Four arms, identical seeded worlds (5 paired seeds × 60-tick budget), real Qwen Cloud
calls. Full tables in [bench/results/2026-06-11/](bench/results/2026-06-11/RESULTS.md);
reproduce with `aftershock bench`.

| arm | coordination | models | lives saved (mean±sd) | missions failed | cost/run | lives per $ |
|---|---|---|---|---|---|---|
| **society** | negotiation protocol | flash ×5 + plus commander | 103.2 ± 23.6 | 0.4 | $0.042 | **2441** |
| solo | none (one agent) | qwen3-max | 104.2 ± 13.6 | 0.4 | $0.065 | 1606 |
| swarm | none (5 agents) | flash ×5 | 75.6 ± 15.4 | 3.0 | $0.016 | 4710* |
| scripted | negotiation protocol | heuristics ($0) | 106.8 ± 18.0 | 0.2 | $0.00 | — |

Two findings, both causal because every arm faces byte-identical worlds:

1. **The protocol is worth +28 lives per run.** Same five cheap models, with vs without
   the negotiation protocol: 103.2 vs 75.6 lives saved, 0.4 vs 3.0 missions failed.
   The run records show why — the swarm wasted 160 decisions racing for empty resource
   pools; the society resolved contention in the auction *before* acting.
   (*swarm's high lives-per-$ is efficiency at a much worse outcome.)
2. **The society matches the flagship at 65% of the cost.** A coordinated team of
   qwen3.5-flash workers under a qwen3.5-plus commander saves as many lives as one
   qwen3-max doing everything (103.2 vs 104.2 — within noise), for 52% more lives per
   dollar, and runs 1.6× faster (parallel small calls beat sequential big ones).

Honest caveat: well-tuned scripted heuristics using the same protocol remain competitive
with all LLM arms on this scenario — the protocol, not raw model intelligence, carries
most of the outcome. That is the point of the project.

Everything we've learned about agent behavior along the way — including the negative
results — is logged with evidence in [docs/FIELD-NOTES.md](docs/FIELD-NOTES.md).

## Status

In active development for the Qwen Cloud Global AI Hackathon. Done: deterministic kernel,
disaster-town society, Qwen-driven agents, 4-arm benchmark harness. Next: live map UI,
MCP spectator server, Alibaba Cloud deployment.

## Quickstart

```bash
uv sync
uv run aftershock run --seed 42 --ticks 60 --arm scripted
uv run aftershock verify --seed 42   # determinism self-check: two runs, identical digests
uv run pytest
```

## License

MIT — see [LICENSE](LICENSE).
