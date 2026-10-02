import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { applyTheme } from './lib/theme'
import { loadCatalog } from './furniture/catalog'
import Root from './Root'
import { loadMe, openShare } from './session'
import Login from './ui/Login'

applyTheme()
const root = createRoot(document.getElementById('root')!)

// the user and the catalog are small and read synchronously everywhere: fetch them before the first render
async function start() {
  // a share link: #/s/<token> -> the project it opens
  const share = /^#\/s\/([^/?]+)/.exec(location.hash)
  if (share) {
    const pid = await openShare(decodeURIComponent(share[1])).catch(() => null)
    if (!pid) {
      root.render(<StrictMode><Login error="Ссылка недействительна: её отозвали, срок истёк или проект удалён." /></StrictMode>)
      return
    }
    history.replaceState(null, '', `${location.pathname}#/p/${pid}`)
  }
  const user = await loadMe().catch(() => undefined)      // undefined: server unreachable, let the app report it
  if (user === null) {
    root.render(<StrictMode><Login /></StrictMode>)
    return
  }
  await loadCatalog()
  root.render(<StrictMode><Root /></StrictMode>)
}
start()
