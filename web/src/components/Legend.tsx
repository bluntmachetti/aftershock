import { useState } from 'react'
import type { MissionState } from '../types'
import {
  MISSION_KIND_COLORS,
  STATUS_COLORS,
  ARM_COLORS,
} from '../lib/palette'

const LS_KEY = 'aftershock-legend-dismissed'

type MissionKind = MissionState['kind']
type MissionStatus = MissionState['status']

// Mission-kind icon glyphs — the same inline SVG path set TownMap draws on its
// markers, mirrored here so a legend swatch reads identically to the thing on
// the map. Authored on a 24×24 viewBox; rendered filled in the kind's color.
const MISSION_ICON_PATHS: Record<MissionKind, string> = {
  medical_surge: 'M10 2h4v7h7v4h-7v7h-4v-7H3v-4h7z',
  fire: 'M12 2c0 0-1.5 3-3 5.5C7.5 10 6 11.5 6 14a6 6 0 0012 0c0-3-2-5-3-7-0.5 1.5-1 3-3 4 0 0 0.5-3.5 0-4.5C12 6.5 12 2 12 2z',
  collapse_rescue:
    'M3 10L12 3l9 7v11H3V10zm3 1v8h4v-5h2v5h4v-8l-5-3.9L6 11z M10 13l1 2-1 2h4l-1-2 1-2h-4z',
  infra_repair:
    'M16.5 3C14 3 12 5 12 7.5c0 .5.1 1 .3 1.4L4 17.2 4 20l2.8 0 8.3-8.3c.4.2.9.3 1.4.3C19 12 21 10 21 7.5c0-.7-.2-1.4-.5-2l-2.8 2.8-1.5-1.5 2.8-2.8C18.4 3.7 17.5 3 16.5 3z',
}

const MISSION_KIND_LABELS: Record<MissionKind, string> = {
  collapse_rescue: 'Collapse rescue',
  fire: 'Fire',
  medical_surge: 'Medical surge',
  infra_repair: 'Infra repair',
}

const STATUS_LABELS: Record<MissionStatus, string> = {
  open: 'Open',
  resolved: 'Resolved',
  failed: 'Failed',
}

// Fixed display order — matches the rows the eye scans on the map.
const MISSION_KIND_ORDER: MissionKind[] = [
  'collapse_rescue',
  'fire',
  'medical_surge',
  'infra_repair',
]
const STATUS_ORDER: MissionStatus[] = ['open', 'resolved', 'failed']

/** A kind row: the actual marker glyph in its color + the kind name. */
function KindRow({ kind }: { kind: MissionKind }) {
  const color = MISSION_KIND_COLORS[kind]
  return (
    <div className="flex items-center gap-2">
      <svg
        viewBox="0 0 24 24"
        width={12}
        height={12}
        className="shrink-0"
        aria-hidden="true"
      >
        <path d={MISSION_ICON_PATHS[kind]} fill={color} fillOpacity={0.9} />
      </svg>
      <span className="text-[11px] text-eoc-secondary">
        {MISSION_KIND_LABELS[kind]}
      </span>
    </div>
  )
}

/** A swatch row: a small color chip + label. Used for status + arm coding. */
function SwatchRow({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className="shrink-0 h-2.5 w-2.5 rounded-sm border border-eoc-border"
        style={{ background: color }}
        aria-hidden="true"
      />
      <span className="text-[11px] text-eoc-secondary">{label}</span>
    </div>
  )
}

/** A titled column of rows inside the legend grid. */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="text-[10px] font-mono uppercase tracking-widest text-eoc-faint">
        {title}
      </div>
      {children}
    </div>
  )
}

/**
 * Dismissible map legend overlay. Absolute-positioned so the parent (MapTab /
 * CompareTab) can drop it over the SVG town. Explains mission-kind glyphs,
 * mission status colors, and the arm coding (society = cyan, baseline = amber).
 *
 * Dismissal persists in localStorage under `aftershock-legend-dismissed`; once
 * dismissed the component renders nothing on subsequent mounts. No "booting"
 * animation — it appears immediately.
 */
export function Legend(): JSX.Element {
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(LS_KEY) === '1'
    } catch {
      return false
    }
  })

  function dismiss() {
    setDismissed(true)
    try {
      localStorage.setItem(LS_KEY, '1')
    } catch {
      /* private mode / storage disabled — dismiss for this session only */
    }
  }

  if (dismissed) return <></>

  return (
    <div className="absolute bottom-3 left-3 z-10 max-w-[15rem] rounded border border-eoc-border bg-eoc-surface/90 px-3 py-2 backdrop-blur-sm shadow-lg">
      <div className="flex items-center justify-between gap-2 pb-1.5">
        <span className="text-[11px] font-mono uppercase tracking-widest text-eoc-secondary">
          Legend
        </span>
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss legend"
          className="text-xs leading-none text-eoc-faint hover:text-eoc-primary transition-colors"
        >
          ✕
        </button>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-2.5">
        <Section title="Mission kind">
          {MISSION_KIND_ORDER.map((kind) => (
            <KindRow key={kind} kind={kind} />
          ))}
        </Section>

        <div className="flex flex-col gap-2.5">
          <Section title="Status">
            {STATUS_ORDER.map((status) => (
              <SwatchRow
                key={status}
                color={STATUS_COLORS[status]}
                label={STATUS_LABELS[status]}
              />
            ))}
          </Section>

          <Section title="Arm">
            <SwatchRow color={ARM_COLORS.society} label="Society" />
            <SwatchRow color={ARM_COLORS.baseline} label="Baseline" />
          </Section>
        </div>
      </div>
    </div>
  )
}
