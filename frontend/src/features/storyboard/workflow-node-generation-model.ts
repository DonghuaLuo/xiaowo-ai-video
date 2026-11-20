import { workflowTaskResultNode } from "./workflow-document-model"
import { isEditableVideoResultNode } from "./workflow-canvas-asset-model"
import {
  directorPlanTextForNode,
  isDirectorBoardNodeType,
  isWorkflowVideoTaskType,
  workflowVideoTaskScope,
  type StoryboardEdge,
  type StoryboardNode,
} from "./workflow-canvas-model"
import { workflowVideoTaskCardHasStandaloneVideoInputs } from "./workflow-input-readiness"
import { isRunnableWorkflowNode } from "./workflow-node-relations"
import { storyboardCinematicScriptReadyForNode } from "./workflow-prompt-node-model"

export function workflowTaskHasGeneratedResult(
  taskNode: StoryboardNode,
  nodes: StoryboardNode[],
  edges: StoryboardEdge[]
) {
  const resultNode = workflowTaskResultNode(taskNode, nodes, edges)
  if (taskNode.data.eyebrow === "prompt.storyboard") {
    return storyboardCinematicScriptReadyForNode(taskNode.data)
  }
  if (isDirectorBoardNodeType(taskNode.data.eyebrow)) {
    return Boolean(directorPlanTextForNode(taskNode.data).trim())
  }
  if (taskNode.data.eyebrow === "storyboard.card") {
    return Boolean(resultNode?.data.activeVersionId || resultNode?.data.activeMediaVersionId || resultNode?.data.mediaVersionId)
  }
  if (isWorkflowVideoTaskType(taskNode.data.eyebrow)) {
    return isEditableVideoResultNode(resultNode)
  }
  return false
}

export function workflowVideoTaskCanRunStandaloneVideo(
  videoTaskNode: StoryboardNode,
  nodes: StoryboardNode[],
  _edges: StoryboardEdge[]
) {
  const standaloneVideoTask =
    workflowVideoTaskCanUseStandaloneInputs(videoTaskNode)
  return Boolean(
    standaloneVideoTask &&
    workflowVideoTaskCardHasStandaloneVideoInputs(
      videoTaskNode,
      standaloneVideoTask,
      nodes
    )
  )
}

export function workflowVideoTaskCanUseStandaloneInputs(
  videoTaskNode: StoryboardNode
) {
  return Boolean(
    isWorkflowVideoTaskType(videoTaskNode.data.eyebrow) &&
    workflowVideoTaskScope(videoTaskNode) === "standalone"
  )
}

export function orderedRunnableNodes(
  nodes: StoryboardNode[],
  edges: StoryboardEdge[],
  routeId?: string
) {
  const candidates = nodes.filter(
    (node) =>
      (!routeId || node.data.routeId === routeId) &&
      isRunnableWorkflowNode(node)
  )
  const candidateIds = new Set(candidates.map((node) => node.id))
  const indegree = new Map(candidates.map((node) => [node.id, 0]))
  const dependents = new Map<string, string[]>()

  edges.forEach((edge) => {
    if (!candidateIds.has(edge.source) || !candidateIds.has(edge.target)) return
    const edgeKind = String(edge.data?.kind ?? "")
    if (
      edgeKind !== "dependency" &&
      edgeKind !== "material" &&
      edgeKind !== "context"
    )
      return
    dependents.set(edge.source, [
      ...(dependents.get(edge.source) ?? []),
      edge.target,
    ])
    indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1)
  })

  const ready = candidates.filter((node) => (indegree.get(node.id) ?? 0) === 0)
  const ordered: StoryboardNode[] = []
  const orderedIds = new Set<string>()
  while (ready.length) {
    const node = ready.shift()
    if (!node || orderedIds.has(node.id)) continue
    ordered.push(node)
    orderedIds.add(node.id)
    ;(dependents.get(node.id) ?? []).forEach((targetId) => {
      const nextDegree = Math.max(0, (indegree.get(targetId) ?? 0) - 1)
      indegree.set(targetId, nextDegree)
      if (nextDegree === 0) {
        const targetNode = candidates.find((item) => item.id === targetId)
        if (targetNode) ready.push(targetNode)
      }
    })
  }
  return ordered.length === candidates.length
    ? ordered
    : [...ordered, ...candidates.filter((node) => !orderedIds.has(node.id))]
}

export function routeRunnableNodes(
  routeId: string,
  nodes: StoryboardNode[],
  edges: StoryboardEdge[]
) {
  return orderedRunnableNodes(nodes, edges, routeId)
}
