import type * as React from 'react'
import { cn } from '@/lib/utils'

/** The browser's own select, styled: reliable on touch screens and with long lists. */
export function Select({ className, ...props }: React.ComponentProps<'select'>) {
  return (
    <select
      className={cn('h-8 min-w-0 cursor-pointer rounded-md border border-input bg-card px-2 py-0 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50', className)}
      {...props}
    />
  )
}
