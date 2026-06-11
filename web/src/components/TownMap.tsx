import type { WorldState, MissionState } from '../types'

// Fixed district grid layout (col, row, colSpan, rowSpan in a 6×4 grid)
const DISTRICT_LAYOUT: Record<string, { x: number; y: number; w: number; h: number; label: string }> = {
  old_town:           { x: 0,   y: 0,   w: 160, h: 120, label: 'Old Town' },
  harbor:             { x: 160, y: 0,   w: 180, h: 120, label: 'Harbor' },
  hospital_district:  { x: 340, y: 0,   w: 160, h: 120, label: 'Hospital' },
  market:             { x: 0,   y: 120, w: 200, h: 140, label: 'Market' },
  residential_north:  { x: 200, y: 120, w: 180, h: 140, label: 'Residential N.' },
  industrial:         { x: 380, y: 120, w: 120, h: 140, label: 'Industrial' },
}

const MISSION_COLORS: Record<string, string> = {
  fire: '#ef4444',
  collapse_rescue: '#f59e0b',
  medical_surge: '#22d3ee',
  infra_repair: '#a78bfa',
}

const MISSION_ICONS: Record<string, string> = {
  fire: '🔥',
  collapse_rescue: '🏚',
  medical_surge: '➕',
  infra_repair: '🔧',
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
      {/* Icon */}
      <text textAnchor="middle" dominantBaseline="central" fontSize={r * 0.9} style={{ userSelect: 'none' }}>
        {MISSION_ICONS[mission.kind] ?? '?'}
      </text>
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
      {/* Staffing pips row */}
      {isOpen && totalRequired > 0 && (
        <g transform={`translate(${-totalRequired * 4},${r + 20})`}>
          {Array.from({ length: totalRequired }).map((_, i) => (
            <rect
              key={i}
              x={i * 8}
              y={0}
              width={6}
              height={4}
              rx={1}
              fill={i < totalAssigned ? color : '#243047'}
              opacity={0.9}
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
  const SVG_H = 280

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
      style={{ background: '#0a0e1a' }}
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
            {/* Blocked road indicator */}
            {blocked && (
              <text
                x={d.x + d.w - 8}
                y={d.y + 14}
                textAnchor="end"
                fill="#ef4444"
                fontSize={9}
                fontFamily="'Share Tech Mono', monospace"
              >
                BLOCKED
              </text>
            )}
          </g>
        )
      })}

      {/* Grid lines */}
      <line x1={160} y1={0} x2={160} y2={SVG_H} stroke="#1a2235" strokeWidth={1} />
      <line x1={340} y1={0} x2={340} y2={SVG_H} stroke="#1a2235" strokeWidth={1} />
      <line x1={0} y1={120} x2={SVG_W} y2={120} stroke="#1a2235" strokeWidth={1} />

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
