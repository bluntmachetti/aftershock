// ---- World state types (matching TownState.to_dict()) ----

export interface DistrictState {
  id: string
  name: string
  road_blocked: boolean
}

export interface MissionState {
  id: string
  kind: 'collapse_rescue' | 'fire' | 'medical_surge' | 'infra_repair'
  district_id: string
  severity: number
  lives_at_risk: number
  spawned_tick: number
  deadline_tick: number
  required: Record<string, number>
  assigned: Record<string, number>
  progress: number
  status: 'open' | 'resolved' | 'failed'
  priority: number
  resolved_tick: number | null
  spread_applied: boolean
}

export interface ResourcePoolState {
  kind: string
  total: number
  available: number
}

export interface PendingArrivalState {
  due_tick: number
  mission_id: string
  resource: string
  qty: number
  district_id: string
}

export interface WorldState {
  tick: number
  seed: number
  panic: number
  lives_saved: number
  lives_lost: number
  next_mission_no: number
  districts: Record<string, DistrictState>
  missions: Record<string, MissionState>
  pools: Record<string, ResourcePoolState>
  pending: PendingArrivalState[]
}

// ---- Protocol types (matching TickRecord) ----

export interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
  model: string
}

export interface Decision {
  decision_id: string
  agent_id: string
  decision_type: string
  params: Record<string, unknown>
  rationale: string
}

export interface Proposal {
  proposal_id: string
  sender: string
  recipient: string | null
  kind: string
  body: Record<string, unknown>
}

export interface ProposalRuling {
  proposal_id: string
  accepted: boolean
  decided_by: string
  reason: string
}

export interface Rejection {
  decision_id: string
  agent_id: string
  decision_type: string
  reason: string
}

export interface AgentResponse {
  agent_id: string
  decisions: Decision[]
  proposals: Proposal[]
  responses: unknown[]
  usage: TokenUsage | null
  error: string
}

export interface WorldEvent {
  event_id: string
  tick: number
  kind: string
  payload: Record<string, unknown>
}

export interface TickRecord {
  tick: number
  observation_digests: Record<string, string>
  responses: AgentResponse[]
  rulings: ProposalRuling[]
  accepted: Decision[]
  rejected: Rejection[]
  events: WorldEvent[]
  scores: Record<string, number>
  world_digest: string
}

// ---- API response types ----

export interface RunSummary {
  run_id: string
  seed: number
  arm: string
  ticks: number
  final_scores?: Record<string, number>
  cost?: Record<string, unknown>
  has_world?: boolean
}

export interface TicksResponse {
  ticks: TickRecord[]
  worlds: WorldState[] | null
  total: number
}

export interface BenchArm {
  n: number
  mean_lives_saved: number
  sd_lives_saved: number
  mean_cost_usd: number
  lives_per_dollar?: number
  mean_missions_resolved?: number
  mean_missions_failed?: number
}

export interface BenchResult {
  arms: Record<string, BenchArm>
  paired?: Record<string, Record<string, number>>
}

export interface LiveStatus {
  running: boolean
  live_id: string | null
  tick: number
  arm: string
  seed: number
}

export interface AarKeyMoment {
  tick: number
  description: string
}

export interface AarReport {
  headline: string
  grade: 'A' | 'B' | 'C' | 'D' | 'F'
  what_worked: string[]
  coordination_failures: string[]
  key_moments: AarKeyMoment[]
  lessons: string[]
  doctrine_notes?: string[]
}

// ---- Conformance report types (matching conformance.json shape from DESIGN.md) ----

export interface ConformanceViolation {
  tick: number
  detail: string
}

export interface ConformanceAgentRule {
  applicable: number
  violations: ConformanceViolation[]
  rate: number
}

export interface ConformanceReport {
  arm: string
  seed: number
  rules: Record<string, Record<string, ConformanceAgentRule>>
  role_conformance: Record<string, number>
  team_alignment: number
  notes: string[]
}

export interface LiveWsMessage {
  type: 'tick' | 'done' | 'aar'
  record?: TickRecord
  world?: WorldState
  summary?: RunSummary
  report?: AarReport
  error?: string
}

// ---- UI state ----

export type TabId = 'map' | 'bench' | 'live'

export interface TimelineState {
  runId: string | null
  ticks: TickRecord[]
  worlds: WorldState[] | null
  total: number
  hasWorld: boolean
  cursor: number
  playing: boolean
  speed: number
  loading: boolean
  error: string | null
}
