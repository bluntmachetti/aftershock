import type { WorldState, MissionState } from '../types'

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

const MISSION_COLORS: Record<string, string> = {
  fire: '#ef4444',
  collapse_rescue: '#f59e0b',
  medical_surge: '#22d3ee',
  infra_repair: '#a78bfa',
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

interface MissionMarkerProps {
  mission: MissionState
  cx: number
  cy: number
  selected: boolean
  onSelect: () => void
}

function MissionMarker({ mission, cx, cy, selected, onSelect }: MissionMarkerProps) {
  const color = MISSION_COLORS[mission.kind] ?? '#94a3b8'
  const r = severityRadius(mission.severity)
  const isOpen = mission.status === 'open'
  const pct = Math.min(1, mission.progress)

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
      style={{ filter: selected ? `drop-shadow(0 0 6px ${color})` : undefined }}
    >
      {/* Outer glow ring for active missions */}
      {isOpen && (
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
      <circle r={r} fill="#0f1624" stroke={color} strokeWidth={selected ? 2 : 1.5} opacity={isOpen ? 1 : 0.4} />
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
        <circle r={r - 2} fill="#4ade8020" stroke="#4ade80" strokeWidth={1} />
      )}
      {mission.status === 'failed' && (
        <circle r={r - 2} fill="#ef444420" stroke="#ef4444" strokeWidth={1} />
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
              fill={i < totalAssigned ? color : '#243047'}
              stroke={i < totalAssigned ? `${color}60` : '#1a2235'}
              strokeWidth={0.5}
              opacity={0.95}
            />
          ))}
        </g>
      )}
    </g>
  )
}

interface Props {
  world: WorldState
  selectedMissionId: string | null
  onSelectMission: (id: string | null) => void
}

export function TownMap({ world, selectedMissionId, onSelectMission }: Props) {
  const SVG_W = 500
  const SVG_H = 380  // expanded: GRID_Y(50) + row0(130) + row1(150) + bottom(50)

  // Place missions: spread within district rect
  const missionPositions: Record<string, { cx: number; cy: number }> = {}
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
      missionPositions[m.id] = {
        cx: layout.x + 20 + col * (layout.w - 40),
        cy: layout.y + 24 + row * (layout.h - 48),
      }
    })
  }

  return (
    <svg
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      className="w-full h-full"
      preserveAspectRatio="xMidYMid meet"
      style={{ background: '#0a0e1a', display: 'block' }}
    >
      {/* District blocks */}
      {Object.entries(DISTRICT_LAYOUT).map(([id, d]) => {
        const dist = world.districts[id]
        const blocked = dist?.road_blocked ?? false
        return (
          <g key={id}>
            <rect
              x={d.x + 2}
              y={d.y + 2}
              width={d.w - 4}
              height={d.h - 4}
              rx={4}
              fill={blocked ? '#1a0a0a' : '#0f1624'}
              stroke={blocked ? '#7f1d1d' : '#243047'}
              strokeWidth={blocked ? 2 : 1}
              strokeDasharray={blocked ? '6 3' : undefined}
            />
            {/* District label */}
            <text
              x={d.x + 8}
              y={d.y + 14}
              fill={blocked ? '#ef4444' : '#475569'}
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
                  fill="#7f1d1d"
                  stroke="#ef4444"
                  strokeWidth={0.5}
                />
                <text
                  x={d.x + d.w - 26}
                  y={d.y + 13}
                  textAnchor="middle"
                  fill="#ef4444"
                  fontSize={8}
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
      <line x1={160} y1={GRID_Y} x2={160} y2={GRID_Y + 280} stroke="#1a2235" strokeWidth={1} />
      <line x1={340} y1={GRID_Y} x2={340} y2={GRID_Y + 280} stroke="#1a2235" strokeWidth={1} />
      <line x1={0} y1={GRID_Y + 130} x2={SVG_W} y2={GRID_Y + 130} stroke="#1a2235" strokeWidth={1} />

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
            <circle r={6} fill="#f59e0b20" stroke="#f59e0b" strokeWidth={1} />
            <text textAnchor="middle" dominantBaseline="central" fontSize={7} fill="#f59e0b">
              {pa.qty}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
