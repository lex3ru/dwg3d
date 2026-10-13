import { Plus, Trash2 } from 'lucide-react'
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import {
  archiveType, deleteTypeModel, getType, listCategories, listSets, listTypes, putTypeModel, saveSet, saveType, typeModelUrl,
  type CatalogType, type Category, type Prop, type PropertySet, type TypeBody,
} from '../api'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Tip } from '../components/ui/tooltip'

const ModelPreview = lazy(() => import('../components/ModelPreview'))
const select = 'h-8 rounded-md border bg-card px-2 text-sm'
const KINDS: Record<Prop['kind'], string> = { text: 'текст', number: 'число', date: 'дата', bool: 'да / нет', choice: 'выбор', person: 'человек' }
const EDITORS: Record<Prop['editable_by'], string> = { system: 'система (каталог)', admin: 'администратор здания', responsible: 'ответственный' }
const PORTABLE = 'Перемещать объекты этого типа может и ответственный, а не только администратор здания'
const CONTAINER = 'В объект этого типа можно вкладывать другие объекты'
const WALL = 'Объекты этого типа вешают на стену: при расстановке они встают к ближайшей стене'
const CEILING = 'Объекты этого типа висят под потолком своего этажа, какой бы высоты он ни был'

/** The catalog: types of equipment and furniture, and the property sets their schemas are made of. */
export function Catalog({ kind, item }: { kind?: 'types' | 'sets'; item?: string }) {
  const [categories, setCategories] = useState<Category[]>([])
  const [sets, setSets] = useState<PropertySet[]>([])
  const [types, setTypes] = useState<CatalogType[]>([])
  const [archived, setArchived] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => {
    Promise.all([listCategories(), listSets(), listTypes(!archived)]).then(([c, s, t]) => {
      setCategories(c); setSets(s); setTypes(t); setError(null)
    }, (e: Error) => setError(e.message))
  }, [archived])
  useEffect(load, [load])
  const done = () => { load(); location.hash = '#/catalog' }

  if (kind === 'types' && item) {
    return <TypeEditor key={item} id={item === 'new' ? null : item} categories={categories} sets={sets} onDone={done} onChanged={load} />
  }
  if (kind === 'sets' && item) {
    const existing = sets.find(s => s.id === item)
    if (item !== 'new' && !existing) return <p className="text-sm text-muted-foreground">Загрузка…</p>
    return <SetEditor key={item} existing={existing} onDone={done} />
  }
  return (
    <section className="space-y-6">
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold">Каталог</h1>
          <Button asChild size="sm" variant="outline"
            hint="Описать новый вид мебели или оборудования: габариты, свойства, 3D-модель; из типов ставят объекты"><a href="#/catalog/types/new"><Plus className="size-4" /> Тип</a></Button>
          <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Tip label="Показать вместо действующих типы, убранные из выбора">
              <input type="checkbox" className="accent-primary" checked={archived} onChange={e => setArchived(e.target.checked)} />
            </Tip> архив
          </label>
        </div>
        {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
        {categories.map(c => {
          const mine = types.filter(t => t.category_id === c.id)
          return mine.length > 0 && (
            <div key={c.id} className="mt-4">
              <h2 className="mb-1.5 text-sm font-medium text-muted-foreground">{c.name}</h2>
              <ul className="divide-y rounded-lg border bg-card text-sm" data-testid="types">
                {mine.map(t => (
                  <li key={t.id}>
                    <a href={`#/catalog/types/${t.id}`} className="flex flex-wrap items-center gap-2 px-3 py-2 hover:bg-secondary">
                      <span className="min-w-40 flex-1 font-medium">{t.name}</span>
                      {t.portable && <Tip label={PORTABLE}><Badge variant="accent">переносной</Badge></Tip>}
                      {t.container && <Tip label={CONTAINER}><Badge>контейнер</Badge></Tip>}
                      {t.wall_mounted && <Tip label={WALL}><Badge>на стене</Badge></Tip>}
                      {t.ceiling_mounted && <Tip label={CEILING}><Badge>на потолке</Badge></Tip>}
                      {t.model && <Tip label="Объекты типа показываются в 3D своей моделью, а не фигурой по габаритам"><Badge variant="success">3D-модель</Badge></Tip>}
                      <span className="text-muted-foreground tabular-nums">{t.size.map(v => v.toLocaleString('ru')).join(' × ')} м</span>
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
        {types.length === 0 && !error && <p className="mt-4 text-sm text-muted-foreground">{archived ? 'В архиве пусто.' : 'Типов пока нет.'}</p>}
      </div>
      <div>
        <div className="flex items-center gap-3">
          <h2 className="text-base font-semibold">Наборы свойств</h2>
          <Button asChild size="sm" variant="outline"
            hint="Группа свойств, общая для нескольких типов: правка набора меняет схему их всех"><a href="#/catalog/sets/new"><Plus className="size-4" /> Набор</a></Button>
        </div>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Свойства, общие для нескольких типов. Изменение набора меняет схему всех типов, которые его используют.</p>
        <ul className="mt-3 divide-y rounded-lg border bg-card text-sm" data-testid="sets">
          {sets.map(s => (
            <li key={s.id}>
              <Tip label="Свойства набора; их правка изменит схему всех типов, где он подключён">
                <a href={`#/catalog/sets/${s.id}`} className="flex items-center gap-3 px-3 py-2 hover:bg-secondary">
                  <span className="flex-1 font-medium">{s.name}</span>
                  <span className="text-muted-foreground">свойств: {s.properties.length} · типов: {s.types ?? 0}</span>
                </a>
              </Tip>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

const blank = (): Prop => ({ key: '', title: '', kind: 'text', unit: null, options: null, required: false, stored: 'asset', editable_by: 'admin' })

/** The properties of a set or of a type: what they are called, what they hold, who edits them. */
function Properties({ value, onChange }: { value: Prop[]; onChange: (v: Prop[]) => void }) {
  const set = (i: number, patch: Partial<Prop>) => onChange(value.map((p, j) => (j === i ? { ...p, ...patch } : p)))
  return (
    <div className="grid gap-2" data-testid="properties">
      {value.map((p, i) => (
        <div key={i} className="flex flex-wrap items-end gap-2 rounded-md border bg-card p-2">
          <label className="grid gap-0.5 text-xs text-muted-foreground">Название
            <Input className="h-8 w-48" value={p.title} onChange={e => set(i, { title: e.target.value })} aria-label="Название свойства" />
          </label>
          <label className="grid gap-0.5 text-xs text-muted-foreground">Ключ
            <Tip label="Строчные латинские буквы, цифры и «_», с буквы: под этим именем значение хранится у объектов">
              <Input className="h-8 w-36 font-mono text-xs" value={p.key} onChange={e => set(i, { key: e.target.value })} aria-label="Ключ свойства" />
            </Tip>
          </label>
          <label className="grid gap-0.5 text-xs text-muted-foreground">Вид
            <Tip label="Каким полем свойство заполняется в карточке объекта; для выбора нужен список вариантов">
              <select className={select} value={p.kind} aria-label="Вид значения"
                onChange={e => set(i, { kind: e.target.value as Prop['kind'], options: e.target.value === 'choice' ? p.options ?? [] : null })}>
                {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Tip>
          </label>
          {p.kind === 'number' && (
            <label className="grid gap-0.5 text-xs text-muted-foreground">Единица
              <Tip label="Подпись к числу в карточке объекта, например «кВт» или «мм»">
                <Input className="h-8 w-20" value={p.unit ?? ''} onChange={e => set(i, { unit: e.target.value || null })} />
              </Tip>
            </label>
          )}
          {p.kind === 'choice' && (
            <label className="grid gap-0.5 text-xs text-muted-foreground">Варианты
              <Tip label="Значения списка через запятую, например: дерево, металл, пластик">
                <Input className="h-8 w-56" aria-label="Варианты" value={(p.options ?? []).map(o => o.title).join(', ')}
                  onChange={e => set(i, { options: e.target.value.split(',').map(s => s.trim()).filter(Boolean).map(t => ({ value: t, title: t })) })} />
              </Tip>
            </label>
          )}
          <label className="grid gap-0.5 text-xs text-muted-foreground">Значение
            <Tip label="Своё у каждого объекта — заполняется в его карточке; одно на тип — задаётся в каталоге и видно у всех объектов типа">
              <select className={select} value={p.stored} aria-label="Где хранится" onChange={e => set(i, { stored: e.target.value as Prop['stored'] })}>
                <option value="asset">у каждого объекта</option><option value="type">одно на тип</option>
              </select>
            </Tip>
          </label>
          <label className="grid gap-0.5 text-xs text-muted-foreground">Правит
            <Tip label="Кто вправе менять значение в карточке объекта: «ответственный» — ещё и ответственный за объект, иначе только администратор здания">
              <select className={select} value={p.editable_by} aria-label="Кто правит" onChange={e => set(i, { editable_by: e.target.value as Prop['editable_by'] })}>
                {Object.entries(EDITORS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Tip>
          </label>
          <Button type="button" variant="ghost" size="icon" aria-label="Убрать свойство"
            hint="Свойство пропадёт из схемы, когда вы сохраните; до этого можно уйти по «Отмена»" onClick={() => onChange(value.filter((_, j) => j !== i))}><Trash2 className="size-4" /></Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" className="justify-self-start" onClick={() => onChange([...value, blank()])}
        hint="Новая строка для свойства; в схеме оно появится после сохранения"><Plus className="size-4" /> Свойство</Button>
    </div>
  )
}

function SetEditor({ existing, onDone }: { existing?: PropertySet; onDone: () => void }) {
  const [name, setName] = useState(existing?.name ?? '')
  const [properties, setProperties] = useState<Prop[]>(existing?.properties ?? [])
  const [error, setError] = useState<string | null>(null)
  return (
    <form className="max-w-4xl space-y-4" onSubmit={e => {
      e.preventDefault()
      saveSet({ name, description: existing?.description ?? '', properties }, existing).then(onDone, (ex: Error) => setError(ex.message))
    }}>
      <h1 className="text-xl font-semibold">{existing ? `Набор «${existing.name}»` : 'Новый набор свойств'}</h1>
      {existing && (existing.types ?? 0) > 0 && <p className="text-sm text-muted-foreground">Используют типов: {existing.types}. Их схема изменится вместе с набором.</p>}
      <label className="grid max-w-sm gap-1 text-sm">Название<Input value={name} onChange={e => setName(e.target.value)} required aria-label="Название набора" /></label>
      <Properties value={properties} onChange={setProperties} />
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="flex gap-2">
        <Button type="submit" hint={existing ? 'Схема всех типов, где подключён набор, изменится сразу' : 'Создать набор; подключают его в карточке типа'}>Сохранить</Button>
        <Button asChild type="button" variant="ghost" hint="Вернуться в каталог, ничего не сохраняя"><a href="#/catalog">Отмена</a></Button>
      </div>
    </form>
  )
}

function TypeEditor({ id, categories, sets, onDone, onChanged }: {
  id: string | null; categories: Category[]; sets: PropertySet[]; onDone: () => void; onChanged: () => void
}) {
  const [existing, setExisting] = useState<CatalogType | null>(null)
  const [body, setBody] = useState<TypeBody | null>(id ? null : {
    category_id: '', name: '', w: 1, d: 1, h: 1, container: false, portable: false, sets: [], properties: [], values: {},
    elevation: null, wall_mounted: false, ceiling_mounted: false, shape: 'box', color: null, article: null, supplier: null,
    price: null, currency: 'RUB', sort: 0 })
  const [error, setError] = useState<string | null>(null)
  const picker = useRef<HTMLInputElement>(null)
  const adopt = (t: CatalogType) => {
    setExisting(t)
    // all of the type, also what the form does not show (its shape in 3D, price…): a save replaces the type whole
    setBody({ category_id: t.category_id, name: t.name, w: t.size[0], d: t.size[1], h: t.size[2], container: t.container,
      portable: t.portable, sets: t.sets, properties: t.properties, values: t.values, elevation: t.elevation,
      wall_mounted: t.wall_mounted, ceiling_mounted: t.ceiling_mounted, shape: t.shape, color: t.color, article: t.article,
      supplier: t.supplier, price: t.price, currency: t.currency, sort: t.sort })
  }
  useEffect(() => { if (id) getType(id).then(adopt, (e: Error) => setError(e.message)) }, [id])
  if (!body) return <p className="text-sm text-muted-foreground" role={error ? 'alert' : undefined}>{error ?? 'Загрузка…'}</p>
  const patch = (p: Partial<TypeBody>) => setBody({ ...body, ...p })
  // properties whose value is one for the type: from the chosen sets and the type's own
  const ofType = [...body.sets.flatMap(s => sets.find(x => x.id === s)?.properties ?? []), ...body.properties].filter(p => p.stored === 'type' && p.key)
  const number = (key: 'w' | 'd' | 'h', label: string) => (
    <label className="grid gap-1 text-sm">{label}
      <Tip label="В метрах, от 0,01: по габаритам объект занимает место на плане, а без модели — и в 3D">
        <Input className="w-24" type="number" step="0.01" min="0.01" value={body[key]} onChange={e => patch({ [key]: Number(e.target.value) })} required />
      </Tip>
    </label>
  )
  return (
    <form className="max-w-4xl space-y-5" onSubmit={e => {
      e.preventDefault()
      const values = Object.fromEntries(Object.entries(body.values).filter(([k, v]) => ofType.some(p => p.key === k) && v !== '' && v != null))
      saveType({ ...body, category_id: body.category_id || categories[0]?.id, values }, existing ?? undefined)
        .then(onDone, (ex: Error) => setError(ex.message))
    }}>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{existing ? existing.name : 'Новый тип'}</h1>
        {existing && !existing.active && <Tip label="Тип не предлагается при расстановке; поставленные объекты остаются на учёте"><Badge variant="warning">в архиве</Badge></Tip>}
        {existing && <span className="text-sm text-muted-foreground">версия схемы: {existing.schema_version}</span>}
      </div>
      <div className="flex flex-wrap gap-3">
        <label className="grid gap-1 text-sm">Название<Input className="w-72" value={body.name} onChange={e => patch({ name: e.target.value })} required aria-label="Название типа" /></label>
        <label className="grid gap-1 text-sm">Раздел
          <Tip label="Где тип стоит в каталоге и в выборе при расстановке объектов">
            <select className={`${select} h-9`} value={body.category_id || categories[0]?.id} onChange={e => patch({ category_id: e.target.value })} aria-label="Раздел">
              {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Tip>
        </label>
        {number('w', 'Ширина, м')}{number('d', 'Глубина, м')}{number('h', 'Высота, м')}
        <label className="grid gap-1 text-sm">Монтаж
          <Tip label="Где стоят объекты этого типа: на полу, на стене или под потолком этажа">
            <select className={`${select} h-9`} aria-label="Монтаж" value={body.ceiling_mounted ? 'ceiling' : body.wall_mounted ? 'wall' : 'floor'}
              onChange={e => patch({ wall_mounted: e.target.value === 'wall', ceiling_mounted: e.target.value === 'ceiling' })}>
              <option value="floor">на полу</option>
              <option value="wall">на стене</option>
              <option value="ceiling">на потолке</option>
            </select>
          </Tip>
        </label>
        <label className="grid gap-1 text-sm">Высота установки, м
          <Tip label={body.ceiling_mounted
            ? 'Низ объекта от пола — для этажа, высота которого не известна; на остальных объект висит под потолком'
            : 'Низ объекта от пола этажа; пусто — стоит на полу. У объекта на месте её можно изменить'}>
            <Input className="w-24" type="number" step="0.01" min="0" aria-label="Высота установки" value={body.elevation ?? ''}
              onChange={e => patch({ elevation: e.target.value === '' ? null : Number(e.target.value) })} />
          </Tip>
        </label>
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
        <label className="flex items-center gap-2">
          <Tip label={PORTABLE}>
            <input type="checkbox" className="accent-primary" checked={body.portable} onChange={e => patch({ portable: e.target.checked })} />
          </Tip> Переносной
        </label>
        <label className="flex items-center gap-2">
          <Tip label={CONTAINER}>
            <input type="checkbox" className="accent-primary" checked={body.container} onChange={e => patch({ container: e.target.checked })} />
          </Tip> Контейнер
        </label>
      </div>
      <div>
        <h2 className="text-base font-semibold">Наборы свойств</h2>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1.5 text-sm" data-testid="type-sets">
          {sets.map(s => (
            <label key={s.id} className="flex items-center gap-2">
              <Tip label="Подключить свойства набора к типу; правка набора потом изменит и этот тип">
                <input type="checkbox" className="accent-primary" checked={body.sets.includes(s.id)}
                  onChange={e => patch({ sets: e.target.checked ? [...body.sets, s.id] : body.sets.filter(x => x !== s.id) })} />
              </Tip>
              {s.name} <span className="text-muted-foreground">({s.properties.length})</span>
            </label>
          ))}
        </div>
      </div>
      <div>
        <h2 className="mb-2 text-base font-semibold">Собственные свойства</h2>
        <Properties value={body.properties} onChange={properties => patch({ properties })} />
      </div>
      {ofType.length > 0 && (
        <div>
          <h2 className="text-base font-semibold">Значения для типа</h2>
          <p className="text-sm text-muted-foreground">Одни на все объекты этого типа; показываются в карточке каждого.</p>
          <div className="mt-2 flex flex-wrap gap-3" data-testid="type-values">
            {ofType.map(p => {
              const v = body.values[p.key]
              const put = (x: unknown) => patch({ values: { ...body.values, [p.key]: x } })
              return (
                <label key={p.key} className="grid gap-1 text-sm">{p.title}{p.unit ? `, ${p.unit}` : ''}
                  {p.kind === 'bool' ? <input type="checkbox" className="size-4 accent-primary" checked={v === true} onChange={e => put(e.target.checked)} />
                    : p.kind === 'choice' ? (
                      <select className={`${select} h-9`} value={String(v ?? '')} onChange={e => put(e.target.value || null)}>
                        <option value="">—</option>{(p.options ?? []).map(o => <option key={o.value} value={o.value}>{o.title}</option>)}
                      </select>
                    ) : <Input className="w-48" type={p.kind === 'number' ? 'number' : p.kind === 'date' ? 'date' : 'text'} step="any"
                        value={String(v ?? '')} onChange={e => put(p.kind === 'number' ? (e.target.value === '' ? null : Number(e.target.value)) : e.target.value)} />}
                </label>
              )
            })}
          </div>
        </div>
      )}
      {existing && (
        <div>
          <h2 className="text-base font-semibold">3D-модель</h2>
          <p className="text-sm text-muted-foreground">Файл GLB. Без модели объект показывается фигурой по габаритам.</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => picker.current?.click()}
              hint={`Файл GLB: объекты этого типа будут показаны им в 3D вместо фигуры по габаритам${existing.model ? '; прежний файл заменится' : ''}`}>{existing.model ? 'Заменить модель' : 'Загрузить модель'}</Button>
            <input ref={picker} type="file" accept=".glb" className="hidden" data-testid="model-file" onChange={e => {
              const file = e.target.files?.[0]
              if (file) putTypeModel(existing.id, file).then(t => { adopt({ ...t, schema: existing.schema }); onChanged() }, (ex: Error) => setError(ex.message))
              e.target.value = ''
            }} />
            {existing.model && (
              <>
                <span className="text-sm text-muted-foreground">{existing.model.name} · {(existing.model.size / 1024).toFixed(0)} КБ</span>
                <Button type="button" variant="ghost" size="sm" hint="Удалить файл модели: объекты типа снова будут показаны фигурой по габаритам"
                  onClick={() => deleteTypeModel(existing.id).then(() => getType(existing.id)).then(adopt).then(onChanged, (ex: Error) => setError(ex.message))}>Убрать</Button>
              </>
            )}
          </div>
          {existing.model?.warnings.map(w => <p key={w} role="status" className="mt-2 text-sm text-warning">{w}</p>)}
          {existing.model && <div className="mt-2 max-w-md"><Suspense fallback={null}><ModelPreview url={typeModelUrl(existing)} /></Suspense></div>}
        </div>
      )}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" hint="Сохранить тип; если изменились свойства, у схемы будет новая версия">Сохранить</Button>
        <Button asChild type="button" variant="ghost" hint="Вернуться в каталог, ничего не сохраняя"><a href="#/catalog">Отмена</a></Button>
        {existing && (
          <Button type="button" variant="outline" className="ml-auto"
            hint={existing.active ? 'Тип пропадёт из выбора при расстановке; объекты этого типа останутся на учёте' : 'Тип снова появится в выборе при расстановке объектов'}
            onClick={() => archiveType(existing.id, existing.active).then(onDone, (ex: Error) => setError(ex.message))}>
            {existing.active ? 'В архив' : 'Вернуть из архива'}
          </Button>
        )}
      </div>
    </form>
  )
}
