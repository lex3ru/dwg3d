import { OrbitControls, useGLTF } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Suspense, useMemo } from "react";
import * as THREE from "three";
import { placeModel, type ModelTransform } from "./model3d";

// Просмотр 3D-модели типа рядом с контуром его габаритов: видно, встала ли модель как надо.
// box — ширина, высота, глубина в мм; transform — повороты в градусах и масштаб.


export default function ModelPreview({ url, transform, box }: { url: string | null; transform: ModelTransform; box: [number, number, number] }) {
  const [w, h, d] = [box[0] / 1000, box[1] / 1000, box[2] / 1000];
  const size = Math.max(w, h, d, 0.3);
  return (
    <Canvas camera={{ position: [size * 0.7, size * 1.0, -size * 2.3], fov: 40 }} dpr={[1, 2]}>
      <ambientLight intensity={0.7} />
      <directionalLight position={[3, 5, 4]} intensity={1.2} />
      <directionalLight position={[-2, 4, -5]} intensity={1.2} />
      <hemisphereLight args={["#ffffff", "#8a8f99", 0.5]} />
      <gridHelper args={[size * 4, 8, "#9aa4b2", "#d5dae1"]} />
      <mesh position={[0, h / 2, 0]}>
        <boxGeometry args={[w, h, d]} />
        <meshBasicMaterial color="#2f6fde" wireframe transparent opacity={url ? 0.6 : 1} />
      </mesh>
      {url && (
        <Suspense fallback={null}>
          <Model url={url} transform={transform} box={box} />
        </Suspense>
      )}
      {/* перед предмета: стрелка на полу — сюда смотрит «лицо» (на плане — короткая черта) */}
      <mesh position={[0, 0.002, -(d / 2 + Math.max(0.08, size * 0.08))]} rotation={[-Math.PI / 2, 0, 0]}>
        <shapeGeometry args={[arrow(Math.max(0.12, size * 0.12))]} />
        <meshBasicMaterial color="#2f6fde" side={THREE.DoubleSide} />
      </mesh>
      <OrbitControls target={[0, h / 2, 0]} makeDefault />
    </Canvas>
  );
}

function Model({ url, transform, box }: { url: string; transform: ModelTransform; box: [number, number, number] }) {
  const gltf = useGLTF(url);
  const object = useMemo(() => placeModel(gltf.scene, transform, [box[0], box[1], box[2]]), [gltf, transform, box[0], box[1], box[2]]);
  return <primitive object={object} />;
}

function arrow(k: number) {
  const s = new THREE.Shape();
  // после поворота на −90° вокруг X ось Y фигуры смотрит в −Z сцены
  s.moveTo(0, k);
  s.lineTo(-k * 0.7, 0);
  s.lineTo(k * 0.7, 0);
  s.closePath();
  return s;
}
