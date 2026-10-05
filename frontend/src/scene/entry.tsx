import { useEffect, useState } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'
import App from './App'
import { setAdmin } from './compat'
import { loadCatalog } from './furniture/catalog'
import { loadMe } from './session'

/**
 * The viewer of a drawing (#/f/<drawing>/…): the 3D scene, the 2D plan, the
 * plan editor — carried over from the single-application version. The user
 * and the catalog are read synchronously all over it, so both are loaded
 * before it renders.
 */
export default function Scene({ editable }: { editable: boolean }) {
  setAdmin(editable)
  const [ready, setReady] = useState(false)
  useEffect(() => {
    Promise.all([loadMe().catch(() => undefined), loadCatalog()]).then(() => setReady(true))
  }, [])
  return ready ? <TooltipProvider><App /></TooltipProvider> : null
}
