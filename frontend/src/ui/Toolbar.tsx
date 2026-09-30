import type { FloorMeta, Layer, Pin } from '../api'
import type { Display, NavMode, Tool } from '../state'
import { variantGroups } from '../furniture/layers'
import { Icon, type IconName } from './icons'
import { Check } from './menu'
import { useMenu } from './menuCtx'

const NAV: { id: NavMode; label: string; icon: IconName; hint: string }[] = [
  { id: 'orbit', label: 'Обзор', icon: 'orbit', hint: 'Вращение вокруг здания, зум, панорама' },
  { id: 'fly', label: 'Полёт', icon: 'fly', hint: 'Свободная камера: WASD, мышь, колесо' },
  { id: 'walk', label: 'Прогулка', icon: 'walk', hint: 'От первого лица от главного входа' },
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
  onTool: (t: Tool) => void
  route: RouteState
  routeFloor: FloorMeta | null
  onRouteRoom: (end: 'from' | 'to', node: string) => void
  onClearRoute: () => void
  buildingOpen: boolean
  onBuilding: () => void
  display: Display
  set: (patch: Partial<Display>) => void
  markers: Pin[]
  comments: Pin[]
  onFlyToPin: (p: Pin) => void
  furnitureCount: number | null
  placedCount: number
  onFurniture: () => void
  shapesOpen: boolean
  onShapes: () => void
  shapesCount: number
  conflictCount: number
  layers: Layer[]
  hiddenLayers: Set<string>
  onToggleLayer: (id: string) => void
  onAllLayers: (show: boolean) => void
  /** show this variant of a layer and hide the other variants */
  onVariant: (id: string) => void
  onCompare: () => void
  projectId: string
}

function Group({ id, icon, label, on, onClick, children, title }: {
  id: string; icon: IconName; label?: string; on: boolean; onClick: () => void; children?: React.ReactNode; title: string
}) {
  const m = useMenu(`tb-${id}`)
  return (
    <div className="menu-root tb-group">
      <button className={`tb-main${on ? ' on' : ''}`} onClick={onClick} title={title}>
        <Icon name={icon} size={20} />{label && <span>{label}</span>}
      </button>
      {children && (
        <>
          <button className={`tb-caret${m.isOpen ? ' on' : ''}`} onClick={m.toggle} aria-label={`${title}: меню`}>
            <Icon name="chevron" size={13} />
          </button>
          {m.isOpen && <div className="menu drop-up" role="menu" onClick={(e) => { if ((e.target as HTMLElement).dataset.close) m.close() }}>{children}</div>}
        </>
      )}
    </div>
  )
}

/** Bottom toolbar: navigation mode, route, building & floors, markers, furniture, comments. */
export default function Toolbar(p: Props) {
  const nav = NAV.find((n) => n.id === p.nav)!
  const d = p.display
  const rooms = (p.routeFloor?.rooms ?? []).filter((r) => r.name || (r.type && r.type !== 'other'))
  return (
    <div className="toolbar" role="toolbar">
      <Group id="nav" icon={nav.icon} label={nav.label} on title="Режим навигации"
        onClick={() => p.onNav(NAV[(NAV.findIndex((n) => n.id === p.nav) + 1) % NAV.length].id)}>
        {NAV.map((n) => (
          <button key={n.id} data-close="1" className={`menu-item radio${p.nav === n.id ? ' on' : ''}`} onClick={() => p.onNav(n.id)} title={n.hint}>
            <Icon name={n.icon} size={16} /> {n.label}
          </button>
        ))}
      </Group>
      <span className="tb-sep" />
      <Group id="route" icon="route" on={p.tool === 'route'} title="Маршрут между двумя точками этажа"
        onClick={() => p.onTool(p.tool === 'route' ? 'none' : 'route')}>
        <div className="menu-title">Маршрут{p.routeFloor ? ` · ${p.routeFloor.name}` : ''}</div>
        <p className="menu-note">Щёлкните на полу начало и конец пути или выберите помещения.</p>
        <label className="menu-field">От
          <select value="" onChange={(e) => e.target.value && p.onRouteRoom('from', e.target.value)} disabled={!rooms.length}>
            <option value="">{p.route.fromLabel || '— помещение —'}</option>
            {rooms.map((r) => <option key={r.node} value={r.node}>{r.name || r.type} · {r.area.toFixed(0)} м²</option>)}
          </select>
        </label>
        <label className="menu-field">До
          <select value="" onChange={(e) => e.target.value && p.onRouteRoom('to', e.target.value)} disabled={!rooms.length}>
            <option value="">{p.route.toLabel || '— помещение —'}</option>
            {rooms.map((r) => <option key={r.node} value={r.node}>{r.name || r.type} · {r.area.toFixed(0)} м²</option>)}
          </select>
        </label>
        {p.route.length != null && <p className="menu-note strong">{p.route.length.toFixed(1)} м · ~{Math.max(1, Math.round(p.route.length / 1.3 / 60))} мин пешком</p>}
        {p.route.error && <p className="menu-note err">{p.route.error}</p>}
        <button className="menu-item" data-close="1" onClick={p.onClearRoute}>Очистить маршрут</button>
      </Group>
      <Group id="building" icon="building" on={p.buildingOpen} title="Здание и этажи" onClick={p.onBuilding} />
      <Group id="pois" icon="pin" on={d.pois || p.tool === 'marker'} title="Метки: входы, лифты, лестницы, свои"
        onClick={() => p.set({ pois: !d.pois })}>
        <div className="menu-title">Метки</div>
        <Check on={d.poiKinds.entrance} label="Входы" onChange={(v) => p.set({ poiKinds: { ...d.poiKinds, entrance: v }, pois: true })} />
        <Check on={d.poiKinds.lift} label="Лифты" onChange={(v) => p.set({ poiKinds: { ...d.poiKinds, lift: v }, pois: true })} />
        <Check on={d.poiKinds.stair} label="Лестницы" onChange={(v) => p.set({ poiKinds: { ...d.poiKinds, stair: v }, pois: true })} />
        <Check on={d.poiKinds.marker} label={`Мои метки (${p.markers.length})`} onChange={(v) => p.set({ poiKinds: { ...d.poiKinds, marker: v }, pois: true })} />
        <button className={`menu-item accent${p.tool === 'marker' ? ' on' : ''}`} data-close="1"
          onClick={() => p.onTool(p.tool === 'marker' ? 'none' : 'marker')}>
          <Icon name="plus" size={15} /> {p.tool === 'marker' ? 'Отменить установку' : 'Поставить метку…'}
        </button>
        {p.markers.map((m) => (
          <button key={m.id} className="menu-item" data-close="1" onClick={() => p.onFlyToPin(m)}>📍 {m.label || m.text || 'Метка'}</button>
        ))}
      </Group>
      <Group id="furniture" icon="sofa" on={p.tool === 'furniture'} title="Мебель и оборудование: каталог и расстановка" onClick={p.onFurniture}>
        <div className="menu-title">Мебель и оборудование</div>
        <Check on={d.furniture} label="Показывать" onChange={(v) => p.set({ furniture: v })} />
        <Check on={d.camViews} label="Обзор камер, покрытие Wi-Fi и извещателей" onChange={(v) => p.set({ camViews: v })} />
        <button className={`menu-item accent${p.tool === 'furniture' ? ' on' : ''}`} data-close="1" onClick={p.onFurniture}>
          <Icon name="plus" size={15} /> {p.tool === 'furniture' ? 'Закончить расстановку' : 'Каталог и расстановка…'}
        </button>
        <p className="menu-note">Расставлено: {p.placedCount} шт.{p.furnitureCount ? ` В детальной модели ещё ${p.furnitureCount} объект(ов) мебели.` : ''}</p>
      </Group>
      <Group id="shapes" icon="flows" on={p.shapesOpen} title="Маршруты людей, зоны и кабельные трассы: пути по помещениям и этажам, проверка потоков"
        onClick={p.onShapes} />
      {p.conflictCount > 0 && <span className="tb-badge" title="Конфликты потоков и зон">{p.conflictCount}</span>}
      <Group id="layers" icon="layers" on={p.layers.some((l) => !p.hiddenLayers.has(l.id))} title="Слои проекта: мебель, видеонаблюдение…"
        onClick={() => p.onAllLayers(p.layers.every((l) => p.hiddenLayers.has(l.id)))}>
        <div className="menu-title">Слои проекта</div>
        {!p.layers.length && <p className="menu-note">Слоёв пока нет: первый появится с первым предметом на плане.</p>}
        {p.layers.map((l) => {
          const variants = variantGroups(p.layers).some((g) => g.some((x) => x.id === l.id))
          return (
            <Check key={l.id} on={!p.hiddenLayers.has(l.id)}
              label={`${l.name}${l.locked ? ' 🔒' : ''}${l.count != null ? ` · ${l.count}` : ''}`}
              hint={variants ? 'Вариант: показывается один из вариантов слоя' : undefined}
              onChange={() => (variants && p.hiddenLayers.has(l.id) ? p.onVariant(l.id) : p.onToggleLayer(l.id))} />
          )
        })}
        {variantGroups(p.layers).length > 0 && (
          <button className="menu-item" data-close="1" onClick={p.onCompare}>Сравнить варианты…</button>
        )}
        {p.projectId && <a className="menu-item" href={`#/p/${p.projectId}`}>Настроить слои проекта…</a>}
      </Group>
      <Group id="comments" icon="comment" on={d.comments || p.tool === 'comment'} title="Комментарии"
        onClick={() => p.set({ comments: !d.comments })}>
        <div className="menu-title">Комментарии</div>
        <Check on={d.comments} label="Показывать" onChange={(v) => p.set({ comments: v })} />
        <button className={`menu-item accent${p.tool === 'comment' ? ' on' : ''}`} data-close="1"
          onClick={() => p.onTool(p.tool === 'comment' ? 'none' : 'comment')}>
          <Icon name="plus" size={15} /> {p.tool === 'comment' ? 'Отменить' : 'Добавить комментарий…'}
        </button>
        {p.comments.map((c) => (
          <button key={c.id} className="menu-item" data-close="1" onClick={() => p.onFlyToPin(c)}>💬 {c.text.slice(0, 40)}</button>
        ))}
      </Group>
    </div>
  )
}
