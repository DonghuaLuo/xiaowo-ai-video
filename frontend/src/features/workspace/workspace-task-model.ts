import { PluginSDK } from "xiaowo-sdk"
import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  ClipboardList,
  CircleDollarSign,
  Download,
  Gauge,
  Loader2,
} from "lucide-react"
import { type TaskRow } from "@/backend"
import { isWorkspaceDockTaskActive as isWorkspaceTaskActive } from "@/features/workspace/workspace-dock-store"
import {
  type AssetTab,
  type WorkspaceDock,
  type WorkspaceSection,
} from "@/navigation"


export const WORKSPACE_DOCK_TRIGGER_SELECTOR = "[data-workspace-dock-trigger]"

const WORKSPACE_DOCK_PANEL_WIDTH = 360

const WORKSPACE_DOCK_PANEL_MARGIN = 12

const WORKSPACE_DOCK_PANEL_GAP = 8

export const EMPTY_WORKSPACE_TASKS: TaskRow[] = []

const HOME_ARCHIVE_TASK_TYPES = new Set([
  "home_archive_export",
  "home_archive_import",
])

const ASSISTANT_EXECUTION_TASK_TYPES = new Set(["agent_turn"])

export function isTaskVisibleInProjectDock(task: TaskRow, projectId: string) {
  // 智能体执行在会话内展示；它发起的图片、视频等生成任务仍按各自类型展示。
  if (ASSISTANT_EXECUTION_TASK_TYPES.has(String(task.type ?? "").trim())) return false
  return (
    task.projectId === projectId ||
    (HOME_ARCHIVE_TASK_TYPES.has(task.type) && isWorkspaceTaskActive(task))
  )
}

export type WorkspaceDockAnchor = {
  top: number
  right: number
  bottom: number
  left: number
  width: number
  height: number
}

export type WorkspaceAssistantScope = "project" | "episode"

export type ActiveWorkspaceDock = {
  dock: WorkspaceDock
  anchor: WorkspaceDockAnchor | null
}

export function workspaceDockAnchorFromElement(
  element: HTMLElement
): WorkspaceDockAnchor {
  const rect = element.getBoundingClientRect()
  return {
    top: rect.top,
    right: rect.right,
    bottom: rect.bottom,
    left: rect.left,
    width: rect.width,
    height: rect.height,
  }
}

export function workspaceDockPanelStyle(anchor: WorkspaceDockAnchor | null) {
  const viewportWidth =
    typeof window === "undefined"
      ? WORKSPACE_DOCK_PANEL_WIDTH
      : window.innerWidth
  const preferredLeft = anchor
    ? anchor.left + anchor.width / 2 - WORKSPACE_DOCK_PANEL_WIDTH / 2
    : viewportWidth - WORKSPACE_DOCK_PANEL_WIDTH - WORKSPACE_DOCK_PANEL_MARGIN
  const maxLeft = Math.max(
    WORKSPACE_DOCK_PANEL_MARGIN,
    viewportWidth - WORKSPACE_DOCK_PANEL_WIDTH - WORKSPACE_DOCK_PANEL_MARGIN
  )
  const left = Math.min(
    Math.max(preferredLeft, WORKSPACE_DOCK_PANEL_MARGIN),
    maxLeft
  )
  const top = anchor
    ? Math.max(
        anchor.bottom + WORKSPACE_DOCK_PANEL_GAP,
        WORKSPACE_DOCK_PANEL_MARGIN
      )
    : 64
  return {
    left,
    top,
    width: WORKSPACE_DOCK_PANEL_WIDTH,
    maxHeight: `calc(100vh - ${top + WORKSPACE_DOCK_PANEL_MARGIN}px)`,
  }
}

export const workspaceDockMeta: Record<
  WorkspaceDock,
  { label: string; Icon: typeof Bell }
> = {
  notifications: { label: "通知", Icon: Bell },
  tasks: { label: "任务", Icon: Gauge },
  usage: { label: "用量", Icon: CircleDollarSign },
  export: { label: "导出视频", Icon: Download },
}

export type WorkspaceFocusTargetState = {
  section: WorkspaceSection
  episodeId?: string
  assetTab?: AssetTab | string
  nodeId?: string
  assetId?: string
  requestId: number
}

export const taskStatusMeta: Record<
  TaskRow["status"],
  {
    label: string
    Icon: typeof CheckCircle2
    pillClassName: string
    cardClassName: string
  }
> = {
  created: {
    label: "排队中",
    Icon: ClipboardList,
    pillClassName:
      "border-slate-200 bg-slate-50 text-slate-700 dark:border-white/15 dark:bg-white/[0.06] dark:text-slate-200",
    cardClassName:
      "border-gray-200/80 bg-white/75 dark:border-white/10 dark:bg-white/[0.04]",
  },
  queued: {
    label: "排队中",
    Icon: ClipboardList,
    pillClassName:
      "border-slate-200 bg-slate-50 text-slate-700 dark:border-white/15 dark:bg-white/[0.06] dark:text-slate-200",
    cardClassName:
      "border-gray-200/80 bg-white/75 dark:border-white/10 dark:bg-white/[0.04]",
  },
  waiting: {
    label: "等待中",
    Icon: ClipboardList,
    pillClassName:
      "border-slate-200 bg-slate-50 text-slate-700 dark:border-white/15 dark:bg-white/[0.06] dark:text-slate-200",
    cardClassName:
      "border-gray-200/80 bg-white/75 dark:border-white/10 dark:bg-white/[0.04]",
  },
  waiting_upstream: {
    label: "等待上游",
    Icon: ClipboardList,
    pillClassName:
      "border-slate-200 bg-slate-50 text-slate-700 dark:border-white/15 dark:bg-white/[0.06] dark:text-slate-200",
    cardClassName:
      "border-gray-200/80 bg-white/75 dark:border-white/10 dark:bg-white/[0.04]",
  },
  ready: {
    label: "待执行",
    Icon: ClipboardList,
    pillClassName:
      "border-slate-200 bg-slate-50 text-slate-700 dark:border-white/15 dark:bg-white/[0.06] dark:text-slate-200",
    cardClassName:
      "border-gray-200/80 bg-white/75 dark:border-white/10 dark:bg-white/[0.04]",
  },
  running: {
    label: "执行中",
    Icon: Loader2,
    pillClassName:
      "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200",
    cardClassName:
      "border-sky-200/80 bg-sky-50/45 dark:border-sky-900/40 dark:bg-sky-950/12",
  },
  processing: {
    label: "处理中",
    Icon: Loader2,
    pillClassName:
      "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200",
    cardClassName:
      "border-sky-200/80 bg-sky-50/45 dark:border-sky-900/40 dark:bg-sky-950/12",
  },
  paused: {
    label: "已暂停",
    Icon: ClipboardList,
    pillClassName:
      "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200",
    cardClassName:
      "border-amber-200/80 bg-amber-50/45 dark:border-amber-900/40 dark:bg-amber-950/12",
  },
  completed: {
    label: "成功",
    Icon: CheckCircle2,
    pillClassName:
      "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200",
    cardClassName:
      "border-emerald-200/80 bg-emerald-50/40 dark:border-emerald-900/40 dark:bg-emerald-950/12",
  },
  succeeded: {
    label: "成功",
    Icon: CheckCircle2,
    pillClassName:
      "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200",
    cardClassName:
      "border-emerald-200/80 bg-emerald-50/40 dark:border-emerald-900/40 dark:bg-emerald-950/12",
  },
  failed: {
    label: "失败",
    Icon: AlertTriangle,
    pillClassName:
      "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200",
    cardClassName:
      "border-rose-200/80 bg-rose-50/40 dark:border-rose-900/40 dark:bg-rose-950/12",
  },
  preflight_failed: {
    label: "检查失败",
    Icon: AlertTriangle,
    pillClassName:
      "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200",
    cardClassName:
      "border-rose-200/80 bg-rose-50/40 dark:border-rose-900/40 dark:bg-rose-950/12",
  },
  blocked: {
    label: "阻塞",
    Icon: AlertTriangle,
    pillClassName:
      "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200",
    cardClassName:
      "border-rose-200/80 bg-rose-50/40 dark:border-rose-900/40 dark:bg-rose-950/12",
  },
  cancelled: {
    label: "已取消",
    Icon: ClipboardList,
    pillClassName:
      "border-slate-200 bg-slate-50 text-slate-600 dark:border-white/15 dark:bg-white/[0.06] dark:text-slate-300",
    cardClassName:
      "border-gray-200/80 bg-white/70 dark:border-white/10 dark:bg-white/[0.035]",
  },
}

export const WORKSPACE_SPINNING_TASK_STATUSES = new Set(["running", "processing"])

const WORKSPACE_SUCCESS_TASK_STATUSES = new Set(["completed", "succeeded"])

export const WORKSPACE_FAILED_TASK_STATUSES = new Set([
  "failed",
  "blocked",
  "preflight_failed",
])

const WORKSPACE_NOTIFICATION_TASK_STATUSES = new Set([
  ...WORKSPACE_SUCCESS_TASK_STATUSES,
  ...WORKSPACE_FAILED_TASK_STATUSES,
])

const WORKSPACE_CANVAS_GENERATION_TASK_TYPES = new Set([
  "video_prompt",
  "workflow_cinematic_script",
  "storyboard_image",
  "storyboard_image_edit",
  "visual_handoff_image",
  "storyboard_video",
  "route_video",
])

export function isWorkspaceTaskNotification(task: TaskRow) {
  const status = String(task.status ?? "").trim()
  return (
    WORKSPACE_NOTIFICATION_TASK_STATUSES.has(status) &&
    !task.notificationClearedAt
  )
}

export function taskLocationText(task: TaskRow) {
  return [
    task.assetName,
    task.assetType,
    task.episodeId,
    task.nodeId ?? task.assetId,
  ]
    .filter(Boolean)
    .join(" · ")
}

export function cleanTaskText(value?: string | null) {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim()
}

export function rawTaskText(value?: string | null) {
  return String(value ?? "")
    .replace(/\r\n/g, "\n")
    .trim()
}

export function firstTaskText(...values: Array<string | null | undefined>) {
  for (const value of values) {
    const text = cleanTaskText(value)
    if (text) return text
  }
  return ""
}

function taskNodeTextValue(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim()
    if (typeof value === "number" && Number.isFinite(value))
      return String(value)
  }
  return ""
}

function workspaceTaskNoticeKey(value: string) {
  return value.replace(/\s+/g, "").toLowerCase()
}

const GENERIC_WORKSPACE_SUCCESS_NOTICE_KEYS = new Set(
  [
    "分镜图已生成成功",
    "视觉交接图已生成成功",
    "视频已生成成功",
    "故事版视频已生成成功",
  ].map(workspaceTaskNoticeKey)
)

function workspaceTaskNoticeIsGenericSuccess(value: string) {
  return GENERIC_WORKSPACE_SUCCESS_NOTICE_KEYS.has(
    workspaceTaskNoticeKey(value)
  )
}

function workspaceGenerationTaskStage(task: TaskRow) {
  const taskType = String(task.type ?? task.generationTaskType ?? "").trim()
  if (taskType === "storyboard_image") return "分镜图"
  if (taskType === "storyboard_image_edit") return "分镜图修改版"
  if (taskType === "visual_handoff_image") return "视觉交接图"
  if (taskType === "storyboard_video" || taskType === "route_video")
    return "视频"
  return ""
}

function workspaceTaskWorkChainName(task: TaskRow) {
  return taskNodeTextValue(
    task.workChainLabel,
    task.workChainTitle,
    task.workChainName,
    task.routeLabel
  )
}

function workspaceScopedGenerationNotice(task: TaskRow, statusText: string) {
  if (!statusText) return ""
  const workChainName = workspaceTaskWorkChainName(task)
  return workChainName ? `${workChainName}：${statusText}` : statusText
}

function workspaceTaskSuccessNoticeText(task: TaskRow) {
  const stage = workspaceGenerationTaskStage(task)
  if (stage) return workspaceScopedGenerationNotice(task, `${stage}已生成成功`)
  return ""
}

function workspaceTaskReadyNoticeText(task: TaskRow) {
  const stage = workspaceGenerationTaskStage(task)
  if (!stage) return ""
  return workspaceScopedGenerationNotice(task, `${stage}已就绪`)
}

function workspaceTaskRunningNoticeText(task: TaskRow) {
  const stage = workspaceGenerationTaskStage(task)
  if (!stage) return ""
  return workspaceScopedGenerationNotice(task, `${stage}正在生成`)
}

function workspaceTaskFailureNoticeText(task: TaskRow) {
  const stage = workspaceGenerationTaskStage(task)
  if (!stage) return ""
  return workspaceScopedGenerationNotice(task, `${stage}生成失败`)
}

function workspaceTaskNotificationNodeId(task: TaskRow | undefined | null) {
  if (!task) return ""
  const taskType = taskNodeTextValue(task.type, task.generationTaskType)
  const explicitFocusNodeId = taskNodeTextValue(
    task.focusTarget?.nodeId,
    task.projectEffect?.focusTarget?.nodeId
  )
  if (explicitFocusNodeId) return explicitFocusNodeId
  if (
    taskType === "storyboard_image" ||
    taskType === "storyboard_image_edit" ||
    taskType === "visual_handoff_image" ||
    taskType === "storyboard_video" ||
    taskType === "route_video"
  ) {
    return taskNodeTextValue(
      task.versionNodeId,
      task.outputNodeId,
      task.resultNodeId,
      task.result?.nodeId,
      task.nodeId
    )
  }
  return ""
}

export function workspaceTaskNotificationFocusTarget(task: TaskRow) {
  const nodeId = workspaceTaskNotificationNodeId(task)
  if (!nodeId)
    return task.projectEffect?.focusTarget ?? task.focusTarget ?? null
  const focusTarget =
    task.focusTarget ?? task.projectEffect?.focusTarget ?? null
  return {
    ...(focusTarget ?? {}),
    section: focusTarget?.section ?? "episode",
    episodeId: focusTarget?.episodeId ?? task.episodeId ?? undefined,
    nodeId,
  }
}

function workspaceTaskTimestampMs(value?: number | string | null) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value > 10_000_000_000 ? value : value * 1000
  }
  if (typeof value !== "string") return null
  const text = value.trim()
  if (!text) return null
  const numeric = Number(text)
  if (Number.isFinite(numeric))
    return numeric > 10_000_000_000 ? numeric : numeric * 1000
  const monthDay = text.match(
    /^(\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{2})(?::\d{2})?$/
  )
  if (monthDay) {
    const [, month, day, hour, minute] = monthDay
    return new Date(
      new Date().getFullYear(),
      Number(month) - 1,
      Number(day),
      Number(hour),
      Number(minute)
    ).getTime()
  }
  const parsed = Date.parse(text)
  return Number.isFinite(parsed) ? parsed : null
}

function workspaceTaskSortTimestamp(task: TaskRow) {
  return (
    workspaceTaskTimestampMs(
      task.updatedAt ??
        task.completedAt ??
        task.failedAt ??
        task.startedAt ??
        task.createdAt
    ) ?? 0
  )
}

function workspaceTaskDisplayDedupeKey(task: TaskRow) {
  const taskType = String(task.generationTaskType ?? task.type ?? "").trim()
  if (!WORKSPACE_CANVAS_GENERATION_TASK_TYPES.has(taskType)) {
    const idempotencyKey = cleanTaskText(task.idempotencyKey)
    if (idempotencyKey) return `intent:${idempotencyKey}`
    return task.id ? `id:${task.id}` : ""
  }
  const projectId = cleanTaskText(task.projectId)
  const episodeId = cleanTaskText(task.episodeId ?? task.focusTarget?.episodeId)
  const taskNodeId = (task as TaskRow & { taskNodeId?: unknown }).taskNodeId
  const nodeId = taskNodeTextValue(
    task.generationTaskNodeId,
    taskNodeId,
    task.nodeId,
    task.focusTarget?.nodeId,
    task.projectEffect?.focusTarget?.nodeId
  )
  if (!projectId || !episodeId || !nodeId) {
    const idempotencyKey = cleanTaskText(task.idempotencyKey)
    if (idempotencyKey) return `intent:${idempotencyKey}`
    return task.id ? `id:${task.id}` : ""
  }
  const resultNodeId = taskNodeTextValue(
    task.resultNodeId,
    task.outputNodeId,
    task.versionNodeId,
    task.result?.nodeId
  )
  return [
    "canvas-task",
    taskType,
    projectId,
    episodeId,
    nodeId,
    resultNodeId,
  ].join("|")
}

function selectWorkspaceTaskDisplayRow(current: TaskRow | undefined, next: TaskRow) {
  if (!current) return next
  const currentActive = isWorkspaceTaskActive(current)
  const nextActive = isWorkspaceTaskActive(next)
  if (currentActive !== nextActive) return nextActive ? next : current
  return workspaceTaskSortTimestamp(next) >= workspaceTaskSortTimestamp(current)
    ? next
    : current
}

export function dedupeWorkspaceProjectTasks(tasks: TaskRow[]) {
  const byKey = new Map<string, TaskRow>()
  tasks.forEach((task) => {
    const key = workspaceTaskDisplayDedupeKey(task)
    if (!key) return
    byKey.set(key, selectWorkspaceTaskDisplayRow(byKey.get(key), task))
  })
  return Array.from(byKey.values()).sort(
    (left, right) => workspaceTaskSortTimestamp(right) - workspaceTaskSortTimestamp(left)
  )
}

export function formatWorkspaceTaskDateTime(value?: number | string | null) {
  const timestamp = workspaceTaskTimestampMs(value)
  if (timestamp === null) return ""
  const date = new Date(timestamp)
  const pad = (item: number) => String(item).padStart(2, "0")
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function taskFinishedTimeText(task: TaskRow) {
  return formatWorkspaceTaskDateTime(
    task.completedAt ?? task.failedAt ?? task.updatedAt ?? task.createdAt
  )
}

export function taskStartedTimeText(task: TaskRow) {
  return formatWorkspaceTaskDateTime(
    task.startedAt ?? task.createdAt ?? task.updatedAt
  )
}

export function normalizedTaskNoticeText(task: TaskRow, value?: string | null) {
  const text = cleanTaskText(value)
  const taskType = String(task.type ?? task.generationTaskType ?? "").trim()
  const status = String(task.status ?? "").trim()
  const runningNotice = workspaceTaskRunningNoticeText(task)
  if (
    isWorkspaceTaskActive(task) &&
    runningNotice &&
    !/正在请求取消/.test(text)
  ) {
    return runningNotice
  }
  const successNotice = workspaceTaskSuccessNoticeText(task)
  if (WORKSPACE_SUCCESS_TASK_STATUSES.has(status) && successNotice) {
    if (task.result?.skipped || /已就绪/.test(text)) {
      return workspaceTaskReadyNoticeText(task) || successNotice
    }
    return successNotice
  }
  const failureNotice = workspaceTaskFailureNoticeText(task)
  if (WORKSPACE_FAILED_TASK_STATUSES.has(status) && failureNotice) {
    return failureNotice
  }
  if (!text) return ""
  if (
    taskType === "storyboard_video" &&
    /(?:写入.*版本|已调用视频模型|故事版视频版本已生成)/.test(text)
  ) {
    return successNotice || text
  }
  if (
    (taskType === "storyboard_image" || taskType === "visual_handoff_image") &&
    /(?:故事板分镜图版本已生成|写入.*版本)/.test(text)
  ) {
    return successNotice || text
  }
  if (
    (taskType === "storyboard_video" ||
      taskType === "route_video" ||
      taskType === "storyboard_image" ||
      taskType === "visual_handoff_image") &&
    workspaceTaskNoticeIsGenericSuccess(text)
  ) {
    return successNotice || text
  }
  return text
}

export async function copyTextToClipboard(text: string): Promise<void> {
  try {
    await PluginSDK.clipboard.writeText(text)
    return
  } catch {
    // Fall back to browser APIs in dev mode.
  }

  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }

  const textarea = document.createElement("textarea")
  textarea.value = text
  textarea.style.position = "fixed"
  textarea.style.opacity = "0"
  document.body.appendChild(textarea)
  try {
    textarea.select()
    const copied = document.execCommand("copy")
    if (!copied) throw new Error("复制到剪贴板失败")
  } finally {
    document.body.removeChild(textarea)
  }
}

export function splitFailureText(value?: string | null) {
  const text = cleanTaskText(value)
  if (!text) return { title: "", reason: "" }
  const match = text.match(/^(.*?(?:失败|错误|异常|超时))[：:]\s*(.+)$/)
  if (!match) return { title: text, reason: "" }
  return {
    title: match[1].trim(),
    reason: match[2].trim(),
  }
}

const GENERIC_TASK_FAILURE_TEXTS = new Set([
  "任务执行失败",
  "任务执行失败。",
  "执行失败",
  "执行失败。",
  "操作失败",
  "操作失败。",
  "失败",
  "失败。",
  "发生错误",
  "发生错误。",
  "未知错误",
  "未知错误。",
])

const AUXILIARY_TASK_DETAIL_LABELS = new Set(["动作", "位置"])

const WORKER_STATUS_TASK_DETAIL_LABELS = new Set([
  "当前阶段",
  "执行轮次",
  "提示词",
  "最近阶段",
  "提示快照",
])

export function taskFailureTitleFromText(value?: string | null) {
  const parts = splitFailureText(value)
  if (parts.reason) return parts.title
  const text = cleanTaskText(value)
  if (!text || GENERIC_TASK_FAILURE_TEXTS.has(text)) return ""
  if (text.length <= 36 && /(?:失败|错误|异常|超时)/.test(text)) return text
  return ""
}

export function taskFailureReasonFromText(value?: string | null) {
  const parts = splitFailureText(value)
  if (parts.reason) return parts.reason
  const text = cleanTaskText(value)
  if (!text || GENERIC_TASK_FAILURE_TEXTS.has(text)) return ""
  if (text.length <= 36 && /(?:失败|错误|异常|超时)/.test(text)) return ""
  return text
}

export function dedupeTaskDetailLines(
  rows: Array<{ label: string; value?: string | null }>,
  omitted: Array<string | null | undefined>
) {
  const seen = new Set(
    omitted.map((item) => cleanTaskText(item)).filter(Boolean)
  )
  return rows.filter((row) => {
    const text = cleanTaskText(row.value)
    if (!text || seen.has(text)) return false
    seen.add(text)
    return true
  })
}

export function taskDetailRowsToText(
  rows: Array<{ label: string; value?: string | null }>
) {
  return rows
    .map((row) => {
      const value = rawTaskText(row.value)
      return value ? `${row.label}：${value}` : ""
    })
    .filter(Boolean)
    .join("\n")
}

export function isExpandableTaskDetail(row: { label: string; value?: string | null }) {
  if (AUXILIARY_TASK_DETAIL_LABELS.has(row.label)) return false
  if (WORKER_STATUS_TASK_DETAIL_LABELS.has(row.label)) return false
  if (row.label === "开始时间" || row.label === "完成时间") return false
  const text = rawTaskText(row.value)
  if (!text) return false
  if (
    row.label === "后端异常" ||
    row.label === "完整原因" ||
    row.label === "错误详情"
  ) {
    return true
  }
  return text.includes("\n") || cleanTaskText(text).length > 80
}
