import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { DRACO_GLTF_CONFIG, DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";
import type { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

// Декодеры сжатых GLB — для превью, 3D и вида сверху (DWG3D-15, ADR-0015). Декодер Draco — из
// поставки three (вариант для glTF): сборка кладёт его в assets/ рядом с остальным. С
// gstatic.com, откуда его берёт drei, не пускают CSP (ADR-0014) и закрытая сеть учреждения.
// Загрузчик — GLTFLoader из three, а не useGLTF из drei: загрузчик drei (three-stdlib) теряет
// ошибку распаковки Draco, и испорченная модель грузится вечно, без сообщения.
const draco = new DRACOLoader().setDecoderPath(DRACO_GLTF_CONFIG);

export const withDecoders = (loader: GLTFLoader) => loader.setDRACOLoader(draco).setMeshoptDecoder(MeshoptDecoder);
