import * as THREE from "three";

// Как 3D-модель типа ставится в сцену (5.2.2): повернуть на 90°-шаги, отмасштабировать —
// или вписать в габариты типа по каждой оси; поставить на пол серединой в начало координат.
// Перед модели смотрит в −Z сцены — это +Y плана, «лицо» предмета.

export interface ModelTransform {
  rx: number;
  ry: number;
  rz: number;
  scale: number;
  fit: boolean;
}

export const transformOf = (t?: Partial<ModelTransform> | null): ModelTransform => ({ rx: 0, ry: 0, rz: 0, scale: 1, fit: false, ...t });

// dims — ширина, высота, глубина типа в мм
export function placeModel(scene: THREE.Object3D, tr: ModelTransform, dims: [number, number, number] | null): THREE.Group {
  const r = THREE.MathUtils.degToRad;
  const inner = scene.clone(true);
  inner.rotation.set(r(tr.rx), r(tr.ry), r(tr.rz));
  inner.scale.setScalar(tr.fit ? 1 : tr.scale);
  const rotated = new THREE.Group();
  rotated.add(inner);
  rotated.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(rotated);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  rotated.position.set(-center.x, -box.min.y, -center.z);
  const outer = new THREE.Group();
  if (tr.fit && dims && size.x > 0 && size.y > 0 && size.z > 0) outer.scale.set(dims[0] / 1000 / size.x, dims[1] / 1000 / size.y, dims[2] / 1000 / size.z);
  outer.add(rotated);
  outer.updateMatrixWorld(true);
  return outer;
}
