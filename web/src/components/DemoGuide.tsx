import { useState } from 'react'

const LS_KEY = 'aftershock-demo-guide-dismissed'

const STEPS: Array<{ n: number; title: string; body: string; tab: string }> = [
  {
    n: 1,
    title: 'Grounding',
    body: 'NYC Ida 2021: the RealityStrip shows real EMS demand + unit latency. ProvenancePanel badges every field REAL / MAPPED / INFERRED / SYNTHETIC.',
    tab: 'Map',
  },
  {
    n: 2,
    title: 'Negotiation',
    body: 'The Negotiation Feed shows the live auction log: which role requested resources, whether the kernel GRANTED or declined (with reason), and the contention overlay on the map.',
    tab: 'Map',
  },
  {
    n: 3,
    title: 'Counterfactual',
    body: 'Compare tab: branch at tick N, see the DIVERGES marker and the what-if lives delta vs the baseline.',
    tab: 'Compare',
  },
  {
    n: 4,
    title: 'Stress',
    body: 'Live tab: inject chaos (fire / aftershock / road block) into a district → watch the auction and scores react in real time.',
    tab: 'Live',
  },
  {
    n: 5,
    title: 'Proof',
    body: 'Bench tab: lives saved per dollar across 4 arms, with paired-seed CI + sign-test p + a determinism badge (scripted engine, identical digests).',
    tab: 'Bench',
  },
]

export function DemoGuide() {
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(LS_KEY) === '1'
    } catch {
      return false
    }
  })

  const dismiss = () => {
    try {
      localStorage.setItem(LS_KEY, '1')
    } catch {
      /* localStorage may be blocked — dismiss for this session only */
    }
    setDismissed(true)
  }

  const [reopened, setReopened] = useState(false)

  if (dismissed && !reopened) {
    return (
      <button
        type="button"
        onClick={() => setReopened(true)}
        className="absolute top-3 right-3 z-10 px-2 py-1 rounded text-[10px] font-mono uppercase tracking-wider
          bg-signal-cyan/15 border border-signal-cyan/50 text-signal-cyan
          hover:bg-signal-cyan/25 transition-all"
        aria-label="Reopen demo guide"
      >
        Demo Guide
      </button>
    )
  }

  return (
    <div
      className="absolute top-3 right-3 z-10 max-w-[16rem] rounded border border-eoc-border bg-eoc-surface/95 px-3 py-2.5 backdrop-blur-sm shadow-lg"
      data-testid="demo-guide"
    >
      <div className="flex items-center justify-between gap-2 pb-1.5">
        <span className="text-[11px] font-mono uppercase tracking-widest text-signal-cyan">
          Judge Demo — 5 steps
        </span>
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss demo guide"
          className="text-xs leading-none text-eoc-faint hover:text-eoc-primary transition-colors"
        >
          ✕
        </button>
      </div>
      <ol className="flex flex-col gap-1.5">
        {STEPS.map((s) => (
          <li key={s.n} className="flex gap-1.5 text-[10px] leading-snug">
            <span className="font-mono text-signal-cyan shrink-0">{s.n}.</span>
            <span>
              <span className="font-mono text-eoc-primary font-semibold">{s.title}</span>
              <span className="text-eoc-faint"> · {s.tab} tab</span>
              <br />
              <span className="text-eoc-secondary">{s.body}</span>
            </span>
          </li>
        ))}
      </ol>
      <div className="pt-1.5 mt-1 border-t border-eoc-border text-[9px] font-mono text-eoc-faint">
        Full proof bundle: see docs/EVIDENCE.md
      </div>
    </div>
  )
}
