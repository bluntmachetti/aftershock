import { STATUS_COLORS } from '../lib/palette'

interface Props {
  panic: number // 0-1
}

export function PanicGauge({ panic }: Props) {
  const pct = Math.max(0, Math.min(1, panic))
  // green (calm) → amber (tense) → red (panic); reuse the signal-keyed status hues.
  const color =
    pct < 0.3 ? STATUS_COLORS.resolved : pct < 0.6 ? STATUS_COLORS.open : STATUS_COLORS.failed
  const label = pct < 0.3 ? 'CALM' : pct < 0.6 ? 'TENSE' : 'PANIC'

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-mono text-eoc-secondary">
          Panic
        </span>
        <span
          className="text-[11px] font-mono font-semibold tabular-nums"
          style={{ color }}
        >
          {Math.round(pct * 100)}% {label}
        </span>
      </div>
      <div className="h-1.5 bg-eoc-raised rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{ width: `${pct * 100}%`, background: color, boxShadow: `0 0 4px ${color}60` }}
        />
      </div>
    </div>
  )
}
