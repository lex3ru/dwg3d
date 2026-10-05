import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from 'react'
import {
  ApiError, getBuilding, getDrawing, getMe, getTree, listBuildings, listPlaced, signIn, signOut,
  type Building as BuildingInfo, type Me, type TreeFloor,
} from './api'
import { Button } from './components/ui/button'
import { useTheme } from './lib/theme'
import { Building } from './pages/Building'
import { Buildings } from './pages/Buildings'
import { Home } from './pages/Home'
import { Plan } from './pages/Plan'
import { RoomCard } from './pages/RoomCard'
import { Rooms } from './pages/Rooms'
import { System } from './pages/System'
import { to, useRoute, type Route } from './shell/route'
import { Shell, type Crumb } from './shell/Shell'
import { useEvents } from './stream'

// the 3D scene is heavy (three.js): loaded when the editor is opened
const Scene = lazy(() => import('./scene/entry'))

export function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState<string | null>(null)
  const route = useRoute()
  const failed = new URLSearchParams(location.search).get('signin') === 'failed'

  useEffect(() => {
    if (failed) return
    getMe().then(setMe, (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) signIn()
      else setError(e instanceof Error ? e.message : 'Не удалось связаться с сервером')
    })
  }, [failed])

  if (failed) {
    return (
      <Centered title="Войти не удалось" text="Сеанс входа истёк или был прерван. Попробуйте ещё раз.">
        <Button onClick={() => location.assign('/')}>Войти снова</Button>
      </Centered>
    )
  }
  if (error) {
    return (
      <Centered title="Сервер недоступен" text={error}>
        <Button onClick={() => location.reload()}>Повторить</Button>
      </Centered>
    )
  }
  if (!me) return <Centered title="Загрузка…" />
  return <Signed me={me} route={route} />
}

/** What of a building every screen of it needs: the building, its floors with rooms, the drawing the editor opens. */
type Scope = { building: BuildingInfo; floors: TreeFloor[]; editor: string | null }

function useScope(id: string | null): { scope: Scope | null; error: string | null; reload: () => void } {
  const [state, setState] = useState<{ id: string; scope: Scope } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const reload = useCallback(() => {
    if (!id) return
    Promise.all([getBuilding(id), getTree(id), listPlaced(id)]).then(([building, floors, placed]) => {
      setState({ id, scope: { building, floors, editor: placed.find(p => p.build_id)?.id ?? null } })
      setError(null)
    }, (e: Error) => setError(e.message))
  }, [id])
  useEffect(reload, [reload])
  useEvents(event => { if (id && (event.type.startsWith('buildings.') || event.type === 'import.drawing.deleted')) reload() })
  return { scope: state && state.id === id ? state.scope : null, error: id ? error : null, reload }
}

function Signed({ me, route }: { me: Me; route: Route }) {
  const admin = me.user.is_admin          // until rights by area exist (stage 2), buildings are for the system administrator
  const [count, setCount] = useState<number | null>(admin ? null : 0)
  useEffect(() => { if (admin) listBuildings().then(b => setCount(b.length), () => setCount(0)) }, [admin, route.page])

  // the editor is opened by a drawing: find its building for the menu
  const [drawingOf, setDrawingOf] = useState<Record<string, string>>({})
  const drawing = route.page === 'editor' ? route.drawing : null
  useEffect(() => {
    if (drawing && admin && !drawingOf[drawing]) getDrawing(drawing).then(d => setDrawingOf(m => ({ ...m, [drawing]: d.building_id })), () => {})
  }, [drawing, admin, drawingOf])

  const current = !admin ? null : route.page === 'building' ? route.building : drawing ? drawingOf[drawing] ?? null : null
  // «Я» and the system pages keep the menu of the building one came from
  const [last, setLast] = useState<string | null>(null)
  if (current && current !== last) setLast(current)
  const buildingId = current ?? (admin && (route.page === 'me' || route.page === 'system') ? last : null)
  const { scope, error, reload } = useScope(buildingId)
  const b = scope?.building ?? null

  let content: ReactNode
  let panel: ReactNode = null
  let closePanel: (() => void) | undefined
  const crumbs: Crumb[] = []
  if (route.page === 'editor' && admin) {
    content = <Suspense fallback={<Centered title="Загрузка…" />}><Scene /></Suspense>
  } else if (route.page === 'system' && admin) {
    crumbs.push({ label: 'Состояние системы' })
    content = <System />
  } else if (route.page === 'me') {
    crumbs.push({ label: 'Я' })
    content = <Profile me={me} building={b} editor={scope?.editor ?? null} />
  } else if (route.page === 'building' && admin) {
    if (!scope) {
      content = <p className="text-sm text-muted-foreground" role={error ? 'alert' : undefined}>{error ?? 'Загрузка…'}</p>
    } else {
      const { building, floors } = scope
      const room = (id?: string) => {
        for (const f of floors) { const r = f.rooms.find(x => x.id === id); if (r) return { room: r, floor: f } }
        return null
      }
      crumbs.push({ label: building.name, href: to.home(building.id) })
      if (route.section === 'drawings') {
        crumbs.push({ label: 'Чертежи' })
        content = <Building key={building.id} id={building.id} />
      } else if (route.section === 'rooms') {
        const chosen = room(route.item)
        crumbs.push({ label: 'Помещения', href: to.rooms(building.id) })
        if (chosen) crumbs.push({ label: chosen.floor.name, href: to.plan(building.id, chosen.floor.id) }, { label: chosen.room.name || 'Без названия' })
        content = <Rooms key={route.q ?? ''} building={building.id} floors={floors} selected={route.item} initialQuery={route.q} />
        if (chosen) {
          panel = <RoomCard key={chosen.room.id + chosen.room.version} building={building.id} {...chosen} admin={admin} onChanged={reload} onPlan />
          closePanel = () => { location.hash = to.rooms(building.id) }
        }
      } else if (route.section === 'plan') {
        const chosen = room(route.sub)
        const floor = floors.find(f => f.id === route.item)
        crumbs.push({ label: 'План', href: to.plan(building.id) })
        if (floor) crumbs.push({ label: floor.name, href: to.plan(building.id, floor.id) })
        if (chosen) crumbs.push({ label: chosen.room.name || 'Без названия' })
        content = <Plan building={building.id} floors={floors} floor={route.item} room={route.sub} />
        if (chosen) {
          // beside the plan on a wide screen; on a phone the plan stays and the card is one tap away
          panel = <div className="max-md:hidden"><RoomCard key={chosen.room.id + chosen.room.version} building={building.id} {...chosen} admin={admin} onChanged={reload} /></div>
          closePanel = () => { location.hash = to.plan(building.id, route.item) }
        }
      } else {
        crumbs.push({ label: 'Кабинет' })
        content = <Home building={building} floors={floors} admin={admin} />
      }
    }
  } else {
    crumbs.push({ label: 'Мои здания' })
    content = <Buildings me={me} />
  }
  const planPanel = route.page === 'building' && route.section === 'plan'
  return (
    <Shell me={me} route={route} building={b} several={(count ?? 0) > 1 || admin} editor={scope?.editor ?? null} crumbs={crumbs}
      panel={panel} onClosePanel={closePanel} keepMain={planPanel}>
      {content}
    </Shell>
  )
}

/** The user; on a phone also what the menu on the left holds on a wide screen. */
function Profile({ me, building, editor }: { me: Me; building: BuildingInfo | null; editor: string | null }) {
  const { isDark, setTheme } = useTheme()
  const admin = me.user.is_admin
  const links: [string, string][] = [
    ...(admin && building ? [[to.drawings(building.id), 'Чертежи здания']] as [string, string][] : []),
    ...(admin && editor ? [[to.editor(editor), 'Редактор']] as [string, string][] : []),
    ...(admin ? [[to.buildings, 'Здания'], ['#/system', 'Состояние системы']] as [string, string][] : []),
  ]
  return (
    <section className="max-w-md space-y-4">
      <div>
        <h1 className="text-xl font-semibold">{me.user.name || me.user.login}</h1>
        <p className="text-sm text-muted-foreground">{[me.user.email, admin && 'администратор системы'].filter(Boolean).join(' · ')}</p>
      </div>
      {links.length > 0 && (
        <ul className="divide-y rounded-lg border bg-card text-sm">
          {links.map(([href, label]) => <li key={href}><a href={href} className="block px-3 py-2.5 hover:bg-secondary">{label}</a></li>)}
        </ul>
      )}
      <div className="flex gap-2">
        <Button variant="outline" onClick={() => setTheme(isDark ? 'light' : 'dark')}>{isDark ? 'Светлая тема' : 'Тёмная тема'}</Button>
        <Button variant="outline" onClick={() => { void signOut() }}>Выйти</Button>
      </div>
    </section>
  )
}

function Centered({ title, text, children }: { title: string; text?: string; children?: ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center">
      <h1 className="text-lg font-semibold">{title}</h1>
      {text && <p className="max-w-sm text-sm text-muted-foreground">{text}</p>}
      {children}
    </div>
  )
}
