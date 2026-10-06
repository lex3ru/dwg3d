import { useEffect, useRef, useState } from 'react'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Tip } from '../components/ui/tooltip'
import { to } from '../shell/route'

// the browser's own QR reader (Chrome, Android, recent Safari); where there is none, the code is typed in
type Detector = { detect(source: HTMLVideoElement): Promise<{ rawValue: string }[]> }
declare const BarcodeDetector: (new (options: { formats: string[] }) => Detector) | undefined
const able = () => typeof BarcodeDetector !== 'undefined' && !!navigator.mediaDevices?.getUserMedia

/** The camera reads a label; its link leads to the card of the object. */
export function Scan() {
  const video = useRef<HTMLVideoElement>(null)
  const [state, setState] = useState<'starting' | 'looking' | 'none' | 'denied'>(() => able() ? 'starting' : 'none')
  const [code, setCode] = useState('')
  useEffect(() => {
    if (!able()) return
    let stream: MediaStream | null = null, timer = 0, stopped = false
    const detector = new BarcodeDetector!({ formats: ['qr_code'] })
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }).then(s => {
      if (stopped) { s.getTracks().forEach(t => t.stop()); return }
      stream = s
      if (video.current) { video.current.srcObject = s; void video.current.play() }
      setState('looking')
      const look = async () => {
        if (stopped || !video.current || video.current.readyState < 2) { timer = window.setTimeout(look, 300); return }
        try {
          const found = await detector.detect(video.current)
          const hit = found.map(f => /\/q\/([A-Za-z0-9]+)/.exec(f.rawValue)?.[1]).find(Boolean)
          if (hit) { location.hash = to.qr(hit); return }
        } catch { /* the frame was not ready */ }
        timer = window.setTimeout(look, 300)
      }
      void look()
    }, () => setState('denied'))
    return () => { stopped = true; clearTimeout(timer); stream?.getTracks().forEach(t => t.stop()) }
  }, [])
  const go = (e: React.FormEvent) => { e.preventDefault(); const c = code.trim().toUpperCase(); if (c) location.hash = to.qr(c) }
  return (
    <section className="mx-auto max-w-md space-y-4">
      <h1 className="text-xl font-semibold">Сканировать QR-метку</h1>
      {state !== 'none' && state !== 'denied' && (
        <video ref={video} muted playsInline className="aspect-square w-full rounded-lg border bg-black object-cover" data-testid="scanner" />
      )}
      <p className="text-sm text-muted-foreground">
        {state === 'looking' ? 'Наведите камеру на метку.' : state === 'denied' ? 'Камера недоступна: доступ не дан.'
          : state === 'none' ? 'В этом браузере нет чтения QR-кодов камерой.' : 'Включаю камеру…'}
        {' '}Можно ввести код с метки вручную.
      </p>
      <form onSubmit={go} className="flex gap-2">
        <Tip label="Латинские буквы и цифры, напечатанные под QR-кодом; регистр не важен">
          <Input value={code} onChange={e => setCode(e.target.value)} aria-label="Код с метки" placeholder="Код под QR-кодом" className="uppercase" />
        </Tip>
        <Button type="submit" disabled={!code.trim()}
          hint={code.trim() ? 'Открыть карточку объекта с этой меткой, если он вам доступен' : 'Сначала введите код с метки'}>Открыть</Button>
      </form>
    </section>
  )
}
