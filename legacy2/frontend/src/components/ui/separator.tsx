import { Separator as Sep } from 'radix-ui'
import type * as React from 'react'
import { cn } from '@/lib/utils'

export function Separator({ className, orientation = 'horizontal', ...props }: React.ComponentProps<typeof Sep.Root>) {
  return <Sep.Root orientation={orientation} decorative
    className={cn('shrink-0 bg-border', orientation === 'horizontal' ? 'h-px w-full' : 'h-full w-px', className)} {...props} />
}
