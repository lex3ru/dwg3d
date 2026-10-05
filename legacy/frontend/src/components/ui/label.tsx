import type * as React from 'react'
import { cn } from '@/lib/utils'

export function Label({ className, ...props }: React.ComponentProps<'label'>) {
  return <label className={cn('grid gap-1.5 text-sm font-medium text-foreground', className)} {...props} />
}
