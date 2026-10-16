import { ImageUp } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { FormError, Input } from "@/ui/form";
import { Card, PageHeader } from "@/ui/misc";
import { decoder, QrCamera } from "./scanner";

// QR-сканер (5.4.8 п. 3, 6.5.12): камера телефона в браузере, без приложения. Метка вещи
// открывает её карточку, метка склада — склад, метка на двери — помещение на плане для обхода.

// «https://…/q/AB12CD…» или сам код метки (12 знаков) → код
export function labelCode(text: string): string | null {
  const t = text.trim();
  const m = t.match(/\/q\/([A-Za-z0-9]+)\/?(?:[?#].*)?$/);
  if (m) return m[1]!.toUpperCase();
  return /^[A-HJ-NP-Za-hj-np-z2-9]{12}$/.test(t) ? t.toUpperCase() : null;
}

export function ScanPage() {
  const navigate = useNavigate();
  const canvas = useRef<HTMLCanvasElement>(null);
  const photo = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState("");

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
      <Card className="overflow-hidden p-2">
        <QrCamera onCode={found} />
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
