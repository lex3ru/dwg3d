import { request, type FullConfig } from "@playwright/test";

export const ADMIN = process.env.E2E_ADMIN ?? "admin";
export const PASSWORD = process.env.E2E_PASSWORD ?? "Dev-admin-pass1";

// На свежей базе у администратора временный пароль: войти с ним и сменить на постоянный.
export default async function setup(config: FullConfig) {
  const temp = process.env.E2E_TEMP_PASSWORD;
  if (!temp) return;
  const api = await request.newContext({
    baseURL: config.projects[0]!.use.baseURL,
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: { "X-Requested-With": "app" },
  });
  const ok = await api.post("/api/auth/login", { data: { login: ADMIN, password: PASSWORD } });
  if (ok.ok()) return;
  const login = await api.post("/api/auth/login", { data: { login: ADMIN, password: temp } });
  if (!login.ok()) throw new Error(`не удалось войти администратором: ${await login.text()}`);
  const change = await api.post("/api/auth/password", { data: { current: temp, new: PASSWORD } });
  if (!change.ok()) throw new Error(`не удалось сменить пароль: ${await change.text()}`);
}
