import {
  canvasMutationChangedResources,
  canvasMutationTargetsEpisode,
  eventProjectId,
  canvasPayloadHasMutationEnvelope,
  canvasMutationOpType,
  canvasMutationTxMarkers,
} from "./workflow-document-model"
import {
  workflowVideoDurationSyncWarningMessage,
  workflowVersionResultNodeIds,
  canvasMutationRevision,
} from "./workflow-document-model"
import { useCallback, useEffect } from "react"
import {
  CANVAS_DOCUMENT_REPLACE_ACTIONS,
  CANVAS_INCREMENTAL_CHANGED_RESOURCES,
  CANVAS_INCREMENTAL_OP_TYPES,
  CANVAS_LOCAL_PROJECT_CHANGED_ACTIONS,
  isWorkflowGeneratedMediaResultNode,
  workflowNodeDataHasEditableOriginalImage,
} from "./workflow-canvas-asset-model"
import {
  normalizeWorkflowVersion,
  recordValue,
  type WorkflowNodeData,
} from "./workflow-canvas-model"
import { canvasPlainObject } from "./workflow-canvas-mutation-model"
import { workflowNodeMediaType } from "./workflow-node-relations"
import {
  workflowStatusTaskType,
  workflowTaskCanvasResultNodeIds,
  workflowTaskRelatedNodeIds,
  workflowTaskSuccessText,
  workflowTaskVersion,
  workflowTaskVersionId,
} from "./workflow-task-status"
import { toast } from "sonner"
import { type AssetType, type TaskRow } from "@/backend"
import { invalidateCachedAssetRows } from "@/features/assets/asset-cache"
import { unboundCanvasAssetImageIds } from "./canvas-reference-views"
import { workflowNodeStatusFromTask } from "./workflow-task-projection"
import type { WorkflowCanvasDocument } from "./workflow-canvas-document"
import type { useBackend } from "@/hooks/useBackend"
import type { useWorkflowCanvasDetails } from "./use-workflow-canvas-details"
import type { useWorkflowDocumentSync } from "./use-workflow-document-sync"
import type { useWorkflowTaskLifecycle } from "./use-workflow-task-lifecycle"
export function useWorkflowCanvasEvents({
  projectId,
  episodeId,
  backendReady,
  onBackendEvent,
  canvasDocument,
  canvasDetails,
  documentSync,
  taskLifecycle,
}: {
  projectId: string
  episodeId: string
  backendReady: boolean
  onBackendEvent: ReturnType<typeof useBackend>["onBackendEvent"]
  canvasDocument: WorkflowCanvasDocument
  canvasDetails: ReturnType<typeof useWorkflowCanvasDetails>
  documentSync: ReturnType<typeof useWorkflowDocumentSync>
  taskLifecycle: ReturnType<typeof useWorkflowTaskLifecycle>
}) {
  const isStaleCanvasMutationRevision = useCallback((payload: any) => {
    // Wait for the snapshot's baseline before comparing event revisions,
    // including when a loaded canvas is being reconciled in the background.
    if (canvasDocument.read().snapshotLoading || canvasDocument.read().loadedCanvasScopeKey !== canvasDocument.scope.key) return false
    const workflowVersion = canvasMutationRevision(payload)
    if (workflowVersion === undefined || workflowVersion === null) return false
    const incomingRevision = normalizeWorkflowVersion(workflowVersion)
    return (
      incomingRevision > 0 &&
      incomingRevision < canvasDocument.read().workflowVersion
    )
  }, [])

  const hydrateOpenStoryboardScriptEditor = useCallback(
    (
      payload: any,
      eventName?: "task_completed" | "task_failed",
      mutationApplied = false
    ) => {
      if (eventName && eventName !== "task_completed") return false
      const action = String(payload?.action ?? "")
      const taskType = workflowStatusTaskType(payload as TaskRow)
      const taskStatus = String(payload?.status ?? "").trim()
      const isCinematicScriptResult =
        action === "workflow_cinematic_script_generated" ||
        (taskType === "workflow_cinematic_script" &&
          ["completed", "succeeded"].includes(taskStatus))
      if (!isCinematicScriptResult) return false

      const selectedNodeId = canvasDocument.read().selectedNodeId
      if (!selectedNodeId) return false
      const selectedNode = canvasDocument
        .read()
        .nodes.find((node) => node.id === selectedNodeId)
      if (selectedNode?.data.eyebrow !== "prompt.storyboard") return false

      const relatedNodeIds = workflowTaskRelatedNodeIds(payload as TaskRow)
      const payloadResult = recordValue(payload?.result)
      const addNodeId = (value: unknown) => {
        const id = String(recordValue(value).id ?? "").trim()
        if (id) relatedNodeIds.add(id)
      }
      addNodeId(payload?.node)
      addNodeId(payload?.resultNode)
      addNodeId(payloadResult.node)
      addNodeId(payloadResult.resultNode)

      const payloadWorkChainId = String(
        payload?.workChainId ?? payloadResult.workChainId ?? ""
      ).trim()
      const matchedByNode = relatedNodeIds.has(selectedNodeId)
      const matchedByWorkChain =
        Boolean(payloadWorkChainId) &&
        payloadWorkChainId ===
          String(selectedNode.data.workChainId ?? "").trim()
      if (!matchedByNode && !matchedByWorkChain) return false

      if (!mutationApplied) {
        void canvasDetails.hydrate(selectedNodeId, { force: true })
      }
      return true
    },
    [canvasDetails.hydrate]
  )

  const applyWorkflowTaskResultToCanvas = useCallback(
    (task: TaskRow) => {
      if (task.type === "video_prompt" && task.promptOperation === "optimize")
        return
      const statusNodeIds = workflowTaskRelatedNodeIds(task)
      const resultNodeIds = workflowTaskCanvasResultNodeIds(task)
      if (statusNodeIds.size === 0 && resultNodeIds.size === 0) return
      const status = workflowNodeStatusFromTask(task)
      const version = workflowTaskVersion(task)
      const versionId = workflowTaskVersionId(task)
      const versionMedia = version?.media ?? null
      canvasDocument.updateNodes((current) => {
        const targetIds = new Set<string>(statusNodeIds)
        const mediaTargetIds = new Set<string>()
        resultNodeIds.forEach((nodeId) => {
          const resultIds = workflowVersionResultNodeIds(
            nodeId,
            current,
            canvasDocument.read().edges
          )
          if (resultIds.size) {
            resultIds.forEach((id) => {
              targetIds.add(id)
              mediaTargetIds.add(id)
            })
          } else {
            targetIds.add(nodeId)
            mediaTargetIds.add(nodeId)
          }
        })
        return current.map((node) => {
          if (!targetIds.has(node.id)) return node
          const nextData: WorkflowNodeData = {
            ...node.data,
            status,
            summary: node.data.summary,
          }
          if (versionId && workflowNodeMediaType(node)) {
            if (
              mediaTargetIds.has(node.id) &&
              isWorkflowGeneratedMediaResultNode(node)
            ) {
              nextData.summary = version?.summary || node.data.summary
              if (versionMedia) {
                nextData.activeVersionId = versionId
                nextData.sourceVersionId = versionId
                nextData.mediaVersionId = versionId
                nextData.activeMediaVersionId = versionId
                nextData.status = "ready"
                nextData.media = versionMedia
                nextData.storage = null
              }
            } else if (
              versionMedia &&
              !isWorkflowGeneratedMediaResultNode(node)
            ) {
              nextData.activeVersionId = versionId
              nextData.sourceVersionId = versionId
              nextData.mediaVersionId = versionId
              nextData.activeMediaVersionId = versionId
            }
          }
          return { ...node, data: nextData }
        })
      })
    },
    [canvasDocument.updateNodes]
  )

  const hydrateWorkflowTaskResultCardsIfNeeded = useCallback(
    (task: TaskRow | null | undefined) => {
      if (!task) return false
      const status = String(task.status ?? "").trim()
      if (!["completed", "succeeded"].includes(status)) return false
      if (!workflowTaskVersionId(task)) return false
      const version = workflowTaskVersion(task)
      if (version?.media) return false
      const currentNodes = canvasDocument.read().nodes
      const targetIds = new Set<string>()
      workflowTaskCanvasResultNodeIds(task).forEach((nodeId) => {
        workflowVersionResultNodeIds(
          nodeId,
          currentNodes,
          canvasDocument.read().edges
        ).forEach((id) => targetIds.add(id))
      })
      let scheduled = false
      targetIds.forEach((targetId) => {
        const node = currentNodes.find((item) => item.id === targetId)
        if (!isWorkflowGeneratedMediaResultNode(node)) return
        scheduled = true
        void canvasDetails.hydrate(targetId, { force: true })
      })
      return scheduled
    },
    [canvasDetails.hydrate]
  )

  useEffect(() => {
    if (!backendReady) return
    const requestScope = canvasDocument.scope
    const changedResourcesForEvent = (payload: any) =>
      canvasMutationChangedResources(payload)
    const eventTargetsCurrentEpisode = (payload: any) => {
      return canvasMutationTargetsEpisode(payload, projectId, episodeId)
    }
    const projectAssetTypes = new Set<AssetType>([
      "characters",
      "creatures",
      "scenes",
      "props",
    ])
    const assetTypeForEvent = (payload: any) => {
      const value = String(payload?.assetType ?? payload?.asset_type ?? "")
      return projectAssetTypes.has(value as AssetType)
        ? (value as AssetType)
        : null
    }
    const invalidateProjectAssetRowsForEvent = (payload: any) => {
      if (!payload || eventProjectId(payload) !== projectId) return
      const assetType = assetTypeForEvent(payload)
      const changedResources = changedResourcesForEvent(payload)
      const assetsChanged = changedResources.some((resource: string) => {
        if (resource === "assets") return true
        return projectAssetTypes.has(resource as AssetType)
      })
      if (!assetType && !assetsChanged) return
      if (assetType) {
        invalidateCachedAssetRows({
          scope: "project",
          projectId: projectId,
          assetType,
        })
        return
      }
      invalidateCachedAssetRows({ scope: "project", projectId: projectId })
    }
    const isCurrentEpisodeEvent = (payload: any) =>
      Boolean(
        payload &&
        eventProjectId(payload) === projectId &&
        eventTargetsCurrentEpisode(payload)
      )
    const sourceTextChanged = (payload: any) => {
      const action = String(payload?.action ?? "")
      const changedResources = changedResourcesForEvent(payload)
      return (
        action === "episode_source_text_saved" ||
        changedResources.some((resource: string) =>
          [
            "episode_source",
            "episodeSource",
            "source_text",
            "sourceText",
          ].includes(resource)
        )
      )
    }
    const eventCarriesCanvasSnapshot = (payload: any) => {
      const payloadResult = canvasPlainObject(payload?.result)
      const payloadItem = canvasPlainObject(payload?.item)
      const payloadVersion = canvasPlainObject(payload?.version)
      const payloadResultVersion = canvasPlainObject(payloadResult?.version)
      const payloadItemType = String(payload?.itemType ?? "").trim()
      const action = String(payload?.action ?? "").trim()
      const carriesLocalDeletePatch =
        action === "workflow_item_deleted" &&
        Boolean(
          payload?.itemId ||
          [
            "deletedNodeIds",
            "deletedEdgeIds",
            "deletedRouteIds",
            "deletedWorkChainIds",
          ].some(
            (key) => Array.isArray(payload?.[key]) && payload[key].length > 0
          )
        )
      return Boolean(
        carriesLocalDeletePatch ||
        (Array.isArray(payload?.nodes) && payload.nodes.length > 0) ||
        (Array.isArray(payload?.edges) && payload.edges.length > 0) ||
        (Array.isArray(payload?.routes) && payload.routes.length > 0) ||
        (Array.isArray(payload?.workChains) && payload.workChains.length > 0) ||
        (Array.isArray(payload?.work_chains) &&
          payload.work_chains.length > 0) ||
        (Array.isArray(payload?.tasks) && payload.tasks.length > 0) ||
        (Array.isArray(payload?.versions) && payload.versions.length > 0) ||
        (Array.isArray(payloadResult?.nodes) &&
          payloadResult.nodes.length > 0) ||
        (Array.isArray(payloadResult?.edges) &&
          payloadResult.edges.length > 0) ||
        (Array.isArray(payloadResult?.routes) &&
          payloadResult.routes.length > 0) ||
        (Array.isArray(payloadResult?.workChains) &&
          payloadResult.workChains.length > 0) ||
        (Array.isArray(payloadResult?.work_chains) &&
          payloadResult.work_chains.length > 0) ||
        (Array.isArray(payloadResult?.tasks) &&
          payloadResult.tasks.length > 0) ||
        (Array.isArray(payloadResult?.versions) &&
          payloadResult.versions.length > 0) ||
        payload?.node ||
        payload?.resultNode ||
        payload?.edge ||
        payload?.route ||
        payloadVersion ||
        payloadResult?.node ||
        payloadResult?.resultNode ||
        payloadResult?.edge ||
        payloadResult?.route ||
        payloadResultVersion ||
        (["node", "edge", "route"].includes(payloadItemType) && payloadItem)
      )
    }
    const isLocalTaskCanvasUpdate = (payload: any) => {
      const action = String(payload?.action ?? "")
      const taskType = String(payload?.type ?? "")
      return (
        [
          "video_prompt",
          "storyboard_image",
          "storyboard_image_edit",
          "storyboard_plan",
          "workflow_cinematic_script",
          "visual_handoff_image",
          "storyboard_video",
          "route_video",
        ].includes(taskType) ||
        [
          "storyboard_image_generated",
          "director_plan_generated",
          "visual_handoff_image_generated",
          "storyboard_video_generated",
          "workflow_node_generated",
          "workflow_batch_generated",
          "variant_quality_result_saved",
          "workflow_node_preflight_checked",
          "workflow_cinematic_script_generated",
          "storyboard_image_requested",
          "storyboard_image_edit_completed",
          "storyboard_image_edit_failed",
          "storyboard_video_requested",
          "route_video_requested",
          "route_video_generated",
          "workflow_variant_selected",
          "storyboard_version_deleted",
          "episode_production_status_updated",
        ].includes(action) ||
        action.startsWith("workflow_task_")
      )
    }
    const eventHasCanvasMutationEnvelope = (payload: any) => {
      return canvasPayloadHasMutationEnvelope(payload)
    }
    const shouldUseCanvasChanges = (payload: any) => {
      if (!payload || eventProjectId(payload) !== projectId) return false
      if (!eventTargetsCurrentEpisode(payload)) return false
      if (eventCarriesCanvasSnapshot(payload)) return false
      const opType = canvasMutationOpType(payload)
      if (opType && !CANVAS_INCREMENTAL_OP_TYPES.has(opType)) return false
      const changedResources = changedResourcesForEvent(payload)
      const hasIncrementalResource = changedResources.some((resource: string) =>
        CANVAS_INCREMENTAL_CHANGED_RESOURCES.has(resource)
      )
      if (opType && CANVAS_INCREMENTAL_OP_TYPES.has(opType)) return true
      if (hasIncrementalResource) return true
      return (
        payload.workflowOmitted === true &&
        eventHasCanvasMutationEnvelope(payload)
      )
    }
    const shouldRefresh = (payload: any, mutationApplied = false) => {
      if (!payload || eventProjectId(payload) !== projectId) return false
      if (!eventTargetsCurrentEpisode(payload)) return false
      const action = String(payload.action ?? "")
      const taskType = workflowStatusTaskType(payload as TaskRow)
      if (
        action === "workflow_cinematic_script_generated" ||
        taskType === "workflow_cinematic_script"
      ) {
        return false
      }
      const workflowOmitted = payload.workflowOmitted === true
      const opType = canvasMutationOpType(payload)
      const changedResources = changedResourcesForEvent(payload)
      const canvasDocumentChanged = changedResources.some((resource: string) =>
        ["canvas_document", "canvas_documents"].includes(resource)
      )
      const documentReplaceChanged =
        opType === "document_replace" ||
        (CANVAS_DOCUMENT_REPLACE_ACTIONS.has(action) &&
          (canvasDocumentChanged || eventHasCanvasMutationEnvelope(payload)))
      if (documentReplaceChanged) return true
      if (shouldUseCanvasChanges(payload)) return false
      if (CANVAS_LOCAL_PROJECT_CHANGED_ACTIONS.has(action)) return false
      if (
        mutationApplied &&
        (eventHasCanvasMutationEnvelope(payload) ||
          eventCarriesCanvasSnapshot(payload))
      ) {
        return false
      }
      if (mutationApplied && !workflowOmitted) return false
      if (action === "workflow_node_inline_saved" && !workflowOmitted)
        return false
      if (action === "node_edit_history_restored" && !workflowOmitted)
        return false
      if (action === "node_edit_history_deleted" && !workflowOmitted)
        return false
      const workflowResourceChanged = changedResources.some(
        (resource: string) => ["workflow"].includes(resource)
      )
      if (
        workflowResourceChanged &&
        (workflowOmitted || eventHasCanvasMutationEnvelope(payload))
      ) {
        return false
      }
      if (isLocalTaskCanvasUpdate(payload) && !workflowOmitted) return false
      return workflowResourceChanged
    }
    const shouldSyncCanvasChanges = (payload: any) => {
      return shouldUseCanvasChanges(payload)
    }
    const notifyTaskResult = (
      eventName: "task_completed" | "task_failed",
      payload: any
    ) => {
      if (!payload || eventProjectId(payload) !== projectId) return
      if (payload.episodeId && payload.episodeId !== episodeId) return
      const taskType = String(payload.type ?? "")
      if (
        ![
          "video_prompt",
          "storyboard_image",
          "storyboard_image_edit",
          "storyboard_plan",
          "workflow_cinematic_script",
          "visual_handoff_image",
          "storyboard_video",
          "route_video",
        ].includes(taskType)
      ) {
        return
      }
      if (String(payload.status ?? "") === "cancelled") return
      const isVideoTask =
        taskType === "storyboard_video" || taskType === "route_video"
      const isDirectorPlanTask = taskType === "storyboard_plan"
      const isCinematicScriptTask = taskType === "workflow_cinematic_script"
      const isVisualHandoffTask = taskType === "visual_handoff_image"
      const isImageEditTask = taskType === "storyboard_image_edit"
      const payloadResult =
        payload.result &&
        typeof payload.result === "object" &&
        !Array.isArray(payload.result)
          ? payload.result
          : undefined
      const isCanvasImageEditTask =
        isImageEditTask &&
        String(
          payload.imageEditKind ??
            payload.image_edit_kind ??
            payloadResult?.imageEditKind ??
            payloadResult?.image_edit_kind ??
            ""
        ) === "canvas_image"
      if (eventName === "task_completed") {
        toast.success(
          workflowTaskSuccessText(payload as TaskRow, payloadResult)
        )
        return
      } else {
        const failureTitle =
          taskType === "video_prompt"
            ? payload.promptOperation === "optimize"
              ? "视频提示词优化失败"
              : "视频提示词生成失败"
            : isVideoTask
              ? "视频生成失败"
              : isDirectorPlanTask
                ? "分镜脚本生成失败"
                : isCinematicScriptTask
                  ? "影视化剧本生成失败"
                  : isVisualHandoffTask
                    ? "视觉交接图生成失败"
                    : isImageEditTask
                      ? isCanvasImageEditTask
                        ? "编辑图片失败"
                        : "分镜图修改失败"
                      : "分镜图生成失败"
        toast.error(failureTitle)
      }
    }
    const refresh = (
      payload: any,
      eventName?: "task_completed" | "task_failed"
    ) => {
      if (canvasDocument.scope !== requestScope) return
      if (isCurrentEpisodeEvent(payload)) documentSync.notifyProductionStatusWarning(payload)
      if (
        payload?.type === "video_prompt" &&
        payload.promptOperation === "optimize"
      ) {
        taskLifecycle.mergeEvent(payload)
        if (eventName) notifyTaskResult(eventName, payload)
        void documentSync.sync(payload)
        return
      }
      if (
        isCurrentEpisodeEvent(payload) &&
        isStaleCanvasMutationRevision(payload)
      ) {
        canvasDocument.markTransactions(canvasMutationTxMarkers(payload))
        return
      }
      if (isCurrentEpisodeEvent(payload) && sourceTextChanged(payload)) {
        canvasDetails.invalidateSourceText()
      }
      const mutationApplied = documentSync.applyMutation(payload)
      hydrateOpenStoryboardScriptEditor(payload, eventName, mutationApplied)
      const task = taskLifecycle.mergeEvent(payload)
      if (task) {
        applyWorkflowTaskResultToCanvas(task)
        hydrateWorkflowTaskResultCardsIfNeeded(task)
        if (eventName === "task_completed") {
          const videoDurationSyncWarning =
            workflowVideoDurationSyncWarningMessage(recordValue(task.result))
          if (videoDurationSyncWarning) {
            toast.warning(`视频生成时长同步失败：${videoDurationSyncWarning}`)
          }
        }
      } else if (
        eventProjectId(payload) === projectId &&
        (!payload.episodeId || payload.episodeId === episodeId) &&
        isLocalTaskCanvasUpdate(payload)
      ) {
        void taskLifecycle.refresh()
      }
      if (eventName) notifyTaskResult(eventName, payload)
      if (shouldRefresh(payload, mutationApplied)) {
        void documentSync.reconcile("project_changed_snapshot_reconcile")
      } else if (!mutationApplied && shouldSyncCanvasChanges(payload)) {
        void documentSync.sync(payload)
      }
    }
    const disposers = [
      onBackendEvent("task_created", refresh),
      onBackendEvent("task_progress", refresh),
      onBackendEvent("task_completed", (payload: any) =>
        refresh(payload, "task_completed")
      ),
      onBackendEvent("task_failed", (payload: any) =>
        refresh(payload, "task_failed")
      ),
      onBackendEvent("task_cancelled", refresh),
      onBackendEvent("project_changed", (payload: any) => {
        invalidateProjectAssetRowsForEvent(payload)
        if (
          unboundCanvasAssetImageIds(
            canvasDocument.read().nodes,
            projectId,
            (node) => workflowNodeDataHasEditableOriginalImage(node.data),
            payload
          ).length
        ) {
          documentSync.refreshReferences()
        }
        refresh(payload)
      }),
    ]
    return () => disposers.forEach((dispose) => dispose())
  }, [
    documentSync.sync,
    documentSync.applyMutation,
    applyWorkflowTaskResultToCanvas,
    backendReady,
    episodeId,
    hydrateOpenStoryboardScriptEditor,
    hydrateWorkflowTaskResultCardsIfNeeded,
    canvasDetails.invalidateSourceText,
    isStaleCanvasMutationRevision,
    canvasDocument.markTransactions,
    taskLifecycle.mergeEvent,
    onBackendEvent,
    projectId,
    documentSync.reconcile,
    documentSync.notifyProductionStatusWarning,
    taskLifecycle.refresh,
  ])
  return { acceptTask: applyWorkflowTaskResultToCanvas }
}
