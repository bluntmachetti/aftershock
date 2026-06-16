# §21 — contract trim A/B (trimmed vs full contract, paired by seed)

Baseline = `s1-infra-fix` society cells (full contract, §19 infra prompt, flash, doctrine on). Treatment = same config, **trimmed contract only** (compact JSON skeleton + deduped Hard Rules + compressed proposal-doc descriptions). Same 5 seeds / 60 ticks — only `contract.py` + `PROPOSAL_DOCS` differ.

| seed | cost full | cost trim | Δ% | lives f | lives t | TA f | TA t | acts f | acts t |
|---|---|---|---|---|---|---|---|---|---|
| 11 | 0.0361 | 0.0332 | -7.9 | 136 | 140 | 0.919 | 0.810 | 217 | 205 |
| 23 | 0.0402 | 0.0341 | -15.1 | 94 | 94 | 0.913 | 0.910 | 230 | 225 |
| 37 | 0.0466 | 0.0391 | -16.1 | 92 | 93 | 0.919 | 0.947 | 254 | 235 |
| 42 | 0.0411 | 0.0363 | -11.6 | 95 | 101 | 0.933 | 0.877 | 233 | 235 |
| 57 | 0.0415 | 0.0340 | -18.2 | 101 | 110 | 0.894 | 0.851 | 224 | 220 |
| **mean** | **0.0411** | **0.0353** | **-14.0** | 103.6 | 107.6 | 0.916 | 0.879 | 232 | 224 |

- **Cost 0.0411 → 0.0353 (-14.0%)** — prompt tokens -11.2% (deterministic from the −106-tok/-11% prefix trim).
- **Lives-per-$ 2522 → 3046 (+21%)** — the headline metric.
- **Lives 103.6 → 107.6** (Δ +4.0, sign p=0.1250) — no regression.
- **Conformance (team_align) 0.916 → 0.879** (Δ -0.037, sign p=0.3750) — NOT significant; within the §18–20 historical band (~0.85–0.92). Watch-item (likely the proposal-doc compression).
- **Actions emitted (parse-success proxy) 232 → 224** (-3.3%) — no parse collapse.

**Verdict: KEEP.** A credible, largely-deterministic −14% cost / +21% lives-per-$ at no credible regression in lives or conformance (both deltas sign-test non-significant). The conformance dip is a noted watch-item, not a credible effect. README/SUBMISSION cost numbers can be refreshed downward in a later pass.
