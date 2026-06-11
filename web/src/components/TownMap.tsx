import React, { useMemo } from 'react'
import type { WorldState, MissionState } from '../types'
import {
  MISSION_KIND_COLORS,
  STATUS_COLORS,
  FALLBACK_COLOR,
} from '../lib/palette'

// SVG-only chrome colors. Tailwind classes can't reach inside <svg fill>, so
// these read the EOC RGB-channel CSS vars (defined in index.css :root) as
// `rgb(var(--x) / a)` strings — token-driven, zero hex literals in this .tsx
// (the data-driven mission/arm/status colors come from palette.ts). The two
// "blocked district" reds are derived from --signal-red at low alpha rather than
// hardcoded maroons.
const EOC_GROUND = 'rgb(var(--eoc-ground))'
const EOC_SURFACE = 'rgb(var(--eoc-surface))'
const EOC_RAISED = 'rgb(var(--eoc-raised))'
const EOC_BORDER = 'rgb(var(--eoc-border))'
const EOC_GRID = 'rgb(var(--eoc-raised))'
const BLOCKED_FILL = 'rgb(var(--signal-red) / 0.12)'
const BLOCKED_BADGE_FILL = 'rgb(var(--signal-red) / 0.4)'

// Fixed district grid layout — 2 rows × 3 cols inside a 500×380 viewBox.
// GRID_Y offsets the whole 2-row block downward so it reads centred with breathing room.
const GRID_Y = 50  // top margin before row-0 districts
const DISTRICT_LAYOUT: Record<string, { x: number; y: number; w: number; h: number; label: string }> = {
  old_town:           { x: 0,   y: GRID_Y,       w: 160, h: 130, label: 'Old Town' },
  harbor:             { x: 160, y: GRID_Y,       w: 180, h: 130, label: 'Harbor' },
  hospital_district:  { x: 340, y: GRID_Y,       w: 160, h: 130, label: 'Hospital' },
  market:             { x: 0,   y: GRID_Y + 130, w: 200, h: 150, label: 'Market' },
  residential_north:  { x: 200, y: GRID_Y + 130, w: 180, h: 150, label: 'Residential N.' },
  industrial:         { x: 380, y: GRID_Y + 130, w: 120, h: 150, label: 'Industrial' },
}

// Inline monochrome SVG path icons — rendered as SVG <path> elements, scaled to fit
// Each icon is authored on a 24×24 viewBox; caller scales via transform.
const MISSION_ICON_PATHS: Record<string, { d: string; fill?: boolean }> = {
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

function severityRadius(s: number): number {
  return 8 + s * 3
}

type Effects = 'normal' | 'quiet'

interface MissionMarkerProps {
  mission: MissionState
  cx: number
  cy: number
  selected: boolean
  effects: Effects
  onSelect: () => void
}

function MissionMarker({ mission, cx, cy, selected, effects, onSelect }: MissionMarkerProps) {
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
            <svg
              viewBox="0 0 24 24"
              width={iconSize}
              height={iconSize}
              overflow="visible"
            >
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
function MissionPopover({ mission, cx, cy, requester }: MissionPopoverProps) {
  const color = MISSION_KIND_COLORS[mission.kind] ?? FALLBACK_COLOR
  const rows = resourceRows(mission)
  const PAD = 8
  const LINE = 12
  const W = 168
  // header(2 lines) + each resource row + deadline/priority + optional requester
  const bodyRows = rows.length + 2 + (requester ? 1 : 0)
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
      {/* Status + severity */}
      <text x={ox + PAD} y={lineY(row++)} fill={STATUS_COLORS[mission.status]} fontSize={9} fontFamily="'JetBrains Mono', monospace">
        {mission.status} · sev {mission.severity} · {mission.lives_at_risk}♥
      </text>
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
    </g>
  )
}

interface Props {
  world: WorldState
  selectedMissionId: string | null
  onSelectMission: (id: string | null) => void
  /** 'quiet' (compare mode) disables animate-ping + selected drop-shadow. */
  effects?: Effects
  /** District ids to briefly highlight (inject pulse) — keyed by district. */
  pulseDistricts?: string[]
  /** agent_id → mission_id this tick (most recent resource requester per mission). */
  missionRequesters?: Record<string, string>
}

function TownMapImpl({
  world,
  selectedMissionId,
  onSelectMission,
  effects = 'normal',
  pulseDistricts,
  missionRequesters,
}: Props) {
  const SVG_W = 500
  const SVG_H = 380  // expanded: GRID_Y(50) + row0(130) + row1(150) + bottom(50)
  const quiet = effects === 'quiet'

  // Place missions: spread within district rect. Memoized on the missions map
  // so two synced compare maps don't recompute layout every 125ms at 8×.
  const missionPositions = useMemo(() => {
    const positions: Record<string, { cx: number; cy: number }> = {}
    const districtMissions: Record<string, MissionState[]> = {}

    for (const m of Object.values(world.missions)) {
      if (!districtMissions[m.district_id]) districtMissions[m.district_id] = []
      districtMissions[m.district_id].push(m)
    }

    for (const [distId, missions] of Object.entries(districtMissions)) {
      const layout = DISTRICT_LAYOUT[distId]
      if (!layout) continue
      const n = missions.length
      missions.forEach((m, i) => {
        const col = n <= 1 ? 0.5 : (i % 3) / Math.max(1, Math.min(n, 3) - 1)
        const row = n <= 3 ? 0.5 : i < 3 ? 0.33 : 0.67
        positions[m.id] = {
          cx: layout.x + 20 + col * (layout.w - 40),
          cy: layout.y + 24 + row * (layout.h - 48),
        }
      })
    }
    return positions
  }, [world.missions])

  const pulseSet = useMemo(() => new Set(pulseDistricts ?? []), [pulseDistricts])

  const selected = selectedMissionId ? world.missions[selectedMissionId] : undefined
  const selectedPos = selectedMissionId ? missionPositions[selectedMissionId] : undefined

  return (
    <svg
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      className="w-full h-full"
      preserveAspectRatio="xMidYMid meet"
      style={{ background: EOC_GROUND, display: 'block' }}
    >
      {/* District blocks */}
      {Object.entries(DISTRICT_LAYOUT).map(([id, d]) => {
        const dist = world.districts[id]
        const blocked = dist?.road_blocked ?? false
        const pulsing = !quiet && pulseSet.has(id)
        return (
          <g key={id}>
            <rect
              x={d.x + 2}
              y={d.y + 2}
              width={d.w - 4}
              height={d.h - 4}
              rx={4}
              fill={blocked ? BLOCKED_FILL : EOC_SURFACE}
              stroke={blocked ? STATUS_COLORS.failed : EOC_BORDER}
              strokeWidth={blocked ? 2 : 1}
              strokeDasharray={blocked ? '6 3' : undefined}
            />
            {/* Inject-pulse overlay — fades after ~2s via animate-ping on the district */}
            {pulsing && (
              <rect
                x={d.x + 2}
                y={d.y + 2}
                width={d.w - 4}
                height={d.h - 4}
                rx={4}
                fill="none"
                stroke={MISSION_KIND_COLORS.medical_surge}
                strokeWidth={2}
                className="animate-ping"
                style={{ animationDuration: '1s' }}
              />
            )}
            {/* District label */}
            <text
              x={d.x + 8}
              y={d.y + 14}
              fill={blocked ? STATUS_COLORS.failed : FALLBACK_COLOR}
              fontSize={9}
              fontFamily="'Share Tech Mono', monospace"
              letterSpacing={1}
            >
              {d.label.toUpperCase()}
            </text>
            {/* Blocked road indicator — corner badge */}
            {blocked && (
              <g>
                <rect
                  x={d.x + d.w - 46}
                  y={d.y + 4}
                  width={40}
                  height={13}
                  rx={2}
                  fill={BLOCKED_BADGE_FILL}
                  stroke={STATUS_COLORS.failed}
                  strokeWidth={0.5}
                />
                <text
                  x={d.x + d.w - 26}
                  y={d.y + 13}
                  textAnchor="middle"
                  fill={STATUS_COLORS.failed}
                  fontSize={9}
                  fontFamily="'Share Tech Mono', monospace"
                  letterSpacing={0.5}
                >
                  BLOCKED
                </text>
              </g>
            )}
          </g>
        )
      })}

      {/* Grid lines — vertical columns and horizontal row separator */}
      <line x1={160} y1={GRID_Y} x2={160} y2={GRID_Y + 280} stroke={EOC_GRID} strokeWidth={1} />
      <line x1={340} y1={GRID_Y} x2={340} y2={GRID_Y + 280} stroke={EOC_GRID} strokeWidth={1} />
      <line x1={0} y1={GRID_Y + 130} x2={SVG_W} y2={GRID_Y + 130} stroke={EOC_GRID} strokeWidth={1} />

      {/* Mission markers */}
      {Object.values(world.missions).map((m) => {
        const pos = missionPositions[m.id]
        if (!pos) return null
        return (
          <MissionMarker
            key={m.id}
            mission={m}
            cx={pos.cx}
            cy={pos.cy}
            selected={selectedMissionId === m.id}
            effects={effects}
            onSelect={() =>
              onSelectMission(selectedMissionId === m.id ? null : m.id)
            }
          />
        )
      })}

      {/* Pending arrival indicators */}
      {world.pending.map((pa, i) => {
        const layout = DISTRICT_LAYOUT[pa.district_id]
        if (!layout) return null
        return (
          <g key={i} transform={`translate(${layout.x + layout.w - 16},${layout.y + layout.h - 16})`}>
            <circle r={6} fill={`${STATUS_COLORS.open}20`} stroke={STATUS_COLORS.open} strokeWidth={1} />
            <text textAnchor="middle" dominantBaseline="central" fontSize={9} fill={STATUS_COLORS.open}>
              {pa.qty}
            </text>
          </g>
        )
      })}

      {/* Mission popover — rendered last so it sits above markers */}
      {selected && selectedPos && (
        <MissionPopover
          mission={selected}
          cx={selectedPos.cx}
          cy={selectedPos.cy}
          requester={missionRequesters?.[selected.id] ?? null}
        />
      )}
    </svg>
  )
}

export const TownMap = React.memo(TownMapImpl)
