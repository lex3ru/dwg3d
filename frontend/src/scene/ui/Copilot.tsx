import { Bot, Check, Eye, History, Loader2, Plus, Send, Square, Trash2, Wrench, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import {
  applyProposal, askCopilot, deleteCopilotChat, getCopilotChat, getProposal, listCopilotChats,
  type CopilotItem, type CopilotProposal, type CopilotStatus, type ProposalFull, type UIContext,
} from '@/scene/api'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Tip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { MARK_COLOR } from '../viewer/Furniture'

/** what the copilot is doing, in words */
const TOOL_LABEL: Record<string, string> = {
  project_overview: 'смотрю проект', list_rooms: 'смотрю помещения', layer_kinds: 'смотрю типы слоёв',
  search_catalog: 'ищу в каталоге', query_objects: 'ищу объекты', get_object: 'смотрю объект', report: 'считаю спецификацию',
  recent_changes: 'смотрю журнал', proposal_status: 'проверяю предложение', propose_changes: 'готовлю предложение',
  place_in_room: 'подбираю места', place_row: 'рассчитываю ряд', camera_coverage: 'считаю обзор камер',
  get_ui_context: 'смотрю, что открыто', show_in_viewer: 'показываю на плане', compare_variants: 'сравниваю варианты',
  list_comments: 'читаю комментарии', add_comment: 'оставляю комментарий',
  place_in_rooms: 'расставляю по помещениям', place_detectors: 'считаю извещатели', check_project: 'проверяю проект',
  plan_route: 'прокладываю маршрут',
}

const EXAMPLES = ['Проверь этот этаж', 'Где камеры не видят помещения?', 'Добавь пожарные извещатели, где не хватает', 'Сделай вариант мебели и сравни с текущим']

function ProposalCard({ p, editable, onPreview }: { p: CopilotProposal; editable: boolean; onPreview: (p: ProposalFull | null) => void }) {
  const [state, setState] = useState<string | null>(null)
  const n = p.counts
  return (
    <div className="grid gap-1.5 rounded-lg border border-border bg-card p-2 text-sm">
      <div className="text-xs text-muted-foreground">Предложение</div>
      <div>{p.summary}</div>
      {n && (
        <div className="text-xs">
          <span style={{ color: MARK_COLOR.new }}>+{n.create}</span>{' '}
          <span style={{ color: MARK_COLOR.changed }}>~{n.update}</span>{' '}
          <span style={{ color: MARK_COLOR.removed }}>−{n.delete}</span>
          {!!n.layers && <span>{' · '}слоёв: {n.layers}</span>}
        </div>
      )}
      {state ? <div className="text-xs text-muted-foreground">{state}</div> : (
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" variant="secondary" hint="Показать на плане результат: новое, изменённое и удаляемое обведено цветом" onClick={async () => {
            try {
              const full = await getProposal(p.id)
              if (full.status === 'open') onPreview(full)
              else setState(`Предложение ${full.status_name}${full.reason ? `: ${full.reason}` : ''}`)
            } catch (e) { setState((e as Error).message) }
          }}><Eye /> Показать</Button>
          {editable && (
            <Button size="sm" hint="Внести изменения сразу, без подтверждения, от вашего имени с пометкой копилота" onClick={async () => {
              try { await applyProposal(p.id); setState('Применено'); onPreview(null) } catch (e) { setState((e as Error).message) }
            }}><Check /> Применить</Button>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * The copilot's chat: questions about the project, answers streamed as they come,
 * the tools it uses, its proposals (shown on the plan, applied in one click).
 * Each message carries what this window shows, so "here" and "this" make sense.
 */
export default function Copilot({ projectId, status, ui, editable, onPreview, onClose }: {
  projectId: string
  status: CopilotStatus
  ui: Omit<UIContext, 'client'> & { client?: string }
  editable: boolean
  onPreview: (p: ProposalFull | null) => void
  onClose: () => void
}) {
  const [items, setItems] = useState<CopilotItem[]>([])
  const [chat, setChat] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [thinking, setThinking] = useState(0)
  const [history, setHistory] = useState<{ id: string; title: string }[] | null>(null)
  const abort = useRef<AbortController | null>(null)
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [items])
  useEffect(() => () => abort.current?.abort(), [])

  const send = async (msg: string) => {
    msg = msg.trim()
    if (!msg || busy) return
    setText('')
    setBusy(true)
    setItems((x) => [...x, { type: 'user', text: msg }])
    const ctl = new AbortController()
    abort.current = ctl
    try {
      await askCopilot(projectId, { message: msg, chat, ui }, (ev) => {
        if (ev.type === 'chat') setChat(ev.id)
        else if (ev.type === 'thinking') setThinking(ev.chars)
        else if (ev.type === 'text') {
          setThinking(0)
          setItems((x) => {
            const last = x[x.length - 1]
            return last?.type === 'assistant' ? [...x.slice(0, -1), { ...last, text: last.text + ev.text }] : [...x, { type: 'assistant', text: ev.text }]
          })
        } else if (ev.type === 'tool' || ev.type === 'proposal' || ev.type === 'error') { setThinking(0); setItems((x) => [...x, ev]) }
      }, ctl.signal)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setItems((x) => [...x, { type: 'error', message: (e as Error).message }])
    }
    abort.current = null
    setThinking(0)
    setBusy(false)
  }
  const open = async (id: string) => {
    setHistory(null)
    try {
      const c = await getCopilotChat(projectId, id)
      setChat(c.id)
      setItems(c.items)
    } catch (e) { setItems([{ type: 'error', message: (e as Error).message }]) }
  }
  const fresh = () => { abort.current?.abort(); setChat(null); setItems([]); setHistory(null) }

  return (
    <div className="fixed right-4 bottom-12 z-40 flex h-[min(640px,calc(100vh-140px))] w-[400px] max-w-[calc(100vw-32px)] flex-col rounded-xl border border-border bg-card text-card-foreground shadow-xl">
      <div className="flex items-center gap-1 border-b border-border px-3 py-2">
        <Bot className="size-4 text-primary" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">Копилот</div>
          <div className="truncate text-xs text-muted-foreground">
            {status.model}{status.daily_limit ? ` · сегодня ${status.used_today} из ${status.daily_limit}` : ''}
          </div>
        </div>
        <Button size="icon" variant="ghost" aria-label="Прошлые разговоры"
          hint={history ? 'Вернуться к текущему разговору' : 'Разговоры с копилотом по этому проекту: открыть и продолжить или удалить'} onClick={async () => {
          setHistory(history ? null : await listCopilotChats(projectId).catch(() => []))
        }}><History /></Button>
        <Button size="icon" variant="ghost" aria-label="Новый разговор" hint="Начать с чистого листа; этот останется в прошлых разговорах" onClick={fresh}><Plus /></Button>
        <Button size="icon" variant="ghost" aria-label="Закрыть" hint="Свернуть панель в кнопку; разговор останется в прошлых" onClick={onClose}><X /></Button>
      </div>
      {history ? (
        <div className="grid flex-1 content-start gap-1 overflow-y-auto p-2">
          {!history.length && <p className="m-2 text-sm text-muted-foreground">Разговоров пока нет.</p>}
          {history.map((h) => (
            <div key={h.id} className="flex items-center gap-1 rounded-md hover:bg-secondary/60">
              <Tip label="Открыть разговор и продолжить с того места" side="left">
                <button type="button" className="min-w-0 flex-1 truncate px-2 py-1.5 text-left text-sm" onClick={() => open(h.id)}>{h.title || 'Без названия'}</button>
              </Tip>
              <Button size="icon" variant="ghost" aria-label="Удалить" hint="Удалить разговор сразу, без подтверждения" onClick={async () => {
                await deleteCopilotChat(projectId, h.id).catch(() => {})
                setHistory((x) => (x ?? []).filter((y) => y.id !== h.id))
                if (chat === h.id) fresh()
              }}><Trash2 /></Button>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-3">
          {!items.length && (
            <div className="grid gap-2 text-sm text-muted-foreground">
              <p className="m-0">Спросите о проекте или попросите что-то сделать. «Здесь» и «это» — то, что открыто и выделено на экране.</p>
              <div className="flex flex-wrap gap-1.5">
                {EXAMPLES.map((x) => (
                  <Tip key={x} label="Отправить этот вопрос копилоту сразу">
                    <button type="button" className="rounded-full border border-border px-2.5 py-1 text-xs hover:bg-secondary" onClick={() => send(x)}>{x}</button>
                  </Tip>
                ))}
              </div>
            </div>
          )}
          <div className="grid gap-2">
            {items.map((it, i) => {
              if (it.type === 'user') return <div key={i} className="ml-8 rounded-lg bg-primary px-3 py-2 text-sm whitespace-pre-wrap text-primary-foreground">{it.text}</div>
              if (it.type === 'assistant') return <div key={i} className="mr-4 text-sm whitespace-pre-wrap">{it.text}</div>
              if (it.type === 'tool') {
                return (
                  <div key={i} className={cn('flex items-center gap-1.5 text-xs', it.error ? 'text-destructive' : 'text-muted-foreground')} title={it.error}>
                    <Wrench className="size-3" /> {TOOL_LABEL[it.name] ?? it.name}{it.error ? ' — ошибка' : ''}
                  </div>
                )
              }
              if (it.type === 'proposal') return <ProposalCard key={i} p={it.proposal} editable={editable} onPreview={onPreview} />
              return <div key={i} className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">{it.message}</div>
            })}
            {busy && <div className="flex items-center gap-1.5 text-xs text-muted-foreground"><Loader2 className="size-3 animate-spin" /> {thinking ? `модель рассуждает… (${thinking} симв.)` : 'думаю…'}</div>}
            <div ref={end} />
          </div>
        </div>
      )}
      <form className="flex items-end gap-2 border-t border-border p-2" onSubmit={(e) => { e.preventDefault(); send(text) }}>
        <Tip label="Enter — отправить, Shift+Enter — новая строка">
          <Textarea rows={2} className="min-h-0 flex-1 resize-none text-sm" value={text} placeholder="Сообщение копилоту…"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(text) } e.stopPropagation() }} />
        </Tip>
        {busy
          ? <Button type="button" size="icon" variant="secondary" aria-label="Остановить" hint="Прервать ответ модели; уже написанное останется" onClick={() => abort.current?.abort()}><Square /></Button>
          : <Button size="icon" aria-label="Отправить" hint={text.trim() ? 'Спросить копилота (Enter); он видит, что открыто и выделено на экране' : 'Сначала напишите сообщение'} disabled={!text.trim()}><Send /></Button>}
      </form>
    </div>
  )
}
