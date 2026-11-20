import {
  storyboardVersionNodeDataPatch,
  storyboardVersionForWorkflowMutation,
} from "./workflow-version-asset-model"
import { useCallback } from "react"
import {
  applyInputLinkChangeLocally,
  inputChangeReasonForCanvasAction,
  isWorkflowGeneratedMediaResultNode,
  mergeTargetInputLink,
  removeInputLinksFromNode,
  storyboardBackendEdgeId,
  upsertStoryboardEdgeLocally,
  workflowNodeVersionStorageNodeId,
} from "./workflow-canvas-asset-model"
import {
  isDirectorBoardNodeType,
  isWorkflowVideoTaskType,
  mergeCreatedWorkflowNodesLocally,
  normalizeWorkflowVersion,
  recordValue,
  toStoryboardEdges,
  toStoryboardEdgesFromBackend,
  toStoryboardNodes,
  toStoryboardNodesFromBackend,
  upsertStoryboardNodesLocally,
  workflowNodeDataCurrentVersionId,
  type WorkflowNodeData,
} from "./workflow-canvas-model"
import { canvasPlainObject } from "./workflow-canvas-mutation-model"
import {
  type EpisodeWorkflow,
  type StoryboardVersion,
  type TaskRow,
  type WorkflowEdge,
  type WorkflowNode,
  type WorkflowRoute,
  type WorkflowWorkChain,
} from "@/backend"
import { preservePendingWorkChains } from "./work-chain-draft"
import {
  workflowVersionResultNodeIds,
  workflowExtras,
  workflowDocumentExtrasPatch,
  canvasUnknownEqual,
  canvasMutationRevision,
  canvasMutationTxMarkers,
  canvasVersionRefKey,
  canvasVersionRefKeyFromParts,
  canvasVersionRefFromValue,
  canvasRemovedVersionRefs,
  clearRemovedCanvasVersionRefs,
  canvasMutationTargetsEpisode,
  canvasDocumentExtrasCandidates,
} from "./workflow-document-model"
import type { WorkflowCanvasDocument } from "./workflow-canvas-document"
import type { WorkflowCanvasDetails } from "./use-workflow-canvas-details"
import type { WorkflowTaskLifecycle } from "./use-workflow-task-lifecycle"
import type { WorkflowNodeActions } from "./workflow-canvas-model"
/** Applies synchronous backend records inside the document's transaction boundary. */
export function useWorkflowDocumentMutations({
  canvasDocument,
  projectId,
  episodeId,
  workflowNodeActions,
  canvasDetails,
  taskLifecycle,
  onHistoryMutation,
}: {
  canvasDocument: WorkflowCanvasDocument
  projectId: string
  episodeId: string
  workflowNodeActions: WorkflowNodeActions
  canvasDetails: WorkflowCanvasDetails
  taskLifecycle: WorkflowTaskLifecycle
  onHistoryMutation: (payload: unknown) => boolean
}) {
  const canvasScopeKey = projectId + "\u0000" + episodeId
  const applyReturnedWorkflow = useCallback(
    (
      workflow?: EpisodeWorkflow | null,
      options: { preserveSelection?: boolean } = {}
    ) => {
      return canvasDocument.transaction(() => {
        if (!workflow) return false
        workflow = preservePendingWorkChains(
          workflow,
          canvasDocument.pendingCreationDrafts()
        )
        const restoredNodeIds = new Set(workflow.nodes.map((node) => node.id))
        const preserveSelection = options.preserveSelection === true
        const selectedIds = new Set(preserveSelection ? canvasDocument.read().nodes.filter(node => node.selected).map(node => node.id) : [])
        canvasDetails.reset()
        canvasDocument.updateNodes(
          toStoryboardNodes(workflow, workflowNodeActions).map(node => ({ ...node, selected: selectedIds.has(node.id) }))
        )
        canvasDocument.updateEdges(toStoryboardEdges(workflow))
        canvasDocument.updateRoutes(workflow.routes ?? [])
        canvasDocument.confirmRevision(workflow.version, { mode: "trusted" })
        canvasDocument.updateProductionState(workflow.state ?? null)
        canvasDocument.updateMetadata(workflowExtras(workflow))
        canvasDocument.markLoaded(canvasScopeKey)
        const nextWorkChains = workflow.workChains ?? []
        canvasDocument.selectWorkChain((current) =>
          current === "all" ||
          nextWorkChains.some((workChain) => workChain.id === current)
            ? current
            : "all"
        )
        canvasDocument.selectNode((current) =>
          preserveSelection && current && restoredNodeIds.has(current)
            ? current
            : null
        )
        return true
      })
    },
    [
      canvasScopeKey,
      canvasDocument.markLoaded,
      canvasDetails.reset,
      canvasDocument.updateEdges,
      canvasDocument.updateNodes,
      canvasDocument.confirmRevision,
      workflowNodeActions,
    ]
  )

  const applyWorkflowMutationEventToCanvas = useCallback(
    (payload: any) => {
      return canvasDocument.transaction(() => {
        if (
          canvasDocument.scope.key !== canvasScopeKey ||
          !canvasMutationTargetsEpisode(payload, projectId, episodeId)
        ) {
          return false
        }

        // Establish the snapshot's revision before applying any live records.
        // A single backfill after loading will include these committed changes.
        if (canvasDocument.read().snapshotLoading || canvasDocument.read().loadedCanvasScopeKey !== canvasScopeKey) {
          canvasDocument.requestBackfill(payload)
          return false
        }

        const payloadAction = String(payload.action ?? "").trim()
        const payloadResult = canvasPlainObject(payload.result)
        const createdWorkChainId = String(
          payload.workChainId ?? payloadResult?.workChainId ?? ""
        ).trim()
        const pendingCreatedDraft = createdWorkChainId
          ? canvasDocument.pendingCreation(createdWorkChainId)
          : undefined
        const finalizePendingCreation = () => {
          if (!createdWorkChainId || !pendingCreatedDraft) return
          canvasDocument.finishCreation(createdWorkChainId)
          canvasDocument.updateNodes((current) =>
            current.map((node) =>
              node.data.workChainId === createdWorkChainId &&
              node.data.creationPending
                ? { ...node, data: { ...node.data, creationPending: false } }
                : node
            )
          )
        }
        const workflowVersion = canvasMutationRevision(payload)
        const incomingRevision =
          workflowVersion !== undefined && workflowVersion !== null
            ? normalizeWorkflowVersion(workflowVersion)
            : null
        const currentRevision = canvasDocument.read().workflowVersion
        const isCanvasChangesReplay = payloadAction === "canvas_changes_applied"
        const carriesCompleteWorkflow = Boolean(
          canvasPlainObject(payload.workflow) ||
          canvasPlainObject(payloadResult?.workflow) ||
          canvasPlainObject(payload.snapshot) ||
          canvasPlainObject(payload.canvasSnapshot)
        )
        const hasRevisionGap =
          incomingRevision !== null &&
          incomingRevision > 0 &&
          incomingRevision > currentRevision + 1 &&
          !isCanvasChangesReplay
        const isStaleRevision =
          incomingRevision !== null &&
          incomingRevision > 0 &&
          incomingRevision < currentRevision
        if (isStaleRevision) {
          if (payloadAction === "manual_workflow_chain_created") {
            finalizePendingCreation()
          }
          canvasDocument.markTransactions(canvasMutationTxMarkers(payload))
          return true
        }

        let applied = isCanvasChangesReplay
        const payloadItem = canvasPlainObject(payload.item)
        const payloadItemType = String(payload.itemType ?? "").trim()
        const isLayoutPatchEvent =
          payloadAction === "workflow_node_layout_updated"
        const layoutNodePatch = isLayoutPatchEvent
          ? canvasPlainObject(payload.node ?? payloadResult?.node)
          : undefined
        const layoutNodeId = String(
          payload.nodeId ?? layoutNodePatch?.id ?? ""
        ).trim()
        if (layoutNodePatch && layoutNodeId) {
          const positionPatch = canvasPlainObject(layoutNodePatch.position)
          const x = Number(positionPatch?.x)
          const y = Number(positionPatch?.y)
          const hasPositionPatch = Number.isFinite(x) && Number.isFinite(y)
          const dataPatch = canvasPlainObject(layoutNodePatch.data)
          const cardStatePatch = canvasPlainObject(dataPatch?.cardState)
          const hasCardStatePatch = cardStatePatch
            ? Object.keys(cardStatePatch).length > 0
            : false
          if (hasPositionPatch || hasCardStatePatch) {
            canvasDocument.updateNodes((current) =>
              current.map((node) => {
                if (node.id !== layoutNodeId) return node
                let nextData = node.data
                if (hasCardStatePatch && cardStatePatch) {
                  nextData = {
                    ...node.data,
                    cardState: {
                      ...recordValue(node.data.cardState),
                      ...cardStatePatch,
                    },
                  }
                }
                return {
                  ...node,
                  position: hasPositionPatch ? { x, y } : node.position,
                  data: nextData,
                }
              })
            )
            applied = true
          }
        }
        const batchLayoutNodes = isLayoutPatchEvent ? [
          ...(Array.isArray(payload.nodes) ? payload.nodes : []),
          ...(Array.isArray(payloadResult?.nodes) ? payloadResult.nodes : []),
        ] : []
        if (batchLayoutNodes.length) {
          const positions = new Map<string, { x: number; y: number }>()
          for (const patch of batchLayoutNodes) {
            if (typeof patch?.id === "string" && Number.isFinite(patch.position?.x) && Number.isFinite(patch.position?.y)) {
              positions.set(patch.id, { x: patch.position.x, y: patch.position.y })
            }
          }
          // Layout replies contain coordinates, not complete card data.
          canvasDocument.updateNodes(current => current.map(node => positions.has(node.id) ? { ...node, position: positions.get(node.id)! } : node))
          applied = positions.size > 0 || applied
        }
        const backendNodes = [
          ...(!isLayoutPatchEvent && Array.isArray(payload.nodes) ? payload.nodes : []),
          ...(!isLayoutPatchEvent && Array.isArray(payloadResult?.nodes) ? payloadResult.nodes : []),
          ...(isLayoutPatchEvent
            ? []
            : [
                payload.node,
                payload.resultNode,
                payloadResult?.node,
                payloadResult?.resultNode,
              ]),
          payloadItemType === "node" ? payloadItem : undefined,
        ].filter(
          (node): node is WorkflowNode =>
            Boolean(node) &&
            typeof node === "object" &&
            typeof node.id === "string" &&
            typeof node.type === "string"
        )
        const backendNodeIds = new Set(backendNodes.map((node) => node.id))
        const backendWorkflowCardSnapshotIds = new Set<string>()
        if (backendNodes.length) {
          const storyboardNodes = toStoryboardNodesFromBackend(
            backendNodes,
            workflowNodeActions,
            canvasDocument.read().routes
          )
          const hydratedWorkflowCardNodeIds = storyboardNodes
            .filter(
              (node) =>
                (isDirectorBoardNodeType(node.data.eyebrow) ||
                  isWorkflowVideoTaskType(node.data.eyebrow)) &&
                (Array.isArray(node.data.referenceVideoThumbnails) ||
                  Array.isArray(node.data.referenceThumbnails) ||
                  Array.isArray(node.data.assetThumbnails))
            )
            .map((node) => node.id)
          if (hydratedWorkflowCardNodeIds.length) {
            hydratedWorkflowCardNodeIds.forEach((nodeId) =>
              backendWorkflowCardSnapshotIds.add(nodeId)
            )
            canvasDetails.markLoaded(hydratedWorkflowCardNodeIds)
          }
          canvasDocument.updateNodes((current) =>
            payloadAction === "manual_workflow_chain_created"
              ? mergeCreatedWorkflowNodesLocally(current, storyboardNodes)
              : upsertStoryboardNodesLocally(current, storyboardNodes)
          )
          applied = true
        }

        const backendEdges = [
          ...(Array.isArray(payload.edges) ? payload.edges : []),
          ...(Array.isArray(payloadResult?.edges) ? payloadResult.edges : []),
          payload.edge,
          payloadResult?.edge,
          payloadItemType === "edge" ? payloadItem : undefined,
        ].filter(
          (edge): edge is WorkflowEdge =>
            Boolean(edge) &&
            typeof edge === "object" &&
            typeof edge.source === "string" &&
            typeof edge.target === "string"
        )
        const backendEdgeIds = new Set(
          backendEdges
            .map((edge) => String(edge.id ?? "").trim())
            .filter(Boolean)
        )
        if (backendEdges.length) {
          canvasDocument.updateEdges((current) => {
            const storyboardEdges = toStoryboardEdgesFromBackend(
              backendEdges,
              canvasDocument.read().nodes,
              backendNodes,
              canvasDocument.read().routes
            )
            return storyboardEdges.reduce(
              (nextEdges, edge) => upsertStoryboardEdgeLocally(nextEdges, edge),
              current
            )
          })
          applied = true
        }

        const backendRoutes = [
          ...(Array.isArray(payload.routes) ? payload.routes : []),
          ...(Array.isArray(payloadResult?.routes) ? payloadResult.routes : []),
          payload.route,
          payloadResult?.route,
          payloadItemType === "route" ? payloadItem : undefined,
        ].filter(
          (route): route is WorkflowRoute =>
            Boolean(route) &&
            typeof route === "object" &&
            !Array.isArray(route) &&
            typeof route.id === "string"
        )
        if (backendRoutes.length) {
          canvasDocument.updateRoutes((current) => {
            return backendRoutes.reduce((next, payloadRoute) => {
              const index = next.findIndex(
                (route) => route.id === payloadRoute.id
              )
              if (index < 0) return [...next, payloadRoute]
              const updated = [...next]
              updated[index] = { ...next[index], ...payloadRoute }
              return updated
            }, current)
          })
          applied = true
        }

        const backendWorkChains = [
          ...(Array.isArray(payload.workChains) ? payload.workChains : []),
          ...(Array.isArray(payload.work_chains) ? payload.work_chains : []),
          ...(Array.isArray(payloadResult?.workChains)
            ? payloadResult.workChains
            : []),
          ...(Array.isArray(payloadResult?.work_chains)
            ? payloadResult.work_chains
            : []),
        ].filter(
          (workChain): workChain is WorkflowWorkChain =>
            Boolean(workChain) &&
            typeof workChain === "object" &&
            !Array.isArray(workChain) &&
            typeof workChain.id === "string"
        )
        if (backendWorkChains.length) {
          canvasDocument.updateMetadata((current) => {
            const currentWorkChains = Array.isArray(current.workChains)
              ? current.workChains
              : []
            const nextWorkChains = backendWorkChains.reduce(
              (next, workChain) => {
                const index = next.findIndex((item) => item.id === workChain.id)
                if (index < 0) return [...next, workChain]
                const updated = [...next]
                updated[index] = { ...next[index], ...workChain }
                return updated
              },
              currentWorkChains
            )
            return { ...current, workChains: nextWorkChains }
          })
          applied = true
        }

        const backendTasks = [
          ...(Array.isArray(payload.tasks) ? payload.tasks : []),
          ...(Array.isArray(payloadResult?.tasks) ? payloadResult.tasks : []),
        ].filter(
          (task): task is TaskRow =>
            Boolean(task) &&
            typeof task === "object" &&
            !Array.isArray(task) &&
            Boolean(String((task as Record<string, unknown>).id ?? "").trim())
        )
        if (backendTasks.length) {
          taskLifecycle.upsertRecords(backendTasks)
          applied = true
        }

        const backendVersions = [
          ...(Array.isArray(payload.versions) ? payload.versions : []),
          ...(Array.isArray(payloadResult?.versions)
            ? payloadResult.versions
            : []),
          payload.version,
          payloadResult?.version,
        ].filter(
          (version): version is StoryboardVersion =>
            Boolean(version) &&
            typeof version === "object" &&
            !Array.isArray(version) &&
            Boolean(
              String((version as Record<string, unknown>).id ?? "").trim()
            )
        )
        if (backendVersions.length) {
          const referenceNodes = canvasDocument.read().nodes
          const referenceEdges = canvasDocument.read().edges
          const targetIdsByVersionRef = new Map<string, Set<string>>()
          backendVersions.forEach((version) => {
            const versionId = String(version.id ?? "").trim()
            if (!versionId) return
            const versionRecord = version as Record<string, unknown>
            const versionNodeId = String(
              version.nodeId ??
                versionRecord.node_id ??
                versionRecord.cardId ??
                versionRecord.card_id ??
                ""
            ).trim()
            if (!versionNodeId) return
            const versionRefKey = canvasVersionRefKeyFromParts(
              versionNodeId,
              versionId
            )
            if (!versionRefKey) return
            const targetIds = new Set<string>()
            workflowVersionResultNodeIds(
              versionNodeId,
              referenceNodes,
              referenceEdges
            ).forEach((id) => targetIds.add(id))
            referenceNodes.forEach((node) => {
              const currentVersionId = workflowNodeDataCurrentVersionId(
                node.data
              )
              const mediaVersionId = String(
                node.data.mediaVersionId ?? ""
              ).trim()
              const activeMediaVersionId = String(
                node.data.activeMediaVersionId ?? ""
              ).trim()
              const nodeVersionOwnerId = workflowNodeVersionStorageNodeId(
                node.id,
                node.data
              )
              if (
                nodeVersionOwnerId === versionNodeId &&
                isWorkflowGeneratedMediaResultNode(node) &&
                (currentVersionId === versionId ||
                  mediaVersionId === versionId ||
                  activeMediaVersionId === versionId)
              ) {
                targetIds.add(node.id)
              }
            })
            if (
              !targetIds.size &&
              referenceNodes.some(
                (node) =>
                  node.id === versionNodeId &&
                  isWorkflowGeneratedMediaResultNode(node)
              )
            ) {
              targetIds.add(versionNodeId)
            }
            if (targetIds.size)
              targetIdsByVersionRef.set(versionRefKey, targetIds)
          })
          if (targetIdsByVersionRef.size) {
            canvasDocument.updateNodes((current) => {
              let changed = false
              const nextNodes = current.map((node) => {
                const matchingVersions = backendVersions.filter((item) => {
                  const ref = canvasVersionRefFromValue(item)
                  return ref
                    ? targetIdsByVersionRef
                        .get(canvasVersionRefKey(ref))
                        ?.has(node.id)
                    : false
                })
                const version = storyboardVersionForWorkflowMutation(
                  node.data,
                  matchingVersions
                )
                if (!version?.id) return node
                const versionStatus = String(version.status ?? "")
                  .trim()
                  .toLowerCase()
                const nextStatus =
                  versionStatus === "processing"
                    ? "waiting"
                    : ["failed", "blocked", "cancelled", "canceled"].includes(
                          versionStatus
                        )
                      ? "failed"
                      : "ready"
                const nextData: WorkflowNodeData = {
                  ...node.data,
                  ...storyboardVersionNodeDataPatch(node.data, version, {
                    status: nextStatus,
                    storageMode: "clear",
                  }),
                }
                if (version.winner) {
                  nextData.winnerVersionId = version.id
                  nextData.selectionReason =
                    version.selectionReason ?? node.data.selectionReason
                  nextData.selectedAt =
                    version.selectedAt ?? node.data.selectedAt
                }
                if (canvasUnknownEqual(nextData, node.data)) return node
                changed = true
                return { ...node, data: nextData }
              })
              if (!changed) return current
              return nextNodes
            })
            applied = true
          }
        }

        const removedVersionRefs = canvasRemovedVersionRefs(payload)
        if (removedVersionRefs.size) {
          canvasDocument.updateNodes((current) =>
            current.map((node) => {
              const nextData = clearRemovedCanvasVersionRefs(
                node.id,
                node.data,
                removedVersionRefs
              )
              return nextData === node.data ? node : { ...node, data: nextData }
            })
          )
          applied = true
        }

        const action = String(payload.action ?? "")
        const targetNodeId = String(payload.targetNodeId ?? "").trim()
        const payloadInputLink =
          payload.inputLink &&
          typeof payload.inputLink === "object" &&
          !Array.isArray(payload.inputLink)
            ? (payload.inputLink as Record<string, unknown>)
            : undefined
        if (
          action === "workflow_input_linked" &&
          payloadInputLink &&
          targetNodeId &&
          !backendNodes.length
        ) {
          if (
            canvasDocument.read().nodes.some((node) => node.id === targetNodeId)
          ) {
            canvasDocument.updateNodes((current) =>
              current.map((node) =>
                node.id === targetNodeId
                  ? mergeTargetInputLink(node, payloadInputLink)
                  : node
              )
            )
            applied = true
          }
        }

        if (onHistoryMutation(payload)) applied = true
        const removedInputLinkIds = new Set(
          [
            ...(Array.isArray(payload.removedLinkIds)
              ? payload.removedLinkIds
              : []),
            ...(Array.isArray(payload.removedInputLinkIds)
              ? payload.removedInputLinkIds
              : []),
            ...(Array.isArray(payload.removedLinks)
              ? payload.removedLinks.map((link: unknown) =>
                  link && typeof link === "object"
                    ? String((link as Record<string, unknown>).id ?? "")
                    : ""
                )
              : []),
          ]
            .map((item) => String(item || "").trim())
            .filter(Boolean)
        )
        const removedEdgeIds = new Set(
          (Array.isArray(payload.removedEdgeIds) ? payload.removedEdgeIds : [])
            .map((item: unknown) => String(item || "").trim())
            .filter(
              (item: string) => Boolean(item) && !backendEdgeIds.has(item)
            )
        )
        const affectedNodeIds = new Set(
          [
            ...(Array.isArray(payload.affectedNodeIds)
              ? payload.affectedNodeIds
              : []),
          ]
            .map((item: unknown) => String(item || "").trim())
            .filter(Boolean)
        )
        if (
          [
            "workflow_input_linked",
            "workflow_input_unlinked",
            "workflow_reference_usage_updated",
            "workflow_item_deleted",
          ].includes(action)
        ) {
          const refreshCandidateIds = new Set<string>()
          const addRefreshIds = (value: unknown) => {
            if (Array.isArray(value)) {
              value.forEach((item) => {
                const id = String(item || "").trim()
                if (id) refreshCandidateIds.add(id)
              })
              return
            }
            const id = String(value || "").trim()
            if (id) refreshCandidateIds.add(id)
          }
          addRefreshIds(targetNodeId)
          addRefreshIds(Array.from(affectedNodeIds))
          addRefreshIds(payload.inputDirtyNodeIds)
          addRefreshIds(payload.syncedVideoTaskNodeIds)
          addRefreshIds(payloadResult?.inputDirtyNodeIds)
          addRefreshIds(payloadResult?.syncedVideoTaskNodeIds)
          const currentNodes = canvasDocument.read().nodes
          const refreshNodeIds = Array.from(refreshCandidateIds).filter(
            (nodeId) => {
              if (backendWorkflowCardSnapshotIds.has(nodeId)) return false
              const node = currentNodes.find((item) => item.id === nodeId)
              return Boolean(
                node &&
                (isDirectorBoardNodeType(node.data.eyebrow) ||
                  isWorkflowVideoTaskType(node.data.eyebrow))
              )
            }
          )
          if (refreshNodeIds.length) {
            canvasDetails.refresh(refreshNodeIds)
          }
        }
        if (action !== "workflow_input_unlinked" && removedEdgeIds.size) {
          canvasDocument.updateEdges((current) =>
            current.filter(
              (edge) => !removedEdgeIds.has(storyboardBackendEdgeId(edge))
            )
          )
          applied = true
        }
        if (
          action === "workflow_input_unlinked" &&
          (removedInputLinkIds.size || removedEdgeIds.size)
        ) {
          canvasDocument.updateEdges((current) =>
            current.filter((edge) => {
              if (removedEdgeIds.has(storyboardBackendEdgeId(edge)))
                return false
              const inputLinkId = String(edge.data?.inputLinkId ?? "").trim()
              return !inputLinkId || !removedInputLinkIds.has(inputLinkId)
            })
          )
          if (!backendNodes.length && removedInputLinkIds.size) {
            const changeAt = new Date().toISOString()
            canvasDocument.updateNodes((current) =>
              current.map((node) => {
                const targetMatches = !targetNodeId || node.id === targetNodeId
                if (!targetMatches || !Array.isArray(node.data.inputLinks))
                  return node
                return removeInputLinksFromNode(
                  node,
                  removedInputLinkIds,
                  "input_link_unlinked",
                  changeAt
                )
              })
            )
          }
          applied = true
        }

        if (action === "workflow_item_deleted") {
          const itemType = String(payload.itemType ?? "").trim()
          const itemId = String(payload.itemId ?? "").trim()
          const skippedLocked = payload.skippedLocked === true
          const deletedNodeIds = new Set(
            [
              ...(Array.isArray(payload.deletedNodeIds)
                ? payload.deletedNodeIds
                : []),
              itemType === "node" && !skippedLocked ? itemId : "",
            ]
              .map((id) => String(id || "").trim())
              .filter(Boolean)
          )
          const deletedEdgeIds = new Set(
            [
              ...(Array.isArray(payload.deletedEdgeIds)
                ? payload.deletedEdgeIds
                : []),
            ]
              .map((id) => String(id || "").trim())
              .filter(Boolean)
          )
          const deletedRouteIds = new Set(
            [
              ...(Array.isArray(payload.deletedRouteIds)
                ? payload.deletedRouteIds
                : []),
              itemType === "route" && !skippedLocked ? itemId : "",
            ]
              .map((id) => String(id || "").trim())
              .filter(Boolean)
          )
          const deletedWorkChainIds = new Set(
            [
              ...(Array.isArray(payload.deletedWorkChainIds)
                ? payload.deletedWorkChainIds
                : []),
              itemType === "workChain" && !skippedLocked ? itemId : "",
            ]
              .map((id) => String(id || "").trim())
              .filter(Boolean)
          )
          const deletedTaskIds = new Set<string>(
            (Array.isArray(payload.deletedTaskIds)
              ? payload.deletedTaskIds
              : []
            )
              .map((id: unknown) => String(id || "").trim())
              .filter(Boolean)
          )
          const mutationRecords = canvasPlainObject(payload.records)
          ;(Array.isArray(mutationRecords?.removed)
            ? mutationRecords.removed
            : []
          ).forEach((record) => {
            if (!record || typeof record !== "object" || Array.isArray(record))
              return
            const row = record as Record<string, unknown>
            if (String(row.type ?? "").trim() !== "canvas_task") return
            const taskId = String(row.id ?? "").trim()
            if (taskId) deletedTaskIds.add(taskId)
          })
          if (
            deletedNodeIds.size ||
            deletedEdgeIds.size ||
            deletedRouteIds.size ||
            deletedWorkChainIds.size
          ) {
            canvasDocument.updateNodes((current) =>
              current.filter((node) => !deletedNodeIds.has(node.id))
            )
            canvasDocument.updateEdges((current) =>
              current.filter((edge) => {
                if (deletedEdgeIds.has(storyboardBackendEdgeId(edge)))
                  return false
                if (
                  deletedNodeIds.has(edge.source) ||
                  deletedNodeIds.has(edge.target)
                ) {
                  return false
                }
                const routeId = String(edge.data?.routeId ?? "").trim()
                if (routeId && deletedRouteIds.has(routeId)) return false
                const workChainId = String(edge.data?.workChainId ?? "").trim()
                return !workChainId || !deletedWorkChainIds.has(workChainId)
              })
            )
            if (deletedRouteIds.size || deletedWorkChainIds.size) {
              canvasDocument.updateRoutes((current) =>
                current.filter((route) => {
                  if (deletedRouteIds.has(route.id)) return false
                  const workChainId = String(route.workChainId ?? "").trim()
                  return !workChainId || !deletedWorkChainIds.has(workChainId)
                })
              )
              canvasDocument.updateMetadata((current) => {
                const currentWorkChains = Array.isArray(current.workChains)
                  ? current.workChains
                  : []
                if (!currentWorkChains.length) return current
                let changed = false
                const nextWorkChains = currentWorkChains
                  .filter((workChain) => {
                    const workChainId = String(workChain.id ?? "").trim()
                    const keep =
                      !workChainId || !deletedWorkChainIds.has(workChainId)
                    if (!keep) changed = true
                    return keep
                  })
                  .map((workChain): WorkflowWorkChain => {
                    if (!Array.isArray(workChain.routeIds)) return workChain
                    const nextRouteIds = workChain.routeIds.filter(
                      (routeId) =>
                        !deletedRouteIds.has(String(routeId ?? "").trim())
                    )
                    if (nextRouteIds.length === workChain.routeIds.length)
                      return workChain
                    changed = true
                    return { ...workChain, routeIds: nextRouteIds }
                  })
                return changed
                  ? { ...current, workChains: nextWorkChains }
                  : current
              })
            }
            if (deletedTaskIds.size || deletedNodeIds.size) {
              taskLifecycle.removeRecords(deletedTaskIds, deletedNodeIds)
            }
            if (!backendNodes.length && removedInputLinkIds.size) {
              const changeAt = new Date().toISOString()
              canvasDocument.updateNodes((current) =>
                current.map((node) =>
                  deletedNodeIds.has(node.id)
                    ? node
                    : removeInputLinksFromNode(
                        node,
                        removedInputLinkIds,
                        "linked_item_deleted",
                        changeAt
                      )
                )
              )
            }
            applied = true
          }
        }

        if (affectedNodeIds.size) {
          const fallbackAffectedNodeIds = new Set(
            [...affectedNodeIds].filter((id) => !backendNodeIds.has(id))
          )
          if (fallbackAffectedNodeIds.size) {
            const changeAt = new Date().toISOString()
            const changeReason = inputChangeReasonForCanvasAction(action)
            canvasDocument.updateNodes((current) =>
              current.map((node) =>
                fallbackAffectedNodeIds.has(node.id)
                  ? applyInputLinkChangeLocally(node, changeReason, changeAt)
                  : node
              )
            )
            applied = true
          }
        }

        const documentExtrasPatch: Partial<EpisodeWorkflow> = {}
        let documentExtrasChanged = false
        canvasDocumentExtrasCandidates(payload).forEach((candidate) => {
          const patch = workflowDocumentExtrasPatch(candidate)
          if (!patch) return
          Object.assign(documentExtrasPatch, patch)
          documentExtrasChanged = true
        })
        if (documentExtrasChanged) {
          canvasDocument.updateMetadata((current) => ({
            ...current,
            ...documentExtrasPatch,
          }))
          if (documentExtrasPatch.state)
            canvasDocument.updateProductionState(documentExtrasPatch.state)
          applied = true
        }
        if (applied && incomingRevision !== null) {
          const syncedRevision = canvasDocument.read().workflowVersion
          if (hasRevisionGap) {
            canvasDocument.requestBackfill(payload)
          } else if (incomingRevision >= syncedRevision) {
            canvasDocument.confirmRevision(incomingRevision, {
              mode:
                isCanvasChangesReplay || carriesCompleteWorkflow
                  ? "trusted"
                  : "mutation",
              payload,
            })
          }
        }
        if (applied) {
          if (payloadAction === "manual_workflow_chain_created") {
            finalizePendingCreation()
          }
          canvasDocument.markLoaded(canvasScopeKey)
          canvasDocument.markTransactions(canvasMutationTxMarkers(payload))
        }
        return applied
      })
    },
    [
      applyReturnedWorkflow,
      canvasScopeKey,
      episodeId,
      canvasDocument.markLoaded,
      onHistoryMutation,
      projectId,
      canvasDocument.markTransactions,
      canvasDetails.refresh,
      canvasDocument.requestBackfill,
      canvasDocument.updateEdges,
      canvasDocument.updateNodes,
      canvasDocument.confirmRevision,
      canvasDocument.updateMetadata,
      taskLifecycle.replaceSnapshot,
      taskLifecycle.upsertRecords,
      taskLifecycle.removeRecords,
      workflowNodeActions,
    ]
  )
  return {
    replace: applyReturnedWorkflow,
    applyMutation: applyWorkflowMutationEventToCanvas,
  }
}
