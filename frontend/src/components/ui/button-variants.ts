import { cva } from 'class-variance-authority'

export const buttonVariants = cva(
  'inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md border border-transparent text-sm font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 py-0 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*=size-])]:size-4 cursor-pointer',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        secondary: 'border-border bg-card text-foreground hover:bg-secondary',
        ghost: 'bg-transparent text-foreground hover:bg-secondary',
        outline: 'border-input bg-transparent text-foreground hover:bg-secondary',
        destructive: 'bg-destructive text-white hover:bg-destructive/90',
        link: 'bg-transparent text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-8 px-3 pointer-coarse:h-9',
        sm: 'h-7 px-2 text-xs pointer-coarse:h-9',
        lg: 'h-10 px-4',
        icon: 'size-8 pointer-coarse:size-9',
        'icon-sm': 'size-7 pointer-coarse:size-9',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)
