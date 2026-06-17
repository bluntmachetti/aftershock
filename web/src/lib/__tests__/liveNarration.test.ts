import { describe, it, expect } from 'vitest'
import { liveNarration } from '../liveNarration'
import type {
  TickRecord,
  WorldState,
  MissionState,
  Proposal,
  ProposalRuling,
  AgentResponse,
  WorldEvent,
} from '../../types'
import type { ContentionResult } from '../contention'

// ---- Tiny typed builders ----

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

function world(missions: MissionState[], panic = 0.4, lives_saved = 10): WorldState {
  const m: Record<string, MissionState> = {}
  for (const x of missions) m[x.id] = x
  return {
    tick: 1,
    seed: 42,
    panic,
    lives_saved,
    lives_lost: 2,
    next_mission_no: missions.length,
    districts: {},
    missions: m,
    pools: {},
    pending: [],
  }
}

function proposal(id: string, sender: string, resource: string, missionId: string, qty = 2): Proposal {
  return {
    proposal_id: id,
    sender,
    recipient: null,
    kind: 'resource_request',
    body: { resource, mission_id: missionId, qty, urgency: 8 },
  }
}

function ruling(proposalId: string, accepted: boolean, reason = ''): ProposalRuling {
  return { proposal_id: proposalId, accepted, decided_by: 'kernel:auction', reason }
}

function tick(
  props: Partial<TickRecord> & { tick: number } = { tick: 1 },
): TickRecord {
  return {
    observation_digests: {},
    responses: [],
    rulings: [],
    accepted: [],
    rejected: [],
    events: [],
    scores: {},
    world_digest: '',
    ...props,
  }
}

function agentResponse(agentId: string, proposals: Proposal[]): AgentResponse {
  return {
    agent_id: agentId,
    decisions: [],
    proposals,
    responses: [],
    usage: null,
    error: '',
  }
}

function injectedEvent(kind: string, district: string): WorldEvent {
  return {
    event_id: 'evt-1',
    tick: 1,
    kind: 'mission_spawned',
    payload: { injected: true, inject_kind: kind, district_id: district },
  }
}

const EMPTY_CONTENTION: ContentionResult = { contestedMissions: new Set(), pairs: [] }

describe('liveNarration', () => {
  it('returns empty narration for null tick', () => {
    const result = liveNarration({
      tick: null,
      world: null,
      contention: EMPTY_CONTENTION,
      inject: null,
    })
    expect(result.text).toBe('')
  })

  it('returns alert for pending inject marker', () => {
    const result = liveNarration({
      tick: tick({ tick: 5 }),
      world: null,
      contention: EMPTY_CONTENTION,
      inject: { kind: 'fire', district: 'harbor', tick: -1 },
    })
    expect(result.severity).toBe('alert')
    expect(result.text).toContain('INJECTION')
    expect(result.text).toContain('fire')
    expect(result.text).toContain('harbor')
  })

  it('returns alert for injected event in tick', () => {
    const result = liveNarration({
      tick: tick({
        tick: 3,
        events: [injectedEvent('aftershock', 'market')],
      }),
      world: null,
      contention: EMPTY_CONTENTION,
      inject: null,
    })
    expect(result.severity).toBe('alert')
    expect(result.text).toContain('INJECTION')
    expect(result.text).toContain('aftershock')
    expect(result.text).toContain('market')
  })

  it('returns warning for contention', () => {
    const w = world([mission('m1', 'harbor'), mission('m2', 'market')])
    const t = tick({
      tick: 14,
      responses: [
        agentResponse('rescue', [
          proposal('p1', 'rescue', 'rescue_crew', 'm1'),
          proposal('p2', 'rescue', 'rescue_crew', 'm2'),
        ]),
      ],
      rulings: [
        ruling('p1', true),
        ruling('p2', false, 'pool exhausted: rescue_crew granted to m1 (priority 7)'),
      ],
    })
    const contention: ContentionResult = {
      contestedMissions: new Set(['m1', 'm2']),
      pairs: [{ loserDistrict: 'market', winnerDistrict: 'harbor', resources: ['rescue_crew'] }],
    }
    const result = liveNarration({
      tick: t,
      world: w,
      contention,
      inject: null,
    })
    expect(result.severity).toBe('warning')
    expect(result.text).toContain('contested')
    expect(result.text).toContain('rescue_crew')
    expect(result.text).toContain('market')
    expect(result.text).toContain('rescue')
    expect(result.text).toContain('Panic 40%')
  })

  it('returns nominal for a granted ruling', () => {
    const t = tick({
      tick: 7,
      responses: [
        agentResponse('medical', [
          proposal('p1', 'medical', 'ambulance', 'm1', 3),
        ]),
      ],
      rulings: [ruling('p1', true)],
    })
    const result = liveNarration({
      tick: t,
      world: null,
      contention: EMPTY_CONTENTION,
      inject: null,
    })
    expect(result.severity).toBe('nominal')
    expect(result.text).toContain('T7')
    expect(result.text).toContain('medical')
    expect(result.text).toContain('3× ambulance')
    expect(result.text).toContain('GRANTED')
  })

  it('returns warning for a rejected ruling', () => {
    const t = tick({
      tick: 5,
      responses: [
        agentResponse('fire', [
          proposal('p1', 'fire', 'fire_engine', 'm2', 1),
        ]),
      ],
      rulings: [ruling('p1', false, 'pool exhausted')],
    })
    const result = liveNarration({
      tick: t,
      world: null,
      contention: EMPTY_CONTENTION,
      inject: null,
    })
    expect(result.severity).toBe('warning')
    expect(result.text).toContain('rejected')
  })

  it('returns nominal fallback when no notable ruling exists', () => {
    const w = world([], 0.6, 42)
    const t = tick({
      tick: 31,
      rulings: [],
      scores: { lives_saved: 42, panic: 0.6 },
    })
    const result = liveNarration({
      tick: t,
      world: w,
      contention: EMPTY_CONTENTION,
      inject: null,
    })
    expect(result.severity).toBe('nominal')
    expect(result.text).toContain('T31')
    expect(result.text).toContain('42 saved')
    expect(result.text).toContain('panic 60%')
  })

  it('never throws on partial/missing data', () => {
    const t = tick({ tick: 1, scores: {} })
    expect(() =>
      liveNarration({
        tick: t,
        world: null,
        contention: EMPTY_CONTENTION,
        inject: null,
      }),
    ).not.toThrow()

    expect(() =>
      liveNarration({
        tick: { ...t, responses: [{ agent_id: 'x', decisions: [], proposals: [], responses: [], usage: null, error: '' }] },
        world: null,
        contention: EMPTY_CONTENTION,
        inject: null,
      }),
    ).not.toThrow()
  })

  it('uses scores fallback when world is null', () => {
    const t = tick({
      tick: 10,
      scores: { lives_saved: 5, panic: 0.3 },
    })
    const result = liveNarration({
      tick: t,
      world: null,
      contention: EMPTY_CONTENTION,
      inject: null,
    })
    expect(result.text).toContain('5 saved')
    expect(result.text).toContain('panic 30%')
  })
})
