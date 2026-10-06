import { List, Map as MapIcon } from 'lucide-react'
import { Tip } from '../components/ui/tooltip'
import { cn } from '../lib/utils'
import { to } from './route'

/** «План» shows the rooms of the building two ways: a floor on the drawing, or a list with a search. */
export function PlanViews({ building, list }: { building: string; list: boolean }) {
  const view = (here: boolean, href: string, label: string, Icon: typeof List, hint: string) => (
    <Tip label={hint}>
      <a href={href} aria-current={here ? 'page' : undefined}
        className={cn('flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm text-muted-foreground hover:text-foreground',
          here && 'bg-card text-foreground shadow-sm')}>
        <Icon className="size-4" />{label}
      </a>
    </Tip>
  )
  return (
    <nav className="flex gap-0.5 rounded-lg bg-secondary p-0.5" aria-label="Вид" data-testid="plan-views">
      {view(!list, to.plan(building), 'План', MapIcon, 'Этаж на чертеже: помещения и объекты на своих местах; щелчок по помещению открывает его карточку')}
      {view(list, to.rooms(building), 'Список', List, 'Все помещения по этажам с поиском по названию и номеру')}
    </nav>
  )
}
