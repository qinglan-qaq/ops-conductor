import { expect, test } from '@playwright/test'

test.beforeEach(async ({ request }) => {
  const response = await request.post('/api/v1/dispatch/reset')
  expect(response.ok()).toBeTruthy()
})

test('overview shows backend status, scenario catalog and status board', async ({
  page,
}) => {
  await page.goto('/dispatch')

  await expect(page.getByText('后端已连接')).toBeVisible()
  await expect(page.locator('[data-sidebar-group]')).toHaveCount(11)
  await expect(page.locator('[data-approval-progress]')).toContainText('0/3 已批')
  await expect(page.locator('[data-chain-stage]')).toHaveCount(10)
  await expect(page.locator('[data-agent-id]')).toHaveCount(8)
  await expect(page.getByText('NestWell Home US').first()).toBeVisible()

  await expect(page.locator('[data-insight-board]')).toBeVisible()
  await expect(page.locator('[data-sales-point]')).toHaveCount(7)
  await expect(page.locator('[data-agent-usage]')).toHaveCount(8)
  await expect(page.locator('[data-result-stage]')).toHaveCount(10)
  await expect(page.locator('[data-sales-chart]')).toContainText('$99,600')
})

test('insight charts filter agents and open stage results', async ({ page }) => {
  await page.goto('/dispatch')

  await page.locator('[data-agent-usage="order"]').click()
  await expect(page.getByText('已筛选 order')).toBeVisible()

  await page.locator('[data-result-stage="order"]').click()
  await expect(page).toHaveURL(/\/dispatch\/stages\/order$/)
  await expect(page.locator('[data-stage-result]')).toContainText('分类 6 单异常')
})

test('order stage shows agent result, artifacts and source', async ({ page }) => {
  await page.goto('/dispatch')
  await page.locator('[data-sidebar-group="order"] .stage-group-link').click()

  await expect(page).toHaveURL(/\/dispatch\/stages\/order$/)
  await expect(page.locator('[data-stage-result]')).toContainText('分类 6 单异常')
  await expect(page.locator('[data-stage-result]')).toContainText(
    'order-exceptions.csv',
  )
  await expect(page.locator('[data-stage-result]')).toContainText(
    'MockPlatformAdapter',
  )
  await expect(page.locator('[data-stage-result]')).toContainText('nestwell-us')
  await expect(page.locator('[data-stage-workspace]')).toContainText('ORD-01')
})

test('stage step deep link survives reload', async ({ page }) => {
  await page.goto('/dispatch/stages/order?step=split')

  const active = page.locator('.flow-step[aria-current="page"]')
  await expect(active).toContainText('拆单 / 改址')

  await page.reload()
  await expect(page.locator('.flow-step[aria-current="page"]')).toContainText(
    '拆单 / 改址',
  )
})

test('approval decision updates progress and sidebar counts', async ({
  page,
}) => {
  await page.goto('/dispatch/approvals')
  await page.getByRole('button', { name: /批准 广告预算/ }).click()

  await expect(page.getByText('已批准 · 广告预算 · 3 个 Campaign')).toBeVisible()
  await page.goto('/dispatch')
  await expect(page.locator('[data-approval-progress]')).toContainText('1/3 已批')
  await expect(page.getByRole('link', { name: /待批 2/ })).toBeVisible()
  await expect(
    page.locator('[data-sidebar-group="paid"] .count-gold'),
  ).toHaveCount(0)
})

test('exception drawer shows three playbook phases and closes with Escape', async ({
  page,
}) => {
  await page.goto('/dispatch/exceptions')
  await page.locator('[data-exception-id="ORD-01"]').click()

  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('超时未发货')
  await expect(dialog.locator('.playbook-phases > li')).toHaveCount(3)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})

test('integrations page shows capability-driven mock health', async ({ page }) => {
  await page.goto('/dispatch/integrations')

  await expect(page.locator('[data-integration-platform="mock"]')).toContainText(
    'NestWell Home US',
  )
  await expect(page.locator('[data-integrations-view]')).toContainText('data.orders')
  await expect(page.locator('[data-integrations-view]')).toContainText(
    'control.price',
  )
  await expect(page.getByText('本期只读')).toBeVisible()
})

test('offline fixture is explicit when the API is unreachable', async ({
  page,
}) => {
  await page.route('**/api/v1/dispatch/**', (route) => route.abort())
  await page.goto('/dispatch/stages/order')

  await expect(page.getByText('离线数据').first()).toBeVisible()
  await expect(page.locator('[data-stage-result]')).toContainText('分类 6 单异常')
})
