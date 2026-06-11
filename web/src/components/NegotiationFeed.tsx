import type { TickRecord, ProposalRuling, Proposal } from '../types'
import { MISSION_KIND_COLORS, STATUS_COLORS, FALLBACK_COLOR } from '../lib/palette'

// Role/agent color coding for senders in the feed. commander=amber,
// rescue=red, medical=cyan, fire=red, infrastructure=violet, comms=green.
// Drawn from the canonical palette so no raw hex lives here.
const ROLE_COLORS: Record<string, string> = {
  commander: STATUS_COLORS.open, // amber
  rescue: STATUS_COLORS.failed, // signal-red
  medical: MISSION_KIND_COLORS.medical_surge, // cyan
  fire: MISSION_KIND_COLORS.fire, // signal-red
  infrastructure: MISSION_KIND_COLORS.infra_repair, // violet
  comms: STATUS_COLORS.resolved, // green
}

function roleColor(sender: string): string {
  return ROLE_COLORS[sender] ?? FALLBACK_COLOR
}

interface FeedEntry {
  tick: number
  ruling: ProposalRuling
  proposal?: Proposal
}

function buildFeed(ticks: TickRecord[], cursor: number): FeedEntry[] {
  const entries: FeedEntry[] = []
  // Show rulings from current tick and a few recent
  const start = Math.max(0, cursor - 4)
  for (let i = cursor; i >= start; i--) {
    const tick = ticks[i]
    if (!tick) continue
    // Build proposal map for this tick
    const proposals: Record<string, Proposal> = {}
    for (const resp of tick.responses) {
      for (const p of resp.proposals) {
        proposals[p.proposal_id] = p
      }
    }
    for (const ruling of [...tick.rulings].reverse()) {
      entries.push({ tick: tick.tick, ruling, proposal: proposals[ruling.proposal_id] })
    }
  }
  return entries.slice(0, 30)
}

interface Props {
  ticks: TickRecord[]
  cursor: number
}

export function NegotiationFeed({ ticks, cursor }: Props) {
  const entries = buildFeed(ticks, cursor)

  return (
    <div className="flex flex-col gap-0 overflow-y-auto h-full">
      <h3 className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary px-2 py-1 sticky top-0 bg-eoc-surface border-b border-eoc-border">
        Negotiation Feed
      </h3>
      {entries.length === 0 && (
        <div className="px-2 py-3 text-[11px] text-eoc-secondary font-mono">No rulings yet.</div>
      )}
      {entries.map((e, i) => {
        const accepted = e.ruling.accepted
        const p = e.proposal
        const sender = p?.sender ?? ''
        const senderColor = roleColor(sender)
        const statusColor = accepted ? STATUS_COLORS.resolved : STATUS_COLORS.failed

        return (
          <div
            key={i}
            className="flex items-start gap-2 px-2 py-1 border-b border-eoc-raised text-[11px] leading-tight"
          >
            <span className="font-mono text-[10px] text-eoc-secondary tabular-nums mt-0.5 w-5 shrink-0">
              T{e.tick}
            </span>
            <span
              className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0"
              style={{
                background: statusColor,
                boxShadow: `0 0 4px ${statusColor}80`,
              }}
            />
            <div className="flex flex-col min-w-0">
              <span className="font-mono truncate text-eoc-primary">
                {p?.kind === 'resource_request'
                  ? (() => {
                      const body = p.body as { resource?: string; qty?: number; mission_id?: string }
                      return (
                        <>
                          <span style={{ color: senderColor }} className="font-semibold">
                            {sender}
                          </span>
                          {` → ${body.qty ?? '?'}× ${body.resource ?? '?'} for ${body.mission_id ?? '?'}`}
                        </>
                      )
                    })()
                  : p ? (
                      <>
                        <span style={{ color: senderColor }} className="font-semibold">
                          {sender}
                        </span>
                        {` [${p.kind}]`}
                      </>
                    ) : (
                      e.ruling.proposal_id
                    )}
              </span>
              {!accepted && e.ruling.reason && (
                <span className="text-[10px] text-eoc-secondary truncate">{e.ruling.reason}</span>
              )}
              {accepted && (
                <span
                  className="text-[10px] font-mono font-semibold"
                  style={{ color: STATUS_COLORS.resolved }}
                >
                  GRANTED
                </span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
