import * as React from "react"
import { cn } from "cn"

function Card({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card"
      className={cn("rounded-xl border bg-card text-card-foreground shadow-sm", className)}
      {...props}
    />
  )
}

/** A card rendered as a <section> (a titled region of a page). */
function CardSection({ className, ...props }: React.ComponentProps<"section">) {
  return (
    <section
      data-slot="card"
      className={cn("rounded-xl border bg-card text-card-foreground shadow-sm", className)}
      {...props}
    />
  )
}

export { Card, CardSection }
