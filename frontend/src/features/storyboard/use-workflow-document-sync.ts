import { isWorkflowVideoTaskType } from "./workflow-video-task-types"
import { useWorkflowDocumentMutations } from "./use-workflow-document-mutations"
import type { WorkflowNodeActions } from "./workflow-canvas-model"
import type { ModelCapabilitiesSnapshot } from "@/backend"

import { useCallback, useEffect, useRef } from "react"
import {
  CANVAS_INCREMENTAL_OP_TYPES,
  storyboardBackendEdgeId,
  workflowNodeDataHasEditableOriginalImage,
} from "./workflow-canvas-asset-model"
import {
  initialEpisodeWorkflow,
  toStoryboardEdges,
  toStoryboardNodes,
  type WorkflowNodeData,
} from "./workflow-canvas-model"
import {
  canvasMutationEnvelopeSources,
  canvasPlainObject,
} from "./workflow-canvas-mutation-model"
import { workflowWithEpisodeSourceText } from "./workflow-prompt-node-model"
import { withBackendReadTimeout } from "./workflow-task-status"
import { toast } from "sonner"
import {
  getCanvasChanges,
  getCanvasRecords,
  getCanvasReferenceViews,
  getCanvasSnapshot,
  listModelCapabilities,
  listWorkflowTasks,
  resolveCanvasAssetImages,
  workflowFromCanvasSnapshot,
  type CanvasAssetImagesResult,
  type EpisodeWorkflow,
  type StoryboardVersion,
  type TaskRow,
  type WorkflowEdge,
  type WorkflowNode,
  type WorkflowRoute,
  type WorkflowWorkChain,
} from "@/backend"
import { errMsg } from "@/shared/backend-result"
import {
  createCanvasReferenceViewReader,
  unboundCanvasAssetImageIds,
} from "./canvas-reference-views"
import { preservePendingWorkChains } from "./work-chain-draft"
import {
  workflowExtras,
  workflowDocumentExtrasPatch,
  canvasVersionRefKey,
  canvasVersionRefsFromKeys,
  canvasVersionRefFromValue,
  addCanvasVersionRef,
  addCanvasVersionRefs,
  clearRemovedCanvasVersionRefs,
  canvasMutationTargetsEpisode,
  canvasDocumentExtrasCandidates,
} from "./workflow-document-model"
import type { WorkflowCanvasDocument } from "./workflow-canvas-document"
import type { WorkflowCanvasDetails } from "./use-workflow-canvas-details"
import type { WorkflowTaskLifecycle } from "./use-workflow-task-lifecycle"
import type { BackendCaller } from "@/backend"

export function useWorkflowDocumentSync({
  canvasDocument,
  projectId,
  episodeId,
  backendReady,
  callBackend,
  onBackendEvent,
  workflowNodeActions,
  canvasDetails,
  taskLifecycle,
  onHistoryMutation,
  cacheCapabilities,
}: {
  canvasDocument: WorkflowCanvasDocument
  projectId: string
  episodeId: string
  backendReady: boolean
  callBackend: BackendCaller
  onBackendEvent: (eventName: string, callback: (payload: unknown) => void) => () => void
  workflowNodeActions: WorkflowNodeActions
  canvasDetails: WorkflowCanvasDetails
  taskLifecycle: WorkflowTaskLifecycle
  onHistoryMutation: (payload: unknown) => boolean
  cacheCapabilities: (snapshot: ModelCapabilitiesSnapshot | null) => void
}) {
  const canvasScopeKey = `${projectId}\u0000${episodeId}`
  const { nodes, loadedCanvasScopeKey, workflowVersion } = canvasDocument.read()
  const capabilitiesRequestSequenceRef = useRef(0)
  const canvasSnapshotRequestRef = useRef<{ scope: WorkflowCanvasDocument["scope"]; hadLoadedCanvas: boolean } | null>(null)
  const deferredCanvasSyncRef = useRef<WorkflowCanvasDocument["scope"] | null>(null)
  const deferredStatusRefreshRef = useRef<WorkflowCanvasDocument["scope"] | null>(null)
  const productionRefreshTriggerRef = useRef<(() => void) | null>(null)
  const productionRefreshInFlightRef = useRef<{ scope: WorkflowCanvasDocument["scope"]; pending: boolean } | null>(null)
  const latestCapabilitiesRef = useRef<{ scope: WorkflowCanvasDocument["scope"]; snapshot: ModelCapabilitiesSnapshot | null } | null>(null)
  useEffect(() => {
    if (!backendReady) return
    let cancelled = false
    const unsubscribe = onBackendEvent("model_config_changed", () => {
      if (canvasDocument.scope.key !== canvasScopeKey) return
      const requestScope = canvasDocument.scope
      const requestSequence = ++capabilitiesRequestSequenceRef.current
      void listModelCapabilities(callBackend, projectId, episodeId)
        .then((snapshot) => {
          if (cancelled || canvasDocument.scope !== requestScope || capabilitiesRequestSequenceRef.current !== requestSequence) return
          latestCapabilitiesRef.current = { scope: requestScope, snapshot }
          cacheCapabilities(snapshot)
          canvasDocument.updateNodes((current) => current.map((node) => ({
            ...node,
            data: { ...node.data, modelCapabilitiesSnapshot: snapshot },
          })))
          productionRefreshTriggerRef.current?.()
        })
        .catch(() => undefined)
    })
    return () => { cancelled = true; unsubscribe() }
  }, [backendReady, callBackend, cacheCapabilities, canvasDocument, canvasScopeKey, episodeId, onBackendEvent, projectId])
  const referenceViewReaderRef = useRef<ReturnType<
    typeof createCanvasReferenceViewReader
  > | null>(null)

  const applyResolvedAssetImagesRef = useRef<
    ((result: CanvasAssetImagesResult) => void) | null
  >(null)

  const referenceViewNodes = nodes.filter(
    (node) =>
      (["director.board", "storyboard.card"].includes(node.data.eyebrow) || isWorkflowVideoTaskType(node.data.eyebrow)) &&
      !node.data.creationPending
  )

  const referenceViewTargets = referenceViewNodes
    .map((node) => node.id)
    .sort()
    .join("\u0000")

  const missingReferenceViews = referenceViewNodes.some(
    (node) => !Array.isArray(node.data.assetThumbnails)
  )

  useEffect(() => {
    if (!backendReady || loadedCanvasScopeKey !== canvasScopeKey) return
    const requestScope = canvasDocument.scope
    const reader = createCanvasReferenceViewReader(
      async () => {
        if (canvasDocument.scope !== requestScope) throw new Error("画布已切换")
        const nodeIds = unboundCanvasAssetImageIds(
          canvasDocument.read().nodes,
          projectId,
          (node) => workflowNodeDataHasEditableOriginalImage(node.data)
        )
        if (nodeIds.length) {
          const result = await resolveCanvasAssetImages(
            callBackend,
            projectId,
            episodeId,
            nodeIds
          )
          if (canvasDocument.scope !== requestScope)
            throw new Error("画布已切换")
          applyResolvedAssetImagesRef.current?.(result)
        }
        return getCanvasReferenceViews(callBackend, projectId, episodeId)
      },
      ({ views }) => {
        if (canvasDocument.scope !== requestScope) return
        const byId = new Map(views.map((view) => [view.nodeId, view]))
        canvasDocument.updateNodes((current) =>
          current.map((node) => {
            const view = byId.get(node.id)
            if (!view) return node
            const data = { ...node.data, ...view.data }
            return { ...node, data: data as WorkflowNodeData }
          })
        )
      },
      (error) => {
        if (canvasDocument.scope !== requestScope) return
        toast.warning(errMsg(error, "读取资产图片失败"), {
          action: {
            label: "重试",
            onClick: () =>
              reader.refresh(canvasDocument.read().workflowVersion, true),
          },
        })
      }
    )
    referenceViewReaderRef.current = reader
    reader.refresh(canvasDocument.read().workflowVersion, true)
    return () => {
      reader.dispose()
      if (referenceViewReaderRef.current === reader)
        referenceViewReaderRef.current = null
    }
  }, [
    backendReady,
    loadedCanvasScopeKey,
    canvasScopeKey,
    projectId,
    episodeId,
    callBackend,
    canvasDocument.updateNodes,
  ])

  useEffect(() => {
    referenceViewReaderRef.current?.refresh(
      workflowVersion,
      missingReferenceViews ? "missing" : false
    )
  }, [workflowVersion, referenceViewTargets, missingReferenceViews])

  const canvasChangesInFlightRef = useRef<{
    scope: { key: string }
    promise: Promise<void>
  } | null>(null)

  const canvasChangesPendingRef = useRef(false)

  const canvasChangesBackfillRef = useRef<((payload?: any) => void) | null>(
    null
  )

  const scheduleCanvasChangesBackfill = useCallback((payload?: any) => {
    window.setTimeout(() => {
      canvasChangesBackfillRef.current?.(payload)
    }, 0)
  }, [])

  const loadWorkflowInFlightRef = useRef<Promise<void> | null>(null)

  const loadWorkflowPendingRef = useRef<{ preserveSelection: boolean } | null>(
    null
  )

  const {
    replace: applyReturnedWorkflow,
    applyMutation: applyWorkflowMutationEventToCanvas,
  } = useWorkflowDocumentMutations({
    canvasDocument,
    projectId,
    episodeId,
    workflowNodeActions,
    canvasDetails,
    taskLifecycle,
    onHistoryMutation,
  })
  const notifyProductionStatusWarning = useCallback((payload: any) => {
    if (!payload?.productionStatusRefreshFailed) return false
    const requestScope = canvasDocument.scope
    const id = `production-status-refresh:${projectId}:${episodeId}`
    const showWarning = () => toast.warning(
      payload.productionStatusWarning || payload.message || "内容已保存，工作链状态同步失败",
      { id, action: { label: "重试同步", onClick: () => { void retry() } } }
    )
    const retry = async () => {
      if (canvasDocument.scope !== requestScope) return
      try {
        const result = await callBackend<any>("update_episode_production_status", { projectId, episodeId })
        if (canvasDocument.scope !== requestScope) return
        if (!result?.success) throw new Error("状态同步失败")
        const event = { ...result, projectId, episodeId, action: "episode_production_status_updated" }
        if (!applyWorkflowMutationEventToCanvas(event)) scheduleCanvasChangesBackfill(event)
        toast.success("工作链状态已同步", { id })
      } catch {
        if (canvasDocument.scope === requestScope) showWarning()
      }
    }
    showWarning()
    return true
  }, [callBackend, canvasDocument, projectId, episodeId, applyWorkflowMutationEventToCanvas, scheduleCanvasChangesBackfill])
  const refreshProductionStatus = useCallback(() => {
    if (!backendReady || canvasDocument.scope.key !== canvasScopeKey) return
    const requestScope = canvasDocument.scope
    if (canvasDocument.read().snapshotLoading || canvasDocument.read().loadedCanvasScopeKey !== canvasScopeKey) {
      deferredStatusRefreshRef.current = requestScope
      return
    }
    const active = productionRefreshInFlightRef.current
    if (active?.scope === requestScope) {
      active.pending = true
      return
    }
    const refresh = { scope: requestScope, pending: false }
    productionRefreshInFlightRef.current = refresh
    void (async () => {
      try {
        do {
          refresh.pending = false
          const result = await callBackend<any>("update_episode_production_status", { projectId, episodeId })
          if (canvasDocument.scope !== requestScope) return
          if (!result?.success) throw new Error("工作链状态同步失败")
          const event = { ...result, projectId, episodeId, action: "episode_production_status_updated" }
          if (!applyWorkflowMutationEventToCanvas(event)) scheduleCanvasChangesBackfill(event)
        } while (refresh.pending && canvasDocument.scope === requestScope)
      } catch (error) {
        if (canvasDocument.scope === requestScope) notifyProductionStatusWarning({
          productionStatusRefreshFailed: true,
          productionStatusWarning: errMsg(error, "工作链状态同步失败"),
        })
      } finally {
        if (productionRefreshInFlightRef.current === refresh) productionRefreshInFlightRef.current = null
      }
    })()
  }, [backendReady, callBackend, canvasDocument, canvasScopeKey, projectId, episodeId, applyWorkflowMutationEventToCanvas, scheduleCanvasChangesBackfill, notifyProductionStatusWarning])
  productionRefreshTriggerRef.current = refreshProductionStatus
  const completeCanvasSnapshot = useCallback((request: { scope: WorkflowCanvasDocument["scope"] }, refreshStatus = false) => {
    const isCurrent = () => canvasDocument.scope === request.scope && canvasSnapshotRequestRef.current === request
    if (!isCurrent()) return
    // The ledger must describe the installed baseline, not changes deferred
    // while it was loading. Replay those changes before acknowledging them.
    canvasDocument.transaction(() => {
      canvasDocument.clearTransactions()
      canvasDocument.markLoaded(request.scope.key)
      canvasDocument.setSnapshotLoading(false)
      canvasDocument.setLoading(false)
    })
    if (deferredCanvasSyncRef.current === request.scope) {
      deferredCanvasSyncRef.current = null
      scheduleCanvasChangesBackfill()
    }
    if (refreshStatus || deferredStatusRefreshRef.current === request.scope) {
      deferredStatusRefreshRef.current = null
      window.setTimeout(() => {
        if (isCurrent()) productionRefreshTriggerRef.current?.()
      }, 0)
    }
  }, [canvasDocument, scheduleCanvasChangesBackfill])
  const loadWorkflow = useCallback(
    async (options: { preserveSelection?: boolean } = {}) => {
      let preserveSelection = options.preserveSelection === true
      const activeLoad = loadWorkflowInFlightRef.current
      if (activeLoad) {
        const pending = loadWorkflowPendingRef.current as {
          preserveSelection: boolean
        } | null
        loadWorkflowPendingRef.current = {
          preserveSelection: Boolean(
            pending?.preserveSelection || preserveSelection
          ),
        }
        await activeLoad
        const nextPending = loadWorkflowPendingRef.current
        if (nextPending && loadWorkflowRef.current === loadWorkflow) {
          loadWorkflowPendingRef.current = null
          await loadWorkflowRef.current({
            preserveSelection: nextPending.preserveSelection,
          })
        } else if (loadWorkflowRef.current !== loadWorkflow) {
          await loadWorkflowRef.current(options)
        }
        return
      }

      const runLoadWorkflow = async (preserveCurrentSelection: boolean) => {
        const requestCanvasScopeKey = canvasScopeKey
        const requestScope = canvasDocument.scope
        if (requestScope.key !== requestCanvasScopeKey) return
        const previousRequest = canvasSnapshotRequestRef.current
        const hadLoadedCanvas = canvasDocument.read().loadedCanvasScopeKey === requestCanvasScopeKey ||
          (previousRequest?.scope === requestScope && previousRequest.hadLoadedCanvas)
        const request = { scope: requestScope, hadLoadedCanvas }
        canvasSnapshotRequestRef.current = request
        const isCurrentCanvasLoad = () => canvasDocument.scope === requestScope && canvasSnapshotRequestRef.current === request
        canvasDocument.setSnapshotLoading(true)
        canvasDetails.reset()
        if (!backendReady) {
          const workflow = initialEpisodeWorkflow(episodeId)
          cacheCapabilities(null)
          canvasDocument.updateNodes(
            toStoryboardNodes(workflow, workflowNodeActions)
          )
          canvasDocument.updateEdges(toStoryboardEdges(workflow))
          canvasDocument.updateRoutes(workflow.routes ?? [])
          canvasDocument.confirmRevision(workflow.version, { mode: "trusted" })
          canvasDocument.updateProductionState(workflow.state ?? null)
          canvasDocument.updateMetadata(workflowExtras(workflow))
          canvasDocument.selectNode((current) =>
            preserveCurrentSelection &&
            current &&
            workflow.nodes.some((node) => node.id === current)
              ? current
              : null
          )
          taskLifecycle.clear()
          completeCanvasSnapshot(request)
          return
        }
        canvasDocument.setLoading(true)
        try {
          cacheCapabilities(null)
          latestCapabilitiesRef.current = null
          const capabilitiesRequestSequence = ++capabilitiesRequestSequenceRef.current
          const modelCapabilitiesPromise = withBackendReadTimeout(
            listModelCapabilities(callBackend, projectId, episodeId),
            "加载模型能力超时",
            8000
          ).catch(() => null)
          void modelCapabilitiesPromise
            .then((modelCapabilitiesSnapshot) => {
              // Model discovery belongs to this canvas, independently of graph reads.
              if (canvasDocument.scope !== requestScope || capabilitiesRequestSequenceRef.current !== capabilitiesRequestSequence) return
              latestCapabilitiesRef.current = { scope: requestScope, snapshot: modelCapabilitiesSnapshot }
              cacheCapabilities(modelCapabilitiesSnapshot)
              if (modelCapabilitiesSnapshot && canvasDocument.read().loadedCanvasScopeKey === requestScope.key) {
                canvasDocument.updateNodes((current) => current.map((node) => ({
                  ...node,
                  data: { ...node.data, modelCapabilitiesSnapshot },
                })))
              }
            })
            .catch(() => undefined)
          const snapshot = await withBackendReadTimeout(
            getCanvasSnapshot(callBackend, projectId, episodeId, {
              detail: "summary",
              includeVersions: false,
            }),
            "加载分集画布超时"
          )
          if (!isCurrentCanvasLoad()) return
          notifyProductionStatusWarning(snapshot)
          const rawWorkflow = workflowFromCanvasSnapshot(snapshot)
          const cachedSourceTextDetail =
            (rawWorkflow.state?.sourceReady &&
              canvasDetails.peekSourceText()) ||
            null
          const workflow = preservePendingWorkChains(
            cachedSourceTextDetail
              ? workflowWithEpisodeSourceText(
                  rawWorkflow,
                  cachedSourceTextDetail
                )
              : rawWorkflow,
            canvasDocument.pendingCreationDrafts()
          )
          canvasDocument.updateNodes(
            toStoryboardNodes(workflow, workflowNodeActions)
          )
          const latestCapabilities = latestCapabilitiesRef.current as {
            scope: WorkflowCanvasDocument["scope"]
            snapshot: ModelCapabilitiesSnapshot | null
          } | null
          if (latestCapabilities?.scope === requestScope && latestCapabilities.snapshot) {
            canvasDocument.updateNodes((current) => current.map((node) => ({
              ...node,
              data: { ...node.data, modelCapabilitiesSnapshot: latestCapabilities.snapshot },
            })))
          }
          canvasDocument.updateEdges(toStoryboardEdges(workflow))
          canvasDocument.updateRoutes(workflow.routes ?? [])
          canvasDocument.confirmRevision(workflow.version, { mode: "trusted" })
          canvasDocument.updateProductionState(workflow.state ?? null)
          canvasDocument.updateMetadata(workflowExtras(workflow))
          completeCanvasSnapshot(request, snapshot.productionStatusNeedsRefresh)
          if (rawWorkflow.state?.sourceReady && !cachedSourceTextDetail) {
            void canvasDetails
              .readSourceText()
              .then((sourceTextDetail) => {
                if (!sourceTextDetail || !isCurrentCanvasLoad()) return
                canvasDetails.applySourceText(
                  sourceTextDetail,
                  requestCanvasScopeKey,
                  rawWorkflow.version
                )
              })
              .catch((error) => {
                console.warn("后台加载分集原文失败:", error)
              })
          }
          try {
            const requestTasks = taskLifecycle.snapshot()
            const taskResult = await withBackendReadTimeout(
              listWorkflowTasks(callBackend, projectId, episodeId, {
                lightweight: true,
              }),
              "加载工作流任务超时"
            )
            if (!isCurrentCanvasLoad()) return
            taskLifecycle.replaceSnapshot(taskResult.tasks, requestTasks)
          } catch (error) {
            console.warn("加载工作流任务状态失败:", error)
          }
          if (!isCurrentCanvasLoad()) return
          const nextWorkChains = workflow.workChains ?? []
          canvasDocument.selectWorkChain((current) =>
            current === "all" ||
            nextWorkChains.some((workChain) => workChain.id === current)
              ? current
              : "all"
          )
          canvasDocument.selectNode((current) =>
            preserveCurrentSelection &&
            current &&
            workflow.nodes.some((node) => node.id === current)
              ? current
              : null
          )
        } catch (error) {
          if (!isCurrentCanvasLoad()) return
          toast.error(errMsg(error, "加载分镜工作流失败"))
          if (
            canvasDocument.read().nodes.length > 0 &&
            hadLoadedCanvas
          ) {
            completeCanvasSnapshot(request)
            return
          }
          const workflow = initialEpisodeWorkflow(episodeId)
          cacheCapabilities(null)
          canvasDocument.updateNodes(
            toStoryboardNodes(workflow, workflowNodeActions)
          )
          canvasDocument.updateEdges(toStoryboardEdges(workflow))
          canvasDocument.updateRoutes(workflow.routes ?? [])
          canvasDocument.confirmRevision(workflow.version, { mode: "trusted" })
          canvasDocument.updateProductionState(workflow.state ?? null)
          canvasDocument.updateMetadata(workflowExtras(workflow))
          canvasDocument.selectNode((current) =>
            preserveCurrentSelection &&
            current &&
            workflow.nodes.some((node) => node.id === current)
              ? current
              : null
          )
          completeCanvasSnapshot(request)
        } finally {
          if (isCurrentCanvasLoad()) {
            canvasDocument.setLoading(false)
          }
        }
      }

      while (true) {
        loadWorkflowPendingRef.current = null
        const loadPromise = runLoadWorkflow(preserveSelection)
        loadWorkflowInFlightRef.current = loadPromise
        try {
          await loadPromise
        } finally {
          if (loadWorkflowInFlightRef.current === loadPromise) {
            loadWorkflowInFlightRef.current = null
          }
        }
        if (loadWorkflowRef.current !== loadWorkflow) break
        const pending = loadWorkflowPendingRef.current as unknown as {
          preserveSelection: boolean
        } | null
        if (!pending) break
        preserveSelection = pending.preserveSelection
      }
    },
    [
      backendReady,
      canvasDetails.applySourceText,
      callBackend,
      canvasScopeKey,
      episodeId,
      canvasDetails.peekSourceText,
      canvasDetails.readSourceText,
      canvasDocument.markLoaded,
      projectId,
      canvasDetails.reset,
      canvasDocument.updateEdges,
      canvasDocument.updateNodes,
      canvasDocument.confirmRevision,
      workflowNodeActions,
      notifyProductionStatusWarning,
      completeCanvasSnapshot,
    ]
  )

  const loadWorkflowRef = useRef(loadWorkflow)

  useEffect(() => {
    loadWorkflowRef.current = loadWorkflow
  }, [loadWorkflow])

  const reconcileCanvasSnapshot = useCallback(
    async (reason = "canvas_snapshot_reconcile") => {
      if (!backendReady) return false
      const requestScope = canvasDocument.scope
      if (requestScope.key !== canvasScopeKey) return false
      if (canvasDocument.read().snapshotLoading || canvasDocument.read().loadedCanvasScopeKey !== canvasScopeKey) {
        deferredCanvasSyncRef.current = requestScope
        return false
      }
      const requestCanvasScopeKey = canvasScopeKey
      const request = { scope: requestScope, hadLoadedCanvas: true }
      canvasSnapshotRequestRef.current = request
      const isCurrentCanvasScope = () =>
        canvasDocument.scope === requestScope &&
        canvasSnapshotRequestRef.current === request
      canvasDocument.setSnapshotLoading(true)
      const requestTasks = taskLifecycle.snapshot()
      try {
        const snapshot = await withBackendReadTimeout(
          getCanvasSnapshot(callBackend, projectId, episodeId, {
            detail: "summary",
            includeVersions: false,
            includeTasks: true,
            includeProjections: true,
          }),
          "同步画布快照超时",
          8000
        )
        if (!isCurrentCanvasScope()) return false
        const snapshotWorkflow = workflowFromCanvasSnapshot(snapshot)
        const cachedSourceTextDetail =
          (snapshotWorkflow.state?.sourceReady &&
            canvasDetails.peekSourceText()) ||
          null
        const workflow = cachedSourceTextDetail
          ? workflowWithEpisodeSourceText(
              snapshotWorkflow,
              cachedSourceTextDetail
            )
          : snapshotWorkflow
        const applied = applyReturnedWorkflow(workflow, {
          preserveSelection: true,
        })
        completeCanvasSnapshot(request, applied && snapshot.productionStatusNeedsRefresh)
        if (snapshotWorkflow.state?.sourceReady && !cachedSourceTextDetail) {
          void canvasDetails
            .readSourceText()
            .then((sourceTextDetail) => {
              if (!sourceTextDetail || !isCurrentCanvasScope()) return
              canvasDetails.applySourceText(
                sourceTextDetail,
                requestCanvasScopeKey,
                snapshotWorkflow.version
              )
            })
            .catch((error) => {
              console.warn("后台同步分集原文失败:", reason, error)
            })
        }
        const snapshotTasks = Array.isArray(snapshot.records?.tasks)
          ? (snapshot.records.tasks as TaskRow[])
          : null
        if (snapshotTasks) {
          taskLifecycle.replaceSnapshot(snapshotTasks, requestTasks)
        } else if (applied) {
          void taskLifecycle.refresh({ immediate: true })
        }
        return applied
      } catch (error) {
        console.warn("同步画布快照失败:", reason, error)
        return false
      } finally {
        if (isCurrentCanvasScope() && canvasDocument.read().snapshotLoading) {
          completeCanvasSnapshot(request)
        }
      }
    },
    [
      canvasDetails.applySourceText,
      applyReturnedWorkflow,
      backendReady,
      callBackend,
      canvasScopeKey,
      completeCanvasSnapshot,
      episodeId,
      canvasDetails.peekSourceText,
      canvasDetails.readSourceText,
      projectId,
      taskLifecycle.refresh,
      taskLifecycle.replaceSnapshot,
      taskLifecycle.upsertRecords,
      taskLifecycle.removeRecords,
    ]
  )

  const applyCanvasChangesFromBackend = useCallback(
    async (payload?: any) => {
      if (!backendReady) return
      const requestScope = canvasDocument.scope
      const currentScope = () => canvasDocument.scope === requestScope
      if (requestScope.key !== canvasScopeKey) return
      if (
        payload &&
        !canvasMutationTargetsEpisode(payload, projectId, episodeId)
      ) {
        return
      }

      if (canvasDocument.read().snapshotLoading || canvasDocument.read().loadedCanvasScopeKey !== canvasScopeKey) {
        deferredCanvasSyncRef.current = requestScope
        return
      }

      const activeSync = canvasChangesInFlightRef.current
      if (activeSync?.scope === requestScope) {
        canvasChangesPendingRef.current = true
        await activeSync.promise
        return
      }

      const runOnce = async () => {
        if (!currentScope()) return
        const requestSnapshot = canvasSnapshotRequestRef.current
        const retryAfterSnapshot = () => {
          if (!currentScope()) return
          if (!canvasDocument.read().snapshotLoading && canvasDocument.read().loadedCanvasScopeKey === canvasScopeKey) {
            canvasChangesPendingRef.current = true
          } else {
            deferredCanvasSyncRef.current = requestScope
          }
        }
        const canApplyChanges = () => {
          if (!currentScope()) return false
          if (canvasSnapshotRequestRef.current !== requestSnapshot || canvasDocument.read().snapshotLoading ||
            canvasDocument.read().loadedCanvasScopeKey !== canvasScopeKey) {
            retryAfterSnapshot()
            return false
          }
          return true
        }
        if (!canApplyChanges()) return
        const sinceRevision = canvasDocument.read().workflowVersion
        const result = await withBackendReadTimeout(
          getCanvasChanges(callBackend, projectId, episodeId, sinceRevision),
          "同步画布变更超时",
          8000
        )
        if (!canApplyChanges()) return
        const changes = Array.isArray(result.changes) ? result.changes : []
        if (result.snapshotRequired === true) {
          await reconcileCanvasSnapshot("canvas_changes_snapshot_required")
          return
        }
        if (result.currentRevision < canvasDocument.read().workflowVersion)
          return
        const freshChanges = changes.filter(
          (change) => !canvasDocument.hasTransaction(change)
        )
        if (!freshChanges.length) {
          if (result.currentRevision > sinceRevision) {
            applyWorkflowMutationEventToCanvas({
              action: "canvas_changes_applied",
              projectId: projectId,
              episodeId,
              workflowVersion: result.currentRevision,
            })
          }
          return
        }

        const shouldReloadWorkflow = freshChanges.some(
          (change) =>
            !CANVAS_INCREMENTAL_OP_TYPES.has(String(change.opType ?? ""))
        )
        if (shouldReloadWorkflow) {
          const reconciliation = reconcileCanvasSnapshot("canvas_changes_unknown_op")
          const fallbackRequest = canvasSnapshotRequestRef.current
          await reconciliation
          if (canvasSnapshotRequestRef.current !== fallbackRequest) retryAfterSnapshot()
          return
        }

        const documentExtrasPatch: Partial<EpisodeWorkflow> = {}
        let documentExtrasChanged = false
        const collectDocumentExtras = (value: unknown) => {
          const patch = workflowDocumentExtrasPatch(value)
          if (!patch) return
          Object.assign(documentExtrasPatch, patch)
          documentExtrasChanged = true
        }
        freshChanges.forEach((change) => {
          const changePayload = canvasPlainObject(change.payload)
          if (!changePayload) return
          canvasDocumentExtrasCandidates(changePayload).forEach(
            collectDocumentExtras
          )
          collectDocumentExtras(changePayload.document)
        })
        const recordIds = {
          nodeIds: new Set<string>(),
          edgeIds: new Set<string>(),
          routeIds: new Set<string>(),
          workChainIds: new Set<string>(),
          versionRefs: new Set<string>(),
          taskIds: new Set<string>(),
          projectionKeys: new Set<string>(),
        }
        const removedRecordIds = {
          nodeIds: new Set<string>(),
          edgeIds: new Set<string>(),
          routeIds: new Set<string>(),
          workChainIds: new Set<string>(),
          versionRefs: new Set<string>(),
          taskIds: new Set<string>(),
          projectionKeys: new Set<string>(),
        }
        const addRecordId = (target: Set<string>, value: unknown) => {
          const text = String(value ?? "").trim()
          if (text) target.add(text)
        }
        const addRecordIds = (target: Set<string>, values: unknown) => {
          if (!Array.isArray(values)) return
          values.forEach((value) => addRecordId(target, value))
        }
        const addMutationRecordRefs = (records: unknown) => {
          if (!records || typeof records !== "object" || Array.isArray(records))
            return
          const row = records as Record<string, unknown>
          const typeTargets: Record<string, Set<string>> = {
            canvas_node: recordIds.nodeIds,
            canvas_edge: recordIds.edgeIds,
            canvas_route: recordIds.routeIds,
            canvas_work_chain: recordIds.workChainIds,
            canvas_task: recordIds.taskIds,
            canvas_projection: recordIds.projectionKeys,
          }
          const removedTypeTargets: Record<string, Set<string>> = {
            canvas_node: removedRecordIds.nodeIds,
            canvas_edge: removedRecordIds.edgeIds,
            canvas_route: removedRecordIds.routeIds,
            canvas_work_chain: removedRecordIds.workChainIds,
            canvas_task: removedRecordIds.taskIds,
            canvas_projection: removedRecordIds.projectionKeys,
          }
          ;["added", "updated"].forEach((bucketName) => {
            const bucket = row[bucketName]
            if (!Array.isArray(bucket)) return
            bucket.forEach((record) => {
              if (
                !record ||
                typeof record !== "object" ||
                Array.isArray(record)
              )
                return
              const recordRow = record as Record<string, unknown>
              const recordType = String(recordRow.type ?? "").trim()
              if (recordType === "canvas_version") {
                addCanvasVersionRef(recordIds.versionRefs, recordRow)
                return
              }
              const target = typeTargets[recordType]
              if (target) addRecordId(target, recordRow.id)
            })
          })
          const removedBucket = row.removed
          if (Array.isArray(removedBucket)) {
            removedBucket.forEach((record) => {
              if (
                !record ||
                typeof record !== "object" ||
                Array.isArray(record)
              )
                return
              const recordRow = record as Record<string, unknown>
              const recordType = String(recordRow.type ?? "").trim()
              if (recordType === "canvas_version") {
                addCanvasVersionRef(removedRecordIds.versionRefs, recordRow)
                return
              }
              const target = removedTypeTargets[recordType]
              if (target) addRecordId(target, recordRow.id)
            })
          }
        }
        const addPayloadRecordIds = (source: Record<string, unknown>) => {
          addRecordIds(recordIds.nodeIds, source.nodeIds)
          addRecordIds(recordIds.edgeIds, source.edgeIds)
          addRecordIds(recordIds.routeIds, source.routeIds)
          addRecordIds(recordIds.workChainIds, source.workChainIds)
          addCanvasVersionRefs(recordIds.versionRefs, source.versionRefs)
          addRecordIds(recordIds.taskIds, source.taskIds)
          addRecordIds(recordIds.projectionKeys, source.projectionKeys)
          addRecordIds(removedRecordIds.nodeIds, source.removedNodeIds)
          addRecordIds(removedRecordIds.edgeIds, source.removedEdgeIds)
          addRecordIds(removedRecordIds.routeIds, source.removedRouteIds)
          addRecordIds(
            removedRecordIds.workChainIds,
            source.removedWorkChainIds
          )
          addCanvasVersionRefs(
            removedRecordIds.versionRefs,
            source.removedVersionRefs
          )
          addRecordIds(removedRecordIds.taskIds, source.removedTaskIds)
          addRecordIds(
            removedRecordIds.projectionKeys,
            source.removedProjectionKeys
          )
        }
        freshChanges.forEach((change) => {
          addMutationRecordRefs(change.records)
          const changePayload = canvasPlainObject(change.payload)
          if (!changePayload) return
          canvasMutationEnvelopeSources(changePayload).forEach((source) => {
            addPayloadRecordIds(source)
            addMutationRecordRefs(source.records)
          })
        })
        const embeddedRecords: Record<string, unknown> =
          result.records &&
          typeof result.records === "object" &&
          !Array.isArray(result.records)
            ? result.records
            : {}
        const embeddedNodes = [
          ...(Array.isArray(embeddedRecords.nodes)
            ? embeddedRecords.nodes
            : []),
          ...(Array.isArray(result.nodes) ? result.nodes : []),
        ].filter(
          (node): node is WorkflowNode =>
            Boolean(node) &&
            typeof node === "object" &&
            typeof node.id === "string" &&
            typeof node.type === "string"
        )
        const embeddedEdges = (
          Array.isArray(embeddedRecords.edges) ? embeddedRecords.edges : []
        ).filter(
          (edge): edge is WorkflowEdge =>
            Boolean(edge) &&
            typeof edge === "object" &&
            typeof edge.source === "string" &&
            typeof edge.target === "string"
        )
        const embeddedRoutes = (
          Array.isArray(embeddedRecords.routes) ? embeddedRecords.routes : []
        ).filter(
          (route): route is WorkflowRoute =>
            Boolean(route) &&
            typeof route === "object" &&
            typeof route.id === "string"
        )
        const embeddedWorkChains = (
          Array.isArray(embeddedRecords.workChains)
            ? embeddedRecords.workChains
            : []
        ).filter(
          (workChain): workChain is WorkflowWorkChain =>
            Boolean(workChain) &&
            typeof workChain === "object" &&
            typeof workChain.id === "string"
        )
        const embeddedTasks = (
          Array.isArray(embeddedRecords.tasks) ? embeddedRecords.tasks : []
        ).filter(
          (task): task is TaskRow =>
            Boolean(task) &&
            typeof task === "object" &&
            !Array.isArray(task) &&
            Boolean(String((task as Record<string, unknown>).id ?? "").trim())
        )
        const embeddedVersions = (
          Array.isArray(embeddedRecords.versions)
            ? embeddedRecords.versions
            : []
        ).filter(
          (version): version is StoryboardVersion =>
            Boolean(version) &&
            typeof version === "object" &&
            !Array.isArray(version) &&
            Boolean(
              String((version as Record<string, unknown>).id ?? "").trim()
            )
        )
        const embeddedProjections = (
          Array.isArray(embeddedRecords.projections)
            ? embeddedRecords.projections
            : []
        ).filter(
          (projection): projection is Record<string, unknown> =>
            Boolean(projection) &&
            typeof projection === "object" &&
            !Array.isArray(projection)
        )
        const embeddedNodeIds = new Set(embeddedNodes.map((node) => node.id))
        const embeddedEdgeIds = new Set(
          embeddedEdges.map((edge) => edge.id).filter(Boolean)
        )
        const embeddedRouteIds = new Set(
          embeddedRoutes.map((route) => route.id)
        )
        const embeddedWorkChainIds = new Set(
          embeddedWorkChains.map((workChain) => workChain.id)
        )
        const embeddedTaskIds = new Set(
          embeddedTasks
            .map((task) => String(task.id ?? "").trim())
            .filter(Boolean)
        )
        const embeddedVersionRefs = new Set(
          embeddedVersions
            .map((version) => {
              const ref = canvasVersionRefFromValue(version)
              return ref ? canvasVersionRefKey(ref) : ""
            })
            .filter(Boolean)
        )
        const embeddedProjectionKeys = new Set(
          embeddedProjections
            .map((projection) =>
              String(projection.key ?? projection.id ?? "").trim()
            )
            .filter(Boolean)
        )
        const missingNodeIds = [...recordIds.nodeIds].filter(
          (nodeId) => !embeddedNodeIds.has(nodeId)
        )
        const missingEdgeIds = [...recordIds.edgeIds].filter(
          (edgeId) => !embeddedEdgeIds.has(edgeId)
        )
        const missingRouteIds = [...recordIds.routeIds].filter(
          (routeId) => !embeddedRouteIds.has(routeId)
        )
        const missingWorkChainIds = [...recordIds.workChainIds].filter(
          (workChainId) => !embeddedWorkChainIds.has(workChainId)
        )
        const missingTaskIds = [...recordIds.taskIds].filter(
          (taskId) => !embeddedTaskIds.has(taskId)
        )
        const missingVersionRefKeys = [...recordIds.versionRefs].filter(
          (versionRef) => !embeddedVersionRefs.has(versionRef)
        )
        const missingVersionRefs = canvasVersionRefsFromKeys(
          missingVersionRefKeys
        )
        const missingProjectionKeys = [...recordIds.projectionKeys].filter(
          (projectionKey) => !embeddedProjectionKeys.has(projectionKey)
        )
        const hasConcreteRecords =
          embeddedNodes.length ||
          embeddedEdges.length ||
          embeddedRoutes.length ||
          embeddedWorkChains.length ||
          embeddedVersions.length ||
          embeddedTasks.length ||
          embeddedProjections.length
        const hasReferencedRecords =
          recordIds.nodeIds.size ||
          recordIds.edgeIds.size ||
          recordIds.routeIds.size ||
          recordIds.workChainIds.size ||
          recordIds.versionRefs.size ||
          recordIds.taskIds.size ||
          recordIds.projectionKeys.size
        const hasRemovedRecords =
          removedRecordIds.nodeIds.size ||
          removedRecordIds.edgeIds.size ||
          removedRecordIds.routeIds.size ||
          removedRecordIds.workChainIds.size ||
          removedRecordIds.versionRefs.size ||
          removedRecordIds.taskIds.size ||
          removedRecordIds.projectionKeys.size
        if (
          !hasReferencedRecords &&
          !hasConcreteRecords &&
          !hasRemovedRecords
        ) {
          applyWorkflowMutationEventToCanvas({
            action: "canvas_changes_applied",
            projectId: projectId,
            episodeId,
            workflowVersion: result.currentRevision,
            documentExtras: documentExtrasChanged
              ? documentExtrasPatch
              : undefined,
          })
          canvasDocument.markTransactions(freshChanges)
          return
        }

        const missingRecordResult =
          missingNodeIds.length ||
          missingEdgeIds.length ||
          missingRouteIds.length ||
          missingWorkChainIds.length ||
          missingVersionRefs.length ||
          missingTaskIds.length ||
          missingProjectionKeys.length
            ? await withBackendReadTimeout(
                getCanvasRecords(callBackend, projectId, episodeId, {
                  detail: "full",
                  ids: {
                    nodeIds: missingNodeIds,
                    edgeIds: missingEdgeIds,
                    routeIds: missingRouteIds,
                    workChainIds: missingWorkChainIds,
                    versionRefs: missingVersionRefs,
                    taskIds: missingTaskIds,
                    projectionKeys: missingProjectionKeys,
                  },
                }),
                "加载画布变更记录超时",
                8000
              )
            : null
        if (
          !canApplyChanges() ||
          result.currentRevision < canvasDocument.read().workflowVersion
        )
          return
        const missingRecords: Record<string, unknown> =
          missingRecordResult?.records &&
          typeof missingRecordResult.records === "object" &&
          !Array.isArray(missingRecordResult.records)
            ? missingRecordResult.records
            : {}
        const backendNodes = [
          ...embeddedNodes,
          ...(Array.isArray(missingRecords.nodes) ? missingRecords.nodes : []),
        ]
        const backendEdges = [
          ...embeddedEdges,
          ...(Array.isArray(missingRecords.edges) ? missingRecords.edges : []),
        ]
        const backendRoutes = [
          ...embeddedRoutes,
          ...(Array.isArray(missingRecords.routes)
            ? missingRecords.routes
            : []),
        ]
        const backendWorkChains = [
          ...embeddedWorkChains,
          ...(Array.isArray(missingRecords.workChains)
            ? missingRecords.workChains
            : []),
        ]
        const backendTasks = [
          ...embeddedTasks,
          ...(Array.isArray(missingRecords.tasks) ? missingRecords.tasks : []),
        ]
        const backendVersions = [
          ...embeddedVersions,
          ...(Array.isArray(missingRecords.versions)
            ? missingRecords.versions
            : []),
        ].filter(
          (version): version is StoryboardVersion =>
            Boolean(version) &&
            typeof version === "object" &&
            !Array.isArray(version) &&
            Boolean(
              String((version as Record<string, unknown>).id ?? "").trim()
            )
        )
        const backendProjections = [
          ...embeddedProjections,
          ...(Array.isArray(missingRecords.projections)
            ? missingRecords.projections
            : []),
        ]
        const backendNodeIds = new Set(backendNodes.map((node) => node.id))
        const backendEdgeIds = new Set(
          backendEdges.map((edge) => edge.id).filter(Boolean)
        )
        const backendRouteIds = new Set(backendRoutes.map((route) => route.id))
        const backendWorkChainIds = new Set(
          backendWorkChains.map((workChain) => workChain.id)
        )
        const backendTaskIds = new Set(
          backendTasks
            .map((task) => String(task.id ?? "").trim())
            .filter(Boolean)
        )
        const backendVersionRefs = new Set(
          backendVersions
            .map((version) => {
              const ref = canvasVersionRefFromValue(version)
              return ref ? canvasVersionRefKey(ref) : ""
            })
            .filter(Boolean)
        )
        const finalRemovedNodeIds = new Set(
          [...removedRecordIds.nodeIds].filter((id) => !backendNodeIds.has(id))
        )
        const finalRemovedEdgeIds = new Set(
          [...removedRecordIds.edgeIds].filter((id) => !backendEdgeIds.has(id))
        )
        const finalRemovedRouteIds = new Set(
          [...removedRecordIds.routeIds].filter(
            (id) => !backendRouteIds.has(id)
          )
        )
        const finalRemovedWorkChainIds = new Set(
          [...removedRecordIds.workChainIds].filter(
            (id) => !backendWorkChainIds.has(id)
          )
        )
        const finalRemovedTaskIds = new Set(
          [...removedRecordIds.taskIds].filter((id) => !backendTaskIds.has(id))
        )
        const finalRemovedVersionRefs = new Set(
          [...removedRecordIds.versionRefs].filter(
            (ref) => !backendVersionRefs.has(ref)
          )
        )
        if (
          finalRemovedNodeIds.size ||
          finalRemovedEdgeIds.size ||
          finalRemovedRouteIds.size ||
          finalRemovedWorkChainIds.size
        ) {
          canvasDocument.updateNodes((current) =>
            current.filter((node) => !finalRemovedNodeIds.has(node.id))
          )
          canvasDocument.updateEdges((current) =>
            current.filter((edge) => {
              if (finalRemovedEdgeIds.has(storyboardBackendEdgeId(edge)))
                return false
              if (
                finalRemovedNodeIds.has(edge.source) ||
                finalRemovedNodeIds.has(edge.target)
              ) {
                return false
              }
              const routeId = String(edge.data?.routeId ?? "").trim()
              if (routeId && finalRemovedRouteIds.has(routeId)) return false
              const workChainId = String(edge.data?.workChainId ?? "").trim()
              return !workChainId || !finalRemovedWorkChainIds.has(workChainId)
            })
          )
          if (finalRemovedRouteIds.size || finalRemovedWorkChainIds.size) {
            canvasDocument.updateRoutes((current) =>
              current.filter((route) => {
                if (finalRemovedRouteIds.has(route.id)) return false
                const workChainId = String(route.workChainId ?? "").trim()
                return (
                  !workChainId || !finalRemovedWorkChainIds.has(workChainId)
                )
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
                    !workChainId || !finalRemovedWorkChainIds.has(workChainId)
                  if (!keep) changed = true
                  return keep
                })
                .map((workChain): WorkflowWorkChain => {
                  if (!Array.isArray(workChain.routeIds)) return workChain
                  const nextRouteIds = workChain.routeIds.filter(
                    (routeId) =>
                      !finalRemovedRouteIds.has(String(routeId ?? "").trim())
                  )
                  if (nextRouteIds.length === workChain.routeIds.length) {
                    return workChain
                  }
                  changed = true
                  return { ...workChain, routeIds: nextRouteIds }
                })
              return changed
                ? { ...current, workChains: nextWorkChains }
                : current
            })
          }
          canvasDocument.selectNode((current) =>
            current && finalRemovedNodeIds.has(current) ? null : current
          )
          canvasDocument.selectWorkChain((current) =>
            current !== "all" && finalRemovedWorkChainIds.has(current)
              ? "all"
              : current
          )
        }
        if (finalRemovedVersionRefs.size) {
          canvasDocument.updateNodes((current) =>
            current.map((node) => {
              const nextData = clearRemovedCanvasVersionRefs(
                node.id,
                node.data,
                finalRemovedVersionRefs
              )
              return nextData === node.data ? node : { ...node, data: nextData }
            })
          )
        }
        if (finalRemovedTaskIds.size || finalRemovedNodeIds.size) {
          taskLifecycle.removeRecords(finalRemovedTaskIds, finalRemovedNodeIds)
        }
        const appliedChangedResources: string[] = []
        if (backendNodes.length || finalRemovedNodeIds.size) {
          appliedChangedResources.push("canvas_node")
        }
        if (backendEdges.length || finalRemovedEdgeIds.size) {
          appliedChangedResources.push("canvas_edge")
        }
        if (backendRoutes.length || finalRemovedRouteIds.size) {
          appliedChangedResources.push("canvas_route")
        }
        if (backendWorkChains.length || finalRemovedWorkChainIds.size) {
          appliedChangedResources.push("canvas_work_chain")
        }
        if (backendVersionRefs.size || finalRemovedVersionRefs.size) {
          appliedChangedResources.push("canvas_version")
        }
        if (backendTasks.length || finalRemovedTaskIds.size) {
          appliedChangedResources.push("canvas_task")
        }
        if (backendProjections.length) {
          appliedChangedResources.push("canvas_projection")
        }
        if (!appliedChangedResources.length) {
          appliedChangedResources.push("canvas_document")
        }
        applyWorkflowMutationEventToCanvas({
          action: "canvas_changes_applied",
          projectId: projectId,
          episodeId,
          changedResources: appliedChangedResources,
          workflowVersion: result.currentRevision,
          nodes: backendNodes,
          edges: backendEdges,
          routes: backendRoutes,
          workChains: backendWorkChains,
          tasks: backendTasks,
          versions: backendVersions,
          projections: backendProjections,
          documentExtras: documentExtrasChanged
            ? documentExtrasPatch
            : undefined,
        })
        canvasDocument.markTransactions(freshChanges)
      }

      let syncPromise: Promise<void> | null = null
      syncPromise = (async () => {
        try {
          do {
            if (!currentScope()) return
            canvasChangesPendingRef.current = false
            try {
              await runOnce()
            } catch (error) {
              if (!currentScope()) return
              console.warn("同步画布增量变更失败，回退到快照对账:", error)
              await reconcileCanvasSnapshot("canvas_changes_sync_error")
            }
          } while (currentScope() && canvasChangesPendingRef.current)
        } finally {
          if (
            currentScope() &&
            syncPromise &&
            canvasChangesInFlightRef.current?.promise === syncPromise
          ) {
            canvasChangesInFlightRef.current = null
          }
        }
      })()
      canvasChangesInFlightRef.current = {
        scope: requestScope,
        promise: syncPromise,
      }
      await syncPromise
    },
    [
      applyWorkflowMutationEventToCanvas,
      backendReady,
      callBackend,
      canvasScopeKey,
      episodeId,
      canvasDocument.hasTransaction,
      canvasDocument.markTransactions,
      projectId,
      reconcileCanvasSnapshot,
      canvasDocument.updateEdges,
      canvasDocument.updateNodes,
      canvasDocument.updateRoutes,
      canvasDocument.selectNode,
      canvasDocument.selectWorkChain,
      canvasDocument.updateMetadata,
      taskLifecycle.replaceSnapshot,
      taskLifecycle.upsertRecords,
      taskLifecycle.removeRecords,
    ]
  )

  useEffect(() => {
    canvasChangesBackfillRef.current = (payload?: any) => {
      void applyCanvasChangesFromBackend(payload)
    }
    applyResolvedAssetImagesRef.current = (result) => {
      if (!result.nodes.length) return
      const payload = {
        ...result,
        action: "canvas_asset_images_resolved",
        projectId: projectId,
      }
      if (!applyWorkflowMutationEventToCanvas(payload))
        void applyCanvasChangesFromBackend(payload)
    }
    return () => {
      canvasChangesBackfillRef.current = null
      applyResolvedAssetImagesRef.current = null
    }
  }, [
    applyCanvasChangesFromBackend,
    applyWorkflowMutationEventToCanvas,
    projectId,
  ])

  useEffect(
    () =>
      canvasDocument.subscribeEvents((event) => {
        if (event.type === "reference-reset")
          referenceViewReaderRef.current?.reset()
        else scheduleCanvasChangesBackfill(event.payload)
      }),
    [canvasDocument, scheduleCanvasChangesBackfill]
  )
  const refreshReferences = useCallback(
    () =>
      referenceViewReaderRef.current?.refresh(
        canvasDocument.read().workflowVersion,
        true
      ),
    [canvasDocument]
  )
  return {
    load: loadWorkflow,
    replace: applyReturnedWorkflow,
    reconcile: reconcileCanvasSnapshot,
    applyMutation: applyWorkflowMutationEventToCanvas,
    sync: applyCanvasChangesFromBackend,
    refreshReferences,
    scheduleBackfill: scheduleCanvasChangesBackfill,
    notifyProductionStatusWarning,
  }
}
