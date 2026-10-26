// Очередь отметок обхода (6.7 п. 1): что ушло на сервер — по очереди; нет связи — копится в
// браузере (localStorage, переживает перезагрузку) и досылается, когда связь вернётся.
// Отметка уходит из очереди, только когда сервер её принял или отказал по ней самой (R-030).
import { ApiError } from "@/lib/api";

export type Job =
  | { kind: "scan"; code: string; place: string }
  | { kind: "mark"; unit_id: string; place: string }
  | { kind: "unmark"; unit_id: string }
  | { kind: "stock"; place: string; type_id: string; model_id: string | null; counted: number | null };

// почему очередь ждёт: нет связи, сервер не принимает, сеанс кончился
export type Wait = "offline" | "server" | "session";

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

export function loadQueue(key: string): Job[] {
  try {
    return JSON.parse(localStorage.getItem(key) ?? "[]") as Job[];
  } catch {
    return [];
  }
}

function save(key: string, jobs: Job[]) {
  localStorage.setItem(key, JSON.stringify(jobs));
}

export function pushQueue(key: string, job: Job): Job[] {
  const jobs = [...loadQueue(key), job];
  save(key, jobs);
  return jobs;
}

const busy = new Set<string>();

// Досылает по одной, по порядку. false — очередь уже досылается.
export async function drainQueue(key: string, send: (job: Job) => Promise<void>, report: Report): Promise<boolean> {
  if (busy.has(key)) return false;
  busy.add(key);
  try {
    for (;;) {
      const job = loadQueue(key)[0];
      if (!job) break;
      try {
        await send(job);
        report.waiting(null);
      } catch (e) {
        const why = verdict(e);
        if (why !== "drop") {
          report.waiting(why);
          break; // досылать позже — с этой же отметки
        }
        report.dropped(e instanceof Error ? e.message : String(e));
      }
      const rest = loadQueue(key).slice(1);
      save(key, rest);
      report.changed(rest);
    }
  } finally {
    busy.delete(key);
  }
  return true;
}
