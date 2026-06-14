// EOC condition state (RED/AMBER/BLUE/GREEN) for the Mission Control header —
// ported from the prototype's `conditionFor`. Deadline-, severity-, and
// panic-driven; pure and testable. No engine data; reads the current world only.

import type { WorldState } from '../types'
import { CONDITION_COLORS, type ConditionLevel } from './palette'

export interface ConditionState {
  level: ConditionLevel
  label: 'RED' | 'AMBER' | 'BLUE' | 'GREEN'
  color: string
}

const LABELS: Record<ConditionLevel, ConditionState['label']> = {
  red: 'RED',
  amber: 'AMBER',
  blue: 'BLUE',
  green: 'GREEN',
}

function make(level: ConditionLevel): ConditionState {
  return { level, label: LABELS[level], color: CONDITION_COLORS[level] }
}

/** Derive the EOC condition from the current world + tick number.
 *  - RED:   an open mission ≤2 ticks from deadline, or panic ≥ 0.6
 *  - AMBER: an open mission ≤5 ticks from deadline or severity ≥ 4, or panic ≥ 0.3
 *  - BLUE:  any open missions remain
 *  - GREEN: nothing open */
export function conditionFor(
  world: WorldState | null | undefined,
  tick: number,
): ConditionState {
  if (!world) return make('green')
  const open = Object.values(world.missions).filter((m) => m.status === 'open')
  const panic = world.panic
  if (open.some((m) => m.deadline_tick - tick <= 2) || panic >= 0.6) return make('red')
  if (
    open.some((m) => m.deadline_tick - tick <= 5 || m.severity >= 4) ||
    panic >= 0.3
  )
    return make('amber')
  if (open.length > 0) return make('blue')
  return make('green')
}
