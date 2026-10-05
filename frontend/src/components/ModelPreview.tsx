import { Bounds, OrbitControls, useGLTF } from '@react-three/drei'
import { Canvas } from '@react-three/fiber'
import { Suspense, useMemo } from 'react'
import type { Mesh, MeshStandardMaterial } from 'three'

function Model({ url }: { url: string }) {
  const gltf = useGLTF(url)
  // there is no environment to reflect here: a fully metallic material would come out black
  const scene = useMemo(() => {
    const copy = gltf.scene.clone(true)
    copy.traverse(o => {
      const mesh = o as Mesh
      if (!mesh.isMesh) return
      const tame = (m: MeshStandardMaterial) => { const c = m.clone(); if ('metalness' in c) c.metalness = Math.min(c.metalness, 0.1); return c }
      mesh.material = Array.isArray(mesh.material) ? mesh.material.map(m => tame(m as MeshStandardMaterial)) : tame(mesh.material as MeshStandardMaterial)
    })
    return copy
  }, [gltf])
  return <primitive object={scene} />
}

/** A 3D model turning under the mouse: what a type of the catalog looks like. */
export default function ModelPreview({ url }: { url: string }) {
  return (
    <div className="h-56 overflow-hidden rounded-lg border bg-secondary" data-testid="model-preview">
      <Canvas camera={{ position: [3, 2, 3], fov: 40 }}>
        <ambientLight intensity={1.4} />
        <directionalLight position={[4, 8, 5]} intensity={2.2} />
        <directionalLight position={[-5, 3, -4]} intensity={0.8} />
        <Suspense fallback={null}>
          <Bounds fit clip observe margin={1.3}><Model url={url} /></Bounds>
        </Suspense>
        <OrbitControls makeDefault />
      </Canvas>
    </div>
  )
}
