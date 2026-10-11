/**
 * The sketch being edited: loaded from the import service, its undo history,
 * and saving — a moment after each change, over the save the edits started
 * from. A save someone made meanwhile (another window) stops saving: the
 * editor offers to load theirs.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, getSketch, saveSketch } from '@/api'
import { bearingOnly, emptyFloor, parseSketch, SketchError, type Floor, type Sketch } from '@/plan'
import { Conflict, Saver } from './saver'

const DEPTH = 200
const SAVE_DELAY = 800

/** loading — not here yet; saved; unsaved — a save is coming; saving; conflict — saved elsewhere meanwhile;
 * failed — the server refused or is away (the next change tries again); broken — what is stored is not a plan */
export type SaveStatus = 'loading' | 'saved' | 'unsaved' | 'saving' | 'conflict' | 'failed' | 'broken'

interface History { past: Sketch[]; present: Sketch; future: Sketch[] }

export interface SketchState {
  status: SaveStatus
  error: string | null
  sketch: Sketch | null
  floor: Floor | null
  setFloorId: (id: string) => void
  /** replaces the current floor; one step of undo */
  commit: (f: Floor) => void
  undo: () => void
  redo: () => void
  canUndo: boolean
  canRedo: boolean
  /** a floor on top: with the bearing walls of the one under it, a copy of it whole, or empty */
  addFloor: (start?: 'bearing' | 'copy' | 'empty') => void
  removeFloor: (id: string) => void
  /** saves what is not saved yet; resolves when the server has it */
  flush: () => Promise<void>
  /** drops what is not saved and loads the plan as stored (after a conflict) */
  reload: () => void
}

export function useSketch(drawing: string): SketchState {
  const [h, setH] = useState<History | null>(null)
  const [floorId, setFloorId] = useState<string | null>(null)
  const [status, setStatus] = useState<SaveStatus>('loading')
  const [error, setError] = useState<string | null>(null)
  const [loads, setLoads] = useState(0)
  const timer = useRef<number | undefined>(undefined)
  const saver = useMemo(() => new Saver<Sketch>(
    (sketch, version) => saveSketch(drawing, sketch, version).then(r => r.version, (e: Error) => {
      throw e instanceof ApiError && e.code === 'conflict' ? new Conflict(e.message) : e
    }),
    (state, e) => { setStatus(state); setError(e?.message ?? null) },
  ), [drawing])

  useEffect(() => {
    let alive = true
    getSketch(drawing).then(r => {
      if (!alive) return
      const s = parseSketch(r.sketch)
      saver.reset(s, r.version)
      setH({ past: [], present: s, future: [] })
      setFloorId(id => (s.floors.some(f => f.id === id) ? id : s.floors[0].id))
      setStatus('saved')
      setError(null)
    }, (e: Error) => {
      if (!alive) return
      setStatus(e instanceof SketchError ? 'broken' : 'failed')
      setError(e.message)
    })
    return () => { alive = false }
  }, [drawing, loads, saver])

  const present = h?.present ?? null
  useEffect(() => {
    if (!present) return
    saver.change(present)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => { saver.save().catch(() => {}) }, SAVE_DELAY)
  }, [present, saver])

  // leaving with changes not saved: the browser asks first
  useEffect(() => {
    const leave = (e: BeforeUnloadEvent) => { if (saver.dirty) e.preventDefault() }
    addEventListener('beforeunload', leave)
    return () => removeEventListener('beforeunload', leave)
  }, [saver])

  const flush = useCallback(() => {
    window.clearTimeout(timer.current)
    return saver.save()
  }, [saver])
  const reload = useCallback(() => { setStatus('loading'); setLoads(n => n + 1) }, [])

  // a change: «не сохранено» until the save a moment later (a save running or a conflict says more)
  const changed = useCallback(() => setStatus(s => (s === 'saving' || s === 'conflict' ? s : 'unsaved')), [])
  const push = useCallback((next: (s: Sketch) => Sketch) => {
    if (!h) return
    const n = next(h.present)
    if (n === h.present) return
    changed()
    setH({ past: [...h.past.slice(-DEPTH + 1), h.present], present: n, future: [] })
  }, [h, changed])
  const commit = useCallback((f: Floor) => {
    push(s => s.floors.includes(f) ? s : { ...s, floors: s.floors.map(x => (x.id === f.id ? f : x)) })
  }, [push])
  const undo = useCallback(() => {
    if (!h?.past.length) return
    changed()
    setH({ past: h.past.slice(0, -1), present: h.past[h.past.length - 1], future: [h.present, ...h.future] })
  }, [h, changed])
  const redo = useCallback(() => {
    if (!h?.future.length) return
    changed()
    setH({ past: [...h.past, h.present], present: h.future[0], future: h.future.slice(1) })
  }, [h, changed])

  const floors = useMemo(() => present?.floors ?? [], [present])
  const floor = floors.find(f => f.id === floorId) ?? floors[0] ?? null
  const addFloor = useCallback((start: 'bearing' | 'copy' | 'empty' = 'bearing') => {
    if (!floors.length) return
    // the floor goes on top, starting from the floor under it
    const top = floors.reduce((a, b) => (b.level > a.level ? b : a))
    const from = start === 'copy' ? top : start === 'bearing' ? bearingOnly(top) : null
    const f = emptyFloor(top.level + 1, {
      elevation: top.elevation + top.height, height: top.height,
      ...(from ? { nodes: from.nodes, walls: from.walls, openings: from.openings, rooms: from.rooms } : {}),
    })
    push(s => ({ ...s, floors: [...s.floors, f] }))
    setFloorId(f.id)
  }, [push, floors])
  const removeFloor = useCallback((id: string) => {
    if (floors.length < 2) return
    push(s => ({ ...s, floors: s.floors.filter(f => f.id !== id) }))
    if (id === floor?.id) setFloorId(floors.find(f => f.id !== id)!.id)
  }, [push, floors, floor])

  return {
    status, error, sketch: present, floor, setFloorId, commit, undo, redo,
    canUndo: !!h?.past.length, canRedo: !!h?.future.length, addFloor, removeFloor, flush, reload,
  }
}
