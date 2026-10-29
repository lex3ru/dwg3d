import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpDown, Box, Building, CircleHelp, Columns2, DoorOpen, FileUp, FolderKanban, Image as ImageIcon, Maximize, Minus, MousePointer2, Plus, Printer,
  Redo2, RectangleHorizontal, Ruler, Save, Scissors, Spline, Square, SquareDashed, Tag, Undo2, Wand2,
} from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError, api, get, patch, post } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import { useCardTitle } from "@/shell/context";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { ErrorBoundary } from "@/ui/ErrorBoundary";
import { FloorDialog } from "@/pages/Buildings";
import { Field, Input } from "@/ui/form";
import { Empty, Loading } from "@/ui/misc";
import { useTree } from "@/catalog/parts";
import type { Tree } from "@/catalog/types";
import { Canvas, type WallDefaults } from "./Canvas";
import { ItemPanel } from "./ItemPanel";
import { footprint, normAngle, warningsFor, type Item, type WarningCode } from "./items";
import { PlacePanel } from "./PlacePanel";
import { useCalcs } from "./calc";
import { LabelsOffer, RegisterDialog, RemoveDialog, useLink, useLinkInStore, type Registered } from "./link";
import { floorUrl, groundFloor, rememberFloor } from "./floors";
import { copyItems, requestRemove, toChanges, type Catalog } from "./placement";
import { copy, paste, remove, type Clip } from "./ops";
import { dist, type Check, type Lift, type Plan, type PlanView, type Pt } from "./plan";
import { Properties, NumberField } from "./Properties";
import { EditorStore, clearDraft, layersChosen, readDraft, useEditor, type ItemOp, type Mode, type Tool } from "./store";
import { PDF_RENDER_WIDTH, underlayToWorld, worldToUnderlay } from "./Underlay";
import { useIsPhone, WalkBar } from "./Walk";
import { holding, SaveDialog, type SaveState } from "./SaveDialog";

const View3D = lazy(() => import("./View3D"));

type ViewMode = "2d" | "3d" | "both";

const TOOLS: { tool: Tool; title: string; icon: typeof Square; key?: string }[] = [
  { tool: "select", title: "Выбор", icon: MousePointer2, key: "V" },
  { tool: "wall", title: "Стена", icon: Minus, key: "W" },
  { tool: "arc", title: "Дуговая стена", icon: Spline, key: "A" },
  { tool: "door", title: "Дверь", icon: DoorOpen, key: "D" },
  { tool: "window", title: "Окно", icon: Columns2, key: "O" },
  { tool: "passage", title: "Проход", icon: SquareDashed },
  { tool: "glazing", title: "Витраж", icon: RectangleHorizontal },
  { tool: "column", title: "Колонна", icon: Square },
  { tool: "stair", title: "Лестница", icon: ArrowUpDown },
  { tool: "lift", title: "Лифт", icon: Box },
  { tool: "room", title: "Подпись помещения", icon: Tag, key: "R" },
  { tool: "cut", title: "Разрезать стену", icon: Scissors },
  { tool: "measure", title: "Измерить", icon: Ruler, key: "M" },
];

export function EditorPage() {
  const { buildingId, floorId } = useParams();
  const { search } = useLocation();
  const navigate = useNavigate();
  const building = useQuery({
    queryKey: ["building", buildingId],
    queryFn: () => get<{ id: string; name: string; floors: { id: string; name: string; elevation: number }[] }>(`/api/buildings/${buildingId}`),
  });
  useEffect(() => {
    try {
      if (building.data) localStorage.setItem("building", building.data.id);
    } catch {
      /* не запомнится */
    }
  }, [building.data]);
  useEffect(() => {
    // адрес без этажа — первый надземный с тем же ?project=, ?view=… (R-054)
    if (building.data && !floorId && building.data.floors.length) navigate(`/plan/${buildingId}/${groundFloor(building.data.floors)!.id}${search}`, { replace: true });
  }, [building.data, floorId, buildingId, search, navigate]);
  // «Открыть на плане» у проекта ведёт на последний открытый этаж (R-043)
  useEffect(() => {
    if (buildingId && floorId) rememberFloor(buildingId, floorId);
  }, [buildingId, floorId]);
  if (building.isLoading) return <Loading />;
  if (!building.data) return <Empty title="Здание не найдено" />;
  if (!building.data.floors.length) {
    return <Empty title={`В здании «${building.data.name}» нет этажей`}>Добавьте этажи в «Управление › Здания».</Empty>;
  }
  if (!floorId) return <Loading />;
  return <FloorEditor key={floorId} buildingId={building.data.id} floorId={floorId} />;
}

function FloorEditor({ buildingId, floorId }: { buildingId: string; floorId: string }) {
  const me = useMe();
  const readOnly = me.role !== "admin";
  const [params] = useSearchParams();
  // режим проекта (5.3.6): та же расстановка с изменениями проекта; только администратор
  const projectId = readOnly ? null : params.get("project");
  const view = useQuery({ queryKey: ["plan", floorId], queryFn: () => get<PlanView>(`/api/floors/${floorId}/plan`), refetchOnWindowFocus: false });
  const items = useQuery({
    queryKey: ["items", floorId, projectId ?? ""],
    queryFn: () => get<{ items: Item[]; removed?: Item[] }>(projectId ? `/api/projects/${projectId}/floors/${floorId}` : `/api/floors/${floorId}/items`),
    refetchOnWindowFocus: false,
  });
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => get<ProjectView>(`/api/projects/${projectId}`), enabled: !!projectId });
  // и архивные типы: предметы архивного типа остаются на плане
  const tree = useTree(true);
  if (view.isLoading || items.isLoading || tree.isLoading || (projectId && project.isLoading)) return <Loading />;
  if (!view.data) return <Empty title="Этаж не найден" />;
  // проект не открылся — так и сказать: молча открыть расстановку значит править её (R-054)
  if (projectId && (!project.data || items.isError)) {
    const error = (project.error ?? items.error) as ApiError | null;
    return (
      <Empty title={error?.status === 404 ? "Проект не найден" : "Проект не открылся"}>
        {error?.status === 404 ? "Его удалили или адрес неверный." : error?.message}{" "}
        <Link to={`/plan/${buildingId}/${floorId}`} className="text-accent-ink">
          Открыть этаж без проекта
        </Link>
      </Empty>
    );
  }
  return <Loaded key={projectId ?? "layout"} data={view.data} items={items.data?.items ?? []} removed={items.data?.removed ?? []} project={projectId ? (project.data ?? null) : null} tree={tree.data} readOnly={readOnly} />;
}

function startMode(readOnly: boolean, asked: string | null): Mode {
  if (readOnly) return "place";
  if (asked === "build" || asked === "place") return asked;
  try {
    return (localStorage.getItem("editor-mode") as Mode) || "build";
  } catch {
    return "build";
  }
}

function Loaded({ data, items: serverItems, removed, project, tree, readOnly }: { data: PlanView; items: Item[]; removed: Item[]; project: ProjectView | null; tree: Tree | undefined; readOnly: boolean }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const client = useQueryClient();
  const store = useMemo(() => {
    const s = new EditorStore(data.floor.id, structuredClone(data.plan), data.plan_version, data.lifts, serverItems, startMode(readOnly, params.get("mode")));
    // только чтение: помещения — как сохранены, проверку не спрашиваем
    if (readOnly)
      s.set({
        check: {
          issues: [], merges: [], splits: [], removed: [], needs_confirmation: false, slabs: data.slabs,
          rooms: data.rooms.map((r, index) => ({ ...r, index, label: r.id, labels: [r.id], status: "kept" as const })),
        },
      });
    // проект: правится только расстановка, план — нет
    if (project) s.set({ project: { id: project.id, name: project.name }, removedItems: removed, mode: "place" });
    return s;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.floor.id]);
  useCardTitle(`${data.building.name} · ${data.floor.name}${project ? ` · проект «${project.name}»` : ""}`);
  const guest = useMe().role === "guest";
  const itemsUrl = project ? `/api/projects/${project.id}/floors/${data.floor.id}` : `/api/floors/${data.floor.id}/items`;

  // ---------------------------------------------------------------- расстановка (5.3.2, 6.5.2)

  const cat: Catalog | null = useMemo(
    () => (tree ? { types: new Map(tree.types.map((t) => [t.id, t])), layers: new Map(tree.layers.map((l) => [l.id, l])) } : null),
    [tree],
  );
  // слои, скрытые по умолчанию (видимость из каталога), — пока человек сам не выбрал
  useEffect(() => {
    if (tree && !layersChosen()) store.set({ hiddenLayers: tree.layers.filter((l) => !l.visible).map((l) => l.id) });
  }, [tree, store]);

  // действия уходят на сервер по очереди: каждое — с версиями, которые вернуло предыдущее
  const versions = useRef(new Map(serverItems.map((i) => [i.id, i.version])));
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const pendingOps = useRef(0);
  const [itemsBusy, setItemsBusy] = useState(false);
  useEffect(() => {
    store.sendItems = (op: ItemOp) => {
      pendingOps.current += 1;
      setItemsBusy(true);
      queue.current = queue.current.then(async () => {
        try {
          const body = toChanges(op, versions.current);
          const r = await post<{ items: Item[]; deleted: string[]; notes: string[]; removed?: Item[] }>(project ? `${itemsUrl}/changes` : `/api/floors/${data.floor.id}/items/changes`, body);
          if (project) {
            store.set({ removedItems: r.removed ?? [] });
            client.invalidateQueries({ queryKey: ["project", project.id] });
            client.invalidateQueries({ queryKey: ["projects"] });
          }
          for (const i of r.items) versions.current.set(i.id, i.version);
          for (const id of r.deleted) versions.current.delete(id);
          store.itemsSaved(r.items, r.deleted);
          // связанные с учётом: перенос в другое помещение — перемещение (С13), убрали — в «Неразмещённые»
          const linked = [...Object.values(op.before), ...Object.values(op.after)].some((i) => i?.unit_id);
          if (linked || r.notes.length) {
            client.invalidateQueries({ queryKey: ["link", data.floor.id] });
            client.invalidateQueries({ queryKey: ["inventory"] });
          }
          if (r.notes.length) flash("ok", r.notes.join(" "));
        } catch (e) {
          flash("bad", `${(e as ApiError).message} Расстановка обновлена с сервера.`);
          const fresh = await get<{ items: Item[]; removed?: Item[] }>(itemsUrl);
          if (project) store.set({ removedItems: fresh.removed ?? [] });
          versions.current = new Map(fresh.items.map((i) => [i.id, i.version]));
          store.set({ items: fresh.items, itemPast: [], itemFuture: [], selection: [] });
          client.invalidateQueries({ queryKey: ["link", data.floor.id] });
        } finally {
          pendingOps.current -= 1;
          if (!pendingOps.current) setItemsBusy(false);
        }
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store, data.floor.id, itemsUrl]);
  // расстановку изменили в другом окне — подхватить, когда своих действий в пути нет
  useEffect(() => {
    if (pendingOps.current) return;
    const mine = new Map(store.state.items.map((i) => [i.id, i.version]));
    const same = serverItems.length === mine.size && serverItems.every((i) => mine.get(i.id) === i.version);
    if (same) return;
    versions.current = new Map(serverItems.map((i) => [i.id, i.version]));
    store.set({ items: serverItems, itemPast: [], itemFuture: [] });
  }, [serverItems, store]);

  // план с сервера обновился (чужое сохранение, лифты) — подхватить, если своих правок нет
  useEffect(() => {
    store.set({ lifts: data.lifts });
    if (store.state.edits === 0 && store.state.baseVersion !== data.plan_version) store.saved(structuredClone(data.plan), data.plan_version);
  }, [data, store]);

  const [mode, setMode] = useState<ViewMode>(() => (params.get("view") as ViewMode) || "2d");
  useEffect(() => {
    const t = setTimeout(() => window.dispatchEvent(new Event("editor:fit")), 50);
    return () => clearTimeout(t);
  }, [mode]);
  useEffect(() => {
    // прогулка из 2D — нужен 3D рядом с планом
    const on = (e: Event) => {
      setMode((m) => (m === "2d" ? "both" : m));
      setWalkRequest((r) => ({ p: (e as CustomEvent<Pt>).detail, n: (r?.n ?? 0) + 1 }));
    };
    window.addEventListener("editor:walk-here", on);
    return () => window.removeEventListener("editor:walk-here", on);
  }, []);
  const [wallDefaults, setWallDefaults] = useState<WallDefaults>({ thickness: 120, kind: "partition" });
  const [lengthPrompt, setLengthPrompt] = useState<{ at: [number, number]; apply: (mm: number) => void } | null>(null);
  const [calibration, setCalibration] = useState<[Pt, Pt] | null>(null);
  const [saveState, setSaveState] = useState<SaveState | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [help, setHelp] = useState(false);
  const [printing, setPrinting] = useState(false);
  const [addingFloor, setAddingFloor] = useState(false);
  const [draft, setDraft] = useState(() => (readOnly ? null : readDraft(data.floor.id)));
  const [walker, setWalker] = useState<{ p: Pt; angle: number } | null>(null);
  const [walkRequest, setWalkRequest] = useState<{ p: Pt; n: number } | null>(null);
  const clip = useRef<Clip | null>(null);
  const edits = useEditor(store, (s) => s.edits);
  const plan = useEditor(store, (s) => s.plan);
  const check = useEditor(store, (s) => s.check);
  const tool = useEditor(store, (s) => s.tool);
  const snaps = useEditor(store, (s) => s.snaps);
  const editMode = useEditor(store, (s) => s.mode);
  const items = useEditor(store, (s) => s.items);
  const selection = useEditor(store, (s) => s.selection);
  const canUndo = useEditor(store, (s) => (s.mode === "place" ? s.itemPast.length : s.past.length) > 0);
  const canRedo = useEditor(store, (s) => (s.mode === "place" ? s.itemFuture.length : s.future.length) > 0);
  const undo = () => (store.state.mode === "place" ? store.undoItems() : store.undo());
  const redo = () => (store.state.mode === "place" ? store.redoItems() : store.redo());
  const setEditMode = (m: Mode) => {
    store.set({ mode: m, selection: [], tool: "select", placing: null });
    try {
      localStorage.setItem("editor-mode", m);
    } catch {
      /* не запомнится */
    }
  };

  // предупреждения расстановки (5.3.2 п. 6) — когда предметы перестали двигаться
  const [warnings, setWarnings] = useState<Map<string, WarningCode[]>>(new Map());
  useEffect(() => {
    if (!cat) return;
    const t = setTimeout(() => {
      const outlines = (check?.rooms ?? data.rooms).map((r) => r.outline);
      const placed = items.filter((i) => !i.parent_id).map((i) => ({ item: i, type: cat.types.get(i.type_id), poly: footprint(i, cat.types.get(i.type_id)) }));
      setWarnings(warningsFor(plan, outlines, placed));
    }, 200);
    return () => clearTimeout(t);
  }, [items, plan, check, cat, data.rooms]);

  // выделить помещение из адреса (?room=…) — поиск ведёт сюда; предмет (?item=…) — карточка
  // единицы, «Показать на плане»
  useEffect(() => {
    const room = params.get("room");
    const label = room && store.state.plan.rooms.find((r) => r.id === room);
    if (label) store.set({ selection: [{ kind: "room", id: label.id }], focus: [label.x, label.y] });
    const itemId = params.get("item");
    const item = itemId && store.state.items.find((i) => i.id === itemId);
    if (item) {
      store.set({ mode: "place", selection: [{ kind: "item", id: item.id }] });
      // помещение предмета во весь экран — после того, как план впишется в окно
      const outline = data.rooms.find((r) => r.id === item.room_id)?.outline;
      const t = setTimeout(() => {
        const bottom = (document.querySelector('[aria-label="Обход"]') as HTMLElement | null)?.offsetHeight ?? 0;
        if (outline) window.dispatchEvent(new CustomEvent("editor:fit-room", { detail: { outline, bottom } }));
      }, 200);
      return () => clearTimeout(t);
    }
  }, [params, store, data.rooms]);

  // на телефоне — только расстановка (обход, 6.5.12): строительство недоступно
  const phone = useIsPhone();
  useEffect(() => {
    if (phone && !readOnly && store.state.mode === "build") store.set({ mode: "place", selection: [], tool: "select", placing: null });
  }, [phone, readOnly, store]);

  // расчёты (5.3.7): включённые пересчитываются по расстановке на экране
  const calcList = useCalcs(store, data.floor.id);
  const calcs = calcList.data?.items ?? [];

  // связь с учётом (5.5): единицы этажа, неразмещённые, сверка
  const link = useLink(data.floor.id);
  useLinkInStore(store, link.data);
  const [registering, setRegistering] = useState<string[] | null>(null);
  const [registered, setRegistered] = useState<Registered | null>(null);
  const linkChanged = () => {
    client.invalidateQueries({ queryKey: ["link", data.floor.id] });
    client.invalidateQueries({ queryKey: ["inventory"] });
  };

  // проверка плана на сервере: помещения, замечания (5.1.5) — после каждой правки
  useEffect(() => {
    if (readOnly) return;
    const t = setTimeout(() => {
      post<Check>(`/api/floors/${data.floor.id}/plan/check`, { plan })
        .then((c) => store.set({ check: c }))
        .catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [plan, data.floor.id, readOnly, store]);

  const flash = (tone: "ok" | "bad", text: string) => {
    setMessage({ tone, text });
    setTimeout(() => setMessage((m) => (m?.text === text ? null : m)), 6000);
  };
  useEffect(() => {
    const on = (e: Event) => flash("bad", (e as CustomEvent<string>).detail);
    window.addEventListener("editor:flash", on);
    return () => window.removeEventListener("editor:flash", on);
  }, []);

  // ---------------------------------------------------------------- сохранение (5.1.6)

  const save = useMutation({
    mutationFn: (body: { merges?: { rooms: string[]; keep: string }[]; confirm?: boolean; moves?: Record<string, string> }) =>
      api<PlanView>("PUT", `/api/floors/${data.floor.id}/plan`, { plan: store.state.plan, plan_version: store.state.baseVersion, ...body }),
    onSuccess: (saved) => {
      store.saved(structuredClone(saved.plan), saved.plan_version);
      // выделенная подпись получила ключ помещения
      store.set({ selection: store.state.selection.map((s) => (s.kind === "room" && saved.label_ids?.[s.id] ? { ...s, id: saved.label_ids[s.id]! } : s)) });
      setSaveState(null);
      client.setQueryData(["plan", data.floor.id], saved);
      client.invalidateQueries({ queryKey: ["building", data.building.id] });
      flash("ok", "План сохранён.");
    },
    onError: (e: ApiError) => {
      if (e.code === "needs_confirmation") return;
      // пока окно было открыто, в убираемом помещении появилось имущество — окно перечитывает
      // проверку и спрашивает место и для него; ошибка видна в окне (R-023)
      if (e.code === "needs_place") {
        void checkPlan().then((preview) => setSaveState((s) => s && { ...s, preview }));
        return;
      }
      setSaveState(null);
      flash("bad", e.message);
    },
  });

  const checkPlan = async () => {
    const preview = await post<Check>(`/api/floors/${data.floor.id}/plan/check`, { plan: store.state.plan });
    store.set({ check: preview });
    // несколько подписей в одном помещении — это и есть объединение, о нём спросит диалог
    preview.issues = preview.issues.filter((i) => i.code !== "labels_together" || !preview.merges.length);
    return preview;
  };

  const startSave = async () => {
    const preview = await checkPlan();
    if (preview.needs_confirmation || preview.issues.length) {
      setSaveState({ preview, keep: Object.fromEntries(preview.merges.map((m) => [m.index, m.rooms[0]!.id])), moves: {} });
      return;
    }
    save.mutate({});
  };

  const confirmSave = () => {
    if (!saveState) return;
    const merges = saveState.preview.merges.map((m) => ({ rooms: m.rooms.map((r) => r.id), keep: saveState.keep[m.index]! }));
    // место — только для убираемых помещений с имуществом из этой проверки
    const moves = Object.fromEntries(holding(saveState.preview).flatMap((r) => (saveState.moves[r.id] ? [[r.id, saveState.moves[r.id]!]] : [])));
    save.mutate({ merges, confirm: true, moves });
  };

  const fix = async () => {
    const result = await post<{ plan: Plan; fixed: string[]; issues: unknown[] }>(`/api/floors/${data.floor.id}/plan/fix`, { plan: store.state.plan });
    if (!result.fixed.length) {
      flash("bad", "Автоматически исправлять нечего — оставшееся правится вручную.");
      return;
    }
    store.commit(result.plan, []);
    flash("ok", `Исправлено: ${result.fixed.join("; ")}.${result.issues.length ? ` Осталось вручную: ${result.issues.length}.` : ""}`);
  };

  // ---------------------------------------------------------------- лифты (сохраняются сразу)

  const liftsChanged = () => client.invalidateQueries({ queryKey: ["plan"] });
  const createLift = useCallback(
    async (p: Pt) => {
      try {
        const lift = await post<Lift>(`/api/buildings/${data.building.id}/lifts`, { x: p[0], y: p[1], w: 2000, d: 2200, floor_ids: [data.floor.id] });
        store.set({ lifts: [...store.state.lifts, lift], selection: [{ kind: "lift", id: lift.id }], tool: "select" });
        liftsChanged();
      } catch (e) {
        flash("bad", (e as ApiError).message);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data.building.id, data.floor.id, store],
  );
  const changeLift = async (lift: Lift, change: Partial<Lift>) => {
    try {
      const updated = await patch<Lift>(`/api/lifts/${lift.id}`, change);
      store.set({ lifts: store.state.lifts.map((l) => (l.id === lift.id ? updated : l)) });
      liftsChanged();
    } catch (e) {
      flash("bad", (e as ApiError).message);
    }
  };
  const deleteLift = async (lift: Lift) => {
    await api("DELETE", `/api/lifts/${lift.id}`);
    store.set({ lifts: store.state.lifts.filter((l) => l.id !== lift.id), selection: [] });
    liftsChanged();
  };

  // ---------------------------------------------------------------- клавиатура (6.5.2)

  useEffect(() => {
    if (readOnly) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement) return;
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();
      if (store.state.mode === "place") {
        placeKey(e, mod, key);
        return;
      }
      if (mod && (key === "z" || key === "я")) {
        e.preventDefault();
        if (e.shiftKey) store.redo();
        else store.undo();
      } else if (mod && (key === "y" || key === "н")) {
        e.preventDefault();
        store.redo();
      } else if (mod && (key === "c" || key === "с")) {
        clip.current = copy(store.state.plan, store.state.selection);
      } else if (mod && (key === "v" || key === "м")) {
        if (!clip.current) return;
        const c = clip.current;
        let sel: ReturnType<typeof paste> = [];
        store.apply((p) => {
          sel = paste(p, c, [500, -500]);
        });
        store.set({ selection: sel });
      } else if (mod && (key === "s" || key === "ы")) {
        e.preventDefault();
        void startSave();
      } else if (e.key === "Delete" || e.key === "Backspace") {
        if (store.state.selection.some((s) => s.kind !== "lift")) store.apply((p) => remove(p, store.state.selection.filter((s) => s.kind !== "lift")), []);
      } else if (e.key === "Escape") {
        store.set({ tool: "select", selection: [] });
      } else if (e.key === "?") {
        setHelp(true);
      } else if (!mod) {
        const t = TOOLS.find((x) => x.key?.toLowerCase() === key);
        if (t) store.set({ tool: t.tool });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // клавиши «Расстановки»: отмена, копия, удаление, поворот, сдвиг стрелками
  const itemClip = useRef<Item[]>([]);
  const placeKey = (e: KeyboardEvent, mod: boolean, key: string) => {
    const s = store.state;
    const ids = new Set(s.selection.filter((x) => x.kind === "item").map((x) => x.id));
    const chosen = s.items.filter((i) => ids.has(i.id));
    const free = chosen.filter((i) => !i.parent_id);
    const shift = (fn: (i: Item) => Partial<Item>) => store.changeItems(s.items.map((i) => (ids.has(i.id) && !i.parent_id ? { ...i, ...fn(i) } : i)));
    if (mod && (key === "z" || key === "я")) {
      e.preventDefault();
      if (e.shiftKey) store.redoItems();
      else store.undoItems();
    } else if (mod && (key === "y" || key === "н")) {
      e.preventDefault();
      store.redoItems();
    } else if (mod && (key === "c" || key === "с")) {
      itemClip.current = free;
    } else if (mod && (key === "v" || key === "м")) {
      if (itemClip.current.length) copyItems(store, itemClip.current.filter((i) => s.items.some((x) => x.id === i.id)), [500, -500]);
    } else if (mod && (key === "d" || key === "в")) {
      e.preventDefault();
      if (free.length) copyItems(store, free, [500, -500]);
    } else if (mod && (key === "s" || key === "ы")) {
      e.preventDefault();
      void startSave();
    } else if (e.key === "Delete" || e.key === "Backspace") {
      if (ids.size) requestRemove(store, ids, cat ?? undefined);
    } else if (e.key === "Escape") {
      store.set({ placing: null, selection: [] });
    } else if (e.key === "?") {
      setHelp(true);
    } else if (!mod && (key === "r" || key === "к") && free.length) {
      shift((i) => ({ angle: normAngle(i.angle + (e.shiftKey ? -15 : 15)) }));
    } else if (!mod && e.key.startsWith("Arrow") && free.length) {
      e.preventDefault();
      const step = e.shiftKey ? 100 : 10;
      const [dx, dy] = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[e.key] ?? [0, 0];
      shift((i) => ({ x: (i.x ?? 0) + dx!, y: (i.y ?? 0) + dy! }));
    }
  };

  // ---------------------------------------------------------------- подложка (5.1.4 п. 5)

  const uploadUnderlay = async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch("/api/files?accept=pdf,png,jpeg,webp", { method: "POST", body: form, headers: { "X-Requested-With": "app" }, credentials: "same-origin" });
    const body = await response.json();
    if (!response.ok) {
      flash("bad", body?.error?.message ?? "Файл не загрузился.");
      return;
    }
    const v = store.state.view;
    const scale = body.content_type === "application/pdf" ? 42000 / PDF_RENDER_WIDTH : 10;
    store.apply((p) => {
      p.underlay = { file_id: body.id, page: 1, x: -v.x / v.scale, y: v.y / v.scale, scale, angle: 0, opacity: 0.5, visible: true };
    });
    flash("ok", "Подложка положена. Задайте масштаб: «Масштаб по двум точкам».");
  };

  const applyCalibration = (realMm: number) => {
    if (!calibration) return;
    const [a, b] = calibration;
    store.apply((p) => {
      const u = p.underlay!;
      const k = realMm / dist(a, b);
      const pa = worldToUnderlay(u, a[0], a[1]);
      const scaled = { ...u, scale: u.scale * k, x: 0, y: 0 };
      const at = underlayToWorld(scaled, pa[0], pa[1]);
      p.underlay = { ...scaled, x: a[0] - at[0], y: a[1] - at[1] };
    });
    setCalibration(null);
    store.set({ tool: "select" });
  };

  const floors = data.floors;
  const unlabeled = check?.rooms.filter((r) => !r.label).length ?? 0;
  const issues = check?.issues ?? [];
  const autoIssues = issues.filter((i) => i.auto).length;

  const show2d = mode !== "3d";
  const show3d = mode !== "2d";

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* верх: этаж, вид, отмена, привязки, сохранение (5.3.1) */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line bg-surface px-3 py-2">
        <label className="flex items-center gap-2 text-[13px] text-ink-2">
          <Building className="size-4" aria-hidden />
          <span className="sr-only">Этаж</span>
          <select
            aria-label="Этаж"
            value={data.floor.id}
            onChange={(e) => navigate(floorUrl(data.building.id, e.target.value, { project: project?.id, view: mode }))}
            className="h-9 rounded-lg border border-line-strong bg-surface px-2 text-sm text-ink max-md:h-11"
          >
            {[...floors].reverse().map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </label>
        {/* в проекте — нет: этаж добавился бы в настоящее здание, проект меняет только расстановку */}
        {!readOnly && !project && (
          <Button size="sm" variant="ghost" onClick={() => setAddingFloor(true)} title="Добавить этаж">
            <Plus /> этаж
          </Button>
        )}
        {!readOnly && <ProjectPicker buildingId={data.building.id} floorId={data.floor.id} project={project} />}
        {!readOnly && !project && (
          <div role="tablist" aria-label="Режим" className="flex rounded-lg border border-line-strong p-0.5 max-md:hidden">
            {([["build", "Строительство"], ["place", "Расстановка"]] as const).map(([m, title]) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={editMode === m}
                onClick={() => setEditMode(m)}
                className={cn("h-8 cursor-pointer rounded-md border-0 px-3 text-[13px] max-md:h-11", editMode === m ? "bg-ink text-surface" : "bg-transparent text-ink hover:bg-surface-2")}
              >
                {title}
              </button>
            ))}
          </div>
        )}
        <div role="radiogroup" aria-label="Вид" className="flex rounded-lg border border-line-strong p-0.5">
          {(["2d", "3d", "both"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              onClick={() => {
                setMode(m);
                setParams((p) => {
                  const out = new URLSearchParams(p);
                  if (m === "2d") out.delete("view");
                  else out.set("view", m);
                  return out;
                }, { replace: true });
              }}
              className={cn("h-8 cursor-pointer rounded-md border-0 px-3 text-[13px] max-md:h-11", mode === m ? "bg-accent text-on-accent" : "bg-transparent text-ink hover:bg-surface-2")}
            >
              {m === "2d" ? "2D" : m === "3d" ? "3D" : "оба"}
            </button>
          ))}
        </div>
        {!readOnly && (
          <>
            <Button size="icon" variant="ghost" aria-label="Отменить (Ctrl+Z)" title="Отменить (Ctrl+Z)" disabled={!canUndo} onClick={undo}>
              <Undo2 />
            </Button>
            <Button size="icon" variant="ghost" aria-label="Повторить (Ctrl+Y)" title="Повторить (Ctrl+Y)" disabled={!canRedo} onClick={redo}>
              <Redo2 />
            </Button>
            <div className="flex items-center gap-1 text-[12px] text-ink-2 max-lg:hidden" role="group" aria-label="Привязки">
              {([["nodes", "к стенам"], ["angles", "углы 45°"], ["grid", "сетка 100 мм"]] as const).map(([k, t]) => (
                <label key={k} className="flex cursor-pointer items-center gap-1 rounded-md px-1.5 py-1 hover:bg-surface-2">
                  <input type="checkbox" checked={snaps[k]} onChange={(e) => store.set({ snaps: { ...snaps, [k]: e.target.checked } })} />
                  {t}
                </label>
              ))}
            </div>
          </>
        )}
        <Button size="icon" variant="ghost" aria-label="Показать весь этаж" title="Показать весь этаж" onClick={() => window.dispatchEvent(new Event("editor:fit"))}>
          <Maximize />
        </Button>
        {!guest && (
          <Button size="icon" variant="ghost" aria-label="Печать и выгрузка" title="Печать и выгрузка" onClick={() => setPrinting(true)}>
            <Printer />
          </Button>
        )}
        <Button size="icon" variant="ghost" aria-label="Подсказка по клавишам" title="Клавиши (?)" onClick={() => setHelp(true)}>
          <CircleHelp />
        </Button>
        <div className="flex-1" />
        {message && (
          <span role="status" className={cn("max-w-md truncate text-[13px]", message.tone === "ok" ? "text-ok" : "text-bad")} title={message.text}>
            {message.text}
          </span>
        )}
        {/* постоянная ширина: надпись меняется на каждом действии, панель не должна прыгать */}
        {!readOnly && editMode === "place" && <span className="inline-block w-48 text-right text-[13px] text-ink-2">{itemsBusy ? "Сохраняю…" : project ? "Проект сохраняется сразу" : "Расстановка сохраняется сразу"}</span>}
        {!readOnly && !project && (
          <>
            {edits > 0 && <span className="text-[13px] text-ink-2">Несохранённые правки плана: {edits}</span>}
            <Button variant="primary" onClick={() => void startSave()} disabled={edits === 0 || save.isPending} className={cn(editMode === "place" && edits === 0 && "max-md:hidden")}>
              <Save /> Сохранить план
            </Button>
          </>
        )}
      </div>

      {project && (
        // режим проекта — другим цветом и с названием, чтобы не спутать с «как есть» (6.5.2)
        <div role="status" aria-label="Режим проекта" className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 bg-violet-600 px-4 py-1.5 text-[13px] text-white">
          <FolderKanban className="size-4" aria-hidden />
          <b>Проект «{project.name}»</b>
          <span className="opacity-90">правки меняют проект, расстановка остаётся как есть</span>
          <span className="flex items-center gap-2 opacity-90">
            <span className="inline-block size-2.5 rounded-sm bg-[#2E7D32]" /> новое
            <span className="inline-block size-2.5 rounded-sm bg-[#EF6C00]" /> перемещённое
            <span className="inline-block size-2.5 rounded-sm bg-[#1565C0]" /> изменённое
            <span className="inline-block size-2.5 rounded-sm border border-dashed border-white" /> убранное
          </span>
          {project.conflicts.length > 0 && <span className="rounded bg-white/20 px-1.5">устарел: столкновений {project.conflicts.length}</span>}
          <span className="flex-1" />
          <Link to={`/projects/${project.id}`} className="text-white underline">
            Открыть проект
          </Link>
        </div>
      )}
      <div className={cn("flex min-h-0 flex-1", project && "border-4 border-t-0 border-violet-600")}>
        {/* в «Расстановке» каталог и свойства — и при одном 3D: ставить можно и там */}
        {editMode === "place" && cat && (
          <aside aria-label="Слои и каталог" className="flex w-60 shrink-0 flex-col overflow-hidden border-r border-line bg-surface max-md:hidden">
            <PlacePanel store={store} cat={cat} readOnly={readOnly} link={project ? undefined : link.data} calcs={calcs} />
          </aside>
        )}
        {!readOnly && show2d && editMode === "build" && (
          <aside aria-label="Инструменты" className="flex w-52 shrink-0 flex-col overflow-y-auto border-r border-line bg-surface max-md:w-14">
            <div className="grid grid-cols-1 gap-0.5 p-2">
              {TOOLS.map((t) => (
                <button
                  key={t.tool}
                  type="button"
                  onClick={() => store.set({ tool: t.tool, selection: t.tool === "select" ? store.state.selection : [] })}
                  aria-pressed={tool === t.tool}
                  title={t.key ? `${t.title} (${t.key})` : t.title}
                  className={cn("flex h-9 cursor-pointer items-center gap-2.5 rounded-lg border-0 px-2.5 text-left text-[13px] max-md:h-11 max-md:justify-center", tool === t.tool ? "bg-accent-soft font-medium text-accent-ink" : "bg-transparent text-ink hover:bg-surface-2")}
                >
                  <t.icon className="size-[18px] shrink-0" aria-hidden />
                  <span className="max-md:sr-only">{t.title}</span>
                </button>
              ))}
            </div>
            <UnderlayPanel store={store} onUpload={uploadUnderlay} />
          </aside>
        )}

        <div className="relative flex min-w-0 flex-1">
          {show2d && (
            <div className={cn("relative min-w-0", show3d ? "w-1/2 border-r border-line" : "flex-1")}>
              <Canvas
                store={store}
                readOnly={readOnly}
                floorId={data.floor.id}
                dbRooms={data.rooms}
                wallDefaults={wallDefaults}
                onCreateLift={createLift}
                onLiftMoved={(lift, p) => void changeLift(lift, { x: p[0], y: p[1] })}
                onCalibrate={(a, b) => setCalibration([a, b])}
                onLengthPrompt={setLengthPrompt}
                walker={walker}
                cat={cat}
                warnings={warnings}
                floorHeight={data.floor.height}
              />
              {/* в проекте учёта нет, как и на компьютере: «Карточка» (?card=…) ещё и вывела бы из проекта */}
              {phone && !readOnly && editMode === "place" && cat && <WalkBar store={store} cat={cat} link={project ? undefined : link.data} rooms={data.rooms} onRegister={setRegistering} />}
              {lengthPrompt && <LengthPrompt at={lengthPrompt.at} onApply={lengthPrompt.apply} onCancel={() => setLengthPrompt(null)} />}
              {draft && (
                <div className="absolute top-3 left-1/2 z-10 flex max-w-[90%] -translate-x-1/2 flex-wrap items-center gap-3 rounded-xl border border-warn/40 bg-warn-soft px-4 py-2.5 text-sm text-warn shadow">
                  <span>
                    Есть несохранённые правки этого этажа от {formatDateTime(draft.at)}
                    {draft.base !== data.plan_version ? " — план с тех пор сохраняли, сверьте после восстановления" : ""}.
                  </span>
                  <Button size="sm" variant="primary" onClick={() => { store.commit(draft.plan); store.set({ edits: draft.edits || 1 }); setDraft(null); }}>
                    Восстановить
                  </Button>
                  <Button size="sm" onClick={() => { clearDraft(data.floor.id); setDraft(null); }}>
                    Отбросить
                  </Button>
                </div>
              )}
            </div>
          )}
          {show3d && (
            <div className="relative min-w-0 flex-1">
              <ErrorBoundary fallback={(retry) => <Unavailable3D onRetry={retry} />}>
                <Suspense fallback={<Loading />}>
                  <View3D buildingId={data.building.id} floorId={data.floor.id} projectId={project?.id ?? null} floors={floors} plan={plan} lifts={store.state.lifts} onWalker={setWalker} walkRequest={walkRequest} store={store} cat={cat} readOnly={readOnly} />
                </Suspense>
              </ErrorBoundary>
            </div>
          )}
        </div>

        {(show2d || (editMode === "place" && cat)) && (
          <aside aria-label="Свойства" className="flex w-72 shrink-0 flex-col overflow-y-auto border-l border-line bg-surface max-lg:hidden">
            {editMode === "place" && cat && !selection.some((x) => x.kind === "room") ? (
              <ItemPanel store={store} cat={cat} rooms={data.rooms} readOnly={readOnly} warnings={warnings} link={project ? undefined : link.data} onRegister={setRegistering} calcs={calcs} />
            ) : (
              <Properties
                store={store}
                readOnly={readOnly}
                floors={floors}
                floorId={data.floor.id}
                wallDefaults={wallDefaults}
                setWallDefaults={setWallDefaults}
                onLiftChange={(l, c) => void changeLift(l, c)}
                onLiftDelete={(l) => void deleteLift(l)}
              />
            )}
            {!readOnly && editMode === "build" && (
              <section className="flex flex-col gap-2 px-4 py-4" aria-label="Проверка плана">
                <h3 className="m-0 flex items-center justify-between text-sm font-semibold">
                  Проверка плана
                  <span className={cn("text-[12px] font-normal", issues.length ? "text-warn" : "text-ok")}>{issues.length ? `замечаний: ${issues.length}` : "без замечаний"}</span>
                </h3>
                {unlabeled > 0 && <p className="m-0 text-[12px] text-warn">Помещений без подписи: {unlabeled}. Подпишите их инструментом «Подпись помещения» — или они сохранятся без номера.</p>}
                <ul className="m-0 flex list-none flex-col gap-1 p-0">
                  {issues.slice(0, 30).map((issue, i) => (
                    <li key={i} className="flex items-center gap-2 text-[13px]">
                      <span className={cn("size-2 shrink-0 rounded-full", issue.auto ? "bg-warn" : "bg-bad")} />
                      <span className="flex-1">
                        {issue.message}
                        <span className="block text-[11px] text-ink-3">{issue.auto ? "исправится автоматически" : "править вручную"}</span>
                      </span>
                      <Button size="sm" variant="ghost" onClick={() => store.set({ focus: [issue.x, issue.y], selection: issue.ids.map((id) => ({ kind: (plan.walls.some((w) => w.id === id) ? "wall" : plan.openings.some((o) => o.id === id) ? "opening" : "room") as "wall", id })) })}>
                        Показать
                      </Button>
                    </li>
                  ))}
                </ul>
                {autoIssues > 0 && (
                  <Button size="sm" onClick={() => void fix()}>
                    <Wand2 /> Исправить автоматически ({autoIssues})
                  </Button>
                )}
              </section>
            )}
          </aside>
        )}
      </div>

      <SaveDialog state={saveState} setState={setSaveState} onConfirm={confirmSave} pending={save.isPending} error={save.error && (save.error as ApiError).code !== "needs_confirmation" ? (save.error as ApiError).message : null} />
      <CalibrateDialog open={calibration !== null} measured={calibration ? dist(calibration[0], calibration[1]) : 0} onApply={applyCalibration} onCancel={() => setCalibration(null)} />
      <HelpDialog open={help} onOpenChange={setHelp} />
      <FloorDialog
        building={{ id: data.building.id, floors }}
        floor={addingFloor ? "new" : null}
        onClose={() => setAddingFloor(false)}
        onDone={(floor) => {
          client.invalidateQueries({ queryKey: ["building", data.building.id] });
          client.invalidateQueries({ queryKey: ["buildings"] });
          client.invalidateQueries({ queryKey: ["plan"] });
          navigate(floorUrl(data.building.id, floor.id, { view: mode }));
        }}
      />
      <PrintDialog open={printing} onOpenChange={setPrinting} floorId={data.floor.id} unsaved={edits > 0 && !readOnly} />
      {cat && (
        <>
          <RegisterDialog
            open={registering !== null}
            onClose={() => setRegistering(null)}
            floorId={data.floor.id}
            items={items.filter((i) => registering?.includes(i.id))}
            cat={cat}
            onDone={(r) => {
              const linked = new Map(r.items.map((i) => [i.id, i]));
              for (const i of r.items) versions.current.set(i.id, i.version);
              store.set({ items: store.state.items.map((i) => (linked.has(i.id) ? { ...i, unit_id: linked.get(i.id)!.unit_id, version: linked.get(i.id)!.version } : i)), itemPast: [], itemFuture: [] });
              setRegistering(null);
              setRegistered(r);
              linkChanged();
            }}
          />
          <LabelsOffer result={registered} onClose={() => setRegistered(null)} />
          <RemoveDialog
            store={store}
            cat={cat}
            onDone={(text, deleted) => {
              for (const id of deleted) versions.current.delete(id);
              flash("ok", text);
              linkChanged();
            }}
          />
        </>
      )}
    </div>
  );
}

// 3D не показалось: нет WebGL, сбой видеокарты, ошибка в сцене — план и остальной редактор
// работают (R-032). «Попробовать снова» создаёт 3D-вид заново.
function Unavailable3D({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="flex h-full flex-col items-center justify-center gap-3 bg-surface-2 px-6 text-center">
      <div className="text-base font-medium">3D-вид недоступен</div>
      <div className="max-w-sm text-sm text-ink-2">Браузер или видеокарта не смогли показать 3D. План и остальной редактор работают.</div>
      <Button onClick={onRetry}>Попробовать снова</Button>
    </div>
  );
}

function UnderlayPanel({ store, onUpload }: { store: EditorStore; onUpload: (f: File) => void }) {
  const underlay = useEditor(store, (s) => s.plan.underlay);
  const file = useRef<HTMLInputElement>(null);
  const set = (patch: Partial<NonNullable<typeof underlay>>) => store.apply((p) => void (p.underlay = { ...p.underlay!, ...patch }));
  return (
    <section className="flex flex-col gap-2 border-t border-line p-3 max-md:hidden" aria-label="Подложка">
      <h3 className="m-0 flex items-center gap-2 text-[13px] font-semibold">
        <ImageIcon className="size-4" aria-hidden /> Подложка
      </h3>
      <input ref={file} type="file" accept="application/pdf,image/png,image/jpeg,image/webp" className="hidden" onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])} />
      {!underlay ? (
        <>
          <p className="m-0 text-[12px] text-ink-2">Скан плана (PDF или картинка) под этажом — чтобы обвести стены.</p>
          <Button size="sm" onClick={() => file.current?.click()}>
            <FileUp /> Положить подложку
          </Button>
        </>
      ) : (
        <>
          <label className="flex items-center gap-2 text-[12px]">
            <input type="checkbox" checked={underlay.visible} onChange={(e) => set({ visible: e.target.checked })} /> показывать
          </label>
          <label className="flex flex-col gap-1 text-[12px] text-ink-2">
            Прозрачность
            <input type="range" min={0.05} max={1} step={0.05} value={underlay.opacity} onChange={(e) => store.preview({ ...store.state.plan, underlay: { ...underlay, opacity: Number(e.target.value) } })} onPointerUp={(e) => set({ opacity: Number((e.target as HTMLInputElement).value) })} />
          </label>
          <Button size="sm" onClick={() => store.set({ tool: "calibrate", selection: [] })}>
            <Ruler /> Масштаб по двум точкам
          </Button>
          <div className="grid grid-cols-2 gap-1.5">
            <NumberField label="X" unit="мм" value={underlay.x} onChange={(x) => set({ x })} />
            <NumberField label="Y" unit="мм" value={underlay.y} onChange={(y) => set({ y })} />
            <NumberField label="Поворот" unit="°" value={underlay.angle} onChange={(angle) => set({ angle })} digits={1} />
            <NumberField label="Страница" hint="Какую страницу PDF положить подложкой." value={underlay.page} min={1} onChange={(page) => set({ page: Math.round(page) })} />
          </div>
          <Button size="sm" variant="ghost" onClick={() => store.apply((p) => void (p.underlay = null))}>
            Убрать подложку
          </Button>
        </>
      )}
    </section>
  );
}

function LengthPrompt({ at, onApply, onCancel }: { at: [number, number]; onApply: (mm: number) => void; onCancel: () => void }) {
  const [text, setText] = useState("");
  return (
    <form
      className="absolute z-10 flex items-center gap-1 rounded-lg border border-line bg-surface p-1.5 shadow-lg"
      style={{ left: at[0] + 12, top: at[1] + 12 }}
      onSubmit={(e) => {
        e.preventDefault();
        const v = Number.parseFloat(text.replace(",", "."));
        if (v > 0) onApply(v);
      }}
    >
      <label className="text-[12px] text-ink-2" htmlFor="wall-length">
        Длина
      </label>
      <input id="wall-length" autoFocus value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Escape" && onCancel()} inputMode="decimal" className="h-8 w-24 rounded-md border border-line-strong px-2 font-mono text-[13px]" placeholder="мм" />
    </form>
  );
}

function CalibrateDialog({ open, measured, onApply, onCancel }: { open: boolean; measured: number; onApply: (mm: number) => void; onCancel: () => void }) {
  const [text, setText] = useState("");
  const v = Number.parseFloat(text.replace(",", "."));
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onCancel()}
      title="Масштаб подложки"
      description="Сколько на самом деле между двумя отмеченными точками?"
      footer={
        <>
          <Button onClick={onCancel}>Отмена</Button>
          <Button variant="primary" disabled={!(v > 0)} onClick={() => onApply(v)}>
            Применить
          </Button>
        </>
      }
    >
      <Field label="Расстояние, мм" hint={`Сейчас на подложке: ${Math.round(measured)} мм.`}>
        {(p) => <Input {...p} autoFocus inputMode="decimal" value={text} onChange={(e) => setText(e.target.value)} placeholder="например, 6000" />}
      </Field>
    </Dialog>
  );
}

// Печать этажа листами и выгрузка (5.1.8): печатается сохранённый план
function PrintDialog({ open, onOpenChange, floorId, unsaved }: { open: boolean; onOpenChange: (o: boolean) => void; floorId: string; unsaved: boolean }) {
  const [paper, setPaper] = useState("A4");
  const [orientation, setOrientation] = useState("landscape");
  const [scale, setScale] = useState("");
  const select = "h-9 rounded-lg border border-line-strong bg-surface px-2.5 text-sm max-md:h-11";
  const pdf = `/api/floors/${floorId}/export.pdf?paper=${paper}&orientation=${orientation}${scale ? `&scale=${scale}` : ""}`;
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Печать и выгрузка плана"
      footer={
        <>
          <Button asChild>
            <a href={`/api/floors/${floorId}/export.dxf`} download>
              Скачать DXF
            </a>
          </Button>
          <Button variant="primary" asChild>
            <a href={pdf} target="_blank" rel="noreferrer">
              <Printer /> Открыть PDF для печати
            </a>
          </Button>
        </>
      }
    >
      {unsaved && <p className="m-0 rounded-lg bg-warn-soft px-3 py-2 text-[13px] text-warn">Печатается сохранённый план — несохранённые правки в него не попадут.</p>}
      <div className="grid grid-cols-3 gap-3">
        <label className="flex flex-col gap-1 text-[13px] font-medium">
          Лист
          <select className={select} value={paper} onChange={(e) => setPaper(e.target.value)}>
            <option value="A4">А4</option>
            <option value="A3">А3</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[13px] font-medium">
          Ориентация
          <select className={select} value={orientation} onChange={(e) => setOrientation(e.target.value)}>
            <option value="landscape">альбомная</option>
            <option value="portrait">книжная</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[13px] font-medium">
          Масштаб
          <select className={select} value={scale} onChange={(e) => setScale(e.target.value)}>
            <option value="">по размеру листа</option>
            {[50, 100, 200, 500].map((s) => (
              <option key={s} value={s}>
                1:{s}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="m-0 text-[13px] text-ink-2">Если этаж в выбранном масштабе не помещается, он печатается несколькими листами. Рамка с названием здания, этажа, масштабом и номером листа. DXF — в миллиметрах, по слоям: стены, перегородки, проёмы, колонны, лестницы, лифты, помещения.</p>
    </Dialog>
  );
}

function HelpDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const common: [string, ReactNode][] = [
    ["Ctrl+Z / Ctrl+Y", "отменить / повторить"],
    ["Ctrl+C / Ctrl+V", "копировать / вставить выделенное"],
    ["Delete", "удалить выделенное"],
    ["Ctrl+S", "сохранить план"],
    ["Колесо мыши", "приблизить / отдалить"],
    ["Пробел + перетаскивание, средняя кнопка", "сдвинуть план"],
    ["Shift + щелчок, рамка", "выделить несколько"],
  ];
  const build: [string, ReactNode][] = [
    ["Esc", "закончить цепочку стен, снять выделение"],
    ["Enter", "при рисовании стены — ввести длину"],
    ["V W A D O R M", "выбор, стена, дуга, дверь, окно, подпись помещения, измерение"],
  ];
  const place: [string, ReactNode][] = [
    ["Ctrl+D", "копия выделенного рядом"],
    ["R / Shift+R", "повернуть на 15° против / по часовой"],
    ["Стрелки, Shift+стрелки", "сдвинуть на 10 / 100 мм"],
    ["Alt при перетаскивании", "без прилипания к стене и без шага поворота"],
    ["Esc", "перестать ставить выбранный тип, снять выделение"],
    ["В 3D: перетаскивание, Shift", "двигать по полу (настенный — вдоль стены), поворачивать"],
  ];
  const rows: [string, ReactNode][] = [...common, ["", <b key="b">Строительство</b>], ...build, ["", <b key="p">Расстановка</b>], ...place];
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Клавиши редактора">
      <table className="w-full border-collapse text-sm">
        <tbody>
          {rows.map(([k, v], i) => (
            <tr key={i}>
              <td className="py-1.5 pr-4 font-mono text-[12px] whitespace-nowrap text-ink-2">{k}</td>
              <td className="py-1.5">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Dialog>
  );
}


export interface ProjectView {
  id: string;
  building_id: string;
  name: string;
  status: "draft" | "outdated" | "applied" | "archived";
  status_title: string;
  changes: number;
  added: number;
  moved: number;
  removed: number;
  rooms: string[];
  floor_ids: string[];
  conflicts: { item_id: string; floor_id: string; kind: string; text: string; x?: number; y?: number }[];
  total: number;
  created_by: string;
  created_at: string;
  updated_at: string;
  applied_at: string | null;
  archived: boolean;
  version: number;
}

// «Как есть ▾ / Проект …» (5.3.1): расстановка или один из проектов здания
function ProjectPicker({ buildingId, floorId, project }: { buildingId: string; floorId: string; project: ProjectView | null }) {
  const navigate = useNavigate();
  const list = useQuery({ queryKey: ["projects", buildingId], queryFn: () => get<{ items: ProjectView[] }>(`/api/projects?building_id=${buildingId}`) });
  const items = list.data?.items ?? [];
  return (
    <select
      aria-label="Расстановка или проект"
      value={project?.id ?? ""}
      onChange={(e) => navigate(`/plan/${buildingId}/${floorId}${e.target.value ? `?project=${e.target.value}` : "?mode=place"}`)}
      className={cn("h-9 max-w-56 rounded-lg border px-2 text-sm max-md:h-11", project ? "border-violet-600 bg-violet-50 text-violet-900 dark:bg-violet-950 dark:text-violet-100" : "border-line-strong bg-surface text-ink")}
    >
      <option value="">Как есть</option>
      {items.map((p) => (
        <option key={p.id} value={p.id}>
          Проект «{p.name}»{p.status === "outdated" ? " — устарел" : ""}
        </option>
      ))}
      {project && !items.some((p) => p.id === project.id) && <option value={project.id}>Проект «{project.name}»</option>}
    </select>
  );
}
