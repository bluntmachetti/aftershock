import type { TickRecord, ProposalRuling, Proposal } from '../types'
import { MISSION_KIND_COLORS, STATUS_COLORS, FALLBACK_COLOR } from '../lib/palette'

const ROLE_COLORS: Record<string, string> = {
  commander: STATUS_COLORS.open,
  rescue: STATUS_COLORS.failed,
  medical: MISSION_KIND_COLORS.medical_surge,
  fire: MISSION_KIND_COLORS.fire,
  infrastructure: MISSION_KIND_COLORS.infra_repair,
  comms: STATUS_COLORS.resolved,
}

function roleColor(sender: string): string {
  return ROLE_COLORS[sender] ?? FALLBACK_COLOR
}

interface FeedEntry {
  tick: number
  ruling: ProposalRuling
  proposal?: Proposal
  tickRecord: TickRecord
  type: 'ruling'
}

interface InjectEntry {
  type: 'inject'
  tick: number
  kind: string
  district: string
}

type AnyEntry = FeedEntry | InjectEntry

interface InjectMarker {
  kind: string
  district: string
  tick: number
}

function buildFeed(
  ticks: TickRecord[],
  cursor: number,
  injectMarker: InjectMarker | null,
): AnyEntry[] {
  const entries: AnyEntry[] = []

  for (let i = Math.max(0, cursor - 4); i <= cursor; i++) {
    const tick = ticks[i]
    if (!tick) continue

    const proposals: Record<string, Proposal> = {}
    for (const resp of tick.responses) {
      for (const p of resp.proposals) {
        proposals[p.proposal_id] = p
      }
    }

    for (const evt of tick.events) {
      if (evt.payload?.injected === true) {
        const kind = (evt.payload.inject_kind as string)
          ?? (evt.kind === 'mission_spawned'
            ? (evt.payload.mission_kind as string ?? 'mission')
            : evt.kind === 'road_blocked' ? 'road_block' : evt.kind)
        entries.push({
          type: 'inject',
          tick: tick.tick,
          kind,
          district: (evt.payload.district_id as string) ?? '',
        })
      }
    }

    for (const ruling of [...tick.rulings].reverse()) {
      entries.push({
        type: 'ruling',
        tick: tick.tick,
        ruling,
        proposal: proposals[ruling.proposal_id],
        tickRecord: tick,
      })
    }
  }

  if (injectMarker && injectMarker.tick === -1) {
    entries.unshift({
      type: 'inject',
      tick: cursor >= 0 ? ticks[cursor]?.tick ?? 0 : 0,
      kind: injectMarker.kind,
      district: injectMarker.district,
    })
  }

  return entries.slice(0, 40)
}

interface Props {
  ticks: TickRecord[]
  cursor: number
  injectMarker?: InjectMarker | null
  /** Called when a ruling row is clicked (used to open the Decision Receipt).
   *  When absent, ruling rows are non-interactive (no affordance shown). */
  onSelectRuling?: (ruling: ProposalRuling, tick: TickRecord) => void
}

export function NegotiationFeed({ ticks, cursor, injectMarker = null, onSelectRuling }: Props) {
  const entries = buildFeed(ticks, cursor, injectMarker)

  return (
    <div className="flex flex-col gap-0 overflow-y-auto h-full">
      <h3 className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary px-2 py-1 sticky top-0 bg-eoc-surface border-b border-eoc-border">
        Negotiation Feed
      </h3>
      {entries.length === 0 && (
        <div className="px-2 py-3 text-[11px] text-eoc-secondary font-mono">No rulings yet.</div>
      )}
      {entries.map((e, i) => {
        if (e.type === 'inject') {
          return (
            <div
              key={`inject-${i}`}
              className="flex items-start gap-2 px-2 py-1.5 border-b border-eoc-raised text-[11px] leading-tight bg-signal-red/5"
            >
              <span className="font-mono text-[10px] text-eoc-secondary tabular-nums mt-0.5 w-5 shrink-0">
                T{e.tick}
              </span>
              <span className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 bg-signal-red shadow-[0_0_4px_rgba(239,68,68,0.5)]" />
              <div className="flex flex-col min-w-0">
                <span className="font-mono text-signal-red font-semibold">
                  INJECTED: {e.kind.replace(/_/g, ' ')}
                </span>
                <span className="text-[10px] text-eoc-secondary">
                  → {e.district.replace(/_/g, ' ')}
                </span>
              </div>
            </div>
          )
        }

        const accepted = e.ruling.accepted
        const p = e.proposal
        const sender = p?.sender ?? ''
        const senderColor = roleColor(sender)
        const statusColor = accepted ? STATUS_COLORS.resolved : STATUS_COLORS.failed
        const clickable = !!onSelectRuling

        return (
          <div
            key={i}
            className={`flex items-start gap-2 px-2 py-1 border-b border-eoc-raised text-[11px] leading-tight ${
              clickable ? 'cursor-pointer hover:bg-eoc-surface transition-colors' : ''
            }`}
            onClick={clickable ? () => onSelectRuling!(e.ruling, e.tickRecord) : undefined}
            role={clickable ? 'button' : undefined}
            tabIndex={clickable ? 0 : undefined}
            onKeyDown={
              clickable
                  ? (ev) => {
                    if (ev.key === 'Enter' || ev.key === ' ') {
                      ev.preventDefault()
                      onSelectRuling!(e.ruling, e.tickRecord)
                    }
                  }
                : undefined
            }
            aria-label={
              clickable ? `Open decision receipt for ${e.ruling.proposal_id}` : undefined
            }
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
