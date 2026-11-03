import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CountingPanel } from "./CountingPanel";
import { Video } from "lucide-react";
import { get, put } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";

export function LivePreview({ itemId }: { itemId: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState("Подключение…");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setStatus("Подключение…");
    async function play() {
      while (!controller.signal.aborted) {
        const response = await fetch(`/api/surveillance/cameras/${itemId}/preview`, { signal: controller.signal });
        if (!response.ok || !response.body) {
          const detail = await response.json().catch(() => null);
          throw new Error(detail?.error?.message ?? "Не удалось открыть видео. Проверьте подключение камеры или доступ к зданию.");
        }
        const reader = response.body.getReader();
        let pending = new Uint8Array(0);
        let received = false;
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const buffer = new Uint8Array(pending.length + value.length);
            buffer.set(pending); buffer.set(value, pending.length);
            pending = buffer;
            // MJPEG: извлекаем JPEG между SOI/EOI, независимо от границ сетевых чанков.
            let start = -1;
            for (let i = 0; i < pending.length - 1; i++) {
              if (pending[i] === 255 && pending[i + 1] === 216) start = i;
              if (start >= 0 && pending[i] === 255 && pending[i + 1] === 217) {
                const bitmap = await createImageBitmap(new Blob([pending.slice(start, i + 2)], { type: "image/jpeg" }));
                const el = canvas.current;
                if (el && !controller.signal.aborted) {
                  el.width = bitmap.width; el.height = bitmap.height;
                  el.getContext("2d")?.drawImage(bitmap, 0, 0);
                  setStatus("Прямой эфир · без звука");
                }
                bitmap.close(); received = true;
                pending = pending.slice(i + 2); i = -1; start = -1;
              }
            }
            if (pending.length > 4 * 1024 * 1024) throw new Error("Не удалось прочитать видео с камеры.");
          }
        } finally { await reader.cancel(); }
        if (!received) throw new Error("Камера не передаёт изображение.");
        setStatus("Переподключение…");
        // Сервер завершает превью раз в минуту: новый запрос повторно проверяет права.
      }
    }
    void play().catch((error: unknown) => {
      if (!controller.signal.aborted) setStatus(error instanceof Error ? error.message : "Связь с камерой потеряна.");
    });
    return () => controller.abort();
  }, [itemId, attempt]);
  return <>
    <canvas ref={canvas} className="aspect-video w-full rounded-lg bg-black" aria-label="Видео с камеры" />
    <div role="status" className="text-sm text-ink-2">{status}</div>
    <Button onClick={() => setAttempt((n) => n + 1)}>Переподключить</Button>
  </>;
}

interface Connection {
  configured: boolean;
  version: number;
  address?: string;
  username?: string;
  has_password?: boolean;
}

function ConnectionForm({ itemId, data, onSaved }: { itemId: string; data: Connection; onSaved: () => void }) {
  const [address, setAddress] = useState(data.address ?? "");
  const [username, setUsername] = useState(data.username ?? "");
  const [password, setPassword] = useState("");
  const [clearPassword, setClearPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputClass = "rounded-md border border-line-strong bg-surface px-3 py-2 text-ink";
  return <form className="flex flex-col gap-3" onSubmit={async (event) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await put(`/api/surveillance/cameras/${itemId}`, {
        address, username, password: clearPassword ? "" : password || null, version: data.version,
      });
      setPassword(""); onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось сохранить подключение."); }
    finally { setBusy(false); }
  }}>
    <label className="flex flex-col gap-1 text-sm">Адрес потока RTSP
      <input required maxLength={2048} className={inputClass} value={address} disabled={busy}
        placeholder="rtsp://192.168.1.100:554/stream1" onChange={(e) => setAddress(e.target.value)} />
    </label>
    <p className="m-0 text-xs text-ink-2">Укажите адрес потока, доступный серверу приложения. Логин и пароль вводятся отдельно.</p>
    <label className="flex flex-col gap-1 text-sm">Логин камеры
      <input maxLength={200} autoComplete="off" className={inputClass} value={username} disabled={busy} onChange={(e) => setUsername(e.target.value)} />
    </label>
    <label className="flex flex-col gap-1 text-sm">Пароль камеры
      <input type="password" maxLength={1000} autoComplete="new-password" className={inputClass} value={password} disabled={busy || clearPassword}
        placeholder={data.has_password ? "Сохранён. Оставьте пустым, чтобы не менять" : "Не задан"} onChange={(e) => setPassword(e.target.value)} />
    </label>
    {data.has_password && <label className="flex gap-2 text-sm"><input type="checkbox" checked={clearPassword} disabled={busy} onChange={(e) => setClearPassword(e.target.checked)} />Удалить сохранённый пароль</label>}
    {error && <p role="alert" className="text-sm text-bad">{error}</p>}
    <Button type="submit" variant="primary" disabled={busy}>{busy ? "Сохраняю…" : "Сохранить и открыть видео"}</Button>
  </form>;
}

export function CameraWindow({ itemId, title, onClose }: { itemId: string; title: string; onClose?: () => void }) {
  const [open, setOpen] = useState(true);
  const admin = useMe().role === "admin";
  const [tab, setTab] = useState<"video" | "settings" | "analytics">("video");
  const camera = useQuery({
    queryKey: ["surveillance", itemId],
    queryFn: () => get<Connection>(`/api/surveillance/cameras/${itemId}`),
    enabled: open,
  });
  return <>
    <Button onClick={() => setOpen(true)}><Video /> Видео с камеры</Button>
    <Dialog open={open} onOpenChange={(value) => { setOpen(value); if (!value) onClose?.(); }} title={title} wide description="Видеонаблюдение">
      <div className="flex gap-2">
        <Button onClick={() => setTab("video")} variant={tab === "video" ? "primary" : "ghost"}>Видео</Button>
        <Button onClick={() => setTab("settings")} variant={tab === "settings" ? "primary" : "ghost"}>Настройки</Button>
        <Button onClick={() => setTab("analytics")} variant={tab === "analytics" ? "primary" : "ghost"}>Аналитика</Button>
      </div>
      {camera.isPending && <p>Загрузка подключения…</p>}
      {camera.isError && <p role="alert">Не удалось загрузить камеру. Проверьте доступ и настройки подключения.</p>}
      {camera.data && (tab === "analytics" ? <CountingPanel itemId={itemId} /> : tab === "video" ? (
        camera.data.configured ? <LivePreview itemId={itemId} /> : <>
          <p>Физическая камера ещё не подключена.</p>
          {admin ? <Button onClick={() => setTab("settings")}>Настроить подключение</Button> : <p>Обратитесь к администратору.</p>}
        </>
      ) : <>
        {admin ? <ConnectionForm key={camera.data.version} itemId={itemId} data={camera.data} onSaved={() => { void camera.refetch().then(() => setTab("video")); }} /> : <p>Подключение настроено администратором.</p>}
        <p>Подсчёт проходов настраивается на вкладке «Аналитика».</p>
      </>)}
    </Dialog>
  </>;
}
