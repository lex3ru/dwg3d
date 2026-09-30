/** Catalog of furniture and equipment for medical centres.
 *
 * Sizes are meters: w — width (local X), d — depth (local Z, the front faces
 * +Z, i.e. away from the wall), h — height. `clear` is the service zone in
 * front of the item (where a person stands or sits to use it), `wall` — the
 * item is normally placed back to a wall, `elev` — mounting height of the
 * bottom (wall-hung items). `kind` selects the procedural model used when no
 * GLB `model` is given (or while it loads).
 *
 * GLB models under public/catalog/kenney/ — Kenney Furniture Kit 2.0,
 * CC0 (www.kenney.nl, see License.txt there); their front faces +Z. */

export interface CatalogItem {
  id: string
  name: string
  cat: string
  w: number
  d: number
  h: number
  kind: string
  color?: string
  clear?: number
  wall?: boolean
  elev?: number
  /** GLB under /catalog/, scaled to w×d×h; `modelRot` turns it (deg) so its front faces +Z */
  model?: string
  modelRot?: number
  tags?: string
  /** CCTV camera: horizontal view angle (deg, 360 = panoramic), range and
   * face identification distance (m); it looks along its front (+Z) */
  cam?: { fov: number; range: number; ident: number }
}

export interface Category { id: string; name: string; color: string }

export const CATEGORIES: Category[] = [
  { id: 'reception', name: 'Регистратура и ожидание', color: '#1c7ed6' },
  { id: 'doctor', name: 'Кабинет врача', color: '#0ca678' },
  { id: 'procedure', name: 'Процедурная', color: '#f08c00' },
  { id: 'dental', name: 'Стоматология', color: '#7048e8' },
  { id: 'diagnostics', name: 'Диагностика и лаборатория', color: '#d6336c' },
  { id: 'ward', name: 'Палата и перемещение', color: '#1098ad' },
  { id: 'sanitary', name: 'Санузел', color: '#74b816' },
  { id: 'storage', name: 'Хранение и офис', color: '#868e96' },
  { id: 'engineering', name: 'Инженерное оборудование', color: '#495057' },
  { id: 'security', name: 'Видеонаблюдение', color: '#7048e8' },
]

const UPH = '#20c997'          // upholstery
const WHITE = '#f1f3f5'
const WOOD = '#d2b48c'

export const CATALOG: CatalogItem[] = [
  // ---- reception & waiting
  { id: 'rec.desk', name: 'Стойка регистратуры', cat: 'reception', w: 2.0, d: 0.8, h: 1.1, kind: 'reception', color: WOOD, clear: 1.0, tags: 'ресепшн администратор' },
  { id: 'rec.seats3', name: 'Секция кресел ожидания, 3 места', cat: 'reception', w: 1.7, d: 0.6, h: 0.8, kind: 'seats', color: UPH, clear: 0.6, wall: true, tags: 'стулья ряд' },
  { id: 'rec.seats4', name: 'Секция кресел ожидания, 4 места', cat: 'reception', w: 2.25, d: 0.6, h: 0.8, kind: 'seats', color: UPH, clear: 0.6, wall: true, tags: 'стулья ряд' },
  { id: 'rec.sofa', name: 'Диван, 2 места', cat: 'reception', w: 1.4, d: 0.75, h: 0.8, kind: 'sofa', color: '#339af0', clear: 0.6, wall: true, model: 'kenney/loungeSofa.glb' },
  { id: 'rec.table', name: 'Журнальный столик', cat: 'reception', w: 0.8, d: 0.5, h: 0.45, kind: 'table', color: WOOD, model: 'kenney/tableCoffee.glb' },
  { id: 'rec.cooler', name: 'Кулер для воды', cat: 'reception', w: 0.33, d: 0.33, h: 1.1, kind: 'cooler', clear: 0.5, wall: true },
  { id: 'rec.kiosk', name: 'Инфокиоск / терминал очереди', cat: 'reception', w: 0.5, d: 0.45, h: 1.5, kind: 'kiosk', clear: 0.7, tags: 'электронная очередь' },
  { id: 'rec.wardrobe', name: 'Гардеробная стойка', cat: 'reception', w: 1.5, d: 0.6, h: 1.8, kind: 'rack', color: '#adb5bd', clear: 0.8, wall: true, tags: 'вешалка' },
  { id: 'rec.armchair', name: 'Кресло мягкое', cat: 'reception', w: 0.75, d: 0.75, h: 0.8, kind: 'sofa', color: '#339af0', clear: 0.5, wall: true, model: 'kenney/loungeChair.glb' },
  { id: 'rec.coatrack', name: 'Вешалка напольная', cat: 'reception', w: 0.5, d: 0.5, h: 1.8, kind: 'iv', color: '#8d6e63', model: 'kenney/coatRackStanding.glb', tags: 'гардероб' },
  { id: 'rec.plant', name: 'Растение в кашпо', cat: 'reception', w: 0.5, d: 0.5, h: 1.2, kind: 'plant', model: 'kenney/pottedPlant.glb' },
  { id: 'rec.tv', name: 'Телевизор / инфоэкран на стене', cat: 'reception', w: 1.1, d: 0.08, h: 0.65, kind: 'screen_tv', elev: 1.6, wall: true },

  // ---- doctor's office
  { id: 'doc.desk', name: 'Стол врача с компьютером', cat: 'doctor', w: 1.4, d: 0.7, h: 0.75, kind: 'desk_pc', color: WOOD, clear: 0.8, wall: true },
  { id: 'doc.desk_corner', name: 'Стол письменный', cat: 'doctor', w: 1.2, d: 0.6, h: 0.75, kind: 'desk', color: WOOD, clear: 0.8, wall: true, model: 'kenney/desk.glb' },
  { id: 'doc.chair', name: 'Кресло врача', cat: 'doctor', w: 0.6, d: 0.6, h: 1.05, kind: 'chair_office', color: '#343a40', model: 'kenney/chairDesk.glb' },
  { id: 'doc.visitor', name: 'Стул посетителя', cat: 'doctor', w: 0.5, d: 0.52, h: 0.85, kind: 'chair', color: UPH, model: 'kenney/chairCushion.glb' },
  { id: 'doc.couch', name: 'Кушетка смотровая', cat: 'doctor', w: 1.9, d: 0.65, h: 0.7, kind: 'couch', color: UPH, clear: 0.8, wall: true },
  { id: 'doc.screen', name: 'Ширма медицинская, 3 секции', cat: 'doctor', w: 1.6, d: 0.45, h: 1.7, kind: 'folding', color: '#e3fafc' },
  { id: 'doc.cab_med', name: 'Шкаф медицинский, стеклянный', cat: 'doctor', w: 0.6, d: 0.4, h: 1.75, kind: 'cabinet_glass', clear: 0.7, wall: true },
  { id: 'doc.sink', name: 'Раковина для мытья рук', cat: 'doctor', w: 0.55, d: 0.45, h: 0.85, kind: 'sink', clear: 0.6, wall: true, tags: 'умывальник', model: 'kenney/bathroomSink.glb' },
  { id: 'doc.recirc', name: 'Рециркулятор бактерицидный (настенный)', cat: 'doctor', w: 0.3, d: 0.15, h: 0.9, kind: 'device_wall', elev: 1.0, wall: true, tags: 'облучатель уф' },
  { id: 'doc.stadiometer', name: 'Ростомер с весами', cat: 'doctor', w: 0.45, d: 0.5, h: 2.05, kind: 'stadiometer', clear: 0.5, wall: true, tags: 'весы' },
  { id: 'doc.bin', name: 'Контейнер для медотходов', cat: 'doctor', w: 0.35, d: 0.35, h: 0.5, kind: 'bin', color: '#fab005', tags: 'мусор отходы' },

  // ---- procedure room
  { id: 'proc.table', name: 'Стол манипуляционный', cat: 'procedure', w: 0.7, d: 0.5, h: 0.85, kind: 'cart', clear: 0.6, tags: 'инструментальный' },
  { id: 'proc.cart', name: 'Тележка медицинская', cat: 'procedure', w: 0.6, d: 0.45, h: 0.9, kind: 'cart', color: '#a5d8ff' },
  { id: 'proc.iv', name: 'Штатив для капельниц', cat: 'procedure', w: 0.5, d: 0.5, h: 1.9, kind: 'iv', tags: 'инфузия' },
  { id: 'proc.chair', name: 'Кресло процедурное (забор крови)', cat: 'procedure', w: 0.7, d: 0.8, h: 1.1, kind: 'armchair_med', color: UPH, clear: 0.8 },
  { id: 'proc.fridge', name: 'Холодильник фармацевтический', cat: 'procedure', w: 0.6, d: 0.6, h: 1.5, kind: 'fridge', clear: 0.7, wall: true },
  { id: 'proc.autoclave', name: 'Стерилизатор / автоклав на тумбе', cat: 'procedure', w: 0.6, d: 0.55, h: 0.95, kind: 'device', clear: 0.7, wall: true },
  { id: 'proc.gyn', name: 'Кресло гинекологическое', cat: 'procedure', w: 0.7, d: 1.4, h: 1.2, kind: 'exam_chair', color: UPH, clear: 0.9 },

  // ---- dental
  { id: 'den.unit', name: 'Стоматологическая установка', cat: 'dental', w: 1.6, d: 2.0, h: 1.6, kind: 'dental', color: '#63e6be', clear: 0.9 },
  { id: 'den.stool', name: 'Стул стоматолога', cat: 'dental', w: 0.5, d: 0.5, h: 0.6, kind: 'stool', color: '#343a40' },
  { id: 'den.cabinet', name: 'Тумба с мойкой', cat: 'dental', w: 1.2, d: 0.5, h: 0.9, kind: 'counter_sink', clear: 0.7, wall: true },
  { id: 'den.cabinet2', name: 'Тумба медицинская', cat: 'dental', w: 0.8, d: 0.5, h: 0.9, kind: 'counter', clear: 0.7, wall: true },
  { id: 'den.xray', name: 'Рентген дентальный (настенный)', cat: 'dental', w: 0.4, d: 0.5, h: 0.35, kind: 'device_wall', elev: 1.4, wall: true, color: '#e9ecef' },

  // ---- diagnostics & lab
  { id: 'diag.us', name: 'Аппарат УЗИ', cat: 'diagnostics', w: 0.6, d: 0.85, h: 1.45, kind: 'ultrasound', clear: 0.6 },
  { id: 'diag.ecg', name: 'Электрокардиограф на тележке', cat: 'diagnostics', w: 0.5, d: 0.45, h: 1.0, kind: 'cart', color: '#e9ecef', tags: 'экг' },
  { id: 'diag.xray', name: 'Рентгеновский стол со штативом', cat: 'diagnostics', w: 2.4, d: 1.0, h: 1.9, kind: 'xray', clear: 1.0 },
  { id: 'diag.ct', name: 'Компьютерный томограф (КТ)', cat: 'diagnostics', w: 2.2, d: 4.4, h: 1.95, kind: 'ct', color: '#4dabf7', clear: 1.0, tags: 'кт томограф рентген ct' },
  { id: 'diag.mri', name: 'Магнитно-резонансный томограф (МРТ) 1,5 Тл', cat: 'diagnostics', w: 2.3, d: 4.6, h: 2.3, kind: 'mri', color: '#7048e8', clear: 1.0, tags: 'мрт томограф mri магнит' },
  { id: 'diag.mri_cab', name: 'Шкафы электроники МРТ (техпомещение)', cat: 'diagnostics', w: 2.4, d: 0.8, h: 2.1, kind: 'server', clear: 1.0, wall: true, tags: 'мрт стойка градиентный усилитель' },
  { id: 'diag.console', name: 'Пульт оператора КТ / МРТ', cat: 'diagnostics', w: 1.6, d: 0.8, h: 0.75, kind: 'desk_pc', color: '#dee2e6', clear: 0.9, wall: true, tags: 'кт мрт рабочее место лаборанта' },
  { id: 'diag.injector', name: 'Инжектор контрастного вещества', cat: 'diagnostics', w: 0.6, d: 0.6, h: 1.5, kind: 'iv', color: '#e9ecef', tags: 'кт мрт контраст' },
  { id: 'diag.lab', name: 'Стол лабораторный', cat: 'diagnostics', w: 1.5, d: 0.75, h: 0.9, kind: 'counter', clear: 0.9, wall: true },
  { id: 'diag.hood', name: 'Бокс биологической безопасности', cat: 'diagnostics', w: 1.3, d: 0.8, h: 2.0, kind: 'hood', clear: 1.0, wall: true, tags: 'ламинар шкаф вытяжной' },
  { id: 'diag.centrifuge', name: 'Центрифуга настольная', cat: 'diagnostics', w: 0.4, d: 0.5, h: 0.3, kind: 'device', elev: 0.9, wall: true },

  // ---- ward & transport
  { id: 'ward.bed', name: 'Кровать функциональная', cat: 'ward', w: 1.0, d: 2.15, h: 0.9, kind: 'bed', clear: 0.9, wall: true, tags: 'койка' },
  { id: 'ward.night', name: 'Тумба прикроватная', cat: 'ward', w: 0.45, d: 0.45, h: 0.8, kind: 'nightstand', model: 'kenney/sideTableDrawers.glb' },
  { id: 'ward.wheelchair', name: 'Кресло-коляска', cat: 'ward', w: 0.65, d: 1.05, h: 0.95, kind: 'wheelchair', color: '#343a40', tags: 'инвалидная мгн' },
  { id: 'ward.gurney', name: 'Каталка', cat: 'ward', w: 0.7, d: 2.0, h: 0.9, kind: 'gurney', tags: 'носилки' },

  // ---- sanitary
  { id: 'san.toilet', name: 'Унитаз', cat: 'sanitary', w: 0.4, d: 0.7, h: 0.8, kind: 'toilet', clear: 0.6, wall: true, model: 'kenney/toilet.glb' },
  { id: 'san.sink', name: 'Раковина', cat: 'sanitary', w: 0.55, d: 0.45, h: 0.85, kind: 'sink', clear: 0.6, wall: true, model: 'kenney/bathroomSink.glb' },
  { id: 'san.accessible', name: 'Кабина для МГН (зона разворота Ø1,5 м)', cat: 'sanitary', w: 1.65, d: 1.8, h: 0.05, kind: 'zone', color: '#74c0fc', tags: 'инвалид колясочник' },

  // ---- storage & office
  { id: 'st.cabinet', name: 'Шкаф для документов', cat: 'storage', w: 0.8, d: 0.4, h: 1.9, kind: 'cabinet', color: WOOD, clear: 0.7, wall: true, model: 'kenney/bookcaseClosedWide.glb' },
  { id: 'st.wardrobe', name: 'Шкаф для одежды', cat: 'storage', w: 0.8, d: 0.55, h: 1.9, kind: 'cabinet', color: WHITE, clear: 0.7, wall: true, model: 'kenney/bookcaseClosedWide.glb' },
  { id: 'st.bookcase', name: 'Стеллаж открытый', cat: 'storage', w: 0.9, d: 0.35, h: 1.9, kind: 'rack', color: '#d2b48c', clear: 0.7, wall: true, model: 'kenney/bookcaseOpen.glb', tags: 'полки' },
  { id: 'st.shelf', name: 'Стеллаж металлический', cat: 'storage', w: 1.0, d: 0.5, h: 2.0, kind: 'rack', color: '#adb5bd', clear: 0.7, wall: true },
  { id: 'st.lockers', name: 'Шкаф для персонала (4 ячейки)', cat: 'storage', w: 0.8, d: 0.5, h: 1.8, kind: 'lockers', color: '#a5d8ff', clear: 0.7, wall: true },
  { id: 'st.meeting', name: 'Стол для совещаний', cat: 'storage', w: 2.4, d: 1.0, h: 0.75, kind: 'table', color: WOOD, model: 'kenney/table.glb' },
  { id: 'st.printer', name: 'МФУ на тумбе', cat: 'storage', w: 0.55, d: 0.5, h: 1.0, kind: 'device', color: '#dee2e6', clear: 0.6 },

  // ---- engineering
  { id: 'eng.panel', name: 'Электрощит', cat: 'engineering', w: 0.6, d: 0.2, h: 0.9, kind: 'panel', elev: 1.0, wall: true, clear: 0.8, tags: 'щиток' },
  { id: 'eng.rack', name: 'Серверный шкаф', cat: 'engineering', w: 0.6, d: 1.0, h: 2.0, kind: 'server', clear: 1.0, tags: 'стойка сеть' },
  { id: 'eng.ac', name: 'Кондиционер (внутренний блок)', cat: 'engineering', w: 0.9, d: 0.25, h: 0.3, kind: 'ac', elev: 2.3, wall: true, tags: 'сплит' },
  { id: 'eng.radiator', name: 'Радиатор отопления', cat: 'engineering', w: 1.0, d: 0.1, h: 0.5, kind: 'radiator', elev: 0.12, wall: true },
  { id: 'eng.fire', name: 'Огнетушитель', cat: 'engineering', w: 0.2, d: 0.2, h: 0.6, kind: 'extinguisher', wall: true },
  // ---- CCTV (the view is drawn on the floor, cut by walls)
  { id: 'sec.dome', name: 'Камера купольная (потолок)', cat: 'security', w: 0.14, d: 0.14, h: 0.1, kind: 'cam_dome', elev: 2.6, cam: { fov: 100, range: 12, ident: 4 }, tags: 'видеокамера cctv' },
  { id: 'sec.bullet', name: 'Камера цилиндрическая (настенная)', cat: 'security', w: 0.12, d: 0.3, h: 0.14, kind: 'cam_bullet', elev: 2.5, wall: true, cam: { fov: 90, range: 20, ident: 6 }, tags: 'видеокамера cctv' },
  { id: 'sec.tele', name: 'Камера с узким углом (коридор)', cat: 'security', w: 0.12, d: 0.35, h: 0.14, kind: 'cam_bullet', elev: 2.5, wall: true, cam: { fov: 35, range: 40, ident: 15 }, tags: 'видеокамера вариофокальная cctv' },
  { id: 'sec.fisheye', name: 'Камера панорамная 360°', cat: 'security', w: 0.16, d: 0.16, h: 0.06, kind: 'cam_fisheye', elev: 2.6, cam: { fov: 360, range: 8, ident: 2.5 }, tags: 'видеокамера fisheye рыбий глаз cctv' },
  { id: 'sec.ptz', name: 'Камера поворотная (PTZ)', cat: 'security', w: 0.22, d: 0.22, h: 0.3, kind: 'cam_ptz', elev: 2.4, cam: { fov: 60, range: 50, ident: 20 }, tags: 'видеокамера поворотная cctv' },
  { id: 'sec.nvr', name: 'Видеорегистратор в шкафу', cat: 'security', w: 0.6, d: 0.6, h: 1.2, kind: 'server', clear: 0.8, wall: true, tags: 'nvr' },
  { id: 'sec.monitor', name: 'Пост видеонаблюдения (стол с мониторами)', cat: 'security', w: 1.4, d: 0.7, h: 0.75, kind: 'desk_pc', color: '#adb5bd', clear: 0.8, wall: true, tags: 'охрана' },
  { id: 'eng.o2', name: 'Кислородный концентратор', cat: 'engineering', w: 0.4, d: 0.4, h: 0.7, kind: 'device', color: '#e9ecef' },
]

export const CATALOG_BY_ID = new Map(CATALOG.map((c) => [c.id, c]))

/** Stand-in for an item missing from the catalog (e.g. removed later). */
export function catalogItem(id: string): CatalogItem {
  return CATALOG_BY_ID.get(id) ?? { id, name: `Неизвестный предмет (${id})`, cat: 'storage', w: 0.5, d: 0.5, h: 0.5, kind: 'device' }
}
