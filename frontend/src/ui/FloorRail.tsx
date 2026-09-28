import type { FloorMeta } from '../api'

/** Vertical "floor ladder": top floor first, "+" shows the whole building. */
export default function FloorRail({ floors, active, onSelect }: {
  floors: FloorMeta[]        // any order
  active: string | null
  onSelect: (id: string | null) => void
}) {
  const desc = [...floors].sort((a, b) => b.elevation! - a.elevation!)
  return (
    <nav className="floor-rail" aria-label="Этажи">
      <button className={`rail-btn all${active == null ? ' on' : ''}`} title="Все этажи" onClick={() => onSelect(null)}>+</button>
      <div className="rail-list">
        {desc.map((f) => (
          <button key={f.id} className={`rail-btn${active === f.id ? ' on' : ''}`} onClick={() => onSelect(f.id)}
            title={`${f.name} · ${f.elevation! >= 0 ? '+' : ''}${f.elevation!.toFixed(2)} м`}>
            {f.level ?? '·'}
          </button>
        ))}
      </div>
    </nav>
  )
}
