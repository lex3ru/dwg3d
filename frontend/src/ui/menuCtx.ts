import { createContext, useContext, useEffect, useRef } from 'react'

/** One open popup at a time; a click outside any popup closes it. */
export const MenuCtx = createContext<{ open: string | null; setOpen: (id: string | null) => void }>({
  open: null, setOpen: () => {},
})

export function useMenu(id: string) {
  const { open, setOpen } = useContext(MenuCtx)
  return { isOpen: open === id, toggle: () => setOpen(open === id ? null : id), close: () => setOpen(null), open: () => setOpen(id) }
}

export function useOutsideClose(setOpen: (id: string | null) => void) {
  const ref = useRef(setOpen)
  useEffect(() => { ref.current = setOpen }, [setOpen])
  useEffect(() => {
    const down = (e: MouseEvent) => {
      const t = e.target as HTMLElement | null
      if (!t?.closest?.('.menu-root')) ref.current(null)
    }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') ref.current(null) }
    document.addEventListener('mousedown', down)
    window.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', down)
      window.removeEventListener('keydown', esc)
    }
  }, [])
}

