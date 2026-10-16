import { expect, type Page } from "@playwright/test";
import { ADMIN, PASSWORD } from "../global-setup";

export { ADMIN, PASSWORD };

export async function login(page: Page, name: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Имя для входа").fill(name);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти" }).click();
}

export async function loginAdmin(page: Page) {
  await login(page, ADMIN, PASSWORD);
  await expect(page.getByRole("button", { name: /^Пользователь:/ })).toBeVisible();
}

export const unique = (prefix: string) => `${prefix}${Date.now().toString(36)}`;
