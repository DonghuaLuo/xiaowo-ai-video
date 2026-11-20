import { useCallback, useEffect, useState } from "react"
import {
  canvasAssetCardState,
  defaultAssetMediaVersionId,
  mediaPurposeUsesVoiceStyle,
  renameAssetTitleFromNode,
  renameImageMediaPurposeFromNode,
  workflowAssetRenameKind,
  workflowNodeVersionStorageNodeId,
  type ExternalMediaPurpose,
  type RenameAssetDraft,
} from "./workflow-canvas-asset-model"
import {
  canvasAssetNodeInProjectLibrary,
  canvasAssetNodeLibraryName,
  canvasAssetNodeReferencesSplitAsset,
  canvasAssetPayloadFromNode,
  canvasProjectAssetTypeFromNode,
  canvasProjectAssetTypeLabel,
  canvasWorkflowMediaRecordForNode,
  detachCanvasProjectAssetReference,
  mediaPurposeAssetType,
  mediaPurposeMaterialSlot,
  mediaPurposeTargetSlot,
  type CanvasProjectAssetType,
} from "./workflow-canvas-assets"
import {
  canvasMediaReference,
  isWorkflowItemLocked,
  recordValue,
  type StoryboardNode,
  type WorkflowNodeData,
} from "./workflow-canvas-model"
import { toast } from "sonner"
import {
  createAsset,
  deleteAsset,
  listStoryboardVersions,
  listWorkflowMedia,
  renameWorkflowAssetNode,
  saveWorkflowNodeInlineEdit,
  type AssetItem,
} from "@/backend"
import {
  getCachedAssetRows,
  invalidateCachedAssetRows,
  loadCachedAssetRows,
} from "@/features/assets/asset-cache"
import { errMsg } from "@/shared/backend-result"
import { mediaPreviewSrc } from "@/shared/media"
import type { BackendCaller } from "@/backend"
import type { WorkflowCanvasDocument } from "./workflow-canvas-document"
import type { useWorkflowDocumentSync } from "./use-workflow-document-sync"
export function useWorkflowProjectAssets({
  projectId,
  episodeId,
  backendReady,
  callBackend,
  canvasDocument,
  documentSync,
  contextNode,
  dismiss,
}: {
  projectId: string
  episodeId: string
  backendReady: boolean
  callBackend: BackendCaller
  canvasDocument: WorkflowCanvasDocument
  documentSync: ReturnType<typeof useWorkflowDocumentSync>
  contextNode?: StoryboardNode
  dismiss: (reason: "rename" | "added") => void
}) {
  const { nodes } = canvasDocument.read()
  const contextAssetType = contextNode
    ? canvasProjectAssetTypeFromNode(contextNode)
    : null
  const [renameAssetDraft, setRenameAssetDraft] =
    useState<RenameAssetDraft | null>(null)

  const [savingRenameAsset, setSavingRenameAsset] = useState(false)

  const [contextAssetRowsByType, setContextAssetRowsByType] = useState<
    Partial<Record<CanvasProjectAssetType, AssetItem[]>>
  >({})

  const [addingAssetLibraryNodeId, setAddingAssetLibraryNodeId] = useState<
    string | null
  >(null)

  const handleOpenRenameAssetDialog = useCallback((node: StoryboardNode) => {
    const kind = workflowAssetRenameKind(node)
    if (!kind) {
      toast.info("当前节点不支持重命名")
      return
    }
    canvasDocument.selectNode(node.id)
    dismiss("rename")
    setRenameAssetDraft({
      nodeId: node.id,
      kind,
      mediaPurpose:
        kind === "video"
          ? "video_result"
          : renameImageMediaPurposeFromNode(node),
      title: renameAssetTitleFromNode(node),
      voiceStyle: String(node.data.voiceStyle ?? "").trim(),
    })
  }, [])

  const handleSaveRenameAsset = useCallback(async () => {
    const requestScope = canvasDocument.scope
    const currentScope = () => canvasDocument.scope === requestScope
    const draft = renameAssetDraft
    if (!draft) return
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    const currentNode = nodes.find((node) => node.id === draft.nodeId)
    if (!currentNode) {
      toast.error("节点不存在")
      setRenameAssetDraft(null)
      return
    }
    const kind = workflowAssetRenameKind(currentNode)
    if (!kind || kind !== draft.kind) {
      toast.info("当前节点不支持重命名")
      setRenameAssetDraft(null)
      return
    }
    const assetId = String(currentNode.data.assetId ?? "").trim()
    const directProjectAsset = currentNode.data.sourceType === "asset"
    const projectAssetType = canvasProjectAssetTypeFromNode(currentNode)
    const projectAssetRows = projectAssetType
      ? contextAssetRowsByType[projectAssetType]
      : undefined
    if (directProjectAsset && (!assetId || !projectAssetType)) {
      toast.info("资产来源信息不完整，不能重命名")
      setRenameAssetDraft(null)
      return
    }
    if (
      directProjectAsset &&
      projectAssetType &&
      !Array.isArray(projectAssetRows)
    ) {
      toast.info("正在校验资产来源，请稍后再试")
      return
    }
    if (canvasAssetNodeReferencesSplitAsset(currentNode, projectAssetRows)) {
      toast.info("拆分资产参与自动关联，不能重命名")
      setRenameAssetDraft(null)
      return
    }
    const title = draft.title.trim()
    if (!title) {
      toast.info("请输入名称")
      return
    }

    const nextData: WorkflowNodeData = {
      ...currentNode.data,
      title,
      assetName: title,
    }
    if (kind === "video") {
      nextData.assetKind = "video"
      nextData.assetType = "video"
      nextData.mediaPurpose = "video_result"
      nextData.preferredTargetSlot = "video_result"
      nextData.voiceStyle = ""
    } else {
      const mediaPurpose = draft.mediaPurpose as ExternalMediaPurpose
      const assetType = mediaPurposeAssetType(mediaPurpose)
      nextData.mediaPurpose = mediaPurpose
      nextData.preferredTargetSlot =
        mediaPurposeMaterialSlot(mediaPurpose) ||
        mediaPurposeTargetSlot(mediaPurpose)
      nextData.assetKind = assetType
      nextData.assetType = assetType
      if (directProjectAsset && assetType !== projectAssetType) {
        detachCanvasProjectAssetReference(nextData)
      }
      nextData.voiceStyle = mediaPurposeUsesVoiceStyle(mediaPurpose)
        ? draft.voiceStyle.trim()
        : ""
    }

    const nextNode: StoryboardNode = {
      ...currentNode,
      data: nextData,
    }
    setSavingRenameAsset(true)
    canvasDocument.updateNodes((current) =>
      current.map((node) => (node.id === nextNode.id ? nextNode : node))
    )
    try {
      const result = await renameWorkflowAssetNode(
        callBackend,
        projectId,
        episodeId,
        {
          nodeId: currentNode.id,
          title,
          kind,
          mediaPurpose: kind === "image" ? draft.mediaPurpose : "video_result",
          voiceStyle: kind === "image" ? draft.voiceStyle.trim() : "",
          reason: "canvas_asset_node_renamed",
        }
      )
      if (!currentScope()) return
      if (result.skippedLocked) {
        canvasDocument.updateNodes((current) =>
          current.map((node) =>
            node.id === currentNode.id ? currentNode : node
          )
        )
        toast.info(result.message ?? "节点已锁定，未重命名")
        await documentSync.reconcile("rename_asset_skipped_locked")
        return
      }
      documentSync.applyMutation({
        ...result,
        action: "workflow_asset_node_renamed",
        projectId: projectId,
        episodeId,
        itemType: result.itemType ?? "node",
        itemId: result.item
          ? String(result.item.id ?? nextNode.id)
          : nextNode.id,
      })
      if (
        result.workflowVersion !== undefined &&
        result.workflowVersion !== null
      ) {
        canvasDocument.confirmRevision(result.workflowVersion)
      }
      setRenameAssetDraft(null)
      toast.success("资产已重命名")
    } catch (error) {
      if (!currentScope()) return
      canvasDocument.updateNodes((current) =>
        current.map((node) => (node.id === currentNode.id ? currentNode : node))
      )
      toast.error(errMsg(error, "资产重命名失败"))
    } finally {
      if (!currentScope()) return
      setSavingRenameAsset(false)
    }
  }, [
    documentSync.applyMutation,
    backendReady,
    callBackend,
    contextAssetRowsByType,
    episodeId,
    nodes,
    projectId,
    documentSync.reconcile,
    renameAssetDraft,
    canvasDocument.updateNodes,
    canvasDocument.confirmRevision,
  ])

  const handleAddContextNodeToAssetLibrary = useCallback(
    async (nodeId: string) => {
      const requestScope = canvasDocument.scope
      const currentScope = () => canvasDocument.scope === requestScope
      if (!backendReady) {
        if (currentScope()) toast.error("后端尚未就绪")
        return
      }
      const node = nodes.find((item) => item.id === nodeId)
      if (!node) {
        if (currentScope()) toast.info("资产节点不在当前画布中")
        return
      }
      if (isWorkflowItemLocked(node.data)) {
        if (currentScope()) toast.info("该节点已锁定，不能加入资产库")
        return
      }
      const assetType = canvasProjectAssetTypeFromNode(node)
      if (!assetType) {
        if (currentScope())
          toast.info("只有角色、生物、场景、道具图片资产可以加入资产库")
        return
      }
      const projectAssetRows = contextAssetRowsByType[assetType]
      if (canvasAssetNodeInProjectLibrary(node, projectAssetRows)) {
        if (currentScope()) toast.info("当前项目资产库已存在该资产")
        return
      }
      if (!projectAssetRows) {
        if (currentScope()) toast.info("正在校验资产库，请稍后再试")
        return
      }
      const assetName = canvasAssetNodeLibraryName(node)
      if (!assetName) {
        if (currentScope()) toast.info("请先填写资产名称")
        return
      }
      setAddingAssetLibraryNodeId(nodeId)
      const projectAssetCacheOptions = {
        scope: "project" as const,
        projectId: projectId,
        assetType,
        lifecycleStatus: "active" as const,
      }
      let createdAsset: AssetItem | null = null
      let nodeSaveSucceeded = false
      let rollbackAttempted = false
      const rollbackCreatedAsset = async () => {
        if (!createdAsset?.id || rollbackAttempted) return
        rollbackAttempted = true
        await deleteAsset(
          callBackend,
          assetType,
          createdAsset.id,
          "project",
          projectId
        )
        createdAsset = null
        invalidateCachedAssetRows(projectAssetCacheOptions)
      }
      try {
        const versionOwnerNodeId = workflowNodeVersionStorageNodeId(
          node.id,
          node.data
        )
        const [nodeVersions, workflowMedia] = await Promise.all([
          listStoryboardVersions(
            callBackend,
            projectId,
            episodeId,
            versionOwnerNodeId
          ),
          node.data.eyebrow === "media.external"
            ? listWorkflowMedia(callBackend, projectId, episodeId)
            : Promise.resolve({ items: [] }),
        ])
        const workflowMediaRecord =
          node.data.eyebrow === "media.external"
            ? canvasWorkflowMediaRecordForNode(workflowMedia.items, node)
            : null
        const asset = await createAsset(
          callBackend,
          assetType,
          canvasAssetPayloadFromNode(node, nodeVersions, workflowMediaRecord),
          "project",
          projectId
        )
        createdAsset = asset

        const media = canvasMediaReference(
          asset.media ?? node.data.media ?? node.data.storage ?? null
        )
        const hasMedia = Boolean(mediaPreviewSrc(media))
        const mediaVersionId =
          String(asset.activeMediaVersionId ?? "").trim() ||
          defaultAssetMediaVersionId(asset)
        const dataPatch: Record<string, unknown> = {
          sourceType: "asset",
          assetScope: "reusable",
          assetKind: assetType,
          assetType,
          assetId: asset.id,
          rootAssetType: assetType,
          rootAssetId: asset.id,
          rootAssetProjectId: projectId,
          assetName: asset.name,
          title: asset.name || node.data.title,
          cardState: canvasAssetCardState("asset", hasMedia),
          provenance: {
            ...recordValue(node.data.provenance),
            action: "canvas_asset_added_to_project_library",
            addedAt: new Date().toISOString(),
            assetId: asset.id,
            assetType,
          },
          ...(hasMedia && media
            ? {
                media,
                storage: media,
                mediaId: media.id,
              }
            : {}),
          ...(hasMedia && mediaVersionId
            ? {
                sourceVersionId: mediaVersionId,
                mediaVersionId,
                activeMediaVersionId: mediaVersionId,
                activeVersionId: mediaVersionId,
              }
            : {}),
        }
        const result = await saveWorkflowNodeInlineEdit(
          callBackend,
          projectId,
          episodeId,
          {
            nodeId,
            data: dataPatch,
            source: "user",
            reason: "canvas_asset_added_to_project_library",
            returnProductionStatus: false,
          }
        )
        if (result.skippedLocked) {
          try {
            await rollbackCreatedAsset()
          } catch (rollbackError) {
            console.warn("回滚项目资产失败:", rollbackError)
            invalidateCachedAssetRows(projectAssetCacheOptions)
            if (currentScope())
              toast.error("节点已锁定，新建资产回滚失败，请刷新后检查资产库")
            return
          }
          if (currentScope()) toast.info(result.message ?? "节点已锁定，未保存")
          return
        }
        nodeSaveSucceeded = true
        invalidateCachedAssetRows(projectAssetCacheOptions)
        if (!currentScope()) return
        setContextAssetRowsByType((current) => {
          const rows = current[assetType] ?? []
          const nextRows = rows.some((row) => row.id === asset.id)
            ? rows.map((row) => (row.id === asset.id ? asset : row))
            : [...rows, asset]
          return { ...current, [assetType]: nextRows }
        })
        const returnedNodeData = result.node
          ? recordValue(result.node.data)
          : undefined
        canvasDocument.updateNodes((current) =>
          current.map((item) => {
            if (item.id !== nodeId) return item
            const nextData: WorkflowNodeData = {
              ...item.data,
              ...dataPatch,
              ...(returnedNodeData ?? {}),
            } as WorkflowNodeData
            if (result.node) {
              nextData.eyebrow = result.node.type || item.data.eyebrow
              nextData.nodeId = result.node.id || item.data.nodeId
            }
            return { ...item, data: nextData }
          })
        )
        if (
          result.workflowVersion !== undefined &&
          result.workflowVersion !== null
        ) {
          canvasDocument.confirmRevision(result.workflowVersion)
        }
        dismiss("added")
        if (currentScope())
          toast.success(
            `已加入当前项目${canvasProjectAssetTypeLabel(assetType)}资产库`
          )
      } catch (error) {
        if (createdAsset?.id && !nodeSaveSucceeded) {
          try {
            await rollbackCreatedAsset()
            if (currentScope())
              toast.error(`${errMsg(error, "加入资产库失败")}，已回滚新建资产`)
          } catch (rollbackError) {
            console.warn("回滚项目资产失败:", rollbackError)
            invalidateCachedAssetRows(projectAssetCacheOptions)
            if (currentScope())
              toast.error(
                `${errMsg(error, "加入资产库失败")}；新建资产回滚失败，请刷新后检查资产库`
              )
          }
        } else {
          if (currentScope()) toast.error(errMsg(error, "加入资产库失败"))
        }
      } finally {
        if (!currentScope()) return
        setAddingAssetLibraryNodeId((current) =>
          current === nodeId ? null : current
        )
      }
    },
    [
      backendReady,
      callBackend,
      contextAssetRowsByType,
      episodeId,
      nodes,
      projectId,
      canvasDocument.updateNodes,
      canvasDocument.confirmRevision,
    ]
  )

  useEffect(() => setContextAssetRowsByType({}), [projectId])
  useEffect(() => {
    const assetType = contextAssetType
    if (!assetType || !backendReady) return
    const cacheOptions = {
      scope: "project" as const,
      projectId: projectId,
      assetType,
      lifecycleStatus: "active" as const,
      includeSourceMetadata: true,
    }
    const cachedRows = getCachedAssetRows(cacheOptions) as AssetItem[] | null
    if (cachedRows) {
      setContextAssetRowsByType((current) => ({
        ...current,
        [assetType]: cachedRows,
      }))
      return
    }
    let cancelled = false
    loadCachedAssetRows(callBackend, cacheOptions)
      .then((rows) => {
        if (cancelled) return
        setContextAssetRowsByType((current) => ({
          ...current,
          [assetType]: rows,
        }))
      })
      .catch((error) => {
        if (!cancelled) {
          console.warn("加载项目资产用于菜单判重失败:", error)
        }
      })
    return () => {
      cancelled = true
    }
  }, [backendReady, callBackend, contextAssetType, projectId])
  useEffect(() => {
    setRenameAssetDraft(null)
    setSavingRenameAsset(false)
    setAddingAssetLibraryNodeId(null)
  }, [projectId, episodeId])
  return {
    renameDraft: renameAssetDraft,
    setRenameDraft: setRenameAssetDraft,
    savingRename: savingRenameAsset,
    projectAssets: contextAssetRowsByType,
    addingNodeId: addingAssetLibraryNodeId,
    openRename: handleOpenRenameAssetDialog,
    saveRename: handleSaveRenameAsset,
    addToLibrary: handleAddContextNodeToAssetLibrary,
  }
}
