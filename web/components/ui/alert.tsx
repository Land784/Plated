import * as React from "react"
import { cn } from "cn"

/** The warning callout from the mockup (shadcn Alert, warning colors). */
function Alert({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert"
      role="alert"
      className={cn(
        "flex gap-2 rounded-lg border border-warning-border bg-warning p-3 text-sm text-warning-foreground",
        className
      )}
      {...props}
    />
  )
}

export { Alert }
