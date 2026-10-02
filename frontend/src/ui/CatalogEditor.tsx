import { Plus, Search, Trash2, Upload } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import { createCatalogItem, saveCategory, updateCatalogItem, uploadCatalogModel } from '../api'
import { loadCatalog, type CatalogItem, type Category } from '../furniture/catalog'
import { MODEL_KINDS } from '../furniture/models'

/** Form state: numbers as typed, '' = not set. */
interface Form {
  id: string
  cat: string
  name: string
  kind: string
  w: string
  d: string
  h: string
  elev: string
  clear: string
  wall: boolean
  color: string
  tags: string
  article: string
  supplier: string
  price: string
  currency: string
  cam: boolean
  fov: string
  range: string
  ident: string
  modelRot: string
  active: boolean
}

const s = (v: number | string | undefined | null) => (v === undefined || v === null ? '' : String(v))
const toForm = (c: CatalogItem | null, cat: string): Form => ({
  id: c?.id ?? '', cat: c?.cat ?? cat, name: c?.name ?? '', kind: c?.kind ?? 'device',
  w: s(c?.w ?? 1), d: s(c?.d ?? 1), h: s(c?.h ?? 1), elev: s(c?.elev), clear: s(c?.clear), wall: !!c?.wall,
  color: c?.color ?? '', tags: c?.tags ?? '', article: c?.article ?? '', supplier: c?.supplier ?? '',
  price: s(c?.price), currency: c?.currency ?? 'RUB', cam: !!c?.cam, fov: s(c?.cam?.fov ?? 90),
  range: s(c?.cam?.range ?? 15), ident: s(c?.cam?.ident ?? 5), modelRot: s(c?.modelRot), active: c?.active !== false,
})

/** The whole catalog, withdrawn items included. */
async function fetchCatalog(): Promise<{ categories: Category[]; items: CatalogItem[] }> {
  const r = await fetch('/api/catalog')
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

const num = (v: string) => (v.trim() === '' ? null : Number(v.replace(',', '.')))

/** The API body of a form: every field, null for the cleared optional ones. */
function body(f: Form): Record<string, unknown> {
  return {
    cat: f.cat, name: f.name.trim(), kind: f.kind, w: num(f.w), d: num(f.d), h: num(f.h),
    elev: num(f.elev), clear: num(f.clear), wall: f.wall, color: f.color || null, tags: f.tags.trim() || null,
    article: f.article.trim() || null, supplier: f.supplier.trim() || null, price: num(f.price),
    currency: f.currency.trim().toUpperCase() || 'RUB', modelRot: num(f.modelRot), active: f.active,
    cam: f.cam ? { fov: num(f.fov), range: num(f.range), ident: num(f.ident) } : null,
  }
}

const money = (v: number | undefined, cur?: string) =>
  v === undefined ? '' : `${v.toLocaleString('ru-RU', { maximumFractionDigits: 2 })} ${cur === 'RUB' || !cur ? '₽' : cur}`

/** Equipment catalog editor (catalog_admin): items with sizes, models, articles, suppliers and prices. */
export default function CatalogEditor({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const [cats, setCats] = useState<Category[]>([])
  const [items, setItems] = useState<CatalogItem[]>([])
  const [cat, setCat] = useState('all')
  const [q, setQ] = useState('')
  const [withInactive, setWithInactive] = useState(false)
  const [sel, setSel] = useState<string | null>(null)       // item id, '' = new item
  const [form, setForm] = useState<Form | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [catEdit, setCatEdit] = useState<(Category & { isNew: boolean }) | null>(null)
  const file = useRef<HTMLInputElement>(null)

  const apply = (data: { categories: Category[]; items: CatalogItem[] }) => {
    setCats(data.categories)
    setItems(data.items)
  }
  const reload = async () => apply(await fetchCatalog())
  useEffect(() => {
    let alive = true
    fetchCatalog().then((d) => { if (alive) apply(d) }).catch((e) => { if (alive) setErr((e as Error).message) })
    return () => { alive = false }
  }, [])

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase()
    return items.filter((c) => (cat === 'all' || c.cat === cat) && (withInactive || c.active !== false) &&
      (!t || `${c.name} ${c.id} ${c.article ?? ''} ${c.supplier ?? ''} ${c.tags ?? ''}`.toLowerCase().includes(t)))
  }, [items, cat, q, withInactive])
  const current = sel ? items.find((c) => c.id === sel) ?? null : null

  const open = (id: string | null) => {
    setErr(null)
    setSel(id)
    setForm(id === null ? null : toForm(id ? items.find((c) => c.id === id) ?? null : null, cat === 'all' ? cats[0]?.id ?? '' : cat))
  }
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => (f ? { ...f, [k]: v } : f))

  /** After a change: refresh this list and the catalog the viewer uses. */
  const changed = async (id: string) => {
    await reload()
    await loadCatalog()
    onChanged()
    setSel(id)
  }
  const save = async () => {
    if (!form) return
    setBusy(true)
    setErr(null)
    try {
      const saved = sel ? await updateCatalogItem(sel, body(form)) : await createCatalogItem({ id: form.id.trim(), ...body(form) } as Partial<CatalogItem>)
      await changed(saved.id)
      setForm(toForm(saved, saved.cat))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const upload = async (f: File | undefined) => {
    if (!f || !sel) return
    setBusy(true)
    setErr(null)
    try {
      const saved = await uploadCatalogModel(sel, f)
      await changed(saved.id)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
      if (file.current) file.current.value = ''
    }
  }
  const dropModel = async () => {
    if (!sel) return
    setBusy(true)
    try {
      await updateCatalogItem(sel, { model: null, modelRot: null })
      await changed(sel)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const saveCat = async () => {
    if (!catEdit) return
    setErr(null)
    try {
      const { isNew, ...c } = catEdit
      await saveCategory(c, isNew)
      await reload()
      await loadCatalog()
      onChanged()
      setCatEdit(null)
      setCat(c.id)
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  const count = (id: string) => items.filter((c) => c.cat === id && (withInactive || c.active !== false)).length
  const f = form

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent aria-describedby={undefined} onKeyDown={(e) => e.stopPropagation()}
        className="flex h-[85vh] max-w-6xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b border-border px-5 py-3 pr-12">
          <DialogTitle>Каталог оборудования</DialogTitle>
        </DialogHeader>
        <div className={cn('grid min-h-0 flex-1 overflow-y-auto lg:overflow-hidden lg:grid-rows-[minmax(0,1fr)]',
          f ? 'lg:grid-cols-[13rem_minmax(0,1fr)_minmax(20rem,23rem)]' : 'lg:grid-cols-[13rem_minmax(0,1fr)]')}>
          <nav className="flex flex-wrap gap-0.5 border-b border-border p-2 lg:flex-col lg:flex-nowrap lg:overflow-y-auto lg:border-r lg:border-b-0">
            <CatButton on={cat === 'all'} onClick={() => setCat('all')} count={items.filter((c) => withInactive || c.active !== false).length}>Все</CatButton>
            {cats.map((c) => (
              <CatButton key={c.id} on={cat === c.id} onClick={() => setCat(c.id)} color={c.color} count={count(c.id)}
                onDoubleClick={() => setCatEdit({ ...c, isNew: false })} title="Двойной щелчок — переименовать">
                {c.name}
              </CatButton>
            ))}
            <Button variant="link" size="sm" className="justify-start px-2" onClick={() => setCatEdit({ id: '', name: '', color: '#868e96', isNew: true })}>
              <Plus /> Категория
            </Button>
            {catEdit && (
              <div className="grid w-full gap-1.5 rounded-md bg-secondary p-2">
                {catEdit.isNew && <Input placeholder="id (латиница)" value={catEdit.id} onChange={(e) => setCatEdit({ ...catEdit, id: e.target.value })} />}
                <Input placeholder="Название" value={catEdit.name} onChange={(e) => setCatEdit({ ...catEdit, name: e.target.value })} />
                <ColorInput value={catEdit.color} onChange={(v) => setCatEdit({ ...catEdit, color: v })} />
                <div className="flex gap-1.5">
                  <Button size="sm" onClick={saveCat}>Сохранить</Button>
                  <Button size="sm" variant="secondary" onClick={() => setCatEdit(null)}>Отмена</Button>
                </div>
              </div>
            )}
          </nav>

          <section className="flex min-h-0 min-w-0 flex-col">
            <div className="flex items-center gap-2 border-b border-border px-3 py-2">
              <div className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute top-1/2 left-2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input className="pl-7" placeholder="Поиск: название, id, артикул, поставщик" value={q} onChange={(e) => setQ(e.target.value)} />
              </div>
              <label className="flex cursor-pointer items-center gap-1.5 text-xs whitespace-nowrap text-muted-foreground">
                <Switch checked={withInactive} onCheckedChange={setWithInactive} /> снятые
              </label>
              <Button size="sm" onClick={() => open('')}><Plus /> Позиция</Button>
            </div>
            <div className="max-h-[50vh] min-h-0 flex-1 overflow-auto lg:max-h-none">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="[&>th]:sticky [&>th]:top-0 [&>th]:border-b [&>th]:border-border [&>th]:bg-popover [&>th]:px-2 [&>th]:py-1.5 [&>th]:text-left [&>th]:font-semibold [&>th]:text-muted-foreground">
                    <th>Наименование</th><th>Артикул</th><th>Поставщик</th><th className="text-right!">Цена</th><th className="text-right!">Габариты, см</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((c) => (
                    <tr key={c.id} onClick={() => open(c.id)}
                      className={cn('cursor-pointer align-top [&>td]:border-b [&>td]:border-border [&>td]:px-2 [&>td]:py-1.5',
                        sel === c.id ? 'bg-accent' : 'hover:bg-secondary/60', c.active === false && 'text-muted-foreground')}>
                      <td>
                        <b className="font-medium">{c.name}</b>
                        <small className="block text-[11px] text-muted-foreground">{c.id}{c.model ? ' · GLB' : ''}{c.active === false ? ' · снята' : ''}</small>
                      </td>
                      <td>{c.article}</td>
                      <td>{c.supplier}</td>
                      <td className="text-right whitespace-nowrap tabular-nums">{money(c.price, c.currency)}</td>
                      <td className="text-right whitespace-nowrap tabular-nums">{Math.round(c.w * 100)}×{Math.round(c.d * 100)}×{Math.round(c.h * 100)}</td>
                    </tr>
                  ))}
                  {!shown.length && <tr><td colSpan={5} className="px-2 py-3 text-muted-foreground">Ничего не найдено</td></tr>}
                </tbody>
              </table>
            </div>
            {!f && err && <p className="m-0 border-t border-border px-3 py-2 text-sm text-destructive">{err}</p>}
          </section>

          {f && (
            <section className="flex min-h-0 flex-col border-t border-border lg:border-t-0 lg:border-l">
              <div className="grid min-h-0 flex-1 content-start gap-3 overflow-y-auto px-4 py-3">
                <h3 className="m-0 text-sm font-semibold">{sel ? 'Позиция' : 'Новая позиция'}</h3>
                <div className="grid gap-2">
                  {!sel && <Row label="id"><Input value={f.id} placeholder="diag.mri3t" onChange={(e) => set('id', e.target.value)} /></Row>}
                  <Row label="Категория">
                    <Select className="w-full" value={f.cat} onChange={(e) => set('cat', e.target.value)}>{cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
                  </Row>
                  <Row label="Наименование"><Input value={f.name} onChange={(e) => set('name', e.target.value)} /></Row>
                  <Row label="Артикул"><Input value={f.article} onChange={(e) => set('article', e.target.value)} /></Row>
                  <Row label="Поставщик"><Input value={f.supplier} onChange={(e) => set('supplier', e.target.value)} /></Row>
                  <Row label="Цена">
                    <div className="flex gap-1">
                      <Input className={NUM} inputMode="decimal" value={f.price} onChange={(e) => set('price', e.target.value)} />
                      <Input className="w-14 uppercase" aria-label="Валюта" value={f.currency} maxLength={3} onChange={(e) => set('currency', e.target.value)} />
                    </div>
                  </Row>
                  <Row label="Габариты Ш×Г×В, м">
                    <div className="grid w-full grid-cols-3 gap-1">
                      {(['w', 'd', 'h'] as const).map((k) => <Input key={k} className="min-w-0 text-right tabular-nums" inputMode="decimal" aria-label={{ w: 'Ширина', d: 'Глубина', h: 'Высота' }[k]} value={f[k]} onChange={(e) => set(k, e.target.value)} />)}
                    </div>
                  </Row>
                  <Row label="Высота установки, м"><Input className={NUM} inputMode="decimal" value={f.elev} placeholder="на полу" onChange={(e) => set('elev', e.target.value)} /></Row>
                  <Row label="Зона обслуживания, м"><Input className={NUM} inputMode="decimal" value={f.clear} onChange={(e) => set('clear', e.target.value)} /></Row>
                  <Row label="Ставится к стене"><Switch checked={f.wall} onCheckedChange={(v) => set('wall', v)} /></Row>
                  <Row label="Процедурная модель">
                    <Select className="w-full" value={f.kind} onChange={(e) => set('kind', e.target.value)}>
                      {[...new Set([...MODEL_KINDS, f.kind])].map((k) => <option key={k}>{k}</option>)}
                    </Select>
                  </Row>
                  <Row label="Цвет">
                    <div className="flex items-center gap-1.5">
                      <ColorInput value={f.color || '#adb5bd'} onChange={(v) => set('color', v)} />
                      {f.color && <Button size="sm" variant="ghost" onClick={() => set('color', '')}>по умолчанию</Button>}
                    </div>
                  </Row>
                  <Row label="Теги для поиска"><Input value={f.tags} onChange={(e) => set('tags', e.target.value)} /></Row>
                  <Row label="Камера видеонаблюдения"><Switch checked={f.cam} onCheckedChange={(v) => set('cam', v)} /></Row>
                  {f.cam && (
                    <Row label="Угол° · дальность · опознание, м">
                      <div className="flex gap-1">
                        {(['fov', 'range', 'ident'] as const).map((k) => <Input key={k} className={NUM} inputMode="decimal" value={f[k]} onChange={(e) => set(k, e.target.value)} />)}
                      </div>
                    </Row>
                  )}
                  <Row label="В продаже (видна в каталоге)"><Switch checked={f.active} onCheckedChange={(v) => set('active', v)} /></Row>
                </div>
                {sel && (
                  <div className="grid gap-2 border-t border-border pt-3">
                    <h3 className="m-0 text-sm font-semibold">3D-модель (GLB)</h3>
                    <p className="m-0 text-xs text-muted-foreground">{current?.model
                      ? <>Файл: <a className="text-primary hover:underline" href={current.modelUrl} download>{current.model}</a>. Масштабируется до габаритов, фасад — к +Z.</>
                      : 'Нет — используется процедурная модель.'}</p>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Button size="sm" variant="secondary" disabled={busy} onClick={() => file.current?.click()}>
                        <Upload /> {current?.model ? 'Заменить…' : 'Загрузить GLB…'}
                      </Button>
                      {current?.model && <Button size="sm" variant="destructive" disabled={busy} onClick={dropModel}><Trash2 /> Убрать</Button>}
                      {current?.model && (
                        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                          поворот°<Input className={NUM} inputMode="decimal" value={f.modelRot} onChange={(e) => set('modelRot', e.target.value)} />
                        </label>
                      )}
                    </div>
                    <input ref={file} type="file" accept=".glb" hidden onChange={(e) => upload(e.target.files?.[0])} />
                  </div>
                )}
                {err && <p className="m-0 text-sm text-destructive">{err}</p>}
              </div>
              <DialogFooter className="border-t border-border px-4 py-2.5">
                <Button variant="secondary" onClick={() => open(null)}>Закрыть</Button>
                <Button disabled={busy || !f.name.trim() || (!sel && !f.id.trim())} onClick={save}>{busy ? 'Сохранение…' : 'Сохранить'}</Button>
              </DialogFooter>
            </section>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

const NUM = 'w-16 tabular-nums'

/** A form row: label on the left, control on the right. */
const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] items-center gap-2">
    <span className="text-xs text-muted-foreground">{label}</span>
    <div className="flex min-w-0 items-center">{children}</div>
  </div>
)

const ColorInput = ({ value, onChange }: { value: string; onChange: (v: string) => void }) => (
  <input type="color" value={value} onChange={(e) => onChange(e.target.value)}
    className="h-8 w-12 cursor-pointer rounded-md border border-input bg-card p-0.5" />
)

function CatButton({ on, color, count, children, ...props }: React.ComponentProps<'button'> & { on: boolean; color?: string; count: number }) {
  return (
    <button type="button" {...props}
      className={cn('flex cursor-pointer items-center gap-2 rounded-md border-0 px-2 py-1.5 text-left text-sm',
        on ? 'bg-accent text-accent-foreground' : 'bg-transparent text-foreground hover:bg-secondary')}>
      {color && <i className="size-2.5 shrink-0 rounded-[3px]" style={{ background: color }} />}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      <small className="text-xs text-muted-foreground tabular-nums">{count}</small>
    </button>
  )
}
