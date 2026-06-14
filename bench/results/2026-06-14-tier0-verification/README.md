# Tier-0 measurement verification (2026-06-14)

The paid verification of the Tier-0 measurement harness against live DashScope. Raw run dirs are
gitignored; this directory holds the curated results. Full findings: `docs/FIELD-NOTES.md` §13–14.

## M1 — does DashScope honor the sampling `seed`? **No.**

`society` seed 42 × 30 ticks, run twice **with** `--seed-sampler` and twice **without**, comparing the
recorded decision streams:

| pair | world_digest | decision content | lives_saved |
|---|---|---|---|
| seeded (`--seed-sampler`) ×2 | diverge @ tick 6 | diverge @ tick 1 | 96 vs 99 |
| unseeded (baseline) ×2 | diverge @ tick 6 | diverge @ tick 1 | 90 vs 98 |

The seeded pair is no more alike than the unseeded baseline → **DashScope accepts but ignores `seed`**
(at temperature 0.3). `--seed-sampler` is kept as a documented no-op opt-in. The LLM arms are
irreducibly stochastic run-to-run; the engine remains byte-deterministic (scripted anchor).

## M2 — within-seed (LLM) vs between-seed (world) variance

`society`, 3 seeds (11, 42, 57) × 3 repeats, 30 ticks (`bench --repeat-seeds 3`). See `REPEATS.md` /
`repeats.json`:

| mean | σ_within (LLM) | σ_between (world) | σ_total | ICC (world fraction) |
|---|---|---|---|---|
| 110.7 | 7.75 | 14.87 | 16.76 | **0.79** |

Per-seed means: 11→126.7, 42→95.7, 57→109.7. **~79% of variance is the world, ~21% is the model.**

### Consequence: pair, don't repeat

Pairing control vs treatment on the same seeds cancels the world variance (the dominant 79%). Paired-Δ
SD ≈ √2·σ_within ≈ 11.0 vs an unpaired contrast's √2·σ_total ≈ 23.7. Seeds needed for 80% power
(α=0.05), via `stats.required_n_for_effect`:

| effect | paired (`aftershock ablation`) | unpaired |
|---|---|---|
| +5 lives | 38 | 177 |
| +10 lives | 10 | 45 |
| +15 lives | 5 | 20 |

→ Every agent-tuning result goes through the paired ablation harness; ~10 seeds make a +10-life effect
visible. σ here is at 30 ticks; the published headline σ≈23.6 is 60-tick between-seed spread (same story
at larger scale, not re-validated tick-for-tick).

## Cost

13 society runs at 30 ticks (4 for M1, 9 for M2) ≈ a few cents total; each run ~80 s.
