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

interface Side {
  mid: string
  district: string
}

/** Compute the per-tick contention overlay. Returns an empty result for a null
 *  tick/world, a tick with no auction rulings, or a tick where no resource has
 *  both a winner and a loser (i.e. no genuine contention to show). */
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

  const winners: Record<string, Side[]> = {}
  const losers: Record<string, Side[]> = {}

  for (const ruling of tick.rulings) {
    if (ruling.decided_by !== 'kernel:auction') continue
    const p = byId[ruling.proposal_id]
    if (!p || p.kind !== 'resource_request') continue
    const resource = strField(p.body, 'resource')
    const mid = strField(p.body, 'mission_id')
    if (!resource || !mid) continue
    // District is authoritative from world state, not the proposal body.
    const district = world.missions[mid]?.district_id ?? ''
    if (!district) continue // injected/unknown mission with no world entry
    if (ruling.accepted) {
      ;(winners[resource] ||= []).push({ mid, district })
    } else if (ruling.reason.startsWith('pool exhausted')) {
      ;(losers[resource] ||= []).push({ mid, district })
    }
  }

  // Only a resource that has BOTH a winner and a loser is genuinely contended.
  // Group contested links by loser→winner district axis, collecting every
  // resource contested along it, so the same axis renders one combined badge
  // instead of stacking a badge per resource at the identical midpoint.
  const contestedMissions = new Set<string>()
  const pairMap = new Map<string, ContestPair>()
  for (const resource of Object.keys(losers).sort()) {
    const ws = winners[resource]
    if (!ws || ws.length === 0) continue
    // The auction emits winners priority-first, so ws[0] is the top winner.
    const winner = ws[0]
    for (const loser of losers[resource]) {
      contestedMissions.add(loser.mid)
      contestedMissions.add(winner.mid)
      if (loser.district === winner.district) continue
      const key = `${loser.district}->${winner.district}`
      let entry = pairMap.get(key)
      if (!entry) {
        entry = { loserDistrict: loser.district, winnerDistrict: winner.district, resources: [] }
        pairMap.set(key, entry)
      }
      if (!entry.resources.includes(resource)) entry.resources.push(resource)
    }
  }

  const pairs = [...pairMap.values()]
  if (contestedMissions.size === 0 && pairs.length === 0) return EMPTY
  return { contestedMissions, pairs }
}
