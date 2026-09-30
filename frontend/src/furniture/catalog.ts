/** Catalog of furniture and equipment for medical centres — types and the
 * client-side copy loaded from the server (GET /api/catalog, PostgreSQL;
 * source: backend/dwg3d/catalog_seed.yaml) before the app renders.
 *
 * Sizes are meters: w — width (local X), d — depth (local Z, the front faces
 * +Z, i.e. away from the wall), h — height. `clear` is the service zone in
 * front of the item (where a person stands or sits to use it), `wall` — the
 * item is normally placed back to a wall, `elev` — mounting height of the
 * bottom (wall-hung items). `kind` selects the procedural model used when no
 * GLB `model` is given (or while it loads). */

export interface CatalogItem {
  id: string
  name: string
  cat: string
  w: number
  d: number
  h: number
  kind: string
  color?: string
  clear?: number
  wall?: boolean
  elev?: number
  /** GLB under /catalog/, scaled to w×d×h; `modelRot` turns it (deg) so its front faces +Z */
  model?: string
  /** where the GLB is served: /catalog/… (bundled) or /api/catalog/models/… (uploaded) */
  modelUrl?: string
  modelRot?: number
  tags?: string
  /** CCTV camera: horizontal view angle (deg, 360 = panoramic), range and
   * face identification distance (m); it looks along its front (+Z) */
  cam?: { fov: number; range: number; ident: number }
  article?: string
  supplier?: string
  price?: number
  currency?: string
  /** false — withdrawn: still drawn where already placed, hidden from the picker */
  active?: boolean
}

export interface Category { id: string; name: string; color: string }

export let CATEGORIES: Category[] = []
/** Items offered for placement (active ones) */
export let CATALOG: CatalogItem[] = []
let byId = new Map<string, CatalogItem>()
/** Why the catalog could not be loaded (null when it is loaded) */
export let catalogError: string | null = null

export async function loadCatalog(): Promise<void> {
  try {
    const r = await fetch('/api/catalog')
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const data = await r.json() as { categories: Category[]; items: CatalogItem[] }
    CATEGORIES = data.categories
    CATALOG = data.items.filter((c) => c.active !== false)
    byId = new Map(data.items.map((c) => [c.id, c]))
    catalogError = null
  } catch (e) {
    catalogError = `Каталог не загружен: ${e instanceof Error ? e.message : e}`
    console.error(catalogError)
  }
}

/** Stand-in for an item missing from the catalog (e.g. removed later). */
export function catalogItem(id: string): CatalogItem {
  return byId.get(id) ?? { id, name: `Неизвестный предмет (${id})`, cat: 'storage', w: 0.5, d: 0.5, h: 0.5, kind: 'device' }
}
