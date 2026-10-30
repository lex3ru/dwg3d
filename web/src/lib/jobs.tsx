import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Button } from "@/ui/button";
import { FormError } from "@/ui/form";
import { ApiError, get, post } from "./api";
import { userKey } from "./userStorage";

// Длительные операции (6.6): ход виден, уйти с экрана можно — по окончании придёт
// сообщение со ссылкой на результат. Следим за задачами из localStorage.

export interface Job {
  id: string;
  title: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: { done: number; total: number | null };
  message: string | null;
  error: string | null;
  cancel_requested?: boolean;
  result?: Record<string, unknown> | null;
  created_at?: string;
}

/** Задача стоит в очереди дольше 3 с: обработчик обычно берёт её за доли секунды, а дольше — он
 *  занят другой задачей той же полосы или не запущен (R-067). useJob спрашивает о задаче раз в
 *  секунду — ответ меняется без своего таймера. */
export function inQueue(job: Job | null | undefined, now = Date.now()): boolean {
  return job?.status === "queued" && !!job.created_at && now - Date.parse(job.created_at) > 3000;
}

/** Задача завершилась: выполнена, не удалась или отменена (R-026). */
export function finished(job: Job | null | undefined): boolean {
  return !!job && (job.status === "done" || job.status === "failed" || job.status === "cancelled");
}

interface Watched {
  id: string;
  title: string;
  href: string;
}

const KEY = "watched-jobs";

function read(): Watched[] {
  try {
    return JSON.parse(localStorage.getItem(userKey(KEY)) ?? "[]") as Watched[];
  } catch {
    return [];
  }
}

function write(list: Watched[]) {
  try {
    localStorage.setItem(userKey(KEY), JSON.stringify(list));
  } catch {
    /* не запомнится — сообщение придёт, пока страница открыта */
  }
  window.dispatchEvent(new Event("jobs:changed"));
}

export function watchJob(job: Watched) {
  write([...read().filter((j) => j.id !== job.id), job]);
}

export function useJob(id: string | null | undefined) {
  const [job, setJob] = useState<Job | null>(null);
  useEffect(() => {
    if (!id) {
      setJob(null);
      return;
    }
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const j = await get<Job>(`/api/system/tasks/${id}`);
        if (!alive) return;
        setJob(j);
        if (finished(j)) return;
      } catch {
        /* связь прервалась — спросим ещё раз */
      }
      timer = window.setTimeout(tick, 1000);
    };
    void tick();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [id]);
  return job;
}

interface Notice {
  id: string;
  title: string;
  href: string;
  status: Job["status"];
  text: string;
}

export function JobNotices() {
  const client = useQueryClient();
  const [notices, setNotices] = useState<Notice[]>([]);
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      const list = read();
      for (const w of list) {
        try {
          const j = await get<Job>(`/api/system/tasks/${w.id}`);
          if (finished(j)) {
            write(read().filter((x) => x.id !== w.id));
            client.invalidateQueries();
            const text = j.status === "done" ? "готово" : j.status === "cancelled" ? "отменено" : (j.error ?? "не удалось");
            if (alive) setNotices((n) => [...n, { ...w, status: j.status, text }]);
          }
        } catch {
          write(read().filter((x) => x.id !== w.id));
        }
      }
    };
    const t = window.setInterval(poll, 2000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [client]);
  if (!notices.length) return null;
  return (
    <div className="fixed right-4 bottom-4 z-50 flex w-80 flex-col gap-2 max-md:right-2 max-md:bottom-20 max-md:left-2 max-md:w-auto" role="status">
      {notices.map((n) => (
        <div key={n.id} className="flex items-start gap-3 rounded-xl border border-line bg-surface p-3 shadow-lg">
          <div className="flex flex-1 flex-col gap-1 text-sm">
            <span className="font-medium">{n.title}</span>
            <span className={n.status === "done" ? "text-ok" : n.status === "cancelled" ? "text-ink-2" : "text-bad"}>{n.text}</span>
            <Link to={n.href} className="text-[13px] text-accent" onClick={() => setNotices((x) => x.filter((y) => y.id !== n.id))}>
              Открыть результат →
            </Link>
          </div>
          <button type="button" aria-label="Закрыть" className="cursor-pointer border-0 bg-transparent p-0 text-ink-3" onClick={() => setNotices((x) => x.filter((y) => y.id !== n.id))}>
            <X className="size-4" />
          </button>
        </div>
      ))}
    </div>
  );
}

/** «Отменить» у хода задачи (R-026, ADR-0011): из очереди задача уходит сразу, выполняемую
 * обработчик останавливает за 1–2 с — её изменения не сохраняются. */
export function CancelJob({ job }: { job: Job | null }) {
  const [asked, setAsked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!job || finished(job)) return null;
  const cancel = async () => {
    setError(null);
    setAsked(true);
    try {
      await post(`/api/system/tasks/${job.id}/cancel`);
    } catch (e) {
      // уже завершилась — ход покажет итог сам
      if ((e as ApiError).code !== "finished") {
        setAsked(false);
        setError((e as ApiError).message);
      }
    }
  };
  const stopping = asked || !!job.cancel_requested;
  return (
    <div className="flex flex-col gap-1">
      <div>
        <Button onClick={cancel} disabled={stopping}>
          {stopping ? "Отменяется…" : "Отменить"}
        </Button>
      </div>
      <FormError message={error} />
    </div>
  );
}
