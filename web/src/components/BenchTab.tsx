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

const CHART_H = 200   // usable pixel height for bars
const LABEL_H = 20    // space below bars for arm name

function BarChart({ arms }: { arms: Record<string, BenchArm> }) {
  const visibleArms = ARM_ORDER.filter((a) => arms[a])

  // Scale: 0 → CHART_H px, max → 0 px (bars grow upward).
  // 14% headroom so the tallest whisker's value label never clips the chart top.
  const maxVal = Math.ceil(
    Math.max(...visibleArms.map((a) => arms[a].mean_lives_saved + (arms[a].sd_lives_saved ?? 0)), 1) *
      1.14
  )

  const toY = (v: number) => CHART_H - Math.max(0, Math.min(1, v / maxVal)) * CHART_H

  const totalW = 400
  const barW = Math.floor(totalW / Math.max(visibleArms.length, 1) * 0.5)
  const gap = Math.floor(totalW / Math.max(visibleArms.length, 1))

  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
        Lives Saved — Mean ± SD
      </h3>
      <svg
        viewBox={`0 0 ${totalW} ${CHART_H + LABEL_H}`}
        className="w-full"
        style={{ height: CHART_H + LABEL_H }}
        aria-label="Bar chart of lives saved per arm"
      >
        {/* Baseline */}
        <line x1={0} y1={CHART_H} x2={totalW} y2={CHART_H} stroke="#243047" strokeWidth={1} />

        {visibleArms.map((armId, idx) => {
          const arm = arms[armId]
          const color = ARM_COLORS[armId] ?? '#94a3b8'
          const mean = arm.mean_lives_saved
          const sd = arm.sd_lives_saved ?? 0
          const cx = gap * idx + gap / 2
          const barTop = toY(mean)
          const barHeight = CHART_H - barTop
          const sdTopY = toY(mean + sd)
          const sdBotY = toY(Math.max(0, mean - sd))
          const capW = barW * 0.6
          // value label sits above the whisker top
          const labelY = Math.max(sdTopY - 6, 4)

          return (
            <g key={armId}>
              {/* Bar */}
              <rect
                x={cx - barW / 2}
                y={barTop}
                width={barW}
                height={Math.max(barHeight, 1)}
                rx={2}
                fill={`url(#grad-${armId})`}
                style={{ filter: `drop-shadow(0 0 4px ${color}40)` }}
              />
              {/* Gradient def */}
              <defs>
                <linearGradient id={`grad-${armId}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.85} />
                  <stop offset="100%" stopColor={color} stopOpacity={0.35} />
                </linearGradient>
              </defs>

              {/* SD whisker — vertical line */}
              <line
                x1={cx} y1={sdTopY}
                x2={cx} y2={sdBotY}
                stroke={`${color}b0`}
                strokeWidth={1.5}
              />
              {/* Top cap */}
              <line
                x1={cx - capW / 2} y1={sdTopY}
                x2={cx + capW / 2} y2={sdTopY}
                stroke={color}
                strokeWidth={1.5}
              />
              {/* Bottom cap */}
              <line
                x1={cx - capW / 2} y1={sdBotY}
                x2={cx + capW / 2} y2={sdBotY}
                stroke={color}
                strokeWidth={1.5}
              />

              {/* Value label above whisker */}
              <text
                x={cx}
                y={labelY}
                textAnchor="middle"
                fill={color}
                fontSize={10}
                fontFamily="'JetBrains Mono', monospace"
                fontWeight="600"
              >
                {mean.toFixed(1)}
              </text>

              {/* Arm name */}
              <text
                x={cx}
                y={CHART_H + LABEL_H - 4}
                textAnchor="middle"
                fill={color}
                fontSize={9}
                fontFamily="'JetBrains Mono', monospace"
                letterSpacing={1}
              >
                {armId.toUpperCase()}
              </text>
            </g>
          )
        })}
      </svg>
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
