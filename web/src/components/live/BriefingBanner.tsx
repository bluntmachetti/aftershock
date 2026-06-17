import { useState, useCallback } from 'react'

const BRIEFING_KEY_PREFIX = 'aftershock-live-briefing-seen-v1'

function storageGet(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

function storageSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* private mode / storage disabled */
  }
}

interface Props {
  audience: 'public' | 'operator'
}

export function BriefingBanner({ audience }: Props) {
  const [dismissed, setDismissed] = useState<boolean>(() =>
    storageGet(`${BRIEFING_KEY_PREFIX}-${audience}`),
  )

  const dismiss = useCallback(() => {
    setDismissed(true)
    storageSet(`${BRIEFING_KEY_PREFIX}-${audience}`, '1')
  }, [audience])

  if (dismissed) return null

  return (
    <div className="absolute top-14 left-1/2 -translate-x-1/2 z-20 max-w-xl w-full px-4">
      <div className="rounded border border-signal-cyan/40 bg-eoc-surface/90 backdrop-blur-sm shadow-lg px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <h2 className="text-[10px] font-mono uppercase tracking-widest text-signal-cyan mb-1.5">
              SYSTEM BRIEFING // AGENT SOCIETY TELEMETRY
            </h2>
            <p className="text-[11px] font-mono text-eoc-primary leading-relaxed">
              A society of Qwen agents negotiating scarce rescue resources through a typed auction
              protocol — benchmarked on lives saved per dollar against scripted / solo / swarm
              baselines.
            </p>
            <p className="text-[10px] font-mono text-eoc-secondary mt-2 leading-relaxed">
              <span className="text-signal-green font-semibold">● LIVE DEMO</span>{' '}
              · WATCHER MODE — this stream runs the deterministic scripted arm; operator controls
              are locked.
            </p>
            {audience === 'operator' && (
              <p className="text-[10px] font-mono text-signal-cyan mt-1.5 leading-relaxed">
                Operator session: launch the society/swarm/solo arms, inject events, and take the
                floor from the ambient demo via the left controls.
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={dismiss}
            aria-label="Dismiss briefing"
            className="text-xs leading-none text-eoc-faint hover:text-eoc-primary transition-colors shrink-0 mt-0.5"
          >
            ✕
          </button>
        </div>
      </div>
    </div>
  )
}
