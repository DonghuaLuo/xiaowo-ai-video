"use client"

import {
  CircleCheck,
  CircleX,
  Info,
  Loader2,
  TriangleAlert,
  X,
} from "lucide-react"
import { Toaster as Sonner, type ToasterProps } from "sonner"

const toastClassNames = {
  toast:
    "ai-video-toast ai-video-toast-enter pointer-events-auto flex items-start gap-2.5 rounded-lg border px-4 py-2.5 text-sm shadow-lg backdrop-blur-sm",
  default: "border-gray-600/60 bg-gray-800/90 text-gray-100",
  info: "border-sky-500/50 bg-sky-950/90 text-sky-100",
  success: "border-emerald-500/50 bg-emerald-950/90 text-emerald-100",
  error: "border-rose-500/50 bg-rose-950/90 text-rose-100",
  warning: "border-amber-500/50 bg-amber-950/90 text-amber-100",
  loading: "border-gray-500/50 bg-gray-900/90 text-gray-100",
  icon: "flex h-4 w-4 shrink-0 items-center justify-center",
  content: "min-w-0 flex-1",
  title:
    "block text-sm font-normal leading-5 whitespace-normal break-words text-inherit",
  description:
    "block text-xs leading-5 whitespace-normal break-words text-inherit opacity-80",
  closeButton:
    "ai-video-toast-close ml-1 shrink-0 rounded p-0.5 text-inherit opacity-50 transition-opacity hover:opacity-100",
}

const toastIcons = {
  info: <Info className="h-4 w-4 shrink-0 text-sky-400" aria-hidden />,
  success: (
    <CircleCheck className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden />
  ),
  error: <CircleX className="h-4 w-4 shrink-0 text-rose-300" aria-hidden />,
  warning: (
    <TriangleAlert className="h-4 w-4 shrink-0 text-amber-400" aria-hidden />
  ),
  loading: (
    <Loader2
      className="h-4 w-4 shrink-0 animate-spin text-gray-400"
      aria-hidden
    />
  ),
  close: <X className="h-3.5 w-3.5" aria-hidden />,
}

const Toaster = ({ theme = "system", ...props }: ToasterProps) => {
  return (
    <Sonner
      theme={theme}
      position="top-center"
      offset={{ top: "3.5rem" }}
      mobileOffset="1rem"
      duration={7000}
      visibleToasts={1}
      closeButton
      icons={toastIcons}
      toastOptions={{
        unstyled: true,
        classNames: toastClassNames,
      }}
      className="ai-video-toast-viewport"
      {...props}
    />
  )
}

export { Toaster }
