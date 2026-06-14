# Follow-ups

Short list of known project tasks that are not part of the current deployment path.

## NEXT SESSION — Mission Control observatory redesign (submission polish)

The next tranche. **Full plan + decision + porting sequence:** `.omc/plans/mission-control-redesign.md`
(local scratch). **Prototype + rendered style screenshots:** `.omc/mission-control-prototype/` (local scratch).

- **Decision (CCG-synthesized — Claude + Codex + Gemini):** redesign the observatory **Map tab** into
  the "Mission Control / EOC" command-center shell, with the **③ Tiles** map (geographic tiles +
  kind-iconed mission pins) **+ a contention overlay** ported from the ① Sector style (dashed
  "RPR contested" links / pin halos on contesting districts during auction events). **Committed —
  not switchable.** Same dark design language as the new blog (`blog/assets/css/blog.css`).
- **Scope (MVP):** Map tab only; one production `MissionControlMap` wired to **live** run data; one
  contested-resource overlay; polished NYC Ida path. Frontend-only → zero engine/determinism risk.
- **Invariants to preserve:** `web/src/lib/palette.ts` single hex-source (society=cyan, baseline=amber);
  `RealityStrip` + REAL/MAPPED/INFERRED/SYNTHETIC provenance honesty; `WorldState`/`MissionState`
  shapes; scrubber/tabs semantics; `vitest` green; live FastAPI data (not just the canned demo).
- **OPEN QUESTIONS — confirm with Kenny before building (asked, not yet answered):**
  1. Confirm **Tiles + contention overlay, committed** (vs straight ① Sector / vs keep switchable).
  2. **Map tab only** (recommended) vs full-observatory reskin before July 9.
  3. Keep the real-Ida story **on the Map** (with provenance) vs move it to **Compare/Bench**.
- **Execution model when approved:** fold the contract into `docs/DESIGN.md` §"Mission Control map"
  first → disjoint-surface workflow (shell / tile-map / overlay / rails-restyle) → adversarial review
  → verify (tsc/vitest/build + 1080p) → staging→prod promotion gate.

## Shipped this session (2026-06-14)

- **Function calling (PRs #1 + #2, merged + deployed to k12 staging + Alicloud prod):** native Qwen
  function calling is now an opt-in (`--society-tools` / `build_llm_agents(force_tools=True)`); the
  society arm **default is JSON-contract mode** (cost-optimal — restores the "matches solo cheaper"
  headline). Benchmark showed tool mode ~2× cost / ~2.5× latency for statistically-equal lives
  (structural per-call schema overhead). Ablation published: `bench/results/2026-06-13-tool-ablation/`;
  finding in `docs/FIELD-NOTES.md` §12; README "Native Qwen function calling (measured ablation)".
- **Build blog reskin (live):** dropped minima for the custom "Field Log" mission-control theme
  (`blog/_layouts/*`, `blog/assets/css/blog.css`); markdown posts render natively; new post
  "We added native function calling. The benchmark told us to turn it off." Author byline set to
  **Kenny Ademolu** (GitHub/Pages handle stays bluntmachetti). Live: <https://bluntmachetti.github.io/aftershock/>.

## Observatory

- Fix Compare-tab provenance: the header `DATA` chip is currently driven by the single Map
  timeline, so Compare can show no chip or stale Map-run provenance while the Compare view is
  showing a shared real scenario.
- Decide whether scenario CLI run ids should include scenario identity. Current ids remain
  `seed{N}-{arm}`, so scenario runs can overwrite synthetic runs with the same seed/arm.
- Refresh stale UI copy: `LiveTab` says its synthetic tick default matches the server default even
  though the UI passes 60 explicitly while the omitted server default is 30.

## Deferred Scope

- `tur-2023` scenario pack remains deferred.
