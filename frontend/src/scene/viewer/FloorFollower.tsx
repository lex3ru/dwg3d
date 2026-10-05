import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import type * as THREE from 'three'
import type { SceneCtx } from './scene'

/** Group that follows a floor: its explode offset and its visibility.
 * (Used instead of a portal into the glTF node, so that children keep the
 * main store's camera.) */
export default function FloorFollower({ ctx, floor, children }: { ctx: SceneCtx; floor: string; children: React.ReactNode }) {
  const ref = useRef<THREE.Group>(null)
  useFrame(() => {
    const g = ref.current
    if (!g) return
    g.position.y = ctx.offset.get(floor) ?? 0
    const n = ctx.groups.get(floor)
    g.visible = n ? n.visible : true
  })
  return <group ref={ref}>{children}</group>
}
