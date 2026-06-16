import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { LiveTab } from '../LiveTab'
import { api } from '../../lib/api'

// Mock the API module
vi.mock('../../lib/api', () => ({
  api: {
    liveStatus: vi.fn().mockResolvedValue({ running: false, live_id: null, tick: 0, arm: '', seed: 0 }),
    getScenarios: vi.fn().mockResolvedValue([]),
    startLive: vi.fn().mockResolvedValue({ live_id: 'test' }),
    injectEvent: vi.fn().mockResolvedValue(undefined),
  },
}))

// Mock WebSocket
class MockWebSocket {
  static instances: MockWebSocket[] = []
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  close = vi.fn()
  constructor() {
    MockWebSocket.instances.push(this)
  }
}
// @ts-expect-error - assigning to global
globalThis.WebSocket = MockWebSocket

beforeEach(() => {
  MockWebSocket.instances = []
})

describe('LiveTab layout', () => {
  it('renders three-panel layout: controls, map area, feed', () => {
    render(<LiveTab onTickReceived={vi.fn()} />)

    // Left panel: Start controls
    expect(screen.getByText('Start Run')).toBeInTheDocument()
    expect(screen.getByText('Inject Event')).toBeInTheDocument()

    // Center: empty state with Demo button
    expect(screen.getByText('Start a run to see the map')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Run Demo/i })).toBeInTheDocument()

    // Right: Negotiation Feed
    expect(screen.getByText('Negotiation Feed')).toBeInTheDocument()
  })

  it('renders Demo Mode button', () => {
    render(<LiveTab onTickReceived={vi.fn()} />)
    expect(screen.getByText('Demo Mode')).toBeInTheDocument()
  })

  it('renders arm selection buttons', () => {
    render(<LiveTab onTickReceived={vi.fn()} />)
    expect(screen.getByText('scripted')).toBeInTheDocument()
    expect(screen.getByText('solo')).toBeInTheDocument()
    expect(screen.getByText('swarm')).toBeInTheDocument()
    expect(screen.getByText('society')).toBeInTheDocument()
  })

  it('renders inject event controls', () => {
    render(<LiveTab onTickReceived={vi.fn()} />)
    expect(screen.getByText('fire')).toBeInTheDocument()
    expect(screen.getByText('aftershock')).toBeInTheDocument()
    expect(screen.getByText('road_block')).toBeInTheDocument()
  })

  it('shows IDLE status when not running', () => {
    render(<LiveTab onTickReceived={vi.fn()} />)
    expect(screen.getByText(/IDLE/)).toBeInTheDocument()
  })

  it('auto-starts a scripted demo stream on mount', async () => {
    render(<LiveTab onTickReceived={vi.fn()} />)
    // Without any click, the tab kicks off a deterministic scripted run.
    await waitFor(() => {
      expect(api.startLive).toHaveBeenCalledWith('scripted', 42, 30)
    })
  })
})
