import { expect, test as base } from "@playwright/test";

export * from "@playwright/test";

// Страж политики безопасности страницы (R-018 п. 1): сценарий падает, если браузер что-то
// заблокировал по Content-Security-Policy, — так политика не ломает интерфейс незаметно.
// Следит за основным окном сценария; на интерфейсе разработки (Vite) политики нет.
export const test = base.extend<{ csp: void }>({
  csp: [
    async ({ context }, use) => {
      const blocked: string[] = [];
      context.on("console", (m) => {
        if (m.type() === "error" && m.text().includes("Content Security Policy")) blocked.push(m.text());
      });
      await use();
      expect(blocked, "браузер заблокировал по политике безопасности").toEqual([]);
    },
    { auto: true },
  ],
});
