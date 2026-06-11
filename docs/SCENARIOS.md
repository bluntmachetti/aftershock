# Real-data scenario packs (task #4 — engine/data + observatory)

Run the existing agent society on scenarios compiled from **real open incident data**, with
real response latency as the on-screen baseline. Distinct from task #3 (arm-vs-arm compare,
same synthetic seed, merged as `8047d54`): this is **sim-vs-reality** — real demand arrival,
real first-on-scene times, simulated outcomes. Research provenance: 14 datasets
adversarially verified on 2026-06-11 (live API fetches, exact row counts); full report and
evidence in `.omc/research/open-datasets-compare-mode.md`. This spec was itself reviewed
against the post-merge codebase (3-lens pass, 27 findings applied).

**Fold order (pinned):** fold this section into `docs/DESIGN.md` as a standalone docs-only
commit *before* Phase S4 implementation starts, deleting this file in the same commit — one
spec copy at all times. Commit this file first so engine commits can reference it.

## Invariants (non-negotiable)

1. **No engine vocabulary change.** `MissionKind`, `ResourceKind`, district ids, dynamics,
   scoring are untouched. Real incident types are mapped onto the existing four mission
   kinds *in the compiler*, and the mapping is published as provenance. (The all-hazards
   vocabulary refactor is explicitly deferred — see "Deferred" at the end.)
2. **Determinism preserved.** The compiler runs **offline** and emits a versioned JSON
   artifact committed to the repo. The engine never touches the network. Same pack + same
   seed + same decisions = same outcome, byte for byte — identical guarantee to today,
   because a scenario is already just a precomputed `timeline`. `aftershock verify` must
   pass with `--scenario`.
3. **Bench fairness.** Scenario packs are demo/observatory surfaces only. `aftershock bench`
   and `bench/default.yaml` refuse scenario packs; the published 4-arm results stay
   synthetic-seed only. (Same spirit as the lessons-only-for-society guard in `build_arm`.)
4. **Honesty labels are part of the contract, not polish.** Every scenario surface carries
   the field-provenance markers (REAL / MAPPED / INFERRED / SYNTHETIC) and a caveat line
   drawn from a fixed approved set, **chosen per pack so it never claims a category the
   pack's `field_provenance` does not support**:
   - dispatch packs (SF, NYC): *"Demand: real · Latency baseline: real · Lives & outcomes:
     simulated model."*
   - hazard-only packs (Türkiye): *"Hazard timing: real · Demand & outcomes: simulated
     model."*
   Never claim agents are compared against real responders' *outcomes*.
5. **Sequencing.** Originally Phase S4 was gated on task #3; that gate is **satisfied by
   commit `8047d54`** — all phases S1–S6 are now parallel-startable. S1–S3 touch only
   Python/`Dockerfile`/`scenarios/`; S4 touches `web/src/**` per the surface table below
   (the table, not this list, is the authoritative file-ownership map).

## The scenario pack (`scenarios/<id>/scenario.json`)

One self-contained JSON artifact per scenario, validated by pydantic models in
`town/scenario.py`. Canonical example (`nyc-ida-2021`, abridged where marked):

```jsonc
{
  "format_version": 1,
  "id": "nyc-ida-2021",                      // ^[a-z0-9][a-z0-9-]*$, dir name == id
  "name": "Hurricane Ida — NYC, night of 2021-09-01",
  "hazard": "hurricane_flood",               // free label: earthquake|hurricane_flood|storm|routine
  "adapter": "nyc",                          // which compiler adapter produced this pack
  "compiler_version": "<git rev of the compiler at emit time>",
  "config_sha256": "<sha256 of the adapter config YAML>",
  "tick_minutes": 12,                        // real minutes per tick (display + reference math)
  "window": { "start": "2021-09-01T18:00:00-04:00", "end": "2021-09-02T06:00:00-04:00" },

  // Canonical district ids are POSITIONAL SLOTS — the SVG map layout keys off them.
  // Packs override display names; `members` documents the real zoning.
  "districts": [
    { "id": "old_town",          "name": "Manhattan",      "members": ["M1", "M2"] },
    { "id": "harbor",            "name": "Staten Island",  "members": ["S1", "S2"] },
    { "id": "hospital_district", "name": "Bronx",          "members": ["B1", "B2"] },
    { "id": "market",            "name": "Brooklyn West",  "members": ["K1", "K2"] },
    { "id": "residential_north", "name": "Queens",         "members": ["Q1", "Q2"] },
    { "id": "industrial",        "name": "Brooklyn East",  "members": ["K3", "K4"] }
  ],

  "pools": {                                  // feeds ResourcePool(kind, total, available)
    // "observed" is reserved for pools the data actually counts. NYC EMS (76xm-jjuj) has
    // NO unit identity/counts — only the Fire dataset's apparatus counts are observable.
    "ambulance":   { "size": 4, "basis": "calibrated", "note": "no EMS unit counts in 76xm-jjuj; calibrated against held_indicator saturation" },
    "rescue_crew": { "size": 3, "basis": "calibrated", "note": "no real analog; synthetic default" },
    "fire_engine": { "size": 3, "basis": "observed",   "note": "engines_assigned p75 in window (8m42-w767)" },
    "repair_crew": { "size": 3, "basis": "calibrated", "note": "no real analog" },
    "supply_truck":{ "size": 3, "basis": "calibrated", "note": "no real analog" }
  },

  "timeline": [                               // exact TimelineEntry shape, sorted by tick
    // tick = floor((received − window.start) / tick_minutes): 21:04:11 → tick 15
    { "tick": 15, "kind": "mission", "mission_kind": "medical_surge",
      "district_id": "residential_north", "severity": 4, "lives_at_risk": 16 },
    { "tick": 17, "kind": "blockage", "district_id": "residential_north" }
  ],

  "field_provenance": {                       // drives the REAL/MAPPED/INFERRED/SYNTHETIC badges
    "tick": "real", "district_id": "real", "mission_kind": "mapped",
    "severity": "mapped", "lives_at_risk": "inferred", "blockage": "synthetic"
  },

  "mapping": {                                // the semantic decisions, published verbatim
    "version": "nyc-v1",
    "mission_kind": { "EMS severity 1-3 medical": "medical_surge",
                      "Fire incident_classification Structural Fires": "fire",
                      "NonStructural/utility": "infra_repair",
                      "rescue classifications + water rescue": "collapse_rescue" },
    // generic NYC table; this pack's sampling.filter narrows the domain to codes 1-3
    "severity_rule": "EMS code 1-2→5, 3→4 (codes 4-8 excluded by filter); Fire by units-assigned quantile",
    "lives_rule": "LIVES[kind][severity] lookup table vNYC-1 (inferred field)"
  },

  "sampling": {                               // no silent caps — say what was dropped
    "method": "stratified by (tick-bucket, mission_kind)",
    "sample_seed": 4636,                      // compiler-only RNG; recorded, not engine rng_for
    "kept": 16, "total": "<post-filter incident count, computed by the adapter>",
    "filter": "severity codes 1-3 OR Fire structural/rescue; boroughs only (CW/X1 dropped)"
  },

  "source": [                                 // one entry per upstream dataset
    { "dataset": "EMS Incident Dispatch Data", "provider": "FDNY via NYC Open Data",
      "dataset_id": "76xm-jjuj",
      "query_url": "https://data.cityofnewyork.us/resource/76xm-jjuj.json?$where=...",
      "fetched_at": "2026-06-11", "rows_fetched": 2003,
      "license": "NYC Open Data terms (no formal license)", "license_url": "https://opendata.cityofnewyork.us/overview/",
      "attribution": "FDNY via NYC Open Data" },
    { "dataset": "Fire Incident Dispatch Data", "provider": "FDNY via NYC Open Data",
      "dataset_id": "8m42-w767",
      "query_url": "https://data.cityofnewyork.us/resource/8m42-w767.json?$where=...",
      "fetched_at": "2026-06-11", "rows_fetched": 2022,
      "license": "NYC Open Data terms (no formal license)", "license_url": "https://opendata.cityofnewyork.us/overview/",
      "attribution": "FDNY via NYC Open Data" }
  ],

  "reference": {                              // the reality baseline (only what the data proves)
    "missions": {                             // keyed by TIMELINE INDEX of the mission entry;
      "0": { "received": "2021-09-01T21:04:11-04:00",   // see "index ↔ mission id" below
             "first_on_scene": "2021-09-01T21:19:53-04:00",
             "latency_s": 942 }               // null first_on_scene/latency when no unit arrived
    },
    "aggregates": {                           // computed by the adapter over the FULL filtered
      "mean_latency_s": 948,                  // window (not the sample); mean AND median both
      "median_latency_s": "<computed>",       // emitted — verified Ida figures are MEANS (948 s)
      "held_rate": 0.165,
      "baseline_mean_latency_s": "<computed>", "baseline_median_latency_s": "<computed>",
      "baseline_held_rate": "<computed>",
      "baseline_note": "<adapter-computed calm window, stated explicitly, e.g. 2021-08-18/19>"
      // The verified 538 s / 6.9 % normal-period figures are from the 2012-10-15/16 window
      // (pre-Sandy baseline) — the NYC adapter must compute an Ida-adjacent baseline rather
      // than reuse them, and must name the window it used.
    }
  }
}
```

**Index ↔ mission id.** Engine mission ids (`m1..`) come from a single shared counter, and
live injections consume it *before* that tick's timeline spawns
(`town/events.py:217` drains injections first; ids assigned at `events.py:244` and
`events.py:288`). So timeline index → mission id is **not** reconstructible by counting.
The UI maps them by walking `mission_spawned` events in record order and **skipping events
whose payload has `injected: true`** (flag already emitted, `events.py:274`); the nth
non-injected spawn corresponds to the nth mission entry in `timeline`. This works with
injections active and is the normative mechanism for `reference.missions` lookups.

Loader validation (pydantic, hard errors): district ids exactly the canonical six; pool kinds
exactly the five `ResourceKind`s, sizes 1–12; mission kinds in `MissionKind`; severity 1–5;
`lives_at_risk` 1–64; timeline sorted by tick; **last mission tick + max(`DEADLINE_TICKS`)
(= 16) ≤ 120**, so every mission can resolve or fail within the live tick cap (the engine
loop is `while tick < max_ticks`, `kernel/engine.py:127`, and `_MAX_TICKS_LIVE = 120` — the
highest executed tick is 119); reference mission keys must index mission entries. The pack's
SHA-256 (`pack_digest`) is computed at load and stamped into the run manifest.

## The compiler (`src/aftershock/data/` — NEW package)

Offline CLI pipeline, one adapter per upstream dataset. Never imported by the engine.

```
aftershock compile-scenario --adapter sf --config src/aftershock/data/configs/sf-routine.yaml \
    --out scenarios/sf-routine-2026
```

Stages (shared skeleton, per the verified research mappings):

1. **Extract** — adapter-specific fetch (SODA query, CSV slice) → raw rows cached to
   `scenarios/<id>/raw/` (gitignored — add `scenarios/*/raw/` to `.gitignore`; for AFAD this
   is also a license requirement, see Packs). Fetch metadata (`fetched_at`, `rows_fetched`,
   `query_url`) is recorded **once, at extract time**, into `raw/manifest.json`; Emit copies
   it verbatim. Tests use small committed fixture slices under `tests/fixtures/data/` —
   **tests never touch the network**.
2. **Aggregate** — group unit rows to incidents; compute per-incident `received`,
   `first_on_scene = MIN(on_scene over units, nulls dropped)`, unit roster, zone, type,
   priority fields. Adapter-specific gotchas live here and are unit-tested (SF: drop
   battalion junk B99/AMB/XXX, use `original_priority` not `final_priority`; NYC: filter by
   `valid_*_indc`, never use Fire `highest_alarm_level`; LFB: UTC-vs-BST skew).
3. **Discretize** — windows ÷ `tick_minutes` → ticks; zone→district lookup from config;
   type→kind mapping table; severity rule; `LIVES[kind][severity]` lookup; blockage synthesis
   rule (or none); **deterministic stratified sampling** down to `target_missions`
   (default 16) using `random.Random(sample_seed)` — compiler-only randomness, recorded in
   the pack. Pools from observed unit roster scaled by the sampling ratio, clamped [2, 6],
   each marked `observed`/`calibrated` (`observed` only where the dataset actually counts
   units). Reference aggregates (mean **and** median, plus the named baseline window) are
   computed over the **full filtered window**, not the sample.
4. **Emit** — `scenario.json` written with sorted keys, stamped with `adapter`,
   `compiler_version`, and `config_sha256`, plus a human `README.md` per pack stating
   source, license, attribution, and the pack's caveat line.

**Byte-identity scope:** recompiling from identical `raw/` input + identical config hash is
byte-identical (golden test). Re-*fetching* is never byte-stable — upstream datasets refresh
(SF daily, NYC ~quarterly) — which is exactly why fetch metadata is frozen at extract time.

Sampling rationale: a real 12 h city window is 300–2,000 incidents; the society + pool model
is tuned for ~10–20 missions. Downscaling is unavoidable — so it is stratified (preserves the
arrival-time distribution and kind mix), seeded, and published (`kept`/`total`) rather than
silent.

## Engine integration (single touchpoint)

- **`town/scenario.py` (NEW):** pydantic models + `load_scenario(path) -> ScenarioPack` +
  `town_from_scenario(pack, seed) -> TownState` (districts with display names from the pack,
  pools from the pack, timeline verbatim, counters zeroed). `state.py` is not modified.
- **`src/aftershock/town/arms.py`:** `build_arm(arm, seed, provider, lessons=None,
  scenario: ScenarioPack | None = None)`; `world = town_from_scenario(scenario, seed) if
  scenario else new_town(seed)` (today's `town/arms.py:101`). `seed` keeps its meaning for
  every other `rng_for` stream and for replay identity.
- **`cli.py`:** `aftershock run --scenario <id>` (resolves `scenarios/<id>/scenario.json`);
  with `--scenario`, `--ticks` becomes optional and defaults to
  `min(last timeline tick + 20, 120)` (deadline headroom: max deadline is 16 ticks) — an
  explicit under-budget `--ticks` is a hard error, not silent truncation. Same for
  `aftershock verify --scenario <id>` (two-run digest check). `bench` rejects `--scenario`
  (invariant 3).
- **Run manifest** (`run.json`) gains:
  `"scenario": {id, name, hazard, tick_minutes, pack_digest, config_sha256, source,
  field_provenance, caveat_line, reference_aggregates}` — enough for the UI to render
  provenance without a second fetch. Absent for synthetic runs (UI treats absence as
  `SYN·QUAKE`).

Mission deadlines remain the `DEADLINE_TICKS` model constants — they are part of the outcome
model, not the data (at 12 min/tick, medical_surge's 8-tick deadline = 96 min, defensible).
Live injection (`/api/live/inject`) keeps working in scenario runs; injected events already
carry `injected: true` provenance, and the index↔id mapping above is injection-safe.

## Web API (`web.py` — additive)

- **`GET /api/scenarios`** — scans `scenarios/` (ids validated against the **pack-id regex**
  `^[a-z0-9][a-z0-9-]*$` — a strict subset of the run-id charset, same traversal-guard
  pattern as `_validate_run_id`), returns `[{id, name, hazard, tick_minutes, window,
  missions: len, sampling: {kept, total}, source: [{dataset, provider, license,
  attribution}]}]`. **Deliberately ungated**: like every existing GET (including
  `/api/runs`), it is public even when `OBSERVATORY_TOKEN` is set — only POST endpoints are
  token-gated. Packs contain published open data + our own config; nothing sensitive.
- **`GET /api/scenarios/{id}`** — full pack including `reference` (the RealityStrip data
  source for replays).
- **`POST /api/live`** — `LiveRunRequest` gains `scenario: str | None = None`, and `ticks`
  changes from `int = 30` to `int | None = None` so the server can tell "omitted" from "30":
  default 30 for synthetic, `min(last timeline tick + 20, 120)` for scenario runs. Unknown
  scenario id → 404. The pack loads server-side and passes to `build_arm`. Token gate
  unchanged. `_run_live`'s manifest gains the scenario block.
- **`GET /api/runs`** — `_scan_runs` passes through a compact
  `scenario: {id, name, hazard} | null` per run. `GET /api/runs/{id}` returns the full block.
- **Deployment:** `scenarios/` is committed and `COPY`d in the Dockerfile next to the app;
  no runtime network or new env vars.

## Web UI (Phase S4 — unblocked, task #3 merged as `8047d54`)

Honors the task #3 style contract (text floor, hierarchy by weight, effects restraint) and
its token system; all colors via `palette.ts`. This table is the authoritative ownership map.

| Surface | Owns | What it does |
|---|---|---|
| **Trigger** | `LiveTab.tsx` (+`api.ts` additive) | SCENARIO select above the existing arm/seed/ticks controls: `SYNTHETIC QUAKE (seed N)` default + one entry per `/api/scenarios` (`IDA · NYC 2021 · 16 missions`). Seed still seeds the agents; ticks pre-fills from the pack. POST includes `scenario`. Token flow unchanged. |
| **Badges** | `RunPicker.tsx`, `palette.ts` (additive), `types.ts`, `CompareTab.tsx` (additive) | Hazard chip per run row and run header: `SYN·QUAKE` (dim) vs `REAL·IDA NYC` (signal color from a new `palette.ts` hazard map). There is **no shared run-header component** — `CompareTab.tsx` renders its own per-side header inside its local `SidePanel` (`CompareTab.tsx:388–400`), so the chip is added there explicitly (or extract a shared `RunHeader` first and consume it from both — implementer's choice, both in scope). |
| **Provenance** | `ProvenancePanel.tsx` (NEW) | A `DATA` chip (mounted by Integration) opens a panel: source table (dataset · provider · license · fetched_at · query URL, monospaced, copyable), mapping version + rules verbatim, `config_sha256` + `compiler_version`, sampling line — "16 of N incidents (stratified, seed 4636)" with N from the pack — and the field-provenance grid rendering REAL / MAPPED / INFERRED / SYNTHETIC as four badge styles. Footer: the attribution line(s) verbatim. |
| **Reality baseline** | `RealityStrip.tsx` (NEW) | One compact strip: REAL mean/median first-on-scene (grey, from `reference.aggregates`, labeled **mean** or **median** to match the field used — never relabel a mean as a median) vs AGENTS mean **spawn→first-arrival** `ticks × tick_minutes` (arm color; spawn→arrival matches the real received→on-scene interval) · held-rate pair where present · the pack's caveat line, not dismissible · sub-caption: *"directionally comparable under identical demand — travel and dispatch abstractions differ."* |
| **Map names + popover** | `TownMap.tsx` (additive) | **Mandatory:** district labels are currently hardcoded in the `DISTRICT_LAYOUT` constant (`TownMap.tsx:26–32`, rendered at `:396`) — `world.districts[].name` reaches the frontend (`state.py:196`, `types.ts:5`) but the map ignores it. Change the label source to `world.districts[id]?.name ?? DISTRICT_LAYOUT[id].label` (geometry stays keyed by canonical id); without this, `nyc-ida-2021` renders "Old Town" instead of "Manhattan". Mission popover gains two lines when scenario: `first on scene (real): 14 min` / `agents (sim): 24 min` from `reference.missions` via the injection-safe index mapping; `lives_at_risk` gets an `INFERRED` badge. |
| **Integration** | `App.tsx`, `MapTab.tsx` (mount edits) | Mounts the `DATA` chip in the app header (`App.tsx:165` area) and `RealityStrip` in `MapTab`/`CompareTab` when `run.scenario` is present. Final density sweep. |

## Packs to ship

| Pack | Source (verified 2026-06-11) | Role | Status of ground truth |
|---|---|---|---|
| `sf-routine-2026` | DataSF `nuek-vuh3` (SODA, keyless, **PDDL**), 7.34 M rows | **MVP** — cleanest single source, builds the compiler | Real demand + real per-unit latency |
| `nyc-ida-2021` | NYC Open Data `76xm-jjuj` + `8m42-w767` (keyless), Ida window verified: 2,003 EMS incidents, 16.5 % held, **avg** 948 s (vs avg 538 s in the verified 2012-10-15/16 normal-period window; adapter computes an Ida-adjacent baseline) | **Headline** — real disaster surge | Real demand + real latency + held-rate |
| `tur-2023` *(optional)* | AFAD `apiv2/event/filter` (curl -L) + USGS ComCat/ShakeMap/PAGER for `us6000jllz` | On-theme showpiece — real M7.7→M7.6 doublet timeline | Hazard only — **all demand/response synthesized**; `field_provenance` mostly `inferred`; no `reference` block, so RealityStrip does not render; caveat line: *"Hazard timing: real · Demand & outcomes: simulated model"* |

Licensing notes for `tur-2023`: AFAD has **no formal open license** — attribution required
per site footer; **do not commit or redistribute the raw catalog** (`raw/` is gitignored for
this reason). USGS products are US public domain; use "Credit: U.S. Geological Survey".

Adapter-specific mapping decisions for SF/NYC are in §2 of the research report (call-type →
kind tables, severity rules, null-handling) — implement them as the config YAMLs, not code.

## Testing & definition of done

- **Compiler:** unit tests per adapter against committed fixtures (no network); golden-file
  test that recompiling from identical `raw/` fixture + config yields byte-identical
  `scenario.json`; sampling determinism test (same `sample_seed` → same `kept` set).
- **Pack loading:** pydantic rejection tests (bad district id, severity 0/6, unsorted
  timeline, unknown pool kind, reference key out of range, last-mission-tick + 16 > 120).
- **Engine:** `aftershock verify --scenario sf-routine-2026` passes (two runs, identical
  digests); scripted-arm e2e on a fixture pack resolves/fails missions and spawned mission
  count == `sampling.kept`; under-budget explicit `--ticks` errors; `bench --scenario` exits
  with error.
- **API:** `/api/scenarios` list + detail; `POST /api/live` with unknown scenario → 404,
  with valid scenario → manifest contains scenario block and server-side ticks default
  applied when omitted; `/api/runs` carries the compact scenario summary; path-traversal
  probes on scenario id → 404.
- **Web:** `npm run build` + `npx tsc --noEmit` clean; vitest for RealityStrip math
  (ticks×tick_minutes, null-latency handling), the injection-safe index↔mission-id mapping
  (with and without injected spawns), provenance badge rendering, and district-name
  fallback; existing single-run and compare behaviour unchanged when `run.scenario` is null.
- **Docs:** README gets a "Real-data scenarios" subsection with the attribution lines;
  per-pack `README.md` committed alongside each `scenario.json`; this spec folded into
  `DESIGN.md` per the pinned fold order.

## Phasing & effort

All phases are unblocked (task #3 merged). S1–S3 and S4 can proceed in parallel — they share
no files.

| Phase | Scope | Files | Est. |
|---|---|---|---|
| **S1** | `town/scenario.py`, `town/arms.py`, `cli.py`, tests | engine-side only | 0.5–1 d |
| **S2** | compiler package + SF adapter + `sf-routine-2026` pack + fixtures | `src/aftershock/data/`, `scenarios/`, `.gitignore` (`scenarios/*/raw/`) | 1–2 d |
| **S3** | API endpoints + manifest plumbing + Dockerfile COPY | `web.py`, `Dockerfile` | 0.5–1 d |
| **S4** | UI: trigger, badges, ProvenancePanel, RealityStrip, map names/popover, mounts | `web/src/**` per surface table | 1.5–2 d |
| **S5** | `nyc-ida-2021` (EMS+Fire join, computed baseline window) | adapter + pack | 1–2 d |
| **S6** *(opt)* | `tur-2023` (AFAD+ShakeMap; rasterio/tifffile) | adapter + pack | 2–3 d |

MVP = S1–S4 with the SF pack (~3.5–5 dev-days); headline demo adds S5.

**Deferred (explicit non-goals):** all-hazards engine vocabulary (scenario-defined mission/
resource kinds, dynamics packs) — post-hackathon v2; live re-fetching of upstream data at
run time (never — invariant 2); using scenario packs in `bench` (invariant 3); renaming
injection kinds per hazard (display-only nicety).
