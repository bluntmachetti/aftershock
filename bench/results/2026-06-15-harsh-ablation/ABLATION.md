# Ablation — society vs swarm (paired)

**n=11 paired seeds** · mean swarm=57.09 · mean society=61.82

**Δ lives = +4.73** (sd 16.66) · 95% bootstrap CI [-4.00, +14.73] · sign test p=1.0000 (6+/5-/0=)

Observed power to detect this Δ at n=11: **0.15** (α=0.05).

> Verdict: **not distinguishable from noise** — the CI includes 0. Add seeds (see the power curve) or seed the sampler (M1) before claiming an effect.

## Per-seed

| seed | swarm | society | Δ |
|---|---|---|---|
| 5 | 78 | 63 | -15 |
| 11 | 39 | 70 | +31 |
| 13 | 50 | 55 | +5 |
| 23 | 66 | 63 | -3 |
| 29 | 90 | 80 | -10 |
| 37 | 64 | 70 | +6 |
| 41 | 67 | 56 | -11 |
| 42 | 62 | 72 | +10 |
| 53 | 43 | 50 | +7 |
| 57 | 32 | 69 | +37 |
| 67 | 37 | 32 | -5 |

## Power curve

Paired z-approximation; seeds needed for 80% power at α=0.05, given the observed Δ sd=16.66.

| effect (lives) | seeds needed | power at current n |
|---|---|---|
| +2 | 545 | 0.06 |
| +5 | 88 | 0.17 |
| +10 | 22 | 0.51 |
| +15 | 10 | 0.85 |
| +20 | 6 | 0.98 |

