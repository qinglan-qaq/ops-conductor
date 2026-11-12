import { expect, test } from '@playwright/test'

test.beforeEach(async ({ request }) => {
  const response = await request.post('/api/v1/dispatch/reset')
  expect(response.ok()).toBeTruthy()
})

test('capture desktop and mobile screenshots for manual review', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/dispatch')
  await page.waitForTimeout(600)
  await page.screenshot({
    path: 'test-results/dispatch-1440.png',
    fullPage: true,
  })

  await page.goto('/dispatch/stages/order')
  await page.waitForTimeout(400)
  await page.screenshot({
    path: 'test-results/stage-order-1440.png',
    fullPage: true,
  })

  await page.goto('/dispatch/approvals')
  await page.waitForTimeout(300)
  await page.screenshot({
    path: 'test-results/approvals-1440.png',
    fullPage: true,
  })

  await page.goto('/dispatch/exceptions')
  await page.locator('[data-exception-id="ORD-01"]').click()
  await page.waitForTimeout(300)
  await page.screenshot({
    path: 'test-results/exception-drawer-1440.png',
    fullPage: false,
  })

  await page.goto('/dispatch/integrations')
  await page.waitForTimeout(300)
  await page.screenshot({
    path: 'test-results/integrations-1440.png',
    fullPage: true,
  })

  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/dispatch')
  await page.waitForTimeout(400)
  await page.screenshot({
    path: 'test-results/dispatch-375.png',
    fullPage: true,
  })

  await page.getByRole('button', { name: '打开场景目录' }).click()
  await page.waitForTimeout(300)
  await page.screenshot({
    path: 'test-results/catalog-375.png',
    fullPage: false,
  })

  await page.locator('[data-sidebar-group="order"] .stage-group-link').click()
  await page.waitForTimeout(500)
  await page.screenshot({
    path: 'test-results/stage-order-375.png',
    fullPage: true,
  })
})
