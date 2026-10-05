import { useGLTF } from '@react-three/drei'
import { Suspense, useMemo } from 'react'
import { neighbours, type Neighbour } from '../compat'

function Model({ n }: { n: Neighbour }) {
  const gltf = useGLTF(n.url)
  const scene = useMemo(() => gltf.scene.clone(true), [gltf])
  return <primitive object={scene} position={n.position} rotation={[0, n.turn, 0]} />
}

/**
 * The other drawings of the building, standing where their placement puts them
 * relative to the drawing on screen. They are there to be seen: floors, rooms
 * and tools work on the drawing that is open; another one is opened from the tree.
 */
export default function Neighbours({ drawing }: { drawing: string }) {
  return (
    <>
      {neighbours(drawing).map((n) => (
        <Suspense key={n.url} fallback={null}><Model n={n} /></Suspense>
      ))}
    </>
  )
}
