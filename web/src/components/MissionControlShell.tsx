import type { WorldState } from '../types'
import { conditionFor } from '../lib/condition'

interface Props {
  world: WorldState | null
  /** Current tick number (from the selected tick record), or null if none. */
  tickNumber: number | null
  /** Highest tick of the loaded run (the "op clock" denominator). */
  totalTicks: number
  arm: string | null
  seed: number | null
}

interface CounterProps {
  label: string
  value: number | string
  color?: string
  dim?: boolean
}

function Counter({ label, value, color, dim }: CounterProps) {
  return (
    <div className="flex flex-col items-end leading-none">
      <span
        className="font-mono font-semibold tabular-nums text-base"
        style={color ? { color } : undefined}
      >
        {value}
      </span>
      <span
        className={`font-mono text-[9px] uppercase tracking-widest mt-0.5 ${
          dim ? 'text-eoc-faint' : 'text-eoc-secondary'
        }`}
      >
        {label}
      </span>
    </div>
  )
}

/** The Map-tab command band — CONDITION state + run identity + op clock + the
 *  saved/lost/active/at-risk counters. Presentational: reads the current world,
 *  computes nothing the engine doesn't already provide. Renders a neutral strip
 *  when no run is loaded. */
export function MissionControlShell({ world, tickNumber, totalTicks, arm, seed }: Props) {
  const condition = conditionFor(world, tickNumber ?? 0)
  const open = world ? Object.values(world.missions).filter((m) => m.status === 'open') : []
  const atRisk = open.reduce((s, m) => s + m.lives_at_risk, 0)
  const armLabel = (arm ?? '').toUpperCase()

  return (
    <div className="flex items-center gap-4 px-4 h-11 shrink-0 border-b border-eoc-border bg-eoc-ground">
      {/* CONDITION chip */}
      <div className="flex items-center gap-2 shrink-0">
        <span className="font-mono text-[9px] uppercase tracking-widest text-eoc-faint">
          Condition
        </span>
        <span
          className="w-2 h-2 rounded-full"
          style={{ background: condition.color, boxShadow: `0 0 6px ${condition.color}` }}
        />
        <span
          className="font-mono font-semibold text-sm tracking-wider"
          style={{ color: condition.color }}
        >
          {condition.label}
        </span>
      </div>

      <div className="w-px h-5 bg-eoc-border shrink-0" />

      {/* Run identity */}
      <div className="flex items-center gap-2 min-w-0">
        {seed !== null && (
          <span className="font-mono text-xs text-eoc-primary truncate">
            seed-{seed}
            {armLabel && <span className="text-eoc-secondary"> · {armLabel}</span>}
          </span>
        )}
        {!world && (
          <span className="font-mono text-xs text-eoc-secondary">No run loaded</span>
        )}
        {world && (
          <span className="font-mono text-[9px] uppercase tracking-widest text-eoc-faint border border-eoc-border rounded px-1 py-px">
            Replay
          </span>
        )}
      </div>

      {/* Op clock */}
      {tickNumber !== null && (
        <div className="flex items-baseline gap-1.5 shrink-0">
          <span className="font-mono font-semibold tabular-nums text-sm text-eoc-primary">
            T{tickNumber}
          </span>
          {/* Denominator mirrors the Scrubber (T{tick} / {timeline.total}) so the
              band and scrubber always read the same op-clock. */}
          <span className="font-mono text-[9px] uppercase tracking-widest text-eoc-faint">
            / {totalTicks} op clock
          </span>
        </div>
      )}

      <div className="flex-1" />

      {/* Counters */}
      {world && (
        <div className="flex items-center gap-5 shrink-0">
          <Counter label="Saved" value={world.lives_saved} color="rgb(var(--signal-green))" />
          <Counter label="Lost" value={world.lives_lost} color="rgb(var(--signal-red))" />
          <Counter label="Active" value={open.length} color="rgb(var(--signal-amber))" />
          <Counter label="At risk" value={atRisk} dim />
        </div>
      )}
    </div>
  )
}
