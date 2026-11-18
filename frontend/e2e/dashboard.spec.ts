import { expect, test } from '@playwright/test'

// One representative journey through the real stack: browser -> Vite proxy ->
// FastAPI WebSocket -> replayed events. Unit tests cover the logic; this
// checks the pieces are wired together.
test('dashboard shows replayed activity and filters by wiki', async ({ page }) => {
  await page.goto('/')

  // Nothing connects (and no AI is used) until the demo is started.
  await expect(page.getByRole('status')).toHaveText('Not started')
  await page.getByRole('button', { name: 'Start demo' }).first().click()

  // Recorded data is labelled as such, never as "Live".
  await expect(page.getByRole('status')).toHaveText('Replay (recorded data)')

  // Numbers, trending articles and the feed all fill in.
  const rate = page.locator('.rate .big')
  await expect(rate).toHaveText(/^[1-9]\d*$/)
  await expect(page.locator('.top-pages li').first()).toBeVisible()
  await expect(page.locator('.feed li').first()).toBeVisible()

  // With AI off, only strong rule matches are flagged, and they say so.
  await expect(page.locator('.flags li').first()).toContainText('not reviewed by AI')

  // Filtering to one wiki narrows every panel to it.
  await page.getByLabel('Wiki').selectOption({ value: 'dewiki' })
  await expect(page.getByRole('heading', { name: /Edits per minute · dewiki/ })).toBeVisible()
  await expect(page.locator('.feed li').first()).toBeVisible()
  const feedWikis = () => page.locator('.feed-meta > .tag:first-of-type').allTextContents()
  await expect.poll(async () => new Set(await feedWikis())).toEqual(new Set(['dewiki']))
  await expect(page.locator('.top-pages .tag')).toHaveCount(0) // wiki tags hidden once filtered
  await expect(page.getByText('not filtered to dewiki')).toBeVisible() // Pulse is global

  // And back to everything.
  await page.getByLabel('Wiki').selectOption({ value: '' })
  await expect(page.locator('.top-pages .tag').first()).toBeVisible()

  // Stopping disconnects but keeps the last numbers on screen.
  await page.getByRole('button', { name: 'Stop demo' }).click()
  await expect(page.getByRole('status')).toHaveText('Demo stopped')
  await expect(page.getByRole('button', { name: 'Start demo' })).toBeVisible()
})
