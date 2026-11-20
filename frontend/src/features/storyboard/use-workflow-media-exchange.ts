import {
  buildStoryboardVersionCanvasAsset,
  storyboardVersionPreviewSrc,
  storyboardVersionPreviewKind,
  storyboardVersionDisplayMedia,
} from "./workflow-version-asset-model"
import { useCallback, useEffect, useState, useRef } from "react"
import { isFrameImage } from "./frame-reference-menu"
import {
  clipboardImageFile,
  clipboardImageInputFile,
  defaultWorkflowCardSize,
  focusedElementAcceptsTextInput,
  inflateCanvasRect,
  isWorkflowAssetNodeType,
  nextCanvasAssetPosition,
  readCanvasAssetClipboard,
  rectsOverlap,
  storyboardVersionIsActive,
  workflowCanvasRect,
  workflowCardSize,
  workflowNodeCurrentVersionId,
  workflowNodeDataClipboardSnapshot,
  workflowNodeId,
  workflowNodeIsVisualHandoffAsset,
  workflowNodeRect,
  workflowNodeVersionStorageNodeId,
  writeCanvasAssetClipboard,
  type CanvasAssetClipboardItem,
  type StoryboardVersionCanvasCopy,
  type StoryboardVersionCanvasDrop,
  type StoryboardVersionCanvasPlacement,
} from "./workflow-canvas-asset-model"
import {
  canvasAssetNodeProjectAssetIdentity,
  canvasAssetNodeRootFields,
} from "./workflow-canvas-assets"
import {
  CANVAS_NODE_ROLE_IMAGE_ASSET,
  canvasMediaReference,
  optionalString,
  type StoryboardNode,
} from "./workflow-canvas-model"
import {
  mediaAssetInputFile,
  videoClipMediaKind,
  videoClipResultInputFile,
  type VideoClipCanvasResult,
  type VideoClipDialogSource,
} from "./video-clip-model"
import { toast } from "sonner"
import { listStoryboardVersions, type InputImageFile } from "@/backend"
import { errMsg } from "@/shared/backend-result"
import { mediaPreviewSrc } from "@/shared/media"
import { mediaDownloadSource } from "@/shared/unified-media-frame"
import { resolveProjectMediaUrl } from "@/utils/style-thumbnails"
import type { BackendCaller, WorkflowWorkChain, WorkflowRoute } from "@/backend"
import type { WorkflowNodeActions } from "./workflow-canvas-model"
import type { WorkflowAssetPersistence } from "./use-workflow-asset-persistence"
import type { WorkflowAssetPicker } from "./use-workflow-asset-picker"

type Point = { x: number; y: number }
type WorkflowMediaExchangeGraph = {
  workChains: WorkflowWorkChain[]
  routes: WorkflowRoute[]
  workflowNodeActions: WorkflowNodeActions
  visibleNodes: StoryboardNode[]
  workChainId: string
  routeIds: Set<string>
}

/** Owns cross-canvas clipboard content, historical-version placement and clip-dialog lifecycle. */
export function useWorkflowMediaExchange({
  projectId,
  episodeId,
  backendReady,
  callBackend,
  readNodes,
  getFlowInstance,
  graph,
  assetPersistence,
  assetPicker,
  dismiss,
}: {
  projectId: string
  episodeId: string
  backendReady: boolean
  callBackend: BackendCaller
  readNodes: () => StoryboardNode[]
  getFlowInstance: () => {
    screenToFlowPosition: (point: Point) => Point
  } | null
  graph: WorkflowMediaExchangeGraph
  assetPersistence: WorkflowAssetPersistence
  assetPicker: WorkflowAssetPicker
  dismiss: (reason: "paste" | "clip" | "clipboard-image") => void
}) {
  const {
    workChains,
    routes,
    workflowNodeActions,
    visibleNodes,
    workChainId: selectedWorkChainId,
    routeIds: selectedWorkChainRouteIds,
  } = graph
  const workChainFilterActive = Boolean(
    selectedWorkChainId && selectedWorkChainId !== "all"
  )
  const { assetDraft, open: openAddAssetDialog } = assetPicker
  const scopeKey = `${projectId}\u0000${episodeId}`
  const scopeRef = useRef({ key: scopeKey })
  if (scopeRef.current.key !== scopeKey) scopeRef.current = { key: scopeKey }
  useEffect(() => {
    setCopiedAssetClipboard((current) => current ?? readCanvasAssetClipboard())
  }, [episodeId])
  const [videoClipDialogSource, setVideoClipDialogSource] =
    useState<VideoClipDialogSource | null>(null)

  const [copiedAssetClipboard, setCopiedAssetClipboard] =
    useState<CanvasAssetClipboardItem | null>(() => readCanvasAssetClipboard())

  const handleCreateStoryboardVersionCanvasAsset = useCallback(
    async ({
      version,
      sourceNode,
      screenPosition,
      label,
    }: StoryboardVersionCanvasDrop) => {
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const versionKind = storyboardVersionPreviewKind(version)
      const flowInstance = getFlowInstance()
      if (!flowInstance || typeof document === "undefined") {
        toast.error("画布尚未就绪")
        return
      }
      const elementAtPoint = document.elementFromPoint(
        screenPosition.x,
        screenPosition.y
      )
      if (
        elementAtPoint instanceof Element &&
        elementAtPoint.closest("[data-slot='dialog-content']")
      ) {
        return
      }
      const flowElement = document.querySelector<HTMLElement>(".react-flow")
      const flowRect = flowElement?.getBoundingClientRect()
      if (
        !flowRect ||
        screenPosition.x < flowRect.left ||
        screenPosition.x > flowRect.right ||
        screenPosition.y < flowRect.top ||
        screenPosition.y > flowRect.bottom
      ) {
        toast.info("请拖到画布区域后松开")
        return
      }
      const media = storyboardVersionDisplayMedia(version)
      if (!media) {
        toast.error(
          versionKind === "video" ? "该版本没有可用视频" : "该版本没有可用图片"
        )
        return
      }

      const { node: newNode, sourceIsAssetImage } =
        buildStoryboardVersionCanvasAsset({
          version,
          sourceNode,
          position: { x: 0, y: 0 },
          label,
          projectId: projectId,
          episodeId,
          workChains,
          routes,
          workflowNodeActions,
          origin: "drag",
        })
      const cardSize = defaultWorkflowCardSize(newNode.data.eyebrow)
      const flowPosition = flowInstance.screenToFlowPosition(screenPosition)
      newNode.position = {
        x: flowPosition.x - cardSize.width / 2,
        y: flowPosition.y - cardSize.height / 2,
      }
      await assetPersistence.addNodes(
        [newNode],
        versionKind === "video"
          ? "canvas_asset_node_created_from_video_version"
          : sourceIsAssetImage
            ? "canvas_asset_node_created_from_asset_version"
            : "canvas_asset_node_created_from_storyboard_version",
        {
          successMessage: "已拖动到画布",
          errorMessage:
            versionKind === "video"
              ? "创建视频素材卡片失败"
              : sourceIsAssetImage
                ? "创建设计图素材卡片失败"
                : "创建分镜图素材卡片失败",
          selectOnConfirmation: true,
        }
      )
    },
    [
      backendReady,
      episodeId,
      assetPersistence.addNodes,
      projectId,
      routes,
      workChains,
      workflowNodeActions,
      callBackend,
      getFlowInstance,
    ]
  )

  const handleCopyStoryboardVersionCanvasAsset = useCallback(
    ({ version, sourceNode, label }: StoryboardVersionCanvasCopy) => {
      const media = storyboardVersionDisplayMedia(version)
      const versionKind = storyboardVersionPreviewKind(version)
      if (!media) {
        toast.error(
          versionKind === "video" ? "该版本没有可用视频" : "该版本没有可用图片"
        )
        return
      }
      const sourceIsVisualHandoff =
        versionKind === "image" && workflowNodeIsVisualHandoffAsset(sourceNode)
      const sourceIsAssetImage =
        versionKind === "image" &&
        (sourceNode.data.eyebrow === "asset.image" ||
          sourceIsVisualHandoff ||
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
      const assetKind =
        versionKind === "video"
          ? "video"
          : sourceIsAssetImage
            ? sourceAssetType || "asset_image"
            : "storyboard_image"
      const clipboard: CanvasAssetClipboardItem = {
        schemaVersion: 1,
        kind: "ai_video_canvas_asset",
        clipboardSource: "version",
        sourceProjectId: projectId,
        sourceEpisodeId: episodeId,
        sourceNodeId: sourceNode.id,
        sourceNodeType: sourceNode.data.eyebrow,
        title: sourceNode.data.assetName || sourceNode.data.title || label,
        mediaKind: versionKind,
        media,
        preview:
          storyboardVersionPreviewSrc(version) ||
          mediaPreviewSrc(media) ||
          undefined,
        mediaSourceType: "version",
        sourceVersionId: version.id,
        version,
        versionLabel: label,
        sourceNodeData: workflowNodeDataClipboardSnapshot(sourceNode.data),
        assetScope:
          versionKind === "video"
            ? "result"
            : sourceIsAssetImage
              ? sourceNode.data.assetScope || "reusable"
              : "reusable",
        assetKind,
        assetType: sourceIsAssetImage
          ? sourceAssetType || assetKind
          : assetKind,
        ...(sourceIsAssetImage && sourceRootAssetId ? sourceRootFields : {}),
        canvasNodeRole:
          versionKind !== "video" ? CANVAS_NODE_ROLE_IMAGE_ASSET : undefined,
        copiedAt: new Date().toISOString(),
      }
      setCopiedAssetClipboard(clipboard)
      writeCanvasAssetClipboard(clipboard)
      toast.success("资产已复制，可在画布空白处右键粘贴")
    },
    [episodeId, projectId]
  )

  const importCanvasMediaAssetToCanvas = useCallback(
    async ({
      file,
      mediaKind,
      title,
      position,
      sourceNode,
      mediaId,
      sourceType,
      mediaPurpose = "auto",
      assetName = title,
      assetScope,
      assetKind,
      assetType,
      canvasNodeRole = CANVAS_NODE_ROLE_IMAGE_ASSET,
      note,
      successMessage = "资产已粘贴",
      errorMessage = "粘贴资产失败",
    }: {
      file: InputImageFile
      mediaKind: "image" | "video"
      title: string
      position: { x: number; y: number }
      sourceNode?: StoryboardNode | null
      mediaId?: string
      sourceType?: string
      mediaPurpose?: string
      assetName?: string
      assetScope?: string
      assetKind?: string
      assetType?: string
      canvasNodeRole?: string
      note?: string
      successMessage?: string
      errorMessage?: string
    }) => {
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return false
      }
      const mediaNodeId = workflowNodeId("media_external")
      const workChainId = String(sourceNode?.data.workChainId ?? "").trim()
      const visibilityScope = workChainId ? "workChain" : "global"
      return assetPersistence.importMedia(
        {
          file,
          mediaId: mediaId || file.id,
          mediaNodeId,
          mediaKind,
          mediaPurpose,
          title,
          assetName,
          visibilityScope,
          scope: visibilityScope,
          ...(workChainId ? { workChainId } : {}),
          ...(sourceType ? { sourceType } : {}),
          ...(assetScope ? { assetScope } : {}),
          ...(assetKind ? { assetKind } : {}),
          ...(assetType ? { assetType } : {}),
          ...(canvasNodeRole ? { canvasNodeRole } : {}),
          position,
          ...(note ? { note } : {}),
          returnProductionStatus: false,
        },
        { successMessage, errorMessage }
      )
    },
    [
      assetPersistence.importMedia,
      backendReady,
      episodeId,
      projectId,
      routes,
      workflowNodeActions,
      callBackend,
    ]
  )

  const createStoryboardVersionCanvasAssetAtPosition = useCallback(
    async ({
      version,
      sourceNode,
      position,
      label,
    }: StoryboardVersionCanvasPlacement) => {
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return false
      }
      const versionKind = storyboardVersionPreviewKind(version)
      const media = storyboardVersionDisplayMedia(version)
      if (!media) {
        toast.error(
          versionKind === "video" ? "该版本没有可用视频" : "该版本没有可用图片"
        )
        return false
      }

      const { node: newNode, sourceIsAssetImage } =
        buildStoryboardVersionCanvasAsset({
          version,
          sourceNode,
          position,
          label,
          projectId: projectId,
          episodeId,
          workChains,
          routes,
          workflowNodeActions,
        })
      return assetPersistence.addNodes(
        [newNode],
        versionKind === "video"
          ? "canvas_asset_node_created_from_video_version"
          : sourceIsAssetImage
            ? "canvas_asset_node_created_from_asset_version"
            : "canvas_asset_node_created_from_storyboard_version",
        {
          successMessage: "资产已粘贴",
          errorMessage: "粘贴资产失败",
          selectOnConfirmation: true,
        }
      )
    },
    [
      backendReady,
      episodeId,
      assetPersistence.addNodes,
      projectId,
      routes,
      workChains,
      workflowNodeActions,
      callBackend,
    ]
  )

  const handlePasteCanvasAssetNode = useCallback(
    async (position: { x: number; y: number }) => {
      const clipboard = copiedAssetClipboard ?? readCanvasAssetClipboard()
      if (!clipboard) {
        toast.info("还没有复制的资产")
        return
      }
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      if (clipboard.sourceProjectId !== projectId) {
        toast.info("暂不支持跨项目粘贴资产")
        return
      }
      const clipboardSource = clipboard.clipboardSource ?? "node"
      if (clipboardSource === "media") {
        const media = clipboard.media
        if (!media) {
          toast.info("当前复制内容不是资产")
          return
        }
        const mediaKind = clipboard.mediaKind || videoClipMediaKind(media)
        const title =
          clipboard.title ||
          media.originalName ||
          media.id ||
          (mediaKind === "video" ? "复制视频" : "复制图片")
        const file = mediaAssetInputFile(
          media,
          title,
          mediaKind,
          clipboard.preview
        )
        dismiss("paste")
        await importCanvasMediaAssetToCanvas({
          file,
          mediaKind,
          mediaId: media.id || file.id,
          title,
          position,
          sourceType: clipboard.mediaSourceType || "media",
          mediaPurpose: clipboard.mediaPurpose || "auto",
          assetName: title,
          assetScope: clipboard.assetScope,
          assetKind: clipboard.assetKind,
          assetType: clipboard.assetType,
          canvasNodeRole:
            clipboard.canvasNodeRole || CANVAS_NODE_ROLE_IMAGE_ASSET,
          note:
            clipboard.mediaSourceType === "video_clip_result"
              ? "来自视频剪辑"
              : undefined,
        })
        return
      }
      if (clipboardSource === "version") {
        if (
          !clipboard.version ||
          !clipboard.sourceNodeId ||
          !clipboard.sourceNodeData
        ) {
          toast.info("当前复制内容不是资产")
          return
        }
        const sourceNodeData = clipboard.sourceNodeData
        const sourceNode = {
          id: clipboard.sourceNodeId,
          type: "storyboardNode",
          position: { x: 0, y: 0 },
          data: {
            ...sourceNodeData,
            projectId: sourceNodeData.projectId || clipboard.sourceProjectId,
            episodeId: sourceNodeData.episodeId || clipboard.sourceEpisodeId,
            nodeId: sourceNodeData.nodeId || clipboard.sourceNodeId,
            eyebrow:
              sourceNodeData.eyebrow ||
              clipboard.sourceNodeType ||
              "media.external",
          },
        } as StoryboardNode
        dismiss("paste")
        await createStoryboardVersionCanvasAssetAtPosition({
          version: clipboard.version,
          sourceNode,
          position,
          label: clipboard.versionLabel || clipboard.title || "历史版本",
        })
        return
      }
      if (
        clipboard.sourceNodeType &&
        !isWorkflowAssetNodeType(clipboard.sourceNodeType)
      ) {
        toast.info("当前复制内容不是资产")
        return
      }
      if (!clipboard.sourceNodeId) {
        toast.info("当前复制内容不是资产")
        return
      }
      dismiss("paste")
      await assetPersistence.pasteNode({
        sourceProjectId: clipboard.sourceProjectId,
        sourceEpisodeId: clipboard.sourceEpisodeId,
        sourceNodeId: clipboard.sourceNodeId,
        sourceNodeType: clipboard.sourceNodeType,
        position,
        reason: "canvas_asset_node_pasted",
      })
    },
    [
      backendReady,
      copiedAssetClipboard,
      createStoryboardVersionCanvasAssetAtPosition,
      assetPersistence.pasteNode,
      episodeId,
      importCanvasMediaAssetToCanvas,
      projectId,
      routes,
      workflowNodeActions,
      callBackend,
      dismiss,
    ]
  )

  const resolveVideoClipDialogSource = useCallback(
    async (node: StoryboardNode): Promise<VideoClipDialogSource | null> => {
      const requestScope = scopeRef.current
      const current = () => scopeRef.current === requestScope
      const directMedia = canvasMediaReference(
        node.data.media ?? node.data.storage ?? null
      )
      let media = directMedia
      if (!mediaDownloadSource(media)?.path) {
        const versionId = workflowNodeCurrentVersionId(node)
        if (versionId && backendReady) {
          try {
            const versions = await listStoryboardVersions(
              callBackend,
              projectId,
              episodeId,
              workflowNodeVersionStorageNodeId(node.id, node.data)
            )
            if (!current()) return null
            const selectedVersion =
              versions.find((version) => version.id === versionId) ??
              versions.find(storyboardVersionIsActive)
            media = canvasMediaReference(selectedVersion?.media ?? null)
          } catch (error) {
            if (!current()) return null
            toast.error(errMsg(error, "读取视频版本失败"))
            return null
          }
        }
      }
      const source = mediaDownloadSource(media)
      if (!media || !source?.path) {
        toast.info("当前视频没有可剪辑的本地文件")
        return null
      }
      const src =
        (await resolveProjectMediaUrl(projectId, media)) ||
        mediaPreviewSrc(media)
      if (!current()) return null
      if (!src) {
        toast.info("当前视频无法预览")
        return null
      }
      return {
        nodeId: node.id,
        title: node.data.title || source.name || "视频",
        media,
        src,
        position: node.position,
      }
    },
    [backendReady, episodeId, projectId, callBackend]
  )

  const handleOpenVideoClipDialog = useCallback(
    async (node: StoryboardNode) => {
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const requestScope = scopeRef.current
      const source = await resolveVideoClipDialogSource(node)
      if (scopeRef.current !== requestScope) return
      if (!source) return
      dismiss("clip")
      setVideoClipDialogSource(source)
    },
    [backendReady, resolveVideoClipDialogSource, dismiss]
  )

  const nextVideoClipResultPosition = useCallback(
    (
      sourceNode?: StoryboardNode | null,
      explicitPosition?: { x: number; y: number }
    ) => {
      if (explicitPosition) return explicitPosition
      if (!sourceNode) {
        return nextCanvasAssetPosition(
          readNodes(),
          visibleNodes,
          workChainFilterActive ? selectedWorkChainId : "all",
          selectedWorkChainRouteIds
        )
      }
      const sourceSize = workflowCardSize(sourceNode.data)
      const resultSize = defaultWorkflowCardSize("media.external")
      const stepX = resultSize.width + 48
      let candidate = {
        x: sourceNode.position.x + sourceSize.width + 72,
        y: sourceNode.position.y,
      }
      for (let index = 0; index < 80; index += 1) {
        const candidateRect = workflowCanvasRect(candidate, resultSize)
        const overlaps = readNodes().some((node) => {
          if (node.id === sourceNode.id) return false
          return rectsOverlap(
            inflateCanvasRect(candidateRect, 12),
            inflateCanvasRect(workflowNodeRect(node), 8)
          )
        })
        if (!overlaps) return candidate
        candidate = { ...candidate, x: candidate.x + stepX }
      }
      return candidate
    },
    [
      selectedWorkChainId,
      selectedWorkChainRouteIds,
      visibleNodes,
      workChainFilterActive,
      readNodes,
    ]
  )

  const handleSendVideoClipResultToCanvas = useCallback(
    async (
      result: VideoClipCanvasResult,
      explicitPosition?: { x: number; y: number }
    ) => {
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const sourceNode = videoClipDialogSource
        ? readNodes().find((node) => node.id === videoClipDialogSource.nodeId)
        : null
      const position = nextVideoClipResultPosition(sourceNode, explicitPosition)
      const file = videoClipResultInputFile(result)
      await importCanvasMediaAssetToCanvas({
        file,
        mediaKind: result.kind,
        mediaId: file.id,
        title: result.title,
        position,
        sourceNode,
        sourceType: "video_clip_result",
        mediaPurpose: result.kind === "image" ? "frame_image" : "auto",
        assetName: result.title,
        assetScope: "result",
        assetKind: result.kind === "video" ? "video" : "frame_image",
        canvasNodeRole: CANVAS_NODE_ROLE_IMAGE_ASSET,
        note: "来自视频剪辑",
        successMessage: "已拖动到画布",
        errorMessage: "拖动到画布失败",
      })
    },
    [
      backendReady,
      importCanvasMediaAssetToCanvas,
      nextVideoClipResultPosition,
      videoClipDialogSource,
      readNodes,
    ]
  )

  const handleCopyVideoClipResultAsset = useCallback(
    (result: VideoClipCanvasResult) => {
      const sourceNode = videoClipDialogSource
        ? readNodes().find((node) => node.id === videoClipDialogSource.nodeId)
        : null
      const clipboard: CanvasAssetClipboardItem = {
        schemaVersion: 1,
        kind: "ai_video_canvas_asset",
        clipboardSource: "media",
        sourceProjectId: projectId,
        sourceEpisodeId: episodeId,
        sourceNodeId: sourceNode?.id,
        sourceNodeType: sourceNode?.data.eyebrow,
        title: result.title,
        mediaKind: result.kind,
        media: result.media,
        preview: result.src,
        mediaSourceType: "video_clip_result",
        mediaPurpose: result.kind === "image" ? "frame_image" : "auto",
        assetScope: "result",
        assetKind: result.kind === "video" ? "video" : "frame_image",
        canvasNodeRole: CANVAS_NODE_ROLE_IMAGE_ASSET,
        copiedAt: new Date().toISOString(),
      }
      setCopiedAssetClipboard(clipboard)
      writeCanvasAssetClipboard(clipboard)
      toast.success("资产已复制，可在画布空白处右键粘贴")
    },
    [episodeId, projectId, videoClipDialogSource, readNodes]
  )

  const handleDropVideoClipResultToCanvas = useCallback(
    (
      result: VideoClipCanvasResult,
      screenPosition: { x: number; y: number }
    ) => {
      const flowElement = document.querySelector<HTMLElement>(".react-flow")
      const flowRect = flowElement?.getBoundingClientRect()
      if (
        !flowRect ||
        screenPosition.x < flowRect.left ||
        screenPosition.x > flowRect.right ||
        screenPosition.y < flowRect.top ||
        screenPosition.y > flowRect.bottom
      ) {
        toast.info("请拖到画布区域后松开")
        return
      }
      const flowInstance = getFlowInstance()
      if (!flowInstance) {
        toast.error("画布尚未就绪")
        return
      }
      const flowPosition = flowInstance.screenToFlowPosition(screenPosition)
      const resultSize = defaultWorkflowCardSize("media.external")
      const position = {
        x: flowPosition.x - resultSize.width / 2,
        y: flowPosition.y - resultSize.height / 2,
      }
      void handleSendVideoClipResultToCanvas(result, position)
    },
    [handleSendVideoClipResultToCanvas, getFlowInstance]
  )

  const availableCopiedAssetClipboard =
    copiedAssetClipboard ?? readCanvasAssetClipboard()
  useEffect(() => {
    if (typeof window === "undefined") return
    const handlePaste = (event: ClipboardEvent) => {
      if (
        assetDraft ||
        videoClipDialogSource ||
        focusedElementAcceptsTextInput(event.target)
      ) {
        return
      }
      const hasImage = Boolean(clipboardImageFile(event))
      if (!hasImage) return
      event.preventDefault()
      void (async () => {
        const instance = getFlowInstance()
        const flowElement = document.querySelector<HTMLElement>(".react-flow")
        const rect = flowElement?.getBoundingClientRect()
        const placementPosition =
          instance && rect
            ? instance.screenToFlowPosition({
                x: rect.left + rect.width / 2,
                y: rect.top + rect.height / 2,
              })
            : nextCanvasAssetPosition(
                readNodes(),
                visibleNodes,
                workChainFilterActive ? selectedWorkChainId : "all",
                selectedWorkChainRouteIds
              )
        const requestScope = scopeRef.current
        try {
          const inputFile = await clipboardImageInputFile(event)
          if (!inputFile || scopeRef.current !== requestScope) return
          const title = String(inputFile.name || "粘贴图片")
            .replace(/\.[a-z0-9]+$/i, "")
            .trim()
          openAddAssetDialog("media", placementPosition, {
            mediaFile: inputFile,
            mediaPurpose: "character_reference",
            title: title || "粘贴图片",
          })
          dismiss("clipboard-image")
          toast.success("已读取剪贴板图片")
        } catch (error) {
          if (scopeRef.current !== requestScope) return
          toast.error(errMsg(error, "读取剪贴板图片失败"))
        }
      })()
    }
    window.addEventListener("paste", handlePaste)
    return () => window.removeEventListener("paste", handlePaste)
  }, [
    assetDraft,
    getFlowInstance,
    readNodes,
    dismiss,
    openAddAssetDialog,
    selectedWorkChainId,
    selectedWorkChainRouteIds,
    videoClipDialogSource,
    visibleNodes,
    workChainFilterActive,
  ])

  useEffect(() => {
    if (scopeRef.current.key !== scopeKey) scopeRef.current = { key: scopeKey }
    setVideoClipDialogSource(null)
    const scope = scopeRef.current
    return () => {
      if (scopeRef.current === scope) scopeRef.current = { key: "" }
    }
  }, [scopeKey])
  return {
    clipboard: availableCopiedAssetClipboard,
    acceptCopied: setCopiedAssetClipboard,
    clipSource: videoClipDialogSource,
    setClipSource: setVideoClipDialogSource,
    createVersionAsset: handleCreateStoryboardVersionCanvasAsset,
    copyVersion: handleCopyStoryboardVersionCanvasAsset,
    paste: handlePasteCanvasAssetNode,
    openClip: handleOpenVideoClipDialog,
    sendClipResult: handleSendVideoClipResultToCanvas,
    copyClipResult: handleCopyVideoClipResultAsset,
    dropClipResult: handleDropVideoClipResultToCanvas,
  }
}
