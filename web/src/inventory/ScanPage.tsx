import { Camera, ImageUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { FormError, Input } from "@/ui/form";
import { Card, PageHeader } from "@/ui/misc";

// QR-сканер (5.4.8 п. 3, 6.5.12): камера телефона в браузере, без приложения. Метка вещи
// открывает её карточку, метка склада — склад, метка на двери — помещение на плане для обхода.

// «https://…/q/AB12CD…» или сам код метки (12 знаков) → код
export function labelCode(text: string): string | null {
  const t = text.trim();
  const m = t.match(/\/q\/([A-Za-z0-9]+)\/?(?:[?#].*)?$/);
  if (m) return m[1]!.toUpperCase();
  return /^[A-HJ-NP-Za-hj-np-z2-9]{12}$/.test(t) ? t.toUpperCase() : null;
}

type Detector = { detect: (source: CanvasImageSource) => Promise<{ rawValue: string }[]> };

async function decoder(): Promise<(canvas: HTMLCanvasElement) => Promise<string | null>> {
  // встроенный распознаватель (Chrome на Android) — быстрее; иначе jsQR
  const Native = (window as unknown as { BarcodeDetector?: new (o: { formats: string[] }) => Detector }).BarcodeDetector;
  if (Native) {
    try {
      const d = new Native({ formats: ["qr_code"] });
      return async (canvas) => (await d.detect(canvas))[0]?.rawValue ?? null;
    } catch {
      /* нет QR среди форматов — jsQR */
    }
  }
  const { default: jsQR } = await import("jsqr");
  return async (canvas) => {
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
    return jsQR(img.data, img.width, img.height, { inversionAttempts: "dontInvert" })?.data ?? null;
  };
}

export function ScanPage() {
  const navigate = useNavigate();
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const photo = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<"off" | "starting" | "on">("off");
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState("");
  const stream = useRef<MediaStream | null>(null);

  const found = (text: string) => {
    const code = labelCode(text);
    if (!code) {
      setError("Это не метка системы — наведите на QR-код с наклейки.");
      return false;
    }
    navigator.vibrate?.(80);
    navigate(`/q/${code}`);
    return true;
  };

  const stop = () => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    setState("off");
  };

  const start = async () => {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Камера недоступна в этом браузере (нужно защищённое соединение https). Введите код с наклейки или выберите фото.");
      return;
    }
    setState("starting");
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
      const v = video.current!;
      v.srcObject = stream.current;
      await v.play();
      setState("on");
      const decode = await decoder();
      const c = canvas.current!;
      const tick = async () => {
        if (!stream.current) return;
        if (v.videoWidth) {
          // кадр уменьшаем до 640 по длинной стороне — быстрее, QR читается
          const k = Math.min(1, 640 / Math.max(v.videoWidth, v.videoHeight));
          c.width = Math.round(v.videoWidth * k);
          c.height = Math.round(v.videoHeight * k);
          c.getContext("2d", { willReadFrequently: true })!.drawImage(v, 0, 0, c.width, c.height);
          const text = await decode(c).catch(() => null);
          if (text && found(text)) {
            stop();
            return;
          }
        }
        setTimeout(() => void tick(), 120);
      };
      void tick();
    } catch (e) {
      stop();
      setError((e as Error).name === "NotAllowedError" ? "Доступ к камере запрещён — разрешите его в настройках браузера." : "Камера не включилась. Введите код с наклейки или выберите фото.");
    }
  };

  useEffect(() => {
    void start();
    return () => stream.current?.getTracks().forEach((t) => t.stop());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fromPhoto = async (file: File) => {
    setError(null);
    const bitmap = await createImageBitmap(file);
    const c = canvas.current!;
    const k = Math.min(1, 1280 / Math.max(bitmap.width, bitmap.height));
    c.width = Math.round(bitmap.width * k);
    c.height = Math.round(bitmap.height * k);
    c.getContext("2d", { willReadFrequently: true })!.drawImage(bitmap, 0, 0, c.width, c.height);
    const text = await (await decoder())(c).catch(() => null);
    if (!text) setError("На фото не нашлось QR-кода.");
    else found(text);
  };

  return (
    <PageBody>
      <PageHeader title="QR-сканер" subtitle="Наведите камеру на метку вещи, склада или двери помещения" />
      <Card className="overflow-hidden">
        <div className="relative aspect-square max-h-[45dvh] w-full bg-black md:aspect-video">
          <video ref={video} muted playsInline className="h-full w-full object-cover" aria-label="Камера" />
          {state === "on" && <div className="pointer-events-none absolute top-1/2 left-1/2 size-[55%] max-w-72 -translate-x-1/2 -translate-y-1/2 rounded-2xl border-4 border-white/80" />}
          {state !== "on" && (
            <div className="absolute inset-0 flex items-center justify-center">
              <Button variant="primary" onClick={() => void start()} disabled={state === "starting"}>
                <Camera /> {state === "starting" ? "Включаю камеру…" : "Включить камеру"}
              </Button>
            </div>
          )}
        </div>
        <canvas ref={canvas} className="hidden" />
      </Card>
      <FormError message={error} />
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          // код метки — открыть; инвентарный номер или название — найти
          if (!manual.trim()) return;
          if (labelCode(manual)) found(manual);
          else navigate(`/search?q=${encodeURIComponent(manual.trim())}`);
        }}
      >
        <Input aria-label="Код метки или инвентарный номер" placeholder="Инв. номер или код метки" value={manual} onChange={(e) => setManual(e.target.value)} className="w-56" />
        <Button type="submit">Открыть</Button>
        <Button type="button" variant="ghost" onClick={() => photo.current?.click()}>
          <ImageUp /> Из фото
        </Button>
        <input ref={photo} type="file" accept="image/*" capture="environment" className="hidden" aria-label="Фото метки" onChange={(e) => e.target.files?.[0] && void fromPhoto(e.target.files[0])} />
      </form>
    </PageBody>
  );
}
