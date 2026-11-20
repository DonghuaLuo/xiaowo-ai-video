import type { TextareaHTMLAttributes } from "react"
import { useEffect, useLayoutEffect, useRef } from "react"
import { cn } from "@/lib/utils"

const TEXTAREA_CLS =
  "min-h-24 min-w-0 w-full max-w-full resize-y rounded-xl border border-gray-200/70 bg-white/70 px-3 py-2 text-[12.5px] leading-[1.5] text-gray-700 outline-none transition-colors hover:border-indigo-200 focus:border-indigo-400 focus:ring-0 focus-visible:border-indigo-400 focus-visible:ring-0 focus-visible:ring-offset-0 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-300 dark:hover:border-indigo-800/60 dark:focus:border-indigo-500 dark:focus-visible:border-indigo-500"

const AUTO_TEXTAREA_MAX_VIEWPORT_RATIO = 0.72

function autoTextareaMaxHeight() {
  if (typeof window === "undefined") return 520
  return Math.max(160, Math.floor(window.innerHeight * AUTO_TEXTAREA_MAX_VIEWPORT_RATIO))
}

function resizeTextareaToContent(element: HTMLTextAreaElement | null) {
  if (!element) return
  const maxHeight = autoTextareaMaxHeight()
  element.style.maxHeight = `${maxHeight}px`
  element.style.height = "auto"
  const nextHeight = Math.min(element.scrollHeight, maxHeight)
  element.style.height = `${nextHeight}px`
  element.style.overflowY = element.scrollHeight > maxHeight ? "auto" : "hidden"
}

export function AutoResizeTextarea({
  className,
  onInput,
  value,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  useLayoutEffect(() => {
    resizeTextareaToContent(textareaRef.current)
  }, [value])

  useEffect(() => {
    const handleResize = () => resizeTextareaToContent(textareaRef.current)
    window.addEventListener("resize", handleResize)
    return () => window.removeEventListener("resize", handleResize)
  }, [])

  return (
    <textarea
      {...props}
      ref={textareaRef}
      value={value}
      onInput={(event) => {
        onInput?.(event)
        resizeTextareaToContent(event.currentTarget)
      }}
      className={cn(TEXTAREA_CLS, className)}
    />
  )
}
