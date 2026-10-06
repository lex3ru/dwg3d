import { useEffect, useRef } from 'react'

const users = new WeakMap<object, number>()

/** Free `thing` (GPU buffers, materials) when no mounted component uses it any more. Not on the unmount React does
 * in development (StrictMode) right before mounting again with the same thing: freed then, materials dropped out
 * of their list and kept the clipping planes of the floor shown before, so the models of another floor were cut
 * away, and instanced meshes were drawn empty. */
export function useFreeWhenUnused(thing: object, free: () => void) {
  const freeRef = useRef(free)
  freeRef.current = free
  useEffect(() => {
    users.set(thing, (users.get(thing) ?? 0) + 1)
    return () => {
      users.set(thing, (users.get(thing) ?? 1) - 1)
      setTimeout(() => { if (!users.get(thing)) freeRef.current() }, 0)
    }
  }, [thing])
}
