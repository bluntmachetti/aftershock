import { useState, useEffect } from 'react'
import type { BenchResult, BenchArm } from '../types'
import { api } from '../lib/api'

const ARM_COLORS: Record<string, string> = {
  scripted: '#94a3b8',
  solo: '#f59e0b',
  swarm: '#22d3ee',
  society: '#4ade80',
}

const ARM_ORDER = ['scripted', 'solo', 'swarm', 'society']

function BarChart({ arms }: { arms: Record<string, BenchArm> }) {
  const maxVal = Math.max(
    ...Object.values(arms).map((a) => a.mean_lives_saved + (a.sd_lives_saved ?? 0)),
    1,
  )

  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
        Lives Saved — Mean ± SD
      </h3>
      <div className="flex items-end gap-4 h-40 px-2">
        {ARM_ORDER.filter((a) => arms[a]).map((armId) => {
          const arm = arms[armId]
          const color = ARM_COLORS[armId] ?? '#94a3b8'
          const barH = (arm.mean_lives_saved / maxVal) * 100
          const sdH = ((arm.sd_lives_saved ?? 0) / maxVal) * 100

          return (
            <div key={armId} className="flex flex-col items-center gap-1 flex-1">
              <div className="relative w-full flex flex-col items-center justify-end" style={{ height: '100%' }}>
                {/* SD error bar */}
                <div
                  className="absolute w-0.5 rounded"
                  style={{
                    background: `${color}80`,
                    height: `${Math.min(sdH * 2, 100 - barH)}%`,
                    bottom: `${barH}%`,
                  }}
                />
                {/* Bar */}
                <div
                  className="w-full rounded-t transition-all duration-500"
                  style={{
                    height: `${barH}%`,
                    background: `linear-gradient(to top, ${color}cc, ${color}60)`,
                    boxShadow: `0 0 8px ${color}40`,
                    minHeight: '2px',
                  }}
                />
                {/* Value */}
                <div
                  className="absolute text-[10px] font-mono tabular-nums font-semibold"
                  style={{ bottom: `${barH + 2}%`, color }}
                >
                  {arm.mean_lives_saved.toFixed(1)}
                </div>
              </div>
              <span
                className="text-[10px] font-mono uppercase tracking-wider"
                style={{ color }}
              >
                {armId}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function CostTable({ arms }: { arms: Record<string, BenchArm> }) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
        Cost & Efficiency
      </h3>
      <table className="w-full text-[11px] font-mono">
        <thead>
          <tr className="border-b border-[#243047]">
            {['Arm', 'N', 'Mean Saved', 'SD', 'Cost USD', 'Lives/$'].map((h) => (
              <th key={h} className="text-left py-1 px-2 text-[9px] uppercase tracking-widest text-slate-500">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ARM_ORDER.filter((a) => arms[a]).map((armId) => {
            const arm = arms[armId]
            const color = ARM_COLORS[armId] ?? '#94a3b8'
            return (
              <tr key={armId} className="border-b border-[#1a2235] hover:bg-[#1a2235] transition-colors">
                <td className="py-1 px-2 font-semibold" style={{ color }}>
                  {armId}
                </td>
                <td className="py-1 px-2 tabular-nums text-slate-400">{arm.n}</td>
                <td className="py-1 px-2 tabular-nums text-slate-200">
                  {arm.mean_lives_saved.toFixed(1)}
                </td>
                <td className="py-1 px-2 tabular-nums text-slate-500">
                  ±{(arm.sd_lives_saved ?? 0).toFixed(1)}
                </td>
                <td className="py-1 px-2 tabular-nums text-slate-400">
                  {arm.mean_cost_usd > 0 ? `$${arm.mean_cost_usd.toFixed(4)}` : '—'}
                </td>
                <td className="py-1 px-2 tabular-nums text-green-400">
                  {arm.lives_per_dollar != null
                    ? arm.lives_per_dollar.toFixed(1)
                    : '∞'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="text-[9px] text-slate-600 font-mono mt-1">
        * Scripted arm has zero API cost. Lives/$ omitted. SD from sample variance across seeds.
      </p>
    </div>
  )
}

export function BenchTab() {
  const [results, setResults] = useState<BenchResult[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .bench()
      .then((r) => { setResults(r); setLoading(false) })
      .catch((e: Error) => { setError(e.message); setLoading(false) })
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-amber-400 font-mono animate-pulse">
        Loading bench results…
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-red-400 font-mono text-sm">
        Error: {error}
      </div>
    )
  }

  if (results.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-slate-600 font-mono text-sm">
        <span>No bench results found.</span>
        <span className="text-[11px] text-slate-700">
          Run <code className="text-amber-500">aftershock bench</code> to generate results.
        </span>
      </div>
    )
  }

  const latest = results[0]

  return (
    <div className="p-6 overflow-y-auto h-full">
      <div className="max-w-3xl mx-auto flex flex-col gap-8">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-amber-500" />
          <h2 className="text-sm font-mono uppercase tracking-widest text-amber-400">
            Benchmark Results
          </h2>
        </div>

        {latest.arms && (
          <>
            <div className="bg-[#0f1624] border border-[#243047] rounded-lg p-4">
              <BarChart arms={latest.arms} />
            </div>
            <div className="bg-[#0f1624] border border-[#243047] rounded-lg p-4">
              <CostTable arms={latest.arms} />
            </div>
          </>
        )}

        {/* Paired table */}
        {latest.paired && Object.keys(latest.paired).length > 0 && (
          <div className="bg-[#0f1624] border border-[#243047] rounded-lg p-4">
            <h3 className="text-[10px] font-mono uppercase tracking-widest text-slate-500 mb-3">
              Per-Seed Paired: Lives Saved
            </h3>
            <div className="overflow-x-auto">
              <table className="text-[10px] font-mono w-full">
                <thead>
                  <tr className="border-b border-[#243047]">
                    <th className="text-left py-1 px-2 text-slate-500">Arm</th>
                    {Object.keys(Object.values(latest.paired)[0] ?? {}).map((seed) => (
                      <th key={seed} className="text-right py-1 px-2 text-slate-500">
                        s{seed}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(latest.paired).map(([armId, seeds]) => {
                    const color = ARM_COLORS[armId] ?? '#94a3b8'
                    return (
                      <tr key={armId} className="border-b border-[#1a2235]">
                        <td className="py-1 px-2 font-semibold" style={{ color }}>
                          {armId}
                        </td>
                        {Object.values(seeds).map((v, i) => (
                          <td key={i} className="text-right py-1 px-2 tabular-nums text-slate-300">
                            {typeof v === 'number' ? v.toFixed(0) : String(v)}
                          </td>
                        ))}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
