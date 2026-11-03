import { useQuery } from "@tanstack/react-query";
import { Video } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { get } from "@/lib/api";
import type { BuildingSummary } from "@/pages/Buildings";
import { lastBuilding } from "@/pages/PlanIndex";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { Chip, Empty, Loading, PageHeader } from "@/ui/misc";
import { CameraWindow, LivePreview } from "./CameraWindow";

type Camera = { id: string; title: string; type_name: string; floor_id: string; floor_name: string; room: string; configured: boolean };

export function CamerasPage() {
  const [params, setParams] = useSearchParams();
  const buildings = useQuery({ queryKey: ["buildings", false], queryFn: () => get<{ items: BuildingSummary[] }>("/api/buildings") });
  const list = buildings.data?.items ?? [];
  const selected = params.get("building") ?? lastBuilding();
  const building = list.find((b) => b.id === selected) ?? list[0];
  if (buildings.isPending) return <Loading />;
  if (buildings.isError) return <PageBody><p role="alert">Не удалось загрузить здания.</p></PageBody>;
  return <PageBody>
    <PageHeader title="Видеокамеры" subtitle="Видеонаблюдение" />
    {!building ? <Empty title="Нет доступных зданий" /> : <>
      <label className="flex max-w-sm flex-col gap-1 text-sm">Здание
        <select className="rounded-md border border-line-strong bg-surface p-2" value={building.id} onChange={(e) => setParams({ building: e.target.value })}>
          {list.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
      </label>
      <CameraGrid key={building.id} buildingId={building.id} />
    </>}
  </PageBody>;
}

function CameraGrid({ buildingId }: { buildingId: string }) {
  const [page, setPage] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [selected, setSelected] = useState<Camera | null>(null);
  const query = useQuery({ queryKey: ["surveillance-cameras", buildingId], queryFn: () => get<{ items: Camera[] }>(`/api/surveillance/cameras?building_id=${buildingId}`) });
  if (query.isPending) return <Loading />;
  if (query.isError) return <div role="alert">Не удалось загрузить камеры. <Button onClick={() => void query.refetch()}>Повторить</Button></div>;
  const cameras = query.data.items;
  if (!cameras.length) return <Empty title="Камер пока нет">Добавьте камеры в расстановке здания. <Link to={`/plan/${buildingId}?mode=place`}>Открыть план</Link></Empty>;
  const total = Math.ceil(cameras.length / 4);
  const current = Math.min(page, total - 1);
  const visible = cameras.slice(current * 4, current * 4 + 4);
  return <>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <span className="text-sm text-ink-2">Всего камер: {cameras.length} · подключено: {cameras.filter((c) => c.configured).length}</span>
      <Button onClick={() => setPlaying((value) => !value)}>{playing ? "Приостановить просмотр" : "Продолжить просмотр"}</Button>
    </div>
    <div className="grid gap-4 xl:grid-cols-2">
      {visible.map((camera) => <section key={camera.id} aria-label={camera.title} className="flex min-w-0 flex-col gap-3 rounded-xl border border-line bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="m-0 text-base font-semibold">{camera.title}</h2><Chip tone={camera.configured ? "accent" : "muted"}>{camera.configured ? "Подключение настроено" : "Не подключена"}</Chip></div>
        <p className="m-0 text-sm text-ink-2">{camera.floor_name} · {camera.room} · {camera.type_name}</p>
        {camera.configured && playing && !selected ? <LivePreview itemId={camera.id} /> : <div className="flex aspect-video items-center justify-center rounded-lg bg-surface-2 text-sm text-ink-3"><Video className="mr-2 size-5" />{camera.configured ? "Просмотр приостановлен" : "Укажите адрес камеры в настройках"}</div>}
        <div className="flex flex-wrap items-center gap-3"><Button onClick={() => setSelected(camera)}>Открыть камеру</Button><Link to={`/plan/${buildingId}/${camera.floor_id}?item=${camera.id}`}>На плане</Link></div>
      </section>)}
    </div>
    {total > 1 && <div className="flex items-center justify-center gap-3"><Button disabled={current === 0} onClick={() => setPage(current - 1)}>Назад</Button><span className="text-sm">{current + 1} / {total} · по 4 камеры</span><Button disabled={current + 1 === total} onClick={() => setPage(current + 1)}>Далее</Button></div>}
    {selected && <CameraWindow key={selected.id} itemId={selected.id} title={selected.title} onClose={() => setSelected(null)} />}
  </>;
}
