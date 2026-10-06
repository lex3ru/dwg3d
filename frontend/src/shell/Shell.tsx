import {
  Activity, BookOpen, Box, Building2, ChevronRight, FileStack, GitBranch, History, Home, KeyRound, LogOut, Map as MapIcon, Moon, PencilRuler, Search, Sun,
  User, Users, X,
  type LucideIcon,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { manages, signOut, type Building, type Me } from '../api'
import { Button } from '../components/ui/button'
import { Tip } from '../components/ui/tooltip'
import { useTheme } from '../lib/theme'
import { cn } from '../lib/utils'
import { to, type Route } from './route'

type Item = { key: string; href: string; label: string; icon: LucideIcon; active: boolean
  /** what the section is for (components/ui/tooltip.tsx) */ hint: string }
export type Crumb = { label: string; href?: string }

/** What the menu holds for this user in this place. A section whose service does not exist yet,
 * or which the user has no right to, is simply not there. */
function menu(route: Route, me: Me, building: Building | null, editor: string | null) {
  const b = building?.id
  const section = route.page === 'building' ? route.section : null
  const main: Item[] = b ? [
    { key: 'home', href: to.home(b), label: 'Обзор', icon: Home, active: section === 'home',
      hint: 'С чего начать: что в здании требует ваших действий, ваши помещения и объекты, поиск и сканер QR' },
    { key: 'plan', href: to.plan(b), label: 'План', icon: MapIcon, active: section === 'plan' || section === 'rooms',
      hint: 'Помещения здания: поэтажный план с объектами на своих местах или список с поиском; карточка помещения — по щелчку' },
    { key: 'assets', href: to.assets(b), label: 'Объекты', icon: Box, active: section === 'assets',
      hint: 'Реестр мебели и оборудования: поиск, отбор по состоянию, загрузка и выгрузка Excel, QR-метки' },
  ] : []
  const manage: Item[] = b && manages(me, b) ? [
    { key: 'drawings', href: to.drawings(b), label: 'Чертежи', icon: FileStack, active: section === 'drawings',
      hint: 'Загрузка поэтажных планов DWG/DXF, их сборка в этажи и помещения, проверка новых сборок' },
    ...(editor ? [{ key: 'editor', href: to.editor(editor), label: 'Редактор', icon: PencilRuler, active: route.page === 'editor',
      hint: '3D-сцена здания: расстановка объектов, слои инженерных систем' }] : []),
    { key: 'people', href: to.people(b), label: 'Люди', icon: Users, active: section === 'people',
      hint: 'Справочник людей организации: кто в каком помещении работает, рабочие места' },
    { key: 'access', href: to.access(b), label: 'Доступ', icon: KeyRound, active: section === 'access',
      hint: 'Кто что может в здании: права людей на здание, этаж, помещение; ссылки для просмотра без учётной записи' },
    { key: 'variants', href: to.variants(b), label: 'Варианты', icon: GitBranch, active: section === 'variants',
      hint: 'Черновики перестановки объектов: сравнить с фактом, оценить и перенести в учёт' },
    { key: 'journal', href: to.journal(b), label: 'Журнал', icon: History, active: section === 'journal',
      hint: 'Лента событий здания: кто, что и когда изменил; отбор по виду и периоду' },
  ] : []
  const system: Item[] = me.user.is_admin ? [
    { key: 'buildings', href: to.buildings, label: 'Здания', icon: Building2, active: route.page === 'buildings',
      hint: 'Все здания системы; здесь же создаётся новое' },
    { key: 'catalog', href: '#/catalog', label: 'Каталог', icon: BookOpen, active: route.page === 'catalog',
      hint: 'Типы мебели и оборудования и наборы их свойств — общие для всех зданий' },
    { key: 'system', href: '#/system', label: 'Состояние системы', icon: Activity, active: route.page === 'system',
      hint: 'Работают ли сервисы и доходят ли события' },
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
  // the name is cut short in the menu: the hint carries it whole
  const toBuilding = several ? 'К списку всех доступных вам зданий' : 'На главную страницу здания: что требует внимания, мои помещения и объекты'
  // folded to icons, the hint names the section too
  const link = (it: Item) => (
    <Tip key={it.key} side="right" label={rail ? <><b>{it.label}</b><br />{it.hint}</> : it.hint}>
      <a href={it.href} aria-label={rail ? it.label : undefined} aria-current={it.active ? 'page' : undefined}
        className={cn('flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-secondary',
          it.active && 'bg-accent font-medium text-accent-foreground hover:bg-accent', rail && 'justify-center px-0')}>
        <it.icon className="size-4 shrink-0" />{!rail && <span className="truncate">{it.label}</span>}
      </a>
    </Tip>
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
          <Tip side="right" label={<><b>{building.name}</b><br />{toBuilding}</>}>
            <a href={several ? to.buildings : to.home(building.id)} aria-label={rail ? building.name : undefined}
              className={cn('mb-2 flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm font-medium hover:bg-secondary', rail && 'justify-center px-0')}>
              <Building2 className="size-4 shrink-0 text-muted-foreground" />
              {!rail && <span className="flex-1 truncate" data-testid="building-name">{building.name}</span>}
              {!rail && several && <ChevronRight className="size-3.5 text-muted-foreground" />}
            </a>
          </Tip>
        ) : !rail && <div className="mb-2 px-2.5 py-1.5 text-sm font-semibold">Цифровой двойник</div>}
        <nav className="grid gap-0.5" aria-label="Разделы">
          {building && !rail && main.length > 0 && <div className="px-2.5 pb-1 text-xs text-muted-foreground">Здание</div>}
          {main.map(link)}
        </nav>
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
            <aside className={cn('flex w-96 shrink-0 flex-col overflow-x-hidden overflow-y-auto border-l bg-card max-md:w-full max-md:border-l-0', keepMain && 'max-md:hidden')} aria-label="Карточка" data-testid="panel">
              <div className="flex justify-end px-2 pt-2">
                <Button variant="ghost" size="icon" aria-label="Закрыть" hint="Убрать карточку; раздел останется на том же месте" hintSide="left" onClick={onClosePanel}><X className="size-4" /></Button>
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
              ? <Tip label="Вернуться на этот уровень" side="bottom"><a href={c.href} className="truncate text-muted-foreground hover:text-foreground">{c.label}</a></Tip>
              : <span className="truncate font-medium">{c.label}</span>}
          </span>
        ))}
      </div>
      {building && (
        <form className="relative ml-auto w-56 max-sm:hidden" role="search"
          onSubmit={e => { e.preventDefault(); location.hash = to.rooms(building.id, undefined, q.trim()) }}>
          <Search className="pointer-events-none absolute top-2 left-2 size-4 text-muted-foreground" />
          <Tip label="Название или номер помещения этого здания; Enter откроет список найденного" side="bottom">
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Найти помещение" aria-label="Поиск"
              className="h-8 w-full rounded-md border bg-background pr-2 pl-8 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
          </Tip>
        </form>
      )}
      <div className={cn('flex items-center gap-1', !building && 'ml-auto')}>
        <span className="mr-1 truncate text-sm text-muted-foreground max-md:hidden" data-testid="user-name">{me.user.name || me.user.login}</span>
        <Button variant="ghost" size="icon" aria-label={isDark ? 'Светлая тема' : 'Тёмная тема'} hintSide="bottom"
          hint={isDark ? 'Включить светлое оформление; выбор запомнится в этом браузере' : 'Включить тёмное оформление; выбор запомнится в этом браузере'}
          onClick={() => setTheme(isDark ? 'light' : 'dark')}>
          {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </Button>
        <Button variant="ghost" size="icon" aria-label="Выйти" disabled={leaving} hintSide="bottom"
          hint="Завершить сеанс в этом браузере; чтобы продолжить, придётся войти снова"
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
  // [address, label, icon, active, hint]
  const tabs: [string, string, LucideIcon, boolean, string][] = [
    [b ? to.home(b) : to.buildings, b ? 'Обзор' : 'Здания', Home, section === 'home' || route.page === 'buildings',
      b ? 'Что в здании требует ваших действий, ваши помещения и объекты, сканер QR' : 'Здания, доступные вам'],
    ...(b ? [
      [to.plan(b), 'План', MapIcon, section === 'plan' || section === 'rooms', 'Помещения здания: план этажа или список с поиском'],
      [to.assets(b), 'Объекты', Box, section === 'assets', 'Реестр мебели и оборудования с поиском и отбором'],
    ] as [string, string, LucideIcon, boolean, string][] : []),
    ['#/me', 'Я', User, route.page === 'me', 'Ваша учётная запись, тема, выход; разделы, не уместившиеся во вкладки'],
  ]
  return (
    <nav className="flex shrink-0 border-t bg-card md:hidden" aria-label="Вкладки">
      {tabs.map(([href, label, Icon, active, hint]) => (
        <Tip key={label} label={hint}>
          <a href={href} aria-current={active ? 'page' : undefined}
            className={cn('flex flex-1 flex-col items-center gap-0.5 py-1.5 text-xs text-muted-foreground', active && 'text-primary')}>
            <Icon className="size-5" />{label}
          </a>
        </Tip>
      ))}
    </nav>
  )
}
