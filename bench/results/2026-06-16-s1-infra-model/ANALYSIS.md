# §20 — infra model bump (flash → plus), model isolated

Baseline = `s1-infra-fix` (§19 prompt, infra=**flash**). Treatment = same prompt, infra=**plus**. Same 5 seeds/60t/doctrine-on — ONLY `roles/infrastructure.yaml` `model:` differs. Isolates the model.

| seed | infra flash | infra plus | Δ | lives F | lives P | cost F | cost P |
|---|---|---|---|---|---|---|---|
| 11 | 0.867 | 1.000 | +0.133 | 136 | 132 | 0.0361 | 0.0499 |
| 23 | 0.867 | 1.000 | +0.133 | 94 | 92 | 0.0402 | 0.0559 |
| 37 | 0.844 | 0.957 | +0.112 | 92 | 95 | 0.0466 | 0.0576 |
| 42 | 0.921 | 0.974 | +0.053 | 95 | 95 | 0.0411 | 0.0577 |
| 57 | 0.818 | 1.000 | +0.182 | 101 | 105 | 0.0415 | 0.0510 |
| **mean** | **0.863** | **0.986** | **+0.123** | 103.6 | 103.8 | 0.0411 | 0.0544 |

- **Infra conformance Δ = +0.123**, 5/5 positive (sign p=0.0625).
- **Lives Δ = +0.20** (sign p=1.0000) — flat, I1 is outcome-neutral.
- **Cost 0.0411 → 0.0544 (+33%)** → **lives-per-$ 2522 → 1907 (-24%)**.

## Per-rule infra (summed)

| rule | flash | plus |
|---|---|---|
| T3 urgency honesty | 1.000 (0/14) | 1.000 (0/17) |
| T5 no resubmit | 0.000 (2/2) | — |
| I1 repair preconditions | 0.560 (22/50) | 0.957 (1/23) |

**Read:** the plus model fixes the rule prompting couldn't — **I1 0.560 → 0.957**. So infra's stickiness (§19) was a *model-capability* floor, not a prompt problem: flash won't reliably gate repair_road on (blocked ∩ crew); plus does. T5 falls to 0/0 (no invalid repairs ⇒ nothing to resubmit). **But lives are flat and cost is +33% — lives-per-$ drops ~21%.** Paying a third more to perfect an outcome-neutral discipline metric trades away the society's headline cost-efficiency. **Decision: ship as an opt-in operating mode, not the default** — `--role-model infrastructure=qwen3.5-plus` (a general per-role override). Default stays flash (headline lives-per-$ intact); flip to plus when discipline matters more than cost. The capability-floor finding is the durable result; reproducible via the flag (these cells were produced with the equivalent hardcoded config).
