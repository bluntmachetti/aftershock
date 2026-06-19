import { ARM_COLORS } from '../lib/palette'

/**
 * Voucher-pending status chip.
 *
 * When the Qwen (DashScope) key is absent on the server, solo/swarm/society
 * live + counterfactual requests 503. Instead of letting the operator hit a raw
 * error, this chip explains the state and steers toward the replayable recorded
 * society episodes (which need no key). Shown next to the arm selector (Live)
 * or the Branch controls (Compare) only when `arm` is an LLM arm and the key is
 * missing.
 *
 * Honesty: "replaying high-fidelity episodes" = the curated runs/episodes/
 * society records, NOT a live engine run. Scripted arms are keyless and never
 * trigger this chip.
 */
interface Props {
  /** The arm the operator is about to run/branch. */
  arm: string
  /** True when the server reports DASHSCOPE_API_KEY is configured. */
  llmKey: boolean
  /** Compact variant for inline placement (Compare controls). */
  compact?: boolean
}

const LLM_ARMS = new Set(['solo', 'swarm', 'society'])

export function VoucherChip({ arm, llmKey, compact = false }: Props) {
  if (llmKey || !LLM_ARMS.has(arm)) return null
  const accent = ARM_COLORS.society // cyan — the society arm this gates
  if (compact) {
    return (
      <span
        className="shrink-0 text-[10px] font-mono leading-tight"
        style={{ color: accent }}
        title="Qwen society live-engine offline (voucher pending) — replaying recorded episodes."
      >
        voucher pending
      </span>
    )
  }
  return (
    <div
      className="flex items-start gap-2 rounded-lg border px-2 py-1.5 text-[9px] font-mono leading-relaxed"
      style={{
        borderColor: `${accent}40`,
        backgroundColor: `${accent}10`,
        color: accent,
      }}
      role="status"
    >
      <span className="mt-0.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: accent }} />
      <span>
        <span className="font-semibold uppercase tracking-widest">Qwen society live-engine offline</span>
        {' — voucher pending. '}
        Replaying high-fidelity recorded episodes (no key needed). Scripted runs
        stay live; pick a society episode from the runs list to inspect real
        agent rationales.
      </span>
    </div>
  )
}
