import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { mediaPreviewSrc } from "@/shared/media"
import {
  mediaDownloadSource,
  UnifiedMediaFrame,
} from "@/shared/unified-media-frame"
import {
  Handle,
  Position,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react"
import { Lock, Play } from "lucide-react"
import type { ComponentType } from "react"
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type WheelEvent,
} from "react"
import { createPortal } from "react-dom"
import {
  clampWorkflowCardSize,
  getNodeHandleSpecs,
  isWorkflowTaskCardType,
  nodeHandleClassName,
  nodeHandlePosition,
  nodeHandleStyle,
  nodeHandleTooltipSide,
  workflowCardSize,
  workflowMediaAspectRatio,
  workflowNodeGenerationStatusLabel,
  workflowNodePrimaryDisplayStatus,
  type WorkflowCardSize,
} from "./workflow-canvas-asset-model"
import {
  hasInlineTaskParameterPanel,
  isDirectorBoardNodeType,
  isWorkflowItemLocked,
  sourceCardDisplayTitle,
  sourceTextForNode,
  workflowCardHeaderLocator,
  workflowCardTypeLabel,
  type WorkflowNodeData,
} from "./workflow-canvas-model"
import {
  useWorkflowFloatingPanelRect,
  WORKFLOW_CENTERED_TASK_EDITOR_CONTENT_HEIGHT,
  WORKFLOW_FLOATING_DIRECTOR_EDITOR_PREFERRED_HEIGHT,
  WORKFLOW_FLOATING_TASK_EDITOR_PREFERRED_HEIGHT,
  WORKFLOW_FLOATING_TASK_PANEL_WIDTH,
} from "./workflow-floating-panel"
import { InlineEditActionBar } from "./workflow-inline-controls"
import { WorkflowPureMediaFrame } from "./workflow-media-frame"

type StoryboardNodeLike = Node<WorkflowNodeData, "storyboardNode">
type StoryboardNodeCardComponents = {
  TaskConfigSummary: ComponentType<{ data: WorkflowNodeData }>
  TaskParameterPanel: ComponentType<{
    id: string
    data: WorkflowNodeData
    width: number
    maxHeight?: number
    sourceDraft?: string
    maximized?: boolean
    onToggleMaximized?: () => void
  }>
}

function recordValue(value: unknown): Record<string, any> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, any>) : {}
}

function stopCardWheel(event: WheelEvent<HTMLElement>) {
  event.stopPropagation()
  event.nativeEvent.stopImmediatePropagation?.()
}

type StoryboardNodeCardProps = NodeProps<StoryboardNodeLike> & {
  components: StoryboardNodeCardComponents
}

function StoryboardNodeCard({
  id,
  data,
  selected,
  dragging,
  components,
}: StoryboardNodeCardProps) {
  const { TaskConfigSummary: WorkflowTaskConfigSummary, TaskParameterPanel: WorkflowTaskParameterPanel } = components
  const handles = getNodeHandleSpecs(data.eyebrow, data)
  const locked = isWorkflowItemLocked(data)
  const persistedSize = workflowCardSize(data)
  const [localSize, setLocalSize] = useState<WorkflowCardSize>(persistedSize)
  const sourceTextValue = sourceTextForNode(data)
  const [sourceDraft, setSourceDraft] = useState(sourceTextValue)
  const taskPanelAnchorRef = useRef<HTMLDivElement | null>(null)
  const [taskParameterPanelMaximized, setTaskParameterPanelMaximized] =
    useState(false)
  const resizeRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    startWidth: number
    startHeight: number
    lastSize: WorkflowCardSize
  } | null>(null)
  const isStoryboardImage = data.eyebrow === "storyboard.image"
  const isVideoResultCard = data.eyebrow === "video.result"
  const isCanvasImageAsset =
    data.eyebrow === "asset.image" || data.eyebrow === "media.external"
  const canvasImageMedia = data.media ?? data.storage ?? null
  const canvasImageSrc = mediaPreviewSrc(canvasImageMedia)
  const isPureMediaCard =
    isCanvasImageAsset || isStoryboardImage || isVideoResultCard
  const isSourceTextCard = data.eyebrow === "source.text"
  const pureMediaAspectRatio = workflowMediaAspectRatio(data, canvasImageMedia)
  const isTaskCard = isWorkflowTaskCardType(data.eyebrow)
  const showStatusBadge = isTaskCard
  const displayStatus = workflowNodePrimaryDisplayStatus(data)
  const statusClass =
    displayStatus === "running" || displayStatus === "processing"
      ? "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-300"
      : displayStatus === "succeeded" || displayStatus === "ready"
        ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300"
        : "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/30 dark:text-indigo-300"
  const summaryText = String(data.summary ?? "").trim()
  const hideSummaryForNode = data.status === "failed" || isTaskCard
  const showSummary = Boolean(
    summaryText &&
    !hideSummaryForNode &&
    summaryText !== data.title &&
    ![
      "source.text",
      "director.board",
      "prompt.storyboard",
      "video.result",
    ].includes(data.eyebrow)
  )
  const showMetaBadges = Boolean(
    data.model || data.metric || data.duration || data.cost
  )
  const showTaskParameterPanel =
    selected &&
    !isDirectorBoardNodeType(data.eyebrow) &&
    !dragging &&
    !data.creationPending &&
    !data.hideTaskParameterPanel &&
    hasInlineTaskParameterPanel(data.eyebrow)
  const showFloatingTaskPanel = showTaskParameterPanel
  const taskParameterPanelWidth = WORKFLOW_FLOATING_TASK_PANEL_WIDTH
  const taskParameterPanelPreferredHeight = (
    isDirectorBoardNodeType(data.eyebrow) || data.eyebrow === "storyboard.card"
  )
    ? WORKFLOW_FLOATING_DIRECTOR_EDITOR_PREFERRED_HEIGHT
    : WORKFLOW_FLOATING_TASK_EDITOR_PREFERRED_HEIGHT
  const getTaskPanelAnchor = useCallback(() => taskPanelAnchorRef.current, [])
  const taskParameterPanelRect = useWorkflowFloatingPanelRect(
    showFloatingTaskPanel,
    taskParameterPanelWidth,
    getTaskPanelAnchor,
    `${id}:${localSize.height}`,
    taskParameterPanelPreferredHeight
  )
  // Keep the portal and editor tree mounted while switching between both layouts.
  const taskPanelPortalTarget =
    typeof document !== "undefined"
      ? taskPanelAnchorRef.current?.closest<HTMLElement>(
          "[data-workflow-canvas-surface]"
        )
      : null
  useEffect(() => {
    if (!showFloatingTaskPanel) setTaskParameterPanelMaximized(false)
  }, [showFloatingTaskPanel])
  const cardTypeLabel = workflowCardTypeLabel(data.eyebrow, data)
  const cardHeaderPrimary = cardTypeLabel
  const cardHeaderSecondary = workflowCardHeaderLocator(data)
  const statusLabel = workflowNodeGenerationStatusLabel(data, displayStatus)
  const sourceCardCode = [cardHeaderPrimary, cardHeaderSecondary].filter(Boolean).join(" · ")
  const sourceCardTitle =
    sourceCardDisplayTitle(data.episodeTitle, data.episodeId) ||
    sourceCardDisplayTitle(data.title, data.episodeId) ||
    "待提取标题"
  const isSingleTextEditorCard = false
  const sourceTextDirty =
    data.eyebrow === "source.text" && sourceDraft !== sourceTextValue
  const textEditorDirty = sourceTextDirty

  useEffect(() => {
    setLocalSize(workflowCardSize(data))
  }, [data.cardState, data.eyebrow])

  useEffect(() => {
    setSourceDraft(sourceTextValue)
  }, [sourceTextValue])

  const persistCardSize = (size: WorkflowCardSize) => {
    const nextSize = clampWorkflowCardSize(size)
    data.onUpdateNodeData?.(
      id,
      {
        cardState: {
          ...recordValue(data.cardState),
          size: nextSize,
        },
      },
      "node_card_resized"
    )
  }

  const handleCancelTextEdit = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    if (sourceTextDirty) setSourceDraft(sourceTextValue)
  }

  const handleSaveTextEdit = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    if (!data.onUpdateNodeData) return
    if (sourceTextDirty) {
      return data.onUpdateNodeData(
        id,
        {
          sourceText: sourceDraft,
          summary: "",
        },
        "inline_source_text_saved",
        { successMessage: "修改已保存" }
      )
    }
  }

  const handleResizePointerDown = (
    event: React.PointerEvent<HTMLButtonElement>
  ) => {
    event.preventDefault()
    event.stopPropagation()
    resizeRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      startWidth: localSize.width,
      startHeight: localSize.height,
      lastSize: localSize,
    }
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId)
    } catch {
      // Pointer capture can fail if the event stream is interrupted.
    }
  }

  const handleResizePointerMove = (
    event: React.PointerEvent<HTMLButtonElement>
  ) => {
    const drag = resizeRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    event.preventDefault()
    event.stopPropagation()
    const deltaX = event.clientX - drag.startX
    const deltaY = event.clientY - drag.startY
    const nextWidth = isPureMediaCard
      ? drag.startWidth +
        (Math.abs(deltaX) >= Math.abs(deltaY)
          ? deltaX
          : deltaY * pureMediaAspectRatio)
      : drag.startWidth + deltaX
    const nextSize = clampWorkflowCardSize({
      ...localSize,
      width: nextWidth,
      height: isPureMediaCard
        ? nextWidth / pureMediaAspectRatio
        : drag.startHeight + deltaY,
    })
    resizeRef.current = { ...drag, lastSize: nextSize }
    setLocalSize(nextSize)
  }

  const handleResizePointerEnd = (
    event: React.PointerEvent<HTMLButtonElement>
  ) => {
    const drag = resizeRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    event.preventDefault()
    event.stopPropagation()
    resizeRef.current = null
    try {
      event.currentTarget.releasePointerCapture?.(event.pointerId)
    } catch {
      // Pointer capture may already be gone.
    }
    persistCardSize(drag.lastSize)
  }

  if (isPureMediaCard) {
    return (
      <div
        data-workspace-focus-surface
        className={cn(
          "nowheel group/canvas-card relative cursor-grab overflow-visible rounded-lg transition-[filter] active:cursor-grabbing",
          data.focusToken || selected ? "z-10" : null
        )}
        style={{
          width: localSize.width,
          minWidth: localSize.minWidth,
          maxWidth: localSize.maxWidth,
        }}
      >
        <div className="pointer-events-none mb-1 flex h-6 min-w-0 items-center gap-1.5 px-1 text-white">
          <span
            className={cn(
              "size-1.5 shrink-0 rounded-full bg-gradient-to-br",
              data.tone
            )}
          />
          <span className="shrink-0 text-[10px] font-semibold leading-none text-white/70">
            {cardHeaderPrimary}
          </span>
          {cardHeaderSecondary ? (
            <span className="truncate text-[11px] font-medium leading-none text-white/90">
              {cardHeaderSecondary}
            </span>
          ) : null}
        </div>
        {handles.targets.map((handle: any) => {
          const position = nodeHandlePosition(handle, Position.Left)
          return (
            <Tooltip key={handle.id}>
              <TooltipTrigger asChild>
                <Handle
                  id={handle.id}
                  type="target"
                  position={position}
                  style={nodeHandleStyle(handle, position)}
                  className={nodeHandleClassName("target", position)}
                />
              </TooltipTrigger>
              <TooltipContent
                side={nodeHandleTooltipSide(position)}
                sideOffset={8}
              >
                {handle.label}
              </TooltipContent>
            </Tooltip>
          )
        })}
        <WorkflowPureMediaFrame
          projectId={data.projectId}
          episodeId={data.episodeId}
          nodeId={id}
          data={data}
          className={cn(
            "w-full rounded-lg border bg-black shadow-xl shadow-gray-950/10 transition-[border-color,box-shadow]",
            data.focusToken
              ? "border-emerald-300 shadow-[0_0_0_4px_rgba(16,185,129,0.14),0_18px_38px_rgba(15,23,42,0.12)]"
              : selected
                ? "border-indigo-400 ring-2 ring-indigo-300/50"
                : "border-gray-200/80 dark:border-white/10"
          )}
        />
        {handles.sources.map((handle: any) => {
          const position = nodeHandlePosition(handle, Position.Right)
          return (
            <Tooltip key={handle.id}>
              <TooltipTrigger asChild>
                <Handle
                  id={handle.id}
                  type="source"
                  position={position}
                  style={nodeHandleStyle(handle, position)}
                  className={nodeHandleClassName("source", position)}
                />
              </TooltipTrigger>
              <TooltipContent
                side={nodeHandleTooltipSide(position)}
                sideOffset={8}
              >
                {handle.label}
              </TooltipContent>
            </Tooltip>
          )
        })}
        {data.action &&
        !isStoryboardImage &&
        !isVideoResultCard &&
        !isCanvasImageAsset ? (
          <Button
            type="button"
            size="sm"
            className="nodrag nopan absolute right-7 bottom-2 left-2 z-10 h-7 gap-1.5 bg-white/92 px-2 text-[11px] text-gray-800 shadow-md shadow-black/20 backdrop-blur-sm hover:bg-white dark:bg-[#18181b]/92 dark:text-gray-100 dark:hover:bg-[#202025]"
            onClick={(event) => {
              event.stopPropagation()
              data.onRun?.(id)
            }}
            disabled={data.status === "running"}
          >
            <Play className="size-3.5 shrink-0" />
            <span className="truncate">{data.action}</span>
          </Button>
        ) : null}
        <WorkflowResizeGrip
          className="text-white/55 opacity-0 group-hover/canvas-card:opacity-100 hover:text-white focus-visible:opacity-100 focus-visible:ring-white/40"
          onPointerDown={handleResizePointerDown}
          onPointerMove={handleResizePointerMove}
          onPointerUp={handleResizePointerEnd}
          onPointerCancel={handleResizePointerEnd}
        />
      </div>
    )
  }

  return (
    <>
      <div
        ref={taskPanelAnchorRef}
        className="nowheel relative flex flex-col items-center overflow-visible"
        style={{
          width: localSize.width,
        }}
      >
        {handles.targets.map((handle: any) => {
          const position = nodeHandlePosition(handle, Position.Left)
          return (
            <Tooltip key={handle.id}>
              <TooltipTrigger asChild>
                <Handle
                  id={handle.id}
                  type="target"
                  position={position}
                  style={nodeHandleStyle(handle, position)}
                  className={nodeHandleClassName("target", position)}
                />
              </TooltipTrigger>
              <TooltipContent
                side={nodeHandleTooltipSide(position)}
                sideOffset={8}
              >
                {handle.label}
              </TooltipContent>
            </Tooltip>
          )
        })}
        <div
          data-workspace-focus-surface
          className={cn(
            "nowheel relative flex cursor-grab overflow-hidden rounded-lg border transition-[background-color,border-color,box-shadow] active:cursor-grabbing",
            isSourceTextCard
              ? "bg-white/92 shadow-lg shadow-gray-950/[0.06] dark:bg-[#202025]/92 dark:shadow-black/20"
              : "bg-white shadow-xl shadow-gray-950/5 dark:bg-[#202025]",
            data.focusToken
              ? isSourceTextCard
                ? "border-emerald-300/70 shadow-[0_0_0_3px_rgba(16,185,129,0.12),0_14px_30px_rgba(15,23,42,0.12)] dark:border-emerald-400/45"
                : "border-emerald-300/80 bg-gradient-to-br from-emerald-500/14 via-teal-400/8 to-white shadow-[0_0_0_4px_rgba(16,185,129,0.14),0_18px_38px_rgba(15,23,42,0.12)] dark:border-emerald-400/55 dark:from-emerald-400/14 dark:via-teal-300/8 dark:to-[#202025]"
              : selected
                ? "border-indigo-400 ring-2 ring-indigo-300/50"
                : "border-gray-200/80 dark:border-white/10"
          )}
          style={{
            width: localSize.width,
            height: localSize.height,
            minWidth: localSize.minWidth,
            minHeight: localSize.minHeight,
            maxWidth: localSize.maxWidth,
            maxHeight: localSize.maxHeight,
            ...(isSourceTextCard
              ? {
                  backgroundImage:
                    "linear-gradient(135deg, rgba(99,102,241,0.10) 0px, rgba(99,102,241,0.10) 1px, transparent 1px, transparent 12px), linear-gradient(90deg, rgba(16,185,129,0.07), transparent 46%)",
                  backgroundSize: "12px 12px, 100% 100%",
                }
              : {}),
          }}
        >
          {isSourceTextCard ? (
            <div className="pointer-events-none absolute inset-0 bg-white/35 dark:bg-black/10" />
          ) : null}
          <div className="flex min-h-0 flex-1 flex-col">
            {!isSourceTextCard ? (
              <div className="flex min-h-10 shrink-0 items-center border-b border-gray-100/80 bg-white/95 px-3.5 py-2 backdrop-blur-sm dark:border-white/10 dark:bg-[#202025]/95">
                <div className="flex w-full items-center justify-between gap-3">
                  <div
                    className="flex min-w-0 items-center gap-1.5"
                    title={data.eyebrow}
                  >
                    <span
                      className={cn(
                        "size-1.5 shrink-0 rounded-full bg-gradient-to-br",
                        data.tone
                      )}
                    />
                    <span className="truncate text-[12px] font-semibold leading-none text-gray-800 dark:text-gray-100">
                      {cardHeaderPrimary}
                    </span>
                    {cardHeaderSecondary ? (
                      <span className="min-w-0 truncate text-[11px] leading-none text-gray-500 dark:text-gray-400">
                        · {cardHeaderSecondary}
                      </span>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1.5">
                    {showStatusBadge ? (
                      <Badge
                        variant="outline"
                        className={cn("rounded-full text-[10px]", statusClass)}
                      >
                        {statusLabel}
                      </Badge>
                    ) : null}
                    {locked ? (
                      <Badge
                        variant="outline"
                        className="gap-1 rounded-full border-amber-200 bg-amber-50 text-[10px] text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300"
                      >
                        <Lock className="size-3" />
                        锁定
                      </Badge>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : (
              <>
                <span className="pointer-events-none absolute top-2 left-2 z-10 inline-flex h-6 items-center rounded-md border border-gray-200/70 bg-white/70 px-1.5 text-[10px] font-medium leading-none tracking-normal text-gray-500 shadow-sm shadow-gray-950/[0.03] dark:border-white/10 dark:bg-white/[0.04] dark:text-gray-400">
                  {sourceCardCode}
                </span>
                {showStatusBadge ? (
                  <Badge
                    variant="outline"
                    className={cn(
                      "pointer-events-none absolute top-2 right-2 z-10 h-6 rounded-md px-1.5 text-[10px] font-medium leading-none shadow-sm shadow-gray-950/[0.03]",
                      statusClass
                    )}
                  >
                    {statusLabel}
                  </Badge>
                ) : null}
              </>
            )}
            <div
              className={cn(
                "nowheel min-h-0 flex-1 [scrollbar-gutter:stable]",
                isSourceTextCard
                  ? "flex items-center justify-center overflow-hidden p-4"
                  : "overflow-y-auto px-3.5 py-3",
                isSingleTextEditorCard ? "flex flex-col" : null
              )}
              onWheel={stopCardWheel}
              onWheelCapture={stopCardWheel}
            >
              {isSourceTextCard ? (
                <div className="relative z-10 min-w-0 text-center">
                  <div className="line-clamp-2 text-[17px] leading-snug font-semibold tracking-normal text-gray-900 dark:text-gray-50">
                    {sourceCardTitle}
                  </div>
                </div>
              ) : (
                <>
                  {showSummary ? (
                    <p className="line-clamp-3 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                      {summaryText}
                    </p>
                  ) : null}
                  {isCanvasImageAsset && canvasImageSrc ? (
                    <div className="mt-3">
                      <UnifiedMediaFrame
                        src={canvasImageSrc}
                        alt={data.title}
                        title={data.title}
                        kind="image"
                        className="aspect-[4/3] rounded-lg"
                        fit="cover"
                        downloadSource={mediaDownloadSource(canvasImageMedia)}
                        fallbackClassName={data.tone}
                      />
                    </div>
                  ) : null}
                  {showMetaBadges ? (
                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      {data.model ? (
                        <Badge
                          variant="outline"
                          className="rounded-full text-[11px]"
                        >
                          {data.model}
                        </Badge>
                      ) : null}
                      {data.metric ? (
                        <Badge
                          variant="outline"
                          className="rounded-full text-[11px]"
                        >
                          {data.metric}
                        </Badge>
                      ) : null}
                      {data.duration ? (
                        <Badge
                          variant="outline"
                          className="rounded-full text-[11px]"
                        >
                          {data.duration}
                        </Badge>
                      ) : null}
                      {data.cost ? (
                        <Badge
                          variant="outline"
                          className="rounded-full text-[11px]"
                        >
                          {data.cost}
                        </Badge>
                      ) : null}
                    </div>
                  ) : null}
                  <WorkflowTaskConfigSummary data={data} />
                </>
              )}
            </div>
            {!isSourceTextCard &&
            ((data.action && !isTaskCard) || textEditorDirty) ? (
              <div className="nodrag nopan shrink-0 border-t border-gray-100/80 bg-white/95 px-3.5 py-2.5 backdrop-blur-sm dark:border-white/10 dark:bg-[#202025]/95">
                <InlineEditActionBar
                  visible={textEditorDirty}
                  onCancel={handleCancelTextEdit}
                  onSave={handleSaveTextEdit}
                  className="mb-2"
                />
                {data.action && !isTaskCard ? (
                  <Button
                    size="sm"
                    className="h-8 w-full gap-1.5 text-xs shadow-sm"
                    onClick={(event) => {
                      event.stopPropagation()
                      data.onRun?.(id)
                    }}
                    disabled={data.status === "running"}
                  >
                    <Play className="size-3.5" />
                    {data.action}
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>
          {!isSourceTextCard ? (
            <WorkflowResizeGrip
              onPointerDown={handleResizePointerDown}
              onPointerMove={handleResizePointerMove}
              onPointerUp={handleResizePointerEnd}
              onPointerCancel={handleResizePointerEnd}
            />
          ) : null}
        </div>
        {handles.sources.map((handle: any) => {
          const position = nodeHandlePosition(handle, Position.Right)
          return (
            <Tooltip key={handle.id}>
              <TooltipTrigger asChild>
                <Handle
                  id={handle.id}
                  type="source"
                  position={position}
                  style={nodeHandleStyle(handle, position)}
                  className={nodeHandleClassName("source", position)}
                />
              </TooltipTrigger>
              <TooltipContent
                side={nodeHandleTooltipSide(position)}
                sideOffset={8}
              >
                {handle.label}
              </TooltipContent>
            </Tooltip>
          )
        })}
      </div>
      {showFloatingTaskPanel &&
      taskParameterPanelRect &&
      taskPanelPortalTarget
        ? createPortal(
            <div
              data-workflow-task-parameter-panel
              className={cn(
                "nodrag nopan nowheel",
                taskParameterPanelMaximized
                  ? "absolute inset-0 z-[300] flex bg-black/45 backdrop-blur-sm"
                  : "fixed z-[130]"
              )}
              style={
                taskParameterPanelMaximized
                  ? undefined
                  : {
                      left: taskParameterPanelRect.left,
                      top: taskParameterPanelRect.top,
                      width: taskParameterPanelRect.width,
                      transform: taskParameterPanelRect.transform,
                    }
              }
              onPointerDown={(event) => {
                event.stopPropagation()
                if (
                  taskParameterPanelMaximized &&
                  event.button === 0 &&
                  event.target === event.currentTarget
                ) {
                  setTaskParameterPanelMaximized(false)
                }
              }}
              onClick={(event) => event.stopPropagation()}
              onContextMenu={(event) => {
                if (!taskParameterPanelMaximized) return
                const target = event.target
                if (
                  target instanceof Element &&
                  target.closest("[data-workflow-image-browser]")
                ) {
                  return
                }
                event.preventDefault()
                event.stopPropagation()
                setTaskParameterPanelMaximized(false)
              }}
              onWheel={stopCardWheel}
              onWheelCapture={
                taskParameterPanelMaximized ? undefined : stopCardWheel
              }
            >
              <WorkflowTaskParameterPanel
                id={id}
                data={data}
                width={
                  taskParameterPanelMaximized
                    ? taskParameterPanelWidth
                    : taskParameterPanelRect.width
                }
                maxHeight={
                  taskParameterPanelMaximized
                    ? WORKFLOW_CENTERED_TASK_EDITOR_CONTENT_HEIGHT
                    : taskParameterPanelRect.maxHeight
                }
                sourceDraft={sourceDraft}
                maximized={taskParameterPanelMaximized}
                onToggleMaximized={() =>
                  setTaskParameterPanelMaximized((current) => !current)
                }
              />
            </div>,
            taskPanelPortalTarget
          )
        : null}
    </>
  )
}


export function createStoryboardNodeTypes(components: StoryboardNodeCardComponents): NodeTypes {
  return {
    storyboardNode: (props) => (
      <StoryboardNodeCard {...props} components={components} />
    ),
  } as NodeTypes
}


function WorkflowResizeGrip({
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onPointerCancel,
  className,
}: {
  onPointerDown: (event: React.PointerEvent<HTMLButtonElement>) => void
  onPointerMove: (event: React.PointerEvent<HTMLButtonElement>) => void
  onPointerUp: (event: React.PointerEvent<HTMLButtonElement>) => void
  onPointerCancel: (event: React.PointerEvent<HTMLButtonElement>) => void
  className?: string
}) {
  return (
    <button
      type="button"
      className={cn(
        "nodrag nopan absolute right-0 bottom-0 z-20 size-4 cursor-nwse-resize rounded-tl-sm text-gray-400/70 transition hover:text-indigo-500 focus-visible:ring-2 focus-visible:ring-indigo-400/40 focus-visible:outline-none dark:text-gray-500 dark:hover:text-indigo-200",
        className
      )}
      aria-label="调整卡片尺寸"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onClick={(event) => event.stopPropagation()}
    >
      <span
        aria-hidden="true"
        className="absolute right-0.5 bottom-0.5 size-1.5 opacity-80"
        style={{
          backgroundImage:
            "repeating-linear-gradient(135deg, transparent 0 2px, currentColor 2px 3px)",
        }}
      />
    </button>
  )
}
