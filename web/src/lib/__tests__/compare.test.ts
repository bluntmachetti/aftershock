import { describe, it, expect } from 'vitest'
import {
  indexForTick,
  maxComparableTick,
  selectRunningCost,
  deriveScrubberEvents,
} from '../timeline'
import type {
  TickRecord,
  WorldState,
  AgentResponse,
  TokenUsage,
  WorldEvent,
  MissionState,
} from '../../types'

// ---- Tiny typed builders (keep fixtures readable + strict) ----

function usage(cost: number): TokenUsage {
  return { prompt_tokens: 10, completion_tokens: 10, cost_usd: cost, model: 'qwen3.5-flash' }
}

function response(cost: number | null): AgentResponse {
  return {
    agent_id: 'a',
    decisions: [],
    proposals: [],
    responses: [],
    usage: cost === null ? null : usage(cost),
    error: '',
  }
}

function event(kind: string, payload: Record<string, unknown>, id = `e-${kind}`): WorldEvent {
  return { event_id: id, tick: 0, kind, payload }
}

function tick(
  t: number,
  opts: { responses?: AgentResponse[]; events?: WorldEvent[] } = {},
): TickRecord {
  return {
    tick: t,
    observation_digests: {},
    responses: opts.responses ?? [],
    rulings: [],
    accepted: [],
    rejected: [],
    events: opts.events ?? [],
    scores: {},
    world_digest: `d${t}`,
  }
}

function mission(id: string, status: MissionState['status']): MissionState {
  return {
    id,
    kind: 'fire',
    district_id: 'harbor',
    severity: 2,
    lives_at_risk: 5,
    spawned_tick: 0,
    deadline_tick: 10,
    required: { fire_engine: 1 },
    assigned: {},
    progress: 0,
    status,
    priority: 0,
    resolved_tick: status === 'resolved' ? 1 : null,
    spread_applied: false,
  }
}

function world(t: number, missions: MissionState[]): WorldState {
  return {
    tick: t,
    seed: 42,
    panic: 0,
    lives_saved: 0,
    lives_lost: 0,
    next_mission_no: 1,
    districts: {},
    missions: Object.fromEntries(missions.map((m) => [m.id, m])),
    pools: {},
    pending: [],
  }
}

// Two sides with deliberately different lengths / tick coverage.
const sideA: TickRecord[] = [tick(0), tick(1), tick(2), tick(3)]
const sideB: TickRecord[] = [tick(0), tick(2), tick(5)] // sparse: skips ticks 1, 3, 4

describe('indexForTick', () => {
  it('returns 0 for an empty timeline (0 floor)', () => {
    expect(indexForTick([], 0)).toBe(0)
    expect(indexForTick([], 99)).toBe(0)
  })

  it('returns the exact array index on an exact tick match', () => {
    expect(indexForTick(sideA, 0)).toBe(0)
    expect(indexForTick(sideA, 2)).toBe(2)
    expect(indexForTick(sideA, 3)).toBe(3)
  })

  it('returns the last record with tick <= target on an inexact tick', () => {
    // sideB has ticks [0, 2, 5]; logical tick 3 and 4 hold the index of tick 2.
    expect(indexForTick(sideB, 3)).toBe(1)
    expect(indexForTick(sideB, 4)).toBe(1)
    // Beyond the last record clamps to the last index, not out of range.
    expect(indexForTick(sideB, 99)).toBe(2)
  })

  it('floors at index 0 when the target precedes the first record', () => {
    const future: TickRecord[] = [tick(5), tick(6), tick(7)]
    expect(indexForTick(future, 0)).toBe(0)
    expect(indexForTick(future, 4)).toBe(0)
  })

  it('mirrors a shared logical tick onto two differing-length sides', () => {
    // The compare controller drives both sides off ONE logical tick.
    const t = 3
    expect(indexForTick(sideA, t)).toBe(3) // exact on A
    expect(indexForTick(sideB, t)).toBe(1) // holds tick-2 frame on B
  })
})

describe('maxComparableTick', () => {
  it('is the min of each side last tick', () => {
    // A last tick = 3, B last tick = 5 -> 3.
    expect(maxComparableTick(sideA, sideB)).toBe(3)
    expect(maxComparableTick(sideB, sideA)).toBe(3)
  })

  it('handles equal-length, equal-coverage sides', () => {
    expect(maxComparableTick(sideA, sideA)).toBe(3)
  })

  it('returns 0 when either side is empty', () => {
    expect(maxComparableTick([], sideA)).toBe(0)
    expect(maxComparableTick(sideA, [])).toBe(0)
    expect(maxComparableTick([], [])).toBe(0)
  })
})

describe('selectRunningCost', () => {
  const costed: TickRecord[] = [
    tick(0, { responses: [response(0.01), response(0.02)] }), // 0.03
    tick(1, { responses: [response(0.05)] }), // 0.05
    tick(2, { responses: [response(null), response(0.04)] }), // 0.04, null ignored
    tick(3, { responses: [] }), // 0.00
  ]

  it('returns 0 for an empty timeline', () => {
    expect(selectRunningCost([], 0)).toBe(0)
    expect(selectRunningCost([], 5)).toBe(0)
  })

  it('is cumulative through the cursor (inclusive)', () => {
    expect(selectRunningCost(costed, 0)).toBeCloseTo(0.03)
    expect(selectRunningCost(costed, 1)).toBeCloseTo(0.08)
    expect(selectRunningCost(costed, 2)).toBeCloseTo(0.12)
    expect(selectRunningCost(costed, 3)).toBeCloseTo(0.12)
  })

  it('treats null usage and zero-cost (scripted) arms as 0', () => {
    const scripted: TickRecord[] = [
      tick(0, { responses: [response(null), response(0)] }),
      tick(1, { responses: [response(null)] }),
    ]
    expect(selectRunningCost(scripted, 1)).toBe(0)
  })

  it('clamps the cursor into range', () => {
    // Beyond the end sums everything; negative floors to the first tick.
    expect(selectRunningCost(costed, 999)).toBeCloseTo(0.12)
    expect(selectRunningCost(costed, -5)).toBeCloseTo(0.03)
  })
})

describe('deriveScrubberEvents', () => {
  it('derives spawn markers from timeline mission_spawned events', () => {
    const ticks: TickRecord[] = [
      tick(0, {
        events: [event('mission_spawned', { mission_id: 'm1', mission_kind: 'fire' })],
      }),
    ]
    const out = deriveScrubberEvents(ticks, null)
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({ tick: 0, kind: 'spawn', label: 'fire' })
  })

  it('derives inject markers from injected-provenance events (not spawn)', () => {
    const ticks: TickRecord[] = [
      tick(4, {
        events: [
          event('mission_spawned', {
            mission_id: 'm9',
            mission_kind: 'medical_surge',
            injected: true,
          }),
        ],
      }),
      tick(5, {
        events: [event('road_blocked', { district_id: 'harbor', injected: true })],
      }),
    ]
    const out = deriveScrubberEvents(ticks, null)
    expect(out).toHaveLength(2)
    expect(out.every((e) => e.kind === 'inject')).toBe(true)
    expect(out[0]).toMatchObject({ tick: 4, kind: 'inject', label: 'm9' })
    expect(out[1]).toMatchObject({ tick: 5, kind: 'inject', label: 'harbor' })
  })

  it('derives resolve/fail from mission status transitions between adjacent worlds', () => {
    const worlds: WorldState[] = [
      world(0, [mission('m1', 'open'), mission('m2', 'open')]),
      world(1, [mission('m1', 'resolved'), mission('m2', 'open')]), // m1 resolves at t1
      world(2, [mission('m1', 'resolved'), mission('m2', 'failed')]), // m2 fails at t2
    ]
    const out = deriveScrubberEvents([], worlds)
    expect(out).toEqual([
      { tick: 1, kind: 'resolve', label: 'm1' },
      { tick: 2, kind: 'fail', label: 'm2' },
    ])
  })

  it('only transitions OUT OF open count (steady resolved emits nothing)', () => {
    const worlds: WorldState[] = [
      world(0, [mission('m1', 'resolved')]),
      world(1, [mission('m1', 'resolved')]),
    ]
    expect(deriveScrubberEvents([], worlds)).toEqual([])
  })

  it('omits resolve/fail markers entirely when there is no world data', () => {
    const ticks: TickRecord[] = [
      tick(0, { events: [event('mission_spawned', { mission_id: 'm1', mission_kind: 'fire' })] }),
    ]
    const out = deriveScrubberEvents(ticks, null)
    expect(out).toHaveLength(1)
    expect(out[0].kind).toBe('spawn')
  })

  it('combines event- and world-derived markers in ascending (tick, kind) order', () => {
    const ticks: TickRecord[] = [
      tick(0, { events: [event('mission_spawned', { mission_id: 'm1', mission_kind: 'fire' })] }),
      tick(2, {
        events: [
          event('mission_spawned', { mission_id: 'm9', mission_kind: 'fire', injected: true }),
        ],
      }),
    ]
    const worlds: WorldState[] = [
      world(0, [mission('m1', 'open')]),
      world(1, [mission('m1', 'open')]),
      world(2, [mission('m1', 'resolved')]),
    ]
    const out = deriveScrubberEvents(ticks, worlds)
    expect(out).toEqual([
      { tick: 0, kind: 'spawn', label: 'fire' },
      { tick: 2, kind: 'inject', label: 'm9' },
      { tick: 2, kind: 'resolve', label: 'm1' },
    ])
  })

  it('deduplicates a repeated (tick, kind, mission) event', () => {
    const ticks: TickRecord[] = [
      tick(0, {
        events: [
          event('mission_spawned', { mission_id: 'm1', mission_kind: 'fire' }, 'e1'),
          event('mission_spawned', { mission_id: 'm1', mission_kind: 'fire' }, 'e2'),
        ],
      }),
    ]
    expect(deriveScrubberEvents(ticks, null)).toHaveLength(1)
  })

  it('returns nothing for empty ticks and empty/short worlds', () => {
    expect(deriveScrubberEvents([], null)).toEqual([])
    expect(deriveScrubberEvents([], [])).toEqual([])
    expect(deriveScrubberEvents([], [world(0, [mission('m1', 'open')])])).toEqual([])
  })
})
