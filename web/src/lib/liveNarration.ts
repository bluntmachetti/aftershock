import type { TickRecord, WorldState, Proposal } from '../types'
import type { ContentionResult } from './contention'

export type NarrationSeverity = 'nominal' | 'warning' | 'alert'

export interface Narration {
  text: string
  severity: NarrationSeverity
}

const EMPTY: Narration = { text: '', severity: 'nominal' }

function strField(body: Record<string, unknown> | undefined, key: string): string {
  const v = body?.[key]
  return typeof v === 'string' ? v : ''
}

function findInjectedEvent(tick: TickRecord): { kind: string; district: string } | null {
  for (const evt of tick.events) {
    if (evt.payload?.injected === true) {
      const kind = (evt.payload.inject_kind as string) ?? evt.kind
      const district = (evt.payload.district_id as string) ?? ''
      return { kind, district }
    }
  }
  return null
}

function findContentionNarration(
  tick: TickRecord,
  world: WorldState | null,
  contention: ContentionResult,
): Narration | null {
  if (contention.pairs.length === 0) return null

  const pair = contention.pairs[0]
  const resource = pair.resources[0] ?? 'resource'

  // Try to find the winning ruling for this resource
  const byId: Record<string, Proposal> = {}
  for (const resp of tick.responses) {
    for (const p of resp.proposals) byId[p.proposal_id] = p
  }

  let winnerRole = ''
  for (const ruling of tick.rulings) {
    if (ruling.decided_by !== 'kernel:auction' || !ruling.accepted) continue
    const p = byId[ruling.proposal_id]
    if (!p || p.kind !== 'resource_request') continue
    const r = strField(p.body, 'resource')
    if (r === resource) {
      winnerRole = p.sender
      break
    }
  }

  const panic = world ? Math.round(world.panic * 100) : 0
  const winnerClause = winnerRole ? `; auction resolved to ${winnerRole}` : ''
  return {
    text: `T${tick.tick} · contested — ${resource} in ${pair.loserDistrict.replace(/_/g, ' ')}${winnerClause}. Panic ${panic}%`,
    severity: 'warning',
  }
}

function findNotableRuling(
  tick: TickRecord,
): Narration | null {
  const byId: Record<string, Proposal> = {}
  for (const resp of tick.responses) {
    for (const p of resp.proposals) byId[p.proposal_id] = p
  }

  for (const ruling of tick.rulings) {
    if (ruling.decided_by !== 'kernel:auction') continue
    const p = byId[ruling.proposal_id]
    if (!p || p.kind !== 'resource_request') continue

    const sender = p.sender
    const body = p.body as { resource?: string; qty?: number; mission_id?: string }
    const resource = body.resource ?? 'resource'
    const qty = body.qty ?? '?'
    const mission = body.mission_id ?? '?'
    const verdict = ruling.accepted
      ? 'GRANTED'
      : `rejected: ${ruling.reason || 'no reason'}`

    return {
      text: `T${tick.tick} · ${sender} requested ${qty}× ${resource} for ${mission} — ${verdict}`,
      severity: ruling.accepted ? 'nominal' : 'warning',
    }
  }

  return null
}

function nominalFallback(tick: TickRecord, world: WorldState | null): Narration {
  const saved = world?.lives_saved ?? tick.scores['lives_saved'] ?? 0
  const panic = world ? Math.round(world.panic * 100) : Math.round((tick.scores['panic'] ?? 0) * 100)
  return {
    text: `T${tick.tick} · dispatching resources · ${saved} saved · panic ${panic}%`,
    severity: 'nominal',
  }
}

export function liveNarration(input: {
  tick: TickRecord | null
  world: WorldState | null
  contention: ContentionResult
  inject: { kind: string; district: string; tick: number } | null
  arm?: string | null
}): Narration {
  const { tick, world, contention, inject } = input

  // No tick yet
  if (!tick) return EMPTY

  // Priority 1: operator inject (pending marker)
  if (inject && inject.tick === -1) {
    return {
      text: `INJECTION · ${inject.kind.replace(/_/g, ' ')} in ${inject.district.replace(/_/g, ' ')} — agents re-evaluating priorities`,
      severity: 'alert',
    }
  }

  // Priority 2: injected event in the tick
  const injectedEvt = findInjectedEvent(tick)
  if (injectedEvt) {
    return {
      text: `INJECTION · ${injectedEvt.kind.replace(/_/g, ' ')} in ${injectedEvt.district.replace(/_/g, ' ')} — agents re-evaluating priorities`,
      severity: 'alert',
    }
  }

  // Priority 3: contention
  const contentionNarr = findContentionNarration(tick, world, contention)
  if (contentionNarr) return contentionNarr

  // Priority 4: notable ruling
  const rulingNarr = findNotableRuling(tick)
  if (rulingNarr) return rulingNarr

  // Priority 5: nominal fallback
  return nominalFallback(tick, world)
}
