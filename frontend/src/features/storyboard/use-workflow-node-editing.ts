import { useEffect } from "react"
import type { WorkflowNodeActions } from "./workflow-canvas-model"
import type { WorkflowWorkChain } from "@/backend"
import {
  workflowVideoDurationSyncWarningMessage,
  workflowVersionResultNodeIds,
  canvasMutationRevision,
} from "./workflow-document-model"
import {
  storyboardVersionDisplayMedia,
  storyboardVersionNodeDataPatch,
  storyboardVersionWithResponseMedia,
} from "./workflow-version-asset-model"
import { useCallback, useRef, useState } from "react"
import {
  useWorkflowEditHistory,
  type WorkflowEditHistoryRestoredEvent,
} from "./use-workflow-edit-history"
import {
  canOpenCanvasImageEditor,
  isWorkChainStoryboardResultImageNode,
  isWorkflowGeneratedMediaResultNode,
  storyboardVersionHistoryDescription,
  workflowNodeId,
  workflowNodeVersionActivationMode,
  type NodeVersionHistoryDialogState,
  type StoryboardImageEditState,
  type StoryboardVersionChangeKind,
} from "./workflow-canvas-asset-model"
import {
  canvasAssetNodeLibraryName,
  canvasProjectAssetTypeFromNode,
} from "./workflow-canvas-assets"
import {
  optionalString,
  recordValue,
  toStoryboardNodesFromBackend,
  upsertStoryboardNodesLocally,
  workflowNodeDataCurrentVersionId,
  type ManualSaveOptions,
  type StoryboardEdgeData,
  type StoryboardNode,
  type WorkflowImageEditOptions,
  type WorkflowInlineEditPatch,
  type WorkflowNodeData,
} from "./workflow-canvas-model"
import { nodeEditHistoryItemsFromPayload } from "./workflow-edit-history-model"
import { workflowNodeMediaType } from "./workflow-node-relations"
import {
  isNarrowNodeDataSaveReason,
  mergeLocalGenerationConfigPatch,
  mergeWorkflowInlineDataPatches,
} from "./workflow-prompt-node-model"
import { toast } from "sonner"
import {
  editStoryboardImage,
  saveEpisodeSourceText,
  saveWorkflowNodeInlineEdit,
  selectWorkflowVariant,
  updateWorkflowNodeLayout,
  type InputImageFile,
  type StoryboardVersion,
} from "@/backend"
import { errMsg } from "@/shared/backend-result"
import {
  workflowVersionOwnerNodeId,
  workflowVersionRelatedNodeIds,
} from "./workflow-version-asset-model"
import type { BackendCaller } from "@/backend"
import type { WorkflowCanvasDocument } from "./workflow-canvas-document"
import type { WorkflowCanvasDetails } from "./use-workflow-canvas-details"
import type { useWorkflowDocumentSync } from "./use-workflow-document-sync"
export function useWorkflowNodeEditing({
  projectId,
  episodeId,
  backendReady,
  callBackend,
  canvasDocument,
  canvasDetails,
  documentSync,
  workflowNodeActions,
  workChains,
  onOpenVersion,
}: {
  projectId: string
  episodeId: string
  backendReady: boolean
  callBackend: BackendCaller
  canvasDocument: WorkflowCanvasDocument
  canvasDetails: WorkflowCanvasDetails
  documentSync: ReturnType<typeof useWorkflowDocumentSync>
  workflowNodeActions: WorkflowNodeActions
  workChains: WorkflowWorkChain[]
  onOpenVersion: () => void
}) {
  const canvasScopeKey = `${projectId}\u0000${episodeId}`
  const versionScope = canvasDocument.scope
  const { nodes, edges, routes } = canvasDocument.read()
  const [storyboardImageEdit, setStoryboardImageEdit] =
    useState<StoryboardImageEditState | null>(null)

  const [nodeVersionHistoryDialog, setNodeVersionHistoryDialog] =
    useState<NodeVersionHistoryDialogState | null>(null)

  const inlineNodeSaveQueueRef = useRef<Promise<void>>(Promise.resolve())


  const storyboardImageEditNode = storyboardImageEdit
    ? nodes.find((node) => node.id === storyboardImageEdit.nodeId)
    : undefined

  const nodeVersionHistoryNode = nodeVersionHistoryDialog
    ? nodes.find((node) => node.id === nodeVersionHistoryDialog.nodeId)
    : undefined

  const nodeVersionHistoryDescription = nodeVersionHistoryNode
    ? storyboardVersionHistoryDescription(
        nodeVersionHistoryNode,
        workChains,
        routes
      )
    : "当前分镜图"

  const handleEditHistoryRestored = useCallback(
    ({ nodeId, result }: WorkflowEditHistoryRestoredEvent) => {
      const backendRestoredNodes = [
        ...(result.node ? [result.node] : []),
        ...(Array.isArray(result.nodes) ? result.nodes : []),
      ]
      if (backendRestoredNodes.length) {
        const restoredNodes = toStoryboardNodesFromBackend(
          backendRestoredNodes,
          workflowNodeActions,
          routes
        )
        canvasDocument.updateNodes((current) =>
          upsertStoryboardNodesLocally(current, restoredNodes)
        )
      } else if (result.sourceText) {
        canvasDocument.updateNodes((current) =>
          current.map((node) =>
            node.id === nodeId
              ? {
                  ...node,
                  data: {
                    ...node.data,
                    episodeId: result.sourceText?.episodeId,
                    title: result.sourceText?.title || node.data.title,
                    sourceText: result.sourceText?.text ?? node.data.sourceText,
                    summary: result.sourceText?.text
                      ? result.sourceText.text.slice(0, 180)
                      : node.data.summary,
                  },
                }
              : node
          )
        )
      }
      if (
        result.workflowVersion !== undefined &&
        result.workflowVersion !== null
      ) {
        canvasDocument.confirmRevision(result.workflowVersion)
      }
    },
    [
      routes,
      canvasDocument.updateNodes,
      canvasDocument.confirmRevision,
      workflowNodeActions,
    ]
  )

  const editHistory = useWorkflowEditHistory({
    callBackend,
    backendReady,
    projectId: projectId,
    episodeId,
    onRestored: handleEditHistoryRestored,
  })

  const editHistoryNode = nodes.find(
    (node) => node.id === editHistory.nodeId
  )

  const applyStoryboardVersionToCanvas = useCallback(
    (
      nodeId: string,
      version?: StoryboardVersion | null,
      changeKind: StoryboardVersionChangeKind = "active"
    ) => {
      if (!version?.id && changeKind !== "winner-cleared") return
      canvasDocument.updateNodes((current) => {
        const targetIds = workflowVersionResultNodeIds(nodeId, current, edges)
        if (!targetIds.size) return current
        return current.map((node) => {
          if (!targetIds.has(node.id)) return node
          if (changeKind === "winner-cleared") {
            return {
              ...node,
              data: {
                ...node.data,
                winnerVersionId: null,
                selectionReason: null,
                selectedAt: null,
              },
            }
          }
          if (!version?.id) return node
          const versionStatus = String(version.status ?? "").trim()
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
          if (changeKind === "winner") {
            nextData.winnerVersionId = version.id
            nextData.selectionReason =
              version.selectionReason ?? node.data.selectionReason
            nextData.selectedAt = version.selectedAt ?? node.data.selectedAt
          }
          return {
            ...node,
            data: nextData,
          }
        })
      })
    },
    [edges, canvasDocument.updateNodes]
  )

  const submitStoryboardImageEdit = useCallback(
    async (
      nodeId: string,
      prompt: string,
      referenceFiles: InputImageFile[],
      options?: WorkflowImageEditOptions
    ) => {
      const requestScope = canvasDocument.scope
      const currentScope = () => canvasDocument.scope === requestScope
      if (requestScope.key !== canvasScopeKey) return

      if (!backendReady) {
        toast.error("后端尚未就绪")
        return false
      }
      const node = nodes.find((item) => item.id === nodeId)
      const useStoryboardWorkChainEdit =
        isWorkChainStoryboardResultImageNode(node)
      if (
        !node ||
        !canOpenCanvasImageEditor(node)
      ) {
        toast.info("当前图片不可编辑；空白结果卡请先通过对应生成入口生成图片")
        return false
      }
      if (!prompt.trim()) {
        toast.info("请输入修改描述")
        return false
      }
      try {
        const canvasAssetType = canvasProjectAssetTypeFromNode(node)
        const canvasAssetName = canvasAssetNodeLibraryName(node)
        const result = await editStoryboardImage(
          callBackend,
          projectId,
          episodeId,
          {
            nodeId,
            prompt: prompt.trim(),
            useOriginal: options?.useOriginal,
            hideTurnaroundHeads: canvasAssetType === "characters" ? options?.hideTurnaroundHeads : undefined,
            useProjectVisual: options?.useProjectVisual,
            storyboardTemplate: options?.storyboardTemplate,
            baseVersionId: useStoryboardWorkChainEdit
              ? workflowNodeDataCurrentVersionId(node.data)
              : null,
            assetType: canvasAssetType || undefined,
            asset_type: canvasAssetType || undefined,
            assetName: canvasAssetName || undefined,
            asset_name: canvasAssetName || undefined,
            referenceFiles,
            modelId: options?.modelId,
            model_id: options?.modelId,
            providerId: options?.providerId,
            provider_id: options?.providerId,
            resolution: options?.resolution,
            size: options?.resolution,
            resolvedConfig: options?.resolvedConfig,
            generationConfig: options?.resolvedConfig,
            allowGenerationConfigOverride:
              options?.allowGenerationConfigOverride,
            returnProductionStatus: false,
          }
        )
        if (!currentScope()) return
        const resultVersion = storyboardVersionWithResponseMedia(
          result.version,
          result.media ?? null
        )
        if (useStoryboardWorkChainEdit && resultVersion) {
          applyStoryboardVersionToCanvas(result.nodeId || nodeId, resultVersion)
        } else {
          const resultMedia = result.media ?? null
          canvasDocument.updateNodes((current) =>
            current.map((item) => {
              if (item.id !== (result.nodeId || nodeId)) return item
              const nextDataPatch = resultVersion
                ? storyboardVersionNodeDataPatch(item.data, resultVersion, {
                    status: "ready",
                    storageMode: "clear",
                  })
                : {
                    status: "ready" as const,
                    media: resultMedia,
                    storage: null,
                    mediaId: resultMedia?.id,
                  }
              return {
                ...item,
                data: {
                  ...item.data,
                  ...nextDataPatch,
                },
              }
            })
          )
        }
        if (
          result.workflowVersion !== undefined &&
          result.workflowVersion !== null
        ) {
          canvasDocument.confirmRevision(result.workflowVersion)
        }
        setStoryboardImageEdit(null)
        toast.success(
          useStoryboardWorkChainEdit ? "分镜图修改版已生成" : "图片已编辑"
        )
        return true
      } catch (error) {
        if (!currentScope()) return

        toast.error(
          errMsg(
            error,
            useStoryboardWorkChainEdit ? "修改分镜图失败" : "编辑图片失败"
          )
        )
        return false
      }
    },
    [
      applyStoryboardVersionToCanvas,
      backendReady,
      callBackend,
      episodeId,
      nodes,
      projectId,
      canvasDocument.updateNodes,
      canvasDocument.confirmRevision,
    ]
  )

  const handleSaveInlineNodeEdit = useCallback(
    async (
      nodeId: string,
      patch: WorkflowInlineEditPatch,
      options?: ManualSaveOptions
    ) => {
      const requestScope = canvasDocument.scope
      const currentScope = () => canvasDocument.scope === requestScope
      const node = canvasDocument
        .read()
        .nodes.find((item) => item.id === nodeId)
      if (!node) {
        toast.error("未找到要保存的节点")
        throw new Error("未找到要保存的节点")
      }
      if (node.data.creationPending) {
        toast.info("节点正在创建，请稍后再保存")
        return
      }
      const dataPatch =
        patch.data && Object.keys(patch.data).length
          ? (patch.data as Record<string, unknown>)
          : undefined
      const generationConfigPatch =
        patch.generationConfig && Object.keys(patch.generationConfig).length
          ? patch.generationConfig
          : undefined
      if (!dataPatch && !generationConfigPatch) return
      if (!backendReady) {
        toast.error("后端尚未就绪")
        throw new Error("后端尚未就绪")
      }
      const optimisticTxId = workflowNodeId("inline_save")
      canvasDocument.stageNodeData(optimisticTxId, (current) => {
        const item = current.find((item) => item.id === nodeId)
        if (!item) return new Map()
        const merged = mergeWorkflowInlineDataPatches(item.data, dataPatch) ?? {}
        const nextData: Partial<WorkflowNodeData> = Object.fromEntries(
          Object.keys(dataPatch ?? {}).map((key) => [key, (merged as Record<string, unknown>)[key]])
        )
        if (generationConfigPatch) {
          nextData.generationConfig = mergeLocalGenerationConfigPatch(
            item.data.generationConfig,
            generationConfigPatch
          )
        }
        return new Map([[nodeId, nextData]])
      })
      const previousInlineSave = inlineNodeSaveQueueRef.current.catch(
        () => undefined
      )
      let releaseSaveBarrier: (() => void) | undefined
      const currentInlineSave = new Promise<void>((resolve) => {
        releaseSaveBarrier = resolve
      })
      inlineNodeSaveQueueRef.current = Promise.all([
        previousInlineSave,
        currentInlineSave,
      ]).then(() => undefined)
      const inlineSaveReason = patch.reason ?? "inline_node_edit_saved"
      try {
        await previousInlineSave
        if (!currentScope()) return
        const result = await saveWorkflowNodeInlineEdit(
          callBackend,
          projectId,
          episodeId,
          {
            nodeId,
            data: dataPatch,
            generationConfig: generationConfigPatch,
            source: "user",
            reason: inlineSaveReason,
          }
        )
        if (!currentScope()) return
        const productionStatusWarning = documentSync.notifyProductionStatusWarning(result)
        if (result.skippedLocked) {
          if (node.data.sourceMode === "independent") {
            throw new Error(result.message ?? "独立原文已锁定，未保存")
          }
          await documentSync.reconcile("inline_save_locked")
          toast.info(result.message ?? "节点已锁定，未保存")
          return
        }
        if (result.editHistoryWarning) toast.warning(result.editHistoryWarning)
        editHistory.mergeItems(nodeEditHistoryItemsFromPayload(result))
        const derived = result.productionStatusMutation
        const onlyOwnDerivedRefresh = derived &&
          Number(derived.baseRevision) === Number(canvasMutationRevision(result)) &&
          Number(canvasMutationRevision(derived)) === canvasDocument.read().workflowVersion
        if (canvasDocument.isStaleRevision(canvasMutationRevision(result)) && !onlyOwnDerivedRefresh) {
          if (!canvasDocument.hasTransaction(result)) await documentSync.reconcile("inline_save_superseded")
          return
        }
        const returnedNodeData = result.node
          ? recordValue(result.node.data)
          : undefined
        canvasDocument.updateNodes((current) =>
          current.map((item) => {
            if (item.id !== nodeId) return item
            const nextData: WorkflowNodeData = {
              ...item.data,
              ...(dataPatch ?? {}),
              ...(returnedNodeData ?? {}),
            } as WorkflowNodeData
            if (result.node) {
              nextData.eyebrow = result.node.type || item.data.eyebrow
              nextData.nodeId = result.node.id || item.data.nodeId
              ;[
                "assetRefs",
                "missingAssetRefs",
                "missingAssetRefsConfirmed",
                "inputLinks",
              ].forEach((key) => {
                if (!(key in returnedNodeData!)) {
                  delete (nextData as Record<string, unknown>)[key]
                }
              })
            }
            if (generationConfigPatch && !returnedNodeData) {
              nextData.generationConfig = mergeLocalGenerationConfigPatch(
                item.data.generationConfig,
                generationConfigPatch
              )
            }
            return {
              ...item,
              data: nextData,
            }
          })
        )
        const returnedBackendNodes = Array.isArray(result.nodes)
          ? result.nodes
          : []
        if (returnedBackendNodes.length) {
          const returnedStoryboardNodes = toStoryboardNodesFromBackend(
            returnedBackendNodes,
            workflowNodeActions,
            routes
          )
          const returnedNodeById = new Map(
            returnedStoryboardNodes.map((item) => [item.id, item])
          )
          canvasDocument.updateNodes((current) =>
            current.map((item) => {
              const returnedNode = returnedNodeById.get(item.id)
              if (!returnedNode) return item
              return {
                ...item,
                ...returnedNode,
                selected: item.selected,
                dragging: item.dragging,
                data: {
                  ...item.data,
                  ...returnedNode.data,
                },
              }
            })
          )
        }
        if (
          patch.reason === "result_frame_slot_set" &&
          typeof dataPatch?.eyebrow === "string"
        ) {
          const nextNodeType = dataPatch.eyebrow
          canvasDocument.updateEdges((current) =>
            current.map((edge) => {
              if (edge.source !== nodeId && edge.target !== nodeId) return edge
              const nextEdgeData: StoryboardEdgeData = {
                role: edge.data?.role ?? "manual_link",
                ...edge.data,
                ...(edge.source === nodeId
                  ? { sourceNodeType: nextNodeType }
                  : {}),
                ...(edge.target === nodeId
                  ? { targetNodeType: nextNodeType }
                  : {}),
              }
              return {
                ...edge,
                data: nextEdgeData,
              }
            })
          )
        }
        if (
          result.workflowVersion !== undefined &&
          result.workflowVersion !== null
        ) {
          canvasDocument.confirmRevision(result.workflowVersion)
        }
        if (result.structureChanged) {
          await documentSync.reconcile("director_allocation_changed")
        }
        if (result.storyboardAllocationWarning) {
          toast.warning(`分镜单元分配未同步：${result.storyboardAllocationWarning}`)
        }
        if (result.allocationNeedsSave) {
          toast.warning("分镜草稿已保存，请在分镜工作台完成镜头分组后再制作")
        }
        if (result.productionStatus) {
          canvasDocument.updateMetadata((current) => ({
            ...current,
            productionStatus: result.productionStatus,
          }))
        }
        if (derived) {
          const event = { ...derived, projectId, episodeId }
          if (!documentSync.applyMutation(event)) documentSync.scheduleBackfill(event)
        }
        const videoDurationSyncWarning =
          workflowVideoDurationSyncWarningMessage(result)
        if (videoDurationSyncWarning) {
          toast.warning(`视频生成时长同步失败：${videoDurationSyncWarning}`)
        } else if (!productionStatusWarning && options?.showSuccess !== false && options?.successMessage) {
          toast.success(options.successMessage)
        }
      } catch (error) {
        if (!currentScope()) throw error
        canvasDocument.finishNodeData(optimisticTxId)
        await documentSync.reconcile("inline_save_failed")
        toast.error(errMsg(error, "保存失败"))
        throw error
      } finally {
        if (currentScope()) canvasDocument.finishNodeData(optimisticTxId)
        releaseSaveBarrier?.()
      }
    },
    [
      backendReady,
      canvasScopeKey,

      documentSync.reconcile,
      callBackend,
      episodeId,
      editHistory.mergeItems,
      projectId,
      routes,
      canvasDocument.updateEdges,
      canvasDocument.updateNodes,
      canvasDocument.confirmRevision,
      workflowNodeActions,
    ]
  )

  const handleUpdateInlineNodeData = useCallback(
    async (
      nodeId: string,
      patch: Partial<WorkflowNodeData>,
      reason: string,
      options?: ManualSaveOptions
    ) => {
      const requestScope = canvasDocument.scope
      const currentScope = () => canvasDocument.scope === requestScope
      if (requestScope.key !== canvasScopeKey) return

      if (reason === "video_winner_selected" && patch.winnerVersionId) {
        if (!backendReady) {
          toast.error("后端尚未就绪")
          return
        }
        const selectionReason =
          typeof patch.selectionReason === "string"
            ? patch.selectionReason.trim()
            : ""
        if (!selectionReason) {
          toast.info("请先填写选择原因")
          return
        }
        try {
          const result = await selectWorkflowVariant(
            callBackend,
            projectId,
            episodeId,
            {
              nodeId,
              versionId: patch.winnerVersionId,
              reason: selectionReason,
              returnProductionStatus: false,
            }
          )
          if (!currentScope()) return
          const selectedVersion = result.version
          const mutationApplied = documentSync.applyMutation({
            ...result,
            action: "workflow_variant_selected",
            projectId: projectId,
            episodeId,
            nodeId,
            versionId: patch.winnerVersionId,
          })
          if (!mutationApplied) {
            canvasDocument.updateNodes((current) => {
              const targetIds = workflowVersionRelatedNodeIds(
                nodeId,
                current,
                edges
              )
              return current.map((item) => {
                if (!targetIds.has(item.id)) return item
                if (!workflowNodeMediaType(item)) return item
                const nextData: WorkflowNodeData = {
                  ...item.data,
                  activeVersionId: patch.winnerVersionId,
                  winnerVersionId: patch.winnerVersionId,
                  selectionReason,
                  selectedAt:
                    selectedVersion?.selectedAt ?? item.data.selectedAt,
                  status: "succeeded",
                  summary: selectedVersion?.summary || item.data.summary,
                }
                if (
                  isWorkflowGeneratedMediaResultNode(item) &&
                  selectedVersion?.media
                ) {
                  nextData.media = selectedVersion.media
                  nextData.storage = null
                }
                return {
                  ...item,
                  data: nextData,
                }
              })
            })
          }
          const workflowVersion = result.workflowVersion
          if (workflowVersion !== undefined && workflowVersion !== null) {
            canvasDocument.confirmRevision(workflowVersion)
          }
          toast.success("视频 winner 已选择")
        } catch (error) {
          if (!currentScope()) return

          toast.error(errMsg(error, "选择 winner 失败"))
        }
        return
      }
      if (!backendReady) {
        toast.error("后端尚未就绪")
        throw new Error("后端尚未就绪")
      }
      const currentNode = nodes.find((item) => item.id === nodeId)
      if (currentNode?.data.creationPending) {
        toast.info("节点正在创建，请稍后再保存")
        return
      }
      if (reason === "node_card_resized") {
        const nextCardState = recordValue(patch.cardState)
        const nextSize = recordValue(nextCardState.size)
        if (!Object.keys(nextSize).length) return
        canvasDocument.updateNodes((current) =>
          current.map((item) =>
            item.id === nodeId
              ? {
                  ...item,
                  data: {
                    ...item.data,
                    cardState: {
                      ...recordValue(item.data.cardState),
                      size: nextSize,
                    },
                  },
                }
              : item
          )
        )
        try {
          const result = await updateWorkflowNodeLayout(
            callBackend,
            projectId,
            episodeId,
            {
              nodeId,
              size: nextSize,
              reason,
            }
          )
          if (!currentScope()) return
          if (result.skippedLocked) {
            toast.info(result.message ?? "节点已锁定，未保存")
            await documentSync.reconcile("resize_node_skipped_locked")
            return
          }
          if (
            result.workflowVersion !== undefined &&
            result.workflowVersion !== null
          ) {
            canvasDocument.confirmRevision(result.workflowVersion)
          }
        } catch (error) {
          if (!currentScope()) return

          toast.error(errMsg(error, "保存卡片尺寸失败"))
          await documentSync.reconcile("resize_node_failed")
          throw error
        }
        return
      }
      if (
        reason === "inline_source_text_saved" &&
        currentNode?.data.sourceMode !== "independent" &&
        typeof patch.sourceText === "string"
      ) {
        try {
          const detail = await saveEpisodeSourceText(
            callBackend,
            projectId,
            episodeId,
            {
              text: patch.sourceText,
              title: String(currentNode?.data.title ?? ""),
              reason,
            }
          )
          if (!currentScope()) return
          canvasDetails.cacheSourceText(detail)
          canvasDocument.updateNodes((current) =>
            current.map((item) =>
              item.id === nodeId
                ? {
                    ...item,
                    data: {
                      ...item.data,
                      ...patch,
                      episodeId: detail.episodeId,
                      title: detail.title || item.data.title,
                      sourceText: detail.text,
                      summary: patch.summary ?? item.data.summary,
                    },
                  }
                : item
            )
          )
          if (options?.showSuccess !== false) {
            toast.success(options?.successMessage ?? "修改已保存")
          }
        } catch (error) {
          if (!currentScope()) return

          toast.error(errMsg(error, "保存失败"))
          throw error
        }
        return
      }
      const inlineOptions =
        options?.showSuccess === false
          ? options
          : {
              ...options,
              successMessage:
                options?.successMessage ??
                (isNarrowNodeDataSaveReason(reason) ? "" : "节点已保存"),
            }
      await handleSaveInlineNodeEdit(
        nodeId,
        {
          data: patch,
          reason,
        },
        inlineOptions
      )
    },
    [
      documentSync.applyMutation,
      backendReady,
      callBackend,
      canvasDetails.cacheSourceText,
      edges,
      episodeId,
      handleSaveInlineNodeEdit,
      nodes,
      projectId,
      documentSync.reconcile,
      canvasDocument.updateNodes,
      canvasDocument.confirmRevision,
    ]
  )

  const handleOpenNodeVersionHistory = useCallback(
    (node: StoryboardNode) => {
      const versionNodeId =
        workflowNodeVersionActivationMode(node) === "local"
          ? node.id
          : workflowVersionOwnerNodeId(node, nodes, edges)
      onOpenVersion()
      setNodeVersionHistoryDialog({ nodeId: versionNodeId })
    },
    [edges, nodes, onOpenVersion]
  )

  const handleNodeVersionHistoryChanged = useCallback(
    async (
      version?: StoryboardVersion | null,
      changeKind?: StoryboardVersionChangeKind
    ) => {
      if (canvasDocument.scope !== versionScope) return
      const nodeId = nodeVersionHistoryDialog?.nodeId
      if (!nodeId || changeKind === "deleted") return
      const targetNode = nodes.find((node) => node.id === nodeId)
      if (
        targetNode &&
        workflowNodeVersionActivationMode(targetNode) === "local" &&
        version?.id
      ) {
        const nextMedia = storyboardVersionDisplayMedia(version)
        if (!nextMedia) {
          throw new Error("该版本没有可用图片")
        }
        const now = new Date().toISOString()
        const payload = recordValue(version.payload)
        const provenance = recordValue(targetNode.data.provenance)
        const nextData: Partial<WorkflowNodeData> = {
          ...storyboardVersionNodeDataPatch(targetNode.data, version, {
            status: "ready",
            storageMode: "mirror-media",
          }),
          assetVersionId:
            targetNode.data.eyebrow === "asset.image"
              ? version.id
              : targetNode.data.assetVersionId,
          provenance: {
            ...provenance,
            action: "canvas_image_version_activated",
            lastVersionSwitchAt: now,
            versionId: version.id,
            mediaVersionId: version.id,
            versionTitle: version.title,
            versionSource:
              optionalString(payload.versionSource) ||
              optionalString(version.source) ||
              provenance.versionSource,
          },
        }
        await handleUpdateInlineNodeData(
          targetNode.id,
          nextData,
          "canvas_image_version_activated",
          { showSuccess: false }
        )
        return
      }
      if (version?.id || changeKind === "winner-cleared") {
        applyStoryboardVersionToCanvas(nodeId, version, changeKind)
      }
    },
    [
      applyStoryboardVersionToCanvas,
      handleUpdateInlineNodeData,
      nodes,
      nodeVersionHistoryDialog?.nodeId,
      versionScope,
    ]
  )
  const handleVersionRevisionChanged = useCallback(
    (value: unknown) => {
      if (canvasDocument.scope !== versionScope) return
      canvasDocument.confirmRevision(value)
    },
    [canvasDocument, versionScope]
  )
  const handleVersionMutationCommitted = useCallback(
    (payload: Record<string, unknown>) => {
      if (canvasDocument.scope !== versionScope) return
      if (!documentSync.applyMutation(payload)) {
        documentSync.scheduleBackfill(payload)
      }
    },
    [canvasDocument, versionScope, documentSync.applyMutation, documentSync.scheduleBackfill]
  )
  useEffect(() => {
    inlineNodeSaveQueueRef.current = Promise.resolve()
    setStoryboardImageEdit(null)
    setNodeVersionHistoryDialog(null)
  }, [canvasScopeKey])
  const waitForWrites = useCallback(
    () => inlineNodeSaveQueueRef.current.catch(() => undefined),
    []
  )
  return {
    editHistory,
    editHistoryNodeTitle: editHistoryNode?.data.title,
    editHistoryNodeType: editHistoryNode?.data.eyebrow,
    waitForWrites,
    imageEdit: storyboardImageEdit,
    setImageEdit: setStoryboardImageEdit,
    imageEditNode: storyboardImageEditNode,
    versionDialog: nodeVersionHistoryDialog,
    setVersionDialog: setNodeVersionHistoryDialog,
    versionNode: nodeVersionHistoryNode,
    versionDescription: nodeVersionHistoryDescription,
    submitImageEdit: submitStoryboardImageEdit,
    saveInline: handleSaveInlineNodeEdit,
    updateData: handleUpdateInlineNodeData,
    openVersion: handleOpenNodeVersionHistory,
    versionChanged: handleNodeVersionHistoryChanged,
    versionRevisionChanged: handleVersionRevisionChanged,
    versionMutationCommitted: handleVersionMutationCommitted,
  }
}
