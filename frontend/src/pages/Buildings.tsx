import { Building2, Plus, Search } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { createBuilding, listBuildings, type Building, type Me } from '../api'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Tip } from '../components/ui/tooltip'
import { useEvents } from '../stream'

/** Why an account that is not in the directory of people sees nothing, and what to do. */
const NOBODY: Record<string, string> = {
  unknown: 'Вашей учётной записи нет в справочнике людей, поэтому доступа пока нет. Обратитесь к администратору здания: он добавит вас в справочник и выдаст права.',
  ambiguous: 'Вашу почту в справочнике людей носят несколько человек, поэтому учётная запись не связалась сама. Обратитесь к администратору здания.',
  left: 'В справочнике людей вы отмечены как выбывший, доступ закрыт. Если это ошибка, обратитесь к администратору здания.',
}

const plural = (n: number, one: string, few: string, many: string) => {
  const d = n % 10, h = n % 100
  return `${n} ${d === 1 && h !== 11 ? one : d >= 2 && d <= 4 && (h < 12 || h > 14) ? few : many}`
}

/** The buildings the user may see. Until rights by area exist (stage 2): all of them, for the system administrator. */
export function Buildings({ me, refresh }: { me: Me; /** changes when the set of visible buildings may have */ refresh?: string }) {
  const admin = me.user.is_admin
  const [items, setItems] = useState<Building[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [q, setQ] = useState('')
  const needle = q.trim().toLowerCase()
  const shown = items && needle ? items.filter(b => `${b.name} ${b.address ?? ''}`.toLowerCase().includes(needle)) : items

  const load = useCallback(() => {
    void refresh
    listBuildings().then(setItems, (e: Error) => setError(e.message))
  }, [refresh])
  useEffect(load, [load])
  useEvents(event => { if (event.type.startsWith('buildings.')) load() })

  return (
    <section>
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Мои здания</h1>
        {admin && !adding && (
          <Button variant="outline" size="sm" hint="Новое пустое здание: дальше в него загружают поэтажные планы DWG или DXF"
            onClick={() => setAdding(true)}><Plus className="size-4" /> Создать здание</Button>
        )}
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      {adding && <NewBuilding onDone={() => { setAdding(false); load() }} />}
      {items && items.length > 8 && (
        <div className="relative mt-4 w-64 max-w-full">
          <Search className="pointer-events-none absolute top-2 left-2 size-4 text-muted-foreground" />
          <Tip label="Название или адрес здания; список сужается по мере ввода">
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Найти здание" aria-label="Поиск здания"
              className="h-8 w-full rounded-md border bg-card pr-2 pl-8 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
          </Tip>
        </div>
      )}
      {shown && needle && shown.length === 0 && <p className="mt-4 text-sm text-muted-foreground">Ничего не найдено. Проверьте название или адрес.</p>}
      {shown && shown.length > 0 && (
        <ul className="mt-5 grid gap-3 sm:grid-cols-2" data-testid="buildings">
          {shown.map(b => (
            <li key={b.id}>
              <Tip label="Кабинет здания: что требует внимания, помещения, объекты, план">
                <a href={`#/b/${b.id}`} className="block rounded-lg border bg-card p-4 hover:border-primary">
                  <div className="flex items-center gap-2 font-medium"><Building2 className="size-4 text-muted-foreground" /> {b.name}</div>
                  {b.address && <div className="mt-1 text-sm text-muted-foreground">{b.address}</div>}
                  <div className="mt-2 text-xs text-muted-foreground">
                    {b.drawings ? `${plural(b.floors ?? 0, 'этаж', 'этажа', 'этажей')} · ${plural(b.rooms ?? 0, 'помещение', 'помещения', 'помещений')}`
                      : 'Чертежи ещё не загружены'}
                  </div>
                </a>
              </Tip>
            </li>
          ))}
        </ul>
      )}
      {items && items.length === 0 && !adding && (
        <div className="mt-6 flex flex-col items-center gap-2 rounded-lg border border-dashed bg-card px-6 py-14 text-center">
          <Building2 className="size-8 text-muted-foreground" />
          <p className="font-medium">Зданий пока нет</p>
          <p className="max-w-md text-sm text-muted-foreground">
            {admin ? 'Создайте здание и загрузите в него поэтажные планы (DWG или DXF).'
              : me.person ? 'Здесь появятся здания, к которым вам выдадут доступ. Обратитесь к администратору здания.'
                : NOBODY[me.reason ?? 'unknown']}
          </p>
        </div>
      )}
    </section>
  )
}

function NewBuilding({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    createBuilding(name, address).then(b => { location.hash = `#/p/${b.id}`; onDone() },
      (ex: Error) => { setError(ex.message); setBusy(false) })
  }
  return (
    <form onSubmit={submit} className="mt-4 grid max-w-lg gap-2 rounded-lg border bg-card p-4">
      <label className="grid gap-1 text-sm">Название
        <Input value={name} onChange={e => setName(e.target.value)} required maxLength={200} autoFocus placeholder="Корпус А" />
      </label>
      <label className="grid gap-1 text-sm">Адрес
        <Input value={address} onChange={e => setAddress(e.target.value)} maxLength={500} placeholder="необязательно" />
      </label>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="mt-1 flex gap-2">
        <Button type="submit" disabled={busy || !name.trim()}
          hint={name.trim() ? 'Откроются чертежи нового здания для загрузки планов; другим оно станет видно после выдачи доступа' : 'Сначала введите название'}>Создать</Button>
        <Button type="button" variant="ghost" hint="Закрыть форму, ничего не создавая" onClick={onDone}>Отмена</Button>
      </div>
    </form>
  )
}
