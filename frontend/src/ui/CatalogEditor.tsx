import { useEffect, useMemo, useRef, useState } from 'react'
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
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal catalog-modal" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label="Каталог оборудования">
        <header><h2>Каталог оборудования</h2><button className="ghost" onClick={onClose} aria-label="Закрыть">✕</button></header>
        <div className={`cat-layout${f ? ' with-form' : ''}`}>
          <nav className="cat-cats">
            <button className={cat === 'all' ? 'on' : ''} onClick={() => setCat('all')}>Все <small>{items.filter((c) => withInactive || c.active !== false).length}</small></button>
            {cats.map((c) => (
              <button key={c.id} className={cat === c.id ? 'on' : ''} onClick={() => setCat(c.id)}
                onDoubleClick={() => setCatEdit({ ...c, isNew: false })} title="Двойной щелчок — переименовать">
                <i style={{ background: c.color }} />{c.name} <small>{count(c.id)}</small>
              </button>
            ))}
            <button className="link" onClick={() => setCatEdit({ id: '', name: '', color: '#868e96', isNew: true })}>+ Категория</button>
            {catEdit && (
              <div className="cat-edit">
                {catEdit.isNew && <input placeholder="id (латиница)" value={catEdit.id} onChange={(e) => setCatEdit({ ...catEdit, id: e.target.value })} />}
                <input placeholder="Название" value={catEdit.name} onChange={(e) => setCatEdit({ ...catEdit, name: e.target.value })} />
                <input type="color" value={catEdit.color} onChange={(e) => setCatEdit({ ...catEdit, color: e.target.value })} />
                <div><button className="small primary" onClick={saveCat}>Сохранить</button> <button className="small" onClick={() => setCatEdit(null)}>Отмена</button></div>
              </div>
            )}
          </nav>

          <section className="cat-list">
            <div className="cat-tools">
              <input placeholder="Поиск: название, id, артикул, поставщик" value={q} onChange={(e) => setQ(e.target.value)} />
              <label><input type="checkbox" checked={withInactive} onChange={(e) => setWithInactive(e.target.checked)} /> снятые</label>
              <button className="small primary" onClick={() => open('')}>+ Позиция</button>
            </div>
            <div className="cat-scroll">
            <table>
              <thead><tr><th>Наименование</th><th>Артикул</th><th>Поставщик</th><th className="r">Цена</th><th className="r">Габариты, см</th></tr></thead>
              <tbody>
                {shown.map((c) => (
                  <tr key={c.id} className={`${sel === c.id ? 'on' : ''}${c.active === false ? ' off' : ''}`} onClick={() => open(c.id)}>
                    <td><b>{c.name}</b><small>{c.id}{c.model ? ' · GLB' : ''}{c.active === false ? ' · снята' : ''}</small></td>
                    <td>{c.article}</td>
                    <td>{c.supplier}</td>
                    <td className="r">{money(c.price, c.currency)}</td>
                    <td className="r">{Math.round(c.w * 100)}×{Math.round(c.d * 100)}×{Math.round(c.h * 100)}</td>
                  </tr>
                ))}
                {!shown.length && <tr><td colSpan={5} className="hint">Ничего не найдено</td></tr>}
              </tbody>
            </table>
            </div>
          </section>

          {f && (
            <section className="cat-form">
              <h3>{sel ? 'Позиция' : 'Новая позиция'}</h3>
              <div className="params one">
                {!sel && <label><span>id</span><input value={f.id} placeholder="diag.mri3t" onChange={(e) => set('id', e.target.value)} /></label>}
                <label><span>Категория</span>
                  <select value={f.cat} onChange={(e) => set('cat', e.target.value)}>{cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
                <label><span>Наименование</span><input value={f.name} onChange={(e) => set('name', e.target.value)} /></label>
                <label><span>Артикул</span><input value={f.article} onChange={(e) => set('article', e.target.value)} /></label>
                <label><span>Поставщик</span><input value={f.supplier} onChange={(e) => set('supplier', e.target.value)} /></label>
                <label><span>Цена</span><span className="pair">
                  <input className="num" inputMode="decimal" value={f.price} onChange={(e) => set('price', e.target.value)} />
                  <input className="cur" value={f.currency} maxLength={3} onChange={(e) => set('currency', e.target.value)} /></span></label>
                <label><span>Габариты Ш×Г×В, м</span><span className="pair">
                  {(['w', 'd', 'h'] as const).map((k) => <input key={k} className="num" inputMode="decimal" value={f[k]} onChange={(e) => set(k, e.target.value)} />)}</span></label>
                <label><span>Высота установки, м</span><input className="num" inputMode="decimal" value={f.elev} placeholder="на полу" onChange={(e) => set('elev', e.target.value)} /></label>
                <label><span>Зона обслуживания, м</span><input className="num" inputMode="decimal" value={f.clear} onChange={(e) => set('clear', e.target.value)} /></label>
                <label><span>Ставится к стене</span><input type="checkbox" checked={f.wall} onChange={(e) => set('wall', e.target.checked)} /></label>
                <label><span>Процедурная модель</span>
                  <select value={f.kind} onChange={(e) => set('kind', e.target.value)}>
                    {[...new Set([...MODEL_KINDS, f.kind])].map((k) => <option key={k}>{k}</option>)}</select></label>
                <label><span>Цвет</span><span className="pair">
                  <input type="color" value={f.color || '#adb5bd'} onChange={(e) => set('color', e.target.value)} />
                  {f.color && <button className="small ghost" onClick={() => set('color', '')}>по умолчанию</button>}</span></label>
                <label><span>Теги для поиска</span><input value={f.tags} onChange={(e) => set('tags', e.target.value)} /></label>
                <label><span>Камера видеонаблюдения</span><input type="checkbox" checked={f.cam} onChange={(e) => set('cam', e.target.checked)} /></label>
                {f.cam && <label><span>Угол° · дальность · опознание, м</span><span className="pair">
                  {(['fov', 'range', 'ident'] as const).map((k) => <input key={k} className="num" inputMode="decimal" value={f[k]} onChange={(e) => set(k, e.target.value)} />)}</span></label>}
                <label><span>В продаже (видна в каталоге)</span><input type="checkbox" checked={f.active} onChange={(e) => set('active', e.target.checked)} /></label>
              </div>
              {sel && (
                <>
                  <h3>3D-модель (GLB)</h3>
                  <p className="hint">{current?.model
                    ? <>Файл: <a href={current.modelUrl} download>{current.model}</a>. Масштабируется до габаритов, фасад — к +Z.</>
                    : 'Нет — используется процедурная модель.'}</p>
                  <div className="pair">
                    <button className="small" disabled={busy} onClick={() => file.current?.click()}>{current?.model ? 'Заменить…' : 'Загрузить GLB…'}</button>
                    {current?.model && <button className="small danger" disabled={busy} onClick={dropModel}>Убрать</button>}
                    {current?.model && <label className="inline">поворот°<input className="num" inputMode="decimal" value={f.modelRot} onChange={(e) => set('modelRot', e.target.value)} /></label>}
                  </div>
                  <input ref={file} type="file" accept=".glb" hidden onChange={(e) => upload(e.target.files?.[0])} />
                </>
              )}
              {err && <p className="error">{err}</p>}
              <footer className="cat-actions">
                <button onClick={() => open(null)}>Закрыть</button>
                <button className="primary" disabled={busy || !f.name.trim() || (!sel && !f.id.trim())} onClick={save}>{busy ? 'Сохранение…' : 'Сохранить'}</button>
              </footer>
            </section>
          )}
          {!f && err && <p className="error">{err}</p>}
        </div>
      </div>
    </div>
  )
}
