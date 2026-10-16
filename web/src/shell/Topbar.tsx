import { useQuery } from "@tanstack/react-query";
import { DropdownMenu } from "radix-ui";
import { Check, ChevronRight, KeyRound, LogOut, Moon, QrCode, Search, Sun, SunMoon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { get, post, query } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { applyTheme, readTheme, type Theme } from "@/lib/theme";
import { useQueryClient } from "@tanstack/react-query";
import { useShell } from "./context";
import { findItem, titleFor } from "./menu";
import { PasswordDialog } from "./PasswordDialog";

interface Hit {
  group: string;
  title: string;
  subtitle: string;
  href: string;
}

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase();
}

export function Crumbs() {
  const me = useMe();
  const { pathname } = useLocation();
  const { cardTitle } = useShell();
  const item = findItem(pathname);
  const parts = [item?.group, item ? titleFor(item, me.role) : pathname === "/search" ? "Поиск" : null, cardTitle].filter(Boolean) as string[];
  return (
    <div className="flex min-w-0 flex-1 items-center gap-1.5 text-sm text-ink-2" aria-label="Где я">
      {parts.map((part, i) => (
        <span key={i} className={cn("flex min-w-0 items-center gap-1.5", i === parts.length - 1 && "text-ink")}>
          {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-ink-3" aria-hidden />}
          <span className="truncate">{part}</span>
        </span>
      ))}
    </div>
  );
}

export function SearchBox({ autoFocus, className, initial = "" }: { autoFocus?: boolean; className?: string; initial?: string }) {
  const [text, setText] = useState(initial);
  const [open, setOpen] = useState(!!initial);
  const [debounced, setDebounced] = useState(initial);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(text.trim()), 200);
    return () => clearTimeout(t);
  }, [text]);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const results = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => get<{ items: Hit[] }>(`/api/search${query({ q: debounced })}`),
    enabled: debounced.length >= 2,
  });
  const groups = new Map<string, Hit[]>();
  for (const hit of results.data?.items ?? []) groups.set(hit.group, [...(groups.get(hit.group) ?? []), hit]);
  return (
    <div ref={box} className={cn("relative", className)}>
      <label htmlFor="global-search" className="sr-only">
        Поиск
      </label>
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-[18px] -translate-y-1/2 text-ink-3" aria-hidden />
      <input
        id="global-search"
        type="search"
        autoFocus={autoFocus}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        placeholder="Помещение, вещь, инв. номер, документ…"
        className="h-[38px] w-full rounded-lg border border-line-strong bg-surface-2 pr-3 pl-9 text-sm text-ink placeholder:text-ink-3 max-md:h-11"
        autoComplete="off"
      />
      {open && debounced.length >= 2 && (
        <div className="absolute top-full right-0 left-0 z-40 mt-1 max-h-[60vh] overflow-y-auto rounded-xl border border-line bg-surface py-2 shadow-lg">
          {results.isLoading ? (
            <div className="px-4 py-3 text-sm text-ink-2">Ищем…</div>
          ) : groups.size === 0 ? (
            <div className="px-4 py-3 text-sm text-ink-2">Ничего не найдено. Поиск охватит помещения, имущество, документы и каталог, когда они появятся.</div>
          ) : (
            [...groups].map(([group, hits]) => (
              <div key={group} className="py-1">
                <div className="px-4 py-1 text-[11px] font-medium tracking-wide text-ink-3 uppercase">{group}</div>
                {hits.map((hit) => (
                  <Link key={hit.href} to={hit.href} onClick={() => setOpen(false)} className="flex flex-col px-4 py-2 text-ink no-underline hover:bg-surface-2">
                    <span className="text-sm">{hit.title}</span>
                    <span className="text-xs text-ink-2">{hit.subtitle}</span>
                  </Link>
                ))}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function UserMenu() {
  const me = useMe();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [password, setPassword] = useState(false);
  const [theme, setTheme] = useState<Theme>(readTheme);
  const choose = (value: Theme) => {
    setTheme(value);
    applyTheme(value);
  };
  const logout = async () => {
    await post("/api/auth/logout").catch(() => {});
    client.clear();
    client.setQueryData(["me"], null);
    navigate("/login");
  };
  const themes: { value: Theme; title: string; icon: typeof Sun }[] = [
    { value: "light", title: "Светлая", icon: Sun },
    { value: "dark", title: "Тёмная", icon: Moon },
    { value: "system", title: "Как в системе", icon: SunMoon },
  ];
  const item = "flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-sm text-ink outline-none data-[highlighted]:bg-surface-2 max-md:h-11 [&_svg]:size-4";
  return (
    <>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button type="button" aria-label={`Пользователь: ${me.full_name}, ${me.role_title}`} className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-lg border-0 bg-transparent py-0 pr-2 pl-1 text-ink hover:bg-surface-2 max-md:h-11">
            <span className="inline-flex size-[30px] items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-ink">{initials(me.full_name)}</span>
            <span className="flex flex-col items-start leading-tight max-lg:hidden">
              <span className="text-[13px] font-medium">{me.full_name}</span>
              <span className="text-xs text-ink-2">{me.role_title}</span>
            </span>
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content align="end" sideOffset={6} className="z-50 min-w-56 rounded-xl border border-line bg-surface p-1.5 shadow-lg">
            <div className="px-2.5 py-2">
              <div className="text-sm font-medium">{me.full_name}</div>
              <div className="text-xs text-ink-2">
                {me.login} · {me.role_title}
              </div>
            </div>
            <DropdownMenu.Separator className="my-1 h-px bg-line" />
            <DropdownMenu.Item className={item} onSelect={() => setPassword(true)}>
              <KeyRound /> Сменить пароль
            </DropdownMenu.Item>
            <DropdownMenu.Separator className="my-1 h-px bg-line" />
            <DropdownMenu.Label className="px-2.5 py-1 text-[11px] font-medium tracking-wide text-ink-3 uppercase">Тема</DropdownMenu.Label>
            <DropdownMenu.RadioGroup value={theme} onValueChange={(v) => choose(v as Theme)}>
              {themes.map((t) => (
                <DropdownMenu.RadioItem key={t.value} value={t.value} className={item}>
                  <t.icon /> <span className="flex-1">{t.title}</span>
                  <DropdownMenu.ItemIndicator>
                    <Check />
                  </DropdownMenu.ItemIndicator>
                </DropdownMenu.RadioItem>
              ))}
            </DropdownMenu.RadioGroup>
            <DropdownMenu.Separator className="my-1 h-px bg-line" />
            <DropdownMenu.Item className={item} onSelect={logout}>
              <LogOut /> Выйти
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
      <PasswordDialog open={password} onOpenChange={setPassword} />
    </>
  );
}

export function Topbar() {
  return (
    <header className="flex min-h-16 shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface px-6 py-3 max-md:px-4">
      <Crumbs />
      <SearchBox className="w-[420px] max-w-full max-md:hidden" />
      <Link to="/scan" aria-label="QR-сканер" className="inline-flex size-[38px] items-center justify-center rounded-lg border border-line-strong text-ink max-md:hidden">
        <QrCode className="size-[18px]" />
      </Link>
      <UserMenu />
    </header>
  );
}
