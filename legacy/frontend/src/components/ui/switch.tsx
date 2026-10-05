import { Switch as Sw } from 'radix-ui'
import type * as React from 'react'
import { cn } from '@/lib/utils'

export function Switch({ className, ...props }: React.ComponentProps<typeof Sw.Root>) {
  return (
    <Sw.Root className={cn('inline-flex h-4.5 w-8 shrink-0 cursor-pointer items-center rounded-full border border-transparent bg-input outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring data-[state=checked]:bg-primary disabled:opacity-50', className)} {...props}>
      <Sw.Thumb className="block size-3.5 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[16px]" />
    </Sw.Root>
  )
}
