import { Crosshair, Eye, EyeOff, GitCompare, Lock, LockOpen, Settings2 } from 'lucide-react'
import type { Layer, LayerKindInfo } from '@/api'
import { Button } from '@/components/ui/button'
import { Tip } from '@/components/ui/tooltip'
import { variantGroups } from '@/furniture/layers'
import { cn } from '@/lib/utils'

/**
 * Layers of the project in the viewer: show or hide each (a variant of a group
 * shows alone), pick the one new items go to, lock, compare variants.
 */
export default function LayersPanel(p: {
  layers: Layer[]
  kinds: LayerKindInfo[]
  hidden: Set<string>
  activeLayer: string | null
  projectId: string
  editable: boolean
  onToggle: (id: string) => void
  onVariant: (id: string) => void
  onAll: (show: boolean) => void
  onActive: (id: string | null) => void
  onLock: (l: Layer, patch: Partial<Layer>) => void
  onCompare: () => void
}) {
  const groups = variantGroups(p.layers)
  const inVariants = (l: Layer) => groups.some((g) => g.some((x) => x.id === l.id))
  const takesItems = (l: Layer) => !!p.kinds.find((k) => k.kind === l.kind)?.geoms.includes('point')
  const allShown = p.layers.length > 0 && p.layers.every((l) => !p.hidden.has(l.id))
  return (
    <section aria-label="Слои проекта" className="flex h-full min-h-0 flex-col">
      <header className="flex items-center gap-1 border-b border-border px-3 py-1.5">
        <b className="mr-auto text-sm">Слои проекта</b>
        {p.layers.length > 1 && (
          <Button variant="ghost" size="sm" onClick={() => p.onAll(!allShown)}>{allShown ? 'Скрыть все' : 'Показать все'}</Button>
        )}
      </header>
      <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto p-1.5">
        {!p.layers.length && (
          <p className="m-0 px-2 py-3 text-sm text-muted-foreground">Слоёв пока нет: первый появится с первым предметом на плане.</p>
        )}
        <ul className="m-0 grid list-none grid-cols-[minmax(0,1fr)] gap-0.5 p-0">
          {p.layers.map((l) => {
            const off = p.hidden.has(l.id)
            const variant = inVariants(l)
            const active = p.activeLayer === l.id
            return (
              <li key={l.id} className={cn('flex items-center gap-1 rounded-lg px-1.5 py-1 hover:bg-secondary/70', active && 'bg-accent')}>
                <Tip label={off ? (variant ? 'Показать этот вариант (остальные скроются)' : 'Показать слой') : 'Скрыть слой'}>
                  <Button variant="ghost" size="icon-sm" aria-pressed={!off} aria-label={off ? 'Показать слой' : 'Скрыть слой'}
                    onClick={() => (variant && off ? p.onVariant(l.id) : p.onToggle(l.id))}>
                    {off ? <EyeOff className="text-muted-foreground" /> : <Eye />}
                  </Button>
                </Tip>
                <div className="min-w-0 flex-1 leading-tight">
                  <div className={cn('truncate text-sm', off && 'text-muted-foreground')}>{l.name}</div>
                  <div className="truncate text-xs text-muted-foreground">
                    {p.kinds.find((k) => k.kind === l.kind)?.name ?? l.kind}{l.count != null ? ` · ${l.count}` : ''}{variant ? ' · вариант' : ''}
                  </div>
                </div>
                {p.editable && takesItems(l) && (
                  <Tip label={active ? 'Сюда ставятся новые предметы (нажмите, чтобы отменить выбор)' : 'Ставить новые предметы в этот слой'}>
                    <Button variant="ghost" size="icon-sm" aria-pressed={active} aria-label="Активный слой"
                      className={active ? 'text-primary' : 'text-muted-foreground'} onClick={() => p.onActive(active ? null : l.id)}>
                      <Crosshair />
                    </Button>
                  </Tip>
                )}
                {p.editable ? (
                  <Tip label={l.locked ? 'Слой заблокирован — разблокировать' : 'Заблокировать: слой нельзя менять'}>
                    <Button variant="ghost" size="icon-sm" aria-pressed={l.locked} aria-label="Блокировка"
                      className={l.locked ? '' : 'text-muted-foreground'} onClick={() => p.onLock(l, { locked: !l.locked })}>
                      {l.locked ? <Lock /> : <LockOpen />}
                    </Button>
                  </Tip>
                ) : l.locked && <Lock className="mx-1.5 size-4 text-muted-foreground" />}
              </li>
            )
          })}
        </ul>
      </div>
      <footer className="flex items-center gap-1 border-t border-border px-2 py-1.5">
        {groups.length > 0 && <Button variant="ghost" size="sm" onClick={p.onCompare}><GitCompare /> Сравнить варианты</Button>}
        <span className="flex-1" />
        {p.projectId && <Button asChild variant="ghost" size="sm"><a href={`#/p/${p.projectId}/layers`}><Settings2 /> Настроить</a></Button>}
      </footer>
    </section>
  )
}
