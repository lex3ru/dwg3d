import { RefreshCw, Send } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createNote, getStatus, type SystemStatus } from '../api'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Tip } from '../components/ui/tooltip'
import { useEvents, useStreamConnected } from '../stream'
import { CopilotSettings } from './CopilotSettings'

const mark = (value: boolean | null) =>
  value === null ? <span className="text-muted-foreground">—</span>
    : value ? <Badge variant="success">да</Badge> : <Badge variant="destructive">нет</Badge>

/** For the system administrator: are the services up, and do events get through. */
export function System() {
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchStatus = useCallback(
    () => getStatus().then(s => { setStatus(s); setError(null) }, (e: Error) => setError(e.message)).finally(() => setLoading(false)),
    [])
  useEffect(() => { void fetchStatus() }, [fetchStatus])
  const load = () => { setLoading(true); void fetchStatus() }

  return (
    <section className="space-y-8">
      <div>
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">Состояние системы</h1>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}
            hint="Заново опросить сервисы: отвечают ли они, есть ли у них связь с базой и шиной событий">
            <RefreshCw className="size-4" /> Обновить
          </Button>
        </div>
        {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
        {status && (
          <div className="mt-4 overflow-x-auto rounded-lg border bg-card">
            <table className="w-full text-sm" data-testid="services">
              <thead className="text-left text-muted-foreground">
                <tr className="border-b">
                  <th className="px-3 py-2 font-medium">Сервис</th>
                  <th className="px-3 py-2 font-medium">Отвечает</th>
                  <th className="px-3 py-2 font-medium">База</th>
                  <th className="px-3 py-2 font-medium">Шина событий</th>
                  <th className="px-3 py-2 text-right font-medium">Ответ, мс</th>
                </tr>
              </thead>
              <tbody>
                {status.services.map(s => (
                  <tr key={s.name} className="border-b last:border-0" data-service={s.name} data-ok={s.ok}>
                    <td className="px-3 py-2 font-medium">{s.name}</td>
                    <td className="px-3 py-2">{mark(s.ok)}</td>
                    <td className="px-3 py-2">{mark(s.db)}</td>
                    <td className="px-3 py-2">{mark(s.nats)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{s.ms ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <Delivery />
      <CopilotSettings />
    </section>
  )
}

type Probe = { state: 'idle' } | { state: 'waiting'; id: string | null; since: number }
  | { state: 'done'; ms: number } | { state: 'failed'; message: string }

/** Create a note in the sample service and wait for its event to come back through the bus and the stream. */
function Delivery() {
  const connected = useStreamConnected()
  const [probe, setProbe] = useState<Probe>({ state: 'idle' })
  const early = useRef(new Set<string>())         // events that arrived before the request returned

  useEvents(event => {
    if (event.type !== 'ping.note.created') return
    early.current.add(event.subject.id)
    setProbe(p => (p.state === 'waiting' && p.id === event.subject.id
      ? { state: 'done', ms: Math.round(performance.now() - p.since) } : p))
  })

  useEffect(() => {
    if (probe.state !== 'waiting') return
    const timer = setTimeout(() => setProbe({ state: 'failed', message: 'Событие не пришло за 10 секунд' }), 10_000)
    return () => clearTimeout(timer)
  }, [probe.state])

  const run = async () => {
    const since = performance.now()
    early.current.clear()
    setProbe({ state: 'waiting', id: null, since })
    try {
      const note = await createNote(`проверка ${new Date().toLocaleTimeString('ru')}`)
      setProbe(p => (p.state !== 'waiting' ? p : early.current.has(note.id)
        ? { state: 'done', ms: Math.round(performance.now() - since) } : { ...p, id: note.id }))
    } catch (e) {
      setProbe({ state: 'failed', message: e instanceof Error ? e.message : 'Запрос не выполнен' })
    }
  }

  return (
    <div>
      <h2 className="text-base font-semibold">Доставка событий</h2>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
        Проверка создаёт запись в сервисе-образце. Сервис публикует событие, оно проходит через шину и шлюз и
        возвращается в браузер.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button onClick={run} disabled={probe.state === 'waiting'}
          hint="Создать запись в сервисе-образце и замерить, за сколько её событие вернётся в браузер; ждём до 10 секунд"><Send className="size-4" /> Проверить</Button>
        <span className="text-sm" data-testid="stream-state">
          Поток событий: {connected
            ? <Tip label="Браузер получает события сервера: списки на страницах обновляются сами"><Badge variant="success">подключён</Badge></Tip>
            : <Tip label="События сервера не доходят: чужие изменения появятся только после обновления страницы"><Badge variant="warning">нет связи</Badge></Tip>}
        </span>
        <span className="text-sm" role="status" data-testid="delivery">
          {probe.state === 'waiting' && 'Ждём событие…'}
          {probe.state === 'done' && `Событие получено за ${probe.ms} мс`}
          {probe.state === 'failed' && <span className="text-destructive">{probe.message}</span>}
        </span>
      </div>
    </div>
  )
}
