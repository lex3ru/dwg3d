import { House, PencilRuler, QrCode, Search } from "lucide-react";
import { NavLink } from "react-router";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { homeFor } from "./menu";

// На телефоне меню заменяют вкладки внизу (6.3)
export function TabBar() {
  const me = useMe();
  const tabs = [
    { to: homeFor(me.role), title: "Главная", icon: House, end: true },
    { to: "/search", title: "Поиск", icon: Search },
    { to: "/scan", title: "QR", icon: QrCode },
    { to: "/plan", title: "План", icon: PencilRuler },
  ].filter((tab, i, all) => all.findIndex((t) => t.to === tab.to) === i);
  return (
    <nav aria-label="Разделы" className="grid shrink-0 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] md:hidden" style={{ gridTemplateColumns: `repeat(${tabs.length}, 1fr)` }}>
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.end}
          className={({ isActive }) =>
            cn("flex h-14 flex-col items-center justify-center gap-0.5 text-[11px] text-ink-2 no-underline", isActive && "text-accent")
          }
        >
          <tab.icon className="size-[22px]" aria-hidden />
          {tab.title}
        </NavLink>
      ))}
    </nav>
  );
}
