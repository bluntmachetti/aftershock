import type { TickRecord } from '../types'

interface Props {
  tick: TickRecord | null
}

function Stat({ label, value, color = 'text-eoc-primary' }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="flex flex-col items-center">
      <span className={`font-mono text-sm tabular-nums font-semibold ${color}`}>{value}</span>
      <span className="text-[10px] text-eoc-secondary tracking-wide">{label}</span>
    </div>
  )
}

export function Scoreboard({ tick }: Props) {
  if (!tick) {
    return (
      <div className="flex gap-4 items-center px-3 py-1.5 rounded-md bg-eoc-ground border border-eoc-border">
        <span className="text-eoc-secondary text-xs font-mono">— no run loaded —</span>
      </div>
    )
  }

  const s = tick.scores
  return (
    <div className="flex gap-4 items-center px-3 py-1.5 rounded-md bg-eoc-ground border border-eoc-border">
      <Stat label="tick" value={tick.tick} color="text-signal-amber" />
      <Stat label="saved" value={Math.round(s['lives_saved'] ?? 0)} color="text-signal-green" />
      <Stat label="lost" value={Math.round(s['lives_lost'] ?? 0)} color="text-signal-red" />
      <Stat label="panic" value={`${Math.round((s['panic'] ?? 0) * 100)}%`} color="text-signal-amber" />
      <Stat label="open" value={Math.round(s['missions_open'] ?? 0)} />
      <Stat label="resolved" value={Math.round(s['missions_resolved'] ?? 0)} color="text-signal-cyan" />
    </div>
  )
}
