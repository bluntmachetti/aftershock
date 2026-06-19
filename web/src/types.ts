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

// ---- Scenario pack types (task #4 — real-data scenario packs) ----
//
// These mirror the Python shapes EXACTLY:
//   - the compact run-manifest block + /api/runs passthrough (web.py
//     `_scenario_manifest_block` / `_scenario_compact_from_manifest`),
//   - the /api/scenarios list rows (`_scenario_list_entry`),
//   - the full pack from /api/scenarios/{id} (`ScenarioPack.model_dump()` in
//     town/scenario.py).
// Behavior is unchanged when a run has no scenario: every consumer treats a
// null/absent `scenario` as the synthetic case.

/** Field-provenance marker for the two-tier badge system. `real` => solid fill;
 *  `mapped`/`inferred`/`synthetic` => ghost/dotted border. */
export type ProvenanceLabel = 'real' | 'mapped' | 'inferred' | 'synthetic'

/** The six field-provenance markers carried by every pack (drives the badge
 *  grid in ProvenancePanel). Mirrors `ScenarioFieldProvenance` in scenario.py. */
export interface ScenarioFieldProvenance {
  tick: ProvenanceLabel
  district_id: ProvenanceLabel
  mission_kind: ProvenanceLabel
  severity: ProvenanceLabel
  lives_at_risk: ProvenanceLabel
  blockage: ProvenanceLabel
}

/** One upstream dataset (verbatim attribution, license, query). Mirrors
 *  `ScenarioSource`; extra keys allowed there, but these are the stable ones. */
export interface ScenarioSource {
  dataset: string
  provider: string
  dataset_id?: string
  query_url?: string
  fetched_at?: string
  rows_fetched?: number
  license?: string
  license_url?: string
  attribution?: string
}

/** The real-vs-window observation window. Mirrors `ScenarioWindow`. */
export interface ScenarioWindow {
  start: string
  end: string
}

/** Published semantic decisions (verbatim, for provenance). Mirrors
 *  `ScenarioMapping` (pydantic extra="allow", so extra keys may appear). */
export interface ScenarioMapping {
  version: string
  mission_kind: Record<string, string>
  severity_rule?: string
  lives_rule?: string
}

/** How the real window was downscaled. Mirrors `ScenarioSampling`. */
export interface ScenarioSampling {
  method: string
  sample_seed: number
  kept: number
  total: number
  filter?: string
}

/** One district slot (canonical id + pack display name). Mirrors
 *  `ScenarioDistrict`. */
export interface ScenarioDistrict {
  id: string
  name: string
  members: string[]
}

/** One resource pool (size + observed/calibrated basis). Mirrors
 *  `ScenarioPool`. */
export interface ScenarioPool {
  size: number
  basis: string
  note: string
}

/** One timeline entry — exact TimelineEntry shape. Mirrors
 *  `ScenarioTimelineEntry`. */
export interface ScenarioTimelineEntry {
  tick: number
  kind: 'mission' | 'blockage'
  mission_kind: string
  district_id: string
  severity: number
  lives_at_risk: number
}

/** Per-mission real baseline, keyed by TIMELINE INDEX of the mission entry.
 *  `first_on_scene`/`latency_s` are null when no unit arrived. Mirrors
 *  `ScenarioReferenceMission`. */
export interface ScenarioReferenceMission {
  received: string | null
  first_on_scene: string | null
  latency_s: number | null
}

/** The reality baseline. `missions` keyed by string timeline index;
 *  `aggregates` computed over the full filtered window (mean/median latency,
 *  held-rate, named calm-window baseline). Mirrors `ScenarioReference`. */
export interface ScenarioReference {
  missions: Record<string, ScenarioReferenceMission>
  aggregates: Record<string, unknown>
}

/** The full scenario pack as returned by GET /api/scenarios/{id}
 *  (`ScenarioPack.model_dump()`). The RealityStrip + ProvenancePanel data
 *  source. */
export interface ScenarioPack {
  format_version: number
  id: string
  name: string
  hazard: string
  adapter: string
  compiler_version: string
  config_sha256: string
  tick_minutes: number
  window: ScenarioWindow
  districts: ScenarioDistrict[]
  pools: Record<string, ScenarioPool>
  timeline: ScenarioTimelineEntry[]
  field_provenance: ScenarioFieldProvenance
  mapping: ScenarioMapping
  sampling: ScenarioSampling
  source: ScenarioSource[]
  reference: ScenarioReference
  pack_digest: string
}

/** Compact list row from GET /api/scenarios (`_scenario_list_entry`). Used by
 *  the LiveTab scenario select. `source` is the trimmed 4-field view. */
export interface ScenarioSummary {
  id: string
  name: string
  hazard: string
  tick_minutes: number
  window: ScenarioWindow
  missions: number
  sampling: { kept: number; total: number }
  source: Array<{
    dataset: string
    provider: string
    license: string
    attribution: string
  }>
}

/** The run-manifest scenario block (`_scenario_manifest_block`) — enough for the
 *  UI to render provenance without a second fetch. Carried on a scenario run's
 *  `run.json` and surfaced by GET /api/runs/{id}. */
export interface ScenarioManifestBlock {
  id: string
  name: string
  hazard: string
  tick_minutes: number
  pack_digest: string
  config_sha256: string
  source: ScenarioSource[]
  field_provenance: ScenarioFieldProvenance
  caveat_line: string
  reference_aggregates: Record<string, unknown>
}

/** The compact passthrough on /api/runs list rows
 *  (`_scenario_compact_from_manifest`): just enough to badge a row. */
export interface ScenarioCompact {
  id: string
  name: string
  hazard: string
}

export interface RunSummary {
  run_id: string
  seed: number
  arm: string
  ticks: number
  final_scores?: Record<string, number>
  cost?: Record<string, unknown>
  has_world?: boolean
  // Compact {id, name, hazard} from the run manifest; null/absent for synthetic
  // runs (the UI treats absence as SYN·QUAKE).
  scenario?: ScenarioCompact | null
  // Counterfactual branch metadata; present only on branch runs.
  counterfactual?: {
    at_tick: number
    kind: string
    target: string
    params: Record<string, unknown>
    branch_of: string | null
  }
}

/** GET /api/runs/{id} detail. The full scenario manifest block (or null for a
 *  synthetic run) rides alongside the manifest. Mirrors `run_detail`. */
export interface RunDetail {
  run_id: string
  manifest: Record<string, unknown>
  final_scores: Record<string, number>
  n_ticks: number
  has_world: boolean
  scenario: ScenarioManifestBlock | null
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
  // Server-computed paired control-vs-treatment stats (Day 2). One entry per
  // non-control arm sharing seeds with the `scripted` control; absent/empty when
  // no common seeds. The BenchTab renders CI whiskers + sign-test p + power +
  // verdict from this so stats are never reimplemented in TS.
  paired_stats?: PairedComparison[]
  // Source batch dir (bench/results/<batch>/) + whether it's the canonical
  // published demo batch that BenchTab headlines (server-tagged).
  batch?: string
  canonical?: boolean
}

/** One paired control-vs-treatment comparison (server-computed). Mirrors the
 *  pure `bench.paired_comparisons()` adapter. `verdict` is the honest call:
 *  "credible" (CI excludes 0 AND sign test sig), "suggestive" (CI only), or
 *  "noise" (CI includes 0). */
export interface PairedComparison {
  control: string
  treatment: string
  n: number
  seeds: number[]
  mean_delta: number
  sd_delta: number
  n_positive: number
  n_negative: number
  n_tied: number
  sign_test_p: number
  verdict: 'noise' | 'suggestive' | 'credible'
  ci_excludes_zero: boolean
  sign_significant: boolean
  ci: { lower: number; upper: number; confidence: number; n_resamples: number }
  observed_power: number | null
}

/** GET /api/determinism — the scripted-engine verify check (re-run twice,
 *  identical world_digest sequences). Scoped to the scripted arm ONLY; DashScope
 *  ignores `seed` so LLM/society arms are NOT reproducible. */
export interface DeterminismReport {
  arm: string
  seed: number
  ticks: number
  passed: boolean
  n_digests: number
  scope: string
  note: string
}

export interface LiveStatus {
  running: boolean
  live_id: string | null
  tick: number
  arm: string
  seed: number
  // "ambient" = the server-driven looping demo run; "manual" = an operator run.
  mode?: 'ambient' | 'manual' | null
}

/** GET /api/status — voucher/key detection for graceful UI degradation.
 *  `llm_key` is true when the server has DASHSCOPE_API_KEY configured; when
 *  false, solo/swarm/society live + counterfactual requests 503 and the UI
 *  should show a "voucher pending" chip instead of a raw error. Scripted arms
 *  are keyless and never gated. The key itself is never leaked. */
export interface StatusInfo {
  llm_key: boolean
  demo_mode: boolean
  llm_arms: string[]
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

export type TabId = 'map' | 'bench' | 'live' | 'compare'

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
