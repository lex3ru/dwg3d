import { useEffect, useState } from "react";
import type { Underlay } from "./plan";

// Подложка (5.1.4 п. 5): PDF рисуется в картинку в браузере (pdf.js), картинка — как есть.
// Размер картинки в пикселях нужен для калибровки, поэтому сообщается наверх.

const cache = new Map<string, Promise<{ url: string; width: number; height: number }>>();
// страница PDF рисуется так, что её ширина — столько пикселей; масштаб подложки — мм на пиксель
export const PDF_RENDER_WIDTH = 4000;

async function render(fileId: string, page: number) {
  const response = await fetch(`/api/files/${fileId}`, { credentials: "same-origin" });
  if (!response.ok) throw new Error("файл подложки недоступен");
  const blob = await response.blob();
  if (blob.type !== "application/pdf") {
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.src = url;
    await img.decode();
    return { url, width: img.naturalWidth, height: img.naturalHeight };
  }
  const pdfjs = await import("pdfjs-dist");
  pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
  const doc = await pdfjs.getDocument({ data: new Uint8Array(await blob.arrayBuffer()) }).promise;
  const pdfPage = await doc.getPage(Math.min(page, doc.numPages));
  const base = pdfPage.getViewport({ scale: 1 });
  const viewport = pdfPage.getViewport({ scale: PDF_RENDER_WIDTH / base.width });
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(viewport.width);
  canvas.height = Math.round(viewport.height);
  await pdfPage.render({ canvas, viewport }).promise;
  const out = await new Promise<Blob>((resolve) => canvas.toBlob((b) => resolve(b!), "image/png"));
  return { url: URL.createObjectURL(out), width: canvas.width, height: canvas.height };
}

export function useUnderlayImage(underlay: Underlay | null) {
  const [image, setImage] = useState<{ url: string; width: number; height: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = underlay ? `${underlay.file_id}:${underlay.page}` : null;
  useEffect(() => {
    if (!underlay || !key) {
      setImage(null);
      return;
    }
    let alive = true;
    let promise = cache.get(key);
    if (!promise) {
      promise = render(underlay.file_id, underlay.page);
      cache.set(key, promise);
      promise.catch(() => cache.delete(key));
    }
    promise.then(
      (img) => alive && (setImage(img), setError(null)),
      (e: Error) => alive && setError(e.message),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return { image, error };
}

export function UnderlayImage({ underlay, image }: { underlay: Underlay; image: { url: string; width: number; height: number } | null }) {
  if (!underlay.visible || !image) return null;
  return (
    <image
      href={image.url}
      width={image.width}
      height={image.height}
      opacity={underlay.opacity}
      transform={`translate(${underlay.x} ${underlay.y}) rotate(${underlay.angle}) scale(${underlay.scale} ${-underlay.scale})`}
      style={{ pointerEvents: "none" }}
      preserveAspectRatio="none"
    />
  );
}

// Точка подложки (пиксели картинки) → точка плана
export function underlayToWorld(u: Underlay, px: number, py: number): [number, number] {
  const r = (u.angle * Math.PI) / 180;
  const x = px * u.scale;
  const y = -py * u.scale;
  return [u.x + x * Math.cos(r) - y * Math.sin(r), u.y + x * Math.sin(r) + y * Math.cos(r)];
}

// Точка плана → точка подложки
export function worldToUnderlay(u: Underlay, wx: number, wy: number): [number, number] {
  const r = (-u.angle * Math.PI) / 180;
  const dx = wx - u.x;
  const dy = wy - u.y;
  const x = dx * Math.cos(r) - dy * Math.sin(r);
  const y = dx * Math.sin(r) + dy * Math.cos(r);
  return [x / u.scale, -y / u.scale];
}
