import { useEffect, useRef } from 'react'
import type { ProjectEvent } from '../api'

/** silence after which the stream is taken for dead (the server pings every 25 s) */
const SILENT_MS = 60000

/** Changes in the project as they happen (Server-Sent Events). After a lost connection
 * comes back, `on` gets `{entity: 'resync'}`: what changed meanwhile is unknown.
 * EventSource retries by itself only after a dropped stream; an error answer (the API
 * restarting behind a proxy: 502) closes it for good, and a proxy may keep a dead stream
 * open — so it is also opened again here: when closed, or silent for SILENT_MS, waiting
 * longer after each failure (up to 30 s). */
export function useProjectEvents(projectId: string, on: (ev: ProjectEvent) => void) {
  const handler = useRef(on)
  useEffect(() => { handler.current = on })
  useEffect(() => {
    if (!projectId || typeof EventSource === 'undefined') return
    let es: EventSource | null = null
    let retry: number | undefined
    let wait = 1000
    let lost = false
    let heard = Date.now()
    const reopen = () => {
      es?.close()
      lost = true
      heard = Date.now() + wait               // the watchdog waits for this attempt
      window.clearTimeout(retry)
      retry = window.setTimeout(open, wait)
      wait = Math.min(wait * 2, 30000)
    }
    const open = () => {
      heard = Date.now()
      es = new EventSource(`/api/projects/${projectId}/events`)
      es.addEventListener('change', (e) => {
        heard = Date.now()
        try { handler.current(JSON.parse((e as MessageEvent).data)) } catch { /* not ours */ }
      })
      es.addEventListener('ping', () => { heard = Date.now() })
      es.onopen = () => {
        heard = Date.now()
        wait = 1000
        if (lost) { lost = false; handler.current({ entity: 'resync' }) }
      }
      es.onerror = () => {
        lost = true
        if (es?.readyState === EventSource.CLOSED) reopen()
      }
    }
    open()
    const watchdog = window.setInterval(() => { if (Date.now() - heard > SILENT_MS) reopen() }, 5000)
    return () => { window.clearInterval(watchdog); window.clearTimeout(retry); es?.close() }
  }, [projectId])
}
