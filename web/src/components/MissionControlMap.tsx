import React, { useMemo } from 'react'
import type {
  WorldState,
  MissionState,
  ScenarioReferenceMission,
} from '../types'
import { MISSION_KIND_COLORS, STATUS_COLORS, FALLBACK_COLOR, CONTENTION_COLOR } from '../lib/palette'
import type { ContentionResult } from '../lib/contention'
import { resourceCode } from '../lib/resources'
import {
  DISTRICT_LAYOUT,
  GRID_Y,
  SVG_W,
  SVG_H,
  EOC_GROUND,
  EOC_BORDER,
  BLOCKED_FILL,
  BLOCKED_BADGE_FILL,
  districtCenter,
  MissionMarker,
  MissionPopover,
  type Effects,
} from './mapShared'

// Token-driven backdrop fills (no hex; read EOC RGB-channel vars at low alpha so
// the schematic water/roads/tiles read as an ops map without fighting the pins).
const TILE_FILL = 'rgb(var(--eoc-surface) / 0.55)'
const ROAD_FILL = 'rgb(var(--text-eoc-faint) / 0.18)'
const WATER_FILL = 'rgb(var(--signal-cyan) / 0.08)'
const WATER_EDGE = 'rgb(var(--signal-cyan) / 0.22)'

interface Props {
  world: WorldState
  selectedMissionId: string | null
  onSelectMission: (id: string | null) => void
  /** 'quiet' disables animation/glow (kept for parity with TownMap; the Map tab
   *  always passes 'normal'). */
  effects?: Effects
  /** District ids to briefly highlight (inject pulse). */
  pulseDistricts?: string[]
  /** agent_id → mission_id this tick (most recent resource requester per mission). */
  missionRequesters?: Record<string, string>
  /** Scenario reality baseline lookup for the selected mission (popover lines). */
  scenarioRefForMission?: (missionId: string) => ScenarioReferenceMission | null
  /** First-arrival tick lookup for the selected mission (sim latency line). */
  agentFirstArrivalForMission?: (missionId: string) => number | null
  /** Pack tick length in minutes — only set on a scenario run. */
  tickMinutes?: number | null
  /** Contention overlay for the current tick (derived in MapTab from proposals +
   *  rulings). Absent → renders nothing extra, identical to a plain tile map. */
  contest?: ContentionResult | null
}

function MissionControlMapImpl({
  world,
  selectedMissionId,
  onSelectMission,
  effects = 'normal',
  pulseDistricts,
  missionRequesters,
  scenarioRefForMission,
  agentFirstArrivalForMission,
  tickMinutes,
  contest,
}: Props) {
  const quiet = effects === 'quiet'

  // Same mission-position logic as TownMap (spread within each district tile),
  // memoized on the missions map so playback stays cheap.
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
  const contestedMissions = contest?.contestedMissions
  const contestPairs = contest?.pairs ?? []

  const selected = selectedMissionId ? world.missions[selectedMissionId] : undefined
  const selectedPos = selectedMissionId ? missionPositions[selectedMissionId] : undefined

  return (
    <svg
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      className="w-full h-full"
      preserveAspectRatio="xMidYMid meet"
      style={{ background: EOC_GROUND, display: 'block' }}
    >
      <defs>
        <marker id="mc-arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
          <path d="M0,0 L7,4 L0,8 Z" fill={CONTENTION_COLOR} />
        </marker>
      </defs>

      {/* ---- Schematic ops backdrop (static; reads as a geographic tile map) ---- */}
      {/* Water — fills the top margin directly above the harbor column, with a
          lit edge meeting the harbor tile so it reads as the coastline. */}
      <rect x={160} y={2} width={180} height={46} fill={WATER_FILL} />
      <rect x={160} y={46} width={180} height={2} fill={WATER_EDGE} />
      {/* Road grid — muted bands under the column/row boundaries, drawn behind tiles. */}
      <rect x={158} y={GRID_Y} width={4} height={280} fill={ROAD_FILL} />
      <rect x={338} y={GRID_Y} width={4} height={280} fill={ROAD_FILL} />
      <rect x={0} y={GRID_Y + 128} width={SVG_W} height={4} fill={ROAD_FILL} />

      {/* ---- District tiles ---- */}
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
              rx={5}
              fill={blocked ? BLOCKED_FILL : TILE_FILL}
              stroke={blocked ? STATUS_COLORS.failed : EOC_BORDER}
              strokeWidth={blocked ? 2 : 1}
              strokeDasharray={blocked ? '6 3' : undefined}
            />
            {pulsing && (
              <rect
                x={d.x + 2}
                y={d.y + 2}
                width={d.w - 4}
                height={d.h - 4}
                rx={5}
                fill="none"
                stroke={MISSION_KIND_COLORS.medical_surge}
                strokeWidth={2}
                className="animate-ping"
                style={{ animationDuration: '1s' }}
              />
            )}
            <text
              x={d.x + 8}
              y={d.y + 14}
              fill={blocked ? STATUS_COLORS.failed : FALLBACK_COLOR}
              fontSize={9}
              fontFamily="'Share Tech Mono', monospace"
              letterSpacing={1}
            >
              {(dist?.name ?? d.label).toUpperCase()}
            </text>
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

      {/* ---- Contention links (district-center → district-center), below pins ---- */}
      {!quiet &&
        contestPairs.map((p) => {
          const a = districtCenter(p.loserDistrict)
          const b = districtCenter(p.winnerDistrict)
          if (!a || !b) return null
          const mx = (a.x + b.x) / 2
          const my = (a.y + b.y) / 2
          const label = `${p.resources.map(resourceCode).join('+')} CONTESTED`
          // Badge width tracks the (mono) label so combined labels never clip.
          const bw = label.length * 5.6 + 14
          return (
            <g key={`${p.loserDistrict}->${p.winnerDistrict}`}>
              <line
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={CONTENTION_COLOR}
                strokeWidth={1.5}
                strokeDasharray="5 4"
                opacity={0.85}
                markerEnd="url(#mc-arrow)"
                className="mc-contest-link"
              />
              <rect
                x={mx - bw / 2}
                y={my - 9}
                width={bw}
                height={18}
                rx={3}
                fill={EOC_GROUND}
                stroke={CONTENTION_COLOR}
                strokeWidth={1}
                opacity={0.96}
              />
              <text
                x={mx}
                y={my + 4}
                textAnchor="middle"
                fontSize={9}
                fontFamily="'JetBrains Mono', monospace"
                fill={CONTENTION_COLOR}
                letterSpacing={1}
              >
                {label}
              </text>
            </g>
          )
        })}

      {/* ---- Mission markers (rich; shared with TownMap) ---- */}
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
            contested={contestedMissions?.has(m.id) ?? false}
            onSelect={() => onSelectMission(selectedMissionId === m.id ? null : m.id)}
          />
        )
      })}

      {/* ---- Pending arrivals ---- */}
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

      {/* ---- Popover (top) ---- */}
      {selected && selectedPos && (
        <MissionPopover
          mission={selected}
          cx={selectedPos.cx}
          cy={selectedPos.cy}
          requester={missionRequesters?.[selected.id] ?? null}
          scenarioRef={scenarioRefForMission?.(selected.id) ?? null}
          agentFirstArrivalTick={agentFirstArrivalForMission?.(selected.id) ?? null}
          tickMinutes={tickMinutes ?? null}
        />
      )}
    </svg>
  )
}

export const MissionControlMap = React.memo(MissionControlMapImpl)
