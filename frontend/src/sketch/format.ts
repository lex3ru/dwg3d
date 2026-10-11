/** How the 2D editor writes sizes: lengths in whole centimetres, areas in m² with a comma. */
export const cmText = (m: number) => String(Math.round(m * 100))
export const areaText = (m2: number) => `${m2.toFixed(2).replace('.', ',')} м²`
