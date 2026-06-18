import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { RunSummary, TickRecord, WorldState } from '../../types'
import { api } from '../../lib/api'
import { CompareTab } from '../CompareTab'

// Mock the API so loadSide resolves with a small completed run, and stub the heavy
// map / reality-band children (not under test here).
vi.mock('../../lib/api', () => ({
  api: {
    run: vi.fn(),
    ticks: vi.fn(),
    runDetail: vi.fn(),
    getScenario: vi.fn(),
    counterfactual: vi.fn(),
  },
}))
vi.mock('../TownMap', () => ({ TownMap: () => <div data-testid="townmap" /> }))
vi.mock('../RealityStrip', () => ({ RealityStrip: () => <div data-testid="reality" /> }))

const N = 12

function makeTicks(): TickRecord[] {
  return Array.from({ length: N }, (_, i) => ({
    tick: i,
    world_digest: `d${i}`,
    events: [],
    responses: [],
  })) as unknown as TickRecord[]
}

function makeWorlds(): WorldState[] {
  return Array.from({ length: N }, (_, i) => ({
    tick: i,
    lives_saved: 0,
    lives_lost: 0,
    panic: 0,
    missions: {},
  })) as unknown as WorldState[]
}

const leftRun: RunSummary = {
  run_id: 'seed42-society',
  seed: 42,
  arm: 'society',
  ticks: N,
  has_world: true,
}

const branchRun: RunSummary = {
  run_id: 'cf-abc12345-drop_protocol-at5',
  seed: 42,
  arm: 'scripted',
  ticks: N,
  has_world: true,
  counterfactual: {
    at_tick: 5,
    kind: 'drop_protocol',
    target: '',
    params: {},
    branch_of: 'seed42-society',
  },
}

beforeEach(() => {
  vi.mocked(api.run).mockResolvedValue({ has_world: true, ticks: N } as unknown as RunSummary)
  vi.mocked(api.ticks).mockResolvedValue({
    ticks: makeTicks(),
    worlds: makeWorlds(),
    total: N,
  } as unknown as Awaited<ReturnType<typeof api.ticks>>)
})

describe('CompareTab — counterfactual surfacing', () => {
  it('renders the DIVERGES marker and a WHAT-IF badge when the right run is a branch', async () => {
    render(
      <CompareTab
        runs={[leftRun, branchRun]}
        initialLeft="seed42-society"
        initialRight="cf-abc12345-drop_protocol-at5"
      />,
    )
    // The divergence marker is driven by rightRun.counterfactual.at_tick, surfaced
    // via the /api/runs list row — previously always null, so the marker was dead.
    expect(await screen.findByText('DIVERGES')).toBeInTheDocument()
    // The branch side is honestly labelled as a fabricated what-if, not a measurement.
    expect(await screen.findByText(/WHAT-IF/)).toBeInTheDocument()
  })
})
