import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, Download, FileUp, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { ApiError, api, patch, post } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { PageBody } from "@/shell/Shell";
import { useCardTitle } from "@/shell/context";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Field, FormError, Input } from "@/ui/form";
import { Card, Chip, Empty, Loading, PageHeader, SIDE_LIST, toPageTop } from "@/ui/misc";
import { CharDialog, DeferredInput, useInvalidateCatalog, useSerialPatch, useTree } from "./parts";
import { TypeCard } from "./TypeCard";
import { KINDS, LEVELS, type CharSet, type Characteristic, type Layer, type TypeBrief } from "./types";

type Section = "types" | "sets" | "layers";
type TypeTab = "main" | "view" | "chars" | "models";

// 6.5.9: слева дерево «слой → тип» с поиском, справа карточка типа; наборы характеристик
// и слои — своими вкладками. Адрес: ?section=…&type=<id>&tab=…
export function CatalogPage() {
  const [params, setParams] = useSearchParams();
  const section = (params.get("section") as Section) || "types";
  const go = (values: Record<string, string | null>) =>
    setParams((p) => {
      const out = new URLSearchParams(p);
      for (const [k, v] of Object.entries(values)) {
        if (v) out.set(k, v);
        else out.delete(k);
      }
      return out;
    });
  const [importing, setImporting] = useState(false);
  const sections: [Section, string][] = [
    ["types", "Типы"],
    ["sets", "Наборы характеристик"],
    ["layers", "Слои"],
  ];
  return (
    <PageBody>
      <PageHeader
        title="Каталог"
        subtitle="Слои, типы, модели и их характеристики — общие для планировки и учёта"
        actions={
          <>
            <Button onClick={() => setImporting(true)}>
              <FileUp /> Загрузить из Excel
            </Button>
            <Button asChild>
              <a href="/api/catalog/export.xlsx" download>
                <Download /> Выгрузить в Excel
              </a>
            </Button>
          </>
        }
      />
      <div role="tablist" aria-label="Разделы каталога" className="flex gap-1 border-b border-line">
        {sections.map(([k, title]) => (
          <button
            key={k}
            role="tab"
            type="button"
            aria-selected={section === k}
            onClick={() => go({ section: k === "types" ? null : k })}
            className={cn("-mb-px h-10 cursor-pointer border-0 border-b-2 bg-transparent px-3 text-sm max-md:h-11", section === k ? "border-accent font-medium" : "border-transparent text-ink-2")}
          >
            {title}
          </button>
        ))}
      </div>
      {section === "types" && <TypesSection typeId={params.get("type")} tab={(params.get("tab") as TypeTab) || "main"} go={go} />}
      {section === "sets" && <SetsSection />}
      {section === "layers" && <LayersSection />}
      <ImportDialog open={importing} onClose={() => setImporting(false)} />
    </PageBody>
  );
}

function TypesSection({ typeId, tab, go }: { typeId: string | null; tab: TypeTab; go: (v: Record<string, string | null>) => void }) {
  const me = useMe();
  const [archived, setArchived] = useState(false);
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const tree = useTree(archived);
  const selected = tree.data?.types.find((t) => t.id === typeId);
  useCardTitle(selected?.name);
  const groups = useMemo(() => {
    if (!tree.data) return [];
    const q = search.trim().toLowerCase();
    const match = (t: TypeBrief) => !q || t.name.toLowerCase().includes(q);
    const out: { layer: Layer | null; types: TypeBrief[] }[] = tree.data.layers.map((l) => ({ layer: l, types: tree.data.types.filter((t) => t.layer_id === l.id && match(t)) }));
    out.push({ layer: null, types: tree.data.types.filter((t) => !t.layer_id && match(t)) });
    return out.filter((g) => g.types.length || (!q && g.layer));
  }, [tree.data, search]);
  if (tree.isLoading) return <Loading />;
  return (
    <div className="grid gap-6 md:grid-cols-[300px_1fr]">
      <div className={cn("flex flex-col gap-3", SIDE_LIST, typeId && "max-md:hidden")}>
        <label className="sticky top-0 z-10 flex h-9 shrink-0 items-center gap-2 rounded-lg border border-line-strong bg-surface px-2.5 max-md:h-11">
          <Search className="size-4 text-ink-3" />
          <input aria-label="Поиск типа" placeholder="Поиск типа" value={search} onChange={(e) => setSearch(e.target.value)} className="min-w-0 flex-1 border-0 bg-transparent text-sm outline-none" />
        </label>
        <div className="flex items-center justify-between gap-2">
          <label className="flex items-center gap-2 text-[13px] text-ink-2">
            <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> с архивом
          </label>
          {me.role === "admin" && (
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus /> Тип
            </Button>
          )}
        </div>
        <nav aria-label="Типы по слоям" className="flex flex-col gap-3">
          {groups.map((g) => (
            <section key={g.layer?.id ?? "none"} className="flex flex-col">
              <h3 className="m-0 mb-1 flex items-center gap-2 text-[12px] font-semibold tracking-wide text-ink-2 uppercase">
                <span className="size-2.5 rounded-full" style={{ background: g.layer?.color ?? "#9aa4b2" }} />
                {g.layer?.name ?? "Без слоя"}
                <span className="font-normal text-ink-3">{g.types.length}</span>
              </h3>
              {g.types.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => {
                    go({ type: t.id, tab: null });
                    toPageTop();
                  }}
                  className={cn(
                    "flex cursor-pointer items-center gap-2 rounded-md border-0 px-2 py-1.5 text-left text-[13px] max-md:py-2.5",
                    t.id === typeId ? "bg-accent-soft font-medium text-accent-ink" : "bg-transparent text-ink hover:bg-surface-2",
                    t.archived && "text-ink-3",
                  )}
                >
                  <span className="min-w-0 flex-1 truncate">{t.name}</span>
                  {t.model_url && <span className="text-[11px] text-ink-3">3D</span>}
                  {t.archived && <span className="text-[11px]">архив</span>}
                </button>
              ))}
            </section>
          ))}
          {!groups.length && <p className="m-0 text-[13px] text-ink-2">Ничего не нашлось.</p>}
        </nav>
      </div>
      <div className={cn("min-w-0", !typeId && "max-md:hidden")}>
        {typeId ? (
          <>
            <Button size="sm" variant="ghost" className="mb-2 md:hidden" onClick={() => go({ type: null, tab: null })}>
              <ArrowLeft /> К списку
            </Button>
            <TypeCard key={typeId} id={typeId} tab={tab} onTab={(t) => go({ tab: t === "main" ? null : t })} onGone={() => go({ type: null, tab: null })} />
          </>
        ) : (
          <Card>
            <Empty title="Выберите тип слева">
              Тип — вид предмета: «Кушетка», «Камера», «Светильник». У типа — слой, габариты, способ установки, 3D-модель, характеристики и модели.
            </Empty>
          </Card>
        )}
      </div>
      <NewTypeDialog open={creating} onClose={() => setCreating(false)} layers={tree.data?.layers ?? []} onCreated={(id) => go({ type: id, tab: null })} />
    </div>
  );
}

function NewTypeDialog({ open, onClose, layers, onCreated }: { open: boolean; onClose: () => void; layers: Layer[]; onCreated: (id: string) => void }) {
  const refresh = useInvalidateCatalog();
  const [name, setName] = useState("");
  const [layer, setLayer] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const create = useMutation({
    mutationFn: () => post<{ id: string }>("/api/catalog/types", { name, layer_id: layer || null, ...(layer ? {} : { mount: "none" }) }),
    onSuccess: (t) => {
      refresh();
      setName("");
      onClose();
      onCreated(t.id);
    },
    onError: (e) => setError(e as ApiError),
  });
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title="Новый тип">
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Field label="Название" error={error?.field === "name" ? error.message : undefined}>
          {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} required autoFocus placeholder="Кушетка смотровая" />}
        </Field>
        <Field label="Слой" hint="Без слоя тип не ставится на план — только учитывается (расходные материалы).">
          {(p) => (
            <select {...p} value={layer} onChange={(e) => setLayer(e.target.value)} className="h-9 rounded-lg border border-line-strong bg-surface px-2 text-sm max-md:h-11">
              <option value="">без слоя</option>
              {layers.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <FormError message={error && error.field !== "name" ? error.message : null} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Отмена</Button>
          <Button type="submit" variant="primary" disabled={create.isPending}>
            Создать
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

// ------------------------------------------------------------------ наборы характеристик

function SetsSection() {
  const me = useMe();
  const ro = me.role !== "admin";
  const tree = useTree();
  const refresh = useInvalidateCatalog();
  const [dialog, setDialog] = useState<{ set: CharSet; char: Characteristic | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  if (tree.isLoading || !tree.data) return <Loading />;
  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      refresh();
    } catch (e) {
      setError((e as ApiError).message);
    }
  };
  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 max-w-3xl text-[13px] text-ink-2">
        Набор — характеристики, общие для нескольких типов («Электрооборудование»: мощность, напряжение). Набор подключается к типу на его вкладке «Основное».
      </p>
      <FormError message={error} />
      {tree.data.sets.map((s) => (
        <Card key={s.id} className="flex flex-col gap-3 p-4">
          <div className="flex flex-wrap items-center gap-3">
            {ro ? (
              <h3 className="m-0 text-base font-semibold">{s.name}</h3>
            ) : (
              <DeferredInput
                label="Название набора"
                value={s.name}
                onCommit={(v) => v && void act(() => patch(`/api/catalog/sets/${s.id}`, { name: v, version: s.version }))}
                className="h-8 min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-1 text-base font-semibold hover:border-line-strong focus:border-line-strong"
              />
            )}
            <Chip>{s.types ? `в ${s.types} типах` : "не подключён"}</Chip>
            {!ro && (
              <Button size="icon" variant="ghost" aria-label={`Удалить набор ${s.name}`} onClick={() => void act(() => api("DELETE", `/api/catalog/sets/${s.id}`))}>
                <Trash2 />
              </Button>
            )}
          </div>
          {s.characteristics.length > 0 && (
            <table className="w-full border-collapse text-[13px]">
              <tbody>
                {s.characteristics.map((c) => (
                  <tr key={c.id} className="border-t border-line">
                    <td className="py-2 pr-3">
                      {c.name}
                      {c.unit && <span className="text-ink-3">, {c.unit}</span>}
                      {c.required && <span className="text-bad"> *</span>}
                    </td>
                    <td className="py-2 pr-3 text-ink-2">
                      {KINDS[c.kind]}
                      {c.kind === "choice" && c.choices.length > 0 && `: ${c.choices.join(" / ")}`}
                    </td>
                    <td className="py-2 pr-3 text-ink-2">{LEVELS[c.level]}</td>
                    <td className="w-10 py-2">
                      {!ro && (
                        <Button size="icon" variant="ghost" aria-label={`Изменить ${c.name}`} onClick={() => setDialog({ set: s, char: c })}>
                          <Pencil />
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {!ro && (
            <div>
              <Button size="sm" onClick={() => setDialog({ set: s, char: null })}>
                <Plus /> Характеристика
              </Button>
            </div>
          )}
        </Card>
      ))}
      {!ro && (
        <form
          className="flex max-w-md gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) void act(() => post("/api/catalog/sets", { name: name.trim() })).then(() => setName(""));
          }}
        >
          <Input aria-label="Название нового набора" placeholder="Новый набор" value={name} onChange={(e) => setName(e.target.value)} />
          <Button type="submit">
            <Plus /> Добавить
          </Button>
        </form>
      )}
      <CharDialog open={dialog !== null} onOpenChange={(o) => !o && setDialog(null)} owner={{ set_id: dialog?.set.id }} editing={dialog?.char ?? null} />
    </div>
  );
}

// ------------------------------------------------------------------ слои

function LayersSection() {
  const me = useMe();
  const ro = me.role !== "admin";
  const tree = useTree();
  const refresh = useInvalidateCatalog();
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  if (tree.isLoading || !tree.data) return <Loading />;
  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      refresh();
    } catch (e) {
      setError((e as ApiError).message);
    }
  };
  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 max-w-3xl text-[13px] text-ink-2">
        Слой группирует типы по назначению: мебель, видеонаблюдение, освещение. Слои на плане включаются и выключаются; новый слой добавляется здесь, без доработки системы.
      </p>
      <FormError message={error} />
      <Card className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="text-left text-xs text-ink-2">
              {["Цвет", "Слой", "Примечание", "Типов", "Виден сразу", ""].map((h) => (
                <th key={h} className="border-b border-line px-3 py-2 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tree.data.layers.map((l) => (
              <LayerRow key={l.id} l={l} ro={ro} onDelete={() => void act(() => api("DELETE", `/api/catalog/layers/${l.id}`))} />
            ))}
          </tbody>
        </table>
      </Card>
      {!ro && (
        <form
          className="flex max-w-md gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) void act(() => post("/api/catalog/layers", { name: name.trim() })).then(() => setName(""));
          }}
        >
          <Input aria-label="Название нового слоя" placeholder="Новый слой" value={name} onChange={(e) => setName(e.target.value)} />
          <Button type="submit">
            <Plus /> Добавить
          </Button>
        </form>
      )}
    </div>
  );
}

function LayerRow({ l, ro, onDelete }: { l: Layer; ro: boolean; onDelete: () => void }) {
  const { set, error } = useSerialPatch<Layer>(`/api/catalog/layers/${l.id}`, l.version);
  return (
    <>
      <tr>
        <td className="w-14 border-b border-line px-3 py-2">
          <ColorInput label={`Цвет слоя ${l.name}`} disabled={ro} value={l.color} onCommit={(color) => void set({ color })} />
        </td>
        <td className="border-b border-line px-3 py-2">
          <DeferredInput label="Название слоя" disabled={ro} value={l.name} onCommit={(v) => v && void set({ name: v })} className="h-8 w-full rounded-md border border-transparent bg-transparent px-1 font-medium hover:border-line-strong focus:border-line-strong" />
        </td>
        <td className="border-b border-line px-3 py-2">
          <DeferredInput label={`Примечание к слою ${l.name}`} disabled={ro} value={l.note} onCommit={(v) => void set({ note: v })} className="h-8 w-full rounded-md border border-transparent bg-transparent px-1 text-ink-2 hover:border-line-strong focus:border-line-strong" />
        </td>
        <td className="border-b border-line px-3 py-2 font-mono">{l.types}</td>
        <td className="border-b border-line px-3 py-2">
          <input type="checkbox" aria-label={`Слой ${l.name} виден сразу`} disabled={ro} checked={l.visible} onChange={(e) => void set({ visible: e.target.checked })} />
        </td>
        <td className="w-10 border-b border-line px-3 py-2">
          {!ro && !l.types && (
            <Button size="icon" variant="ghost" aria-label={`Удалить слой ${l.name}`} onClick={onDelete}>
              <Trash2 />
            </Button>
          )}
        </td>
      </tr>
      {error && (
        <tr>
          <td colSpan={6} className="px-3 pb-2">
            <FormError message={error.message} />
          </td>
        </tr>
      )}
    </>
  );
}

// Цвет сохраняется, когда палитра закрыта (событие change), а не на каждом её движении
function ColorInput({ label, value, onCommit, disabled }: { label: string; value: string; onCommit: (v: string) => void; disabled?: boolean }) {
  const ref = useRef<HTMLInputElement>(null);
  const commit = useRef(onCommit);
  commit.current = onCommit;
  useEffect(() => {
    const input = ref.current;
    if (!input) return;
    input.value = value.toLowerCase();
    const changed = () => input.value !== value.toLowerCase() && commit.current(input.value);
    input.addEventListener("change", changed);
    return () => input.removeEventListener("change", changed);
  }, [value]);
  return <input ref={ref} type="color" aria-label={label} disabled={disabled} defaultValue={value.toLowerCase()} className="h-7 w-9 cursor-pointer border-0 bg-transparent p-0" />;
}

// ------------------------------------------------------------------ загрузка из Excel (5.2.6)

interface Report {
  created: Record<string, string[]>;
  updated: Record<string, string[]>;
  errors: { sheet: string; row: number | null; message: string }[];
  ok: boolean;
  applied: boolean;
}

async function sendImport(file: File, apply: boolean): Promise<Report> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(`/api/catalog/import${apply ? "?apply=true" : ""}`, { method: "POST", body: form, headers: { "X-Requested-With": "app" }, credentials: "same-origin" });
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(r.status, body?.error?.code ?? "http", body?.error?.message ?? "Файл не загрузился.");
  return body as Report;
}

function ImportDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const refresh = useInvalidateCatalog();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const reset = () => {
    setFile(null);
    setReport(null);
    setError(null);
  };
  const run = async (f: File, apply: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = await sendImport(f, apply);
      setReport(r);
      if (r.applied) refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const count = (b: Record<string, string[]>) => Object.values(b).reduce((n, x) => n + x.length, 0);
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          reset();
          onClose();
        }
      }}
      title="Загрузить каталог из Excel"
    >
      <div className="flex flex-col gap-4">
        <p className="m-0 text-[13px] text-ink-2">
          Файл того же вида, что выгрузка каталога. Сначала он проверяется и показывается, что изменится; загружается целиком или никак. Записи узнаются по названию: новые добавятся, существующие обновятся, остальное не тронется.
        </p>
        <input
          ref={input}
          type="file"
          accept=".xlsx"
          aria-label="Файл каталога"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (!f) return;
            setFile(f);
            setReport(null);
            void run(f, false);
          }}
        />
        <div className="flex items-center gap-2">
          <Button onClick={() => input.current?.click()} disabled={busy}>
            <FileUp /> {file ? "Другой файл" : "Выбрать файл"}
          </Button>
          {file && <span className="truncate text-[13px] text-ink-2">{file.name}</span>}
        </div>
        {busy && <p className="m-0 text-[13px] text-ink-2">Проверяю…</p>}
        <FormError message={error} />
        {report && !busy && (
          <div className="flex flex-col gap-3 text-[13px]">
            {report.applied ? (
              <p className="m-0 rounded-lg bg-ok-soft px-3 py-2 text-ok">Каталог загружен.</p>
            ) : report.ok && !count(report.created) && !count(report.updated) ? (
              <p className="m-0 rounded-lg bg-ok-soft px-3 py-2 text-ok">Ошибок нет, и каталог уже такой же — загружать нечего.</p>
            ) : report.ok ? (
              <p className="m-0 rounded-lg bg-accent-soft px-3 py-2">Ошибок нет. Будет добавлено: {count(report.created)}, обновлено: {count(report.updated)}.</p>
            ) : (
              <p className="m-0 rounded-lg bg-bad-soft px-3 py-2 text-bad">Найдены ошибки ({report.errors.length}) — каталог не изменится, пока они не исправлены в файле.</p>
            )}
            {report.errors.length > 0 && (
              <ul className="m-0 max-h-48 list-none overflow-y-auto p-0">
                {report.errors.map((e, i) => (
                  <li key={i} className="border-b border-line py-1.5">
                    <span className="text-ink-2">
                      {e.sheet}
                      {e.row ? `, строка ${e.row}` : ""}:
                    </span>{" "}
                    {e.message}
                  </li>
                ))}
              </ul>
            )}
            {(["created", "updated"] as const).map((bucket) =>
              Object.entries(report[bucket]).length ? (
                <div key={bucket} className="flex flex-col gap-1">
                  <div className="font-medium">{bucket === "created" ? "Добавится" : "Обновится"}</div>
                  {Object.entries(report[bucket]).map(([kind, names]) => (
                    <details key={kind}>
                      <summary className="cursor-pointer">
                        {kind}: {names.length}
                      </summary>
                      <div className="pt-1 pl-4 text-ink-2">{names.join(", ")}</div>
                    </details>
                  ))}
                </div>
              ) : null,
            )}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button
            onClick={() => {
              reset();
              onClose();
            }}
          >
            {report?.applied ? "Закрыть" : "Отмена"}
          </Button>
          {report?.ok && !report.applied && file && count(report.created) + count(report.updated) > 0 && (
            <Button variant="primary" disabled={busy} onClick={() => void run(file, true)}>
              Загрузить
            </Button>
          )}
        </div>
      </div>
    </Dialog>
  );
}
