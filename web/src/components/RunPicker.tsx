import type { RunSummary, ScenarioCompact } from '../types'
import { ARM_COLORS, HAZARD_SYNTHETIC_ACCENT, hazardAccent } from '../lib/palette'

// Canonical arm coding (palette.ts): society = cyan, every baseline
// (scripted/solo/swarm) = amber. Matches COMPARE's "good vs baseline" read —
// never redefined per component.
function armColor(arm: string): string {
  return arm === 'society' ? ARM_COLORS.society : ARM_COLORS.baseline
}

// Hazard chip (UX delta #7). RunPicker rows must stay compact, so the chip is
// DIM here — the strong, signal-accented hazard chip lives in run/side HEADERS
// (owned by the integrator), never stamped at equal weight on every list row.
//
//   no scenario (synthetic run) -> `SYN·QUAKE`  (dim/neutral sentinel)
//   real scenario pack          -> `REAL·IDA NYC` (signal accent from palette)
//
// `accent` always comes from palette: dim synthetic token for SYN, the hazard
// accent (signal) for a real pack. Even though the row keeps the chip visually
// restrained, the accent token still encodes REAL-vs-SYN truthfully.
interface HazardChip {
  label: string
  accent: string
  real: boolean
}

// Build a short, uppercase tail from a scenario id: drop a trailing 4-digit
// year token and join the remaining hyphen tokens with spaces (`nyc-ida-2021`
// -> `NYC IDA`). Falls back to the raw uppercased id when nothing remains.
function shortScenarioTail(id: string): string {
  const tokens = id
    .split('-')
    .filter((t) => t.length > 0 && !/^\d{4}$/.test(t))
  const base = tokens.length > 0 ? tokens : id.split('-').filter(Boolean)
  return base.join(' ').toUpperCase()
}

function hazardChipFor(scenario: ScenarioCompact | null | undefined): HazardChip {
  // Absent/null scenario => synthetic run: dim SYN·QUAKE sentinel.
  if (!scenario) {
    return { label: 'SYN·QUAKE', accent: HAZARD_SYNTHETIC_ACCENT, real: false }
  }
  return {
    label: `REAL·${shortScenarioTail(scenario.id)}`,
    accent: hazardAccent(scenario.hazard),
    real: true,
  }
}

interface Props {
  runs: RunSummary[]
  selectedRunId: string | null
  error: string | null
  loading: boolean
  // True while the run LIST is still being fetched (distinct from `loading`, which is
  // the per-run tick load). Without it the picker shows "No runs found" mid-fetch.
  runsLoading?: boolean
  onSelect: (run: RunSummary) => void
  // Re-fetch the run list and load the flagship demo run. Powers the empty/error-state
  // CTA so a judge always has a one-click path to recorded data.
  onLoadDemo?: () => void
}

// Shared CTA so the empty + error states both offer a one-click path to the demo.
function LoadDemoButton({ onLoadDemo, label }: { onLoadDemo?: () => void; label: string }) {
  if (!onLoadDemo) return null
  return (
    <button
      onClick={onLoadDemo}
      className="mt-2 px-2.5 py-1 rounded text-[11px] font-mono uppercase tracking-wider font-semibold text-eoc-ground bg-signal-amber hover:opacity-90 transition-opacity"
    >
      {label}
    </button>
  )
}

export function RunPicker({
  runs,
  selectedRunId,
  error,
  loading,
  runsLoading,
  onSelect,
  onLoadDemo,
}: Props) {
  if (error) {
    return (
      <div className="p-3 flex flex-col items-start text-[11px] font-mono text-signal-red border border-signal-red/30 rounded-lg bg-signal-red/10">
        <span>Error loading runs: {error}</span>
        <LoadDemoButton onLoadDemo={onLoadDemo} label="Retry" />
      </div>
    )
  }

  // List still loading (first fetch) — show a quiet pulse, not the empty state.
  if (runsLoading && runs.length === 0) {
    return (
      <div className="p-3 text-[11px] font-mono text-eoc-secondary animate-pulse">
        Loading runs…
      </div>
    )
  }

  if (runs.length === 0) {
    return (
      <div className="p-3 flex flex-col items-start text-[11px] font-mono text-eoc-secondary">
        <span>
          No runs found. Run <code className="text-signal-amber">aftershock run --seed 42</code> to create one,
        </span>
        <span>or load a recorded demo run:</span>
        <LoadDemoButton onLoadDemo={onLoadDemo} label="Load demo" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1 flex-1 min-h-0">
      <h3 className="shrink-0 text-[10px] font-mono uppercase tracking-widest text-eoc-secondary mb-1">
        Recorded Runs
        <span className="ml-1 text-eoc-faint tabular-nums">({runs.length})</span>
      </h3>
      <div className="flex flex-col gap-1 overflow-y-auto flex-1 min-h-0 pr-1">
        {runs.map((run) => {
          const color = armColor(run.arm)
          const selected = selectedRunId === run.run_id
          const chip = hazardChipFor(run.scenario)
          return (
            <button
              key={run.run_id}
              onClick={() => onSelect(run)}
              disabled={loading}
              className="flex items-center gap-2 px-2 py-1.5 rounded text-left transition-colors disabled:opacity-50 border border-eoc-border"
              style={{
                background: selected ? `${color}15` : 'transparent',
                borderColor: selected ? color : undefined,
              }}
            >
              <span
                className="text-[10px] font-mono uppercase tracking-wider shrink-0 px-1.5 py-0.5 rounded font-semibold"
                style={{ color, background: `${color}1a` }}
              >
                {run.arm}
              </span>
              <span
                className="text-[9px] font-mono uppercase tracking-wider shrink-0 px-1 py-0.5 rounded border tabular-nums"
                style={{
                  color: chip.accent,
                  borderColor: `${chip.accent}${chip.real ? '66' : '40'}`,
                  background: `${chip.accent}14`,
                }}
                title={
                  chip.real
                    ? `Real scenario: ${run.scenario?.name ?? run.scenario?.id ?? ''}`
                    : 'Synthetic run (no scenario pack)'
                }
              >
                {chip.label}
              </span>
              <span className="text-[11px] font-mono text-eoc-primary flex-1 truncate">
                {run.run_id}
              </span>
              <span className="text-[10px] font-mono tabular-nums text-eoc-secondary shrink-0">
                s{run.seed} / {run.ticks}t
              </span>
              {!run.has_world && (
                <span className="text-[10px] font-mono text-eoc-secondary shrink-0 px-1 py-0.5 rounded bg-eoc-raised">
                  no-world
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
