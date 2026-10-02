import { Icon } from './icons'

export function HelpButton({ onClick }: { onClick: () => void }) {
  return <button className="help-btn round" onClick={onClick} title="Справка по управлению"><Icon name="help" /></button>
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
    <div className="help-overlay" onClick={onClose}>
      <div className="help-card" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Справка">
        <header><h2>Управление</h2><button className="icon" onClick={onClose} aria-label="Закрыть"><Icon name="close" /></button></header>
        <div className="help-grid">
          {HELP.map(([title, rows]) => (
            <section key={title}>
              <h3>{title}</h3>
              <dl>{rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}
