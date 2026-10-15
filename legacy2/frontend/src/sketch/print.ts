/** Sheets of a drawn plan for print: the paper, its parts, and the scale a floor fits at. */

export type Paper = 'A4' | 'A3'

/** Landscape, millimetres. */
export const PAPER: Record<Paper, [number, number]> = { A4: [297, 210], A3: [420, 297] }
/** Around the sheet; on the right the room schedule and the title block. */
export const MARGIN = 10
export const SIDE = 85
export const SCALES = [20, 25, 50, 100, 200, 500]

/** The field the plan is drawn in, millimetres: [width, height]. */
export function field(paper: Paper): [number, number] {
  const [w, h] = PAPER[paper]
  return [w - 2 * MARGIN - SIDE - 5, h - 2 * MARGIN]
}

/**
 * The scale to draw `size` (meters, with its dimension lines) at: the largest of the usual ones
 * it fits at (1:50 is larger than 1:100), or null when it fits at none.
 */
export function fitScale(size: [number, number], paper: Paper): number | null {
  const [fw, fh] = field(paper)
  return SCALES.find(s => (size[0] * 1000) / s <= fw && (size[1] * 1000) / s <= fh) ?? null
}
