import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { LiveTab } from '../LiveTab'
import { api } from '../../lib/api'

// Mock the API module. hasToken defaults true so the operator controls render; the
// read-only test flips it to false.
vi.mock('../../lib/api', () => ({
  api: {
    liveStatus: vi.fn().mockResolvedValue({ running: false, live_id: null, tick: 0, arm: '', seed: 0, mode: null }),
    getScenarios: vi.fn().mockResolvedValue([]),
    startLive: vi.fn().mockResolvedValue({ live_id: 'test' }),
    stopLive: vi.fn().mockResolvedValue({ ok: true, running: false }),
    injectEvent: vi.fn().mockResolvedValue(undefined),
    hasToken: vi.fn().mockReturnValue(true),
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
  vi.mocked(api.hasToken).mockReturnValue(true)
  vi.mocked(api.liveStatus).mockResolvedValue({
    running: false, live_id: null, tick: 0, arm: '', seed: 0, mode: null,
  })
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

  it('hides operator controls in the read-only (no-token) view', () => {
    vi.mocked(api.hasToken).mockReturnValue(false)
    render(<LiveTab onTickReceived={vi.fn()} />)
    // The mutating controls are gone for the public/judge view…
    expect(screen.queryByText('Start Run')).not.toBeInTheDocument()
    expect(screen.queryByText('Inject Event')).not.toBeInTheDocument()
    expect(screen.queryByText('Demo Mode')).not.toBeInTheDocument()
    // …but the watchable panels remain.
    expect(screen.getByText('Negotiation Feed')).toBeInTheDocument()
  })

  it('reopens the WS when the live run identity changes (pre-emption / rollover)', async () => {
    vi.useFakeTimers()
    try {
      // First poll: an ambient run. Later polls: a different run id (an operator
      // pre-empted it, or one ambient run rolled into the next) with running still true.
      vi.mocked(api.liveStatus)
        .mockResolvedValueOnce({
          running: true, live_id: 'run-1', tick: 1, arm: 'scripted', seed: 42, mode: 'ambient',
        })
        .mockResolvedValue({
          running: true, live_id: 'run-2', tick: 0, arm: 'scripted', seed: 99, mode: 'manual',
        })
      render(<LiveTab onTickReceived={vi.fn()} />)
      await act(async () => { await vi.advanceTimersByTimeAsync(5) }) // poll → run-1
      expect(MockWebSocket.instances.length).toBe(1)
      await act(async () => { await vi.advanceTimersByTimeAsync(2000) }) // poll → run-2
      expect(MockWebSocket.instances.length).toBe(2)
    } finally {
      vi.useRealTimers()
    }
  })
})
