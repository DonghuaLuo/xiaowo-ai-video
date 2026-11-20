import { isWorkflowVideoTaskType } from "./workflow-video-task-types"
import type { StoryboardVersion,TaskRow } from "@/backend"
import type { WorkflowVideoTaskActionOptions } from "./workflow-canvas-model"

type WorkflowNodeLike = {
  id: string
  data: Record<string, any>
}

type WorkflowEdgeLike = Record<string, any>

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function isDirectorBoardNodeType(value?: string | null) {
  return value === "director.board"
}


function isStoryboardResultImageNode(node?: WorkflowNodeLike | null) {
  return node?.data?.eyebrow === "storyboard.image"
}
function taskTimestampMs(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value > 10_000_000_000 ? value : value * 1000
  }
  if (typeof value === "string" && value.trim()) {
    const text = value.trim()
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
  return null
}

function formatWorkflowFullDateTime(value: unknown) {
  const timestamp = taskTimestampMs(value)
  if (timestamp === null) return String(value ?? "").trim()
  const date = new Date(timestamp)
  const pad = (item: number) => String(item).padStart(2, "0")
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function taskTextValue(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim()
    if (typeof value === "number" && Number.isFinite(value))
      return String(value)
  }
  return ""
}

const GENERIC_WORKFLOW_TASK_TITLE_KEYS = new Set(
  [
    "任务",
    "生成版本",
    "分镜",
    "片段剧本",
    "分镜脚本",
    "分镜单元",
    "分镜图",
    "分镜图资产",
    "分镜结果图",
    "分镜图结果卡",
    "故事板分镜图",
    "当前分镜图",
    "视觉交接图",
    "视觉交接",
    "视频",
    "视频片段",
    "故事版视频",
    "最终视频",
    "当前视频",
    "视频提示词",
    "视频生成",
    "影视化剧本",
  ].map((item) => item.replace(/\s+/g, "").toLowerCase())
)

function workflowTaskTitleKey(value: string) {
  return value.replace(/\s+/g, "").toLowerCase()
}

function workflowTaskMeaningfulTitle(...values: unknown[]) {
  for (const value of values) {
    const title = taskTextValue(value)
    if (
      title &&
      !GENERIC_WORKFLOW_TASK_TITLE_KEYS.has(workflowTaskTitleKey(title))
    ) {
      return title
    }
  }
  return ""
}

function workflowTaskNoticeIsGenericSuccess(value: string) {
  const key = workflowTaskTitleKey(value)
  return new Set([
    "分镜图已生成成功",
    "视觉交接图已生成成功",
    "视频已生成成功",
    "故事版视频已生成成功",
  ]).has(key)
}

function workflowTaskOutputSuccessText(title: string, outputLabel: string) {
  const cleanTitle = title.trim()
  if (!cleanTitle) return `${outputLabel}已生成成功`
  if (
    workflowTaskTitleKey(cleanTitle).endsWith(workflowTaskTitleKey(outputLabel))
  ) {
    return `${cleanTitle}已生成成功`
  }
  return `${cleanTitle}${outputLabel}已生成成功`
}

function workflowTaskSuccessText(
  task: TaskRow | undefined,
  result?: Record<string, unknown>
) {
  if (!task) return "任务已完成"
  if (task.type === "video_prompt" && task.promptOperation === "optimize") return "视频提示词优化成功"
  const taskType = String(task.type ?? task.generationTaskType ?? "").trim()
  const resultNode = recordValue(result?.node ?? result?.resultNode)
  const resultNodeData = recordValue(resultNode.data)
  const version = recordValue(result?.version)
  const taskResult = recordValue(task.result)
  const taskResultNode = recordValue(taskResult.node ?? taskResult.resultNode)
  const taskResultNodeData = recordValue(taskResultNode.data)
  const taskVersion = recordValue(task.version)
  const videoJob = recordValue(
    (task as TaskRow & { videoJob?: unknown }).videoJob
  )
  const focusTarget = recordValue(task.focusTarget)
  const projectEffect = recordValue(task.projectEffect)
  const title = workflowTaskMeaningfulTitle(
    (task as TaskRow & { nodeTitle?: unknown }).nodeTitle,
    (task as TaskRow & { title?: unknown }).title,
    task.assetName,
    videoJob.resultTitle,
    videoJob.taskTitle,
    videoJob.title,
    taskResultNodeData.assetName,
    resultNodeData.assetName,
    taskResultNodeData.title,
    resultNodeData.title,
    taskVersion.title,
    version.title,
    focusTarget.label
  )
  const notice = taskTextValue(task.notice, projectEffect.notice, task.message)
  const backendTextPattern =
    /(?:写入.*版本|故事版.*版本|已调用.*模型|任务卡已有提示词|工作流节点已运行)/
  if (
    notice &&
    !backendTextPattern.test(notice) &&
    !workflowTaskNoticeIsGenericSuccess(notice)
  ) {
    return notice
  }
  if (taskType === "storyboard_image") {
    return workflowTaskOutputSuccessText(title, "分镜图")
  }
  if (taskType === "workflow_cinematic_script") {
    return workflowTaskOutputSuccessText(title, "片段剧本")
  }
  if (taskType === "storyboard_plan") {
    return workflowTaskOutputSuccessText(title, "分镜脚本")
  }
  if (taskType === "video_prompt") {
    return workflowTaskOutputSuccessText(title, "视频提示词")
  }
  if (taskType === "visual_handoff_image") {
    return workflowTaskOutputSuccessText(title, "视觉交接图")
  }
  if (taskType === "storyboard_image_edit")
    return `${title || "分镜图"}修改版已生成成功`
  if (taskType === "storyboard_video" || taskType === "route_video") {
    return workflowTaskOutputSuccessText(title, "视频")
  }
  return `${title || "任务"}已完成`
}

const ACTIVE_WORKFLOW_TASK_STATUSES = new Set([
  "created",
  "queued",
  "waiting",
  "waiting_upstream",
  "running",
  "processing",
])

const BLOCKING_WORKFLOW_TASK_STATUSES = new Set([
  "created",
  "queued",
  "waiting_upstream",
  "running",
  "processing",
])

const WORKFLOW_PRIMARY_RUNNING_TASK_STATUSES = new Set([
  "created",
  "queued",
  "waiting",
  "waiting_upstream",
  "running",
  "processing",
])

function workflowTaskNodeId(task: TaskRow | undefined | null) {
  if (!task) return ""
  return taskTextValue(
    task.focusTarget?.nodeId,
    task.projectEffect?.focusTarget?.nodeId,
    task.nodeId
  )
}

function workflowTaskExecutionNodeId(task: TaskRow | undefined | null) {
  if (!task) return ""
  return taskTextValue(
    task.nodeId,
    task.generationTaskNodeId,
    (task as TaskRow & { taskNodeId?: unknown }).taskNodeId,
    task.result?.nodeId,
    task.focusTarget?.nodeId,
    task.projectEffect?.focusTarget?.nodeId
  )
}

function workflowTaskRelatedNodeIds(task: TaskRow | undefined | null) {
  const ids = new Set<string>()
  const add = (value: unknown) => {
    const id = String(value ?? "").trim()
    if (id) ids.add(id)
  }
  add(workflowTaskExecutionNodeId(task))
  add(workflowTaskNodeId(task))
  add(task?.nodeId)
  add(task?.generationTaskNodeId)
  add(
    (task as (TaskRow & { taskNodeId?: unknown }) | undefined | null)
      ?.taskNodeId
  )
  add(task?.resultNodeId)
  add(task?.outputNodeId)
  add(task?.versionNodeId)
  add(task?.result?.nodeId)
  add(task?.focusTarget?.nodeId)
  add(task?.projectEffect?.focusTarget?.nodeId)
  const resultNode = recordValue(task?.result?.node)
  const resultOutputNode = recordValue(task?.result?.resultNode)
  add(resultNode.id)
  add(resultOutputNode.id)
  return ids
}

const WORKFLOW_GENERATED_MEDIA_TASK_TYPES = new Set([
  "storyboard_image",
  "storyboard_image_generation",
  "storyboard_image_edit",
  "visual_handoff_image",
  "storyboard_video",
  "route_video",
  "storyboard_video_generation",
])

function workflowTaskCanvasResultNodeIds(task: TaskRow | undefined | null) {
  if (!WORKFLOW_GENERATED_MEDIA_TASK_TYPES.has(workflowStatusTaskType(task))) {
    return new Set<string>()
  }
  const ids = new Set<string>()
  const add = (value: unknown) => {
    const id = String(value ?? "").trim()
    if (id) ids.add(id)
  }
  add(task?.resultNodeId)
  add(task?.outputNodeId)
  add(task?.versionNodeId)
  add(task?.result?.nodeId)
  add((task?.result as Record<string, unknown> | undefined)?.resultNodeId)
  const resultNode = recordValue(task?.result?.node)
  const resultOutputNode = recordValue(task?.result?.resultNode)
  add(resultNode.id)
  add(resultOutputNode.id)
  return ids
}

function workflowTaskBlockingNodeIds(task: TaskRow | undefined | null) {
  const ids = new Set<string>()
  const add = (value: unknown) => {
    const id = String(value ?? "").trim()
    if (id) ids.add(id)
  }
  add(workflowTaskExecutionNodeId(task))
  add(task?.nodeId)
  add(task?.generationTaskNodeId)
  add(
    (task as (TaskRow & { taskNodeId?: unknown }) | undefined | null)
      ?.taskNodeId
  )
  if (ids.size === 0) add(workflowTaskNodeId(task))
  return ids
}

function workflowTaskId(task: TaskRow | undefined | null) {
  return String(task?.id ?? "").trim()
}

function workflowTaskVersionId(task: TaskRow | undefined | null) {
  const payload = task as
    | (TaskRow & {
        version?: StoryboardVersion | null
        result?: { version?: StoryboardVersion | null } | null
      })
    | undefined
    | null
  return taskTextValue(
    payload?.versionId,
    payload?.version?.id,
    payload?.result?.version?.id
  )
}

function workflowTaskVersion(task: TaskRow | undefined | null) {
  const payload = task as
    | (TaskRow & {
        version?: StoryboardVersion | null
        result?:
          | (TaskRow["result"] & { version?: StoryboardVersion | null })
          | null
      })
    | undefined
    | null
  const directVersion = payload?.version
  if (directVersion && typeof directVersion === "object") return directVersion
  const resultVersion = payload?.result?.version
  return resultVersion && typeof resultVersion === "object"
    ? resultVersion
    : null
}

function workflowTaskCanvasStatus(task: TaskRow | undefined | null) {
  const status = String(task?.status ?? "").trim()
  return task?.type === "agent_turn" && ACTIVE_WORKFLOW_TASK_STATUSES.has(status)
    ? String(task.canvasStageStatus || status)
    : status
}

function isWorkflowTaskActive(task: TaskRow | undefined | null) {
  return ACTIVE_WORKFLOW_TASK_STATUSES.has(workflowTaskCanvasStatus(task))
}

function isWorkflowTaskBlockingRun(task: TaskRow | undefined | null) {
  return BLOCKING_WORKFLOW_TASK_STATUSES.has(workflowTaskCanvasStatus(task))
}

function workflowTaskIsRunningForPrimaryDisplay(
  task: TaskRow | undefined | null
) {
  return WORKFLOW_PRIMARY_RUNNING_TASK_STATUSES.has(
    workflowTaskCanvasStatus(task)
  )
}

function workflowTaskCardPrimaryTaskTypes(nodeType: string) {
  if (nodeType === "prompt.storyboard") return ["workflow_cinematic_script"]
  if (isDirectorBoardNodeType(nodeType)) return ["storyboard_plan"]
  if (isWorkflowVideoTaskType(nodeType)) {
    return [
      "video_prompt",
      "storyboard_video",
      "route_video",
      "storyboard_video_generation",
    ]
  }
  return []
}

function workflowTaskMatchesTaskCardPrimaryState(
  data: Record<string, any>,
  task: TaskRow | undefined | null
) {
  if (!task) return false
  return workflowTaskCardPrimaryTaskTypes(data.eyebrow).includes(
    workflowStatusTaskType(task)
  )
}

function findBlockingWorkflowTaskForNode(tasks: TaskRow[], nodeId: string) {
  const targetNodeId = String(nodeId ?? "").trim()
  if (!targetNodeId) return undefined
  return tasks.find(
    (task) =>
      workflowTaskBlockingNodeIds(task).has(targetNodeId) &&
      isWorkflowTaskBlockingRun(task)
  )
}

const WORKFLOW_TASK_REFRESH_DEBOUNCE_MS = 180
const WORKFLOW_BACKEND_READ_TIMEOUT_MS = 12000
const WORKFLOW_MISSING_ACTIVE_TASK_GRACE_MS = 0
const LOCAL_WORKFLOW_LAUNCH_STALE_MS = 8_000
const WORKFLOW_STALE_INDICATOR_SWEEP_MS = 3_000

const WORKFLOW_STALE_NODE_TASK_STATUSES = new Set([
  "created",
  "queued",
  "waiting",
  "waiting_upstream",
  "running",
  "processing",
])

function isStaleWorkflowNodeTaskStatus(status: unknown) {
  return WORKFLOW_STALE_NODE_TASK_STATUSES.has(String(status ?? "").trim())
}

function withBackendReadTimeout<T>(
  promise: Promise<T>,
  message: string,
  timeoutMs = WORKFLOW_BACKEND_READ_TIMEOUT_MS
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

function filterWorkflowTasksForNodes(
  tasks: TaskRow[],
  nodes: Array<{ id?: string | null }>
) {
  const nodeIds = new Set(
    nodes.map((node) => String(node.id ?? "").trim()).filter(Boolean)
  )
  return tasks.filter((task) => {
    const relatedNodeIds = workflowTaskRelatedNodeIds(task)
    return (
      relatedNodeIds.size === 0 ||
      Array.from(relatedNodeIds).some((nodeId) => nodeIds.has(nodeId)) ||
      !isWorkflowTaskActive(task)
    )
  })
}

function workflowTaskPriority(task: TaskRow) {
  const status = String(task.status || "")
  let priority = task.type === "workflow_node" ? 0 : 4
  if (["created", "queued", "waiting", "waiting_upstream"].includes(status))
    priority += 4
  if (status === "running") priority += 5
  if (["failed", "blocked", "preflight_failed"].includes(status)) priority += 6
  if (["completed", "succeeded"].includes(status)) priority += 3
  if (status === "cancelled" || status === "canceled") priority -= 1
  return priority
}

function workflowTaskTimestampValue(task: TaskRow | undefined | null) {
  const value =
    task?.updatedAt ??
    task?.completedAt ??
    task?.failedAt ??
    task?.startedAt ??
    task?.createdAt
  return taskTimestampMs(value) ?? 0
}

function workflowTaskIsRecentEnough(
  task: TaskRow,
  now: number,
  graceMs: number
) {
  const timestamp = workflowTaskTimestampValue(task)
  return timestamp > 0 && now - timestamp <= graceMs
}

function selectWorkflowTaskEventRow(
  existing: TaskRow | undefined,
  incoming: TaskRow
) {
  if (!existing) return incoming
  const existingTimestamp = workflowTaskTimestampValue(existing)
  const incomingTimestamp = workflowTaskTimestampValue(incoming)
  if (
    !isWorkflowTaskActive(existing) &&
    isWorkflowTaskActive(incoming) &&
    incomingTimestamp <= existingTimestamp
  ) {
    return existing
  }
  if (existingTimestamp > incomingTimestamp) return existing
  return incoming
}

function buildActiveWorkflowTaskByNodeId(tasks: TaskRow[]) {
  const map = new Map<string, TaskRow>()
  tasks.forEach((task) => {
    if (!isWorkflowTaskBlockingRun(task)) return
    workflowTaskRelatedNodeIds(task).forEach((nodeId) => {
      const existing = map.get(nodeId)
      if (
        !existing ||
        workflowTaskPriority(task) > workflowTaskPriority(existing) ||
        (workflowTaskPriority(task) === workflowTaskPriority(existing) &&
          workflowTaskTimestampValue(task) >=
            workflowTaskTimestampValue(existing))
      ) {
        map.set(nodeId, task)
      }
    })
  })
  return map
}

const WORKFLOW_STATUS_TASK_TYPES = new Set([
  "video_prompt",
  "workflow_node",
  "workflow_batch",
  "storyboard_image",
  "storyboard_image_generation",
  "storyboard_image_edit",
  "storyboard_plan",
  "workflow_cinematic_script",
  "visual_handoff_image",
  "storyboard_video",
  "route_video",
  "storyboard_video_generation",
])

function workflowStatusTaskType(task: TaskRow | undefined | null) {
  return String(task?.generationTaskType || task?.type || "").trim()
}

function workflowTaskEpisodeId(task: TaskRow | undefined | null) {
  return taskTextValue(
    task?.episodeId,
    task?.focusTarget?.episodeId,
    task?.projectEffect?.focusTarget?.episodeId
  )
}

function workflowTaskDedupeKey(task: TaskRow | undefined | null) {
  const taskId = workflowTaskId(task)
  const idempotencyKey = String(task?.idempotencyKey ?? "").trim()
  if (idempotencyKey) return `intent:${idempotencyKey}`
  if (!isWorkflowTaskActive(task)) return taskId ? `id:${taskId}` : ""
  const taskType = workflowStatusTaskType(task)
  const nodeIds = Array.from(workflowTaskBlockingNodeIds(task)).sort()
  if (!taskType || nodeIds.length === 0) return taskId ? `id:${taskId}` : ""
  const resultNodeIds = Array.from(workflowTaskCanvasResultNodeIds(task)).sort()
  return [
    "active",
    String(task?.projectId ?? "").trim(),
    workflowTaskEpisodeId(task),
    taskType,
    nodeIds.join(","),
    resultNodeIds.join(","),
  ].join(":")
}

type WorkflowCanvasTaskScopeIndex = {
  nodeIds: Set<string>
  routeIds: Set<string>
  workChainIds: Set<string>
}

function buildWorkflowCanvasTaskScopeIndex(
  nodes: WorkflowNodeLike[]
): WorkflowCanvasTaskScopeIndex {
  const nodeIds = new Set<string>()
  const routeIds = new Set<string>()
  const workChainIds = new Set<string>()
  nodes.forEach((node) => {
    if (node.id) nodeIds.add(node.id)
    const routeId = String(node.data.routeId ?? "").trim()
    if (routeId) routeIds.add(routeId)
    const workChainId = String(node.data.workChainId ?? "").trim()
    if (workChainId) workChainIds.add(workChainId)
  })
  return { nodeIds, routeIds, workChainIds }
}

function workflowTaskBelongsToCanvas(
  task: TaskRow,
  projectId: string,
  episodeId: string,
  scopeIndex: WorkflowCanvasTaskScopeIndex
) {
  if (String(task.projectId ?? "").trim() !== projectId) return false
  const taskEpisodeId = workflowTaskEpisodeId(task)
  if (taskEpisodeId && taskEpisodeId !== episodeId) return false
  const taskType = workflowStatusTaskType(task)
  if (!WORKFLOW_STATUS_TASK_TYPES.has(taskType)) return false

  const nodeId = workflowTaskNodeId(task)
  const relatedNodeIds = workflowTaskRelatedNodeIds(task)
  if (nodeId && scopeIndex.nodeIds.has(nodeId)) return true
  for (const relatedNodeId of relatedNodeIds) {
    if (scopeIndex.nodeIds.has(relatedNodeId)) return true
  }
  const routeId = String(task.routeId ?? "").trim()
  if (routeId && scopeIndex.routeIds.has(routeId)) return true
  const workChainId = String(task.workChainId ?? "").trim()
  if (workChainId && scopeIndex.workChainIds.has(workChainId)) return true
  return Boolean(taskEpisodeId)
}

function mergeWorkflowStatusTasks(...groups: TaskRow[][]) {
  // A task can move between stages/targets. Resolve its immutable ID before
  // coalescing separate tasks which represent the same active generation.
  const byId = new Map<string, TaskRow>()
  groups.flat().forEach((task) => {
    const id = workflowTaskId(task) || workflowTaskDedupeKey(task)
    const existing = byId.get(id)
    byId.set(id, existing ? selectWorkflowTaskEventRow(task, existing) : task)
  })
  const byKey = new Map<string, TaskRow>()
  byId.forEach((task) => {
    const taskKey = workflowTaskDedupeKey(task)
    if (!taskKey) return
    byKey.set(taskKey, selectWorkflowTaskEventRow(byKey.get(taskKey), task))
  })
  return Array.from(byKey.values()).sort(
    (left, right) =>
      workflowTaskTimestampValue(right) - workflowTaskTimestampValue(left) ||
      workflowTaskPriority(right) - workflowTaskPriority(left)
  )
}

function mergeWorkflowTaskSnapshot(
  current: TaskRow[],
  incoming: TaskRow[],
  requestTasks: TaskRow[]
) {
  const currentById = new Map(current.map((task) => [workflowTaskId(task), task]))
  const requestedById = new Map(requestTasks.map((task) => [workflowTaskId(task), task]))
  const incomingIds = new Set(incoming.map(workflowTaskId))
  const retained = current.filter((task) =>
    !incomingIds.has(workflowTaskId(task)) &&
    requestedById.get(workflowTaskId(task)) !== task
  )
  return mergeWorkflowStatusTasks(
    incoming
      // Do not resurrect a task removed while the snapshot was being read.
      .filter((task) => !requestedById.has(workflowTaskId(task)) || currentById.has(workflowTaskId(task)))
      .map((task) => selectWorkflowTaskEventRow(currentById.get(workflowTaskId(task)), task)),
    retained
  )
}

function localWorkflowLaunchTaskType(
  node: WorkflowNodeLike,
  _nodes: WorkflowNodeLike[] = [],
  _edges: WorkflowEdgeLike[] = []
) {
  if (isWorkflowVideoTaskType(node.data.eyebrow)) {
    return "storyboard_video"
  }
  if (node.data.eyebrow === "prompt.storyboard")
    return "workflow_cinematic_script"
  if (isDirectorBoardNodeType(node.data.eyebrow)) return "storyboard_plan"
  if (isStoryboardResultImageNode(node)) {
    return "storyboard_image"
  }
  if (node.data.eyebrow === "video.result") return "storyboard_video"
  return "workflow_node"
}

function buildLocalWorkflowLaunchTask(
  projectId: string,
  episodeId: string,
  node: WorkflowNodeLike,
  taskType: string,
  message: string
): TaskRow {
  const now = Date.now()
  return {
    id: `local-workflow-task:${node.id}:${taskType}`,
    type: taskType,
    generationTaskType: taskType,
    projectId,
    episodeId,
    nodeId: node.id,
    nodeType: node.data.eyebrow,
    routeId: String(node.data.routeId ?? ""),
    workChainId: String(node.data.workChainId ?? ""),
    segmentId: String(node.data.segmentId ?? ""),
    status: "running",
    progress: 0,
    message,
    createdAt: now,
    startedAt: now,
    updatedAt: now,
  }
}

function buildWorkflowStatusProjection({
  projectId,
  episodeId,
  nodes,
  edges,
  workflowTasks,
  workspaceTasks,
  runningNodeIds,
  runningNodeTaskTypeByNodeId,
}: {
  projectId: string
  episodeId: string
  nodes: WorkflowNodeLike[]
  edges: WorkflowEdgeLike[]
  workflowTasks: TaskRow[]
  workspaceTasks: TaskRow[]
  runningNodeIds: Set<string>
  runningNodeTaskTypeByNodeId: Map<string, string>
}) {
  const canvasTaskScopeIndex = buildWorkflowCanvasTaskScopeIndex(nodes)
  const canvasWorkspaceTasks = workspaceTasks.filter((task) =>
    workflowTaskBelongsToCanvas(
      task,
      projectId,
      episodeId,
      canvasTaskScopeIndex
    )
  )
  const canvasWorkspaceTaskById = new Map(
    canvasWorkspaceTasks
      .map((task) => [workflowTaskId(task), task] as const)
      .filter(([taskId]) => Boolean(taskId))
  )
  const now = Date.now()
  const canvasWorkflowTasks = workflowTasks
    .filter((task) =>
      workflowTaskBelongsToCanvas(
        task,
        projectId,
        episodeId,
        canvasTaskScopeIndex
      )
    )
    .filter((task) => {
      if (!isWorkflowTaskBlockingRun(task)) return true
      const taskId = workflowTaskId(task)
      const workspaceTask = taskId
        ? canvasWorkspaceTaskById.get(taskId)
        : undefined
      if (workspaceTask) return isWorkflowTaskBlockingRun(workspaceTask)
      return workflowTaskIsRecentEnough(
        task,
        now,
        WORKFLOW_MISSING_ACTIVE_TASK_GRACE_MS
      )
    })
  const realTasks = mergeWorkflowStatusTasks(
    canvasWorkflowTasks,
    canvasWorkspaceTasks
  )
  const realActiveTaskByNodeId = buildActiveWorkflowTaskByNodeId(realTasks)
  const localTasks = nodes.flatMap((node) => {
    if (realActiveTaskByNodeId.has(node.id)) return []
    const launching = runningNodeIds.has(node.id)
    if (!launching) return []
    const taskType =
      runningNodeTaskTypeByNodeId.get(node.id) ||
      localWorkflowLaunchTaskType(node, nodes, edges)
    return [
      buildLocalWorkflowLaunchTask(
        projectId,
        episodeId,
        node,
        taskType,
        "正在启动任务..."
      ),
    ]
  })
  const tasks = mergeWorkflowStatusTasks(realTasks, localTasks)
  return {
    tasks,
    activeTaskByNodeId: buildActiveWorkflowTaskByNodeId(tasks),
  }
}

export { ACTIVE_WORKFLOW_TASK_STATUSES,BLOCKING_WORKFLOW_TASK_STATUSES,buildActiveWorkflowTaskByNodeId,buildLocalWorkflowLaunchTask,buildWorkflowCanvasTaskScopeIndex,buildWorkflowStatusProjection,filterWorkflowTasksForNodes,findBlockingWorkflowTaskForNode,formatWorkflowFullDateTime,isStaleWorkflowNodeTaskStatus,isWorkflowTaskActive,isWorkflowTaskBlockingRun,LOCAL_WORKFLOW_LAUNCH_STALE_MS,localWorkflowLaunchTaskType,mergeWorkflowStatusTasks,mergeWorkflowTaskSnapshot,selectWorkflowTaskEventRow,taskTextValue,taskTimestampMs,withBackendReadTimeout,WORKFLOW_BACKEND_READ_TIMEOUT_MS,WORKFLOW_GENERATED_MEDIA_TASK_TYPES,WORKFLOW_MISSING_ACTIVE_TASK_GRACE_MS,WORKFLOW_PRIMARY_RUNNING_TASK_STATUSES,WORKFLOW_STALE_INDICATOR_SWEEP_MS,WORKFLOW_STATUS_TASK_TYPES,WORKFLOW_TASK_REFRESH_DEBOUNCE_MS,workflowStatusTaskType,workflowTaskBelongsToCanvas,workflowTaskBlockingNodeIds,workflowTaskCanvasResultNodeIds,workflowTaskCardPrimaryTaskTypes,workflowTaskDedupeKey,workflowTaskEpisodeId,workflowTaskExecutionNodeId,workflowTaskId,workflowTaskIsRecentEnough,workflowTaskIsRunningForPrimaryDisplay,workflowTaskMatchesTaskCardPrimaryState,workflowTaskMeaningfulTitle,workflowTaskNodeId,workflowTaskPriority,workflowTaskRelatedNodeIds,workflowTaskSuccessText,workflowTaskTimestampValue,workflowTaskVersion,workflowTaskVersionId }


export function workflowContextRunLabel(
  nodeType: string,
  _options: WorkflowVideoTaskActionOptions = {}
) {
  if (nodeType === "prompt.storyboard") return "生成片段剧本"
  if (isDirectorBoardNodeType(nodeType)) return "生成分镜脚本"
  if (isWorkflowVideoTaskType(nodeType)) {
    return "生成视频"
  }
  return "运行节点"
}

export function workflowContextRunningLabel(
  nodeType: string,
  options: WorkflowVideoTaskActionOptions = {}
) {
  if (options.activeTaskType === "workflow_cinematic_script") {
    return "正在生成片段剧本"
  }
  if (options.activeTaskType === "storyboard_plan") {
    return "正在生成分镜脚本"
  }
  if (options.activeTaskType === "video_prompt") {
    return "正在生成视频提示词"
  }
  if (nodeType === "prompt.storyboard" || nodeType === "storyboard.image") {
    return nodeType === "prompt.storyboard" ? "正在生成片段剧本" : "正在生成分镜图"
  }
  if (isWorkflowVideoTaskType(nodeType)) {
    return "正在生成视频"
  }
  return "正在运行节点"
}

export function workflowContextDeleteLabel(nodeType: string) {
  if (nodeType === "prompt.storyboard") return "删除片段剧本"
  if (isDirectorBoardNodeType(nodeType)) return "删除分镜脚本"
  if (isWorkflowVideoTaskType(nodeType)) return "删除视频生成"
  if (
    nodeType === "asset.image" ||
    nodeType === "media.external"
  )
    return "删除资产"
  if (nodeType === "storyboard.image") return "删除分镜图"
  if (nodeType === "video.result") return "删除视频片段"
  return "删除节点"
}

export function assertWorkflowTaskAccepted(task: TaskRow) {
  const status = String(task?.status ?? "").trim()
  if (
    status === "failed" ||
    status === "blocked" ||
    status === "preflight_failed"
  ) {
    throw new Error(String(task?.message || "节点运行失败"))
  }
}
