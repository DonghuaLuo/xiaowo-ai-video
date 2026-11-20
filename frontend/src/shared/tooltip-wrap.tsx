import type { ReactElement, ReactNode } from "react"

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export function TooltipWrap({
  content,
  children,
  contentClassName,
  sideOffset = 6,
}: {
  content?: ReactNode
  children: ReactElement
  contentClassName?: string
  sideOffset?: number
}) {
  if (!content) return children
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent className={contentClassName} sideOffset={sideOffset}>
        {content}
      </TooltipContent>
    </Tooltip>
  )
}
