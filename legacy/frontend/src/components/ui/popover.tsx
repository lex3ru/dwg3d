import { Popover as P } from 'radix-ui'
import type * as React from 'react'
import { cn } from '@/lib/utils'

export const Popover = P.Root
export const PopoverTrigger = P.Trigger

export function PopoverContent({ className, align = 'end', sideOffset = 8, ...props }: React.ComponentProps<typeof P.Content>) {
  return (
    <P.Portal>
      <P.Content align={align} sideOffset={sideOffset}
        className={cn('z-[100] max-h-[var(--radix-popover-content-available-height)] overflow-y-auto rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-lg outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95', className)}
        {...props} />
    </P.Portal>
  )
}
