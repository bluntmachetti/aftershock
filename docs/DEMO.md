# DEMO — Aftershock observatory (3-minute judge arc)

A voucher-free walk-through. Every step replays **recorded** runs or runs the
**scripted** (LLM-free, deterministic) engine — no `DASHSCOPE_API_KEY` needed.
Live LLM arms (solo/swarm/society) are voucher-gated; when the key is absent the
UI shows a **"Qwen society live-engine offline (voucher pending)"** chip and
steers you to the recorded society episodes instead of erroring.

Start the observatory locally:

```bash
uv run aftershock serve --runs-dir runs --port 8788
# then open http://127.0.0.1:8788
```

## The 5-step arc

| # | Beat | Tab | Frozen run id(s) | Seed | Arm |
|---|------|-----|------------------|------|-----|
| 1 | Grounding (real data) | Map | `seed91-society` | 91 | society |
| 2 | Decision (agent reasoning) | Map | `ep1-seed100-society` | 100 | society |
| 3 | Counterfactual (what-if) | Compare | `seed42-society` ↔ `cf-a1646318-none` | 42 | society / scripted |
| 4 | Stress (chaos injection) | Live | (live scripted demo) | 42 | scripted |
| 5 | Proof (determinism + bench) | Bench | `aftershock verify` + Bench tab | 42 | scripted |

All run ids above are reachable from the runs list (`GET /api/runs`), including
the `ep1-seed100-society` episode (nested under `runs/episodes/`, served flat).

---

### 1. Grounding — NYC Ida 2021 (real demand + latency baseline)

Open the **Map** tab and select **`seed91-society`** (seed 91, society, 80
ticks). This run was built from the committed **`nyc-ida-2021`** scenario pack.

- **RealityStrip** plots the *real* first-on-scene latencies (NYC FDNY/EMS
  dispatch records) against the society's per-tick response — the only real
  *outcomes* here are demand + latency baseline; lives are a simulated model.
- **ProvenancePanel** shows the per-field `REAL`/`MAPPED`/`INFERRED`/`SYNTHETIC`
  badges and the pack caveat line. The hazard chip reads as verified data.

> Honesty: real demand + latency baseline are REAL; lives & outcomes are a
> simulated model. Never state the agents beat real *outcomes*.

### 2. Decision — contested-mission reasoning (society rationales)

Switch to **`ep1-seed100-society`** (seed 100, society, 60 ticks). This curated
episode carries populated agent rationales, an **AAR** (`aar.json`, grade B), and
a **conformance** report (`conformance.json`, `team_alignment = 0.759`).

- Scrub to a contested tick and open a mission in **MissionControlMap**.
- **NegotiationFeed** shows the typed proposals + kernel rulings
  (`decided_by: kernel:*`).
- Agent `rationale` text is labeled **agent-stated**; kernel `ruling.reason` is
  **decided by kernel**. (The consolidated **Decision Receipt** card lands
  Day 3 — until then the chain reads from the feed + mission tile.)

### 3. Counterfactual — branch at tick N, DIVERGES marker

Open the **Compare** tab. Left = **`seed42-society`** (baseline, society, 5
ticks). Right = **`cf-a1646318-none`** (a pre-baked **control** branch:
`kind=none`, `at_tick=2` — a byte-identical re-run proving the prefix matches up
to the intervention tick).

- The scrubber's **DIVERGES** marker sits at the branch tick; for a `none`
  control the traces stay identical (the honesty proof). For a real divergence
  (`drop_protocol` / `kill_agent` / `inject_event`), an operator with a token
  can start a new branch from the Compare controls — scripted baselines work
  voucher-free; society baselines show the voucher chip when the key is absent.

> Counterfactual runs are labeled **what-if (simulated)**. `POST /api/counterfactual`
> is a mutating branch-starter, never fired per-card.

### 4. Stress — inject chaos, watch the auction react

Open the **Live** tab. With an operator token (`?token=…`), start a **scripted**
run (seed 42, 30 ticks) and use **Inject Event** to fire an `aftershock`,
`fire`, or `road_block` into a district mid-run. The negotiation auction and
scoreboard react live over the read-only WS.

- No token? The public box runs the server-side **ambient demo loop**
  (`AFTERSHOCK_DEMO_MODE`) so the Live tab is always alive without any client
  mutation.

### 5. Proof — determinism + benchmark

- **Determinism:** run `uv run aftershock verify --seed 42 --ticks 60` — it
  re-runs the scripted engine twice and asserts identical `world_digest`
  sequences. (Determinism covers the **scripted** engine only; DashScope ignores
  `seed`, so society runs are not bit-reproducible.)
- **Bench tab:** `uv run aftershock bench` runs the 4 arms over paired seeds
  and `/api/bench` serves lives-saved per dollar. Day 2 adds a bootstrap CI +
  paired sign-test p-value + power + a method note; non-significant effects are
  shown as non-significant (no green check on a weak p).

---

## Voucher-pending behavior (the graceful chip)

When `DASHSCOPE_API_KEY` is unset on the server, `GET /api/status` reports
`llm_key: false`. The UI then:

- shows the **"Qwen society live-engine offline (voucher pending)"** chip next
  to the arm selector (Live) and the Branch controls (Compare), and
- short-circuits a society/solo/swarm live start or society baseline branch with
  a graceful message instead of a raw `503`.

Scripted arms are keyless and never gated. Recorded society episodes (`ep1-…`
through `ep5-…`) replay without the voucher — they are the demo's society
surface until Day 5+ regenerates fresh live runs.

## Frozen run reference

| run_id | seed | arm | ticks | scenario | aar | conformance |
|--------|------|-----|-------|----------|-----|-------------|
| `seed91-society` | 91 | society | 80 | nyc-ida-2021 | — | ✓ |
| `ep1-seed100-society` | 100 | society | 60 | — (synthetic) | ✓ (B) | ✓ (0.759) |
| `seed42-society` | 42 | society | 5 | — | — | ✓ |
| `cf-a1646318-none` | 42 | scripted | 5 | — (control branch, at_tick=2) | — | — |
| `seed42-scripted` | 42 | scripted | 10 | — | — | ✓ |
