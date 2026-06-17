import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AnalystTicker } from '../live/AnalystTicker'
import type { TickRecord, WorldState } from '../../types'
import type { ContentionResult } from '../../lib/contention'

const EMPTY_CONTENTION: ContentionResult = { contestedMissions: new Set(), pairs: [] }

function makeTick(overrides: Partial<TickRecord> = {}): TickRecord {
  return {
    tick: 1,
    observation_digests: {},
    responses: [],
    rulings: [],
    accepted: [],
    rejected: [],
    events: [],
    scores: {},
    world_digest: '',
    ...overrides,
  }
}

function makeWorld(overrides: Partial<WorldState> = {}): WorldState {
  return {
    tick: 1,
    seed: 42,
    panic: 0.3,
    lives_saved: 10,
    lives_lost: 2,
    next_mission_no: 0,
    districts: {},
    missions: {},
    pools: {},
    pending: [],
    ...overrides,
  }
}

describe('AnalystTicker', () => {
  it('renders nothing when tick is null', () => {
    const { container } = render(
      <AnalystTicker tick={null} world={null} contention={EMPTY_CONTENTION} inject={null} />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('renders narration text for a tick with scores', () => {
    render(
      <AnalystTicker
        tick={makeTick({ tick: 5, scores: { lives_saved: 12, panic: 0.4 } })}
        world={makeWorld({ lives_saved: 12, panic: 0.4 })}
        contention={EMPTY_CONTENTION}
        inject={null}
      />,
    )
    expect(screen.getByText(/T5/)).toBeTruthy()
    expect(screen.getByText(/12 saved/)).toBeTruthy()
  })

  it('renders alert for inject marker', () => {
    render(
      <AnalystTicker
        tick={makeTick()}
        world={null}
        contention={EMPTY_CONTENTION}
        inject={{ kind: 'fire', district: 'harbor', tick: -1 }}
      />,
    )
    expect(screen.getByText(/INJECTION/)).toBeTruthy()
    expect(screen.getByText(/fire/)).toBeTruthy()
  })

  it('has aria-live="polite" and aria-atomic="true"', () => {
    const { container } = render(
      <AnalystTicker
        tick={makeTick({ tick: 1, scores: { lives_saved: 0, panic: 0 } })}
        world={makeWorld()}
        contention={EMPTY_CONTENTION}
        inject={null}
      />,
    )
    const el = container.querySelector('[aria-live="polite"]')
    expect(el).toBeTruthy()
    expect(el).toHaveAttribute('aria-atomic', 'true')
  })
})
