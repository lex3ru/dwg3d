import { useSyncExternalStore } from 'react'

/**
 * What the 3D/2D editor of a drawing shows right now, told to the copilot's pane: the floor (the building's
 * floor id when the build knows it), the room clicked, the objects selected, 2D or 3D. The scene publishes,
 * the shell reads; nothing else shares state between them.
 */
export interface SceneState {
  drawing: string | null
  floor: { candidate: string; id: string | null; name: string } | null
  room: { name: string; area: number } | null
  /** ids of the selected objects (assets of the records); objects of a variant are named by the variant */
  selected: { kind: 'asset' | 'variant'; id: string; name?: string }[]
  view: '2d' | '3d'
}

let state: SceneState | null = null
const listeners = new Set<() => void>()

export function publishScene(next: SceneState | null) {
  state = next
  listeners.forEach(l => l())
}

const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l) } }
export const useSceneState = () => useSyncExternalStore(subscribe, () => state, () => state)
