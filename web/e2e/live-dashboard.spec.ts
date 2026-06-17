import { test, expect } from '@playwright/test'

test.describe('Live Negotiation Dashboard (operator)', () => {
  test.beforeEach(async ({ page }) => {
    // ?token=… configures an operator session so the mutating controls render; these
    // tests assert the idle control surface. The public read-only view is covered below.
    await page.goto('/?token=demo')
    await page.getByRole('button', { name: 'live', exact: true }).click()
  })

  test('renders 3-panel layout', async ({ page }) => {
    // Left panel: controls
    await expect(page.getByText('Start Run')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Inject Event' })).toBeVisible()

    // Center: empty state
    await expect(page.getByText('Start a run to see the map')).toBeVisible()
    await expect(page.getByRole('button', { name: /Run Demo/i })).toBeVisible()

    // Right: negotiation feed
    await expect(page.getByText('Negotiation Feed')).toBeVisible()
    await expect(page.getByText('No rulings yet.')).toBeVisible()
  })

  test('inject controls disabled when not running', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Inject' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'fire' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'aftershock' })).toBeDisabled()
  })

  test('arm selection toggles correctly', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'scripted' })).toHaveClass(/font-semibold/)

    await page.getByRole('button', { name: 'society' }).click()
    await expect(page.getByRole('button', { name: 'society' })).toHaveClass(/font-semibold/)

    await page.getByRole('button', { name: 'swarm' }).click()
    await expect(page.getByRole('button', { name: 'swarm' })).toHaveClass(/font-semibold/)
  })

  test('Demo Mode sets preset values', async ({ page }) => {
    await page.getByRole('button', { name: 'Demo Mode' }).click()

    // scripted arm selected
    await expect(page.getByRole('button', { name: 'scripted' })).toHaveClass(/font-semibold/)
    // seed = 42
    const seedInput = page.locator('input[type="number"]').first()
    await expect(seedInput).toHaveValue('42')
    // ticks = 30
    const ticksInput = page.locator('input[type="number"]').nth(1)
    await expect(ticksInput).toHaveValue('30')
  })

  test('scenario select populated on mount', async ({ page }) => {
    const select = page.getByRole('combobox').first()
    await expect(select).toBeVisible()
    // Default option is SYNTHETIC QUAKE (empty value)
    await expect(select).toHaveValue('')
  })

  test('AAR and MEMORY toggle buttons exist', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'AAR' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'MEM' })).toBeVisible()
  })

  test('status shows IDLE when no run', async ({ page }) => {
    await expect(page.getByText('IDLE')).toBeVisible()
  })

  test('start button exists and is clickable', async ({ page }) => {
    const startBtn = page.getByRole('button', { name: 'Start' })
    await expect(startBtn).toBeVisible()
    await expect(startBtn).toBeEnabled()
  })
})

test.describe('Live read-only (public, no token)', () => {
  test('hides the operator controls and shows the read-only note', async ({ page }) => {
    // No ?token=: the public/judge view is read-only — the server-side ambient loop
    // keeps it alive; the browser only watches.
    await page.goto('/')
    await page.getByRole('button', { name: 'live', exact: true }).click()

    // The mutating controls are gone…
    await expect(page.getByText('Start Run')).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Inject Event' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Demo Mode' })).toHaveCount(0)
    // …replaced by the read-only note, and the watch panel remains.
    await expect(page.getByText(/Read-only view/i)).toBeVisible()
    await expect(page.getByText('Negotiation Feed')).toBeVisible()
  })
})

test.describe('Live onboarding — public', () => {
  test.beforeEach(async ({ page }) => {
    // Clear onboarding state so the banner always shows
    await page.goto('/')
    await page.evaluate(() => {
      localStorage.removeItem('aftershock-live-briefing-seen-v1-public')
    })
    await page.getByRole('button', { name: 'live', exact: true }).click()
  })

  test('briefing banner is visible with public copy', async ({ page }) => {
    await expect(page.getByText('SYSTEM BRIEFING')).toBeVisible()
    await expect(page.getByText(/typed auction protocol/)).toBeVisible()
    await expect(page.getByText(/WATCHER MODE/)).toBeVisible()
    // Public banner should NOT show the operator-specific line
    await expect(page.getByText(/Operator session/)).toHaveCount(0)
  })

  test('help button is visible', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Open help' })).toBeVisible()
  })

  test('banner dismiss persists across reload', async ({ page }) => {
    await page.getByRole('button', { name: 'Dismiss briefing' }).click()
    await expect(page.getByText('SYSTEM BRIEFING')).toHaveCount(0)

    // Reload and verify it stays dismissed
    await page.reload()
    await page.getByRole('button', { name: 'live', exact: true }).click()
    await expect(page.getByText('SYSTEM BRIEFING')).toHaveCount(0)
  })
})

test.describe('Live onboarding — operator', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/?token=demo')
    await page.evaluate(() => {
      localStorage.removeItem('aftershock-live-briefing-seen-v1-operator')
    })
    await page.getByRole('button', { name: 'live', exact: true }).click()
  })

  test('briefing banner shows operator-specific copy', async ({ page }) => {
    await expect(page.getByText('SYSTEM BRIEFING')).toBeVisible()
    await expect(page.getByText(/Operator session/)).toBeVisible()
  })
})
