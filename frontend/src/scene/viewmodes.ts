import { Briefcase, Building, Cable, Palette, Route, SlidersHorizontal, type LucideIcon } from 'lucide-react'
import type { Layer } from './api'
import type { Display } from './state'

/**
 * Ready-made views of the building: what to show on the plan and which kinds
 * of layers. Choosing one writes these settings; the current mode is whichever
 * preset the settings match now (otherwise "own view").
 */
export type ViewMode = 'architecture' | 'rooms' | 'systems' | 'flows' | 'client'

export interface ModeDef {
  id: ViewMode
  label: string
  hint: string
  key: string
  icon: LucideIcon
  patch: Partial<Display>
  /** kinds of layers shown (the others are hidden); null leaves the layers as they are */
  kinds: string[] | null
  /** hides the docks and the status bar: for showing the model */
  presentation?: boolean
}

const OFF: Partial<Display> = { highlight: true, furniture: false, camViews: false, pois: false, comments: false, xray: false }

export const MODES: ModeDef[] = [
  { id: 'architecture', label: 'Архитектура', key: '1', icon: Building, kinds: [],
    hint: 'Стены, проёмы, этажи — без цветов помещений, подписей и объектов',
    patch: { ...OFF, roomColors: false, labels: false, roof: true, glass: true } },
  { id: 'rooms', label: 'Помещения', key: '2', icon: Palette, kinds: [],
    hint: 'Помещения по типам: цвета, подписи, входы и лифты',
    patch: { ...OFF, roomColors: true, labels: true, pois: true } },
  { id: 'systems', label: 'Инженерные системы', key: '3', icon: Cable, kinds: ['cctv', 'lighting', 'network', 'fire', 'access', 'wifi'],
    hint: 'Видеонаблюдение, освещение, СКС, пожарная сигнализация, СКУД, Wi-Fi: оборудование, обзор, освещённость и покрытие',
    patch: { ...OFF, furniture: true, camViews: true, roomColors: false, labels: false, xray: true } },
  { id: 'flows', label: 'Маршруты и потоки', key: '4', icon: Route, kinds: ['routes', 'zones'],
    hint: 'Пути людей и зоны, конфликты потоков',
    patch: { ...OFF, roomColors: true, labels: true, pois: true } },
  { id: 'client', label: 'Заказчику', key: '5', icon: Briefcase, kinds: null, presentation: true,
    hint: 'Без панелей: модель, этажи и комментарии',
    patch: { highlight: true, roomColors: true, labels: true, furniture: true, camViews: false, pois: true, comments: true, xray: false } },
]

export const CUSTOM = { label: 'Свой вид', icon: SlidersHorizontal }

/** The preset the settings match now, or null. */
export function currentMode(display: Display, layers: Layer[], hidden: Set<string>): ModeDef | null {
  return MODES.find((m) => {
    if (!(Object.entries(m.patch) as [keyof Display, unknown][]).every(([k, v]) => display[k] === v)) return false
    if (!m.kinds) return true
    return layers.every((l) => hidden.has(l.id) === !m.kinds!.includes(l.kind))
  }) ?? null
}
