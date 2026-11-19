import { expect, test } from '@playwright/test'

test.beforeEach(async ({ request }) => {
  const response = await request.post('/api/v1/dispatch/reset')
  expect(response.ok()).toBeTruthy()
})

test('run page shows the relay chain, ledger and step details', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/dispatch')
  await page.getByRole('button', { name: '运行 Agent 团队' }).first().click()

  await expect(page).toHaveURL(/\/dispatch\/runs\/run-/, { timeout: 15_000 })
  await expect(page.locator('[data-run-summary]')).toBeVisible({ timeout: 15_000 })
  await expect(page.locator('[data-run-header]')).toContainText('10')
  await expect(page.locator('[data-run-header]')).toContainText('8')
  await expect(page.locator('[data-chain-node]')).toHaveCount(10)
  await expect(page.locator('[data-handoff-link]')).toHaveCount(8)
  await expect(page.locator('[data-continuation-link]')).toHaveCount(1)
  await expect(page.locator('[data-handoff-row]')).toHaveCount(8)
  await expect(page.locator('[data-governance-chip]')).toHaveCount(5)

  await page.locator('[data-swimlane-step]').first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('工具调用')
  await expect(dialog.locator('[data-tool-call]')).toHaveCount(1)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})

test('run page can step through events and seek from the chain', async ({
  page,
  request,
}) => {
  const response = await request.post('/api/v1/dispatch/runs')
  const run = await response.json()

  await page.goto(`/dispatch/runs/${run.id}?autoplay=0`)
  await expect(page.locator('[data-run-header]')).toBeVisible()
  await expect(page.locator('.run-event-row')).toHaveCount(0)

  await page.locator('[data-player-next]').click()
  await expect(page.locator('.run-event-row')).toHaveCount(1)
  await page.locator('[data-player-prev]').click()
  await expect(page.locator('.run-event-row')).toHaveCount(0)

  await page.locator('[data-player-show-all]').click()
  await expect(page.locator('[data-run-summary]')).toBeVisible()

  await page.locator('[data-player-show-all]').click()
  await page.evaluate(() => window.scrollTo({ top: 0 }))
  await page.locator('[data-chain-node]').nth(4).click()
  await expect(page.locator('[data-run-event-stream]')).toContainText('第 5 步')

  await page.locator('[data-handoff-row]').first().click()
  const firstHandoffSeq = run.handoffs[0].event_seq as number
  await expect(page.locator(`.run-event-row[data-event-seq="${firstHandoffSeq}"]`)).toHaveClass(
    /run-event-row--active/,
  )
})

test('run page plays to completion at 4x', async ({ page, request }) => {
  const response = await request.post('/api/v1/dispatch/runs')
  const run = await response.json()

  await page.goto(`/dispatch/runs/${run.id}?speed=4`)
  await expect(page.locator('[data-run-summary]')).toBeVisible({ timeout: 20_000 })
})

test('run page remains usable at 375px without horizontal overflow', async ({
  page,
  request,
}) => {
  const response = await request.post('/api/v1/dispatch/runs')
  const run = await response.json()
  await page.setViewportSize({ width: 375, height: 812 })

  await page.goto(`/dispatch/runs/${run.id}?autoplay=0`)
  await expect(page.locator('[data-run-header]')).toBeVisible()
  await expect(page.locator('[data-player-toggle]')).toBeVisible()

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  )
  expect(overflow).toBe(false)
})

test('unknown run shows an explicit empty state', async ({ page }) => {
  await page.goto('/dispatch/runs/run-missing')

  await expect(page.getByText('这条运行记录不存在')).toBeVisible()
})
