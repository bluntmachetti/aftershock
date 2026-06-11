import type {
  RunSummary,
  TicksResponse,
  BenchResult,
  LiveStatus,
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

  ticks: (
    runId: string,
    start = 0,
    limit = 50,
  ): Promise<TicksResponse> =>
    get(`/api/runs/${runId}/ticks?start=${start}&limit=${limit}`),

  bench: (): Promise<BenchResult[]> => get('/api/bench'),

  liveStatus: (): Promise<LiveStatus> => get('/api/live'),

  startLive: (arm: string, seed: number, ticks: number): Promise<{ live_id: string }> =>
    post('/api/live', { arm, seed, ticks }),

  injectEvent: (kind: string, district: string): Promise<void> =>
    post('/api/live/inject', { kind, district }),
}
