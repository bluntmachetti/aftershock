# D2 — harder world (tight pools) + S2 headroom check (2026-06-15)

Tier-1, driven by the M5 diagnostic. Question: does a harder world create the *priority inversions*
that S2 (partial-grant auction) is built to fix? **Answer: no.** Full write-up: `docs/FIELD-NOTES.md` §15.

`--pools tight` = ambulance 4→3, rescue_crew 3→2. society, 3 seeds (11,42,57) × 2 repeats, 30 ticks.
Raw runs gitignored; `REPEATS.md` / `repeats.json` hold the variance table.

## Auction-loss diagnosis: default world vs tight world (per run)

| metric | default world | tight world |
|---|---|---|
| runs | 9 | 6 |
| lives_saved (mean) | 110.7 | 106.5 |
| **priority_inversion** | **0** | **0** |
| displacement / run | 6.6 | 12.3 |
| pure_shortage / run | 28 | 35 |
| redundant / run | 50 | 57 |
| missions failed / resolved | 4 / 101 | 5 / 64 |
| ICC (world fraction of variance) | 0.79 | 0.65 |

Across both worlds: **133 contested losses, every one legitimate** (loser priority ≤ winner priority),
verified with zero unknown-priority lookups that could hide an inversion.

## Verdict

- **Do not build S2.** The all-or-nothing pathology it targets does not occur in this domain, even
  under engineered scarcity — the auction ranks priority-desc and serves the top mission first, and
  agents don't over-request the quantity needed to let a low-priority remainder-fitter win.
- The real binding constraints are **pure shortage** (pool empty — nothing to partially grant) and
  **redundant bids** (the dominant loss category; a discipline/conformance issue, harmless to lives).
- Tightening pools raised contention but the task stays ~93% resolved; a *lives* effect needs a much
  harsher regime that forces genuine triage, not an auction-policy change.
- This is the Tier-0 harness paying for itself: it killed the program's headline lever before a line of
  it was written.
