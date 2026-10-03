import { useEffect, useMemo } from 'react'
import { closeUIContext, reportUIContext, type UIContext } from '../api'
import { me } from '../session'

const newClient = () => `tab-${Math.random().toString(36).slice(2, 14)}`

/** This tab's id, kept across reloads of the tab. */
function tabClient(): string {
  try {
    const k = 'dwg3d.client'
    const v = sessionStorage.getItem(k) ?? newClient()
    sessionStorage.setItem(k, v)
    return v
  } catch { return newClient() }
}

/** What this window shows, reported for the user's copilot: soon after a change, then every
 * minute while the tab is visible, and `closed` when the page goes away. Returns the context. */
export function useUIContext(projectId: string, s: Omit<UIContext, 'client' | 'closed'>): UIContext {
  const client = useMemo(() => tabClient(), [])
  const selected = (s.selected ?? []).join('\n')
  const ui = useMemo(() => ({
    client, drawing: s.drawing, floor: s.floor, view: s.view,
    selected: selected ? selected.split('\n') : [], room: s.room, proposal: s.proposal, tool: s.tool,
  }), [client, s.drawing, s.floor, s.view, selected, s.room, s.proposal, s.tool])
  useEffect(() => {
    if (!projectId || me?.guest) return
    const send = () => { if (document.visibilityState === 'visible') reportUIContext(projectId, ui).catch(() => {}) }
    const t = window.setTimeout(send, 500)
    const every = window.setInterval(send, 60000)
    const bye = () => closeUIContext(projectId, client)
    window.addEventListener('pagehide', bye)
    return () => { window.clearTimeout(t); window.clearInterval(every); window.removeEventListener('pagehide', bye) }
  }, [projectId, ui, client])
  return ui
}
