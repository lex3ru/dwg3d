import { Check, ChevronRight, Circle } from 'lucide-react'
import { DropdownMenu as M } from 'radix-ui'
import type * as React from 'react'
import { cn } from '@/lib/utils'

export const DropdownMenu = M.Root
export const DropdownMenuTrigger = M.Trigger
export const DropdownMenuGroup = M.Group
export const DropdownMenuSub = M.Sub
export const DropdownMenuRadioGroup = M.RadioGroup

const item = 'relative flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none focus:bg-secondary data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0'

export function DropdownMenuContent({ className, sideOffset = 6, ...props }: React.ComponentProps<typeof M.Content>) {
  return (
    <M.Portal>
      <M.Content sideOffset={sideOffset}
        className={cn('z-[100] min-w-44 max-h-[var(--radix-dropdown-menu-content-available-height)] overflow-y-auto rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-lg data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95', className)}
        {...props} />
    </M.Portal>
  )
}
export const DropdownMenuItem = ({ className, destructive, ...p }: React.ComponentProps<typeof M.Item> & { destructive?: boolean }) =>
  <M.Item className={cn(item, destructive && 'text-destructive', className)} {...p} />
export function DropdownMenuCheckboxItem({ className, children, ...props }: React.ComponentProps<typeof M.CheckboxItem>) {
  return (
    <M.CheckboxItem className={cn(item, 'pl-7', className)} {...props}>
      <span className="absolute left-2 flex size-4 items-center justify-center"><M.ItemIndicator><Check /></M.ItemIndicator></span>
      {children}
    </M.CheckboxItem>
  )
}
export function DropdownMenuRadioItem({ className, children, ...props }: React.ComponentProps<typeof M.RadioItem>) {
  return (
    <M.RadioItem className={cn(item, 'pl-7', className)} {...props}>
      <span className="absolute left-2 flex size-4 items-center justify-center"><M.ItemIndicator><Circle className="!size-2 fill-current" /></M.ItemIndicator></span>
      {children}
    </M.RadioItem>
  )
}
export const DropdownMenuLabel = ({ className, ...p }: React.ComponentProps<typeof M.Label>) =>
  <M.Label className={cn('px-2 py-1 text-xs font-medium text-muted-foreground', className)} {...p} />
export const DropdownMenuSeparator = ({ className, ...p }: React.ComponentProps<typeof M.Separator>) =>
  <M.Separator className={cn('-mx-1 my-1 h-px bg-border', className)} {...p} />
export function DropdownMenuSubTrigger({ className, children, ...props }: React.ComponentProps<typeof M.SubTrigger>) {
  return <M.SubTrigger className={cn(item, className)} {...props}>{children}<ChevronRight className="ml-auto" /></M.SubTrigger>
}
export const DropdownMenuSubContent = ({ className, ...p }: React.ComponentProps<typeof M.SubContent>) =>
  <M.Portal><M.SubContent className={cn('z-[100] min-w-40 rounded-lg border border-border bg-popover p-1 shadow-lg', className)} {...p} /></M.Portal>
