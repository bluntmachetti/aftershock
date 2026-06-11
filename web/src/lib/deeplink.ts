/**
 * Deep links — History API only (the app has no router).
 *
 * Two shapes, parsed once after `api.runs()` resolves so a token recipient can
 * land on an exact frame or a specific comparison:
 *
 *   ?run=<run_id>&t=<tick>
 *     select a single run, page until logical `tick` is loaded, set the cursor.
 *
 *   ?compare=<arm|run_id>,<arm|run_id>&seed=<n>&t=<tick>
 *     resolve both sides (by arm+seed, or exact run_ids), load both, set the
 *     shared logical `cursorTick`.
 *
 * Scrub/playback are reflected back into the URL via `history.replaceState`,
 * THROTTLED (>=250ms) so 8x playback never spams history. The writer preserves
 * every existing non-secret query param — `api.ts` already scrubbed `?token`
 * eagerly at module load, so whatever is still in `location.search` is safe to
 * round-trip.
 *
 * Pure parsing functions take an explicit `search` string + the resolved run
 * list so they are unit-testable without touching `window`. The reflector hook
 * is the only part that reaches for `window.history`.
 */
import { useEffect, useRef } from 'react'
import type { RunSummary } from '../types'

// ---- Parsed link shapes ----

export interface RunLink {
  kind: 'run'
  runId: string
  tick: number
}

export interface CompareLink {
  kind: 'compare'
  leftRunId: string
  rightRunId: string
  tick: number
}

export type DeepLink = RunLink | CompareLink

/** Parse a non-negative integer query param; null when absent/blank/invalid. */
function parseTick(raw: string | null): number {
  if (raw == null || raw.trim() === '') return 0
  const n = parseInt(raw, 10)
  return Number.isFinite(n) && n >= 0 ? n : 0
}

/**
 * Resolve one side of a compare link. A token is either an exact `run_id` (it
 * matches a run's id) or an arm name (`society`/`swarm`/`solo`/`scripted`),
 * resolved against `seed`. Returns the run_id, or null when nothing matches.
 * Prefers runs that have world data (compare needs it) and the newest match.
 */
function resolveToken(
  token: string,
  seed: number | null,
  runs: RunSummary[],
): string | null {
  const trimmed = token.trim()
  if (!trimmed) return null

  // Exact run_id match wins.
  const exact = runs.find((r) => r.run_id === trimmed)
  if (exact) return exact.run_id

  // Otherwise treat it as an arm name resolved by seed. `runs` is newest-first
  // from the API; prefer a world-bearing run, else the first arm+seed match.
  const matches = runs.filter(
    (r) => r.arm === trimmed && (seed == null || r.seed === seed),
  )
  if (matches.length === 0) return null
  const withWorld = matches.find((r) => r.has_world !== false)
  return (withWorld ?? matches[0]).run_id
}

/**
 * Parse the current query string into a deep link, resolving run/arm references
 * against the loaded run list. Returns null when the params describe no
 * actionable link (or references that don't resolve).
 *
 * `search` is `window.location.search` (with or without the leading `?`).
 */
export function parseDeepLink(
  search: string,
  runs: RunSummary[],
): DeepLink | null {
  const params = new URLSearchParams(
    search.startsWith('?') ? search.slice(1) : search,
  )

  const compareRaw = params.get('compare')
  if (compareRaw) {
    const parts = compareRaw.split(',').map((s) => s.trim()).filter(Boolean)
    if (parts.length >= 2) {
      const seedRaw = params.get('seed')
      const seed =
        seedRaw != null && seedRaw.trim() !== '' && Number.isFinite(parseInt(seedRaw, 10))
          ? parseInt(seedRaw, 10)
          : null
      const left = resolveToken(parts[0], seed, runs)
      const right = resolveToken(parts[1], seed, runs)
      if (left && right) {
        return { kind: 'compare', leftRunId: left, rightRunId: right, tick: parseTick(params.get('t')) }
      }
    }
    return null
  }

  const runRaw = params.get('run')
  if (runRaw) {
    const runId = resolveToken(runRaw, null, runs)
    if (runId) {
      return { kind: 'run', runId, tick: parseTick(params.get('t')) }
    }
  }

  return null
}

// ---- URL reflection (write side) ----

/**
 * Build the query string that reflects the given app state, PRESERVING any
 * existing non-secret params already on `search`. Only the deep-link keys
 * (`run`, `compare`, `seed`, `t`) are rewritten; everything else is kept as-is.
 * Returns the full `pathname + search` to hand to `history.replaceState`.
 */
export function buildReflectedUrl(
  pathname: string,
  search: string,
  state:
    | { kind: 'run'; runId: string; tick: number }
    | { kind: 'compare'; leftRunId: string; rightRunId: string; seed?: number; tick: number }
    | { kind: 'none' },
): string {
  const params = new URLSearchParams(
    search.startsWith('?') ? search.slice(1) : search,
  )

  // Clear the deep-link keys we own; leave foreign params untouched.
  params.delete('run')
  params.delete('compare')
  params.delete('seed')
  params.delete('t')

  if (state.kind === 'run') {
    params.set('run', state.runId)
    params.set('t', String(state.tick))
  } else if (state.kind === 'compare') {
    params.set('compare', `${state.leftRunId},${state.rightRunId}`)
    if (state.seed != null) params.set('seed', String(state.seed))
    params.set('t', String(state.tick))
  }

  const query = params.toString()
  return pathname + (query ? `?${query}` : '')
}

/**
 * Throttled `history.replaceState` reflector. Call with the latest app state;
 * the URL is rewritten at most once per `intervalMs` (default 250ms) so fast
 * playback doesn't spam history. A trailing write fires after the burst so the
 * final resting state is always reflected. No-ops when state is `none`.
 */
export function useUrlReflection(
  state:
    | { kind: 'run'; runId: string; tick: number }
    | { kind: 'compare'; leftRunId: string; rightRunId: string; seed?: number; tick: number }
    | { kind: 'none' },
  intervalMs = 250,
): void {
  const lastWriteRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Keep the freshest state in a ref so the trailing-edge timer writes it.
  const stateRef = useRef(state)
  stateRef.current = state

  useEffect(() => {
    if (state.kind === 'none') return

    const write = () => {
      lastWriteRef.current = Date.now()
      const url = buildReflectedUrl(
        window.location.pathname,
        window.location.search,
        stateRef.current,
      )
      window.history.replaceState(null, '', url)
    }

    const now = Date.now()
    const elapsed = now - lastWriteRef.current
    if (elapsed >= intervalMs) {
      write()
    } else if (timerRef.current == null) {
      // Schedule a trailing write for the remainder of the window.
      timerRef.current = setTimeout(() => {
        timerRef.current = null
        write()
      }, intervalMs - elapsed)
    }

    return () => {
      if (timerRef.current != null) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
    // Re-run whenever the reflected fields change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    state.kind,
    state.kind === 'run' ? state.runId : undefined,
    state.kind === 'run' ? state.tick : undefined,
    state.kind === 'compare' ? state.leftRunId : undefined,
    state.kind === 'compare' ? state.rightRunId : undefined,
    state.kind === 'compare' ? state.tick : undefined,
    intervalMs,
  ])
}
