import { memo } from "react";
import type { Layer, TypeBrief } from "@/catalog/types";
import { sizeOf, type Gap, type Item, type WarningCode } from "./items";
import { add, rect, rot, toPath, type Pt } from "./plan";

// Предметы на 2D-плане (5.3.2): контур по габаритам в цвете слоя или значок; передняя
// сторона отмечена. Каждый предмет — отдельный запомненный элемент: при перетаскивании
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
}

// значок учёта на предмете: учтён и в работе — зелёный, неисправен — красный, в ремонте —
// жёлтый, на хранении — серый
const UNIT_COLOR: Record<string, string> = { in_use: "var(--ok)", broken: "var(--bad)", repair: "var(--warn)", storage: "var(--ink-3)" };

export const ItemShape = memo(function ItemShape({ item, type, color, px, selected, warn, pale, contents, unit }: ShapeProps) {
  const { w, d } = sizeOf(type);
  const x = item.x ?? 0;
  const y = item.y ?? 0;
  const stroke = selected ? "var(--accent)" : warn ? "var(--bad)" : color;
  const icon = type?.top_view === "icon";
  // передняя сторона — +Y предмета: короткая черта у края
  const f0 = add([x, y], rot([-w / 4, d / 2], item.angle));
  const f1 = add([x, y], rot([w / 4, d / 2], item.angle));
  return (
    <g opacity={pale ? 0.3 : 1} data-item={item.id}>
      {icon ? (
        <>
          <circle cx={x} cy={y} r={Math.max(Math.min(w, d) / 2, 6 * px)} fill={color} fillOpacity={0.35} stroke={stroke} strokeWidth={(selected ? 3 : 1.5) * px} />
          <path d={`M${x},${y}L${add([x, y], rot([0, Math.max(d / 2, 10 * px)], item.angle)).join(",")}`} stroke={stroke} strokeWidth={1.5 * px} />
        </>
      ) : (
        <>
          <path d={toPath(rect(x, y, w, d, item.angle))} fill={color} fillOpacity={0.22} stroke={stroke} strokeWidth={(selected ? 3 : 1.2) * px} strokeDasharray={warn && !selected ? `${5 * px} ${3 * px}` : undefined} />
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
