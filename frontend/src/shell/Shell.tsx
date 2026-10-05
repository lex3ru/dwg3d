import {
  Activity, Building2, ChevronRight, DoorOpen, FileStack, Home, KeyRound, LogOut, Map as MapIcon, Moon, PencilRuler, Search, Sun, User,
  Users, X,
  type LucideIcon,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { manages, signOut, type Building, type Me } from '../api'
import { Button } from '../components/ui/button'
import { useTheme } from '../lib/theme'
import { cn } from '../lib/utils'
import { to, type Route } from './route'

type Item = { key: string; href: string; label: string; icon: LucideIcon; active: boolean }
export type Crumb = { label: string; href?: string }

/** What the menu holds for this user in this place. A section whose service does not exist yet,
 * or which the user has no right to, is simply not there. */
function menu(route: Route, me: Me, building: Building | null, editor: string | null) {
  const b = building?.id
  const section = route.page === 'building' ? route.section : null
  const main: Item[] = b ? [
    { key: 'home', href: to.home(b), label: 'Кабинет', icon: Home, active: section === 'home' },
    { key: 'rooms', href: to.rooms(b), label: 'Помещения', icon: DoorOpen, active: section === 'rooms' },
    { key: 'plan', href: to.plan(b), label: 'План', icon: MapIcon, active: section === 'plan' },
  ] : []
  const manage: Item[] = b && manages(me, b) ? [
    { key: 'drawings', href: to.drawings(b), label: 'Чертежи', icon: FileStack, active: section === 'drawings' },
    ...(editor ? [{ key: 'editor', href: to.editor(editor), label: 'Редактор', icon: PencilRuler, active: route.page === 'editor' }] : []),
    { key: 'people', href: to.people(b), label: 'Люди', icon: Users, active: section === 'people' },
    { key: 'access', href: to.access(b), label: 'Доступ', icon: KeyRound, active: section === 'access' },
  ] : []
  const system: Item[] = me.user.is_admin ? [
    { key: 'buildings', href: to.buildings, label: 'Здания', icon: Building2, active: route.page === 'buildings' },
    { key: 'system', href: '#/system', label: 'Состояние системы', icon: Activity, active: route.page === 'system' },
  ] : []
  return { main, manage, system }
}

/**
 * The frame of every screen: the menu on the left (tabs at the bottom on a phone), where
 * one is and the search on top, the section in the middle, the card of what is chosen on the right.
 * In the editor the menu folds to icons and the section takes the whole height.
 */
export function Shell({ me, route, building, several, editor, crumbs, panel, onClosePanel, keepMain, children }: {
  me: Me; route: Route; building: Building | null
  /** more than one building is open to the user: the name on top leads to the list */
  several: boolean
  /** the drawing the editor opens, when the building has a built one */
  editor: string | null
  crumbs: Crumb[]; panel?: ReactNode; onClosePanel?: () => void
  /** on a phone the card replaces the section — unless the section must stay (the plan) */
  keepMain?: boolean
  children: ReactNode
}) {
  const { main, manage, system } = menu(route, me, building, editor)
  const rail = route.page === 'editor'
  const link = (it: Item) => (
    <a key={it.key} href={it.href} title={rail ? it.label : undefined} aria-current={it.active ? 'page' : undefined}
      className={cn('flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-secondary',
        it.active && 'bg-accent font-medium text-accent-foreground hover:bg-accent', rail && 'justify-center px-0')}>
      <it.icon className="size-4 shrink-0" />{!rail && <span className="truncate">{it.label}</span>}
    </a>
  )
  const group = (title: string, items: Item[]) => items.length > 0 && (
    <div className="grid gap-0.5">
      {!rail && <div className="px-2.5 pt-3 pb-1 text-xs text-muted-foreground">{title}</div>}
      {rail && <div className="mx-2 my-2 border-t" />}
      {items.map(link)}
    </div>
  )
  return (
    <div className="flex h-full">
      <aside className={cn('flex shrink-0 flex-col gap-0.5 border-r bg-card p-2 max-md:hidden', rail ? 'w-12' : 'w-52')} aria-label="Меню">
        {building ? (
          <a href={several ? to.buildings : to.home(building.id)} title={building.name}
            className={cn('mb-2 flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm font-medium hover:bg-secondary', rail && 'justify-center px-0')}>
            <Building2 className="size-4 shrink-0 text-muted-foreground" />
            {!rail && <span className="flex-1 truncate" data-testid="building-name">{building.name}</span>}
            {!rail && several && <ChevronRight className="size-3.5 text-muted-foreground" />}
          </a>
        ) : !rail && <div className="mb-2 px-2.5 py-1.5 text-sm font-semibold">Цифровой двойник</div>}
        <nav className="grid gap-0.5" aria-label="Разделы">{main.map(link)}</nav>
        {group('Управление', manage)}
        {group('Система', system)}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {!rail && <TopBar me={me} crumbs={crumbs} building={building} />}
        <div className="flex min-h-0 flex-1">
          <main className={cn('min-w-0 flex-1', rail ? 'h-full' : 'overflow-y-auto', panel && !keepMain && 'max-md:hidden')}>
            {rail ? children : <div className="mx-auto w-full max-w-5xl px-4 py-5">{children}</div>}
          </main>
          {panel && (
            <aside className={cn('flex w-80 shrink-0 flex-col overflow-y-auto border-l bg-card max-md:w-full max-md:border-l-0', keepMain && 'max-md:hidden')} aria-label="Карточка" data-testid="panel">
              <div className="flex justify-end px-2 pt-2">
                <Button variant="ghost" size="icon" title="Закрыть" onClick={onClosePanel}><X className="size-4" /></Button>
              </div>
              <div className="px-4 pb-5">{panel}</div>
            </aside>
          )}
        </div>
        {!rail && <Tabs route={route} building={building} />}
      </div>
    </div>
  )
}

function TopBar({ me, crumbs, building }: { me: Me; crumbs: Crumb[]; building: Building | null }) {
  const { isDark, setTheme } = useTheme()
  const [leaving, setLeaving] = useState(false)
  const [q, setQ] = useState('')
  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b bg-card px-4">
      <div className="flex min-w-0 items-center gap-1.5 text-sm" data-testid="crumbs">
        {crumbs.map((c, i) => (
          <span key={i} className={cn('flex min-w-0 items-center gap-1.5', i < crumbs.length - 2 && 'max-md:hidden')}>
            {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />}
            {c.href && i < crumbs.length - 1
              ? <a href={c.href} className="truncate text-muted-foreground hover:text-foreground">{c.label}</a>
              : <span className="truncate font-medium">{c.label}</span>}
          </span>
        ))}
      </div>
      {building && (
        <form className="relative ml-auto w-56 max-sm:hidden" role="search"
          onSubmit={e => { e.preventDefault(); location.hash = to.rooms(building.id, undefined, q.trim()) }}>
          <Search className="pointer-events-none absolute top-2 left-2 size-4 text-muted-foreground" />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Найти помещение" aria-label="Поиск"
            className="h-8 w-full rounded-md border bg-background pr-2 pl-8 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </form>
      )}
      <div className={cn('flex items-center gap-1', !building && 'ml-auto')}>
        <span className="mr-1 truncate text-sm text-muted-foreground max-md:hidden" data-testid="user-name">{me.user.name || me.user.login}</span>
        <Button variant="ghost" size="icon" title={isDark ? 'Светлая тема' : 'Тёмная тема'} onClick={() => setTheme(isDark ? 'light' : 'dark')}>
          {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </Button>
        <Button variant="ghost" size="icon" title="Выйти" disabled={leaving}
          onClick={() => { setLeaving(true); signOut().catch(() => setLeaving(false)) }}>
          <LogOut className="size-4" />
        </Button>
      </div>
    </header>
  )
}

/** On a phone the menu is four tabs at the bottom; what does not fit is on the «Я» page. */
function Tabs({ route, building }: { route: Route; building: Building | null }) {
  const b = building?.id
  const section = route.page === 'building' ? route.section : null
  const tabs: [string, string, LucideIcon, boolean][] = [
    [b ? to.home(b) : to.buildings, 'Главная', Home, section === 'home' || route.page === 'buildings'],
    ...(b ? [[to.rooms(b), 'Помещения', DoorOpen, section === 'rooms'], [to.plan(b), 'План', MapIcon, section === 'plan']] as [string, string, LucideIcon, boolean][] : []),
    ['#/me', 'Я', User, route.page === 'me'],
  ]
  return (
    <nav className="flex shrink-0 border-t bg-card md:hidden" aria-label="Вкладки">
      {tabs.map(([href, label, Icon, active]) => (
        <a key={label} href={href} aria-current={active ? 'page' : undefined}
          className={cn('flex flex-1 flex-col items-center gap-0.5 py-1.5 text-xs text-muted-foreground', active && 'text-primary')}>
          <Icon className="size-5" />{label}
        </a>
      ))}
    </nav>
  )
}
