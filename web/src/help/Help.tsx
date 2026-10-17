import { CircleHelp, Search, X } from "lucide-react";
import { Dialog as D } from "radix-ui";
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/cn";
import type { Role } from "@/lib/types";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { Input } from "@/ui/form";
import { Card, PageHeader } from "@/ui/misc";
import { HELP, SCENARIOS, sectionFor, visibleFor, type HelpSection, type Topic } from "./content";

// Встроенная справка (8.6 п. 1, 3): по разделу, где человек сейчас, — F1 или «Справка»
// вверху; поиск по всей справке; страница /help — вся справка с указателем сценариев.

function sections(role: Role): HelpSection[] {
  const can = visibleFor(role);
  return HELP.filter(can)
    .map((s) => ({ ...s, topics: s.topics.filter(can) }))
    .filter((s) => s.topics.length);
}

function matches(t: Topic, q: string) {
  // «С1» — именно этот сценарий, а не С10–С19
  if (/^с\d+$/i.test(q.trim())) return (t.scenario ?? "").split(", ").includes(q.trim().toUpperCase());
  const low = q.toLowerCase();
  return t.q.toLowerCase().includes(low) || t.steps.some((s) => s.toLowerCase().includes(low)) || (t.scenario ?? "").toLowerCase().includes(low);
}

function TopicView({ t, open }: { t: Topic; open?: boolean }) {
  return (
    <details open={open} className="group rounded-lg border border-line bg-surface">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium [&::-webkit-details-marker]:hidden">
        <span className="text-ink-3 transition-transform group-open:rotate-90" aria-hidden>
          ›
        </span>
        <span className="flex-1">{t.q}</span>
        {t.scenario && (
          <span className="shrink-0 rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-2" title={t.scenario.split(", ").map((c) => `${c} — ${SCENARIOS[c] ?? ""}`).join("; ")}>
            {t.scenario}
          </span>
        )}
      </summary>
      <ol className="m-0 flex flex-col gap-1.5 px-3 pb-3 pl-9 text-[13px] leading-relaxed text-ink-2">
        {t.steps.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>
    </details>
  );
}

function SectionView({ s, openFirst }: { s: HelpSection; openFirst?: boolean }) {
  return (
    <section aria-label={`Справка: ${s.title}`} className="flex flex-col gap-2">
      <h3 className="m-0 text-sm font-semibold">{s.title}</h3>
      <p className="m-0 text-[13px] leading-relaxed text-ink-2">{s.intro}</p>
      {s.topics.map((t, i) => (
        <TopicView key={t.q} t={t} open={openFirst && i === 0} />
      ))}
    </section>
  );
}

function Found({ list, q }: { list: HelpSection[]; q: string }) {
  const found = list.flatMap((s) => s.topics.filter((t) => matches(t, q)).map((t) => ({ s, t })));
  if (!found.length) return <p className="m-0 text-[13px] text-ink-3">Ничего не нашлось. Попробуйте другое слово — например, «метки», «склад», «камера».</p>;
  return (
    <div className="flex flex-col gap-2" aria-label="Найдено в справке">
      {found.map(({ s, t }) => (
        <div key={`${s.path}:${t.q}`} className="flex flex-col gap-1">
          <span className="text-[11px] text-ink-3">{s.title}</span>
          <TopicView t={t} open={found.length <= 3} />
        </div>
      ))}
    </div>
  );
}

export function HelpButton() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "F1") {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Справка"
        title="Справка (F1)"
        className="inline-flex size-[38px] items-center justify-center rounded-lg border border-line-strong text-ink hover:bg-surface-2 max-md:size-11"
      >
        <CircleHelp className="size-[18px]" />
      </button>
      <HelpSheet open={open} onOpenChange={setOpen} />
    </>
  );
}

function HelpSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const me = useMe();
  const { pathname } = useLocation();
  const list = useMemo(() => sections(me.role), [me.role]);
  const here = sectionFor(pathname);
  const current = list.find((s) => s.path === here?.path) ?? list[0];
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<"here" | "all">("here");
  useEffect(() => {
    if (open) {
      setQ("");
      setTab("here");
    }
  }, [open, pathname]);
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-50 bg-black/30" />
        <D.Content className="fixed top-0 right-0 z-50 flex h-dvh w-[440px] max-w-full flex-col border-l border-line bg-ground shadow-xl" aria-describedby={undefined}>
          <div className="flex items-center gap-2 border-b border-line bg-surface px-4 py-3">
            <CircleHelp className="size-5 text-accent" aria-hidden />
            <D.Title className="m-0 flex-1 text-base font-semibold">Справка</D.Title>
            <D.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Закрыть справку">
                <X />
              </Button>
            </D.Close>
          </div>
          <div className="flex flex-col gap-2 border-b border-line bg-surface px-4 py-3">
            <label className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
              <Input aria-label="Поиск в справке" placeholder="Как… (например, «метки» или «перемещение»)" value={q} onChange={(e) => setQ(e.target.value)} className="w-full pl-8" />
            </label>
            {!q && (
              <div role="tablist" aria-label="Что показать" className="grid grid-cols-2 gap-1 rounded-lg bg-surface-2 p-1">
                {(
                  [
                    ["here", current?.title ?? "Этот раздел"],
                    ["all", "Все разделы"],
                  ] as const
                ).map(([k, t]) => (
                  <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={cn("min-h-9 cursor-pointer truncate rounded-md border-0 px-2 text-[13px]", tab === k ? "bg-surface font-medium text-ink shadow-sm" : "bg-transparent text-ink-2")}>
                    {t}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 py-4">
            {q ? <Found list={list} q={q} /> : tab === "here" && current ? <SectionView s={current} openFirst /> : list.map((s) => <SectionView key={s.path} s={s} />)}
          </div>
          <div className="border-t border-line bg-surface px-4 py-2.5 text-[13px]">
            <Link to="/help" onClick={() => onOpenChange(false)}>
              Вся справка на одной странице
            </Link>
            <span className="text-ink-3"> · F1 — открыть справку из любого раздела</span>
          </div>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

// /help: вся справка и указатель сценариев С1–С22
export function HelpPage() {
  const me = useMe();
  const list = useMemo(() => sections(me.role), [me.role]);
  const [q, setQ] = useState("");
  const byScenario = useMemo(() => {
    const out: Record<string, { s: HelpSection; t: Topic }[]> = {};
    for (const s of list) for (const t of s.topics) for (const c of (t.scenario ?? "").split(", ").filter(Boolean)) (out[c] ??= []).push({ s, t });
    return out;
  }, [list]);
  return (
    <PageBody>
      <PageHeader title="Справка" subtitle="Как сделать основное в каждом разделе. Из любого раздела справка открывается клавишей F1." />
      <Input aria-label="Поиск в справке" placeholder="Как… (например, «метки» или «перемещение»)" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xl" />
      {q ? (
        <Found list={list} q={q} />
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[1fr_280px]">
          <div className="flex flex-col gap-6">
            {list.map((s) => (
              <SectionView key={s.path} s={s} />
            ))}
          </div>
          {me.role === "admin" && (
            <Card className="p-4 lg:sticky lg:top-4" aria-label="Сценарии">
              <h3 className="m-0 mb-2 text-sm font-semibold">Сценарии</h3>
              <ul className="m-0 flex list-none flex-col gap-1 p-0 text-[13px]">
                {Object.entries(SCENARIOS).map(([c, title]) => (
                  <li key={c}>
                    <button type="button" className="cursor-pointer border-0 bg-transparent p-0 text-left text-accent-ink hover:underline" onClick={() => setQ(c)}>
                      <span className="font-mono text-[11px] text-ink-3">{c}</span> {title}
                    </button>
                    <span className="text-ink-3"> — {[...new Set((byScenario[c] ?? []).map((x) => x.s.title))].join(", ")}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}
    </PageBody>
  );
}
