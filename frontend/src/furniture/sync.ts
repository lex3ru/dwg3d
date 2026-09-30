/** Saving placed furniture row by row: the diff against what the server
 * confirmed last, and a readable message when someone else got there first. */
import { ApiError, type PlacedItem, type RowConflict, type RowOp } from '../api'

const FIELDS = ['layer', 'floor', 'item', 'at', 'angle', 'size', 'note', 'elev', 'fov', 'range'] as const
const LABEL: Record<string, string> = {
  layer: 'слой', floor: 'этаж', item: 'предмет', at: 'положение', angle: 'поворот', size: 'размер', note: 'заметка',
  elev: 'высота установки', fov: 'угол обзора', range: 'дальность',
}

const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null)

/** Create / update / delete operations turning `saved` into `list`; updates carry
 * only the changed fields (null removes an override) and the saved version. */
export function furnitureOps(saved: Map<string, PlacedItem>, list: PlacedItem[]): RowOp[] {
  const ops: RowOp[] = []
  const ids = new Set<string>()
  for (const it of list) {
    ids.add(it.id)
    const prev = saved.get(it.id)
    if (!prev) {
      const { version: _v, ...fields } = it
      ops.push({ op: 'create', ...fields })
      continue
    }
    const changed: Record<string, unknown> = {}
    for (const k of FIELDS) if (!same(it[k], prev[k]) && !(k === 'layer' && it[k] == null)) changed[k] = it[k] ?? null
    if (Object.keys(changed).length) ops.push({ op: 'update', id: it.id, version: prev.version, ...changed })
  }
  for (const [id, prev] of saved) if (!ids.has(id)) ops.push({ op: 'delete', id, version: prev.version })
  return ops
}

/** Message for a failed save; for conflicts, which items and what the other
 * person changed (compared with `before`, the state this window started from). */
export function conflictText(e: unknown, name: (id: string) => string,
  before?: (id: string) => Record<string, unknown> | undefined): string {
  const msg = e instanceof Error ? e.message : String(e)
  const conflicts = e instanceof ApiError && e.status === 409 ? (e.body?.conflicts as RowConflict[] | undefined) : undefined
  if (!conflicts?.length) return msg
  const lines = conflicts.slice(0, 8).map(({ id, current }) => {
    if (!current) return `• ${name(id)} — удалён другим пользователем`
    const was = before?.(id)
    const what = was ? FIELDS.filter((k) => k in LABEL && !same(was[k], (current as unknown as Record<string, unknown>)[k])).map((k) => LABEL[k]) : []
    return `• ${name(id)} — изменён другим пользователем${what.length ? ` (${what.join(', ')})` : ''}`
  })
  if (conflicts.length > 8) lines.push(`• и ещё ${conflicts.length - 8}`)
  return `${msg}\n\n${lines.join('\n')}\n\nПоказаны текущие данные с сервера.`
}
