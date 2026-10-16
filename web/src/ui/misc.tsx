import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type Tone = "ok" | "bad" | "warn" | "muted" | "accent";

const tones: Record<Tone, string> = {
  ok: "bg-ok-soft text-ok",
  bad: "bg-bad-soft text-bad",
  warn: "bg-warn-soft text-warn",
  muted: "bg-muted-soft text-muted",
  accent: "bg-accent-soft text-accent-ink",
};

export function Chip({ tone = "muted", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={cn("inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium whitespace-nowrap", tones[tone])}>
      {children}
    </span>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cn("rounded-xl border border-line bg-surface", className)}>{children}</section>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="m-0 text-[26px] font-semibold max-md:text-[22px]">{title}</h1>
        {subtitle && <div className="text-sm text-ink-2">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <div className="text-base font-medium">{title}</div>
      {children && <div className="max-w-md text-sm text-ink-2">{children}</div>}
    </div>
  );
}

export function Loading() {
  return <div className="px-6 py-12 text-center text-sm text-ink-2">Загрузка…</div>;
}
