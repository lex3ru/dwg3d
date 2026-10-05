import { Building2, Activity, LogOut, Moon, Sun } from 'lucide-react'
import { lazy, Suspense, useEffect, useState } from 'react'
import { ApiError, getMe, signIn, signOut, type Me } from './api'
import { Button } from './components/ui/button'
import { useTheme } from './lib/theme'
import { cn } from './lib/utils'
import { Building } from './pages/Building'
import { Buildings } from './pages/Buildings'
import { System } from './pages/System'

// the 3D viewer is heavy (three.js): loaded when a drawing is opened
const Scene = lazy(() => import('./scene/entry'))

type Page = 'buildings' | 'system'
type Route = { page: Page; building?: string; scene?: boolean }
/** #/buildings · #/p/<building> · #/f/<drawing>/… (the viewer) · #/system */
function routeOf(hash: string): Route {
  const [first, second] = hash.replace(/^#\/?/, '').split(/[/?]/)
  if (first === 'f' && second) return { page: 'buildings', scene: true }
  if (first === 'p' && second) return { page: 'buildings', building: second }
  return { page: first === 'system' ? 'system' : 'buildings' }
}

function useRoute(): Route {
  const [hash, set] = useState(location.hash)
  useEffect(() => {
    const on = () => set(location.hash)
    addEventListener('hashchange', on)
    return () => removeEventListener('hashchange', on)
  }, [])
  return routeOf(hash)
}

export function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState<string | null>(null)
  const route = useRoute()
  const page = route.page
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
  if (route.scene) return <Suspense fallback={<Centered title="Загрузка…" />}><Scene /></Suspense>

  return (
    <div className="flex min-h-full flex-col">
      <Header me={me} page={page} />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
        {page === 'system' && me.user.is_admin ? <System />
          : route.building && me.user.is_admin ? <Building key={route.building} id={route.building} /> : <Buildings me={me} />}
      </main>
    </div>
  )
}

function Header({ me, page }: { me: Me; page: Page }) {
  const { isDark, setTheme } = useTheme()
  const [leaving, setLeaving] = useState(false)
  const link = (to: Page, label: string, Icon: typeof Building2) => (
    <a
      href={`#/${to}`}
      aria-current={page === to ? 'page' : undefined}
      className={cn('flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-secondary',
        page === to && 'bg-secondary font-medium text-foreground')}
    >
      <Icon className="size-4" />
      <span className="max-sm:hidden">{label}</span>
    </a>
  )
  return (
    <header className="border-b bg-card">
      <div className="mx-auto flex h-12 max-w-5xl items-center gap-2 px-4">
        <span className="mr-3 font-semibold max-sm:hidden">Цифровой двойник</span>
        <nav className="flex items-center gap-1" aria-label="Разделы">
          {link('buildings', 'Мои здания', Building2)}
          {me.user.is_admin && link('system', 'Состояние системы', Activity)}
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <span className="mr-1 truncate text-sm text-muted-foreground" data-testid="user-name">{me.user.name || me.user.login}</span>
          <Button variant="ghost" size="icon" title={isDark ? 'Светлая тема' : 'Тёмная тема'}
            onClick={() => setTheme(isDark ? 'light' : 'dark')}>
            {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </Button>
          <Button variant="ghost" size="icon" title="Выйти" disabled={leaving}
            onClick={() => { setLeaving(true); signOut().catch(() => setLeaving(false)) }}>
            <LogOut className="size-4" />
          </Button>
        </div>
      </div>
    </header>
  )
}

function Centered({ title, text, children }: { title: string; text?: string; children?: React.ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center">
      <h1 className="text-lg font-semibold">{title}</h1>
      {text && <p className="max-w-sm text-sm text-muted-foreground">{text}</p>}
      {children}
    </div>
  )
}
