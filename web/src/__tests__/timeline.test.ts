import { describe, it, expect } from 'vitest'
import fixture from '../__fixtures__/demo-ticks.json'
import {
  initialTimelineState,
  timelineReducer,
  selectCurrentWorld,
  selectCurrentTick,
  selectHasMore,
  selectMaxCursor,
  selectNextCursor,
  selectAtEnd,
  judgeStartIndex,
} from '../lib/timeline'
import type { TimelineState, TickRecord, WorldState } from '../types'

const fixtureTicks = fixture.ticks as TickRecord[]
const fixtureWorlds = fixture.worlds as WorldState[]

// Helper: build a loaded state from fixture
function loadedState(): TimelineState {
  return timelineReducer(
    timelineReducer(initialTimelineState, {
      type: 'LOAD_RUN',
      runId: 'seed42-scripted',
      hasWorld: true,
      total: 29,
    }),
    {
      type: 'APPEND_TICKS',
      ticks: fixtureTicks,
      worlds: fixtureWorlds,
      total: 29,
    },
  )
}

describe('timelineReducer', () => {
  it('starts with initial state', () => {
    const s = initialTimelineState
    expect(s.cursor).toBe(0)
    expect(s.ticks).toHaveLength(0)
    expect(s.playing).toBe(false)
  })

  it('LOAD_RUN resets state and sets runId', () => {
    const s = timelineReducer(initialTimelineState, {
      type: 'LOAD_RUN',
      runId: 'seed42-scripted',
      hasWorld: true,
      total: 29,
    })
    expect(s.runId).toBe('seed42-scripted')
    expect(s.loading).toBe(true)
    expect(s.ticks).toHaveLength(0)
    expect(s.hasWorld).toBe(true)
    expect(s.total).toBe(29)
  })

  it('APPEND_TICKS stores ticks and worlds', () => {
    const s = loadedState()
    expect(s.ticks).toHaveLength(3)
    expect(s.worlds).toHaveLength(3)
    expect(s.loading).toBe(false)
  })

  it('APPEND_TICKS accumulates on subsequent pages', () => {
    const s0 = loadedState()
    const s1 = timelineReducer(s0, {
      type: 'APPEND_TICKS',
      ticks: [fixtureTicks[0]],
      worlds: [fixtureWorlds[0]],
      total: 29,
    })
    expect(s1.ticks).toHaveLength(4)
    expect(s1.worlds).toHaveLength(4)
  })

  it('SET_CURSOR clamps to valid range', () => {
    const s = loadedState()
    const atZero = timelineReducer(s, { type: 'SET_CURSOR', cursor: 0 })
    expect(atZero.cursor).toBe(0)

    const atMax = timelineReducer(s, { type: 'SET_CURSOR', cursor: 999 })
    expect(atMax.cursor).toBe(2)

    const atNeg = timelineReducer(s, { type: 'SET_CURSOR', cursor: -5 })
    expect(atNeg.cursor).toBe(0)
  })

  it('PLAY and PAUSE toggle playing', () => {
    const s = loadedState()
    const playing = timelineReducer(s, { type: 'PLAY' })
    expect(playing.playing).toBe(true)
    const paused = timelineReducer(playing, { type: 'PAUSE' })
    expect(paused.playing).toBe(false)
  })

  it('SET_SPEED updates speed', () => {
    const s = timelineReducer(initialTimelineState, { type: 'SET_SPEED', speed: 4 })
    expect(s.speed).toBe(4)
  })

  it('LIVE_TICK appends tick and auto-advances cursor', () => {
    const s0 = loadedState()
    const liveTick = fixtureTicks[0]
    const liveWorld = fixtureWorlds[0]
    const s1 = timelineReducer(s0, { type: 'LIVE_TICK', tick: liveTick, world: liveWorld })
    expect(s1.ticks).toHaveLength(4)
    expect(s1.cursor).toBe(3) // cursor at newest
  })

  it('LIVE_TICK handles null world (no world data)', () => {
    const s0: TimelineState = { ...loadedState(), worlds: null, hasWorld: false }
    const s1 = timelineReducer(s0, {
      type: 'LIVE_TICK',
      tick: fixtureTicks[0],
      world: null,
    })
    expect(s1.worlds).toBeNull()
    expect(s1.ticks).toHaveLength(4)
  })

  it('RESET returns to initial state', () => {
    const s = timelineReducer(loadedState(), { type: 'RESET' })
    expect(s).toEqual(initialTimelineState)
  })
})

describe('selectors', () => {
  it('selectCurrentWorld returns world at cursor', () => {
    const s = loadedState()
    const w = selectCurrentWorld(s)
    expect(w).not.toBeNull()
    expect(w!.tick).toBe(fixtureWorlds[0].tick)
  })

  it('selectCurrentWorld at cursor=1 returns second world', () => {
    const s = timelineReducer(loadedState(), { type: 'SET_CURSOR', cursor: 1 })
    const w = selectCurrentWorld(s)
    expect(w!.tick).toBe(fixtureWorlds[1].tick)
  })

  it('selectCurrentWorld returns null when no worlds', () => {
    const s: TimelineState = { ...loadedState(), worlds: null }
    expect(selectCurrentWorld(s)).toBeNull()
  })

  it('selectCurrentTick returns tick record at cursor', () => {
    const s = loadedState()
    const t = selectCurrentTick(s)
    expect(t).not.toBeNull()
    expect(t!.tick).toBe(fixtureTicks[0].tick)
  })

  it('selectCurrentTick returns null when no ticks', () => {
    expect(selectCurrentTick(initialTimelineState)).toBeNull()
  })

  it('selectHasMore is true when loaded < total', () => {
    const s = loadedState()
    expect(selectHasMore(s)).toBe(true) // 3 loaded, total 29
  })

  it('selectHasMore is false when loaded == total', () => {
    const s: TimelineState = { ...loadedState(), total: 3 }
    expect(selectHasMore(s)).toBe(false)
  })

  it('selectMaxCursor is length-1', () => {
    const s = loadedState()
    expect(selectMaxCursor(s)).toBe(2)
  })

  it('selectMaxCursor is 0 when empty', () => {
    expect(selectMaxCursor(initialTimelineState)).toBe(0)
  })

  it('selectNextCursor advances by 1', () => {
    const s = timelineReducer(loadedState(), { type: 'SET_CURSOR', cursor: 1 })
    expect(selectNextCursor(s)).toBe(2)
  })

  it('selectNextCursor clamps at max', () => {
    const s = timelineReducer(loadedState(), { type: 'SET_CURSOR', cursor: 999 })
    expect(selectNextCursor(s)).toBe(2)
  })

  it('selectAtEnd is true at last tick', () => {
    const s = timelineReducer(loadedState(), { type: 'SET_CURSOR', cursor: 2 })
    expect(selectAtEnd(s)).toBe(true)
  })

  it('selectAtEnd is false before last tick', () => {
    const s = timelineReducer(loadedState(), { type: 'SET_CURSOR', cursor: 1 })
    expect(selectAtEnd(s)).toBe(false)
  })

  it('world-fallback: selectCurrentWorld clamps when cursor > worlds length', () => {
    // Simulate worlds loaded but cursor advanced beyond them
    const s: TimelineState = {
      ...loadedState(),
      cursor: 10,
    }
    const w = selectCurrentWorld(s)
    // Should return last available world (index 2), not crash
    expect(w).not.toBeNull()
    expect(w!.tick).toBe(fixtureWorlds[2].tick)
  })
})

describe('judgeStartIndex', () => {
  it('prefers the first tick with a ruling and an accepted or rejected action', () => {
    const ticks: TickRecord[] = fixtureTicks.map((tick) => ({
      ...tick,
      rulings: [],
      accepted: [],
      rejected: [],
      events: [],
    }))
    ticks[1] = { ...ticks[1], events: [{ event_id: 'e1', tick: 1, kind: 'mission_spawned', payload: {} }] }
    ticks[2] = {
      ...ticks[2],
      rulings: [{ proposal_id: 'p1', accepted: true, decided_by: 'kernel', reason: 'priority' }],
      accepted: [{ decision_id: 'd1', agent_id: 'medical', decision_type: 'dispatch', params: {}, rationale: '' }],
    }
    expect(judgeStartIndex(ticks)).toBe(2)
  })

  it('falls back to protocol activity, then a world event, then zero', () => {
    const empty: TickRecord[] = fixtureTicks.map((tick) => ({
      ...tick,
      rulings: [],
      accepted: [],
      rejected: [],
      events: [],
    }))
    const withEvent = empty.map((tick) => ({ ...tick }))
    withEvent[1] = {
      ...withEvent[1],
      events: [{ event_id: 'e1', tick: 1, kind: 'mission_spawned', payload: {} }],
    }
    expect(judgeStartIndex(withEvent)).toBe(1)
    expect(judgeStartIndex(empty)).toBe(0)
    expect(judgeStartIndex([])).toBe(0)
  })
})
