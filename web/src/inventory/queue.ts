// Очередь отметок обхода (6.7 п. 1): что ушло на сервер — по очереди; нет связи — копится в
// браузере (localStorage, переживает перезагрузку) и досылается, когда связь вернётся.
// Отметка уходит из очереди, только когда сервер её принял или отказал по ней самой (R-030).
// Зависший запрос обрывается через 15 с и повторяется. Каждая отметка несёт устройство и свой
// номер, и сервер пропускает опоздавший запрос, если более новый уже принят (R-049, ADR-0006).
import { ApiError, offline } from "@/lib/api";

export type Mark =
  | { kind: "scan"; code: string; place: string }
  | { kind: "mark"; unit_id: string; place: string }
  | { kind: "unmark"; unit_id: string }
  | { kind: "stock"; place: string; type_id: string; model_id: string | null; counted: number | null };

// отметка в очереди: номер даётся при постановке и не меняется при повторах
export type Job = Mark & { seq: number };

// почему очередь ждёт: нет связи, сервер не принимает, сеанс кончился
export type Wait = "offline" | "server" | "session";

export const TIMEOUT = 15_000; // мс: запрос отметки дольше — завис, обрывается

// Чем кончилась отправка, если сервер отметку не принял: ждать (и чего) или выбросить её.
// Сервер перезапускается (502 у Caddy), перегружен, упал, развёл гонку («обновите и
// повторите») — повторить; сеанс кончился или права отняли — стоять до входа; прочий отказ —
// про саму отметку (единица списана, места нет в ведомости, ведомость проведена).
export function verdict(e: unknown): Wait | "drop" {
  if (!(e instanceof ApiError)) return "drop";
  if (e.code === "offline") return "offline";
  if (e.status === 401 || e.status === 403) return "session";
  if (e.status >= 500 || e.status === 408 || e.status === 429 || e.code === "stale") return "server";
  return "drop";
}

export interface Report {
  changed: (jobs: Job[]) => void; // что ещё ждёт отправки
  waiting: (reason: Wait | null) => void; // null — сервер принял отметку
  dropped: (message: string) => void; // отметка не принята и выброшена — почему
}

// Устройство — этот браузер: UUID и счётчик номеров отметок, один на все ведомости
const DEVICE = "count-device";

interface Device {
  id: string;
  seq: number;
}

// UUID v4 из getRandomValues: crypto.randomUUID есть только на HTTPS и localhost, а телефон в
// разработке ходит по http:// на адрес компьютера
function uuid4(): string {
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6]! & 0x0f) | 0x40;
  b[8] = (b[8]! & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

function device(): Device {
  try {
    const d = JSON.parse(localStorage.getItem(DEVICE) ?? "null") as Device | null;
    if (typeof d?.id === "string" && Number.isSafeInteger(d.seq)) return d;
  } catch {
    /* испорчено — устройство заново */
  }
  const d = { id: uuid4(), seq: 0 };
  localStorage.setItem(DEVICE, JSON.stringify(d));
  return d;
}

export const deviceId = () => device().id;

function nextSeq(): number {
  const d = device();
  d.seq += 1;
  localStorage.setItem(DEVICE, JSON.stringify(d));
  return d.seq;
}

// заголовки запроса отметки: по ним сервер узнаёт опоздавший повтор
export function headersOf(job: Job): Record<string, string> {
  return { "X-Count-Device": deviceId(), "X-Count-Seq": String(job.seq) };
}

export function loadQueue(key: string): Job[] {
  let jobs: (Mark & { seq?: number })[];
  try {
    jobs = JSON.parse(localStorage.getItem(key) ?? "[]") as (Mark & { seq?: number })[];
  } catch {
    return [];
  }
  // отметки из прежней версии — без номера: номера по порядку, один раз
  if (jobs.some((j) => j.seq === undefined)) {
    jobs = jobs.map((j) => (j.seq === undefined ? { ...j, seq: nextSeq() } : j));
    save(key, jobs as Job[]);
  }
  return jobs as Job[];
}

function save(key: string, jobs: Job[]) {
  localStorage.setItem(key, JSON.stringify(jobs));
}

export function pushQueue(key: string, mark: Mark): Job[] {
  const jobs = [...loadQueue(key), { ...mark, seq: nextSeq() }];
  save(key, jobs);
  return jobs;
}

// Отправка с тайм-аутом: ни ответа, ни ошибки за TIMEOUT — запрос оборван, «нет связи» (R-049)
async function sendWithin(send: (job: Job, signal: AbortSignal) => Promise<void>, job: Job): Promise<void> {
  const abort = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const hung = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      abort.abort();
      reject(offline());
    }, TIMEOUT);
  });
  try {
    await Promise.race([send(job, abort.signal), hung]);
  } finally {
    clearTimeout(timer);
  }
}

const busy = new Set<string>();

// Досылает по одной, по порядку. false — очередь уже досылается.
export async function drainQueue(key: string, send: (job: Job, signal: AbortSignal) => Promise<void>, report: Report): Promise<boolean> {
  if (busy.has(key)) return false;
  busy.add(key);
  try {
    for (;;) {
      const job = loadQueue(key)[0];
      if (!job) break;
      try {
        await sendWithin(send, job);
        report.waiting(null);
      } catch (e) {
        const why = verdict(e);
        if (why !== "drop") {
          report.waiting(why);
          break; // досылать позже — с этой же отметки
        }
        report.dropped(e instanceof Error ? e.message : String(e));
      }
      // по номеру, а не первую: вкладка рядом могла уже убрать эту и ещё не дослать следующую
      const rest = loadQueue(key).filter((j) => j.seq !== job.seq);
      save(key, rest);
      report.changed(rest);
    }
  } finally {
    busy.delete(key);
  }
  return true;
}
