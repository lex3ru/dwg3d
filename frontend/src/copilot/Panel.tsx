import { Bot, History, Plus, Send, Square, Trash2, Wrench, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  askCopilot, createCopilotChat, deleteCopilotChat, getCopilotChat, listCopilotChats,
  type CopilotChat, type CopilotEvent, type CopilotItem, type CopilotStatus, type CopilotUI,
} from '../api'
import { Button } from '../components/ui/button'
import { Tip } from '../components/ui/tooltip'
import { cn } from '../lib/utils'
import { hrefOf } from './links'
import { Answer } from './render'

const TOOL_LABEL: Record<string, string> = {
  buildings: 'здания', building_overview: 'обзор здания', find_rooms: 'поиск помещений', room: 'помещение',
  find_assets: 'поиск объектов', asset: 'карточка объекта', search_catalog: 'каталог', type_schema: 'схема свойств',
  people: 'люди', person: 'человек', grants: 'права', my_rights: 'мои права', journal: 'журнал', variants: 'варианты',
  compare_variants: 'сравнение вариантов', variant: 'вариант', report_link: 'отчёт', show: 'показать',
}
const EXAMPLES = ['Что в этом помещении требует внимания?', 'Сколько объектов на этаже и в каком они состоянии?',
  'У кого истекает гарантия в этом месяце?', 'Кто отвечает за принтеры?']

type Shown = Exclude<CopilotItem, { type: 'assistant' }> | { type: 'assistant'; text: string; live?: boolean }

/** The button in the corner of every screen that opens the copilot. */
export function CopilotButton({ onOpen }: { onOpen: () => void }) {
  return (
    <Button className="fixed right-4 bottom-16 z-40 shadow-lg md:bottom-4" onClick={onOpen} data-testid="copilot-open"
      hint="Открыть помощника: спросить о здании, помещениях, объектах и людях; он отвечает по вашим данным и правам">
      <Bot className="size-4" /> Помощник
    </Button>
  )
}

/**
 * The copilot's pane: a chat beside the screen (a column on the right; the whole screen on a phone), aware of
 * what is open. Answers stream; what the copilot shows (`ui`) opens in place.
 */
export function CopilotPane({ ui, building, status, onClose }: { ui: CopilotUI; building: string | null; status: CopilotStatus; onClose: () => void }) {
  return <Chat ui={ui} building={building} status={status} onClose={onClose} />
}

function Chat({ ui, building, status, onClose }: { ui: CopilotUI; building: string | null; status: CopilotStatus; onClose: () => void }) {
  const [chat, setChat] = useState<string | null>(() => sessionStorage.getItem('twin.copilot.chat'))
  const [items, setItems] = useState<Shown[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState<null | 'думаю…' | string>(null)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<CopilotChat[] | null>(null)
  const [used, setUsed] = useState(status.used_today)
  const abort = useRef<AbortController | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const uiRef = useRef(ui)
  useEffect(() => { uiRef.current = ui }, [ui])

  // an earlier chat of this tab comes back with its messages
  useEffect(() => {
    if (!chat) return
    getCopilotChat(chat).then(c => setItems(c.items), () => { setChat(null); setItems([]) })
  }, [chat])
  useEffect(() => { if (chat) sessionStorage.setItem('twin.copilot.chat', chat); else sessionStorage.removeItem('twin.copilot.chat') }, [chat])
  useEffect(() => { bottom.current?.scrollIntoView({ block: 'end' }) }, [items, busy])

  const onEvent = useCallback((e: CopilotEvent) => {
    if (e.type === 'chat' || e.type === 'done') return
    if (e.type === 'thinking') { setBusy(`модель рассуждает… (${e.chars} зн.)`); return }
    if (e.type === 'text') {
      setBusy('думаю…')
      setItems(list => {
        const last = list[list.length - 1]
        if (last && last.type === 'assistant' && last.live) return [...list.slice(0, -1), { ...last, text: last.text + e.text }]
        return [...list, { type: 'assistant', text: e.text, live: true }]
      })
      return
    }
    if (e.type === 'ui') {
      const href = hrefOf(e.href, building) ?? e.href
      if (href.startsWith('#/')) location.hash = href.slice(1)
    }
    setItems(list => [...list.map(x => x.type === 'assistant' ? { ...x, live: false } : x), e])
    if (e.type === 'tool') setBusy('думаю…')
  }, [building])

  const send = async (question?: string) => {
    const q = (question ?? text).trim()
    if (!q || busy) return
    setError(null)
    setText('')
    setBusy('думаю…')
    setItems(list => [...list, { type: 'user', text: q }])
    const controller = new AbortController()
    abort.current = controller
    try {
      let id = chat
      if (!id) {
        id = (await createCopilotChat(building)).id
        setChat(id)
      }
      await askCopilot(id, q, uiRef.current, onEvent, controller.signal)
      setUsed(n => n + 1)
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) setError(e instanceof Error ? e.message : 'Запрос не выполнен')
    } finally {
      setItems(list => list.map(x => x.type === 'assistant' ? { ...x, live: false } : x))
      setBusy(null)
      abort.current = null
    }
  }
  const stop = () => abort.current?.abort()
  const fresh = () => { if (busy) stop(); setChat(null); setItems([]); setHistory(null); setError(null) }
  const showHistory = () => {
    if (history) { setHistory(null); return }
    listCopilotChats(building).then(setHistory, () => setHistory([]))
  }
  const remove = (id: string) => deleteCopilotChat(id).then(() => {
    setHistory(h => h?.filter(c => c.id !== id) ?? null)
    if (id === chat) fresh()
  }, (e: Error) => setError(e.message))

  return (
    <aside data-testid="copilot" aria-label="Помощник"
      className="flex w-[400px] shrink-0 flex-col border-l bg-card max-md:fixed max-md:inset-0 max-md:z-40 max-md:w-full max-md:border-l-0">
      <header className="flex items-center gap-2 border-b px-3 py-2">
        <Bot className="size-4 text-primary" />
        <div className="min-w-0 flex-1 leading-tight">
          <div className="text-sm font-medium">Помощник</div>
          <div className="truncate text-xs text-muted-foreground">
            {status.model}{status.daily_limit > 0 && ` · сегодня ${used} из ${status.daily_limit}`}
          </div>
        </div>
        <Button variant="ghost" size="icon" aria-label="Беседы" hint="Прежние беседы в этом здании: открыть или удалить" onClick={showHistory}><History className="size-4" /></Button>
        <Button variant="ghost" size="icon" aria-label="Новая беседа" hint="Начать с чистого листа; текущая беседа останется в списке" onClick={fresh}><Plus className="size-4" /></Button>
        <Button variant="ghost" size="icon" aria-label="Закрыть" hint="Свернуть помощника; беседа сохранится" onClick={onClose}><X className="size-4" /></Button>
      </header>
      {history && (
        <ul className="max-h-48 overflow-y-auto border-b text-sm" data-testid="copilot-chats">
          {history.length === 0 && <li className="px-3 py-2 text-muted-foreground">Бесед ещё нет</li>}
          {history.map(c => (
            <li key={c.id} className={cn('flex items-center gap-1 px-2 py-1 hover:bg-secondary', c.id === chat && 'bg-accent')}>
              <button className="min-w-0 flex-1 truncate text-left" onClick={() => { setChat(c.id); setHistory(null) }}>{c.title}</button>
              <Button variant="ghost" size="icon" className="size-7" aria-label="Удалить беседу" hint="Удалить беседу навсегда" onClick={() => remove(c.id)}><Trash2 className="size-3.5" /></Button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3" data-testid="copilot-items">
        {items.length === 0 && (
          <div className="space-y-2 text-sm text-muted-foreground">
            <p>Спросите о здании, помещениях, объектах, людях или правах — отвечу по данным, которые видны вам.{status.can_propose && ' Изменения предложу, применять будете вы.'}</p>
            <div className="flex flex-wrap gap-1.5">
              {EXAMPLES.map(ex => <button key={ex} onClick={() => send(ex)} className="rounded-full border px-2.5 py-1 text-xs hover:bg-secondary">{ex}</button>)}
            </div>
          </div>
        )}
        {items.map((it, i) => <Item key={i} item={it} building={building} />)}
        {busy && <p className="text-xs text-muted-foreground" data-testid="copilot-busy">{busy}</p>}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <div ref={bottom} />
      </div>
      <form className="flex items-end gap-2 border-t p-2" onSubmit={e => { e.preventDefault(); void send() }}>
        <textarea value={text} onChange={e => setText(e.target.value)} rows={2} maxLength={8000} aria-label="Вопрос помощнику"
          placeholder="Спросить… (Enter — отправить, Shift+Enter — новая строка)"
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send() } }}
          className="min-h-9 flex-1 resize-none rounded-md border bg-background px-2 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        {busy
          ? <Button type="button" variant="outline" size="icon" aria-label="Остановить" hint="Прервать ответ; сказанное останется" onClick={stop}><Square className="size-4" /></Button>
          : <Button type="submit" size="icon" aria-label="Отправить" disabled={!text.trim()} hint="Отправить вопрос помощнику"><Send className="size-4" /></Button>}
      </form>
    </aside>
  )
}

function Item({ item, building }: { item: Shown; building: string | null }) {
  if (item.type === 'user') {
    return <div className="ml-8 rounded-lg bg-primary px-3 py-2 text-sm whitespace-pre-wrap text-primary-foreground">{item.text}</div>
  }
  if (item.type === 'assistant') return <div className="mr-4"><Answer text={item.text} building={building} /></div>
  if (item.type === 'tool') {
    return (
      <Tip label={item.error ? `Ошибка: ${item.error}` : `Инструмент ${item.name}`} side="left">
        <div className={cn('flex items-center gap-1.5 text-xs text-muted-foreground', item.error && 'text-destructive')} data-testid="copilot-tool">
          <Wrench className="size-3" /> {TOOL_LABEL[item.name] ?? item.name}{item.error && ' — ошибка'}
        </div>
      </Tip>
    )
  }
  if (item.type === 'ui') {
    const href = hrefOf(item.href, building) ?? item.href
    return <a href={href} className="block text-xs text-primary underline underline-offset-2">Показано: {item.label || 'на экране'}</a>
  }
  if (item.type === 'error') return <p role="alert" className="text-sm text-destructive">{item.message}</p>
  if (item.type === 'proposal') return <div className="rounded-md border px-3 py-2 text-sm">Предложение: {String((item.proposal as { summary?: string }).summary ?? '')}</div>
  return null
}
