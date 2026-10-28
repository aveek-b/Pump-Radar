import { expect, test } from '@playwright/test'

test('filter radar, inspect a coin, and complete a replay without browser errors', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await expect(page.getByText('SYNTHETIC PREVIEW')).toBeVisible()
  await expect(page.locator('tbody tr')).toHaveCount(60)
  await page.screenshot({ path: 'test-results/radar-desktop.png', fullPage: true })
  await page.getByLabel('Horizon').selectOption('30')
  await page.getByLabel('Tier', { exact: true }).selectOption('low')
  await page.getByRole('searchbox').fill('MOCK001')
  await expect(page.locator('tbody tr')).toHaveCount(1)
  await expect(page).toHaveURL(/horizon=.*30/)
  await page.reload()
  await expect(page.getByLabel('Horizon')).toHaveValue('30')
  await page.getByRole('link', { name: 'MOCK001BTC', exact: true }).first().click()
  await expect(page.getByRole('heading', { name: 'MOCK001BTC', exact: true })).toBeVisible()
  await expect(page.getByText('360 bars,', { exact: false })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Score drivers' })).toBeVisible()
  await page.getByRole('link', { name: 'Replay', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible()
  await page.getByLabel('Speed', { exact: true }).selectOption('16')
  await page.getByRole('button', { name: 'Play', exact: true }).click()
  await expect(page.getByText('Playback complete', { exact: false })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('Not evaluated').first()).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Replay', exact: true })).toBeVisible()
  expect(errors).toEqual([])
})

test('markets distinguish unscored coins and filters have an empty state', async ({ page }) => {
  await page.goto('/?tab=markets')
  await expect(page.locator('tbody tr')).toHaveCount(61)
  await page.getByRole('searchbox').fill('MOCK061')
  await expect(page.getByRole('cell', { name: 'Not scored', exact: true })).toBeVisible()
  await page.getByRole('searchbox').fill('does-not-exist')
  await expect(page.getByText('No markets match.', { exact: false })).toBeVisible()
  await page.getByRole('link', { name: 'Honesty', exact: true }).click()
  await expect(page.getByText('Not measured yet.', { exact: false })).toBeVisible()
})

test('real price snapshots appear in Radar and Honesty without inventing risk scores', async ({ page }) => {
  await page.addInitScript(() => {
    class QuietEventSource extends EventTarget {
      onopen: (() => void) | null = null
      onerror: (() => void) | null = null
      constructor() { super(); queueMicrotask(() => this.onopen?.()) }
      close() {}
    }
    Object.assign(window, { EventSource: QuietEventSource })
  })
  await page.route('**/api/radar', route => route.fulfill({ json: {
    scorer: 'demo_stub', mock: false, model_version: null, minute: null,
    notice: 'Real market/model integration is pending.', rows: [], coins: [], sequence: null,
  } }))
  await page.route('**/api/markets', route => route.fulfill({ json: {
    scorer: 'demo_stub', mock: false, model_version: null,
    notice: 'Live public market prices. No research model is loaded; none is scored.',
    as_of: '2026-10-29T00:00:00Z', markets: [
      { symbol: 'BTCUSDT', quote_asset: 'USDT', price: 65000, change_24h_pct: 1.2, volume_24h_quote: 1_000_000, scored: false },
      { symbol: 'ETHUSDT', quote_asset: 'USDT', price: 3200, change_24h_pct: -0.4, volume_24h_quote: 500_000, scored: false },
    ],
  } }))
  await page.route('**/api/honesty', route => route.fulfill({ json: {
    scorer: 'demo_stub', mock: false, model_version: null, notice: 'Live model pending.',
    status: 'unavailable', precision: null, recall: null, median_lead_minutes: null,
    hit_at_5: null, false_alerts_per_hour: null, alert_budget_per_hour: null,
    limitations: ['No cross-sectional model loaded.'],
  } }))
  await page.goto('/')
  await expect(page.getByText('Public price watch', { exact: false })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'BTCUSDT' })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Not scored' }).first()).toBeVisible()
  await expect(page.locator('.feed-banner')).toContainText('research risk model is not loaded')
  await page.getByRole('button', { name: 'All markets' }).click()
  await expect(page.getByRole('cell', { name: 'ETHUSDT' })).toBeVisible()
  await page.getByRole('link', { name: 'Honesty', exact: true }).click()
  await expect(page.getByText('Public markets with prices')).toBeVisible()
  await expect(page.getByText('Real prices and 24-hour market statistics', { exact: false })).toBeVisible()
  await expect(page.getByText('Not measured yet.', { exact: false })).toBeVisible()
})

test('mobile pages stay within the viewport and support direct links', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  for (const path of ['/', '/coin/MOCK001BTC', '/replay', '/honesty', '/method']) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByText('Loading data…')).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    if (path === '/') await page.screenshot({ path: 'test-results/radar-mobile.png', fullPage: true })
  }
})

test('replayed SSE snapshots do not duplicate toast alerts and disconnect is visible', async ({ page }) => {
  await page.addInitScript(() => {
    class FakeEventSource extends EventTarget {
      static instances: FakeEventSource[] = []
      onopen: (() => void) | null = null
      onerror: (() => void) | null = null
      constructor() { super(); FakeEventSource.instances.push(this); setTimeout(() => this.onopen?.(), 0) }
      close() { FakeEventSource.instances = FakeEventSource.instances.filter(s => s !== this) }
    }
    Object.assign(window, { EventSource: FakeEventSource, streams: FakeEventSource.instances })
    Object.defineProperty(window, 'activeStreams', { get: () => FakeEventSource.instances })
  })
  await page.goto('/')
  await expect(page.locator('tbody tr')).toHaveCount(60)
  const tick = await (await page.request.get('/api/radar')).json()
  const send = async (sequence: number) => page.evaluate(({ tick, sequence }) => {
    const streams = (window as unknown as { activeStreams: EventTarget[] }).activeStreams
    const event = { ...tick, as_of: tick.minute, sequence, newAlerts: [{ id: `alert-${sequence}`, pair: 'MOCK001BTC', time: tick.minute, horizon: '10', risk: .9, mock: true, reasons: ['Synthetic test alert'] }] }
    streams.forEach(s => s.dispatchEvent(new MessageEvent('tick', { data: JSON.stringify(event) })))
  }, { tick, sequence })
  await send(0)
  await send(1)
  await send(1)
  await expect(page.locator('[data-sonner-toast]')).toHaveCount(1)
  await page.evaluate(() => (window as unknown as { activeStreams: { onerror: () => void }[] }).activeStreams.forEach(s => s.onerror()))
  await expect(page.getByRole('status')).toContainText('Reconnecting')
})
