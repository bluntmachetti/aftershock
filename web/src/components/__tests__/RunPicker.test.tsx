import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { RunPicker } from '../RunPicker'
import type { RunSummary } from '../../types'

function makeRun(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: 'seed91-society',
    seed: 91,
    arm: 'society',
    ticks: 65,
    final_scores: {},
    cost: {},
    has_world: true,
    scenario: null,
    ...overrides,
  } as RunSummary
}

describe('RunPicker empty / loading / error states', () => {
  it('shows "Loading runs…" while the list is still fetching (not "No runs found")', () => {
    render(
      <RunPicker
        runs={[]}
        selectedRunId={null}
        error={null}
        loading={false}
        runsLoading
        onSelect={vi.fn()}
        onLoadDemo={vi.fn()}
      />,
    )
    expect(screen.getByText(/loading runs/i)).toBeTruthy()
    expect(screen.queryByText(/no runs found/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /load demo/i })).toBeNull()
  })

  it('shows the empty state with a Load demo button once the (empty) list resolves', () => {
    const onLoadDemo = vi.fn()
    render(
      <RunPicker
        runs={[]}
        selectedRunId={null}
        error={null}
        loading={false}
        runsLoading={false}
        onSelect={vi.fn()}
        onLoadDemo={onLoadDemo}
      />,
    )
    expect(screen.getByText(/no runs found/i)).toBeTruthy()
    const btn = screen.getByRole('button', { name: /load demo/i })
    fireEvent.click(btn)
    expect(onLoadDemo).toHaveBeenCalledTimes(1)
  })

  it('shows an error with a Retry button that triggers onLoadDemo', () => {
    const onLoadDemo = vi.fn()
    render(
      <RunPicker
        runs={[]}
        selectedRunId={null}
        error="500 Internal Server Error"
        loading={false}
        runsLoading={false}
        onSelect={vi.fn()}
        onLoadDemo={onLoadDemo}
      />,
    )
    expect(screen.getByText(/error loading runs/i)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(onLoadDemo).toHaveBeenCalledTimes(1)
  })

  it('renders run rows and fires onSelect when a row is clicked', () => {
    const onSelect = vi.fn()
    const run = makeRun()
    render(
      <RunPicker
        runs={[run]}
        selectedRunId={null}
        error={null}
        loading={false}
        runsLoading={false}
        onSelect={onSelect}
        onLoadDemo={vi.fn()}
      />,
    )
    // The run id is rendered; clicking its row selects it.
    fireEvent.click(screen.getByText('seed91-society'))
    expect(onSelect).toHaveBeenCalledWith(run)
  })
})
