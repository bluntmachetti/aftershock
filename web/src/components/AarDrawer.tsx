import { useState } from 'react'
import type { AarReport, AarKeyMoment } from '../types'
import { STATUS_COLORS } from '../lib/palette'

// Grade -> signal hue (green A/B .. amber C .. red D/F). Rendered as a translucent
// pill (bg-<hue>/10 + text-<hue>); no raw hex lives here.
const GRADE_COLORS: Record<string, string> = {
  A: STATUS_COLORS.resolved,
  B: STATUS_COLORS.resolved,
  C: STATUS_COLORS.open,
  D: STATUS_COLORS.failed,
  F: STATUS_COLORS.failed,
}

interface Props {
  report: AarReport
  /** Called when the user clicks a key-moment chip — sets the scrubber cursor to that tick index */
  onJumpToTick: (tick: number) => void
}

export function AarDrawer({ report, onJumpToTick }: Props) {
  const [open, setOpen] = useState(false)

  const grade = report.grade ?? 'C'
  const gradeColor = GRADE_COLORS[grade] ?? GRADE_COLORS['C']

  return (
    <div
      className="border-t border-eoc-border bg-eoc-ground"
      data-testid="aar-drawer"
    >
      {/* Toggle bar */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-eoc-surface transition-colors group"
        aria-expanded={open}
        aria-controls="aar-drawer-body"
      >
        <div className="flex items-center gap-2">
          {/* Grade pill */}
          <span
            className="inline-flex items-center justify-center w-6 h-6 rounded text-[11px] font-mono font-bold"
            style={{ background: `${gradeColor}1a`, color: gradeColor }}
            aria-label={`Grade ${grade}`}
          >
            {grade}
          </span>
          <span className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary group-hover:text-eoc-primary transition-colors">
            After-Action Report
          </span>
          <span className="text-[10px] font-mono text-eoc-secondary truncate max-w-[260px]">
            — {report.headline}
          </span>
        </div>
        <span className="text-eoc-secondary text-[10px] font-mono select-none">
          {open ? '▲' : '▼'}
        </span>
      </button>

      {/* Body */}
      {open && (
        <div
          id="aar-drawer-body"
          className="px-3 pb-4 pt-2 flex flex-col gap-4 border-t border-eoc-raised"
        >
          {/* Headline */}
          <p className="text-xs font-mono text-eoc-primary leading-snug">
            {report.headline}
          </p>

          {/* Two-column: what worked / failures */}
          <div className="grid grid-cols-2 gap-3">
            {/* What worked */}
            <div className="flex flex-col gap-1">
              <div className="text-[10px] font-mono uppercase tracking-widest text-signal-green mb-1">
                What Worked
              </div>
              {(!Array.isArray(report.what_worked) || report.what_worked.length === 0) ? (
                <span className="text-[10px] font-mono text-eoc-secondary">—</span>
              ) : (
                <ul className="flex flex-col gap-1">
                  {report.what_worked.map((item, i) => (
                    <li key={i} className="text-[10px] font-mono text-signal-green flex gap-1.5 leading-snug">
                      <span className="text-signal-green/60 shrink-0">+</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Coordination failures */}
            <div className="flex flex-col gap-1">
              <div className="text-[10px] font-mono uppercase tracking-widest text-signal-red mb-1">
                Coord. Failures
              </div>
              {(!Array.isArray(report.coordination_failures) || report.coordination_failures.length === 0) ? (
                <span className="text-[10px] font-mono text-eoc-secondary">—</span>
              ) : (
                <ul className="flex flex-col gap-1">
                  {report.coordination_failures.map((item, i) => (
                    <li key={i} className="text-[10px] font-mono text-signal-red flex gap-1.5 leading-snug">
                      <span className="text-signal-red/60 shrink-0">✕</span>
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
              <div className="text-[10px] font-mono uppercase tracking-widest text-signal-amber mb-1">
                Lessons
              </div>
              <ol className="flex flex-col gap-1 list-none">
                {report.lessons.map((lesson, i) => (
                  <li key={i} className="text-[10px] font-mono text-signal-amber flex gap-1.5 leading-snug">
                    <span className="text-signal-amber/70 tabular-nums shrink-0 w-4">{i + 1}.</span>
                    <span>{lesson}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Doctrine notes — amber list, only when present */}
          {Array.isArray(report.doctrine_notes) && report.doctrine_notes.length > 0 && (
            <div className="flex flex-col gap-1">
              <div className="text-[10px] font-mono uppercase tracking-widest text-signal-amber mb-1">
                Doctrine
              </div>
              <ol className="flex flex-col gap-1 list-none">
                {report.doctrine_notes.map((note, i) => (
                  <li key={i} className="text-[10px] font-mono text-signal-amber flex gap-1.5 leading-snug">
                    <span className="text-signal-amber/70 tabular-nums shrink-0 w-4">{i + 1}.</span>
                    <span>{note}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Key moments — clickable tick-jump chips */}
          {report.key_moments.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <div className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary mb-1">
                Key Moments
              </div>
              <div className="flex flex-wrap gap-1.5">
                {report.key_moments.map((km: AarKeyMoment, i) => (
                  <button
                    key={i}
                    onClick={() => onJumpToTick(km.tick)}
                    data-testid={`aar-key-moment-${km.tick}`}
                    className="flex items-center gap-1.5 px-2 py-1 rounded border border-eoc-border bg-eoc-surface
                      hover:border-signal-amber/60 hover:bg-signal-amber/10 transition-all group/chip"
                    title={`Jump to T${km.tick}`}
                  >
                    <span className="text-[10px] font-mono text-signal-amber tabular-nums group-hover/chip:text-signal-amber transition-colors">
                      T{km.tick}
                    </span>
                    <span className="text-[10px] font-mono text-eoc-secondary group-hover/chip:text-eoc-primary transition-colors max-w-[200px] truncate">
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
