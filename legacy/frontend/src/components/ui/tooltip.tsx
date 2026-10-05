import { Tooltip as Tt } from 'radix-ui'
import type * as React from 'react'
import { cn } from '@/lib/utils'

export const TooltipProvider = ({ delayDuration = 400, ...p }: React.ComponentProps<typeof Tt.Provider>) =>
  <Tt.Provider delayDuration={delayDuration} {...p} />

/** <Tip label="Text"><button/></Tip> */
export function Tip({ label, children, side = 'top' }: { label: React.ReactNode; children: React.ReactElement; side?: 'top' | 'bottom' | 'left' | 'right' }) {
  if (!label) return children
  return (
    <Tt.Root>
      <Tt.Trigger asChild>{children}</Tt.Trigger>
      <Tt.Portal>
        <Tt.Content side={side} sideOffset={6}
          className={cn('z-[100] max-w-72 rounded-md bg-foreground px-2 py-1 text-xs text-background shadow-md animate-in fade-in-0 zoom-in-95')}>
          {label}
        </Tt.Content>
      </Tt.Portal>
    </Tt.Root>
  )
}
