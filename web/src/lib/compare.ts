/**
 * Compare-mode pure logic (no React, no side-effects).
 *
 * Compare mode replays two arms recorded on the same seed against a shared
 * *logical tick* (see timeline.ts `indexForTick` / `maxComparableTick` /
 * `selectRunningCost`). This module owns the cross-side derivations the
 * COMPARE surface renders — the per-side readout at the shared cursor and the
 * top-center delta strip — plus the small clamps the controller needs. All map
 * state still comes from `worlds[idx]`; nothing here folds events on the client.
 */
import type { RunSummary, TickRecord, WorldState } from '../types'
import { ARM_COLORS } from './palette'
import {
  indexForTick,
  maxComparableTick,
  selectRunningCost,
} from './timeline'

// ---- Shared controller ----

/** The single shared compare controller. The two timelineReducer instances are
 *  mirrored from this — `cursorTick` is the LOGICAL tick, not an array index. */
export interface CompareController {
  leftRunId: string | null
  rightRunId: string | null
  cursorTick: number
  playing: boolean
  speed: number
}

export const initialController: CompareController = {
  leftRunId: null,
  rightRunId: null,
  cursorTick: 0,
  playing: false,
  speed: 1,
}

// ---- Per-side readout at the shared cursor ----

/** The world + open/resolved counts a side shows at the shared logical tick. */
export interface SideReadout {
  index: number
  world: WorldState | null
  livesSaved: number
  livesLost: number
  panic: number
  open: number
  resolved: number
  failed: number
  cost: number
}

function countStatuses(world: WorldState | null): {
  open: number
  resolved: number
  failed: number
} {
  let open = 0
  let resolved = 0
  let failed = 0
  if (world) {
    for (const m of Object.values(world.missions)) {
      if (m.status === 'open') open++
      else if (m.status === 'resolved') resolved++
      else if (m.status === 'failed') failed++
    }
  }
  return { open, resolved, failed }
}

/**
 * Derive a side's readout at the shared logical `cursorTick`. The array index
 * comes from `indexForTick` (exact match, else the last record ≤ cursor, so a
 * short side holds its final frame). Lives / panic come from `worlds[idx]`;
 * cost is the cumulative model spend through that index.
 */
export function deriveSide(
  ticks: TickRecord[],
  worlds: WorldState[] | null,
  cursorTick: number,
): SideReadout {
  const index = indexForTick(ticks, cursorTick)
  const world =
    worlds && worlds.length > 0 ? worlds[Math.min(index, worlds.length - 1)] ?? null : null
  const { open, resolved, failed } = countStatuses(world)
  return {
    index,
    world,
    livesSaved: world?.lives_saved ?? 0,
    livesLost: world?.lives_lost ?? 0,
    panic: world?.panic ?? 0,
    open,
    resolved,
    failed,
    cost: selectRunningCost(ticks, index),
  }
}

// ---- Delta strip ----

export type DeltaWinner = 'left' | 'right' | 'tie'

export interface DeltaMetric {
  /** left − right. */
  delta: number
  left: number
  right: number
  /** Which side this metric favours, given whether higher is better. */
  winner: DeltaWinner
}

export interface DeltaStrip {
  livesSaved: DeltaMetric
  livesLost: DeltaMetric
  panic: DeltaMetric
  open: DeltaMetric
  resolved: DeltaMetric
  cost: DeltaMetric
}

/** Build one metric. `higherIsBetter` flips winner attribution for "bad"
 *  metrics (lost / panic / open / cost — lower wins). */
function metric(left: number, right: number, higherIsBetter: boolean): DeltaMetric {
  const delta = left - right
  let winner: DeltaWinner = 'tie'
  if (delta !== 0) {
    const leftWins = higherIsBetter ? delta > 0 : delta < 0
    winner = leftWins ? 'left' : 'right'
  }
  return { delta, left, right, winner }
}

/** The five+1 delta readouts (each `left − right`), winner-attributed. Lives
 *  saved / resolved: higher wins. Lost / panic / open / cost: lower wins. */
export function computeDeltaStrip(left: SideReadout, right: SideReadout): DeltaStrip {
  return {
    livesSaved: metric(left.livesSaved, right.livesSaved, true),
    livesLost: metric(left.livesLost, right.livesLost, false),
    panic: metric(left.panic, right.panic, false),
    open: metric(left.open, right.open, false),
    resolved: metric(left.resolved, right.resolved, true),
    cost: metric(left.cost, right.cost, false),
  }
}

// ---- Arm coding for the delta strip ----

/** Map a run's arm to its compare color: `society` → cyan, every baseline
 *  (swarm/solo/scripted) → amber. Used to tint the winning side of a metric. */
export function armColor(arm: string | undefined): string {
  return arm === 'society' ? ARM_COLORS.society : ARM_COLORS.baseline
}

/** The hex color a metric's value should take, given the two sides' arms and
 *  which side won. A tie is neutral (caller supplies its own neutral class). */
export function winnerColor(
  winner: DeltaWinner,
  leftArm: string | undefined,
  rightArm: string | undefined,
): string | null {
  if (winner === 'left') return armColor(leftArm)
  if (winner === 'right') return armColor(rightArm)
  return null
}

// ---- Controller clamps & paging ----

/** The shared end-of-playback tick for the two loaded sides. Play stops here. */
export function compareEndTick(left: TickRecord[], right: TickRecord[]): number {
  return maxComparableTick(left, right)
}

/**
 * Whether a side is "under-paged" for the given logical cursor: it still has
 * more records to load from the server AND the cursor is at/over the last
 * record it currently holds. Compare pauses and auto-loads the next page in
 * that case so playback never stalls mid-run.
 */
export function sideUnderPaged(
  ticks: TickRecord[],
  loadedTotal: number,
  serverTotal: number,
  cursorTick: number,
): boolean {
  if (loadedTotal >= serverTotal) return false
  if (ticks.length === 0) return true
  const lastTick = ticks[ticks.length - 1].tick
  return cursorTick >= lastTick
}

/** Both runs must have world data — two-map replay is only meaningful with it.
 *  Returns the runs lacking it (for a precise notice), empty when both are ok. */
export function worldlessRuns(
  left: RunSummary | undefined,
  right: RunSummary | undefined,
): RunSummary[] {
  const missing: RunSummary[] = []
  if (left && left.has_world === false) missing.push(left)
  if (right && right.has_world === false) missing.push(right)
  return missing
}

/** A compact per-side run header label: `SOCIETY · seed 42 · T31`. The tick is
 *  the side's loaded length endpoint (final tick number it holds). */
export function sideHeaderLabel(run: RunSummary | undefined, finalTick: number): string {
  if (!run) return '—'
  return `${run.arm.toUpperCase()} · seed ${run.seed} · T${finalTick}`
}
