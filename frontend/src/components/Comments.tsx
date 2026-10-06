import { MessageSquare } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { addComment, deleteComment, listComments, resolveComment, type Comment, type CommentTarget, type Me } from '../api'
import { useEvents } from '../stream'
import { Button } from './ui/button'

/** Comments to a room or an object: whoever sees the target reads and writes; the author or the building's
 * administrator closes. Point comments live on the plan (Plan.tsx) and share this list's rendering. */
export function Comments({ me, building, target_kind, target_id, admin }: {
  me: Me; building: string; target_kind: CommentTarget; target_id: string; admin: boolean
}) {
  const [items, setItems] = useState<Comment[]>([])
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => {
    listComments({ building_id: building, target_kind, target_id }).then(setItems, () => setItems([]))
  }, [building, target_kind, target_id])
  useEffect(load, [load])
  useEvents(event => { if (event.type.startsWith('buildings.comment.')) load() })
  const send = (e: React.FormEvent) => {
    e.preventDefault()
    if (!text.trim()) return
    addComment({ building_id: building, target_kind, target_id, body: text.trim() })
      .then(() => { setText(''); setError(null); load() }, (ex: Error) => setError(ex.message))
  }
  return (
    <div data-testid="comments">
      <h3 className="flex items-center gap-1.5 font-medium"><MessageSquare className="size-4" /> Комментарии{items.length > 0 && ` · ${items.length}`}</h3>
      <CommentList items={items} me={me} admin={admin} onChanged={load} onError={setError} />
      <form onSubmit={send} className="mt-2 flex gap-2">
        <input value={text} onChange={e => setText(e.target.value)} aria-label="Новый комментарий" placeholder="Написать…" maxLength={4000}
          className="h-8 min-w-0 flex-1 rounded-md border bg-card px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        <Button type="submit" size="sm" variant="outline" disabled={!text.trim()}>Оставить</Button>
      </form>
      {error && <p role="alert" className="mt-1 text-sm text-destructive">{error}</p>}
    </div>
  )
}

export function CommentList({ items, me, admin, onChanged, onError, chosen }: {
  items: Comment[]; me: Me; admin: boolean; onChanged: () => void; onError: (m: string | null) => void; chosen?: string
}) {
  const mine = (c: Comment) => c.author.sub === me.user.sub
  const act = (work: Promise<unknown>) => work.then(() => { onError(null); onChanged() }, (ex: Error) => onError(ex.message))
  if (items.length === 0) return <p className="mt-1 text-sm text-muted-foreground">Комментариев нет.</p>
  return (
    <ul className="mt-1 grid gap-1.5">
      {items.map(c => (
        <li key={c.id} data-comment={c.id} className={`rounded-md border px-2 py-1.5 text-sm ${c.id === chosen ? 'border-primary' : ''}`}>
          <div className="whitespace-pre-wrap">{c.body}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
            <span>{c.author.name || 'кто-то'} · {new Date(c.created_at).toLocaleString('ru')}</span>
            {(mine(c) || admin) && !c.resolved_at && (
              <>
                <button type="button" className="text-primary" onClick={() => act(resolveComment(c.id))}>Закрыть</button>
                <button type="button" className="text-primary" onClick={() => act(deleteComment(c.id))}>Удалить</button>
              </>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}
