# Ablation — doctrine on/off (society, paired)

Δ = **society (doctrine on)** − **society-nodoctrine (doctrine off)**, everything else held constant (world seed, tools, pools). A positive Δ means doctrine adds the metric.

## Conformance (primary signal — deterministic)

**Team alignment: 0.696 (off) → 0.852 (on)** · Δ = +0.156 · sign test p=0.0625 · n=5

| seed | off | on | Δ |
|---|---|---|---|
| 11 | 0.688 | 0.837 | +0.150 |
| 23 | 0.736 | 0.810 | +0.073 |
| 37 | 0.676 | 0.895 | +0.220 |
| 42 | 0.676 | 0.872 | +0.196 |
| 57 | 0.704 | 0.843 | +0.139 |

Per-role mean alignment (off → on):

| role | off | on | Δ |
|---|---|---|---|
| commander | 0.952 | 0.940 | -0.013 |
| comms | 0.773 | 0.992 | +0.219 |
| fire | 0.772 | 0.875 | +0.103 |
| infrastructure | 0.574 | 0.667 | +0.094 |
| medical | 0.733 | 0.894 | +0.160 |
| rescue | 0.655 | 0.824 | +0.169 |

## Lives (secondary signal)

**n=5 paired seeds** · mean society-nodoctrine=100.40 · mean society=104.20

**Δ lives = +3.80** (sd 5.59) · 95% bootstrap CI [+0.20, +8.60] · sign test p=0.3750 (4+/1-/0=)

Observed power to detect this Δ at n=5: **0.33** (α=0.05).

> Verdict (lives Δ): **suggestive but unconfirmed** — the 95% CI excludes 0, but the sign test is not significant (p=0.375 ≥ 0.05) and power is 0.33. The percentile bootstrap is optimistic on small, skewed samples; treat this as a lead and add seeds (see the power curve) until the sign test agrees.

## Per-seed

| seed | society-nodoctrine | society | Δ |
|---|---|---|---|
| 11 | 127 | 140 | +13 |
| 23 | 85 | 86 | +1 |
| 37 | 94 | 93 | -1 |
| 42 | 90 | 95 | +5 |
| 57 | 106 | 107 | +1 |

## Power curve

Paired z-approximation; seeds needed for 80% power at α=0.05, given the observed Δ sd=5.59.

| effect (lives) | seeds needed | power at current n |
|---|---|---|
| +2 | 62 | 0.12 |
| +5 | 10 | 0.52 |
| +10 | 3 | 0.98 |
| +15 | 2 | 1.00 |
| +20 | 2 | 1.00 |

