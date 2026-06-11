# Routine emergency demand — San Francisco, Independence Day 2018

**Scenario id:** `sf-routine-2018`  ·  **Hazard:** `routine`  ·  **Adapter:** `sf`

> Demand: real · Latency baseline: real · Lives & outcomes: simulated model.

## Source

- **Dataset:** Fire Department and Emergency Medical Services Dispatched Calls for Service (`nuek-vuh3`)
- **Provider:** DataSF (San Francisco Open Data)
- **License:** PDDL 1.0 (Public Domain Dedication and License) — http://opendatacommons.org/licenses/pddl/1.0/
- **Attribution:** DataSF
- **Fetched:** 2026-06-11  ·  **Rows fetched:** 510
- **Query:**

  ```
  https://data.sfgov.org/resource/nuek-vuh3.json?%24where=received_dttm+between+%272018-07-04T06%3A00%3A00%27+and+%272018-07-04T18%3A00%3A00%27&%24order=received_dttm%2Ccall_number%2Cunit_id&%24limit=50000
  ```

## Window & sampling

- **Window:** 2018-07-04T06:00:00-07:00 → 2018-07-04T18:00:00-07:00 (12 min/tick)
- **Sampling:** 16 of 193 incidents — stratified by (tick-bucket, mission_kind), seed 1844.
- **Filter:** battalion in B01-B10 (junk B99/AMB/XXX dropped); call_type mapped to a MissionKind (Alarms/Citizen Assist/Other dropped)

## Reality baseline

- **No held/saturation ground truth.** DataSF `nuek-vuh3` has no held/saturation field, so `held_rate` is emitted as **null** — it is *not* the same measurement as the NYC pack's real `held_indicator` rate, and the no-arrival fraction is deliberately not reused under that name.
- **No baseline comparison.** This is the routine (non-disaster) pack; it ships no computed baseline window, so the `baseline_*` figures stay null and no comparison is advertised.

## Provenance (REAL / MAPPED / INFERRED / SYNTHETIC)

| Field | Marker |
|---|---|
| `tick` | REAL |
| `district_id` | REAL |
| `mission_kind` | MAPPED |
| `severity` | MAPPED |
| `lives_at_risk` | INFERRED |
| `blockage` | SYNTHETIC |

Real incident *types* are mapped onto the four engine MissionKinds in the offline compiler (mapping `sf-v1`); the mapping is published above as provenance. Severity is a rule over `original_priority`/`call_type_group`/alarms; `lives_at_risk` is an **inferred** lookup, not a real casualty count. Blockages are not present in this dataset (synthetic field, none emitted for the routine pack).

## Caveat

> Demand: real · Latency baseline: real · Lives & outcomes: simulated model.

Real arrival process and real first-on-scene latency; lives saved is a simulated model, **not** a claim about real outcomes.
