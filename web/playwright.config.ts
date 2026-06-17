import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:8788',
    headless: true,
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'cd .. && uv run aftershock serve --host 127.0.0.1 --port 8788 --runs-dir runs',
    port: 8788,
    reuseExistingServer: true,
    timeout: 15_000,
  },
})
