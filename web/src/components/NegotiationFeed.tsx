import type { TickRecord, ProposalRuling, Proposal } from '../types'

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
      <h3 className="text-[10px] font-mono uppercase tracking-widest text-slate-500 px-2 py-1 sticky top-0 bg-[#0f1624] border-b border-[#243047]">
        Negotiation Feed
      </h3>
      {entries.length === 0 && (
        <div className="px-2 py-3 text-[11px] text-slate-600 font-mono">No rulings yet.</div>
      )}
      {entries.map((e, i) => {
        const accepted = e.ruling.accepted
        const p = e.proposal

        let summary = ''
        if (p?.kind === 'resource_request') {
          const body = p.body as { resource?: string; qty?: number; mission_id?: string }
          summary = `${p.sender} → ${body.qty ?? '?'}× ${body.resource ?? '?'} for ${body.mission_id ?? '?'}`
        } else if (p) {
          summary = `${p.sender} [${p.kind}]`
        } else {
          summary = e.ruling.proposal_id
        }

        return (
          <div
            key={i}
            className="flex items-start gap-2 px-2 py-1.5 border-b border-[#1a2235] text-[11px]"
          >
            <span className="font-mono text-[9px] text-slate-600 tabular-nums mt-0.5 w-5 shrink-0">
              T{e.tick}
            </span>
            <span
              className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0"
              style={{
                background: accepted ? '#4ade80' : '#ef4444',
                boxShadow: accepted ? '0 0 4px #4ade8080' : '0 0 4px #ef444480',
              }}
            />
            <div className="flex flex-col min-w-0">
              <span
                className="font-mono truncate"
                style={{ color: accepted ? '#4ade80' : '#ef4444' }}
              >
                {summary}
              </span>
              {!accepted && e.ruling.reason && (
                <span className="text-[10px] text-slate-500 truncate">{e.ruling.reason}</span>
              )}
              {accepted && (
                <span className="text-[10px] text-slate-500">GRANTED</span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
