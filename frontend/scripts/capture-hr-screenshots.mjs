import { mkdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(here, '../../design/opsconductor-hr-deck/images')
const base = process.env.DECK_BASE_URL ?? 'http://127.0.0.1:8010'

await mkdir(outDir, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1,
})
await page.emulateMedia({ reducedMotion: 'reduce' })

async function open(path, selector) {
  await page.goto(`${base}${path}`, { waitUntil: 'domcontentloaded' })
  if (selector) await page.waitForSelector(selector)
  await page.waitForTimeout(900)
}

async function viewportShot(name) {
  await page.screenshot({ path: resolve(outDir, name), fullPage: false })
}

await open('/dispatch', '[data-insight-board]')
await viewportShot('04-dashboard.png')

await open('/dispatch/stages/order', '[data-stage-result]')
await viewportShot('06-stage-workspace.png')

await open('/dispatch/approvals', '[data-approval-id="budget"]')
await viewportShot('08-approvals.png')

await open('/dispatch/exceptions', '[data-exception-id="ORD-01"]')
await page.locator('[data-exception-id="ORD-01"]').click()
await page.waitForSelector('[role="dialog"]')
await page.waitForTimeout(350)
await viewportShot('09-exception.png')

await open('/dispatch/integrations', '[data-integration-platform="mock"]')
await viewportShot('11-integrations.png')

await open('/dispatch', '[data-insight-board]')
await page.locator('[data-insight-board]').screenshot({
  path: resolve(outDir, '10-analytics.png'),
})

await browser.close()
console.log(`captured HR deck screenshots in ${outDir}`)
