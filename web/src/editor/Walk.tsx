// Обход с телефона (6.5.12, С10): упрощённая расстановка — помещение во весь экран,
// «Добавить» (поиск, недавние, ждущие расстановки), касание места на плане; сдвинуть,
// повернуть, убрать; отмеченное — «Поставить на учёт» с печатью меток. Помещение — на плане
// этажа или по QR-метке на двери. Строительство на телефоне недоступно.

import { CheckSquare, Plus, QrCode, RotateCcw, RotateCw, Search, Trash2, X, PackagePlus } from "lucide-react";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Link, useSearchParams } from "react-router";
import type { TypeBrief } from "@/catalog/types";
import { cn } from "@/lib/cn";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { normAngle } from "./items";
import { registrable, stockGap, type LinkUnit, type LinkView } from "./link";
import { placeable, requestRemove, type Catalog } from "./placement";
import type { Room } from "./plan";
import { useEditor, type EditorStore } from "./store";

const PHONE = "(max-width: 767px)";

export function useIsPhone() {
  return useSyncExternalStore(
    (on) => {
      const m = window.matchMedia(PHONE);
      m.addEventListener("change", on);
      return () => m.removeEventListener("change", on);
    },
    () => window.matchMedia(PHONE).matches,
  );
}

const RECENT = "recent-types";

function recentTypes(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT) ?? "[]") as string[];
  } catch {
    return [];
  }
}

function remember(typeId: string) {
  try {
    localStorage.setItem(RECENT, JSON.stringify([typeId, ...recentTypes().filter((t) => t !== typeId)].slice(0, 8)));
  } catch {
    /* не запомнится */
  }
}

const roomName = (r: Room) => [r.number, r.name].filter(Boolean).join(" ") || "без номера";

export function WalkBar({ store, cat, link, rooms, onRegister }: { store: EditorStore; cat: Catalog; link: LinkView | undefined; rooms: Room[]; onRegister: (ids: string[]) => void }) {
  const [params, setParams] = useSearchParams();
  const items = useEditor(store, (s) => s.items);
  const selection = useEditor(store, (s) => s.selection);
  const placing = useEditor(store, (s) => s.placing);
  const placingUnit = useEditor(store, (s) => s.placingUnit);
  const multi = useEditor(store, (s) => s.multiSelect);
  const [adding, setAdding] = useState(false);
  const bar = useRef<HTMLDivElement>(null);
  const sorted = useMemo(() => [...rooms].sort((a, b) => a.number.localeCompare(b.number, "ru", { numeric: true })), [rooms]);
  const roomId = params.get("room") ?? "";
  const room = rooms.find((r) => r.id === roomId);
  // помещение во весь экран — когда выбрали (или пришли по метке на двери)
  useEffect(() => {
    if (!room) return;
    const t = setTimeout(() => window.dispatchEvent(new CustomEvent("editor:fit-room", { detail: { outline: room.outline, bottom: bar.current?.offsetHeight ?? 0 } })), 80);
    return () => clearTimeout(t);
  }, [room]);
  const chooseRoom = (id: string) =>
    setParams((p) => {
      const out = new URLSearchParams(p);
      if (id) out.set("room", id);
      else out.delete("room");
      return out;
    }, { replace: true });

  const chosen = items.filter((i) => selection.some((s) => s.kind === "item" && s.id === i.id));
  const unlinked = registrable(link, chosen, cat);
  const turn = (by: number) => store.changeItems(store.state.items.map((i) => (chosen.some((c) => c.id === i.id) && !i.parent_id ? { ...i, angle: normAngle(i.angle + by) } : i)));
  const one = chosen.length === 1 ? chosen[0]! : null;
  const unit = one?.unit_id ? link?.units.find((u) => u.id === one.unit_id) : undefined;
  const placingName = placing ? cat.types.get(placing)?.name : null;

  return (
    <div ref={bar} className="absolute inset-x-0 bottom-0 z-20 flex flex-col gap-2 border-t border-line bg-surface/95 px-3 pt-2 pb-3 shadow-[0_-4px_16px_rgba(0,0,0,0.08)] backdrop-blur md:hidden" aria-label="Обход">
      <div className="flex items-center gap-2">
        <select aria-label="Помещение" value={roomId} onChange={(e) => chooseRoom(e.target.value)} className="h-11 min-w-0 flex-1 rounded-lg border border-line-strong bg-surface px-2 text-sm">
          <option value="">Весь этаж</option>
          {sorted.map((r) => (
            <option key={r.id} value={r.id}>
              {roomName(r)}
            </option>
          ))}
        </select>
        <Button asChild size="icon" aria-label="Помещение по метке на двери" title="Помещение по метке на двери">
          <Link to="/scan">
            <QrCode />
          </Link>
        </Button>
      </div>
      {placing ? (
        <div className="flex items-center gap-2">
          <p className="m-0 min-w-0 flex-1 text-[13px]">
            Коснитесь места на плане: <b>{placingName}</b>
            {placingUnit && link && <span className="text-ink-2"> № {link.units.find((u) => u.id === placingUnit)?.number}</span>}
          </p>
          <Button onClick={() => store.set({ placing: null, placingUnit: null })}>
            <X /> Отмена
          </Button>
        </div>
      ) : chosen.length ? (
        <>
          <p className="m-0 truncate text-[13px]">
            {one ? (cat.types.get(one.type_id)?.name ?? "Предмет") : `Выбрано: ${chosen.length}`}
            {unit && <span className="text-ink-2"> · № {unit.number}</span>}
            {one && !one.unit_id && <span className="text-ink-3">{stockGap(link, one, cat) === null ? " · не на учёте" : " · остатком"}</span>}
          </p>
          <div className="grid grid-cols-4 gap-2">
            <Button aria-label="Повернуть на 15° против часовой" onClick={() => turn(15)}>
              <RotateCcw /> 15°
            </Button>
            <Button aria-label="Повернуть на 90° по часовой" onClick={() => turn(-90)}>
              <RotateCw /> 90°
            </Button>
            <Button variant="danger" aria-label="Убрать" onClick={() => requestRemove(store, new Set(chosen.map((i) => i.id)), cat)}>
              <Trash2 />
            </Button>
            {unit ? (
              <Button asChild>
                <Link to={`?card=unit:${unit.id}`}>Карточка</Link>
              </Button>
            ) : (
              <Button variant="primary" disabled={!unlinked.length} onClick={() => onRegister(unlinked.map((i) => i.id))}>
                <PackagePlus /> На учёт
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant={multi ? "primary" : "ghost"} aria-pressed={multi} onClick={() => store.set({ multiSelect: !multi })}>
              <CheckSquare /> Несколько
            </Button>
            <Button size="sm" variant="ghost" onClick={() => store.set({ selection: [], multiSelect: false })}>
              Снять выбор
            </Button>
          </div>
        </>
      ) : (
        <div className="flex gap-2">
          <Button variant="primary" className="flex-1" onClick={() => setAdding(true)}>
            <Plus /> Добавить
          </Button>
          <Button variant={multi ? "primary" : "secondary"} aria-pressed={multi} onClick={() => store.set({ multiSelect: !multi })}>
            <CheckSquare /> Несколько
          </Button>
        </div>
      )}
      <AddSheet open={adding} onClose={() => setAdding(false)} store={store} cat={cat} link={link} roomId={roomId} />
    </div>
  );
}

// «Добавить»: ждущие расстановки в этом помещении, недавние типы, поиск по каталогу
function AddSheet({ open, onClose, store, cat, link, roomId }: { open: boolean; onClose: () => void; store: EditorStore; cat: Catalog; link: LinkView | undefined; roomId: string }) {
  const [q, setQ] = useState("");
  useEffect(() => {
    if (open) setQ("");
  }, [open]);
  const unplaced = useMemo(() => {
    const ids = new Set(link?.unplaced ?? []);
    const list = (link?.units ?? []).filter((u) => ids.has(u.id));
    return [...list.filter((u) => u.room_id === roomId), ...list.filter((u) => u.room_id !== roomId)].slice(0, 30);
  }, [link, roomId]);
  const recent = recentTypes()
    .map((id) => cat.types.get(id))
    .filter((t): t is TypeBrief => !!t && placeable(t));
  const query = q.trim().toLowerCase();
  const found = query ? [...cat.types.values()].filter((t) => placeable(t) && t.name.toLowerCase().includes(query)).sort((a, b) => a.name.localeCompare(b.name)).slice(0, 40) : [];
  const pick = (type: TypeBrief, unit?: LinkUnit) => {
    remember(type.id);
    store.set({ placing: type.id, placingUnit: unit?.id ?? null, selection: [], multiSelect: false });
    onClose();
  };
  const row = "flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-lg border-0 bg-transparent px-2 text-left text-sm hover:bg-surface-2";
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title="Добавить на план">
      <div className="flex flex-col gap-3">
        <label className="flex h-11 items-center gap-2 rounded-lg border border-line-strong bg-surface px-2.5">
          <Search className="size-4 text-ink-3" />
          <input aria-label="Поиск типа" placeholder="Что ставим: стол, кушетка, монитор…" value={q} onChange={(e) => setQ(e.target.value)} className="min-w-0 flex-1 border-0 bg-transparent text-sm outline-none" />
        </label>
        {query ? (
          <ul aria-label="Найдено в каталоге" className="m-0 list-none p-0">
            {found.map((t) => (
              <li key={t.id}>
                <button type="button" className={row} onClick={() => pick(t)}>
                  {t.name}
                </button>
              </li>
            ))}
            {!found.length && <li className="px-2 text-[13px] text-ink-3">Ничего не нашлось.</li>}
          </ul>
        ) : (
          <>
            {unplaced.length > 0 && (
              <section>
                <h3 className="m-0 mb-1 text-[12px] font-semibold tracking-wide text-ink-2 uppercase">Ждут расстановки</h3>
                <ul aria-label="Ждут расстановки" className="m-0 list-none p-0">
                  {unplaced.map((u) => {
                    const t = cat.types.get(u.type_id);
                    return (
                      <li key={u.id}>
                        <button type="button" className={row} disabled={!t} onClick={() => t && pick(t, u)}>
                          <span className="min-w-0 flex-1 truncate">
                            {t?.name ?? u.title} {u.number && <span className="font-mono text-[12px] text-ink-3">№ {u.number}</span>}
                          </span>
                          <span className={cn("text-[11px]", u.room_id === roomId ? "text-ok" : "text-ink-3")}>{u.room_id === roomId ? "здесь" : u.room_title}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}
            {recent.length > 0 && (
              <section>
                <h3 className="m-0 mb-1 text-[12px] font-semibold tracking-wide text-ink-2 uppercase">Недавние</h3>
                <ul aria-label="Недавние типы" className="m-0 list-none p-0">
                  {recent.map((t) => (
                    <li key={t.id}>
                      <button type="button" className={row} onClick={() => pick(t)}>
                        {t.name}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {!unplaced.length && !recent.length && <p className="m-0 text-[13px] text-ink-2">Найдите тип в каталоге поиском.</p>}
          </>
        )}
      </div>
    </Dialog>
  );
}
