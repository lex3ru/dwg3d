import { Box, LogIn } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { signIn } from '../session'

/** Sign-in screen shown when the server asks for it (401 from /api/auth/me): sign-in is in Keycloak. */
export default function Login({ error }: { error?: string }) {
  return (
    <div className="grid min-h-full place-items-center bg-background p-4 text-foreground">
      <div className="grid w-full max-w-sm gap-4 rounded-2xl border border-border bg-card p-8 shadow-sm">
        <span className="grid size-10 place-items-center rounded-xl bg-accent text-accent-foreground"><Box className="size-5" /></span>
        <div className="grid gap-1">
          <h1 className="m-0 text-xl font-semibold">Поэтажные планы → 3D</h1>
          <p className="m-0 text-sm text-muted-foreground">Войдите, чтобы открыть проекты.</p>
        </div>
        {error && <p className="m-0 text-sm text-destructive">{error}</p>}
        <Button size="lg" autoFocus onClick={signIn}><LogIn /> Войти</Button>
      </div>
    </div>
  )
}
