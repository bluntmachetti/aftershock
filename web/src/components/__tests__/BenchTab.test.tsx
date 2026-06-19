import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { BenchTab } from '../BenchTab'
import { api } from '../../lib/api'
import type { BenchResult, DeterminismReport, PairedComparison } from '../../types'

vi.mock('../../lib/api', () => ({
  api: {
    bench: vi.fn(),
    determinism: vi.fn(),
  },
}))

const credibleCmp: PairedComparison = {
  control: 'scripted',
  treatment: 'society',
  n: 5,
  seeds: [42, 7, 13, 23, 57],
  mean_delta: 12.4,
  sd_delta: 4.1,
  n_positive: 5,
  n_negative: 0,
  n_tied: 0,
  sign_test_p: 0.031,
  verdict: 'credible',
  ci_excludes_zero: true,
  sign_significant: true,
  ci: { lower: 6.2, upper: 18.1, confidence: 0.95, n_resamples: 10000 },
  observed_power: 0.82,
}

const noiseCmp: PairedComparison = {
  ...credibleCmp,
  mean_delta: 1.2,
  sign_test_p: 0.625,
  verdict: 'noise',
  ci_excludes_zero: false,
  sign_significant: false,
  ci: { lower: -4.0, upper: 6.4, confidence: 0.95, n_resamples: 10000 },
  observed_power: 0.12,
}

const benchResult: BenchResult = {
  arms: {
    scripted: { n: 5, mean_lives_saved: 100.0, sd_lives_saved: 5.0, mean_cost_usd: 0, mean_missions_resolved: 4, mean_missions_failed: 0 },
    society: { n: 5, mean_lives_saved: 112.4, sd_lives_saved: 6.0, mean_cost_usd: 0.044, lives_per_dollar: 2554, mean_missions_resolved: 5, mean_missions_failed: 0 },
  },
  paired: {
    scripted: { 42: '100', 7: '95', 13: '102', 23: '98', 57: '105' } as unknown as Record<string, number>,
    society: { 42: '112', 7: '108', 13: '114', 23: '110', 57: '118' } as unknown as Record<string, number>,
  },
  paired_stats: [credibleCmp],
}

const determinismReport: DeterminismReport = {
  arm: 'scripted',
  seed: 42,
  ticks: 60,
  passed: true,
  n_digests: 60,
  scope: 'scripted engine only',
  note: 'Two seeded scripted runs produce identical world-digest sequences. DashScope ignores `seed`, so LLM/society arms are NOT reproducible.',
}

beforeEach(() => {
  vi.mocked(api.bench).mockReset()
  vi.mocked(api.determinism).mockReset()
  vi.mocked(api.bench).mockResolvedValue([benchResult])
  vi.mocked(api.determinism).mockResolvedValue(determinismReport)
})

describe('BenchTab — paired stats credibility', () => {
  it('renders CI, sign-test p, power, and a method note', async () => {
    render(<BenchTab />)
    await waitFor(() => expect(screen.getByText(/Paired Comparison/i)).toBeInTheDocument())
    // CI row
    expect(screen.getByText(/\[6\.2, 18\.1\]/)).toBeInTheDocument()
    // sign-test p
    expect(screen.getByText('0.031')).toBeInTheDocument()
    // observed power
    expect(screen.getByText('82%')).toBeInTheDocument()
    // method note
    expect(screen.getByText(/Paired seeds \(n=5\)/i)).toBeInTheDocument()
    expect(screen.getByText(/credible.*requires the CI to exclude 0 AND p<0\.05/i)).toBeInTheDocument()
  })

  it('shows a green check + "credible" only for a credible verdict', async () => {
    render(<BenchTab />)
    await waitFor(() => expect(screen.getByText(/Paired Comparison/i)).toBeInTheDocument())
    // The verdict badge carries the ✓ prefix; the method note does not.
    const badge = screen.getByText(/✓ credible/i)
    expect(badge).toBeInTheDocument()
  })

  it('labels a non-significant effect as "not significant" — no green check', async () => {
    vi.mocked(api.bench).mockResolvedValue([{ ...benchResult, paired_stats: [noiseCmp] }])
    render(<BenchTab />)
    await waitFor(() =>
      expect(screen.getAllByText(/not significant/i).length).toBeGreaterThan(0),
    )
    // The verdict badge for a noise effect never carries a green check.
    // (The determinism badge's ✓ is a separate, legitimate claim.)
    expect(screen.queryByText(/✓ credible/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/✓ not significant/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/✓ suggestive/i)).not.toBeInTheDocument()
  })

  it('renders the determinism badge scoped to the scripted engine', async () => {
    render(<BenchTab />)
    await waitFor(() =>
      expect(screen.getByText(/scripted engine — identical digests/i)).toBeInTheDocument(),
    )
    // The badge must NOT imply LLM/society arms are reproducible.
    expect(screen.getByText(/NOT reproducible/i)).toBeInTheDocument()
  })
})
