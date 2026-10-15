import { Printer } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { getBuilding, getDrawing, getSketch } from '@/api'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import {
  columnRing, ends, findRooms, outlines, parseSketch, stairEnds, stairRing, stairTreads, wallSides,
  type Floor, type Sketch, type XY,
} from '@/plan'
import { add, dot, mul, perp, sub, unit } from '@/plan/vec'
import { extents, faceChain } from './dims'
import { field, fitScale, MARGIN, PAPER, SCALES, SIDE, type Paper } from './print'
import { openingShape } from './symbols'

/** Millimetres on paper as metres of the plan at the scale. */
const mm = (v: number, scale: number) => (v * scale) / 1000
const cm = (m: number) => String(Math.round(m * 100))
const area = (m2: number) => m2.toFixed(2).replace('.', ',')
/** Outlines in plan coordinates: drawn inside the group that turns Y up. */
const path = (rings: XY[][]) => rings.map(r => 'M' + r.map(p => `${p[0]} ${p[1]}`).join('L') + 'Z').join('')

const PRINT_CSS = `
@media print {
  @page { margin: 0; }
  .no-print { display: none !important; }
  .sheets { background: none !important; padding: 0 !important; gap: 0 !important; }
  .sheet { box-shadow: none !important; margin: 0 !important; }
  .sheet:not(:last-child) { break-after: page; }
}
.sheet text { font-family: Arial, sans-serif; }
`

/** One floor's plan in plan units (y turned down for SVG), sized for paper at the scale. */
function Drawing({ floor, scale, box }: { floor: Floor; scale: number; box: [number, number, number, number] }) {
  const lines = useMemo(() => outlines(floor), [floor])
  const bearing = useMemo(() => outlines({ ...floor, walls: Object.fromEntries(Object.entries(floor.walls).filter(([, w]) => w.kind === 'bearing')) }), [floor])
  const rooms = useMemo(() => findRooms(floor, lines), [floor, lines])
  const t = (v: number) => mm(v, scale)
  const [x0, y0, x1, y1] = box
  const text = (at: XY, s: ReactNode, size: number, angle = 0, weight = 400, fill = '#222') => (
    <text x={at[0]} y={-at[1]} fontSize={t(size)} fontWeight={weight} fill={fill} textAnchor="middle" dominantBaseline="middle"
      transform={angle ? `rotate(${-angle} ${at[0]} ${-at[1]})` : undefined}>{s}</text>
  )
  // dimension lines along each face: the chain next to the wall, the whole face further out
  const dims: ReactNode[] = []
  for (const [id, w] of Object.entries(floor.walls)) {
    const o = lines[id], s = wallSides(floor, id, o)
    const [a, b] = ends(floor, w)
    const d = unit(sub(b, a)), n = perp(d)
    let ang = (Math.atan2(d[1], d[0]) * 180) / Math.PI
    if (ang > 90) ang -= 180
    if (ang <= -90) ang += 180
    for (const [side, sign] of [['plus', 1], ['minus', -1]] as const) {
      const start = side === 'plus' ? o.aPlus : o.aMinus, s0 = dot(sub(start, a), d)
      const at = (x: number, off: number) => add(add(start, mul(d, x - s0)), mul(n, sign * t(off)))
      const chain = faceChain(floor, id, o, side), whole = side === 'plus' ? s.plus : s.minus
      if (whole * 1000 / scale < 8) continue
      for (const c of chain) if ((c.to - c.from) * 1000 / scale >= 6) dims.push(text(at((c.from + c.to) / 2, 2.2), cm(c.to - c.from), 1.8, ang, 400, c.opening ? '#1864ab' : '#333'))
      dims.push(text(at(s0 + whole / 2, chain.length ? 5 : 2.2), cm(whole), 1.8, ang))
    }
  }
  const [ox0, oy0, ox1, oy1] = extents(lines) ?? box
  const g = t(11), tick = t(1.2)
  return (
    <svg width={`${(x1 - x0) * 1000 / scale}mm`} height={`${(y1 - y0) * 1000 / scale}mm`} viewBox={`${x0} ${-y1} ${x1 - x0} ${y1 - y0}`}>
      <g transform="scale(1 -1)">
      {rooms.map(r => <path key={r.key} d={path([r.contour, ...r.holes])} fill="#fbfaf6" fillRule="evenodd" stroke="#bbb" strokeWidth={t(0.15)} />)}
      {Object.values(floor.stairs ?? {}).map((st, i) => {
        const [f0, f1] = stairEnds(st)
        return (
          <g key={`s${i}`} fill="none" stroke="#333" strokeWidth={t(0.2)}>
            <path d={path([stairRing(st)])} fill="#fff" />
            {stairTreads(st).map(([p, q], k) => <path key={k} d={`M${p[0]} ${p[1]}L${q[0]} ${q[1]}`} />)}
            <path d={`M${f0[0]} ${f0[1]}L${f1[0]} ${f1[1]}`} />
          </g>
        )
      })}
      <path d={path(Object.entries(floor.walls).filter(([, w]) => w.kind === 'partition').map(([id]) => lines[id].poly))} fill="#9a9a9a" />
      <path d={path(Object.values(bearing).map(o => o.poly))} fill="#333" />
      {Object.values(floor.columns ?? {}).map((c, i) => <path key={`c${i}`} d={path([columnRing(c)])} fill="#333" />)}
      {Object.values(floor.openings).map((o, i) => {
        const sh = openingShape(floor, o, t(0.1))
        return (
          <g key={`o${i}`}>
            <path d={sh.gap} fill="#fff" />
            <path d={sh.lines} fill="none" stroke="#333" strokeWidth={t(0.2)} />
            {sh.swing && <path d={sh.swing} fill="none" stroke="#666" strokeWidth={t(0.15)} strokeDasharray={`${t(1)} ${t(0.7)}`} />}
          </g>
        )
      })}
      {/* the overall size, outside */}
      <g stroke="#555" strokeWidth={t(0.15)}>
        <path d={`M${ox0} ${oy1 + g}H${ox1}M${ox0} ${oy1 + g - tick}v${2 * tick}M${ox1} ${oy1 + g - tick}v${2 * tick}`} />
        <path d={`M${ox0 - g} ${oy0}V${oy1}M${ox0 - g - tick} ${oy0}h${2 * tick}M${ox0 - g - tick} ${oy1}h${2 * tick}`} />
      </g>
      </g>
      {dims}
      {text([(ox0 + ox1) / 2, oy1 + g + t(2)], cm(ox1 - ox0), 2)}
      {text([ox0 - g - t(2), (oy0 + oy1) / 2], cm(oy1 - oy0), 2, 90)}
      {rooms.map(r => (
        <g key={`l${r.key}`}>
          {text([r.labelAt[0], r.labelAt[1] + t(2)], [r.label?.number, r.label?.name].filter(Boolean).join(' ') || '—', 2.5, 0, 600)}
          {text([r.labelAt[0], r.labelAt[1] - t(2)], `${area(r.area)} м²`, 2.2)}
        </g>
      ))}
    </svg>
  )
}

/** The plan's sheets for print: a floor a sheet, at a scale, with its room schedule and title block. */
export function SketchPrint({ drawing }: { drawing: string }) {
  const [data, setData] = useState<{ sketch: Sketch; name: string; building: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [paper, setPaper] = useState<Paper>('A4')
  const [chosen, setChosen] = useState<number | 'fit'>('fit')
  const [date] = useState(() => new Date().toLocaleDateString('ru-RU'))
  useEffect(() => {
    Promise.all([getSketch(drawing), getDrawing(drawing)]).then(async ([s, d]) => {
      const b = await getBuilding(d.building_id).catch(() => null)
      setData({ sketch: parseSketch(s.sketch), name: d.name, building: b?.name ?? '' })
    }, (e: Error) => setError(e.message))
  }, [drawing])
  if (error) return <p className="p-6 text-sm text-destructive">{error}</p>
  if (!data) return <p className="p-6 text-sm text-muted-foreground">Загрузка…</p>
  const floors = [...data.sketch.floors].filter(f => Object.keys(f.walls).length).sort((a, b) => a.level - b.level)
  const [pw, ph] = PAPER[paper]
  const [fw, fh] = field(paper)
  return (
    <div className="min-h-full bg-muted" data-testid="sketch-print">
      <style>{`${PRINT_CSS} @media print { @page { size: ${paper} landscape; } }`}</style>
      <div className="no-print sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b bg-card px-4 py-2">
        <span className="text-sm font-semibold">{data.name} — листы для печати</span>
        <Select value={paper} onChange={e => setPaper(e.target.value as Paper)} aria-label="Формат листа" className="w-24" data-testid="print-paper">
          <option value="A4">A4</option>
          <option value="A3">A3</option>
        </Select>
        <Select value={chosen} onChange={e => setChosen(e.target.value === 'fit' ? 'fit' : Number(e.target.value))} aria-label="Масштаб" className="w-36" data-testid="print-scale">
          <option value="fit">по размеру листа</option>
          {SCALES.map(s => <option key={s} value={s}>1:{s}</option>)}
        </Select>
        <Button size="sm" onClick={() => window.print()} hint="Напечатать листы или сохранить их в PDF из окна печати браузера"><Printer className="size-4" />Печать</Button>
        <span className="text-xs text-muted-foreground">В окне печати выберите «Сохранить как PDF», чтобы получить файл.</span>
      </div>
      <div className="sheets flex flex-col items-center gap-6 p-6">
        {floors.length === 0 && <p className="text-sm text-muted-foreground">В плане нет ни одной стены — печатать нечего.</p>}
        {floors.map((f, i) => {
          const lines = outlines(f)
          const [x0, y0, x1, y1] = extents(lines)!
          // room for the dimension lines round the walls: 16 mm on paper
          const pad = (s: number) => mm(16, s)
          const fits = (s: number) => (x1 - x0 + 2 * pad(s)) * 1000 / s <= fw && (y1 - y0 + 2 * pad(s)) * 1000 / s <= fh
          const scale = chosen === 'fit' ? (SCALES.find(fits) ?? fitScale([x1 - x0, y1 - y0], paper) ?? SCALES[SCALES.length - 1]) : chosen
          const box: [number, number, number, number] = [x0 - pad(scale), y0 - pad(scale), x1 + pad(scale), y1 + pad(scale)]
          const rooms = findRooms(f, lines).sort((a, b) => (a.label?.number ?? '').localeCompare(b.label?.number ?? '', 'ru', { numeric: true }) || (a.label?.name ?? '').localeCompare(b.label?.name ?? '', 'ru'))
          const total = rooms.reduce((s, r) => s + r.area, 0)
          return (
            <section key={f.id} className="sheet relative bg-white text-black shadow" style={{ width: `${pw}mm`, height: `${ph}mm` }} data-testid="print-sheet">
              <div className="absolute overflow-hidden border border-black/70" style={{ left: `${MARGIN}mm`, top: `${MARGIN}mm`, width: `${fw}mm`, height: `${fh}mm` }}>
                <div className="flex h-full w-full items-center justify-center"><Drawing floor={f} scale={scale} box={box} /></div>
              </div>
              <div className="absolute flex flex-col justify-between text-[2.6mm] leading-tight" style={{ right: `${MARGIN}mm`, top: `${MARGIN}mm`, width: `${SIDE}mm`, height: `${fh}mm` }}>
                <table className="w-full border-collapse" data-testid="print-schedule">
                  <caption className="mb-[1mm] text-left font-semibold">Экспликация помещений</caption>
                  <thead><tr className="border-b border-black"><th className="w-[12mm] text-left font-semibold">№</th><th className="text-left font-semibold">Наименование</th><th className="w-[18mm] text-right font-semibold">Площадь, м²</th></tr></thead>
                  <tbody>
                    {rooms.map(r => <tr key={r.key} className="border-b border-black/20"><td>{r.label?.number ?? ''}</td><td>{r.label?.name || 'Помещение'}</td><td className="text-right tabular-nums">{area(r.area)}</td></tr>)}
                    <tr className="font-semibold"><td /><td>Итого</td><td className="text-right tabular-nums" data-testid="print-total">{area(total)}</td></tr>
                  </tbody>
                </table>
                <table className="w-full border-collapse border border-black" data-testid="print-title">
                  <tbody>
                    {[['Здание', data.building], ['План', data.name], ['Этаж', f.name], ['Масштаб', `1:${scale}`], ['Дата', date], ['Лист', `${i + 1} из ${floors.length}`]].map(([k, v]) => (
                      <tr key={k} className="border-b border-black/40"><td className="w-[22mm] border-r border-black/40 px-[1mm] text-black/60">{k}</td><td className="px-[1mm] font-semibold">{v}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )
        })}
      </div>
    </div>
  )
}
