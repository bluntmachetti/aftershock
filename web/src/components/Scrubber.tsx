import type { TimelineState } from '../types'
import type { TimelineAction } from '../lib/timeline'
import type { ScrubberEvent, ScrubberEventKind } from '../lib/timeline'
import { selectMaxCursor, selectHasMore } from '../lib/timeline'
import { STATUS_COLORS, ARM_COLORS } from '../lib/palette'

const SPEEDS = [0.5, 1, 2, 4, 8]

// Marker colors, sourced from palette.ts (no #rrggbb literals here). spawn maps
// to the "open" amber (a new mission appears), inject to society cyan (an
// operator/external action), resolve to green, fail to red.
const EVENT_COLORS: Record<ScrubberEventKind, string> = {
  spawn: STATUS_COLORS.open,
  inject: ARM_COLORS.society,
  resolve: STATUS_COLORS.resolved,
  fail: STATUS_COLORS.failed,
}

const EVENT_LABELS: Record<ScrubberEventKind, string> = {
  spawn: 'spawn',
  inject: 'inject',
  resolve: 'resolve',
  fail: 'fail',
}

interface Props {
  timeline: TimelineState
  dispatch: React.Dispatch<TimelineAction>
  onLoadMore: () => void
  /** Optional notable moments to mark along the track (computed by the caller
   *  via deriveScrubberEvents). Omitting them keeps single-map usage unchanged. */
  events?: ScrubberEvent[]
  /** Called when a marker is clicked, with the marker's logical tick. */
  onJump?: (tick: number) => void
}

export function Scrubber({ timeline, dispatch, onLoadMore, events, onJump }: Props) {
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

  // Span of the rendered timeline, used to position markers as a 0–100% offset.
  const minTick = timeline.ticks[0]?.tick ?? 0
  const maxTick = timeline.ticks[max]?.tick ?? minTick
  const span = maxTick - minTick

  return (
    <div className="flex items-center gap-3 px-3 py-2 bg-eoc-surface border-t border-eoc-border">
      {/* Play/pause */}
      <button
        onClick={togglePlay}
        className="w-7 h-7 rounded flex items-center justify-center bg-eoc-raised hover:bg-eoc-border text-signal-amber transition-colors shrink-0"
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
        className="text-xs font-mono text-eoc-secondary hover:text-signal-amber w-8 text-center shrink-0 transition-colors"
        aria-label="Cycle speed"
      >
        {timeline.speed}×
      </button>

      {/* Slider + event markers share one positioned track */}
      <div className="flex-1 flex items-center gap-2">
        <div className="relative flex-1 flex items-center">
          <input
            type="range"
            min={0}
            max={max}
            value={timeline.cursor}
            onChange={handleSlider}
            className="w-full h-1 accent-signal-amber cursor-pointer"
            style={{ accentColor: EVENT_COLORS.spawn }}
          />
          {events && events.length > 0 && span > 0 && (
            <div className="pointer-events-none absolute inset-x-0 top-0 bottom-0">
              {events.map((event, i) => {
                const pct = ((event.tick - minTick) / span) * 100
                if (pct < 0 || pct > 100) return null
                const color = EVENT_COLORS[event.kind]
                const labelText = event.label ?? EVENT_LABELS[event.kind]
                return (
                  <button
                    key={`${event.tick}-${event.kind}-${i}`}
                    type="button"
                    onClick={() => onJump?.(event.tick)}
                    title={`T${event.tick} · ${EVENT_LABELS[event.kind]}${event.label ? ` · ${event.label}` : ''}`}
                    aria-label={`Jump to tick ${event.tick}, ${EVENT_LABELS[event.kind]} ${labelText}`}
                    className="pointer-events-auto absolute top-1/2 w-0.5 h-3 -translate-x-1/2 -translate-y-1/2 rounded-full opacity-70 hover:opacity-100 hover:h-4 transition-all cursor-pointer"
                    style={{ left: `${pct}%`, backgroundColor: color }}
                  />
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Tick indicator */}
      <span className="text-xs font-mono tabular-nums text-eoc-secondary shrink-0">
        T{currentTick?.tick ?? '—'} / {timeline.total}
      </span>

      {/* Load more */}
      {hasMore && (
        <button
          onClick={onLoadMore}
          disabled={timeline.loading}
          className="text-xs font-mono text-signal-cyan hover:text-signal-cyan/80 disabled:text-eoc-faint transition-colors shrink-0"
        >
          {timeline.loading ? 'loading…' : `+load`}
        </button>
      )}
    </div>
  )
}
