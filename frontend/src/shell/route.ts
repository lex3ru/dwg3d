import { useEffect, useState } from 'react'

// Every screen has an address (the part after #):
//
//   /buildings                         the buildings one may see
//   /b/<building>                      «Кабинет» of a building
//   /b/<building>/rooms[/<room>]       rooms; with a room — its card is open
//   /b/<building>/assets[/<asset>]     objects; with one — its card is open
//   /b/<building>/plan[/<floor>][/<room>]   the 2D plan of a floor
//   /b/<building>/drawings             drawings (the building's administrator)
//   /b/<building>/people, /access      the directory of people; who may do what in the building
//   /f/<drawing>/…                     the editor: the 3D / 2D scene of a drawing
//   /catalog[/types/<id>|/sets/<id>]   the catalog (the system administrator; «new» instead of an id — a new one)
//   /q/<code>                          a QR label: leads to the card of its object (or «нет доступа»)
//   /scan                              the camera reads a QR label
//   /me                                the user (on a phone: also what the menu holds)
//   /system                            the state of the services (the system administrator)

export type Section = 'home' | 'rooms' | 'assets' | 'plan' | 'drawings' | 'people' | 'access'
export type Route =
  | { page: 'buildings' }
  | { page: 'building'; building: string; section: Section; item?: string; sub?: string; q?: string
      /** on the plan: the object being moved */ move?: string }
  | { page: 'editor'; drawing: string }
  | { page: 'me' }
  | { page: 'qr'; code: string }
  | { page: 'scan' }
  | { page: 'catalog'; kind?: 'types' | 'sets'; item?: string }
  | { page: 'system' }

export function parseRoute(hash: string): Route {
  const [path, query = ''] = hash.replace(/^#\/?/, '').split('?')
  const [first, second, third, fourth, fifth] = path.split('/')
  if (first === 'f' && second) return { page: 'editor', drawing: second }
  if (first === 'p' && second) return { page: 'building', building: second, section: 'drawings' }     // the old address
  if (first === 'b' && second) {
    const sections: Section[] = ['rooms', 'assets', 'plan', 'drawings', 'people', 'access']
    const section: Section = sections.includes(third as Section) ? third as Section : 'home'
    return { page: 'building', building: second, section, item: fourth || undefined, sub: fifth || undefined,
      q: new URLSearchParams(query).get('q') ?? undefined, move: new URLSearchParams(query).get('move') ?? undefined }
  }
  if (first === 'catalog') return { page: 'catalog', kind: second === 'sets' ? 'sets' : second === 'types' ? 'types' : undefined, item: third || undefined }
  if (first === 'q' && second) return { page: 'qr', code: second }
  if (first === 'scan') return { page: 'scan' }
  if (first === 'system' || first === 'me') return { page: first }
  return { page: 'buildings' }
}

export const to = {
  buildings: '#/buildings',
  home: (b: string) => `#/b/${b}`,
  rooms: (b: string, room?: string, q?: string) => `#/b/${b}/rooms${room ? `/${room}` : ''}${q ? `?q=${encodeURIComponent(q)}` : ''}`,
  assets: (b: string, asset?: string, q?: string) => `#/b/${b}/assets${asset ? `/${asset}` : ''}${q ? `?q=${encodeURIComponent(q)}` : ''}`,
  qr: (code: string) => `#/q/${code}`,
  scan: '#/scan',
  plan: (b: string, floor?: string, room?: string) => `#/b/${b}/plan${floor ? `/${floor}` : ''}${floor && room ? `/${room}` : ''}`,
  move: (b: string, floor: string, asset: string) => `#/b/${b}/plan/${floor}?move=${asset}`,
  drawings: (b: string) => `#/b/${b}/drawings`,
  people: (b: string) => `#/b/${b}/people`,
  access: (b: string) => `#/b/${b}/access`,
  editor: (drawing: string) => `#/f/${drawing}`,
}

export function useRoute(): Route {
  const [hash, set] = useState(location.hash)
  useEffect(() => {
    const on = () => set(location.hash)
    addEventListener('hashchange', on)
    return () => removeEventListener('hashchange', on)
  }, [])
  return parseRoute(hash)
}
