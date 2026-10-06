import { Tooltip as Tt } from 'radix-ui'
import * as React from 'react'
import { cn } from '@/lib/utils'

// Hints of the interface. A hint says what an element is FOR and what will happen — never its own label
// again: «Выдать ссылку» → «Ссылка, по которой посмотрят этаж без учётной записи; её покажут один раз».
// An icon without a label must have one. On a touch screen a hint opens on a long press.

export const TooltipProvider = ({ delayDuration = 400, ...p }: React.ComponentProps<typeof Tt.Provider>) =>
  <Tt.Provider delayDuration={delayDuration} {...p} />

const LONG_PRESS_MS = 500

/** <Tip label="What it is for"><button/></Tip>. A disabled control gets no pointer events: it is wrapped so
 * that its hint (why it is disabled, what it would do) still shows. */
export function Tip({ label, children, side = 'top' }: { label: React.ReactNode; children: React.ReactElement; side?: 'top' | 'bottom' | 'left' | 'right' }) {
  const [touched, setTouched] = React.useState(false)
  const timer = React.useRef<number | undefined>(undefined)
  React.useEffect(() => () => window.clearTimeout(timer.current), [])
  if (!label) return children
  const disabled = !!(children.props as { disabled?: boolean }).disabled
  const press = {
    onPointerDown: (e: React.PointerEvent) => {
      if (e.pointerType !== 'touch') return
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setTouched(true), LONG_PRESS_MS)
    },
    onPointerUp: () => window.clearTimeout(timer.current),
    onPointerCancel: () => window.clearTimeout(timer.current),
  }
  const trigger = disabled ? <span tabIndex={0} className="inline-flex" {...press}>{children}</span> : children
  return (
    <Tt.Root open={touched || undefined} onOpenChange={(open) => { if (!open) setTouched(false) }}>
      <Tt.Trigger asChild {...(disabled ? {} : press)}>{trigger}</Tt.Trigger>
      <Tt.Portal>
        <Tt.Content side={side} sideOffset={6} onPointerDownOutside={() => setTouched(false)}
          className={cn('z-[100] max-w-72 rounded-md bg-foreground px-2 py-1 text-xs text-background shadow-md animate-in fade-in-0 zoom-in-95')}>
          {label}
        </Tt.Content>
      </Tt.Portal>
    </Tt.Root>
  )
}
