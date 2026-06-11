import type { ResourcePoolState } from '../types'
import { MISSION_KIND_COLORS, STATUS_COLORS, FALLBACK_COLOR } from '../lib/palette'

const RESOURCE_LABELS: Record<string, string> = {
  ambulance: 'AMB',
  rescue_crew: 'RSC',
  fire_engine: 'FEG',
  repair_crew: 'RPR',
  supply_truck: 'SUP',
}

// Resource hues reuse the canonical mission-kind / status palette entries so no
// raw hex lives here: ambulance=cyan, rescue=amber, fire=red, repair=violet,
// supply=green.
const RESOURCE_COLORS: Record<string, string> = {
  ambulance: MISSION_KIND_COLORS.medical_surge,
  rescue_crew: MISSION_KIND_COLORS.collapse_rescue,
  fire_engine: MISSION_KIND_COLORS.fire,
  repair_crew: MISSION_KIND_COLORS.infra_repair,
  supply_truck: STATUS_COLORS.resolved,
}

interface PoolRowProps {
  pool: ResourcePoolState
}

function PoolRow({ pool }: PoolRowProps) {
  const color = RESOURCE_COLORS[pool.kind] ?? FALLBACK_COLOR
  const label = RESOURCE_LABELS[pool.kind] ?? pool.kind.toUpperCase().slice(0, 3)
  const pct = pool.total > 0 ? pool.available / pool.total : 0
  const depleted = pool.available === 0

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center justify-between">
        <span
          className="text-[11px] font-mono"
          style={{ color: depleted ? STATUS_COLORS.failed : color }}
        >
          {label}
        </span>
        <span
          className="text-[11px] font-mono tabular-nums"
          style={{ color: depleted ? STATUS_COLORS.failed : FALLBACK_COLOR }}
        >
          {pool.available}/{pool.total}
        </span>
      </div>
      <div className="h-1 bg-eoc-raised rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{
            width: `${pct * 100}%`,
            background: depleted ? STATUS_COLORS.failed : color,
            boxShadow: depleted ? undefined : `0 0 3px ${color}60`,
          }}
        />
      </div>
      {/* Unit pips */}
      <div className="flex gap-0.5 mt-0.5">
        {Array.from({ length: pool.total }).map((_, i) => (
          <div
            key={i}
            className="w-3 h-3 rounded-sm border border-eoc-border"
            style={{
              borderColor: i < pool.available ? color : undefined,
              background: i < pool.available ? `${color}30` : 'transparent',
            }}
          />
        ))}
      </div>
    </div>
  )
}

interface Props {
  pools: Record<string, ResourcePoolState>
}

export function ResourcePoolSidebar({ pools }: Props) {
  const ordered = ['ambulance', 'rescue_crew', 'fire_engine', 'repair_crew', 'supply_truck']

  return (
    <div className="flex flex-col gap-3 p-3 bg-eoc-surface border border-eoc-border rounded-lg">
      <h3 className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary">
        Resource Pools
      </h3>
      {ordered.map((k) => {
        const pool = pools[k]
        if (!pool) return null
        return <PoolRow key={k} pool={pool} />
      })}
    </div>
  )
}
