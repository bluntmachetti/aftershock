import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { CounterfactualControls } from '../CounterfactualControls'
import { api } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  api: { counterfactual: vi.fn() },
}))

const baseProps = {
  baselineRunId: 'seed42-society',
  baselineArm: 'society',
  baselineSeed: 42,
  baselineTicks: 60,
  running: false,
}

beforeEach(() => {
  vi.mocked(api.counterfactual).mockReset()
  vi.mocked(api.counterfactual).mockResolvedValue({ live_id: 'live-1', run_id: 'cf-live1-drop_protocol-at5' })
})

describe('CounterfactualControls — Branch enabled-state', () => {
  it('enables Branch for the default drop_protocol (the headline intervention)', () => {
    render(<CounterfactualControls {...baseProps} />)
    // Regression: the disabled gate used to require a target for every non-`none`
    // kind, leaving drop_protocol — which exposes no target selector — dead.
    expect(screen.getByRole('button', { name: 'Branch' })).toBeEnabled()
  })

  it('gates kill_agent on a target: disabled until an agent is chosen', () => {
    render(<CounterfactualControls {...baseProps} />)
    const kindSelect = screen.getAllByRole('combobox')[0]
    fireEvent.change(kindSelect, { target: { value: 'kill_agent' } })
    expect(screen.getByRole('button', { name: 'Branch' })).toBeDisabled()
    // The agent selector is the second combobox once kill_agent is chosen.
    const targetSelect = screen.getAllByRole('combobox')[1]
    fireEvent.change(targetSelect, { target: { value: 'commander' } })
    expect(screen.getByRole('button', { name: 'Branch' })).toBeEnabled()
  })
})

describe('CounterfactualControls — submit', () => {
  it('passes the baseline scenario id and reports the branch run_id to onBranchStarted', async () => {
    const onBranchStarted = vi.fn()
    render(
      <CounterfactualControls
        {...baseProps}
        baselineScenarioId="nyc-ida-2021"
        onBranchStarted={onBranchStarted}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Branch' }))
    await waitFor(() => expect(onBranchStarted).toHaveBeenCalledWith('cf-live1-drop_protocol-at5'))
    expect(api.counterfactual).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'drop_protocol', scenario: 'nyc-ida-2021' }),
    )
  })
})

describe('CounterfactualControls — voucher-pending graceful degradation', () => {
  it('disables Branch and shows the voucher chip when a society baseline has no key', () => {
    render(<CounterfactualControls {...baseProps} baselineArm="society" llmKey={false} />)
    expect(screen.getByRole('button', { name: 'Branch' })).toBeDisabled()
    // The compact voucher chip surfaces the offline state.
    expect(screen.getByText('voucher pending')).toBeInTheDocument()
    expect(api.counterfactual).not.toHaveBeenCalled()
  })

  it('keeps Branch enabled for a scripted baseline even without a key', () => {
    render(<CounterfactualControls {...baseProps} baselineArm="scripted" llmKey={false} />)
    expect(screen.getByRole('button', { name: 'Branch' })).toBeEnabled()
    expect(screen.queryByText('voucher pending')).not.toBeInTheDocument()
  })

  it('does not fire the request when voucher-blocked (button disabled)', () => {
    render(<CounterfactualControls {...baseProps} baselineArm="society" llmKey={false} />)
    fireEvent.click(screen.getByRole('button', { name: 'Branch' }))
    expect(api.counterfactual).not.toHaveBeenCalled()
  })
})
