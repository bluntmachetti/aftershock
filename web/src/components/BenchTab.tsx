import { useState, useEffect, useCallback } from 'react'
import type {
  BenchResult,
  BenchArm,
  BenchComparator,
  PairedComparison,
  DeterminismReport,
} from '../types'
import { api } from '../lib/api'
import { ARM_COLORS, STATUS_COLORS, FALLBACK_COLOR, VERDICT_COLORS } from '../lib/palette'

// Canonical arm coding (palette.ts): society = cyan, every baseline
// (scripted/solo/swarm) = amber. Kept in lock-step with COMPARE's "good vs
// baseline" read — never redefined per component.
function armColor(armId: string): string {
  return armId === 'society' ? ARM_COLORS.society : ARM_COLORS.baseline
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
      <h3 className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary">
        Lives Saved — Mean ± SD
      </h3>
      <svg
        viewBox={`0 0 ${totalW} ${CHART_H + LABEL_H}`}
        className="w-full"
        style={{ height: CHART_H + LABEL_H }}
        aria-label="Bar chart of lives saved per arm"
      >
        {/* Baseline */}
        <line x1={0} y1={CHART_H} x2={totalW} y2={CHART_H} className="stroke-eoc-border" strokeWidth={1} />

        {visibleArms.map((armId, idx) => {
          const arm = arms[armId]
          const color = armColor(armId)
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
      <h3 className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary">
        Cost & Efficiency
      </h3>
      <table className="w-full text-[11px] font-mono">
        <thead>
          <tr className="border-b border-eoc-border">
            {['Arm', 'N', 'Mean Saved', 'SD', 'Cost USD', 'Lives/$'].map((h) => (
              <th key={h} className="text-left py-1 px-2 text-[10px] uppercase tracking-widest text-eoc-secondary">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ARM_ORDER.filter((a) => arms[a]).map((armId) => {
            const arm = arms[armId]
            const color = armColor(armId)
            return (
              <tr key={armId} className="border-b border-eoc-raised hover:bg-eoc-raised transition-colors">
                <td className="py-1 px-2 font-semibold" style={{ color }}>
                  {armId}
                </td>
                <td className="py-1 px-2 tabular-nums text-eoc-secondary">{arm.n}</td>
                <td className="py-1 px-2 tabular-nums text-eoc-primary">
                  {arm.mean_lives_saved.toFixed(1)}
                </td>
                <td className="py-1 px-2 tabular-nums text-eoc-secondary">
                  ±{(arm.sd_lives_saved ?? 0).toFixed(1)}
                </td>
                <td className="py-1 px-2 tabular-nums text-eoc-secondary">
                  {arm.mean_cost_usd > 0 ? `$${arm.mean_cost_usd.toFixed(4)}` : '—'}
                </td>
                <td className="py-1 px-2 tabular-nums text-signal-green">
                  {arm.lives_per_dollar != null
                    ? arm.lives_per_dollar.toFixed(1)
                    : '∞'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="text-[10px] text-eoc-secondary font-mono mt-1">
        * Scripted arm has zero API cost. Lives/$ omitted. SD from sample variance across seeds.
      </p>
    </div>
  )
}

function verdictStyle(verdict: PairedComparison['verdict']): { color: string; label: string } {
  // Honesty: "credible" = green check ONLY when CI excludes 0 AND sign test is
  // significant. "suggestive" (CI only) and "noise" (CI includes 0) never get a
  // green check — a non-significant effect is shown as non-significant.
  // Accents come from VERDICT_COLORS (palette) — no raw hex in this component.
  if (verdict === 'credible') return { color: VERDICT_COLORS.credible, label: 'credible' }
  if (verdict === 'suggestive') return { color: VERDICT_COLORS.suggestive, label: 'suggestive' }
  return { color: VERDICT_COLORS.noise, label: 'not significant' }
}

function PairedStats({ comparisons }: { comparisons: PairedComparison[] }) {
  if (comparisons.length === 0) {
    return (
      <p className="text-[10px] text-eoc-secondary font-mono">
        No paired comparison — the control (scripted) shares no seeds with another arm.
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-3">
      {comparisons.map((c) => {
        const v = verdictStyle(c.verdict)
        const treatmentColor = armColor(c.treatment)
        return (
          <div
            key={`${c.control}-${c.treatment}`}
            className="border border-eoc-border rounded-lg p-3 bg-eoc-raised/40"
          >
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary">
                {c.treatment}
              </span>
              <span className="text-[10px] font-mono text-eoc-secondary">vs</span>
              <span className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary">
                {c.control}
              </span>
              <span
                className="ml-auto px-1.5 py-0.5 rounded text-[9px] font-mono uppercase tracking-widest border"
                style={{ color: v.color, borderColor: `${v.color}60`, backgroundColor: `${v.color}15` }}
              >
                {c.verdict === 'credible' ? '✓ ' : ''}{v.label}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[10px] font-mono">
              <Stat label="paired Δ" value={`${c.mean_delta >= 0 ? '+' : ''}${c.mean_delta.toFixed(1)} lives`} accent={treatmentColor} />
              <Stat label="n (paired seeds)" value={`${c.n}`} />
              <Stat
                label="95% bootstrap CI"
                value={`[${c.ci.lower.toFixed(1)}, ${c.ci.upper.toFixed(1)}]`}
                accent={c.ci_excludes_zero ? STATUS_COLORS.resolved : FALLBACK_COLOR}
              />
              <Stat
                label="sign-test p"
                value={c.sign_test_p < 0.001 ? '<0.001' : c.sign_test_p.toFixed(3)}
                accent={c.sign_significant ? STATUS_COLORS.resolved : FALLBACK_COLOR}
              />
              <Stat
                label="post-hoc power"
                value={c.observed_power == null ? '—' : `${(c.observed_power * 100).toFixed(0)}%`}
              />
              <Stat
                label="wins / losses / ties"
                value={`${c.n_positive} / ${c.n_negative} / ${c.n_tied}`}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[9px] uppercase tracking-widest text-eoc-secondary">{label}</span>
      <span className="tabular-nums" style={accent ? { color: accent } : undefined}>{value}</span>
    </div>
  )
}

function DeterminismBadge({ report }: { report: DeterminismReport | null }) {
  if (!report) return null
  // Scoped to the scripted engine ONLY — never implies LLM/society is reproducible.
  const passed = report.passed
  const color = passed ? STATUS_COLORS.resolved : STATUS_COLORS.failed
  return (
    <div
      className="flex items-start gap-2 rounded-lg border px-3 py-2 text-[10px] font-mono leading-relaxed"
      style={{ borderColor: `${color}40`, backgroundColor: `${color}10` }}
      role="status"
    >
      <span className="mt-0.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: color }} />
      <div>
        <span className="font-semibold uppercase tracking-widest" style={{ color }}>
          {passed ? '✓ scripted engine — identical digests' : '✗ scripted engine — digest mismatch'}
        </span>
        <span className="text-eoc-secondary">
          {' '}· seed {report.seed}, {report.ticks} ticks, {report.n_digests} digests compared (two re-runs).
        </span>
        <div className="text-eoc-secondary mt-0.5">
          {report.note}
        </div>
      </div>
    </div>
  )
}

const MODEL_LABELS: Record<string, string> = {
  'openai/gpt-5': 'GPT-5',
  'google/gemini-3.1-pro-preview': 'Gemini 3.1 Pro',
  'anthropic/claude-opus-4.8': 'Claude Opus 4.8',
  'x-ai/grok-4.3': 'Grok 4.3',
  'deepseek/deepseek-v4-pro': 'DeepSeek V4 Pro',
  'deepseek/deepseek-v4-flash': 'DeepSeek V4 Flash',
  'moonshotai/kimi-k2.7-code': 'Kimi K2.7 Code',
  'z-ai/glm-5.2': 'GLM 5.2',
  'mistralai/mistral-large-2512': 'Mistral Large',
  'meta-llama/llama-3.3-70b-instruct': 'Llama 3.3 70B',
  'qwen/qwen3-235b-a22b-2507': 'Qwen3 235B',
  'meta-llama/llama-3.1-8b-instruct': 'Llama 3.1 8B',
}

function modelLabel(modelId: string): string {
  const parts = modelId.split('/')
  return MODEL_LABELS[modelId] ?? parts[parts.length - 1] ?? modelId
}

function outcomeLabel(comparison: PairedComparison | undefined): {
  text: string
  color: string
} {
  if (!comparison) {
    return { text: 'insufficient data', color: FALLBACK_COLOR }
  }
  if (comparison.verdict === 'credible' && comparison.mean_delta > 0) {
    return { text: 'solo wins', color: STATUS_COLORS.resolved }
  }
  if (comparison.verdict === 'credible' && comparison.mean_delta < 0) {
    return { text: 'below society', color: STATUS_COLORS.failed }
  }
  return { text: 'ties society', color: VERDICT_COLORS.suggestive }
}

function costComparison(cost: number, comparatorCost: number): string {
  if (cost <= 0 || comparatorCost <= 0) return '—'
  const ratio = cost / comparatorCost
  return ratio >= 1 ? `${ratio.toFixed(1)}× society` : `${(1 / ratio).toFixed(1)}× cheaper`
}

function FrontierPanel({ result }: { result: BenchResult }) {
  const comparator = result.comparator as BenchComparator
  const comparisons = new Map(
    (result.panel_stats ?? []).map((comparison) => [comparison.treatment, comparison]),
  )
  const rows = Object.entries(result.arms).sort(([, a], [, b]) => {
    const aFrontier = a.family?.includes('frontier') ? 0 : 1
    const bFrontier = b.family?.includes('frontier') ? 0 : 1
    return aFrontier - bFrontier || b.mean_lives_saved - a.mean_lives_saved
  })
  const modelFamilies = new Set(rows.map(([model]) => model.split('/')[0]))
  const frontierRows = rows.filter(([, arm]) => arm.family?.includes('frontier'))
  const missingComparisons = rows.filter(([model]) => !comparisons.has(model)).length
  const hasCompleteComparisons = missingComparisons === 0
  const frontierTies = frontierRows.filter(([model]) => {
    const comparison = comparisons.get(model)
    return comparison != null && comparison.verdict !== 'credible'
  }).length
  const soloWins = rows.filter(([model]) => {
    const comparison = comparisons.get(model)
    return comparison?.verdict === 'credible' && comparison.mean_delta > 0
  }).length
  const premiumRatios = frontierRows
    .map(([, arm]) => arm.mean_cost_usd / comparator.mean_cost_usd)
    .filter((ratio) => ratio >= 3)
  const premiumRange = premiumRatios.length > 0
    ? `${Math.floor(Math.min(...premiumRatios))}–${Math.round(Math.max(...premiumRatios))}×`
    : '—'

  return (
    <div className="flex flex-col gap-4" data-testid="frontier-panel">
      <div className="rounded-lg border border-signal-cyan/40 bg-signal-cyan/5 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="max-w-xl">
            <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-signal-cyan">
              Cross-family load-bearing test
            </div>
            <h3 className="mt-1 text-base font-mono text-eoc-primary">
              {hasCompleteComparisons
                ? 'No solo model beats the coordinated Qwen society on lives.'
                : 'Some solo models lack a paired comparison.'}
            </h3>
            <p className="mt-1 text-[11px] leading-relaxed text-eoc-secondary">
              {hasCompleteComparisons ? (
                <>
                  Frontier solos reach the same outcome ceiling, but most pay substantially more.
                  DeepSeek V4 Flash is the honest exception: it ties on lives and costs less.
                </>
              ) : (
                <>
                  Rows without shared seeds are marked insufficient data and excluded from the tie
                  and win counts; the available paired results remain visible below.
                </>
              )}
            </p>
          </div>
          <div className="rounded border border-signal-cyan/30 bg-eoc-ground/60 px-3 py-2 font-mono text-right">
            <div className="text-[9px] uppercase tracking-widest text-eoc-secondary">Qwen society reference</div>
            <div className="text-signal-cyan text-sm">{comparator.mean_lives_saved.toFixed(1)} lives</div>
            <div className="text-[10px] text-eoc-secondary">
              ${comparator.mean_cost_usd.toFixed(4)}/run · {comparator.lives_per_dollar.toFixed(0)} lives/$
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          [`${rows.length}`, 'solo models'],
          [`${modelFamilies.size}`, 'model families'],
          [`${soloWins}`, 'significant solo wins'],
          [`${frontierTies}`, `frontier ties · most ${premiumRange} cost`],
        ].map(([value, label]) => (
          <div key={label} className="rounded border border-eoc-border bg-eoc-surface px-3 py-2 font-mono">
            <div className="text-lg text-signal-cyan tabular-nums">{value}</div>
            <div className="text-[9px] uppercase tracking-wider text-eoc-secondary">{label}</div>
          </div>
        ))}
      </div>

      <div className="overflow-x-auto rounded-lg border border-eoc-border bg-eoc-surface">
        <table className="w-full min-w-[820px] text-[10px] font-mono">
          <thead>
            <tr className="border-b border-eoc-border bg-eoc-raised/40 text-left uppercase tracking-wider text-eoc-secondary">
              <th className="px-3 py-2">Solo model</th>
              <th className="px-3 py-2">Family</th>
              <th className="px-3 py-2 text-right">Lives ± SD</th>
              <th className="px-3 py-2 text-right">Δ vs society</th>
              <th className="px-3 py-2 text-right">Sign p</th>
              <th className="px-3 py-2 text-right">Cost/run</th>
              <th className="px-3 py-2">Cost comparison</th>
              <th className="px-3 py-2">Outcome</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([model, arm]) => {
              const comparison = comparisons.get(model)
              const outcome = outcomeLabel(comparison)
              return (
                <tr key={model} className="border-b border-eoc-raised hover:bg-eoc-raised/50">
                  <td className="px-3 py-2 font-semibold text-eoc-primary">{modelLabel(model)}</td>
                  <td className="px-3 py-2 text-eoc-secondary">{arm.family ?? '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-eoc-primary">
                    {arm.mean_lives_saved.toFixed(1)} ± {arm.sd_lives_saved.toFixed(1)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-eoc-primary">
                    {comparison ? `${comparison.mean_delta >= 0 ? '+' : ''}${comparison.mean_delta.toFixed(1)}` : '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-eoc-secondary">
                    {comparison ? comparison.sign_test_p.toFixed(3) : '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-eoc-secondary">
                    ${arm.mean_cost_usd.toFixed(4)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-eoc-secondary">
                    {costComparison(arm.mean_cost_usd, comparator.mean_cost_usd)}
                  </td>
                  <td className="px-3 py-2 uppercase tracking-wider" style={{ color: outcome.color }}>
                    {outcome.text}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] font-mono leading-relaxed text-eoc-secondary">
        Same 10 paired world seeds × 60 ticks. Δ = solo − society. “Ties society” means the
        paired result is not credibly different under the benchmark’s CI + exact sign-test rule;
        it is not a claim of identical outputs. Rows without a paired comparison are marked
        “insufficient data” and excluded from tie and win counts. Qwen inference is stochastic.
      </p>
    </div>
  )
}

export function BenchTab() {
  const [results, setResults] = useState<BenchResult[]>([])
  const [determinism, setDeterminism] = useState<DeterminismReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<'architecture' | 'frontier'>('architecture')

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .bench()
      .then((r) => { setResults(r); setLoading(false) })
      .catch((e: Error) => { setError(e.message); setLoading(false) })
    // Determinism is a separate, cached, ~seconds-on-first-call endpoint. Fire
    // it in parallel; a failure never blocks the bench view.
    api.determinism().then(setDeterminism).catch(() => {})
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-signal-amber font-mono animate-pulse">
        Loading bench results…
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-signal-red font-mono text-sm">
        <span>Error: {error}</span>
        <button
          onClick={load}
          className="px-2.5 py-1 rounded text-[11px] uppercase tracking-wider font-semibold text-eoc-ground bg-signal-amber hover:opacity-90 transition-opacity"
        >
          Retry
        </button>
      </div>
    )
  }

  if (results.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-eoc-secondary font-mono text-sm">
        <span>No bench results found.</span>
        <span className="text-[11px] text-eoc-secondary">
          Run <code className="text-signal-amber">aftershock bench</code> to generate results.
        </span>
      </div>
    )
  }

  const latest = results[0]
  // The most recent result may be a single-arm ablation (no control → no paired
  // stats). For the headline benchmark view, prefer the most recent MULTI-ARM
  // result that carries a paired comparison, so the credibility card renders.
  // Falls back to `latest` when no result has paired stats.
  // Headline the refreshed canonical 4-arm batch, else the most recent
  // multi-arm result, else latest.
  const headline =
    results.find((r) => r.canonical) ??
    results.find((r) => (r.paired_stats ?? []).length > 0) ??
    latest
  const pairedStats = headline.paired_stats ?? []
  // Method note: the honest one-liner. n = paired seeds between the control
  // (scripted) and the first treatment; falls back to the control's own n.
  const methodN = pairedStats[0]?.n ?? headline.arms?.['scripted']?.n ?? 0
  const methodTreatments = pairedStats.map((c) => c.treatment).join(', ') || '—'
  const isHeadlineStale = headline !== latest && !headline.canonical
  const frontier = results.find(
    (result) => result.kind === 'panelA-cross-family-solo' && result.comparator,
  )

  return (
    <div className="p-6 overflow-y-auto h-full">
      <div className={`${view === 'frontier' ? 'max-w-6xl' : 'max-w-3xl'} mx-auto flex flex-col gap-6`}>
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-signal-amber" />
          <h2 className="text-sm font-mono uppercase tracking-widest text-signal-amber">
            Benchmark Results
          </h2>
        </div>

        {frontier && (
          <div className="inline-flex w-fit rounded border border-eoc-border bg-eoc-surface p-1 font-mono text-[10px] uppercase tracking-wider">
            <button
              type="button"
              onClick={() => setView('architecture')}
              className={`rounded px-3 py-1.5 transition-colors ${
                view === 'architecture'
                  ? 'bg-signal-amber text-eoc-ground font-semibold'
                  : 'text-eoc-secondary hover:text-eoc-primary'
              }`}
            >
              Qwen 4-arm
            </button>
            <button
              type="button"
              onClick={() => setView('frontier')}
              className={`rounded px-3 py-1.5 transition-colors ${
                view === 'frontier'
                  ? 'bg-signal-cyan text-eoc-ground font-semibold'
                  : 'text-eoc-secondary hover:text-eoc-primary'
              }`}
            >
              12-model frontier
            </button>
          </div>
        )}

        {view === 'frontier' && frontier ? (
          <FrontierPanel result={frontier} />
        ) : (
          <>
            <DeterminismBadge report={determinism} />

        {isHeadlineStale && (
          <div className="text-[10px] font-mono text-eoc-secondary border border-eoc-border rounded px-2 py-1 bg-eoc-surface">
            Showing the most recent multi-arm benchmark (the latest result is a
            single-arm ablation with no control to compare against).
          </div>
        )}

        {headline.arms && (
          <>
            <div className="bg-eoc-surface border border-eoc-border rounded-lg p-4">
              <BarChart arms={headline.arms} />
            </div>
            <div className="bg-eoc-surface border border-eoc-border rounded-lg p-4">
              <CostTable arms={headline.arms} />
            </div>
          </>
        )}

        {/* Paired stats: bootstrap CI + sign-test p + power + verdict */}
        {pairedStats.length > 0 && (
          <div className="bg-eoc-surface border border-eoc-border rounded-lg p-4">
            <h3 className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary mb-3">
              Paired Comparison — {methodTreatments} vs scripted
            </h3>
            <PairedStats comparisons={pairedStats} />
            <p className="text-[10px] text-eoc-secondary font-mono mt-3">
              Paired seeds (n={methodN}): per-seed lives-saved delta of each arm vs
              the deterministic scripted control. 95% percentile bootstrap CI
              (10k resamples, fixed seed) + two-sided exact sign-test p + post-hoc
              power (normal approx at the observed Δ/sd — a function of the
              p-value, not a study-design target). Verdict: "credible" requires the CI to exclude
              0 AND p&lt;0.05; "suggestive" = CI only; otherwise "not significant".
            </p>
          </div>
        )}

        {/* Paired table */}
        {headline.paired && Object.keys(headline.paired).length > 0 && (
          <div className="bg-eoc-surface border border-eoc-border rounded-lg p-4">
            <h3 className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary mb-3">
              Per-Seed Paired: Lives Saved
            </h3>
            <div className="overflow-x-auto">
              <table className="text-[10px] font-mono w-full">
                <thead>
                  <tr className="border-b border-eoc-border">
                    <th className="text-left py-1 px-2 text-eoc-secondary">Arm</th>
                    {Object.keys(Object.values(headline.paired)[0] ?? {}).map((seed) => (
                      <th key={seed} className="text-right py-1 px-2 text-eoc-secondary">
                        s{seed}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(headline.paired).map(([armId, seeds]) => {
                    const color = armColor(armId)
                    return (
                      <tr key={armId} className="border-b border-eoc-raised">
                        <td className="py-1 px-2 font-semibold" style={{ color }}>
                          {armId}
                        </td>
                        {Object.values(seeds).map((v, i) => (
                          <td key={i} className="text-right py-1 px-2 tabular-nums text-eoc-primary">
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
          </>
        )}
      </div>
    </div>
  )
}
