import { useState } from 'react'
import { signIn } from '../session'

/** Sign-in screen shown when the server asks for it (401 from /api/auth/me). */
export default function Login({ onDone }: { onDone: () => void }) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      await signIn(login, password)
      onDone()
    } catch (ex) {
      setErr((ex as Error).message)
      setBusy(false)
    }
  }
  return (
    <div className="upload-screen">
      <form className="login-card" onSubmit={submit}>
        <h1>Поэтажные планы → 3D</h1>
        <p className="hint">Войдите, чтобы открыть проекты.</p>
        <label>Логин
          <input autoFocus autoComplete="username" value={login} onChange={(e) => setLogin(e.target.value)} />
        </label>
        <label>Пароль
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {err && <p className="error">{err}</p>}
        <button className="primary" disabled={busy || !login || !password}>{busy ? 'Вход…' : 'Войти'}</button>
      </form>
    </div>
  )
}
