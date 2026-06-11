# Hurricane Ida — NYC, night of 2021-09-01

**Scenario id:** `nyc-ida-2021`  ·  **Hazard:** `hurricane_flood`  ·  **Adapter:** `nyc`

> Demand: real · Latency baseline: real · Lives & outcomes: simulated model.

## Sources (EMS + Fire, joined on the Ida window)

- **EMS Incident Dispatch Data** (`76xm-jjuj`)
  - Provider: FDNY via NYC Open Data
  - License: NYC Open Data terms (no formal license) — https://opendata.cityofnewyork.us/overview/
  - Attribution: FDNY via NYC Open Data
  - Fetched: 2026-06-11  ·  Rows fetched: 2003
  - Query:

    ```
    https://data.cityofnewyork.us/resource/76xm-jjuj.json?%24where=incident_datetime+between+%272021-09-01T18%3A00%3A00%27+and+%272021-09-02T06%3A00%3A00%27&%24order=incident_datetime%2Cincident_id&%24limit=50000
    ```

- **Fire Incident Dispatch Data** (`8m42-w767`)
  - Provider: FDNY via NYC Open Data
  - License: NYC Open Data terms (no formal license) — https://opendata.cityofnewyork.us/overview/
  - Attribution: FDNY via NYC Open Data
  - Fetched: 2026-06-11  ·  Rows fetched: 2022
  - Query:

    ```
    https://data.cityofnewyork.us/resource/8m42-w767.json?%24where=incident_datetime+between+%272021-09-01T18%3A00%3A00%27+and+%272021-09-02T06%3A00%3A00%27&%24order=incident_datetime%2Cstarfire_incident_id&%24limit=50000
    ```

## Window & sampling

- **Window:** 2021-09-01T18:00:00-04:00 → 2021-09-02T06:00:00-04:00 (12 min/tick) — the night of Hurricane Ida.
- **Sampling:** 16 of 2212 incidents — stratified by (tick-bucket, mission_kind), seed 4636.
- **Filter:** EMS initial_severity_level_code in {1,2,3} (codes 4-8 dropped); Fire incident_classification_group in {Structural,NonStructural Fires,NonMedical Emergencies}; boroughs only (no CW/X1 noise); response times filtered by valid_incident_rspns_time_indc=Y

## Reality baseline

- **Ida window:** mean first-on-scene 948 s · median 540 s · held 16.5%.
- **Baseline window:** Ida-adjacent calm window: 2021-08-18 (Wed) 18:00 -> 08-19 06:00 EDT (two weeks prior). — mean 524 s · median 451 s · held 4.2%.
  The baseline is an Ida-adjacent calm window computed by the adapter — **not** the 538 s / 6.9 % pre-Sandy figures.
- **Fire timestamps are minute-rounded upstream** (the Fire Incident Dispatch table stamps whole-minute `incident_datetime` / `first_on_scene_datetime`). For Fire-backed reference missions the displayed `latency_s` is recomputed as `round(first_on_scene - received)` so the popover triple (received · first-on-scene · latency) is self-consistent at minute precision; EMS keeps its authoritative second-resolution latency. A mission with no valid response time shows neither a first-on-scene nor a latency.

## Provenance (REAL / MAPPED / INFERRED / SYNTHETIC)

| Field | Marker |
|---|---|
| `tick` | REAL |
| `district_id` | REAL |
| `mission_kind` | MAPPED |
| `severity` | MAPPED |
| `lives_at_risk` | INFERRED |
| `blockage` | SYNTHETIC |

Real EMS/Fire incident *types* are mapped onto the four engine MissionKinds in the offline compiler (mapping `nyc-v1`). EMS severity codes 1-8 are rebinned (1-2→5, 3→4; codes 4-8 excluded by the filter); Fire severity comes from engines-assigned quantiles (p50=1, p75=1, p90=3) — **never** `highest_alarm_level`. `lives_at_risk` is an **inferred** lookup, not a real casualty count. Blockages are not present in these datasets (synthetic field, none emitted).

## Caveat

> Demand: real · Latency baseline: real · Lives & outcomes: simulated model.

Real arrival process and real first-on-scene latency (held-rate and response-seconds verified in the data); lives saved is a simulated model, **not** a claim about real outcomes. Demand is real · Latency baseline is real · Lives & outcomes are a simulated model.
