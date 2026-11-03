import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { get, put } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { Button } from "@/ui/button";
import { LivePreview } from "./CameraWindow";

type Point = { x: number; y: number };
type Settings = { enabled: boolean; door: string; p1: Point; p2: Point; inside: Point };
type Configuration = { settings: Settings | null; version: number; state?: string };
type Event = { id: string; door: string; direction: "in" | "out"; occurred_at: string };

export function CountingPanel({ itemId }: { itemId: string }) {
  const admin = useMe().role === "admin";
  const config = useQuery({ queryKey: ["counting", itemId], queryFn: () => get<Configuration>(`/api/surveillance/cameras/${itemId}/analytics`), refetchInterval: 10000 });
  const events = useQuery({ queryKey: ["passages", itemId], queryFn: () => get<{items: Event[]; counts: {in: number; out: number}}>(`/api/surveillance/cameras/${itemId}/events`), refetchInterval: 5000 });
  return <>
    <p>Подсчёт работает независимо от просмотра. Подтверждение прохода может занимать около 8 секунд.</p>
    {config.isPending && <p>Загрузка настроек…</p>}
    {config.isError && <p role="alert">Не удалось загрузить настройки аналитики.</p>}
    {config.data && (admin ? <Editor key={`${itemId}-${config.data.version}`} itemId={itemId} data={config.data} saved={() => void config.refetch()} /> : <p>{config.data.settings?.enabled ? "Подсчёт включён" : "Подсчёт выключен"}</p>)}
    {config.data?.settings?.enabled && <p>Состояние сервиса: {config.data.state === "running" ? "обработка идёт" : config.data.state === "connecting" ? "подключение к камере" : config.data.state === "error" ? "ошибка обработки" : "нет связи"}</p>}
    {events.data && <p>За всё время: вошло {events.data.counts.in} · вышло {events.data.counts.out}</p>}
    <h3>Последние проходы</h3>
    {events.isError && <p role="alert">Не удалось загрузить события.</p>}
    {events.data && !events.data.items.length && <p>Событий пока нет.</p>}
    <ul>{events.data?.items.map(e => <li key={e.id}>{new Date(e.occurred_at).toLocaleString()} · {e.door} · {e.direction === "in" ? "Вход" : "Выход"}</li>)}</ul>
  </>;
}

function Editor({ itemId, data, saved }: { itemId: string; data: Configuration; saved: () => void }) {
  const [points, setPoints] = useState<Point[]>(data.settings ? [data.settings.p1, data.settings.p2, data.settings.inside] : []);
  const [enabled, setEnabled] = useState(data.settings?.enabled ?? false);
  const [door, setDoor] = useState(data.settings?.door ?? "Вход");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return <div className="flex flex-col gap-3">
    <label>Название двери / помещения <input className="rounded border border-line p-2" value={door} maxLength={100} onChange={e => setDoor(e.target.value)} /></label>
    <p>Укажите два конца линии порога, затем точку со стороны помещения, вход в которое считаем. Для новой разметки нажмите «Разметить заново».</p>
    <div className="relative">
      <LivePreview itemId={itemId} />
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Разметка прохода: два конца линии и сторона входа" className="absolute left-0 top-0 aspect-video w-full cursor-crosshair" onClick={e => {
        if (points.length === 3) return;
        const r = e.currentTarget.getBoundingClientRect();
        setPoints([...points, {x: (e.clientX-r.left)/r.width, y: (e.clientY-r.top)/r.height}]);
      }}>
        {points[0] && points[1] && <line x1={points[0].x*100} y1={points[0].y*100} x2={points[1].x*100} y2={points[1].y*100} stroke="#facc15" strokeWidth="0.6" />}
        {points.map((p, i) => <circle key={i} cx={p.x*100} cy={p.y*100} r="1" fill={i === 2 ? "#22c55e" : "#facc15"} />)}
      </svg>
    </div>
    <span>{points.length === 3 ? "Зелёная точка — сторона входа" : `Выбрано точек: ${points.length} из 3`}</span>
    <Button onClick={() => setPoints([])}>Разметить заново</Button>
    <label><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /> Включить подсчёт проходов</label>
    {error && <p role="alert">{error}</p>}
    <Button disabled={busy || points.length !== 3 || !door.trim()} onClick={async () => {
      setBusy(true); setError("");
      try {
        await put(`/api/surveillance/cameras/${itemId}/analytics`, {enabled, door, p1: points[0], p2: points[1], inside: points[2], version: data.version});
        saved();
      } catch (e) { setError(e instanceof Error ? e.message : "Не удалось сохранить разметку."); }
      finally { setBusy(false); }
    }}>{busy ? "Сохраняю…" : "Сохранить аналитику"}</Button>
  </div>;
}
