/**
 * RealityStrip — the scenario-level reality baseline (task #4, surface table
 * "Reality baseline" row; UX-contract deltas 2/3/4).
 *
 * It is SCENARIO-LEVEL: exactly one instance per surface, never per-arm. The
 * single grey REAL baseline is paired against one or two agent (sim) readouts:
 *   - MapTab     → single-arm mode (one arm bar vs the grey real bar),
 *   - CompareTab → two-arm shared band (BOTH arms' sim latency vs the ONE real
 *     baseline — never two grey bars, never two strips).
 *
 * Content (always visible, never click-only — delta 3):
 *   - a compact PAIRED-BAR chartlet: REAL mean/median first-on-scene (grey) vs
 *     AGENTS mean spawn→first-arrival (arm color), labeled `mean`/`median` to
 *     match the aggregate field actually used;
 *   - a held-rate pair ONLY where the pack provides a real `held_rate` (NYC has
 *     it; SF's is null → the held pair is omitted);
 *   - the inline provenance summary `REAL demand · REAL latency · INFERRED lives`;
 *   - the per-pack caveat line (NOT dismissible — it is the data contract);
 *   - the short sub-caption "Same real demand; simulated dispatch & travel differ."
 *
 * Honesty rule: we render NOTHING when there is no real latency baseline
 * (`realLatencyMinutes`-style null) — never a fabricated grey number. All colors
 * come from palette tokens; no inline #rrggbb literals live here.
 */

import type { ReactNode } from 'react'
import { FALLBACK_COLOR, PROVENANCE_COLORS } from '../lib/palette'
import { formatMinutes } from '../lib/scenario'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

/** One agent (sim) side readout. `latencyMinutes` is the arm's mean
 *  spawn→first-arrival latency in MINUTES (already computed via
 *  `agentLatencyMinutes` averaged across the run's timeline missions by the
 *  caller); null when the arm never put a comparable unit on scene. `heldRate`
 *  is the arm's sim held/unserved fraction in [0,1], or null/undefined when the
 *  caller has none. `color` is the arm color (palette token) — society=cyan,
 *  baseline=amber — supplied by the mount. */
export interface RealityStripArm {
  arm: string
  latencyMinutes: number | null
  heldRate?: number | null
  color: string
}

export interface RealityStripProps {
  /** The single scenario reality baseline aggregates — `reference.aggregates`
   *  (full pack) or the manifest block's `reference_aggregates`. Read for
   *  `mean_latency_s` / `median_latency_s` (seconds) and `held_rate` (fraction).
   *  A `Record<string, unknown>` so it accepts either source verbatim. */
  aggregates: Record<string, unknown> | null | undefined
  /** The per-pack Invariant-4 caveat line (the data contract — always shown,
   *  not dismissible). */
  caveatLine: string
  /** One arm (MapTab) or two arms (CompareTab). The component pairs each arm
   *  against the SINGLE grey real baseline; it never draws a second grey bar. */
  arms: RealityStripArm[]
  /** Optional class hook for the mount to slot the strip as a map-footer (MapTab)
   *  or a shared band (CompareTab). */
  className?: string
}

// ---------------------------------------------------------------------------
// Aggregate coercion (safe reads off the untyped Record)
// ---------------------------------------------------------------------------

/** Read a finite number off the untyped aggregates record, else null. */
function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** The grey REAL first-on-scene baseline (minutes) + which field it came from.
 *  Prefers `mean_latency_s` (labeled "mean"); falls back to `median_latency_s`
 *  ("median"). Seconds → minutes. Null when neither aggregate is a finite
 *  number — the strip renders nothing in that case (no fabricated grey). */
function realLatencyBaseline(
  aggregates: Record<string, unknown> | null | undefined,
): { minutes: number; label: 'mean' | 'median' } | null {
  if (!aggregates) return null
  const mean = num(aggregates.mean_latency_s)
  if (mean !== null) return { minutes: mean / 60, label: 'mean' }
  const median = num(aggregates.median_latency_s)
  if (median !== null) return { minutes: median / 60, label: 'median' }
  return null
}

/** The real held/unserved rate in [0,1], or null when the pack has none (SF's
 *  `held_rate` is null → the held pair is omitted entirely). */
function realHeldRate(
  aggregates: Record<string, unknown> | null | undefined,
): number | null {
  if (!aggregates) return null
  return num(aggregates.held_rate)
}

// ---------------------------------------------------------------------------
// Chartlet primitives
// ---------------------------------------------------------------------------

/** Format a [0,1] fraction as a whole-percent string, or the em-dash for null. */
function formatRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return '—'
  return `${Math.round(rate * 100)}%`
}

/** A single horizontal bar in a paired-bar group. `value`/`max` size the fill;
 *  `color` is a palette token (grey real / arm color). A null value renders an
 *  empty track (no fill) — used so a missing arm latency shows a gap, not a
 *  fabricated bar. */
function Bar({
  label,
  value,
  max,
  color,
  display,
  striped,
}: {
  label: string
  value: number | null
  max: number
  color: string
  display: string
  /** When two agent arms share the same arm color (e.g. swarm-vs-solo, both
   *  amber), the later one is hatched so the two sim bars stay separable while
   *  the grey real bar stays dominant. */
  striped?: boolean
}) {
  const pct =
    value !== null && Number.isFinite(value) && max > 0
      ? Math.max(0, Math.min(100, (value / max) * 100))
      : 0
  const fillStyle = striped
    ? {
        width: `${pct}%`,
        backgroundImage: `repeating-linear-gradient(45deg, ${color} 0, ${color} 2px, transparent 2px, transparent 4px)`,
      }
    : { width: `${pct}%`, background: color }
  return (
    <div className="flex items-center gap-2">
      <span className="w-16 shrink-0 text-right font-mono text-[9px] uppercase tracking-wide text-eoc-secondary">
        {label}
      </span>
      <div className="h-2 flex-1 overflow-hidden rounded-sm bg-eoc-raised">
        <div className="h-full rounded-sm transition-all duration-300" style={fillStyle} />
      </div>
      <span
        className="w-12 shrink-0 text-right font-mono text-[10px] font-semibold tabular-nums"
        style={{ color }}
      >
        {display}
      </span>
    </div>
  )
}

/** A paired-bar group: the single grey REAL bar on top, then one arm bar per
 *  agent side (the arm color). Shared max across all bars so the lengths read
 *  comparably. */
function PairedBars({
  title,
  realLabel,
  realValue,
  realDisplay,
  arms,
}: {
  title: string
  realLabel: string
  realValue: number | null
  realDisplay: string
  arms: Array<{ arm: string; value: number | null; color: string; display: string; striped?: boolean }>
}) {
  const values = [realValue, ...arms.map((a) => a.value)].filter(
    (v): v is number => v !== null && Number.isFinite(v),
  )
  const max = values.length ? Math.max(...values) : 0
  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-[9px] uppercase tracking-widest text-eoc-secondary">
        {title}
      </span>
      <Bar
        label={realLabel}
        value={realValue}
        max={max}
        color={FALLBACK_COLOR}
        display={realDisplay}
      />
      {arms.map((a) => (
        <Bar
          key={a.arm}
          label={a.arm}
          value={a.value}
          max={max}
          color={a.color}
          display={a.display}
          striped={a.striped}
        />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Provenance summary chips (delta 3 — always visible inline summary)
// ---------------------------------------------------------------------------

/** The always-visible inline `REAL demand · REAL latency · INFERRED lives`
 *  summary. The two REAL chips use the solid-fill REAL tier; the INFERRED chip
 *  is a ghost border (so it never reads as an error). Neutral colors only. */
function ProvenanceSummary() {
  return (
    <div className="flex flex-wrap items-center gap-1.5 font-mono text-[9px] uppercase tracking-wide">
      <ProvChip tier="real">REAL demand</ProvChip>
      <ProvChip tier="real">REAL latency</ProvChip>
      <ProvChip tier="inferred">INFERRED lives</ProvChip>
    </div>
  )
}

function ProvChip({
  tier,
  children,
}: {
  tier: 'real' | 'inferred'
  children: ReactNode
}) {
  const c = PROVENANCE_COLORS[tier]
  return (
    <span
      className="rounded-sm border px-1 py-px"
      style={{ borderColor: c.border, background: c.fill, color: c.text }}
    >
      {children}
    </span>
  )
}

// ---------------------------------------------------------------------------
// RealityStrip
// ---------------------------------------------------------------------------

export function RealityStrip({
  aggregates,
  caveatLine,
  arms,
  className,
}: RealityStripProps) {
  const real = realLatencyBaseline(aggregates)
  // Honesty rule: NO real latency baseline → render nothing (never a fabricated
  // grey number). This is also the synthetic-run path (null aggregates).
  if (!real) return null

  const heldRate = realHeldRate(aggregates)
  const hasHeld = heldRate !== null

  // Hatch the later of any two arms that resolve to the SAME arm color (e.g. a
  // swarm-vs-solo compare, both amber) so the two sim bars stay separable. The
  // headline society-vs-baseline path (cyan vs amber) never triggers this.
  const seenColors = new Set<string>()
  const striped = arms.map((a) => {
    const color = a.color || FALLBACK_COLOR
    const dup = seenColors.has(color)
    seenColors.add(color)
    return dup
  })

  const latencyArms = arms.map((a, i) => ({
    arm: a.arm.toUpperCase(),
    value: a.latencyMinutes,
    color: a.color || FALLBACK_COLOR,
    display: formatMinutes(a.latencyMinutes),
    striped: striped[i],
  }))

  const heldArms = arms.map((a, i) => ({
    arm: a.arm.toUpperCase(),
    value: a.heldRate ?? null,
    color: a.color || FALLBACK_COLOR,
    display: formatRate(a.heldRate),
    striped: striped[i],
  }))

  return (
    <div
      className={`flex flex-col gap-2 border-eoc-border bg-eoc-ground px-4 py-2 ${className ?? ''}`}
      data-testid="reality-strip"
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-eoc-secondary">
          Reality baseline
        </span>
        <ProvenanceSummary />
      </div>

      <div className="flex flex-wrap items-start gap-x-8 gap-y-2">
        <PairedBars
          title={`first on scene · ${real.label}`}
          realLabel="real"
          realValue={real.minutes}
          realDisplay={formatMinutes(real.minutes)}
          arms={latencyArms}
        />
        {hasHeld && (
          <PairedBars
            title="held / unserved"
            realLabel="real"
            realValue={heldRate}
            realDisplay={formatRate(heldRate)}
            arms={heldArms}
          />
        )}
      </div>

      <div className="flex flex-col gap-0.5">
        <span className="font-mono text-[10px] text-eoc-secondary">{caveatLine}</span>
        <span className="font-mono text-[9px] italic text-eoc-secondary">
          Same real demand; simulated dispatch &amp; travel differ.
        </span>
      </div>
    </div>
  )
}
