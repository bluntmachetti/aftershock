import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { NegotiationFeed } from '../NegotiationFeed'
import type { TickRecord, Proposal, ProposalRuling } from '../../types'

function makeProposal(overrides: Partial<Proposal> = {}): Proposal {
  return {
    proposal_id: 'test-p0',
    sender: 'medical',
    recipient: null,
    kind: 'resource_request',
    body: { mission_id: 'm1', resource: 'ambulance', qty: 1, urgency: 5 },
    ...overrides,
  }
}

function makeRuling(overrides: Partial<ProposalRuling> = {}): ProposalRuling {
  return {
    proposal_id: 'test-p0',
    accepted: true,
    decided_by: 'kernel:auction',
    reason: '',
    ...overrides,
  }
}

function makeTick(overrides: Partial<TickRecord> = {}): TickRecord {
  return {
    tick: 0,
    observation_digests: {},
    responses: [
      {
        agent_id: 'medical',
        decisions: [],
        proposals: [makeProposal()],
        responses: [],
        usage: null,
        error: '',
      },
    ],
    rulings: [makeRuling()],
    accepted: [],
    rejected: [],
    events: [],
    scores: { lives_saved: 0, lives_lost: 0, panic: 0, missions_open: 1, missions_resolved: 0, missions_failed: 0 },
    world_digest: '',
    ...overrides,
  }
}

describe('NegotiationFeed', () => {
  it('renders empty state when no ticks', () => {
    render(<NegotiationFeed ticks={[]} cursor={-1} />)
    expect(screen.getByText(/No rulings yet/)).toBeInTheDocument()
  })

  it('renders resource request rulings', () => {
    const tick = makeTick()
    render(<NegotiationFeed ticks={[tick]} cursor={0} />)
    expect(screen.getByText(/medical/)).toBeInTheDocument()
    expect(screen.getByText(/ambulance/)).toBeInTheDocument()
    expect(screen.getByText('GRANTED')).toBeInTheDocument()
  })

  it('renders declined rulings with reason', () => {
    const tick = makeTick({
      rulings: [makeRuling({ accepted: false, reason: 'pool exhausted: ambulance' })],
    })
    render(<NegotiationFeed ticks={[tick]} cursor={0} />)
    expect(screen.getByText('pool exhausted: ambulance')).toBeInTheDocument()
  })

  it('renders inject event markers', () => {
    const tick = makeTick({
      events: [
        {
          event_id: 'ev-0-0',
          tick: 0,
          kind: 'mission_spawned',
          payload: { injected: true, mission_kind: 'fire', district_id: 'market' },
        },
      ],
    })
    render(<NegotiationFeed ticks={[tick]} cursor={0} />)
    expect(screen.getByText(/INJECTED/)).toBeInTheDocument()
    expect(screen.getByText(/fire/)).toBeInTheDocument()
    expect(screen.getByText(/market/)).toBeInTheDocument()
  })

  it('renders optimistic inject marker before tick arrives', () => {
    const tick = makeTick()
    const marker = { kind: 'aftershock', district: 'old_town', tick: -1 }
    render(<NegotiationFeed ticks={[tick]} cursor={0} injectMarker={marker} />)
    expect(screen.getByText(/INJECTED/)).toBeInTheDocument()
    expect(screen.getByText(/aftershock/)).toBeInTheDocument()
  })

  it('shows a cumulative newest-first log up to the cursor', () => {
    const ticks = Array.from({ length: 10 }, (_, i) =>
      makeTick({
        tick: i,
        responses: [
          {
            agent_id: 'medical',
            decisions: [],
            proposals: [makeProposal({ proposal_id: `p-${i}` })],
            responses: [],
            usage: null,
            error: '',
          },
        ],
        rulings: [makeRuling({ proposal_id: `p-${i}` })],
      }),
    )
    render(<NegotiationFeed ticks={ticks} cursor={9} />)
    // Cumulative (not a 5-tick window): every tick 0..9 contributes a ruling.
    const entries = screen.getAllByText(/medical/)
    expect(entries.length).toBe(10)
    // Newest tick leads the log; the earliest tick (T0) — which the old sliding
    // window dropped at cursor 9 — is now present.
    const tickLabels = screen.getAllByText(/^T\d$/).map((el) => el.textContent)
    expect(tickLabels[0]).toBe('T9')
    expect(tickLabels).toContain('T0')
  })

  it('caps the cumulative log so a long run stays bounded', () => {
    const ticks = Array.from({ length: 120 }, (_, i) =>
      makeTick({
        tick: i,
        responses: [
          {
            agent_id: 'medical',
            decisions: [],
            proposals: [makeProposal({ proposal_id: `p-${i}` })],
            responses: [],
            usage: null,
            error: '',
          },
        ],
        rulings: [makeRuling({ proposal_id: `p-${i}` })],
      }),
    )
    render(<NegotiationFeed ticks={ticks} cursor={119} />)
    // One ruling per tick, 120 ticks, but the feed caps at 60 rows.
    expect(screen.getAllByText(/medical/).length).toBe(60)
  })
})
