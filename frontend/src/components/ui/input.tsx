import * as React from "react"

import { cn } from "@/lib/utils"

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        data-slot="input"
        className={cn(
          "file:text-foreground placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground border-input h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 text-base text-gray-900 shadow-xs transition-[color,box-shadow,background-color,border-color] outline-none file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:!border-white/15 dark:!bg-[#2a2b33] dark:!text-gray-100 dark:placeholder:!text-gray-500 dark:disabled:!bg-white/[0.04]",
          "focus:border-indigo-400 focus:ring-0 focus-visible:border-indigo-400 focus-visible:ring-0 focus-visible:ring-offset-0 dark:focus:!border-indigo-400 dark:focus:!bg-[#30313b] dark:focus-visible:!border-indigo-400",
          "aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = "Input"

export { Input }
