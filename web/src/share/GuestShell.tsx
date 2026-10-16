import { Eye } from "lucide-react";
import { Outlet } from "react-router";
import { useMe } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import { ShellProvider } from "@/shell/context";

// Гость по ссылке (6.4): без меню — только план и 3D здания
export function GuestShell() {
  const me = useMe();
  return (
    <ShellProvider>
      <div className="flex h-dvh flex-col">
        <header className="flex min-h-12 shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-line bg-surface px-4 py-2">
          <span className="font-semibold">{me.buildings[0]?.name ?? "Здание"}</span>
          <span className="flex items-center gap-1.5 text-[13px] text-ink-2">
            <Eye className="size-4" aria-hidden /> просмотр по ссылке
            {me.expires_at && ` · до ${formatDateTime(me.expires_at)}`}
          </span>
        </header>
        <main className="min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </ShellProvider>
  );
}
