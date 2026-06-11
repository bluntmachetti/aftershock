import type { TimelineState } from '../types'
import type { TimelineAction } from '../lib/timeline'
import { selectMaxCursor, selectHasMore } from '../lib/timeline'

const SPEEDS = [0.5, 1, 2, 4, 8]

interface Props {
  timeline: TimelineState
  dispatch: React.Dispatch<TimelineAction>
  onLoadMore: () => void
}

export function Scrubber({ timeline, dispatch, onLoadMore }: Props) {
  const max = selectMaxCursor(timeline)
  const hasMore = selectHasMore(timeline)

  function handleSlider(e: React.ChangeEvent<HTMLInputElement>) {
    dispatch({ type: 'SET_CURSOR', cursor: parseInt(e.target.value, 10) })
  }

  function togglePlay() {
    dispatch({ type: timeline.playing ? 'PAUSE' : 'PLAY' })
  }

  function cycleSpeed() {
    const idx = SPEEDS.indexOf(timeline.speed)
    const next = SPEEDS[(idx + 1) % SPEEDS.length]
    dispatch({ type: 'SET_SPEED', speed: next })
  }

  const currentTick = timeline.ticks[timeline.cursor]

  return (
    <div className="flex items-center gap-3 px-3 py-2 bg-[#0f1624] border-t border-[#243047]">
      {/* Play/pause */}
      <button
        onClick={togglePlay}
        className="w-7 h-7 rounded flex items-center justify-center bg-[#1a2235] hover:bg-[#243047] text-amber-400 transition-colors shrink-0"
        aria-label={timeline.playing ? 'Pause' : 'Play'}
      >
        {timeline.playing ? (
          <svg viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3">
            <rect x="3" y="2" width="3.5" height="12" rx="1" />
            <rect x="9.5" y="2" width="3.5" height="12" rx="1" />
          </svg>
        ) : (
          <svg viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3">
            <path d="M4 2.5l10 5.5-10 5.5V2.5z" />
          </svg>
        )}
      </button>

      {/* Speed */}
      <button
        onClick={cycleSpeed}
        className="text-[10px] font-mono text-slate-400 hover:text-amber-400 w-8 text-center shrink-0 transition-colors"
        aria-label="Cycle speed"
      >
        {timeline.speed}×
      </button>

      {/* Slider */}
      <div className="flex-1 flex items-center gap-2">
        <input
          type="range"
          min={0}
          max={max}
          value={timeline.cursor}
          onChange={handleSlider}
          className="flex-1 h-1 accent-amber-500 cursor-pointer"
          style={{ accentColor: '#f59e0b' }}
        />
      </div>

      {/* Tick indicator */}
      <span className="text-[10px] font-mono tabular-nums text-slate-400 shrink-0">
        T{currentTick?.tick ?? '—'} / {timeline.total}
      </span>

      {/* Load more */}
      {hasMore && (
        <button
          onClick={onLoadMore}
          disabled={timeline.loading}
          className="text-[10px] font-mono text-cyan-400 hover:text-cyan-300 disabled:text-slate-600 transition-colors shrink-0"
        >
          {timeline.loading ? 'loading…' : `+load`}
        </button>
      )}
    </div>
  )
}
