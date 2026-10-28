// Тестовая Draco-модель (DWG3D-15): коробка 1,0 × 0,5 × 0,8 м (x × y × z, y — вверх), геометрия
// сжата KHR_draco_mesh_compression — так GLB выгружают Blender и Sketchfab. Её грузят e2e
// (`stage4.spec.ts`) и тесты сервера (`server/tests/test_catalog.py`). Готовый файл лежит
// рядом: draco-box.glb. Пересобрать: `node e2e/fixtures/draco-box.mjs` из корня репозитория
// после `npm install` в web/ — кодировщик draco3d приходит туда вместе с drei.
import { writeFileSync } from "node:fs";
import { createRequire } from "node:module";

const draco3d = createRequire(new URL("../../web/package.json", import.meta.url))("draco3d");
const SIZE = [1.0, 0.5, 0.8];

// грани: нормаль и две оси вдоль грани, u × v = n — обход против часовой снаружи
const FACES = [
  [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
  [[-1, 0, 0], [0, 0, 1], [0, 1, 0]],
  [[0, 1, 0], [0, 0, 1], [1, 0, 0]],
  [[0, -1, 0], [1, 0, 0], [0, 0, 1]],
  [[0, 0, 1], [1, 0, 0], [0, 1, 0]],
  [[0, 0, -1], [0, 1, 0], [1, 0, 0]],
];
const positions = [];
const normals = [];
const indices = [];
for (const [n, u, v] of FACES) {
  const base = positions.length / 3;
  for (const [su, sv] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
    for (let k = 0; k < 3; k++) positions.push((0.5 + 0.5 * (n[k] + su * u[k] + sv * v[k])) * SIZE[k]);
    normals.push(...n);
  }
  indices.push(base, base + 1, base + 2, base, base + 2, base + 3);
}
const points = positions.length / 3;

const m = await draco3d.createEncoderModule({});
const builder = new m.MeshBuilder();
const mesh = new m.Mesh();
builder.AddFacesToMesh(mesh, indices.length / 3, new Uint32Array(indices));
const position = builder.AddFloatAttributeToMesh(mesh, m.POSITION, points, 3, new Float32Array(positions));
const normal = builder.AddFloatAttributeToMesh(mesh, m.NORMAL, points, 3, new Float32Array(normals));
const encoder = new m.Encoder();
// последовательное кодирование сохраняет порядок и число вершин — как в accessor ниже
encoder.SetEncodingMethod(m.MESH_SEQUENTIAL_ENCODING);
encoder.SetAttributeQuantization(m.POSITION, 14);
encoder.SetAttributeQuantization(m.NORMAL, 10);
const out = new m.DracoInt8Array();
const length = encoder.EncodeMeshToDracoBuffer(mesh, out);
if (length <= 0) throw new Error("draco3d не сжал сетку");
const bin = Buffer.alloc(Math.ceil(length / 4) * 4);
for (let i = 0; i < length; i++) bin.writeInt8(out.GetValue(i), i);
for (const o of [out, encoder, mesh, builder]) m.destroy(o);

const doc = {
  asset: { version: "2.0", generator: "dwg3d e2e/fixtures/draco-box.mjs" },
  extensionsUsed: ["KHR_draco_mesh_compression"],
  extensionsRequired: ["KHR_draco_mesh_compression"],
  scene: 0,
  scenes: [{ nodes: [0] }],
  nodes: [{ name: "Коробка", mesh: 0, translation: [0.3, 0, -0.2] }],
  meshes: [{
    primitives: [{
      attributes: { POSITION: 0, NORMAL: 1 },
      indices: 2,
      material: 0,
      extensions: { KHR_draco_mesh_compression: { bufferView: 0, attributes: { POSITION: position, NORMAL: normal } } },
    }],
  }],
  materials: [{ pbrMetallicRoughness: { baseColorFactor: [0.85, 0.55, 0.25, 1], metallicFactor: 0, roughnessFactor: 0.8 } }],
  // у сжатых примитивов accessor без bufferView, но min и max у POSITION обязательны (glTF 2.0)
  accessors: [
    { componentType: 5126, count: points, type: "VEC3", min: [0, 0, 0], max: SIZE },
    { componentType: 5126, count: points, type: "VEC3" },
    { componentType: 5123, count: indices.length, type: "SCALAR" },
  ],
  bufferViews: [{ buffer: 0, byteOffset: 0, byteLength: length }],
  buffers: [{ byteLength: bin.length }],
};
let json = Buffer.from(JSON.stringify(doc));
json = Buffer.concat([json, Buffer.alloc((4 - (json.length % 4)) % 4, " ")]);
const chunk = (data, kind) => {
  const head = Buffer.alloc(8);
  head.writeUInt32LE(data.length, 0);
  head.write(kind, 4, "latin1");
  return Buffer.concat([head, data]);
};
const body = Buffer.concat([chunk(json, "JSON"), chunk(bin, "BIN\0")]);
const head = Buffer.alloc(12);
head.write("glTF", 0, "latin1");
head.writeUInt32LE(2, 4);
head.writeUInt32LE(12 + body.length, 8);
const file = new URL("draco-box.glb", import.meta.url);
writeFileSync(file, Buffer.concat([head, body]));
console.log(`${file.pathname}: ${12 + body.length} байт, Draco — ${length}`);
