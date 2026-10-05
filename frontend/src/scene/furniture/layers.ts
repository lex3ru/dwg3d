import type { Layer, LayerKindInfo } from '../api'

/** Layers that may hold a catalog item of category `cat` (their kind takes points of it). */
export function layersFor(layers: Layer[], kinds: LayerKindInfo[], cat: string) {
  return layers.filter((l) => {
    const k = kinds.find((x) => x.kind === l.kind)
    return !!k && k.geoms.includes('point') && (k.categories == null || k.categories.includes(cat))
  })
}

/** The variant group of a layer (the id of its first layer; its own id when it has no variants). */
export const variantGroup = (l: Layer) => (l.props?.variant_group as string | undefined) ?? l.id

/** The variants of layers: groups of layers sharing props.variant_group (only groups of two or more). */
export function variantGroups(layers: Layer[]): Layer[][] {
  const g = new Map<string, Layer[]>()
  for (const l of layers) g.set(variantGroup(l), [...(g.get(variantGroup(l)) ?? []), l])
  return [...g.values()].filter((x) => x.length > 1)
}
