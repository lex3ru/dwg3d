import type { Layer, LayerKindInfo } from '../api'

/** Layers that may hold a catalog item of category `cat` (their kind takes points of it). */
export function layersFor(layers: Layer[], kinds: LayerKindInfo[], cat: string) {
  return layers.filter((l) => {
    const k = kinds.find((x) => x.kind === l.kind)
    return !!k && k.geoms.includes('point') && (k.categories == null || k.categories.includes(cat))
  })
}
