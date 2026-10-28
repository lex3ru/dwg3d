// Переходы между этажами редактора: какой этаж открыть и с чем (5.3.1, 5.3.6 п. 2)

type Floor = { id: string; elevation: number };

// Адрес другого этажа: проект и вид (2D, 3D, оба) переходят вместе с человеком — иначе после
// смены этажа правки пошли бы в настоящую расстановку (R-042). Помещение и предмет из адреса —
// старого этажа, их не переносим.
export function floorUrl(buildingId: string, floorId: string, keep: { project?: string | null; view?: string }): string {
  const q = new URLSearchParams();
  if (keep.project) q.set("project", keep.project);
  if (keep.view && keep.view !== "2d") q.set("view", keep.view);
  const s = q.toString();
  return `/plan/${buildingId}/${floorId}${s ? `?${s}` : ""}`;
}

// Первый надземный этаж — с него открывается здание
export function groundFloor<F extends Floor>(floors: F[]): F | undefined {
  return floors.find((f) => f.elevation >= 0) ?? floors[0];
}

// Этаж для «Открыть на плане» у проекта (R-043). Этажи — снизу вверх, `changed` — этажи с
// изменениями проекта, `last` — последний открытый в редакторе этаж здания. С изменениями —
// последний открытый, если он среди них, иначе нижний из них; без изменений — последний
// открытый, иначе первый надземный.
export function projectFloor<F extends Floor>(floors: F[], changed: string[], last: string | null): F | undefined {
  const withChanges = floors.filter((f) => changed.includes(f.id));
  if (withChanges.length) return withChanges.find((f) => f.id === last) ?? withChanges[0];
  return floors.find((f) => f.id === last) ?? groundFloor(floors);
}

// последний открытый этаж здания — в браузере человека
export function rememberFloor(buildingId: string, floorId: string) {
  try {
    localStorage.setItem(`floor:${buildingId}`, floorId);
  } catch {
    /* не запомнится */
  }
}

export function lastFloor(buildingId: string): string | null {
  try {
    return localStorage.getItem(`floor:${buildingId}`);
  } catch {
    return null;
  }
}
