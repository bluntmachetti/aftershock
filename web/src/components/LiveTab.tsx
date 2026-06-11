import { useState, useEffect, useRef, useCallback } from 'react'
import type { TickRecord, WorldState, LiveStatus, LiveWsMessage } from '../types'
import { api } from '../lib/api'

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

const ARM_COLORS: Record<string, string> = {
  scripted: '#94a3b8',
  solo: '#f59e0b',
  swarm: '#22d3ee',
  society: '#4ade80',
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

  // WebSocket lifecycle
  useEffect(() => {
    if (!status?.running) {
      wsRef.current?.close()
      wsRef.current = null
      return
    }
    if (wsRef.current) return // already connected

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/live`)
    wsRef.current = ws

    ws.onopen = () => appendLog('[ws] connected')
    ws.onclose = () => { appendLog('[ws] disconnected'); wsRef.current = null }
    ws.onerror = () => appendLog('[ws] error')
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as LiveWsMessage
        if (msg.type === 'tick' && msg.record) {
          appendLog(
            `T${msg.record.tick} — saved:${msg.record.scores['lives_saved'] ?? 0} ` +
            `panic:${((msg.record.scores['panic'] ?? 0) * 100).toFixed(0)}%`,
          )
          onTickReceived(msg.record, msg.world ?? null)
        } else if (msg.type === 'done') {
          appendLog('[done] run finished')
        }
      } catch {
        appendLog('[ws] parse error')
      }
    }

    return () => { ws.close(); wsRef.current = null }
  }, [status?.running, appendLog, onTickReceived])

  async function handleStart() {
    setStartError(null)
    setStarting(true)
    setLog([])
    try {
      await api.startLive(arm, seed, ticks)
      appendLog(`[start] arm=${arm} seed=${seed} ticks=${ticks}`)
    } catch (e) {
      setStartError((e as Error).message)
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
      setInjectError((e as Error).message)
    }
  }

  const isRunning = status?.running ?? false

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left panel: controls */}
      <div className="w-72 shrink-0 flex flex-col gap-4 p-4 border-r border-[#243047] overflow-y-auto bg-[#0a0e1a]">
        {/* Status badge */}
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${isRunning ? 'bg-green-400 animate-pulse' : 'bg-slate-600'}`}
          />
          <span className="text-[11px] font-mono text-slate-400">
            {isRunning
              ? `RUNNING — ${status?.arm} / seed ${status?.seed} / T${status?.tick}`
              : 'IDLE'}
          </span>
        </div>
        {statusError && (
          <div className="text-[10px] font-mono text-red-400">{statusError}</div>
        )}

        {/* Start controls */}
        <div className="flex flex-col gap-3 p-3 bg-[#0f1624] border border-[#243047] rounded-lg">
          <h3 className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
            Start Run
          </h3>

          {/* Arm */}
          <div className="flex flex-col gap-1">
            <label className="text-[9px] font-mono uppercase tracking-widest text-slate-600">
              Arm
            </label>
            <div className="flex gap-1 flex-wrap">
              {ARMS.map((a) => {
                const color = ARM_COLORS[a] ?? '#94a3b8'
                const sel = arm === a
                return (
                  <button
                    key={a}
                    onClick={() => setArm(a)}
                    disabled={isRunning || starting}
                    className="px-2 py-0.5 rounded text-[10px] font-mono transition-all disabled:opacity-40"
                    style={{
                      background: sel ? `${color}25` : 'transparent',
                      border: `1px solid ${sel ? color : '#243047'}`,
                      color: sel ? color : '#475569',
                    }}
                  >
                    {a}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Seed */}
          <div className="flex items-center gap-2">
            <label className="text-[9px] font-mono uppercase tracking-widest text-slate-600 w-10">
              Seed
            </label>
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(parseInt(e.target.value, 10) || 0)}
              disabled={isRunning || starting}
              className="flex-1 bg-[#1a2235] border border-[#243047] rounded px-2 py-1 text-[11px] font-mono text-slate-200 disabled:opacity-40"
            />
          </div>

          {/* Ticks */}
          <div className="flex items-center gap-2">
            <label className="text-[9px] font-mono uppercase tracking-widest text-slate-600 w-10">
              Ticks
            </label>
            <input
              type="number"
              min={1}
              max={120}
              value={ticks}
              onChange={(e) => setTicks(Math.min(120, parseInt(e.target.value, 10) || 1))}
              disabled={isRunning || starting}
              className="flex-1 bg-[#1a2235] border border-[#243047] rounded px-2 py-1 text-[11px] font-mono text-slate-200 disabled:opacity-40"
            />
          </div>

          <button
            onClick={handleStart}
            disabled={isRunning || starting}
            className="w-full py-1.5 rounded text-[11px] font-mono uppercase tracking-wider transition-all
              bg-amber-500/20 border border-amber-500 text-amber-400
              hover:bg-amber-500/30 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {starting ? 'Starting…' : isRunning ? 'Running…' : 'Start'}
          </button>

          {startError && (
            <div className="text-[10px] font-mono text-red-400 border border-red-900 bg-red-950/20 rounded px-2 py-1">
              {startError}
            </div>
          )}
        </div>

        {/* Inject event */}
        <div className="flex flex-col gap-3 p-3 bg-[#0f1624] border border-[#243047] rounded-lg">
          <h3 className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
            Inject Event
          </h3>

          <div className="flex flex-col gap-1">
            <label className="text-[9px] font-mono uppercase tracking-widest text-slate-600">
              Kind
            </label>
            <div className="flex gap-1 flex-wrap">
              {EVENT_KINDS.map((k) => (
                <button
                  key={k}
                  onClick={() => setInjectKind(k)}
                  disabled={!isRunning}
                  className={`px-2 py-0.5 rounded text-[10px] font-mono transition-all disabled:opacity-40 ${
                    injectKind === k
                      ? 'bg-red-900/40 border border-red-500 text-red-400'
                      : 'border border-[#243047] text-slate-500'
                  }`}
                >
                  {k}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[9px] font-mono uppercase tracking-widest text-slate-600">
              District
            </label>
            <select
              value={injectDistrict}
              onChange={(e) => setInjectDistrict(e.target.value)}
              disabled={!isRunning}
              className="bg-[#1a2235] border border-[#243047] rounded px-2 py-1 text-[11px] font-mono text-slate-200 disabled:opacity-40"
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
                ? 'bg-green-900/30 border-green-500 text-green-400'
                : 'bg-red-900/20 border-red-700 text-red-400 hover:bg-red-900/30'
            }`}
          >
            {injectOk ? 'Injected ✓' : 'Inject'}
          </button>

          {injectError && (
            <div className="text-[10px] font-mono text-red-400">{injectError}</div>
          )}
        </div>
      </div>

      {/* Right: live log */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-3 py-2 border-b border-[#243047] bg-[#0f1624] flex items-center justify-between">
          <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
            Live Feed
          </span>
          {log.length > 0 && (
            <button
              onClick={() => setLog([])}
              className="text-[9px] font-mono text-slate-600 hover:text-slate-400 transition-colors"
            >
              clear
            </button>
          )}
        </div>
        <div
          ref={logRef}
          className="flex-1 overflow-y-auto p-3 font-mono text-[11px] space-y-0.5"
        >
          {log.length === 0 && (
            <span className="text-slate-600">Waiting for run…</span>
          )}
          {log.map((line, i) => (
            <div
              key={i}
              className={`${
                line.startsWith('[ws]')
                  ? 'text-slate-500'
                  : line.startsWith('[inject]')
                    ? 'text-cyan-400'
                    : line.startsWith('[done]')
                      ? 'text-green-400'
                      : line.startsWith('[start]')
                        ? 'text-amber-400'
                        : 'text-slate-300'
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
