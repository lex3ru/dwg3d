import type { ProjectEvent } from '../api'

/**
 * Live changes of a project used to come over its own event stream. The new
 * stream (/api/stream) carries events of the services; the viewer is switched
 * to it together with the objects it shows (stage 4). Until then there is
 * nothing to hear — while a build runs the viewer polls it.
 */
export function useProjectEvents(_projectId: string, _on: (ev: ProjectEvent) => void) {}
