import {
  workflowTaskHasGeneratedResult,
  workflowVideoTaskCanRunStandaloneVideo,
  workflowVideoTaskCanUseStandaloneInputs,
} from "./workflow-node-generation-model"
import {
  isDefaultWorkChainVideoTaskNode,
  isEditableVideoResultNode,
  isStoryboardResultImageNode,
  isWorkflowResultNodeType,
  isWorkflowTaskCardType,
  isWorkflowTaskNodeType,
  workflowNodeDataHasConcreteMediaReference,
  workflowNodeIsVisualHandoffAsset,
  workflowVideoTaskCardIsReady,
} from "./workflow-canvas-asset-model"
import {
  isDirectorBoardNodeType,
  isWorkflowResultImageType,
  isWorkflowVideoTaskType,
  optionalString,
  promptTextForNode,
  recordValue,
  workflowNodeStatus,
  workflowTaskResultEdgeByTypes,
  type StoryboardEdge,
  type StoryboardNode,
  type WorkflowNodeData,
} from "./workflow-canvas-model"
import { stringArrayValue } from "./workflow-edit-history-model"
import {
  isDefaultWorkChainStoryboardResultNode,
  storyboardResultImageHasGeneratedMedia,
  workflowNodeMediaType,
} from "./workflow-node-relations"
import {
  storyboardShootableContentReadyForNode,
  storyboardSourceFactTextForNode,
  workflowScriptCreationNodeForScope,
} from "./workflow-prompt-node-model"
import {
  isWorkflowTaskBlockingRun,
  workflowStatusTaskType,
  workflowTaskId,
  workflowTaskIsRunningForPrimaryDisplay,
  workflowTaskNodeId,
  workflowTaskPriority,
  workflowTaskRelatedNodeIds,
  workflowTaskTimestampValue,
} from "./workflow-task-status"
import {
  WORK_CHAIN_PRODUCTION_STAGES,
  WORK_CHAIN_STAGE_TASK_TYPES,
  type WorkChainProductionStateId,
  type WorkChainProgressState,
  type WorkChainProgressStep,
} from "./production-status-popover"
import {
  type EpisodeProductionStatus,
  type TaskRow,
  type WorkflowRoute,
  type WorkflowWorkChain,
} from "@/backend"

export function workChainProductionRouteIds(
  workChain: WorkflowWorkChain,
  routes: WorkflowRoute[]
) {
  const routeIds = new Set<string>()
  for (const routeId of workChain.routeIds ?? []) {
    const id = String(routeId ?? "").trim()
    if (id) routeIds.add(id)
  }
  routes.forEach((route) => {
    if (route.workChainId === workChain.id || route.id === workChain.id) {
      routeIds.add(route.id)
    }
  })
  return routeIds
}

export function workChainProductionRouteStates(
  productionStatus: EpisodeProductionStatus | undefined | null,
  workChain: WorkflowWorkChain,
  routes: WorkflowRoute[]
) {
  const routeStates = recordValue(productionStatus).routeStates
  if (!Array.isArray(routeStates)) return []
  const routeIds = workChainProductionRouteIds(workChain, routes)
  return routeStates.map(recordValue).filter((routeState) => {
    if (!Object.keys(routeState).length) return false
    const workChainId = optionalString(routeState.workChainId)
    const routeId = optionalString(routeState.routeId)
    return (
      workChainId === workChain.id || Boolean(routeId && routeIds.has(routeId))
    )
  })
}

export function workChainRouteStateSet(
  routeState: Record<string, unknown>,
  key: string
) {
  return new Set(stringArrayValue(routeState[key]))
}

export function workChainProductionStageStatus(
  routeStates: Array<Record<string, unknown>>,
  stateId: WorkChainProductionStateId
) {
  if (!routeStates.length) {
    return { completed: false }
  }
  const completed = routeStates.every((routeState) => {
    const completedStates = workChainRouteStateSet(
      routeState,
      "completedStates"
    )
    return completedStates.has(stateId)
  })
  const reviewRequired = routeStates.some((routeState) =>
    Array.isArray(routeState.blockedBy) && routeState.blockedBy.some((issue: unknown) => {
      const row = recordValue(issue)
      return row.state === stateId && row.category === "script_continuity"
    }))
  return { completed, reviewRequired }
}

export function workChainProgressStepHasRunningTask(
  stageId: WorkChainProductionStateId,
  workChain: WorkflowWorkChain,
  routeIds: Set<string>,
  nodeIds: Array<string | undefined>,
  activeTaskByNodeId: Map<string, TaskRow>
) {
  const taskTypes = new Set(WORK_CHAIN_STAGE_TASK_TYPES[stageId])
  const targetNodeIds = new Set(
    nodeIds
      .map(optionalString)
      .filter((nodeId): nodeId is string => Boolean(nodeId))
  )
  const seenTaskKeys = new Set<string>()
  for (const task of activeTaskByNodeId.values()) {
    const taskKey =
      workflowTaskId(task) ||
      [
        workflowStatusTaskType(task),
        workflowTaskTimestampValue(task),
        workflowTaskNodeId(task),
      ].join(":")
    if (seenTaskKeys.has(taskKey)) continue
    seenTaskKeys.add(taskKey)
    if (!workflowTaskIsRunningForPrimaryDisplay(task)) continue
    if (!taskTypes.has(workflowStatusTaskType(task))) continue

    const relatedNodeIds = workflowTaskRelatedNodeIds(task)
    for (const nodeId of targetNodeIds) {
      if (relatedNodeIds.has(nodeId)) return true
    }

    const taskRecord = recordValue(task)
    const taskResult = recordValue(taskRecord.result)
    const taskWorkChainId = optionalString(
      taskRecord.workChainId ??
        taskRecord.work_chain_id ??
        taskResult.workChainId ??
        taskResult.work_chain_id
    )
    const taskRouteId = optionalString(
      taskRecord.routeId ??
        taskRecord.route_id ??
        taskResult.routeId ??
        taskResult.route_id
    )
    if (taskWorkChainId && taskWorkChainId === workChain.id) return true
    if (taskRouteId && routeIds.has(taskRouteId)) return true
  }
  return false
}

export function pendingVisualHandoffCards(
  storyboardResults: StoryboardNode[],
  handoffResults: StoryboardNode[],
  cardForResult: (image?: StoryboardNode) => StoryboardNode | undefined
): StoryboardNode[] {
  const generatedCardIds = new Set(
    handoffResults
      .filter(visualHandoffResultHasGeneratedMedia)
      .map((node) => String(node.data.resultOfNodeId ?? node.data.sourceNodeId ?? ""))
  )
  const seenCardIds = new Set<string>()
  return storyboardResults
    .filter(storyboardResultImageHasGeneratedMedia)
    .map(cardForResult)
    .filter((card): card is StoryboardNode => {
      if (!card || generatedCardIds.has(card.id) || seenCardIds.has(card.id))
        return false
      seenCardIds.add(card.id)
      return true
    })
}

export function storyboardUnitResultProgress(
  cards: StoryboardNode[],
  storyboardResults: StoryboardNode[],
  handoffResults: StoryboardNode[]
) {
  const results = cards.flatMap((card) => {
    const candidates = storyboardResults.filter((node) =>
      String(node.data.resultOfNodeId ?? node.data.sourceNodeId ?? "") === card.id &&
      node.data.shotGroupId === card.data.shotGroupId
    )
    const result = candidates.find(storyboardResultImageHasGeneratedMedia) ?? candidates[0]
    return result ? [result] : []
  })
  return {
    results,
    storyboardGeneratedCount: results.filter(storyboardResultImageHasGeneratedMedia).length,
    handoffGeneratedCount: cards.filter((card) =>
      handoffResults.some((node) =>
        String(node.data.resultOfNodeId ?? node.data.sourceNodeId ?? "") === card.id &&
        visualHandoffResultHasGeneratedMedia(node)
      )
    ).length,
  }
}

export function orderedShotGroupNodes(nodes: StoryboardNode[]): StoryboardNode[] {
  return [...nodes].sort((left, right) => {
    const leftOrder = Number(left.data.shotGroupOrder)
    const rightOrder = Number(right.data.shotGroupOrder)
    const orderDifference =
      (Number.isFinite(leftOrder) && leftOrder > 0 ? leftOrder : Number.MAX_SAFE_INTEGER) -
      (Number.isFinite(rightOrder) && rightOrder > 0 ? rightOrder : Number.MAX_SAFE_INTEGER)
    if (orderDifference) return orderDifference
    return left.id.localeCompare(right.id)
  })
}

export function workflowNodeProductionStateId(
  node: StoryboardNode
): WorkChainProductionStateId | null {
  if (node.data.eyebrow === "prompt.storyboard")
    return "cinematic_script.generated"
  if (isDirectorBoardNodeType(node.data.eyebrow))
    return "director_plan.generated"
  if (isWorkflowVideoTaskType(node.data.eyebrow)) {
    return "video.generated"
  }
  return null
}

export function workflowNodeProductionRouteState(
  productionStatus: EpisodeProductionStatus | undefined | null,
  node: StoryboardNode
) {
  const routeId = optionalString(node.data.routeId)
  const workChainId = optionalString(node.data.workChainId)
  if (!routeId && !workChainId) return null
  const root = recordValue(productionStatus)
  const independent = recordValue(recordValue(root.independentWorkChains)[workChainId ?? ""])
  const routeStates = Array.isArray(independent.routeStates) ? independent.routeStates : root.routeStates
  if (!Array.isArray(routeStates)) return null
  return (
    routeStates.map(recordValue).find((routeState) => {
      if (!Object.keys(routeState).length) return false
      const stateRouteId = optionalString(routeState.routeId)
      const stateWorkChainId = optionalString(routeState.workChainId)
      return (
        Boolean(routeId && stateRouteId === routeId) ||
        Boolean(workChainId && stateWorkChainId === workChainId)
      )
    }) ?? null
  )
}

export function workflowNodeScriptContinuityReview(
  node: StoryboardNode,
  productionStatus: EpisodeProductionStatus | undefined | null
): WorkflowNodeData["scriptContinuityReview"] {
  if (node.data.eyebrow !== "prompt.storyboard") return undefined
  const routeState = workflowNodeProductionRouteState(productionStatus, node)
  const issues = routeState?.blockedBy
  if (!Array.isArray(issues)) return undefined
  const issue = issues.map(recordValue).find((row) =>
    row.category === "script_continuity" && row.nodeId === node.id
  )
  const context = recordValue(issue?.reviewContext)
  const previousScriptHash = optionalString(context.previousScriptHash)
  const scriptHash = optionalString(context.scriptHash)
  return previousScriptHash && scriptHash ? { previousScriptHash, scriptHash } : undefined
}

export function workflowNodeProductionCanvasStatus(
  node: StoryboardNode,
  productionStatus: EpisodeProductionStatus | undefined | null
): WorkflowNodeData["status"] | null {
  const stateId = workflowNodeProductionStateId(node)
  if (!stateId) return null
  const routeState = workflowNodeProductionRouteState(productionStatus, node)
  if (!routeState) return null
  if (workChainProductionStageStatus([routeState], stateId).reviewRequired) return "blocked"
  const completedStates = workChainRouteStateSet(routeState, "completedStates")
  if (completedStates.has(stateId)) {
    return "succeeded"
  }
  return null
}

export function workflowTaskCardReadinessStatus(
  node: StoryboardNode,
  nodes: StoryboardNode[],
  edges: StoryboardEdge[]
): WorkflowNodeData["status"] {
  if (!isWorkflowTaskCardType(node.data.eyebrow)) return node.data.status
  if (workflowTaskHasGeneratedResult(node, nodes, edges)) return "succeeded"
  if (node.data.eyebrow === "prompt.storyboard") {
    return storyboardSourceFactTextForNode(node.data).trim() ? "ready" : "draft"
  }
  if (isDirectorBoardNodeType(node.data.eyebrow)) {
    const scriptNode = workflowScriptCreationNodeForScope(nodes, node)
    const shootableReady =
      storyboardShootableContentReadyForNode(node.data) ||
      Boolean(
        scriptNode && storyboardShootableContentReadyForNode(scriptNode.data)
      )
    return shootableReady ? "ready" : "draft"
  }
  if (node.data.eyebrow === "storyboard.card") {
    return node.data.shotNos?.length ? "ready" : "draft"
  }
  if (isWorkflowVideoTaskType(node.data.eyebrow)) {
    if (workflowVideoTaskCanUseStandaloneInputs(node)) {
      return workflowVideoTaskCanRunStandaloneVideo(node, nodes, edges)
        ? "ready"
        : "draft"
    }
    if (!workflowVideoTaskCardIsReady(node)) return "draft"
    return "ready"
  }
  return "draft"
}

export function buildWorkChainProgressSteps(
  workChain: WorkflowWorkChain,
  routes: WorkflowRoute[],
  nodes: StoryboardNode[],
  productionStatus: EpisodeProductionStatus | undefined | null,
  activeTaskByNodeId: Map<string, TaskRow> = new Map()
): WorkChainProgressStep[] {
  const routeIds = workChainProductionRouteIds(workChain, routes)
  const chainNodes = nodes.filter((node) => {
    const routeId = String(node.data.routeId ?? "")
    return (
      node.data.workChainId === workChain.id ||
      (routeId && routeIds.has(routeId))
    )
  })
  const storyboardTask = chainNodes.find(
    (node) => node.data.eyebrow === "prompt.storyboard"
  )
  const directorTask = chainNodes.find((node) =>
    isDirectorBoardNodeType(node.data.eyebrow)
  )
  const isCanonicalResultNode = (
    node: StoryboardNode,
    sourceTypeMatches: (value: string) => boolean
  ) => {
    if (node.data.sourceType === "version" || node.data.copiedFromNodeId)
      return false
    const sourceNodeId = String(
      node.data.resultOfNodeId ?? node.data.sourceNodeId ?? ""
    ).trim()
    if (!sourceNodeId) return true
    const sourceNode = chainNodes.find((item) => item.id === sourceNodeId)
    return Boolean(sourceNode && sourceTypeMatches(sourceNode.data.eyebrow))
  }
  const storyboardResultCandidates = chainNodes.filter(
    (node) =>
      isStoryboardResultImageNode(node) &&
      isCanonicalResultNode(node, (type) => type === "storyboard.card")
  )
  const storyboardResult =
    storyboardResultCandidates.find(storyboardResultImageHasGeneratedMedia) ??
    storyboardResultCandidates[0]
  const assignedStoryboardCards = orderedShotGroupNodes(chainNodes.filter((node) =>
    node.data.eyebrow === "storyboard.card" && Boolean(node.data.shotGroupId)
  ))
  const storyboardCardForResult = (image?: StoryboardNode) => image
    ? chainNodes.find((node) =>
        node.data.eyebrow === "storyboard.card" &&
        node.id === String(image.data.resultOfNodeId ?? image.data.sourceNodeId ?? "")
      )
    : undefined
  const visualHandoffResults = nodes.filter((node) =>
    workflowNodeIsVisualHandoffAsset(node) &&
    node.data.sourceType !== "version" &&
    !node.data.copiedFromNodeId &&
    chainNodes.some((source) =>
      source.data.eyebrow === "storyboard.card" &&
      source.id === String(node.data.resultOfNodeId ?? node.data.sourceNodeId ?? "")
    )
  )
  const visualHandoffResult = visualHandoffResults.find(visualHandoffResultHasGeneratedMedia) ?? visualHandoffResults[0]
  const unitProgress = storyboardUnitResultProgress(
    assignedStoryboardCards,
    storyboardResultCandidates,
    visualHandoffResults
  )
  const assignedStoryboardResults = unitProgress.results
  const nextStoryboardResult =
    assignedStoryboardResults.find((node) => !storyboardResultImageHasGeneratedMedia(node)) ??
    assignedStoryboardResults[0]
  const handoffCardsToGenerate = pendingVisualHandoffCards(
    assignedStoryboardResults,
    visualHandoffResults,
    storyboardCardForResult
  )
  const videoTasks = chainNodes.filter((node) =>
    isWorkflowVideoTaskType(node.data.eyebrow)
  )
  const videoTask = videoTasks[0]
  const assignedVideoTasks = orderedShotGroupNodes(
    videoTasks.filter((node) => Boolean(node.data.shotGroupId))
  )
  const videoResultCandidates = chainNodes.filter(
    (node) =>
      node.data.eyebrow === "video.result" &&
      isCanonicalResultNode(node, isWorkflowVideoTaskType)
  )
  const videoResult =
    videoResultCandidates.find(isEditableVideoResultNode) ??
    videoResultCandidates[0]
  const branchCounts: Partial<Record<WorkChainProductionStateId, number>> = {
    "storyboard.generated": assignedStoryboardCards.length,
    "visual_handoff.generated": assignedStoryboardCards.length,
    "video_prompt.ready": assignedVideoTasks.length,
    "video.generated": assignedVideoTasks.length,
  }
  const branchCompletedCounts: Partial<Record<WorkChainProductionStateId, number>> = {
    "storyboard.generated": unitProgress.storyboardGeneratedCount,
    "visual_handoff.generated": unitProgress.handoffGeneratedCount,
    "video_prompt.ready": assignedVideoTasks.filter((node) => promptTextForNode(node.data).trim()).length,
    "video.generated": assignedVideoTasks.filter((task) =>
      videoResultCandidates.some((result) =>
        String(result.data.resultOfNodeId ?? result.data.sourceNodeId ?? "") === task.id &&
        isEditableVideoResultNode(result)
      )
    ).length,
  }
  const routeStates = workChainProductionRouteStates(
    productionStatus?.independentWorkChains?.[workChain.id] ?? productionStatus,
    workChain,
    routes
  )
  const stageStatuses = new Map(
    WORK_CHAIN_PRODUCTION_STAGES.map((stage) => [
      stage.id,
      workChainProductionStageStatus(routeStates, stage.id),
    ])
  )
  const videoStepNodeId = stageStatuses.get("video.generated")?.completed
    ? (videoResult?.id ?? videoTask?.id)
    : (videoTask?.id ?? videoResult?.id)
  const stepNodeIds: Partial<
    Record<WorkChainProductionStateId, string | undefined>
  > = {
    "cinematic_script.generated": storyboardTask?.id,
    "director_plan.generated": directorTask?.id,
    "storyboard.generated": storyboardResult?.id ?? directorTask?.id,
    "video_prompt.ready": videoTask?.id,
    "visual_handoff.generated": visualHandoffResult?.id ?? assignedStoryboardCards[0]?.id,
    "video.generated": videoStepNodeId,
  }
  const singleActionTargetNodeIds: Partial<
    Record<WorkChainProductionStateId, string | undefined>
  > = {
    "cinematic_script.generated": storyboardTask?.id,
    "director_plan.generated": directorTask?.id,
    "storyboard.generated": nextStoryboardResult?.id,
    "video_prompt.ready": assignedVideoTasks[0]?.id,
    "visual_handoff.generated": handoffCardsToGenerate[0]?.id,
    "video.generated": assignedVideoTasks[0]?.id,
  }
  const branchActionTargetIds: Partial<Record<WorkChainProductionStateId, string[]>> = {
    "storyboard.generated": assignedStoryboardResults.map((node) => node.id),
    "visual_handoff.generated": handoffCardsToGenerate.map((node) => node.id),
    "video_prompt.ready": assignedVideoTasks.map((node) => node.id),
    "video.generated": assignedVideoTasks.map((node) => node.id),
  }
  const missingActionText: Record<WorkChainProductionStateId, string> = {
    "cinematic_script.generated": "当前工作链缺少片段剧本",
    "director_plan.generated": "当前工作链缺少分镜脚本",
    "storyboard.generated": "请先在分镜脚本保存镜头分组",
    "video_prompt.ready": "当前工作链缺少视频生成",
    "visual_handoff.generated": assignedStoryboardCards.length > 0 &&
      branchCompletedCounts["visual_handoff.generated"] === assignedStoryboardCards.length
      ? "视觉交接图均已生成"
      : "请先生成待处理单元的分镜图",
    "video.generated": "当前工作链缺少视频生成",
  }

  return WORK_CHAIN_PRODUCTION_STAGES.map((stage) => {
    const stageStatus = stageStatuses.get(stage.id)
    const nodeId = stepNodeIds[stage.id]
    const actionTargetNodeId = singleActionTargetNodeIds[stage.id]
    const actionTargetNodeIds = branchActionTargetIds[stage.id]
    const count = branchCounts[stage.id]
    const completedCount = branchCompletedCounts[stage.id] ?? 0
    const optional = "optional" in stage && stage.optional === true
    const running = workChainProgressStepHasRunningTask(
      stage.id,
      workChain,
      routeIds,
      [nodeId, actionTargetNodeId, ...(actionTargetNodeIds ?? [])],
      activeTaskByNodeId
    )
    const makeStep = (
      state: WorkChainProgressState,
      statusText: string,
      progress?: {
        included?: boolean
        completed?: boolean
      }
    ): WorkChainProgressStep => ({
      stageId: stage.id,
      label: stage.label,
      state,
      statusText,
      nodeId,
      actionLabel: stage.actionLabel,
      actionTargetNodeId,
      actionTargetNodeIds,
      count,
      actionDisabledText: actionTargetNodeId
        ? undefined
        : missingActionText[stage.id],
      optional,
      progressIncluded: progress?.included ?? !optional,
      progressCompleted:
        progress?.completed ?? (!optional && state === "completed"),
    })
    if (count !== undefined) {
      const statusText = count ? `${completedCount}/${count} 已完成` : "暂无分支"
      if (running) return makeStep("running", statusText)
      if (count > 0 && completedCount === count) return makeStep("completed", statusText)
      return makeStep("pending", statusText)
    }
    if (running) {
      return makeStep("running", optional ? "运行中 · 可选" : "运行中", {
        included: !optional,
        completed: !optional && Boolean(stageStatus?.completed),
      })
    }
    if (stageStatus?.reviewRequired) return makeStep("pending", "待复核")
    if (stageStatus?.completed) {
      return makeStep("completed", "已完成", {
        included: !optional,
        completed: !optional,
      })
    }
    return makeStep("pending", optional ? "待生成 · 可选" : "待生成", {
      included: !optional,
      completed: false,
    })
  })
}

export function workflowResultTaskAppliesToSourceTask(
  sourceNode: StoryboardNode,
  resultNode: StoryboardNode,
  task: TaskRow
) {
  const sourceType = sourceNode.data.eyebrow
  const resultType = resultNode.data.eyebrow
  const taskType = workflowStatusTaskType(task)
  if (
    sourceType === "storyboard.card" &&
    isWorkflowResultImageType(resultType)
  ) {
    return (
      taskType === "storyboard_image" ||
      taskType === "storyboard_image_generation"
    )
  }
  if (isWorkflowVideoTaskType(sourceType) && resultType === "video.result") {
    return (
      taskType === "storyboard_video" ||
      taskType === "route_video" ||
      taskType === "storyboard_video_generation"
    )
  }
  return false
}

export type WorkflowTaskResultRelationIndex = {
  nodeById: Map<string, StoryboardNode>
  resultNodeIdsBySourceId: Map<string, Set<string>>
}

export function buildWorkflowTaskResultRelationIndex(
  nodes: StoryboardNode[],
  edges: StoryboardEdge[]
): WorkflowTaskResultRelationIndex {
  const nodeById = new Map(nodes.map((item) => [item.id, item] as const))
  const resultNodeIdsBySourceId = new Map<string, Set<string>>()
  const addResultNode = (
    sourceNodeId?: string | null,
    resultNodeId?: string | null
  ) => {
    const sourceId = String(sourceNodeId ?? "").trim()
    const resultId = String(resultNodeId ?? "").trim()
    if (!sourceId || !resultId) return
    const existing = resultNodeIdsBySourceId.get(sourceId)
    if (existing) {
      existing.add(resultId)
      return
    }
    resultNodeIdsBySourceId.set(sourceId, new Set([resultId]))
  }

  edges.forEach((edge) => {
    const sourceType =
      edge.data?.sourceNodeType ?? nodeById.get(edge.source)?.data.eyebrow
    const targetType =
      edge.data?.targetNodeType ?? nodeById.get(edge.target)?.data.eyebrow
    const taskResultEdge = workflowTaskResultEdgeByTypes(
      edge,
      sourceType,
      targetType
    )
    if (
      taskResultEdge &&
      !(
        sourceType === "storyboard.card" &&
        targetType === "storyboard.image" &&
        !isDefaultWorkChainStoryboardResultNode(nodeById.get(edge.target))
      )
    ) {
      addResultNode(edge.source, edge.target)
    }
  })
  nodes.forEach((node) => {
    if (!isWorkflowResultNodeType(node.data.eyebrow)) return
    addResultNode(node.data.resultOfNodeId, node.id)
    addResultNode(node.data.sourceNodeId, node.id)
  })

  return { nodeById, resultNodeIdsBySourceId }
}

export function activeWorkflowTaskForCanvasNode(
  node: StoryboardNode,
  relationIndex: WorkflowTaskResultRelationIndex,
  activeTaskByNodeId: Map<string, TaskRow>
) {
  const directTask = activeTaskByNodeId.get(node.id)
  if (directTask) return directTask
  if (!isWorkflowTaskNodeType(node.data.eyebrow)) return null

  const resultNodeIds = relationIndex.resultNodeIdsBySourceId.get(node.id)
  if (!resultNodeIds?.size) return null

  const inheritedTasks: TaskRow[] = []
  resultNodeIds.forEach((resultNodeId) => {
    const resultNode = relationIndex.nodeById.get(resultNodeId)
    const task = activeTaskByNodeId.get(resultNodeId)
    if (
      resultNode &&
      task &&
      workflowResultTaskAppliesToSourceTask(node, resultNode, task)
    ) {
      inheritedTasks.push(task)
    }
  })
  inheritedTasks.sort(
    (left, right) =>
      workflowTaskPriority(right) - workflowTaskPriority(left) ||
      workflowTaskTimestampValue(right) - workflowTaskTimestampValue(left)
  )
  return inheritedTasks[0] ?? null
}

export function visualHandoffResultHasGeneratedMedia(
  node?: StoryboardNode | null
) {
  return Boolean(
    node &&
    workflowNodeIsVisualHandoffAsset(node) &&
    workflowNodeDataHasConcreteMediaReference(node.data)
  )
}

export function workflowNodeStageHasCompletedResult(
  node: StoryboardNode,
  nodes: StoryboardNode[],
  edges: StoryboardEdge[]
) {
  if (workflowTaskHasGeneratedResult(node, nodes, edges)) return true
  if (isStoryboardResultImageNode(node))
    return storyboardResultImageHasGeneratedMedia(node)
  if (node.data.eyebrow === "video.result")
    return isEditableVideoResultNode(node)
  return false
}

export function workflowNodeCanvasDisplayStatus(
  node: StoryboardNode,
  nodes: StoryboardNode[],
  edges: StoryboardEdge[],
  productionStatus: EpisodeProductionStatus | undefined | null
): WorkflowNodeData["status"] {
  const productionDisplayStatus = workflowNodeProductionCanvasStatus(
    node,
    productionStatus
  )
  if (productionDisplayStatus) return productionDisplayStatus
  if (isWorkflowTaskCardType(node.data.eyebrow)) {
    return workflowTaskCardReadinessStatus(node, nodes, edges)
  }
  if (workflowNodeStageHasCompletedResult(node, nodes, edges))
    return "succeeded"
  return node.data.status
}

export function fallbackWorkflowNodeStatusAfterMissingTask(
  node: StoryboardNode,
  nodes: StoryboardNode[],
  edges: StoryboardEdge[]
): WorkflowNodeData["status"] {
  if (workflowTaskHasGeneratedResult(node, nodes, edges)) return "succeeded"
  if (
    workflowNodeMediaType(node) &&
    workflowNodeDataHasConcreteMediaReference(node.data)
  ) {
    return "ready"
  }
  if (workflowVideoTaskCardIsReady(node)) return "ready"
  return "draft"
}

export function workflowVideoTaskPromptIsSyncing(
  videoTaskNode: StoryboardNode,
  activeTaskByNodeId: Map<string, TaskRow>
) {
  return (
    isDefaultWorkChainVideoTaskNode(videoTaskNode) &&
    workflowStatusTaskType(activeTaskByNodeId.get(videoTaskNode.id)) ===
      "video_prompt"
  )
}

export function workflowNodeStatusFromTask(
  task: TaskRow
): WorkflowNodeData["status"] {
  const status = String(task.status ?? "").trim()
  if (status === "created") return "queued"
  if (status === "completed") return "succeeded"
  const mapped = workflowNodeStatus(status)
  return mapped === "draft" && isWorkflowTaskBlockingRun(task)
    ? "running"
    : mapped
}
