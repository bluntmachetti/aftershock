import { useReducer, useState, useEffect, useCallback, useRef } from 'react'
import type { TabId, RunSummary, ScenarioPack } from './types'
import {
  timelineReducer,
  initialTimelineState,
  indexForTick,
} from './lib/timeline'
import { api } from './lib/api'
import {
  parseDeepLink,
  useUrlReflection,
} from './lib/deeplink'
import type { CompareController } from './lib/compare'
import { MapTab } from './components/MapTab'
import { BenchTab } from './components/BenchTab'
import { LiveTab } from './components/LiveTab'
import { CompareTab } from './components/CompareTab'
import { Scoreboard } from './components/Scoreboard'
import { DataChip, ProvenancePanel } from './components/ProvenancePanel'

const TABS: TabId[] = ['map', 'bench', 'live', 'compare']

// Page size for deep-link paging — match the single-run loader's 50.
const PAGE = 50

// The run a judge lands on with zero clicks when there's no deep link: prefer the
// NYC-Ida society flagship, then any real-scenario society run, then any society run,
// then whatever the list leads with. Keeps first contact on real evidence, not an
// empty "select a run" panel.
function pickDefaultRun(list: RunSummary[]): RunSummary | undefined {
  return (
    list.find((r) => r.run_id === 'seed91-society') ??
    list.find((r) => r.arm === 'society' && r.scenario) ??
    list.find((r) => r.arm === 'society') ??
    list[0]
  )
}

interface CompareInit {
  left: string
  right: string
  tick: number
}

export default function App() {
  const [tab, setTab] = useState<TabId>('map')
  const [timeline, dispatch] = useReducer(timelineReducer, initialTimelineState)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [runsError, setRunsError] = useState<string | null>(null)
  // True until the first /api/runs fetch resolves; lets RunPicker show "Loading runs…"
  // instead of a misleading "No runs found" during the fetch.
  const [runsLoading, setRunsLoading] = useState(true)

  // Deep-link seed for COMPARE (resolved once after api.runs()); the live
  // controller state flows back up via onStateChange for URL reflection.
  const [compareInit, setCompareInit] = useState<CompareInit | null>(null)
  const [compareState, setCompareState] = useState<CompareController | null>(null)

  // DATA chip + provenance deep-dive (task #4). The chip is mounted in the app
  // header ONLY when the active MAP run carries a scenario block; absent →
  // nothing renders (behavior unchanged for synthetic runs). The full pack is
  // fetched lazily per scenario id and cached so the panel needs no second hit.
  const [provenanceOpen, setProvenanceOpen] = useState(false)
  const [scenarioPack, setScenarioPack] = useState<ScenarioPack | null>(null)

  // The compact scenario ({id,name,hazard}) of the active MAP run, or null for a
  // synthetic run. Drives whether the DATA chip mounts at all.
  const activeScenario =
    runs.find((r) => r.run_id === timeline.runId)?.scenario ?? null

  // Guard so the deep link is applied exactly once (not on every runs refresh).
  const deepLinkAppliedRef = useRef(false)

  const handleSelectRun = useCallback(
    async (runId: string, hasWorld: boolean, total: number) => {
      dispatch({ type: 'LOAD_RUN', runId, hasWorld, total })
      try {
        const data = await api.ticks(runId, 0, PAGE)
        dispatch({
          type: 'APPEND_TICKS',
          ticks: data.ticks,
          worlds: data.worlds,
          total: data.total,
        })
      } catch (e) {
        dispatch({ type: 'SET_ERROR', error: (e as Error).message })
      }
    },
    [],
  )

  const handleLoadMore = useCallback(async () => {
    if (!timeline.runId) return
    const start = timeline.ticks.length
    try {
      const data = await api.ticks(timeline.runId, start, PAGE)
      dispatch({
        type: 'APPEND_TICKS',
        ticks: data.ticks,
        worlds: data.worlds,
        total: data.total,
      })
    } catch (e) {
      dispatch({ type: 'SET_ERROR', error: (e as Error).message })
    }
  }, [timeline.runId, timeline.ticks.length])

  // Re-fetch the run list on demand (the mount effect below only loads once).
  // CompareTab uses this to surface a freshly-branched counterfactual run without
  // a page reload; returns the fresh list so the caller can act on it.
  const refreshRuns = useCallback(async (): Promise<RunSummary[]> => {
    const list = await api.runs()
    setRuns(list)
    return list
  }, [])

  // Empty/error-state CTA: re-fetch the run list and load the flagship demo run. Gives a
  // judge a one-click recovery path if the first auto-load ever fails (slow/empty deploy).
  const loadDemoRun = useCallback(async () => {
    setRunsError(null)
    setRunsLoading(true)
    try {
      const list = await api.runs()
      setRuns(list)
      const def = pickDefaultRun(list)
      if (def) handleSelectRun(def.run_id, def.has_world ?? false, def.ticks ?? 0)
    } catch (e) {
      setRunsError((e as Error).message)
    } finally {
      setRunsLoading(false)
    }
  }, [handleSelectRun])

  // Load run list on mount, then apply any deep link AFTER runs resolve.
  useEffect(() => {
    let cancelled = false
    api.runs()
      .then(async (list) => {
        if (cancelled) return
        setRuns(list)
        setRunsLoading(false)
        if (deepLinkAppliedRef.current) return
        deepLinkAppliedRef.current = true

        const link = parseDeepLink(window.location.search, list)
        if (!link) {
          // No deep link → auto-load a sensible default so the map renders real data on
          // first contact (zero-click demo) instead of an empty "select a run" panel.
          const def = pickDefaultRun(list)
          if (!def) return
          dispatch({
            type: 'LOAD_RUN',
            runId: def.run_id,
            hasWorld: def.has_world ?? false,
            total: def.ticks ?? 0,
          })
          try {
            const data = await api.ticks(def.run_id, 0, PAGE)
            if (cancelled) return
            dispatch({
              type: 'APPEND_TICKS',
              ticks: data.ticks,
              worlds: data.worlds,
              total: data.total,
            })
          } catch (e) {
            if (!cancelled) dispatch({ type: 'SET_ERROR', error: (e as Error).message })
          }
          return
        }

        if (link.kind === 'compare') {
          setCompareInit({ left: link.leftRunId, right: link.rightRunId, tick: link.tick })
          setTab('compare')
          return
        }

        // kind === 'run' — select it, page until the target tick is loaded,
        // then set the cursor to that logical tick. Paging here (not in
        // handleSelectRun) keeps the normal click-to-load path untouched.
        const meta = list.find((r) => r.run_id === link.runId)
        const hasWorld = meta?.has_world ?? false
        dispatch({ type: 'LOAD_RUN', runId: link.runId, hasWorld, total: meta?.ticks ?? 0 })

        const loaded: import('./types').TickRecord[] = []
        let total = Infinity
        try {
          while (loaded.length < total) {
            const data = await api.ticks(link.runId, loaded.length, PAGE)
            if (cancelled) return
            total = data.total
            dispatch({
              type: 'APPEND_TICKS',
              ticks: data.ticks,
              worlds: data.worlds,
              total: data.total,
            })
            loaded.push(...data.ticks)
            if (data.ticks.length === 0) break
            const last = loaded[loaded.length - 1]
            if (last && last.tick >= link.tick) break
          }
          dispatch({ type: 'SET_CURSOR', cursor: indexForTick(loaded, link.tick) })
        } catch (e) {
          if (!cancelled) dispatch({ type: 'SET_ERROR', error: (e as Error).message })
        }
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setRunsError(e.message)
          setRunsLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  // ---- URL reflection (throttled history.replaceState) ----
  // Reflect the active tab's scrub/playback state. COMPARE reflects the shared
  // controller; MAP reflects the single-run cursor. Other tabs write nothing.
  const reflectState = (() => {
    if (tab === 'compare' && compareState?.leftRunId && compareState.rightRunId) {
      const seed = runs.find((r) => r.run_id === compareState.leftRunId)?.seed
      return {
        kind: 'compare' as const,
        leftRunId: compareState.leftRunId,
        rightRunId: compareState.rightRunId,
        seed,
        tick: compareState.cursorTick,
      }
    }
    if (tab === 'map' && timeline.runId) {
      const tickRec = timeline.ticks[timeline.cursor]
      return {
        kind: 'run' as const,
        runId: timeline.runId,
        tick: tickRec?.tick ?? 0,
      }
    }
    return { kind: 'none' as const }
  })()
  useUrlReflection(reflectState)

  // Lazily fetch the full scenario pack for the active MAP run (the
  // ProvenancePanel data source). A synthetic run (no scenario) clears the pack
  // and force-closes the panel, so the deep dive is impossible to leave open
  // across a scenario→synthetic switch. Re-fetches only when the id changes.
  const activeScenarioId = activeScenario?.id ?? null
  useEffect(() => {
    if (!activeScenarioId) {
      setScenarioPack(null)
      setProvenanceOpen(false)
      return
    }
    let cancelled = false
    setProvenanceOpen(false)
    api.getScenario(activeScenarioId)
      .then((pack) => { if (!cancelled) setScenarioPack(pack) })
      .catch(() => { if (!cancelled) setScenarioPack(null) })
    return () => { cancelled = true }
  }, [activeScenarioId])

  return (
    <div className="flex flex-col h-screen bg-eoc-ground text-eoc-primary overflow-hidden">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-2 border-b border-eoc-border bg-eoc-surface shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-signal-amber animate-pulse" />
          <span className="font-mono text-signal-amber text-sm tracking-widest uppercase">
            Aftershock Observatory
          </span>
        </div>
        <Scoreboard tick={timeline.ticks[timeline.cursor] ?? null} />
        <div className="flex items-center gap-2">
          {/* DATA chip — mounted ONLY when the active MAP run carries a
              scenario; a synthetic run renders nothing here (no inert chip). */}
          {activeScenario && (
            <DataChip
              active={provenanceOpen}
              onClick={() => setProvenanceOpen((v) => !v)}
            />
          )}
          <nav className="flex gap-1">
            {TABS.map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-3 py-1 text-xs font-mono uppercase tracking-wider rounded transition-colors ${
                  tab === t
                    ? 'bg-signal-amber text-eoc-ground font-semibold'
                    : 'text-eoc-secondary hover:text-eoc-primary hover:bg-eoc-raised'
                }`}
              >
                {t}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 overflow-hidden">
        {tab === 'map' && (
          <MapTab
            timeline={timeline}
            runs={runs}
            runsError={runsError}
            runsLoading={runsLoading}
            onSelectRun={handleSelectRun}
            onLoadMore={handleLoadMore}
            onLoadDemo={loadDemoRun}
            dispatch={dispatch}
          />
        )}
        {tab === 'bench' && <BenchTab />}
        {tab === 'live' && (
          <LiveTab
            onTickReceived={(tick, world) =>
              dispatch({ type: 'LIVE_TICK', tick, world })
            }
          />
        )}
        {tab === 'compare' && (
          <CompareTab
            runs={runs}
            initialLeft={compareInit?.left}
            initialRight={compareInit?.right}
            cursorTick={compareInit?.tick}
            onStateChange={setCompareState}
            onRunsRefresh={refreshRuns}
          />
        )}
      </main>

      {/* Provenance deep-dive — floats over the app as a right-anchored sheet.
          Self-renders nothing unless `open` AND a `pack` is present, so a
          synthetic run can never surface it. */}
      <ProvenancePanel
        pack={scenarioPack}
        open={provenanceOpen}
        onClose={() => setProvenanceOpen(false)}
      />
    </div>
  )
}
