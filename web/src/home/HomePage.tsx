import { useQuery } from "@tanstack/react-query";
import { ArrowDownToLine, BarChart3, ClipboardCheck, QrCode, Truck } from "lucide-react";
import { Link, useSearchParams } from "react-router";
import { dateRu, money } from "@/inventory/types";
import { get } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { BuildingSummary } from "@/pages/Buildings";
import { lastBuilding } from "@/pages/PlanIndex";
import { FormError } from "@/ui/form";
import { PageBody } from "@/shell/Shell";
import { Card, Empty, Loading, PageHeader } from "@/ui/misc";

interface Attention {
  key: string;
  title: string;
  count: number;
  href: string;
}

interface Summary {
  building: { id: string; name: string };
  attention: Attention[];
  cost: { initial: number; value: number; units: number };
  documents: { id: string; title: string; date: string; status: string; kind: string }[];
}

// Главная (6.5.1): что требует внимания, стоимость, последние документы, быстрые действия
export function HomePage() {
  const [params] = useSearchParams();
  const buildings = useQuery({ queryKey: ["buildings", false], queryFn: () => get<{ items: BuildingSummary[] }>("/api/buildings") });
  const all = buildings.data?.items ?? [];
  const wanted = params.get("building") ?? lastBuilding();
  const building = all.find((b) => b.id === wanted) ?? all[0];
  const summary = useQuery({ queryKey: ["home", building?.id], queryFn: () => get<Summary>(`/api/home?building_id=${building!.id}`), enabled: !!building });
  const plan = useQuery({ queryKey: ["home-plan", building?.id], queryFn: () => get<{ attention: Attention[] }>(`/api/home/plan?building_id=${building!.id}`), enabled: !!building });
  if (buildings.isLoading) return <Loading />;
  if (!building)
    return (
      <PageBody>
        <PageHeader title="Главная" />
        <Card>
          <Empty title="Зданий пока нет">
            Начните с <Link to="/buildings">«Зданий»</Link>: заведите здание, этажи и план — или загрузите чертёж.
          </Empty>
        </Card>
      </PageBody>
    );
  const s = summary.data;
  const attention = [...(s?.attention ?? []), ...(plan.data?.attention ?? [])];
  return (
    <PageBody>
      <PageHeader title="Главная" subtitle={building.name} />
      {(summary.isError || plan.isError) && <FormError message="Сводка не загрузилась — обновите страницу." />}
      <section aria-label="Требует внимания" className="flex flex-col gap-2">
        <h2 className="m-0 text-sm font-semibold text-ink-2">Требует внимания</h2>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          {attention.map((a) => (
            <Link key={a.key} to={a.href} className={cn("rounded-xl border bg-surface p-3 no-underline hover:border-accent", a.count ? "border-warn/50" : "border-line")}>
              <div className={cn("font-mono text-2xl font-semibold", a.count ? "text-warn" : "text-ink-3")}>{a.count}</div>
              <div className="text-[13px] text-ink">{a.title}</div>
            </Link>
          ))}
          {plan.isLoading && <div className="rounded-xl border border-line bg-surface p-3 text-[13px] text-ink-3">Считаю план, освещённость и проекты…</div>}
        </div>
      </section>
      <div className="grid gap-4 md:grid-cols-[1fr_1.4fr]">
        <Card className="p-4" aria-label="Стоимость имущества">
          <h2 className="m-0 mb-2 text-sm font-semibold text-ink-2">Стоимость имущества</h2>
          {s ? (
            <dl className="m-0 grid grid-cols-2 gap-y-1 text-[13px]">
              <dt className="text-ink-2">Первоначальная</dt>
              <dd className="m-0 text-right font-mono">{money(s.cost.initial)}</dd>
              <dt className="text-ink-2">Остаточная</dt>
              <dd className="m-0 text-right font-mono font-semibold">{money(s.cost.value)}</dd>
              <dt className="text-ink-2">Единиц</dt>
              <dd className="m-0 text-right font-mono">{s.cost.units}</dd>
            </dl>
          ) : summary.isError ? (
            <span className="text-[13px] text-ink-3">—</span>
          ) : (
            <Loading />
          )}
          <Link to={`/property?tab=cost`} className="mt-2 inline-block text-[13px]">
            Ведомость стоимости
          </Link>
        </Card>
        <Card className="p-4" aria-label="Последние документы">
          <h2 className="m-0 mb-2 text-sm font-semibold text-ink-2">Последние документы</h2>
          <ul className="m-0 flex list-none flex-col p-0 text-[13px]">
            {s?.documents.map((d) => (
              <li key={d.id} className="flex justify-between gap-2 border-b border-line py-1.5 last:border-b-0">
                <Link to={d.kind === "inventory" ? `/inventory/${d.id}` : `/documents/${d.id}`}>{d.title}</Link>
                <span className="text-ink-3">{dateRu(d.date)}</span>
              </li>
            ))}
            {s && !s.documents.length && <li className="text-ink-3">Документов пока нет.</li>}
          </ul>
        </Card>
      </div>
      <section aria-label="Быстрые действия" className="grid grid-cols-2 gap-2 md:grid-cols-5">
        {[
          ["/warehouse", "Принять на склад", ArrowDownToLine],
          ["/documents", "Переместить", Truck],
          ["/scan", "Найти по QR", QrCode],
          ["/inventory", "Инвентаризация", ClipboardCheck],
          ["/reports", "Отчёты", BarChart3],
        ].map(([to, title, Icon]) => {
          const I = Icon as typeof Truck;
          return (
            <Link key={to as string} to={to as string} className="flex min-h-12 items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink no-underline hover:border-accent">
              <I className="size-4 text-accent" /> {title as string}
            </Link>
          );
        })}
      </section>
    </PageBody>
  );
}
