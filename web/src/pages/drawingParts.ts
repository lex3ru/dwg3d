// Предложение карточки чертежа: какая часть листа — какой этаж (5.1.3 п. 1, 4, R-064)

export interface PartInfo {
  key: string;
  name: string;
  level: number | null;
  width: number;
  height: number;
  preview: string;
  floor_like: boolean;
  // что это за часть листа — по подписи, штампу и форме (R-061); "" — не понять
  kind?: string;
}

export interface PartResult {
  floor_id: string;
  floor: string;
  walls: number;
  openings: number;
  rooms: number;
  labelled: number;
  issues: number;
  notes: string[];
  // замкнут ли план: концы стен без примыкания и доля этажа в помещениях, % (R-066);
  // у итогов до DWG3D-23 этого нет
  open_ends?: number;
  covered?: number;
  closed?: boolean;
}

interface Floor {
  id: string;
  name: string;
}

export function floorName(part: PartInfo): string {
  if (part.level !== null && part.level !== undefined) return part.level < 0 ? "Подвал" : `${part.level} этаж`;
  if (/техн/i.test(part.name)) return "Технический этаж";
  if (/мансард/i.test(part.name)) return "Мансарда";
  if (/цокол/i.test(part.name)) return "Цокольный этаж";
  const name = part.name.replace(/^план\s+/i, "").trim();
  return name ? name[0]!.toUpperCase() + name.slice(1) : "";
}

// названия этажей сравниваются как на сервере: без регистра и лишних пробелов
export const sameName = (name: string) => name.trim().replace(/\s+/g, " ").toLowerCase();

/** Выбор этажей по умолчанию и названия новых этажей. Переведённые части и не-этажи (рамки,
 *  штампы, таблицы) — «не переводить»: иначе повторный перевод заменит планы этажей штампами.
 *  Часть-этаж — на этаж с тем же названием, если его ещё не взяла другая часть, иначе — новый
 *  этаж; названия новых этажей не повторяют ни этажи здания, ни друг друга. */
export function propose(parts: PartInfo[], results: Record<string, PartResult>, floors: Floor[]): { choice: Record<string, string>; names: Record<string, string> } {
  const choice: Record<string, string> = {};
  const names: Record<string, string> = {};
  const used = new Set(floors.map((f) => sameName(f.name)));
  const taken = new Set<string>();
  // часть без подписи — «N этаж», свободный номер по порядку частей-этажей; прочие — после них
  let n = 0;
  const free = () => {
    do n += 1;
    while (used.has(sameName(`${n} этаж`)));
    used.add(sameName(`${n} этаж`));
    return `${n} этаж`;
  };
  for (const p of [...parts.filter((p) => p.floor_like), ...parts.filter((p) => !p.floor_like)]) {
    const own = floorName(p);
    const same = own ? floors.find((f) => sameName(f.name) === sameName(own)) : undefined;
    const done = results[p.key];
    if (done || !p.floor_like) {
      choice[p.key] = "";
      names[p.key] = own || done?.floor || free();
    } else if (same) {
      // этаж уже взят другой частью с той же подписью — эта, скорее всего, штамп или копия
      choice[p.key] = taken.has(same.id) ? "" : same.id;
      taken.add(same.id);
      names[p.key] = own;
    } else if (own && used.has(sameName(own))) {
      choice[p.key] = "";
      names[p.key] = own;
    } else {
      choice[p.key] = "new";
      names[p.key] = own || free();
      used.add(sameName(names[p.key]!));
    }
  }
  return { choice, names };
}
