import { X } from 'lucide-react'
import { Dialog as D } from 'radix-ui'
import type * as React from 'react'
import { cn } from '@/lib/utils'

export const Dialog = D.Root
export const DialogTrigger = D.Trigger
export const DialogClose = D.Close

export function DialogContent({ className, children, ...props }: React.ComponentProps<typeof D.Content>) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-[90] bg-black/40 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
      <D.Content
        className={cn('fixed top-1/2 left-1/2 z-[91] grid w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 rounded-xl border border-border bg-popover p-5 text-popover-foreground shadow-xl outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95', className)}
        {...props}>
        {children}
        <D.Close aria-label="Закрыть" className="absolute top-3 right-3 inline-flex size-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-muted-foreground hover:bg-secondary hover:text-foreground">
          <X className="size-4" />
        </D.Close>
      </D.Content>
    </D.Portal>
  )
}
export const DialogHeader = ({ className, ...p }: React.ComponentProps<'div'>) => <div className={cn('grid gap-1', className)} {...p} />
export const DialogFooter = ({ className, ...p }: React.ComponentProps<'div'>) => <div className={cn('flex justify-end gap-2', className)} {...p} />
export const DialogTitle = ({ className, ...p }: React.ComponentProps<typeof D.Title>) => <D.Title className={cn('text-base font-semibold', className)} {...p} />
export const DialogDescription = ({ className, ...p }: React.ComponentProps<typeof D.Description>) => <D.Description className={cn('text-sm text-muted-foreground', className)} {...p} />
