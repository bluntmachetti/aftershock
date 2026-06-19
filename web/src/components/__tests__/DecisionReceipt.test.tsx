import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { MockInstance } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DecisionReceipt } from '../DecisionReceipt'
import type {
  TickRecord,
  Proposal,
  ProposalRuling,
  Decision,
  AgentResponse,
  WorldState,
  MissionState,
} from '../../types'

function makeProposal(overrides: Partial<Proposal> = {}): Proposal {
  return {
    proposal_id: 'medical-t1-p0',
    sender: 'medical',
    recipient: null,
    kind: 'resource_request',
    body: { mission_id: 'm1', resource: 'ambulance', qty: 2, urgency: 9 },
    ...overrides,
  }
}

function makeRuling(overrides: Partial<ProposalRuling> = {}): ProposalRuling {
  return {
    proposal_id: 'medical-t1-p0',
    accepted: true,
    decided_by: 'kernel:auction',
    reason: '',
    ...overrides,
  }
}

function makeGrant(overrides: Partial<Decision> = {}): Decision {
  return {
    decision_id: 'medical-t1-p0-grant',
    agent_id: 'medical',
    decision_type: 'dispatch',
    params: { mission_id: 'm1', resource: 'ambulance', qty: 2 },
    rationale: '',
    ...overrides,
  }
}

function makePriorityDecision(
  agentId: string,
  missionId: string,
  rationale: string,
): Decision {
  return {
    decision_id: `${agentId}-t1-prio-${missionId}`,
    agent_id: agentId,
    decision_type: 'set_priority',
    params: { mission_id: missionId, priority: 10 },
    rationale,
  }
}

function makeResponse(
  agentId: string,
  opts: { proposals?: Proposal[]; decisions?: Decision[] } = {},
): AgentResponse {
  return {
    agent_id: agentId,
    decisions: opts.decisions ?? [],
    proposals: opts.proposals ?? [],
    responses: [],
    usage: {
      prompt_tokens: 1000,
      completion_tokens: 200,
      cost_usd: 0.0012,
      model: 'qwen3.5-flash',
    },
    error: '',
  }
}

function makeTick(overrides: Partial<TickRecord> = {}): TickRecord {
  return {
    tick: 1,
    observation_digests: {},
    responses: [
      makeResponse('medical', { proposals: [makeProposal()] }),
      makeResponse('commander', {
        decisions: [
          makePriorityDecision(
            'commander',
            'm1',
            'Medical surge with shortest deadline (7). Max priority to save lives.',
          ),
        ],
      }),
    ],
    rulings: [makeRuling()],
    accepted: [makeGrant()],
    rejected: [],
    events: [],
    scores: { lives_saved: 3, lives_lost: 0, panic: 0, missions_open: 1, missions_resolved: 0, missions_failed: 0 },
    world_digest: '',
    ...overrides,
  }
}

function makeMission(overrides: Partial<MissionState> = {}): MissionState {
  return {
    id: 'm1',
    kind: 'medical_surge',
    district_id: 'market',
    severity: 3,
    lives_at_risk: 40,
    spawned_tick: 0,
    deadline_tick: 8,
    required: { ambulance: 2 },
    assigned: { ambulance: 2 },
    progress: 0.5,
    status: 'open',
    priority: 10,
    resolved_tick: null,
    spread_applied: false,
    ...overrides,
  }
}

function makeWorld(overrides: Partial<WorldState> = {}): WorldState {
  return {
    tick: 1,
    seed: 100,
    panic: 0,
    lives_saved: 3,
    lives_lost: 0,
    next_mission_no: 2,
    districts: {},
    missions: { m1: makeMission() },
    pools: {},
    pending: [],
    ...overrides,
  }
}

describe('DecisionReceipt', () => {
  let fetchSpy: MockInstance<[URL | RequestInfo, RequestInit?], Promise<Response>>

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'))
  })
  afterEach(() => {
    fetchSpy.mockRestore()
  })

  it('renders an auction-grant chain with kernel ruling + agent-stated rationale', () => {
    const tick = makeTick()
    render(<DecisionReceipt ruling={tick.rulings[0]} tick={tick} />)

    // Kernel ruling labeled distinctly ("decided by kernel") and GRANTED.
    // "decided by kernel" appears on both the ruling row and the grant row.
    expect(screen.getAllByText(/decided by kernel/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('GRANTED')).toBeInTheDocument()
    expect(screen.getByText('kernel:auction')).toBeInTheDocument()

    // Matched proposal (agent-stated request) with urgency.
    expect(screen.getByText('medical')).toBeInTheDocument()
    expect(screen.getByText(/2× ambulance/)).toBeInTheDocument()
    expect(screen.getByText(/urgency 9/)).toBeInTheDocument()

    // Agent-stated rationale (non-empty) for the same mission.
    expect(screen.getByText(/agent-stated · rationale/i)).toBeInTheDocument()
    expect(
      screen.getByText(/Max priority to save lives/),
    ).toBeInTheDocument()

    // Kernel-issued grant decision by the `proposal_id-grant` convention.
    expect(screen.getByText(/medical-t1-p0-grant/)).toBeInTheDocument()

    // Cost line present, honestly labeled tick-level.
    expect(screen.getByText(/tick-level/i)).toBeInTheDocument()
    expect(screen.getByText(/\$0\.002400/)).toBeInTheDocument()
  })

  it('makes NO request to /api/counterfactual (or any fetch) on render', () => {
    const tick = makeTick()
    render(<DecisionReceipt ruling={tick.rulings[0]} tick={tick} />)
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('maps proposal -> grant decision by the `-grant` id convention', () => {
    const tick = makeTick()
    render(<DecisionReceipt ruling={tick.rulings[0]} tick={tick} />)
    // The grant decision id is exactly `${proposal_id}-grant` (rendered with
    // its decision_type, so match by substring).
    expect(screen.getByText(/medical-t1-p0-grant/)).toBeInTheDocument()
    expect(screen.getByText(/dispatch/)).toBeInTheDocument()
  })

  it('renders a rejected ruling with reason only (no grant decision)', () => {
    const ruling = makeRuling({
      accepted: false,
      reason: 'pool exhausted: ambulance granted to m2 (priority 10)',
    })
    const tick = makeTick({ rulings: [ruling], accepted: [] })
    render(<DecisionReceipt ruling={ruling} tick={tick} />)

    expect(screen.getByText('DECLINED')).toBeInTheDocument()
    expect(screen.getByText(/pool exhausted: ambulance granted to m2/)).toBeInTheDocument()
    // No grant decision rendered for a rejected ruling.
    expect(screen.queryByText(/medical-t1-p0-grant/)).not.toBeInTheDocument()
  })

  it('shows the mission outcome (status / lives at risk / deadline) from world', () => {
    const tick = makeTick()
    const prev = makeTick({
      tick: 0,
      scores: { lives_saved: 0, lives_lost: 0, panic: 0, missions_open: 1, missions_resolved: 0, missions_failed: 0 },
    })
    render(
      <DecisionReceipt
        ruling={tick.rulings[0]}
        tick={tick}
        prevTick={prev}
        world={makeWorld()}
      />,
    )
    expect(screen.getByText(/40 lives at risk/)).toBeInTheDocument()
    expect(screen.getByText(/deadline T8/)).toBeInTheDocument()
    // The delta is honestly labeled town-wide (not attributable to this ruling),
    // so a per-ruling causal read is impossible — B-1 honesty fix.
    expect(screen.getByText(/town-wide this tick/i)).toBeInTheDocument()
    expect(screen.getByText(/\+3 saved/)).toBeInTheDocument()
  })

  it('hides the town-wide delta line when there was no change this tick', () => {
    const tick = makeTick()
    const prev = makeTick({
      tick: 0,
      scores: { lives_saved: 3, lives_lost: 0, panic: 0, missions_open: 1, missions_resolved: 0, missions_failed: 0 },
    })
    render(
      <DecisionReceipt
        ruling={tick.rulings[0]}
        tick={tick}
        prevTick={prev}
        world={makeWorld()}
      />,
    )
    expect(screen.queryByText(/town-wide this tick/i)).not.toBeInTheDocument()
  })

  it('renders a provenance badge when missionProvenance is provided', () => {
    const tick = makeTick()
    const { container } = render(
      <DecisionReceipt ruling={tick.rulings[0]} tick={tick} missionProvenance="real" />,
    )
    expect(screen.getByText('real')).toBeInTheDocument()
    // Badge is the only uppercase "real" text chip — ensure it is present once.
    expect(container.querySelectorAll('[title^="mission-kind provenance"]').length).toBe(1)
  })

  it('omits the rationale section when no agent set_priority rationale exists', () => {
    const tick = makeTick({
      responses: [
        makeResponse('medical', { proposals: [makeProposal()] }),
        makeResponse('commander', { decisions: [] }),
      ],
    })
    render(<DecisionReceipt ruling={tick.rulings[0]} tick={tick} />)
    expect(screen.queryByText(/agent-stated · rationale/i)).not.toBeInTheDocument()
  })

  it('labels a commander (non-kernel) ruling by its decider, not the kernel, and suppresses the auction grant row', () => {
    const ruling = makeRuling({
      proposal_id: 'fire-t1-p1',
      decided_by: 'commander',
      accepted: true,
    })
    const tick = makeTick({
      rulings: [ruling],
      accepted: [],
      responses: [
        makeResponse('fire', {
          proposals: [
            makeProposal({
              proposal_id: 'fire-t1-p1',
              sender: 'fire',
              body: { mission_id: 'm4', resource: 'engine', qty: 1, urgency: 8 },
            }),
          ],
        }),
      ],
    })
    render(<DecisionReceipt ruling={ruling} tick={tick} />)
    expect(screen.getByText(/decided by commander/i)).toBeInTheDocument()
    // An LLM arbiter must NOT be attributed to the kernel.
    expect(screen.queryByText(/decided by kernel/i)).not.toBeInTheDocument()
    // Non-auction ruling => no auction grant row fabricated.
    expect(screen.queryByText(/fire-t1-p1-grant/)).not.toBeInTheDocument()
  })

  it('shows a "dispatch rejected" row when the auction accepted but the kernel refused the grant', () => {
    const ruling = makeRuling({ accepted: true })
    const tick = makeTick({
      rulings: [ruling],
      accepted: [],
      rejected: [
        {
          decision_id: 'medical-t1-p0-grant',
          agent_id: 'medical',
          decision_type: 'dispatch',
          reason: "mission 'm1' is not open",
        },
      ],
    })
    render(<DecisionReceipt ruling={ruling} tick={tick} />)
    // The auction stage still reads GRANTED...
    expect(screen.getByText('GRANTED')).toBeInTheDocument()
    // ...but the dispatch-rejected row prevents implying the resource landed.
    expect(screen.getByText(/dispatch rejected/i)).toBeInTheDocument()
    expect(screen.getByText(/mission 'm1' is not open/)).toBeInTheDocument()
  })

  it('resolves the mission via grant params when no matching proposal exists', () => {
    const ruling = makeRuling({ accepted: true })
    const tick = makeTick({
      responses: [makeResponse('medical', { decisions: [] })],
      rulings: [ruling],
      accepted: [makeGrant()],
    })
    render(<DecisionReceipt ruling={ruling} tick={tick} world={makeWorld()} />)
    // missionId falls back to grant.params.mission_id (m1) since no proposal exists.
    expect(screen.getByText(/40 lives at risk/)).toBeInTheDocument()
    expect(screen.getByText(/deadline T8/)).toBeInTheDocument()
  })
})
