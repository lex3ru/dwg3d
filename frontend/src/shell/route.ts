import { useEffect, useState } from 'react'

// Every screen has an address (the part after #):
//
//   /buildings                         the buildings one may see
//   /b/<building>                      «Кабинет» of a building
//   /b/<building>/rooms[/<room>]       rooms; with a room — its card is open
//   /b/<building>/plan[/<floor>][/<room>]   the 2D plan of a floor
//   /b/<building>/drawings             drawings (the building's administrator)
//   /f/<drawing>/…                     the editor: the 3D / 2D scene of a drawing
//   /me                                the user (on a phone: also what the menu holds)
//   /system                            the state of the services (the system administrator)

export type Section = 'home' | 'rooms' | 'plan' | 'drawings'
export type Route =
  | { page: 'buildings' }
  | { page: 'building'; building: string; section: Section; item?: string; sub?: string; q?: string }
  | { page: 'editor'; drawing: string }
  | { page: 'me' }
  | { page: 'system' }

export function parseRoute(hash: string): Route {
  const [path, query = ''] = hash.replace(/^#\/?/, '').split('?')
  const [first, second, third, fourth, fifth] = path.split('/')
  if (first === 'f' && second) return { page: 'editor', drawing: second }
  if (first === 'p' && second) return { page: 'building', building: second, section: 'drawings' }     // the old address
  if (first === 'b' && second) {
    const section: Section = third === 'rooms' || third === 'plan' || third === 'drawings' ? third : 'home'
    return { page: 'building', building: second, section, item: fourth || undefined, sub: fifth || undefined,
      q: new URLSearchParams(query).get('q') ?? undefined }
  }
  if (first === 'system' || first === 'me') return { page: first }
  return { page: 'buildings' }
}

export const to = {
  buildings: '#/buildings',
  home: (b: string) => `#/b/${b}`,
  rooms: (b: string, room?: string, q?: string) => `#/b/${b}/rooms${room ? `/${room}` : ''}${q ? `?q=${encodeURIComponent(q)}` : ''}`,
  plan: (b: string, floor?: string, room?: string) => `#/b/${b}/plan${floor ? `/${floor}` : ''}${floor && room ? `/${room}` : ''}`,
  drawings: (b: string) => `#/b/${b}/drawings`,
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
