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

## Status

Early development. The kernel and the scripted-agent simulation land first; Qwen-driven
agents, the benchmark harness, the live map UI, and the MCP spectator server follow.

## Quickstart

```bash
uv sync
uv run aftershock run --seed 42 --ticks 60 --arm scripted
uv run aftershock verify --seed 42   # determinism self-check: two runs, identical digests
uv run pytest
```

## License

MIT — see [LICENSE](LICENSE).
