import { Text } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { FloorMeta, RoomType } from '../api'

export const FONT = '/fonts/NotoSans-Regular.ttf'
const noRaycast = () => null

interface Label {
  key: string
  text: string
  typeOnly: boolean
  pos: THREE.Vector3
  angle: number
  size: number
  width: number
}

/** Font size from the room area (large halls get large text), limited by
 * the room depth so that a couple of wrapped lines still fit. */
function labelSize(area: number, depth: number | undefined): number {
  const s = Math.min(0.85, Math.max(0.2, Math.sqrt(Math.max(area, 0)) * 0.075))
  return depth ? Math.max(0.16, Math.min(s, depth * 0.3)) : s
}

/** Room names lying on the floor of one storey (rendered inside the floor
 * node, so they follow its visibility and the explode offset). Labels fade
 * out when they become smaller than a few pixels on screen. */
export default function RoomLabels({ floor, show, typeLabels }: {
  floor: FloorMeta
  show: boolean
  typeLabels: RoomType[]
}) {
  const labels = useMemo<Label[]>(() => {
    const tl = new Map(typeLabels.map((t) => [t.type, t.label]))
    return floor.rooms.flatMap((r) => {
      const typeText = r.type && r.type !== 'other' ? tl.get(r.type) : undefined
      const text = r.name || typeText
      if (!text) return []
      const [x, y, z] = r.label_pos
      return [{
        key: r.node, text, typeOnly: !r.name,
        pos: new THREE.Vector3(x, y + 0.03, z),
        angle: r.label_angle ?? 0,
        size: labelSize(r.area, r.label_d) * (r.name ? 1 : 0.8),
        width: Math.max(1, r.label_w ?? Math.sqrt(r.area)),
      }]
    })
  }, [floor, typeLabels])
  const refs = useRef<(THREE.Mesh & { fillOpacity?: number; outlineOpacity?: number } | null)[]>([])
  const tmp = useMemo(() => new THREE.Vector3(), [])

  useFrame(({ camera, size }) => {
    if (!show) return
    const persp = camera as THREE.PerspectiveCamera
    const ortho = camera as THREE.OrthographicCamera
    labels.forEach((l, i) => {
      const m = refs.current[i]
      if (!m) return
      // on-screen height of the text in pixels
      let px: number
      if (ortho.isOrthographicCamera) px = l.size * ortho.zoom
      else {
        m.getWorldPosition(tmp)
        const d = tmp.distanceTo(camera.position)
        px = (l.size / (2 * d * Math.tan((persp.fov * Math.PI) / 360))) * size.height
      }
      const a = THREE.MathUtils.clamp((px - 4) / 5, 0, 1)
      m.visible = a > 0.02
      m.fillOpacity = a * (l.typeOnly ? 0.7 : 1)
      m.outlineOpacity = a * 0.85
    })
  })

  if (!show) return null
  return (
    <group>
      {labels.map((l, i) => (
        <group key={l.key} position={l.pos} rotation-y={l.angle}>
          <Text
            ref={(m: THREE.Mesh | null) => { refs.current[i] = m }}
            font={FONT} fontSize={l.size} maxWidth={l.width} textAlign="center" anchorX="center" anchorY="middle"
            lineHeight={1.1} rotation-x={-Math.PI / 2} color={l.typeOnly ? '#6c5f4b' : '#2b2f33'}
            outlineWidth={l.size * 0.08} outlineColor="#ffffff" raycast={noRaycast} renderOrder={2}
            userData={{ role: 'label' }}
          >
            {l.text}
          </Text>
        </group>
      ))}
    </group>
  )
}
