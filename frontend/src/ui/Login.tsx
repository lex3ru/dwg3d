import { signIn } from '../session'

/** Sign-in screen shown when the server asks for it (401 from /api/auth/me): sign-in is in Keycloak. */
export default function Login({ error }: { error?: string }) {
  return (
    <div className="upload-screen">
      <div className="login-card">
        <h1>Поэтажные планы → 3D</h1>
        <p className="hint">Войдите, чтобы открыть проекты.</p>
        {error && <p className="error">{error}</p>}
        <button className="primary" autoFocus onClick={signIn}>Войти</button>
      </div>
    </div>
  )
}
