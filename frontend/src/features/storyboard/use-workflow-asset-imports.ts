import { useCallback } from "react"
import {
  activeAssetMedia,
  assetDesignPromptForCanvas,
  canvasAssetBatchPositions,
  canvasAssetCardState,
  defaultAssetMediaVersionId,
  externalMediaAssetScope,
  externalMediaPurposeRequiresFile,
  externalMediaPurposeSummary,
  externalMediaTitleFieldLabel,
  inputMediaFileKind,
  mediaPurposeUsesVoiceStyle,
  nextCanvasAssetPosition,
  workflowNodeId,
} from "./workflow-canvas-asset-model"
import {
  canvasProjectAssetNameExists,
  canvasProjectAssetTypeLabel,
  mediaPurposeAssetType,
  mediaPurposeMaterialSlot,
  mediaPurposeProjectAssetType,
  mediaPurposeTargetSlot,
} from "./workflow-canvas-assets"
import {
  CANVAS_NODE_ROLE_IMAGE_ASSET,
  canvasMediaReference,
  workflowTone,
} from "./workflow-canvas-model"
import { toast } from "sonner"
import { type AssetItem, type AssetType } from "@/backend"
import {
  getCachedAssetRows,
  invalidateCachedAssetRows,
  loadCachedAssetRows,
} from "@/features/assets/asset-cache"
import { errMsg } from "@/shared/backend-result"
import { mediaAssetFromImageFile, mediaPreviewSrc } from "@/shared/media"
import { useEffect, useRef, useState } from "react"
import type {
  StoryboardNode,
  WorkflowNodeActions,
} from "./workflow-canvas-model"
import type { WorkflowCanvasRect } from "./workflow-canvas-asset-model"
import type { BackendCaller } from "@/backend"
import { useWorkflowAssetPicker } from "./use-workflow-asset-picker"
import type { useWorkflowAssetPersistence } from "./use-workflow-asset-persistence"

export type WorkflowAssetPlacement = {
  nodes: StoryboardNode[]
  visibleNodes: StoryboardNode[]
  workChainId: string
  routeIds: Set<string>
  bounds: () => WorkflowCanvasRect | null
}

/** Complete add-asset flow: draft/catalogue, validation, node construction and persistence. */
export function useWorkflowAssetImports({
  backendReady,
  callBackend,
  projectId,
  episodeId,
  placement,
  workflowNodeActions,
  assetPersistence,
}: {
  backendReady: boolean
  callBackend: BackendCaller
  projectId: string
  episodeId: string
  placement: WorkflowAssetPlacement
  workflowNodeActions: WorkflowNodeActions
  assetPersistence: ReturnType<typeof useWorkflowAssetPersistence>
}) {
  const assetPicker = useWorkflowAssetPicker({
    projectId,
    backendReady,
    callBackend,
  })
  const { assetDraft, activeAddAssetConfig, selectedAssetRows } = assetPicker
  const [savingAsset, setSavingAsset] = useState(false)
  const scopeKey = `${projectId}\u0000${episodeId}`
  const scopeRef = useRef({ key: scopeKey })
  if (scopeRef.current.key !== scopeKey) scopeRef.current = { key: scopeKey }
  useEffect(() => {
    if (scopeRef.current.key !== scopeKey) scopeRef.current = { key: scopeKey }
    setSavingAsset(false)
    const scope = scopeRef.current
    return () => {
      if (scopeRef.current === scope) scopeRef.current = { key: "" }
    }
  }, [scopeKey])
  const handleAddAssetToCanvas = useCallback(async () => {
    if (!assetDraft || !activeAddAssetConfig) return
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }

    const requestScope = scopeRef.current
    const currentScope = () => scopeRef.current === requestScope
    const scopedWorkChainId = placement.workChainId
    const visibilityScope = scopedWorkChainId ? "workChain" : "global"
    const now = new Date().toISOString()
    const customTitle = assetDraft.title.trim()
    const note = assetDraft.note.trim()
    const voiceStyle = assetDraft.voiceStyle.trim()
    const newNodesToAdd: StoryboardNode[] = []
    let placementNodes = placement.nodes
    const appendNode = (node: StoryboardNode) => {
      node.data.nodeId = node.id
      newNodesToAdd.push(node)
      placementNodes = [...placementNodes, node]
    }
    const placementAnchor = assetDraft.placementPosition
    const placementWorkChainId = placement.workChainId || "all"
    const batchPlacementPositions =
      placementAnchor && activeAddAssetConfig.sourceType === "asset"
        ? canvasAssetBatchPositions({
            anchor: placementAnchor,
            count: selectedAssetRows.length,
            nodes: placementNodes,
            visibleNodes: placement.visibleNodes,
            nodeType: "asset.image",
            bounds: placement.bounds(),
          })
        : []
    let batchPlacementIndex = 0
    const nextPosition = () => {
      if (placementAnchor) {
        if (activeAddAssetConfig.sourceType === "asset") {
          const position = batchPlacementPositions[batchPlacementIndex]
          batchPlacementIndex += 1
          if (position) return position
        } else {
          return placementAnchor
        }
      }
      return nextCanvasAssetPosition(
        placementNodes,
        placement.visibleNodes,
        placementWorkChainId,
        placement.routeIds
      )
    }

    if (activeAddAssetConfig.sourceType === "media") {
      const mediaFile = assetDraft.mediaFile
      if (!customTitle) {
        toast.info(
          `请输入${externalMediaTitleFieldLabel(assetDraft.mediaPurpose)}`
        )
        return
      }
      const mediaPurpose = assetDraft.mediaPurpose
      if (externalMediaPurposeRequiresFile(mediaPurpose) && !mediaFile) {
        toast.info("请上传媒体文件")
        return
      }
      if (
        mediaFile &&
        (mediaPurpose === "video") !==
          (inputMediaFileKind(mediaFile) === "video")
      ) {
        toast.info(
          mediaPurpose === "video" ? "请选择视频文件" : "此分类必须上传图片文件"
        )
        return
      }
      const preferredTargetSlot =
        mediaPurposeMaterialSlot(mediaPurpose) ||
        mediaPurposeTargetSlot(mediaPurpose)
      const inferredAssetType = mediaPurposeAssetType(mediaPurpose)
      const assetScope = externalMediaAssetScope(mediaPurpose)
      const duplicateAssetType = mediaPurposeProjectAssetType(mediaPurpose)
      if (duplicateAssetType) {
        const cacheOptions = {
          scope: "project" as const,
          projectId: projectId,
          assetType: duplicateAssetType as AssetType,
          lifecycleStatus: "active" as const,
        }
        let rows = getCachedAssetRows(cacheOptions) as AssetItem[] | null
        if (!rows) {
          setSavingAsset(true)
          try {
            rows = (await loadCachedAssetRows(
              callBackend,
              cacheOptions
            )) as AssetItem[]
            if (!currentScope()) return
          } catch (error) {
            if (!currentScope()) return
            toast.error(errMsg(error, "校验资产名称失败"))
            setSavingAsset(false)
            return
          }
          setSavingAsset(false)
        }
        if (canvasProjectAssetNameExists(rows, customTitle)) {
          toast.error(
            `项目中已存在同名${canvasProjectAssetTypeLabel(duplicateAssetType)}「${customTitle}」`
          )
          return
        }
      }
      if (mediaFile) {
        const mediaBase = mediaAssetFromImageFile(mediaFile)
        const mediaKind = inputMediaFileKind(mediaFile)
        const mediaNodeId = workflowNodeId("media_external")
        const mediaPosition = nextPosition()
        const pendingSummary =
          mediaKind === "video"
            ? "视频正在导入，完成后会自动显示。"
            : "图片正在导入，完成后会自动显示。"
        const hasPendingPreview = Boolean(mediaPreviewSrc(mediaBase))
        const optimisticMediaNode: StoryboardNode = {
          id: mediaNodeId,
          type: "storyboardNode",
          position: mediaPosition,
          data: {
            projectId: projectId,
            episodeId,
            nodeId: mediaNodeId,
            title: customTitle,
            eyebrow: "media.external",
            summary: note || pendingSummary,
            status: "processing",
            tone: workflowTone("media.external"),
            visibilityScope,
            ...(scopedWorkChainId ? { workChainId: scopedWorkChainId } : {}),
            sourceType: "external_media",
            canvasNodeRole: CANVAS_NODE_ROLE_IMAGE_ASSET,
            mediaPurpose,
            preferredTargetSlot,
            assetScope,
            assetKind: inferredAssetType || "",
            ...(inferredAssetType ? { assetType: inferredAssetType } : {}),
            assetName: customTitle,
            media: mediaBase,
            storage: mediaBase,
            sourceFileName:
              mediaBase.originalName || mediaBase.file || mediaBase.path,
            ...(mediaPurposeUsesVoiceStyle(mediaPurpose) && voiceStyle
              ? { voiceStyle }
              : {}),
            cardState: canvasAssetCardState("media", hasPendingPreview),
            provenance: {
              source: "user",
              action: "canvas_external_media_import_pending",
              createdAt: now,
              mediaPurpose,
              ...(note ? { note } : {}),
              ...(mediaPurposeUsesVoiceStyle(mediaPurpose) && voiceStyle
                ? { voiceStyle }
                : {}),
            },
            onRun: workflowNodeActions.onRun,
            onUpdateNodeData: workflowNodeActions.onUpdateNodeData,
            onUpdateReferenceUsage: workflowNodeActions.onUpdateReferenceUsage,
            onUpdateFrameReference: workflowNodeActions.onUpdateFrameReference,
            onRemoveInputLink: workflowNodeActions.onRemoveInputLink,
            onFocusNode: workflowNodeActions.onFocusNode,
            onSubmitStoryboardImageEdit:
              workflowNodeActions.onSubmitStoryboardImageEdit,
          },
        }
        assetPicker.close()
        setSavingAsset(false)
        await assetPersistence.importMedia(
          {
            file: mediaFile,
            ...(mediaFile.id ? { mediaId: mediaFile.id } : {}),
            mediaNodeId,
            mediaKind,
            mediaPurpose,
            title: customTitle,
            assetName: customTitle,
            ...(preferredTargetSlot ? { preferredTargetSlot } : {}),
            ...(inferredAssetType
              ? { assetKind: inferredAssetType, assetType: inferredAssetType }
              : {}),
            assetScope,
            visibilityScope,
            scope: visibilityScope,
            ...(scopedWorkChainId ? { workChainId: scopedWorkChainId } : {}),
            canvasNodeRole: CANVAS_NODE_ROLE_IMAGE_ASSET,
            position: mediaPosition,
            note,
            ...(mediaPurposeUsesVoiceStyle(mediaPurpose) && voiceStyle
              ? { voiceStyle }
              : {}),
            returnProductionStatus: false,
          },
          {
            pendingNode: optimisticMediaNode,
            successMessage:
              mediaKind === "video" ? "视频已导入画布" : "图片已导入画布",
            errorMessage: "导入媒体失败",
            onImported: () => {
              if (duplicateAssetType)
                invalidateCachedAssetRows({
                  scope: "project",
                  projectId: projectId,
                  assetType: duplicateAssetType as AssetType,
                  lifecycleStatus: "active",
                })
            },
          }
        )
        return
      }

      const summary =
        note ||
        `空${externalMediaPurposeSummary(mediaPurpose)}资产，可在编辑弹窗中补充或生成图片。`
      appendNode({
        id: workflowNodeId("media_external"),
        type: "storyboardNode",
        position: nextPosition(),
        data: {
          nodeId: "",
          title: customTitle,
          eyebrow: "media.external",
          summary,
          status: "ready",
          tone: workflowTone("media.external"),
          visibilityScope,
          ...(scopedWorkChainId ? { workChainId: scopedWorkChainId } : {}),
          sourceType: "external_media",
          canvasNodeRole: CANVAS_NODE_ROLE_IMAGE_ASSET,
          mediaPurpose,
          preferredTargetSlot,
          assetScope,
          assetKind: inferredAssetType || "",
          ...(inferredAssetType ? { assetType: inferredAssetType } : {}),
          assetName: customTitle,
          ...(mediaPurposeUsesVoiceStyle(mediaPurpose) && voiceStyle
            ? { voiceStyle }
            : {}),
          cardState: canvasAssetCardState("media", false),
          provenance: {
            source: "user",
            action: "canvas_empty_media_created",
            createdAt: now,
            mediaPurpose,
            ...(note ? { note } : {}),
            ...(mediaPurposeUsesVoiceStyle(mediaPurpose) && voiceStyle
              ? { voiceStyle }
              : {}),
          },
          onRun: workflowNodeActions.onRun,
          onUpdateNodeData: workflowNodeActions.onUpdateNodeData,
          onUpdateReferenceUsage: workflowNodeActions.onUpdateReferenceUsage,
          onUpdateFrameReference: workflowNodeActions.onUpdateFrameReference,
          onRemoveInputLink: workflowNodeActions.onRemoveInputLink,
          onFocusNode: workflowNodeActions.onFocusNode,
          onSubmitStoryboardImageEdit:
            workflowNodeActions.onSubmitStoryboardImageEdit,
        },
      })
    } else {
      const assets = selectedAssetRows
      if (!assets.length) {
        toast.info(`请选择至少一个${activeAddAssetConfig.noun}`)
        return
      }

      const assetPlans = assets.map((asset) => {
        const selectedMediaVersionId =
          assetDraft.selectedMediaVersionIds?.[asset.id] ||
          (assetDraft.selectedAssetId === asset.id
            ? assetDraft.selectedMediaVersionId
            : "") ||
          defaultAssetMediaVersionId(asset)
        const selectedMediaVersion = asset.mediaVersions?.find(
          (version) => version.id === selectedMediaVersionId
        )
        const media = canvasMediaReference(
          activeAssetMedia(asset, selectedMediaVersionId)
        )
        return { asset, selectedMediaVersionId, selectedMediaVersion, media }
      })

      assetPlans.forEach(
        ({ asset, selectedMediaVersionId, selectedMediaVersion, media }) => {
          const hasMedia = Boolean(mediaPreviewSrc(media))
          const summary =
            note ||
            assetDesignPromptForCanvas(asset) ||
            `${activeAddAssetConfig.noun}资产图片，可通过画布连线接入分镜脚本、分镜单元或视频生成。`
          appendNode({
            id: workflowNodeId("asset_image"),
            type: "storyboardNode",
            position: nextPosition(),
            data: {
              nodeId: "",
              title: asset.name,
              eyebrow: "asset.image",
              summary,
              status: "ready",
              tone: workflowTone("asset.image"),
              visibilityScope,
              ...(scopedWorkChainId ? { workChainId: scopedWorkChainId } : {}),
              sourceType: "asset",
              canvasNodeRole: CANVAS_NODE_ROLE_IMAGE_ASSET,
              assetScope: "reusable",
              assetKind: activeAddAssetConfig.assetType,
              assetId: asset.id,
              assetType: activeAddAssetConfig.assetType,
              rootAssetId: asset.id,
              rootAssetType: activeAddAssetConfig.assetType,
              rootAssetProjectId: projectId,
              assetName: asset.name,
              ...(media?.id ? { mediaId: media.id } : {}),
              ...(hasMedia && selectedMediaVersionId
                ? {
                    sourceVersionId: selectedMediaVersionId,
                    mediaVersionId: selectedMediaVersionId,
                    activeMediaVersionId: selectedMediaVersionId,
                    activeVersionId: selectedMediaVersionId,
                  }
                : {}),
              ...(hasMedia ? { media, storage: media } : {}),
              cardState: canvasAssetCardState("asset", hasMedia),
              provenance: {
                source: "user",
                action: "canvas_asset_node_created",
                createdAt: now,
                mediaVersionId: selectedMediaVersionId || undefined,
                mediaVersionTitle: selectedMediaVersion?.title || undefined,
                ...(note ? { note } : {}),
              },
              onRun: workflowNodeActions.onRun,
              onUpdateNodeData: workflowNodeActions.onUpdateNodeData,
              onUpdateReferenceUsage: workflowNodeActions.onUpdateReferenceUsage,
              onUpdateFrameReference: workflowNodeActions.onUpdateFrameReference,
              onRemoveInputLink: workflowNodeActions.onRemoveInputLink,
              onFocusNode: workflowNodeActions.onFocusNode,
              onSubmitStoryboardImageEdit:
                workflowNodeActions.onSubmitStoryboardImageEdit,
            },
          })
        }
      )
    }

    if (!newNodesToAdd.length) return
    const successMessage =
      newNodesToAdd.length > 1
        ? `已添加 ${newNodesToAdd.length} 个资产到画布`
        : "已添加到画布，可手动拖线接入任务卡"
    assetPicker.close()
    setSavingAsset(false)
    await assetPersistence.addNodes(newNodesToAdd, "canvas_asset_node_added", {
      successMessage,
      errorMessage: "添加资产节点失败",
    })
  }, [
    activeAddAssetConfig,
    assetDraft,
    assetPicker.close,
    backendReady,
    callBackend,
    episodeId,
    projectId,
    placement,
    selectedAssetRows,
    workflowNodeActions,
    assetPersistence.addNodes,
    assetPersistence.importMedia,
  ])

  return {
    picker: assetPicker,
    saving: savingAsset,
    addToCanvas: handleAddAssetToCanvas,
  }
}
