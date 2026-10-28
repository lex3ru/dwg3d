import { query } from "@/lib/api";

// Ленты журнала (5.7.3): по зданию, этажу, помещению, предмету, единице, документу,
// пользователю. Запись находится по ссылке вида «room:<id>» — сама сущность и то, к чему она
// относится.

export interface FeedFilters {
  ref: string; // одна сущность — из перехода «Журнал» у помещения, документа…
  building: string;
  floor: string;
}

/** По какой ссылке отбирать записи: сущность из перехода, иначе этаж, иначе здание. */
export function feedRef({ ref, building, floor }: FeedFilters): string {
  if (ref) return ref;
  if (floor) return `floor:${floor}`;
  return building ? `building:${building}` : "";
}

/** Адрес ленты одной сущности; `about` — что показано, подпись над лентой. */
export function journalUrl(ref: string, about: string): string {
  return `/journal${query({ ref, about })}`;
}

/** Адрес ленты здания или его этажа. */
export function placeJournalUrl(building: string, floor?: string): string {
  return `/journal${query({ building, floor })}`;
}
