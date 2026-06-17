import type {
  RunSummary,
  RunDetail,
  TicksResponse,
  BenchResult,
  LiveStatus,
  AarReport,
  ConformanceReport,
  ScenarioSummary,
  ScenarioPack,
} from '../types'

const TOKEN_KEY = 'observatory-token'

// Token for deployments that set OBSERVATORY_TOKEN on the server. Accepted once
// via ?token=... (then scrubbed from the address bar so it never shows in
// recordings), persisted to localStorage for the session's mutating calls.
function resolveToken(): string | null {
  const params = new URLSearchParams(window.location.search)
  const fromUrl = params.get('token')
  if (fromUrl) {
    localStorage.setItem(TOKEN_KEY, fromUrl)
    params.delete('token')
    const query = params.toString()
    window.history.replaceState(
      null,
      '',
      window.location.pathname + (query ? `?${query}` : ''),
    )
    return fromUrl
  }
  return localStorage.getItem(TOKEN_KEY)
}

function authHeaders(): Record<string, string> {
  const token = resolveToken()
  return token ? { 'X-Observatory-Token': token } : {}
}

// Consume ?token= eagerly at app load — not lazily on the first mutating call —
// so the secret never lingers in the address bar (or in a screen recording).
resolveToken()

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${text}`)
  }
  return res.json() as Promise<T>
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${text}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  runs: (): Promise<RunSummary[]> => get('/api/runs'),

  run: (runId: string): Promise<RunSummary> => get(`/api/runs/${runId}`),

  // Full run detail — the truthful /api/runs/{id} shape (manifest, n_ticks,
  // has_world, and the scenario manifest block or null). Use this when a
  // component needs the scenario block (provenance / RealityStrip); `run`
  // remains for the legacy summary-shaped reads.
  runDetail: (runId: string): Promise<RunDetail> => get(`/api/runs/${runId}`),

  ticks: (
    runId: string,
    start = 0,
    limit = 50,
  ): Promise<TicksResponse> =>
    get(`/api/runs/${runId}/ticks?start=${start}&limit=${limit}`),

  bench: (): Promise<BenchResult[]> => get('/api/bench'),

  liveStatus: (): Promise<LiveStatus> => get('/api/live'),

  // True when an operator token is configured (via ?token=… or stored). Gates the
  // mutating controls in the UI; the server still enforces the gate independently.
  hasToken: (): boolean => !!localStorage.getItem(TOKEN_KEY),

  aar: (runId: string): Promise<AarReport> => get(`/api/runs/${runId}/aar`),

  conformance: (runId: string): Promise<ConformanceReport> =>
    get(`/api/runs/${runId}/conformance`),

  // Scenario packs (task #4). Both GETs are ungated, like every other GET.
  getScenarios: (): Promise<ScenarioSummary[]> => get('/api/scenarios'),

  getScenario: (scenarioId: string): Promise<ScenarioPack> =>
    get(`/api/scenarios/${scenarioId}`),

  // `ticks` is optional so the server applies the scenario budget default
  // (min(last timeline tick + 20, 120)) when a scenario is selected and no
  // explicit tick count is given. Passing `scenario` builds the world from the
  // committed pack; omitting it preserves the synthetic behavior exactly.
  startLive: (
    arm: string,
    seed: number,
    ticks?: number,
    opts?: { aar?: boolean; memory?: boolean; scenario?: string },
  ): Promise<{ live_id: string }> =>
    post('/api/live', {
      arm,
      seed,
      ...(ticks !== undefined ? { ticks } : {}),
      ...(opts ?? {}),
    }),

  injectEvent: (kind: string, district: string): Promise<void> =>
    post('/api/live/inject', { kind, district }),

  // Cancel the in-progress live run (idempotent) so the operator can take manual
  // control — e.g. interrupt the auto-started scripted demo to start a real run.
  stopLive: (): Promise<{ ok: boolean; running: boolean }> =>
    post('/api/live/stop', {}),

  // Counterfactual branch: re-run a seed with one intervention at tick N, streaming
  // over the same /ws/live channel. The branch lands in runs/ under a distinct run_id
  // and is replayable by Compare against its baseline.
  counterfactual: (
    body: {
      arm: string
      seed: number
      ticks: number
      atTick: number
      kind: string
      target?: string
      params?: Record<string, unknown>
      baselineRunId?: string
    },
  ): Promise<{ live_id: string }> =>
    post('/api/counterfactual', {
      arm: body.arm,
      seed: body.seed,
      ticks: body.ticks,
      at_tick: body.atTick,
      kind: body.kind,
      target: body.target ?? '',
      params: body.params ?? {},
      baseline_run_id: body.baselineRunId ?? null,
    }),
}
