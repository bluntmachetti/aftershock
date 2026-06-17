import { useEffect, useRef, useCallback } from 'react'

interface Props {
  open: boolean
  onClose: () => void
  audience: 'public' | 'operator'
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <h3 className="text-[10px] font-mono uppercase tracking-widest text-signal-cyan mb-1.5">
        {title}
      </h3>
      <div className="text-[11px] font-mono text-eoc-secondary leading-relaxed space-y-1.5">
        {children}
      </div>
    </div>
  )
}

export function HelpDrawer({ open, onClose, audience }: Props) {
  const drawerRef = useRef<HTMLDivElement>(null)

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (e.key !== 'Tab' || !drawerRef.current) return
      const focusable = drawerRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    },
    [onClose],
  )

  useEffect(() => {
    if (!open) return
    const prev = document.activeElement as HTMLElement | null
    // Focus the drawer after paint
    requestAnimationFrame(() => {
      drawerRef.current?.focus()
    })
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      prev?.focus()
    }
  }, [open, handleKeyDown])

  if (!open) return null

  return (
    <div
      ref={drawerRef}
      role="dialog"
      aria-labelledby="help-drawer-title"
      tabIndex={-1}
      className="fixed inset-y-0 right-0 z-50 w-96 max-w-full bg-eoc-ground border-l border-eoc-border shadow-2xl overflow-y-auto outline-none"
    >
      <div className="p-4">
        <div className="flex items-center justify-between mb-4">
          <h2
            id="help-drawer-title"
            className="text-[11px] font-mono uppercase tracking-widest text-eoc-primary"
          >
            Reference Guide
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close help"
            className="text-xs leading-none text-eoc-faint hover:text-eoc-primary transition-colors"
          >
            ✕
          </button>
        </div>

        <Section title="What you're watching">
          <p>
            A disaster simulation where agents negotiate scarce rescue resources through a typed
            auction protocol. The public ambient stream runs the deterministic <strong className="text-eoc-primary">scripted</strong> arm;
            the full Qwen <strong className="text-signal-cyan">society</strong> + baselines are what the benchmark compares.
          </p>
        </Section>

        <Section title="Scoreboard">
          Saved vs Lost. Lives saved by timely allocation vs casualties from depleted pools /
          dispatch lag. Headline metric = lives saved per simulated dollar vs scripted/solo/swarm
          baselines.
        </Section>

        <Section title="Panic gauge">
          District panic index (0–100%). Rises when dispatch latency on active crises (fire,
          medical) exceeds thresholds.
        </Section>

        <Section title="Map">
          Town map of active missions + the contention overlay (yellow) where agents contend for
          the same resource. Marker color = mission kind (see legend), not arm.
        </Section>

        <Section title="Negotiation feed">
          The live auction log: which role proposed a resource request, and whether the auction
          GRANTED or rejected it (with reason). Red = an injected disruption.
        </Section>

        <Section title="Resource pools">
          Deployable capacity (ambulances, engines, rescue squads…). Depletion forces agents into
          the auction to negotiate trade-offs.
        </Section>

        {audience === 'public' && (
          <Section title="Watcher mode">
            This view is read-only. The server drives the ambient demo; operator controls are
            locked. Append <span className="text-eoc-primary">?token=…</span> to the URL for the
            full operator session.
          </Section>
        )}

        {audience === 'operator' && (
          <>
            <Section title="Operator controls">
              <p><strong className="text-signal-cyan">Demo Mode</strong> — pre-fills scripted arm, seed 42, 30 ticks.</p>
              <p><strong className="text-eoc-primary">Start Run</strong> — launch any arm (scripted/solo/swarm/society) with configurable seed and ticks.</p>
              <p><strong className="text-signal-red">Inject Event</strong> — inject a disruption (fire, aftershock, road_block) into a district mid-run.</p>
            </Section>

            <Section title="Arms">
              <p><strong className="text-eoc-primary">scripted</strong> — deterministic heuristics, no LLM. The public ambient demo.</p>
              <p><strong className="text-eoc-primary">solo</strong> — a single LLM agent handling every role (no decomposition).</p>
              <p><strong className="text-eoc-primary">swarm</strong> — LLM agents acting independently, without the negotiation protocol (they collide on contested resources).</p>
              <p><strong className="text-signal-cyan">society</strong> — full Qwen agent society: qwen3.5-flash workers + qwen3.5-plus commander + qwen3-max analyst (AAR).</p>
            </Section>
          </>
        )}
      </div>
    </div>
  )
}
