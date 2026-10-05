import type * as React from 'react'
import { cn } from '@/lib/utils'

/** The glass look of the controls floating over the scene. */
export const floatClass = 'border border-float-border bg-float text-foreground shadow-md backdrop-blur'

export function Float({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn(floatClass, className)} {...props} />
}
