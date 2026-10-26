// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { deviceId, drainQueue, headersOf, type Job, loadQueue, type Mark, pushQueue, type Report } from "./queue";

// R-030, 6.7 п. 1: очередь досылает отметки, когда связь вернётся, — ни одна не теряется при
// сбоях связи, сервера и сеанса; выбрасывается только отметка, от которой отказался сам сервер

const KEY = "count-queue:test";
const a: Mark = { kind: "mark", unit_id: "u1", place: "r:1" };
const b: Mark = { kind: "scan", code: "AB12CD34EF56", place: "r:1" };
const c: Mark = { kind: "unmark", unit_id: "u3" };

beforeEach(() => localStorage.clear());
afterEach(() => vi.useRealTimers());

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

function queue(...marks: Mark[]) {
  for (const mark of marks) pushQueue(KEY, mark);
}

test("нет связи — отметки ждут и уходят по порядку, когда связь вернулась", async () => {
  queue(a, b);
  const s = server(OFFLINE());
  const r = report();
  await drainQueue(KEY, s.send, r);
  expect(loadQueue(KEY)).toMatchObject([a, b]);
  expect(r.waiting).toHaveBeenLastCalledWith("offline");
  expect(r.dropped).not.toHaveBeenCalled();

  await drainQueue(KEY, s.send, r);
  expect(s.got).toMatchObject([a, b]);
  expect(loadQueue(KEY)).toEqual([]);
  expect(r.waiting).toHaveBeenLastCalledWith(null);
});

test.each([500, 502, 503, 504, 408, 429])("ответ %i — отметка остаётся и досылается, когда сервер ответит", async (status) => {
  queue(a, b);
  const s = server(fail(status));
  const r = report();
  await drainQueue(KEY, s.send, r);
  expect(loadQueue(KEY)).toMatchObject([a, b]);
  expect(r.waiting).toHaveBeenLastCalledWith("server");
  expect(r.dropped).not.toHaveBeenCalled();

  await drainQueue(KEY, s.send, r);
  expect(s.got).toMatchObject([a, b]);
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
  expect(loadQueue(KEY)).toMatchObject([a, b, c]);
  expect(r.waiting).toHaveBeenLastCalledWith("session");
  expect(r.dropped).not.toHaveBeenCalled();

  // вошли снова — сервер принимает
  const after = server();
  await drainQueue(KEY, after.send, r);
  expect(after.got).toMatchObject([a, b, c]);
});

test("409 «обновите и повторите» — гонка, отметка повторяется, а не выбрасывается", async () => {
  queue(a);
  const s = server(fail(409, "stale", "Эти данные уже изменил другой пользователь. Обновите страницу и повторите."));
  const r = report();
  await drainQueue(KEY, s.send, r);
  expect(loadQueue(KEY)).toMatchObject([a]);
  expect(r.dropped).not.toHaveBeenCalled();

  await drainQueue(KEY, s.send, r);
  expect(s.got).toMatchObject([a]);
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
  expect(s.got).toMatchObject([b]);
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

// R-049, ADR-0006: запрос повис (полуоткрытое соединение на телефоне) — ни ответа, ни ошибки.
// Через 15 с он оборван, на экране «нет связи», досылка свободна; повтор — та же отметка с тем
// же номером, поэтому сервер пропустит старый запрос, если тот всё-таки дойдёт

test("R-049: запрос повис — через 15 с «нет связи», отметка ждёт и досылается с тем же номером", async () => {
  vi.useFakeTimers();
  queue(a, b);
  const sent: { job: Job; signal: AbortSignal }[] = [];
  const send = vi.fn((job: Job, signal: AbortSignal) => {
    sent.push({ job, signal });
    return sent.length === 1 ? new Promise<void>(() => {}) : Promise.resolve();
  });
  const r = report();
  const first = drainQueue(KEY, send, r);
  await vi.advanceTimersByTimeAsync(14_999);
  expect(r.waiting).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1);
  expect(r.waiting).toHaveBeenLastCalledWith("offline");
  expect(sent[0]!.signal.aborted).toBe(true);
  expect(await first).toBe(true);
  expect(loadQueue(KEY)).toMatchObject([a, b]);
  expect(r.dropped).not.toHaveBeenCalled();

  await drainQueue(KEY, send, r);
  expect(sent).toHaveLength(3);
  expect(sent[1]!.job).toEqual(sent[0]!.job);
  expect(sent[2]!.job).toMatchObject(b);
  expect(loadQueue(KEY)).toEqual([]);
  expect(r.waiting).toHaveBeenLastCalledWith(null);
});

test("номера отметок растут в порядке постановки, общие для всех ведомостей и переживают перезагрузку", async () => {
  queue(a, b);
  const [ja, jb] = loadQueue(KEY);
  expect(jb!.seq).toBeGreaterThan(ja!.seq);
  const id = deviceId();
  expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  expect(headersOf(jb!)).toEqual({ "X-Count-Device": id, "X-Count-Seq": String(jb!.seq) });

  // перезагрузка страницы: модуль заново, а устройство, номера и очередь — в localStorage
  vi.resetModules();
  const again = await import("./queue");
  expect(again.loadQueue(KEY)).toEqual([ja, jb]);
  expect(again.deviceId()).toBe(id);
  const [jc] = again.pushQueue("count-queue:other", c);
  expect(jc!.seq).toBeGreaterThan(jb!.seq);
});

test("отметки из прежней версии, без номера, получают номера при чтении очереди — по порядку и один раз", () => {
  localStorage.setItem(KEY, JSON.stringify([a, b]));
  const jobs = loadQueue(KEY);
  expect(jobs).toMatchObject([a, b]);
  expect(jobs[0]!.seq).toBeGreaterThan(0);
  expect(jobs[1]!.seq).toBeGreaterThan(jobs[0]!.seq);
  expect(loadQueue(KEY)).toEqual(jobs);
});

// у каждой вкладки свой модуль (и своё «досылка занята»), а очередь в localStorage — общая
async function tab() {
  vi.resetModules();
  return { queue: await import("./queue"), api: await import("@/lib/api") };
}

test("две вкладки одной ведомости: отметка, которую другая вкладка не дослала, из очереди не снимается", async () => {
  queue(a, b);
  const [ja, jb] = loadQueue(KEY);
  const one = await tab();
  const two = await tab();
  const got: Job[] = [];
  let release!: () => void;
  // первая вкладка шлёт a долго; вторая шлёт a быстро, а на b связь пропала
  const slow = vi.fn(async (job: Job) => {
    if (job.kind === a.kind) await new Promise<void>((done) => (release = done));
    got.push(job);
  });
  const fast = vi.fn(async (job: Job) => {
    if (job.kind === b.kind) throw new two.api.ApiError(0, "offline", "Нет связи с сервером. Проверьте сеть и повторите.");
    got.push(job);
  });
  const running = one.queue.drainQueue(KEY, slow, report());
  const r = report();
  await two.queue.drainQueue(KEY, fast, r);
  expect(r.waiting).toHaveBeenLastCalledWith("offline");
  expect(loadQueue(KEY)).toEqual([jb]);

  // первая вкладка дослала a (повтор сервер пропустит по номеру) — b остаётся и уходит
  release();
  await running;
  expect(got).toEqual([ja, ja, jb]);
  expect(loadQueue(KEY)).toEqual([]);
});
