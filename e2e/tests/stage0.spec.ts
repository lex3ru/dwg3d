import { expect, test } from '@playwright/test'
import { signIn, users } from './helpers'

// Stage 0 (docs/ACCEPTANCE.md, section 2): the skeleton.

test('a user signs in, sees the empty «Мои здания» with their name, and signs out', async ({ page }) => {
  await signIn(page, 'user')
  await expect(page.getByRole('heading', { name: 'Мои здания' })).toBeVisible()
  await expect(page.getByText('Зданий пока нет')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Состояние системы' })).toHaveCount(0)

  await page.getByLabel('Выйти', { exact: true }).click()
  await expect(page).toHaveURL(/\/kc\/realms\/twin\//)        // signed out of Keycloak too: it asks again
  await expect(page.locator('#username')).toBeVisible()
  expect((await page.request.get('/api/me')).status()).toBe(401)
})

test('without a session the API answers 401, through the gateway', async ({ request }) => {
  for (const path of ['/api/me', '/api/ping/v1/notes', '/api/system/status', '/api/stream']) {
    const response = await request.get(path)
    expect(response.status(), path).toBe(401)
    expect(response.headers()['content-type']).toContain('application/problem+json')
  }
})

test('an ordinary user is refused the system status', async ({ page }) => {
  await signIn(page, 'user')
  expect((await page.request.get('/api/system/status')).status()).toBe(403)
  await page.goto('/#/system')
  await expect(page.getByRole('heading', { name: 'Мои здания' })).toBeVisible()
})

test('the administrator sees the services up, and an event comes back to the browser within 2 seconds', async ({ page }) => {
  await signIn(page, 'admin', '/#/system')
  await expect(page.getByRole('heading', { name: 'Состояние системы' })).toBeVisible()
  for (const service of ['gateway', 'ping']) {
    await expect(page.locator(`tr[data-service="${service}"]`)).toHaveAttribute('data-ok', 'true')
  }
  await expect(page.getByTestId('stream-state')).toContainText('подключён')

  await page.getByRole('button', { name: 'Проверить' }).click()
  const delivery = page.getByTestId('delivery')
  await expect(delivery).toContainText(/Событие получено за \d+ мс/, { timeout: 5000 })
  const ms = Number((await delivery.textContent())!.match(/за (\d+) мс/)![1])
  expect(ms).toBeLessThan(2000)

  // the note really is in the service, handled exactly once
  const { items } = await (await page.request.get('/api/ping/v1/notes')).json()
  expect(items[0].echoes).toBe(1)
  expect(users.admin.name).toBeTruthy()
})

test('the pages work in the dark theme and on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 })
  await signIn(page, 'admin', '/#/system')
  await page.getByLabel('Тёмная тема', { exact: true }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await expect(page.getByRole('heading', { name: 'Состояние системы' })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
