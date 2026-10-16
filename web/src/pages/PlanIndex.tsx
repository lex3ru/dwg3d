import { useQuery } from "@tanstack/react-query";
import { Navigate, Link } from "react-router";
import { get } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { PageBody } from "@/shell/Shell";
import { Card, Empty, Loading, PageHeader } from "@/ui/misc";
import type { BuildingSummary } from "./Buildings";

export function lastBuilding(): string | null {
  try {
    return localStorage.getItem("building");
  } catch {
    return null;
  }
}

// «План»: одно здание — сразу его редактор; несколько — выбор (6.3)
export function PlanIndex() {
  const me = useMe();
  const list = useQuery({ queryKey: ["buildings", false], queryFn: () => get<{ items: BuildingSummary[] }>("/api/buildings") });
  if (list.isLoading) return <Loading />;
  const items = list.data?.items ?? [];
  const last = lastBuilding();
  const pick = items.length === 1 ? items[0] : items.find((b) => b.id === last);
  if (pick) return <Navigate to={`/plan/${pick.id}`} replace />;
  return (
    <PageBody>
      <PageHeader title={me.role === "admin" ? "План и расстановка" : "План"} subtitle="Выберите здание" />
      {!items.length ? (
        <Card>
          <Empty title="Зданий нет">{me.role === "admin" ? <>Создайте здание в разделе <Link to="/buildings">«Здания»</Link>.</> : "Вам ещё не выдан доступ ни к одному зданию — обратитесь к администратору."}</Empty>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((b) => (
            <Link key={b.id} to={`/plan/${b.id}`} className="rounded-xl border border-line bg-surface p-4 text-ink no-underline hover:border-accent">
              <div className="font-medium">{b.name}</div>
              <div className="text-[13px] text-ink-2">{[b.address, `этажей ${b.floors}`, `помещений ${b.rooms}`].filter(Boolean).join(" · ")}</div>
            </Link>
          ))}
        </div>
      )}
    </PageBody>
  );
}
