# S1 — infra prompt fix vs baseline (paired by seed)

Baseline = doctrine-ablation society (doctrine ON, **old** infra prompt). Fix = society (doctrine ON, **new** infra prompt). Same 5 seeds, 60 ticks, default pools, JSON mode — the ONLY difference is `roles/infrastructure.yaml`. Each side is one LLM run/seed (DashScope is non-deterministic), so conformance (low-variance) is the primary read; lives is the no-regression gate.

## Infra role conformance + team alignment + lives

| seed | infra base | infra fix | Δ | TA base | TA fix | lives base | lives fix | Δ lives |
|---|---|---|---|---|---|---|---|---|
| 11 | 0.679 | 0.867 | +0.188 | 0.837 | 0.919 | 140 | 136 | -4 |
| 23 | 0.632 | 0.867 | +0.235 | 0.810 | 0.913 | 86 | 94 | +8 |
| 37 | 0.682 | 0.844 | +0.163 | 0.895 | 0.919 | 93 | 92 | -1 |
| 42 | 0.800 | 0.921 | +0.121 | 0.872 | 0.933 | 95 | 95 | +0 |
| 57 | 0.545 | 0.818 | +0.273 | 0.843 | 0.894 | 107 | 101 | -6 |
| **mean** | **0.667** | **0.863** | **+0.196** | 0.852 | 0.916 | 104.2 | 103.6 | **-0.6** |

- **Infra conformance Δ = +0.196**, all 5 seeds positive (sign test p=0.0625).
- **Team alignment Δ = +0.064** (5/5 positive).
- **Lives Δ = -0.60** — per-seed [-4.0, 8.0, -1.0, 0.0, -6.0], sign test p=0.6250: no detectable change (gate: no regression).

## Per-rule infra conformance (summed over 5 seeds)

| rule | meaning | base | fix | base viol | fix viol |
|---|---|---|---|---|---|
| T2 | request only what's needed | 0.973 (2/75) | 1.000 (0/110) | 2 | 0 |
| T3 | urgency honesty (>8 only if sev≥4/dl≤4) | 0.350 (13/20) | 1.000 (0/14) | 13 | 0 |
| T5 | never resubmit a rejected decision | 0.000 (17/17) | 0.000 (2/2) | 17 | 2 |
| T6 | don't duplicate a peer | 0.000 (1/1) | — (0/0) | 1 | 0 |
| I1 | repair only blocked districts w/ crew | 0.627 (28/75) | 0.560 (22/50) | 28 | 22 |
| I2 | clear open-mission districts first | — (0/0) | — (0/0) | 0 | 0 |

**Read:** T3 (urgency) fully fixed (0.350→1.000). T5 rate still 0 but absolute violations collapsed 17→2 — the upstream fix produced far fewer rejected repairs to resubmit. **I1 stayed sticky** (0.627→0.560 by rate; 28→22 absolute): the model still attempts some invalid repairs even when told exactly which observation fields (BLOCKED line, POOLS repair_crew) to check. Net infra conformance +0.196 at no lives cost — a partial, honest win, driven by urgency calibration, not precondition gating.
