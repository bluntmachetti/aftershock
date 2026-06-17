import { useMemo } from 'react'
import type { TickRecord, WorldState } from '../../types'
import type { ContentionResult } from '../../lib/contention'
import { liveNarration } from '../../lib/liveNarration'

const SEVERITY_CLASS: Record<string, string> = {
  nominal: 'text-eoc-secondary',
  warning: 'text-signal-amber',
  alert: 'text-signal-red',
}

interface Props {
  tick: TickRecord | null
  world: WorldState | null
  contention: ContentionResult
  inject: { kind: string; district: string; tick: number } | null
  arm?: string | null
}

export function AnalystTicker({ tick, world, contention, inject, arm }: Props) {
  const narration = useMemo(
    () => liveNarration({ tick, world, contention, inject, arm }),
    [tick, world, contention, inject, arm],
  )

  if (!narration.text) return null

  const severityClass = SEVERITY_CLASS[narration.severity] ?? 'text-eoc-secondary'

  return (
    <div
      aria-live="polite"
      aria-atomic="true"
      className="w-full px-3 py-1.5 text-[11px] font-mono leading-tight border-b border-eoc-border bg-eoc-surface/80 backdrop-blur-sm"
    >
      <span className={`${severityClass} font-semibold`}>●</span>{' '}
      <span className="text-eoc-primary">{narration.text}</span>
    </div>
  )
}
