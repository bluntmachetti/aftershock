import { test, expect } from '@playwright/test'

test.describe('Counterfactual controls', () => {
  test('What-if controls render after selecting two runs', async ({ page }) => {
    await page.goto('/?token=demo')
    await page.getByRole('button', { name: 'compare', exact: true }).click()

    await expect(page.getByText('Compare two arms')).toBeVisible({ timeout: 10000 })

    const leftHeading = page.getByText('LEFT', { exact: true })
    const rightHeading = page.getByText('RIGHT', { exact: true })
    await expect(leftHeading).toBeVisible()
    await expect(rightHeading).toBeVisible()

    const leftBtns = leftHeading.locator('..').locator('button')
    const rightBtns = rightHeading.locator('..').locator('button')

    await expect(leftBtns.first()).toBeVisible({ timeout: 10000 })
    await leftBtns.first().click()

    // The first RIGHT button is disabled (same run selected on LEFT), so click the second.
    const secondRight = rightBtns.nth(1)
    await expect(secondRight).toBeVisible()
    await expect(secondRight).toBeEnabled()
    await secondRight.click()

    await expect(page.getByText('What-if')).toBeVisible({ timeout: 10000 })
    // The default intervention is drop_protocol (the headline). Its Branch button
    // must be ENABLED — it exposes no target selector, and gating it on a target
    // left it permanently disabled (regression guard).
    const branch = page.getByRole('button', { name: 'Branch' })
    await expect(branch).toBeVisible()
    await expect(branch).toBeEnabled()
  })
})
