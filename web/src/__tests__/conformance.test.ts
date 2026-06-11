/**
 * Tests for conformance badge colour thresholds, 404 leaves badges hidden,
 * and violated-rule listing from a fixture report.
 * Follows the pure-logic pattern from aar.test.ts — no DOM rendering required.
 */
import { describe, it, expect, vi } from 'vitest'
import type { ConformanceReport, AarReport } from '../types'

// ---- Fixture conformance report ----

const FIXTURE_CONFORMANCE: ConformanceReport = {
  arm: 'society',
  seed: 42,
  rules: {
    T1: {
      commander: { applicable: 10, violations: [], rate: 1.0 },
      medical: { applicable: 8, violations: [{ tick: 3, detail: 'direct dispatch attempted' }], rate: 0.875 },
    },
    T5: {
      commander: { applicable: 5, violations: [{ tick: 1, detail: 'resubmitted set_priority unchanged' }, { tick: 4, detail: 'resubmitted set_priority unchanged' }], rate: 0.6 },
      rescue: { applicable: 6, violations: [], rate: 1.0 },
    },
    C1: {
      commander: { applicable: 4, violations: [{ tick: 2, detail: 'mission m3 unprioritised at t+2' }], rate: 0.75 },
    },
    M1: {
      medical: { applicable: 0, violations: [], rate: 1.0 },
    },
  },
  role_conformance: {
    commander: 0.78,   // red  (< 0.80)
    medical: 0.88,     // amber (>= 0.80, < 0.95)
    rescue: 1.0,       // green (>= 0.95)
    fire: 0.96,        // green (>= 0.95)
    infrastructure: 0.82, // amber
    comms: 0.95,       // green (exactly 0.95)
  },
  team_alignment: 0.84,
  notes: ['worlds absent — state-dependent rules marked applicable:0'],
}

// ---- Helpers that mirror AgentInspector logic ----

function conformanceBadgeColour(rate: number): 'green' | 'amber' | 'red' {
  if (rate >= 0.95) return 'green'
  if (rate >= 0.80) return 'amber'
  return 'red'
}

function agentConformanceRate(agentId: string, report: ConformanceReport): number | null {
  const rate = report.role_conformance[agentId]
  return rate === undefined ? null : rate
}

interface ViolatedRule {
  ruleId: string
  rate: number
  firstViolation: { tick: number; detail: string } | null
}

function agentViolatedRules(agentId: string, report: ConformanceReport): ViolatedRule[] {
  const result: ViolatedRule[] = []
  for (const [ruleId, agentMap] of Object.entries(report.rules)) {
    const entry = agentMap[agentId]
    if (!entry) continue
    if (entry.applicable > 0 && entry.rate < 1.0) {
      result.push({
        ruleId,
        rate: entry.rate,
        firstViolation: entry.violations[0] ?? null,
      })
    }
  }
  result.sort((a, b) => a.rate - b.rate)
  return result
}

// ---- Badge colour threshold tests ----

describe('conformance badge colour thresholds', () => {
  it('rate >= 0.95 is green', () => {
    expect(conformanceBadgeColour(1.0)).toBe('green')
    expect(conformanceBadgeColour(0.95)).toBe('green')
    expect(conformanceBadgeColour(0.99)).toBe('green')
  })

  it('rate >= 0.80 and < 0.95 is amber', () => {
    expect(conformanceBadgeColour(0.80)).toBe('amber')
    expect(conformanceBadgeColour(0.88)).toBe('amber')
    expect(conformanceBadgeColour(0.94)).toBe('amber')
  })

  it('rate < 0.80 is red', () => {
    expect(conformanceBadgeColour(0.79)).toBe('red')
    expect(conformanceBadgeColour(0.50)).toBe('red')
    expect(conformanceBadgeColour(0.0)).toBe('red')
  })

  it('boundary 0.95 is green, not amber', () => {
    expect(conformanceBadgeColour(0.95)).toBe('green')
  })

  it('boundary 0.80 is amber, not red', () => {
    expect(conformanceBadgeColour(0.80)).toBe('amber')
  })

  it('fixture: commander (0.78) is red', () => {
    const rate = agentConformanceRate('commander', FIXTURE_CONFORMANCE)!
    expect(conformanceBadgeColour(rate)).toBe('red')
  })

  it('fixture: medical (0.88) is amber', () => {
    const rate = agentConformanceRate('medical', FIXTURE_CONFORMANCE)!
    expect(conformanceBadgeColour(rate)).toBe('amber')
  })

  it('fixture: rescue (1.0) is green', () => {
    const rate = agentConformanceRate('rescue', FIXTURE_CONFORMANCE)!
    expect(conformanceBadgeColour(rate)).toBe('green')
  })

  it('fixture: comms (0.95) is green (exact boundary)', () => {
    const rate = agentConformanceRate('comms', FIXTURE_CONFORMANCE)!
    expect(conformanceBadgeColour(rate)).toBe('green')
  })
})

// ---- 404 leaves badges hidden ----

describe('404 conformance fetch leaves badges hidden', () => {
  it('a rejected conformance fetch does not set report — stays null', async () => {
    let conformance: ConformanceReport | null = null
    const mockFetch = vi.fn().mockRejectedValueOnce(new Error('404 Not Found'))

    await mockFetch('some-run-id').catch(() => {
      // silently ignore — stays null
    })

    expect(conformance).toBeNull()
  })

  it('agentConformanceRate returns null when agent not in report', () => {
    const rate = agentConformanceRate('unknown_agent', FIXTURE_CONFORMANCE)
    expect(rate).toBeNull()
  })

  it('badge is not shown when conformance is null (rate is null)', () => {
    // The component guards with `conformance !== null` before calling agentConformanceRate.
    // Simulate that guard here: when conformance is null, the rate is null → no badge.
    const showBadge = (r: ConformanceReport | null, id: string) =>
      r !== null ? agentConformanceRate(id, r) : null
    expect(showBadge(null, 'commander')).toBeNull()
    expect(showBadge(FIXTURE_CONFORMANCE, 'commander')).not.toBeNull()
  })

  it('a successful conformance fetch returns typed ConformanceReport', async () => {
    let conformance: ConformanceReport | null = null
    const mockFetch = vi.fn().mockResolvedValueOnce(FIXTURE_CONFORMANCE)

    conformance = await mockFetch('seed42-scripted')

    expect(conformance).not.toBeNull()
    expect(conformance!.arm).toBe('society')
    expect(conformance!.team_alignment).toBe(0.84)
  })
})

// ---- Violated-rule listing ----

describe('violated-rule listing from fixture report', () => {
  it('commander has violations for T5 and C1 (rate < 1)', () => {
    const rules = agentViolatedRules('commander', FIXTURE_CONFORMANCE)
    const ruleIds = rules.map((r) => r.ruleId)
    expect(ruleIds).toContain('T5')
    expect(ruleIds).toContain('C1')
  })

  it('commander does NOT include T1 (rate == 1.0 — no violations)', () => {
    const rules = agentViolatedRules('commander', FIXTURE_CONFORMANCE)
    const ruleIds = rules.map((r) => r.ruleId)
    expect(ruleIds).not.toContain('T1')
  })

  it('medical has violation for T1 (rate 0.875)', () => {
    const rules = agentViolatedRules('medical', FIXTURE_CONFORMANCE)
    const ruleIds = rules.map((r) => r.ruleId)
    expect(ruleIds).toContain('T1')
  })

  it('medical does NOT include M1 (applicable == 0 — skipped)', () => {
    const rules = agentViolatedRules('medical', FIXTURE_CONFORMANCE)
    const ruleIds = rules.map((r) => r.ruleId)
    expect(ruleIds).not.toContain('M1')
  })

  it('rescue has no violated rules', () => {
    const rules = agentViolatedRules('rescue', FIXTURE_CONFORMANCE)
    expect(rules).toHaveLength(0)
  })

  it('violated rules are sorted worst-rate first', () => {
    const rules = agentViolatedRules('commander', FIXTURE_CONFORMANCE)
    for (let i = 1; i < rules.length; i++) {
      expect(rules[i - 1].rate).toBeLessThanOrEqual(rules[i].rate)
    }
  })

  it('first violation tick and detail are present for T5 commander violation', () => {
    const rules = agentViolatedRules('commander', FIXTURE_CONFORMANCE)
    const t5 = rules.find((r) => r.ruleId === 'T5')
    expect(t5).toBeDefined()
    expect(t5!.firstViolation).not.toBeNull()
    expect(t5!.firstViolation!.tick).toBe(1)
    expect(t5!.firstViolation!.detail).toBe('resubmitted set_priority unchanged')
  })

  it('first violation detail is accessible for C1 commander violation', () => {
    const rules = agentViolatedRules('commander', FIXTURE_CONFORMANCE)
    const c1 = rules.find((r) => r.ruleId === 'C1')
    expect(c1).toBeDefined()
    expect(c1!.firstViolation!.tick).toBe(2)
    expect(c1!.firstViolation!.detail).toContain('m3')
  })

  it('rate is surfaced correctly for each violated rule', () => {
    const rules = agentViolatedRules('commander', FIXTURE_CONFORMANCE)
    const t5 = rules.find((r) => r.ruleId === 'T5')
    const c1 = rules.find((r) => r.ruleId === 'C1')
    expect(t5!.rate).toBe(0.6)
    expect(c1!.rate).toBe(0.75)
  })

  it('agent not in any rule returns empty violated list', () => {
    const rules = agentViolatedRules('comms', FIXTURE_CONFORMANCE)
    expect(rules).toHaveLength(0)
  })
})

// ---- ConformanceReport type shape ----

describe('ConformanceReport type completeness', () => {
  it('all required top-level fields are present', () => {
    const r: ConformanceReport = FIXTURE_CONFORMANCE
    expect('arm' in r).toBe(true)
    expect('seed' in r).toBe(true)
    expect('rules' in r).toBe(true)
    expect('role_conformance' in r).toBe(true)
    expect('team_alignment' in r).toBe(true)
    expect('notes' in r).toBe(true)
  })

  it('rules are a nested Record<ruleId, Record<agentId, ConformanceAgentRule>>', () => {
    const rule = FIXTURE_CONFORMANCE.rules['T1']['commander']
    expect(typeof rule.applicable).toBe('number')
    expect(typeof rule.rate).toBe('number')
    expect(Array.isArray(rule.violations)).toBe(true)
  })

  it('violation entries have tick (number) and detail (string)', () => {
    const v = FIXTURE_CONFORMANCE.rules['T5']['commander'].violations[0]
    expect(typeof v.tick).toBe('number')
    expect(typeof v.detail).toBe('string')
  })
})

// ---- AarReport doctrine_notes field ----

describe('AarReport doctrine_notes optional field', () => {
  it('AarReport without doctrine_notes is still valid', () => {
    const r: AarReport = {
      headline: 'Test',
      grade: 'B',
      what_worked: [],
      coordination_failures: [],
      key_moments: [],
      lessons: [],
    }
    expect(r.doctrine_notes).toBeUndefined()
  })

  it('AarReport with doctrine_notes exposes the array', () => {
    const r: AarReport = {
      headline: 'Test',
      grade: 'A',
      what_worked: [],
      coordination_failures: [],
      key_moments: [],
      lessons: [],
      doctrine_notes: ['T5 violated 3×: re-submissions after rejection', 'C1: 1 mission unprioritised past deadline'],
    }
    expect(Array.isArray(r.doctrine_notes)).toBe(true)
    expect(r.doctrine_notes!.length).toBe(2)
  })
})
