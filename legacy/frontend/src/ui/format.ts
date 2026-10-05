/** Russian plural form: plural(n, 'чертёж', 'чертежа', 'чертежей'). */
export const plural = (n: number, one: string, few: string, many: string) => {
  const m10 = n % 10, m100 = n % 100
  return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many
}

/** A date from a UNIX timestamp (s), or a dash. */
export const fmtDate = (t: number | null | undefined) => (t ? new Date(t * 1000).toLocaleDateString('ru-RU') : '—')
