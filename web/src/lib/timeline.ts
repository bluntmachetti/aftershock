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
