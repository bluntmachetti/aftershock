import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import type { RunSummary } from '../types'
import {
  timelineReducer,
  initialTimelineState,
  indexForTick,
} from '../lib/timeline'
import {
  type CompareController,
  type DeltaMetric,
  type SideReadout,
  initialController,
  deriveSide,
  computeDeltaStrip,
  compareEndTick,
  sideUnderPaged,
  worldlessRuns,
  winnerColor,
} from '../lib/compare'
import { usePlaybackClock as useSharedClock } from '../lib/usePlaybackClock'
import { ARM_COLORS } from '../lib/palette'
import { api } from '../lib/api'
import { TownMap } from './TownMap'

const PAGE = 100 // larger page in compare so 8× playback never stalls mid-run
const SPEEDS = [0.5, 1, 2, 4, 8]
// Scrubber accent — the baseline (amber) signal color, sourced from palette.ts
// so no #rrggbb literal lives in this .tsx (design DoD).
const SCRUB_ACCENT = ARM_COLORS.baseline

interface Props {
  runs: RunSummary[]
  initialLeft?: string
  initialRight?: string
  cursorTick?: number
  onStateChange?: (s: CompareController) => void
}

/**
 * COMPARE — side-by-side synced replay of two arms on the same seed.
 *
 * Two independent `timelineReducer` instances are mirrored from one shared
 * controller (`{leftRunId,rightRunId,cursorTick,playing,speed}`) on the shared
 * LOGICAL tick. A single `usePlaybackClock` drives the cursor; playback stops at
 * the shared `compareEndTick` (the shorter side's last tick), and each map
 * freezes on its last available frame past its own end. Fully self-contained —
 * App only feeds it `runs` + optional deep-link seeds.
 */
export function CompareTab({
  runs,
  initialLeft,
  initialRight,
  cursorTick,
  onStateChange,
}: Props) {
  const [left, dispatchLeft] = useReducer(timelineReducer, initialTimelineState)
  const [right, dispatchRight] = useReducer(timelineReducer, initialTimelineState)
  const [controller, setController] = useState<CompareController>({
    ...initialController,
    leftRunId: initialLeft ?? null,
    rightRunId: initialRight ?? null,
    cursorTick: cursorTick ?? 0,
  })

  const runById = useMemo(() => {
    const m = new Map<string, RunSummary>()
    for (const r of runs) m.set(r.run_id, r)
    return m
  }, [runs])

  const leftRun = controller.leftRunId ? runById.get(controller.leftRunId) : undefined
  const rightRun = controller.rightRunId ? runById.get(controller.rightRunId) : undefined

  // ---- Loaders (page size 100) ----

  const loadSide = useCallback(
    async (
      runId: string,
      dispatch: React.Dispatch<Parameters<typeof timelineReducer>[1]>,
    ) => {
      try {
        const detail = await api.run(runId).catch(() => undefined)
        const hasWorld = detail?.has_world ?? false
        const total = detail?.ticks ?? 0
        dispatch({ type: 'LOAD_RUN', runId, hasWorld, total })
        const page = await api.ticks(runId, 0, PAGE)
        dispatch({
          type: 'APPEND_TICKS',
          ticks: page.ticks,
          worlds: page.worlds,
          total: page.total,
        })
      } catch (e) {
        dispatch({ type: 'SET_ERROR', error: e instanceof Error ? e.message : String(e) })
      }
    },
    [],
  )

  const loadMoreSide = useCallback(
    async (
      runId: string,
      loadedCount: number,
      dispatch: React.Dispatch<Parameters<typeof timelineReducer>[1]>,
    ) => {
      dispatch({ type: 'SET_LOADING', loading: true })
      try {
        const page = await api.ticks(runId, loadedCount, PAGE)
        dispatch({
          type: 'APPEND_TICKS',
          ticks: page.ticks,
          worlds: page.worlds,
          total: page.total,
        })
      } catch (e) {
        dispatch({ type: 'SET_ERROR', error: e instanceof Error ? e.message : String(e) })
      }
    },
    [],
  )

  // Load left / right when their run id changes.
  useEffect(() => {
    if (controller.leftRunId) void loadSide(controller.leftRunId, dispatchLeft)
  }, [controller.leftRunId, loadSide])

  useEffect(() => {
    if (controller.rightRunId) void loadSide(controller.rightRunId, dispatchRight)
  }, [controller.rightRunId, loadSide])

  // ---- Mirror the shared LOGICAL cursor into both reducers ----
  useEffect(() => {
    dispatchLeft({ type: 'SET_CURSOR', cursor: indexForTick(left.ticks, controller.cursorTick) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controller.cursorTick, left.ticks])

  useEffect(() => {
    dispatchRight({ type: 'SET_CURSOR', cursor: indexForTick(right.ticks, controller.cursorTick) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controller.cursorTick, right.ticks])

  // Surface controller changes to the integration layer (deep-link reflection).
  useEffect(() => {
    onStateChange?.(controller)
  }, [controller, onStateChange])

  // ---- The single shared clock ----
  const endTick = compareEndTick(left.ticks, right.ticks)
  // Keep the freshest paging facts in a ref so the tick callback stays stable.
  const pagingRef = useRef({ left, right, controller, endTick })
  pagingRef.current = { left, right, controller, endTick }

  const onTick = useCallback(() => {
    const { left: l, right: r, controller: c, endTick: end } = pagingRef.current
    const next = c.cursorTick + 1

    // Pause + auto-load any under-paged side before stepping past its data.
    const leftShort =
      c.leftRunId != null &&
      sideUnderPaged(l.ticks, l.ticks.length, l.total, next) &&
      l.ticks.length < l.total
    const rightShort =
      c.rightRunId != null &&
      sideUnderPaged(r.ticks, r.ticks.length, r.total, next) &&
      r.ticks.length < r.total
    if (leftShort || rightShort) {
      setController((s) => ({ ...s, playing: false }))
      if (leftShort && c.leftRunId) void loadMoreSide(c.leftRunId, l.ticks.length, dispatchLeft)
      if (rightShort && c.rightRunId) void loadMoreSide(c.rightRunId, r.ticks.length, dispatchRight)
      return
    }

    if (next > end) {
      setController((s) => ({ ...s, playing: false }))
      return
    }
    setController((s) => ({ ...s, cursorTick: next }))
  }, [loadMoreSide])

  // Single timer for both sides (never two intervals).
  useSharedClock(controller.playing, controller.speed, onTick)

  // ---- Controls ----
  const togglePlay = () =>
    setController((s) => ({ ...s, playing: !s.playing && s.cursorTick < endTick }))
  const cycleSpeed = () =>
    setController((s) => {
      const idx = SPEEDS.indexOf(s.speed)
      return { ...s, speed: SPEEDS[(idx + 1) % SPEEDS.length] }
    })
  const scrub = (tick: number) =>
    setController((s) => ({ ...s, cursorTick: Math.max(0, Math.min(tick, endTick)), playing: false }))

  // ---- Derived readouts ----
  const leftSide = useMemo(
    () => deriveSide(left.ticks, left.worlds, controller.cursorTick),
    [left.ticks, left.worlds, controller.cursorTick],
  )
  const rightSide = useMemo(
    () => deriveSide(right.ticks, right.worlds, controller.cursorTick),
    [right.ticks, right.worlds, controller.cursorTick],
  )
  const delta = useMemo(() => computeDeltaStrip(leftSide, rightSide), [leftSide, rightSide])

  const bothSelected = controller.leftRunId != null && controller.rightRunId != null
  const worldless = worldlessRuns(leftRun, rightRun)
  // Compare is "two arms on the SAME seed". If the picker landed on mismatched
  // seeds the deltas compare unrelated scenarios — warn, but don't block.
  const seedsDiffer =
    leftRun != null && rightRun != null && leftRun.seed !== rightRun.seed

  // ---- Guards / pickers ----
  if (!bothSelected) {
    return <ComparePicker runs={runs} controller={controller} setController={setController} />
  }

  if (worldless.length > 0) {
    return (
      <div className="flex flex-col h-full">
        <ComparePicker runs={runs} controller={controller} setController={setController} compact />
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="max-w-md rounded-lg border border-signal-red/40 bg-eoc-surface p-4 text-center">
            <div className="text-xs font-semibold text-signal-red">Compare needs world data</div>
            <p className="mt-2 text-[11px] text-eoc-secondary leading-relaxed">
              {worldless.map((r) => r.run_id).join(' and ')}{' '}
              {worldless.length > 1 ? 'were' : 'was'} recorded without world snapshots, so the
              two-map replay would be empty. Pick runs that have world data.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Seeds-differ warning — deltas across unrelated scenarios are not
          comparable, so flag it without blocking the replay. */}
      {seedsDiffer && (
        <div className="border-b border-signal-amber/40 bg-signal-amber/10 px-4 py-1 text-center text-[11px] font-semibold text-signal-amber">
          Seeds differ (s{leftRun?.seed} vs s{rightRun?.seed}) — deltas not comparable
        </div>
      )}

      {/* Top-center delta strip — the hero readout */}
      <DeltaStripView
        delta={delta}
        leftArm={leftRun?.arm}
        rightArm={rightRun?.arm}
      />

      {/* Two maps with per-side headers */}
      <div className="flex flex-1 overflow-hidden">
        <SidePanel
          run={leftRun}
          side={leftSide}
          align="left"
        />
        <div className="w-px bg-eoc-border shrink-0" />
        <SidePanel
          run={rightRun}
          side={rightSide}
          align="right"
        />
      </div>

      {/* Shared control bar */}
      <CompareControls
        controller={controller}
        endTick={endTick}
        leftError={left.error}
        rightError={right.error}
        onTogglePlay={togglePlay}
        onCycleSpeed={cycleSpeed}
        onScrub={scrub}
      />
    </div>
  )
}

// ---- Run pickers ----

interface PickerProps {
  runs: RunSummary[]
  controller: CompareController
  setController: React.Dispatch<React.SetStateAction<CompareController>>
  compact?: boolean
}

function ComparePicker({ runs, controller, setController, compact }: PickerProps) {
  const setLeft = (id: string) =>
    setController((s) => ({ ...s, leftRunId: id, cursorTick: 0, playing: false }))
  const setRight = (id: string) =>
    setController((s) => ({ ...s, rightRunId: id, cursorTick: 0, playing: false }))

  const body = (
    <div className="flex gap-4">
      <RunColumn
        label="LEFT"
        runs={runs}
        selectedId={controller.leftRunId}
        otherId={controller.rightRunId}
        onSelect={setLeft}
      />
      <RunColumn
        label="RIGHT"
        runs={runs}
        selectedId={controller.rightRunId}
        otherId={controller.leftRunId}
        onSelect={setRight}
      />
    </div>
  )

  if (compact) {
    return <div className="border-b border-eoc-border bg-eoc-ground px-4 py-3">{body}</div>
  }

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-6">
      <div className="text-[11px] font-semibold uppercase tracking-widest text-eoc-secondary">
        Compare two arms · same seed
      </div>
      {body}
      <p className="max-w-md text-center text-[11px] text-eoc-secondary leading-relaxed">
        Pick a society run and a baseline (swarm/solo) on the same seed to replay them side by
        side and read the deltas live.
      </p>
    </div>
  )
}

interface RunColumnProps {
  label: string
  runs: RunSummary[]
  selectedId: string | null
  otherId: string | null
  onSelect: (id: string) => void
}

function RunColumn({ label, runs, selectedId, otherId, onSelect }: RunColumnProps) {
  return (
    <div className="flex w-56 flex-col gap-1">
      <div className="mb-1 text-[10px] font-mono uppercase tracking-widest text-eoc-secondary">
        {label}
      </div>
      <div className="flex max-h-64 flex-col gap-1 overflow-y-auto">
        {runs.map((run) => {
          const selected = selectedId === run.run_id
          const disabled = otherId === run.run_id
          const color = run.arm === 'society' ? 'text-signal-cyan' : 'text-signal-amber'
          return (
            <button
              key={run.run_id}
              onClick={() => onSelect(run.run_id)}
              disabled={disabled}
              className={`flex items-center gap-2 rounded border px-2 py-1.5 text-left transition-colors disabled:opacity-30 ${
                selected
                  ? 'border-eoc-secondary bg-eoc-raised'
                  : 'border-eoc-border hover:border-eoc-secondary/60'
              }`}
            >
              <span className={`shrink-0 text-[11px] font-semibold ${color}`}>
                {run.arm.toUpperCase()}
              </span>
              <span className="flex-1 truncate text-[11px] text-eoc-primary">{run.run_id}</span>
              <span className="shrink-0 text-[10px] tabular-nums text-eoc-secondary">
                s{run.seed}/{run.ticks}t
              </span>
              {run.has_world === false && (
                <span className="shrink-0 text-[10px] text-eoc-secondary">no-world</span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ---- Per-side map panel ----

interface SidePanelProps {
  run: RunSummary | undefined
  side: SideReadout
  align: 'left' | 'right'
}

function SidePanel({ run, side, align }: SidePanelProps) {
  const finalTick = side.world?.tick ?? 0
  const armColorClass = run?.arm === 'society' ? 'text-signal-cyan' : 'text-signal-amber'
  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Run header — SOCIETY · seed 42 · T31 */}
      <div
        className={`flex items-center gap-2 border-b border-eoc-border bg-eoc-surface px-3 py-1.5 ${
          align === 'right' ? 'flex-row-reverse text-right' : ''
        }`}
      >
        <span className={`text-xs font-semibold ${armColorClass}`}>
          {run?.arm.toUpperCase() ?? '—'}
        </span>
        <span className="text-[11px] tabular-nums text-eoc-secondary">
          {run ? `seed ${run.seed} · T${finalTick}` : '—'}
        </span>
      </div>

      {/* Map — quiet effects in compare (no scanlines/animated rings competing) */}
      <div className="relative flex-1 overflow-hidden">
        {side.world ? (
          <TownMap
            world={side.world}
            selectedMissionId={null}
            onSelectMission={() => {}}
            effects="quiet"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-[11px] text-eoc-secondary">
            Loading…
          </div>
        )}
      </div>

      {/* Per-side totals footer */}
      <div className="flex items-center gap-4 border-t border-eoc-border bg-eoc-surface px-3 py-1.5 text-[11px] tabular-nums">
        <SideStat label="saved" value={side.livesSaved} className="text-signal-green" />
        <SideStat label="lost" value={side.livesLost} className="text-signal-red" />
        <SideStat label="open" value={side.open} className="text-signal-amber" />
        <SideStat label="panic" value={side.panic.toFixed(2)} className="text-eoc-primary" />
        <SideStat
          label="cost"
          value={side.cost > 0 ? `$${side.cost.toFixed(3)}` : '$0'}
          className="text-eoc-secondary"
        />
      </div>
    </div>
  )
}

function SideStat({
  label,
  value,
  className,
}: {
  label: string
  value: number | string
  className: string
}) {
  return (
    <div className="flex flex-col leading-tight">
      <span className={`text-sm font-semibold ${className}`}>{value}</span>
      <span className="text-[10px] text-eoc-secondary">{label}</span>
    </div>
  )
}

// ---- Delta strip ----

interface DeltaStripViewProps {
  delta: ReturnType<typeof computeDeltaStrip>
  leftArm: string | undefined
  rightArm: string | undefined
}

function DeltaStripView({ delta, leftArm, rightArm }: DeltaStripViewProps) {
  return (
    <div className="flex items-stretch justify-center gap-6 border-b border-eoc-border bg-eoc-ground px-4 py-2">
      {/* Dominant LIVES-SAVED pair */}
      <HeroDelta metric={delta.livesSaved} leftArm={leftArm} rightArm={rightArm} />
      <div className="my-1 w-px bg-eoc-border" />
      <div className="flex items-center gap-5">
        <DeltaCell label="Δ lost" metric={delta.livesLost} leftArm={leftArm} rightArm={rightArm} invertGood />
        <DeltaCell label="Δ panic" metric={delta.panic} leftArm={leftArm} rightArm={rightArm} invertGood fixed={2} />
        <DeltaCell label="Δ open" metric={delta.open} leftArm={leftArm} rightArm={rightArm} invertGood />
        <DeltaCell label="Δ resolved" metric={delta.resolved} leftArm={leftArm} rightArm={rightArm} />
        <DeltaCell label="Δ cost" metric={delta.cost} leftArm={leftArm} rightArm={rightArm} invertGood money />
      </div>
    </div>
  )
}

function formatDelta(d: number, opts: { fixed?: number; money?: boolean }): string {
  const sign = d > 0 ? '+' : d < 0 ? '−' : ''
  const abs = Math.abs(d)
  const body = opts.money
    ? `$${abs.toFixed(3)}`
    : opts.fixed != null
      ? abs.toFixed(opts.fixed)
      : String(abs)
  return `${sign}${body}`
}

function HeroDelta({
  metric,
  leftArm,
  rightArm,
}: {
  metric: DeltaMetric
  leftArm: string | undefined
  rightArm: string | undefined
}) {
  const color = winnerColor(metric.winner, leftArm, rightArm)
  return (
    <div className="flex flex-col items-center justify-center px-2">
      <div className="flex items-baseline gap-3">
        <span
          className="text-2xl font-bold tabular-nums"
          style={color ? { color } : undefined}
        >
          {formatDelta(metric.delta, {})}
        </span>
        <span className="text-[11px] tabular-nums text-eoc-secondary">
          {metric.left} <span className="text-eoc-faint">vs</span> {metric.right}
        </span>
      </div>
      <span className="text-[10px] font-semibold uppercase tracking-widest text-eoc-secondary">
        lives saved (L − R)
      </span>
    </div>
  )
}

function DeltaCell({
  label,
  metric,
  leftArm,
  rightArm,
  invertGood,
  fixed,
  money,
}: {
  label: string
  metric: DeltaMetric
  leftArm: string | undefined
  rightArm: string | undefined
  invertGood?: boolean
  fixed?: number
  money?: boolean
}) {
  // winner is already correctly attributed by computeDeltaStrip per metric;
  // invertGood is only a documentation hint here (the math lives in compare.ts).
  void invertGood
  const color = winnerColor(metric.winner, leftArm, rightArm)
  return (
    <div className="flex flex-col items-center leading-tight">
      <span
        className="text-sm font-semibold tabular-nums"
        style={color ? { color } : undefined}
      >
        {formatDelta(metric.delta, { fixed, money })}
      </span>
      <span className="text-[10px] text-eoc-secondary">{label}</span>
    </div>
  )
}

// ---- Shared control bar ----

interface CompareControlsProps {
  controller: CompareController
  endTick: number
  leftError: string | null
  rightError: string | null
  onTogglePlay: () => void
  onCycleSpeed: () => void
  onScrub: (tick: number) => void
}

function CompareControls({
  controller,
  endTick,
  leftError,
  rightError,
  onTogglePlay,
  onCycleSpeed,
  onScrub,
}: CompareControlsProps) {
  const error = leftError ?? rightError
  return (
    <div className="flex flex-col">
      {error && (
        <div className="border-t border-signal-red/40 bg-eoc-surface px-3 py-1 text-[11px] text-signal-red">
          {error}
        </div>
      )}
      <div className="flex items-center gap-3 border-t border-eoc-border bg-eoc-surface px-3 py-2">
        <button
          onClick={onTogglePlay}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-eoc-raised text-signal-amber transition-colors hover:bg-eoc-border"
          aria-label={controller.playing ? 'Pause' : 'Play'}
        >
          {controller.playing ? (
            <svg viewBox="0 0 16 16" fill="currentColor" className="h-3 w-3">
              <rect x="3" y="2" width="3.5" height="12" rx="1" />
              <rect x="9.5" y="2" width="3.5" height="12" rx="1" />
            </svg>
          ) : (
            <svg viewBox="0 0 16 16" fill="currentColor" className="h-3 w-3">
              <path d="M4 2.5l10 5.5-10 5.5V2.5z" />
            </svg>
          )}
        </button>

        <button
          onClick={onCycleSpeed}
          className="w-8 shrink-0 text-center text-xs tabular-nums text-eoc-secondary transition-colors hover:text-signal-amber"
          aria-label="Cycle speed"
        >
          {controller.speed}×
        </button>

        <input
          type="range"
          min={0}
          max={Math.max(0, endTick)}
          value={Math.min(controller.cursorTick, endTick)}
          onChange={(e) => onScrub(parseInt(e.target.value, 10))}
          className="h-1 flex-1 cursor-pointer"
          style={{ accentColor: SCRUB_ACCENT }}
          aria-label="Shared scrubber"
        />

        <span className="shrink-0 text-[11px] tabular-nums text-eoc-secondary">
          T{controller.cursorTick} / {endTick}
        </span>
      </div>
    </div>
  )
}
