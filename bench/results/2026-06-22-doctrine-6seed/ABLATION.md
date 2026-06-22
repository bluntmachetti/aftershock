# Ablation — doctrine on/off (society, paired)

Δ = **society (doctrine on)** − **society-nodoctrine (doctrine off)**, everything else held constant (world seed, tools, pools). A positive Δ means doctrine adds the metric.

## Conformance (primary signal — deterministic)

**Team alignment: 0.763 (off) → 0.888 (on)** · Δ = +0.125 · sign test p=0.0312 · n=6

> Verdict (conformance Δ): **credible improvement** — the 95% CI excludes 0 *and* the sign test is significant (p=0.031).

| seed | off | on | Δ |
|---|---|---|---|
| 11 | 0.711 | 0.892 | +0.181 |
| 23 | 0.738 | 0.929 | +0.190 |
| 37 | 0.771 | 0.914 | +0.143 |
| 42 | 0.785 | 0.864 | +0.079 |
| 57 | 0.772 | 0.864 | +0.092 |
| 73 | 0.802 | 0.868 | +0.065 |

Per-role mean alignment (off → on):

| role | off | on | Δ |
|---|---|---|---|
| commander | 0.953 | 0.960 | +0.008 |
| comms | 0.791 | 0.976 | +0.185 |
| fire | 0.786 | 0.873 | +0.086 |
| infrastructure | 0.727 | 0.896 | +0.169 |
| medical | 0.714 | 0.838 | +0.124 |
| rescue | 0.770 | 0.847 | +0.077 |

## Lives (secondary signal)

**n=6 paired seeds** · mean society-nodoctrine=103.67 · mean society=109.67

**Δ lives = +6.00** (sd 9.76) · 95% bootstrap CI [-0.33, +13.67] · sign test p=0.3750 (4+/1-/1=)

Observed power to detect this Δ at n=6: **0.33** (α=0.05).

> Verdict (lives Δ): **not distinguishable from noise** — the 95% CI includes 0 (sign test p=0.375). Add seeds (see the power curve) before claiming an effect.

## Per-seed

| seed | society-nodoctrine | society | Δ |
|---|---|---|---|
| 11 | 134 | 139 | +5 |
| 23 | 83 | 94 | +11 |
| 37 | 96 | 92 | -4 |
| 42 | 96 | 97 | +1 |
| 57 | 106 | 106 | +0 |
| 73 | 107 | 130 | +23 |

## Power curve

Paired z-approximation; seeds needed for 80% power at α=0.05, given the observed Δ sd=9.76.

| effect (lives) | seeds needed | power at current n |
|---|---|---|
| +2 | 187 | 0.07 |
| +5 | 30 | 0.24 |
| +10 | 8 | 0.71 |
| +15 | 4 | 0.96 |
| +20 | 2 | 1.00 |

