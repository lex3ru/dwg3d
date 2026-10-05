import { Bot, ChevronRight, LogOut, Monitor, Moon, Package, Sun, UserRound } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useTheme, type Theme } from '@/lib/theme'
import { can, me, signOut } from '@/session'
import CatalogEditor from '@/ui/CatalogEditor'
import CopilotSettings from '@/ui/CopilotSettings'

export interface Crumb { label: string; href?: string }

/** The bar of the pages outside the viewer: the app, where you are, the user menu. */
export default function AppHeader({ crumbs = [] }: { crumbs?: Crumb[] }) {
  const [catalog, setCatalog] = useState(false)
  const [copilot, setCopilot] = useState(false)
  const { theme, setTheme } = useTheme()
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-card/90 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-6xl items-center gap-2 px-4">
        <a href="#/" className="text-sm font-bold text-foreground no-underline">Поэтажные планы → 3D</a>
        {crumbs.map((c, i) => (
          <span key={i} className="flex min-w-0 items-center gap-2 text-sm text-muted-foreground">
            <ChevronRight className="size-3.5 shrink-0" />
            {c.href ? <a href={c.href} className="truncate text-muted-foreground no-underline hover:text-foreground">{c.label}</a>
              : <span className="truncate text-foreground">{c.label}</span>}
          </span>
        ))}
        <span className="flex-1" />
        {me?.guest && <span className="rounded-full bg-secondary px-2 py-0.5 text-xs">просмотр по ссылке</span>}
        {can('catalog_admin') && (
          <Button variant="ghost" size="sm" onClick={() => setCatalog(true)}><Package /> <span className="hidden sm:inline">Каталог оборудования</span></Button>
        )}
        {can('admin') && (
          <Button variant="ghost" size="sm" onClick={() => setCopilot(true)}><Bot /> <span className="hidden sm:inline">Копилот</span></Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" aria-label="Меню пользователя">
              {theme === 'dark' ? <Moon /> : theme === 'light' ? <Sun /> : <UserRound />}
              {me?.auth && !me.guest && <span className="hidden max-w-32 truncate sm:inline">{me.name}</span>}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            {me?.auth && !me.guest && (
              <>
                <DropdownMenuLabel className="grid">
                  <span className="text-sm text-foreground">{me.name}</span>
                  <span>{me.login}{me.role !== 'user' ? ` · ${me.role_name}` : ''}</span>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
              </>
            )}
            <DropdownMenuLabel>Тема</DropdownMenuLabel>
            <DropdownMenuRadioGroup value={theme} onValueChange={(v) => setTheme(v as Theme)}>
              <DropdownMenuRadioItem value="light"><Sun /> Светлая</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="dark"><Moon /> Тёмная</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="system"><Monitor /> Как в системе</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
            {me?.auth && !me.guest && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={signOut}><LogOut /> Выйти</DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {catalog && <CatalogEditor onClose={() => setCatalog(false)} onChanged={() => {}} />}
      {copilot && <CopilotSettings onClose={() => setCopilot(false)} />}
    </header>
  )
}

/** Page frame: header and a centred column. */
export function Page({ crumbs, children, wide }: { crumbs?: Crumb[]; children: ReactNode; wide?: boolean }) {
  return (
    <div className="min-h-full bg-background text-foreground">
      <AppHeader crumbs={crumbs} />
      <div className={`mx-auto px-4 py-6 ${wide ? 'max-w-6xl' : 'max-w-4xl'}`}>{children}</div>
    </div>
  )
}
