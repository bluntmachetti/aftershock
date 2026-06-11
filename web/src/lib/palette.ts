// Single source of truth for JS/SVG colors (hex literals) shared across
// TownMap / BenchTab / RunPicker / LiveTab / AgentInspector / CompareTab.
//
// DOM/Tailwind surfaces use the semantic `eoc.*` / `signal.*` / `text-eoc-*`
// token classes (backed by the RGB-channel vars in index.css). This module is
// for places Tailwind can't reach: SVG `fill`/`stroke`, inline `style`, and
// chart libraries that need raw hex strings. Per the design DoD, ALL #rrggbb
// literals in the web app live here — components import from this file rather
// than redefining their own.

import type { MissionState, ProvenanceLabel } from '../types'

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

// ---------------------------------------------------------------------------
// Scenario packs (task #4) — hazard accents + two-tier provenance badges.
// ---------------------------------------------------------------------------

/** Hazard accent map (delta 7): a REAL/dispatch hazard gets a signal accent so
 *  the hazard chip reads as ground-truth; the synthetic placeholder is a DIM,
 *  neutral token (matches text-eoc-faint, never a signal color). The chip is the
 *  one place a scenario surface carries a signal accent — provenance badges stay
 *  neutral (see PROVENANCE_COLORS).
 *
 *  Real hazard labels come from the pack's free `hazard` field
 *  (earthquake|hurricane_flood|storm|routine|...); `synthetic` is the sentinel
 *  the UI uses for a run with no scenario (SYN·QUAKE). Unknown real hazards fall
 *  back to HAZARD_REAL_ACCENT via `hazardAccent`. */
export const HAZARD_COLORS = {
  /** Signal accent shared by every REAL hazard chip (steel-cyan-leaning green is
   *  intentionally NOT used; we reuse the established green signal so "real data"
   *  reads as a confirmed/verified accent, distinct from amber baseline and cyan
   *  society arm colors). */
  earthquake: '#4ade80',
  hurricane_flood: '#4ade80',
  storm: '#4ade80',
  routine: '#4ade80',
  /** The synthetic sentinel — dim/neutral, no signal. Matches --text-eoc-faint. */
  synthetic: '#475569',
} as const

/** Accent for any REAL hazard chip (the signal-green "verified data" accent). */
export const HAZARD_REAL_ACCENT = '#4ade80'

/** Dim/neutral accent for the synthetic (no-scenario) hazard chip. */
export const HAZARD_SYNTHETIC_ACCENT = '#475569'

/** Resolve a hazard label to its chip accent. A null/absent hazard (synthetic
 *  run) returns the dim token; a known hazard returns its mapped accent; an
 *  unknown-but-present (real) hazard returns the shared real accent — never the
 *  synthetic dim, so a new real pack still reads as ground truth. */
export function hazardAccent(hazard: string | null | undefined): string {
  if (!hazard || hazard === 'synthetic') return HAZARD_SYNTHETIC_ACCENT
  return (
    (HAZARD_COLORS as Record<string, string>)[hazard] ?? HAZARD_REAL_ACCENT
  )
}

/** Two-tier provenance badge styling (delta 5). NEUTRAL colors only — these must
 *  NOT reuse ARM_COLORS.society (#22d3ee cyan) or ARM_COLORS.baseline (#f59e0b
 *  amber), because RealityStrip pairs grey-real vs arm-color-agent and any reuse
 *  would collide on that very strip.
 *
 *  Tier 1 (REAL): solid fill — ground truth, the strongest neutral.
 *  Tier 2 (MAPPED/INFERRED/SYNTHETIC): ghost/dotted border, no fill — so
 *  `INFERRED` never reads as an error. `border` is the stroke/outline color,
 *  `fill` the (transparent for ghosts) background, `text` the label color. */
export const PROVENANCE_COLORS: Record<
  ProvenanceLabel,
  { border: string; fill: string; text: string }
> = {
  // Solid neutral fill — bright text on the raised neutral chip.
  real: { border: '#94a3b8', fill: '#94a3b8', text: '#0a0e1a' },
  // Ghost/dotted borders, transparent fill, neutral text. Distinct dimness per
  // tier (mapped slightly brighter than inferred/synthetic) but all neutral.
  mapped: { border: '#94a3b8', fill: 'transparent', text: '#94a3b8' },
  inferred: { border: '#475569', fill: 'transparent', text: '#94a3b8' },
  synthetic: { border: '#475569', fill: 'transparent', text: '#475569' },
} as const

/** Whether a provenance tier is the solid-fill REAL tier (vs a ghost border). */
export function isRealProvenance(label: ProvenanceLabel): boolean {
  return label === 'real'
}
