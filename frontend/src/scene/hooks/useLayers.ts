import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { layerKinds, listLayers, type Job, type Layer, type LayerKindInfo, type PlacedItem } from '../api'
import type { CatalogItem } from '../furniture/catalog'
import { variantGroup, variantGroups } from '../furniture/layers'
import type { Rules } from '../viewer/routing'

/**
 * Layers of the project as this viewer sees them: which are shown and which this viewer has locked against
 * a slip of the hand (both kept per project in localStorage — the services keep no lock), the active one
 * for new items, the variant chosen in each group, and the layer kinds with the flow rules from the server.
 */
export function useLayers(shown: Job | null, projectId: string) {
  const [served, setLayers] = useState<Layer[]>([])
  useEffect(() => { setLayers(shown?.layers ?? []) }, [shown?.layers])
  const [myLocks, setMyLocks] = useState<Set<string>>(new Set())
  /** the server's layers with this viewer's locks laid over (a layer the server locks stays locked) */
  const layers = useMemo(() => served.map((l) => (!l.locked && myLocks.has(l.id) ? { ...l, locked: true } : l)), [served, myLocks])
  const [kinds, setKinds] = useState<LayerKindInfo[]>([])
  const [rules, setRules] = useState<Rules | null>(null)
  useEffect(() => { layerKinds().then((k) => { setKinds(k.kinds); setRules(k) }).catch(() => {}) }, [])
  const [hiddenLayers, setHiddenLayers] = useState<Set<string>>(new Set())
  const [activeLayer, setActiveLayer] = useState<string | null>(null)
  // variants of a layer: one of them is shown (the first by default)
  const [variantPick, setVariantPick] = useState<Record<string, string>>({})
  useEffect(() => {
    if (!projectId) return
    // this viewer's choice (localStorage); a layer hidden on the server starts hidden
    let saved: { hidden?: string[]; active?: string | null; variants?: Record<string, string>; locked?: string[] } = {}
    try { saved = JSON.parse(localStorage.getItem(`dwg3d.layers.${projectId}`) ?? '{}') } catch { /* private mode */ }
    setHiddenLayers(new Set(saved.hidden ?? (shown?.layers ?? []).filter((l) => !l.visible).map((l) => l.id)))
    setActiveLayer(saved.active ?? null)
    setVariantPick(saved.variants ?? {})
    setMyLocks(new Set(saved.locked ?? []))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])
  useEffect(() => {
    if (!projectId) return
    try { localStorage.setItem(`dwg3d.layers.${projectId}`, JSON.stringify({ hidden: [...hiddenLayers], active: activeLayer,
      variants: variantPick, locked: [...myLocks] })) } catch { /* private mode */ }
  }, [projectId, hiddenLayers, activeLayer, variantPick, myLocks])
  /** Hidden here: switched off, or another variant of the layer is chosen. */
  const hiddenNow = useMemo(() => {
    const h = new Set(hiddenLayers)
    for (const g of variantGroups(layers)) {
      const pick = g.find((l) => l.id === variantPick[variantGroup(g[0])]) ?? g[0]
      for (const l of g) if (l.id !== pick.id) h.add(l.id)
    }
    return h
  }, [hiddenLayers, layers, variantPick])
  const showVariant = (id: string) => {
    const l = layers.find((x) => x.id === id)
    if (!l) return
    setVariantPick((v) => ({ ...v, [variantGroup(l)]: id }))
    setHiddenLayers((h) => { const n = new Set(h); n.delete(id); return n })
  }
  const toggleLayer = (id: string) => setHiddenLayers((h) => {
    const n = new Set(h)
    if (n.has(id)) n.delete(id)
    else n.add(id)
    return n
  })
  /** Show only the layers of these kinds. */
  const showOnlyKinds = (kinds: string[]) => setHiddenLayers(new Set(layers.filter((l) => !kinds.includes(l.kind)).map((l) => l.id)))
  const setAllLayers = (show: boolean) => setHiddenLayers(show ? new Set() : new Set(layers.map((l) => l.id)))
  /** The layer for a new catalog item: the chosen one if it takes the item, else the first that does. */
  const layerFor = (c: CatalogItem): string | undefined => {
    const takes = (l: Layer) => {
      const k = kinds.find((x) => x.kind === l.kind)
      return !!k && k.geoms.includes('point') && (k.categories == null || k.categories.includes(c.cat))
    }
    const act = layers.find((l) => l.id === activeLayer)
    if (act && takes(act)) return act.id
    // a kind made for this category (CCTV, fire alarm, Wi-Fi...): its layer, or none yet — the server creates it.
    // Of its layers the one on the screen (the fact or the variant shown); a hidden one is shown, so that what
    // is placed does not vanish the moment it is put down
    const own = kinds.find((k) => k.categories?.includes(c.cat))
    const mine = layers.filter((l) => (own ? l.kind === own.kind : true) && takes(l))
    const seen = mine.find((l) => !hiddenNow.has(l.id))
    if (seen) return seen.id
    const pick = mine.find((l) => hiddenLayers.has(l.id))
    if (pick) setHiddenLayers((h) => { const n = new Set(h); n.delete(pick.id); return n })
    return pick?.id ?? mine[0]?.id
  }
  const refuseLocked = (it: PlacedItem | undefined) => {
    const l = layers.find((x) => x.id === it?.layer && x.locked)
    if (l) alert(myLocks.has(l.id) ? `Слой «${l.name}» заблокирован: снимите замок в дереве слева` : `Слой «${l.name}» только для просмотра`)
    return !!l
  }
  const reloadLayers = useCallback(() => {
    if (projectId) listLayers(projectId).then(setLayers).catch(() => {})
  }, [projectId])
  /** After a save: reload the layers (their object counts, or one the server has just created), a moment
   * after the last save of a burst (dragging saves often). */
  const syncTimer = useRef<number | undefined>(undefined)
  const syncLayers = useCallback(() => {
    window.clearTimeout(syncTimer.current)
    syncTimer.current = window.setTimeout(reloadLayers, 500)
  }, [reloadLayers])
  useEffect(() => () => window.clearTimeout(syncTimer.current), [])
  /** Lock or unlock a layer for this viewer only: the services keep no lock of a layer. */
  const lockLayer = (l: Layer, locked: boolean) => setMyLocks((m) => {
    const n = new Set(m)
    if (locked) n.add(l.id)
    else n.delete(l.id)
    return n
  })
  return {
    lockLayer, showOnlyKinds, layers, setLayers, kinds, rules, hiddenNow, activeLayer, setActiveLayer,
    showVariant, toggleLayer, setAllLayers, layerFor, refuseLocked, syncLayers, reloadLayers,
  }
}
