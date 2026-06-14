// Shared map primitives — extracted verbatim from TownMap so the new
// MissionControlMap (Map tab) and the original TownMap (Compare tab) render the
// SAME rich mission markers + popover without duplication. Pure extraction: no
// behaviour change. The data-driven mission/arm/status colors come from
// palette.ts; the SVG chrome colors read the EOC RGB-channel vars from index.css.

import type { MissionState, ScenarioReferenceMission } from '../types'
import {
  MISSION_KIND_COLORS,
  STATUS_COLORS,
  FALLBACK_COLOR,
  PROVENANCE_COLORS,
  CONTENTION_COLOR,
} from '../lib/palette'
import {
  agentLatencyMinutes,
  realLatencyMinutes,
  formatMinutes,
} from '../lib/scenario'

// SVG-only chrome colors. Tailwind classes can't reach inside <svg fill>, so
// these read the EOC RGB-channel CSS vars (defined in index.css :root) as
// `rgb(var(--x) / a)` strings — token-driven, zero hex literals here. The two
// "blocked district" reds are derived from --signal-red at low alpha.
export const EOC_GROUND = 'rgb(var(--eoc-ground))'
export const EOC_SURFACE = 'rgb(var(--eoc-surface))'
export const EOC_RAISED = 'rgb(var(--eoc-raised))'
export const EOC_BORDER = 'rgb(var(--eoc-border))'
export const EOC_GRID = 'rgb(var(--eoc-raised))'
export const BLOCKED_FILL = 'rgb(var(--signal-red) / 0.12)'
export const BLOCKED_BADGE_FILL = 'rgb(var(--signal-red) / 0.4)'

// Fixed district grid layout — 2 rows × 3 cols inside a 500×380 viewBox.
// GRID_Y offsets the whole 2-row block downward so it reads centred with breathing room.
export const GRID_Y = 50 // top margin before row-0 districts
export const SVG_W = 500
export const SVG_H = 380 // GRID_Y(50) + row0(130) + row1(150) + bottom(50)

export const DISTRICT_LAYOUT: Record<
  string,
  { x: number; y: number; w: number; h: number; label: string }
> = {
  old_town: { x: 0, y: GRID_Y, w: 160, h: 130, label: 'Old Town' },
  harbor: { x: 160, y: GRID_Y, w: 180, h: 130, label: 'Harbor' },
  hospital_district: { x: 340, y: GRID_Y, w: 160, h: 130, label: 'Hospital' },
  market: { x: 0, y: GRID_Y + 130, w: 200, h: 150, label: 'Market' },
  residential_north: { x: 200, y: GRID_Y + 130, w: 180, h: 150, label: 'Residential N.' },
  industrial: { x: 380, y: GRID_Y + 130, w: 120, h: 150, label: 'Industrial' },
}

/** Center of a district rect (for contention-link endpoints). */
export function districtCenter(districtId: string): { x: number; y: number } | null {
  const d = DISTRICT_LAYOUT[districtId]
  if (!d) return null
  return { x: d.x + d.w / 2, y: d.y + d.h / 2 }
}

// Inline monochrome SVG path icons — authored on a 24×24 viewBox; caller scales via transform.
export const MISSION_ICON_PATHS: Record<string, { d: string; fill?: boolean }> = {
  // Medical cross — two overlapping rectangles
  medical_surge: {
    d: 'M10 2h4v7h7v4h-7v7h-4v-7H3v-4h7z',
    fill: true,
  },
  // Flame — teardrop with inner curl
  fire: {
    d: 'M12 2c0 0-1.5 3-3 5.5C7.5 10 6 11.5 6 14a6 6 0 0012 0c0-3-2-5-3-7-0.5 1.5-1 3-3 4 0 0 0.5-3.5 0-4.5C12 6.5 12 2 12 2z',
    fill: true,
  },
  // Collapsing building — house silhouette with crack
  collapse_rescue: {
    d: 'M3 10L12 3l9 7v11H3V10zm3 1v8h4v-5h2v5h4v-8l-5-3.9L6 11z M10 13l1 2-1 2h4l-1-2 1-2h-4z',
    fill: true,
  },
  // Wrench
  infra_repair: {
    d: 'M16.5 3C14 3 12 5 12 7.5c0 .5.1 1 .3 1.4L4 17.2 4 20l2.8 0 8.3-8.3c.4.2.9.3 1.4.3C19 12 21 10 21 7.5c0-.7-.2-1.4-.5-2l-2.8 2.8-1.5-1.5 2.8-2.8C18.4 3.7 17.5 3 16.5 3z',
    fill: true,
  },
}

export function severityRadius(s: number): number {
  return 8 + s * 3
}

export type Effects = 'normal' | 'quiet'

interface MissionMarkerProps {
  mission: MissionState
  cx: number
  cy: number
  selected: boolean
  effects: Effects
  /** When true, draw a contention halo (loser/winner of an active auction). */
  contested?: boolean
  onSelect: () => void
}

export function MissionMarker({
  mission,
  cx,
  cy,
  selected,
  effects,
  contested = false,
  onSelect,
}: MissionMarkerProps) {
  const color = MISSION_KIND_COLORS[mission.kind] ?? FALLBACK_COLOR
  const r = severityRadius(mission.severity)
  const isOpen = mission.status === 'open'
  const pct = Math.min(1, mission.progress)
  // Compare mode ('quiet') drops the drop-shadow + animate-ping so two synced
  // maps stay calm and cheap to re-render at 8×.
  const quiet = effects === 'quiet'

  // Staffing pips: count how many resources are fully staffed
  const totalRequired = Object.values(mission.required).reduce((s, v) => s + v, 0)
  const totalAssigned = Object.values(mission.assigned).reduce((s, v) => s + v, 0)

  // Circumference for progress arc
  const circum = 2 * Math.PI * r
  const dash = pct * circum

  return (
    <g
      transform={`translate(${cx},${cy})`}
      onClick={onSelect}
      className="cursor-pointer"
      style={{ filter: selected && !quiet ? `drop-shadow(0 0 6px ${color})` : undefined }}
    >
      {/* Contention halo — drawn beneath the marker, suppressed in quiet mode.
          Dashed ring in the caution color signals an active auction. */}
      {contested && !quiet && (
        <circle
          r={r + 7}
          fill="none"
          stroke={CONTENTION_COLOR}
          strokeWidth={1.5}
          strokeDasharray="3 3"
          opacity={0.9}
          className="mc-contest-halo"
        />
      )}
      {/* Outer glow ring for active missions — suppressed in quiet mode */}
      {isOpen && !quiet && (
        <circle
          r={r + 4}
          fill="none"
          stroke={color}
          strokeWidth={1}
          opacity={0.2}
          className="animate-ping"
          style={{ animationDuration: '3s' }}
        />
      )}
      {/* Background circle */}
      <circle r={r} fill={EOC_SURFACE} stroke={color} strokeWidth={selected ? 2 : 1.5} opacity={isOpen ? 1 : 0.4} />
      {/* Progress arc */}
      {isOpen && (
        <circle
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={3}
          strokeDasharray={`${dash} ${circum - dash}`}
          strokeDashoffset={circum / 4}
          strokeLinecap="round"
          opacity={0.9}
        />
      )}
      {/* Status fill for resolved/failed */}
      {mission.status === 'resolved' && (
        <circle r={r - 2} fill={`${STATUS_COLORS.resolved}20`} stroke={STATUS_COLORS.resolved} strokeWidth={1} />
      )}
      {mission.status === 'failed' && (
        <circle r={r - 2} fill={`${STATUS_COLORS.failed}20`} stroke={STATUS_COLORS.failed} strokeWidth={1} />
      )}
      {/* Icon — inline SVG path scaled to fit within the circle */}
      {(() => {
        const iconDef = MISSION_ICON_PATHS[mission.kind]
        if (!iconDef) return null
        const iconSize = r * 1.4
        const half = iconSize / 2
        return (
          <g transform={`translate(${-half},${-half})`}>
            <svg viewBox="0 0 24 24" width={iconSize} height={iconSize} overflow="visible">
              <path
                d={iconDef.d}
                fill={iconDef.fill ? color : 'none'}
                stroke={iconDef.fill ? 'none' : color}
                strokeWidth={iconDef.fill ? 0 : 2}
                fillOpacity={isOpen ? 0.9 : 0.4}
                strokeOpacity={isOpen ? 0.9 : 0.4}
              />
            </svg>
          </g>
        )
      })()}
      {/* Lives at risk */}
      {isOpen && (
        <text
          y={r + 10}
          textAnchor="middle"
          fill={color}
          fontSize={9}
          fontFamily="'JetBrains Mono', monospace"
          fontWeight="600"
        >
          {mission.lives_at_risk}♥
        </text>
      )}
      {/* Staffing pips row — slightly larger for 1080p legibility */}
      {isOpen && totalRequired > 0 && (
        <g transform={`translate(${-totalRequired * 5.5},${r + 20})`}>
          {Array.from({ length: totalRequired }).map((_, i) => (
            <rect
              key={i}
              x={i * 10}
              y={0}
              width={8}
              height={5}
              rx={1}
              fill={i < totalAssigned ? color : EOC_BORDER}
              stroke={i < totalAssigned ? `${color}60` : EOC_RAISED}
              strokeWidth={0.5}
              opacity={0.95}
            />
          ))}
        </g>
      )}
    </g>
  )
}

interface MissionPopoverProps {
  mission: MissionState
  cx: number
  cy: number
  /** The agent_id that most recently requested resources for this mission, if any. */
  requester: string | null
  /** Scenario reality baseline for THIS mission (resolved by the caller via the
   *  injection-safe index→mission map in lib/scenario.ts). Null/undefined for a
   *  synthetic run or an injected mission with no timeline baseline — in that case
   *  the two scenario lines + INFERRED badge are suppressed entirely. */
  scenarioRef?: ScenarioReferenceMission | null
  /** The tick the first assigned resource arrived for this mission, if any. Feeds
   *  agentLatencyMinutes(spawned_tick, firstArrival, tickMinutes). */
  agentFirstArrivalTick?: number | null
  /** Pack tick length in minutes (only present on scenario runs). When set
   *  together with scenarioRef, the two real-vs-sim latency lines render. */
  tickMinutes?: number | null
}

// Resource-kind tracking for the required/assigned breakdown rows.
function resourceRows(mission: MissionState): { kind: string; req: number; got: number }[] {
  const kinds = new Set<string>([
    ...Object.keys(mission.required),
    ...Object.keys(mission.assigned),
  ])
  return Array.from(kinds)
    .sort()
    .map((kind) => ({
      kind,
      req: mission.required[kind] ?? 0,
      got: mission.assigned[kind] ?? 0,
    }))
}

/** Mission detail card anchored to the marker. Pure SVG (foreignObject avoided
 *  to keep the card crisp under 1080p capture and inside preserveAspectRatio). */
export function MissionPopover({
  mission,
  cx,
  cy,
  requester,
  scenarioRef,
  agentFirstArrivalTick,
  tickMinutes,
}: MissionPopoverProps) {
  const color = MISSION_KIND_COLORS[mission.kind] ?? FALLBACK_COLOR
  const rows = resourceRows(mission)
  const PAD = 8
  const LINE = 12
  const W = 168

  // Scenario reality lines (UX delta #8 — KEPT). Only present on a scenario run
  // where this mission resolves to a timeline baseline (scenarioRef supplied) and
  // a pack tick length is known. The real line uses lib/scenario.realLatencyMinutes
  // — which returns null whenever latency_s is null EVEN IF first_on_scene exists,
  // so we render NOTHING for the real line in that case (never a fabricated delta).
  // The sim line uses agentLatencyMinutes(spawn, firstArrival, tickMinutes); null
  // (no unit on scene yet) renders the em-dash placeholder.
  const hasScenario = Boolean(
    scenarioRef && tickMinutes !== null && tickMinutes !== undefined,
  )
  const realMin = hasScenario ? realLatencyMinutes(scenarioRef) : null
  const simMin = hasScenario
    ? agentLatencyMinutes(
        mission.spawned_tick,
        agentFirstArrivalTick ?? null,
        tickMinutes as number,
      )
    : null
  const showRealLine = hasScenario && realMin !== null
  const showSimLine = hasScenario
  const scenarioLineCount = (showRealLine ? 1 : 0) + (showSimLine ? 1 : 0)

  // header(2 lines) + each resource row + deadline/priority + optional requester
  // + the scenario reality lines (grown so they never clip — delta #8).
  const bodyRows = rows.length + 2 + (requester ? 1 : 0) + scenarioLineCount
  const H = PAD * 2 + LINE * (2 + bodyRows)

  // Anchor to the right of the marker by default; flip left near the right edge.
  const flipLeft = cx > 360
  const ox = flipLeft ? cx - W - 16 : cx + 16
  const oy = Math.max(4, Math.min(cy - H / 2, 380 - H - 4))

  let row = 0
  const lineY = (i: number) => oy + PAD + LINE * (i + 1)

  return (
    <g style={{ pointerEvents: 'none' }}>
      <rect
        x={ox}
        y={oy}
        width={W}
        height={H}
        rx={4}
        fill={EOC_SURFACE}
        stroke={color}
        strokeWidth={1}
        opacity={0.98}
      />
      {/* Title: mission id + kind */}
      <text x={ox + PAD} y={lineY(row++)} fill={color} fontSize={10} fontFamily="'JetBrains Mono', monospace" fontWeight="700">
        {mission.id} · {mission.kind.replace(/_/g, ' ')}
      </text>
      {/* Status + severity + lives. On a scenario run, lives_at_risk carries an
          INFERRED ghost badge (border-only, neutral — never reads as an error). */}
      {(() => {
        const y = lineY(row++)
        const prefix = `${mission.status} · sev ${mission.severity} · `
        if (!hasScenario) {
          return (
            <text x={ox + PAD} y={y} fill={STATUS_COLORS[mission.status]} fontSize={9} fontFamily="'JetBrains Mono', monospace">
              {prefix}{mission.lives_at_risk}♥
            </text>
          )
        }
        // Approx mono char advance at 9px to place the ghost badge after the lives glyph.
        const CH = 5.4
        const livesText = `${mission.lives_at_risk}♥`
        const badgeX = ox + PAD + (prefix.length + livesText.length) * CH + 4
        const badgeY = y - 8
        const inf = PROVENANCE_COLORS.inferred
        return (
          <g>
            <text x={ox + PAD} y={y} fill={STATUS_COLORS[mission.status]} fontSize={9} fontFamily="'JetBrains Mono', monospace">
              {prefix}{livesText}
            </text>
            {/* INFERRED ghost badge — transparent fill, dotted neutral border. */}
            <rect
              x={badgeX}
              y={badgeY - 1}
              width={48}
              height={12}
              rx={2}
              fill={inf.fill}
              stroke={inf.border}
              strokeWidth={0.75}
              strokeDasharray="2 1.5"
            />
            <text
              x={badgeX + 24}
              y={badgeY + 8}
              textAnchor="middle"
              fill={inf.text}
              fontSize={9}
              fontFamily="'JetBrains Mono', monospace"
              letterSpacing={0.2}
            >
              INFERRED
            </text>
          </g>
        )
      })()}
      {/* Required vs assigned per resource */}
      {rows.map((r) => {
        const y = lineY(row++)
        const met = r.got >= r.req
        return (
          <text key={r.kind} x={ox + PAD} y={y} fontSize={9} fontFamily="'JetBrains Mono', monospace" fill={FALLBACK_COLOR}>
            {r.kind}{' '}
            <tspan fill={met ? STATUS_COLORS.resolved : color} fontWeight="600">
              {r.got}/{r.req}
            </tspan>
          </text>
        )
      })}
      {/* Deadline + priority */}
      <text x={ox + PAD} y={lineY(row++)} fontSize={9} fontFamily="'JetBrains Mono', monospace" fill={FALLBACK_COLOR}>
        deadline T{mission.deadline_tick} · prio {mission.priority}
      </text>
      {/* Progress */}
      <text x={ox + PAD} y={lineY(row++)} fontSize={9} fontFamily="'JetBrains Mono', monospace" fill={FALLBACK_COLOR}>
        progress {Math.round(Math.min(1, mission.progress) * 100)}%
      </text>
      {/* Requester (when known from this tick's resource requests) */}
      {requester && (
        <text x={ox + PAD} y={lineY(row++)} fontSize={9} fontFamily="'JetBrains Mono', monospace" fill={FALLBACK_COLOR}>
          requested by{' '}
          <tspan fill={color} fontWeight="600">{requester}</tspan>
        </text>
      )}
      {/* Scenario reality lines (delta #8). Real first-on-scene baseline (grey),
          then agents-sim latency (arm/kind color). Real line is suppressed when
          the pack's latency_s is null — realLatencyMinutes already returns null. */}
      {showRealLine && (
        <text x={ox + PAD} y={lineY(row++)} fontSize={9} fontFamily="'JetBrains Mono', monospace" fill={FALLBACK_COLOR}>
          first on scene (real):{' '}
          <tspan fontWeight="600">{formatMinutes(realMin)}</tspan>
        </text>
      )}
      {showSimLine && (
        <text x={ox + PAD} y={lineY(row++)} fontSize={9} fontFamily="'JetBrains Mono', monospace" fill={FALLBACK_COLOR}>
          agents (sim):{' '}
          <tspan fill={color} fontWeight="600">{formatMinutes(simMin)}</tspan>
        </text>
      )}
    </g>
  )
}
