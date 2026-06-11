import { useState, useEffect, useRef } from 'react'
import type { TimelineState, RunSummary, AarReport } from '../types'
import type { TimelineAction } from '../lib/timeline'
import {
  selectCurrentWorld,
  selectCurrentTick,
  selectAtEnd,
  selectNextCursor,
} from '../lib/timeline'
import { api } from '../lib/api'
import { TownMap } from './TownMap'
import { PanicGauge } from './PanicGauge'
import { ResourcePoolSidebar } from './ResourcePoolSidebar'
import { NegotiationFeed } from './NegotiationFeed'
import { AgentInspector } from './AgentInspector'
import { Scrubber } from './Scrubber'
import { RunPicker } from './RunPicker'
import { AarDrawer } from './AarDrawer'

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
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const world = selectCurrentWorld(timeline)
  const tick = selectCurrentTick(timeline)

  // Playback interval
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    if (!timeline.playing) return

    const ms = 1000 / timeline.speed
    intervalRef.current = setInterval(() => {
      if (selectAtEnd(timeline)) {
        dispatch({ type: 'PAUSE' })
        return
      }
      dispatch({ type: 'SET_CURSOR', cursor: selectNextCursor(timeline) })
    }, ms)

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [timeline.playing, timeline.speed, timeline.cursor, timeline.ticks.length, dispatch])

  // Clear AAR when run changes
  useEffect(() => {
    setAar(null)
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
        <div className="w-52 shrink-0 flex flex-col gap-3 p-3 border-r border-[#243047] overflow-y-auto bg-[#0a0e1a]">
          <RunPicker
            runs={runs}
            selectedRunId={timeline.runId}
            error={runsError}
            loading={timeline.loading}
            onSelect={handleRunDetails}
          />
          {world && (
            <>
              <div className="border-t border-[#243047]" />
              <PanicGauge panic={world.panic} />
              <div className="border-t border-[#243047]" />
              <ResourcePoolSidebar pools={world.pools} />
              <div className="border-t border-[#243047]" />
              <div className="flex flex-col gap-1">
                <div className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
                  Totals
                </div>
                <div className="flex justify-between text-[11px] font-mono tabular-nums">
                  <span className="text-green-400">Saved</span>
                  <span className="text-green-400">{world.lives_saved}</span>
                </div>
                <div className="flex justify-between text-[11px] font-mono tabular-nums">
                  <span className="text-red-400">Lost</span>
                  <span className="text-red-400">{world.lives_lost}</span>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Center: map */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {timeline.error && (
            <div className="px-3 py-2 text-[11px] font-mono text-red-400 bg-red-950/20 border-b border-red-900">
              {timeline.error}
            </div>
          )}
          {!world && !timeline.loading && (
            <div className="flex-1 flex items-center justify-center text-slate-600 font-mono text-sm">
              Select a run to load the map.
            </div>
          )}
          {timeline.loading && (
            <div className="flex-1 flex items-center justify-center text-amber-400 font-mono text-sm">
              <span className="animate-pulse">Loading…</span>
            </div>
          )}
          {world && (
            <div className="flex-1 relative overflow-hidden scanlines">
              <TownMap
                world={world}
                selectedMissionId={selectedMission}
                onSelectMission={setSelectedMission}
              />
            </div>
          )}
          {!timeline.hasWorld && timeline.runId && !timeline.loading && (
            <div className="px-3 py-1 text-[10px] font-mono text-slate-500 border-t border-[#243047] bg-[#0f1624]">
              No world data — showing feeds only.
            </div>
          )}
        </div>

        {/* Right rail: negotiation feed + agent inspector */}
        <div className="w-64 shrink-0 flex flex-col border-l border-[#243047] bg-[#0a0e1a] overflow-hidden">
          <div className="flex-1 overflow-hidden border-b border-[#243047]">
            <NegotiationFeed ticks={timeline.ticks} cursor={timeline.cursor} />
          </div>
          <div className="h-48 overflow-y-auto">
            <div className="text-[10px] font-mono uppercase tracking-widest text-slate-500 px-2 py-1 sticky top-0 bg-[#0f1624] border-b border-[#243047]">
              Agent Inspector · T{tick?.tick ?? '—'}
            </div>
            <AgentInspector
              tick={tick}
              selectedAgent={selectedAgent}
              onSelectAgent={setSelectedAgent}
            />
          </div>
        </div>
      </div>

      {/* Scrubber */}
      <Scrubber timeline={timeline} dispatch={dispatch} onLoadMore={onLoadMore} />

      {/* AAR Drawer — visible only when the loaded run has an AAR */}
      {aar && (
        <AarDrawer report={aar} onJumpToTick={handleJumpToTick} />
      )}
    </div>
  )
}
