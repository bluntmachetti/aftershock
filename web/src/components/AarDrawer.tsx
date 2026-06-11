import { useState } from 'react'
import type { AarReport, AarKeyMoment } from '../types'

// Grade -> colour mapping (green A .. red F)
const GRADE_STYLES: Record<string, { bg: string; border: string; text: string }> = {
  A: { bg: '#052e16', border: '#16a34a', text: '#4ade80' },
  B: { bg: '#052e16', border: '#22c55e', text: '#86efac' },
  C: { bg: '#1c1409', border: '#d97706', text: '#fbbf24' },
  D: { bg: '#1c0a09', border: '#dc2626', text: '#f87171' },
  F: { bg: '#1c0a09', border: '#ef4444', text: '#fca5a5' },
}

interface Props {
  report: AarReport
  /** Called when the user clicks a key-moment chip — sets the scrubber cursor to that tick index */
  onJumpToTick: (tick: number) => void
}

export function AarDrawer({ report, onJumpToTick }: Props) {
  const [open, setOpen] = useState(false)

  const grade = report.grade ?? 'C'
  const gs = GRADE_STYLES[grade] ?? GRADE_STYLES['C']

  return (
    <div
      className="border-t border-[#243047] bg-[#0a0e1a]"
      data-testid="aar-drawer"
    >
      {/* Toggle bar */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-[#0f1624] transition-colors group"
        aria-expanded={open}
        aria-controls="aar-drawer-body"
      >
        <div className="flex items-center gap-2">
          {/* Grade badge */}
          <span
            className="inline-flex items-center justify-center w-6 h-6 rounded text-[11px] font-mono font-bold border"
            style={{ background: gs.bg, borderColor: gs.border, color: gs.text }}
            aria-label={`Grade ${grade}`}
          >
            {grade}
          </span>
          <span className="text-[10px] font-mono uppercase tracking-widest text-slate-400 group-hover:text-slate-200 transition-colors">
            After-Action Report
          </span>
          <span className="text-[10px] font-mono text-slate-600 truncate max-w-[260px]">
            — {report.headline}
          </span>
        </div>
        <span className="text-slate-600 text-[10px] font-mono select-none">
          {open ? '▲' : '▼'}
        </span>
      </button>

      {/* Body */}
      {open && (
        <div
          id="aar-drawer-body"
          className="px-3 pb-4 pt-2 flex flex-col gap-4 border-t border-[#1a2235]"
        >
          {/* Headline */}
          <p className="text-[12px] font-mono text-slate-300 leading-snug">
            {report.headline}
          </p>

          {/* Two-column: what worked / failures */}
          <div className="grid grid-cols-2 gap-3">
            {/* What worked */}
            <div className="flex flex-col gap-1">
              <div className="text-[9px] font-mono uppercase tracking-widest text-green-600 mb-1">
                What Worked
              </div>
              {(!Array.isArray(report.what_worked) || report.what_worked.length === 0) ? (
                <span className="text-[10px] font-mono text-slate-600">—</span>
              ) : (
                <ul className="flex flex-col gap-1">
                  {report.what_worked.map((item, i) => (
                    <li key={i} className="text-[10px] font-mono text-green-400 flex gap-1.5 leading-snug">
                      <span className="text-green-700 shrink-0">+</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Coordination failures */}
            <div className="flex flex-col gap-1">
              <div className="text-[9px] font-mono uppercase tracking-widest text-red-700 mb-1">
                Coord. Failures
              </div>
              {(!Array.isArray(report.coordination_failures) || report.coordination_failures.length === 0) ? (
                <span className="text-[10px] font-mono text-slate-600">—</span>
              ) : (
                <ul className="flex flex-col gap-1">
                  {report.coordination_failures.map((item, i) => (
                    <li key={i} className="text-[10px] font-mono text-red-400 flex gap-1.5 leading-snug">
                      <span className="text-red-700 shrink-0">✕</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {/* Lessons */}
          {report.lessons.length > 0 && (
            <div className="flex flex-col gap-1">
              <div className="text-[9px] font-mono uppercase tracking-widest text-amber-600 mb-1">
                Lessons
              </div>
              <ol className="flex flex-col gap-1 list-none">
                {report.lessons.map((lesson, i) => (
                  <li key={i} className="text-[10px] font-mono text-amber-300 flex gap-1.5 leading-snug">
                    <span className="text-amber-600 tabular-nums shrink-0 w-4">{i + 1}.</span>
                    <span>{lesson}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Doctrine notes — amber list, only when present */}
          {Array.isArray(report.doctrine_notes) && report.doctrine_notes.length > 0 && (
            <div className="flex flex-col gap-1">
              <div className="text-[9px] font-mono uppercase tracking-widest text-amber-500 mb-1">
                Doctrine
              </div>
              <ol className="flex flex-col gap-1 list-none">
                {report.doctrine_notes.map((note, i) => (
                  <li key={i} className="text-[10px] font-mono text-amber-400 flex gap-1.5 leading-snug">
                    <span className="text-amber-600 tabular-nums shrink-0 w-4">{i + 1}.</span>
                    <span>{note}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Key moments — clickable tick-jump chips */}
          {report.key_moments.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <div className="text-[9px] font-mono uppercase tracking-widest text-slate-500 mb-1">
                Key Moments
              </div>
              <div className="flex flex-wrap gap-1.5">
                {report.key_moments.map((km: AarKeyMoment, i) => (
                  <button
                    key={i}
                    onClick={() => onJumpToTick(km.tick)}
                    data-testid={`aar-key-moment-${km.tick}`}
                    className="flex items-center gap-1.5 px-2 py-1 rounded border border-[#243047] bg-[#0f1624]
                      hover:border-amber-500/60 hover:bg-amber-500/10 transition-all group/chip"
                    title={`Jump to T${km.tick}`}
                  >
                    <span className="text-[9px] font-mono text-amber-500 tabular-nums group-hover/chip:text-amber-300 transition-colors">
                      T{km.tick}
                    </span>
                    <span className="text-[9px] font-mono text-slate-400 group-hover/chip:text-slate-200 transition-colors max-w-[200px] truncate">
                      {km.description}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
