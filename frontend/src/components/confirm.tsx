import { useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

export interface ConfirmOptions {
  title: string
  text?: ReactNode
  confirm?: string
  danger?: boolean
  /** the user must type this to confirm (deleting a project) */
  typed?: string
}

/**
 * `const [ask, dialog] = useConfirm()`: render `dialog` once, then
 * `if (await ask({ title: ... })) ...` instead of window.confirm.
 */
export function useConfirm() {
  const [st, setSt] = useState<(ConfirmOptions & { resolve: (ok: boolean) => void }) | null>(null)
  const [typed, setTyped] = useState('')
  const ask = (o: ConfirmOptions) => new Promise<boolean>((resolve) => { setTyped(''); setSt({ ...o, resolve }) })
  const close = (ok: boolean) => { st?.resolve(ok); setSt(null) }
  const dialog = (
    <Dialog open={!!st} onOpenChange={(o) => { if (!o) close(false) }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{st?.title}</DialogTitle>
          {st?.text && <DialogDescription>{st.text}</DialogDescription>}
        </DialogHeader>
        {st?.typed && <Input autoFocus value={typed} placeholder={st.typed} onChange={(e) => setTyped(e.target.value)} />}
        <DialogFooter>
          <Button variant="secondary" onClick={() => close(false)}>Отмена</Button>
          <Button variant={st?.danger ? 'destructive' : 'default'} disabled={!!st?.typed && typed !== st.typed} onClick={() => close(true)}>
            {st?.confirm ?? 'Подтвердить'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
  return [ask, dialog] as const
}
