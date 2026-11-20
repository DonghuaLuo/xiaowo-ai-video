import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  ChevronLeft,
  ChevronRight,
  Film,
  Layers3,
  Loader2,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react"
import { type CustomCanvasEntry } from "@/backend"
import { Button } from "@/components/ui/button"
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu"
import { cn } from "@/lib/utils"
import type { ProjectRow } from "@/features/projects/types"
import { buildProjectEpisodes, episodeStatusLabel } from "@/features/workspace/episodes"
import {
  COUNT_BADGE_CLS,
  COUNT_BADGE_MUTED_CLS,
  ICON_GHOST_BTN_CLS,
} from "@/shared/button-styles"
import { TooltipWrap } from "@/shared/tooltip-wrap"
import { type WorkspaceSection } from "@/navigation"
import {
  persistWorkspaceSidebarCollapsed,
  readWorkspaceSidebarCollapsed,
  type WorkspaceCanvasMode,
  type WorkspaceEpisodeDeleteMode,
  workspaceNav,
} from "./workspace-navigation"
import {
  formatWorkspaceTaskDateTime,
  type WorkspaceAssistantScope,
} from "./workspace-task-model"


type WorkspaceSidebarEpisode = ReturnType<typeof buildProjectEpisodes>[number]

function episodeNumberRank(id: string) {
  const matches = id.match(/\d+/g)
  if (!matches?.length) return Number.NEGATIVE_INFINITY
  const value = matches[matches.length - 1]
  return value ? Number(value) : Number.NEGATIVE_INFINITY
}

export function sortEpisodesByLatestFirst(episodes: WorkspaceSidebarEpisode[]) {
  return episodes
    .map((episode, index) => ({ episode, index }))
    .sort((left, right) => {
      const rankDiff =
        episodeNumberRank(right.episode.id) - episodeNumberRank(left.episode.id)
      return rankDiff || right.index - left.index
    })
    .map(({ episode }) => episode)
}

function normalizeEpisodeLabel(value?: string | null) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "")
}

function stripEpisodeTitlePrefix(title: string, episodeId: string) {
  const episodeNumber = episodeNumberRank(episodeId)
  let text = title.trim()
  if (Number.isFinite(episodeNumber) && episodeNumber > 0) {
    text = text
      .replace(new RegExp(`^e\\s*0*${episodeNumber}\\s*[·:：\\-—_ ]+`, "i"), "")
      .replace(
        new RegExp(`^ep\\s*0*${episodeNumber}\\s*[·:：\\-—_ ]+`, "i"),
        ""
      )
      .replace(
        new RegExp(`^episode\\s*0*${episodeNumber}\\s*[·:：\\-—_ ]+`, "i"),
        ""
      )
      .replace(
        new RegExp(`^第\\s*0*${episodeNumber}\\s*集\\s*[·:：\\-—_ ]+`),
        ""
      )
      .replace(
        /^第\s*[零〇一二三四五六七八九十百千万两]+\s*集\s*[·:：\-—_ ]+/,
        ""
      )
      .trim()
  }
  return text
}

export function episodeDisplayTitle(episode: WorkspaceSidebarEpisode) {
  const title = stripEpisodeTitlePrefix(
    String(episode.title ?? "").trim(),
    episode.id
  )
  const episodeNumber = episodeNumberRank(episode.id)
  const normalizedTitle = normalizeEpisodeLabel(title)
  const genericTitles =
    Number.isFinite(episodeNumber) && episodeNumber > 0
      ? new Set([
          normalizeEpisodeLabel(episode.id),
          `第${episodeNumber}集`,
          `第${String(episodeNumber).padStart(2, "0")}集`,
          `episode${episodeNumber}`,
          `ep${episodeNumber}`,
          `e${String(episodeNumber).padStart(2, "0")}`,
        ])
      : new Set([normalizeEpisodeLabel(episode.id)])
  if (
    !title ||
    title === "分集原文" ||
    title === "本集原文" ||
    title === "原文" ||
    genericTitles.has(normalizedTitle) ||
    /^第[零〇一二三四五六七八九十百千万两]+集$/.test(normalizedTitle) ||
    /^第[零〇一二三四五六七八九十百千万两]+集原文$/.test(normalizedTitle)
  ) {
    return ""
  }
  return title
}

function episodeProgressSummary(episode: WorkspaceSidebarEpisode) {
  return episodeStatusLabel(episode.status)
}

function customCanvasUpdatedAtText(canvas: CustomCanvasEntry) {
  const updatedAt = formatWorkspaceTaskDateTime(
    canvas.updatedAt ?? canvas.createdAt
  )
  return updatedAt || "暂无记录"
}

export function WorkspaceSidebar({
  project,
  section,
  episodeId,
  assistantOpen,
  assistantScope,
  projectConversationSelected,
  canvasMode,
  customCanvases,
  activeCustomCanvasId,
  customCanvasesLoading,
  customCanvasActionLoading,
  onNavigate,
  onOpenProjectConversation,
  onSelectCanvasMode,
  onCreateCustomCanvas,
  onSelectCustomCanvas,
  onRenameCustomCanvas,
  onRequestDeleteCustomCanvas,
  onRequestDeleteEpisode,
}: {
  project: ProjectRow
  section: WorkspaceSection
  episodeId: string
  assistantOpen: boolean
  assistantScope: WorkspaceAssistantScope
  projectConversationSelected: boolean
  canvasMode: WorkspaceCanvasMode
  customCanvases: CustomCanvasEntry[]
  activeCustomCanvasId: string
  customCanvasesLoading: boolean
  customCanvasActionLoading: string
  onNavigate: (section: WorkspaceSection, episodeId?: string) => void
  onOpenProjectConversation: () => void
  onSelectCanvasMode: (mode: WorkspaceCanvasMode) => void
  onCreateCustomCanvas: () => void
  onSelectCustomCanvas: (canvasId: string) => void
  onRenameCustomCanvas: (canvas: CustomCanvasEntry, title: string) => void
  onRequestDeleteCustomCanvas: (canvas: CustomCanvasEntry) => void
  onRequestDeleteEpisode: (
    episode: WorkspaceSidebarEpisode,
    mode: WorkspaceEpisodeDeleteMode
  ) => void
}) {
  const [collapsed, setCollapsed] = useState(readWorkspaceSidebarCollapsed)
  const [renamingCustomCanvasId, setRenamingCustomCanvasId] = useState("")
  const [customCanvasTitleDraft, setCustomCanvasTitleDraft] = useState("")
  const renamingCustomCanvasRef = useRef("")
  const renameContainerRef = useRef<HTMLDivElement | null>(null)
  const handleToggleCollapsed = useCallback(() => {
    setCollapsed((current) => {
      const next = !current
      persistWorkspaceSidebarCollapsed(next)
      return next
    })
  }, [])
  const visibleEpisodes = useMemo(
    () => sortEpisodesByLatestFirst(buildProjectEpisodes(project)),
    [project]
  )
  const navCounts: Partial<Record<WorkspaceSection, number>> = {
    sources: project.sourceCount,
    characters: project.characterCount ?? 0,
    creatures: project.creatureCount ?? 0,
    scenes: project.sceneCount ?? 0,
    props: project.propCount ?? 0,
  }
  const projectConversationActive =
    projectConversationSelected || (assistantOpen && assistantScope === "project")
  const renamingCustomCanvas = useMemo(
    () =>
      customCanvases.find(
        (canvas) => canvas.canvasId === renamingCustomCanvasId
      ) ?? null,
    [customCanvases, renamingCustomCanvasId]
  )
  const startRenameCustomCanvas = useCallback((canvas: CustomCanvasEntry) => {
    renamingCustomCanvasRef.current = canvas.canvasId
    setRenamingCustomCanvasId(canvas.canvasId)
    setCustomCanvasTitleDraft(canvas.title)
  }, [])
  const cancelRenameCustomCanvas = useCallback(() => {
    renamingCustomCanvasRef.current = ""
    setRenamingCustomCanvasId("")
    setCustomCanvasTitleDraft("")
  }, [])
  const commitRenameCustomCanvas = useCallback((canvas: CustomCanvasEntry) => {
    if (renamingCustomCanvasRef.current !== canvas.canvasId) return
    const nextTitle = customCanvasTitleDraft.trim()
    cancelRenameCustomCanvas()
    if (!nextTitle || nextTitle === canvas.title) return
    onRenameCustomCanvas(canvas, nextTitle)
  }, [cancelRenameCustomCanvas, customCanvasTitleDraft, onRenameCustomCanvas])
  useEffect(() => {
    renamingCustomCanvasRef.current = renamingCustomCanvasId
  }, [renamingCustomCanvasId])
  useEffect(() => {
    if (!renamingCustomCanvas || typeof document === "undefined") return
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target
      if (
        target instanceof Node &&
        renameContainerRef.current?.contains(target)
      ) {
        return
      }
      commitRenameCustomCanvas(renamingCustomCanvas)
    }
    document.addEventListener("pointerdown", handlePointerDown, true)
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true)
    }
  }, [commitRenameCustomCanvas, renamingCustomCanvas])
  return (
    <aside
      className={cn(
        "ai-video-edge-r flex shrink-0 flex-col border-r border-gray-200/70 bg-white/45 transition-[width] dark:border-white/10 dark:bg-white/[0.035]",
        collapsed ? "w-[60px]" : "w-[270px]"
      )}
    >
      <div className={cn("shrink-0 px-3 py-3", collapsed && "px-1.5")}>
        <button
          type="button"
          className={cn(
            "mb-2 flex h-9 items-center rounded-lg border border-transparent text-sm transition-colors",
            collapsed
              ? "mx-auto w-9 justify-center px-0 text-gray-500 hover:border-gray-200 hover:bg-white/70 hover:text-gray-950 dark:text-gray-400 dark:hover:border-white/10 dark:hover:bg-white/[0.06] dark:hover:text-gray-50"
              : "w-full justify-between gap-2 px-2 text-left hover:border-gray-200 hover:bg-white/65 dark:hover:border-white/10 dark:hover:bg-white/[0.05]"
          )}
          aria-label={collapsed ? "展开导航" : "折叠导航"}
          onClick={handleToggleCollapsed}
        >
          {!collapsed ? (
            <span className="font-mono text-[10px] font-bold tracking-[0.16em] text-gray-400 uppercase dark:text-gray-500">
              导航
            </span>
          ) : null}
          {collapsed ? (
            <ChevronRight className="size-4" />
          ) : (
            <ChevronLeft className="size-4 text-gray-500 dark:text-gray-400" />
          )}
        </button>
        <div className={cn("space-y-1", collapsed && "space-y-1.5")}>
          {workspaceNav.map((item) => {
            const Icon = item.icon
            const active = section === item.id
            const count = navCounts[item.id]
            const button = (
              <button
                key={item.id}
                type="button"
                className={cn(
                  "relative flex items-center rounded-lg border text-sm transition-colors",
                  collapsed
                    ? "mx-auto size-9 justify-center px-0"
                    : "w-full gap-2.5 px-3 py-2 text-left",
                  active
                    ? "border-indigo-200 bg-indigo-50/80 text-indigo-700 shadow-sm dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
                    : "border-transparent text-gray-500 hover:border-gray-200 hover:bg-white/65 hover:text-gray-950 dark:text-gray-400 dark:hover:border-white/10 dark:hover:bg-white/[0.05] dark:hover:text-gray-50"
                )}
                aria-label={item.label}
                onClick={() => onNavigate(item.id)}
              >
                <Icon className="size-4 shrink-0" />
                {!collapsed ? (
                  <>
                    <span className="min-w-0 flex-1 truncate">
                      {item.label}
                    </span>
                    {typeof count === "number" ? (
                      <span
                        className={cn(
                          "shrink-0",
                          active ? COUNT_BADGE_CLS : COUNT_BADGE_MUTED_CLS
                        )}
                      >
                        {count}
                      </span>
                    ) : null}
                  </>
                ) : typeof count === "number" && count > 0 ? (
                  <span
                    className={cn(
                      "absolute -top-1 -right-1 max-w-8 truncate",
                      active ? COUNT_BADGE_CLS : COUNT_BADGE_MUTED_CLS
                    )}
                  >
                    {count}
                  </span>
                ) : null}
              </button>
            )
            return button
          })}
        </div>
      </div>
      <div
        className={cn(
          "flex min-h-0 flex-1 flex-col overflow-hidden border-t border-gray-200/70 dark:border-white/10",
          collapsed ? "px-1.5 py-3" : "px-3 py-4"
        )}
      >
        <button
          type="button"
          className={cn(
            "mb-3 rounded-lg border text-left transition-colors",
            collapsed
              ? "mx-auto grid h-9 w-9 place-items-center px-0 text-center"
              : "w-full px-3 py-2",
            projectConversationActive
              ? "border-indigo-200 bg-indigo-50/80 text-indigo-700 shadow-sm dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
              : "border-transparent text-gray-500 hover:border-gray-200 hover:bg-white/65 hover:text-gray-950 dark:text-gray-400 dark:hover:border-white/10 dark:hover:bg-white/[0.05] dark:hover:text-gray-50"
          )}
          aria-label="项目会话"
          onClick={onOpenProjectConversation}
        >
          {collapsed ? (
            <Sparkles className="size-4" />
          ) : (
            <div className="flex items-center gap-2.5">
              <Sparkles className="size-4 shrink-0" />
              <span className="min-w-0 flex-1 truncate text-sm font-medium">
                项目会话
              </span>
            </div>
          )}
        </button>
        {!collapsed ? (
          <div className="mb-3">
            <div className="grid grid-cols-2 gap-1 rounded-lg bg-white/55 p-1 dark:bg-white/[0.035]">
              {(
                [
                  ["custom", "自定义画布", Layers3],
                  ["work_chain", "工作链画布", Film],
                ] satisfies Array<[WorkspaceCanvasMode, string, typeof Film]>
              ).map(([mode, label, Icon]) => {
                const active = canvasMode === mode
                return (
                  <button
                    key={mode}
                    type="button"
                    className={cn(
                      "flex h-8 items-center justify-center gap-1.5 rounded-md px-2 text-[12px] font-medium transition-colors",
                      active
                        ? "bg-white text-indigo-700 shadow-sm dark:bg-white/10 dark:text-indigo-200"
                        : "text-gray-500 hover:bg-white/70 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-white/[0.06] dark:hover:text-gray-100"
                    )}
                    onClick={() => onSelectCanvasMode(mode)}
                  >
                    <Icon className="size-3.5" />
                    <span className="truncate">{label}</span>
                  </button>
                )
              })}
            </div>
            {canvasMode === "custom" ? (
              <div className="mt-2 flex items-center justify-between gap-2 px-2">
                <div className="font-mono text-[10px] font-bold tracking-[0.16em] text-gray-400 uppercase dark:text-gray-500">
                  Custom
                </div>
                <TooltipWrap content="新建自定义画布">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    className={cn(ICON_GHOST_BTN_CLS, "size-7")}
                    disabled={customCanvasActionLoading === "create"}
                    onClick={onCreateCustomCanvas}
                  >
                    {customCanvasActionLoading === "create" ? (
                      <Loader2 className="size-3.5 animate-spin" />
                    ) : (
                      <Plus className="size-3.5" />
                    )}
                  </Button>
                </TooltipWrap>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="mb-3 grid gap-1.5">
            <button
              type="button"
              className={cn(
                "mx-auto grid h-9 w-9 place-items-center rounded-lg border transition-colors",
                canvasMode === "custom"
                  ? "border-indigo-200 bg-indigo-50/80 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
                  : "border-transparent text-gray-500 hover:border-gray-200 hover:bg-white/65 hover:text-gray-950 dark:text-gray-400 dark:hover:border-white/10 dark:hover:bg-white/[0.05] dark:hover:text-gray-50"
              )}
              aria-label="自定义画布"
              onClick={() => onSelectCanvasMode("custom")}
            >
              <Layers3 className="size-4" />
            </button>
            <button
              type="button"
              className={cn(
                "mx-auto grid h-9 w-9 place-items-center rounded-lg border transition-colors",
                canvasMode === "work_chain"
                  ? "border-emerald-200 bg-emerald-50/80 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-300"
                  : "border-transparent text-gray-500 hover:border-gray-200 hover:bg-white/65 hover:text-gray-950 dark:text-gray-400 dark:hover:border-white/10 dark:hover:bg-white/[0.05] dark:hover:text-gray-50"
              )}
              aria-label="工作链画布"
              onClick={() => onSelectCanvasMode("work_chain")}
            >
              <Film className="size-4" />
            </button>
            {canvasMode === "custom" ? (
              <button
                type="button"
                className="mx-auto grid h-8 w-8 place-items-center rounded-lg border border-transparent text-gray-500 transition-colors hover:border-gray-200 hover:bg-white/65 hover:text-gray-950 dark:text-gray-400 dark:hover:border-white/10 dark:hover:bg-white/[0.05] dark:hover:text-gray-50"
                aria-label="新建自定义画布"
                disabled={customCanvasActionLoading === "create"}
                onClick={onCreateCustomCanvas}
              >
                {customCanvasActionLoading === "create" ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Plus className="size-3.5" />
                )}
              </button>
            ) : null}
          </div>
        )}
        <div
          className={cn(
            "min-h-0 flex-1 overflow-y-auto",
            collapsed ? "space-y-1.5" : "space-y-1.5"
          )}
        >
          {canvasMode === "work_chain"
            ? visibleEpisodes.map((episode) => {
                const active =
                  section === "episode" &&
                  canvasMode === "work_chain" &&
                  episodeId === episode.id &&
                  !projectConversationActive
                const isLatestEpisode = episode.id === visibleEpisodes[0]?.id
                const displayTitle = episodeDisplayTitle(episode)
                const titleLabel = displayTitle || "待提取标题"
                const progressSummary = episodeProgressSummary(episode)
                const button = (
                  <button
                    type="button"
                    className={cn(
                      "rounded-lg border text-left transition-colors",
                      collapsed
                        ? "mx-auto grid h-9 w-9 place-items-center px-0 text-center"
                        : "w-full px-3 py-2",
                      active
                        ? "border-emerald-200 bg-emerald-50/80 text-emerald-700 shadow-sm dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-300"
                        : "border-transparent text-gray-500 hover:border-gray-200 hover:bg-white/65 hover:text-gray-950 dark:text-gray-400 dark:hover:border-white/10 dark:hover:bg-white/[0.05] dark:hover:text-gray-50"
                    )}
                    aria-label={[episode.id, titleLabel, progressSummary]
                      .filter(Boolean)
                      .join(" ")}
                    onClick={() => onNavigate("episode", episode.id)}
                  >
                    {collapsed ? (
                      <span className="max-w-full truncate font-mono text-[11px] font-semibold">
                        {episode.id}
                      </span>
                    ) : (
                      <>
                        <div className="flex items-center gap-2">
                          <span className="shrink-0 font-mono text-[12px] font-semibold">
                            {episode.id}
                          </span>
                          <span
                            className={cn(
                              "min-w-0 flex-1 truncate text-[13px]",
                              displayTitle
                                ? null
                                : "text-gray-400 dark:text-gray-500"
                            )}
                          >
                            {titleLabel}
                          </span>
                        </div>
                        <div className="mt-1 truncate text-[11px] opacity-75">
                          进度：{progressSummary}
                        </div>
                      </>
                    )}
                  </button>
                )
                return (
                  <ContextMenu key={episode.id}>
                    <ContextMenuTrigger asChild>{button}</ContextMenuTrigger>
                    <ContextMenuContent className="w-44">
                      <ContextMenuItem
                        onSelect={() => onRequestDeleteEpisode(episode, "canvas")}
                      >
                        <Trash2 className="size-3.5" />
                        删除本集画布
                      </ContextMenuItem>
                      {isLatestEpisode ? (
                        <>
                          <ContextMenuSeparator />
                          <ContextMenuItem
                            variant="destructive"
                            onSelect={() =>
                              onRequestDeleteEpisode(episode, "episode")
                            }
                          >
                            <Trash2 className="size-3.5" />
                            删除本集
                          </ContextMenuItem>
                        </>
                      ) : null}
                    </ContextMenuContent>
                  </ContextMenu>
                )
              })
            : null}
          {canvasMode === "custom" && customCanvasesLoading ? (
            <div className="flex items-center justify-center gap-2 rounded-lg border border-dashed border-gray-200/80 px-3 py-8 text-xs text-gray-500 dark:border-white/10 dark:text-gray-400">
              <Loader2 className="size-3.5 animate-spin" />
              正在加载
            </div>
          ) : null}
          {canvasMode === "custom" && !customCanvasesLoading
            ? customCanvases.map((canvas) => {
                const active =
                  section === "episode" &&
                  canvasMode === "custom" &&
                  activeCustomCanvasId === canvas.canvasId &&
                  !projectConversationActive
                const renaming = renamingCustomCanvasId === canvas.canvasId
                const actionBusy = customCanvasActionLoading.endsWith(
                  `:${canvas.canvasId}`
                )
                const updatedAtText = customCanvasUpdatedAtText(canvas)
                const item = renaming ? (
                  <div
                    ref={renameContainerRef}
                    className="px-3 py-2 text-gray-500 dark:text-gray-400"
                  >
                    <div className="flex items-center gap-2">
                      <input
                        value={customCanvasTitleDraft}
                        onChange={(event) =>
                          setCustomCanvasTitleDraft(event.target.value)
                        }
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault()
                            commitRenameCustomCanvas(canvas)
                          } else if (event.key === "Escape") {
                            event.preventDefault()
                            cancelRenameCustomCanvas()
                          }
                        }}
                        className="h-6 min-w-0 flex-1 border-0 border-b border-gray-300 bg-transparent px-0 text-[13px] font-medium text-gray-800 outline-none focus:border-gray-400 focus:ring-0 dark:border-white/20 dark:text-gray-100 dark:focus:border-white/35"
                      />
                    </div>
                    <div className="mt-1 truncate text-[11px] opacity-75">
                      {updatedAtText}
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    className={cn(
                      "rounded-lg border text-left transition-colors",
                      collapsed
                        ? "mx-auto grid h-9 w-9 place-items-center px-0 text-center"
                        : "w-full px-3 py-2",
                      active
                        ? "border-indigo-200 bg-indigo-50/80 text-indigo-700 shadow-sm dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
                        : "border-transparent text-gray-500 hover:border-gray-200 hover:bg-white/65 hover:text-gray-950 dark:text-gray-400 dark:hover:border-white/10 dark:hover:bg-white/[0.05] dark:hover:text-gray-50"
                    )}
                    aria-label={canvas.title}
                    onClick={() => onSelectCustomCanvas(canvas.canvasId)}
                    onDoubleClick={() => {
                      if (!collapsed) startRenameCustomCanvas(canvas)
                    }}
                  >
                    {collapsed ? (
                      <span className="max-w-full truncate text-[11px] font-semibold">
                        {canvas.title.slice(0, 2)}
                      </span>
                    ) : (
                      <>
                        <div className="flex items-center gap-2">
                          <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
                            {canvas.title}
                          </span>
                          {actionBusy ? (
                            <Loader2 className="size-3.5 shrink-0 animate-spin" />
                          ) : null}
                        </div>
                        <div className="mt-1 truncate text-[11px] opacity-75">
                          {updatedAtText}
                        </div>
                      </>
                    )}
                  </button>
                )
                return (
                  <ContextMenu key={canvas.canvasId}>
                    <ContextMenuTrigger asChild>{item}</ContextMenuTrigger>
                    <ContextMenuContent
                      className="w-44"
                      onCloseAutoFocus={(event) => {
                        if (renamingCustomCanvasRef.current === canvas.canvasId) {
                          event.preventDefault()
                        }
                      }}
                    >
                      <ContextMenuItem
                        disabled={collapsed || Boolean(customCanvasActionLoading)}
                        onSelect={() => startRenameCustomCanvas(canvas)}
                      >
                        <Pencil className="size-3.5" />
                        重命名
                      </ContextMenuItem>
                      <ContextMenuSeparator />
                      <ContextMenuItem
                        variant="destructive"
                        disabled={Boolean(customCanvasActionLoading)}
                        onSelect={() => onRequestDeleteCustomCanvas(canvas)}
                      >
                        <Trash2 className="size-3.5" />
                        删除画布
                      </ContextMenuItem>
                    </ContextMenuContent>
                  </ContextMenu>
                )
              })
            : null}
          {canvasMode === "custom" &&
          !customCanvasesLoading &&
          customCanvases.length === 0 ? (
            <div className="rounded-lg border border-dashed border-gray-200/80 px-3 py-8 text-center text-xs leading-5 text-gray-500 dark:border-white/10 dark:text-gray-400">
              点击上方加号新建画布
            </div>
          ) : null}
        </div>
      </div>
    </aside>
  )
}
