/**
 * Bending a wall into an arc and back (model.ts `Curve`, arc.ts): the wall —
 * or the curved wall it is a face of — is laid again from end to end as faces
 * along the arc, or as one straight wall; its openings keep their place along
 * the wall and go into the face they fall on.
 */
import { arcLength, curveChain, curveJoints, defaultSegments, arcPoints, MAX_SEGMENTS } from './arc.ts'
import { draft, ends, openingsOf } from './graph.ts'
import { newId, type Floor, type Opening, type Wall } from './model.ts'
import { fitOpening } from './openings.ts'
import { dist } from './vec.ts'

/** The curve the wall is a face of, with its chain, or null for a straight wall. */
export function curveOf(f: Floor, wall: string) {
  const id = f.walls[wall]?.curve
  const curve = id ? f.curves?.[id] : undefined
  const chain = id ? curveChain(f, id) : null
  return id && curve && chain ? { id, curve, chain, joints: curveJoints(f, chain) } : null
}

/** The walls given, and with a face of a curved wall all its other faces: what is picked together. */
export function withCurves(f: Floor, walls: string[]): string[] {
  const curves = new Set(walls.map(w => f.walls[w]?.curve).filter(Boolean))
  if (!curves.size) return walls
  return [...new Set([...walls, ...Object.keys(f.walls).filter(w => curves.has(f.walls[w].curve))])]
}

/** The wall's length along its middle: the arc's for a curved one. */
export function curvedLength(f: Floor, wall: string): number {
  const c = curveOf(f, wall)
  if (!c) return f.walls[wall] ? dist(...ends(f, f.walls[wall])) : 0
  return arcLength(f.nodes[c.curve.a], f.nodes[c.curve.b], c.curve.bulge)
}

/**
 * The wall bent to stand `bulge` off its chord in `segments` faces (by default as many as the arc needs);
 * a bulge of 0 makes it straight again. `lost`: the openings no face had room for. null when the wall cannot be
 * bent: other walls meet it between its ends.
 */
export function bendWall(f: Floor, wall: string, bulge: number, segments?: number): { floor: Floor; wall: string; lost: number } | null {
  const w = f.walls[wall]
  if (!w) return null
  const c = curveOf(f, wall)
  if (w.curve && !c) return null
  if (c?.joints.length) return null
  const [a, b] = c ? [c.curve.a, c.curve.b] : [w.a, w.b]
  const walls = c ? c.chain.walls : [wall]
  const nodes = c ? c.chain.nodes : [w.a, w.b]
  const props: Omit<Wall, 'a' | 'b' | 'curve'> = { thickness: w.thickness, height: w.height, kind: w.kind }

  // the openings by where they are along the wall, 0..1 from a to b, as if looking from a to b
  const lengths = walls.map(id => dist(...ends(f, f.walls[id])))
  const total = lengths.reduce((s, l) => s + l, 0)
  const moved: { id: string; frac: number; op: Opening }[] = []
  let before = 0
  walls.forEach((id, i) => {
    const forward = f.walls[id].a === nodes[i]
    for (const o of openingsOf(f, id)) {
      const op = f.openings[o]
      const along = forward ? op.at : lengths[i] - op.at
      moved.push({
        id: o, frac: total > 0 ? (before + along) / total : 0.5,
        op: forward ? op : { ...op, hinge: op.hinge === 'a' ? 'b' : 'a', side: op.side === 'left' ? 'right' : 'left' },
      })
    }
    before += lengths[i]
  })

  const d = draft(f)
  d.curves = { ...f.curves }
  if (c) delete d.curves[c.id]
  for (const id of walls) delete d.walls[id]
  for (const m of moved) delete d.openings[m.id]
  for (const n of nodes.slice(1, -1)) delete d.nodes[n]

  const A = d.nodes[a], B = d.nodes[b]
  const straight = Math.abs(bulge) < 0.005
  // by default faces fine enough for the arc, yet each wide enough for the widest opening to stand in
  const widest = Math.max(0, ...moved.map(m => m.op.width))
  const roomy = widest ? Math.max(2, Math.floor(arcLength(A, B, bulge) / (widest + w.thickness + 0.1))) : MAX_SEGMENTS
  const n = straight ? 1 : Math.max(2, Math.min(MAX_SEGMENTS, Math.round(segments ?? Math.min(defaultSegments(A, B, bulge), roomy))))
  const pts = straight ? [A, B] : arcPoints(A, B, bulge, n)
  const curve = straight ? undefined : newId(d.curves)
  if (curve) d.curves[curve] = { a, b, bulge, segments: n }
  const chain = [a]
  for (const p of pts.slice(1, -1)) {
    const id = newId(d.nodes)
    d.nodes[id] = p
    chain.push(id)
  }
  chain.push(b)
  const faces: string[] = []
  for (let i = 1; i < chain.length; i++) {
    const id = newId(d.walls)
    d.walls[id] = { ...props, a: chain[i - 1], b: chain[i], ...(curve ? { curve } : {}) }
    faces.push(id)
  }
  if (!curve && !Object.keys(d.curves).length) delete d.curves

  let lost = 0
  for (const m of moved) {
    const k = Math.min(n - 1, Math.floor(m.frac * n))
    const face = faces[k]
    const len = dist(d.nodes[chain[k]], d.nodes[chain[k + 1]])
    const at = fitOpening(d, face, (m.frac * n - k) * len, m.op.width)
    if (at === null) { lost++; continue }
    d.openings[m.id] = { ...m.op, wall: face, at }
  }
  // the face nearest the middle stands for the wall in the inspector
  return { floor: d, wall: faces[Math.floor((faces.length - 1) / 2)], lost }
}
