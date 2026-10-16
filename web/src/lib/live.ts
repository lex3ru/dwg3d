import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

// Изменения других пользователей — без перезагрузки (6.1 п. 8): сервер присылает, что
// изменилось, а мы перечитываем показанные данные.
export function useLiveUpdates(enabled: boolean) {
  const client = useQueryClient();
  useEffect(() => {
    if (!enabled) return;
    let socket: WebSocket | null = null;
    let closed = false;
    let delay = 1000;
    let timer: number | undefined;

    const connect = () => {
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${scheme}://${location.host}/api/ws`);
      socket.onopen = () => {
        delay = 1000;
      };
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.action === "ping") return;
        client.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" || message.entity?.startsWith("user:") });
      };
      socket.onclose = (event) => {
        if (closed) return;
        if (event.code === 4401) {
          window.dispatchEvent(new CustomEvent("app:unauthenticated"));
          return;
        }
        timer = window.setTimeout(connect, delay);
        delay = Math.min(delay * 2, 30_000);
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      socket?.close();
    };
  }, [enabled, client]);
}
