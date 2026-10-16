import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, FileUp, Pencil, Plus, Trash2 } from "lucide-react";
import { Fragment, lazy, Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, api, get, patch, post, put } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { NumberField, Segmented, TextField } from "@/editor/Properties";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Field, FormError, Input } from "@/ui/form";
import { Chip, Loading } from "@/ui/misc";
import { transformOf, type ModelTransform } from "./model3d";
import { CharDialog, ValueInput, useInvalidateCatalog, useSerialPatch, useTree } from "./parts";
import { LEVELS, MOUNTS, rub, showValue, type Characteristic, type ModelInfo, type Mount, type TypeFull } from "./types";

const ModelPreview = lazy(() => import("./ModelPreview"));

type Tab = "main" | "view" | "chars" | "models";

export function TypeCard({ id, tab, onTab, onGone }: { id: string; tab: Tab; onTab: (t: Tab) => void; onGone: () => void }) {
  const me = useMe();
  const ro = me.role !== "admin";
  const t = useQuery({ queryKey: ["catalog-type", id], queryFn: () => get<TypeFull>(`/api/catalog/types/${id}`) });
  if (t.isLoading) return <Loading />;
  if (!t.data) return null;
  const d = t.data;
  const tabs: [Tab, string][] = [
    ["main", "Основное"],
    ["view", "Вид"],
    ["chars", `Характеристики (${d.characteristics.length})`],
    ["models", `Модели (${d.models.filter((m) => !m.archived).length})`],
  ];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="m-0 flex-1 text-xl font-semibold">{d.name}</h2>
        {d.archived && <Chip>в архиве</Chip>}
      </div>
      <div role="tablist" className="flex gap-1 border-b border-line">
        {tabs.map(([k, title]) => (
          <button
            key={k}
            role="tab"
            type="button"
            aria-selected={tab === k}
            onClick={() => onTab(k)}
            className={cn("-mb-px h-10 cursor-pointer border-0 border-b-2 bg-transparent px-3 text-sm max-md:h-11", tab === k ? "border-accent font-medium" : "border-transparent text-ink-2")}
          >
            {title}
          </button>
        ))}
      </div>
      {tab === "main" && <MainTab t={d} ro={ro} onGone={onGone} />}
      {tab === "view" && <ViewTab t={d} ro={ro} />}
      {tab === "chars" && <CharsTab t={d} ro={ro} />}
      {tab === "models" && <ModelsTab t={d} ro={ro} />}
    </div>
  );
}

function useTypeEdit(t: TypeFull) {
  const client = useQueryClient();
  return useSerialPatch<TypeFull>(`/api/catalog/types/${t.id}`, t.version, (next) => client.setQueryData(["catalog-type", t.id], next));
}

function MainTab({ t, ro, onGone }: { t: TypeFull; ro: boolean; onGone: () => void }) {
  const tree = useTree();
  const refresh = useInvalidateCatalog();
  const { set, error } = useTypeEdit(t);
  const layers = tree.data?.layers ?? [];
  const sets = tree.data?.sets ?? [];
  const grid = "grid grid-cols-2 gap-3 sm:grid-cols-3";
  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <TextField label="Название" value={t.name} disabled={ro} onChange={(name) => set({ name })} />
      <div className={grid}>
        <label className="flex flex-col gap-1 text-[12px] text-ink-2">
          Слой
          <select
            aria-label="Слой"
            disabled={ro}
            value={t.layer_id ?? ""}
            onChange={(e) => set({ layer_id: e.target.value || null, ...(e.target.value ? {} : { mount: "none" }) })}
            className="h-8 rounded-md border border-line-strong bg-surface px-2 text-[13px] text-ink max-md:h-11"
          >
            <option value="">без слоя — на план не ставится</option>
            {layers.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
        <NumberField label="Срок службы" unit="мес." value={t.life_months ?? 0} min={0} disabled={ro} onChange={(v) => set({ life_months: v || null })} />
        {"price" in t && <NumberField label="Ориентировочная цена" unit="₽" value={Number(t.price ?? 0)} min={0} digits={2} disabled={ro} onChange={(v) => set({ price: v })} />}
      </div>
      <Segmented<Mount> label="Установка" value={t.mount} disabled={ro} onChange={(mount) => set({ mount })} options={(Object.keys(MOUNTS) as Mount[]).map((m) => ({ value: m, title: MOUNTS[m] }))} />
      <div className={grid}>
        <NumberField label="Ширина" unit="мм" value={t.width ?? 0} min={0} disabled={ro} onChange={(v) => set({ width: v || null })} />
        <NumberField label="Глубина" unit="мм" value={t.depth ?? 0} min={0} disabled={ro} onChange={(v) => set({ depth: v || null })} />
        <NumberField label="Высота" unit="мм" value={t.height ?? 0} min={0} disabled={ro} onChange={(v) => set({ height: v || null })} />
        {(t.mount === "wall" || t.mount === "ceiling") && (
          <NumberField label={t.mount === "wall" ? "Высота установки" : "Высота установки (0 — под потолком)"} unit="мм" value={t.mount_height ?? 0} min={0} disabled={ro} onChange={(v) => set({ mount_height: v || null })} />
        )}
      </div>
      <Segmented label="Вид учёта" value={t.accounting} disabled={ro} onChange={(accounting) => set({ accounting })} options={[{ value: "piece", title: "поштучно — у каждой вещи номер" }, { value: "quantity", title: "количеством — остаток" }]} />
      <div className={grid}>
        <TextField label="Единица измерения" value={t.unit} disabled={ro} onChange={(unit) => set({ unit: unit || "шт." })} />
        <label className="flex items-center gap-2 self-end text-sm">
          <input type="checkbox" checked={t.container} disabled={ro} onChange={(e) => set({ container: e.target.checked })} /> может содержать другие (шкаф, стойка)
        </label>
      </div>
      <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
        <legend className="mb-1.5 p-0 text-[12px] text-ink-2">Наборы характеристик</legend>
        <div className="flex flex-wrap gap-2">
          {sets.map((s) => (
            <label key={s.id} className={cn("flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-[13px]", t.set_ids.includes(s.id) ? "border-accent bg-accent-soft" : "border-line-strong")}>
              <input
                type="checkbox"
                disabled={ro}
                checked={t.set_ids.includes(s.id)}
                onChange={(e) => set({ set_ids: e.target.checked ? [...t.set_ids, s.id] : t.set_ids.filter((x) => x !== s.id) })}
              />
              {s.name}
            </label>
          ))}
        </div>
      </fieldset>
      <FormError message={error?.message} />
      {!ro && (
        <div className="flex flex-wrap gap-2 border-t border-line pt-4">
          <Button
            size="sm"
            onClick={async () => {
              await post(`/api/catalog/types/${t.id}/${t.archived ? "unarchive" : "archive"}`);
              refresh();
            }}
          >
            {t.archived ? <ArchiveRestore /> : <Archive />} {t.archived ? "Вернуть из архива" : "В архив"}
          </Button>
          {!t.used && (
            <Button
              size="sm"
              variant="danger"
              onClick={async () => {
                await api("DELETE", `/api/catalog/types/${t.id}`);
                refresh();
                onGone();
              }}
            >
              <Trash2 /> Удалить
            </Button>
          )}
          <span className="self-center text-[12px] text-ink-3">{t.used ? `Используется: ${t.used} — можно только в архив.` : "Тип ещё нигде не используется."}</span>
        </div>
      )}
    </div>
  );
}

function ViewTab({ t, ro }: { t: TypeFull; ro: boolean }) {
  const refresh = useInvalidateCatalog();
  const file = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const { set, error: editError } = useTypeEdit(t);
  const tr = transformOf(t.model_transform);
  const setTransform = (patchT: Partial<ModelTransform>) => set({ model_transform: { ...tr, ...patchT } });
  const upload = async (f: File) => {
    setError(null);
    const form = new FormData();
    form.append("file", f);
    const r = await fetch(`/api/catalog/types/${t.id}/model3d`, { method: "POST", body: form, headers: { "X-Requested-With": "app" }, credentials: "same-origin" });
    const body = await r.json();
    if (!r.ok) setError(body?.error?.message ?? "Модель не загрузилась.");
    refresh();
  };
  // размер модели после поворота и масштаба — сравнение с габаритами типа (м)
  const size = rotatedSize(t.model_size, tr);
  const dims = [t.width, t.height, t.depth].map((v) => (v ? v / 1000 : null));
  const width = dims[0];
  const fitScale = size && width ? width / size[0] : null;
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_300px]">
      <div className="aspect-[4/3] overflow-hidden rounded-xl border border-line bg-surface-2">
        <Suspense fallback={<Loading />}>
          <ModelPreview url={t.model_url} transform={tr} box={[t.width ?? 500, t.height ?? 500, t.depth ?? 500]} />
        </Suspense>
      </div>
      <div className="flex flex-col gap-3">
        <input ref={file} type="file" accept=".glb" className="hidden" aria-label="Файл 3D-модели" onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
        {t.model_url ? (
          <>
            <div className="text-[13px]">
              {tr.fit ? (
                <>Модель вписана в габариты типа: <span className="font-mono">{dims.map((v) => (v ? v.toFixed(2) : "—")).join(" × ")} м</span></>
              ) : (
                <>
                  Модель: <span className="font-mono">{size?.map((v) => v.toFixed(2)).join(" × ")} м</span> (ширина × высота × глубина)
                  <br />
                  Габариты типа: <span className="font-mono">{dims.map((v) => (v ? v.toFixed(2) : "—")).join(" × ")} м</span>
                </>
              )}
              {t.model_credit && <span className="mt-1 block text-[12px] text-ink-3">Источник: {t.model_credit}</span>}
              <span className="mt-1 block text-[12px] text-ink-3">Синяя стрелка на полу — перед предмета (на плане — черта у края).</span>
            </div>
            {!tr.fit && size && width && Math.abs(size[0] - width) / width > 0.1 && (
              <p className="m-0 rounded-lg bg-warn-soft px-3 py-2 text-[13px] text-warn">Размер модели не совпадает с габаритами — поверните её или подгоните масштаб.</p>
            )}
            {!ro && (
              <>
                <div className="flex flex-col gap-1 text-[12px] text-ink-2">
                  Повернуть на 90°
                  <div className="flex gap-1.5">
                    {(["rx", "ry", "rz"] as const).map((axis) => (
                      <Button key={axis} size="sm" onClick={() => void setTransform({ [axis]: ((tr[axis] ?? 0) + 90) % 360 })}>
                        {axis === "rx" ? "вокруг X" : axis === "ry" ? "вокруг Y" : "вокруг Z"}
                      </Button>
                    ))}
                  </div>
                </div>
                <label className="flex items-center gap-2 text-[13px]">
                  <input type="checkbox" checked={tr.fit} onChange={(e) => void setTransform({ fit: e.target.checked })} /> Вписать в габариты типа (растянуть по осям)
                </label>
                {!tr.fit && <NumberField label="Масштаб" value={tr.scale} digits={3} min={0.0001} onChange={(scale) => void setTransform({ scale })} />}
                {!tr.fit && fitScale && Math.abs(fitScale - 1) > 0.01 && (
                  <Button size="sm" onClick={() => void setTransform({ scale: Number((tr.scale * fitScale).toFixed(4)) })}>
                    Подогнать по ширине (×{fitScale.toFixed(3)})
                  </Button>
                )}
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => file.current?.click()}>
                    <FileUp /> Заменить
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={async () => {
                      await api("DELETE", `/api/catalog/types/${t.id}/model3d`);
                      refresh();
                    }}
                  >
                    Убрать
                  </Button>
                </div>
              </>
            )}
          </>
        ) : (
          <>
            <p className="m-0 text-[13px] text-ink-2">3D-модели нет — в 3D тип показывается коробкой по габаритам в цвете слоя.</p>
            {!ro && (
              <Button size="sm" onClick={() => file.current?.click()}>
                <FileUp /> Загрузить GLB
              </Button>
            )}
          </>
        )}
        <FormError message={error ?? editError?.message} />
        <Segmented
          label="Вид сверху на плане"
          value={t.top_view}
          disabled={ro}
          onChange={(top_view) => void set({ top_view })}
          options={[
            { value: "box", title: "контур по габаритам" },
            { value: "icon", title: "значок" },
          ]}
        />
      </div>
    </div>
  );
}

const empty = (v: unknown) => v === null || v === undefined || v === "";

function rotatedSize(size: [number, number, number] | null, tr: ModelTransform): [number, number, number] | null {
  if (!size) return null;
  let [x, y, z] = size;
  // повороты на 90° переставляют оси
  if ((tr.rx / 90) % 2) [y, z] = [z, y];
  if ((tr.ry / 90) % 2) [x, z] = [z, x];
  if ((tr.rz / 90) % 2) [x, y] = [y, x];
  return [x * tr.scale, y * tr.scale, z * tr.scale];
}

function CharsTab({ t, ro }: { t: TypeFull; ro: boolean }) {
  const tree = useTree();
  const refresh = useInvalidateCatalog();
  const [dialog, setDialog] = useState<Characteristic | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const setName = (c: Characteristic) => (c.set_id ? tree.data?.sets.find((s) => s.id === c.set_id)?.name : "свои");
  const groups = new Map<string, Characteristic[]>();
  for (const c of t.characteristics) groups.set(setName(c) ?? "", [...(groups.get(setName(c) ?? "") ?? []), c]);
  const setValue = async (c: Characteristic, value: unknown) => {
    setError(null);
    try {
      await put(`/api/catalog/types/${t.id}/values`, { values: { [c.id]: value } });
      refresh();
    } catch (e) {
      setError((e as ApiError).message);
    }
  };
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      {[...groups].map(([group, chars]) => (
        <section key={group} className="flex flex-col gap-2">
          <h3 className="m-0 text-sm font-semibold">{group === "свои" ? "Свои характеристики типа" : `Набор «${group}»`}</h3>
          <table className="w-full border-collapse text-[13px]">
            <tbody>
              {chars.map((c) => (
                <tr key={c.id} className="border-b border-line">
                  <td className="w-1/2 py-2 pr-3">
                    {c.name}
                    {c.unit && <span className="text-ink-3">, {c.unit}</span>}
                    {c.required && <span className="text-bad"> *</span>}
                    <div className="text-[11px] text-ink-3">{LEVELS[c.level]}</div>
                  </td>
                  <td className="py-2">
                    {c.level === "type" ? (
                      <>
                        {ro ? showValue(c, t.values[c.id]) : <ValueInput c={c} value={t.values[c.id]} onChange={(v) => void setValue(c, v)} />}
                        {c.required && empty(t.values[c.id]) && <div className="pt-1 text-[11px] text-warn">обязательная — не заполнена</div>}
                      </>
                    ) : (
                      <span className="text-ink-3">{c.level === "model" ? "задаётся у модели" : "задаётся у каждой вещи"}</span>
                    )}
                  </td>
                  {!ro && c.type_id && (
                    <td className="w-10 py-2">
                      <Button size="icon" variant="ghost" aria-label={`Изменить ${c.name}`} onClick={() => setDialog(c)}>
                        <Pencil />
                      </Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      {!t.characteristics.length && <p className="m-0 text-[13px] text-ink-2">Характеристик нет. Подключите набор на вкладке «Основное» или добавьте свою.</p>}
      <FormError message={error} />
      {!ro && (
        <div>
          <Button size="sm" onClick={() => setDialog("new")}>
            <Plus /> Своя характеристика
          </Button>
        </div>
      )}
      <CharDialog open={dialog !== null} onOpenChange={(o) => !o && setDialog(null)} owner={{ type_id: t.id }} editing={dialog === "new" ? null : dialog} />
    </div>
  );
}

function ModelsTab({ t, ro }: { t: TypeFull; ro: boolean }) {
  const refresh = useInvalidateCatalog();
  const [dialog, setDialog] = useState<ModelInfo | "new" | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const modelChars = t.characteristics.filter((c) => c.level === "model");
  const missing = (m: ModelInfo) => modelChars.filter((c) => c.required && empty(m.values[c.id])).length;
  const [error, setError] = useState<string | null>(null);
  const setValue = async (m: ModelInfo, c: Characteristic, value: unknown) => {
    setError(null);
    try {
      await put(`/api/catalog/models/${m.id}/values`, { values: { [c.id]: value } });
      refresh();
    } catch (e) {
      setError((e as ApiError).message);
    }
  };
  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 text-[13px] text-ink-2">Модель — конкретная марка у производителя со своей ценой. Необязательна: можно ставить и учитывать просто тип.</p>
      {t.models.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="text-left text-xs text-ink-2">
                {["Производитель", "Модель", "Артикул", "Поставщик", ...("price" in t ? ["Цена"] : []), ""].map((h) => (
                  <th key={h} className="border-b border-line px-3 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {t.models.map((m) => (
                <Fragment key={m.id}>
                  <tr className={cn("cursor-pointer hover:bg-surface-2", m.archived && "text-ink-3")} onClick={() => setOpen(open === m.id ? null : m.id)}>
                    <td className="border-b border-line px-3 py-2">{m.manufacturer || "—"}</td>
                    <td className="border-b border-line px-3 py-2 font-medium">
                      {m.name} {m.archived && <Chip>в архиве</Chip>}
                      {missing(m) > 0 && <Chip tone="warn">не заполнено обязательных: {missing(m)}</Chip>}
                    </td>
                    <td className="border-b border-line px-3 py-2">{m.article || "—"}</td>
                    <td className="border-b border-line px-3 py-2">{m.supplier || "—"}</td>
                    {"price" in t && <td className="border-b border-line px-3 py-2 font-mono">{rub(m.price)}</td>}
                    <td className="border-b border-line px-3 py-2 text-right">
                      {!ro && (
                        <Button size="icon" variant="ghost" aria-label={`Изменить ${m.name}`} onClick={(e) => (e.stopPropagation(), setDialog(m))}>
                          <Pencil />
                        </Button>
                      )}
                    </td>
                  </tr>
                  {open === m.id && modelChars.length > 0 && (
                    <tr>
                      <td colSpan={6} className="border-b border-line bg-surface-2 px-3 py-3">
                        <div className="grid gap-2 sm:grid-cols-2">
                          {modelChars.map((c) => (
                            <label key={c.id} className="flex flex-col gap-1 text-[12px] text-ink-2">
                              {c.name}
                              {c.unit ? `, ${c.unit}` : ""}
                              {ro ? <span className="text-[13px] text-ink">{showValue(c, m.values[c.id])}</span> : <ValueInput c={c} value={m.values[c.id]} onChange={(v) => void setValue(m, c, v)} />}
                            </label>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <FormError message={error} />
      {!ro && (
        <div>
          <Button size="sm" onClick={() => setDialog("new")}>
            <Plus /> Новая модель
          </Button>
        </div>
      )}
      <ModelDialog typeId={t.id} model={dialog === "new" ? null : dialog} open={dialog !== null} onClose={() => setDialog(null)} showPrice={"price" in t} />
    </div>
  );
}

function ModelDialog({ typeId, model, open, onClose, showPrice }: { typeId: string; model: ModelInfo | null; open: boolean; onClose: () => void; showPrice: boolean }) {
  const refresh = useInvalidateCatalog();
  const [form, setForm] = useState({ manufacturer: "", name: "", article: "", supplier: "", price: "" });
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    if (!open) return;
    setError(null);
    setForm(model ? { manufacturer: model.manufacturer, name: model.name, article: model.article, supplier: model.supplier, price: model.price != null ? String(model.price) : "" } : { manufacturer: "", name: "", article: "", supplier: "", price: "" });
  }, [open, model]);
  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, price: form.price ? Number(form.price.replace(",", ".")) : null };
      return model ? patch(`/api/catalog/models/${model.id}`, { ...body, version: model.version }) : post(`/api/catalog/types/${typeId}/models`, body);
    },
    onSuccess: () => {
      refresh();
      onClose();
    },
    onError: (e) => setError(e as ApiError),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title={model ? "Модель" : "Новая модель"}>
      <form className="flex flex-col gap-4" onSubmit={submit}>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Производитель">{(p) => <Input {...p} value={form.manufacturer} onChange={(e) => setForm({ ...form, manufacturer: e.target.value })} />}</Field>
          <Field label="Модель" error={error?.field === "name" ? error.message : undefined}>
            {(p) => <Input {...p} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />}
          </Field>
          <Field label="Артикул">{(p) => <Input {...p} value={form.article} onChange={(e) => setForm({ ...form, article: e.target.value })} />}</Field>
          <Field label="Поставщик">{(p) => <Input {...p} value={form.supplier} onChange={(e) => setForm({ ...form, supplier: e.target.value })} />}</Field>
          {showPrice && <Field label="Цена, ₽">{(p) => <Input {...p} inputMode="decimal" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} />}</Field>}
        </div>
        <FormError message={error && error.field !== "name" ? error.message : null} />
        <div className="flex justify-end gap-2">
          {model && (
            <Button
              onClick={async () => {
                await post(`/api/catalog/models/${model.id}/${model.archived ? "unarchive" : "archive"}`);
                refresh();
                onClose();
              }}
            >
              {model.archived ? "Вернуть из архива" : "В архив"}
            </Button>
          )}
          <Button onClick={onClose}>Отмена</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            Сохранить
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
