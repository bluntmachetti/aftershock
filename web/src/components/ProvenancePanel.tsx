import { useState } from 'react'
import type {
  ScenarioPack,
  ScenarioSource,
  ProvenanceLabel,
} from '../types'
import { PROVENANCE_COLORS, isRealProvenance } from '../lib/palette'

/**
 * ProvenancePanel — the `DATA`-chip deep dive (task #4, surface table
 * "Provenance" row).
 *
 * This is the *honesty receipts* surface. The always-visible summary of honesty
 * (the caveat line + the `REAL demand · REAL latency · INFERRED lives` inline
 * read) lives on the RealityStrip — NOT here. Behind the `DATA` chip we lay out,
 * verbatim and copyable, the full provenance the judges can audit:
 *
 *   - a monospaced source table (dataset · provider · license · fetched_at ·
 *     query URL) — the whole thing copyable to clipboard,
 *   - the mapping version + the published severity / lives / mission-kind rules
 *     VERBATIM,
 *   - `config_sha256` + `compiler_version` (the determinism fingerprint),
 *   - the one-line sampling provenance ("16 of 2212 incidents · stratified …
 *     seed 4636"),
 *   - the six field-provenance markers as a TWO-TIER badge grid (solid fill =
 *     REAL ground truth; ghost/dotted border = MAPPED / INFERRED / SYNTHETIC),
 *   - a footer of the upstream attribution line(s), verbatim.
 *
 * Colors are NEUTRAL only (the palette `PROVENANCE_COLORS` tokens) — never the
 * amber/cyan arm-color space, per delta 5. The badges are mono 9px.
 *
 * The panel does NOT fetch — the parent (App.tsx integration) passes the already
 * resolved full `ScenarioPack` (the documented ProvenancePanel data source in
 * types.ts). A synthetic run has no pack, so the parent simply does not mount
 * the panel; this component renders nothing when `pack` is null, so behavior is
 * unchanged with no scenario.
 */

// Fixed display order for the field-provenance grid — the six markers in the
// order they tell the data story (when it happened / where / what / how bad /
// who's at risk / what's blocked).
const PROVENANCE_FIELD_ORDER: Array<{
  key: keyof ScenarioPack['field_provenance']
  label: string
}> = [
  { key: 'tick', label: 'tick' },
  { key: 'district_id', label: 'district' },
  { key: 'mission_kind', label: 'mission kind' },
  { key: 'severity', label: 'severity' },
  { key: 'lives_at_risk', label: 'lives at risk' },
  { key: 'blockage', label: 'blockage' },
]

const PROVENANCE_TIER_LABEL: Record<ProvenanceLabel, string> = {
  real: 'REAL',
  mapped: 'MAPPED',
  inferred: 'INFERRED',
  synthetic: 'SYNTHETIC',
}

/** One field-provenance badge. Solid neutral fill for REAL (ground truth); a
 *  ghost/dotted border for MAPPED/INFERRED/SYNTHETIC so INFERRED never reads as
 *  an error. Mono 9px. All hex comes from the palette provenance tokens. */
function ProvenanceBadge({
  field,
  label,
}: {
  field: ProvenanceLabel
  label: string
}): JSX.Element {
  const c = PROVENANCE_COLORS[field]
  const solid = isRealProvenance(field)
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[10px] font-mono text-eoc-secondary lowercase tracking-wide">
        {label}
      </span>
      <span
        className="inline-flex items-center rounded-sm px-1.5 py-0.5 text-[9px] font-mono font-bold uppercase tracking-widest leading-none shrink-0"
        style={{
          color: c.text,
          background: c.fill,
          // Ghost tiers get a dotted border; REAL is a solid filled chip whose
          // border matches its fill (a clean raised pill, no outline noise).
          border: `1px ${solid ? 'solid' : 'dotted'} ${c.border}`,
        }}
        title={`${label}: ${PROVENANCE_TIER_LABEL[field]}`}
      >
        {PROVENANCE_TIER_LABEL[field]}
      </span>
    </div>
  )
}

/** A titled section block inside the panel. */
function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}): JSX.Element {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="text-[10px] font-mono uppercase tracking-widest text-eoc-faint">
        {title}
      </div>
      {children}
    </div>
  )
}

/** Build the copyable plaintext of the source table (TSV-ish, one row per
 *  dataset) so a judge can paste the exact provenance into a sheet/doc. */
function sourceTableText(sources: ScenarioSource[]): string {
  const header = ['dataset', 'provider', 'license', 'fetched_at', 'query_url'].join(
    '\t',
  )
  const rows = sources.map((s) =>
    [
      s.dataset ?? '',
      s.provider ?? '',
      s.license ?? '',
      s.fetched_at ?? '',
      s.query_url ?? '',
    ].join('\t'),
  )
  return [header, ...rows].join('\n')
}

/** Compose the one-line sampling provenance: "16 of 2212 incidents · stratified
 *  by (tick-bucket, mission_kind) · seed 4636". */
function samplingLine(sampling: ScenarioPack['sampling']): string {
  const parts = [
    `${sampling.kept} of ${sampling.total} incidents`,
    sampling.method,
    `seed ${sampling.sample_seed}`,
  ]
  return parts.join(' · ')
}

/** The DATA chip trigger. A neutral mono chip the integration owner mounts in
 *  the header; clicking it opens/closes the deep-dive panel. Disabled (and dim)
 *  when there is no pack, so a synthetic run shows an inert chip rather than a
 *  dead button. */
export function DataChip({
  active,
  onClick,
  disabled = false,
}: {
  active?: boolean
  onClick: () => void
  disabled?: boolean
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      aria-label="Open data provenance panel"
      data-testid="provenance-data-chip"
      className={[
        'inline-flex items-center gap-1.5 rounded-sm border px-2 py-1',
        'text-[10px] font-mono font-bold uppercase tracking-widest leading-none',
        'transition-colors',
        disabled
          ? 'border-eoc-border text-eoc-faint cursor-not-allowed opacity-60'
          : active
            ? 'border-eoc-secondary text-eoc-primary bg-eoc-raised'
            : 'border-eoc-border text-eoc-secondary hover:text-eoc-primary hover:border-eoc-secondary',
      ].join(' ')}
    >
      <span aria-hidden="true" className="text-eoc-faint">
        ⛁
      </span>
      DATA
    </button>
  )
}

interface ProvenancePanelProps {
  /** The full scenario pack (ProvenancePanel data source). Null for a synthetic
   *  run — the panel renders nothing, preserving no-scenario behavior. */
  pack: ScenarioPack | null | undefined
  /** Whether the panel is shown. */
  open: boolean
  /** Close handler (backdrop / ✕). */
  onClose: () => void
}

/**
 * The deep-dive panel itself. Renders only when `open` and a `pack` is present.
 * Floats as a right-anchored sheet over the app (the integration owner controls
 * mount position via the header chip), with its own scroll.
 */
export function ProvenancePanel({
  pack,
  open,
  onClose,
}: ProvenancePanelProps): JSX.Element {
  const [copied, setCopied] = useState(false)

  if (!open || !pack) return <></>

  async function copySources() {
    if (!pack) return
    try {
      await navigator.clipboard.writeText(sourceTableText(pack.source))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard blocked (insecure context / permissions) — no-op, the table
         is still on-screen and selectable. */
    }
  }

  const missionKindEntries = Object.entries(pack.mapping.mission_kind)

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label="Data provenance"
      data-testid="provenance-panel"
    >
      {/* Backdrop — click to dismiss. */}
      <div
        className="absolute inset-0 bg-eoc-ground/70 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Sheet */}
      <div className="relative z-10 h-full w-full max-w-[34rem] overflow-y-auto border-l border-eoc-border bg-eoc-surface shadow-2xl">
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-eoc-border bg-eoc-surface/95 px-4 py-3 backdrop-blur-sm">
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] font-mono uppercase tracking-widest text-eoc-faint">
              Data Provenance
            </span>
            <span className="text-xs font-mono font-bold text-eoc-primary leading-tight">
              {pack.name}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close data provenance panel"
            className="text-sm leading-none text-eoc-faint hover:text-eoc-primary transition-colors"
          >
            ✕
          </button>
        </div>

        <div className="flex flex-col gap-5 px-4 py-4">
          {/* ---- Source table (copyable) ---- */}
          <Section title="Sources">
            <div className="flex items-center justify-between gap-2 pb-0.5">
              <span className="text-[10px] font-mono text-eoc-secondary">
                {pack.source.length} dataset
                {pack.source.length === 1 ? '' : 's'}
              </span>
              <button
                type="button"
                onClick={copySources}
                data-testid="provenance-copy-sources"
                aria-label="Copy source table to clipboard"
                className="inline-flex items-center gap-1 rounded-sm border border-eoc-border px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-widest text-eoc-secondary hover:text-eoc-primary hover:border-eoc-secondary transition-colors"
              >
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
            <div className="flex flex-col gap-2">
              {pack.source.map((s, i) => (
                <div
                  key={s.dataset_id ?? `${s.dataset}-${i}`}
                  className="rounded-sm border border-eoc-border bg-eoc-ground px-2.5 py-2 font-mono"
                >
                  <div className="grid grid-cols-[5.5rem_1fr] gap-x-2 gap-y-1 text-[10px]">
                    <span className="text-eoc-faint uppercase tracking-wide">
                      dataset
                    </span>
                    <span className="text-eoc-primary break-words">
                      {s.dataset}
                      {s.dataset_id ? (
                        <span className="text-eoc-faint"> ({s.dataset_id})</span>
                      ) : null}
                    </span>

                    <span className="text-eoc-faint uppercase tracking-wide">
                      provider
                    </span>
                    <span className="text-eoc-secondary break-words">
                      {s.provider}
                    </span>

                    <span className="text-eoc-faint uppercase tracking-wide">
                      license
                    </span>
                    <span className="text-eoc-secondary break-words">
                      {s.license ?? '—'}
                      {s.license_url ? (
                        <>
                          {' '}
                          <a
                            href={s.license_url}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="text-eoc-secondary underline decoration-eoc-border hover:text-eoc-primary"
                          >
                            terms
                          </a>
                        </>
                      ) : null}
                    </span>

                    {s.fetched_at ? (
                      <>
                        <span className="text-eoc-faint uppercase tracking-wide">
                          fetched
                        </span>
                        <span className="text-eoc-secondary tabular-nums">
                          {s.fetched_at}
                          {typeof s.rows_fetched === 'number' ? (
                            <span className="text-eoc-faint">
                              {' '}
                              · {s.rows_fetched.toLocaleString()} rows
                            </span>
                          ) : null}
                        </span>
                      </>
                    ) : null}

                    {s.query_url ? (
                      <>
                        <span className="text-eoc-faint uppercase tracking-wide">
                          query
                        </span>
                        <a
                          href={s.query_url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="text-[9px] text-eoc-secondary underline decoration-eoc-border hover:text-eoc-primary break-all"
                          title={s.query_url}
                        >
                          {s.query_url}
                        </a>
                      </>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </Section>

          {/* ---- Field provenance grid (two-tier badges) ---- */}
          <Section title="Field provenance">
            <div className="grid grid-cols-2 gap-x-5 gap-y-1.5 rounded-sm border border-eoc-border bg-eoc-ground px-3 py-2.5">
              {PROVENANCE_FIELD_ORDER.map(({ key, label }) => (
                <ProvenanceBadge
                  key={key}
                  field={pack.field_provenance[key]}
                  label={label}
                />
              ))}
            </div>
          </Section>

          {/* ---- Mapping (version + rules verbatim) ---- */}
          <Section title={`Mapping · ${pack.mapping.version}`}>
            <div className="flex flex-col gap-2 rounded-sm border border-eoc-border bg-eoc-ground px-3 py-2.5">
              {missionKindEntries.length > 0 ? (
                <div className="flex flex-col gap-1">
                  <span className="text-[9px] font-mono uppercase tracking-widest text-eoc-faint">
                    mission kind
                  </span>
                  <div className="grid grid-cols-[1fr_auto] gap-x-2 gap-y-0.5">
                    {missionKindEntries.map(([from, to]) => (
                      <div key={from} className="contents">
                        <span className="text-[10px] font-mono text-eoc-secondary break-words">
                          {from}
                        </span>
                        <span className="text-[10px] font-mono text-eoc-primary whitespace-nowrap">
                          → {to}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {pack.mapping.severity_rule ? (
                <div className="flex flex-col gap-0.5">
                  <span className="text-[9px] font-mono uppercase tracking-widest text-eoc-faint">
                    severity rule
                  </span>
                  <span className="text-[10px] font-mono text-eoc-secondary leading-snug break-words">
                    {pack.mapping.severity_rule}
                  </span>
                </div>
              ) : null}

              {pack.mapping.lives_rule ? (
                <div className="flex flex-col gap-0.5">
                  <span className="text-[9px] font-mono uppercase tracking-widest text-eoc-faint">
                    lives rule
                  </span>
                  <span className="text-[10px] font-mono text-eoc-secondary leading-snug break-words">
                    {pack.mapping.lives_rule}
                  </span>
                </div>
              ) : null}
            </div>
          </Section>

          {/* ---- Sampling + determinism fingerprint ---- */}
          <Section title="Sampling & build">
            <div className="flex flex-col gap-1.5 rounded-sm border border-eoc-border bg-eoc-ground px-3 py-2.5 font-mono text-[10px]">
              <div className="text-eoc-secondary leading-snug break-words">
                {samplingLine(pack.sampling)}
              </div>
              {pack.sampling.filter ? (
                <div className="text-eoc-faint leading-snug break-words">
                  filter · {pack.sampling.filter}
                </div>
              ) : null}
              <div className="mt-1 grid grid-cols-[6.5rem_1fr] gap-x-2 gap-y-1 border-t border-eoc-border pt-1.5">
                <span className="text-eoc-faint uppercase tracking-wide">
                  compiler
                </span>
                <span className="text-eoc-secondary break-all">
                  {pack.compiler_version}
                </span>
                <span className="text-eoc-faint uppercase tracking-wide">
                  config sha256
                </span>
                <span className="text-eoc-secondary break-all">
                  {pack.config_sha256}
                </span>
                <span className="text-eoc-faint uppercase tracking-wide">
                  pack digest
                </span>
                <span className="text-eoc-secondary break-all">
                  {pack.pack_digest}
                </span>
              </div>
            </div>
          </Section>

          {/* ---- Footer: attribution line(s), verbatim ---- */}
          <Section title="Attribution">
            <div className="flex flex-col gap-1">
              {Array.from(
                new Set(
                  pack.source
                    .map((s) => s.attribution)
                    .filter((a): a is string => Boolean(a)),
                ),
              ).map((attribution) => (
                <p
                  key={attribution}
                  className="text-[10px] font-mono text-eoc-secondary leading-snug break-words"
                >
                  {attribution}
                </p>
              ))}
            </div>
          </Section>
        </div>
      </div>
    </div>
  )
}
