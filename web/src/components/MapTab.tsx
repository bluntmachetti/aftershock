import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import type {
  TimelineState,
  RunSummary,
  AarReport,
  ConformanceReport,
  ScenarioManifestBlock,
  ScenarioPack,
  ScenarioReferenceMission,
} from '../types'
import type { TimelineAction } from '../lib/timeline'
import {
  selectCurrentWorld,
  selectCurrentTick,
  selectAtEnd,
  selectNextCursor,
  deriveScrubberEvents,
} from '../lib/timeline'
import { usePlaybackClock } from '../lib/usePlaybackClock'
import { api } from '../lib/api'
import {
  mapTimelineIndexToMissionId,
  timelineIndexForMissionId,
  agentLatencyMinutes,
  buildFirstArrivalMap,
} from '../lib/scenario'
import { ARM_COLORS } from '../lib/palette'
import { deriveContention } from '../lib/contention'
import { MissionControlMap } from './MissionControlMap'
import { MissionControlShell } from './MissionControlShell'
import { RealityStrip } from './RealityStrip'
import { PanicGauge } from './PanicGauge'
import { ResourcePoolSidebar } from './ResourcePoolSidebar'
import { NegotiationFeed } from './NegotiationFeed'
import { AgentInspector } from './AgentInspector'
import { Scrubber } from './Scrubber'
import { RunPicker } from './RunPicker'
import { AarDrawer } from './AarDrawer'
import { Legend } from './Legend'
import { DemoGuide } from './DemoGuide'

// Left-rail (run picker + pools) width bounds + persistence key. The rail is
// drag-resizable so a long run list / long run ids stay readable.
const SIDEBAR_MIN_W = 180
const SIDEBAR_MAX_W = 560
const SIDEBAR_DEFAULT_W = 208 // matches the prior fixed w-52
const SIDEBAR_KEY = 'map-sidebar-width'

interface Props {
  timeline: TimelineState
  runs: RunSummary[]
  runsError: string | null
  onSelectRun: (runId: string, hasWorld: boolean, total: number) => void
  onLoadMore: () => void
  dispatch: React.Dispatch<TimelineAction>
}

export function MapTab({
  timeline,
  runs,
  runsError,
  onSelectRun,
  onLoadMore,
  dispatch,
}: Props) {
  const [selectedMission, setSelectedMission] = useState<string | null>(null)
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null)
  const [aar, setAar] = useState<AarReport | null>(null)
  const [conformance, setConformance] = useState<ConformanceReport | null>(null)

  // Scenario reality data (task #4). `scenarioBlock` carries the manifest's
  // reference_aggregates / caveat_line / tick_minutes (for the RealityStrip
  // footer); `scenarioPack` carries reference.missions (per-mission baseline)
  // for the kept popover lines. Both stay null for a synthetic run, so the
  // RealityStrip renders nothing and the map gets no scenario props — behavior
  // unchanged with no scenario.
  const [scenarioBlock, setScenarioBlock] = useState<ScenarioManifestBlock | null>(null)
  const [scenarioPack, setScenarioPack] = useState<ScenarioPack | null>(null)

  // Whether the active run carries a scenario (from the runs-list compact row).
  const activeScenarioId =
    runs.find((r) => r.run_id === timeline.runId)?.scenario?.id ?? null

  const world = selectCurrentWorld(timeline)
  const tick = selectCurrentTick(timeline)

  // Playback — driven by the single shared clock (never two intervals). The
  // tick callback reads the latest timeline via a ref so the clock is not
  // re-armed (and its phase reset) on every cursor change.
  const timelineRef = useRef(timeline)
  timelineRef.current = timeline
  const onPlaybackTick = useCallback(() => {
    const t = timelineRef.current
    if (selectAtEnd(t)) {
      dispatch({ type: 'PAUSE' })
      return
    }
    dispatch({ type: 'SET_CURSOR', cursor: selectNextCursor(t) })
  }, [dispatch])
  usePlaybackClock(timeline.playing, timeline.speed, onPlaybackTick)

  // Clear AAR and conformance when run changes
  useEffect(() => {
    setAar(null)
    setConformance(null)
  }, [timeline.runId])

  // Fetch the scenario reality data when the active run carries a scenario.
  // Pulls the manifest block (aggregates/caveat/tick_minutes) from the run
  // detail and the full pack (per-mission reference baselines) by scenario id.
  // A synthetic run (no scenario id) clears both, restoring no-scenario behavior.
  useEffect(() => {
    if (!timeline.runId || !activeScenarioId) {
      setScenarioBlock(null)
      setScenarioPack(null)
      return
    }
    let cancelled = false
    const runId = timeline.runId
    api.runDetail(runId)
      .then((detail) => { if (!cancelled) setScenarioBlock(detail.scenario) })
      .catch(() => { if (!cancelled) setScenarioBlock(null) })
    api.getScenario(activeScenarioId)
      .then((pack) => { if (!cancelled) setScenarioPack(pack) })
      .catch(() => { if (!cancelled) setScenarioPack(null) })
    return () => { cancelled = true }
  }, [timeline.runId, activeScenarioId])

  // Fetch AAR whenever a run finishes loading (loading goes false and we have a runId)
  useEffect(() => {
    if (!timeline.runId || timeline.loading) return
    let cancelled = false
    api.aar(timeline.runId)
      .then((report) => { if (!cancelled) setAar(report) })
      .catch(() => { /* 404 = no AAR — stay null */ })
    return () => { cancelled = true }
  }, [timeline.runId, timeline.loading])

  // Fetch conformance alongside the AAR — 404 means no report yet, stay null
  useEffect(() => {
    if (!timeline.runId || timeline.loading) return
    let cancelled = false
    api.conformance(timeline.runId)
      .then((report) => { if (!cancelled) setConformance(report) })
      .catch(() => { /* 404 = no conformance report — stay null */ })
    return () => { cancelled = true }
  }, [timeline.runId, timeline.loading])

  // Scrubber event markers — derived from the loaded timeline (no event-folding;
  // provenance from tick events, outcomes from world transitions).
  const scrubberEvents = useMemo(
    () => deriveScrubberEvents(timeline.ticks, timeline.worlds),
    [timeline.ticks, timeline.worlds],
  )

  // Inject pulse: districts touched by an injected-provenance event on the
  // current tick. Cleared automatically when the cursor moves off the tick.
  const pulseDistricts = useMemo(() => {
    if (!tick) return []
    const ids: string[] = []
    for (const event of tick.events) {
      if (event.payload?.injected !== true) continue
      const districtId =
        typeof event.payload?.district_id === 'string'
          ? (event.payload.district_id as string)
          : ''
      if (districtId) ids.push(districtId)
    }
    return ids
  }, [tick])

  // Per-mission resource requesters this tick — read from resource_request
  // proposals so the popover can name who is asking for a mission's resources.
  const missionRequesters = useMemo(() => {
    if (!tick) return {}
    const out: Record<string, string> = {}
    for (const response of tick.responses) {
      for (const proposal of response.proposals) {
        if (proposal.kind !== 'resource_request') continue
        const missionId =
          typeof proposal.body?.mission_id === 'string'
            ? (proposal.body.mission_id as string)
            : ''
        if (missionId) out[missionId] = proposal.sender
      }
    }
    return out
  }, [tick])

  // Contention overlay — contested missions + cross-district links derived from
  // this tick's resource auction (proposals + rulings). Empty on ticks with no
  // contested resource, so the map renders identically when nothing is contested.
  const contest = useMemo(() => deriveContention(tick, world), [tick, world])

  // ---- Scenario reality wiring (task #4) ----
  // All of the below are inert (null/empty) on a synthetic run.

  const tickMinutes = scenarioBlock?.tick_minutes ?? null

  // First-arrival tick per mission id, from the loaded timeline events.
  const firstArrivalMap = useMemo(
    () => buildFirstArrivalMap(timeline.ticks),
    [timeline.ticks],
  )

  // Per-mission real baseline getter for the popover. Resolves the mission's
  // engine id → injection-safe timeline INDEX → `reference.missions[index]`.
  // Returns null for an injected mission (no timeline baseline) or synthetic run.
  const scenarioRefForMission = useCallback(
    (missionId: string): ScenarioReferenceMission | null => {
      if (!scenarioPack) return null
      const idx = timelineIndexForMissionId(timeline.ticks, missionId)
      if (idx === null) return null
      return scenarioPack.reference.missions[String(idx)] ?? null
    },
    [scenarioPack, timeline.ticks],
  )

  // First-arrival tick getter for the popover's sim latency line.
  const agentFirstArrivalForMission = useCallback(
    (missionId: string): number | null => firstArrivalMap.get(missionId) ?? null,
    [firstArrivalMap],
  )

  // The arm's MEAN spawn→first-arrival latency in minutes, averaged across the
  // run's timeline missions (the single-arm RealityStrip readout). Only timeline
  // missions (injection-safe) are considered, and only those with a comparable
  // arrival contribute; null when none do. Pairs against the grey real baseline.
  const armLatencyMinutes = useMemo(() => {
    if (!scenarioPack || tickMinutes === null) return null
    const ids = mapTimelineIndexToMissionId(timeline.ticks)
    const samples: number[] = []
    for (const missionId of ids) {
      if (!missionId) continue
      const mission = world?.missions[missionId]
      const spawnTick = mission?.spawned_tick
      if (spawnTick === undefined) continue
      const arrival = firstArrivalMap.get(missionId) ?? null
      const latency = agentLatencyMinutes(spawnTick, arrival, tickMinutes)
      if (latency !== null) samples.push(latency)
    }
    if (samples.length === 0) return null
    return samples.reduce((s, v) => s + v, 0) / samples.length
  }, [scenarioPack, tickMinutes, timeline.ticks, world, firstArrivalMap])

  // The arm color for the strip — society=cyan, every baseline=amber.
  const armColor =
    runs.find((r) => r.run_id === timeline.runId)?.arm === 'society'
      ? ARM_COLORS.society
      : ARM_COLORS.baseline
  const armLabel =
    runs.find((r) => r.run_id === timeline.runId)?.arm ?? 'agents'

  // Jump scrubber to the tick index whose tick record matches the given tick number
  function handleJumpToTick(tickNumber: number) {
    const idx = timeline.ticks.findIndex((t) => t.tick === tickNumber)
    if (idx !== -1) {
      dispatch({ type: 'SET_CURSOR', cursor: idx })
    }
  }

  // Fetch run details when runs list lacks has_world
  async function handleRunDetails(run: RunSummary) {
    try {
      const detail = await api.run(run.run_id)
      onSelectRun(detail.run_id, detail.has_world ?? false, detail.ticks)
    } catch {
      onSelectRun(run.run_id, false, run.ticks)
    }
  }

  const activeRun = runs.find((r) => r.run_id === timeline.runId)

  // Resizable left rail. During a drag we mutate the element's width directly
  // (no React state churn → the heavy map doesn't re-render mid-drag) and commit
  // the final width to state + localStorage on release.
  const sidebarRef = useRef<HTMLDivElement>(null)
  const [sidebarWidth, setSidebarWidth] = useState<number>(() => {
    const saved = Number(localStorage.getItem(SIDEBAR_KEY))
    return Number.isFinite(saved) && saved >= SIDEBAR_MIN_W && saved <= SIDEBAR_MAX_W
      ? saved
      : SIDEBAR_DEFAULT_W
  })
  const startSidebarResize = useCallback((e: React.PointerEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = sidebarRef.current?.offsetWidth ?? SIDEBAR_DEFAULT_W
    document.body.style.userSelect = 'none'
    const onMove = (ev: PointerEvent) => {
      const w = Math.max(SIDEBAR_MIN_W, Math.min(SIDEBAR_MAX_W, startW + (ev.clientX - startX)))
      if (sidebarRef.current) sidebarRef.current.style.width = `${w}px`
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      document.body.style.userSelect = ''
      const finalW = sidebarRef.current?.offsetWidth ?? startW
      setSidebarWidth(finalW)
      try {
        localStorage.setItem(SIDEBAR_KEY, String(finalW))
      } catch {
        /* localStorage unavailable — width just won't persist */
      }
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }, [])

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Mission Control command band — CONDITION + run identity + op clock +
          saved/lost/active/at-risk counters. */}
      <MissionControlShell
        world={world ?? null}
        tickNumber={tick?.tick ?? null}
        totalTicks={timeline.total}
        arm={activeRun?.arm ?? null}
        seed={activeRun?.seed ?? null}
      />
      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar: run picker + resource pools. Width is drag-resizable
            (handle on the right edge); the run list fills the rail's height so a
            long list scrolls in a tall window, with the pools pinned below. */}
        <div
          ref={sidebarRef}
          style={{ width: sidebarWidth }}
          className="relative shrink-0 flex flex-col gap-3 p-3 border-r border-eoc-border bg-eoc-ground overflow-hidden"
        >
          <RunPicker
            runs={runs}
            selectedRunId={timeline.runId}
            error={runsError}
            loading={timeline.loading}
            onSelect={handleRunDetails}
          />
          {world && (
            <div className="shrink-0 flex flex-col gap-3">
              <div className="border-t border-eoc-border" />
              <PanicGauge panic={world.panic} />
              <div className="border-t border-eoc-border" />
              <ResourcePoolSidebar pools={world.pools} />
            </div>
          )}
          {/* Resize handle — drag to widen/narrow the rail. */}
          <div
            onPointerDown={startSidebarResize}
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize runs panel"
            title="Drag to resize"
            className="absolute top-0 right-0 z-10 h-full w-1.5 cursor-col-resize bg-transparent transition-colors hover:bg-signal-amber/40"
          />
        </div>

        {/* Center: map */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {timeline.error && (
            <div className="px-3 py-2 text-xs font-mono text-signal-red bg-red-950/20 border-b border-red-900">
              {timeline.error}
            </div>
          )}
          {!world && !timeline.loading && (
            <div className="flex-1 flex items-center justify-center text-eoc-secondary font-mono text-xs">
              Select a run to load the map.
            </div>
          )}
          {timeline.loading && (
            <div className="flex-1 flex items-center justify-center text-signal-amber font-mono text-xs">
              <span className="animate-pulse">Loading…</span>
            </div>
          )}
          {world && (
            <div className="flex-1 relative overflow-hidden scanlines">
              <MissionControlMap
                world={world}
                selectedMissionId={selectedMission}
                onSelectMission={setSelectedMission}
                pulseDistricts={pulseDistricts}
                missionRequesters={missionRequesters}
                scenarioRefForMission={scenarioRefForMission}
                agentFirstArrivalForMission={agentFirstArrivalForMission}
                tickMinutes={tickMinutes}
                contest={contest}
              />
              {/* Dismissible legend overlay (self-suppresses via localStorage) */}
              <Legend />
              {/* Judge demo guide — dismissible 5-step arc overlay (Day 4) */}
              <DemoGuide />
            </div>
          )}
          {!timeline.hasWorld && timeline.runId && !timeline.loading && (
            <div className="px-3 py-1 text-[10px] font-mono text-eoc-secondary border-t border-eoc-border bg-eoc-surface">
              No world data — showing feeds only.
            </div>
          )}
        </div>

        {/* Right rail: negotiation feed + agent inspector */}
        <div className="w-64 shrink-0 flex flex-col border-l border-eoc-border bg-eoc-ground overflow-hidden">
          <div className="flex-1 overflow-hidden border-b border-eoc-border">
            <NegotiationFeed ticks={timeline.ticks} cursor={timeline.cursor} />
          </div>
          <div className="h-48 overflow-y-auto">
            <div className="text-[11px] font-mono uppercase tracking-widest text-eoc-secondary px-2 py-1 sticky top-0 bg-eoc-surface border-b border-eoc-border">
              Agent Inspector · T{tick?.tick ?? '—'}
            </div>
            <AgentInspector
              tick={tick}
              selectedAgent={selectedAgent}
              conformance={conformance}
              onSelectAgent={setSelectedAgent}
            />
          </div>
        </div>
      </div>

      {/* Reality baseline — scenario-level map FOOTER pinned ABOVE the Scrubber
          (delta 2). One strip, one arm (this run) vs the single grey real
          baseline. Self-suppresses (renders nothing) when the run has no
          scenario / no real latency baseline, so synthetic behavior is
          unchanged. */}
      {scenarioBlock && (
        <RealityStrip
          aggregates={scenarioBlock.reference_aggregates}
          caveatLine={scenarioBlock.caveat_line}
          arms={[
            {
              arm: armLabel,
              latencyMinutes: armLatencyMinutes,
              color: armColor,
            },
          ]}
          className="border-t"
        />
      )}

      {/* Scrubber */}
      <Scrubber
        timeline={timeline}
        dispatch={dispatch}
        onLoadMore={onLoadMore}
        events={scrubberEvents}
        onJump={handleJumpToTick}
      />

      {/* AAR Drawer — visible only when the loaded run has an AAR */}
      {aar && (
        <AarDrawer report={aar} onJumpToTick={handleJumpToTick} />
      )}
    </div>
  )
}
