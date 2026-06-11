/**
 * usePlaybackClock — the single shared playback timer.
 *
 * One interval, one source of truth for "advance the cursor every N ms". Both
 * the single-run map view and compare mode drive their cursor from this hook so
 * there is never more than one live interval per surface (the spec's "never two
 * intervals"). The hook owns nothing but the timer; the caller decides what a
 * tick means via `onTick` and when to stop by toggling `playing`.
 *
 *   usePlaybackClock(playing, speed, onTick)
 *
 * - `playing` — while true the clock fires; false clears the interval.
 * - `speed`   — playback multiplier; period is `1000 / speed` ms (8× → 125ms).
 * - `onTick`  — called on every elapsed period. Kept in a ref so a caller can
 *   pass a fresh closure each render without tearing down and rebuilding the
 *   interval (which would reset its phase and stutter playback).
 */
import { useEffect, useRef } from 'react'

export function usePlaybackClock(
  playing: boolean,
  speed: number,
  onTick: () => void,
): void {
  // Keep the latest callback without re-arming the interval on every render.
  const onTickRef = useRef(onTick)
  useEffect(() => {
    onTickRef.current = onTick
  }, [onTick])

  useEffect(() => {
    if (!playing) return
    const ms = 1000 / (speed > 0 ? speed : 1)
    const id = setInterval(() => {
      onTickRef.current()
    }, ms)
    return () => clearInterval(id)
  }, [playing, speed])
}
