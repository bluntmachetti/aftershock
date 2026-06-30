# Aftershock — build blog

The build journey of [**Aftershock**](https://github.com/bluntmachetti/aftershock), a
disaster-response society of Qwen agents, for the Qwen Cloud Global AI Hackathon.

**Headline findings (the claims that survive scrutiny):** written doctrine lifts protocol
conformance — **credible at p=0.031** (n=6, positive on all 11 seeds, no lives cost), and **95%**
on the NYC-Ida demo run — and six cheap Qwen models out-deliver one big model at **~65% better
lives-per-dollar**. The society-vs-swarm lives edge is **suggestive only** (+8.9 at n=15, p=0.118):
an early +28 figure firmed down, and we report the honest number. Full evidence:
[docs/EVIDENCE.md](../docs/EVIDENCE.md).

**📖 Read the rendered blog → <https://bluntmachetti.github.io/aftershock/>**

This folder is the Jekyll source for that site (built to GitHub Pages by
[`.github/workflows/pages.yml`](../.github/workflows/pages.yml)):

- `index.md` — site home
- `_posts/` — blog entries
- `_config.yml` — Jekyll config

## Posts

- **2026-06-30 · Log 010 — [We paid 10× for a bigger model and saved zero extra lives — then watched coordination backfire when nothing was scarce.](_posts/2026-06-30-bigger-model-same-lives-scarcity-is-the-game.md)**
- **2026-06-26 · Log 009 — [We put a number on coordination: the price of anarchy in an agent society.](_posts/2026-06-26-the-price-of-anarchy.md)**
- **2026-06-25 · Log 008 — [We firmed our headline until it broke. Here's the one that didn't.](_posts/2026-06-25-the-headline-that-survives.md)**
- **2026-06-22 · Log 007 — [The protocol was 'worth 28 lives.' At fifteen seeds it's worth a caveat.](_posts/2026-06-22-the-protocol-was-worth-28-lives-now-its-worth-a-caveat.md)**
- **2026-06-19 · Log 006 — [We built a proof pack so judges could check our numbers. Auditing it ourselves found a wrong p-value, a fabricated source, and a cherry-picked run.](_posts/2026-06-19-we-proof-checked-our-proof-pack.md)**
- **2026-06-16 · Log 005 — [The fix that would have only fooled the scoreboard — and the one tuning that actually paid.](_posts/2026-06-16-the-fix-that-would-have-only-fooled-the-scoreboard.md)**
- **2026-06-15 · Log 004 — [Build the ruler first. It killed our biggest feature — and a +16-life win that wasn't real.](_posts/2026-06-15-build-the-ruler-first.md)**
- **2026-06-15 · Log 003 — [We drew the agent auction on the map. A review caught it pointing at the wrong district.](_posts/2026-06-15-we-drew-the-auction-on-the-map.md)**
- **2026-06-14 · Log 002 — [We added native function calling. The benchmark told us to turn it off.](_posts/2026-06-14-we-added-function-calling-the-benchmark-told-us-to-turn-it-off.md)**
- **2026-06-12 · Log 001 — [When does a society of small Qwen models beat one big model? Building Aftershock.](_posts/2026-06-12-building-an-agent-society-on-qwen-cloud.md)**

Live demo: <https://aftershock.redoubtlabs.dev> · Code: <https://github.com/bluntmachetti/aftershock>
