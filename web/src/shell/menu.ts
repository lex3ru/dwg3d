import {
  BarChart3, BookOpen, Building2, ClipboardCheck, DoorOpen, FileText, FolderKanban, History,
  House, Link2, Package, PencilRuler, Settings, Users, Video, Warehouse, type LucideIcon,
} from "lucide-react";
import type { Role } from "@/lib/types";

export interface MenuItem {
  path: string;
  title: string;
  icon: LucideIcon;
  group?: string;
  roles: Role[];
  // этап ТЗ (10.1), на котором раздел появляется; пока его нет — заглушка с описанием
  stage: number;
  about: string;
  // название пункта для «просмотра», если отличается (6.4)
  viewerTitle?: string;
}

// Меню — по 6.4. Действие, недоступное роли, не показывается вовсе (2.3).
export const MENU: MenuItem[] = [
  { path: "/", title: "Главная", icon: House, roles: ["admin"], stage: 9,
    about: "Что требует внимания (неисправные, в ремонте, неразмещённые, не найденные, освещённость ниже нормы, расхождения плана и учёта), стоимость имущества, сводка и последние документы (6.5.1)." },
  { path: "/plan", title: "План и расстановка", viewerTitle: "План", icon: PencilRuler, group: "Планировка", roles: ["admin", "viewer"], stage: 1,
    about: "Редактор здания: строительство этажей в 2D и вид в 3D с прогулкой (этап 1), расстановка по слоям (этап 4), обзор камер и освещённость (этап 7) — 6.5.2." },
  { path: "/projects", title: "Проекты", icon: FolderKanban, group: "Планировка", roles: ["admin"], stage: 8,
    about: "Проекты будущих расстановок, сравнение, спецификация и смета, применение с выдачей со склада (6.5.7)." },
  { path: "/cameras", title: "Видеокамеры", icon: Video, group: "Видеонаблюдение", roles: ["admin", "viewer"], stage: 7,
    about: "Все камеры выбранного здания: просмотр потоков, подключение и переход к камере на плане." },
  { path: "/property", title: "Имущество", icon: Package, group: "Учёт имущества", roles: ["admin", "viewer"], stage: 5,
    about: "Реестр инвентарных единиц с фильтрами и карточкой: состояние, место, ответственный, стоимость, история (6.5.4)." },
  { path: "/warehouse", title: "Склад", icon: Warehouse, group: "Учёт имущества", roles: ["admin"], stage: 5,
    about: "Места хранения и остатки на дату (6.5.5)." },
  { path: "/documents", title: "Документы", icon: FileText, group: "Учёт имущества", roles: ["admin"], stage: 5,
    about: "Ввод остатков, приход, перемещение, ремонт, списание, переоценка: черновик → проведён, печатные формы (6.5.6)." },
  { path: "/inventory", title: "Инвентаризация", icon: ClipboardCheck, group: "Учёт имущества", roles: ["admin"], stage: 9,
    about: "Ведомости и обход с телефона по QR-меткам (6.5.8)." },
  { path: "/reports", title: "Отчёты", icon: BarChart3, roles: ["admin"], stage: 9,
    about: "Все отчёты 5.6: выбор, параметры, выгрузка в Excel и PDF." },
  { path: "/catalog", title: "Каталог", icon: BookOpen, group: "Справочники", roles: ["admin"], stage: 3,
    about: "Слои, типы, модели, наборы характеристик, 3D-модели; базовый каталог медицинского учреждения (6.5.9)." },
  { path: "/purposes", title: "Назначения помещений", icon: DoorOpen, group: "Справочники", roles: ["admin"], stage: 3,
    about: "Назначения помещений с нормами освещённости и высотой рабочей поверхности (5.2)." },
  { path: "/buildings", title: "Здания", icon: Building2, group: "Управление", roles: ["admin"], stage: 1,
    about: "Здания, этажи и чертежи (5.1.1–5.1.3)." },
  { path: "/users", title: "Пользователи", icon: Users, group: "Управление", roles: ["admin"], stage: 0,
    about: "Учётные записи и доступ к зданиям (6.5.10)." },
  { path: "/links", title: "Ссылки на просмотр", icon: Link2, group: "Управление", roles: ["admin"], stage: 9,
    about: "Ссылки гостям на план и 3D здания: срок действия, досрочный отзыв (5.7.2)." },
  { path: "/journal", title: "Журнал", icon: History, group: "Управление", roles: ["admin"], stage: 0,
    about: "Лента изменений с фильтрами (5.7.3)." },
  { path: "/settings", title: "Настройки", icon: Settings, group: "Управление", roles: ["admin"], stage: 0,
    about: "Название учреждения, срок хранения журнала, состояние сервера; позже — вид инвентарного номера, наклейки, пороги камер, освещённость." },
];

export const STAGES: Record<number, string> = {
  0: "Каркас", 1: "Здание и план", 2: "Перевод чертежей", 3: "Каталог", 4: "Расстановка",
  5: "Учёт имущества", 6: "Связь и телефон", 7: "Расчёты", 8: "Проекты",
  9: "Инвентаризация, отчёты, доступ", 10: "Итоговая приёмка",
};

export const menuFor = (role: Role) => MENU.filter((item) => item.roles.includes(role));
export const homeFor = (role: Role) => (role === "admin" ? "/" : "/plan");
export const titleFor = (item: MenuItem, role: Role) =>
  role === "viewer" && item.viewerTitle ? item.viewerTitle : item.title;

export function findItem(pathname: string): MenuItem | undefined {
  return MENU.filter((m) => m.path === "/" ? pathname === "/" : pathname.startsWith(m.path))
    .sort((a, b) => b.path.length - a.path.length)[0];
}
