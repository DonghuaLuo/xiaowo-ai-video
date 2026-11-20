import { useEffect, useRef, useState, type MouseEvent } from "react"
import {
  ArrowLeft,
  Bell,
  CircleDollarSign,
  Download,
  Gauge,
  Library,
  Loader2,
  Plus,
  Settings,
  Sparkles,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import { StatusBadge } from "@/features/projects/project-cards"
import type { ContentMode, ProjectRow } from "@/features/projects/types"
import {contentModeLabel} from '@/features/settings/shared-template'
import {
  COUNT_BADGE_CLS,
  COUNT_BADGE_MUTED_CLS,
  COUNT_BADGE_WARNING_CLS,
  ICON_GHOST_BTN_CLS,
} from "@/shared/button-styles"
import { TooltipWrap } from "@/shared/tooltip-wrap"
import { type WorkspaceDock } from "@/navigation"


export function WorkspaceScroll({
  children,
  focusToken,
}: {
  children: React.ReactNode
  focusToken?: number
}) {
  return (
    <WorkspaceScrollSurface focusToken={focusToken}>
      {children}
    </WorkspaceScrollSurface>
  )
}

function WorkspaceScrollSurface({
  children,
  focusToken,
}: {
  children: React.ReactNode
  focusToken?: number
}) {
  const surfaceRef = useRef<HTMLDivElement | null>(null)
  const [activeFocusToken, setActiveFocusToken] = useState<number | null>(null)

  useEffect(() => {
    if (!focusToken) return
    setActiveFocusToken(focusToken)
    window.setTimeout(() => {
      surfaceRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
    }, 30)
    const timer = window.setTimeout(() => {
      setActiveFocusToken((current) =>
        current === focusToken ? null : current
      )
    }, 2600)
    return () => window.clearTimeout(timer)
  }, [focusToken])

  return (
    <ScrollArea className="h-full flex-1">
      <div
        ref={surfaceRef}
        data-workspace-focus-surface
        className={cn(
          "w-full min-w-0 space-y-5 rounded-xl border border-transparent px-6 py-5 transition-[background-color,border-color,box-shadow]",
          activeFocusToken
            ? "border-emerald-300/70 bg-gradient-to-br from-emerald-500/12 via-teal-400/8 to-transparent shadow-[0_0_0_4px_rgba(16,185,129,0.12)] dark:border-emerald-400/50 dark:from-emerald-400/12 dark:via-teal-300/8"
            : ""
        )}
      >
        {children}
      </div>
    </ScrollArea>
  )
}

export function CustomCanvasWorkspaceEmptyState({
  loading,
  creating,
  onCreate,
}: {
  loading: boolean
  creating: boolean
  onCreate: () => void
}) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center bg-slate-100/80 p-6 dark:bg-black/10">
      <div className="w-full max-w-md rounded-xl border border-white/80 bg-white/92 p-6 text-center shadow-xl shadow-gray-950/10 dark:border-white/10 dark:bg-[#202025]/92">
        <button
          type="button"
          className="mx-auto grid size-11 place-items-center rounded-full bg-indigo-50 text-indigo-600 transition-colors hover:bg-indigo-100 focus-visible:ring-2 focus-visible:ring-indigo-400/50 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60 dark:bg-indigo-400/10 dark:text-indigo-300 dark:hover:bg-indigo-400/15"
          disabled={loading || creating}
          aria-label="新建自定义画布"
          title="新建自定义画布"
          onClick={onCreate}
        >
          {loading ? (
            <Loader2 className="size-5 animate-spin" />
          ) : creating ? (
            <Loader2 className="size-5 animate-spin" />
          ) : (
            <Plus className="size-5" />
          )}
        </button>
        <h3 className="mt-4 text-base font-semibold text-gray-950 dark:text-gray-50">
          暂无自定义画布
        </h3>
        <p className="mt-2 truncate whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
          新建空白画布，右键添加素材和任务卡。
        </p>
      </div>
    </div>
  )
}

export function WorkspaceHeader({
  project,
  onBackHome,
  onOpenAssetsLibrary,
  onProjectSettings,
  onOpenDock,
  assistantOpen,
  assistantDisabled = false,
  onToggleAssistant,
  taskSummary,
}: {
  project: ProjectRow
  onBackHome: () => void
  onOpenAssetsLibrary: () => void
  onProjectSettings: () => void
  onOpenDock: (dock: WorkspaceDock, trigger: HTMLElement) => void
  assistantOpen: boolean
  assistantDisabled?: boolean
  onToggleAssistant: () => void
  taskSummary?: {
    total: number
    running: number
    failed: number
    finished: number
  }
}) {
  const modeLabel = contentModeLabel(
    (project.contentMode ?? project.content_mode ?? "drama") as ContentMode
  )

  return (
    <header className="ai-video-edge-b flex h-16 shrink-0 items-center gap-3 border-b border-gray-200/70 bg-white/80 px-4 shadow-sm backdrop-blur-xl dark:border-white/10 dark:bg-[#202025]/88">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <TooltipWrap content="返回项目列表">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className={ICON_GHOST_BTN_CLS}
            aria-label="返回项目列表"
            onClick={onBackHome}
          >
            <ArrowLeft className="size-4" />
          </Button>
        </TooltipWrap>
        <div className="hidden h-6 w-px bg-gray-200/80 xl:block dark:bg-white/10" />
        <div className="min-w-0">
          <h1 className="truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
            {project.name}
          </h1>
          <p className="mt-0.5 truncate text-[11px] text-gray-500 dark:text-gray-400">
            情景模式 · {modeLabel}
          </p>
        </div>
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <StatusBadge project={project} />
        <Button
          variant={
            assistantDisabled ? "outline" : assistantOpen ? "default" : "outline"
          }
          size="sm"
          className={cn(
            "h-8 gap-1.5 text-xs",
            assistantDisabled &&
              "cursor-not-allowed border-gray-200 bg-gray-100 text-gray-400 opacity-100 hover:bg-gray-100 hover:text-gray-400 dark:border-white/10 dark:bg-white/[0.04] dark:text-gray-500 dark:hover:bg-white/[0.04] dark:hover:text-gray-500"
          )}
          aria-disabled={assistantDisabled}
          aria-pressed={assistantDisabled ? false : assistantOpen}
          disabled={assistantDisabled}
          onClick={assistantDisabled ? undefined : onToggleAssistant}
        >
          <Sparkles className="size-3.5" />
          智能体
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1.5 bg-white/55 text-xs dark:bg-white/5"
          data-workspace-dock-trigger="true"
          onClick={(event: MouseEvent<HTMLButtonElement>) =>
            onOpenDock("notifications", event.currentTarget)
          }
        >
          <Bell className="size-3.5" />
          通知
          {taskSummary?.failed ? (
            <span className={cn("ml-0.5", COUNT_BADGE_WARNING_CLS)}>
              {taskSummary.failed}
            </span>
          ) : taskSummary?.finished ? (
            <span className={cn("ml-0.5", COUNT_BADGE_MUTED_CLS)}>
              {taskSummary.finished}
            </span>
          ) : null}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1.5 bg-white/55 text-xs dark:bg-white/5"
          data-workspace-dock-trigger="true"
          onClick={(event: MouseEvent<HTMLButtonElement>) =>
            onOpenDock("tasks", event.currentTarget)
          }
        >
          <Gauge className="size-3.5" />
          任务
          {taskSummary?.running ? (
            <span className={cn("ml-0.5", COUNT_BADGE_CLS)}>
              执行中 {taskSummary.running}
            </span>
          ) : null}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1.5 bg-white/55 text-xs dark:bg-white/5"
          data-workspace-dock-trigger="true"
          onClick={(event: MouseEvent<HTMLButtonElement>) =>
            onOpenDock("usage", event.currentTarget)
          }
        >
          <CircleDollarSign className="size-3.5" />
          用量
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1.5 bg-white/55 text-xs dark:bg-white/5"
          onClick={onOpenAssetsLibrary}
        >
          <Library className="size-3.5" />
          全局资产
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1.5 bg-white/55 text-xs dark:bg-white/5"
          data-workspace-dock-trigger="true"
          onClick={(event: MouseEvent<HTMLButtonElement>) =>
            onOpenDock("export", event.currentTarget)
          }
        >
          <Download className="size-3.5" />
          导出
        </Button>
        <TooltipWrap content="项目设置">
          <Button
            variant="ghost"
            size="icon-sm"
            className={ICON_GHOST_BTN_CLS}
            aria-label="项目设置"
            onClick={onProjectSettings}
          >
            <Settings className="size-4" />
          </Button>
        </TooltipWrap>
      </div>
    </header>
  )
}
