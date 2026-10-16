import { defineConfig, devices } from "@playwright/test";

// Сценарии ТЗ (раздел 4) на работающей системе. Адрес — E2E_URL: установленная система
// (https://…) или интерфейс разработки (http://localhost:5190). Администратор — E2E_ADMIN /
// E2E_PASSWORD; на свежей базе его временный пароль — E2E_TEMP_PASSWORD (global-setup
// сменит его на E2E_PASSWORD). README.md — как запустить.
export default defineConfig({
  testDir: "tests",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  globalSetup: "./global-setup.ts",
  use: {
    baseURL: process.env.E2E_URL ?? "http://localhost:5190",
    ignoreHTTPSErrors: true,
    locale: "ru-RU",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "компьютер", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } }, grepInvert: /@телефон/ },
    { name: "телефон", use: { ...devices["Pixel 7"] }, grep: /@телефон/ },
  ],
});
