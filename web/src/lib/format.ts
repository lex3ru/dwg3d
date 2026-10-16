const dateTime = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
});
const time = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" });
const day = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric" });

export const formatDateTime = (iso: string | null | undefined) =>
  iso ? dateTime.format(new Date(iso)) : "—";
export const formatTime = (iso: string) => time.format(new Date(iso));
export const formatDay = (iso: string) => day.format(new Date(iso));

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: unit ? 1 : 0 })} ${units[unit]}`;
}
