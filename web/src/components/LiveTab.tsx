import { useState, useEffect, useRef, useCallback } from 'react'
import type { TickRecord, WorldState, LiveStatus, LiveWsMessage, ScenarioSummary } from '../types'
import { api } from '../lib/api'
import { deriveContention } from '../lib/contention'
import { STATUS_COLORS, MISSION_KIND_COLORS, FALLBACK_COLOR, ARM_COLORS as ARM_PALETTE } from '../lib/palette'
import { MissionControlMap } from './MissionControlMap'
import { Scoreboard } from './Scoreboard'
import { PanicGauge } from './PanicGauge'
import { NegotiationFeed } from './NegotiationFeed'
import { ResourcePoolSidebar } from './ResourcePoolSidebar'

const SYNTHETIC_DEFAULT_TICKS = 60
const SCENARIO_TICK_PADDING = 20
const SCENARIO_MAX_TICKS = 120
const SYNTHETIC_SCENARIO = ''

function scenarioOptionLabel(s: ScenarioSummary): string {
  const handle = s.id
    .split('-')
    .filter(Boolean)
    .map((part) => part.toUpperCase())
    .join(' · ')
  return `${handle} · ${s.missions} missions`
}

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
  scripted: FALLBACK_COLOR,
  solo: STATUS_COLORS.open,
  swarm: MISSION_KIND_COLORS.infra_repair,
  society: ARM_PALETTE.society,
}

interface InjectMarker {
  kind: string
  district: string
  tick: number
}

interface Props {
  onTickReceived: (tick: TickRecord, world: WorldState | null) => void
}

export function LiveTab({ onTickReceived }: Props) {
  const [status, setStatus] = useState<LiveStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [arm, setArm] = useState('scripted')
  const [seed, setSeed] = useState(42)
  const [ticks, setTicks] = useState(SYNTHETIC_DEFAULT_TICKS)
  const [startError, setStartError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([])
  const [scenario, setScenario] = useState<string>(SYNTHETIC_SCENARIO)
  const scenarioActive = scenario !== SYNTHETIC_SCENARIO
  const [aarEnabled, setAarEnabled] = useState(false)
  const [memoryEnabled, setMemoryEnabled] = useState(false)
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

  const [liveTicks, setLiveTicks] = useState<TickRecord[]>([])
  const [liveWorld, setLiveWorld] = useState<WorldState | null>(null)
  const [selectedMission, setSelectedMission] = useState<string | null>(null)
  const [injectMarker, setInjectMarker] = useState<InjectMarker | null>(null)

  const latestTick = liveTicks.length > 0 ? liveTicks[liveTicks.length - 1] : null
  const cursor = liveTicks.length - 1
  const contention = deriveContention(latestTick, liveWorld)

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

  useEffect(() => {
    let cancelled = false
    api.getScenarios()
      .then((rows) => { if (!cancelled) setScenarios(rows) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  async function handleScenarioChange(nextId: string) {
    setScenario(nextId)
    setStartError(null)
    if (nextId === SYNTHETIC_SCENARIO) {
      setTicks(SYNTHETIC_DEFAULT_TICKS)
      return
    }
    try {
      const pack = await api.getScenario(nextId)
      const lastTick = pack.timeline.reduce(
        (max, e) => (e.tick > max ? e.tick : max),
        0,
      )
      const budget = Math.min(lastTick + SCENARIO_TICK_PADDING, SCENARIO_MAX_TICKS)
      setTicks(budget)
    } catch {}
  }

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [log])

  const appendLogRef = useRef(appendLog)
  const onTickRef = useRef(onTickReceived)
  useEffect(() => {
    appendLogRef.current = appendLog
    onTickRef.current = onTickReceived
  })

  const running = status?.running ?? false
  useEffect(() => {
    if (!running) {
      wsRef.current?.close()
      wsRef.current = null
      return
    }
    if (wsRef.current) return

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
          setLiveTicks((prev) => [...prev, msg.record!])
          setLiveWorld(msg.world ?? null)
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
    setLiveTicks([])
    setLiveWorld(null)
    setSelectedMission(null)
    setInjectMarker(null)
    try {
      const opts = {
        ...(aarEnabled ? { aar: true } : {}),
        ...(memoryEnabled ? { memory: true } : {}),
        ...(scenarioActive ? { scenario } : {}),
      }
      const startTicks = scenarioActive ? undefined : ticks
      await api.startLive(arm, seed, startTicks, opts)
      setMemoryActive(memoryEnabled)
      appendLog(
        `[start] arm=${arm} seed=${seed}` +
        (scenarioActive ? ` scenario=${scenario}` : ` ticks=${ticks}`) +
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
      setInjectMarker({ kind: injectKind, district: injectDistrict, tick: -1 })
      appendLog(`[inject] ${injectKind} → ${injectDistrict}`)
      setTimeout(() => setInjectOk(false), 2000)
    } catch (e) {
      setInjectError(friendlyError(e as Error))
    }
  }

  const handleDemo = useCallback(() => {
    setArm('scripted')
    setSeed(42)
    setTicks(30)
    setScenario(SYNTHETIC_SCENARIO)
    setAarEnabled(false)
    setMemoryEnabled(false)
    setTimeout(() => {
      handleStart()
    }, 100)
  }, [arm, seed, ticks, scenario, aarEnabled, memoryEnabled])

  const isRunning = status?.running ?? false

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left panel: controls */}
      <div className="w-64 shrink-0 flex flex-col gap-3 p-3 border-r border-eoc-border overflow-y-auto bg-eoc-ground">
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${isRunning ? 'bg-signal-green animate-pulse' : 'bg-eoc-border'}`}
          />
          <span className="text-[10px] font-mono text-eoc-secondary">
            {isRunning
              ? `RUNNING — ${status?.arm} / seed ${status?.seed} / T${status?.tick}`
              : 'IDLE'}
          </span>
          {isRunning && memoryActive && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-mono uppercase tracking-widest bg-signal-cyan/10 text-signal-cyan">
              MEMORY
            </span>
          )}
        </div>
        {statusError && (
          <div className="text-[10px] font-mono text-signal-red">{statusError}</div>
        )}

        <button
          onClick={handleDemo}
          disabled={isRunning || starting}
          className="w-full py-1.5 rounded text-[11px] font-mono uppercase tracking-wider transition-all
            bg-signal-cyan/15 border border-signal-cyan/60 text-signal-cyan
            hover:bg-signal-cyan/25 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Demo Mode
        </button>

        <div className="flex flex-col gap-2 p-2 bg-eoc-surface border border-eoc-border rounded-lg">
          <h3 className="text-[9px] font-mono uppercase tracking-widest text-eoc-secondary">
            Start Run
          </h3>

          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-mono text-eoc-secondary">Scenario</label>
            <select
              value={scenario}
              onChange={(e) => handleScenarioChange(e.target.value)}
              disabled={isRunning || starting}
              className="bg-eoc-raised border border-eoc-border rounded px-2 py-1 text-[10px] font-mono text-eoc-primary disabled:opacity-40"
            >
              <option value={SYNTHETIC_SCENARIO}>
                {`SYNTHETIC QUAKE (seed ${seed})`}
              </option>
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>
                  {scenarioOptionLabel(s)}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-mono text-eoc-secondary">Arm</label>
            <div className="flex gap-1 flex-wrap">
              {ARMS.map((a) => {
                const color = ARM_COLORS[a] ?? FALLBACK_COLOR
                const sel = arm === a
                return (
                  <button
                    key={a}
                    onClick={() => setArm(a)}
                    disabled={isRunning || starting}
                    className={`px-1.5 py-0.5 rounded text-[10px] font-mono transition-all disabled:opacity-40 border ${
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

          <div className="flex items-center gap-2">
            <label className="text-[10px] font-mono text-eoc-secondary w-8">Seed</label>
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(parseInt(e.target.value, 10) || 0)}
              disabled={isRunning || starting}
              className="flex-1 bg-eoc-raised border border-eoc-border rounded px-2 py-1 text-[10px] font-mono text-eoc-primary disabled:opacity-40"
            />
          </div>

          <div
            className={`flex items-center gap-2 transition-opacity ${
              scenarioActive ? 'opacity-40' : ''
            }`}
          >
            <label className="text-[10px] font-mono text-eoc-secondary w-8">Ticks</label>
            <input
              type="number"
              min={1}
              max={120}
              value={ticks}
              onChange={(e) => setTicks(Math.min(120, parseInt(e.target.value, 10) || 1))}
              disabled={isRunning || starting || scenarioActive}
              className="flex-1 bg-eoc-raised border border-eoc-border rounded px-2 py-1 text-[10px] font-mono text-eoc-primary disabled:opacity-40"
            />
          </div>

          <div className="flex gap-2">
            {[
              { id: 'aar', label: 'AAR', value: aarEnabled, set: setAarEnabled },
              { id: 'memory', label: 'MEM', value: memoryEnabled, set: setMemoryEnabled },
            ].map(({ id, label, value, set }) => (
              <button
                key={id}
                onClick={() => set((v) => !v)}
                disabled={isRunning || starting}
                aria-pressed={value}
                className={`flex-1 py-0.5 rounded text-[9px] font-mono uppercase tracking-widest transition-all border disabled:opacity-40 ${
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
            className="w-full py-1.5 rounded text-[10px] font-mono uppercase tracking-wider transition-all
              bg-signal-amber/20 border border-signal-amber text-signal-amber
              hover:bg-signal-amber/30 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {starting ? 'Starting…' : isRunning ? 'Running…' : 'Start'}
          </button>

          {startError && (
            <div className="text-[9px] font-mono text-signal-red border border-signal-red/30 bg-signal-red/10 rounded px-2 py-1">
              {startError}
            </div>
          )}
        </div>

        <div className="flex flex-col gap-2 p-2 bg-eoc-surface border border-eoc-border rounded-lg">
          <h3 className="text-[9px] font-mono uppercase tracking-widest text-eoc-secondary">
            Inject Event
          </h3>

          <div className="flex gap-1 flex-wrap">
            {EVENT_KINDS.map((k) => (
              <button
                key={k}
                onClick={() => setInjectKind(k)}
                disabled={!isRunning}
                className={`px-1.5 py-0.5 rounded text-[10px] font-mono transition-all disabled:opacity-40 ${
                  injectKind === k
                    ? 'bg-signal-red/20 border border-signal-red text-signal-red'
                    : 'border border-eoc-border text-eoc-secondary'
                }`}
              >
                {k}
              </button>
            ))}
          </div>

          <select
            value={injectDistrict}
            onChange={(e) => setInjectDistrict(e.target.value)}
            disabled={!isRunning}
            className="bg-eoc-raised border border-eoc-border rounded px-2 py-1 text-[10px] font-mono text-eoc-primary disabled:opacity-40"
          >
            {DISTRICTS.map((d) => (
              <option key={d} value={d}>
                {d.replace(/_/g, ' ')}
              </option>
            ))}
          </select>

          <button
            onClick={handleInject}
            disabled={!isRunning}
            className={`w-full py-1.5 rounded text-[10px] font-mono uppercase tracking-wider transition-all
              border disabled:opacity-40 disabled:cursor-not-allowed ${
              injectOk
                ? 'bg-signal-green/20 border-signal-green text-signal-green'
                : 'bg-signal-red/10 border-signal-red/60 text-signal-red hover:bg-signal-red/20'
            }`}
          >
            {injectOk ? 'Injected ✓' : 'Inject'}
          </button>

          {injectError && (
            <div className="text-[9px] font-mono text-signal-red">{injectError}</div>
          )}
        </div>
      </div>

      {/* Center: map + scoreboard overlay */}
      <div className="flex-1 flex flex-col relative overflow-hidden">
        {liveWorld ? (
          <>
            <div className="absolute top-2 left-1/2 -translate-x-1/2 z-10">
              <Scoreboard tick={latestTick} />
            </div>
            <div className="absolute top-12 left-3 z-10 w-48">
              <PanicGauge panic={liveWorld.panic} />
            </div>
            <div className="flex-1 p-2">
              <MissionControlMap
                world={liveWorld}
                selectedMissionId={selectedMission}
                onSelectMission={setSelectedMission}
                contest={contention}
              />
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <div className="text-eoc-secondary text-sm font-mono mb-2">
                {isRunning ? 'Waiting for first tick…' : 'Start a run to see the map'}
              </div>
              {!isRunning && (
                <button
                  onClick={handleDemo}
                  className="px-4 py-2 rounded text-xs font-mono uppercase tracking-wider
                    bg-signal-cyan/15 border border-signal-cyan/60 text-signal-cyan
                    hover:bg-signal-cyan/25 transition-all"
                >
                  Run Demo
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Right: negotiation feed + resource pools */}
      <div className="w-72 shrink-0 flex flex-col border-l border-eoc-border overflow-hidden">
        <div className="flex-1 overflow-hidden">
          <NegotiationFeed
            ticks={liveTicks}
            cursor={cursor}
            injectMarker={injectMarker}
          />
        </div>
        {liveWorld && (
          <div className="border-t border-eoc-border overflow-y-auto max-h-48">
            <ResourcePoolSidebar pools={liveWorld.pools} />
          </div>
        )}
      </div>
    </div>
  )
}
