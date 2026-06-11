// Single source of truth for JS/SVG colors (hex literals) shared across
// TownMap / BenchTab / RunPicker / LiveTab / AgentInspector / CompareTab.
//
// DOM/Tailwind surfaces use the semantic `eoc.*` / `signal.*` / `text-eoc-*`
// token classes (backed by the RGB-channel vars in index.css). This module is
// for places Tailwind can't reach: SVG `fill`/`stroke`, inline `style`, and
// chart libraries that need raw hex strings. Per the design DoD, ALL #rrggbb
// literals in the web app live here — components import from this file rather
// than redefining their own.

import type { MissionState } from '../types'

// Derive the literal unions from the canonical MissionState interface (kind and
// status are inline unions there) so this file stays in lock-step with types.ts
// without that file having to export extra aliases.
type MissionKind = MissionState['kind']
type MissionStatus = MissionState['status']

/** Mission-kind marker colors. Values mirror the RGB-channel signal.* tokens
 *  where they overlap (fire=red, collapse_rescue=amber, medical_surge=cyan) and
 *  add a violet for infra_repair. Copied verbatim from the original TownMap map. */
export const MISSION_KIND_COLORS: Record<MissionKind, string> = {
  fire: '#ef4444',
  collapse_rescue: '#f59e0b',
  medical_surge: '#22d3ee',
  infra_repair: '#a78bfa',
}

/** Mission lifecycle status colors (open = active amber, resolved = green,
 *  failed = red). Used for status fills, chips, and legend swatches. */
export const STATUS_COLORS: Record<MissionStatus, string> = {
  open: '#f59e0b',
  resolved: '#4ade80',
  failed: '#ef4444',
}

/** Arm coding — fixed once, used everywhere. `society = cyan`, the comparison
 *  baseline (swarm/solo) `= amber`. Drives compare mode's "good vs baseline"
 *  read; never reassign per-component. */
export const ARM_COLORS = {
  society: '#22d3ee',
  baseline: '#f59e0b',
} as const

/** Fallback for an unknown mission kind / arm (matches text-eoc-secondary). */
export const FALLBACK_COLOR = '#94a3b8'
