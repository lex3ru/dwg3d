import { BookOpen } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { to } from '../shell/route'

const KEY = 'twin.howto.closed'

/** A short guide on «Обзор»: what the program is for, its main functions and where they are — for the reader's
 * role. Folded once, it stays folded in this browser. */
export function HowTo({ building, admin, system }: {
  building: string
  /** administers the building: drawings, the editor, people, rights, variants, the journal */
  admin: boolean
  /** the system's administrator: buildings, the catalog, the state of the services */
  system: boolean
}) {
  const [open, setOpen] = useState(() => { try { return localStorage.getItem(KEY) !== '1' } catch { return true } })
  const toggle = (now: boolean) => {
    setOpen(now)
    try { if (now) localStorage.removeItem(KEY); else localStorage.setItem(KEY, '1') } catch { /* private mode */ }
  }
  const go = (href: string, label: string) => <a className="font-medium text-primary hover:underline" href={href}>«{label}»</a>
  const item = (what: ReactNode, text: ReactNode) => <li><span className="mr-1">{what}</span>— {text}</li>
  return (
    <details open={open} onToggle={(e) => toggle((e.currentTarget as HTMLDetailsElement).open)}
      className="rounded-lg border bg-card px-4 py-3 text-sm" data-testid="howto">
      <summary className="flex cursor-pointer list-none items-center gap-2 font-medium [&::-webkit-details-marker]:hidden">
        <BookOpen className="size-4 text-primary" /> Как работать в программе
        <span className="ml-auto text-xs font-normal text-muted-foreground">{open ? 'свернуть' : 'развернуть'}</span>
      </summary>
      <div className="mt-3 grid gap-3 text-muted-foreground">
        <p>
          <b className="text-foreground">Цифровой двойник здания</b> — общий учёт здания в одном месте: поэтажные планы и 3D-модель,
          собранные из чертежей; помещения; мебель и оборудование с инвентарными номерами и QR-метками; кто в каком помещении работает
          и кто что может видеть и менять. Всё меняется с записью в историю.
        </p>
        <div>
          <h3 className="mb-1 font-medium text-foreground">Каждый день</h3>
          <ul className="grid list-disc gap-1 pl-5">
            {item(<b className="text-foreground">«Обзор»</b>, 'ваши помещения, объекты, за которые вы отвечаете, и что требует внимания; поиск объекта по номеру и сканер QR-метки')}
            {item(go(to.plan(building), 'План'), 'этаж на чертеже с объектами на своих местах или список помещений; щелчок по помещению — его карточка: люди, объекты, ведомость, комментарии')}
            {item(go(to.assets(building), 'Объекты'), 'реестр мебели и оборудования: поиск, отбор по состоянию, выгрузка в Excel; в карточке объекта — свойства, ответственный, файлы и история')}
            {item(<b className="text-foreground">Строка поиска вверху</b>, 'быстро найти помещение по названию или номеру')}
          </ul>
          {!admin && <p className="mt-1">Что вам видно, решает администратор здания. Если чего-то не хватает — обратитесь к нему.</p>}
        </div>
        {admin && (
          <div>
            <h3 className="mb-1 font-medium text-foreground">Администратору здания: порядок работы</h3>
            <ol className="grid list-decimal gap-1 pl-5">
              <li>{go(to.drawings(building), 'Чертежи')} — загрузите поэтажные планы DWG или DXF: из них соберутся этажи, помещения и 3D-модель. Новую версию чертежа, которая снимает помещения, система сначала даст проверить; там же задаются номера этажей.</li>
              <li>{go(to.plan(building), 'План')} — проверьте помещения и назовите те, что пришли без названия.</li>
              <li>Расставьте объекты: по одному или рядом на «Плане», из Excel в «Объектах» или в <b className="text-foreground">«Редакторе»</b> — 3D-сцене, где мебель и оборудование ставятся из каталога, а у видеонаблюдения, освещения, Wi-Fi и пожарной сигнализации свои слои с обзором камер и освещённостью. Инвентарный номер можно ввести или сгенерировать.</li>
              <li>{go(to.people(building), 'Люди')} и {go(to.access(building), 'Доступ')} — кто в каком помещении работает и кто что может; там же ссылки для просмотра без учётной записи.</li>
              <li>{go(to.assets(building), 'Объекты')} → «Метки» — распечатайте QR-метки и наклейте на объекты.</li>
            </ol>
            <p className="mt-1">
              Ещё: {go(to.variants(building), 'Варианты')} — черновики перестановки: сравнить с фактом, посчитать по ценам каталога и перенести в учёт;{' '}
              {go(to.journal(building), 'Журнал')} — кто, что и когда менял.
            </p>
          </div>
        )}
        {system && (
          <div>
            <h3 className="mb-1 font-medium text-foreground">Администратору системы</h3>
            <p>
              {go(to.buildings, 'Здания')} — создать здание и назначить ему администратора (в его «Доступе»);{' '}
              {go('#/catalog', 'Каталог')} — типы мебели и оборудования с их свойствами, общие для всех зданий;{' '}
              {go('#/system', 'Состояние системы')} — работают ли сервисы.
            </p>
          </div>
        )}
        <p className="text-xs">Подсказки есть у каждой кнопки: наведите указатель (на телефоне — подержите палец).</p>
      </div>
    </details>
  )
}
