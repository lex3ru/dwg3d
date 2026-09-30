import { useEffect, useState } from 'react'
import App from './App.tsx'
import { me } from './session'
import ProjectPage from './ui/ProjectPage'
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
  if (hash.startsWith('#/f/') || new URLSearchParams(location.search).get('job')) return <App />
  const pid = /^#\/p\/([^/?]+)/.exec(hash)?.[1] ?? me?.guest?.project_id
  if (pid) return <ProjectPage key={pid} pid={pid} />
  return <Projects />
}

