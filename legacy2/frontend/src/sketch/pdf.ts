/**
 * A PDF of a plan, its pages drawn as pictures in the browser (pdf.js) to go
 * under a floor like any other picture. pdf.js is loaded only when a PDF is
 * opened.
 */
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

/** The longer side of a page's picture, pixels: fine lines of a plan stay readable, the file stays small. */
const LONG_SIDE = 4000
/** The picture is sent as PNG while it fits, else as JPEG. */
const MAX_BYTES = 18 * 1024 * 1024

export interface Pdf {
  pages: number
  /** the page (from 1) as a picture file */
  picture: (page: number) => Promise<File>
}

const blob = (canvas: HTMLCanvasElement, type: string, quality?: number) =>
  new Promise<Blob>((resolve, reject) => canvas.toBlob(b => (b ? resolve(b) : reject(new Error('Страницу не удалось нарисовать'))), type, quality))

export async function openPdf(file: File): Promise<Pdf> {
  const pdfjs = await import('pdfjs-dist')
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
  let doc
  try {
    doc = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise
  } catch {
    throw new Error('PDF не открылся: файл повреждён или защищён паролем')
  }
  const stem = file.name.replace(/\.pdf$/i, '')
  return {
    pages: doc.numPages,
    picture: async (n: number) => {
      const page = await doc.getPage(n)
      const one = page.getViewport({ scale: 1 })
      const viewport = page.getViewport({ scale: LONG_SIDE / Math.max(one.width, one.height) })
      const canvas = document.createElement('canvas')
      canvas.width = Math.round(viewport.width)
      canvas.height = Math.round(viewport.height)
      await page.render({ canvas, viewport, background: '#ffffff' }).promise
      let out = await blob(canvas, 'image/png')
      let type = 'png'
      if (out.size > MAX_BYTES) { out = await blob(canvas, 'image/jpeg', 0.9); type = 'jpg' }
      return new File([out], `${stem}-${n}.${type}`, { type: out.type })
    },
  }
}
