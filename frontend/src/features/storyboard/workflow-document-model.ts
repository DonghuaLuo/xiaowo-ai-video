import {
  isEditableVideoResultNode,
  isWorkflowGeneratedMediaResultNode,
  isWorkflowResultNodeType,
  workflowNodeVersionStorageNodeId,
} from "./workflow-canvas-asset-model"
import {
  compactReadableValue,
  recordValue,
  workflowTaskResultEdgeByTypes,
  type StoryboardEdge,
  type StoryboardNode,
  type WorkflowNodeData,
} from "./workflow-canvas-model"
import {
  canvasMutationEnvelopeSources,
  canvasPlainObject,
  canvasProjectionRows,
  canvasProjectionText,
} from "./workflow-canvas-mutation-model"
import {
  isDefaultWorkChainStoryboardResultNode,
  storyboardResultImageHasGeneratedMedia,
  workflowEdgeTypes,
} from "./workflow-node-relations"
import {
  type CanvasVersionRef,
  type EpisodeProductionStatus,
  type EpisodeWorkflow,
  type WorkflowWorkChain,
} from "@/backend"

export function workflowVideoPromptSyncWarningText(value: unknown) {
  if (!value) return ""
  const direct = compactReadableValue(value)
  if (direct) return direct
  const record = recordValue(value)
  const nodeId = compactReadableValue(record.nodeId ?? record.node_id)
  const error = compactReadableValue(record.error ?? record.message)
  if (nodeId && error) return `${nodeId}: ${error}`
  return error || nodeId
}

export function workflowVideoDurationSyncWarningMessage(result: {
  videoDurationSyncWarning?: unknown
  videoDurationSyncWarnings?: unknown
}) {
  const warnings = Array.isArray(result.videoDurationSyncWarnings)
    ? result.videoDurationSyncWarnings
        .map(workflowVideoPromptSyncWarningText)
        .filter(Boolean)
    : []
  const single = workflowVideoPromptSyncWarningText(
    result.videoDurationSyncWarning
  )
  if (single) warnings.push(single)
  return Array.from(new Set(warnings)).join("；")
}

export function isWorkflowTaskResultEdge(
  edge?: StoryboardEdge | null,
  nodes: StoryboardNode[] = []
) {
  if (!edge) return false
  const { sourceType, targetType } = workflowEdgeTypes(edge, nodes)
  const taskResultEdge = workflowTaskResultEdgeByTypes(
    edge,
    sourceType,
    targetType
  )
  if (!taskResultEdge) return false
  if (
    sourceType === "storyboard.card" &&
    targetType === "storyboard.image"
  ) {
    return isDefaultWorkChainStoryboardResultNode(
      nodes.find((node) => node.id === edge.target)
    )
  }
  return true
}

export function workflowTaskResultNode(
  taskNode: StoryboardNode,
  nodes: StoryboardNode[],
  edges: StoryboardEdge[]
) {
  const taskNodeId = String(taskNode.id ?? "").trim()
  const edge = edges.find(
    (item) =>
      item.source === taskNode.id && isWorkflowTaskResultEdge(item, nodes)
  )
  if (edge) return nodes.find((item) => item.id === edge.target)
  if (!taskNodeId) return undefined
  const resultNodes = nodes.filter((node) => {
    if (!isWorkflowResultNodeType(node.data.eyebrow)) return false
    const sourceNodeId = String(
      node.data.resultOfNodeId ?? node.data.sourceNodeId ?? ""
    ).trim()
    return sourceNodeId === taskNodeId
  })
  return (
    resultNodes.find(
      (node) =>
        isEditableVideoResultNode(node) ||
        storyboardResultImageHasGeneratedMedia(node)
    ) ?? resultNodes[0]
  )
}

export function workflowVersionResultNodeIds(
  nodeId: string,
  nodes: StoryboardNode[],
  edges: StoryboardEdge[]
) {
  const targetIds = new Set<string>()
  const addGeneratedNode = (targetNodeId?: string | null) => {
    const id = targetNodeId?.trim()
    if (!id) return
    const node = nodes.find((item) => item.id === id)
    if (isWorkflowGeneratedMediaResultNode(node)) {
      targetIds.add(id)
    }
  }
  const anchor = nodes.find((node) => node.id === nodeId)
  if (anchor && isWorkflowGeneratedMediaResultNode(anchor)) {
    addGeneratedNode(anchor.id)
    return targetIds
  }
  if (anchor) addGeneratedNode(workflowTaskResultNode(anchor, nodes, edges)?.id)
  if (targetIds.size > 0) return targetIds
  nodes.forEach((node) => {
    if (!isWorkflowGeneratedMediaResultNode(node)) return
    if (
      node.data.resultOfNodeId === nodeId ||
      node.data.sourceNodeId === nodeId
    ) {
      targetIds.add(node.id)
    }
  })
  return targetIds
}

export function workflowExtras(
  workflow: EpisodeWorkflow
): Partial<EpisodeWorkflow> {
  return {
    schemaVersion: workflow.schemaVersion,
    workChains: workflow.workChains,
    productionStatus: workflow.productionStatus,
    build: workflow.build,
    state: workflow.state,
  }
}

export function workflowDocumentExtrasPatch(
  value: unknown
): Partial<EpisodeWorkflow> | null {
  const row = canvasPlainObject(value)
  if (!row) return null
  const patch: Partial<EpisodeWorkflow> = {}
  let changed = false
  const workChains = Array.isArray(row.workChains) ? row.workChains : null
  if (workChains) {
    patch.workChains = [...workChains] as WorkflowWorkChain[]
    changed = true
  }
  const productionStatus = row.productionStatus
  if (
    productionStatus &&
    typeof productionStatus === "object" &&
    !Array.isArray(productionStatus)
  ) {
    patch.productionStatus = {
      ...(productionStatus as Record<string, unknown>),
    } as EpisodeProductionStatus
    changed = true
  }
  if (row.build && typeof row.build === "object" && !Array.isArray(row.build)) {
    patch.build = { ...(row.build as Record<string, unknown>) }
    changed = true
  }
  if (row.state && typeof row.state === "object" && !Array.isArray(row.state)) {
    patch.state = { ...(row.state as NonNullable<EpisodeWorkflow["state"]>) }
    changed = true
  }
  return changed ? patch : null
}

export function canvasUnknownEqual(left: unknown, right: unknown) {
  if (Object.is(left, right)) return true
  try {
    return JSON.stringify(left) === JSON.stringify(right)
  } catch {
    return false
  }
}

export function canvasMutationText(value: unknown) {
  return String(value ?? "").trim()
}

export function canvasMutationOpType(payload: unknown) {
  for (const source of canvasMutationEnvelopeSources(payload)) {
    const opType = canvasMutationText(source.opType ?? source.op_type)
    if (opType) return opType
  }
  return ""
}

export function canvasMutationRevision(payload: unknown) {
  for (const source of canvasMutationEnvelopeSources(payload)) {
    const workflowVersion =
      source.workflowVersion ?? source.workflow_version ?? source.revision
    if (workflowVersion !== undefined && workflowVersion !== null) {
      return workflowVersion
    }
  }
  return undefined
}

export function canvasMutationTxMarkers(
  payload: unknown
): Array<{ txId?: unknown }> {
  return canvasMutationEnvelopeSources(payload).map((source) => ({
    txId: source.txId ?? source.tx_id,
  }))
}

export const CANVAS_VERSION_REFERENCE_DATA_KEYS = [
  "activeVersionId",
  "sourceVersionId",
  "winnerVersionId",
  "mediaVersionId",
  "assetVersionId",
  "activeMediaVersionId",
] as const

export function canvasVersionRefKey(ref: CanvasVersionRef) {
  return JSON.stringify([ref.nodeId, ref.versionId])
}

export function canvasVersionRefFromKey(key: string): CanvasVersionRef | null {
  try {
    const row = JSON.parse(key)
    if (!Array.isArray(row) || row.length < 2) return null
    const nodeId = String(row[0] ?? "").trim()
    const versionId = String(row[1] ?? "").trim()
    return nodeId && versionId ? { nodeId, versionId } : null
  } catch {
    return null
  }
}

export function canvasVersionRefsFromKeys(keys: string[]) {
  return keys
    .map((key) => canvasVersionRefFromKey(key))
    .filter((ref): ref is CanvasVersionRef => Boolean(ref))
}

export function canvasVersionRefKeyFromParts(
  nodeId: unknown,
  versionId: unknown
) {
  const normalizedNodeId = String(nodeId ?? "").trim()
  const normalizedVersionId = String(versionId ?? "").trim()
  if (!normalizedNodeId || !normalizedVersionId) return ""
  return canvasVersionRefKey({
    nodeId: normalizedNodeId,
    versionId: normalizedVersionId,
  })
}

export function canvasVersionRefFromValue(
  value: unknown
): CanvasVersionRef | null {
  const row = canvasPlainObject(value)
  if (!row) return null
  const nodeId = String(
    row.nodeId ?? row.node_id ?? row.cardId ?? row.card_id ?? ""
  ).trim()
  const versionId = String(
    row.versionId ?? row.version_id ?? row.id ?? ""
  ).trim()
  if (!nodeId || !versionId) return null
  return { nodeId, versionId }
}

export function addCanvasVersionRef(target: Set<string>, value: unknown) {
  const ref = canvasVersionRefFromValue(value)
  if (ref) target.add(canvasVersionRefKey(ref))
}

export function addCanvasVersionRefs(target: Set<string>, values: unknown) {
  if (!Array.isArray(values)) return
  values.forEach((value) => addCanvasVersionRef(target, value))
}

export function canvasRemovedVersionRefs(payload: unknown) {
  const removedVersionRefs = new Set<string>()
  canvasMutationEnvelopeSources(payload).forEach((source) => {
    addCanvasVersionRefs(
      removedVersionRefs,
      source.removedVersionRefs ?? source.removed_version_refs
    )
    const records = canvasPlainObject(source.records)
    const removed = Array.isArray(records?.removed) ? records.removed : []
    removed.forEach((record) => {
      const row = canvasPlainObject(record)
      if (String(row?.type ?? "").trim() !== "canvas_version") return
      addCanvasVersionRef(removedVersionRefs, row)
    })
  })
  return removedVersionRefs
}

export function clearRemovedCanvasVersionRefs(
  nodeId: string,
  data: WorkflowNodeData,
  removedVersionRefs: Set<string>
) {
  const nextData: WorkflowNodeData = { ...data }
  const mutableNextData = nextData as Record<string, unknown>
  let changed = false
  let clearedWinner = false
  const versionOwnerNodeId = workflowNodeVersionStorageNodeId(nodeId, data)
  CANVAS_VERSION_REFERENCE_DATA_KEYS.forEach((key) => {
    const value = String(nextData[key] ?? "").trim()
    if (
      value &&
      removedVersionRefs.has(
        canvasVersionRefKeyFromParts(versionOwnerNodeId, value)
      )
    ) {
      mutableNextData[key] = null
      changed = true
      if (key === "winnerVersionId") clearedWinner = true
    }
  })
  if (clearedWinner) {
    if (nextData.selectionReason !== null) {
      mutableNextData.selectionReason = null
      changed = true
    }
    if (nextData.selectedAt !== null) {
      mutableNextData.selectedAt = null
      changed = true
    }
  }
  return changed ? nextData : data
}

export function canvasMutationChangedResources(payload: unknown) {
  const seen = new Set<string>()
  const resources: string[] = []
  canvasMutationEnvelopeSources(payload).forEach((source) => {
    const values = Array.isArray(source.changedResources)
      ? source.changedResources
      : Array.isArray(source.changed_resources)
        ? source.changed_resources
        : []
    values.forEach((value) => {
      const resource = canvasMutationText(value)
      if (!resource || seen.has(resource)) return
      seen.add(resource)
      resources.push(resource)
    })
  })
  return resources
}

export function canvasMutationEpisodeIds(payload: any) {
  const episodeIds: string[] = []
  const pushEpisodeId = (value: unknown) => {
    const episodeId = String(value || "").trim()
    if (episodeId && !episodeIds.includes(episodeId)) {
      episodeIds.push(episodeId)
    }
  }
  const pushEpisodeIds = (values: unknown) => {
    if (!Array.isArray(values)) return
    values.forEach(pushEpisodeId)
  }
  pushEpisodeIds(payload?.episodeIds)
  pushEpisodeIds(payload?.episode_ids)
  return episodeIds
}

export function eventProjectId(payload: any) {
  return String(payload?.projectId ?? payload?.project_id ?? "").trim()
}

export function canvasMutationTargetsEpisode(
  payload: any,
  projectId: string,
  episodeId: string
) {
  if (!payload || eventProjectId(payload) !== projectId) return false
  const explicitEpisodeId = String(
    payload.episodeId ?? payload.episode_id ?? ""
  ).trim()
  if (explicitEpisodeId) return explicitEpisodeId === episodeId
  const episodeIds = canvasMutationEpisodeIds(payload)
  return !episodeIds.length || episodeIds.includes(episodeId)
}

export function canvasMutationRecordsHaveRefs(records: unknown) {
  const row = canvasPlainObject(records)
  if (!row) return false
  return ["added", "updated", "removed"].some((bucketName) => {
    const bucket = row[bucketName]
    return Array.isArray(bucket) && bucket.length > 0
  })
}

export function canvasPayloadHasMutationEnvelope(payload: unknown) {
  return canvasMutationEnvelopeSources(payload).some((source) => {
    if (canvasMutationText(source.opType ?? source.op_type)) return true
    if (canvasMutationText(source.txId ?? source.tx_id)) return true
    return canvasMutationRecordsHaveRefs(source.records)
  })
}

export function canvasDocumentExtrasCandidates(payload: unknown) {
  const candidates: unknown[] = []
  canvasMutationEnvelopeSources(payload).forEach((source) => {
    candidates.push(source.documentExtras)
    candidates.push(source.document_extras)
    const topLevelExtras: Record<string, unknown> = {}
    ;(["productionStatus", "build", "state"] as const).forEach((key) => {
      if (source[key] !== undefined) topLevelExtras[key] = source[key]
    })
    if (Object.keys(topLevelExtras).length) candidates.push(topLevelExtras)
  })
  canvasProjectionRows(payload).forEach((projection) => {
    const projectionPayload = projection.payload
    const projectionText = canvasProjectionText(projection)
    candidates.push(projectionPayload)
    if (projectionText.includes("production_status")) {
      candidates.push({ productionStatus: projectionPayload })
    }
    if (
      projectionText.includes("input_links") &&
      Array.isArray(projectionPayload)
    ) {
      candidates.push({ inputLinks: projectionPayload })
    }
    if (
      projectionText.includes("work_chains") &&
      Array.isArray(projectionPayload)
    ) {
      candidates.push({ workChains: projectionPayload })
    }
  })
  return candidates
}
