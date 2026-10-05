import { Armchair, ChevronDown, Footprints, MapPin, MessageCircle, Orbit, Plane, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Pin } from '@/scene/api'
import { floatClass } from '@/components/ui/float'
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup,
  DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { Display, NavMode, Tool } from '../state'

const NAV: { id: NavMode; label: string; icon: LucideIcon; hint: string }[] = [
  { id: 'orbit', label: 'Обзор', icon: Orbit, hint: 'Вращение вокруг здания, зум, панорама' },
  { id: 'fly', label: 'Полёт', icon: Plane, hint: 'Свободная камера: WASD, мышь, колесо' },
  { id: 'walk', label: 'Прогулка', icon: Footprints, hint: 'От первого лица от главного входа' },
]

export interface RouteState {
  floor: string | null
  step: 'from' | 'to' | 'done'
  fromLabel: string
  toLabel: string
  length: number | null
  error: string | null
}

interface Props {
  nav: NavMode
  onNav: (n: NavMode) => void
  tool: Tool
  display: Display
  set: (patch: Partial<Display>) => void
  markers: Pin[]
  comments: Pin[]
  onFlyToPin: (p: Pin) => void
}

const btn = 'inline-flex h-10 min-w-10 cursor-pointer items-center justify-center gap-1.5 rounded-full border-0 px-2.5 text-sm font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-5 [&_svg]:shrink-0'
const on = 'bg-accent text-accent-foreground'
const off = 'bg-transparent text-foreground hover:bg-secondary'

/** A tool button, optionally with a caret that opens a menu above it. */
function Group({ icon: Icon, label, active, onClick, title, children, badge }: {
  icon: LucideIcon; label?: string; active: boolean; onClick: () => void; title: string; children?: ReactNode; badge?: number
}) {
  return (
    <div className="flex shrink-0 items-center">
      <Tip label={title}>
        <button aria-label={title} aria-pressed={active} className={cn(btn, active ? on : off, children && 'pr-1.5')} onClick={onClick}>
          <Icon />{label && <span className="@max-3xl:hidden">{label}</span>}
          {badge ? <span className="-ml-1 self-start rounded-full bg-destructive px-1.5 text-[10px] leading-4 font-bold text-white">{badge}</span> : null}
        </button>
      </Tip>
      {children && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button aria-label={`${title}: меню`} className="-ml-1 grid h-8 w-5 cursor-pointer place-items-center rounded-md border-0 bg-transparent p-0 text-muted-foreground hover:text-foreground">
              <ChevronDown className="size-3.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="center" sideOffset={12} className="w-72">{children}</DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  )
}

const Sep = () => <span className="mx-1.5 h-6 w-px shrink-0 bg-border" />
const Note = ({ children, strong, err }: { children: ReactNode; strong?: boolean; err?: boolean }) => (
  <p className={cn('m-0 px-2 py-1 text-xs text-muted-foreground', strong && 'font-semibold text-foreground', err && 'text-destructive')}>{children}</p>
)
// a menu item that toggles and keeps the menu open
const keep = (e: Event) => e.preventDefault()

/** Bottom of the scene: how the camera moves and what is shown (markers, objects, comments). Tools are in the context bar. */
export default function Toolbar(p: Props) {
  const nav = NAV.find((n) => n.id === p.nav)!
  const d = p.display
  return (
    <div role="toolbar" aria-label="Инструменты"
      className={cn(floatClass, 'absolute bottom-3.5 left-1/2 z-20 flex max-w-[calc(100%-1.5rem)] -translate-x-1/2 items-center gap-0.5 overflow-x-auto rounded-full px-2 py-1')}>
      <Group icon={nav.icon} label={nav.label} active title="Режим навигации"
        onClick={() => p.onNav(NAV[(NAV.findIndex((n) => n.id === p.nav) + 1) % NAV.length].id)}>
        <DropdownMenuRadioGroup value={p.nav} onValueChange={(v) => p.onNav(v as NavMode)}>
          {NAV.map((n) => (
            <DropdownMenuRadioItem key={n.id} value={n.id} className="items-start">
              <n.icon className="mt-0.5" />
              <span className="grid"><span>{n.label}</span><span className="text-xs text-muted-foreground">{n.hint}</span></span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </Group>
      <Sep />
      <Group icon={MapPin} active={d.pois || p.tool === 'marker'} title="Метки: входы, лифты, лестницы, свои" onClick={() => p.set({ pois: !d.pois })}>
        <DropdownMenuLabel>Метки</DropdownMenuLabel>
        <DropdownMenuCheckboxItem checked={d.poiKinds.entrance} onSelect={keep} onCheckedChange={(v) => p.set({ poiKinds: { ...d.poiKinds, entrance: v }, pois: true })}>Входы</DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem checked={d.poiKinds.lift} onSelect={keep} onCheckedChange={(v) => p.set({ poiKinds: { ...d.poiKinds, lift: v }, pois: true })}>Лифты</DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem checked={d.poiKinds.stair} onSelect={keep} onCheckedChange={(v) => p.set({ poiKinds: { ...d.poiKinds, stair: v }, pois: true })}>Лестницы</DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem checked={d.poiKinds.marker} onSelect={keep} onCheckedChange={(v) => p.set({ poiKinds: { ...d.poiKinds, marker: v }, pois: true })}>Мои метки ({p.markers.length})</DropdownMenuCheckboxItem>
        {p.markers.length > 0 && <DropdownMenuSeparator />}
        {p.markers.map((m) => <DropdownMenuItem key={m.id} onSelect={() => p.onFlyToPin(m)}><MapPin /> {m.label || m.text || 'Метка'}</DropdownMenuItem>)}
      </Group>
      <Group icon={Armchair} active={d.furniture} title="Мебель и оборудование на плане" onClick={() => p.set({ furniture: !d.furniture })}>
        <DropdownMenuLabel>Мебель и оборудование</DropdownMenuLabel>
        <DropdownMenuCheckboxItem checked={d.furniture} onSelect={keep} onCheckedChange={(v) => p.set({ furniture: v })}>Показывать</DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem checked={d.camViews} onSelect={keep} onCheckedChange={(v) => p.set({ camViews: v })}>Обзор камер, покрытие Wi-Fi, извещателей и освещения</DropdownMenuCheckboxItem>
        <Note>Что именно показывать, задают слои в дереве слева.</Note>
      </Group>
      <Group icon={MessageCircle} active={d.comments || p.tool === 'comment'} title="Комментарии" onClick={() => p.set({ comments: !d.comments })}>
        <DropdownMenuLabel>Комментарии</DropdownMenuLabel>
        <DropdownMenuCheckboxItem checked={d.comments} onSelect={keep} onCheckedChange={(v) => p.set({ comments: v })}>Показывать</DropdownMenuCheckboxItem>
        {p.comments.length > 0 && <DropdownMenuSeparator />}
        {p.comments.map((c) => <DropdownMenuItem key={c.id} onSelect={() => p.onFlyToPin(c)}><MessageCircle /> {c.text.slice(0, 40)}</DropdownMenuItem>)}
      </Group>
    </div>
  )
}
