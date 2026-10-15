/** Basemap source and sky colours (shared by the map layer and the UI). */
import type { DayTime } from '../state'

/** Basemap with street names: standard OpenStreetMap raster tiles, shown
 * desaturated and lightened by the tile shader. Any XYZ raster source can be
 * set per job (site.tiles / site.attribution); the attribution must match it.
 * The OSM tile servers are for light use only (tile usage policy): for a
 * public deployment point `tiles` to your own or a commercial tile service. */
export const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
export const TILE_SUBDOMAINS = ['a', 'b', 'c', 'd']
export const TILE_ATTRIBUTION = '© участники OpenStreetMap'
export const MAP_BG = '#f2efe9'

/** multiplier of the map colours by time of day */
export const DAY_TINT: Record<DayTime, string> = { day: '#ffffff', evening: '#b8a79a', night: '#4b5068' }

/** sky gradient: zenith, horizon */
export const SKY: Record<DayTime, [string, string]> = {
  day: ['#7fb6f0', '#eef4fa'],
  evening: ['#2f3a66', '#f2a36a'],
  night: ['#060a18', '#1c2544'],
}

/** The scene in a dark page: a dusk-grey day. Evening and night are dark already. */
export function skyColors(dayTime: DayTime, dark: boolean): [string, string] {
  return dark && dayTime === 'day' ? ['#1c2230', '#3b465c'] : SKY[dayTime]
}
export const GROUND = { light: '#e9ecef', dark: '#2a303c' }
export const PAGE_2D = { light: '#f4f5f7', dark: '#1a1d23' }
