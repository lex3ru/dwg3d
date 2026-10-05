import { useEffect, useRef, useState } from 'react'

// Events from the services, as the gateway passes them on (GET /api/stream).
// Nothing is replayed after a break: on reconnecting, reload what is shown.

export type TwinEvent = {
  id: string
  type: string
  time: string
  actor: { kind: string; id: string }
  subject: { kind: string; id: string }
  data: Record<string, unknown>
}

type Listener = (event: TwinEvent) => void
const listeners = new Set<Listener>()
const watchers = new Set<(connected: boolean) => void>()
let source: EventSource | null = null
let connected = false

function setConnected(value: boolean) {
  connected = value
  watchers.forEach(w => w(value))
}

function open() {
  if (source) return
  source = new EventSource('/api/stream')
  source.onopen = () => setConnected(true)
  source.onerror = () => setConnected(false)        // the browser reconnects by itself
  source.onmessage = message => {
    const event = JSON.parse(message.data) as TwinEvent
    listeners.forEach(l => l(event))
  }
}

/** Call `listener` for every event while the component is mounted. */
export function useEvents(listener: Listener) {
  const latest = useRef(listener)
  useEffect(() => { latest.current = listener })
  useEffect(() => {
    const call: Listener = event => latest.current(event)
    listeners.add(call)
    open()
    return () => { listeners.delete(call) }
  }, [])
}

/** Whether the stream is connected now. */
export function useStreamConnected() {
  const [value, set] = useState(connected)
  useEffect(() => {
    watchers.add(set)
    open()
    return () => { watchers.delete(set) }
  }, [])
  return value
}
