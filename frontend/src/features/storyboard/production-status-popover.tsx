import { createPortal } from "react-dom"
import { useEffect, useState } from "react"
import {
  CheckCircle2,
  ClipboardList,
  ImagePlus,
  LayoutGrid,
  Loader2,
  Maximize2,
  Video,
  WandSparkles,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export type WorkChainProgressState = "pending" | "running" | "completed"

export const WORK_CHAIN_PRODUCTION_STAGES = [
  {
    id: "cinematic_script.generated",
    label: "影视剧本",
    actionLabel: "生成影视剧本",
    optional: true,
  },
  {
    id: "director_plan.generated",
    label: "分镜脚本",
    actionLabel: "生成分镜脚本",
  },
  {
    id: "storyboard.generated",
    label: "分镜图",
    actionLabel: "生成分镜图",
    optional: true,
  },
  {
    id: "visual_handoff.generated",
    label: "视觉交接",
    actionLabel: "生成视觉交接图",
    optional: true,
  },
  {
    id: "video_prompt.ready",
    label: "视频提示词",
    actionLabel: "生成视频提示词",
  },
  { id: "video.generated", label: "视频片段", actionLabel: "生成视频片段" },
] as const

export type WorkChainProductionStateId =
  (typeof WORK_CHAIN_PRODUCTION_STAGES)[number]["id"]

export const WORK_CHAIN_STAGE_TASK_TYPES: Record<
  WorkChainProductionStateId,
  readonly string[]
> = {
  "cinematic_script.generated": ["workflow_cinematic_script"],
  "director_plan.generated": ["storyboard_plan"],
  "storyboard.generated": ["storyboard_image", "storyboard_image_generation"],
  "video_prompt.ready": ["video_prompt"],
  "visual_handoff.generated": ["visual_handoff_image"],
  "video.generated": [
    "storyboard_video",
    "route_video",
    "storyboard_video_generation",
  ],
}

export type WorkChainProgressStep = {
  stageId: WorkChainProductionStateId
  label: string
  state: WorkChainProgressState
  statusText: string
  actionLabel: string
  nodeId?: string
  actionTargetNodeId?: string
  actionTargetNodeIds?: string[]
  count?: number
  actionDisabledText?: string
  optional?: boolean
  progressIncluded?: boolean
  progressCompleted?: boolean
}

function workChainProgressStepTone(state: WorkChainProgressState) {
  if (state === "completed")
    return "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800/70 dark:bg-emerald-950/30 dark:text-emerald-200"
  if (state === "running")
    return "border-sky-300 bg-sky-50 text-sky-700 dark:border-sky-800/70 dark:bg-sky-950/30 dark:text-sky-200"
  return "border-gray-200 bg-gray-50 text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400"
}


type FloatingMenuPosition = { x: number; y: number }

export type ProductionStatusPopoverRow = {
  id: string
  label: string
  originLabel: string
  steps: WorkChainProgressStep[]
}

export function ProductionStatusPopover({
  rows,
  onShowAllWorkChains,
  onRelayout,
  onFocusWorkChain,
  onFocusStep,
  onRunStep,
}: {
  rows: ProductionStatusPopoverRow[]
  onShowAllWorkChains: () => void
  onRelayout: () => Promise<void>
  onFocusWorkChain: (workChainId: string) => void
  onFocusStep: (workChainId: string, nodeId?: string) => void
  onRunStep: (workChainId: string, step: WorkChainProgressStep) => void
}) {
  const [stepContextMenu, setStepContextMenu] = useState<
    | (FloatingMenuPosition & {
        workChainId: string
        stageId: WorkChainProductionStateId
      })
    | null
  >(null)
  const [relayoutRunning, setRelayoutRunning] = useState(false)
  const contextMenuRow = stepContextMenu
    ? rows.find((row) => row.id === stepContextMenu.workChainId)
    : undefined
  const contextMenuStep =
    contextMenuRow && stepContextMenu
      ? contextMenuRow.steps.find(
          (step) => step.stageId === stepContextMenu.stageId
        )
      : undefined
  useEffect(() => {
    if (!stepContextMenu) return
    const closeStepContextMenu = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest("[data-work-chain-step-menu='true']")) return
      setStepContextMenu(null)
    }
    const closeStepContextMenuOnKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setStepContextMenu(null)
    }
    window.addEventListener("pointerdown", closeStepContextMenu, true)
    window.addEventListener("keydown", closeStepContextMenuOnKey)
    return () => {
      window.removeEventListener("pointerdown", closeStepContextMenu, true)
      window.removeEventListener("keydown", closeStepContextMenuOnKey)
    }
  }, [stepContextMenu])
  const completed = rows.reduce(
    (count, row) =>
      count + row.steps.filter((step) => step.progressCompleted).length,
    0
  )
  const total = rows.reduce(
    (count, row) =>
      count +
      row.steps.filter((step) => step.progressIncluded !== false).length,
    0
  )
  const percent = total ? Math.round((completed / total) * 100) : 0

  return (
    <div
      className="pointer-events-auto absolute bottom-full left-1/2 z-50 mb-3 w-[min(920px,calc(100vw-1.5rem))] -translate-x-1/2 overflow-hidden rounded-xl border border-gray-200 bg-white text-xs text-gray-700 shadow-2xl shadow-gray-950/20 dark:border-white/10 dark:bg-[#18181b] dark:text-gray-100"
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => event.stopPropagation()}
    >
      <div className="flex items-start justify-between gap-3 border-b border-gray-200/80 px-3 py-2 dark:border-white/10">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold text-gray-950 dark:text-gray-50">
            工作链
          </div>
          <div className="mt-0.5 text-[10px] text-gray-400 dark:text-gray-500">
            {rows.length} 条工作链 · {completed}/{total} 个必选环节完成
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="rounded-full text-[11px]">
            {percent}%
          </Badge>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-[11px]"
            disabled={relayoutRunning}
            title="按当前分镜分组重排原文工作链，包括手动调整过的位置"
            onClick={async () => {
              setRelayoutRunning(true)
              try {
                await onRelayout()
              } finally {
                setRelayoutRunning(false)
              }
            }}
          >
            <LayoutGrid className="size-3" />
            整理布局
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-[11px]"
            onClick={onShowAllWorkChains}
          >
            <Maximize2 className="size-3" />
            全部工作链
          </Button>
        </div>
      </div>
      <div className="max-h-[min(62vh,560px)] [scrollbar-gutter:stable] overflow-y-auto p-3">
        {rows.length ? (
          <div className="grid gap-2.5">
            {rows.map((row) => (
              <section
                key={row.id}
                className="rounded-lg border border-gray-200/80 bg-gray-50/55 p-2.5 dark:border-white/10 dark:bg-white/[0.03]"
              >
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="min-w-0 truncate text-[11px] font-semibold text-gray-800 dark:text-gray-200">
                    {row.label}
                    <span className="ml-2 font-normal text-gray-500 dark:text-gray-400">{row.originLabel}</span>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-6 shrink-0 gap-1 px-2 text-[10px]"
                    onClick={() => onFocusWorkChain(row.id)}
                  >
                    <Maximize2 className="size-3" />
                    定位
                  </Button>
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3 lg:grid-cols-6">
                  {row.steps.map((step, index) => (
                    <div
                      key={`${row.id}-${step.stageId}`}
                      className="relative min-w-0"
                    >
                      {index < row.steps.length - 1 ? (
                        <div
                          className={cn(
                            "pointer-events-none absolute top-1/2 left-full z-0 h-px w-2 -translate-y-1/2 sm:w-3",
                            step.state === "completed"
                              ? "bg-emerald-400"
                              : "bg-gray-200 dark:bg-white/10"
                          )}
                        />
                      ) : null}
                      <button
                        type="button"
                        className={cn(
                          "nodrag nopan relative z-10 block w-full rounded-lg border px-1.5 py-2 text-center transition-transform hover:-translate-y-0.5 hover:shadow-sm",
                          workChainProgressStepTone(step.state)
                        )}
                        title={
                          step.nodeId
                            ? `${row.label} · ${step.label}`
                            : `${step.label} 暂无可定位节点`
                        }
                        onPointerDown={(event) => event.stopPropagation()}
                        onContextMenu={(event) => {
                          event.preventDefault()
                          event.stopPropagation()
                          setStepContextMenu({
                            x: event.clientX,
                            y: event.clientY,
                            workChainId: row.id,
                            stageId: step.stageId,
                          })
                        }}
                        onClick={(event) => {
                          event.preventDefault()
                          event.stopPropagation()
                          onFocusStep(row.id, step.nodeId)
                        }}
                      >
                        <div className="flex items-center justify-center gap-1.5">
                          {step.state === "completed" ? (
                            <CheckCircle2 className="size-3.5" />
                          ) : step.state === "running" ? (
                            <Loader2 className="size-3.5 animate-spin" />
                          ) : (
                            <span className="size-2 rounded-full border border-current/40" />
                          )}
                          <span className="truncate text-[11px] font-semibold">
                            {step.label}
                          </span>
                          {step.count !== undefined ? (
                            <span className="shrink-0 rounded-full bg-current/10 px-1.5 text-[10px] font-semibold tabular-nums">
                              {step.count}
                            </span>
                          ) : null}
                        </div>
                        <div
                          className="mt-1 truncate text-[10px] opacity-85"
                          title={step.statusText}
                        >
                          {step.statusText}
                        </div>
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-gray-300 p-5 text-center text-sm text-gray-500 dark:border-white/10 dark:text-gray-400">
            暂无工作链
          </div>
        )}
      </div>
      {stepContextMenu && contextMenuRow && contextMenuStep
        ? createPortal(
            <div
              data-work-chain-step-menu="true"
              className="fixed z-[620] min-w-40 overflow-hidden rounded-lg border border-gray-200 bg-white p-1 text-[12px] text-gray-700 shadow-2xl shadow-gray-950/20 dark:border-white/10 dark:bg-[#18181b] dark:text-gray-100"
              style={{ left: stepContextMenu.x, top: stepContextMenu.y }}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => event.stopPropagation()}
              onContextMenu={(event) => event.preventDefault()}
            >
              <div className="max-w-56 truncate px-2.5 py-2 text-[11px] font-semibold text-gray-400 dark:text-gray-500">
                {contextMenuRow.label} · {contextMenuStep.label}
              </div>
              <button
                type="button"
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors",
                  contextMenuStep.actionTargetNodeId
                    ? "hover:bg-gray-100 dark:hover:bg-white/10"
                    : "cursor-not-allowed text-gray-400"
                )}
                disabled={!contextMenuStep.actionTargetNodeId}
                title={contextMenuStep.actionDisabledText}
                onClick={() => {
                  if (!contextMenuStep.actionTargetNodeId) return
                  setStepContextMenu(null)
                  onRunStep(contextMenuRow.id, contextMenuStep)
                }}
              >
                {contextMenuStep.stageId === "video.generated" ? (
                  <Video className="size-3.5" />
                ) : contextMenuStep.stageId === "director_plan.generated" ? (
                  <ClipboardList className="size-3.5" />
                ) : contextMenuStep.stageId === "storyboard.generated" ||
                  contextMenuStep.stageId === "visual_handoff.generated" ? (
                  <ImagePlus className="size-3.5" />
                ) : (
                  <WandSparkles className="size-3.5" />
                )}
                {contextMenuStep.count && contextMenuStep.count > 1
                  ? `批量${contextMenuStep.actionLabel}（${contextMenuStep.count}）`
                  : contextMenuStep.actionLabel}
              </button>
            </div>,
            document.body
          )
        : null}
    </div>
  )
}

