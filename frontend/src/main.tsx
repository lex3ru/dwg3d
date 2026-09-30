import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { loadCatalog } from './furniture/catalog'

// the catalog is small and read synchronously everywhere: fetch it before the first render
loadCatalog().finally(() => createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
))
