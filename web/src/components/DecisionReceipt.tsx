import type {
  TickRecord,
  ProposalRuling,
  Proposal,
  Decision,
  Rejection,
  WorldState,
  ProvenanceLabel,
} from '../types'
import { STATUS_COLORS, FALLBACK_COLOR, PROVENANCE_COLORS } from '../lib/palette'

// Decision Receipt — a consolidated "evidence chain" card for one contested
// auction-grant ruling. The chain is honest about provenance:
//   - kernel ruling + kernel-issued grant decision  -> "decided by kernel"
//   - the resource_request proposal (urgency) + any agent set_priority
//     rationale for the same mission                 -> "agent-stated"
//   - cost (tokens/$) is the per-tick total, never per-decision (honestly
//     labeled; a tick fans out many decisions so per-decision attribution
//     would be a lie)
//   - outcome reads recorded scores + mission state; NO counterfactual is
//     ever fired from this card (POST /api/counterfactual is a mutating
//     branch-starter and must not be called per-card)
//
// Proposal -> grant-decision linkage uses the kernel convention
// `decision_id = f"{proposal_id}-grant"` (town/society.py). Rejected rulings
// have no matched decision and render ruling + reason only.

const KERNEL_LABEL = 'decided by kernel'
const AGENT_LABEL = 'agent-stated'

interface Props {
  ruling: ProposalRuling
  tick: TickRecord
  /** Previous tick record, used only for the lives-saved delta line. Optional:
   *  when absent the delta line is omitted (no fabrication). */
  prevTick?: TickRecord | null
  /** Current world state, for mission status / deadline / lives-at-risk. */
  world?: WorldState | null
  /** Scenario mission-kind provenance label, for the provenance badge on a
   *  scenario run. null/absent on a synthetic run renders no badge. */
  missionProvenance?: ProvenanceLabel | null
  onClose?: () => void
}

/** Find the proposal that gave rise to this ruling by id. */
function findProposal(tick: TickRecord, proposalId: string): Proposal | undefined {
  for (const resp of tick.responses) {
    for (const p of resp.proposals) {
      if (p.proposal_id === proposalId) return p
    }
  }
  return undefined
}

/** Find the kernel-issued grant decision by the `proposal_id-grant` convention. */
function findGrantDecision(tick: TickRecord, proposalId: string): Decision | undefined {
  const grantId = `${proposalId}-grant`
  return tick.accepted.find((d) => d.decision_id === grantId)
}

/** Find a kernel REJECTION of the grant: the auction accepted the bid, but the
 *  dispatch was refused downstream (e.g. the mission is no longer open). Same
 *  `{proposal_id}-grant` id convention, but in tick.rejected. */
function findGrantRejection(tick: TickRecord, proposalId: string): Rejection | undefined {
  const grantId = `${proposalId}-grant`
  return tick.rejected.find((d) => d.decision_id === grantId)
}

/** Agent-stated rationales: any agent `set_priority` decision for the same
 *  mission. These carry the LLM's free-text reasoning (the grant decision
 *  itself has an empty rationale — resources flow through the auction), so
 *  this is how a society receipt shows non-empty agent-stated reasoning. */
function findAgentRationales(
  tick: TickRecord,
  missionId: string,
): Array<{ agentId: string; rationale: string }> {
  const out: Array<{ agentId: string; rationale: string }> = []
  for (const resp of tick.responses) {
    for (const d of resp.decisions) {
      if (d.decision_type !== 'set_priority') continue
      if ((d.params as { mission_id?: string }).mission_id !== missionId) continue
      const r = (d.rationale ?? '').trim()
      if (r) out.push({ agentId: resp.agent_id, rationale: r })
    }
  }
  return out
}

/** Per-tick cost totals (tokens + $). Labeled honestly as tick-level, not
 *  per-decision — a tick fans out many proposals/decisions so splitting cost
 *  per ruling would mislead. */
function tickCost(tick: TickRecord): {
  prompt: number
  completion: number
  costUsd: number
} {
  let prompt = 0
  let completion = 0
  let costUsd = 0
  for (const resp of tick.responses) {
    const u = resp.usage
    if (!u) continue
    prompt += u.prompt_tokens
    completion += u.completion_tokens
    costUsd += u.cost_usd
  }
  return { prompt, completion, costUsd }
}

function livesDelta(
  tick: TickRecord,
  prevTick?: TickRecord | null,
): { saved: number; lost: number } | null {
  if (!prevTick) return null
  const cur = tick.scores ?? {}
  const prev = prevTick.scores ?? {}
  return {
    saved: (cur.lives_saved ?? 0) - (prev.lives_saved ?? 0),
    lost: (cur.lives_lost ?? 0) - (prev.lives_lost ?? 0),
  }
}

function ProvenanceBadge({ label }: { label: ProvenanceLabel }) {
  const c = PROVENANCE_COLORS[label]
  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono uppercase tracking-wider"
      style={{
        border: `1px solid ${c.border}`,
        background: c.fill,
        color: c.text,
      }}
      title={`mission-kind provenance: ${label}`}
    >
      {label}
    </span>
  )
}

function Row({
  label,
  labelKind,
  children,
}: {
  label: string
  labelKind: 'kernel' | 'agent' | 'neutral'
  children: React.ReactNode
}) {
  const labelColor =
    labelKind === 'kernel'
      ? STATUS_COLORS.resolved
      : labelKind === 'agent'
        ? STATUS_COLORS.open
        : FALLBACK_COLOR
  return (
    <div className="flex flex-col gap-0.5 py-1 border-b border-eoc-raised last:border-b-0">
      <span
        className="text-[9px] font-mono uppercase tracking-widest"
        style={{ color: labelColor }}
      >
        {label}
      </span>
      <div className="text-[11px] leading-snug text-eoc-primary">{children}</div>
    </div>
  )
}

export function DecisionReceipt({
  ruling,
  tick,
  prevTick,
  world,
  missionProvenance,
  onClose,
}: Props) {
  const proposal = findProposal(tick, ruling.proposal_id)
  const isAuction = ruling.decided_by === 'kernel:auction'
  // A ruling is kernel-decided only when decided_by starts with "kernel:". The
  // commander (an LLM arbiter) also issues rulings — those must NOT be labeled
  // "decided by kernel" (honesty contract): attribute them to their decider.
  const isKernelRuling = ruling.decided_by.startsWith('kernel:')
  const rulingLabel = isKernelRuling ? KERNEL_LABEL : `decided by ${ruling.decided_by}`
  const rulingLabelKind: 'kernel' | 'agent' = isKernelRuling ? 'kernel' : 'agent'
  const grant = ruling.accepted && isAuction ? findGrantDecision(tick, ruling.proposal_id) : undefined
  // Auction accepted the bid but the kernel refused the dispatch downstream
  // (the grant id is in tick.rejected, not tick.accepted): surface it so a
  // GRANTED ruling is never shown without the failure that followed.
  const grantRejection =
    ruling.accepted && isAuction && !grant
      ? findGrantRejection(tick, ruling.proposal_id)
      : undefined
  const missionId =
    (proposal?.body as { mission_id?: string } | undefined)?.mission_id ??
    (grant?.params as { mission_id?: string } | undefined)?.mission_id ??
    null
  const agentRationale = missionId ? findAgentRationales(tick, missionId) : []
  const cost = tickCost(tick)
  const delta = livesDelta(tick, prevTick)
  const mission = missionId && world ? world.missions[missionId] ?? null : null

  const proposalBody = proposal?.body as
    | { resource?: string; qty?: number; urgency?: number }
    | undefined

  return (
    <div
      className="flex flex-col bg-eoc-surface border border-eoc-border rounded"
      data-testid="decision-receipt"
    >
      <div className="flex items-center justify-between px-2 py-1.5 border-b border-eoc-border bg-eoc-ground">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="w-1.5 h-1.5 rounded-full shrink-0"
            style={{
              background: ruling.accepted ? STATUS_COLORS.resolved : STATUS_COLORS.failed,
              boxShadow: `0 0 4px ${ruling.accepted ? STATUS_COLORS.resolved : STATUS_COLORS.failed}80`,
            }}
          />
          <span className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary truncate">
            Decision Receipt · T{tick.tick}
          </span>
          {missionProvenance && <ProvenanceBadge label={missionProvenance} />}
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="text-eoc-secondary hover:text-eoc-primary text-[11px] font-mono px-1"
            aria-label="Close receipt"
          >
            ✕
          </button>
        )}
      </div>

      <div className="px-2 py-1">
        {/* Ruling — kernel:auction/default/broadcast => "decided by kernel";
            a commander ruling is an LLM arbiter, labeled by its decider. */}
        <Row label={rulingLabel} labelKind={rulingLabelKind}>
          <div className="font-mono">
            <span className="text-eoc-primary">{ruling.decided_by}</span>{' '}
            <span style={{ color: ruling.accepted ? STATUS_COLORS.resolved : STATUS_COLORS.failed }}>
              {ruling.accepted ? 'GRANTED' : 'DECLINED'}
            </span>
          </div>
          <div className="text-[10px] text-eoc-secondary font-mono break-all">
            proposal: {ruling.proposal_id}
          </div>
        </Row>

        {/* Matched proposal — agent-stated request */}
        {proposal ? (
          <Row label={`${AGENT_LABEL} · request`} labelKind="agent">
            <div className="font-mono">
              <span className="text-eoc-primary font-semibold">{proposal.sender}</span>
              {proposal.kind === 'resource_request' && proposalBody ? (
                <span className="text-eoc-secondary">
                  {' → '}
                  {proposalBody.qty ?? '?'}× {proposalBody.resource ?? '?'}
                  {proposalBody.urgency != null && (
                    <span className="text-eoc-faint"> (urgency {proposalBody.urgency})</span>
                  )}
                </span>
              ) : (
                <span className="text-eoc-secondary"> [{proposal.kind}]</span>
              )}
            </div>
          </Row>
        ) : null}

        {/* Agent-stated rationale (set_priority for the same mission) */}
        {agentRationale.length > 0 && (
          <Row label={`${AGENT_LABEL} · rationale`} labelKind="agent">
            <ul className="flex flex-col gap-1">
              {agentRationale.map((r, i) => (
                <li key={i} className="text-[11px] leading-snug">
                  <span className="font-mono text-[9px] text-eoc-faint uppercase mr-1">
                    {r.agentId}
                  </span>
                  <span className="text-eoc-primary italic">“{r.rationale}”</span>
                </li>
              ))}
            </ul>
          </Row>
        )}

        {/* Matched grant decision — kernel-issued (rationale empty by design) */}
        {grant ? (
          <Row label={`${KERNEL_LABEL} · grant`} labelKind="kernel">
            <div className="font-mono text-[10px] text-eoc-secondary break-all">
              {grant.decision_id} · {grant.decision_type}
            </div>
            <div className="font-mono text-[10px] text-eoc-secondary">
              {String((grant.params as { resource?: unknown }).resource ?? '?')} ×{' '}
              {String((grant.params as { qty?: unknown }).qty ?? '?')} →{' '}
              {String((grant.params as { mission_id?: unknown }).mission_id ?? '?')}
            </div>
          </Row>
        ) : null}

        {/* Auction accepted the bid, but the kernel refused the dispatch
            downstream — show it so GRANTED is never shown alone. */}
        {grantRejection && (
          <Row label={`${KERNEL_LABEL} · dispatch rejected`} labelKind="neutral">
            <div className="font-mono text-[10px]" style={{ color: STATUS_COLORS.failed }}>
              {grantRejection.decision_id} · {grantRejection.reason}
            </div>
          </Row>
        )}

        {/* Rejected reason — ruling + reason only, no matched decision */}
        {!ruling.accepted && ruling.reason && (
          <Row label={`${rulingLabel} · reason`} labelKind={rulingLabelKind}>
            <span className="text-eoc-primary">{ruling.reason}</span>
          </Row>
        )}

        {/* Cost — tick-level, honestly labeled (not per-decision) */}
        <Row label="cost · tick-level (not per-decision)" labelKind="neutral">
          <div className="font-mono text-[10px] text-eoc-secondary">
            {cost.prompt.toLocaleString()} prompt + {cost.completion.toLocaleString()} completion ·{' '}
            <span className="text-eoc-primary">${cost.costUsd.toFixed(6)}</span>
          </div>
        </Row>

        {/* Outcome — recorded scores + mission state; no counterfactual */}
        <Row label="outcome · recorded" labelKind="neutral">
          {mission ? (
            <div className="font-mono text-[10px] text-eoc-secondary flex flex-col gap-0.5">
              <span>
                mission{' '}
                <span style={{ color: STATUS_COLORS[mission.status] }}>{mission.status}</span> ·{' '}
                {mission.lives_at_risk} lives at risk · deadline T{mission.deadline_tick}
              </span>
              {delta && (delta.saved !== 0 || delta.lost !== 0) && (
                <span className="text-eoc-faint">
                  town-wide this tick (not attributable to this ruling):{' '}
                  <span style={{ color: STATUS_COLORS.resolved }}>+{delta.saved} saved</span>
                  {delta.lost > 0 && (
                    <span style={{ color: STATUS_COLORS.failed }}>, {delta.lost} lost</span>
                  )}
                </span>
              )}
            </div>
          ) : (
            <div className="font-mono text-[10px] text-eoc-faint">
              no world state for this tick
            </div>
          )}
        </Row>
      </div>
    </div>
  )
}
