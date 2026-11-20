import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  LOCAL_WORKFLOW_LAUNCH_STALE_MS,
  WORKFLOW_MISSING_ACTIVE_TASK_GRACE_MS,
  WORKFLOW_STALE_INDICATOR_SWEEP_MS,
  WORKFLOW_STATUS_TASK_TYPES,
  WORKFLOW_TASK_REFRESH_DEBOUNCE_MS,
  buildActiveWorkflowTaskByNodeId,
  buildWorkflowCanvasTaskScopeIndex,
  buildWorkflowStatusProjection,
  filterWorkflowTasksForNodes,
  isWorkflowTaskBlockingRun,
  mergeWorkflowStatusTasks,
  mergeWorkflowTaskSnapshot,
  selectWorkflowTaskEventRow,
  withBackendReadTimeout,
  workflowStatusTaskType,
  workflowTaskBelongsToCanvas,
  workflowTaskDedupeKey,
  workflowTaskId,
  workflowTaskIsRecentEnough,
} from "./workflow-task-status"
import { useWorkspaceDockStore } from "@/features/workspace/workspace-dock-store"
import { listWorkflowTasks, type TaskRow } from "@/backend"
import type { BackendCaller } from "@/backend"
import type { StoryboardNode, StoryboardEdge } from "./workflow-canvas-model"

export function useWorkflowTaskLifecycle({
  projectId,
  episodeId,
  backendReady,
  callBackend,
  nodes,
  edges,
  workspaceTasks,
  onStaleNodes,
}: {
  projectId: string
  episodeId: string
  backendReady: boolean
  callBackend: BackendCaller
  nodes: StoryboardNode[]
  edges: StoryboardEdge[]
  workspaceTasks: TaskRow[]
  onStaleNodes: (
    active: Map<string, TaskRow>,
    freshLaunchingIds: Set<string>
  ) => void
}) {
  const canvasScopeKey = `${projectId}\u0000${episodeId}`
  const canvasRequestScopeRef = useRef({ key: canvasScopeKey })
  if (canvasRequestScopeRef.current.key !== canvasScopeKey)
    canvasRequestScopeRef.current = { key: canvasScopeKey }
  const nodesRef = useRef(nodes)
  nodesRef.current = nodes
  const [runningNodeIds, setRunningNodeIds] = useState<Set<string>>(
    () => new Set()
  )
  const runningNodeIdsRef = useRef<Set<string>>(new Set())
  const runningNodeLaunchStartedAtRef = useRef<Map<string, number>>(new Map())
  const runningNodeLaunchTaskTypeRef = useRef<Map<string, string>>(new Map())
  const setNodeRunLaunching = useCallback(
    (nodeId: string, active: boolean, taskType?: string) => {
      if (!nodeId) return
      const next = new Set(runningNodeIdsRef.current)
      if (active) {
        next.add(nodeId)
        runningNodeLaunchStartedAtRef.current.set(nodeId, Date.now())
        const normalizedTaskType = String(taskType ?? "").trim()
        if (normalizedTaskType) {
          runningNodeLaunchTaskTypeRef.current.set(nodeId, normalizedTaskType)
        } else {
          runningNodeLaunchTaskTypeRef.current.delete(nodeId)
        }
      } else {
        next.delete(nodeId)
        runningNodeLaunchStartedAtRef.current.delete(nodeId)
        runningNodeLaunchTaskTypeRef.current.delete(nodeId)
      }
      runningNodeIdsRef.current = next
      setRunningNodeIds(next)
    },
    []
  )
  const [workflowTasks, setWorkflowTasks] = useState<TaskRow[]>([])
  const workflowTasksRef = useRef<TaskRow[]>(workflowTasks)
  workflowTasksRef.current = workflowTasks
  const refreshWorkflowTasksInFlightRef = useRef<Promise<void> | null>(null)
  const refreshWorkflowTasksPendingRef = useRef(false)
  const refreshWorkflowTasksTimerRef = useRef<number | null>(null)
  const refreshWorkflowTasksDelayResolveRef = useRef<(() => void) | null>(null)
  const workflowStatusProjection = useMemo(
    () =>
      buildWorkflowStatusProjection({
        projectId: projectId,
        episodeId,
        nodes,
        edges,
        workflowTasks,
        workspaceTasks,
        runningNodeIds,
        runningNodeTaskTypeByNodeId: runningNodeLaunchTaskTypeRef.current,
      }),
    [
      edges,
      episodeId,
      nodes,
      projectId,
      runningNodeIds,
      workspaceTasks,
      workflowTasks,
    ]
  )
  const workflowStatusTasks = workflowStatusProjection.tasks
  const activeWorkflowTaskByNodeId = workflowStatusProjection.activeTaskByNodeId
  const reconcileStaleWorkflowIndicators = useCallback(() => {
    if (!backendReady) return
    const now = Date.now()
    const canvasTaskScopeIndex = buildWorkflowCanvasTaskScopeIndex(nodes)
    const authoritativeTasks = workspaceTasks.filter((task) =>
      workflowTaskBelongsToCanvas(
        task,
        projectId,
        episodeId,
        canvasTaskScopeIndex
      )
    )
    const authoritativeTaskById = new Map(
      authoritativeTasks
        .map((task) => [workflowTaskId(task), task] as const)
        .filter(([taskId]) => Boolean(taskId))
    )
    const shouldKeepWorkflowTask = (task: TaskRow) => {
      if (
        !workflowTaskBelongsToCanvas(
          task,
          projectId,
          episodeId,
          canvasTaskScopeIndex
        )
      ) {
        return true
      }
      if (!isWorkflowTaskBlockingRun(task)) return true
      const taskId = workflowTaskId(task)
      const authoritativeTask = taskId
        ? authoritativeTaskById.get(taskId)
        : undefined
      if (authoritativeTask) return isWorkflowTaskBlockingRun(authoritativeTask)
      return workflowTaskIsRecentEnough(
        task,
        now,
        WORKFLOW_MISSING_ACTIVE_TASK_GRACE_MS
      )
    }
    const retainedWorkflowTasks = workflowTasks.filter(shouldKeepWorkflowTask)
    const retainedActiveTaskByNodeId = buildActiveWorkflowTaskByNodeId(
      mergeWorkflowStatusTasks(authoritativeTasks, retainedWorkflowTasks)
    )
    setWorkflowTasks((current) => {
      const next = current.filter(shouldKeepWorkflowTask)
      return next.length === current.length ? current : next
    })
    setRunningNodeIds((current) => {
      let changed = false
      const next = new Set<string>()
      current.forEach((nodeId) => {
        const startedAt = runningNodeLaunchStartedAtRef.current.get(nodeId) ?? 0
        const freshLocalLaunch =
          startedAt > 0 && now - startedAt <= LOCAL_WORKFLOW_LAUNCH_STALE_MS
        const keep = retainedActiveTaskByNodeId.has(nodeId) || freshLocalLaunch
        if (keep) {
          next.add(nodeId)
        } else {
          runningNodeLaunchStartedAtRef.current.delete(nodeId)
          runningNodeLaunchTaskTypeRef.current.delete(nodeId)
          changed = true
        }
      })
      if (!changed && next.size === current.size) return current
      runningNodeIdsRef.current = next
      return next
    })
    const freshLocalNodeIds = new Set<string>()
    runningNodeLaunchStartedAtRef.current.forEach((startedAt, nodeId) => {
      if (now - startedAt <= LOCAL_WORKFLOW_LAUNCH_STALE_MS) {
        freshLocalNodeIds.add(nodeId)
      }
    })
    onStaleNodes(retainedActiveTaskByNodeId, freshLocalNodeIds)
  }, [
    backendReady,
    edges,
    episodeId,
    nodes,
    projectId,
    onStaleNodes,
    workspaceTasks,
    workflowTasks,
  ])

  useEffect(() => {
    reconcileStaleWorkflowIndicators()
    if (!backendReady) return
    const timer = window.setInterval(
      reconcileStaleWorkflowIndicators,
      WORKFLOW_STALE_INDICATOR_SWEEP_MS
    )
    return () => window.clearInterval(timer)
  }, [backendReady, reconcileStaleWorkflowIndicators])

  const refreshWorkflowTasks = useCallback(
    async (options: { immediate?: boolean } = {}) => {
      if (!backendReady) return
      const requestScope = canvasRequestScopeRef.current
      if (requestScope.key !== canvasScopeKey) return
      if (!options.immediate) {
        if (refreshWorkflowTasksTimerRef.current !== null) {
          refreshWorkflowTasksPendingRef.current = true
          return
        }
        await new Promise<void>((resolve) => {
          refreshWorkflowTasksDelayResolveRef.current = resolve
          refreshWorkflowTasksTimerRef.current = window.setTimeout(() => {
            refreshWorkflowTasksTimerRef.current = null
            refreshWorkflowTasksDelayResolveRef.current = null
            resolve()
          }, WORKFLOW_TASK_REFRESH_DEBOUNCE_MS)
        })
        if (!backendReady || canvasRequestScopeRef.current !== requestScope)
          return
      }
      const activeRefresh = refreshWorkflowTasksInFlightRef.current
      if (activeRefresh) {
        refreshWorkflowTasksPendingRef.current = true
        return
      }

      refreshWorkflowTasksPendingRef.current = false
      const requestTasks = workflowTasksRef.current
      const refreshPromise = (async () => {
        try {
          const taskResult = await withBackendReadTimeout(
            listWorkflowTasks(callBackend, projectId, episodeId, {
              lightweight: true,
            }),
            "刷新工作流任务超时"
          )
          if (canvasRequestScopeRef.current !== requestScope) return
          setWorkflowTasks((current) =>
            filterWorkflowTasksForNodes(
              mergeWorkflowTaskSnapshot(
                current,
                taskResult.tasks,
                requestTasks
              ),
              nodesRef.current
            )
          )
        } catch (error) {
          console.warn("刷新工作流任务状态失败:", error)
        }
      })()
      refreshWorkflowTasksInFlightRef.current = refreshPromise
      try {
        await refreshPromise
      } finally {
        if (canvasRequestScopeRef.current !== requestScope) return
        if (refreshWorkflowTasksInFlightRef.current === refreshPromise) {
          refreshWorkflowTasksInFlightRef.current = null
        }
        if (refreshWorkflowTasksPendingRef.current) {
          refreshWorkflowTasksPendingRef.current = false
          void refreshWorkflowTasks()
        }
      }
    },
    [backendReady, callBackend, canvasScopeKey, episodeId, projectId]
  )

  const mergeWorkflowTaskEvent = useCallback(
    (payload: unknown) => {
      const task = payload as TaskRow | null
      if (!task || task.projectId !== projectId) return null
      if (task.episodeId && task.episodeId !== episodeId) return null
      const taskId = String(task.id ?? "").trim()
      if (!taskId) return null
      // IPC acceptance and backend events must update the same authoritative
      // task list before the local launch indicator is released.
      const dock = useWorkspaceDockStore.getState()
      if (
        WORKFLOW_STATUS_TASK_TYPES.has(workflowStatusTaskType(task)) &&
        (!dock.tasksProjectId || dock.tasksProjectId === projectId)
      ) {
        dock.upsertTask(task, projectId)
      }
      const taskKey = workflowTaskDedupeKey(task)
      const selectedTask = selectWorkflowTaskEventRow(
        workflowTasksRef.current.find(
          (item) =>
            String(item.id) === taskId ||
            (Boolean(taskKey) && workflowTaskDedupeKey(item) === taskKey)
        ),
        task
      )
      setWorkflowTasks((current) => {
        const existing = current.find(
          (item) =>
            String(item.id) === taskId ||
            (Boolean(taskKey) && workflowTaskDedupeKey(item) === taskKey)
        )
        const nextTask = selectWorkflowTaskEventRow(existing, task)
        return filterWorkflowTasksForNodes(
          mergeWorkflowStatusTasks([nextTask], current),
          nodesRef.current
        )
      })
      return selectedTask
    },
    [episodeId, projectId, setWorkflowTasks]
  )

  useEffect(() => {
    if (canvasRequestScopeRef.current.key !== canvasScopeKey)
      canvasRequestScopeRef.current = { key: canvasScopeKey }
    const scope = canvasRequestScopeRef.current
    setWorkflowTasks([])
    runningNodeIdsRef.current = new Set()
    setRunningNodeIds(runningNodeIdsRef.current)
    runningNodeLaunchStartedAtRef.current.clear()
    runningNodeLaunchTaskTypeRef.current.clear()
    return () => {
      if (canvasRequestScopeRef.current === scope)
        canvasRequestScopeRef.current = { key: "" }
      if (refreshWorkflowTasksTimerRef.current !== null)
        window.clearTimeout(refreshWorkflowTasksTimerRef.current)
      refreshWorkflowTasksTimerRef.current = null
      refreshWorkflowTasksDelayResolveRef.current?.()
      refreshWorkflowTasksDelayResolveRef.current = null
      refreshWorkflowTasksPendingRef.current = false
      refreshWorkflowTasksInFlightRef.current = null
    }
  }, [canvasScopeKey])
  const snapshot = useCallback(() => workflowTasksRef.current, [])
  const clear = useCallback(() => setWorkflowTasks([]), [])
  const launching = useCallback(() => runningNodeIdsRef.current, [])
  const replaceSnapshot = useCallback(
    (rows: TaskRow[], requested: TaskRow[]) => {
      setWorkflowTasks((current) =>
        filterWorkflowTasksForNodes(
          mergeWorkflowTaskSnapshot(current, rows, requested),
          nodesRef.current
        )
      )
    },
    []
  )
  const upsertRecords = useCallback((rows: TaskRow[]) => {
    setWorkflowTasks((current) =>
      rows.reduce((next, task) => {
        const id = String(task.id ?? "").trim()
        const index = next.findIndex((item) => String(item.id ?? "") === id)
        if (index < 0) return [...next, task]
        const updated = [...next]
        updated[index] = { ...next[index], ...task }
        return updated
      }, current)
    )
  }, [])
  const removeRecords = useCallback(
    (taskIds: Set<string>, nodeIds: Set<string>) => {
      setWorkflowTasks((current) =>
        current.filter((task) => {
          const taskId = String(task.id ?? "").trim()
          if (taskId && taskIds.has(taskId)) return false
          const taskNodeId = String(
            task.nodeId ?? (task as Record<string, unknown>).node_id ?? ""
          ).trim()
          return !taskNodeId || !nodeIds.has(taskNodeId)
        })
      )
    },
    []
  )
  return {
    tasks: workflowStatusTasks,
    activeTaskByNodeId: activeWorkflowTaskByNodeId,
    launchingNodeIds: runningNodeIds,
    launchTaskTypes: runningNodeLaunchTaskTypeRef.current,
    setLaunching: setNodeRunLaunching,
    launching,
    snapshot,
    clear,
    replaceSnapshot,
    upsertRecords,
    removeRecords,
    refresh: refreshWorkflowTasks,
    mergeEvent: mergeWorkflowTaskEvent,
  }
}
export type WorkflowTaskLifecycle = ReturnType<typeof useWorkflowTaskLifecycle>
