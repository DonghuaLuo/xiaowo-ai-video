import { flushSync } from "react-dom"
import { type TaskRow } from "@/backend"
import {
  isWorkspaceDockTaskActive,
  useWorkspaceDockStore,
} from "@/features/workspace/workspace-dock-store"
import {
  type AssistantBackendSuccess,
  type AssistantSessionSummary,
} from "./assistant-session-normalization"

type AssistantWorkspaceAgentTaskRow = TaskRow & {
  type?: string
  project_id?: string
  sessionId?: string
  agentAction?: string
}

export function normalizeAssistantTaskEventPayload(rawPayload: unknown): TaskRow | null {
  if (!rawPayload || typeof rawPayload !== "object") return null
  const wrapper = rawPayload as Partial<TaskRow> & {
    project_id?: string
    task?: Partial<TaskRow> & { project_id?: string }
  }
  const candidate =
    wrapper.task && typeof wrapper.task === "object" ? wrapper.task : wrapper
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

export function assistantBackendResultTasks(result: AssistantBackendSuccess) {
  const rows: unknown[] = []
  if (result.task) rows.push(result.task)
  if (Array.isArray(result.tasks)) rows.push(...result.tasks)
  if (Array.isArray(result.cancelledTasks)) rows.push(...result.cancelledTasks)
  if (Array.isArray(result.uncancelledTasks)) rows.push(...result.uncancelledTasks)
  const seen = new Set<string>()
  return rows.map(normalizeAssistantTaskEventPayload).filter((task): task is TaskRow => {
    if (!task?.id || seen.has(task.id)) return false
    seen.add(task.id)
    return true
  })
}

export function upsertAssistantReturnedTasks(
  result: AssistantBackendSuccess,
  projectId: string
) {
  const tasks = assistantBackendResultTasks(result).filter(
    (task) => task.projectId === projectId
  )
  if (!tasks.length) return
  const workspaceState = useWorkspaceDockStore.getState()
  flushSync(() => {
    for (const task of tasks) {
      workspaceState.upsertTask(task, projectId)
    }
  })
}

function assistantWorkspaceAgentTaskSessionId(task: TaskRow) {
  const agentTask = task as AssistantWorkspaceAgentTaskRow
  return String(agentTask.sessionId ?? "").trim()
}

function isAssistantWorkspaceAgentTurnTask(task: TaskRow) {
  const agentTask = task as AssistantWorkspaceAgentTaskRow
  return (
    String(agentTask.type ?? "").trim() === "agent_turn" ||
    String(agentTask.agentAction ?? "").trim() === "agent_turn"
  )
}

export function markWorkspaceAgentTurnTaskFinishedFromAssistantSession(
  projectId: string,
  sessionId: string,
  status: AssistantSessionSummary["status"] | null | undefined,
  executionId: string | undefined
) {
  const normalizedProjectId = projectId.trim()
  const normalizedSessionId = sessionId.trim()
  if (!normalizedProjectId || !normalizedSessionId || !executionId) return
  const taskStatus: TaskRow["status"] =
    status === "error" ? "failed" : status === "interrupted" ? "cancelled" : "completed"
  const now = Date.now()
  const workspaceState = useWorkspaceDockStore.getState()
  const matchedTasks = workspaceState.tasks.filter(
    (task) =>
      task.projectId === normalizedProjectId &&
      isWorkspaceDockTaskActive(task) &&
      isAssistantWorkspaceAgentTurnTask(task) &&
      task.id === executionId &&
      assistantWorkspaceAgentTaskSessionId(task) === normalizedSessionId
  )
  if (matchedTasks.length <= 0) return
  flushSync(() => {
    for (const task of matchedTasks) {
      workspaceState.upsertTask(
        {
          ...task,
          status: taskStatus,
          progress: taskStatus === "completed" ? 100 : task.progress,
          completedAt:
            taskStatus === "completed" ? (task.completedAt ?? now) : task.completedAt,
          failedAt: taskStatus === "failed" ? (task.failedAt ?? now) : task.failedAt,
        },
        normalizedProjectId
      )
    }
  })
}
