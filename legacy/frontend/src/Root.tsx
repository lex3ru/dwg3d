import { useEffect, useState } from 'react'
import App from './App.tsx'
import { me } from './session'
import { TooltipProvider } from '@/components/ui/tooltip'
import ProjectPage from './ui/project/ProjectPage'
import Projects from './ui/Projects'

/** Pages by the URL hash: #/ projects, #/p/<id> a project, #/f/<drawing>/... the viewer. */
export default function Root() {
  const [hash, setHash] = useState(location.hash)
  useEffect(() => {
    const on = () => setHash(location.hash)
    window.addEventListener('hashchange', on)
    window.addEventListener('popstate', on)
    return () => { window.removeEventListener('hashchange', on); window.removeEventListener('popstate', on) }
  }, [])
  const page = (() => {
    if (hash.startsWith('#/f/') || new URLSearchParams(location.search).get('job')) return <App />
    const m = /^#\/p\/([^/?]+)(?:\/([a-z]+))?/.exec(hash)
    const pid = m?.[1] ?? me?.guest?.project_id
    if (pid) return <ProjectPage key={pid} pid={pid} section={m?.[2]} />
    return <Projects />
  })()
  return <TooltipProvider>{page}</TooltipProvider>
}

