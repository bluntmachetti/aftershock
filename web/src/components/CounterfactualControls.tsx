import { useState } from 'react'
import { api } from '../lib/api'
import { COUNTERFACTUAL_ACCENT } from '../lib/palette'
import { VoucherChip } from './VoucherChip'

interface Props {
  /** The left-side run (the baseline to branch from). */
  baselineRunId: string | null
  baselineArm: string | null
  baselineSeed: number | null
  baselineTicks: number | null
  /** The baseline's scenario id (when it was recorded from a real-data pack), so
   *  the branch rebuilds the SAME world. null/undefined for synthetic baselines. */
  baselineScenarioId?: string | null
  /** Whether a live/counterfactual run is already streaming. */
  running: boolean
  /** True when the server has DASHSCOPE_API_KEY configured. When false, a
   *  society/solo/swarm baseline branch 503s; the controls degrade gracefully. */
  llmKey?: boolean
  /** The server's LLM arm list (for the gate). Defaults to the known set. */
  llmArms?: string[]
  /** Called after the branch starts; receives the branch run_id so the caller can
   *  select it on the right side once it completes. */
  onBranchStarted?: (runId: string) => void
}

const INTERVENTIONS = [
  { value: 'drop_protocol', label: 'Drop protocol', desc: 'Auction → DefaultResolver at tick N' },
  { value: 'kill_agent', label: 'Kill agent', desc: 'Silence one role from tick N' },
  { value: 'inject_event', label: 'Inject event', desc: 'Fire / aftershock / road block at tick N' },
  { value: 'none', label: 'None (control)', desc: 'Byte-identical re-run for prefix proof' },
] as const

const EVENTS = ['fire', 'aftershock', 'road_block'] as const

const AGENTS = ['commander', 'comms', 'fire', 'infrastructure', 'medical', 'rescue'] as const

const DEFAULT_LLM_ARMS = ['solo', 'swarm', 'society']

export function CounterfactualControls({
  baselineRunId,
  baselineArm,
  baselineSeed,
  baselineTicks,
  baselineScenarioId,
  running,
  llmKey = true,
  llmArms,
  onBranchStarted,
}: Props) {
  const [kind, setKind] = useState<string>('drop_protocol')
  const [atTick, setAtTick] = useState<number>(5)
  const [target, setTarget] = useState<string>('')
  const [eventKind, setEventKind] = useState<string>('fire')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!baselineRunId || baselineArm === null || baselineSeed === null || baselineTicks === null) {
    return null
  }

  const llmArmsSet = llmArms ?? DEFAULT_LLM_ARMS
  // A society/solo/swarm baseline re-run needs the key; without it the server
  // 503s. Gate the Branch button and show the voucher chip rather than firing.
  const baselineNeedsKey = llmArmsSet.includes(baselineArm)
  const voucherBlocked = baselineNeedsKey && !llmKey

  const maxTick = Math.max(0, baselineTicks - 1)

  async function handleSubmit() {
    if (submitting || running || voucherBlocked) return
    setSubmitting(true)
    setError(null)
    try {
      const res = await api.counterfactual({
        arm: baselineArm!,
        seed: baselineSeed!,
        ticks: baselineTicks!,
        atTick,
        kind,
        target: kind === 'kill_agent' ? target : kind === 'inject_event' ? target : '',
        params: kind === 'inject_event' ? { event: eventKind } : {},
        baselineRunId: baselineRunId!,
        scenario: baselineScenarioId ?? null,
      })
      onBranchStarted?.(res.run_id)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(
        msg.includes('503')
          ? 'Qwen society live-engine offline (voucher pending) — replay a recorded society branch instead.'
          : msg,
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="flex items-center gap-3 border-t bg-eoc-surface px-3 py-1.5"
      style={{ borderColor: `${COUNTERFACTUAL_ACCENT}40` }}
    >
      <span
        className="shrink-0 text-[10px] font-semibold uppercase tracking-widest"
        style={{ color: COUNTERFACTUAL_ACCENT }}
      >
        What-if
      </span>

      <select
        value={kind}
        onChange={(e) => { setKind(e.target.value); setTarget('') }}
        className="shrink-0 rounded border border-eoc-border bg-eoc-raised px-1.5 py-0.5 text-[11px] text-eoc-primary"
      >
        {INTERVENTIONS.map((iv) => (
          <option key={iv.value} value={iv.value}>
            {iv.label}
          </option>
        ))}
      </select>

      {kind === 'kill_agent' && (
        <select
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          className="shrink-0 rounded border border-eoc-border bg-eoc-raised px-1.5 py-0.5 text-[11px] text-eoc-primary"
        >
          <option value="">agent…</option>
          {AGENTS.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
      )}

      {kind === 'inject_event' && (
        <>
          <select
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            className="shrink-0 rounded border border-eoc-border bg-eoc-raised px-1.5 py-0.5 text-[11px] text-eoc-primary"
          >
            <option value="">district…</option>
            <option value="old_town">Old Town</option>
            <option value="harbor">Harbor</option>
            <option value="hospital_district">Hospital</option>
            <option value="market">Market</option>
            <option value="residential_north">Res North</option>
            <option value="industrial">Industrial</option>
          </select>
          <select
            value={eventKind}
            onChange={(e) => setEventKind(e.target.value)}
            className="shrink-0 rounded border border-eoc-border bg-eoc-raised px-1.5 py-0.5 text-[11px] text-eoc-primary"
          >
            {EVENTS.map((ev) => (
              <option key={ev} value={ev}>{ev}</option>
            ))}
          </select>
        </>
      )}

      <label className="flex shrink-0 items-center gap-1 text-[11px] text-eoc-secondary">
        at
        <input
          type="number"
          min={0}
          max={maxTick}
          value={atTick}
          onChange={(e) => setAtTick(Math.max(0, Math.min(maxTick, parseInt(e.target.value, 10) || 0)))}
          className="w-12 rounded border border-eoc-border bg-eoc-raised px-1 py-0.5 text-center text-[11px] tabular-nums text-eoc-primary"
        />
      </label>

      <button
        onClick={handleSubmit}
        // A target is required ONLY for kinds that expose a selector (kill_agent /
        // inject_event). drop_protocol (the headline) and none take no target, so
        // they must stay submittable — gating them on `target` left the Branch
        // button permanently disabled for the default intervention. Also gated
        // when the baseline is an LLM arm and no key is configured (voucher pending).
        disabled={
          submitting ||
          running ||
          voucherBlocked ||
          ((kind === 'kill_agent' || kind === 'inject_event') && !target)
        }
        className="shrink-0 rounded px-2 py-0.5 text-[11px] font-semibold transition-colors disabled:opacity-40"
        style={{
          backgroundColor: `${COUNTERFACTUAL_ACCENT}20`,
          color: COUNTERFACTUAL_ACCENT,
          borderColor: `${COUNTERFACTUAL_ACCENT}60`,
          borderWidth: 1,
        }}
      >
        {submitting ? 'Running…' : 'Branch'}
      </button>

      <VoucherChip arm={baselineArm} llmKey={llmKey} compact />

      {error && (
        <span className="shrink-0 text-[10px] text-signal-red">{error}</span>
      )}
    </div>
  )
}
