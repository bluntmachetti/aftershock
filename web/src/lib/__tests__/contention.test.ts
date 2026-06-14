import { describe, it, expect } from 'vitest'
import { deriveContention } from '../contention'
import type {
  TickRecord,
  WorldState,
  MissionState,
  Proposal,
  ProposalRuling,
  AgentResponse,
} from '../../types'

// ---- Tiny typed builders (readable + strict) ----

function mission(id: string, district: string): MissionState {
  return {
    id,
    kind: 'collapse_rescue',
    district_id: district,
    severity: 3,
    lives_at_risk: 5,
    spawned_tick: 0,
    deadline_tick: 10,
    required: { rescue_crew: 2 },
    assigned: {},
    progress: 0,
    status: 'open',
    priority: 5,
    resolved_tick: null,
    spread_applied: false,
  }
}

function world(missions: MissionState[]): WorldState {
  const m: Record<string, MissionState> = {}
  for (const x of missions) m[x.id] = x
  return {
    tick: 0,
    seed: 42,
    panic: 0,
    lives_saved: 0,
    lives_lost: 0,
    next_mission_no: missions.length,
    districts: {},
    missions: m,
    pools: {},
    pending: [],
  }
}

function proposal(id: string, sender: string, resource: string, missionId: string): Proposal {
  return {
    proposal_id: id,
    sender,
    recipient: null,
    kind: 'resource_request',
    body: { resource, mission_id: missionId, qty: 2, urgency: 8 },
  }
}

function ruling(proposalId: string, accepted: boolean, reason = ''): ProposalRuling {
  return { proposal_id: proposalId, accepted, decided_by: 'kernel:auction', reason }
}

function tick(proposals: Proposal[], rulings: ProposalRuling[]): TickRecord {
  const resp: AgentResponse = {
    agent_id: 'commander',
    decisions: [],
    proposals,
    responses: [],
    usage: null,
    error: '',
  }
  return {
    tick: 12,
    observation_digests: {},
    responses: [resp],
    rulings,
    accepted: [],
    rejected: [],
    events: [],
    scores: {},
    world_digest: '',
  }
}

const LOSE = 'pool exhausted: rescue_crew granted to m1 (priority 7)'

describe('deriveContention', () => {
  it('pairs a losing district with the winning district for a contested resource', () => {
    const w = world([mission('m1', 'harbor'), mission('m2', 'market')])
    const t = tick(
      [proposal('p1', 'rescue', 'rescue_crew', 'm1'), proposal('p2', 'rescue', 'rescue_crew', 'm2')],
      [ruling('p1', true), ruling('p2', false, LOSE)],
    )
    const r = deriveContention(t, w)
    expect(r.pairs).toEqual([
      { loserDistrict: 'market', winnerDistrict: 'harbor', resources: ['rescue_crew'] },
    ])
    // both endpoints get the halo
    expect([...r.contestedMissions].sort()).toEqual(['m1', 'm2'])
  })

  it('combines two resources contested along the same district axis into one pair', () => {
    // m4 (harbor) loses BOTH ambulance and fire_engine to winners in market.
    const w = world([
      mission('m1', 'market'),
      mission('m3', 'market'),
      mission('m4', 'harbor'),
    ])
    const t = tick(
      [
        proposal('p1', 'medical', 'ambulance', 'm1'),
        proposal('p2', 'fire', 'fire_engine', 'm3'),
        proposal('p3', 'medical', 'ambulance', 'm4'),
        proposal('p4', 'fire', 'fire_engine', 'm4'),
      ],
      [
        ruling('p1', true),
        ruling('p2', true),
        ruling('p3', false, 'pool exhausted: ambulance granted to m1 (priority 7)'),
        ruling('p4', false, 'pool exhausted: fire_engine granted to m3 (priority 7)'),
      ],
    )
    const r = deriveContention(t, w)
    // one link harbor→market, both resources collected (sorted)
    expect(r.pairs).toEqual([
      { loserDistrict: 'harbor', winnerDistrict: 'market', resources: ['ambulance', 'fire_engine'] },
    ])
    expect([...r.contestedMissions].sort()).toEqual(['m1', 'm3', 'm4'])
  })

  it('links a loser to the winner NAMED in its reason, not the first winner', () => {
    // Partial exhaustion: m1 (harbor) and m2 (market) both win ambulance; m3
    // (queens) loses the last unit to m2. The link must point queens→market
    // (the named winner), NOT queens→harbor (the first winner).
    const w = world([
      mission('m1', 'harbor'),
      mission('m2', 'market'),
      mission('m3', 'residential_north'),
    ])
    const t = tick(
      [
        proposal('p1', 'medical', 'ambulance', 'm1'),
        proposal('p2', 'medical', 'ambulance', 'm2'),
        proposal('p3', 'medical', 'ambulance', 'm3'),
      ],
      [
        ruling('p1', true),
        ruling('p2', true),
        ruling('p3', false, 'pool exhausted: ambulance granted to m2 (priority 6)'),
      ],
    )
    const r = deriveContention(t, w)
    expect(r.pairs).toEqual([
      { loserDistrict: 'residential_north', winnerDistrict: 'market', resources: ['ambulance'] },
    ])
    // only the loser and the winner it actually lost to are highlighted (not m1)
    expect([...r.contestedMissions].sort()).toEqual(['m2', 'm3'])
  })

  it('marks both missions contested but draws no link when they share a district', () => {
    const w = world([mission('m1', 'harbor'), mission('m2', 'harbor')])
    const t = tick(
      [proposal('p1', 'rescue', 'rescue_crew', 'm1'), proposal('p2', 'rescue', 'rescue_crew', 'm2')],
      [ruling('p1', true), ruling('p2', false, LOSE)],
    )
    const r = deriveContention(t, w)
    expect(r.pairs).toEqual([])
    expect([...r.contestedMissions].sort()).toEqual(['m1', 'm2'])
  })

  it('returns empty when a resource has a loser but no winner (fully exhausted pool)', () => {
    const w = world([mission('m2', 'market')])
    const t = tick(
      [proposal('p2', 'rescue', 'rescue_crew', 'm2')],
      [ruling('p2', false, 'pool exhausted: rescue_crew has 0 available, need 2')],
    )
    expect(deriveContention(t, w)).toEqual({ contestedMissions: new Set(), pairs: [] })
  })

  it('ignores a loser whose mission is not in world state (injected mission)', () => {
    const w = world([mission('m1', 'harbor')]) // m2 absent
    const t = tick(
      [proposal('p1', 'rescue', 'rescue_crew', 'm1'), proposal('p2', 'rescue', 'rescue_crew', 'm2')],
      [ruling('p1', true), ruling('p2', false, LOSE)],
    )
    const r = deriveContention(t, w)
    // m2 has no district → not contested, no pair; m1 alone isn't contested either
    expect(r.pairs).toEqual([])
    expect(r.contestedMissions.size).toBe(0)
  })

  it('ignores non-auction rulings and non-resource_request proposals', () => {
    const w = world([mission('m1', 'harbor'), mission('m2', 'market')])
    const t = tick(
      [proposal('p1', 'rescue', 'rescue_crew', 'm1'), proposal('p2', 'rescue', 'rescue_crew', 'm2')],
      [
        { proposal_id: 'p1', accepted: true, decided_by: 'kernel:default', reason: '' },
        { proposal_id: 'p2', accepted: false, decided_by: 'kernel:default', reason: LOSE },
      ],
    )
    expect(deriveContention(t, w)).toEqual({ contestedMissions: new Set(), pairs: [] })
  })

  it('returns empty for a null tick or a tick with no rulings', () => {
    expect(deriveContention(null, world([]))).toEqual({ contestedMissions: new Set(), pairs: [] })
    expect(deriveContention(tick([], []), world([]))).toEqual({
      contestedMissions: new Set(),
      pairs: [],
    })
  })
})
