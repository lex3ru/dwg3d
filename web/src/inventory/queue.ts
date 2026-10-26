// Очередь отметок обхода (6.7 п. 1): что ушло на сервер — по очереди; нет связи — копится в
// браузере (localStorage, переживает перезагрузку) и досылается, когда связь вернётся.
import type { ApiError } from "@/lib/api";

export type Job = { kind: "scan"; code: string; place: string } | { kind: "mark"; unit_id: string; place: string } | { kind: "unmark"; unit_id: string };

// почему очередь ждёт: нет связи, сервер не принимает, сеанс кончился
export type Wait = "offline" | "server" | "session";

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
        if ((e as ApiError).code === "offline") {
          report.waiting("offline");
          break; // досылать позже
        }
        report.dropped((e as ApiError).message);
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
