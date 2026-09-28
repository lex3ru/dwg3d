/** Menu items: checkbox and radio rows. */
export function Check({ on, label, onChange, hint, disabled }: {
  on: boolean; label: string; onChange: (v: boolean) => void; hint?: string; disabled?: boolean
}) {
  return (
    <button className={`menu-item check${on ? ' on' : ''}`} onClick={() => onChange(!on)} title={hint} disabled={disabled}
      role="menuitemcheckbox" aria-checked={on}>
      <span className="mark">{on ? '✓' : ''}</span>{label}
    </button>
  )
}

export function Radio<T extends string>({ value, options, onChange }: {
  value: T; options: { id: T; label: string; hint?: string }[]; onChange: (v: T) => void
}) {
  return (
    <>
      {options.map((o) => (
        <button key={o.id} className={`menu-item radio${value === o.id ? ' on' : ''}`} onClick={() => onChange(o.id)}
          title={o.hint} role="menuitemradio" aria-checked={value === o.id}>
          <span className="mark">{value === o.id ? '●' : ''}</span>{o.label}
        </button>
      ))}
    </>
  )
}
