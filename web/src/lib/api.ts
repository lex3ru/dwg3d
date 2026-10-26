// Обращения к серверу. Ошибки сервера приходят человеческим языком (6.1 п. 6):
// {"error": {"code", "message", "field"}} — их и показываем.

export class ApiError extends Error {
  status: number;
  code: string;
  field?: string;

  constructor(status: number, code: string, message: string, field?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.field = field;
  }
}

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

// для отметок обхода: свои заголовки и обрыв зависшего запроса (R-049, ADR-0006)
export interface Options {
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

// нет ответа: сеть пропала или запрос оборван
export const offline = () => new ApiError(0, "offline", "Нет связи с сервером. Проверьте сеть и повторите.");

export async function api<T>(method: Method, path: string, body?: unknown, options: Options = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: {
        // сервер принимает изменения только с этим заголовком (защита от чужих сайтов)
        "X-Requested-With": "app",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: options.signal,
    });
  } catch {
    throw offline();
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = data?.error;
    if (response.status === 401 && path !== "/api/auth/login" && path !== "/api/auth/me") {
      window.dispatchEvent(new CustomEvent("app:unauthenticated"));
    }
    throw new ApiError(
      response.status,
      error?.code ?? "http",
      error?.message ?? `Сервер ответил ошибкой ${response.status}.`,
      error?.field,
    );
  }
  return data as T;
}

export const get = <T>(path: string) => api<T>("GET", path);
export const post = <T>(path: string, body: unknown = {}, options?: Options) => api<T>("POST", path, body, options);
export const patch = <T>(path: string, body: unknown) => api<T>("PATCH", path, body);
export const put = <T>(path: string, body: unknown) => api<T>("PUT", path, body);

export function query(params: Record<string, string | number | undefined | null>): string {
  const out = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") out.set(key, String(value));
  }
  const text = out.toString();
  return text ? `?${text}` : "";
}
