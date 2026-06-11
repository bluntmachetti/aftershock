/**
 * Scenario-pack pure helpers (task #4 — real-data scenario packs).
 *
 * No React, no side-effects, no network. These are the load-bearing primitives
 * the RealityStrip / ProvenancePanel / TownMap-popover surfaces import:
 *
 *  - `mapTimelineIndexToMissionId` — the INJECTION-SAFE index↔id map
 *    (DESIGN.md "Index ↔ mission id"). Engine mission ids (`m1..`) come from a
 *    single shared counter that live injections consume BEFORE that tick's
 *    timeline spawns, so the timeline index cannot be reconstructed by counting.
 *    We walk `mission_spawned` events in record order, SKIP events whose payload
 *    has `injected === true`, and the nth non-injected spawn is the nth timeline
 *    mission index. This is normative for `reference.missions` (keyed by timeline
 *    index).
 *
 *  - RealityStrip math — `agentLatencyMinutes` (`(firstArrival − spawn) ×
 *    tick_minutes`), minute formatting, and STRICT null-latency handling: the
 *    real baseline is null whenever the pack's `latency_s` is null, even if a
 *    `first_on_scene` timestamp exists — we never compute a delta in that case.
 *
 *  - `selectScenarioBaseline` — pull the single scenario-level reality baseline
 *    (the manifest scenario block) from a run; null/absent for synthetic runs so
 *    behavior is unchanged with no scenario.
 */

import type {
  TickRecord,
  RunSummary,
  RunDetail,
  ScenarioManifestBlock,
  ScenarioReferenceMission,
} from '../types'

// ---------------------------------------------------------------------------
// Injection-safe index ↔ mission id mapping
// ---------------------------------------------------------------------------

/**
 * Build the timeline-index → engine-mission-id map by walking `mission_spawned`
 * events across all ticks in record order, skipping injected spawns.
 *
 * Per DESIGN.md: live injections consume the shared id counter before the tick's
 * timeline spawns, so counting ids is wrong. The nth NON-injected `mission_spawned`
 * event corresponds to the nth `timeline` mission entry — and `reference.missions`
 * is keyed by that same timeline index.
 *
 * Ticks are read in array order; within a tick, events in their recorded order
 * (events.py drains injections first, so injected spawns precede the timeline
 * spawn within a tick — but we filter by payload, never by position, so order
 * within a tick does not matter for correctness). An injected spawn is any
 * `mission_spawned` event whose `payload.injected === true`.
 *
 * Returns an array where `result[i]` is the engine mission id (`m3`, …) for
 * timeline mission index `i`. A non-injected spawn missing a string `mission_id`
 * still advances the index (so alignment with the timeline is preserved) but
 * contributes `''` at that slot.
 */
export function mapTimelineIndexToMissionId(ticks: TickRecord[]): string[] {
  const ids: string[] = []
  for (const record of ticks) {
    for (const event of record.events) {
      if (event.kind !== 'mission_spawned') continue
      if (event.payload?.injected === true) continue
      const missionId =
        typeof event.payload?.mission_id === 'string'
          ? (event.payload.mission_id as string)
          : ''
      ids.push(missionId)
    }
  }
  return ids
}

/**
 * The engine mission id (`m3`, …) for a given timeline mission INDEX, or null
 * when the index has not spawned yet (or is out of range). Built on top of
 * `mapTimelineIndexToMissionId`; convenient for the mission popover, which maps a
 * concrete mission back to its `reference.missions[index]` baseline.
 */
export function missionIdForTimelineIndex(
  ticks: TickRecord[],
  timelineIndex: number,
): string | null {
  if (timelineIndex < 0) return null
  const ids = mapTimelineIndexToMissionId(ticks)
  if (timelineIndex >= ids.length) return null
  const id = ids[timelineIndex]
  return id === '' ? null : id
}

/**
 * The inverse: the timeline INDEX for a concrete engine mission id, or null when
 * that id was injected / not a timeline spawn (so it has no `reference.missions`
 * baseline). Walks the same injection-safe ordering.
 */
export function timelineIndexForMissionId(
  ticks: TickRecord[],
  missionId: string,
): number | null {
  const ids = mapTimelineIndexToMissionId(ticks)
  const idx = ids.indexOf(missionId)
  return idx === -1 ? null : idx
}

// ---------------------------------------------------------------------------
// First-arrival selection (feeds the RealityStrip + popover sim latency)
// ---------------------------------------------------------------------------

/**
 * First genuine on-scene arrival tick per engine mission id.
 *
 * Walks every tick's events in record order and records the tick of the first
 * non-return `arrival` event carrying a `mission_id`. `events.py` emits `arrival`
 * with a bare `mission_id` for a dispatch landing; pool returns carry a string
 * `direction`, so those are skipped.
 *
 * CRITICAL (blocked-road exclusion): when a resource is dispatched across a
 * blocked road, the engine emits TWO `arrival` events for the same mission — a
 * dispatch-TIME placeholder at the dispatch tick (`decisions.py`,
 * `pending_due` + `road_blocked:true`, NO `direction`) and the REAL on-scene
 * landing `BLOCKED_DISPATCH_DELAY` ticks later (`events.py`, no `pending_due`).
 * The placeholder is NOT a real arrival, so we skip any event carrying
 * `pending_due`; only the genuine landing (or the immediate `road_blocked:false`
 * dispatch, which carries no `pending_due` and IS the instant arrival) counts.
 * Without this guard `firstArrival` resolves to the dispatch tick and the agents'
 * spawn→arrival latency under-reports by `BLOCKED_DISPATCH_DELAY × tick_minutes`
 * — biasing the AGENTS-vs-REAL comparison in the agents' favor exactly on the
 * flood-blockage headline pack.
 *
 * Feeds `agentLatencyMinutes(spawned_tick, firstArrival, tick_minutes)`. Empty
 * when a run has no scenario (the lookup is simply never consulted in that case).
 */
export function buildFirstArrivalMap(ticks: TickRecord[]): Map<string, number> {
  const out = new Map<string, number>()
  for (const record of ticks) {
    for (const event of record.events) {
      if (event.kind !== 'arrival') continue
      // Pool returns (carry a string `direction`) are not arrivals.
      if (typeof event.payload?.direction === 'string') continue
      // Blocked-road dispatch placeholder — the real landing comes later.
      if (event.payload?.pending_due != null) continue
      const missionId =
        typeof event.payload?.mission_id === 'string'
          ? (event.payload.mission_id as string)
          : ''
      if (!missionId) continue
      if (!out.has(missionId)) out.set(missionId, event.tick)
    }
  }
  return out
}

// ---------------------------------------------------------------------------
// RealityStrip math
// ---------------------------------------------------------------------------

/**
 * The AGENTS sim latency in MINUTES for one mission:
 *   (firstArrivalTick − spawnTick) × tick_minutes.
 *
 * `spawnTick` is the mission's `spawned_tick`; `firstArrivalTick` is the tick the
 * first assigned resource arrived (caller derives it — e.g. from the first
 * `resource_arrived` event / pending-arrival resolution for the mission).
 *
 * Returns null when the agent never put a unit on scene (`firstArrivalTick` is
 * null/undefined), or when the inputs are not finite, or when the arrival is
 * before the spawn (a non-physical negative latency — treated as "no comparable
 * arrival"). Never returns a negative number.
 */
export function agentLatencyMinutes(
  spawnTick: number,
  firstArrivalTick: number | null | undefined,
  tickMinutes: number,
): number | null {
  if (firstArrivalTick === null || firstArrivalTick === undefined) return null
  if (
    !Number.isFinite(spawnTick) ||
    !Number.isFinite(firstArrivalTick) ||
    !Number.isFinite(tickMinutes)
  ) {
    return null
  }
  const deltaTicks = firstArrivalTick - spawnTick
  if (deltaTicks < 0) return null
  return deltaTicks * tickMinutes
}

/**
 * The REAL first-on-scene latency in MINUTES for one mission's reference entry,
 * or null. STRICT null handling (delta from DESIGN.md, invariant 4): we return
 * null whenever `latency_s` is null — EVEN IF `first_on_scene` is present — and
 * never compute a delta from the timestamps ourselves. `latency_s` is the
 * compiler's authoritative figure (MIN over units, nulls dropped); a present
 * `first_on_scene` with a null `latency_s` means the data does not support a
 * clean latency, so the baseline is "no real latency".
 */
export function realLatencyMinutes(
  ref: ScenarioReferenceMission | null | undefined,
): number | null {
  if (!ref) return null
  if (ref.latency_s === null || ref.latency_s === undefined) return null
  if (!Number.isFinite(ref.latency_s)) return null
  return ref.latency_s / 60
}

/**
 * Format a minute count for the strip / popover: rounded to a whole minute with a
 * trailing "min" (e.g. `14 min`). A null/undefined value renders the em-dash
 * placeholder `—` (used for null real latency — never a fabricated number).
 */
export function formatMinutes(
  minutes: number | null | undefined,
  opts: { suffix?: string; placeholder?: string } = {},
): string {
  const suffix = opts.suffix ?? ' min'
  const placeholder = opts.placeholder ?? '—'
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) {
    return placeholder
  }
  return `${Math.round(minutes)}${suffix}`
}

// ---------------------------------------------------------------------------
// Scenario baseline selector
// ---------------------------------------------------------------------------

/**
 * Pull the single scenario-level reality baseline (the manifest scenario block)
 * from a run. Accepts either the full `RunDetail` (which carries the whole
 * `ScenarioManifestBlock` under `.scenario`) or `null`/synthetic.
 *
 * Returns null for a synthetic run (no scenario) — so every consumer can treat
 * the absence as "render no RealityStrip", preserving behavior unchanged.
 */
export function selectScenarioBaseline(
  run: RunDetail | null | undefined,
): ScenarioManifestBlock | null {
  if (!run) return null
  return run.scenario ?? null
}

/**
 * Whether a run row carries a scenario (so callers can decide to badge / fetch
 * its pack). Works off the compact `RunSummary.scenario` passthrough; true only
 * when a non-null scenario block is present. A synthetic run (null/absent
 * scenario) returns false.
 */
export function runHasScenario(
  run: RunSummary | null | undefined,
): boolean {
  return Boolean(run && run.scenario)
}
