/**
 * The sketch being edited: its undo history and the draft kept in this browser
 * until plans are stored on the server.
 */
import { useCallback, useEffect, useState } from 'react'
import { emptyFloor, emptySketch, parseSketch, type Floor, type Sketch } from '@/plan'

const DRAFT_KEY = 'twin.sketch.draft.v1'
const DEPTH = 200

function loadDraft(): Sketch {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    if (raw) return parseSketch(JSON.parse(raw))
  } catch { /* no storage, or a draft of another version: start afresh */ }
  return emptySketch()
}

function saveDraft(s: Sketch): boolean {
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(s))
    return true
  } catch {
    return false
  }
}

interface History { past: Sketch[]; present: Sketch; future: Sketch[] }

export interface SketchState {
  sketch: Sketch
  floor: Floor
  setFloorId: (id: string) => void
  /** replaces the current floor; one step of undo */
  commit: (f: Floor) => void
  undo: () => void
  redo: () => void
  canUndo: boolean
  canRedo: boolean
  addFloor: () => void
  removeFloor: (id: string) => void
  /** an empty plan (the old one stays in undo) */
  reset: () => void
  /** the draft could not be kept in this browser (storage off or full) */
  unsaved: boolean
}

export function useSketch(): SketchState {
  const [h, setH] = useState<History>(() => ({ past: [], present: loadDraft(), future: [] }))
  const [floorId, setFloorId] = useState(() => h.present.floors[0].id)
  const [unsaved, setUnsaved] = useState(false)
  const sketch = h.present
  const floor = sketch.floors.find(f => f.id === floorId) ?? sketch.floors[0]

  useEffect(() => {
    const t = setTimeout(() => setUnsaved(!saveDraft(sketch)), 400)
    return () => clearTimeout(t)
  }, [sketch])

  const push = useCallback((next: (s: Sketch) => Sketch) => {
    setH(x => {
      const n = next(x.present)
      return n === x.present ? x : { past: [...x.past.slice(-DEPTH + 1), x.present], present: n, future: [] }
    })
  }, [])

  const commit = useCallback((f: Floor) => {
    push(s => s.floors.includes(f) ? s : { ...s, floors: s.floors.map(x => (x.id === f.id ? f : x)) })
  }, [push])
  const undo = useCallback(() => setH(x => x.past.length
    ? { past: x.past.slice(0, -1), present: x.past[x.past.length - 1], future: [x.present, ...x.future] } : x), [])
  const redo = useCallback(() => setH(x => x.future.length
    ? { past: [...x.past, x.present], present: x.future[0], future: x.future.slice(1) } : x), [])

  const addFloor = useCallback(() => {
    const top = Math.max(...sketch.floors.map(f => f.level))
    const below = sketch.floors.find(f => f.level === top)!
    const f = emptyFloor(top + 1, { elevation: below.elevation + below.height })
    push(s => ({ ...s, floors: [...s.floors, f] }))
    setFloorId(f.id)
  }, [push, sketch.floors])
  const removeFloor = useCallback((id: string) => {
    if (sketch.floors.length < 2) return
    push(s => ({ ...s, floors: s.floors.filter(f => f.id !== id) }))
    if (id === floor.id) setFloorId(sketch.floors.find(f => f.id !== id)!.id)
  }, [push, sketch.floors, floor.id])
  const reset = useCallback(() => {
    const s = emptySketch()
    push(() => s)
    setFloorId(s.floors[0].id)
  }, [push])

  return {
    sketch, floor, setFloorId, commit, undo, redo, canUndo: h.past.length > 0, canRedo: h.future.length > 0,
    addFloor, removeFloor, reset, unsaved,
  }
}
