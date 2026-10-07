import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-none",
  {
    variants: {
      variant: {
        outline: "border-border text-muted-foreground",
        warning: "border-warning-border bg-warning text-warning-foreground",
      },
    },
    defaultVariants: {
      variant: "outline",
    },
  }
)

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
