import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { RealityStrip } from '../RealityStrip'
import type { RealityStripArm } from '../RealityStrip'
import { ARM_COLORS } from '../../lib/palette'

// Aggregates mirror the committed nyc-ida-2021 pack `reference.aggregates`
// (mean_latency_s 948 -> 16 min, median 540 -> 9 min, held_rate 0.1648 -> 16%).
const NYC_AGGREGATES = {
  mean_latency_s: 948,
  median_latency_s: 540,
  held_rate: 0.1648,
  n_incidents: 2212,
}

// SF-style aggregates: a real mean latency but NO held_rate (null) — the held
// pair must be omitted entirely.
const SF_AGGREGATES = {
  mean_latency_s: 600, // 10 min
  median_latency_s: 480,
  held_rate: null,
}

const NYC_CAVEAT =
  'Demand: real · Latency baseline: real · Lives & outcomes: simulated model.'

function societyArm(over: Partial<RealityStripArm> = {}): RealityStripArm {
  return {
    arm: 'society',
    latencyMinutes: 24,
    heldRate: 0.08,
    color: ARM_COLORS.society,
    ...over,
  }
}

function baselineArm(over: Partial<RealityStripArm> = {}): RealityStripArm {
  return {
    arm: 'swarm',
    latencyMinutes: 36,
    heldRate: 0.2,
    color: ARM_COLORS.baseline,
    ...over,
  }
}

describe('RealityStrip — render', () => {
  it('renders the strip, both paired groups, provenance summary, caveat + sub-caption (single-arm / MapTab)', () => {
    render(
      <RealityStrip
        aggregates={NYC_AGGREGATES}
        caveatLine={NYC_CAVEAT}
        arms={[societyArm()]}
      />,
    )

    const strip = screen.getByTestId('reality-strip')
    expect(strip).toBeInTheDocument()

    // The grey REAL first-on-scene baseline (mean: 948s -> 16 min) and the
    // mean/median label that matches the field used.
    expect(within(strip).getByText(/first on scene · mean/i)).toBeInTheDocument()
    expect(within(strip).getByText('16 min')).toBeInTheDocument()
    // The agent (society) sim latency bar. The arm label appears once per
    // paired group (latency + held), so it is present in both groups.
    expect(within(strip).getByText('24 min')).toBeInTheDocument()
    expect(within(strip).getAllByText('SOCIETY')).toHaveLength(2)

    // Held pair present (NYC has a real held_rate): 16% real vs 8% society.
    expect(within(strip).getByText(/held \/ unserved/i)).toBeInTheDocument()
    expect(within(strip).getByText('16%')).toBeInTheDocument()
    expect(within(strip).getByText('8%')).toBeInTheDocument()

    // Always-visible inline provenance summary (delta 3).
    expect(within(strip).getByText('REAL demand')).toBeInTheDocument()
    expect(within(strip).getByText('REAL latency')).toBeInTheDocument()
    expect(within(strip).getByText('INFERRED lives')).toBeInTheDocument()

    // The non-dismissible per-pack caveat line + the short sub-caption (delta 4).
    expect(within(strip).getByText(NYC_CAVEAT)).toBeInTheDocument()
    expect(
      within(strip).getByText(/Same real demand; simulated dispatch & travel differ\./i),
    ).toBeInTheDocument()
  })

  it('falls back to the median field and labels it "median" when mean_latency_s is absent', () => {
    render(
      <RealityStrip
        aggregates={{ median_latency_s: 540 }}
        caveatLine={NYC_CAVEAT}
        arms={[societyArm({ latencyMinutes: null, heldRate: null })]}
      />,
    )
    const strip = screen.getByTestId('reality-strip')
    expect(within(strip).getByText(/first on scene · median/i)).toBeInTheDocument()
    // 540s -> 9 min real grey baseline.
    expect(within(strip).getByText('9 min')).toBeInTheDocument()
    // A null arm latency renders the em-dash placeholder, never a fabricated bar.
    expect(within(strip).getByText('—')).toBeInTheDocument()
  })
})

describe('RealityStrip — null held (SF pack)', () => {
  it('omits the held pair when the pack has no real held_rate', () => {
    render(
      <RealityStrip
        aggregates={SF_AGGREGATES}
        caveatLine={NYC_CAVEAT}
        arms={[societyArm({ heldRate: null })]}
      />,
    )
    const strip = screen.getByTestId('reality-strip')
    // The latency pair still renders (600s -> 10 min).
    expect(within(strip).getByText('10 min')).toBeInTheDocument()
    // ...but NO held / unserved group at all.
    expect(within(strip).queryByText(/held \/ unserved/i)).not.toBeInTheDocument()
  })
})

describe('RealityStrip — two-arm shared band (CompareTab)', () => {
  it('pairs BOTH arms against the SINGLE real baseline (one grey bar, two arm bars)', () => {
    render(
      <RealityStrip
        aggregates={NYC_AGGREGATES}
        caveatLine={NYC_CAVEAT}
        arms={[societyArm(), baselineArm()]}
      />,
    )
    const strip = screen.getByTestId('reality-strip')

    // Both arm latency readouts are present (society 24, swarm 36)...
    expect(within(strip).getByText('24 min')).toBeInTheDocument()
    expect(within(strip).getByText('36 min')).toBeInTheDocument()
    // ...and each arm labels both the latency and held groups (2 each).
    expect(within(strip).getAllByText('SOCIETY')).toHaveLength(2)
    expect(within(strip).getAllByText('SWARM')).toHaveLength(2)

    // ...against exactly ONE grey real baseline number (16 min appears once —
    // the single shared reality, never double-rendered per arm).
    expect(within(strip).getAllByText('16 min')).toHaveLength(1)

    // Held: one real (16%) + two arm rates (8%, 20%).
    expect(within(strip).getAllByText('16%')).toHaveLength(1)
    expect(within(strip).getByText('8%')).toBeInTheDocument()
    expect(within(strip).getByText('20%')).toBeInTheDocument()
  })
})

describe('RealityStrip — no real latency baseline', () => {
  it('renders nothing when aggregates carry no usable real latency (never a fabricated grey)', () => {
    const { container } = render(
      <RealityStrip
        aggregates={{ held_rate: 0.16 }}
        caveatLine={NYC_CAVEAT}
        arms={[societyArm()]}
      />,
    )
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByTestId('reality-strip')).not.toBeInTheDocument()
  })

  it('renders nothing for null/undefined aggregates (synthetic run path)', () => {
    const { container: c1 } = render(
      <RealityStrip aggregates={null} caveatLine={NYC_CAVEAT} arms={[societyArm()]} />,
    )
    expect(c1).toBeEmptyDOMElement()

    const { container: c2 } = render(
      <RealityStrip aggregates={undefined} caveatLine={NYC_CAVEAT} arms={[societyArm()]} />,
    )
    expect(c2).toBeEmptyDOMElement()
  })
})
