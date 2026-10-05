import { useCallback, useState } from 'react'

interface Saved { open: boolean; width: number }

const key = (id: string) => `dwg3d.dock.${id}`
export const MIN_WIDTH = 240
export const MAX_WIDTH = 600

function read(id: string, width: number): Saved {
  try {
    const s = JSON.parse(localStorage.getItem(key(id)) ?? 'null') as Partial<Saved> | null
    if (s) return { open: !!s.open, width: Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, s.width ?? width)) }
  } catch { /* storage blocked or damaged */ }
  return { open: false, width }
}

/** Whether a dock is open and how wide it is; both are kept per browser. */
export function useDockState(id: string, defaultWidth: number) {
  const [st, setSt] = useState<Saved>(() => read(id, defaultWidth))
  const update = useCallback((patch: Partial<Saved>) => setSt((cur) => {
    const next = { ...cur, ...patch }
    try { localStorage.setItem(key(id), JSON.stringify(next)) } catch { /* storage blocked */ }
    return next
  }), [id])
  const setOpen = useCallback((open: boolean) => update({ open }), [update])
  const setWidth = useCallback((width: number) => update({ width: Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(width))) }), [update])
  const toggle = useCallback(() => setSt((cur) => {
    const next = { ...cur, open: !cur.open }
    try { localStorage.setItem(key(id), JSON.stringify(next)) } catch { /* storage blocked */ }
    return next
  }), [id])
  return { open: st.open, width: st.width, setOpen, setWidth, toggle }
}

export type DockState = ReturnType<typeof useDockState>
