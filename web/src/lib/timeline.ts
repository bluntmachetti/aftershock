/**
 * Timeline reducer + selectors.
 * Pure functions — no side-effects, no imports from React.
 * All state needed by the scrubber and map view.
 */

import type { TimelineState, TickRecord, WorldState } from '../types'

// ---- Action types ----

export type TimelineAction =
  | { type: 'LOAD_RUN'; runId: string; hasWorld: boolean; total: number }
  | { type: 'APPEND_TICKS'; ticks: TickRecord[]; worlds: WorldState[] | null; total: number }
  | { type: 'SET_CURSOR'; cursor: number }
  | { type: 'PLAY' }
  | { type: 'PAUSE' }
  | { type: 'SET_SPEED'; speed: number }
  | { type: 'LIVE_TICK'; tick: TickRecord; world: WorldState | null }
  | { type: 'RESET' }
  | { type: 'SET_LOADING'; loading: boolean }
  | { type: 'SET_ERROR'; error: string | null }

// ---- Initial state ----

export const initialTimelineState: TimelineState = {
  runId: null,
  ticks: [],
  worlds: null,
  total: 0,
  hasWorld: false,
  cursor: 0,
  playing: false,
  speed: 1,
  loading: false,
  error: null,
}

// ---- Reducer ----

export function timelineReducer(
  state: TimelineState,
  action: TimelineAction,
): TimelineState {
  switch (action.type) {
    case 'LOAD_RUN':
      return {
        ...initialTimelineState,
        runId: action.runId,
        hasWorld: action.hasWorld,
        total: action.total,
        loading: true,
      }

    case 'APPEND_TICKS': {
      const newTicks = [...state.ticks, ...action.ticks]
      const newWorlds =
        action.worlds != null
          ? [...(state.worlds ?? []), ...action.worlds]
          : state.worlds
      return {
        ...state,
        ticks: newTicks,
        worlds: newWorlds,
        total: action.total,
        loading: false,
        error: null,
      }
    }

    case 'SET_CURSOR': {
      const max = Math.max(0, state.ticks.length - 1)
      const cursor = Math.max(0, Math.min(action.cursor, max))
      return { ...state, cursor }
    }

    case 'PLAY':
      return { ...state, playing: true }

    case 'PAUSE':
      return { ...state, playing: false }

    case 'SET_SPEED':
      return { ...state, speed: action.speed }

    case 'LIVE_TICK': {
      const newTicks = [...state.ticks, action.tick]
      const newWorlds =
        action.world != null
          ? [...(state.worlds ?? []), action.world]
          : state.worlds
      // Auto-advance cursor to latest
      const cursor = newTicks.length - 1
      return {
        ...state,
        ticks: newTicks,
        worlds: newWorlds,
        total: newTicks.length,
        cursor,
      }
    }

    case 'RESET':
      return initialTimelineState

    case 'SET_LOADING':
      return { ...state, loading: action.loading }

    case 'SET_ERROR':
      return { ...state, loading: false, error: action.error }

    default:
      return state
  }
}

// ---- Selectors ----

/** The world state at the current cursor position. */
export function selectCurrentWorld(state: TimelineState): WorldState | null {
  if (!state.worlds || state.worlds.length === 0) return null
  const idx = Math.min(state.cursor, state.worlds.length - 1)
  return state.worlds[idx] ?? null
}

/** The tick record at the current cursor position. */
export function selectCurrentTick(state: TimelineState): TickRecord | null {
  if (state.ticks.length === 0) return null
  const idx = Math.min(state.cursor, state.ticks.length - 1)
  return state.ticks[idx] ?? null
}

/** Whether more ticks are available to page-load beyond what we have. */
export function selectHasMore(state: TimelineState): boolean {
  return state.ticks.length < state.total
}

/** Max valid cursor value. */
export function selectMaxCursor(state: TimelineState): number {
  return Math.max(0, state.ticks.length - 1)
}

/** Advance cursor by 1, stop at end; returns new cursor. */
export function selectNextCursor(state: TimelineState): number {
  return Math.min(state.cursor + 1, selectMaxCursor(state))
}

/** Whether cursor is at the last loaded tick. */
export function selectAtEnd(state: TimelineState): boolean {
  return state.cursor >= selectMaxCursor(state)
}

// ---- Compare-mode helpers (additive; pure) ----
//
// Compare mode replays two arms on the same seed against a shared *logical tick*
// (not array index), because the two sides can differ in length / paging. These
// helpers translate a logical tick into a side-local array index and derive the
// cross-side readouts the COMPARE surface renders. None of them mutate state.

/**
 * The array index in `ticks` whose record corresponds to logical `tick`.
 * Exact match when a record with `record.tick === tick` exists; otherwise the
 * last record with `record.tick <= tick` (so a side holds its frame between
 * ticks it does not have). Returns 0 when `ticks` is empty or every record is
 * still in the future (the 0 floor — the first loaded frame).
 *
 * Assumes `ticks` is in ascending `.tick` order (the API pages them that way).
 */
export function indexForTick(ticks: TickRecord[], tick: number): number {
  if (ticks.length === 0) return 0
  let idx = 0
  for (let i = 0; i < ticks.length; i++) {
    const t = ticks[i].tick
    if (t === tick) return i
    if (t <= tick) idx = i
    else break
  }
  return idx
}

/**
 * The highest logical tick at which BOTH sides still have a record —
 * `min(last tick of a, last tick of b)`. Play stops here; the shorter side
 * then holds its final frame while the longer one finishes. Returns 0 when
 * either side is empty (nothing comparable yet).
 */
export function maxComparableTick(a: TickRecord[], b: TickRecord[]): number {
  if (a.length === 0 || b.length === 0) return 0
  const lastA = a[a.length - 1].tick
  const lastB = b[b.length - 1].tick
  return Math.min(lastA, lastB)
}

/**
 * Cumulative model spend from tick 0 through `cursor` (inclusive array index):
 * Σ over `ticks[0..cursor]` of every response's `usage?.cost_usd ?? 0`.
 * The zero-cost arms (scripted) and ticks with null usage contribute 0.
 * `cursor` is clamped into `[0, ticks.length - 1]`; an empty timeline is 0.
 */
export function selectRunningCost(ticks: TickRecord[], cursor: number): number {
  if (ticks.length === 0) return 0
  const end = Math.max(0, Math.min(cursor, ticks.length - 1))
  let sum = 0
  for (let i = 0; i <= end; i++) {
    for (const response of ticks[i].responses) {
      sum += response.usage?.cost_usd ?? 0
    }
  }
  return sum
}

// ---- Scrubber event markers ----

export type ScrubberEventKind = 'spawn' | 'inject' | 'resolve' | 'fail'

export interface ScrubberEvent {
  tick: number
  kind: ScrubberEventKind
  label?: string
}

/**
 * Notable moments to mark on the scrubber, derived purely from data the client
 * already has (no event-folding — provenance from `TickRecord.events`, outcomes
 * from world snapshots):
 *
 *  - `spawn`   — a `mission_spawned` event from the scenario timeline
 *                (payload.injected !== true).
 *  - `inject`  — any event whose payload carries `injected: true` (the spectator
 *                inject queue: injected mission spawns or road blocks).
 *  - `resolve` — a mission whose status transitions open → resolved between two
 *                adjacent world snapshots (attributed to the later tick).
 *  - `fail`    — a mission whose status transitions open → failed likewise.
 *
 * `worlds` is optional: with no world data, only spawn/inject markers (which come
 * from tick events) are produced. Markers are returned in ascending `(tick,
 * kind)` order, deduplicated on `(tick, kind, mission_id)`.
 */
export function deriveScrubberEvents(
  ticks: TickRecord[],
  worlds: WorldState[] | null,
): ScrubberEvent[] {
  const events: ScrubberEvent[] = []
  const seen = new Set<string>()

  const push = (tick: number, kind: ScrubberEventKind, key: string, label?: string) => {
    const dedupe = `${tick}|${kind}|${key}`
    if (seen.has(dedupe)) return
    seen.add(dedupe)
    events.push(label !== undefined ? { tick, kind, label } : { tick, kind })
  }

  // Spawn / inject markers from per-tick event provenance.
  for (const record of ticks) {
    for (const event of record.events) {
      const injected = event.payload?.injected === true
      if (injected) {
        const missionId =
          typeof event.payload?.mission_id === 'string'
            ? (event.payload.mission_id as string)
            : ''
        const districtId =
          typeof event.payload?.district_id === 'string'
            ? (event.payload.district_id as string)
            : ''
        const label = missionId || districtId || event.kind
        push(record.tick, 'inject', missionId || districtId || event.event_id, label)
      } else if (event.kind === 'mission_spawned') {
        const missionId =
          typeof event.payload?.mission_id === 'string'
            ? (event.payload.mission_id as string)
            : ''
        const missionKind =
          typeof event.payload?.mission_kind === 'string'
            ? (event.payload.mission_kind as string)
            : ''
        push(record.tick, 'spawn', missionId || event.event_id, missionKind || missionId || undefined)
      }
    }
  }

  // Resolve / fail markers from mission status transitions between adjacent worlds.
  if (worlds && worlds.length > 1) {
    for (let i = 1; i < worlds.length; i++) {
      const prev = worlds[i - 1].missions
      const curr = worlds[i].missions
      const tick = worlds[i].tick
      for (const id of Object.keys(curr)) {
        const before = prev[id]
        const after = curr[id]
        if (!before || before.status !== 'open') continue
        if (after.status === 'resolved') {
          push(tick, 'resolve', id, id)
        } else if (after.status === 'failed') {
          push(tick, 'fail', id, id)
        }
      }
    }
  }

  events.sort((x, y) => (x.tick - y.tick) || x.kind.localeCompare(y.kind))
  return events
}
