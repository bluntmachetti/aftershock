import type { TickRecord, AgentResponse } from '../types'

const AGENT_COLORS: Record<string, string> = {
  commander: '#f59e0b',
  medical: '#22d3ee',
  rescue: '#fb923c',
  fire: '#ef4444',
  infrastructure: '#a78bfa',
  comms: '#4ade80',
}

interface AgentChipProps {
  agentId: string
  selected: boolean
  hasError: boolean
  onSelect: () => void
}

function AgentChip({ agentId, selected, hasError, onSelect }: AgentChipProps) {
  const color = AGENT_COLORS[agentId] ?? '#94a3b8'
  return (
    <button
      onClick={onSelect}
      className="px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider transition-all"
      style={{
        background: selected ? `${color}30` : 'transparent',
        border: `1px solid ${selected ? color : '#243047'}`,
        color: selected ? color : '#475569',
        boxShadow: selected ? `0 0 6px ${color}40` : undefined,
      }}
    >
      {agentId}
      {hasError && <span className="ml-1 text-red-400">!</span>}
    </button>
  )
}

interface Props {
  tick: TickRecord | null
  selectedAgent: string | null
  onSelectAgent: (id: string | null) => void
}

export function AgentInspector({ tick, selectedAgent, onSelectAgent }: Props) {
  if (!tick) {
    return (
      <div className="p-3 text-[11px] text-slate-600 font-mono">
        No tick loaded.
      </div>
    )
  }

  const agentMap: Record<string, AgentResponse> = {}
  for (const r of tick.responses) {
    agentMap[r.agent_id] = r
  }

  const selectedResp = selectedAgent ? agentMap[selectedAgent] : null
  const agentRejections = selectedAgent
    ? tick.rejected.filter((r) => r.agent_id === selectedAgent)
    : []

  return (
    <div className="flex flex-col gap-2 p-2">
      <div className="flex flex-wrap gap-1">
        {tick.responses.map((r) => (
          <AgentChip
            key={r.agent_id}
            agentId={r.agent_id}
            selected={selectedAgent === r.agent_id}
            hasError={!!r.error}
            onSelect={() =>
              onSelectAgent(selectedAgent === r.agent_id ? null : r.agent_id)
            }
          />
        ))}
      </div>

      {selectedResp && (
        <div className="flex flex-col gap-2 mt-1">
          {/* Error */}
          {selectedResp.error && (
            <div className="text-[10px] font-mono text-red-400 bg-red-950/30 rounded px-2 py-1 border border-red-900">
              ERROR: {selectedResp.error}
            </div>
          )}

          {/* Decisions */}
          {selectedResp.decisions.length > 0 && (
            <div>
              <div className="text-[9px] font-mono uppercase tracking-widest text-slate-500 mb-1">
                Decisions ({selectedResp.decisions.length})
              </div>
              {selectedResp.decisions.map((d) => (
                <div key={d.decision_id} className="text-[10px] font-mono mb-1 pl-2 border-l border-[#243047]">
                  <span className="text-amber-400">{d.decision_type}</span>
                  <span className="text-slate-400 ml-1">
                    {JSON.stringify(d.params)}
                  </span>
                  {d.rationale && (
                    <div className="text-[9px] text-slate-500 italic">{d.rationale}</div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Proposals */}
          {selectedResp.proposals.length > 0 && (
            <div>
              <div className="text-[9px] font-mono uppercase tracking-widest text-slate-500 mb-1">
                Proposals ({selectedResp.proposals.length})
              </div>
              {selectedResp.proposals.map((p) => (
                <div key={p.proposal_id} className="text-[10px] font-mono mb-1 pl-2 border-l border-[#243047]">
                  <span className="text-cyan-400">{p.kind}</span>
                  <span className="text-slate-400 ml-1">{JSON.stringify(p.body)}</span>
                </div>
              ))}
            </div>
          )}

          {/* Rejections */}
          {agentRejections.length > 0 && (
            <div>
              <div className="text-[9px] font-mono uppercase tracking-widest text-red-500 mb-1">
                Rejections ({agentRejections.length})
              </div>
              {agentRejections.map((r) => (
                <div key={r.decision_id} className="text-[10px] font-mono mb-1 pl-2 border-l border-red-900">
                  <span className="text-red-400">{r.decision_type}</span>
                  <span className="text-slate-500 ml-1">{r.reason}</span>
                </div>
              ))}
            </div>
          )}

          {/* Empty */}
          {!selectedResp.error &&
            selectedResp.decisions.length === 0 &&
            selectedResp.proposals.length === 0 &&
            agentRejections.length === 0 && (
              <div className="text-[10px] text-slate-600 font-mono">No actions this tick.</div>
            )}
        </div>
      )}
    </div>
  )
}
