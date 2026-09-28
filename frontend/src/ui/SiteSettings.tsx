import { useState } from 'react'
import { deleteDetail, putView, uploadDetail, type ViewSettings, type V3 } from '../api'
import type { DetailInfo } from '../viewer/Viewer'
import { TILE_ATTRIBUTION } from '../viewer/tiles'

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

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal site-modal" onMouseDown={(e) => e.stopPropagation()} role="dialog">
        <header><h2>Карта и детальная модель</h2><button className="ghost" onClick={onClose}>✕</button></header>
        <div className="modal-body">
          <h3>Здание</h3>
          <div className="params">
            <label><span>Название</span><input value={name} placeholder="как в списке зданий" onChange={(e) => setName(e.target.value)} /></label>
          </div>

          <h3>Привязка к карте</h3>
          <p className="hint">Точка — центр модели (начало координат). Азимут — поворот здания по часовой стрелке
            от севера: на сколько градусов ось Y плана отклонена от направления на север. Масштаб подложки — если план
            начерчен не в масштабе 1:1. Координаты можно вставить одной строкой «55.7539, 37.6208».</p>
          <div className="params">
            <label><span>Широта</span><input value={site.lat} placeholder="55.7539" onChange={(e) => updSite({ lat: e.target.value })} /></label>
            <label><span>Долгота</span><input value={site.lon} placeholder="37.6208" onChange={(e) => updSite({ lon: e.target.value })} /></label>
            <label><span>Азимут, °</span><input className="num" value={site.azimuth} onChange={(e) => updSite({ azimuth: e.target.value })} /></label>
            <label><span>Масштаб подложки</span><input className="num" value={site.scale} onChange={(e) => updSite({ scale: e.target.value })} /></label>
          </div>
          <div className="params">
            <label><span>Тайлы (XYZ)</span><input value={site.tiles} placeholder="по умолчанию OpenStreetMap"
              onChange={(e) => updSite({ tiles: e.target.value })} /></label>
            <label><span>Атрибуция</span><input value={site.attribution} placeholder={TILE_ATTRIBUTION}
              onChange={(e) => updSite({ attribution: e.target.value })} /></label>
          </div>
          <p className="hint">По умолчанию — растровые тайлы OpenStreetMap ({TILE_ATTRIBUTION}), обесцвеченные
            в просмотрщике; серверы OSM рассчитаны на небольшую нагрузку, для публичного сервиса укажите свой
            источник: <code>https://…/{'{z}'}/{'{x}'}/{'{y}'}.png</code> и его атрибуцию. Без привязки под зданием —
            нейтральная сетка.</p>

          <h3>Детальная модель (GLB)</h3>
          <p className="hint">Фасад, мебель, оборудование — готовая модель поверх распознанной. Узлы с именем
            <code> floor_&lt;номер этажа&gt;</code> попадают на этот этаж, остальные — по высоте; узлы выше полутора этажей —
            фасад всего здания. Узлы с «furniture» / «мебель» в имени — мебель (кнопка 🛋 внизу).</p>
          {view.detail?.file ? (
            <>
              <div className="detail-file">
                <b>{view.detail.file}</b>
                <span>{((view.detail.size ?? 0) / 1048576).toFixed(1)} МБ</span>
                {detailInfo && <span>этажных узлов {detailInfo.floors}, фасад {detailInfo.building}, мебель {detailInfo.furniture}</span>}
                <button className="small" disabled={busy} onClick={remove}>Удалить</button>
              </div>
              <div className="params">
                <label><span>Сдвиг X, м</span><input className="num" value={det.x} onChange={(e) => updDet({ x: e.target.value })} /></label>
                <label><span>Сдвиг Y (вверх), м</span><input className="num" value={det.y} onChange={(e) => updDet({ y: e.target.value })} /></label>
                <label><span>Сдвиг Z, м</span><input className="num" value={det.z} onChange={(e) => updDet({ z: e.target.value })} /></label>
                <label><span>Поворот, °</span><input className="num" value={det.rotation} onChange={(e) => updDet({ rotation: e.target.value })} /></label>
                <label><span>Масштаб</span><input className="num" value={det.scale} onChange={(e) => updDet({ scale: e.target.value })} /></label>
              </div>
            </>
          ) : null}
          <label className="file-btn">
            <input type="file" accept=".glb" hidden disabled={busy} onChange={(e) => upload(e.target.files?.[0])} />
            <span className="button small">{view.detail?.file ? 'Заменить GLB…' : 'Загрузить GLB…'}</span>
          </label>
          {err && <p className="error">{err}</p>}
        </div>
        <footer>
          <button onClick={onClose}>Отмена</button>
          <button className="primary" disabled={busy} onClick={save}>Сохранить</button>
        </footer>
      </div>
    </div>
  )
}
