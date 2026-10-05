import { Bot, Check, ChevronDown, ChevronUp, Eye, EyeOff, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  applyProposal, getProposal, listProposals, rejectProposal, type PlacedItem, type Proposal, type ProposalFull, type ProposalLayerOp, type ShapeObject,
} from '@/api'
import { useConfirm } from '@/components/confirm'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { catalogItem } from '../furniture/catalog'
import { MARK_COLOR } from '../viewer/Furniture'

type Row = PlacedItem | ShapeObject

const rowName = (r: Row) => ('item' in r && r.item ? catalogItem(r.item).name : ('props' in r && (r.props?.name as string)) || 'линия или зона')

/** What a proposal does, line by line (a few of each). */
function layerOpText(o: ProposalLayerOp): string {
  if (o.op === 'create_layer') return `новый слой «${o.name}»`
  if (o.op === 'copy_layer') return `вариант «${o.name}» — копия «${o.of}» (${o.objects ?? 0} об.)`
  if (o.op === 'delete_layer') return `удалить слой «${o.name}» (${o.objects ?? 0} об.)`
  const c = o.changes ?? {}
  return [c.name != null && `переименовать в «${c.name}»`, c.visible != null && (c.visible ? 'показать' : 'скрыть')]
    .filter(Boolean).join(', ').replace(/^/, `слой «${o.name}»: `) || `слой «${o.name}»: без изменений`
}

function Changes({ p }: { p: ProposalFull }) {
  const lines = [
    ...(p.preview.layers ?? []).map((o) => ({ c: o.op === 'delete_layer' ? MARK_COLOR.removed : MARK_COLOR.changed, t: `▤ ${layerOpText(o)}` })),
    ...p.preview.created.map((r) => ({ c: MARK_COLOR.new, t: `+ ${rowName(r)}` })),
    ...p.preview.updated.map((u) => ({ c: MARK_COLOR.changed, t: `~ ${rowName(u.after)}` })),
    ...p.preview.deleted.map((r) => ({ c: MARK_COLOR.removed, t: `− ${rowName(r)}` })),
  ]
  return (
    <ul className="m-0 grid list-none gap-0.5 p-0 text-xs">
      {lines.slice(0, 10).map((l, i) => <li key={i} style={{ color: l.c }}>{l.t}</li>)}
      {lines.length > 10 && <li className="text-muted-foreground">и ещё {lines.length - 10}</li>}
    </ul>
  )
}

/**
 * Changes proposed by the copilot on this drawing: shown on the plan (new, changed, to be removed —
 * outlined), applied by an editor as their own change, or rejected with a reason for the copilot.
 */
export default function Proposals({ projectId, drawingId, nonce, editable, preview, onPreview, shifted }: {
  projectId: string
  drawingId: string
  /** changes elsewhere: read the list again */
  nonce: number
  editable: boolean
  preview: ProposalFull | null
  onPreview: (p: ProposalFull | null) => void
  /** the copilot's panel is open on the right: stand left of it */
  shifted?: boolean
}) {
  const [list, setList] = useState<Proposal[]>([])
  const [open, setOpen] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [rejecting, setRejecting] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [ask, dialog] = useConfirm()
  useEffect(() => {
    let alive = true
    listProposals(projectId, { status: 'open', drawing: drawingId })
      .then((x) => { if (alive) setList(x) }).catch(() => {})
    return () => { alive = false }
  }, [projectId, drawingId, nonce])
  // the previewed one was decided (here or elsewhere), or changed: look again
  useEffect(() => {
    if (!preview) return
    if (!list.some((x) => x.id === preview.id)) { onPreview(null); return }
    getProposal(preview.id).then((x) => onPreview(x.status === 'open' ? x : null)).catch(() => onPreview(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list, nonce])
  if (!list.length) return null

  const run = async (id: string, fn: () => Promise<unknown>) => {
    setBusy(id)
    setErr(null)
    try { await fn() } catch (e) { setErr((e as Error).message) }
    setBusy(null)
    if (preview?.id === id) onPreview(null)
    listProposals(projectId, { status: 'open', drawing: drawingId }).then(setList).catch(() => {})
  }
  const show = async (p: Proposal) => {
    if (preview?.id === p.id) { onPreview(null); return }
    setErr(null)
    try {
      const full = await getProposal(p.id)
      if (full.status !== 'open') setErr(`Предложение ${full.status_name}${full.reason ? `: ${full.reason}` : ''}`)
      onPreview(full.status === 'open' ? full : null)
    } catch (e) { setErr((e as Error).message) }
  }
  return (
    <div className={`fixed top-28 z-40 w-80 ${shifted ? 'right-[432px] max-[900px]:hidden' : 'right-4'}`}>
      <div className="max-w-[calc(100vw-32px)] rounded-lg border border-border bg-card text-card-foreground shadow-lg">
      <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-medium" onClick={() => setOpen(!open)}>
        <Bot className="size-4 text-primary" />
        <span className="flex-1">Предложения копилота: {list.length}</span>
        {open ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
      </button>
      {open && (
        <div className="grid max-h-[60vh] gap-2 overflow-y-auto border-t border-border p-2">
          {err && <p className="m-0 text-xs text-destructive">{err}</p>}
          {list.map((p) => {
            const on = preview?.id === p.id
            const n = p.counts
            return (
              <div key={p.id} className={`grid gap-1.5 rounded-md p-2 ${on ? 'bg-accent' : 'hover:bg-secondary/60'}`}>
                <div className="text-sm">{p.summary}</div>
                <div className="text-xs text-muted-foreground">
                  {p.agent || 'Копилот'}{p.user ? ` · для ${p.user.name || p.user.login}` : ''}
                  {' · '}
                  <span style={{ color: MARK_COLOR.new }}>+{n.create}</span>{' '}
                  <span style={{ color: MARK_COLOR.changed }}>~{n.update}</span>{' '}
                  <span style={{ color: MARK_COLOR.removed }}>−{n.delete}</span>
                  {!!n.layers && <span>{' · '}слоёв: {n.layers}</span>}
                </div>
                {on && preview && <Changes p={preview} />}
                {rejecting === p.id ? (
                  <form className="flex gap-1.5" onSubmit={(e) => {
                    e.preventDefault()
                    run(p.id, () => rejectProposal(p.id, reason.trim()))
                    setRejecting(null)
                  }}>
                    <Input autoFocus className="h-8 text-xs" value={reason} placeholder="Причина — увидит копилот" maxLength={2000}
                      onChange={(e) => setReason(e.target.value)} />
                    <Button size="sm" variant="destructive" disabled={busy === p.id}>Отклонить</Button>
                    <Button size="sm" type="button" variant="ghost" onClick={() => setRejecting(null)}>Отмена</Button>
                  </form>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    <Button size="sm" variant="secondary" onClick={() => show(p)}>{on ? <EyeOff /> : <Eye />} {on ? 'Скрыть' : 'Показать'}</Button>
                    {editable && (
                      <>
                        <Button size="sm" disabled={busy === p.id} onClick={async () => {
                          const total = n.create + n.update + n.delete + (n.layers ?? 0)
                          if (await ask({ title: 'Применить предложение?', text: `${p.summary}\n\nИзменений: ${total}. В журнале они будут записаны от вашего имени с пометкой копилота.`, confirm: 'Применить' })) {
                            run(p.id, () => applyProposal(p.id))
                          }
                        }}><Check /> Применить</Button>
                        <Button size="sm" variant="ghost" className="text-destructive" onClick={() => { setRejecting(p.id); setReason('') }}><X /> Отклонить</Button>
                      </>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
      </div>
      {dialog}
    </div>
  )
}
