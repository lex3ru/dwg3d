import { Calculator, Eye, EyeOff, Layers, LayoutGrid, Lock, LockOpen, PackageCheck, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { TypeBrief } from "@/catalog/types";
import { cn } from "@/lib/cn";
import { CalcSection, type CalcInfo } from "./calc";
import { UnplacedSection, type LinkView } from "./link";
import { placeable, type Catalog } from "./placement";
import { useEditor, type EditorStore } from "./store";

// Слева в «Расстановке» (5.3.1) — вкладками, одна во всю высоту: каталог (поиск, слой,
// перетаскивание на план или выбор и щелчок), слои (показать, скрыть, заблокировать), учёт
// («Неразмещённые», сверка), расчёты (5.3.7). Вкладка запоминается.
type Tab = "catalog" | "layers" | "stock" | "calc";
const TAB_KEY = "place-tab";

function savedTab(readOnly: boolean): Tab {
  let t: string | null = null;
  try {
    t = localStorage.getItem(TAB_KEY);
  } catch {
    /* нет хранилища */
  }
  if (t === "layers" || t === "calc" || (!readOnly && (t === "catalog" || t === "stock"))) return t;
  return readOnly ? "layers" : "catalog";
}

export function PlacePanel({ store, cat, readOnly, link, calcs }: { store: EditorStore; cat: Catalog; readOnly: boolean; link: LinkView | undefined; calcs: CalcInfo[] }) {
  const items = useEditor(store, (s) => s.items);
  const hidden = useEditor(store, (s) => s.hiddenLayers);
  const locked = useEditor(store, (s) => s.lockedLayers);
  const placing = useEditor(store, (s) => s.placing);
  const [search, setSearch] = useState("");
  const [layer, setLayer] = useState<string | null>(null);
  const counts = useMemo(() => {
    const out = new Map<string, number>();
    for (const it of items) {
      const l = cat.types.get(it.type_id)?.layer_id ?? "";
      out.set(l, (out.get(l) ?? 0) + 1);
    }
    return out;
  }, [items, cat]);
  const layers = [...cat.layers.values()].sort((a, b) => a.position - b.position || a.name.localeCompare(b.name));
  const types = useMemo(() => {
    const q = search.trim().toLowerCase();
    return [...cat.types.values()].filter((t) => placeable(t) && (!layer || t.layer_id === layer) && (!q || t.name.toLowerCase().includes(q))).sort((a, b) => a.name.localeCompare(b.name));
  }, [cat, search, layer]);
  const toggle = (list: string[], id: string) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  const [tab, setTabState] = useState<Tab>(() => (new URLSearchParams(location.search).get("calc") ? "calc" : savedTab(readOnly)));
  const setTab = (t: Tab) => {
    setTabState(t);
    try {
      localStorage.setItem(TAB_KEY, t);
    } catch {
      /* не запомнится */
    }
  };
  const calcsOn = useEditor(store, (s) => s.calcsOn.length);
  const unplaced = link?.unplaced.length ?? 0;
  const tabs: { key: Tab; title: string; icon: typeof Layers; badge?: number; warn?: boolean }[] = [
    ...(readOnly ? [] : [{ key: "catalog" as const, title: "Каталог", icon: LayoutGrid }]),
    { key: "layers", title: "Слои", icon: Layers },
    ...(readOnly || !link ? [] : [{ key: "stock" as const, title: "Учёт", icon: PackageCheck, badge: unplaced || undefined, warn: !!link?.mismatch.length }]),
    ...(calcs.length ? [{ key: "calc" as const, title: "Расчёты", icon: Calculator, badge: calcsOn || undefined }] : []),
  ];
  const shown = tabs.some((t) => t.key === tab) ? tab : tabs[0]!.key;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div role="tablist" aria-label="Панель расстановки" className="grid shrink-0 border-b border-line p-1" style={{ gridTemplateColumns: `repeat(${tabs.length}, 1fr)` }}>
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={shown === t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              "relative flex cursor-pointer flex-col items-center gap-0.5 rounded-md border-0 px-1 py-1.5 text-[11px]",
              shown === t.key ? "bg-accent-soft font-medium text-accent-ink" : "bg-transparent text-ink-2 hover:bg-surface-2",
            )}
          >
            <t.icon className="size-4" aria-hidden />
            {t.title}
            {t.badge !== undefined && <span className="absolute top-0.5 right-1 min-w-4 rounded-full bg-accent px-1 font-mono text-[10px] leading-4 text-on-accent">{t.badge}</span>}
            {t.warn && t.badge === undefined && <span className="absolute top-1 right-2 size-1.5 rounded-full bg-warn" />}
          </button>
        ))}
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        {shown === "layers" && (
          <section aria-label="Слои" className="p-2">
            {layers.map((l) => {
              const off = hidden.includes(l.id);
              const lock = locked.includes(l.id);
              return (
                <div key={l.id} className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-[13px] hover:bg-surface-2">
                  <span className="size-2.5 shrink-0 rounded-full" style={{ background: l.color }} />
                  <span className={cn("min-w-0 flex-1 truncate", off && "text-ink-3")}>{l.name}</span>
                  <span className="font-mono text-[11px] text-ink-3">{counts.get(l.id) ?? 0}</span>
                  <button
                    type="button"
                    aria-label={`${off ? "Показать" : "Скрыть"} слой ${l.name}`}
                    aria-pressed={!off}
                    title={off ? "Показать" : "Скрыть"}
                    onClick={() => store.setLayers(toggle(hidden, l.id), locked)}
                    className="flex size-7 cursor-pointer items-center justify-center rounded border-0 bg-transparent text-ink-2 hover:bg-surface max-md:size-10"
                  >
                    {off ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                  </button>
                  {!readOnly && (
                    <button
                      type="button"
                      aria-label={`${lock ? "Разблокировать" : "Заблокировать"} слой ${l.name}`}
                      aria-pressed={lock}
                      title={lock ? "Разблокировать" : "Заблокировать: виден, но не выбирается"}
                      onClick={() => store.setLayers(hidden, toggle(locked, l.id))}
                      className={cn("flex size-7 cursor-pointer items-center justify-center rounded border-0 bg-transparent hover:bg-surface max-md:size-10", lock ? "text-warn" : "text-ink-3")}
                    >
                      {lock ? <Lock className="size-4" /> : <LockOpen className="size-4" />}
                    </button>
                  )}
                </div>
              );
            })}
          </section>
        )}
        {shown === "calc" && <CalcSection store={store} list={calcs} />}
        {shown === "stock" && <UnplacedSection store={store} cat={cat} link={link} readOnly={readOnly} />}
        {shown === "catalog" && (
          <section aria-label="Каталог" className="flex min-h-0 flex-1 flex-col p-2">
            <label className="mb-1.5 flex h-8 items-center gap-1.5 rounded-md border border-line-strong bg-surface px-2 max-md:h-11">
              <Search className="size-3.5 text-ink-3" />
              <input
                aria-label="Поиск в каталоге"
                placeholder="Поиск"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="min-w-0 flex-1 border-0 bg-transparent text-[13px] outline-none"
              />
            </label>
            <div className="mb-1.5 flex max-h-20 shrink-0 flex-wrap gap-1 overflow-y-auto">
              {[{ id: null, name: "все" }, ...layers].map((l) => (
                <button
                  key={l.id ?? "all"}
                  type="button"
                  aria-pressed={layer === l.id}
                  onClick={() => setLayer(l.id)}
                  className={cn(
                    "h-6 cursor-pointer rounded-full border px-2 text-[11px] max-md:h-9",
                    layer === l.id ? "border-accent bg-accent-soft text-accent-ink" : "border-line-strong bg-transparent text-ink-2",
                  )}
                >
                  {l.name}
                </button>
              ))}
            </div>
            <ul aria-label="Типы для расстановки" className="m-0 min-h-0 flex-1 list-none overflow-y-auto p-0">
              {types.map((t) => (
                <TypeRow
                  key={t.id}
                  t={t}
                  color={cat.layers.get(t.layer_id ?? "")?.color ?? "#607D8B"}
                  active={placing === t.id}
                  onPick={() =>
                    store.set({
                      placing: placing === t.id ? null : t.id,
                      placingUnit: null,
                      selection: [],
                    })
                  }
                />
              ))}
              {!types.length && <li className="px-1.5 py-2 text-[12px] text-ink-3">Ничего не нашлось.</li>}
            </ul>
            <p className="m-0 px-1.5 pt-1.5 text-[11px] text-ink-3">Перетащите на план — или выберите и щёлкните по плану (Shift — несколько раз).</p>
          </section>
        )}
      </div>
    </div>
  );
}

function TypeRow({ t, color, active, onPick }: { t: TypeBrief; color: string; active: boolean; onPick: () => void }) {
  const mount = t.mount === "wall" ? "на стену" : t.mount === "ceiling" ? "на потолок" : t.mount === "none" ? "во вместилище" : "";
  return (
    <li>
      <button
        type="button"
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData("application/x-item-type", t.id);
          e.dataTransfer.effectAllowed = "copy";
        }}
        onClick={onPick}
        aria-pressed={active}
        title={`${t.name}${t.width ? ` · ${t.width}×${t.depth ?? "?"}×${t.height ?? "?"} мм` : ""}${mount ? ` · ${mount}` : ""}`}
        className={cn(
          "flex w-full cursor-grab items-center gap-2 rounded-md border-0 px-1.5 py-1.5 text-left text-[13px] max-md:py-2.5",
          active ? "bg-accent-soft font-medium text-accent-ink" : "bg-transparent text-ink hover:bg-surface-2",
        )}
      >
        <span className="size-3 shrink-0 rounded-sm border" style={{ background: `${color}55`, borderColor: color }} />
        <span className="min-w-0 flex-1 truncate">{t.name}</span>
        {mount && <span className="text-[10px] text-ink-3">{mount}</span>}
      </button>
    </li>
  );
}
