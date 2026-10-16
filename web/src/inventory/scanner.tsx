import { Camera } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { Button } from "@/ui/button";
import { FormError } from "@/ui/form";

// Камера телефона в браузере с распознаванием QR (5.4.8 п. 3, 6.5.8): встроенный распознаватель
// (Chrome на Android) или jsQR. Подряд (обход) — каждый код раз в 2 с; разово (сканер) —
// останавливается, когда onCode вернул true.

type Detector = { detect: (source: CanvasImageSource) => Promise<{ rawValue: string }[]> };

export async function decoder(): Promise<(canvas: HTMLCanvasElement) => Promise<string | null>> {
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

export function QrCamera({ onCode, continuous = false, autoStart = true, className }: { onCode: (text: string) => boolean | void; continuous?: boolean; autoStart?: boolean; className?: string }) {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [state, setState] = useState<"off" | "starting" | "on">("off");
  const [error, setError] = useState<string | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const handler = useRef(onCode);
  handler.current = onCode;
  const last = useRef<{ text: string; at: number } | null>(null);

  const found = (text: string) => {
    // подряд одна и та же метка в кадре — не отмечать её каждые 120 мс
    if (continuous && last.current && last.current.text === text && Date.now() - last.current.at < 2000) return false;
    last.current = { text, at: Date.now() };
    return handler.current(text) === true && !continuous;
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

  useEffect(() => {
    if (autoStart) void start();
    return () => stream.current?.getTracks().forEach((t) => t.stop());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="relative aspect-square max-h-[45dvh] w-full overflow-hidden rounded-lg bg-black md:aspect-video">
        <video ref={video} muted playsInline className="h-full w-full object-cover" aria-label="Камера" />
        {state === "on" && <div className="pointer-events-none absolute top-1/2 left-1/2 size-[55%] max-w-72 -translate-x-1/2 -translate-y-1/2 rounded-2xl border-4 border-white/80" />}
        {state !== "on" && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Button variant="primary" onClick={() => void start()} disabled={state === "starting"}>
              <Camera /> {state === "starting" ? "Включаю камеру…" : "Включить камеру"}
            </Button>
          </div>
        )}
        {state === "on" && continuous && (
          <Button size="sm" className="absolute right-2 bottom-2" onClick={stop}>
            Выключить
          </Button>
        )}
      </div>
      <canvas ref={canvas} className="hidden" />
      <FormError message={error} />
    </div>
  );
}
