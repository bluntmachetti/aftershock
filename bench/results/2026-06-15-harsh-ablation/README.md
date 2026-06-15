# Harsh-world society-vs-swarm ablation (2026-06-15)

Tier-1 lives question: with the world tuned to genuine triage (you can't save everyone), does the
society's coordination protocol beat the uncoordinated swarm on lives? **Answer, properly powered: no.**
Full write-up: `docs/FIELD-NOTES.md` §16. `ABLATION.md` / `ablation.json` hold the raw harness output.

**Config:** `--pools ambulance=2,rescue_crew=2,fire_engine=2,supply_truck=2,repair_crew=2` (the "harsh"
regime: scripted resolves only ~80% of missions, lives saved ≈ lives lost). society vs swarm, 30 ticks.

## The result — and why n matters

| | n=5 (first look) | n=11 (confirmed) |
|---|---|---|
| Δ lives (society − swarm) | **+16.2** | **+4.73** |
| 95% bootstrap CI | [+3.2, +29.6] (excludes 0) | **[−4.0, +14.7] (includes 0)** |
| sign test | p=0.375 (4+/1−) | **p=1.0 (6+/5−)** |
| power | 0.57 | 0.15 |

The +16 at n=5 was a **small-sample false positive**, driven by two lucky seeds (11, 57) where swarm
cratered. Adding 6 seeds surfaced several where swarm *beats* society (5/29/41 → −15/−10/−11) and the
effect collapsed to noise. The "society is more robust" story was the same artifact (society ranges
32–80 at n=11, not the tight 63–72 seen at n=5).

**There is no detectable society-vs-swarm lives advantage on the harsh world.** Power curve at n=11: a
+10 effect would need ~22 seeds; the observed +4.7 would need ~88 — not worth chasing.

## Why this is the headline, not a failure

This is the Tier-0 measurement harness doing its job: it stopped a plausible "coordination is worth +16
lives under triage" claim from being believed/shipped. (Cf. §16.) Caveat it also raises: the published
easy-world "+28 society vs swarm" (FIELD-NOTES §3) deserves the same paired-power re-check.

## Harness lesson

`aftershock ablation`'s auto-verdict keyed on the bootstrap CI and printed "credible improvement" at
n=5 — over-claiming on a small skewed sample. The sign test + power curve were the guardrail. Treat the
auto-verdict as advisory below ~10 seeds; consider hardening it to require sign-test agreement.

## S2 epilogue

At this extreme scarcity priority inversions finally appear — but only 6 of 794 losses (<1%), dwarfed by
443 pure-shortage. The note-15 verdict (don't build S2) holds even on the hardest world.
