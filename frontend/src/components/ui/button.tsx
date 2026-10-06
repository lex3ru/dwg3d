import type { VariantProps } from 'class-variance-authority'
import { Slot } from 'radix-ui'
import type * as React from 'react'
import { cn } from '@/lib/utils'
import { buttonVariants } from './button-variants'
import { Tip } from './tooltip'

/** `hint`: what the button is for and what will happen (components/ui/tooltip.tsx), not its label again. */
export function Button({ className, variant, size, asChild = false, hint, hintSide, ...props }:
  React.ComponentProps<'button'> & VariantProps<typeof buttonVariants> & {
    asChild?: boolean; hint?: React.ReactNode; hintSide?: 'top' | 'bottom' | 'left' | 'right'
  }) {
  const Comp = asChild ? Slot.Root : 'button'
  const button = <Comp className={cn(buttonVariants({ variant, size }), className)} {...props} />
  return hint ? <Tip label={hint} side={hintSide}>{button}</Tip> : button
}
