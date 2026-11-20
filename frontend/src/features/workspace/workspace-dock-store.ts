import { create } from "zustand"

import type { TaskRow, UsageSummary } from "@/backend"

export const WORKSPACE_DOCK_ACTIVE_TASK_STATUSES = new Set([
  "created",
  "queued",
  "waiting",
  "waiting_upstream",
  "running",
  "processing",
  "paused",
])

export const WORKSPACE_DOCK_TERMINAL_TASK_STATUSES = new Set([
  "completed",
  "succeeded",
  "failed",
  "blocked",
  "preflight_failed",
  "cancelled",
])

type WorkspaceDockStoreState = {
  tasks: TaskRow[]
  tasksProjectId: string | null
  tasksLoaded: boolean
  tasksLoading: boolean
  usage: UsageSummary | null
  usageLoaded: boolean
  usageLoading: boolean
  setTasks: (tasks: TaskRow[], projectId: string, requestTasks?: TaskRow[]) => void
  upsertTask: (task: TaskRow, projectId: string) => void
  markTasksLoaded: (projectId: string) => void
  setTasksLoading: (tasksLoading: boolean) => void
  setUsage: (usage: UsageSummary | null) => void
  markUsageLoaded: () => void
  setUsageLoading: (usageLoading: boolean) => void
}

function workspaceTaskFingerprint(task: TaskRow) {
  return JSON.stringify([
    task.id,
    task.type,
    task.status,
    task.progress,
    task.message,
    task.notice,
    task.error,
    task.failureReason,
    task.errorSummary,
    task.providerResponseSummary,
    task.errorDebug,
    task.traceback,
    task.stackTrace,
    task.notificationClearedAt,
    task.startedAt,
    task.createdAt,
    task.updatedAt,
    task.completedAt,
    task.failedAt,
    task.versionId,
    task.workerName,
    task.workerRunId,
    task.assetRangeId,
    task.workerRun,
    task.focusTarget,
    task.projectEffect,
  ])
}

function workspaceTaskRowsEqual(a: TaskRow[], b: TaskRow[]) {
  if (a.length !== b.length) return false
  for (let index = 0; index < a.length; index += 1) {
    if (
      workspaceTaskFingerprint(a[index]) !== workspaceTaskFingerprint(b[index])
    ) {
      return false
    }
  }
  return true
}

function workspaceTaskTimestampValue(task: TaskRow) {
  const value =
    task.updatedAt ??
    task.completedAt ??
    task.failedAt ??
    task.startedAt ??
    task.createdAt
  if (typeof value === "number" && Number.isFinite(value)) {
    return value > 10_000_000_000 ? value : value * 1000
  }
  if (typeof value === "string" && value.trim()) {
    const numeric = Number(value)
    if (Number.isFinite(numeric)) return numeric > 10_000_000_000 ? numeric : numeric * 1000
    const parsed = Date.parse(value)
    return Number.isFinite(parsed) ? parsed : 0
  }
  return 0
}

export function isWorkspaceDockTaskActive(task: TaskRow) {
  return WORKSPACE_DOCK_ACTIVE_TASK_STATUSES.has(String(task.status ?? "").trim())
}

function selectWorkspaceTaskRow(existing: TaskRow | undefined, incoming: TaskRow) {
  if (!existing) return incoming
  if (workspaceTaskFingerprint(existing) === workspaceTaskFingerprint(incoming)) {
    return existing
  }
  const existingTimestamp = workspaceTaskTimestampValue(existing)
  const incomingTimestamp = workspaceTaskTimestampValue(incoming)
  const incomingClearedNotification =
    !!incoming.notificationClearedAt &&
    incoming.notificationClearedAt !== existing.notificationClearedAt
  const existingTerminal = WORKSPACE_DOCK_TERMINAL_TASK_STATUSES.has(
    String(existing.status ?? "")
  )
  if (
    !incomingClearedNotification &&
    existingTerminal &&
    isWorkspaceDockTaskActive(incoming) &&
    incomingTimestamp <= existingTimestamp
  ) {
    return existing
  }
  if (!incomingClearedNotification && existingTimestamp > incomingTimestamp) {
    return existing
  }
  return incoming
}

function mergeWorkspaceTaskRows(
  current: TaskRow[],
  incoming: TaskRow[],
  projectId: string,
  requestTasks: TaskRow[] = current
) {
  const currentRows = current.filter((task) => task.projectId === projectId)
  const currentById = new Map(currentRows.map((task) => [task.id, task]))
  const requestedById = new Map(requestTasks.map((task) => [task.id, task]))
  const incomingIds = new Set(incoming.map((task) => task.id))
  const merged = incoming
    .filter((task) => task.projectId === projectId)
    .map((task) => {
      return selectWorkspaceTaskRow(currentById.get(task.id), task)
    })
  // A snapshot cannot delete tasks added/updated while its request was in flight.
  // A subsequent fresh snapshot can still remove tasks deleted on the backend.
  return [
    ...currentRows.filter((task) =>
      !incomingIds.has(task.id) && requestedById.get(task.id) !== task
    ),
    ...merged,
  ]
}

function upsertWorkspaceTaskRow(
  current: TaskRow[],
  task: TaskRow,
  projectId: string
) {
  if (!task?.id || task.projectId !== projectId) return current
  const existingIndex = current.findIndex((item) => item.id === task.id)
  if (existingIndex < 0) return [task, ...current]
  const nextTask = selectWorkspaceTaskRow(current[existingIndex], task)
  if (nextTask === current[existingIndex]) {
    return current
  }
  const next = [...current]
  next[existingIndex] = nextTask
  return next
}

export const useWorkspaceDockStore = create<WorkspaceDockStoreState>((set) => ({
  tasks: [],
  tasksProjectId: null,
  tasksLoaded: false,
  tasksLoading: false,
  usage: null,
  usageLoaded: false,
  usageLoading: false,
  setTasks: (tasks, projectId, requestTasks) =>
    set((current) => {
      const nextTasks = mergeWorkspaceTaskRows(
        current.tasksProjectId === projectId ? current.tasks : [],
        tasks,
        projectId,
        requestTasks
      )
      if (
        current.tasksProjectId === projectId &&
        current.tasksLoaded &&
        workspaceTaskRowsEqual(current.tasks, nextTasks)
      ) {
        return current
      }
      return {
        tasks: nextTasks,
        tasksProjectId: projectId,
        tasksLoaded: true,
      }
    }),
  upsertTask: (task, projectId) =>
    set((current) => {
      if (!task?.id || task.projectId !== projectId) return current
      const currentTasks =
        current.tasksProjectId === projectId ? current.tasks : []
      const tasks = upsertWorkspaceTaskRow(currentTasks, task, projectId)
      if (
        tasks === current.tasks &&
        current.tasksProjectId === projectId &&
        current.tasksLoaded
      ) {
        return current
      }
      return { tasks, tasksProjectId: projectId, tasksLoaded: true }
    }),
  markTasksLoaded: (projectId) =>
    set((current) => {
      if (current.tasksProjectId === projectId && current.tasksLoaded) {
        return current
      }
      return {
        tasks: current.tasksProjectId === projectId ? current.tasks : [],
        tasksProjectId: projectId,
        tasksLoaded: true,
      }
    }),
  setTasksLoading: (tasksLoading) =>
    set((current) =>
      current.tasksLoading === tasksLoading ? current : { tasksLoading }
    ),
  setUsage: (usage) =>
    set((current) =>
      current.usage === usage && current.usageLoaded
        ? current
        : { usage, usageLoaded: true }
    ),
  markUsageLoaded: () =>
    set((current) =>
      current.usageLoaded ? current : { usageLoaded: true }
    ),
  setUsageLoading: (usageLoading) =>
    set((current) =>
      current.usageLoading === usageLoading ? current : { usageLoading }
    ),
}))
