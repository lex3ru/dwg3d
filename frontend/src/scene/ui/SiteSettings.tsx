import { Armchair, FileBox, Trash2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { deleteDetail, putView, uploadDetail, type ViewSettings, type V3 } from '../api'
import type { DetailInfo } from '../viewer/Viewer'
import { TILE_ATTRIBUTION } from '../viewer/tiles'

/** the fields of the detailed model's alignment */
const ALIGN = 'Подгонка детальной модели к распознанной: видно сразу, в здание записывается кнопкой «Сохранить»'

const num = (s: string, d = 0) => {
  const v = Number(String(s).replace(',', '.'))
  return Number.isFinite(v) ? v : d
}

/** Job viewer settings: building name, map binding, detailed model alignment.
 * Changes preview live (onPreview) and are stored with "Сохранить". */
export default function SiteSettings({ jobId, view, detailInfo, onPreview, onSaved, onClose }: {
  jobId: string
  view: ViewSettings
  detailInfo: DetailInfo | null
  onPreview: (v: ViewSettings) => void
  onSaved: (v: ViewSettings) => void
  onClose: () => void
}) {
  const [name, setName] = useState(view.name ?? '')
  const [site, setSite] = useState({
    lat: String(view.site?.lat ?? ''), lon: String(view.site?.lon ?? ''),
    azimuth: String(view.site?.azimuth ?? 0), scale: String(view.site?.scale ?? 1),
    tiles: view.site?.tiles ?? '', attribution: view.site?.attribution ?? '',
  })
  const d = view.detail
  const [det, setDet] = useState({
    x: String(d?.offset?.[0] ?? 0), y: String(d?.offset?.[1] ?? 0), z: String(d?.offset?.[2] ?? 0),
    rotation: String(d?.rotation ?? 0), scale: String(d?.scale ?? 1),
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const siteValue = (s = site): ViewSettings['site'] | null => (s.lat.trim() && s.lon.trim()
    ? {
        lat: num(s.lat), lon: num(s.lon), azimuth: num(s.azimuth), scale: num(s.scale, 1) || 1,
        ...(s.tiles.trim() ? { tiles: s.tiles.trim(), attribution: s.attribution.trim() } : {}),
      } : null)
  const detailValue = (x = det) => ({ offset: [num(x.x), num(x.y), num(x.z)] as V3, rotation: num(x.rotation), scale: num(x.scale, 1) || 1 })

  const preview = (s = site, x = det) => onPreview({
    ...view, site: siteValue(s) ?? undefined, detail: view.detail ? { ...view.detail, ...detailValue(x) } : undefined,
  })
  const updSite = (patch: Partial<typeof site>) => {
    let s = { ...site, ...patch }
    // "55.7539, 37.6208" pasted into the latitude field
    const m = /^\s*(-?\d+[.,]\d+)\s*[,;\s]\s*(-?\d+[.,]\d+)\s*$/.exec(patch.lat ?? '')
    if (m) s = { ...s, lat: m[1].replace(',', '.'), lon: m[2].replace(',', '.') }
    setSite(s)
    preview(s, det)
  }
  const updDet = (patch: Partial<typeof det>) => {
    const x = { ...det, ...patch }
    setDet(x)
    preview(site, x)
  }

  const save = async () => {
    setBusy(true)
    setErr(null)
    try {
      const body: Record<string, unknown> = { name: name.trim(), site: siteValue() }
      if (view.detail) body.detail = detailValue()
      onSaved(await putView(jobId, body))
      onClose()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const upload = async (f: File | undefined) => {
    if (!f) return
    setBusy(true)
    setErr(null)
    try {
      onSaved(await uploadDetail(jobId, f))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const remove = async () => {
    setBusy(true)
    try { onSaved(await deleteDetail(jobId)) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  const h3 = 'm-0 text-sm font-semibold'
  const hint = 'm-0 text-xs text-muted-foreground'
  const code = 'rounded bg-secondary px-1 font-mono text-[11px]'
  const grid = 'grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-x-5 gap-y-2'
  const row = 'flex items-center justify-between gap-2 font-normal'
  const numCls = 'w-20'

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent aria-describedby={undefined} onKeyDown={(e) => e.stopPropagation()}
        className="max-h-[85vh] max-w-2xl grid-rows-[auto_minmax(0,1fr)_auto]">
        <DialogHeader><DialogTitle>Карта и детальная модель</DialogTitle></DialogHeader>
        <div className="-mx-5 grid min-h-0 content-start gap-3 overflow-y-auto px-5 text-sm">
          <h3 className={h3}>Здание</h3>
          <div className={grid}>
            <Label className={row}><span className="shrink-0">Название</span>
              <Tip label="Имя этого чертежа в списке чертежей здания и в шапке редактора; пусто — не менять">
                <Input value={name} placeholder="как в списке зданий" onChange={(e) => setName(e.target.value)} />
              </Tip></Label>
          </div>

          <h3 className={cn(h3, 'mt-2')}>Привязка к карте</h3>
          <p className={hint}>Точка — центр модели (начало координат). Азимут — поворот здания по часовой стрелке
            от севера: на сколько градусов ось Y плана отклонена от направления на север. Масштаб подложки — если план
            начерчен не в масштабе 1:1. Координаты можно вставить одной строкой «55.7539, 37.6208».</p>
          <div className={grid}>
            <Label className={row}><span className="flex-1">Широта</span>
              <Tip label="Градусы центра модели; можно вставить «55.7539, 37.6208» целиком, пусто — без карты">
                <Input className="w-32" value={site.lat} placeholder="55.7539" onChange={(e) => updSite({ lat: e.target.value })} />
              </Tip></Label>
            <Label className={row}><span className="flex-1">Долгота</span>
              <Tip label="Градусы центра модели, точка или запятая; пусто — без карты">
                <Input className="w-32" value={site.lon} placeholder="37.6208" onChange={(e) => updSite({ lon: e.target.value })} />
              </Tip></Label>
            <Label className={row}><span className="flex-1">Азимут, °</span>
              <Tip label="На сколько градусов по часовой ось Y плана отклонена от севера; карта поворачивается сразу">
                <Input className={numCls} value={site.azimuth} onChange={(e) => updSite({ azimuth: e.target.value })} />
              </Tip></Label>
            <Label className={row}><span className="flex-1">Масштаб подложки</span>
              <Tip label="Поправка, если план начерчен не 1:1; 1 — без поправки">
                <Input className={numCls} value={site.scale} onChange={(e) => updSite({ scale: e.target.value })} />
              </Tip></Label>
          </div>
          <div className="grid gap-2">
            <Label className={row}><span className="w-32 shrink-0">Тайлы (XYZ)</span>
              <Tip label="Свой источник карты: https://…/{z}/{x}/{y}.png; пусто — OpenStreetMap">
                <Input value={site.tiles} placeholder="по умолчанию OpenStreetMap" onChange={(e) => updSite({ tiles: e.target.value })} />
              </Tip></Label>
            <Label className={row}><span className="w-32 shrink-0">Атрибуция</span>
              <Tip label="Подпись правообладателя своих тайлов; сохраняется только вместе с адресом тайлов">
                <Input value={site.attribution} placeholder={TILE_ATTRIBUTION} onChange={(e) => updSite({ attribution: e.target.value })} />
              </Tip></Label>
          </div>
          <p className={hint}>По умолчанию — растровые тайлы OpenStreetMap ({TILE_ATTRIBUTION}), обесцвеченные
            в просмотрщике; серверы OSM рассчитаны на небольшую нагрузку, для публичного сервиса укажите свой
            источник: <code className={code}>https://…/{'{z}'}/{'{x}'}/{'{y}'}.png</code> и его атрибуцию. Без привязки под зданием —
            нейтральная сетка.</p>

          <h3 className={cn(h3, 'mt-2')}>Детальная модель (GLB)</h3>
          <p className={hint}>Фасад, мебель, оборудование — готовая модель поверх распознанной. Узлы с именем
            {' '}<code className={code}>floor_&lt;номер этажа&gt;</code> попадают на этот этаж, остальные — по высоте; узлы выше полутора этажей —
            фасад всего здания. Узлы с «furniture» / «мебель» в имени — мебель (кнопка <Armchair className="inline size-3.5 align-[-2px]" aria-label="мебель" /> внизу).</p>
          {view.detail?.file ? (
            <>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-md bg-secondary px-2.5 py-2">
                <FileBox className="size-4 shrink-0 text-muted-foreground" />
                <b className="break-all">{view.detail.file}</b>
                <span className="text-muted-foreground">{((view.detail.size ?? 0) / 1048576).toFixed(1)} МБ</span>
                {detailInfo && <span className="text-muted-foreground">этажных узлов {detailInfo.floors}, фасад {detailInfo.building}, мебель {detailInfo.furniture}</span>}
                <Button variant="ghost" size="sm" className="ml-auto text-destructive hover:text-destructive" disabled={busy} onClick={remove}
                  hint="Убрать детальную модель у всего здания сразу, без подтверждения; вернуть — только загрузив файл снова">
                  <Trash2 /> Удалить
                </Button>
              </div>
              <div className={grid}>
                <Label className={row}><span className="flex-1">Сдвиг X, м</span>
                  <Tip label={ALIGN}><Input className={numCls} value={det.x} onChange={(e) => updDet({ x: e.target.value })} /></Tip></Label>
                <Label className={row}><span className="flex-1">Сдвиг Y (вверх), м</span>
                  <Tip label={ALIGN}><Input className={numCls} value={det.y} onChange={(e) => updDet({ y: e.target.value })} /></Tip></Label>
                <Label className={row}><span className="flex-1">Сдвиг Z, м</span>
                  <Tip label={ALIGN}><Input className={numCls} value={det.z} onChange={(e) => updDet({ z: e.target.value })} /></Tip></Label>
                <Label className={row}><span className="flex-1">Поворот, °</span>
                  <Tip label={ALIGN}><Input className={numCls} value={det.rotation} onChange={(e) => updDet({ rotation: e.target.value })} /></Tip></Label>
                <Label className={row}><span className="flex-1">Масштаб</span>
                  <Tip label={ALIGN}><Input className={numCls} value={det.scale} onChange={(e) => updDet({ scale: e.target.value })} /></Tip></Label>
              </div>
            </>
          ) : null}
          <div>
            <input ref={fileRef} type="file" accept=".glb" hidden disabled={busy}
              onChange={(e) => { upload(e.target.files?.[0]); e.target.value = '' }} />
            <Button variant="outline" size="sm" disabled={busy} onClick={() => fileRef.current?.click()}
              hint={view.detail?.file ? 'Новый файл .glb сразу заменит прежний у всего здания' : 'Файл .glb уходит на сервер сразу и показывается у всего здания поверх распознанной модели'}>
              <Upload /> {view.detail?.file ? 'Заменить GLB…' : 'Загрузить GLB…'}
            </Button>
          </div>
          {err && <p className="m-0 text-sm text-destructive">{err}</p>}
        </div>
        <DialogFooter>
          <Button variant="secondary" hint="Закрыть, ничего не записывая; предпросмотр сбросится" onClick={onClose}>Отмена</Button>
          <Button disabled={busy} hint="Записать название чертежа, привязку здания к карте и подгонку модели" onClick={save}>Сохранить</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
