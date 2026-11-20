import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { toast } from "sonner"
import { PluginSDK } from "xiaowo-sdk"
import {
  ChevronDown,
  Copy,
  Download,
  Loader2,
  MapPin,
  Trash2,
} from "lucide-react"
import {
  cancelTask,
  clearTaskNotifications,
  detectJianyingDraftRoot,
  getJianyingExportInfo,
  startJianyingDraftExport,
  startVideoFilesExport,
  type JianyingExportInfo,
  type TaskRow,
} from "@/backend"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import type { ProjectRow } from "@/features/projects/types"
import {
  isWorkspaceDockTaskActive as isWorkspaceTaskActive,
  useWorkspaceDockStore,
} from "@/features/workspace/workspace-dock-store"
import { COUNT_BADGE_CLS, COUNT_BADGE_MUTED_CLS } from "@/shared/button-styles"
import { formatCurrency } from "@/shared/format"
import { TooltipWrap } from "@/shared/tooltip-wrap"
import { errMsg } from "@/shared/backend-result"
import {
  WORKSPACE_SECTIONS,
  type WorkspaceDock,
  type WorkspaceSection,
} from "@/navigation"
import {
  EMPTY_WORKSPACE_TASKS,
  WORKSPACE_DOCK_TRIGGER_SELECTOR,
  WORKSPACE_FAILED_TASK_STATUSES,
  WORKSPACE_SPINNING_TASK_STATUSES,
  cleanTaskText,
  copyTextToClipboard,
  dedupeTaskDetailLines,
  dedupeWorkspaceProjectTasks,
  firstTaskText,
  isExpandableTaskDetail,
  isTaskVisibleInProjectDock,
  isWorkspaceTaskNotification,
  normalizedTaskNoticeText,
  rawTaskText,
  splitFailureText,
  taskDetailRowsToText,
  taskFailureReasonFromText,
  taskFailureTitleFromText,
  taskFinishedTimeText,
  taskLocationText,
  taskStartedTimeText,
  taskStatusMeta,
  type WorkspaceDockAnchor,
  workspaceDockMeta,
  workspaceDockPanelStyle,
  workspaceTaskNotificationFocusTarget,
} from "./workspace-task-model"


function TaskStatusBadge({ status }: { status: TaskRow["status"] }) {
  const meta = taskStatusMeta[status] ?? taskStatusMeta.created
  const Icon = meta.Icon
  const spinning = WORKSPACE_SPINNING_TASK_STATUSES.has(
    String(status ?? "").trim()
  )
  return (
    <span
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full border px-2 text-[11px] font-semibold",
        meta.pillClassName
      )}
    >
      <Icon className={cn("size-3.5", spinning && "animate-spin")} />
      {meta.label}
    </span>
  )
}

function TaskDetailLine({
  label,
  value,
}: {
  label: string
  value?: string | null
}) {
  if (!value) return null
  return (
    <div className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-2">
      <span className="text-gray-400 dark:text-gray-500">{label}</span>
      <span className="min-w-0 break-words whitespace-pre-wrap text-gray-600 dark:text-gray-300">
        {value}
      </span>
    </div>
  )
}

function TaskDockCard({
  task,
  notice,
  expanded,
  cancelling = false,
  onToggle,
  renderLocateButton,
  onCancel,
  onCopyFailureReason,
}: {
  task: TaskRow
  notice?: string
  expanded: boolean
  cancelling?: boolean
  onToggle: () => void
  renderLocateButton: (task: TaskRow) => React.ReactNode
  onCancel: (taskId: string) => void
  onCopyFailureReason?: (reason: string) => void
}) {
  const running = isWorkspaceTaskActive(task)
  const progress = Math.max(0, Math.min(100, task.progress || 0))
  const status = String(task.status ?? "").trim()
  const failed = WORKSPACE_FAILED_TASK_STATUSES.has(status)
  const finishedTimeText = running ? "" : taskFinishedTimeText(task)
  const startedTimeText = running ? taskStartedTimeText(task) : ""
  const headerTimeText = startedTimeText || finishedTimeText
  const errorSummaryParts = splitFailureText(task.errorSummary)
  const messageFailure = splitFailureText(task.message)
  const noticeFailure = splitFailureText(notice)
  const displayTitle = failed
    ? firstTaskText(
        taskFailureTitleFromText(task.errorSummary),
        taskFailureTitleFromText(notice),
        taskFailureTitleFromText(task.message),
        "任务执行失败"
      )
    : firstTaskText(notice, task.message) || "任务"
  const failureReason = failed
    ? firstTaskText(
        task.failureReason,
        errorSummaryParts.reason,
        noticeFailure.reason,
        messageFailure.reason,
        task.error,
        task.providerResponseSummary,
        taskFailureReasonFromText(task.errorSummary),
        taskFailureReasonFromText(notice),
        taskFailureReasonFromText(task.message)
      )
    : ""
  const failureDebug = failed
    ? ([task.errorDebug, task.traceback, task.stackTrace]
        .map((value) => rawTaskText(value))
        .find(Boolean) ?? "")
    : ""
  const actionText = cleanTaskText(
    task.agentAction || task.projectEffect?.action
  )
  const detailText = failureReason
    ? `原因：${failureReason}`
    : actionText || (running ? `进度 ${progress}%` : "")
  const statusMeta = taskStatusMeta[task.status] ?? taskStatusMeta.created
  const fullFailureReason = rawTaskText(failureReason)
  const expandedFailureReason =
    failed &&
    !failureDebug &&
    fullFailureReason &&
    (fullFailureReason.includes("\n") ||
      cleanTaskText(fullFailureReason).length > 80)
      ? fullFailureReason
      : ""
  const repeatedFailureTexts = [
    displayTitle,
    detailText,
    failureReason,
    errorSummaryParts.title,
    errorSummaryParts.reason,
    noticeFailure.title,
    noticeFailure.reason,
    messageFailure.title,
    messageFailure.reason,
  ]
    .map((item) => cleanTaskText(item))
    .filter(Boolean)
  const omittedDetailTexts = expandedFailureReason
    ? repeatedFailureTexts.filter(
        (item) => item !== cleanTaskText(expandedFailureReason)
      )
    : repeatedFailureTexts
  const fieldRepeatsCollapsedFailure = (value?: string | null) => {
    if (!failed) return false
    const text = cleanTaskText(value)
    if (!text) return true
    if (repeatedFailureTexts.includes(text)) return true
    const parts = splitFailureText(text)
    return Boolean(
      parts.reason &&
      parts.title === displayTitle &&
      (!failureReason || parts.reason === failureReason)
    )
  }
  const detailRows = dedupeTaskDetailLines(
    [
      {
        label: "接口返回",
        value: fieldRepeatsCollapsedFailure(task.providerResponseSummary)
          ? null
          : task.providerResponseSummary,
      },
      {
        label: "错误摘要",
        value: fieldRepeatsCollapsedFailure(task.errorSummary)
          ? null
          : task.errorSummary,
      },
      { label: "后端异常", value: failureDebug },
      { label: "完整原因", value: expandedFailureReason },
      {
        label: "错误详情",
        value: fieldRepeatsCollapsedFailure(task.error) ? null : task.error,
      },
      {
        label: "详情",
        value: fieldRepeatsCollapsedFailure(task.message) ? null : task.message,
      },
      {
        label: "通知",
        value: fieldRepeatsCollapsedFailure(notice) ? null : notice,
      },
      { label: running ? "开始时间" : "完成时间", value: headerTimeText },
      { label: "动作", value: actionText },
      { label: "位置", value: taskLocationText(task) },
    ],
    omittedDetailTexts
  )
  const expandableDetailRows = failed
    ? detailRows.filter(isExpandableTaskDetail)
    : []
  const hasExpandableDetails = expandableDetailRows.length > 0
  const effectiveExpanded = expanded && hasExpandableDetails
  const hasFailureCopyDetails = failed && expandableDetailRows.length > 0
  const failureCopyText = hasFailureCopyDetails
    ? taskDetailRowsToText(expandableDetailRows)
    : ""
  const locateButton = renderLocateButton(task)
  const canCopyFailureReason = Boolean(
    onCopyFailureReason && hasFailureCopyDetails && failureCopyText
  )
  const hasActions = Boolean(locateButton) || canCopyFailureReason
  const handleToggle = () => {
    if (hasExpandableDetails) onToggle()
  }

  return (
    <article
      className={cn(
        "rounded-lg border p-3 shadow-sm shadow-gray-950/[0.02] transition-colors",
        statusMeta.cardClassName
      )}
    >
      <button
        type="button"
        className={cn(
          "block w-full min-w-0 text-left",
          !hasExpandableDetails && "cursor-default"
        )}
        onClick={handleToggle}
        aria-expanded={effectiveExpanded}
        aria-disabled={!hasExpandableDetails}
        tabIndex={hasExpandableDetails ? 0 : -1}
      >
        <div className="flex min-w-0 items-center gap-2">
          <TaskStatusBadge status={task.status} />
          <span className="min-w-0 flex-1" aria-hidden="true" />
          {headerTimeText ? (
            <span className="shrink-0 text-[10px] text-gray-400 dark:text-gray-500">
              {headerTimeText}
            </span>
          ) : null}
          {hasExpandableDetails ? (
            <ChevronDown
              className={cn(
                "size-4 shrink-0 text-gray-400 transition-transform dark:text-gray-500",
                effectiveExpanded && "rotate-180"
              )}
            />
          ) : null}
        </div>
      </button>

      <div className="mt-2 flex min-w-0 items-start gap-2">
        <button
          type="button"
          className={cn(
            "min-w-0 flex-1 text-left",
            !hasExpandableDetails && "cursor-default"
          )}
          onClick={handleToggle}
          aria-expanded={effectiveExpanded}
          aria-disabled={!hasExpandableDetails}
          tabIndex={hasExpandableDetails ? 0 : -1}
        >
          <h4
            className={cn(
              "text-sm leading-5 font-normal text-gray-900 dark:text-gray-100",
              failed ? "break-words whitespace-normal" : "line-clamp-2"
            )}
          >
            {displayTitle}
          </h4>
          {detailText ? (
            <p
              className={cn(
                "mt-1 text-xs text-gray-500 dark:text-gray-400",
                failed ? "break-words whitespace-pre-wrap" : "line-clamp-1"
              )}
            >
              {detailText}
            </p>
          ) : null}
        </button>
        {running ? (
          <Button
            variant="outline"
            size="sm"
            className="h-7 shrink-0 gap-1.5 border-gray-200/80 bg-white/80 px-2 text-xs text-gray-600 hover:border-gray-300 hover:bg-white hover:text-gray-900 dark:border-white/10 dark:bg-white/[0.05] dark:text-gray-300 dark:hover:border-white/20 dark:hover:bg-white/[0.08] dark:hover:text-white"
            disabled={cancelling}
            onClick={(event) => {
              event.stopPropagation()
              onCancel(task.id)
            }}
          >
            {cancelling ? <Loader2 className="size-3 animate-spin" /> : null}
            {cancelling ? "取消中" : "取消"}
          </Button>
        ) : null}
      </div>

      {hasActions ? (
        <div className="mt-3 flex flex-wrap items-center justify-end gap-1.5">
          {canCopyFailureReason ? (
            <TooltipWrap content="复制错误详情">
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className="size-7 text-rose-600 hover:bg-rose-50 hover:text-rose-700 dark:text-rose-300 dark:hover:bg-rose-950/30 dark:hover:text-rose-200"
                aria-label="复制错误详情"
                onClick={(event) => {
                  event.stopPropagation()
                  onCopyFailureReason?.(failureCopyText)
                }}
              >
                <Copy className="size-3.5" />
              </Button>
            </TooltipWrap>
          ) : null}
          {locateButton}
        </div>
      ) : null}

      {running ? (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-gray-200/70 dark:bg-white/10">
          <div
            className="h-full rounded-full bg-gradient-to-r from-indigo-600 via-sky-600 to-emerald-500"
            style={{ width: `${Math.max(8, progress)}%` }}
          />
        </div>
      ) : null}

      {effectiveExpanded ? (
        <div className="mt-3 space-y-1.5 rounded-md border border-gray-200/70 bg-white/55 px-3 py-2 text-[11px] dark:border-white/10 dark:bg-white/[0.035]">
          {expandableDetailRows.map((row) => (
            <TaskDetailLine
              key={row.label}
              label={row.label}
              value={row.value}
            />
          ))}
        </div>
      ) : null}
    </article>
  )
}

export function WorkspaceDockPanel({
  dock,
  anchor,
  project,
  onRefreshTasks,
  onRefreshUsage,
  onLocateTask,
  onClose,
}: {
  dock: WorkspaceDock
  anchor: WorkspaceDockAnchor | null
  project: ProjectRow
  onRefreshTasks: () => Promise<void>
  onRefreshUsage: () => Promise<void>
  onLocateTask: (task: TaskRow) => boolean
  onClose: () => void
}) {
  const dockMeta = workspaceDockMeta[dock]
  const Icon = dockMeta.Icon
  const { backendReady, callBackend } = useBackend()

  const taskDockActive = dock === "notifications" || dock === "tasks"
  const tasks = useWorkspaceDockStore((state) =>
    taskDockActive ? state.tasks : EMPTY_WORKSPACE_TASKS
  )
  const tasksLoading = useWorkspaceDockStore((state) =>
    taskDockActive ? state.tasksLoading : false
  )
  const tasksLoaded = useWorkspaceDockStore((state) =>
    taskDockActive
      ? state.tasksLoaded && state.tasksProjectId === project.id
      : true
  )
  const usage = useWorkspaceDockStore((state) =>
    dock === "usage" ? state.usage : null
  )
  const usageLoading = useWorkspaceDockStore((state) =>
    dock === "usage" ? state.usageLoading : false
  )
  const usageLoaded = useWorkspaceDockStore((state) =>
    dock === "usage" ? state.usageLoaded : true
  )
  const [expandedTaskIds, setExpandedTaskIds] = useState<Set<string>>(
    () => new Set()
  )
  const [exportSourceMode, setExportSourceMode] =
    useState<"work_chain" | "custom">("work_chain")
  const [exportingJianying, setExportingJianying] = useState(false)
  const [exportingFiles, setExportingFiles] = useState(false)
  const [clearingNotifications, setClearingNotifications] = useState(false)
  const [cancellingTaskIds, setCancellingTaskIds] = useState<Set<string>>(
    () => new Set()
  )
  const panelRef = useRef<HTMLElement | null>(null)
  const [jianyingInfo, setJianyingInfo] = useState<JianyingExportInfo | null>(
    null
  )
  const [jianyingInfoLoading, setJianyingInfoLoading] = useState(false)
  const [selectedExportIds, setSelectedExportIds] = useState<Set<string>>(
    () => new Set()
  )
  const [draftPath, setDraftPath] = useState("")
  const [jianyingVersion, setJianyingVersion] = useState("6")
  const [clipEdits, setClipEdits] = useState<Record<string, { inSec: string; outSec: string }>>({})
  const visibleProjectTasks = tasks.filter((task) =>
    isTaskVisibleInProjectDock(task, project.id)
  )
  const activeTaskRows = dedupeWorkspaceProjectTasks(
    visibleProjectTasks.filter(isWorkspaceTaskActive)
  )
  const notificationTaskRows = dedupeWorkspaceProjectTasks(
    visibleProjectTasks.filter(isWorkspaceTaskNotification)
  )
  const notificationTasks = notificationTaskRows.slice(0, 80)
  const failedNotificationTaskIdsKey = notificationTasks
    .filter((task) =>
      WORKSPACE_FAILED_TASK_STATUSES.has(String(task.status ?? "").trim())
    )
    .map((task) => task.id)
    .join("|")
  const runningTaskCount = activeTaskRows.length
  const notificationTaskCount = notificationTaskRows.length
  const tasksPending = taskDockActive && (!tasksLoaded || tasksLoading)
  const usagePending = dock === "usage" && (!usageLoaded || usageLoading)
  const panelStyle = workspaceDockPanelStyle(anchor)
  const workChainExportEntries =
    jianyingInfo?.sources?.workChain?.entries ?? jianyingInfo?.episodes ?? []
  const customExportEntries = jianyingInfo?.sources?.custom?.entries ?? []
  const exportEntries =
    exportSourceMode === "custom" ? customExportEntries : workChainExportEntries
  const selectedExportEntries = exportEntries.filter((entry) =>
    entry.eligible && selectedExportIds.has(entry.id)
  )
  const hasSelectedFileVideos = selectedExportEntries.some(
    (entry) => (entry.generatedVideoCount ?? 0) > 0
  )
  const hasSelectedJianyingVideos = selectedExportEntries.some((entry) =>
    exportSourceMode === "custom"
      ? (entry.generatedVideoCount ?? 0) > 0
      : (entry.workChainVideoCount ?? 0) > 0
  )
  const getTaskFocusTarget = (task: TaskRow) =>
    workspaceTaskNotificationFocusTarget(task)
  const getTaskNotice = (task: TaskRow) =>
    normalizedTaskNoticeText(
      task,
      task.notice ?? task.projectEffect?.notice ?? task.message
    )
  const handleLocateTaskEffect = (task: TaskRow) => {
    if (onLocateTask(task)) onClose()
  }
  const renderLocateButton = (task: TaskRow) => {
    if (isWorkspaceTaskActive(task)) return null
    const section = getTaskFocusTarget(task)?.section
    if (!section || !WORKSPACE_SECTIONS.includes(section as WorkspaceSection)) {
      return null
    }
    return (
      <Button
        variant="outline"
        size="sm"
        className="h-7 gap-1.5 border-emerald-200 bg-emerald-50/90 px-2 text-xs font-medium text-emerald-700 shadow-sm shadow-emerald-900/[0.04] hover:border-emerald-300 hover:bg-emerald-100 hover:text-emerald-800 dark:border-emerald-800/70 dark:bg-emerald-950/30 dark:text-emerald-200 dark:hover:border-emerald-600 dark:hover:bg-emerald-900/45 dark:hover:text-emerald-100"
        onClick={() => handleLocateTaskEffect(task)}
      >
        <MapPin className="size-3.5" />
        定位
      </Button>
    )
  }

  const toggleTaskExpanded = (taskId: string) => {
    setExpandedTaskIds((current) => {
      const next = new Set(current)
      if (next.has(taskId)) next.delete(taskId)
      else next.add(taskId)
      return next
    })
  }

  useEffect(() => {
    const failedTaskIds = failedNotificationTaskIdsKey.split("|").filter(Boolean)
    if (failedTaskIds.length === 0) return

    setExpandedTaskIds((current) => {
      let changed = false
      const next = new Set(current)
      for (const taskId of failedTaskIds) {
        if (!next.has(taskId)) {
          next.add(taskId)
          changed = true
        }
      }
      return changed ? next : current
    })
  }, [failedNotificationTaskIdsKey])

  useEffect(() => {
    if (dock !== "export" || !backendReady) return
    let cancelled = false
    setJianyingInfoLoading(true)
    void Promise.all([
      getJianyingExportInfo(callBackend, project.id),
      detectJianyingDraftRoot(callBackend).catch(() => ""),
    ])
      .then(([info, detectedPath]) => {
        if (cancelled) return
        setJianyingInfo(info)
        const entries =
          exportSourceMode === "custom"
            ? info.sources?.custom?.entries ?? []
            : info.sources?.workChain?.entries ?? info.episodes
        setSelectedExportIds(
          new Set(entries.filter((entry) => entry.eligible).map((entry) => entry.id))
        )
        if (detectedPath) setDraftPath((current) => current || detectedPath)
      })
      .catch((error) => {
        if (!cancelled) toast.error(errMsg(error, "加载剪映导出信息失败"))
      })
      .finally(() => {
        if (!cancelled) setJianyingInfoLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [backendReady, callBackend, dock, exportSourceMode, project.id])

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target
      if (!(target instanceof Node)) return
      if (panelRef.current?.contains(target)) return
      if (
        target instanceof Element &&
        target.closest(`${WORKSPACE_DOCK_TRIGGER_SELECTOR}, [data-workspace-dock-content]`)
      ) {
        return
      }
      onClose()
    }
    document.addEventListener("pointerdown", handlePointerDown)
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown)
    }
  }, [onClose])

  const handleCancelTask = async (taskId: string) => {
    if (!backendReady) {
      toast.error("后端未就绪，无法取消任务")
      return
    }
    if (cancellingTaskIds.has(taskId)) return
    const currentTask = useWorkspaceDockStore
      .getState()
      .tasks.find((task) => task.id === taskId && task.projectId === project.id)
    setCancellingTaskIds((current) => new Set(current).add(taskId))
    if (currentTask && isWorkspaceTaskActive(currentTask)) {
      useWorkspaceDockStore.getState().upsertTask(
        {
          ...currentTask,
          message: "正在请求取消...",
          updatedAt: Date.now(),
        },
        project.id
      )
    }
    try {
      const task = await cancelTask(callBackend, taskId)
      useWorkspaceDockStore.getState().upsertTask(task, project.id)
      if (task.status === "failed" || task.status === "cancelled") {
        toast.success("任务已取消")
      } else if (task.status === "completed") {
        toast.info("任务已完成，无法取消")
      } else {
        toast.info("任务状态已更新")
      }
      void onRefreshTasks()
    } catch (error) {
      const latestTask = useWorkspaceDockStore
        .getState()
        .tasks.find(
          (task) => task.id === taskId && task.projectId === project.id
        )
      if (currentTask && latestTask && isWorkspaceTaskActive(latestTask)) {
        useWorkspaceDockStore.getState().upsertTask(
          {
            ...currentTask,
            updatedAt: Date.now(),
          },
          project.id
        )
      }
      toast.error(errMsg(error, "取消任务失败"))
      void onRefreshTasks()
    } finally {
      setCancellingTaskIds((current) => {
        if (!current.has(taskId)) return current
        const next = new Set(current)
        next.delete(taskId)
        return next
      })
    }
  }

  const handleCopyFailureReason = async (reason: string) => {
    const text = rawTaskText(reason)
    if (!text) {
      toast.error("没有可复制的错误详情")
      return
    }
    try {
      await copyTextToClipboard(text)
      toast.success("错误详情已复制")
    } catch (error) {
      toast.error(errMsg(error, "复制错误详情失败"))
    }
  }

  const handleClearNotifications = async () => {
    if (!backendReady || clearingNotifications) return
    setClearingNotifications(true)
    try {
      const result = await clearTaskNotifications(callBackend, project.id)
      toast.success(
        result.cleared > 0
          ? `已清除 ${result.cleared} 条通知`
          : "没有需要清除的通知"
      )
      await onRefreshTasks()
    } catch (error) {
      toast.error(errMsg(error, "清除通知失败"))
    } finally {
      setClearingNotifications(false)
    }
  }

  const handleSetExportSourceMode = (mode: "work_chain" | "custom") => {
    setExportSourceMode(mode)
    const entries = mode === "custom" ? customExportEntries : workChainExportEntries
    setSelectedExportIds(
      new Set(entries.filter((entry) => entry.eligible).map((entry) => entry.id))
    )
  }

  const toggleExportEntry = (entryId: string) => {
    setSelectedExportIds((current) => {
      const next = new Set(current)
      if (next.has(entryId)) next.delete(entryId)
      else next.add(entryId)
      return next
    })
  }

  const handlePickDraftPath = async () => {
    try {
      const selected = await PluginSDK.dialog.open({
        title: "选择剪映草稿目录",
        directory: true,
        multiple: false,
      })
      const path = Array.isArray(selected) ? selected[0] : selected
      if (typeof path === "string" && path.trim()) setDraftPath(path.trim())
    } catch (error) {
      toast.error(errMsg(error, "选择剪映草稿目录失败"))
    }
  }

  const handleExportJianying = async () => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    const selectedIds = selectedExportEntries
      .filter((entry) =>
        exportSourceMode === "custom"
          ? (entry.generatedVideoCount ?? 0) > 0
          : (entry.workChainVideoCount ?? 0) > 0
      )
      .map((entry) => entry.id)
    if (selectedIds.length === 0) {
      toast.error(
        exportSourceMode === "custom"
          ? "请至少选择一个包含视频的自定义画布"
          : "请至少选择一集包含工作链视频的分集"
      )
      return
    }
    if (!draftPath.trim()) {
      toast.error("请选择剪映草稿目录")
      return
    }
    const edits = selectedExportEntries.flatMap((entry) =>
      (entry.clips ?? []).map((clip) => {
        const key = `${entry.id}:${clip.nodeId}:${clip.versionId}`
        const values = clipEdits[key]
        return {
          canvasId: entry.id,
          nodeId: clip.nodeId,
          versionId: clip.versionId,
          inSec: Number(values?.inSec ?? 0),
          outSec: clip.mustKeepTail ? clip.durationSec : Number(values?.outSec ?? clip.durationSec),
          sourceDurationSec: clip.durationSec,
          mustKeepTail: clip.mustKeepTail,
        }
      })
    )
    if (edits.some((edit) => !Number.isFinite(edit.inSec) || !Number.isFinite(edit.outSec)
      || edit.inSec < 0 || edit.outSec - edit.inSec < 0.1
      || edit.outSec > edit.sourceDurationSec + 0.01)) {
      toast.error("请检查片段入出点：至少保留 0.1 秒，且不能超出原片时长")
      return
    }
    if (edits.some((edit) => edit.mustKeepTail && edit.outSec < edit.sourceDurationSec - 0.01)) {
      toast.error("下一段采用无切镜直续，上一段必须保留实际末帧")
      return
    }
    setExportingJianying(true)
    try {
      await startJianyingDraftExport(callBackend, {
        projectId: project.id,
        sourceMode: exportSourceMode,
        episodeIds: exportSourceMode === "work_chain" ? selectedIds : [],
        customCanvasIds: exportSourceMode === "custom" ? selectedIds : [],
        draftPath: draftPath.trim(),
        jianyingVersion,
        clipEdits: edits.map((edit) => ({
          canvasId: edit.canvasId, nodeId: edit.nodeId, versionId: edit.versionId,
          inSec: edit.inSec, outSec: edit.outSec,
        })),
      })
      toast.success("剪映草稿导出任务已创建")
      void onRefreshTasks()
      void onRefreshUsage()
      onClose()
    } catch (error) {
      toast.error(errMsg(error, "创建剪映草稿导出任务失败"))
    } finally {
      setExportingJianying(false)
    }
  }

  const handleExportAllVideos = async () => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    const selectedIds = selectedExportEntries
      .filter((entry) => (entry.generatedVideoCount ?? 0) > 0)
      .map((entry) => entry.id)
    if (selectedIds.length === 0) {
      toast.error(
        exportSourceMode === "custom"
          ? "请至少选择一个包含视频的自定义画布"
          : "请至少选择一集包含视频的分集"
      )
      return
    }
    let destinationPath = ""
    try {
      const selected = await PluginSDK.dialog.open({
        title: "选择视频导出目录",
        directory: true,
        multiple: false,
      })
      const path = Array.isArray(selected) ? selected[0] : selected
      if (typeof path !== "string" || !path.trim()) return
      destinationPath = path.trim()
    } catch (error) {
      toast.error(errMsg(error, "选择视频导出目录失败"))
      return
    }
    setExportingFiles(true)
    try {
      await startVideoFilesExport(callBackend, {
        projectId: project.id,
        sourceMode: exportSourceMode,
        episodeIds: exportSourceMode === "work_chain" ? selectedIds : [],
        customCanvasIds: exportSourceMode === "custom" ? selectedIds : [],
        destinationPath,
      })
      toast.success("视频文件导出任务已创建")
      void onRefreshTasks()
      onClose()
    } catch (error) {
      toast.error(errMsg(error, "创建视频文件导出任务失败"))
    } finally {
      setExportingFiles(false)
    }
  }

  // Global workspace panels must escape canvas stacking/clipping contexts and
  // sit above maximized editors, including their reference-setting popovers.
  return createPortal(
    <aside
      ref={panelRef}
      className="fixed z-[11000] flex flex-col overflow-hidden rounded-xl border border-white/70 bg-white/95 shadow-2xl shadow-gray-950/15 backdrop-blur-xl dark:border-white/10 dark:bg-[#202025]/95"
      style={panelStyle}
    >
      <header className="shrink-0 border-b border-gray-200/70 px-4 py-3 dark:border-white/10">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <Icon className="size-4 shrink-0 text-indigo-600 dark:text-indigo-300" />
            <h3 className="text-sm font-semibold text-gray-950 dark:text-gray-50">
              {dockMeta.label}
            </h3>
            {dock === "notifications" ? (
              <span className={cn("ml-0.5", COUNT_BADGE_MUTED_CLS)}>
                共 {notificationTaskCount} 项
              </span>
            ) : null}
            {runningTaskCount > 0 && dock === "tasks" ? (
              <span className={cn("ml-0.5", COUNT_BADGE_CLS)}>
                执行中 {runningTaskCount}
              </span>
            ) : null}
            {usagePending ? (
              <span className={cn("ml-0.5", COUNT_BADGE_MUTED_CLS)}>
                同步中
              </span>
            ) : null}
          </div>
          {dock === "notifications" ? (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 shrink-0 gap-1.5 px-2 text-xs text-gray-600 hover:text-gray-950 dark:text-gray-300 dark:hover:text-white"
              disabled={
                clearingNotifications ||
                tasksPending ||
                notificationTaskRows.length === 0
              }
              onClick={() => void handleClearNotifications()}
            >
              {clearingNotifications ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Trash2 className="size-3.5" />
              )}
              清除所有
            </Button>
          ) : null}
        </div>
      </header>
      <div className="min-h-0 flex-1 [scrollbar-gutter:stable] space-y-3 overflow-y-auto p-4">
        {dock === "notifications" ? (
          notificationTasks.length === 0 ? (
            <EmptyDockState loading={tasksPending} text="暂无通知" />
          ) : (
            <>
              {notificationTasks.map((task) => (
                <TaskDockCard
                  key={task.id}
                  task={task}
                  notice={getTaskNotice(task)}
                  expanded={expandedTaskIds.has(task.id)}
                  cancelling={cancellingTaskIds.has(task.id)}
                  onToggle={() => toggleTaskExpanded(task.id)}
                  renderLocateButton={renderLocateButton}
                  onCancel={(taskId) => void handleCancelTask(taskId)}
                  onCopyFailureReason={(reason) =>
                    void handleCopyFailureReason(reason)
                  }
                />
              ))}
            </>
          )
        ) : null}

        {dock === "tasks" ? (
          activeTaskRows.length === 0 ? (
            <EmptyDockState loading={tasksPending} text="暂无排队任务" />
          ) : (
            <>
              {activeTaskRows.slice(0, 80).map((task) => (
                <TaskDockCard
                  key={task.id}
                  task={task}
                  notice={getTaskNotice(task)}
                  expanded={expandedTaskIds.has(task.id)}
                  cancelling={cancellingTaskIds.has(task.id)}
                  onToggle={() => toggleTaskExpanded(task.id)}
                  renderLocateButton={renderLocateButton}
                  onCancel={(taskId) => void handleCancelTask(taskId)}
                />
              ))}
            </>
          )
        ) : null}

        {dock === "usage" ? (
          usagePending && !usage ? (
            <EmptyDockState loading={usagePending} text="暂无用量数据" />
          ) : (
            <div className="grid gap-3">
              {[
                ["项目", project.name, formatCurrency(usage?.monthCost ?? 0)],
                ["资产设计图", "生成次数", String(usage?.assetImages ?? 0)],
                [
                  "故事版大图",
                  "生成次数",
                  String(usage?.storyboardImages ?? 0),
                ],
                [
                  "故事版视频",
                  "生成次数",
                  String(usage?.storyboardVideos ?? 0),
                ],
                ["失败任务", "需查看诊断", String(usage?.failedTasks ?? 0)],
              ].map(([label, desc, value]) => (
                <div
                  key={label}
                  className="flex items-center justify-between gap-3 rounded-lg border border-gray-200/70 bg-white/70 p-3 dark:border-white/10 dark:bg-white/[0.035]"
                >
                  <div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {label}
                    </div>
                    <div className="mt-1 text-sm font-semibold text-gray-950 dark:text-gray-50">
                      {desc}
                    </div>
                  </div>
                  <div className="font-mono text-sm font-semibold text-emerald-600 dark:text-emerald-300">
                    {value}
                  </div>
                </div>
              ))}
            </div>
          )
        ) : null}

        {dock === "export" ? (
          <>
            <div className="grid grid-cols-2 gap-2">
              {[
                ["work_chain", "工作链画布"],
                ["custom", "自定义画布"],
              ].map(([mode, label]) => {
                const active = exportSourceMode === mode
                return (
                  <button
                    key={mode}
                    type="button"
                    className={cn(
                      "rounded-lg border px-3 py-2 text-center text-xs font-medium transition",
                      active
                        ? "border-indigo-300 bg-indigo-50 text-indigo-700 shadow-sm dark:border-indigo-500/50 dark:bg-indigo-500/15 dark:text-indigo-200"
                        : "border-gray-200/70 bg-white/70 text-gray-600 hover:border-gray-300 hover:bg-gray-50 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-300 dark:hover:border-white/20 dark:hover:bg-white/[0.06]"
                    )}
                    onClick={() =>
                      handleSetExportSourceMode(mode as "work_chain" | "custom")
                    }
                  >
                    {label}
                  </button>
                )
              })}
            </div>
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                {exportSourceMode === "custom" ? "选择自定义画布" : "选择分集"}
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={() => {
                  const eligibleIds = exportEntries
                    .filter((entry) => entry.eligible)
                    .map((entry) => entry.id)
                  const allSelected = eligibleIds.every((entryId) =>
                    selectedExportIds.has(entryId)
                  )
                  setSelectedExportIds(new Set(allSelected ? [] : eligibleIds))
                }}
                disabled={!exportEntries.some((entry) => entry.eligible)}
              >
                全选/取消
              </Button>
            </div>
            {jianyingInfoLoading ? (
              <EmptyDockState loading text="正在统计已生成视频" />
            ) : (
              <div className="grid min-w-0 gap-2">
                {exportEntries.map((entry) => (
                  <label
                    key={entry.id}
                    className={cn(
                      "flex min-w-0 items-start gap-2 rounded-lg border px-3 py-2 text-sm",
                      entry.eligible
                        ? "border-gray-200/70 bg-white/70 dark:border-white/10 dark:bg-white/[0.035]"
                        : "cursor-not-allowed border-gray-200/50 bg-gray-50/60 text-gray-400 dark:border-white/5 dark:bg-white/[0.02] dark:text-gray-500"
                    )}
                  >
                    <input
                      type="checkbox"
                      className="mt-1 shrink-0"
                      checked={selectedExportIds.has(entry.id)}
                      disabled={!entry.eligible}
                      onChange={() => toggleExportEntry(entry.id)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">
                        {entry.title}
                      </span>
                      <span className="mt-0.5 block truncate text-[11px] text-gray-500 dark:text-gray-400">
                        {entry.staleAllocationCount
                          ? "分镜脚本已变化，请重新分配分镜"
                          : entry.missingAllocationCount
                            ? `还有 ${entry.missingAllocationCount} 个分镜视频未生成`
                            : entry.unreadableVideoCount
                              ? `${entry.unreadableVideoCount} 个视频无法读取，请检查素材文件`
                            : exportSourceMode === "custom"
                          ? `${entry.generatedVideoCount ?? 0} 个视频`
                          : `工作链视频 ${entry.workChainVideoCount ?? 0} 个 · 其他视频 ${entry.otherVideoCount ?? 0} 个 · 共 ${entry.generatedVideoCount ?? 0} 个`}
                      </span>
                    </span>
                  </label>
                )) ?? null}
                {!exportEntries.length ? (
                  <EmptyDockState
                    loading={false}
                    text={
                      exportSourceMode === "custom"
                        ? "暂无包含视频的自定义画布"
                        : "暂无包含视频的工作链画布"
                    }
                  />
                ) : null}
              </div>
            )}
            {selectedExportEntries.some((entry) => (entry.clips ?? []).length > 0) ? (
              <div className="grid max-h-56 gap-2 overflow-y-auto rounded-lg border border-gray-200/70 p-2 dark:border-white/10">
                <div className="text-xs font-semibold text-gray-700 dark:text-gray-300">视频片段入出点（秒）</div>
                <p className="text-[11px] text-gray-500 dark:text-gray-400">根据实际画面和声音选择切点；原片混音会随画面一起裁切。</p>
                {selectedExportEntries.flatMap((entry) => (entry.clips ?? []).map((clip, index) => {
                  const key = `${entry.id}:${clip.nodeId}:${clip.versionId}`
                  const values = clipEdits[key]
                  return (
                    <div key={key} className="grid grid-cols-[minmax(0,1fr)_4.5rem_4.5rem] items-center gap-2 text-xs">
                      <span className="truncate" title={clip.mustKeepTail ? "下一段无切镜直续，当前片段须保留实际末帧" : entry.title}>{entry.title} · 片段 {index + 1} / {clip.durationSec.toFixed(2)} 秒{clip.mustKeepTail ? " · 末帧锁定" : ""}</span>
                      <input aria-label={`${entry.title} 片段 ${index + 1} 入点`} type="number" min="0" max={clip.durationSec}
                        step="0.01" value={values?.inSec ?? "0"}
                        onChange={(event) => setClipEdits((current) => ({ ...current, [key]: {
                          inSec: event.target.value, outSec: current[key]?.outSec ?? String(clip.durationSec),
                        } }))}
                        className="w-full rounded border border-gray-200 bg-white px-1 py-1 dark:border-white/10 dark:bg-white/[0.04]" />
                      <input aria-label={`${entry.title} 片段 ${index + 1} 出点`} type="number" min="0" max={clip.durationSec}
                        step="0.01" disabled={clip.mustKeepTail} value={clip.mustKeepTail ? String(clip.durationSec) : (values?.outSec ?? String(clip.durationSec))}
                        onChange={(event) => setClipEdits((current) => ({ ...current, [key]: {
                          inSec: current[key]?.inSec ?? "0", outSec: event.target.value,
                        } }))}
                        className="w-full rounded border border-gray-200 bg-white px-1 py-1 dark:border-white/10 dark:bg-white/[0.04]" />
                    </div>
                  )
                }))}
              </div>
            ) : null}
            <label className="grid gap-1.5 text-xs text-gray-600 dark:text-gray-300">
              剪映版本
              <Select
                value={jianyingVersion}
                onValueChange={setJianyingVersion}
              >
                <SelectTrigger className="h-9 w-full border-gray-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-white/[0.04]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent data-workspace-dock-content className="z-[11010] border-gray-200 bg-white text-gray-900 dark:border-white/10 dark:bg-[#2a2b33] dark:text-gray-100">
                  <SelectItem value="6">剪映 6.0 及以上</SelectItem>
                  <SelectItem value="5">剪映 5.x</SelectItem>
                </SelectContent>
              </Select>
            </label>
            <div className="grid gap-1.5">
              <div className="text-xs text-gray-600 dark:text-gray-300">
                剪映草稿目录
              </div>
              <div className="flex gap-2">
                <input
                  className="h-9 min-w-0 flex-1 rounded-md border border-gray-200 bg-white px-3 text-xs dark:border-white/10 dark:bg-white/[0.04]"
                  value={draftPath}
                  onChange={(event) => setDraftPath(event.target.value)}
                  placeholder="自动检测或手动选择"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-9 px-2"
                  onClick={() => void handlePickDraftPath()}
                >
                  选择
                </Button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Button
                className="gap-1.5"
                onClick={() => void handleExportJianying()}
                disabled={
                  exportingJianying ||
                  exportingFiles ||
                  jianyingInfoLoading ||
                  !hasSelectedJianyingVideos ||
                  !draftPath.trim()
                }
              >
                {exportingJianying ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Download className="size-4" />
                )}
                {exportingJianying ? "创建中" : "导出到剪映草稿"}
              </Button>
              <Button
                variant="outline"
                className="gap-1.5"
                onClick={() => void handleExportAllVideos()}
                disabled={
                  exportingJianying ||
                  exportingFiles ||
                  jianyingInfoLoading ||
                  !hasSelectedFileVideos
                }
              >
                {exportingFiles ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Download className="size-4" />
                )}
                {exportingFiles ? "创建中" : "导出全部视频"}
              </Button>
            </div>
          </>
        ) : null}
      </div>
    </aside>,
    document.body,
  )
}

function EmptyDockState({ loading, text }: { loading: boolean; text: string }) {
  return (
    <div className="rounded-lg border border-dashed border-gray-300/80 bg-white/45 px-4 py-10 text-center text-sm text-gray-500 dark:border-white/15 dark:bg-white/[0.035] dark:text-gray-400">
      {loading ? (
        <span className="inline-flex items-center justify-center gap-2">
          <Loader2 className="size-4 animate-spin" />
          正在同步...
        </span>
      ) : (
        text
      )}
    </div>
  )
}
