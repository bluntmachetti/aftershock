# Harsh-world society-vs-swarm ablation (2026-06-15)

Tier-1 lives question: with the world tuned to genuine triage (you can't save everyone), does the
society's coordination protocol beat the uncoordinated swarm by more than it does on the easy task?
Full write-up: `docs/FIELD-NOTES.md` §16. `ABLATION.md` / `ablation.json` hold the raw harness output.

**Config:** `--pools ambulance=2,rescue_crew=2,fire_engine=2,supply_truck=2,repair_crew=2` (the "harsh"
regime: scripted resolves only ~80% of missions, lives saved ≈ lives lost). society vs swarm, 5 seeds
(11,23,37,42,57), 30 ticks.

## Result

| | swarm | society | Δ |
|---|---|---|---|
| mean lives | 52.6 | 68.8 | **+16.2** |
| per-seed Δ | | | +31, −3, +6, +10, +37 |
| range across seeds | **32–66 (volatile)** | **63–72 (stable)** | |

- 95% bootstrap CI on Δ: **[+3.2, +29.6]** (excludes 0) — **but** sign test **p=0.375** (4+/1−) and
  observed power only **0.57**. **Suggestive, not confirmed.** At n=5 the percentile bootstrap is
  optimistic; the sign test is the guardrail. Power curve: ~11 seeds for +15, ~23 for +10 (80%, α=0.05).
- The defensible finding at n=5 is **robustness**: society's lives floor holds (63–72) while swarm
  collapses on the hard draws (seeds 11/57 → 39/32). First evidence for the previously-untested D5
  "society degrades more gracefully under stress" claim.

## S2 epilogue

At this extreme scarcity priority inversions finally appear — but only **6 of 794 auction losses
(<1%)**, dwarfed by 443 pure-shortage (pool empty). S2's max headroom is ~6 grants → the note-15
verdict (don't build S2) holds even on the hardest world.

## To confirm

Add seeds to the same ablation (`aftershock ablation --control swarm --treatment society --pools ...
--seeds <more> --out runs/d2-harsh-ablation` resumes existing cells) until the CI tightens and the sign
test reaches significance — the power curve says ~11 total.
