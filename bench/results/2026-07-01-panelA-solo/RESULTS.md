# Panel A — cross-family `solo` vs the cheap Qwen society (FIELD-NOTES §28)

Does the §25/§26 "coordination beats model size" result hold across model **families**, or is it a
Qwen artifact? Each model powers the **`solo` arm** (one model decides everything) over the same 10
paired seeds × 60 ticks, via OpenRouter (`DASHSCOPE_BASE_URL`), priced from `bench/panelA_prices.json`.
Comparator = the cheap all-flash Qwen **society** (`bench/results/2026-06-30-mtier-flash`):
**106.0 lives, $0.0248/run, 4272 lives/$**. Δ = solo − society, paired by seed; sign test.

| solo model | family | lives (sd) | cost/run | lives/$ | Δ vs society | sign test |
|---|---|---|---|---|---|---|
| openai/gpt-5 | US frontier | 107.6 (±16.9) | $0.3399 | 317 | +1.6 | p=1.000 (5+/4−) |
| google/gemini-3.1-pro-preview | US frontier | 109.0 (±16.6) | $0.3560 | 306 | +3.0 | p=0.508 (6+/3−) |
| anthropic/claude-opus-4.8 | US frontier | 108.0 (±16.7) | $0.3127 | 345 | +2.0 | p=0.289 (6+/2−) |
| x-ai/grok-4.3 | US frontier | 106.0 (±16.1) | $0.0753 | 1408 | +0.0 | p=0.754 (4+/6−) |
| deepseek/deepseek-v4-pro | CN frontier | 104.0 (±14.1) | $0.0293 | 3551 | −2.0 | p=0.754 (4+/6−) |
| deepseek/deepseek-v4-flash | CN frontier | 103.4 (±11.9) | $0.0058 | **17782** | −2.6 | p=0.508 (3+/6−) |
| moonshotai/kimi-k2.7-code | CN frontier | 101.6 (±21.1) | $0.0755 | 1345 | −4.4 | p=1.000 (4+/5−) |
| z-ai/glm-5.2 | CN frontier | 105.4 (±15.2) | $0.0661 | 1595 | −0.6 | p=0.508 (3+/6−) |
| **cheap Qwen society** | — | **106.0** | **$0.0248** | **4272** | — | — |
| mistralai/mistral-large-2512 | open-weight | 95.1 (±13.9) | $0.0231 | 4114 | −10.9 | **p=0.002 (0+/10−)** |
| meta-llama/llama-3.3-70b-instruct | open-weight | 97.7 (±12.6) | $0.0035 | 28141 | −8.3 | p=0.289 (2+/6−) |
| qwen/qwen3-235b-a22b-2507 | open-weight | 79.7 (±13.4) | $0.0029 | 27638 | −26.3 | **p=0.002 (0+/10−)** |
| meta-llama/llama-3.1-8b-instruct | floor | 24.6 (±22.3) | $0.0007 | 32958 | −81.4 | **p=0.002 (0+/10−)** |

## Verdict

1. **No model's solo beats the cheap six-flash coordinated society on lives.** The eight frontier-class
   models (US + Chinese) only **tie** it (Δ ∈ [−4.4, +3.0], every sign test p ≥ 0.29 → indistinguishable
   from the society at n=10, sd≈16). The strongest (gpt-5/gemini-3.1/opus) reach the society's outcome
   level — refining the Qwen-only §4 finding that a big *Qwen* solo sat at the swarm floor.
2. **The frontiers pay 3–14× for the tie.** lives-per-$ 306–1595 vs the society's 4272. **Exception:**
   `deepseek-v4-flash` ties on lives at **4× better** cost-efficiency ($17782/life) — a genuinely strong
   cheap solo, the one honest dent in "coordination wins on cost."
3. **Below the frontier, solos fall off** — mistral-large −10.9 (p=0.002), qwen3-235b −26.3 (p=0.002) —
   and the **8B floor collapses** (24.6 lives, −81.4, p=0.002): a clean cross-family capability floor
   (cf. §22's 1.7B collapse).

**Caveats:** independent-seed (LLM layer is non-deterministic; §13); prompts/contract are Qwen-tuned,
so a weaker cross-family score is partly prompt-fit (all 12 parsed the JSON contract cleanly). `kimi-k2.7-code`
is the code-specialized build (the only Kimi 2.7 on OpenRouter) and ran ~589s/run. Total spend ~$14.5.
