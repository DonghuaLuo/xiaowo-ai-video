import { workflowSourceStoryboardEdgeByTypes, workflowSourceVideoTextEdgeByTypes } from "./workflow-canvas-model"
import { WORKFLOW_VIDEO_TASK_TYPES } from "./workflow-video-task-types"
import {
  isDefaultWorkChainVideoTaskNode,
  isStoryboardResultImageNode,
  isWorkflowAssetNodeType,
  isWorkflowResultNodeType,
  isWorkflowTaskNodeType,
  workflowMediaKind,
  workflowNodeDataHasConcreteMediaReference,
  workflowNodeDataHasCurrentMediaReference,
  workflowNodeIsVisualHandoffAsset,
} from "./workflow-canvas-asset-model"
import {
  canonicalTargetSlot,
  canvasMediaReference,
  isDirectorBoardNodeType,
  isStoryboardCardNodeType,
  isWorkflowItemLocked,
  isWorkflowVideoTaskType,
  optionalString,
  recordValue,
  type StoryboardEdge,
  type StoryboardNode,
  workflowNodeDataIsWorkChainStoryboardResult,
  type WorkflowNodeLike,
  workflowNodeLikeData,
  workflowNodeTypeValue,
  workflowNodeWorkChainId,
  workflowVideoTaskScope,
} from "./workflow-canvas-model"

export function isContextRunnableWorkflowNode(node: StoryboardNode) {
  return isRunnableWorkflowNode(node)
}

export function isRunnableWorkflowNode(node: StoryboardNode) {
  return RUNNABLE_WORKFLOW_NODE_TYPES.has(node.data.eyebrow)
}

export const RUNNABLE_WORKFLOW_NODE_TYPES = new Set([
  "prompt.storyboard",
  "director.board",
  ...WORKFLOW_VIDEO_TASK_TYPES,
])

export function isWorkflowContextDeleteVisible(node: StoryboardNode) {
  const nodeType = node.data.eyebrow
  if (nodeType === "source.text") return node.data.sourceMode === "independent"
  if (isStandaloneWorkflowTaskNode(node)) return true
  if (isWorkflowTaskNodeType(nodeType)) return false
  if (nodeType === "asset.image" || nodeType === "media.external") return true
  return isWorkflowResultNodeType(nodeType) && isCopiedWorkflowAssetNode(node)
}

export function isStandaloneWorkflowTaskNode(node?: WorkflowNodeLike | null) {
  return Boolean(node && workflowVideoTaskScope(node) === "standalone")
}

export function isCopiedWorkflowAssetNode(node?: StoryboardNode | null) {
  if (!node) return false
  const provenance = recordValue(node.data.provenance)
  return Boolean(
    node.data.copiedFromNodeId ||
    provenance.copiedFromNodeId ||
    provenance.action === "canvas_asset_node_pasted"
  )
}

export function isWorkflowContextCopyVisible(node: StoryboardNode) {
  return isWorkflowAssetNodeType(node.data.eyebrow)
}

export function isWorkflowContextDeleteLocked(node?: StoryboardNode | null) {
  if (!node) return false
  if (workflowNodeIsVisualHandoffAsset(node)) return false
  return isWorkflowItemLocked(node.data)
}

export function isWorkflowEditHistoryVisible(node: StoryboardNode) {
  const nodeType = node.data.eyebrow
  return (
    nodeType === "source.text" ||
    nodeType === "prompt.storyboard" ||
    isWorkflowVideoTaskType(nodeType) ||
    isDirectorBoardNodeType(nodeType)
  )
}

export function isWorkflowVideoClipSourceNode(node?: StoryboardNode | null) {
  if (!node || workflowNodeMediaType(node) !== "video") return false
  if (isWorkflowVideoTaskType(node.data.eyebrow)) return false
  return workflowNodeDataHasCurrentMediaReference(node.data)
}

export function workflowNodeMediaType(
  node: StoryboardNode
): "image" | "video" | null {
  if (isDirectorBoardNodeType(node.data.eyebrow)) {
    return "image"
  }
  if (node.data.eyebrow === "storyboard.image") {
    return "image"
  }
  if (
    node.data.eyebrow === "video.result" ||
    isWorkflowVideoTaskType(node.data.eyebrow)
  ) {
    return "video"
  }
  if (node.data.eyebrow === "media.external") {
    const media = canvasMediaReference(
      node.data.media ?? node.data.storage ?? null
    )
    return workflowMediaKind(node.data, media) === "video" ? "video" : "image"
  }
  if (workflowNodeIsVisualHandoffAsset(node)) {
    return "image"
  }
  return null
}

export function storyboardResultImageHasGeneratedMedia(
  node?: StoryboardNode | null
) {
  if (!node || !isStoryboardResultImageNode(node)) return false
  return workflowNodeDataHasConcreteMediaReference(node.data)
}

export function workflowStoryboardResultsForCardNode(
  nodes: StoryboardNode[],
  cardNode: StoryboardNode
) {
  const groupId = String(cardNode.data.shotGroupId ?? "").trim()
  if (cardNode.data.eyebrow !== "storyboard.card" || !groupId) return []
  return nodes.filter((node) =>
    isStoryboardResultImageNode(node) &&
    String(node.data.resultOfNodeId ?? node.data.sourceNodeId ?? "") === cardNode.id &&
    String(node.data.shotGroupId ?? "").trim() === groupId
  )
}

export function workflowStoryboardResultForScopeNode(
  nodes: StoryboardNode[],
  baseNode: StoryboardNode
) {
  const routeId = String(baseNode.data.routeId ?? "").trim()
  const workChainId = String(baseNode.data.workChainId ?? "").trim()
  const candidates = nodes.filter((node) => {
    if (!isStoryboardResultImageNode(node)) return false
    if (routeId && String(node.data.routeId ?? "").trim() === routeId)
      return true
    return Boolean(
      workChainId && String(node.data.workChainId ?? "").trim() === workChainId
    )
  })
  return (
    candidates.find(storyboardResultImageHasGeneratedMedia) ?? candidates[0]
  )
}

export function isDefaultWorkChainStoryboardResultNode(
  node?: WorkflowNodeLike | null
) {
  const data = workflowNodeLikeData(node)
  return Boolean(
    node &&
    workflowNodeDataIsWorkChainStoryboardResult({
      ...data,
      eyebrow: workflowNodeTypeValue(node),
    }) &&
    workflowNodeWorkChainId(node)
  )
}

export function workflowNodesShareWorkChainRoute(
  sourceNode?: StoryboardNode | null,
  targetNode?: StoryboardNode | null
) {
  const sourceWorkChainId = workflowNodeWorkChainId(sourceNode)
  const targetWorkChainId = workflowNodeWorkChainId(targetNode)
  if (!sourceWorkChainId || sourceWorkChainId !== targetWorkChainId) {
    return false
  }
  const sourceRouteId = workflowNodeRouteId(sourceNode)
  const targetRouteId = workflowNodeRouteId(targetNode)
  return !sourceRouteId || !targetRouteId || sourceRouteId === targetRouteId
}

export function workflowNodeRouteId(node?: WorkflowNodeLike | null) {
  const data = workflowNodeLikeData(node)
  return optionalString(data.routeId) || optionalString(node?.routeId)
}

export function workflowEdgeTypes(
  edge?: StoryboardEdge | null,
  nodes: StoryboardNode[] = []
) {
  if (!edge) return { sourceType: "", targetType: "" }
  const sourceType =
    edge.data?.sourceNodeType ??
    nodes.find((node) => node.id === edge.source)?.data.eyebrow
  const targetType =
    edge.data?.targetNodeType ??
    nodes.find((node) => node.id === edge.target)?.data.eyebrow
  return { sourceType, targetType }
}

export function isWorkflowLockedSystemEdge(
  edge?: StoryboardEdge | null,
  nodes: StoryboardNode[] = []
) {
  if (!edge) return false
  const { sourceType, targetType } = workflowEdgeTypes(edge, nodes)
  const edgeData = (edge.data ?? {}) as Record<string, unknown>
  const role = optionalString(edgeData.role)
  const edgeKind = optionalString(edgeData.kind)
  const targetSlot = canonicalTargetSlot(
    String(edge.targetHandle ?? edgeData.targetSlot ?? edgeData.slot ?? "")
  )
  const sourceNode = nodes.find((node) => node.id === edge.source)
  const targetNode = nodes.find((node) => node.id === edge.target)
  const targetMediaPurpose = optionalString(
    targetNode?.data.mediaPurpose ??
      targetNode?.data.preferredTargetSlot ??
      targetNode?.data.assetKind
  )
  const storyboardDirectorEdge =
    sourceType === "prompt.storyboard" &&
    targetType === "director.board" &&
    (!role ||
      role === "context" ||
      role === "generates" ||
      !targetSlot ||
      targetSlot === "story")
  const directorStoryboardCardEdge =
    sourceType === "director.board" &&
    targetType === "storyboard.card" &&
    workflowNodesShareWorkChainRoute(sourceNode, targetNode)
  const visualHandoffEdge =
    sourceType === "director.board" &&
    targetType === "asset.image" &&
    targetMediaPurpose === "visual_handoff" &&
    (!role ||
      role === "generates" ||
      role === "dependency" ||
      !targetSlot ||
      targetSlot === "asset_context" ||
      targetSlot === "visual_handoff_reference")
  const storyboardVideoEdge =
    sourceType === "storyboard.image" &&
    isWorkflowVideoTaskType(targetType) &&
    targetSlot === "storyboard_image" &&
    (!edgeKind || edgeKind === "material") &&
    isDefaultWorkChainStoryboardResultNode(sourceNode) &&
    isDefaultWorkChainVideoTaskNode(targetNode) &&
    workflowNodesShareWorkChainRoute(sourceNode, targetNode)
  const directorStoryboardResultEdge =
    sourceType === "storyboard.card" &&
    targetType === "storyboard.image" &&
    isDefaultWorkChainStoryboardResultNode(targetNode) &&
    workflowNodesShareWorkChainRoute(sourceNode, targetNode) &&
    (role === "generates" || !targetSlot || targetSlot === "generates" || !role)
  const videoResultEdge =
    isWorkflowVideoTaskType(sourceType) &&
    targetType === "video.result" &&
    (role === "generates" ||
      !targetSlot ||
      targetSlot === "generates" ||
      targetSlot === "video_result" ||
      !role)
  return (
    workflowSourceStoryboardEdgeByTypes(edge, sourceType, targetType) ||
    workflowSourceVideoTextEdgeByTypes(edge, sourceType, targetType) ||
    storyboardDirectorEdge ||
    directorStoryboardCardEdge ||
    visualHandoffEdge ||
    storyboardVideoEdge ||
    directorStoryboardResultEdge ||
    videoResultEdge
  )
}

export function isWorkflowVisualHandoffOutputEdge(
  edge?: StoryboardEdge | null,
  nodes: StoryboardNode[] = []
) {
  if (!edge) return false
  const { sourceType, targetType } = workflowEdgeTypes(edge, nodes)
  const edgeData = (edge.data ?? {}) as Record<string, unknown>
  const role = optionalString(edgeData.role)
  const targetSlot = canonicalTargetSlot(
    String(edgeData.targetSlot ?? edgeData.slot ?? edgeData.role ?? "")
  )
  const targetNode = nodes.find((node) => node.id === edge.target)
  return Boolean(
    isStoryboardCardNodeType(sourceType) &&
    targetType === "asset.image" &&
    workflowNodeIsVisualHandoffAsset(targetNode) &&
    (!role ||
      role === "generates" ||
      role === "dependency" ||
      !targetSlot ||
      targetSlot === "asset_context" ||
      targetSlot === "visual_handoff_reference")
  )
}
