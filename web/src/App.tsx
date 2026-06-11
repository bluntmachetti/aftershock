import { useReducer, useState, useEffect, useCallback } from 'react'
import type { TabId, RunSummary } from './types'
import { timelineReducer, initialTimelineState } from './lib/timeline'
import { api } from './lib/api'
import { MapTab } from './components/MapTab'
import { BenchTab } from './components/BenchTab'
import { LiveTab } from './components/LiveTab'
import { Scoreboard } from './components/Scoreboard'

export default function App() {
  const [tab, setTab] = useState<TabId>('map')
  const [timeline, dispatch] = useReducer(timelineReducer, initialTimelineState)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [runsError, setRunsError] = useState<string | null>(null)

  // Load run list on mount
  useEffect(() => {
    api.runs()
      .then(setRuns)
      .catch((e: Error) => setRunsError(e.message))
  }, [])

  const handleSelectRun = useCallback(
    async (runId: string, hasWorld: boolean, total: number) => {
      dispatch({ type: 'LOAD_RUN', runId, hasWorld, total })
      try {
        const data = await api.ticks(runId, 0, 50)
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
      const data = await api.ticks(timeline.runId, start, 50)
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

  return (
    <div className="flex flex-col h-screen bg-[#0a0e1a] text-slate-200 overflow-hidden">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-2 border-b border-[#243047] bg-[#0f1624] shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
          <span className="font-mono text-amber-400 text-sm tracking-widest uppercase">
            Aftershock Observatory
          </span>
        </div>
        <Scoreboard tick={timeline.ticks[timeline.cursor] ?? null} />
        <nav className="flex gap-1">
          {(['map', 'bench', 'live'] as TabId[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1 text-xs font-mono uppercase tracking-wider rounded transition-colors ${
                tab === t
                  ? 'bg-amber-500 text-slate-950 font-semibold'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-[#243047]'
              }`}
            >
              {t}
            </button>
          ))}
        </nav>
      </header>

      {/* Main content */}
      <main className="flex-1 overflow-hidden">
        {tab === 'map' && (
          <MapTab
            timeline={timeline}
            runs={runs}
            runsError={runsError}
            onSelectRun={handleSelectRun}
            onLoadMore={handleLoadMore}
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
      </main>
    </div>
  )
}
