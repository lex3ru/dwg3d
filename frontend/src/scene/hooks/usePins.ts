import { useState } from 'react'
import { batchRows, type Job, type Pin, type RowOp, type V3, type ViewSettings } from '../api'
import { conflictText } from '../furniture/sync'
import { canEdit, READ_ONLY } from '../session'

type Kind = 'markers' | 'comments'

/** Markers and comments: one server row each; the editor of a new pin and the open pin popup. */
export function usePins(p: {
  shown: Job | null
  view: ViewSettings
  setView: (f: (v: ViewSettings) => ViewSettings) => void
  rebuilding: boolean
  reload: () => void
  onDone: () => void          // a pin was committed: leave the pin tool
}) {
  const { shown, view, setView } = p
  const [openPin, setOpenPin] = useState<string | null>(null)
  const [pending, setPending] = useState<{ kind: Kind; pos: V3; floor: string } | null>(null)
  const [pendingText, setPendingText] = useState('')

  const savePin = async (kind: Kind, op: RowOp, local: Pin[]) => {
    if (!shown) return
    if (!canEdit()) {
      alert(READ_ONLY)
      return
    }
    if (p.rebuilding) {
      alert('Идёт перестроение модели: метки и комментарии можно менять после него')
      return
    }
    setView((v) => ({ ...v, [kind]: local }))
    try {
      const res = await batchRows<Pin>(shown.id, 'pins', shown.build, [op])
      setView((v) => ({
        ...v,
        [kind]: (v[kind] ?? []).filter((x) => !res.deleted.includes(x.id))
          .map((x) => res.items.find((y) => y.id === x.id) ?? x),
      }))
    } catch (e) {
      alert(conflictText(e, (id) => (view[kind] ?? []).find((x) => x.id === id)?.text || 'Метка'))
      p.reload()            // the server's view wins
    }
  }
  const commitPending = () => {
    if (!pending) return
    const text = pendingText.trim()
    const pin: Pin = {
      id: Math.random().toString(36).slice(2, 10), floor: pending.floor, pos: pending.pos, text,
      label: pending.kind === 'markers' ? text.slice(0, 8) : '', created: Date.now() / 1000,
    }
    savePin(pending.kind, { op: 'create', kind: pending.kind, ...pin }, [...(view[pending.kind] ?? []), pin])
    setPending(null)
    setPendingText('')
    p.onDone()
  }
  const deletePin = (kind: Kind, id: string) => {
    const pin = (view[kind] ?? []).find((x) => x.id === id)
    if (pin) savePin(kind, { op: 'delete', id, version: pin.version }, (view[kind] ?? []).filter((x) => x.id !== id))
    setOpenPin(null)
  }
  const startPin = (kind: Kind, pos: V3, floor: string) => {
    setPending({ kind, pos, floor })
    setPendingText('')
  }
  return { openPin, setOpenPin, pending, setPending, pendingText, setPendingText, commitPending, deletePin, startPin }
}
