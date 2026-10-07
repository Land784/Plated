"use client"

import { Toaster as Sonner, type ToasterProps } from "sonner"
import { CircleCheckIcon, OctagonXIcon } from "lucide-react"

/** Toasts follow the system theme, like the rest of the app. */
const Toaster = (props: ToasterProps) => (
  <Sonner
    theme="system"
    position="bottom-center"
    offset={88}
    mobileOffset={88}
    icons={{
      success: <CircleCheckIcon className="size-4 text-success" />,
      error: <OctagonXIcon className="size-4 text-destructive" />,
    }}
    toastOptions={{
      classNames: {
        toast:
          "!rounded-full !border !border-border !bg-background !text-foreground !px-4 !py-2.5 !text-sm !font-medium !shadow-lg",
      },
    }}
    {...props}
  />
)

export { Toaster }
