import { useQuery } from "@tanstack/react-query";
import { ArrowDownToLine, ArrowUpFromLine, MapPin, Plus, QrCode, Search, Truck, Warehouse as WarehouseIcon, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ApiError, get, post, query } from "@/lib/api";
import { cn } from "@/lib/cn";
import { PageBody } from "@/shell/Shell";
import { useCard } from "@/shell/context";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Field, FormError, Input } from "@/ui/form";
import { Card, Empty, Loading, PageHeader, SIDE_LIST, toPageTop } from "@/ui/misc";
import { StateChip, printLabels, useInvalidateInventory, usePlaceTree } from "./parts";
import { money, type Balance, type Doc, type PlaceRef, type UnitBrief } from "./types";

// 6.5.5: слева — места хранения, справа — что в выбранном месте
function lastBuilding(): string | null {
  try {
    return localStorage.getItem("building");
  } catch {
    return null;
  }
}

export function WarehousePage() {
  const tree = usePlaceTree();
  const [params, setParams] = useSearchParams();
  const place = params.get("place");
  const choose = (key: string) => {
    setParams((p) => {
      const out = new URLSearchParams(p);
      out.set("place", key);
      return out;
    });
    toPageTop();
  };
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState("");
  const [toggled, setToggled] = useState<Map<string, boolean>>(new Map());
  const q = search.trim().toLowerCase();
  const hit = (text: string) => !q || text.toLowerCase().includes(q);
  // открыто по умолчанию: здание, выбранное слева в «Здание», и где лежит выбранное место
  const selectedIn = useMemo(() => {
    const out = new Set<string>();
    for (const b of tree.data?.buildings ?? [])
      for (const f of b.floors)
        if (f.rooms.some((r) => r.key === place)) {
          out.add(b.id);
          out.add(f.id);
        }
    return out;
  }, [tree.data, place]);
  const isOpen = (id: string, byDefault: boolean) => toggled.get(id) ?? (q ? true : byDefault || selectedIn.has(id));
  const toggle = (id: string, now: boolean) => setToggled((m) => new Map(m).set(id, !now));
  const item = (key: string, title: string, sub = false) => (
    <button key={key} type="button" onClick={() => choose(key)} className={cn("flex w-full cursor-pointer items-center rounded-md border-0 px-2 py-1.5 text-left text-[13px] max-md:min-h-11 max-md:py-2.5", sub && "pl-6", place === key ? "bg-accent-soft font-medium text-accent-ink" : "bg-transparent text-ink hover:bg-surface-2")}>
      {title}
    </button>
  );
  const home = lastBuilding();
  const buildings = [...(tree.data?.buildings ?? [])].sort((x, y) => Number(y.id === home) - Number(x.id === home));
  const warehouses = (tree.data?.warehouses ?? []).filter((w) => hit(w.name) || w.cells.some((c) => hit(c.name)));
  return (
    <PageBody>
      <PageHeader
        title="Склад"
        subtitle="Места хранения и что в них числится"
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus /> Новый склад
          </Button>
        }
      />
      <div className="grid gap-6 md:grid-cols-[300px_1fr]">
        <nav aria-label="Места хранения" className={cn("flex flex-col gap-3", SIDE_LIST, place && "max-md:hidden")}>
          <label className="sticky top-0 z-10 flex h-9 shrink-0 items-center gap-2 rounded-lg border border-line-strong bg-surface px-2.5 max-md:h-11">
            <Search className="size-4 text-ink-3" />
            <input aria-label="Найти место" placeholder="Склад, ячейка, номер или название помещения" value={search} onChange={(e) => setSearch(e.target.value)} className="min-w-0 flex-1 border-0 bg-transparent text-sm outline-none" />
          </label>
          <section>
            <h3 className="m-0 mb-1 text-[12px] font-semibold tracking-wide text-ink-2 uppercase">Склады</h3>
            {warehouses.map((w) => (
              <div key={w.id}>
                {item(w.key, `Склад «${w.name}»`)}
                {w.cells.filter((c) => hit(c.name) || hit(w.name)).map((c) => item(c.key, c.name, true))}
              </div>
            ))}
            {!warehouses.length && <p className="m-0 px-2 text-[12px] text-ink-3">{q ? "Не нашлось." : "Складов нет."}</p>}
          </section>
          {buildings.map((b) => {
            const floors = b.floors
              .map((f) => ({ ...f, rooms: f.rooms.filter((r) => hit(r.title) || hit(b.name)) }))
              .filter((f) => !q || f.rooms.length);
            if (q && !floors.some((f) => f.rooms.length)) return null;
            const open = isOpen(b.id, b.id === home);
            return (
              <section key={b.id}>
                <button type="button" onClick={() => toggle(b.id, open)} aria-expanded={open} className="w-full cursor-pointer border-0 bg-transparent p-0 py-1 text-left text-[12px] font-semibold tracking-wide text-ink-2 uppercase max-md:min-h-11">
                  {open ? "▾" : "▸"} {b.name}
                </button>
                {open &&
                  floors.map((f) => {
                    const fOpen = isOpen(f.id, false);
                    return (
                      <div key={f.id}>
                        <button type="button" onClick={() => toggle(f.id, fOpen)} aria-expanded={fOpen} className="w-full cursor-pointer rounded-md border-0 bg-transparent px-2 py-1 text-left text-[13px] text-ink-2 hover:bg-surface-2 max-md:min-h-11">
                          {fOpen ? "▾" : "▸"} {f.name} <span className="text-[11px] text-ink-3">{f.rooms.length}</span>
                        </button>
                        {fOpen && f.rooms.map((r) => item(r.key, r.title, true))}
                      </div>
                    );
                  })}
              </section>
            );
          })}
        </nav>
        <div className={cn("min-w-0", !place && "max-md:hidden")}>
          {place ? (
            <PlaceView key={place} place={place} onBack={() => setParams({})} />
          ) : (
            <Card>
              <Empty title="Выберите место слева">Склад, ячейку или помещение — справа будет всё, что там числится, и кнопки «Принять», «Выдать», «Переместить».</Empty>
            </Card>
          )}
        </div>
      </div>
      <NewWarehouse open={creating} onClose={() => setCreating(false)} onCreated={(key) => choose(key)} />
    </PageBody>
  );
}

function PlaceView({ place, onBack }: { place: string; onBack: () => void }) {
  const navigate = useNavigate();
  const [, setCard] = useCard();
  const refresh = useInvalidateInventory();
  const tree = usePlaceTree();
  const data = useQuery({ queryKey: ["inventory", "place", place], queryFn: () => get<{ place: PlaceRef; units: UnitBrief[]; balances: Balance[] }>(`/api/inventory/place${query({ key: place })}`) });
  const [cell, setCell] = useState("");
  const [error, setError] = useState<string | null>(null);
  const open = async (kind: string, header: Record<string, unknown>) => {
    setError(null);
    try {
      const doc = await post<Doc>("/api/inventory/documents", { kind, header });
      navigate(`/documents/${doc.id}`);
    } catch (e) {
      setError((e as ApiError).message);
    }
  };
  if (data.isLoading) return <Loading />;
  if (!data.data) return <Empty title="Место не найдено" />;
  const p = data.data.place;
  const wh = tree.data?.warehouses.find((w) => w.id === p.warehouse_id);
  const total = data.data.units.reduce((s, u) => s + (u.value ?? 0), 0) + data.data.balances.reduce((s, b) => s + (b.amount ?? 0), 0);
  return (
    <div className="flex flex-col gap-4">
      <Button size="sm" variant="ghost" className="self-start md:hidden" onClick={onBack}>
        ← К местам
      </Button>
      <div className="flex flex-wrap items-center gap-2">
        <WarehouseIcon className="size-5 text-ink-2" />
        <h2 className="m-0 flex-1 text-xl font-semibold">{p.title}</h2>
        <Button size="sm" onClick={() => void open("receipt", { to_place: place })}>
          <ArrowDownToLine /> Принять
        </Button>
        <Button size="sm" onClick={() => void open("transfer", { from_place: place })}>
          <ArrowUpFromLine /> Выдать
        </Button>
        <Button size="sm" onClick={() => void open("transfer", { to_place: place })}>
          <Truck /> Переместить сюда
        </Button>
        <Button size="sm" onClick={() => void open("writeoff", { from_place: place })}>
          <XCircle /> Расход / списание
        </Button>
      </div>
      {p.room_id && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" asChild>
            <Link to={`/plan/${p.building_id}/${p.floor_id}?room=${p.room_id}&mode=place`}>
              <MapPin /> На плане
            </Link>
          </Button>
          {/* С10: метки на кабинет — на дверь (обход выбирает помещение по ней) и на вещи */}
          <Button size="sm" onClick={() => void printLabels({ room_ids: [p.room_id!], unit_ids: data.data!.units.map((u) => u.id) }).catch((e) => setError((e as Error).message))}>
            <QrCode /> Метки на помещение ({data.data.units.length + 1})
          </Button>
        </div>
      )}
      <FormError message={error} />
      <div className="text-[13px] text-ink-2">
        Единиц: {data.data.units.length}, позиций остатков: {data.data.balances.length}, остаточная стоимость: {money(total)}
      </div>
      <Card className="overflow-x-auto">
        <h3 className="m-0 border-b border-line px-4 py-2.5 text-sm font-semibold">Инвентарные единицы</h3>
        {data.data.units.length ? (
          <table className="w-full border-collapse text-[13px]">
            <tbody>
              {data.data.units.map((u) => (
                <tr key={u.id} className="cursor-pointer hover:bg-surface-2" onClick={() => setCard(`unit:${u.id}`)}>
                  <td className="border-b border-line px-3 py-2 font-mono">{u.number}</td>
                  <td className="border-b border-line px-3 py-2 font-medium">{u.title}</td>
                  <td className="border-b border-line px-3 py-2">
                    <StateChip state={u.state} />
                  </td>
                  <td className="border-b border-line px-3 py-2 font-mono">{money(u.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="m-0 px-4 py-3 text-[13px] text-ink-3">Нет.</p>
        )}
      </Card>
      <Card className="overflow-x-auto">
        <h3 className="m-0 border-b border-line px-4 py-2.5 text-sm font-semibold">Остатки</h3>
        {data.data.balances.length ? (
          <table className="w-full border-collapse text-[13px]">
            <tbody>
              {data.data.balances.map((b) => (
                <tr key={`${b.place}${b.type_id}${b.model_id}`}>
                  <td className="border-b border-line px-3 py-2 font-medium">
                    {b.type_name} <span className="font-normal text-ink-2">{b.model_name}</span>
                    {b.place !== place && <div className="text-[11px] text-ink-3">{b.place_title}</div>}
                  </td>
                  <td className="border-b border-line px-3 py-2 font-mono">
                    {b.qty.toLocaleString("ru-RU")} {b.unit}
                  </td>
                  <td className="border-b border-line px-3 py-2 font-mono">{money(b.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="m-0 px-4 py-3 text-[13px] text-ink-3">Нет.</p>
        )}
      </Card>
      {wh && p.kind === "warehouse" && (
        <Card className="flex flex-col gap-3 p-4">
          <h3 className="m-0 text-sm font-semibold">Ячейки склада</h3>
          <div className="flex flex-wrap gap-2">
            {wh.cells.map((c) => (
              <span key={c.id} className="rounded-md border border-line px-2 py-1 text-[13px]">
                {c.name}
              </span>
            ))}
            {!wh.cells.length && <span className="text-[13px] text-ink-3">Ячеек нет — склад одним местом.</span>}
          </div>
          <form
            className="flex max-w-md gap-2"
            onSubmit={async (e) => {
              e.preventDefault();
              if (!cell.trim()) return;
              try {
                await post(`/api/inventory/warehouses/${wh.id}/cells`, { name: cell.trim() });
                setCell("");
                refresh();
              } catch (err) {
                setError((err as ApiError).message);
              }
            }}
          >
            <Input aria-label="Новая ячейка" placeholder="Стеллаж 1, полка 2" value={cell} onChange={(e) => setCell(e.target.value)} />
            <Button type="submit">
              <Plus /> Ячейка
            </Button>
          </form>
          <Button size="sm" className="self-start" onClick={() => void printLabels({ codes: [wh.label_code, ...wh.cells.map((c) => c.label_code)] }).catch((e) => setError((e as Error).message))}>
            <QrCode /> Метки склада и ячеек
          </Button>
        </Card>
      )}
    </div>
  );
}

function NewWarehouse({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (key: string) => void }) {
  const refresh = useInvalidateInventory();
  const [name, setName] = useState("");
  const [room, setRoom] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title="Новый склад">
      <form
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            const wh = await post<{ key: string }>("/api/inventory/warehouses", { name, room_id: room ? room.slice(2) : null });
            refresh();
            setName("");
            setRoom(null);
            onClose();
            onCreated(wh.key);
          } catch (err) {
            setError(err as ApiError);
          }
        }}
      >
        <Field label="Название" error={error?.field === "name" ? error.message : undefined}>
          {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} required autoFocus placeholder="Основной" />}
        </Field>
        <Field label="Помещение" hint="Необязательно: склад может быть и вне здания.">
          {(p) => <PlaceRoomPicker id={p.id} value={room} onChange={setRoom} />}
        </Field>
        <FormError message={error && error.field !== "name" ? error.message : null} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Отмена</Button>
          <Button type="submit" variant="primary">
            Создать
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function PlaceRoomPicker({ value, onChange }: { id: string; value: string | null; onChange: (v: string | null) => void }) {
  const tree = usePlaceTree();
  return (
    <select aria-label="Помещение склада" value={value ?? ""} onChange={(e) => onChange(e.target.value || null)} className="h-9 rounded-lg border border-line-strong bg-surface px-2 text-sm">
      <option value="">вне здания</option>
      {tree.data?.buildings.flatMap((b) =>
        b.floors.map((f) => (
          <optgroup key={f.id} label={`${b.name} · ${f.name}`}>
            {f.rooms.map((r) => (
              <option key={r.key} value={r.key}>
                {r.title}
              </option>
            ))}
          </optgroup>
        )),
      )}
    </select>
  );
}
