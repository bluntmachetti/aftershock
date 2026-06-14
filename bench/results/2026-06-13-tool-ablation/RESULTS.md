# Ablation: society arm with native Qwen function calling (2026-06-13)

**This is an opt-in ablation, not the primary benchmark.** The headline 4-arm comparison lives
in [`../2026-06-11/`](../2026-06-11/RESULTS.md) and runs the society in **JSON-contract mode**
(the cost-optimal default). Here the society was re-run with **native Qwen function calling**
(`aftershock bench --society-tools`): per-role `tools`, `tool_choice="auto"`,
`parallel_tool_calls`, and a `no_op` idle tool. Same 5 paired seeds, same 60-tick budget, same
real Qwen Cloud calls.

## The comparison that matters: society JSON vs society tool

| society mode | n | lives saved (mean±sd) | missions failed | cost/run | latency/run | lives per $ |
|---|---|---|---|---|---|---|
| JSON contracts (default, from `../2026-06-11/`) | 5 | 103.2 ± 23.6 | 0.4 | **$0.042** | 120 s | **2441** |
| native function calling (this run) | 5 | 98.2 ± 23.2 | 0.8 | $0.083 | 297 s | 1188 |

**Finding:** native tool calling held decision quality within noise (98.2 vs 103.2 lives — well
inside ±23 SD) but cost ~2× more and ran ~2.5× slower. The cause is structural: the ~1,000-token
tool schema is re-sent on every one of ~240 agent calls per run. Projected trim strategies (strip
pydantic `title`/`default`, compact descriptions, even empty descriptions) floor at ~$0.069/run —
still above the JSON path and above the qwen3-max solo baseline ($0.061). So JSON contracts remain
the default; function calling is implemented, benchmarked, and available behind `--society-tools`.
Full write-up: [`docs/FIELD-NOTES.md` §12](../../../docs/FIELD-NOTES.md).

## Full 4-arm table from this run (society = tool mode)

`results.json` holds the raw aggregate. Note: this run re-ran **all four arms**. Only the
**society** row changed mechanism (JSON → tools). `scripted` is deterministic and reproduced
**byte-identically** to `../2026-06-11/` (106.8 lives), confirming the harness is sound; the
`solo` (104.2 → 109.6) and `swarm` (75.6 → 77.4) differences are ordinary run-to-run LLM variance
on an unchanged code path, shown here only for context — they are **not** part of the ablation.

| arm | n | lives saved (mean±sd) | missions failed | cost/run | latency/run | lives per $ | provenance |
|---|---|---|---|---|---|---|---|
| society (tool mode) | 5 | 98.2 ± 23.2 | 0.8 | $0.083 | 297 s | 1188 | **the ablation** |
| scripted | 5 | 106.8 ± 18.0 | 0.2 | $0.00 | ~0 s | — | determinism check (identical to primary) |
| solo | 5 | 109.6 ± 18.5 | 0.2 | $0.061 | 146 s | 1804 | fresh sample (unchanged path) |
| swarm | 5 | 77.4 ± 16.5 | 2.4 | $0.016 | 53 s | 4986 | fresh sample (unchanged path) |

Reproduce: `aftershock bench --society-tools --out <dir>` (requires `DASHSCOPE_API_KEY`).
