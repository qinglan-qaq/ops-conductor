import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 375, height: 812 } })

test.beforeEach(async ({ request }) => {
  const response = await request.post('/api/v1/dispatch/reset')
  expect(response.ok()).toBeTruthy()
})

test('mobile has no horizontal overflow and the catalog is a drawer', async ({
  page,
}) => {
  await page.goto('/dispatch')
  await expect(page.getByText('后端已连接')).toBeVisible()

  const widths = await page.evaluate(() => ({
    inner: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }))
  expect(widths.inner).toBe(375)
  expect(widths.document).toBe(375)
  expect(widths.body).toBe(375)

  await page.getByRole('button', { name: '打开场景目录' }).click()
  await expect(page.locator('.app-sidebar')).toHaveClass(/is-open/)

  await page.locator('[data-sidebar-group="order"] .stage-group-link').click()
  await expect(page).toHaveURL(/\/dispatch\/stages\/order$/)
  await expect(page.locator('.app-sidebar')).not.toHaveClass(/is-open/)
  await expect(page.locator('[data-stage-result]')).toContainText('分类 6 单异常')
})
