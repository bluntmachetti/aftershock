// Contention overlay — derived PURELY from the current tick's auction results
// (no history, no engine change). The resource auction lives in
// src/aftershock/town/society.py: resource_request proposals are grouped by
// resource; the winner ruling is { accepted: true, decided_by: 'kernel:auction',
// reason: '' }, losers are { accepted: false, reason: 'pool exhausted: <res>
// granted to <mN> (priority p)' }. We group auction rulings by resource and pair
// each losing district with the winning district. The proposal body carries no
// district (only { mission_id, qty, resource, urgency }), so the district is read
// from world.missions[mission_id].district_id.

import type { TickRecord, WorldState, Proposal } from '../types'

export interface ContestPair {
  loserDistrict: string
  winnerDistrict: string
  /** All resources contested along this loser→winner district axis this tick
   *  (sorted), so two resources on the same axis render as ONE link/badge
   *  ("AMB+RSC CONTESTED") rather than stacking. */
  resources: string[]
}

export interface ContentionResult {
  /** Mission ids touched by an active cross-mission auction this tick (losers and
   *  the winner they lost to) — both endpoints get the halo, matching the Sector
   *  prototype's `deriveContest`. */
  contestedMissions: Set<string>
  /** Cross-district contested links (loser district → winning district, per
   *  resource). Same-district pairs are dropped and duplicates deduped. */
  pairs: ContestPair[]
}

const EMPTY: ContentionResult = { contestedMissions: new Set(), pairs: [] }

function strField(body: Record<string, unknown> | undefined, key: string): string {
  const v = body?.[key]
  return typeof v === 'string' ? v : ''
}

/** Compute the per-tick contention overlay. Returns an empty result for a null
 *  tick/world or a tick with no winner-vs-loser auction contest to show. */
export function deriveContention(
  tick: TickRecord | null | undefined,
  world: WorldState | null | undefined,
): ContentionResult {
  if (!tick || !world) return EMPTY

  // proposal_id → proposal across every agent response (the same map the
  // NegotiationFeed builds), so a ruling can be resolved back to its request.
  const byId: Record<string, Proposal> = {}
  for (const resp of tick.responses) {
    for (const p of resp.proposals) byId[p.proposal_id] = p
  }

  // Group contested links by loser→winner district axis, collecting every
  // resource contested along it, so the same axis renders one combined badge
  // instead of stacking a badge per resource at the identical midpoint. Each
  // loser is linked to the SPECIFIC winner named in its auction reason — the
  // marginal grab the pool ran out on — not an assumed "top" winner, so a
  // partially-exhausted pool (m1 wins 2, m2 wins the last 1, m3 loses to m2)
  // points m3 at m2's district, never m1's.
  const contestedMissions = new Set<string>()
  const pairMap = new Map<string, ContestPair>()
  for (const ruling of tick.rulings) {
    if (ruling.decided_by !== 'kernel:auction' || ruling.accepted) continue
    const p = byId[ruling.proposal_id]
    if (!p || p.kind !== 'resource_request') continue
    const resource = strField(p.body, 'resource')
    const loserMid = strField(p.body, 'mission_id')
    if (!resource || !loserMid) continue
    // Parse the winner the loser actually lost to from the auction reason:
    //   "pool exhausted: <resource> granted to <winnerMid> (priority N)".
    // The "has N available, need M" variant has no named winner (the pool was
    // already empty), so there is nothing to link to — skip it.
    const m = /granted to (.+?) \(priority/.exec(ruling.reason)
    if (!m) continue
    const winnerMid = m[1]
    // Districts are authoritative from world state, not the proposal body.
    const loserDistrict = world.missions[loserMid]?.district_id ?? ''
    const winnerDistrict = world.missions[winnerMid]?.district_id ?? ''
    if (!loserDistrict || !winnerDistrict) continue // injected/unknown mission
    contestedMissions.add(loserMid)
    contestedMissions.add(winnerMid)
    if (loserDistrict === winnerDistrict) continue
    const key = `${loserDistrict}->${winnerDistrict}`
    let entry = pairMap.get(key)
    if (!entry) {
      entry = { loserDistrict, winnerDistrict, resources: [] }
      pairMap.set(key, entry)
    }
    if (!entry.resources.includes(resource)) entry.resources.push(resource)
  }

  // Stable resource order within each link (rulings arrive priority-sorted, not
  // resource-sorted) so the combined "AMB+RSC" badge is deterministic.
  for (const entry of pairMap.values()) entry.resources.sort()
  const pairs = [...pairMap.values()]
  if (contestedMissions.size === 0 && pairs.length === 0) return EMPTY
  return { contestedMissions, pairs }
}
