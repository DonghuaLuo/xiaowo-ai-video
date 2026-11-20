"use client"

import * as React from "react"
import * as CheckboxPrimitive from "@radix-ui/react-checkbox"
import { CheckIcon } from "lucide-react"

import { cn } from "@/lib/utils"

function Checkbox({
  className,
  ...props
}: React.ComponentProps<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        "peer size-4 shrink-0 rounded-[4px] border border-slate-500 bg-white shadow-xs transition-colors outline-none data-[state=checked]:border-indigo-600 data-[state=checked]:bg-indigo-600 data-[state=checked]:text-white data-[state=indeterminate]:border-indigo-600 data-[state=indeterminate]:bg-indigo-600 data-[state=indeterminate]:text-white focus-visible:ring-[3px] focus-visible:ring-indigo-500/50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-400 dark:bg-slate-900 dark:data-[state=checked]:border-indigo-400 dark:data-[state=checked]:bg-indigo-500 dark:data-[state=indeterminate]:border-indigo-400 dark:data-[state=indeterminate]:bg-indigo-500 dark:aria-invalid:ring-destructive/40",
        className
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator
        data-slot="checkbox-indicator"
        className="flex items-center justify-center text-current transition-none"
      >
        <CheckIcon className="size-3.5" />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  )
}

export { Checkbox }
