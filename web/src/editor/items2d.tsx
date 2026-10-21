import { memo } from "react";
import type { Layer, TypeBrief } from "@/catalog/types";
import { sizeOf, type Gap, type Item, type WarningCode } from "./items";
import { add, rect, rot, toPath, type Pt } from "./plan";
import { useTopView } from "./topview";

// Предметы на 2D-плане (5.3.2): вид сверху из 3D-модели типа (topview.ts), без модели —
// контур по габаритам в цвете слоя; значок; передняя сторона отмечена. Каждый предмет — отдельный запомненный элемент: при перетаскивании
// одного остальные 2 000 не перерисовываются (8.2).

interface ShapeProps {
  item: Item;
  type: TypeBrief | undefined;
  color: string;
  px: number;
  selected: boolean;
  warn: boolean;
  pale: boolean;
  contents: number;
  unit?: string; // состояние связанной единицы (5.5, 6.5.2)
  mark?: "added" | "moved" | "changed" | null; // в проекте: новое, перемещённое, изменённое (5.3.6)
}

export const PROJECT_COLOR = { added: "#2E7D32", moved: "#EF6C00", changed: "#1565C0", removed: "#C62828" } as const;

// значок учёта на предмете: учтён и в работе — зелёный, неисправен — красный, в ремонте —
// жёлтый, на хранении — серый
const UNIT_COLOR: Record<string, string> = { in_use: "var(--ok)", broken: "var(--bad)", repair: "var(--warn)", storage: "var(--ink-3)" };

export const ItemShape = memo(function ItemShape({ item, type, color, px, selected, warn, pale, contents, unit, mark }: ShapeProps) {
  const { w, d } = sizeOf(type);
  const x = item.x ?? 0;
  const y = item.y ?? 0;
  const stroke = selected ? "var(--accent)" : mark ? PROJECT_COLOR[mark] : warn ? "var(--bad)" : color;
  const icon = type?.top_view === "icon";
  const view = useTopView(type);
  // передняя сторона — +Y предмета: короткая черта у края
  const f0 = add([x, y], rot([-w / 4, d / 2], item.angle));
  const f1 = add([x, y], rot([w / 4, d / 2], item.angle));
  return (
    // попадание по предмету редактор считает сам (Canvas, hitItem) — браузеру не нужно
    // проверять сложные контуры на каждое движение мыши
    <g opacity={pale ? 0.3 : 1} data-item={item.id} pointerEvents="none">
      {icon ? (
        <>
          <circle cx={x} cy={y} r={Math.max(Math.min(w, d) / 2, 6 * px)} fill={color} fillOpacity={0.35} stroke={stroke} strokeWidth={(selected ? 3 : 1.5) * px} />
          <path d={`M${x},${y}L${add([x, y], rot([0, Math.max(d / 2, 10 * px)], item.angle)).join(",")}`} stroke={stroke} strokeWidth={1.5 * px} />
        </>
      ) : view && type ? (
        <>
          {/* чертёж вида сверху — общий на тип (TopViewDefs), в координатах предмета: x вправо,
              y к передней стороне; цвет и толщина контура — свои у предмета */}
          <use href={`#tv-${type.id}`} transform={`translate(${x} ${y}) rotate(${item.angle})`} fill={mark ? PROJECT_COLOR[mark] : color} fillOpacity={mark ? 0.3 : 0.2} stroke={stroke} />
          {(selected || warn || mark) && (
            <path d={toPath(rect(x, y, w, d, item.angle))} fill="none" stroke={stroke} strokeWidth={(selected ? 1.5 : 1.8) * px} strokeDasharray={`${5 * px} ${3 * px}`} strokeOpacity={selected ? 0.7 : 1} />
          )}
        </>
      ) : (
        <>
          <path d={toPath(rect(x, y, w, d, item.angle))} fill={mark ? PROJECT_COLOR[mark] : color} fillOpacity={mark ? 0.3 : 0.22} stroke={stroke} strokeWidth={(selected ? 3 : mark ? 2.2 : 1.2) * px} strokeDasharray={warn && !selected ? `${5 * px} ${3 * px}` : undefined} />
          <line x1={f0[0]} y1={f0[1]} x2={f1[0]} y2={f1[1]} stroke={stroke} strokeWidth={2.5 * px} />
        </>
      )}
      {contents > 0 && <circle cx={x} cy={y} r={4 * px} fill={stroke} />}
      {unit && (
        <circle
          data-unit-state={unit}
          cx={add([x, y], rot([w / 2, -d / 2], item.angle))[0]}
          cy={add([x, y], rot([w / 2, -d / 2], item.angle))[1]}
          r={(unit === "broken" || unit === "repair" ? 5 : 3.5) * px}
          fill={UNIT_COLOR[unit] ?? "var(--ok)"}
          stroke="var(--surface)"
          strokeWidth={1.2 * px}
        />
      )}
    </g>
  );
});

// Чертежи вида сверху — по одному на тип, в <defs>: 2 000 предметов ссылаются на них через
// <use>, а не несут каждый свои длинные пути (8.2)
export function TopViewDefs({ types, px }: { types: TypeBrief[]; px: number }) {
  return (
    <defs>
      {types.map((t) => (
        <TopViewDef key={t.id} type={t} px={px} />
      ))}
    </defs>
  );
}

const TopViewDef = memo(function TopViewDef({ type, px }: { type: TypeBrief; px: number }) {
  const view = useTopView(type);
  if (!view) return null;
  // мелкий на экране — только силуэт: линии деталей там не видны, а перерисовка 2 000
  // предметов с ними медленнее (8.2)
  const { w, d } = sizeOf(type);
  const detailed = Math.max(w, d) / px >= 28;
  return (
    <g id={`tv-${type.id}`}>
      <path d={detailed ? view.fill : view.coarse} fillRule="evenodd" strokeWidth={1.1 * px} strokeLinejoin="round" />
      {detailed && <path d={view.lines} fill="none" strokeWidth={0.8 * px} strokeLinecap="round" strokeOpacity={0.85} />}
    </g>
  );
});

// Размеры от сторон предмета до стен — пока его двигают (С6)
export function GapLines({ gaps, toScreen }: { gaps: Gap[]; toScreen: (p: Pt) => [number, number] }) {
  return (
    <g style={{ pointerEvents: "none" }}>
      {gaps.map((g, i) => {
        const a = toScreen(g.from);
        const b = toScreen(g.to);
        const m: [number, number] = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
        const text = `${Math.round(g.mm)}`;
        const tw = text.length * 7 + 10;
        return (
          <g key={i}>
            <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="var(--accent)" strokeWidth={1} strokeDasharray="4 3" />
            <circle cx={b[0]} cy={b[1]} r={2.5} fill="var(--accent)" />
            <g transform={`translate(${m[0]} ${m[1]})`}>
              <rect x={-tw / 2} y={-9} width={tw} height={17} rx={3} fill="var(--accent)" />
              <text textAnchor="middle" y={4} fontSize={11} fill="white" className="font-mono">
                {text}
              </text>
            </g>
          </g>
        );
      })}
    </g>
  );
}

// Где встанут копии (ряд, сетка)
export function Ghosts({ points, item, type, px }: { points: Pt[]; item: Item; type: TypeBrief | undefined; px: number }) {
  const { w, d } = sizeOf(type);
  return (
    <g style={{ pointerEvents: "none" }}>
      {points.map((p, i) => (
        <path key={i} d={toPath(rect(p[0], p[1], w, d, item.angle))} fill="var(--accent)" fillOpacity={0.12} stroke="var(--accent)" strokeWidth={1.2 * px} strokeDasharray={`${4 * px} ${3 * px}`} />
      ))}
    </g>
  );
}

export function layerColor(layers: Map<string, Layer>, type: TypeBrief | undefined) {
  return (type?.layer_id && layers.get(type.layer_id)?.color) || "#607D8B";
}

export const WARN_ICON: Record<WarningCode, string> = { wall: "стена", door: "дверь", outside: "вне", overlap: "наложение" };

// Что проект убирает из расстановки — пунктирным контуром, не выбирается
export function RemovedShape({ item, type, px }: { item: Item; type: TypeBrief | undefined; px: number }) {
  const { w, d } = sizeOf(type);
  return (
    <path
      d={toPath(rect(item.x ?? 0, item.y ?? 0, w, d, item.angle))}
      fill={PROJECT_COLOR.removed}
      fillOpacity={0.06}
      stroke={PROJECT_COLOR.removed}
      strokeWidth={1.6 * px}
      strokeDasharray={`${5 * px} ${4 * px}`}
      style={{ pointerEvents: "none" }}
      data-removed={item.id}
    />
  );
}
