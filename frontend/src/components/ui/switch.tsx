"use client"

import * as React from "react"
import * as SwitchPrimitive from "@radix-ui/react-switch"

import { cn } from "@/lib/utils"

type SwitchProps = React.ComponentProps<typeof SwitchPrimitive.Root> & {
  thumbClassName?: string
}

function Switch({
  className,
  thumbClassName,
  ...props
}: SwitchProps) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "peer inline-flex h-5 w-9 shrink-0 items-center rounded-full border p-0.5 shadow-sm transition-all outline-none focus-visible:ring-[3px] focus-visible:ring-indigo-500/25 disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:border-indigo-500 data-[state=checked]:bg-indigo-600 data-[state=unchecked]:border-gray-300 data-[state=unchecked]:bg-gray-200 dark:focus-visible:ring-indigo-400/30 dark:data-[state=checked]:border-indigo-400 dark:data-[state=checked]:bg-indigo-500 dark:data-[state=unchecked]:border-white/20 dark:data-[state=unchecked]:bg-[#3a3c46]",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className={cn(
          "pointer-events-none block size-4 rounded-full bg-white shadow-sm ring-0 transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0 dark:bg-white",
          thumbClassName
        )}
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
