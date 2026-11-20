import { useCallback, useEffect, useMemo, useRef } from "react"
import { flushSync } from "react-dom"

import {
  getUsageSummary,
  listTasks,
  type TaskRow,
} from "@/backend"
import { useBackend } from "@/hooks/useBackend"
import {
  WORKSPACE_DOCK_TERMINAL_TASK_STATUSES,
  isWorkspaceDockTaskActive,
  useWorkspaceDockStore,
} from "@/features/workspace/workspace-dock-store"

const WORKSPACE_DOCK_POLL_INTERVAL_MS = 3000
const WORKSPACE_DOCK_IDLE_POLL_INTERVAL_MS = 30000
const WORKSPACE_DOCK_BACKEND_READ_TIMEOUT_MS = 12000

function withWorkspaceDockReadTimeout<T>(
  promise: Promise<T>,
  message: string,
  timeoutMs = WORKSPACE_DOCK_BACKEND_READ_TIMEOUT_MS
): Promise<T> {
  let timer: number | undefined
  return new Promise<T>((resolve, reject) => {
    timer = window.setTimeout(() => {
      reject(new Error(message))
    }, timeoutMs)
    promise.then(resolve, reject).finally(() => {
      if (timer !== undefined) window.clearTimeout(timer)
    })
  })
}

type WorkspaceTaskEventPayload =
  | (Partial<TaskRow> & {
      project_id?: string
      task?: Partial<TaskRow> & { project_id?: string }
    })
  | null
  | undefined

type WorkspaceAgentTaskRow = TaskRow & {
  sessionId?: string
  agentAction?: string
}

type WorkspaceAgentSessionEventPayload = {
  projectId?: string
  project_id?: string
  sessionId?: string
  status?: string
  session?: {
    id?: string
    status?: string
  }
  snapshot?: {
    status?: string
    session?: {
      id?: string
      status?: string
    }
  }
}

type WorkspaceDockSyncOptions = {
  projectId: string
  projectUpdatedAtRank?: number | string | null
  usageDockActive?: boolean
}

function normalizeWorkspaceTaskEventPayload(
  rawPayload: WorkspaceTaskEventPayload
): TaskRow | null {
  if (!rawPayload || typeof rawPayload !== "object") return null
  const wrapper = rawPayload as Partial<TaskRow> & { project_id?: string }
  const candidate =
    rawPayload.task && typeof rawPayload.task === "object"
      ? rawPayload.task
      : rawPayload
  const id = String(candidate.id ?? wrapper.id ?? "").trim()
  const projectId = String(
    candidate.projectId ??
      candidate.project_id ??
      wrapper.projectId ??
      wrapper.project_id ??
      ""
  ).trim()
  if (!id || !projectId) return null
  return {
    ...(candidate as TaskRow),
    id,
    projectId,
  }
}

function normalizeWorkspaceAgentTaskSessionId(task: TaskRow) {
  const agentTask = task as WorkspaceAgentTaskRow
  return String(agentTask.sessionId ?? "").trim()
}

function isWorkspaceAgentTurnTask(task: TaskRow) {
  const agentTask = task as WorkspaceAgentTaskRow
  return (
    String(agentTask.type ?? "").trim() === "agent_turn" ||
    String(agentTask.agentAction ?? "").trim() === "agent_turn"
  )
}

function normalizeWorkspaceAgentSessionEventPayload(
  rawPayload: unknown
): { projectId: string; sessionId: string; taskStatus: TaskRow["status"] } | null {
  if (!rawPayload || typeof rawPayload !== "object") return null
  const payload = rawPayload as WorkspaceAgentSessionEventPayload
  const payloadProjectId = String(
    payload.projectId ?? payload.project_id ?? ""
  ).trim()
  const sessionId = String(
    payload.sessionId ?? payload.snapshot?.session?.id ?? payload.session?.id ?? ""
  ).trim()
  const sessionStatus = String(
    payload.snapshot?.status ??
      payload.snapshot?.session?.status ??
      payload.session?.status ??
      payload.status ??
      ""
  )
    .trim()
    .toLowerCase()
  if (!payloadProjectId || !sessionId) return null
  if (
    !["idle", "completed", "error", "failed", "cancelled", "interrupted"].includes(
      sessionStatus
    )
  ) {
    return null
  }
  const taskStatus: TaskRow["status"] =
    sessionStatus === "error" || sessionStatus === "failed"
      ? "failed"
      : sessionStatus === "cancelled" || sessionStatus === "interrupted"
        ? "cancelled"
        : "completed"
  return { projectId: payloadProjectId, sessionId, taskStatus }
}

export function useWorkspaceDockSync({
  projectId,
  projectUpdatedAtRank,
  usageDockActive = false,
}: WorkspaceDockSyncOptions) {
  const { backendReady, callBackend, onBackendEvent } = useBackend()
  const tasks = useWorkspaceDockStore((state) => state.tasks)
  const setTasks = useWorkspaceDockStore((state) => state.setTasks)
  const upsertTask = useWorkspaceDockStore((state) => state.upsertTask)
  const markTasksLoaded = useWorkspaceDockStore((state) => state.markTasksLoaded)
  const setTasksLoading = useWorkspaceDockStore((state) => state.setTasksLoading)
  const setUsage = useWorkspaceDockStore((state) => state.setUsage)
  const markUsageLoaded = useWorkspaceDockStore((state) => state.markUsageLoaded)
  const setUsageLoading = useWorkspaceDockStore((state) => state.setUsageLoading)
  const taskListRequestIdRef = useRef(0)
  const taskListInFlightRef = useRef<Promise<void> | null>(null)
  const taskListPendingRef = useRef(false)
  const taskEventRevisionRef = useRef(0)

  const refreshTasks = useCallback(
    async (options: { showLoading?: boolean } = {}) => {
      if (!backendReady) return
      if (taskListInFlightRef.current) {
        taskListPendingRef.current = true
        return
      }
      let showLoading = options.showLoading !== false
      while (true) {
        taskListPendingRef.current = false
        const requestId = taskListRequestIdRef.current + 1
        taskListRequestIdRef.current = requestId
        const eventRevision = taskEventRevisionRef.current
        const requestTasks = useWorkspaceDockStore.getState().tasks
        if (showLoading) setTasksLoading(true)
        const refreshPromise = (async () => {
          try {
            const rows = await withWorkspaceDockReadTimeout(
              listTasks(callBackend, {
                projectId,
                workspaceDockOnly: true,
                limit: 120,
              }),
              "加载任务列表超时"
            )
            if (requestId !== taskListRequestIdRef.current) return
            if (eventRevision !== taskEventRevisionRef.current) return
            setTasks(rows, projectId, requestTasks)
          } catch (error) {
            console.warn("加载工作区任务状态失败:", error)
            markTasksLoaded(projectId)
          } finally {
            if (showLoading) setTasksLoading(false)
          }
        })()
        taskListInFlightRef.current = refreshPromise
        try {
          await refreshPromise
        } finally {
          if (taskListInFlightRef.current === refreshPromise) {
            taskListInFlightRef.current = null
          }
        }
        if (!taskListPendingRef.current) break
        showLoading = false
      }
    },
    [
      backendReady,
      callBackend,
      markTasksLoaded,
      projectId,
      setTasks,
      setTasksLoading,
    ]
  )

  const refreshUsage = useCallback(
    async (options: { showLoading?: boolean } = {}) => {
      if (!backendReady) return
      const showLoading = options.showLoading !== false
      if (showLoading) setUsageLoading(true)
      try {
        setUsage(
          await withWorkspaceDockReadTimeout(
            getUsageSummary(callBackend),
            "加载用量统计超时"
          )
        )
      } catch (error) {
        console.warn("加载工作区用量失败:", error)
        markUsageLoaded()
      } finally {
        if (showLoading) setUsageLoading(false)
      }
    },
    [backendReady, callBackend, markUsageLoaded, setUsage, setUsageLoading]
  )

  useEffect(() => {
    void refreshTasks()
  }, [refreshTasks, projectUpdatedAtRank])

  const completedTaskCount = useMemo(
    () =>
      tasks.filter(
        (task) =>
          task.projectId === projectId &&
          WORKSPACE_DOCK_TERMINAL_TASK_STATUSES.has(String(task.status ?? ""))
      ).length,
    [projectId, tasks]
  )

  useEffect(() => {
    void refreshUsage({ showLoading: false })
  }, [refreshUsage, completedTaskCount, projectUpdatedAtRank])

  useEffect(() => {
    if (!usageDockActive) return
    void refreshUsage()
  }, [refreshUsage, usageDockActive])

  useEffect(() => {
    if (!backendReady) return
    const upsertProjectTask = (payload: WorkspaceTaskEventPayload) => {
      const task = normalizeWorkspaceTaskEventPayload(payload)
      if (!task || task.projectId !== projectId) return
      taskEventRevisionRef.current += 1
      const terminalTask = WORKSPACE_DOCK_TERMINAL_TASK_STATUSES.has(
        String(task.status ?? "").trim()
      )
      if (terminalTask) {
        flushSync(() => {
          upsertTask(task, projectId)
        })
        void refreshTasks({ showLoading: false })
      } else {
        upsertTask(task, projectId)
      }
    }
    const finishActiveAgentTasks = (payload: unknown) => {
      const event = normalizeWorkspaceAgentSessionEventPayload(payload)
      if (!event || event.projectId !== projectId) return
      const currentTasks = useWorkspaceDockStore.getState().tasks
      const matchedTasks = currentTasks.filter(
        (task) =>
          task.projectId === projectId &&
          isWorkspaceDockTaskActive(task) &&
          isWorkspaceAgentTurnTask(task) &&
          normalizeWorkspaceAgentTaskSessionId(task) === event.sessionId
      )
      if (matchedTasks.length > 0) {
        taskEventRevisionRef.current += 1
        flushSync(() => {
          for (const task of matchedTasks) {
            upsertTask(
              {
                ...task,
                status: event.taskStatus,
                progress:
                  event.taskStatus === "completed" ? 100 : task.progress,
                completedAt:
                  event.taskStatus === "completed"
                    ? task.completedAt ?? Date.now()
                    : task.completedAt,
                failedAt:
                  event.taskStatus === "failed"
                    ? task.failedAt ?? Date.now()
                    : task.failedAt,
              },
              projectId
            )
          }
        })
      }
      void refreshTasks({ showLoading: false })
    }
    const unsubscribeList = [
      onBackendEvent("task_created", upsertProjectTask),
      onBackendEvent("task_progress", upsertProjectTask),
      onBackendEvent("task_completed", upsertProjectTask),
      onBackendEvent("task_failed", upsertProjectTask),
      onBackendEvent("task_cancelled", upsertProjectTask),
      onBackendEvent("agent_session_updated", finishActiveAgentTasks),
      onBackendEvent("agent_session_snapshot", finishActiveAgentTasks),
      onBackendEvent("task_notifications_cleared", (payload: any) => {
        const payloadProjectId = String(
          payload?.projectId ?? payload?.project_id ?? ""
        ).trim()
        if (payloadProjectId !== projectId) return
        taskEventRevisionRef.current += 1
        void refreshTasks({ showLoading: false })
      }),
    ]
    return () => {
      unsubscribeList.forEach((unsubscribe) => unsubscribe?.())
    }
  }, [backendReady, onBackendEvent, projectId, refreshTasks, upsertTask])

  useEffect(() => {
    if (!backendReady) return
    let lastPollAt = Date.now()
    const refreshVisibleTasks = () => {
      if (document.visibilityState === "hidden") return
      lastPollAt = Date.now()
      void refreshTasks({ showLoading: false })
    }
    const timer = window.setInterval(() => {
      const active = useWorkspaceDockStore.getState().tasks.some(
        (task) => task.projectId === projectId && isWorkspaceDockTaskActive(task)
      )
      const interval = active ? WORKSPACE_DOCK_POLL_INTERVAL_MS : WORKSPACE_DOCK_IDLE_POLL_INTERVAL_MS
      if (Date.now() - lastPollAt >= interval) refreshVisibleTasks()
    }, WORKSPACE_DOCK_POLL_INTERVAL_MS)
    document.addEventListener("visibilitychange", refreshVisibleTasks)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener("visibilitychange", refreshVisibleTasks)
    }
  }, [backendReady, projectId, refreshTasks])

  return {
    refreshTasks,
    refreshUsage,
  }
}
