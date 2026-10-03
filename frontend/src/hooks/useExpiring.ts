import { useEffect, useState } from 'react'

/** State that falls back to `empty` `ms` after it was last set to something else
 * (a notice, a highlight). */
export function useExpiring<T>(empty: T, ms: number) {
  const [value, setValue] = useState<T>(empty)
  const set = Array.isArray(value) ? value.length > 0 : !!value
  useEffect(() => {
    if (!set) return
    const t = window.setTimeout(() => setValue(empty), ms)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])
  return [value, setValue] as const
}
