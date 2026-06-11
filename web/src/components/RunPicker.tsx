import type { RunSummary } from '../types'
import { ARM_COLORS } from '../lib/palette'

// Canonical arm coding (palette.ts): society = cyan, every baseline
// (scripted/solo/swarm) = amber. Matches COMPARE's "good vs baseline" read —
// never redefined per component.
function armColor(arm: string): string {
  return arm === 'society' ? ARM_COLORS.society : ARM_COLORS.baseline
}

interface Props {
  runs: RunSummary[]
  selectedRunId: string | null
  error: string | null
  loading: boolean
  onSelect: (run: RunSummary) => void
}

export function RunPicker({ runs, selectedRunId, error, loading, onSelect }: Props) {
  if (error) {
    return (
      <div className="p-3 text-[11px] font-mono text-signal-red border border-signal-red/30 rounded-lg bg-signal-red/10">
        Error loading runs: {error}
      </div>
    )
  }

  if (runs.length === 0) {
    return (
      <div className="p-3 text-[11px] font-mono text-eoc-secondary">
        No runs found. Run <code className="text-signal-amber">aftershock run --seed 42</code> to create one.
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary mb-1">
        Recorded Runs
      </h3>
      <div className="flex flex-col gap-1 overflow-y-auto max-h-48">
        {runs.map((run) => {
          const color = armColor(run.arm)
          const selected = selectedRunId === run.run_id
          return (
            <button
              key={run.run_id}
              onClick={() => onSelect(run)}
              disabled={loading}
              className="flex items-center gap-2 px-2 py-1.5 rounded text-left transition-colors disabled:opacity-50 border border-eoc-border"
              style={{
                background: selected ? `${color}15` : 'transparent',
                borderColor: selected ? color : undefined,
              }}
            >
              <span
                className="text-[10px] font-mono uppercase tracking-wider shrink-0 px-1.5 py-0.5 rounded font-semibold"
                style={{ color, background: `${color}1a` }}
              >
                {run.arm}
              </span>
              <span className="text-[11px] font-mono text-eoc-primary flex-1 truncate">
                {run.run_id}
              </span>
              <span className="text-[10px] font-mono tabular-nums text-eoc-secondary shrink-0">
                s{run.seed} / {run.ticks}t
              </span>
              {!run.has_world && (
                <span className="text-[10px] font-mono text-eoc-secondary shrink-0 px-1 py-0.5 rounded bg-eoc-raised">
                  no-world
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
