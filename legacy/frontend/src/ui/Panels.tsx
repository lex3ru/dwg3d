import { CircleHelp } from 'lucide-react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { floatClass } from '@/components/ui/float'
import { cn } from '@/lib/utils'

export function HelpButton({ onClick }: { onClick: () => void }) {
  return (
    <button aria-label="Справка по управлению" title="Справка по управлению" onClick={onClick}
      className={cn(floatClass, 'absolute top-3.5 left-3.5 z-20 grid size-10 cursor-pointer place-items-center rounded-full p-0 hover:text-primary')}>
      <CircleHelp className="size-[18px]" />
    </button>
  )
}

const HELP: [string, [string, string][]][] = [
  ['Обзор', [
    ['ЛКМ + перетаскивание', 'вращение вокруг здания'],
    ['ПКМ / Shift + ЛКМ', 'панорама'],
    ['Колесо, щипок, «+» / «−»', 'зум'],
    ['Клик по помещению', 'карточка помещения'],
    ['Номер этажа слева', 'срез до этажа, «+» — всё здание'],
  ]],
  ['Полёт', [
    ['W A S D, стрелки', 'перемещение'],
    ['E / Пробел, Q / C', 'вверх, вниз'],
    ['Перетаскивание мышью', 'осмотр'],
    ['Колесо', 'вперёд / назад'],
    ['Shift', 'быстрее'],
  ]],
  ['Прогулка', [
    ['Клик по сцене', 'захват мыши для осмотра'],
    ['W A S D, стрелки', 'идти'],
    ['Shift', 'быстрее'],
    ['Esc', 'выйти'],
  ]],
  ['Вид 2D', [
    ['ЛКМ + перетаскивание', 'сдвиг плана'],
    ['ПКМ + перетаскивание', 'поворот'],
    ['Колесо', 'зум'],
  ]],
  ['Рулетка', [
    ['Два клика', 'расстояние'],
    ['Клики по вершинам', 'площадь; замкнуть — клик по первой точке, двойной клик или Enter'],
    ['Backspace / Esc', 'убрать точку / сбросить'],
  ]],
]

export function HelpOverlay({ onClose }: { onClose: () => void }) {
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
        <DialogHeader><DialogTitle>Управление</DialogTitle></DialogHeader>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-x-6 gap-y-3">
          {HELP.map(([title, rows]) => (
            <section key={title}>
              <h3 className="mt-1 mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
              <dl className="m-0 grid gap-1.5 text-sm">
                {rows.map(([k, v]) => <div key={k} className="grid grid-cols-2 gap-2"><dt className="font-medium">{k}</dt><dd className="m-0 text-muted-foreground">{v}</dd></div>)}
              </dl>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
