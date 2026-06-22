# Judge Evidence Pack

> A single frozen, citable proof bundle. Every number below traces to a file in
> this repo — no figure is asserted without a source path. Last verified
> 2026-06-22.

## 1. The claim (60-second read)

Aftershock is a **deterministic agent-society benchmark**: identical seeded
disaster scenarios run four ways (scripted heuristics, one big model, a flat
swarm, a structured society with a negotiation protocol), scored on lives saved
per dollar. The robust finding is **cost-efficiency**: six cheap qwen3.5-flash
workers plus a qwen3.5-plus commander **match the expert-heuristic baseline on
lives** (108.4 vs 106.8) and **out-deliver the solo big model** (108.4 vs 95.6)
at **~3.5¢ per run** — **~65% better lives per dollar than the solo big model**.
Against the flat swarm the society holds a **suggestive** lives edge (+8.9 at
n=15, wins 11/15, bootstrap CI [+2.3, +15.4] excludes 0, but sign-test p=0.118 —
suggestive, not significant: the CI excludes 0 but the sign test doesn't clear
significance). Written
**doctrine credibly raises team alignment** (+0.125, n=6, p=0.031). The scripted
expert-heuristic baseline is byte-for-byte reproducible; the Qwen arms
demonstrate real instruction-following (team alignment 0.76–1.00). Real-data
scenario packs (NYC Ida 2021) let the observatory replay real incident demand
while keeping outcomes explicitly simulated.

## 2. What is simulated vs real (the honesty boundary)

| Surface | Real | Simulated |
|---|---|---|
| Scenario demand (NYC Ida) | ✅ Incident timestamps, district IDs — FDNY open data | — |
| Latency baseline | ✅ Real EMS first-on-scene times (calm-window comparison) | — |
| Mission kind / severity | Mapped from real dispatch codes | — |
| Lives at risk | — | Inferred from severity, not observed |
| Road blockages | — | Synthetic (no ground truth) |
| Lives saved / lost / outcomes | — | Fully simulated model — never claimed as real |

Source: `scenarios/nyc-ida-2021/scenario.json` → `field_provenance`. The
caveat line *"Demand: real · Latency baseline: real · Lives & outcomes:
simulated model."* is chosen per pack by `_caveat_line_for_pack` (the
`_CAVEAT_DISPATCH` constant in `src/aftershock/web.py`) and stored in each
scenario run's manifest (`runs/seed91-society/run.json` → `scenario.caveat_line`).

## 3. The benchmark result

**Batch:** `bench/results/2026-06-22-4arm-refresh/results.json` — 4 arms, n=5
paired seeds {11, 23, 37, 42, 57}, 60 ticks each.

| Arm | Mean lives saved | Mean cost/run | Lives per $ |
|---|---|---|---|
| **scripted** (expert heuristics, $0) | 106.8 | $0.0000 | — (free, control) |
| **society** (6-role Qwen, negotiation) | 108.4 | $0.0353 | 3,069 |
| **solo** (one big Qwen model) | 95.6 | $0.0515 | 1,855 |
| **swarm** (flat swarm, no protocol) | 93.8 | $0.0132 | 7,133 |

**The protocol's value — society vs swarm (suggestive, not significant):**

| Stat | Value |
|---|---|
| n (paired seeds) | 15 |
| Mean delta (society − swarm) | **+8.9 lives** |
| Seeds where society won | 11 of 15 |
| Sign-test p (two-sided) | 0.118 |
| Bootstrap 95% CI | [+2.3, +15.4] (excludes 0) |
| Verdict | **suggestive** — CI excludes 0 but sign-test (p=0.118) doesn't clear significance |

> We surface this as **suggestive** — the CI excludes 0 but the sign test
> doesn't clear significance — by the harness's own 3-tier rule (credible =
> CI-excludes-0 AND sign-significant; suggestive = exactly one; noise =
> neither). The direction is consistent (society wins 11/15) and the bootstrap
> 95% CI [+2.3, +15.4] excludes 0, but the sign-test (p=0.118) does not clear
> α=0.05 — exactly one condition holds, so we do not claim a proven lives win.
> **An earlier +28-lives figure was an n=5 overestimate**: one seed dominated
> the small sample. Firming to 15 paired seeds collapsed the magnitude to a
> small, suggestive +8.9. We report the firmed number, not the headline the
> small sample first suggested — the harness caught our own ghost.
>
> **Sources:** `bench/results/2026-06-22-4arm-refresh/` (seeds {11,23,37,42,57})
> + `bench/results/2026-06-22-swarm-firm/` (seeds {60..69}).

**Society vs solo (cost-efficiency — the robust finding):** Six cheap
qwen3.5-flash workers plus a qwen3.5-plus commander **save more lives than one
big model** (108.4 vs 95.6) at **31% lower cost** ($0.0353 vs $0.0515) →
**65% better lives per dollar** (3,069 vs 1,855). The negotiation protocol lets
small models coordinate to out-deliver a single big model for less money.

**Society vs scripted:** The deterministic expert-heuristic baseline is strong
(106.8 vs 108.4). Society **matches the expert heuristics on lives** (108.4 vs
106.8) — a coordinated team of small models holds its own against hand-tuned
domain expertise, at ~$0.035/run.

### Reproduce

```bash
uv run aftershock bench          # re-runs the 4-arm paired-seed benchmark
```

The paired table lives in each `results.json` → `paired` (arm → seed →
lives_saved). The sign-test + bootstrap CI adapter (`bench.paired_comparisons`)
is server-side; the Bench tab renders it. The raw deltas above are reproducible
from the file:

```bash
python3 -c "import json,statistics; d=json.load(open('bench/results/2026-06-22-4arm-refresh/results.json')); s=d['paired']['society']; w=d['paired']['swarm']; seeds=sorted(set(s)&set(w)); deltas=[s[x]-w[x] for x in seeds]; print(f'mean_delta={statistics.mean(deltas):+.1f} deltas={deltas}')"
```

## 4. Determinism proof

```bash
uv run aftershock verify --seed 42 --ticks 60
# → PASS — both runs produced identical world-digest sequences
```

The scripted engine re-runs twice and compares `world_digest` sequences. All
randomness flows from `rng.rng_for(seed, *parts)` — no `random.*`, `time.time()`,
`datetime.now()`, or `uuid4()` in the simulation path (enforced by ruff `DTZ`).
The LLM/society arm is **not** reproducible (DashScope ignores `seed`) — the
determinism claim is scoped to the scripted engine only.

## 5. Qwen-track framing (verified numbers only)

Judges are Alibaba/Qwen representatives. Every figure below is pulled from a
file path, not estimated.

### "3.5-cent agent society"

The 4-arm bench (§3) puts the society at **$0.0353/run on average** — down ~16%
from the first benchmark ($0.0423 on 2026-06-11), now **~3,069 lives per $**.
The frozen episode below is a single longer 6-role society run (commander + comms
+ fire + infrastructure + medical + rescue) and costs **$0.0441** — 171,499
prompt + 24,109 completion tokens. Workers are qwen3.5-flash; the commander is
qwen3.5-plus.

| Source file | Field | Value |
|---|---|---|
| `runs/episodes/ep1-seed100-society/run.json` → `cost.by_agent` (summed) | total cost | $0.0441 |
| same | prompt tokens | 171,499 |
| same | completion tokens | 24,109 |
| same | lives saved / lost | 113 / 57 |
| same | missions resolved / failed | 11 / 0 |

Reproduce:
```bash
python3 -c "import json; r=json.load(open('runs/episodes/ep1-seed100-society/run.json')); c=r['cost']['by_agent']; print(f'cost=\${sum(a[\"cost_usd\"] for a in c.values()):.4f} prompt={sum(a[\"prompt_tokens\"] for a in c.values()):,} comp={sum(a[\"completion_tokens\"] for a in c.values()):,}')"
```

> ⚠️ `runs/` is gitignored — the frozen episode won't reach a fresh prod box via
> `git pull` alone. Provisioning step required (see Day-1 carry-over).

### Deterministic conformance — Qwen instruction-following

The conformance checker measures how often each role's decisions obey the
two-tier doctrine (role envelope + decision registry). `team_alignment` is the
society-wide rate.

| Run | Ticks | team_alignment | Source |
|---|---|---|---|
| `seed42-society` (synthetic) | 5 | 1.0000 | `runs/seed42-society/conformance.json` |
| `seed91-society` (NYC Ida) | 65 recorded (80 budget) | 0.9517 | `runs/seed91-society/conformance.json` |
| `ep1-seed100-society` (episode) | 30 | 0.7588 | `runs/episodes/ep1-seed100-society/conformance.json` |

The demo run (`seed91-society`, 65 recorded ticks on real NYC Ida demand)
achieves **0.9517** — Qwen follows the structured doctrine 95% of the time over
a full scenario. The shorter runs reach perfect alignment. (Never cite 0.915 —
that was a hallucinated figure from an early review that couldn't read the
gitignored file; the real ep1 value is 0.7588.)

> **Conformance ≠ outcome.** High doctrine alignment means the agents followed
> the protocol — it does *not* mean they saved everyone. On `seed91-society`
> the society saved 8 and lost 82 lives (outcomes are fully simulated, §2).
> The conformance number proves instruction-following, not rescue quality.

#### Doctrine on/off — what the structure buys

The strongest *causal* conformance result is a paired ablation: same world seeds,
same tools, doctrine layer toggled on vs off. Doctrine raises team alignment at no
lives cost — and the effect **replicates** across two independent runs. The
conformance Δ is positive on **all 11 seeds across both runs**; at n=6 the sign
test reaches **p=0.03125 → credible** by the harness's CI-and-sign-test gate.

| Run | Metric (society, doctrine off → on) | Off | On | Δ | n | Sign-test p | Verdict |
|---|---|---|---|---|---|---|---|
| original (2026-06-16) | team_alignment (deterministic) | 0.696 | 0.852 | +0.156 | 5 | 0.0625 (5/5 positive) | suggestive |
| **re-test (2026-06-22)** | team_alignment (deterministic) | 0.763 | 0.888 | **+0.125** | **6** | **0.03125 (6/6 positive)** | **credible** |
| original | lives saved | 100.4 | 104.2 | +3.8 | 5 | 0.375 | noise (not a cost) |
| re-test | lives saved | 103.7 | 109.7 | +6.0 | 6 | 0.375 | noise (not a cost) |

**Source:** `bench/results/2026-06-16-doctrine-ablation/` and
`bench/results/2026-06-22-doctrine-6seed/` (`ablation.json` + per-seed
`conformance.json`). Conformance is the deterministic signal; absolute levels
differ between runs (independent LLM sampling), but the **effect** is stable
(+0.125 to +0.156) and positive on every one of the 11 seeds — at n=6 it clears
the n=5 sign-test floor (0.0625 → 0.03125). Lives stays noise in both runs — the
point is that doctrine buys measurable alignment **without** a lives penalty.

### Real Qwen rationales

The Decision Receipt (Day 3) renders the agents' free-text reasoning on
contested resource conflicts. Example from `ep1-seed100-society` tick 1 — the
commander prioritizes missions while role agents request resources through the
auction:

> **commander** (set_priority, mission m2): *"Medical surge with shortest
> deadline (7). Max priority to save lives."*
>
> **commander** (set_priority, mission m3): *"High severity collapse rescue.
> Deadline allows calculation: 4\*2+2=10, capped by resource constraints."*

These are real Qwen outputs, labeled **"agent-stated"** in the UI (distinct from
**"decided by kernel"** rulings). The receipt chains: kernel ruling → matched
proposal → grant decision → agent-stated rationale → tick-level cost → recorded
outcome — with no counterfactual calls.

## 6. NYC Ida 2021 scenario provenance

| Field | Value | Source |
|---|---|---|
| Pack ID | `nyc-ida-2021` | `scenarios/nyc-ida-2021/scenario.json` |
| Hazard | hurricane_flood | same |
| config_sha256 | `5d7485f3d9dad82359f183412e5b6071287adcb2c2cb2aa479b070154b4784bb` | `scenarios/nyc-ida-2021/scenario.json` → `config_sha256` |
| pack_digest | `38d5e4a9a21c8900e7f3b11b9b73b02928468a4e51ecc3b4c6c571969b946782` | computed at load time by `src/aftershock/town/scenario.py` (`_compute_digest`); stored in the run manifest `runs/seed91-society/run.json` → `scenario.pack_digest` (not in `scenario.json` itself) |
| Window | 2021-09-01 18:00 → 09-02 06:00 EDT | same |
| Sources | FDNY EMS Dispatch (76xm-jjuj, 2,003 rows) + Fire Dispatch (8m42-w767, 2,022 rows) | same → `source[]` |
| Real incidents in window | 2,212 | same → `reference.aggregates.n_incidents` |
| Real mean latency | 948 s | same → `reference.aggregates.mean_latency_s` |

**Per-field provenance (the hard honesty contract):**

| Field | Provenance |
|---|---|
| tick (incident time) | **REAL** |
| district_id | **REAL** |
| mission_kind | MAPPED (from dispatch codes) |
| severity | MAPPED |
| lives_at_risk | INFERRED (from severity) |
| blockage | SYNTHETIC (no ground truth) |

We **never** claim agents beat real *outcomes* — only real demand + latency are
real. The observatory's RealityStrip shows the real latency baseline alongside
the simulated arm; ProvenancePanel badges every field.

## 7. Frozen demo run IDs

| Run ID | Purpose | Arm | Seed | Key stat |
|---|---|---|---|---|
| `ep1-seed100-society` | Society episode (receipt demo) | society | 100 | $0.044, 113 lives, alignment 0.759 |
| `seed91-society` | NYC Ida scenario run | society | 91 | 65 ticks, alignment 0.952, 8 saved / 82 lost |
| `seed42-society` | Synthetic society run | society | 42 | alignment 1.000 |
| `seed42-scripted` | Determinism demo | scripted | 42 | verify PASS |

> `runs/` is gitignored. To demo on a fresh box, copy the frozen run dirs or add
> a provisioning step. The bench results (`bench/results/`) and scenario packs
> (`scenarios/*/scenario.json`) **are** tracked and ship via `git pull`.
