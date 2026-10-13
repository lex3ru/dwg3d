// The objects of engineering systems are objects too, but each system is a layer of its own in the editor:
// the catalog's section says which (its ids are those of the catalog's starter data). Everything else is
// in «Объекты учёта». Kept apart from compat.ts so that pages can use it without loading the editor.

const LAYER = 'assets'
const VARIANT = 'variant:'
const section = (n: number) => `0192f000-0000-7000-8000-${n.toString(16).padStart(12, '0')}`

export const SYSTEMS = [
  { kind: 'cctv', name: 'Видеонаблюдение', category: section(0x105) },
  { kind: 'lighting', name: 'Освещение', category: section(0x10a) },
  { kind: 'wifi', name: 'Wi-Fi', category: section(0x109) },
  { kind: 'fire', name: 'Пожарная сигнализация', category: section(0x107) },
  { kind: 'access', name: 'СКУД', category: section(0x108) },
  { kind: 'network', name: 'СКС и электрика', category: section(0x106) },
]

/** `assets` or `assets.<system>`: the layer of the objects of a section of the catalog */
export function layerOf(category: string | null | undefined): string {
  const x = SYSTEMS.find((y) => y.category === category)
  return x ? `${LAYER}.${x.kind}` : LAYER
}

/** the suffix of a layer of a system: `.cctv`, or '' for «Объекты учёта» */
export function systemOf(layer: string): string {
  const i = layer.indexOf('.')
  return i < 0 ? '' : layer.slice(i)
}

/** The set a layer of objects belongs to: `assets` for the fact, `variant:<id>` for a variant of the planning service.
 * A new object stays in the set of the layer being edited — a light put in a variant is the variant's, never the fact's. */
export function layerSet(layer: string): string {
  return layer.slice(0, layer.length - systemOf(layer).length)
}

/** Which variant each layer of objects shows, for the editor to open a variant of the planning service on all of them. */
export function showingVariant(vid: string): Record<string, string> {
  return Object.fromEntries([LAYER, ...SYSTEMS.map((x) => `${LAYER}.${x.kind}`)].map((l) => [l, VARIANT + vid + systemOf(l)]))
}
