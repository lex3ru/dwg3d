import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import type { ComponentProps } from "react";
import { cn } from "@/lib/cn";

const button = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg border text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-[18px] [&_svg]:shrink-0 cursor-pointer",
  {
    variants: {
      variant: {
        primary: "border-accent bg-accent text-white hover:bg-accent-hover hover:border-accent-hover",
        secondary: "border-line-strong bg-surface text-ink hover:bg-surface-2",
        ghost: "border-transparent bg-transparent text-ink hover:bg-surface-2",
        danger: "border-line-strong bg-surface text-bad hover:bg-bad-soft",
      },
      size: {
        md: "h-9 px-3.5 max-md:h-11",
        sm: "h-8 px-2.5 text-[13px] max-md:h-11",
        icon: "size-9 max-md:size-11",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export function Button({
  className,
  variant,
  size,
  asChild,
  type = "button",
  ...props
}: ComponentProps<"button"> & VariantProps<typeof button> & { asChild?: boolean }) {
  const Component = asChild ? Slot.Root : "button";
  return <Component type={asChild ? undefined : type} className={cn(button({ variant, size }), className)} {...props} />;
}
