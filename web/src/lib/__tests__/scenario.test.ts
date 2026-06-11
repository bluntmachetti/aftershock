import { describe, it, expect } from 'vitest'
import {
  mapTimelineIndexToMissionId,
  missionIdForTimelineIndex,
  timelineIndexForMissionId,
  buildFirstArrivalMap,
  agentLatencyMinutes,
  realLatencyMinutes,
  formatMinutes,
  selectScenarioBaseline,
  runHasScenario,
} from '../scenario'
import type {
  TickRecord,
  WorldEvent,
  RunDetail,
  RunSummary,
  ScenarioManifestBlock,
  ScenarioReferenceMission,
} from '../../types'

// ---- Tiny typed builders (mirror the events.py mission_spawned payload) ----

function spawnEvent(
  missionId: string,
  opts: { injected?: boolean; kind?: string; id?: string } = {},
): WorldEvent {
  const payload: Record<string, unknown> = {
    mission_id: missionId,
    mission_kind: opts.kind ?? 'fire',
    district_id: 'old_town',
    severity: 3,
    lives_at_risk: 5,
    deadline_tick: 10,
  }
  if (opts.injected) payload.injected = true
  return {
    event_id: opts.id ?? `e-${missionId}`,
    tick: 0,
    kind: 'mission_spawned',
    payload,
  }
}

// A non-spawn event that must be ignored by the index map.
function panicEvent(id: string): WorldEvent {
  return {
    event_id: id,
    tick: 0,
    kind: 'panic_changed',
    payload: { panic: 0.1, reason: 'mission_spawned' },
  }
}

// `arrival` event builders mirroring the engine payloads (decisions.py /
// events.py). `pending` is the blocked-road dispatch PLACEHOLDER (carries
// `pending_due` + `road_blocked:true`, NOT a real on-scene arrival); the plain
// landing carries no `pending_due`; `direction` marks a pool RETURN.
function arrivalEvent(
  missionId: string,
  t: number,
  opts: { id?: string; pendingDue?: number; roadBlocked?: boolean; direction?: string } = {},
): WorldEvent {
  const payload: Record<string, unknown> = { mission_id: missionId, resource: 'fire_engine', qty: 1 }
  if (opts.pendingDue !== undefined) payload.pending_due = opts.pendingDue
  if (opts.roadBlocked !== undefined) payload.road_blocked = opts.roadBlocked
  if (opts.direction !== undefined) payload.direction = opts.direction
  return {
    event_id: opts.id ?? `arr-${missionId}-${t}`,
    tick: t,
    kind: 'arrival',
    payload,
  }
}

function tick(t: number, events: WorldEvent[]): TickRecord {
  return {
    tick: t,
    observation_digests: {},
    responses: [],
    rulings: [],
    accepted: [],
    rejected: [],
    events,
    scores: {},
    world_digest: 'wd',
  }
}

// ---- Injection-safe index ↔ mission id mapping ----

describe('mapTimelineIndexToMissionId', () => {
  it('maps timeline indices when there are NO injected spawns', () => {
    // Three timeline missions across two ticks, plus noise events.
    const ticks: TickRecord[] = [
      tick(2, [spawnEvent('m1'), panicEvent('p1')]),
      tick(4, [spawnEvent('m2')]),
      tick(6, [spawnEvent('m3'), panicEvent('p2')]),
    ]
    // nth non-injected spawn == nth timeline mission index.
    expect(mapTimelineIndexToMissionId(ticks)).toEqual(['m1', 'm2', 'm3'])
    expect(missionIdForTimelineIndex(ticks, 0)).toBe('m1')
    expect(missionIdForTimelineIndex(ticks, 2)).toBe('m3')
    expect(timelineIndexForMissionId(ticks, 'm2')).toBe(1)
  })

  it('SKIPS injected spawns so timeline indices still align', () => {
    // events.py drains injections FIRST within a tick — so an injected spawn
    // (m2) precedes the timeline spawn (m3) within the same tick, and consumes
    // the shared id counter before it. The injection-safe map must skip m2.
    const ticks: TickRecord[] = [
      tick(2, [spawnEvent('m1')]),
      tick(5, [
        spawnEvent('m2', { injected: true }), // injected: NOT a timeline mission
        spawnEvent('m3'), // the timeline spawn at this tick
      ]),
      tick(8, [
        spawnEvent('m4', { injected: true }), // another inject — skipped
        spawnEvent('m5'),
      ]),
    ]
    // Timeline indices 0,1,2 -> m1, m3, m5 (m2, m4 are injections).
    expect(mapTimelineIndexToMissionId(ticks)).toEqual(['m1', 'm3', 'm5'])
    expect(missionIdForTimelineIndex(ticks, 1)).toBe('m3')
    expect(missionIdForTimelineIndex(ticks, 2)).toBe('m5')
    // An injected mission id has NO timeline index (no reference baseline).
    expect(timelineIndexForMissionId(ticks, 'm2')).toBeNull()
    expect(timelineIndexForMissionId(ticks, 'm4')).toBeNull()
    // The timeline spawns map back to 0,1,2.
    expect(timelineIndexForMissionId(ticks, 'm3')).toBe(1)
  })

  it('returns null for an out-of-range or missing timeline index', () => {
    const ticks: TickRecord[] = [tick(2, [spawnEvent('m1')])]
    expect(missionIdForTimelineIndex(ticks, 5)).toBeNull()
    expect(missionIdForTimelineIndex(ticks, -1)).toBeNull()
    expect(timelineIndexForMissionId(ticks, 'nope')).toBeNull()
  })

  it('handles an empty timeline', () => {
    expect(mapTimelineIndexToMissionId([])).toEqual([])
    expect(missionIdForTimelineIndex([], 0)).toBeNull()
  })
})

// ---- First-arrival selection (feeds the sim-latency comparison) ----

describe('buildFirstArrivalMap', () => {
  it('takes the first genuine on-scene landing, not the blocked-road dispatch placeholder', () => {
    // The headline-pack bug: a resource dispatched across a blocked road emits a
    // dispatch-time placeholder (pending_due + road_blocked:true, NO direction)
    // at the dispatch tick, then the REAL landing BLOCKED_DISPATCH_DELAY ticks
    // later. The placeholder must NOT be picked — else latency under-reports.
    const ticks: TickRecord[] = [
      tick(1, [arrivalEvent('m1', 1, { id: 'dispatch-pending-1-m1-fire_engine', pendingDue: 3, roadBlocked: true })]),
      tick(3, [arrivalEvent('m1', 3, { id: 'arr-1-m1-fire_engine' })]), // the real landing
    ]
    const map = buildFirstArrivalMap(ticks)
    // Must resolve to the LATER real-landing tick (3), not the placeholder (1).
    expect(map.get('m1')).toBe(3)
  })

  it('keeps the immediate road_blocked:false dispatch (it IS the instant arrival)', () => {
    // An unblocked dispatch lands the same tick: road_blocked:false, no
    // pending_due. That genuine arrival must be kept.
    const ticks: TickRecord[] = [
      tick(2, [arrivalEvent('m2', 2, { roadBlocked: false })]),
    ]
    expect(buildFirstArrivalMap(ticks).get('m2')).toBe(2)
  })

  it('skips pool returns (events carrying a string direction)', () => {
    const ticks: TickRecord[] = [
      tick(1, [arrivalEvent('m3', 1, { direction: 'return' })]), // a recall — not an arrival
      tick(4, [arrivalEvent('m3', 4)]), // the real arrival
    ]
    expect(buildFirstArrivalMap(ticks).get('m3')).toBe(4)
  })

  it('records the earliest genuine arrival when several land', () => {
    const ticks: TickRecord[] = [
      tick(5, [arrivalEvent('m4', 5)]),
      tick(7, [arrivalEvent('m4', 7)]),
    ]
    expect(buildFirstArrivalMap(ticks).get('m4')).toBe(5)
  })

  it('returns an empty map when nothing genuinely arrives', () => {
    // Only a blocked-road placeholder ever fires — no real landing in the window.
    const ticks: TickRecord[] = [
      tick(1, [arrivalEvent('m5', 1, { pendingDue: 3, roadBlocked: true })]),
    ]
    expect(buildFirstArrivalMap(ticks).has('m5')).toBe(false)
    expect(buildFirstArrivalMap([]).size).toBe(0)
  })
})

// ---- RealityStrip math: ticks × tick_minutes ----

describe('agentLatencyMinutes', () => {
  it('computes (firstArrival − spawn) × tick_minutes', () => {
    // spawn @ tick 4, first arrival @ tick 6, 12 min/tick => 24 min.
    expect(agentLatencyMinutes(4, 6, 12)).toBe(24)
    // 5 ticks of latency at 12 min/tick.
    expect(agentLatencyMinutes(0, 5, 12)).toBe(60)
    // Zero latency (arrived same tick).
    expect(agentLatencyMinutes(3, 3, 12)).toBe(0)
  })

  it('returns null when no unit arrived (firstArrival null/undefined)', () => {
    expect(agentLatencyMinutes(4, null, 12)).toBeNull()
    expect(agentLatencyMinutes(4, undefined, 12)).toBeNull()
  })

  it('returns null (never negative) when arrival precedes spawn', () => {
    expect(agentLatencyMinutes(6, 4, 12)).toBeNull()
  })

  it('returns null on non-finite inputs', () => {
    expect(agentLatencyMinutes(NaN, 6, 12)).toBeNull()
    expect(agentLatencyMinutes(4, 6, NaN)).toBeNull()
  })
})

// ---- RealityStrip math: null-latency handling ----

describe('realLatencyMinutes', () => {
  it('converts latency_s to minutes', () => {
    const ref: ScenarioReferenceMission = {
      received: '2021-09-01T18:35:00-04:00',
      first_on_scene: '2021-09-01T18:42:00-04:00',
      latency_s: 420, // 7 min
    }
    expect(realLatencyMinutes(ref)).toBe(7)
  })

  it('returns null when latency_s is null EVEN IF first_on_scene exists', () => {
    // The strict rule: a present first_on_scene with null latency_s is still
    // "no real latency" — never compute a delta from the timestamps.
    const ref: ScenarioReferenceMission = {
      received: '2021-09-02T03:26:00-04:00',
      first_on_scene: '2021-09-02T03:30:00-04:00', // present...
      latency_s: null, // ...but null latency => null result.
    }
    expect(realLatencyMinutes(ref)).toBeNull()
  })

  it('returns null for the fully-unarrived reference (mission 11 in nyc-ida)', () => {
    const ref: ScenarioReferenceMission = {
      received: '2021-09-02T03:26:00-04:00',
      first_on_scene: null,
      latency_s: null,
    }
    expect(realLatencyMinutes(ref)).toBeNull()
  })

  it('returns null for a null/undefined reference', () => {
    expect(realLatencyMinutes(null)).toBeNull()
    expect(realLatencyMinutes(undefined)).toBeNull()
  })
})

describe('formatMinutes', () => {
  it('rounds to a whole minute with a min suffix', () => {
    expect(formatMinutes(7)).toBe('7 min')
    expect(formatMinutes(15.7)).toBe('16 min')
    expect(formatMinutes(0)).toBe('0 min')
  })

  it('renders the placeholder for null latency (never a fabricated number)', () => {
    expect(formatMinutes(null)).toBe('—')
    expect(formatMinutes(undefined)).toBe('—')
    expect(formatMinutes(NaN)).toBe('—')
  })

  it('honors custom suffix/placeholder', () => {
    expect(formatMinutes(null, { placeholder: 'n/a' })).toBe('n/a')
    expect(formatMinutes(3, { suffix: 'm' })).toBe('3m')
  })
})

// ---- Scenario baseline selector ----

function manifestBlock(): ScenarioManifestBlock {
  return {
    id: 'nyc-ida-2021',
    name: 'Hurricane Ida — NYC',
    hazard: 'hurricane_flood',
    tick_minutes: 12,
    pack_digest: 'deadbeef',
    config_sha256: 'cfg',
    source: [],
    field_provenance: {
      tick: 'real',
      district_id: 'real',
      mission_kind: 'mapped',
      severity: 'mapped',
      lives_at_risk: 'inferred',
      blockage: 'synthetic',
    },
    caveat_line: 'Demand: real · Latency baseline: real · Lives & outcomes: simulated model.',
    reference_aggregates: { mean_latency_s: 948 },
  }
}

function runDetail(scenario: ScenarioManifestBlock | null): RunDetail {
  return {
    run_id: 'live-abc',
    manifest: {},
    final_scores: {},
    n_ticks: 60,
    has_world: true,
    scenario,
  }
}

describe('selectScenarioBaseline', () => {
  it('returns the manifest scenario block for a scenario run', () => {
    const block = manifestBlock()
    expect(selectScenarioBaseline(runDetail(block))).toBe(block)
  })

  it('returns null for a synthetic run (no scenario) — behavior unchanged', () => {
    expect(selectScenarioBaseline(runDetail(null))).toBeNull()
    expect(selectScenarioBaseline(null)).toBeNull()
    expect(selectScenarioBaseline(undefined)).toBeNull()
  })
})

describe('runHasScenario', () => {
  it('is true only when a non-null compact scenario is present', () => {
    const withScenario: RunSummary = {
      run_id: 'r1',
      seed: 1,
      arm: 'society',
      ticks: 60,
      scenario: { id: 'nyc-ida-2021', name: 'Ida', hazard: 'hurricane_flood' },
    }
    const synthetic: RunSummary = {
      run_id: 'r2',
      seed: 1,
      arm: 'society',
      ticks: 30,
      scenario: null,
    }
    expect(runHasScenario(withScenario)).toBe(true)
    expect(runHasScenario(synthetic)).toBe(false)
    expect(runHasScenario({ run_id: 'r3', seed: 1, arm: 'solo', ticks: 30 })).toBe(false)
    expect(runHasScenario(null)).toBe(false)
  })
})
