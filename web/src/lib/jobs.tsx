import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { get } from "./api";

// Длительные операции (6.6): ход виден, уйти с экрана можно — по окончании придёт
// сообщение со ссылкой на результат. Следим за задачами из localStorage.

export interface Job {
  id: string;
  title: string;
  status: "queued" | "running" | "done" | "failed";
  progress: { done: number; total: number | null };
  message: string | null;
  error: string | null;
}

interface Watched {
  id: string;
  title: string;
  href: string;
}

const KEY = "watched-jobs";

function read(): Watched[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]") as Watched[];
  } catch {
    return [];
  }
}

function write(list: Watched[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
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
        if (j.status === "done" || j.status === "failed") return;
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
  ok: boolean;
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
          if (j.status === "done" || j.status === "failed") {
            write(read().filter((x) => x.id !== w.id));
            client.invalidateQueries();
            if (alive) setNotices((n) => [...n, { ...w, ok: j.status === "done", text: j.status === "done" ? "готово" : (j.error ?? "не удалось") }]);
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
            <span className={n.ok ? "text-ok" : "text-bad"}>{n.text}</span>
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
