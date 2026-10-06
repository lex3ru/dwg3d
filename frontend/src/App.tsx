import { lazy, Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import {
  ApiError, byQr, getBuilding, getDrawing, getMe, getTree, listBuildings, listPlaced, manages, signIn, signOut,
  type Building as BuildingInfo, type Me, type TreeFloor,
} from './api'
import { Button } from './components/ui/button'
import { useTheme } from './lib/theme'
import { Access } from './pages/Access'
import { AssetCard } from './pages/AssetCard'
import { Assets } from './pages/Assets'
import { Building } from './pages/Building'
import { Buildings } from './pages/Buildings'
import { Catalog } from './pages/Catalog'
import { Home } from './pages/Home'
import { People } from './pages/People'
import { Plan } from './pages/Plan'
import { RoomCard } from './pages/RoomCard'
import { Rooms } from './pages/Rooms'
import { Scan } from './pages/Scan'
import { System } from './pages/System'
import { to, useRoute, type Route } from './shell/route'
import { Shell, type Crumb } from './shell/Shell'
import { useEvents } from './stream'

const noop = () => {}

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
  return <Signed me={me} route={route} onRights={() => { getMe().then(setMe, () => {}) }} />
}

/** What of a building every screen of it needs: the building, its floors with rooms, the drawing the editor opens. */
type Scope = { building: BuildingInfo; floors: TreeFloor[]; editor: string | null }

function useScope(id: string | null): { scope: Scope | null; error: string | null; reload: () => void } {
  const [state, setState] = useState<{ id: string; scope: Scope } | null>(null)
  const [error, setError] = useState<string | null>(null)
  // an answer about a building one has already left must not replace the one on screen
  const wanted = useRef(id)
  useEffect(() => { wanted.current = id }, [id])
  const reload = useCallback(() => {
    if (!id) return
    Promise.all([getBuilding(id), getTree(id), listPlaced(id)]).then(([building, floors, placed]) => {
      if (wanted.current !== id) return
      setState({ id, scope: { building, floors, editor: placed.find(p => p.build_id)?.id ?? null } })
      setError(null)
    }, (e: Error) => { if (wanted.current === id) { setState(null); setError(e.message) } })      // gone, or no longer ours
  }, [id])
  useEffect(reload, [reload])
  useEvents(event => { if (id && (event.type.startsWith('buildings.') || event.type === 'import.drawing.deleted')) reload() })
  return { scope: state && state.id === id ? state.scope : null, error: id ? error : null, reload }
}

function Signed({ me, route, onRights }: { me: Me; route: Route; onRights: () => void }) {
  const sys = me.user.is_admin
  // the buildings the user may see: one — go straight into it; several — the name in the menu leads to the list
  const [mine, setMine] = useState<{ page: string; ids: string[] } | null>(null)
  const [again, setAgain] = useState(0)
  useEffect(() => {
    listBuildings().then(b => setMine({ page: route.page, ids: b.map(x => x.id) }), () => setMine({ page: route.page, ids: [] }))
  }, [route.page, again])
  // someone of the directory who sees no building: rights given a moment ago (or the very first
  // sign-in, when the account has just found its person) may not have reached every service yet
  const waiting = !sys && !!me.person && mine?.ids.length === 0 && again < 3
  useEffect(() => {
    if (!waiting) return
    const timer = setTimeout(() => setAgain(n => n + 1), 2500)
    return () => clearTimeout(timer)
  }, [waiting, again])
  // the set of buildings changed: rights were given or taken away — ask again who we are
  const seen = mine?.ids.join()
  const [known, setKnown] = useState(seen)
  if (seen !== known) { setKnown(seen); if (known !== undefined) onRights() }
  useEffect(() => {
    // only by a list asked for on this very page: an older one may name a building that is no longer ours
    if (!sys && route.page === 'buildings' && mine?.page === 'buildings' && mine.ids.length === 1) location.replace(to.home(mine.ids[0]))
  }, [sys, route.page, mine])

  // the editor is opened by a drawing: find its building for the menu
  const [drawingOf, setDrawingOf] = useState<Record<string, string>>({})
  const drawing = route.page === 'editor' ? route.drawing : null
  useEffect(() => {
    if (drawing && !drawingOf[drawing]) getDrawing(drawing).then(d => setDrawingOf(m => ({ ...m, [drawing]: d.building_id })), () => {})
  }, [drawing, drawingOf])

  const current = route.page === 'building' ? route.building : drawing ? drawingOf[drawing] ?? null : null
  // «Я» and the system pages keep the menu of the building one came from
  const [last, setLast] = useState<string | null>(null)
  if (current && current !== last) setLast(current)
  const buildingId = current ?? (route.page === 'me' || route.page === 'system' || route.page === 'catalog' || route.page === 'scan' ? last : null)
  const { scope, error, reload } = useScope(buildingId)
  const b = scope?.building ?? null
  // what the building's administrator may: drawings, the editor, people, rights
  const admin = buildingId ? manages(me, buildingId) : sys

  let content: ReactNode
  let panel: ReactNode = null
  let closePanel: (() => void) | undefined
  const crumbs: Crumb[] = []
  if (route.page === 'editor' && admin) {
    content = <Suspense fallback={<Centered title="Загрузка…" />}><Scene editable={admin} /></Suspense>
  } else if (route.page === 'catalog' && sys) {
    crumbs.push({ label: 'Каталог', href: '#/catalog' })
    content = <Catalog kind={route.kind} item={route.item} />
  } else if (route.page === 'system' && sys) {
    crumbs.push({ label: 'Состояние системы' })
    content = <System />
  } else if (route.page === 'qr') {
    crumbs.push({ label: 'QR-метка' })
    content = <ByQr code={route.code} />
  } else if (route.page === 'scan') {
    crumbs.push({ label: 'Сканировать' })
    content = <Scan />
  } else if (route.page === 'me') {
    crumbs.push({ label: 'Я' })
    content = <Profile me={me} building={b} editor={scope?.editor ?? null} />
  } else if (route.page === 'building') {
    if (!scope) {
      // a building one has no right to is not there at all
      content = error ? <Centered title="Здание не найдено" text="Его нет или у вас нет к нему доступа." />
        : <p className="text-sm text-muted-foreground">Загрузка…</p>
    } else {
      const { building, floors } = scope
      const room = (id?: string) => {
        for (const f of floors) { const r = f.rooms.find(x => x.id === id); if (r) return { room: r, floor: f } }
        return null
      }
      crumbs.push({ label: building.name, href: to.home(building.id) })
      if (route.section === 'people' && admin) {
        crumbs.push({ label: 'Люди' })
        content = <People />
      } else if (route.section === 'access' && admin) {
        crumbs.push({ label: 'Доступ' })
        content = <Access building={building} floors={floors} />
      } else if (route.section === 'drawings' && admin) {
        crumbs.push({ label: 'Чертежи' })
        content = <Building key={building.id} id={building.id} />
      } else if (route.section === 'assets') {
        crumbs.push({ label: 'Объекты', href: to.assets(building.id) })
        content = <Assets key={route.q ?? ''} building={building.id} floors={floors} selected={route.item} admin={admin} initialQuery={route.q} />
        if (route.item) {
          panel = <AssetCard key={route.item} id={route.item} me={me} building={building.id} floors={floors} admin={admin} onGone={noop} />
          closePanel = () => { location.hash = to.assets(building.id) }
        }
      } else if (route.section === 'rooms') {
        const chosen = room(route.item)
        crumbs.push({ label: 'Помещения', href: to.rooms(building.id) })
        if (chosen) crumbs.push({ label: chosen.floor.name, href: to.plan(building.id, chosen.floor.id) }, { label: chosen.room.name || 'Без названия' })
        content = <Rooms key={route.q ?? ''} building={building.id} floors={floors} selected={route.item} initialQuery={route.q} />
        if (chosen) {
          panel = <RoomCard key={chosen.room.id + chosen.room.version} me={me} building={building.id} {...chosen} admin={admin} onChanged={reload} onPlan />
          closePanel = () => { location.hash = to.rooms(building.id) }
        }
      } else if (route.section === 'plan') {
        const chosen = room(route.sub)
        const floor = floors.find(f => f.id === route.item)
        crumbs.push({ label: 'План', href: to.plan(building.id) })
        if (floor) crumbs.push({ label: floor.name, href: to.plan(building.id, floor.id) })
        if (chosen) crumbs.push({ label: chosen.room.name || 'Без названия' })
        content = <Plan me={me} building={building.id} floors={floors} floor={route.item} room={route.sub} admin={admin} move={route.move} />
        if (chosen) {
          // beside the plan on a wide screen; on a phone the plan stays and the card is one tap away
          panel = <div className="max-md:hidden"><RoomCard key={chosen.room.id + chosen.room.version} me={me} building={building.id} {...chosen} admin={admin} onChanged={reload} /></div>
          closePanel = () => { location.hash = to.plan(building.id, route.item) }
        }
      } else {
        crumbs.push({ label: 'Кабинет' })
        content = <Home me={me} building={building} floors={floors} admin={admin} />
      }
    }
  } else {
    crumbs.push({ label: 'Мои здания' })
    content = <Buildings me={me} refresh={seen} />
  }
  const planPanel = route.page === 'building' && route.section === 'plan'
  return (
    <Shell me={me} route={route} building={b} several={(mine?.ids.length ?? 0) > 1 || sys} editor={scope?.editor ?? null} crumbs={crumbs}
      panel={panel} onClosePanel={closePanel} keepMain={planPanel}>
      {content}
    </Shell>
  )
}

/** The user; on a phone also what the menu on the left holds on a wide screen. */
function Profile({ me, building, editor }: { me: Me; building: BuildingInfo | null; editor: string | null }) {
  const { isDark, setTheme } = useTheme()
  const sys = me.user.is_admin
  const admin = building ? manages(me, building.id) : false
  const links: [string, string][] = [
    ...(admin && building ? [[to.drawings(building.id), 'Чертежи здания'], [to.people(building.id), 'Люди'], [to.access(building.id), 'Доступ']] as [string, string][] : []),
    ...(admin && editor ? [[to.editor(editor), 'Редактор']] as [string, string][] : []),
    ...(sys ? [[to.buildings, 'Здания'], ['#/catalog', 'Каталог'], ['#/system', 'Состояние системы']] as [string, string][] : []),
  ]
  return (
    <section className="max-w-md space-y-4">
      <div>
        <h1 className="text-xl font-semibold">{me.user.name || me.user.login}</h1>
        <p className="text-sm text-muted-foreground">{[me.person?.position, me.user.email, sys && 'администратор системы'].filter(Boolean).join(' · ')}</p>
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

/** A QR label was scanned: the object's card, or the same «нет доступа» whether the object is someone else's or does not exist. */
function ByQr({ code }: { code: string }) {
  const [gone, setGone] = useState(false)
  useEffect(() => {
    byQr(code).then(a => location.replace(to.assets(a.building_id, a.asset_id)), () => setGone(true))
  }, [code])
  if (!gone) return <p className="text-sm text-muted-foreground">Открываю карточку…</p>
  return (
    <div className="max-w-md space-y-3" data-testid="qr-denied">
      <h1 className="text-lg font-semibold">Нет доступа</h1>
      <p className="text-sm text-muted-foreground">Объекта с такой меткой нет среди доступных вам. Если это ваш объект, попросите администратора здания выдать право на него.</p>
      <Button asChild variant="outline" size="sm"><a href={to.buildings}>К моим зданиям</a></Button>
    </div>
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
