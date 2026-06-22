# Ablation — contract on/off (society, paired)

Δ = **society (contract trimmed)** − **society-untrimmed (contract untrimmed)**, everything else held constant (world seed, tools, pools). A positive Δ means trimming adds the metric.

## Conformance (primary signal — deterministic)

**Team alignment: 0.898 (off) → 0.880 (on)** · Δ = -0.019 · sign test p=0.1094 · n=10

> Verdict (conformance Δ): **suggestive but unconfirmed** — the 95% CI excludes 0, but the sign test is not significant (p=0.109). Add seeds until the sign test agrees.

| seed | off | on | Δ |
|---|---|---|---|
| 11 | 0.887 | 0.881 | -0.006 |
| 23 | 0.948 | 0.948 | -0.001 |
| 37 | 0.942 | 0.935 | -0.007 |
| 42 | 0.942 | 0.901 | -0.041 |
| 57 | 0.896 | 0.849 | -0.046 |
| 60 | 0.856 | 0.872 | +0.016 |
| 61 | 0.877 | 0.826 | -0.051 |
| 62 | 0.930 | 0.893 | -0.037 |
| 63 | 0.797 | 0.800 | +0.003 |
| 64 | 0.910 | 0.891 | -0.019 |

Per-role mean alignment (off → on):

| role | off | on | Δ |
|---|---|---|---|
| commander | 1.000 | 0.991 | -0.009 |
| comms | 0.989 | 0.971 | -0.018 |
| fire | 0.892 | 0.878 | -0.014 |
| infrastructure | 0.817 | 0.874 | +0.057 |
| medical | 0.867 | 0.846 | -0.021 |
| rescue | 0.838 | 0.791 | -0.048 |

## Lives (secondary signal)

**n=10 paired seeds** · mean society-untrimmed=97.30 · mean society=96.40

**Δ lives = -0.90** (sd 5.53) · 95% bootstrap CI [-4.40, +2.00] · sign test p=1.0000 (4+/3-/3=)

Observed power to detect this Δ at n=10: **0.07** (α=0.05).

> Verdict (lives Δ): **not distinguishable from noise** — the 95% CI includes 0 (sign test p=1.000). Add seeds (see the power curve) before claiming an effect.

## Per-seed

| seed | society-untrimmed | society | Δ |
|---|---|---|---|
| 11 | 139 | 140 | +1 |
| 23 | 94 | 94 | +0 |
| 37 | 96 | 97 | +1 |
| 42 | 90 | 98 | +8 |
| 57 | 101 | 99 | -2 |
| 60 | 99 | 99 | +0 |
| 61 | 53 | 49 | -4 |
| 62 | 99 | 85 | -14 |
| 63 | 114 | 115 | +1 |
| 64 | 88 | 88 | +0 |

## Power curve

Paired z-approximation; seeds needed for 80% power at α=0.05, given the observed Δ sd=5.53.

| effect (lives) | seeds needed | power at current n |
|---|---|---|
| +2 | 60 | 0.21 |
| +5 | 10 | 0.82 |
| +10 | 3 | 1.00 |
| +15 | 2 | 1.00 |
| +20 | 2 | 1.00 |

