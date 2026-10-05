import { DoorOpen, FileStack, Layers, Map as MapIcon } from 'lucide-react'
import type { Building, TreeFloor } from '../api'
import { to } from '../shell/route'

/** «Кабинет» of a building. What is one's own — rooms, objects one answers for — arrives
 * with people, access and objects (stages 2–4); until then: the building at a glance. */
export function Home({ building, floors, admin }: { building: Building; floors: TreeFloor[]; admin: boolean }) {
  const rooms = floors.reduce((n, f) => n + f.rooms.length, 0)
  const area = floors.reduce((n, f) => n + f.rooms.reduce((a, r) => a + r.area, 0), 0)
  const stat = (label: string, value: string, href: string, Icon: typeof Layers) => (
    <a href={href} className="rounded-lg border bg-card p-4 hover:border-primary">
      <div className="flex items-center gap-1.5 text-sm text-muted-foreground"><Icon className="size-4" /> {label}</div>
      <div className="mt-1 text-2xl font-medium">{value}</div>
    </a>
  )
  return (
    <section className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">{building.name}</h1>
        {building.address && <p className="text-sm text-muted-foreground">{building.address}</p>}
      </div>
      {floors.length === 0 ? (
        <div className="rounded-lg border border-dashed bg-card px-6 py-12 text-center">
          <p className="font-medium">В здании пока нет этажей</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
            {admin ? <>Загрузите поэтажные планы в разделе <a className="text-primary" href={to.drawings(building.id)}>«Чертежи»</a>.</>
              : 'Администратор здания ещё не загрузил чертежи.'}
          </p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-3" data-testid="summary">
          {stat('Этажи', String(floors.length), to.plan(building.id), Layers)}
          {stat('Помещения', String(rooms), to.rooms(building.id), DoorOpen)}
          {stat('Площадь помещений', `${Math.round(area).toLocaleString('ru')} м²`, to.plan(building.id), MapIcon)}
        </div>
      )}
      {admin && floors.length > 0 && (
        <a href={to.drawings(building.id)} className="inline-flex items-center gap-1.5 text-sm text-primary">
          <FileStack className="size-4" /> Чертежи здания
        </a>
      )}
    </section>
  )
}
