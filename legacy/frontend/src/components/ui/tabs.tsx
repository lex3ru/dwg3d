import { Tabs as T } from 'radix-ui'
import type * as React from 'react'
import { cn } from '@/lib/utils'

export const Tabs = T.Root

export function TabsList({ className, ...props }: React.ComponentProps<typeof T.List>) {
  return <T.List className={cn('inline-flex items-center gap-1 rounded-lg bg-secondary p-1', className)} {...props} />
}
export function TabsTrigger({ className, ...props }: React.ComponentProps<typeof T.Trigger>) {
  return <T.Trigger className={cn('inline-flex h-7 cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent px-3 text-sm font-medium text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm', className)} {...props} />
}
export function TabsContent({ className, ...props }: React.ComponentProps<typeof T.Content>) {
  return <T.Content className={cn('outline-none', className)} {...props} />
}
