import type { TickRecord } from '../types'

interface Props {
  tick: TickRecord | null
}

function Stat({ label, value, color = 'text-slate-200' }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="flex flex-col items-center">
      <span className={`font-mono text-sm tabular-nums font-semibold ${color}`}>{value}</span>
      <span className="text-[10px] text-slate-500 uppercase tracking-wider">{label}</span>
    </div>
  )
}

export function Scoreboard({ tick }: Props) {
  if (!tick) {
    return (
      <div className="flex gap-4 text-slate-600 text-xs font-mono">
        <span>— no run loaded —</span>
      </div>
    )
  }

  const s = tick.scores
  return (
    <div className="flex gap-4 items-center">
      <Stat label="tick" value={tick.tick} color="text-amber-400" />
      <Stat label="saved" value={Math.round(s['lives_saved'] ?? 0)} color="text-green-400" />
      <Stat label="lost" value={Math.round(s['lives_lost'] ?? 0)} color="text-red-400" />
      <Stat label="panic" value={`${Math.round((s['panic'] ?? 0) * 100)}%`} color="text-orange-400" />
      <Stat label="open" value={Math.round(s['missions_open'] ?? 0)} />
      <Stat label="resolved" value={Math.round(s['missions_resolved'] ?? 0)} color="text-cyan-400" />
    </div>
  )
}
