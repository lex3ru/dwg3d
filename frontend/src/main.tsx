import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { loadCatalog } from './furniture/catalog'
import { loadMe } from './session'
import Login from './ui/Login'

const root = createRoot(document.getElementById('root')!)

// the user and the catalog are small and read synchronously everywhere: fetch them before the first render
async function start() {
  const user = await loadMe().catch(() => undefined)      // undefined: server unreachable, let the app report it
  if (user === null) {
    root.render(<StrictMode><Login onDone={start} /></StrictMode>)
    return
  }
  await loadCatalog()
  root.render(<StrictMode><App /></StrictMode>)
}
start()
