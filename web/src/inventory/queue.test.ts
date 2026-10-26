// @vitest-environment jsdom
import { beforeEach, expect, test, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { drainQueue, type Job, loadQueue, pushQueue, type Report } from "./queue";

// R-030, 6.7 п. 1: очередь досылает отметки, когда связь вернётся, — ни одна не теряется при
// сбоях связи, сервера и сеанса; выбрасывается только отметка, от которой отказался сам сервер

const KEY = "count-queue:test";
const a: Job = { kind: "mark", unit_id: "u1", place: "r:1" };
const b: Job = { kind: "scan", code: "AB12CD34EF56", place: "r:1" };
const c: Job = { kind: "unmark", unit_id: "u3" };

beforeEach(() => localStorage.clear());

const report = () => ({ changed: vi.fn(), waiting: vi.fn(), dropped: vi.fn() }) satisfies Report;

// так отвечает api(): нет ответа — code "offline"; ответ без тела ошибки (Caddy) — code "http"
const fail = (status: number, code = "http", message = `Сервер ответил ошибкой ${status}.`) => new ApiError(status, code, message);
const OFFLINE = () => fail(0, "offline", "Нет связи с сервером. Проверьте сеть и повторите.");

// сервер: на первые отметки — ошибки из списка, дальше принимает
function server(...errors: ApiError[]) {
  const got: Job[] = [];
  const send = vi.fn(async (job: Job) => {
    const e = errors.shift();
    if (e) throw e;
    got.push(job);
  });
  return { send, got };
}

function queue(...jobs: Job[]) {
  for (const job of jobs) pushQueue(KEY, job);
}

test("нет связи — отметки ждут и уходят по порядку, когда связь вернулась", async () => {
  queue(a, b);
  const s = server(OFFLINE());
  const r = report();
  await drainQueue(KEY, s.send, r);
  expect(loadQueue(KEY)).toEqual([a, b]);
  expect(r.waiting).toHaveBeenLastCalledWith("offline");
  expect(r.dropped).not.toHaveBeenCalled();

  await drainQueue(KEY, s.send, r);
  expect(s.got).toEqual([a, b]);
  expect(loadQueue(KEY)).toEqual([]);
  expect(r.waiting).toHaveBeenLastCalledWith(null);
});

test.each([500, 502, 503, 504, 408, 429])("ответ %i — отметка остаётся и досылается, когда сервер ответит", async (status) => {
  queue(a, b);
  const s = server(fail(status));
  const r = report();
  await drainQueue(KEY, s.send, r);
  expect(loadQueue(KEY)).toEqual([a, b]);
  expect(r.waiting).toHaveBeenLastCalledWith("server");
  expect(r.dropped).not.toHaveBeenCalled();

  await drainQueue(KEY, s.send, r);
  expect(s.got).toEqual([a, b]);
});

test.each([
  [401, "not_authenticated", "Нужно войти в систему."],
  [403, "forbidden", "Это действие вам недоступно."],
])("ответ %i — очередь стоит до входа, ни одна отметка не выброшена", async (status, code, message) => {
  queue(a, b, c);
  const s = server(fail(status, code, message), fail(status, code, message), fail(status, code, message));
  const r = report();
  await drainQueue(KEY, s.send, r);
  expect(s.send).toHaveBeenCalledTimes(1);
  expect(loadQueue(KEY)).toEqual([a, b, c]);
  expect(r.waiting).toHaveBeenLastCalledWith("session");
  expect(r.dropped).not.toHaveBeenCalled();

  // вошли снова — сервер принимает
  const after = server();
  await drainQueue(KEY, after.send, r);
  expect(after.got).toEqual([a, b, c]);
});

test("409 «обновите и повторите» — гонка, отметка повторяется, а не выбрасывается", async () => {
  queue(a);
  const s = server(fail(409, "stale", "Эти данные уже изменил другой пользователь. Обновите страницу и повторите."));
  const r = report();
  await drainQueue(KEY, s.send, r);
  expect(loadQueue(KEY)).toEqual([a]);
  expect(r.dropped).not.toHaveBeenCalled();

  await drainQueue(KEY, s.send, r);
  expect(s.got).toEqual([a]);
});

test.each([
  [400, "invalid", "Этого места нет в ведомости."],
  [404, "not_found", "Единица не найдена или списана."],
  [409, "conflict", "Инвентаризация уже проведена — отметки не меняются."],
])("отказ по самой отметке (%i) — она выброшена с сообщением, следующие уходят", async (status, code, message) => {
  queue(a, b);
  const s = server(fail(status, code, message));
  const r = report();
  await drainQueue(KEY, s.send, r);
  expect(r.dropped).toHaveBeenCalledExactlyOnceWith(message);
  expect(s.got).toEqual([b]);
  expect(loadQueue(KEY)).toEqual([]);
  expect(r.changed).toHaveBeenLastCalledWith([]);
});

test("досылка уже идёт — второй запуск не шлёт отметку повторно", async () => {
  queue(a);
  let release!: () => void;
  const send = vi.fn(() => new Promise<void>((done) => (release = done)));
  const first = drainQueue(KEY, send, report());
  expect(await drainQueue(KEY, send, report())).toBe(false);
  release();
  expect(await first).toBe(true);
  expect(send).toHaveBeenCalledTimes(1);
  expect(loadQueue(KEY)).toEqual([]);
});
