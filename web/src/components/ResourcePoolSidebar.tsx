import type { ResourcePoolState } from '../types'

const RESOURCE_LABELS: Record<string, string> = {
  ambulance: 'AMB',
  rescue_crew: 'RSC',
  fire_engine: 'FEG',
  repair_crew: 'RPR',
  supply_truck: 'SUP',
}

const RESOURCE_COLORS: Record<string, string> = {
  ambulance: '#22d3ee',
  rescue_crew: '#f59e0b',
  fire_engine: '#ef4444',
  repair_crew: '#a78bfa',
  supply_truck: '#4ade80',
}

interface PoolRowProps {
  pool: ResourcePoolState
}

function PoolRow({ pool }: PoolRowProps) {
  const color = RESOURCE_COLORS[pool.kind] ?? '#94a3b8'
  const label = RESOURCE_LABELS[pool.kind] ?? pool.kind.toUpperCase().slice(0, 3)
  const pct = pool.total > 0 ? pool.available / pool.total : 0
  const depleted = pool.available === 0

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center justify-between">
        <span
          className="text-[10px] font-mono tracking-wider"
          style={{ color: depleted ? '#ef4444' : color }}
        >
          {label}
        </span>
        <span
          className="text-[10px] font-mono tabular-nums"
          style={{ color: depleted ? '#ef4444' : '#94a3b8' }}
        >
          {pool.available}/{pool.total}
        </span>
      </div>
      <div className="h-1 bg-[#1a2235] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{
            width: `${pct * 100}%`,
            background: depleted ? '#ef4444' : color,
            boxShadow: depleted ? undefined : `0 0 3px ${color}60`,
          }}
        />
      </div>
      {/* Unit pips */}
      <div className="flex gap-0.5 mt-0.5">
        {Array.from({ length: pool.total }).map((_, i) => (
          <div
            key={i}
            className="w-3 h-3 rounded-sm border"
            style={{
              borderColor: i < pool.available ? color : '#243047',
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
    <div className="flex flex-col gap-3 p-3 bg-[#0f1624] border border-[#243047] rounded-lg">
      <h3 className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
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
