import type { RunSummary } from '../types'

const ARM_COLORS: Record<string, string> = {
  scripted: '#94a3b8',
  solo: '#f59e0b',
  swarm: '#22d3ee',
  society: '#4ade80',
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
      <div className="p-3 text-[11px] font-mono text-red-400 border border-red-900 rounded-lg bg-red-950/20">
        Error loading runs: {error}
      </div>
    )
  }

  if (runs.length === 0) {
    return (
      <div className="p-3 text-[11px] font-mono text-slate-600">
        No runs found. Run <code className="text-amber-400">aftershock run --seed 42</code> to create one.
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-[10px] font-mono uppercase tracking-widest text-slate-500 mb-1">
        Recorded Runs
      </h3>
      <div className="flex flex-col gap-1 overflow-y-auto max-h-48">
        {runs.map((run) => {
          const color = ARM_COLORS[run.arm] ?? '#94a3b8'
          const selected = selectedRunId === run.run_id
          return (
            <button
              key={run.run_id}
              onClick={() => onSelect(run)}
              disabled={loading}
              className="flex items-center gap-2 px-2 py-1.5 rounded text-left transition-colors disabled:opacity-50"
              style={{
                background: selected ? `${color}15` : 'transparent',
                border: `1px solid ${selected ? color : '#243047'}`,
              }}
            >
              <span
                className="text-[10px] font-mono uppercase tracking-wider shrink-0"
                style={{ color }}
              >
                {run.arm}
              </span>
              <span className="text-[11px] font-mono text-slate-300 flex-1 truncate">
                {run.run_id}
              </span>
              <span className="text-[10px] font-mono tabular-nums text-slate-500 shrink-0">
                s{run.seed} / {run.ticks}t
              </span>
              {!run.has_world && (
                <span className="text-[9px] font-mono text-slate-600 shrink-0">no-world</span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
