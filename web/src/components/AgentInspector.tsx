import type { TickRecord, AgentResponse, ConformanceReport, ConformanceViolation } from '../types'
import { MISSION_KIND_COLORS, STATUS_COLORS, FALLBACK_COLOR } from '../lib/palette'

// Per-agent colors drawn from the canonical palette (no raw hex). commander=amber,
// medical=cyan, rescue=amber (collapse_rescue hue), fire=red, infrastructure=violet,
// comms=green.
const AGENT_COLORS: Record<string, string> = {
  commander: STATUS_COLORS.open,
  medical: MISSION_KIND_COLORS.medical_surge,
  rescue: MISSION_KIND_COLORS.collapse_rescue,
  fire: MISSION_KIND_COLORS.fire,
  infrastructure: MISSION_KIND_COLORS.infra_repair,
  comms: STATUS_COLORS.resolved,
}

// Conformance pill: translucent badge tinted by the signal hue —
// green >= 95%, amber >= 80%, red below 80%.
function conformanceBadgeColor(rate: number): string {
  if (rate >= 0.95) return STATUS_COLORS.resolved
  if (rate >= 0.80) return STATUS_COLORS.open
  return STATUS_COLORS.failed
}

/** Compute per-agent conformance rate from the full report (all rules combined). */
function agentConformanceRate(
  agentId: string,
  conformance: ConformanceReport,
): number | null {
  // report.role_conformance is the pre-computed per-agent aggregate rate
  const rate = conformance.role_conformance[agentId]
  if (rate === undefined) return null
  return rate
}

/** Collect all violated rules for an agent (rule id, rate, first violation). */
interface ViolatedRule {
  ruleId: string
  rate: number
  firstViolation: ConformanceViolation | null
}

function agentViolatedRules(
  agentId: string,
  conformance: ConformanceReport,
): ViolatedRule[] {
  const result: ViolatedRule[] = []
  for (const [ruleId, agentMap] of Object.entries(conformance.rules)) {
    const entry = agentMap[agentId]
    if (!entry) continue
    // A rule is violated when rate < 1 and applicable > 0
    if (entry.applicable > 0 && entry.rate < 1.0) {
      result.push({
        ruleId,
        rate: entry.rate,
        firstViolation: entry.violations[0] ?? null,
      })
    }
  }
  // Sort by worst rate first
  result.sort((a, b) => a.rate - b.rate)
  return result
}

interface AgentChipProps {
  agentId: string
  selected: boolean
  hasError: boolean
  conformance: ConformanceReport | null
  onSelect: () => void
}

function AgentChip({ agentId, selected, hasError, conformance, onSelect }: AgentChipProps) {
  const color = AGENT_COLORS[agentId] ?? FALLBACK_COLOR

  const conformanceRate = conformance ? agentConformanceRate(agentId, conformance) : null
  const badgeColor = conformanceRate !== null ? conformanceBadgeColor(conformanceRate) : null

  return (
    <button
      onClick={onSelect}
      className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono uppercase tracking-wider transition-all border border-eoc-border"
      style={{
        background: selected ? `${color}30` : 'transparent',
        borderColor: selected ? color : undefined,
        boxShadow: selected ? `0 0 6px ${color}40` : undefined,
      }}
    >
      <span
        className={selected ? 'font-semibold' : 'text-eoc-secondary'}
        style={selected ? { color } : undefined}
      >
        {agentId}
      </span>
      {hasError && <span className="ml-1 text-signal-red">!</span>}
      {badgeColor !== null && conformanceRate !== null && (
        <span
          data-testid={`conformance-badge-${agentId}`}
          className="ml-1 inline-flex items-center justify-center rounded px-1 text-[10px] font-mono tabular-nums leading-none"
          style={{
            background: `${badgeColor}1a`,
            color: badgeColor,
          }}
          aria-label={`Conformance ${Math.round(conformanceRate * 100)}%`}
        >
          {Math.round(conformanceRate * 100)}%
        </span>
      )}
    </button>
  )
}

interface Props {
  tick: TickRecord | null
  selectedAgent: string | null
  conformance: ConformanceReport | null
  onSelectAgent: (id: string | null) => void
}

export function AgentInspector({ tick, selectedAgent, conformance, onSelectAgent }: Props) {
  if (!tick) {
    return (
      <div className="p-3 text-[11px] text-eoc-secondary font-mono">
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

  const violatedRules = selectedAgent && conformance
    ? agentViolatedRules(selectedAgent, conformance)
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
            conformance={conformance}
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
            <div className="text-[10px] font-mono text-signal-red bg-signal-red/10 rounded px-2 py-1 border border-signal-red/30">
              ERROR: {selectedResp.error}
            </div>
          )}

          {/* Decisions */}
          {selectedResp.decisions.length > 0 && (
            <div>
              <div className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary mb-1">
                Decisions ({selectedResp.decisions.length})
              </div>
              {selectedResp.decisions.map((d) => (
                <div key={d.decision_id} className="text-[10px] font-mono mb-1 pl-2 border-l border-eoc-border">
                  <span className="text-signal-amber font-semibold">{d.decision_type}</span>
                  <span className="text-eoc-secondary ml-1">
                    {JSON.stringify(d.params)}
                  </span>
                  {d.rationale && (
                    <div className="text-[10px] text-eoc-secondary italic">{d.rationale}</div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Proposals */}
          {selectedResp.proposals.length > 0 && (
            <div>
              <div className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary mb-1">
                Proposals ({selectedResp.proposals.length})
              </div>
              {selectedResp.proposals.map((p) => (
                <div key={p.proposal_id} className="text-[10px] font-mono mb-1 pl-2 border-l border-eoc-border">
                  <span className="text-signal-cyan font-semibold">{p.kind}</span>
                  <span className="text-eoc-secondary ml-1">{JSON.stringify(p.body)}</span>
                </div>
              ))}
            </div>
          )}

          {/* Rejections */}
          {agentRejections.length > 0 && (
            <div>
              <div className="text-[10px] font-mono uppercase tracking-widest text-signal-red mb-1">
                Rejections ({agentRejections.length})
              </div>
              {agentRejections.map((r) => (
                <div key={r.decision_id} className="text-[10px] font-mono mb-1 pl-2 border-l border-signal-red/40">
                  <span className="text-signal-red font-semibold">{r.decision_type}</span>
                  <span className="text-eoc-secondary ml-1">{r.reason}</span>
                </div>
              ))}
            </div>
          )}

          {/* Conformance violated rules */}
          {violatedRules.length > 0 && (
            <div>
              <div className="text-[10px] font-mono uppercase tracking-widest text-signal-amber mb-1">
                Doctrine Violations ({violatedRules.length})
              </div>
              {violatedRules.map((vr) => (
                <div
                  key={vr.ruleId}
                  data-testid={`violated-rule-${vr.ruleId}`}
                  className="text-[10px] font-mono mb-1 pl-2 border-l border-signal-amber/40"
                >
                  <div className="flex items-center gap-1.5">
                    <span className="text-signal-amber font-semibold">{vr.ruleId}</span>
                    <span className="text-signal-amber/80 tabular-nums">
                      {Math.round(vr.rate * 100)}%
                    </span>
                  </div>
                  {vr.firstViolation && (
                    <div className="text-[10px] text-eoc-secondary">
                      <span className="text-signal-amber/70">T{vr.firstViolation.tick}</span>
                      {' — '}
                      <span>{vr.firstViolation.detail}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Empty */}
          {!selectedResp.error &&
            selectedResp.decisions.length === 0 &&
            selectedResp.proposals.length === 0 &&
            agentRejections.length === 0 &&
            violatedRules.length === 0 && (
              <div className="text-[10px] text-eoc-secondary font-mono">No actions this tick.</div>
            )}
        </div>
      )}
    </div>
  )
}
