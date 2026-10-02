import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import { fileUrl, type Job, type Role } from './api'

const ROLES: (Role | '')[] = ['', 'walls', 'columns', 'windows', 'doors', 'insulation', 'stairs', 'rooms', 'grid', 'ignore']
const ROLE_LABEL: Record<string, string> = {
  '': '—', walls: 'Стены', columns: 'Колонны', windows: 'Окна', doors: 'Двери',
  rooms: 'Помещения', grid: 'Оси', ignore: 'Игнор', insulation: 'Утеплитель', stairs: 'Лестницы',
}

interface FloorRow {
  candidate: string
  name: string
  level: string
  height: string
  elevation: string
  include: boolean
}

const esc = (s: string) => s.replace(/[[\]*?]/g, (c) => `[${c}]`)

export default function Settings({ job, onRebuild, onClose }: {
  job: Job
  onRebuild: (override: Record<string, unknown>) => void
  onClose: () => void
}) {
  const r = job.result!
  const built = useMemo(() => new Map(r.floors.map((f) => [f.id, f])), [r.floors])
  const [rows, setRows] = useState<FloorRow[]>(() =>
    r.candidates.map((c) => {
      const f = built.get(c.id)
      return {
        candidate: c.id,
        name: c.name,
        level: String(f?.level ?? c.level ?? ''),
        height: f?.height != null ? String(f.height) : '',
        elevation: f?.elevation != null ? String(f.elevation) : '',
        include: c.include,
      }
    }),
  )
  const layerNames = useMemo(
    () => Object.keys(r.layers).sort((a, b) => r.layers[b].count - r.layers[a].count),
    [r.layers],
  )
  const [roles, setRoles] = useState<Record<string, Role | ''>>(
    () => Object.fromEntries(layerNames.map((n) => [n, r.layers[n].role ?? ''])),
  )
  const [manualHeights, setManualHeights] = useState<Set<string>>(new Set())
  const [manualElev, setManualElev] = useState<Set<string>>(new Set())
  const [layersDirty, setLayersDirty] = useState(false)
  const bcfg = (job.config?.building ?? {}) as Record<string, number>
  const [params, setParams] = useState({
    floor_height: String(bcfg.floor_height ?? 3.0),
    door_height: String(bcfg.door_height ?? 2.1),
    window_sill: String(bcfg.window_sill ?? 0.9),
    window_head: String(bcfg.window_head ?? 2.4),
  })

  const upd = (i: number, patch: Partial<FloorRow>) =>
    setRows((rs) => rs.map((x, j) => (j === i ? { ...x, ...patch } : x)))

  const submit = () => {
    const items = rows.map((x) => {
      const it: Record<string, unknown> = { candidate: x.candidate, name: x.name, include: x.include }
      if (x.level !== '') it.level = Number(x.level)
      if (manualHeights.has(x.candidate) && x.height !== '') it.height = Number(x.height)
      if (manualElev.has(x.candidate) && x.elevation !== '') it.elevation = Number(x.elevation)
      return it
    })
    const override: Record<string, unknown> = {
      floors: { items },
      building: Object.fromEntries(Object.entries(params).map(([k, v]) => [k, Number(v)])),
    }
    if (layersDirty) {
      const layers: Record<string, string[]> = {
        ignore: [], walls: [], columns: [], windows: [], doors: [], rooms: [], grid: [], insulation: [], stairs: [],
      }
      for (const [name, role] of Object.entries(roles)) if (role) layers[role].push(esc(name))
      override.layers = layers
    }
    onRebuild(override)
  }

  const th = 'border-b border-border px-1 py-1 text-left text-xs font-medium text-muted-foreground'
  const td = 'border-b border-border/50 px-1 py-0.5'
  const numCls = 'w-20'

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent aria-describedby={undefined} onKeyDown={(e) => e.stopPropagation()}
        className="max-h-[85vh] max-w-3xl grid-rows-[auto_minmax(0,1fr)_auto]">
        <DialogHeader><DialogTitle>Настройка построения</DialogTitle></DialogHeader>
        <div className="-mx-5 grid min-h-0 gap-5 overflow-y-auto px-5 text-sm">
          <section className="grid gap-2">
            <h3 className="m-0 text-sm font-semibold">Этажи (листы чертежа)</h3>
            <p className="m-0 text-xs text-muted-foreground">
              Отметьте, какие листы строить, и укажите номер этажа. Высоту и отметку можно
              задать вручную — иначе они берутся из высотных отметок на плане.
            </p>
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr>
                  <th className={th}></th><th className={th}></th><th className={th}>Лист</th><th className={th}>Этаж №</th>
                  <th className={th}>Высота, м</th><th className={th}>Отметка, м</th><th className={th}>2D</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((x, i) => (
                  <tr key={x.candidate} className={cn(!x.include && '[&>td]:opacity-55')}>
                    <td className={td}>
                      <Switch checked={x.include} aria-label="Строить лист" onCheckedChange={(v) => upd(i, { include: v })} />
                    </td>
                    <td className={td}>{(() => {
                      const pv = r.candidates[i]?.preview
                      return pv ? (
                        <svg className="block h-10 w-14 text-muted-foreground" viewBox={`0 0 ${pv.w} ${pv.h}`} preserveAspectRatio="xMidYMid meet">
                          <path d={pv.d} fill="none" stroke="currentColor" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
                        </svg>
                      ) : null
                    })()}</td>
                    <td className={td}><Input value={x.name} onChange={(e) => upd(i, { name: e.target.value })} /></td>
                    <td className={td}><Input className={numCls} type="number" value={x.level} onChange={(e) => upd(i, { level: e.target.value })} /></td>
                    <td className={td}>
                      <Input className={numCls} type="number" step="0.05" value={x.height}
                        onChange={(e) => { upd(i, { height: e.target.value }); setManualHeights((s) => new Set(s).add(x.candidate)) }} />
                    </td>
                    <td className={td}>
                      <Input className={numCls} type="number" step="0.05" value={x.elevation}
                        onChange={(e) => { upd(i, { elevation: e.target.value }); setManualElev((s) => new Set(s).add(x.candidate)) }} />
                    </td>
                    <td className={td}>
                      {built.has(x.candidate)
                        ? <a className="text-primary underline-offset-4 hover:underline" href={fileUrl(job.id, `debug/floor_${x.candidate}.png`, job.build)} target="_blank" rel="noreferrer">план</a>
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="grid gap-2">
            <h3 className="m-0 text-sm font-semibold">Параметры</h3>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-x-5 gap-y-2">
              {([
                ['floor_height', 'Высота этажа по умолчанию'],
                ['door_height', 'Высота дверей'],
                ['window_sill', 'Низ окна (подоконник)'],
                ['window_head', 'Верх окна'],
              ] as const).map(([k, label]) => (
                <Label key={k} className="flex items-center justify-between gap-2 font-normal">
                  <span className="flex-1">{label}, м</span>
                  <Input className={numCls} type="number" step="0.05" value={params[k]}
                    onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.value }))} />
                </Label>
              ))}
            </div>
          </section>

          <section className="grid gap-2">
            <h3 className="m-0 text-sm font-semibold">Слои</h3>
            <p className="m-0 text-xs text-muted-foreground">Роль слоя определяет, как его геометрия попадёт в модель.</p>
            <table className="w-full border-collapse text-sm">
              <thead><tr><th className={th}>Слой</th><th className={cn(th, 'text-right')}>Объектов</th><th className={th}>Роль</th></tr></thead>
              <tbody>
                {layerNames.map((n) => (
                  <tr key={n} className={cn(!r.layers[n].count && '[&>td]:opacity-55')}>
                    <td className={cn(td, 'break-all')}>{n}</td>
                    <td className={cn(td, 'text-right text-muted-foreground tabular-nums')}>{r.layers[n].count}</td>
                    <td className={td}>
                      <Select value={roles[n]} aria-label={`Роль слоя ${n}`} onChange={(e) => {
                        setRoles((s) => ({ ...s, [n]: e.target.value as Role | '' }))
                        setLayersDirty(true)
                      }}>
                        {ROLES.map((ro) => <option key={ro} value={ro}>{ROLE_LABEL[ro]}</option>)}
                      </Select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>Отмена</Button>
          <Button onClick={submit}>Перестроить модель</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
