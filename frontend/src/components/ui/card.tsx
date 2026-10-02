import type * as React from 'react'
import { cn } from '@/lib/utils'

export const Card = ({ className, ...p }: React.ComponentProps<'section'>) =>
  <section className={cn('rounded-xl border border-border bg-card text-card-foreground', className)} {...p} />
export const CardHeader = ({ className, ...p }: React.ComponentProps<'div'>) =>
  <div className={cn('flex flex-wrap items-center gap-3 px-4 pt-4', className)} {...p} />
export const CardTitle = ({ className, ...p }: React.ComponentProps<'h2'>) =>
  <h2 className={cn('m-0 mr-auto text-base font-semibold', className)} {...p} />
export const CardContent = ({ className, ...p }: React.ComponentProps<'div'>) =>
  <div className={cn('p-4', className)} {...p} />
