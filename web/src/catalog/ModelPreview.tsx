import { OrbitControls, useGLTF } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Suspense, useMemo } from "react";
import * as THREE from "three";

// Просмотр 3D-модели типа рядом с контуром его габаритов: видно, встала ли модель как надо.
// box — ширина, высота, глубина в мм; transform — повороты в градусах и масштаб.

type Transform = { rx: number; ry: number; rz: number; scale: number };

export default function ModelPreview({ url, transform, box }: { url: string | null; transform: Transform; box: [number, number, number] }) {
  const [w, h, d] = [box[0] / 1000, box[1] / 1000, box[2] / 1000];
  const size = Math.max(w, h, d, 0.3);
  return (
    <Canvas camera={{ position: [size * 1.6, size * 1.2, size * 1.9], fov: 40 }} dpr={[1, 2]}>
      <ambientLight intensity={0.7} />
      <directionalLight position={[3, 5, 4]} intensity={1.6} />
      <gridHelper args={[size * 4, 8, "#9aa4b2", "#d5dae1"]} />
      <mesh position={[0, h / 2, 0]}>
        <boxGeometry args={[w, h, d]} />
        <meshBasicMaterial color="#2f6fde" wireframe transparent opacity={url ? 0.6 : 1} />
      </mesh>
      {url && (
        <Suspense fallback={null}>
          <Model url={url} transform={transform} />
        </Suspense>
      )}
      <OrbitControls target={[0, h / 2, 0]} makeDefault />
    </Canvas>
  );
}

function Model({ url, transform }: { url: string; transform: Transform }) {
  const gltf = useGLTF(url);
  const object = useMemo(() => {
    const group = new THREE.Group();
    const inner = gltf.scene.clone(true);
    const r = THREE.MathUtils.degToRad;
    inner.rotation.set(r(transform.rx), r(transform.ry), r(transform.rz));
    inner.scale.setScalar(transform.scale);
    group.add(inner);
    // поставить на пол и по центру
    const bounds = new THREE.Box3().setFromObject(group);
    const center = bounds.getCenter(new THREE.Vector3());
    inner.position.set(-center.x, -bounds.min.y, -center.z);
    return group;
  }, [gltf, transform.rx, transform.ry, transform.rz, transform.scale]);
  return <primitive object={object} />;
}
