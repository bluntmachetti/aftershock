import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import type { TimelineState, RunSummary, AarReport, ConformanceReport } from '../types'
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
import { TownMap } from './TownMap'
import { PanicGauge } from './PanicGauge'
import { ResourcePoolSidebar } from './ResourcePoolSidebar'
import { NegotiationFeed } from './NegotiationFeed'
import { AgentInspector } from './AgentInspector'
import { Scrubber } from './Scrubber'
import { RunPicker } from './RunPicker'
import { AarDrawer } from './AarDrawer'
import { Legend } from './Legend'

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

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar: run picker + resource pools */}
        <div className="w-52 shrink-0 flex flex-col gap-3 p-3 border-r border-eoc-border overflow-y-auto bg-eoc-ground">
          <RunPicker
            runs={runs}
            selectedRunId={timeline.runId}
            error={runsError}
            loading={timeline.loading}
            onSelect={handleRunDetails}
          />
          {world && (
            <>
              <div className="border-t border-eoc-border" />
              <PanicGauge panic={world.panic} />
              <div className="border-t border-eoc-border" />
              <ResourcePoolSidebar pools={world.pools} />
              <div className="border-t border-eoc-border" />
              <div className="flex flex-col gap-1">
                <div className="text-[11px] font-mono uppercase tracking-widest text-eoc-secondary">
                  Totals
                </div>
                <div className="flex justify-between text-xs font-mono tabular-nums">
                  <span className="text-eoc-secondary">Saved</span>
                  <span className="text-signal-green font-semibold">{world.lives_saved}</span>
                </div>
                <div className="flex justify-between text-xs font-mono tabular-nums">
                  <span className="text-eoc-secondary">Lost</span>
                  <span className="text-signal-red font-semibold">{world.lives_lost}</span>
                </div>
              </div>
            </>
          )}
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
              <TownMap
                world={world}
                selectedMissionId={selectedMission}
                onSelectMission={setSelectedMission}
                pulseDistricts={pulseDistricts}
                missionRequesters={missionRequesters}
              />
              {/* Dismissible legend overlay (self-suppresses via localStorage) */}
              <Legend />
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
