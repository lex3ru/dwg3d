import { to } from '../shell/route'

/** Where a copilot link leads: a place in the system, a report, or outside. */
export function hrefOf(target: string, building: string | null): string | null {
  const [kind, id] = target.split(':', 2)
  if (kind === 'room' && id) return building ? to.rooms(building, id) : null
  if (kind === 'asset' && id) return building ? to.assets(building, id) : null
  if (kind === 'variant' && id) return building ? to.variants(building, id) : null
  if (kind === 'person') return building ? to.people(building) : null
  if (kind === 'floor' && id) return building ? to.plan(building, id) : null
  if (target.startsWith('#/') || target.startsWith('/api/') || /^https?:\/\//.test(target)) return target
  return null
}
