import { useInfiniteQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { get, query } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDay, formatTime } from "@/lib/format";
import type { JournalEntry, Page } from "@/lib/types";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { Input } from "@/ui/form";
import { Card, Empty, Loading, PageHeader } from "@/ui/misc";

const ACTIONS: { value: string; title: string }[] = [
  { value: "", title: "Все изменения" },
  { value: "auth.", title: "Входы и попытки входа" },
  { value: "user.", title: "Учётные записи" },
  { value: "settings.", title: "Настройки" },
  { value: "journal.", title: "Очистка журнала" },
];

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "boolean") return value ? "да" : "нет";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const FIELD_TITLES: Record<string, string> = {
  full_name: "ФИО", login: "Имя для входа", role: "Роль", buildings: "Здания", blocked: "Заблокирована", ip: "Адрес",
};

export function EntryView({ entry, compact }: { entry: JournalEntry; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const keys = [...new Set([...Object.keys(entry.before ?? {}), ...Object.keys(entry.after ?? {})])];
  return (
    <li className={cn("flex flex-col gap-1 border-b border-line py-2.5 last:border-b-0", !compact && "px-4")}>
      <div className="flex items-start gap-3">
        <span className="w-12 shrink-0 pt-px font-mono text-[13px] text-ink-2">{formatTime(entry.at)}</span>
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-sm">{entry.summary}</span>
          <span className="text-xs text-ink-2">{compact ? formatDay(entry.at) + " · " : ""}{entry.actor_name}</span>
        </div>
        {keys.length > 0 && (
          <button
            type="button"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            className="inline-flex shrink-0 cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-xs text-accent"
          >
            было / стало <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
          </button>
        )}
      </div>
      {open && (
        <table className="mt-1 ml-15 border-collapse text-[13px] max-md:ml-0">
          <thead>
            <tr className="text-left text-xs text-ink-2">
              <th className="py-1 pr-4 font-medium">Поле</th>
              <th className="py-1 pr-4 font-medium">Было</th>
              <th className="py-1 font-medium">Стало</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => (
              <tr key={key}>
                <td className="py-1 pr-4 text-ink-2">{FIELD_TITLES[key] ?? key}</td>
                <td className="py-1 pr-4">{show(entry.before?.[key])}</td>
                <td className="py-1">{show(entry.after?.[key])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </li>
  );
}

// Журнал (5.7.3, С22): лента изменений с фильтрами; фильтры — в адресе (6.1 п. 7)
export function Journal() {
  const [params, setParams] = useSearchParams();
  const filters = {
    q: params.get("q") ?? "",
    action: params.get("action") ?? "",
    ref: params.get("ref") ?? "",
    since: params.get("since") ?? "",
    until: params.get("until") ?? "",
  };
  const [text, setText] = useState(filters.q);
  const set = (key: string, value: string) =>
    setParams((p) => {
      const out = new URLSearchParams(p);
      if (value) out.set(key, value);
      else out.delete(key);
      return out;
    });
  const feed = useInfiniteQuery({
    queryKey: ["journal", filters],
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) =>
      get<Page<JournalEntry>>(
        `/api/journal${query({
          q: filters.q,
          action: filters.action,
          ref: filters.ref,
          since: filters.since ? new Date(filters.since).toISOString() : undefined,
          until: filters.until ? new Date(new Date(filters.until).getTime() + 86_400_000).toISOString() : undefined,
          before_id: pageParam,
          limit: 50,
        })}`,
      ),
    getNextPageParam: (last) => last.next_before_id ?? undefined,
  });
  const entries = feed.data?.pages.flatMap((p) => p.items) ?? [];
  const days: [string, JournalEntry[]][] = [];
  for (const entry of entries) {
    const day = formatDay(entry.at);
    const last = days[days.length - 1];
    if (last && last[0] === day) last[1].push(entry);
    else days.push([day, [entry]]);
  }
  const select = "h-9 rounded-lg border border-line-strong bg-surface px-2.5 text-sm text-ink max-md:h-11";
  return (
    <PageBody>
      <PageHeader title="Журнал" subtitle="Кто, когда, что было и что стало. Записи журнала не правятся." />
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          set("q", text.trim());
        }}
      >
        <label className="flex min-w-60 flex-1 flex-col gap-1 text-[13px] font-medium">
          Текст
          <Input value={text} onChange={(e) => setText(e.target.value)} onBlur={() => set("q", text.trim())} placeholder="Например, фамилия или «пароль»" />
        </label>
        <label className="flex flex-col gap-1 text-[13px] font-medium">
          Что
          <select className={select} value={filters.action} onChange={(e) => set("action", e.target.value)}>
            {ACTIONS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.title}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[13px] font-medium">
          С
          <input type="date" className={select} value={filters.since} onChange={(e) => set("since", e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-[13px] font-medium">
          По
          <input type="date" className={select} value={filters.until} onChange={(e) => set("until", e.target.value)} />
        </label>
      </form>
      {filters.ref && (
        <div className="flex items-center gap-2 text-sm text-ink-2">
          Только записи по одной сущности.
          <Button size="sm" variant="ghost" onClick={() => set("ref", "")}>
            Показать все
          </Button>
        </div>
      )}
      {feed.isLoading ? (
        <Loading />
      ) : !entries.length ? (
        <Card>
          <Empty title="Записей нет">Попробуйте изменить фильтры.</Empty>
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          {days.map(([day, items]) => (
            <Card key={day} className="overflow-hidden">
              <h2 className="m-0 border-b border-line bg-surface-2 px-4 py-2 text-[13px] font-semibold">{day}</h2>
              <ul className="m-0 list-none p-0">
                {items.map((entry) => (
                  <EntryView key={entry.id} entry={entry} />
                ))}
              </ul>
            </Card>
          ))}
          {feed.hasNextPage && (
            <Button onClick={() => feed.fetchNextPage()} disabled={feed.isFetchingNextPage} className="self-center">
              Показать ещё
            </Button>
          )}
        </div>
      )}
    </PageBody>
  );
}
