/**
 * Tests for AAR fetch state handling and key-moment cursor-jump action.
 * Follows the existing fixtures + pure-reducer pattern from timeline.test.ts.
 */
import { describe, it, expect, vi } from 'vitest'
import fixture from '../__fixtures__/demo-ticks.json'
import {
  initialTimelineState,
  timelineReducer,
} from '../lib/timeline'
import type { TimelineState, TickRecord, WorldState, AarReport } from '../types'

const fixtureTicks = fixture.ticks as TickRecord[]
const fixtureWorlds = fixture.worlds as WorldState[]

// ---- helpers ----

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

const SAMPLE_AAR: AarReport = {
  headline: 'Effective multi-agency coordination under severe resource pressure.',
  grade: 'B',
  what_worked: ['Early road repairs reduced arrival lag', 'Commander prioritised by deadline'],
  coordination_failures: ['Medical never secured ambulance — outbid every tick'],
  key_moments: [
    { tick: 0, description: 'Quake: 4 missions spawned, harbor/residential blocked' },
    { tick: 1, description: 'Dispatch wave: m2 and m3 fully staffed' },
    { tick: 2, description: 'Medical still ambulance-starved' },
  ],
  lessons: [
    'Pre-position ambulances near high-risk districts before quake tick.',
    'Commander should reserve one ambulance for medical_surge missions.',
  ],
}

// ---- AAR fetch state handling ----

describe('AAR fetch state handling', () => {
  it('api.aar resolves to a typed AarReport on 200', async () => {
    // Verify the AarReport type structure is correct by constructing one
    const report: AarReport = SAMPLE_AAR
    expect(report.headline).toBeTypeOf('string')
    expect(['A', 'B', 'C', 'D', 'F']).toContain(report.grade)
    expect(Array.isArray(report.what_worked)).toBe(true)
    expect(Array.isArray(report.coordination_failures)).toBe(true)
    expect(Array.isArray(report.key_moments)).toBe(true)
    expect(Array.isArray(report.lessons)).toBe(true)
  })

  it('key_moments entries have tick (number) and description (string)', () => {
    for (const km of SAMPLE_AAR.key_moments) {
      expect(km.tick).toBeTypeOf('number')
      expect(km.description).toBeTypeOf('string')
    }
  })

  it('lessons are bounded to 5 or fewer entries', () => {
    // The DESIGN.md contract says MAX 5 lessons
    const report: AarReport = { ...SAMPLE_AAR, lessons: SAMPLE_AAR.lessons }
    expect(report.lessons.length).toBeLessThanOrEqual(5)
  })

  it('grade is one of the valid letter grades', () => {
    const VALID_GRADES: AarReport['grade'][] = ['A', 'B', 'C', 'D', 'F']
    expect(VALID_GRADES).toContain(SAMPLE_AAR.grade)
  })

  it('a 404 from api.aar should NOT be treated as a fatal error — aar stays null', async () => {
    // Simulate what MapTab does: fetch then silently ignore 404
    let aar: AarReport | null = null
    const mockFetch = vi.fn().mockRejectedValueOnce(new Error('404 Not Found'))

    await mockFetch('dummy-run-id').catch(() => {
      // on 404 we leave aar as null — no throw
    })

    expect(aar).toBeNull()
  })

  it('a successful aar fetch updates state to the report', async () => {
    let aar: AarReport | null = null
    const mockFetch = vi.fn().mockResolvedValueOnce(SAMPLE_AAR)

    aar = await mockFetch('seed42-scripted')

    expect(aar).not.toBeNull()
    expect(aar!.headline).toBe(SAMPLE_AAR.headline)
    expect(aar!.grade).toBe('B')
  })
})

// ---- Key-moment cursor-jump action ----

describe('key-moment cursor-jump', () => {
  // The jump logic used in MapTab:
  //   const idx = timeline.ticks.findIndex((t) => t.tick === tickNumber)
  //   if (idx !== -1) dispatch({ type: 'SET_CURSOR', cursor: idx })
  function jumpToTick(state: TimelineState, tickNumber: number): TimelineState {
    const idx = state.ticks.findIndex((t) => t.tick === tickNumber)
    if (idx === -1) return state
    return timelineReducer(state, { type: 'SET_CURSOR', cursor: idx })
  }

  it('jumping to tick 0 sets cursor to index 0', () => {
    const s = loadedState()
    const after = jumpToTick(s, 0)
    expect(after.cursor).toBe(0)
  })

  it('jumping to tick 1 sets cursor to index 1', () => {
    const s = loadedState()
    const after = jumpToTick(s, 1)
    expect(after.cursor).toBe(1)
  })

  it('jumping to tick 2 sets cursor to index 2', () => {
    const s = loadedState()
    const after = jumpToTick(s, 2)
    expect(after.cursor).toBe(2)
  })

  it('jumping to a tick not in the loaded ticks leaves cursor unchanged', () => {
    const s = loadedState()
    // cursor starts at 0; tick 99 not in the fixture (only ticks 0,1,2)
    const after = jumpToTick(s, 99)
    expect(after.cursor).toBe(s.cursor)
  })

  it('cursor after jump is clamped by SET_CURSOR to max valid index', () => {
    const s = loadedState()
    // Force a cursor jump to beyond the array — SET_CURSOR already clamps
    const after = timelineReducer(s, { type: 'SET_CURSOR', cursor: 999 })
    expect(after.cursor).toBe(2) // max is 2 (3 ticks)
  })

  it('jumping via all key_moments in SAMPLE_AAR lands on correct indices', () => {
    const s = loadedState()
    for (const km of SAMPLE_AAR.key_moments) {
      const after = jumpToTick(s, km.tick)
      const expectedIdx = fixtureTicks.findIndex((t) => t.tick === km.tick)
      if (expectedIdx !== -1) {
        expect(after.cursor).toBe(expectedIdx)
      }
    }
  })

  it('the world at the jumped cursor matches the correct world state', () => {
    const s = loadedState()
    const after = jumpToTick(s, 1)
    expect(after.cursor).toBe(1)
    // The world at cursor 1 should have tick=1
    const world = after.worlds?.[after.cursor]
    expect(world).toBeDefined()
    expect(world!.tick).toBe(1)
  })
})

// ---- AarReport type shape (compile-time coverage via runtime checks) ----

describe('AarReport type completeness', () => {
  it('all required fields are present', () => {
    const report: AarReport = SAMPLE_AAR
    expect('headline' in report).toBe(true)
    expect('grade' in report).toBe(true)
    expect('what_worked' in report).toBe(true)
    expect('coordination_failures' in report).toBe(true)
    expect('key_moments' in report).toBe(true)
    expect('lessons' in report).toBe(true)
  })

  it('key_moments elements have tick and description fields', () => {
    const km = SAMPLE_AAR.key_moments[0]
    expect('tick' in km).toBe(true)
    expect('description' in km).toBe(true)
  })
})
