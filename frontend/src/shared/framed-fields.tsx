import type { ComponentProps } from "react"

import { cn } from "@/lib/utils"

export function FramedTextarea({
  className,
  containerClassName,
  ...props
}: ComponentProps<"textarea"> & {
  containerClassName?: string
}) {
  return (
    <div
      className={cn(
        "overflow-hidden border-2 border-gray-200/70 bg-white/70 transition-colors focus-within:border-indigo-400 dark:border-white/10 dark:bg-white/[0.035] dark:focus-within:border-indigo-500",
        containerClassName
      )}
    >
      <textarea
        {...props}
        className={cn(
          "ai-video-scrollbar w-full border-0 bg-transparent px-3 py-2 text-sm leading-6 text-gray-700 outline-none dark:text-gray-300",
          className
        )}
      />
    </div>
  )
}

export function FramedTextBlock({
  value,
  placeholder,
  className,
  containerClassName,
}: {
  value?: string | null
  placeholder: string
  className?: string
  containerClassName?: string
}) {
  const text = value?.trim() ? value : placeholder
  return (
    <div
      className={cn(
        "overflow-hidden border-2 border-gray-200/70 bg-white/70 dark:border-white/10 dark:bg-white/[0.035]",
        containerClassName
      )}
    >
      <p
        className={cn(
          "min-h-[92px] whitespace-pre-wrap px-3 py-2 text-sm leading-6 text-gray-700 dark:text-gray-300",
          !value?.trim() && "text-gray-400 dark:text-gray-500",
          className
        )}
      >
        {text}
      </p>
    </div>
  )
}
