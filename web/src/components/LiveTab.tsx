import { useState, useEffect, useRef, useCallback } from 'react'
import type { TickRecord, WorldState, LiveStatus, LiveWsMessage } from '../types'
import { api } from '../lib/api'
import { STATUS_COLORS, MISSION_KIND_COLORS, FALLBACK_COLOR, ARM_COLORS as ARM_PALETTE } from '../lib/palette'

const ARMS = ['scripted', 'solo', 'swarm', 'society']
const DISTRICTS = [
  'old_town',
  'harbor',
  'hospital_district',
  'market',
  'residential_north',
  'industrial',
]
const EVENT_KINDS = ['fire', 'aftershock', 'road_block']

// Arm colors from the canonical palette (raw hex only lives in palette.ts).
const ARM_COLORS: Record<string, string> = {
  scripted: FALLBACK_COLOR,
  solo: STATUS_COLORS.open,
  swarm: MISSION_KIND_COLORS.infra_repair,
  society: ARM_PALETTE.society,
}

interface Props {
  onTickReceived: (tick: TickRecord, world: WorldState | null) => void
}

export function LiveTab({ onTickReceived }: Props) {
  const [status, setStatus] = useState<LiveStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [arm, setArm] = useState('scripted')
  const [seed, setSeed] = useState(42)
  const [ticks, setTicks] = useState(60)
  const [startError, setStartError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [aarEnabled, setAarEnabled] = useState(false)
  const [memoryEnabled, setMemoryEnabled] = useState(false)
  // Track whether the *current* live run was started with memory on
  const [memoryActive, setMemoryActive] = useState(false)

  const [injectKind, setInjectKind] = useState('fire')
  const [injectDistrict, setInjectDistrict] = useState('market')
  const [injectError, setInjectError] = useState<string | null>(null)
  const [injectOk, setInjectOk] = useState(false)

  const [log, setLog] = useState<string[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const logRef = useRef<HTMLDivElement>(null)

  const appendLog = useCallback((msg: string) => {
    setLog((prev) => [...prev.slice(-99), msg])
  }, [])

  // Poll status on mount and after start
  useEffect(() => {
    let cancelled = false
    function poll() {
      api.liveStatus()
        .then((s) => { if (!cancelled) setStatus(s) })
        .catch((e: Error) => { if (!cancelled) setStatusError(e.message) })
    }
    poll()
    const id = setInterval(poll, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [log])

  // Latest callbacks via refs: message handlers must never appear in the WS
  // effect's dependencies — tick messages update parent state, which recreates
  // these callbacks, and a dependency on them tears down and reopens the
  // socket on every message (infinite reconnect loop, each replaying T0).
  const appendLogRef = useRef(appendLog)
  const onTickRef = useRef(onTickReceived)
  useEffect(() => {
    appendLogRef.current = appendLog
    onTickRef.current = onTickReceived
  })

  // WebSocket lifecycle — keyed ONLY on whether a run is active.
  const running = status?.running ?? false
  useEffect(() => {
    if (!running) {
      wsRef.current?.close()
      wsRef.current = null
      return
    }
    if (wsRef.current) return // already connected

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/live`)
    wsRef.current = ws

    ws.onopen = () => appendLogRef.current('[ws] connected')
    ws.onclose = () => {
      appendLogRef.current('[ws] disconnected')
      if (wsRef.current === ws) wsRef.current = null
    }
    ws.onerror = () => appendLogRef.current('[ws] error')
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as LiveWsMessage
        if (msg.type === 'tick' && msg.record) {
          appendLogRef.current(
            `T${msg.record.tick} — saved:${msg.record.scores['lives_saved'] ?? 0} ` +
            `panic:${((msg.record.scores['panic'] ?? 0) * 100).toFixed(0)}%`,
          )
          onTickRef.current(msg.record, msg.world ?? null)
        } else if (msg.type === 'done') {
          appendLogRef.current('[done] run finished')
        } else if (msg.type === 'aar') {
          if (msg.error) {
            appendLogRef.current(`[aar] failed: ${msg.error}`)
          } else if (msg.report) {
            appendLogRef.current(`[aar] ${msg.report.headline}`)
          } else {
            appendLogRef.current('[aar] generating…')
          }
        }
      } catch {
        appendLogRef.current('[ws] parse error')
      }
    }

    return () => {
      ws.close()
      if (wsRef.current === ws) wsRef.current = null
    }
  }, [running])

  // 401 means this browser never presented the server's OBSERVATORY_TOKEN —
  // explain the one-time ?token= step instead of echoing the raw response.
  function friendlyError(e: Error): string {
    if (e.message.includes('401')) {
      return (
        'Unauthorized: this browser has no access token. Open the observatory once ' +
        'via ?token=<OBSERVATORY_TOKEN> (the server operator has it) — it is stored ' +
        'locally and scrubbed from the URL, then Start/Inject work from this browser.'
      )
    }
    return e.message
  }

  async function handleStart() {
    setStartError(null)
    setStarting(true)
    setLog([])
    try {
      const opts = {
        ...(aarEnabled ? { aar: true } : {}),
        ...(memoryEnabled ? { memory: true } : {}),
      }
      await api.startLive(arm, seed, ticks, opts)
      setMemoryActive(memoryEnabled)
      appendLog(
        `[start] arm=${arm} seed=${seed} ticks=${ticks}` +
        (aarEnabled ? ' aar=on' : '') +
        (memoryEnabled ? ' memory=on' : ''),
      )
    } catch (e) {
      setStartError(friendlyError(e as Error))
    } finally {
      setStarting(false)
    }
  }

  async function handleInject() {
    setInjectError(null)
    setInjectOk(false)
    try {
      await api.injectEvent(injectKind, injectDistrict)
      setInjectOk(true)
      appendLog(`[inject] ${injectKind} → ${injectDistrict}`)
      setTimeout(() => setInjectOk(false), 2000)
    } catch (e) {
      setInjectError(friendlyError(e as Error))
    }
  }

  const isRunning = status?.running ?? false

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left panel: controls */}
      <div className="w-72 shrink-0 flex flex-col gap-4 p-4 border-r border-eoc-border overflow-y-auto bg-eoc-ground">
        {/* Status badge */}
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${isRunning ? 'bg-signal-green animate-pulse' : 'bg-eoc-border'}`}
          />
          <span className="text-[11px] font-mono text-eoc-secondary">
            {isRunning
              ? `RUNNING — ${status?.arm} / seed ${status?.seed} / T${status?.tick}`
              : 'IDLE'}
          </span>
          {/* MEMORY ON indicator — shown when current run was started with memory */}
          {isRunning && memoryActive && (
            <span
              data-testid="memory-on-indicator"
              className="px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-widest bg-signal-cyan/10 text-signal-cyan"
            >
              MEMORY ON
            </span>
          )}
        </div>
        {statusError && (
          <div className="text-[10px] font-mono text-signal-red">{statusError}</div>
        )}

        {/* Start controls */}
        <div className="flex flex-col gap-3 p-3 bg-eoc-surface border border-eoc-border rounded-lg">
          <h3 className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary">
            Start Run
          </h3>

          {/* Arm */}
          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-mono text-eoc-secondary">
              Arm
            </label>
            <div className="flex gap-1 flex-wrap">
              {ARMS.map((a) => {
                const color = ARM_COLORS[a] ?? FALLBACK_COLOR
                const sel = arm === a
                return (
                  <button
                    key={a}
                    onClick={() => setArm(a)}
                    disabled={isRunning || starting}
                    className={`px-2 py-0.5 rounded text-[11px] font-mono transition-all disabled:opacity-40 border ${
                      sel ? 'font-semibold' : 'border-eoc-border text-eoc-secondary'
                    }`}
                    style={
                      sel
                        ? { background: `${color}25`, borderColor: color, color }
                        : undefined
                    }
                  >
                    {a}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Seed */}
          <div className="flex items-center gap-2">
            <label className="text-[11px] font-mono text-eoc-secondary w-10">
              Seed
            </label>
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(parseInt(e.target.value, 10) || 0)}
              disabled={isRunning || starting}
              className="flex-1 bg-eoc-raised border border-eoc-border rounded px-2 py-1 text-[11px] font-mono text-eoc-primary disabled:opacity-40"
            />
          </div>

          {/* Ticks */}
          <div className="flex items-center gap-2">
            <label className="text-[11px] font-mono text-eoc-secondary w-10">
              Ticks
            </label>
            <input
              type="number"
              min={1}
              max={120}
              value={ticks}
              onChange={(e) => setTicks(Math.min(120, parseInt(e.target.value, 10) || 1))}
              disabled={isRunning || starting}
              className="flex-1 bg-eoc-raised border border-eoc-border rounded px-2 py-1 text-[11px] font-mono text-eoc-primary disabled:opacity-40"
            />
          </div>

          {/* AAR / Memory toggles */}
          <div className="flex gap-2">
            {[
              { id: 'aar', label: 'AAR', value: aarEnabled, set: setAarEnabled },
              { id: 'memory', label: 'MEMORY', value: memoryEnabled, set: setMemoryEnabled },
            ].map(({ id, label, value, set }) => (
              <button
                key={id}
                data-testid={`toggle-${id}`}
                onClick={() => set((v) => !v)}
                disabled={isRunning || starting}
                aria-pressed={value}
                className={`flex-1 py-0.5 rounded text-[10px] font-mono uppercase tracking-widest transition-all border disabled:opacity-40 disabled:cursor-not-allowed ${
                  value
                    ? 'bg-signal-cyan/10 border-signal-cyan text-signal-cyan'
                    : 'border-eoc-border text-eoc-secondary'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <button
            onClick={handleStart}
            disabled={isRunning || starting}
            className="w-full py-1.5 rounded text-[11px] font-mono uppercase tracking-wider transition-all
              bg-signal-amber/20 border border-signal-amber text-signal-amber
              hover:bg-signal-amber/30 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {starting ? 'Starting…' : isRunning ? 'Running…' : 'Start'}
          </button>

          {startError && (
            <div className="text-[10px] font-mono text-signal-red border border-signal-red/30 bg-signal-red/10 rounded px-2 py-1">
              {startError}
            </div>
          )}
        </div>

        {/* Inject event */}
        <div className="flex flex-col gap-3 p-3 bg-eoc-surface border border-eoc-border rounded-lg">
          <h3 className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary">
            Inject Event
          </h3>

          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-mono text-eoc-secondary">
              Kind
            </label>
            <div className="flex gap-1 flex-wrap">
              {EVENT_KINDS.map((k) => (
                <button
                  key={k}
                  onClick={() => setInjectKind(k)}
                  disabled={!isRunning}
                  className={`px-2 py-0.5 rounded text-[11px] font-mono transition-all disabled:opacity-40 ${
                    injectKind === k
                      ? 'bg-signal-red/20 border border-signal-red text-signal-red'
                      : 'border border-eoc-border text-eoc-secondary'
                  }`}
                >
                  {k}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-mono text-eoc-secondary">
              District
            </label>
            <select
              value={injectDistrict}
              onChange={(e) => setInjectDistrict(e.target.value)}
              disabled={!isRunning}
              className="bg-eoc-raised border border-eoc-border rounded px-2 py-1 text-[11px] font-mono text-eoc-primary disabled:opacity-40"
            >
              {DISTRICTS.map((d) => (
                <option key={d} value={d}>
                  {d.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={handleInject}
            disabled={!isRunning}
            className={`w-full py-1.5 rounded text-[11px] font-mono uppercase tracking-wider transition-all
              border disabled:opacity-40 disabled:cursor-not-allowed ${
              injectOk
                ? 'bg-signal-green/20 border-signal-green text-signal-green'
                : 'bg-signal-red/10 border-signal-red/60 text-signal-red hover:bg-signal-red/20'
            }`}
          >
            {injectOk ? 'Injected ✓' : 'Inject'}
          </button>

          {injectError && (
            <div className="text-[10px] font-mono text-signal-red">{injectError}</div>
          )}
        </div>
      </div>

      {/* Right: live log */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-3 py-2 border-b border-eoc-border bg-eoc-surface flex items-center justify-between">
          <span className="text-[10px] font-mono uppercase tracking-widest text-eoc-secondary">
            Live Feed
          </span>
          {log.length > 0 && (
            <button
              onClick={() => setLog([])}
              className="text-[10px] font-mono text-eoc-secondary hover:text-eoc-primary transition-colors"
            >
              clear
            </button>
          )}
        </div>
        <div
          ref={logRef}
          className="flex-1 overflow-y-auto p-3 font-mono text-[11px] leading-tight space-y-0.5"
        >
          {log.length === 0 && (
            <span className="text-eoc-secondary">Waiting for run…</span>
          )}
          {log.map((line, i) => (
            <div
              key={i}
              className={`${
                line.startsWith('[ws]')
                  ? 'text-eoc-secondary'
                  : line.startsWith('[inject]')
                    ? 'text-signal-cyan'
                    : line.startsWith('[done]')
                      ? 'text-signal-green'
                      : line.startsWith('[start]')
                        ? 'text-signal-amber'
                        : 'text-eoc-primary'
              }`}
            >
              {line}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
