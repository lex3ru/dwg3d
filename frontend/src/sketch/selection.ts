/** What is selected in the 2D editor. */
export type Selection = { kind: 'wall'; id: string } | { kind: 'node'; id: string } | { kind: 'room'; key: string } | { kind: 'opening'; id: string }
  /** several walls (with their openings), picked by a box or with Shift */
  | { kind: 'group'; walls: string[] }

/** The walls a selection stands for: a wall, a group, or none. */
export const selectedWalls = (s: Selection | null): string[] => (s?.kind === 'wall' ? [s.id] : s?.kind === 'group' ? s.walls : [])

/** A list of walls as a selection: none, one wall, or a group. */
export const wallsSelection = (ids: string[]): Selection | null =>
  ids.length === 0 ? null : ids.length === 1 ? { kind: 'wall', id: ids[0] } : { kind: 'group', walls: ids }
