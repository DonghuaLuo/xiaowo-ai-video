import {workflowTaskResultNode, isWorkflowTaskResultEdge} from './workflow-document-model'
import {isWorkflowGeneratedMediaResultNode, workflowNodeVersionStorageNodeId} from "./workflow-canvas-asset-model"
import {type StoryboardEdge} from "./workflow-canvas-model"
import type {
  MediaAsset,
  StoryboardVersion,
  WorkflowRoute,
  WorkflowWorkChain,
} from "@/backend"
import { mediaPreviewSrc } from "@/shared/media"
import { isFrameImage } from "./frame-reference-menu"
import {
  CANVAS_NODE_ROLE_IMAGE_ASSET,
  canvasMediaReference,
  optionalString,
  recordValue,
  workflowNodeDataCurrentVersionId,
  workflowTone,
  type StoryboardNode,
  type WorkflowNodeActions,
  type WorkflowNodeData,
} from "./workflow-canvas-model"
import {
  assetTargetSlotForAssetType,
  defaultWorkflowCardSize,
  storyboardVersionHasActiveFlag,
  storyboardVersionHistoryDescription,
  storyboardVersionIsActive,
  workflowNodeId,
  workflowNodeIsVisualHandoffAsset,
  type StoryboardVersionCanvasPlacement,
} from "./workflow-canvas-asset-model"
import {
  canvasAssetNodeProjectAssetIdentity,
  canvasAssetNodeRootFields,
} from "./workflow-canvas-assets"

export function storyboardVersionPreviewSrc(version: StoryboardVersion) {
  return mediaPreviewSrc(version.media, version.preview)
}

export function storyboardVersionPreviewKind(
  version: StoryboardVersion
): "image" | "video" {
  const src = storyboardVersionPreviewSrc(version)
  if (
    version.media?.kind === "video" ||
    version.media?.mimeType?.startsWith("video/") ||
    (src && (/^data:video\//.test(src) || /\.(mp4|webm|mov)(\?|$)/i.test(src)))
  ) {
    return "video"
  }
  return "image"
}

export function storyboardVersionCanvasMedia(version: StoryboardVersion) {
  const media: MediaAsset = version.media ?? {}
  return canvasMediaReference({
    ...media,
    id: media.id || `storyboard-version-${version.id}`,
    kind: storyboardVersionPreviewKind(version),
    preview: media.preview ?? version.preview ?? undefined,
  })
}

export function storyboardVersionDisplayMedia(version: StoryboardVersion) {
  const media = storyboardVersionCanvasMedia(version)
  return media && mediaPreviewSrc(media) ? media : null
}

export function storyboardVersionNodeDataPatch(
  data: WorkflowNodeData,
  version: StoryboardVersion,
  options: {
    status?: WorkflowNodeData["status"]
    storageMode?: "clear" | "mirror-media"
    includeSourceFileName?: boolean
  } = {}
): Partial<WorkflowNodeData> {
  const media = storyboardVersionDisplayMedia(version)
  const patch: Partial<WorkflowNodeData> = {
    ...(options.status ? { status: options.status } : {}),
    summary: version.summary || data.summary,
    activeVersionId: version.id,
    sourceVersionId: version.id,
    mediaVersionId: version.id,
    activeMediaVersionId: version.id,
    media,
    storage: media && options.storageMode === "mirror-media" ? media : null,
    mediaId: media?.id,
  }
  if (options.includeSourceFileName) {
    patch.sourceFileName = media
      ? data.sourceFileName || media.originalName || media.file || media.path
      : undefined
  }
  const useProjectVisual = recordValue(version.payload).useProjectVisual
  if (data.mediaPurpose === "custom_image" && typeof useProjectVisual === "boolean") {
    patch.useProjectVisual = useProjectVisual
  }
  return patch
}

export function storyboardVersionWithResponseMedia(
  version?: StoryboardVersion | null,
  media?: MediaAsset | null
) {
  if (!version || version.media || !media) return version
  return { ...version, media }
}

export function storyboardVersionForWorkflowMutation(
  data: WorkflowNodeData,
  versions: StoryboardVersion[]
) {
  const activeVersion = versions.find(storyboardVersionIsActive)
  if (activeVersion) return activeVersion
  const hasAnyActiveFlag = versions.some(storyboardVersionHasActiveFlag)
  if (hasAnyActiveFlag) return undefined
  if (versions.length === 1) return versions[0]
  const currentVersionId = workflowNodeDataCurrentVersionId(data)
  return currentVersionId
    ? versions.find((item) => item.id === currentVersionId)
    : undefined
}

/** Shared construction contract for dragged and pasted version assets. */
export function buildStoryboardVersionCanvasAsset({
  version,
  sourceNode,
  position,
  label,
  projectId,
  episodeId,
  workChains,
  routes,
  workflowNodeActions,
  origin = "paste",
}: StoryboardVersionCanvasPlacement & {
  projectId: string
  episodeId: string
  workChains: WorkflowWorkChain[]
  routes: WorkflowRoute[]
  workflowNodeActions: WorkflowNodeActions
  origin?: "drag" | "paste"
}) {
  const versionKind = storyboardVersionPreviewKind(version)
  const sourceIsCustomImage = versionKind === "image" && sourceNode.data.mediaPurpose === "custom_image"
  const versionUseProjectVisual = recordValue(version.payload).useProjectVisual
  const sourceIsVisualHandoff =
    versionKind === "image" && workflowNodeIsVisualHandoffAsset(sourceNode)
  const sourceIsAssetImage =
    versionKind === "image" &&
    (sourceNode.data.eyebrow === "asset.image" ||
      sourceIsVisualHandoff ||
      sourceIsCustomImage ||
      isFrameImage(sourceNode.data))
  const sourceProjectAssetIdentity =
    canvasAssetNodeProjectAssetIdentity(sourceNode)
  const sourceAssetType =
    (sourceIsVisualHandoff ? "visual_handoff" : "") ||
    sourceProjectAssetIdentity.assetType ||
    optionalString(sourceNode.data.assetType) ||
    optionalString(sourceNode.data.assetKind)
  const sourceRootAssetId = sourceProjectAssetIdentity.assetId
  const sourceRootFields = canvasAssetNodeRootFields(sourceNode, projectId)
  const nodeType =
    versionKind === "video"
      ? "video.result"
      : sourceIsVisualHandoff || sourceIsCustomImage || isFrameImage(sourceNode.data)
        ? "media.external"
        : "storyboard.image"
  const assetKind =
    versionKind === "video"
      ? "video"
      : sourceIsAssetImage
        ? sourceAssetType || "asset_image"
        : "storyboard_image"
  const mediaPurpose =
    versionKind === "video"
      ? "video_result"
      : sourceIsVisualHandoff
        ? "visual_handoff"
        : sourceIsAssetImage
          ? sourceNode.data.mediaPurpose ||
            assetTargetSlotForAssetType(sourceAssetType)
          : "storyboard_image"
  const cardSize = defaultWorkflowCardSize(nodeType)
  const nodeId = workflowNodeId(
    versionKind === "video" ? "video_version_asset" : "storyboard_version_asset"
  )
  const now = new Date().toISOString()
  const titleBase = storyboardVersionHistoryDescription(
    sourceNode,
    workChains,
    routes
  )
  const title =
    sourceNode.data.assetName || sourceNode.data.title || titleBase || label
  const summary =
    String(version.summary ?? "").trim() ||
    `${label}，从${
      versionKind === "video"
        ? "视频"
        : sourceIsAssetImage
          ? "资产图片"
          : "分镜图"
    }历史版本${origin === "drag" ? "拖拽创建" : "创建"}的画布素材。`
  const baseNodeData: WorkflowNodeData = {
    projectId: projectId,
    episodeId,
    nodeId,
    title,
    eyebrow: nodeType,
    summary,
    status: "ready",
    tone: workflowTone(nodeType),
  }
  const versionPatch = storyboardVersionNodeDataPatch(baseNodeData, version, {
    status: "ready",
    storageMode: "mirror-media",
  })
  const newNode: StoryboardNode = {
    id: nodeId,
    type: "storyboardNode",
    position,
    deletable: true,
    data: {
      ...baseNodeData,
      visibilityScope: "global",
      sourceType: "version",
      ...(versionKind !== "video"
        ? { canvasNodeRole: CANVAS_NODE_ROLE_IMAGE_ASSET }
        : {}),
      assetScope:
        versionKind === "video"
          ? "result"
          : sourceIsAssetImage
            ? sourceNode.data.assetScope || "reusable"
            : "reusable",
      assetKind,
      assetType: sourceIsAssetImage ? sourceAssetType || assetKind : assetKind,
      ...(sourceIsAssetImage
        ? {
            ...sourceRootFields,
            assetName:
              sourceNode.data.assetName || sourceNode.data.title || title,
            assetVersionId: version.id,
          }
        : { assetName: title }),
      ...versionPatch,
      mediaPurpose,
      ...(sourceIsCustomImage ? {
        useProjectVisual: typeof versionUseProjectVisual === "boolean"
          ? versionUseProjectVisual : sourceNode.data.useProjectVisual ?? true,
      } : {}),
      preferredTargetSlot: sourceIsVisualHandoff
        ? "visual_handoff_reference"
        : mediaPurpose,
      cardState: {
        size: cardSize,
      },
      copiedFromNodeId: sourceNode.id,
      provenance: {
        source: "user",
        action:
          versionKind === "video"
            ? "canvas_asset_node_created_from_video_version"
            : sourceIsAssetImage
              ? "canvas_asset_node_created_from_asset_version"
              : "canvas_asset_node_created_from_storyboard_version",
        createdAt: now,
        copiedFromNodeId: sourceNode.id,
        sourceNodeId: sourceNode.id,
        versionId: version.id,
        mediaVersionId: version.id,
        versionTitle: version.title,
        ...(sourceIsAssetImage
          ? {
              ...(sourceRootAssetId ? { assetId: sourceRootAssetId } : {}),
              assetType: sourceAssetType || assetKind,
              ...(sourceRootAssetId ? sourceRootFields : {}),
              assetName:
                sourceNode.data.assetName || sourceNode.data.title || title,
            }
          : {}),
      },
      onRun: workflowNodeActions.onRun,
      onSaveInlineEdit: workflowNodeActions.onSaveInlineEdit,
      onUpdateNodeData: workflowNodeActions.onUpdateNodeData,
      onUpdateReferenceUsage: workflowNodeActions.onUpdateReferenceUsage,
      onUpdateFrameReference: workflowNodeActions.onUpdateFrameReference,
      onRemoveInputLink: workflowNodeActions.onRemoveInputLink,
      onFocusNode: workflowNodeActions.onFocusNode,
      onSubmitStoryboardImageEdit:
        workflowNodeActions.onSubmitStoryboardImageEdit,
    },
  }

  return { node: newNode, versionKind, sourceIsAssetImage }
}

export function workflowVersionOwnerNodeId(
  node: StoryboardNode,
  nodes: StoryboardNode[],
  edges: StoryboardEdge[]
) {
  if (isWorkflowGeneratedMediaResultNode(node)) {
    return node.id
  }
  return workflowTaskResultNode(node, nodes, edges)?.id || node.id
}

export function workflowVersionRelatedNodeIds(
  nodeId: string,
  nodes: StoryboardNode[],
  edges: StoryboardEdge[]
) {
  const targetIds = new Set<string>([nodeId])
  const anchor = nodes.find((node) => node.id === nodeId)
  const ownerNodeId = anchor
    ? workflowNodeVersionStorageNodeId(nodeId, anchor.data)
    : nodeId
  if (ownerNodeId) targetIds.add(ownerNodeId)
  nodes.forEach((node) => {
    if (
      node.data.resultOfNodeId === nodeId ||
      node.data.sourceNodeId === nodeId ||
      node.data.resultOfNodeId === ownerNodeId ||
      node.data.sourceNodeId === ownerNodeId
    ) {
      targetIds.add(node.id)
    }
  })
  edges.forEach((edge) => {
    if (edge.source === ownerNodeId && isWorkflowTaskResultEdge(edge, nodes)) {
      targetIds.add(edge.target)
    }
    if (edge.target === nodeId && isWorkflowTaskResultEdge(edge, nodes)) {
      targetIds.add(edge.source)
    }
  })
  return targetIds
}
