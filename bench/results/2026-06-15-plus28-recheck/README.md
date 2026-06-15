# Re-check of the published "+28 society vs swarm" (2026-06-15)

A **free** integrity check prompted by the harsh-world null result (note 16): apply the new paired
harness (sign test / bootstrap CI / power) to the *already-published* n=5 data that produced the
headline "a coordination protocol is worth 28 lives" (FIELD-NOTES §3). No new runs — re-analysis of
`bench/results/2026-06-11/results.json` (60-tick default world). Full write-up: `docs/FIELD-NOTES.md` §17.

## Result

| seed | swarm | society | Δ |
|---|---|---|---|
| 11 | 52 | 140 | +88 |
| 23 | 79 | 86 | +7 |
| 37 | 81 | 81 | +0 |
| 42 | 72 | 98 | +26 |
| 57 | 94 | 111 | +17 |

**Δ = +27.6** (sd 35.2) · 95% bootstrap CI [+6.2, +58.0] (excludes 0) · sign test **p=0.125** (4+/0−/1=)
· power **0.42**.

## Verdict: direction solid, magnitude soft

- **Directionally robust** — society ≥ swarm on *all five* seeds (4 strictly positive, 1 tie, 0
  negative). Unlike the harsh-world +16 (note 16), which went both ways and collapsed to noise at n=11,
  this gap is real in sign. **Note 3's qualitative claim survives.**
- **Magnitude underpowered** — not sign-test-significant at n=5 (the seed-37 tie drops effective n to
  4), power 0.42, and the "+28" is leveraged by one seed (11 = +88; the other four average +12.5). A
  tight CI on the number would need ~25 seeds.

## Actions

- When the "+28 lives" figure is *quoted* (README, Devpost), caveat it as an n=5 paired mean with a wide
  CI — or add seeds to firm the number.
- Harness bug (2nd sighting, cf. note 16): `aftershock ablation`'s auto-verdict printed "credible
  improvement" on the CI alone while the sign test was non-significant. Harden it to require sign-test
  agreement below ~10 seeds.
