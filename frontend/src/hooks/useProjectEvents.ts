import { useEffect, useRef } from 'react'
import type { ProjectEvent } from '../api'

/** Changes in the project as they happen (Server-Sent Events). After a lost connection
 * comes back, `on` gets `{entity: 'resync'}`: what changed meanwhile is unknown. */
export function useProjectEvents(projectId: string, on: (ev: ProjectEvent) => void) {
  const handler = useRef(on)
  useEffect(() => { handler.current = on })
  useEffect(() => {
    if (!projectId || typeof EventSource === 'undefined') return
    const es = new EventSource(`/api/projects/${projectId}/events`)
    let lost = false
    es.addEventListener('change', (e) => {
      try { handler.current(JSON.parse((e as MessageEvent).data)) } catch { /* not ours */ }
    })
    es.onerror = () => { lost = true }
    es.onopen = () => { if (lost) { lost = false; handler.current({ entity: 'resync' }) } }
    return () => es.close()
  }, [projectId])
}
