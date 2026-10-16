import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { NavLink } from "react-router";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { menuFor, titleFor, type MenuItem } from "./menu";

export function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const me = useMe();
  const groups: { name?: string; items: MenuItem[] }[] = [];
  for (const item of menuFor(me.role)) {
    const last = groups[groups.length - 1];
    if (last && last.name === item.group) last.items.push(item);
    else groups.push({ name: item.group, items: [item] });
  }
  return (
    <nav
      aria-label="Разделы"
      className={cn(
        "flex shrink-0 flex-col border-r border-line bg-surface max-md:hidden",
        collapsed ? "w-[68px]" : "w-[232px]",
      )}
    >
      <div className={cn("flex h-16 items-center gap-2.5 border-b border-line", collapsed ? "justify-center px-2" : "px-4")}>
        <img src="/favicon.svg" alt="" className="size-8" />
        {!collapsed && (
          <div className="flex min-w-0 flex-col leading-tight">
            <span className="text-sm font-semibold">Планировка и учёт</span>
            <span className="truncate text-xs text-ink-2">имущества здания</span>
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-2.5 py-4">
        {groups.map((group, i) => (
          <div key={group.name ?? `g${i}`} className="flex flex-col gap-0.5">
            {group.name && !collapsed && (
              <div className="px-2.5 pb-1 text-[11px] font-medium tracking-wide text-ink-3 uppercase">{group.name}</div>
            )}
            {group.items.map((item) => {
              const title = titleFor(item, me.role);
              return (
                <NavLink
                  key={item.path}
                  to={item.path}
                  end={item.path === "/"}
                  title={collapsed ? title : undefined}
                  className={({ isActive }) =>
                    cn(
                      "flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-sm text-ink no-underline hover:bg-surface-2",
                      collapsed && "justify-center px-0",
                      isActive && "bg-accent-soft font-medium text-accent-ink hover:bg-accent-soft",
                    )
                  }
                >
                  <item.icon className="size-[18px] shrink-0" aria-hidden />
                  {collapsed ? <span className="sr-only">{title}</span> : <span className="truncate">{title}</span>}
                </NavLink>
              );
            })}
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          "flex h-11 cursor-pointer items-center gap-2.5 border-0 border-t border-line bg-transparent text-[13px] text-ink-2 hover:text-ink",
          collapsed ? "justify-center" : "px-5",
        )}
        aria-label={collapsed ? "Развернуть меню" : "Свернуть меню"}
      >
        {collapsed ? <PanelLeftOpen className="size-[18px]" /> : <PanelLeftClose className="size-[18px]" />}
        {!collapsed && "Свернуть"}
      </button>
    </nav>
  );
}
