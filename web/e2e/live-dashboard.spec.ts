import { test, expect } from '@playwright/test'

test.describe('Live Negotiation Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    // ?autostart=0 opens a static control view so these tests assert the idle
    // surface; the auto-start behavior is covered in its own describe block below.
    await page.goto('/?autostart=0')
    await page.getByRole('button', { name: 'live', exact: true }).click()
  })

  test('renders 3-panel layout', async ({ page }) => {
    // Left panel: controls
    await expect(page.getByText('Start Run')).toBeVisible()
    await expect(page.getByText('Inject Event')).toBeVisible()

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

test.describe('Live auto-start', () => {
  test('auto-starts a scripted stream on open and can be stopped', async ({ page }) => {
    // Default (no ?autostart=0): opening the Live tab begins a scripted run with no click.
    await page.goto('/')
    await page.getByRole('button', { name: 'live', exact: true }).click()

    // The status flips to RUNNING and a Stop (take-control) button appears.
    await expect(page.getByText(/RUNNING/)).toBeVisible()
    const stopBtn = page.getByRole('button', { name: 'Stop', exact: true })
    await expect(stopBtn).toBeVisible()

    // Taking manual control returns to idle with Start available again.
    await stopBtn.click()
    await expect(page.getByText('IDLE')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start' })).toBeVisible()
  })
})
