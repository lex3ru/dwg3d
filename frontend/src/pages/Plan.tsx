import { useCallback, useEffect, useState } from 'react'
import { assetTone, createAsset, getFloorPlan, listAssets, listTypes, type Asset, type CatalogType, type FloorPlanData, type TreeFloor } from '../api'
import { FloorPlan } from '../components/FloorPlan'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { useEvents } from '../stream'
import { cn } from '../lib/utils'
import { to } from '../shell/route'

/** The 2D plan of a floor: pick a floor, pick a room. */
export function Plan({ building, floors, floor, room, admin }: {
  building: string; floors: TreeFloor[]; floor?: string; room?: string
  /** the building's administrator places objects here */
  admin?: boolean
}) {
  // the ground floor first, when there is one
  const fallback = floors.find(f => f.level === 1) ?? floors[0]
  const active = floors.find(f => f.id === floor) ?? fallback
  const [plan, setPlan] = useState<{ floor: string; data: FloorPlanData } | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!active) return
    let stale = false
    getFloorPlan(active.id).then(data => { if (!stale) { setPlan({ floor: active.id, data }); setError(null) } },
      (e: Error) => { if (!stale) setError(e.message) })
    return () => { stale = true }
  }, [active])
  // the objects standing on the floor (those the user may see)
  const [assets, setAssets] = useState<Asset[]>([])
  const activeId = active?.id
  const loadAssets = useCallback(() => {
    if (activeId) listAssets({ floor_id: activeId, limit: '500' }).then(r => setAssets(r.items), () => setAssets([]))
  }, [activeId])
  useEffect(loadAssets, [loadAssets])
  useEvents(event => { if (event.type.startsWith('assets.')) loadAssets() })
  // placing: a type and a number, then a click on the plan
  const [types, setTypes] = useState<CatalogType[]>([])
  const [placing, setPlacing] = useState<{ type: string; number: string } | null>(null)
  useEffect(() => { if (admin) listTypes(true).then(setTypes, () => {}) }, [admin])
  const place = (x: number, y: number) => {
    if (!placing?.type || !placing.number.trim() || !active) return setError('Выберите тип и введите инвентарный номер')
    createAsset({ type_id: placing.type, floor_id: active.id, x, y, inventory_no: placing.number.trim() }).then(a => {
      setPlacing(null); setError(null); loadAssets(); location.hash = to.assets(building, a.id)
    }, (e: Error) => setError(e.message))
  }
  if (!active) return <p className="text-sm text-muted-foreground">В здании пока нет этажей.</p>
  const chosen = active.rooms.find(r => r.id === room)
  return (
    <section>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">План</h1>
        <nav className="flex flex-wrap gap-1" aria-label="Этажи" data-testid="floor-tabs">
          {[...floors].reverse().map(f => (
            <a key={f.id} href={to.plan(building, f.id)} title={f.name} aria-current={f.id === active.id ? 'true' : undefined}
              className={cn('min-w-8 rounded-md border px-2 py-1 text-center text-sm hover:bg-secondary',
                f.id === active.id && 'border-primary bg-primary text-primary-foreground hover:bg-primary')}>
              {f.level ?? '?'}
            </a>
          ))}
        </nav>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">{active.name} · помещений: {active.rooms.length} · объектов: {assets.filter(a => a.x != null).length}</p>
      {admin && (placing ? (
        <div className="mt-2 flex flex-wrap items-end gap-2 rounded-lg border bg-card p-2" data-testid="placing">
          <label className="grid gap-0.5 text-xs text-muted-foreground">Тип
            <select className="h-8 rounded-md border bg-card px-2 text-sm" value={placing.type} aria-label="Тип объекта"
              onChange={e => setPlacing({ ...placing, type: e.target.value })}>
              <option value="">— из каталога —</option>
              {types.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
          <label className="grid gap-0.5 text-xs text-muted-foreground">Инвентарный номер
            <Input className="h-8 w-40" value={placing.number} onChange={e => setPlacing({ ...placing, number: e.target.value })} />
          </label>
          <span className="pb-1.5 text-sm">и щёлкните место на плане</span>
          <Button variant="ghost" size="sm" onClick={() => { setPlacing(null); setError(null) }}>Отмена</Button>
        </div>
      ) : <Button className="mt-2" variant="outline" size="sm" onClick={() => setPlacing({ type: '', number: '' })}>Поставить объект</Button>)}
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      {plan?.floor === active.id && (
        <FloorPlan plan={plan.data} selected={room} className="mt-3 max-h-[70vh]"
          dots={assets.filter(a => a.x != null).map(a => ({ id: a.id, x: a.x!, y: a.y!, tone: assetTone(a), title: `${a.type_name} · ${a.inventory_no}` }))}
          onDot={id => { location.hash = to.assets(building, id) }} onPoint={placing ? place : undefined}
          onSelect={id => { location.hash = to.plan(building, active.id, id) }} />
      )}
      {/* on a phone the card is a page of its own; here: what is chosen, one tap from its card */}
      {chosen && (
        <a href={to.rooms(building, chosen.id)} className="mt-2 flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm md:hidden">
          <span className="flex-1 font-medium">{chosen.name || 'Помещение без названия'}</span>
          <span className="text-muted-foreground">{chosen.area.toLocaleString('ru')} м²</span>
        </a>
      )}
    </section>
  )
}
