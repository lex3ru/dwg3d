import { LogOut, Moon, Sun } from 'lucide-react'
import { Component, lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  ApiError, assetTone, endGuest, getFloorPlan, getMe, getModel, getTreeWithBuilding, listAllAssets, listAllTypes,
  type Asset, type Building, type CatalogType, type DrawingModel, type FloorPlanData, type GuestMe, type TreeFloor,
} from '../api'
import { FloorPlan, type Dot } from '../components/FloorPlan'
import { itemOf } from '../components/glyphs'
import { Button } from '../components/ui/button'
import { Tip } from '../components/ui/tooltip'
import { useTheme } from '../lib/theme'
import { cn, until } from '../lib/utils'
import { StateBadge } from './Assets'

// three.js is heavy: loaded when the 3D view is opened
const ModelPreview = lazy(() => import('../components/ModelPreview'))

const floorName = (f: TreeFloor | undefined) => (!f ? 'этаж' : f.level != null ? `этаж ${f.level}` : f.name || 'этаж')

/** A model that could not be loaded must not take the whole page down. */
class Fallback extends Component<{ text: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? <p className="text-sm text-muted-foreground">{this.props.text}</p> : this.props.children }
}

/**
 * What someone without an account sees by a link: one building, or a floor or a room of it — the plan,
 * the 3D model, the objects; read only. No menu, no search, no other pages, no stream of events.
 */
export function GuestView({ me, onEnded, onLeft }: {
  me: GuestMe
  /** the link was revoked or has expired while looking */
  onEnded: () => void
  /** the guest finished the viewing */
  onLeft: () => void
}) {
  const g = me.guest
  const { isDark, setTheme } = useTheme()
  const [tree, setTree] = useState<{ building: Building; floors: TreeFloor[] } | null>(null)
  const [models, setModels] = useState<DrawingModel[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [floor, setFloor] = useState<string | null>(g.floor_id)
  const [view, setView] = useState<'plan' | '3d'>('plan')
  // the room of a room link is highlighted; a click on another room highlights that one
  const [room, setRoom] = useState<string | null>(g.scope.kind === 'room' ? g.scope.id : null)
  const [plan, setPlan] = useState<{ floor: string; data: FloorPlanData } | null>(null)
  const [assets, setAssets] = useState<{ floor: string; items: Asset[] } | null>(null)
  // the catalog's types: the size and shape of every object drawn (a guest the catalog turns away sees half-metre boxes)
  const [types, setTypes] = useState<CatalogType[]>([])
  useEffect(() => { listAllTypes().then(setTypes, () => {}) }, [])
  const byType = useMemo(() => new Map(types.map(t => [t.id, t])), [types])
  const [leaving, setLeaving] = useState(false)

  // a guest has one address
  useEffect(() => { if (!location.hash.startsWith('#/g')) history.replaceState(null, '', '#/g') }, [])
  useEffect(() => {
    getTreeWithBuilding(g.building_id).then(setTree, (e: Error) => setError(e.message))
    getModel(g.building_id).then(setModels, () => setModels([]))
  }, [g.building_id])
  // the link may be revoked while one looks and nothing is asked: ask now and then whether it still holds
  const ended = useRef(onEnded)
  useEffect(() => { ended.current = onEnded })
  useEffect(() => {
    const timer = setInterval(() => {
      getMe().catch((e: unknown) => { if (e instanceof ApiError && e.status === 401) ended.current() })
    }, 60_000)
    return () => clearInterval(timer)
  }, [])

  const floors = useMemo(() => tree?.floors ?? [], [tree])
  const active = floors.find(f => f.id === floor) ?? floors.find(f => f.level === 1) ?? floors[0]
  const activeId = active?.id
  useEffect(() => {
    if (!activeId) return
    let stale = false
    getFloorPlan(activeId).then(data => { if (!stale) setPlan({ floor: activeId, data }) }, (e: Error) => { if (!stale) setError(e.message) })
    listAllAssets({ building_id: g.building_id, floor_id: activeId })
      .then(items => { if (!stale) setAssets({ floor: activeId, items }) }, (e: Error) => { if (!stale) setError(e.message) })
    return () => { stale = true }
  }, [activeId, g.building_id])

  const rooms = useMemo(() => new Map(floors.flatMap(f => f.rooms.map(r => [r.id, r.name || 'без названия'] as const))), [floors])
  const name = g.building_name ?? tree?.building.name ?? 'Здание'
  const area = g.scope.kind === 'building' ? 'всё здание'
    : g.scope.kind === 'floor' ? floorName(floors.find(f => f.id === g.scope.id))
    : `помещение «${rooms.get(g.scope.id) ?? '…'}»`
  const items = assets && assets.floor === activeId ? assets.items : []
  // the chosen room's objects first
  const sorted = room ? [...items].sort((a, b) => Number(b.room_id === room) - Number(a.room_id === room)) : items
  const model = models?.find(d => d.id === active?.drawing_id) ?? (models?.length === 1 ? models[0] : undefined)

  const leave = () => {
    setLeaving(true)
    endGuest().then(onLeft, (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) onLeft()            // already over
      else { setLeaving(false); setError(e instanceof Error ? e.message : 'Не удалось закончить просмотр') }
    })
  }
  const tab = (on: boolean) => cn('min-w-8 rounded-md border px-2.5 py-1 text-center text-sm hover:bg-secondary',
    on && 'border-primary bg-primary text-primary-foreground hover:bg-primary')

  return (
    <div className="flex h-full flex-col" data-testid="guest-view">
      <header className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b bg-card px-4 py-2">
        <div className="min-w-0 flex-1">
          <h1 className="truncate font-semibold">{name}</h1>
          <p className="text-sm text-muted-foreground">
            Просмотр по ссылке до {until(g.expires_at)} · <span data-testid="guest-area">{area}</span>
          </p>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" aria-label={isDark ? 'Светлая тема' : 'Тёмная тема'}
            hintSide="bottom"
            hint={isDark ? 'Включить светлое оформление; выбор запомнится в этом браузере' : 'Включить тёмное оформление; выбор запомнится в этом браузере'} onClick={() => setTheme(isDark ? 'light' : 'dark')}>
            {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </Button>
          <Button variant="outline" size="sm" disabled={leaving} onClick={leave} hintSide="bottom"
            hint="Закрыть просмотр в этом браузере; сама ссылка продолжит действовать до своего срока"><LogOut className="size-4" />Закончить просмотр</Button>
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl px-4 py-4">
          {error && <p role="alert" className="mb-3 text-sm text-destructive">{error}</p>}
          {!tree ? (!error && <p className="text-sm text-muted-foreground">Загрузка…</p>) : !active ? (
            <p className="text-sm text-muted-foreground">В здании пока нет этажей.</p>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-3">
                {floors.length > 1 && (
                  <nav className="flex flex-wrap gap-1" aria-label="Этажи" data-testid="floor-tabs">
                    {[...floors].reverse().map(f => (
                      <Tip key={f.id} label={`${f.name || 'Этаж'}: его план, 3D-модель и объекты`}>
                        <button type="button" aria-current={f.id === active.id ? 'true' : undefined}
                          className={tab(f.id === active.id)} onClick={() => setFloor(f.id)}>{f.level ?? '?'}</button>
                      </Tip>
                    ))}
                  </nav>
                )}
                <div className="flex gap-1" role="group" aria-label="Вид">
                  <Tip label="Поэтажный план с объектами: щелчок по помещению выделяет его и поднимает его объекты в списке">
                    <button type="button" className={tab(view === 'plan')} aria-pressed={view === 'plan'} onClick={() => setView('plan')}>План</button>
                  </Tip>
                  <Tip label="Объёмная модель этажа: вращение — мышью, приближение — колесом">
                    <button type="button" className={tab(view === '3d')} aria-pressed={view === '3d'} onClick={() => setView('3d')}>3D</button>
                  </Tip>
                </div>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {active.name} · помещений: {active.rooms.length} · объектов: {items.length}
                {room && rooms.has(room) && <> · выбрано: {rooms.get(room)}</>}
              </p>

              {view === 'plan' ? (
                <div className="mt-3" data-testid="guest-plan">
                  {plan?.floor === active.id ? (
                    <FloorPlan plan={plan.data} selected={room} className="max-h-[70vh] max-md:max-h-[55vh]"
                      items={items.filter(a => a.x != null).map(a => itemOf(a, byType, { tone: assetTone(a) as Dot['tone'], chosen: !!room && a.room_id === room }))}
                      onSelect={id => setRoom(r => (r === id ? null : id))} />
                  ) : <p className="text-sm text-muted-foreground">Загрузка плана…</p>}
                </div>
              ) : (
                <div className="mt-3" data-testid="guest-3d">
                  {models === null ? <p className="text-sm text-muted-foreground">Загрузка…</p>
                    : !model ? <p className="text-sm text-muted-foreground">3D-модели этого этажа нет.</p> : (
                      <Fallback key={model.model_url} text="3D-модель не загрузилась.">
                        <Suspense fallback={<p className="text-sm text-muted-foreground">Загрузка 3D-модели…</p>}>
                          <ModelPreview url={model.model_url} className="h-[65vh] max-md:h-[50vh]" />
                        </Suspense>
                      </Fallback>
                    )}
                </div>
              )}

              <section className="mt-5" data-testid="guest-objects">
                <h2 className="text-sm font-medium">Объекты этажа · {items.length}</h2>
                {assets?.floor !== active.id ? <p className="mt-2 text-sm text-muted-foreground">Загрузка…</p>
                  : sorted.length === 0 ? <p className="mt-2 text-sm text-muted-foreground">На этом этаже объектов нет.</p> : (
                    <ul className="mt-2 divide-y rounded-lg border bg-card text-sm">
                      {sorted.map(a => (
                        <li key={a.id} data-asset={a.inventory_no}
                          className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2', room && a.room_id === room && 'bg-accent')}>
                          <span className="min-w-40 flex-1"><span className="font-medium">{a.type_name}</span>
                            <span className="ml-2 text-muted-foreground">{a.inventory_no}</span></span>
                          <span className="text-muted-foreground">{rooms.get(a.room_id) ?? ''}</span>
                          <StateBadge a={a} />
                        </li>
                      ))}
                    </ul>
                  )}
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  )
}
