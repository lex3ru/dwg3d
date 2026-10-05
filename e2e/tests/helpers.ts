import { expect, type Page } from '@playwright/test'

export const users = {
  admin: { login: 'e2e-admin', name: 'Проверка Администратор', password: () => process.env.E2E_ADMIN_PASSWORD! },
  user: { login: 'e2e-user', name: 'Проверка Пользователь', password: () => process.env.E2E_USER_PASSWORD! },
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
