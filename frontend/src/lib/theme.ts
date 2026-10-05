import { useEffect, useState } from 'react'

export type Theme = 'light' | 'dark' | 'system'
const KEY = 'twin.theme'

function stored(): Theme {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch { /* storage blocked */ }
  return 'system'
}

const dark = (t: Theme) => t === 'dark' || (t === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)

export function applyTheme(t: Theme = stored()) {
  document.documentElement.classList.toggle('dark', dark(t))
}

/** The theme choice (persisted) and whether the page is dark now. */
export function useTheme() {
  const [theme, set] = useState<Theme>(stored)
  useEffect(() => {
    applyTheme(theme)
    if (theme !== 'system') return
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const on = () => applyTheme('system')
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [theme])
  const setTheme = (t: Theme) => {
    try { localStorage.setItem(KEY, t) } catch { /* storage blocked */ }
    set(t)
  }
  return { theme, setTheme, isDark: dark(theme) }
}

/** Whether the page is dark now (the `dark` class on <html>), following changes. */
export function useDarkClass() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  useEffect(() => {
    const el = document.documentElement
    const on = () => setDark(el.classList.contains('dark'))
    const mo = new MutationObserver(on)
    mo.observe(el, { attributes: true, attributeFilter: ['class'] })
    return () => mo.disconnect()
  }, [])
  return dark
}
