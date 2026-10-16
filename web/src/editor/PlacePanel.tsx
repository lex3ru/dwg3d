import { Eye, EyeOff, Lock, LockOpen, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { TypeBrief } from "@/catalog/types";
import { cn } from "@/lib/cn";
import { placeable, type Catalog } from "./placement";
import { useEditor, type EditorStore } from "./store";

// Слева в «Расстановке» (5.3.1): слои — показать, скрыть, заблокировать; каталог — поиск,
// слой, перетаскивание на план (или выбор и щелчок по плану — на телефоне).
export function PlacePanel({ store, cat, readOnly }: { store: EditorStore; cat: Catalog; readOnly: boolean }) {
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

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <section aria-label="Слои" className="max-h-56 shrink-0 overflow-y-auto border-b border-line p-2">
        <h3 className="m-0 px-1.5 pb-1 text-[12px] font-semibold tracking-wide text-ink-2 uppercase">Слои</h3>
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
      {!readOnly && (
        <section aria-label="Каталог" className="flex min-h-0 flex-1 flex-col p-2">
          <h3 className="m-0 px-1.5 pb-1.5 text-[12px] font-semibold tracking-wide text-ink-2 uppercase">Каталог</h3>
          <label className="mb-1.5 flex h-8 items-center gap-1.5 rounded-md border border-line-strong bg-surface px-2 max-md:h-11">
            <Search className="size-3.5 text-ink-3" />
            <input aria-label="Поиск в каталоге" placeholder="Поиск" value={search} onChange={(e) => setSearch(e.target.value)} className="min-w-0 flex-1 border-0 bg-transparent text-[13px] outline-none" />
          </label>
          <div className="mb-1.5 flex flex-wrap gap-1">
            {[{ id: null, name: "все" }, ...layers].map((l) => (
              <button
                key={l.id ?? "all"}
                type="button"
                aria-pressed={layer === l.id}
                onClick={() => setLayer(l.id)}
                className={cn("h-6 cursor-pointer rounded-full border px-2 text-[11px] max-md:h-9", layer === l.id ? "border-accent bg-accent-soft text-accent-ink" : "border-line-strong bg-transparent text-ink-2")}
              >
                {l.name}
              </button>
            ))}
          </div>
          <ul aria-label="Типы для расстановки" className="m-0 min-h-0 flex-1 list-none overflow-y-auto p-0">
            {types.map((t) => (
              <TypeRow key={t.id} t={t} color={cat.layers.get(t.layer_id ?? "")?.color ?? "#607D8B"} active={placing === t.id} onPick={() => store.set({ placing: placing === t.id ? null : t.id, selection: [] })} />
            ))}
            {!types.length && <li className="px-1.5 py-2 text-[12px] text-ink-3">Ничего не нашлось.</li>}
          </ul>
          <p className="m-0 px-1.5 pt-1.5 text-[11px] text-ink-3">Перетащите на план — или выберите и щёлкните по плану (Shift — несколько раз).</p>
        </section>
      )}
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
        className={cn("flex w-full cursor-grab items-center gap-2 rounded-md border-0 px-1.5 py-1.5 text-left text-[13px] max-md:py-2.5", active ? "bg-accent-soft font-medium text-accent-ink" : "bg-transparent text-ink hover:bg-surface-2")}
      >
        <span className="size-3 shrink-0 rounded-sm border" style={{ background: `${color}55`, borderColor: color }} />
        <span className="min-w-0 flex-1 truncate">{t.name}</span>
        {mount && <span className="text-[10px] text-ink-3">{mount}</span>}
      </button>
    </li>
  );
}
