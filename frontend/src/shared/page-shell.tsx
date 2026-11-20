import type { ReactNode } from "react"
import { ArrowLeft, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import { TooltipWrap } from "@/shared/tooltip-wrap"

const ICON_GHOST_BTN_CLS =
  "text-gray-500 hover:bg-indigo-500 hover:text-white dark:text-gray-400 dark:hover:bg-white/10 dark:hover:text-gray-100"

export function PageHeader({
  eyebrow,
  title,
  description,
  onBack,
  children,
}: {
  eyebrow: string
  title: string
  description?: string
  onBack: () => void
  children?: ReactNode
}) {
  return (
    <header className="sticky top-0 z-20 border-b border-white/60 bg-white/70 px-5 py-4 shadow-sm backdrop-blur-xl dark:border-white/10 dark:bg-[#202025]/80">
      <div className="flex items-center gap-4">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 gap-1.5 bg-white/55 text-xs dark:bg-white/5"
          onClick={onBack}
        >
          <ArrowLeft className="size-3.5" />
          返回
        </Button>
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10px] font-bold tracking-[0.18em] text-indigo-500 uppercase dark:text-indigo-300">
            {eyebrow}
          </div>
          <h1 className="mt-0.5 truncate text-[24px] leading-tight font-semibold text-gray-950 dark:text-gray-50">
            {title}
          </h1>
          {description ? (
            <p className="mt-1 max-w-[760px] text-xs leading-relaxed text-gray-500 dark:text-gray-400">
              {description}
            </p>
          ) : null}
        </div>
        {children}
      </div>
    </header>
  )
}

export function SectionPanel({
  eyebrow,
  title,
  description,
  children,
  className,
  bodyClassName,
}: {
  eyebrow: string
  title: string
  description?: string
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section
      className={cn(
        "overflow-hidden rounded-xl border border-white/60 bg-white/65 shadow-sm backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.045]",
        className
      )}
    >
      <header className="shrink-0 border-b border-gray-200/70 px-5 py-4 dark:border-white/10">
        <div className="font-mono text-[10px] font-bold tracking-[0.16em] text-indigo-500 uppercase dark:text-indigo-300">
          {eyebrow}
        </div>
        <h2 className="mt-1 text-[16px] font-semibold text-gray-950 dark:text-gray-50">
          {title}
        </h2>
        {description ? (
          <p className="mt-1 max-w-[760px] text-xs leading-relaxed text-gray-500 dark:text-gray-400">
            {description}
          </p>
        ) : null}
      </header>
      <div className={cn("p-5", bodyClassName)}>{children}</div>
    </section>
  )
}

export function ModalShell({
  title,
  description,
  descriptionClassName,
  className,
  bodyClassName,
  scrollClassName,
  onClose,
  children,
  footer,
}: {
  title: string
  description?: string
  descriptionClassName?: string
  className?: string
  bodyClassName?: string
  scrollClassName?: string
  onClose: () => void
  children: ReactNode
  footer: ReactNode
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3 backdrop-blur-sm sm:p-5"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        className={cn(
          "flex max-h-[calc(100dvh-1.5rem)] w-full max-w-[720px] flex-col overflow-hidden rounded-2xl border border-white/60 bg-white/95 shadow-2xl sm:max-h-[calc(100dvh-3rem)] dark:border-white/10 dark:bg-[#202025]/95",
          className
        )}
      >
        <header className="shrink-0 border-b border-gray-200/70 px-5 py-4 dark:border-white/10">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-gray-950 dark:text-gray-50">
                {title}
              </h2>
            </div>
            <TooltipWrap content="关闭">
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className={cn(ICON_GHOST_BTN_CLS, "shrink-0")}
                onClick={onClose}
              >
                <X className="size-4" />
              </Button>
            </TooltipWrap>
          </div>
          {description ? (
            <p
              className={cn(
                "mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400",
                descriptionClassName
              )}
            >
              {description}
            </p>
          ) : null}
        </header>
        <ScrollArea className={cn("min-h-0 flex-1", scrollClassName)}>
          <div className={cn("p-4 sm:p-5", bodyClassName)}>{children}</div>
        </ScrollArea>
        <footer className="flex shrink-0 flex-wrap justify-end gap-2 border-t border-gray-200/70 bg-white/95 px-5 py-4 dark:border-white/10 dark:bg-[#202025]/95">
          {footer}
        </footer>
      </section>
    </div>
  )
}
