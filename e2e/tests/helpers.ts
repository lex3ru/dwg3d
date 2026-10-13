import { expect, type Page } from '@playwright/test'

const run = () => process.env.E2E_RUN!
const tag = process.env.E2E_TAG ? `-${process.env.E2E_TAG}` : ''          // see global-setup.ts
export const users = {
  // made anew for every run (global-setup.ts); their e-mail is <login>@example.test
  boss: { get login() { return `e2e-boss-${run()}` }, name: 'Проверка Начальник', password: () => process.env.E2E_BOSS_PASSWORD! },
  // answers for objects in the scenario of stage 4 (one account is one person: scenarios do not share them)
  keeper: { get login() { return `e2e-keeper-${run()}` }, name: 'Проверка Хранитель', password: () => process.env.E2E_KEEPER_PASSWORD! },
  // the person of the cabinet scenario of stage 5
  tenant: { get login() { return `e2e-tenant-${run()}` }, name: 'Проверка Жилец', password: () => process.env.E2E_TENANT_PASSWORD! },
  // the person assigned to a room in the scenario of stage 6
  worker: { get login() { return `e2e-worker-${run()}` }, name: 'Проверка Работник', password: () => process.env.E2E_WORKER_PASSWORD! },
  // the role scenarios (scenarios.spec.ts): the keeper of a room, a person of another building
  steward: { get login() { return `e2e-steward-${run()}` }, name: 'Проверка Завхоз', password: () => process.env.E2E_STEWARD_PASSWORD! },
  outsider: { get login() { return `e2e-outsider-${run()}` }, name: 'Проверка Посторонний', password: () => process.env.E2E_OUTSIDER_PASSWORD! },
  clerk: { get login() { return `e2e-clerk-${run()}` }, name: 'Проверка Сотрудник', password: () => process.env.E2E_CLERK_PASSWORD! },
  admin: { login: `e2e-admin${tag}`, name: 'Проверка Администратор', password: () => process.env.E2E_ADMIN_PASSWORD! },
  user: { login: `e2e-user${tag}`, name: 'Проверка Пользователь', password: () => process.env.E2E_USER_PASSWORD! },
}

/** Open the app; it sends an unknown visitor to Keycloak — sign in there. */
export async function signIn(page: Page, who: keyof typeof users, path = '/') {
  await page.goto(path)
  await expect(page).toHaveURL(/\/kc\/realms\/twin\//)
  await page.locator('#username').fill(users[who].login)
  await page.locator('#password').fill(users[who].password())
  await page.locator('#kc-login').click()
  await expect(page.getByTestId('user-name')).toHaveText(users[who].name)
}

/** The editor asks the inventory number of a new object in its own dialog: give it, or cancel (null). */
export async function answerNumber(page: Page, answer: string | null) {
  const ask = page.getByTestId('number-ask')
  await expect(ask).toBeVisible({ timeout: 10_000 })
  if (answer === null) await ask.getByRole('button', { name: 'Отмена' }).click()
  else {
    await ask.getByLabel('Инвентарный номер').fill(answer)
    await ask.getByRole('button', { name: 'Поставить' }).click()
  }
  await expect(ask).toHaveCount(0)
}
