import { type AssetItem,type AssetType,type InputImageFile,type MediaAsset,type StoryboardVersion,type WorkflowRoute,type WorkflowWorkChain } from "@/backend"
import { cn } from "@/lib/utils"
import { mediaPreviewSrc } from "@/shared/media"
import { Position } from "@xyflow/react"
import { isFrameImage } from "./frame-reference-menu"
import { type SourceSplitSegment } from "./source-split-model"
import { canvasProjectAssetTypeFromNode, mediaPurposeMaterialSlot } from "./workflow-canvas-assets"
import { type StoryboardEdge,type StoryboardNode,WORKFLOW_ASSET_INPUT_HANDLE,WORKFLOW_VIDEO_INPUT_HANDLE,type WorkflowNodeData,type WorkflowNodeDataLookup,type WorkflowNodeLike,canonicalTargetSlot,canonicalWorkflowInputHandle,canvasMediaReference,isDirectorBoardNodeType,isStoryboardCardNodeType,isWorkflowResultImageType,isWorkflowVideoTaskType,optionalString,promptTextForNode,recordValue,sourceTextForNode,workflowNodeDataCurrentVersionId,workflowNodeDataIsIndependentImageAsset,workflowNodeDataIsWorkChainStoryboardResult,workflowVideoTaskCardDataIsReady,workflowVideoTaskScope } from "./workflow-canvas-model"
import { appendInputLinkThumbnailRows,filterRemovedInputAssetRefs,filterRemovedInputLinkIds,filterRemovedInputLinkRows,inputLinkMatchesAnyDirectId,inputLinkReferenceMediaIds,isImageReferenceMediaType,isVideoReferenceMediaType,statusAfterInputLinkChange,workflowNodeCanSupplyImageReference } from "./workflow-input-readiness"
import { workflowTaskIsRunningForPrimaryDisplay,workflowTaskMatchesTaskCardPrimaryState } from "./workflow-task-status"

export type FloatingMenuPosition = { x: number; y: number }

export type CanvasContextMenuState = FloatingMenuPosition & {
  flowPosition: { x: number; y: number }
}

export type NodeContextMenuState = FloatingMenuPosition & { nodeId: string }

export type EdgeContextMenuState = FloatingMenuPosition & { edgeId: string }

export type NodeDetailsState = FloatingMenuPosition & { nodeId: string }

export type SourceSplitEditorState = {
  independent: boolean
  needsApply: boolean
  nodeId: string
  sourceText: string
  segments: SourceSplitSegment[]
  originalSegments: SourceSplitSegment[]
  mode: "split" | "edit"
  workChainIds: string[]
  generatedCount: number
}

export type StoryboardImageEditState = { nodeId: string }

export const CANVAS_ASSET_CLIPBOARD_KEY = "ai-video:canvas-asset-clipboard:v1"

export type CanvasAssetClipboardItem = {
  schemaVersion: 1
  kind: "ai_video_canvas_asset"
  clipboardSource?: "node" | "media" | "version"
  sourceProjectId: string
  sourceEpisodeId: string
  sourceNodeId?: string
  sourceNodeType?: string
  title?: string
  mediaKind?: "image" | "video"
  media?: MediaAsset
  preview?: string
  mediaSourceType?: string
  mediaPurpose?: string
  assetScope?: string
  assetKind?: string
  assetType?: string
  rootAssetId?: string
  rootAssetType?: string
  rootAssetProjectId?: string
  canvasNodeRole?: string
  sourceVersionId?: string
  version?: StoryboardVersion
  versionLabel?: string
  sourceNodeData?: Partial<WorkflowNodeData>
  copiedAt: string
}

export function readCanvasAssetClipboard(): CanvasAssetClipboardItem | null {
  if (typeof window === "undefined") return null
  try {
    const raw = window.localStorage.getItem(CANVAS_ASSET_CLIPBOARD_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<CanvasAssetClipboardItem> | null
    if (
      !parsed ||
      parsed.schemaVersion !== 1 ||
      parsed.kind !== "ai_video_canvas_asset" ||
      !parsed.sourceProjectId ||
      !parsed.sourceEpisodeId
    ) {
      return null
    }
    const clipboardSource =
      parsed.clipboardSource === "media" || parsed.clipboardSource === "version"
        ? parsed.clipboardSource
        : "node"
    if (clipboardSource === "node" && !parsed.sourceNodeId) {
      return null
    }
    if (
      clipboardSource === "media" &&
      (!parsed.media || typeof parsed.media !== "object")
    ) {
      return null
    }
    if (
      clipboardSource === "version" &&
      (!parsed.version ||
        typeof parsed.version !== "object" ||
        !parsed.sourceNodeId ||
        !parsed.sourceNodeData ||
        typeof parsed.sourceNodeData !== "object")
    ) {
      return null
    }
    return {
      schemaVersion: 1,
      kind: "ai_video_canvas_asset",
      clipboardSource,
      sourceProjectId: String(parsed.sourceProjectId),
      sourceEpisodeId: String(parsed.sourceEpisodeId),
      sourceNodeId: parsed.sourceNodeId
        ? String(parsed.sourceNodeId)
        : undefined,
      sourceNodeType: parsed.sourceNodeType
        ? String(parsed.sourceNodeType)
        : undefined,
      title: parsed.title ? String(parsed.title) : undefined,
      mediaKind:
        parsed.mediaKind === "video" || parsed.mediaKind === "image"
          ? parsed.mediaKind
          : undefined,
      media:
        parsed.media && typeof parsed.media === "object"
          ? (parsed.media as MediaAsset)
          : undefined,
      preview: parsed.preview ? String(parsed.preview) : undefined,
      mediaSourceType: parsed.mediaSourceType
        ? String(parsed.mediaSourceType)
        : undefined,
      mediaPurpose: parsed.mediaPurpose
        ? String(parsed.mediaPurpose)
        : undefined,
      assetScope: parsed.assetScope ? String(parsed.assetScope) : undefined,
      assetKind: parsed.assetKind ? String(parsed.assetKind) : undefined,
      assetType: parsed.assetType ? String(parsed.assetType) : undefined,
      rootAssetId: parsed.rootAssetId ? String(parsed.rootAssetId) : undefined,
      rootAssetType: parsed.rootAssetType
        ? String(parsed.rootAssetType)
        : undefined,
      rootAssetProjectId: parsed.rootAssetProjectId
        ? String(parsed.rootAssetProjectId)
        : undefined,
      canvasNodeRole: parsed.canvasNodeRole
        ? String(parsed.canvasNodeRole)
        : undefined,
      sourceVersionId: parsed.sourceVersionId
        ? String(parsed.sourceVersionId)
        : undefined,
      version:
        parsed.version && typeof parsed.version === "object"
          ? (parsed.version as StoryboardVersion)
          : undefined,
      versionLabel: parsed.versionLabel
        ? String(parsed.versionLabel)
        : undefined,
      sourceNodeData:
        parsed.sourceNodeData && typeof parsed.sourceNodeData === "object"
          ? (parsed.sourceNodeData as Partial<WorkflowNodeData>)
          : undefined,
      copiedAt: String(parsed.copiedAt || ""),
    }
  } catch {
    return null
  }
}

export function writeCanvasAssetClipboard(item: CanvasAssetClipboardItem) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(
      CANVAS_ASSET_CLIPBOARD_KEY,
      JSON.stringify(item)
    )
  } catch {
    // Restricted webviews may block localStorage; in-memory state still covers this session.
  }
}

export function workflowNodeDataClipboardSnapshot(
  data: WorkflowNodeData
): Partial<WorkflowNodeData> {
  try {
    return JSON.parse(JSON.stringify(data)) as Partial<WorkflowNodeData>
  } catch {
    return {
      projectId: data.projectId,
      episodeId: data.episodeId,
      nodeId: data.nodeId,
      title: data.title,
      eyebrow: data.eyebrow,
      assetName: data.assetName,
      assetKind: data.assetKind,
      assetType: data.assetType,
      rootAssetId: data.rootAssetId,
      rootAssetType: data.rootAssetType,
      rootAssetProjectId: data.rootAssetProjectId,
      assetScope: data.assetScope,
      mediaPurpose: data.mediaPurpose,
      workChainId: data.workChainId,
      routeId: data.routeId,
      segmentId: data.segmentId,
    }
  }
}

export type NodeEditHistoryDialogState = { nodeId: string }

export type NodeVersionHistoryDialogState = { nodeId: string }

export type GenerationPreflightDialogState = { message: string }

export type NewWorkflowTaskType = "video.storyboard" | "video.keyframe" | "video.character_replace"

export type AddAssetKind = "character" | "creature" | "scene" | "prop" | "media"

export type ExternalMediaPurpose =
  | "custom_image"
  | "video"
  | "frame_image"
  | "character_reference"
  | "creature_reference"
  | "scene_reference"
  | "prop_reference"
  | "storyboard_image"
  | "visual_handoff"
  | "visual_reference"

export type AddAssetDraft = {
  kind: AddAssetKind
  selectedAssetId: string
  selectedAssetIds: string[]
  selectedMediaVersionId?: string
  selectedMediaVersionIds?: Record<string, string>
  mediaFile?: InputImageFile | null
  mediaPurpose: ExternalMediaPurpose
  title: string
  note: string
  voiceStyle: string
  placementPosition?: { x: number; y: number }
}

export type RenameAssetKind = "image" | "video"

export type RenameAssetDraft = {
  nodeId: string
  kind: RenameAssetKind
  mediaPurpose: ExternalMediaPurpose | "video_result"
  title: string
  voiceStyle: string
}

export type AddAssetKindConfig = {
  title: string
  tabLabel: string
  noun: string
  sourceType: "asset" | "media"
  assetType?: Extract<
    AssetType,
    "characters" | "creatures" | "scenes" | "props"
  >
}

export type WorkflowCardSize = {
  width: number
  height: number
  minWidth: number
  minHeight: number
  maxWidth?: number
  maxHeight?: number
}

export const ADD_ASSET_LAST_KIND_KEY = "ai-video.storyboard.addAsset.lastKind"

export const CANVAS_ASSET_PICKER_BATCH_SIZE = 72

export const CANVAS_ASSET_HORIZONTAL_GAP = 180

export const CANVAS_ASSET_VERTICAL_GAP = 112

export const CANVAS_ASSET_LAYOUT_VIEWPORT_MARGIN = 32

export const EXTERNAL_MEDIA_PURPOSE_OPTIONS: Array<{
  value: ExternalMediaPurpose
  label: string
}> = [
  { value: "character_reference", label: "角色" },
  { value: "creature_reference", label: "生物" },
  { value: "scene_reference", label: "场景" },
  { value: "prop_reference", label: "道具" },
  { value: "storyboard_image", label: "分镜图" },
  { value: "visual_handoff", label: "视觉交接" },
  { value: "custom_image", label: "自定义图片" },
  { value: "video", label: "视频" },
]

export const RENAME_IMAGE_MEDIA_PURPOSE_OPTIONS: Array<{
  value: ExternalMediaPurpose
  label: string
}> = [
  { value: "character_reference", label: "角色" },
  { value: "creature_reference", label: "生物" },
  { value: "scene_reference", label: "场景" },
  { value: "prop_reference", label: "道具" },
  { value: "storyboard_image", label: "分镜图" },
  { value: "visual_handoff", label: "视觉交接图" },
  { value: "custom_image", label: "自定义图片" },
]

export function externalMediaPurposeOption(value?: string | null) {
  const normalizedValue =
    value === "visual_reference" ? "storyboard_image" : value
  return (
    EXTERNAL_MEDIA_PURPOSE_OPTIONS.find(
      (option) => option.value === normalizedValue
    ) ?? EXTERNAL_MEDIA_PURPOSE_OPTIONS[0]
  )
}

export function externalMediaPurposeSummary(value?: string | null) {
  const option = externalMediaPurposeOption(value)
  return option.label
}

export function externalMediaTitleFieldLabel(value?: string | null) {
  if (value === "custom_image") return "图片标题"
  if (value === "visual_handoff") return "视觉交接名称"
  return value === "storyboard_image" || value === "visual_reference"
    ? "分镜图名称"
    : `${externalMediaPurposeSummary(value)}名称`
}

export function externalMediaTitleFieldPlaceholder(value?: string | null) {
  if (value === "custom_image") return "输入图片标题"
  if (value === "visual_handoff") return "输入视觉交接名称"
  return value === "storyboard_image" || value === "visual_reference"
    ? "输入分镜图名称"
    : `输入${externalMediaPurposeSummary(value)}名称`
}

export function externalMediaPurposeRequiresFile(value?: string | null) {
  return value === "visual_handoff" || value === "video"
}

export function externalMediaAssetScope(value?: string | null): "reusable" | "result" {
  return value === "storyboard_image" ||
    value === "visual_reference" ||
    value === "visual_handoff" ||
    value === "video"
    ? "result"
    : "reusable"
}

export const CANVAS_TASK_NODE_OPTIONS: Array<{
  type: NewWorkflowTaskType
  label: string
  summary: string
  generationConfig?: Record<string, unknown>
  strategy?: string
}> = [
  {
    type: "video.storyboard",
    label: "新建视频生成",
    summary: "接入图片资产，直接填写提示词并生成独立视频。",
    strategy: "image_reference_video",
    generationConfig: {
      strategy: "image_reference_video",
      videoInputMode: "image_reference",
      inputMode: "image_reference",
      referenceMode: "image_reference",
    },
  },
  {
    type: "video.keyframe",
    label: "新建首尾帧视频生成",
    summary: "以原生首帧或首尾帧生成视频，按模型能力添加参考素材。",
    strategy: "native_keyframe_video",
    generationConfig: {
      strategy: "native_keyframe_video",
      videoInputMode: "native_keyframe",
      inputMode: "native_keyframe",
      referenceMode: "native_keyframe",
    },
  },
  {
    type: "video.character_replace",
    label: "新建角色替换视频生成",
    summary: "接入一段源视频与角色图，替换角色并沿用原片表演、镜头和原声。",
    strategy: "character_replace_video",
    generationConfig: {
      strategy: "character_replace_video",
      videoInputMode: "character_replace",
      inputMode: "character_replace",
      referenceMode: "character_replace",
      resolution: "768p",
      durationSeconds: 10,
    },
  },
]

export const CANVAS_LOCAL_PROJECT_CHANGED_ACTIONS = new Set([
  "canvas_result_committed",
  "workflow_input_linked",
  "workflow_input_unlinked",
  "workflow_reference_usage_updated",
  "workflow_media_imported",
  "workflow_asset_nodes_added",
  "workflow_task_card_created",
  "workflow_item_upserted",
  "workflow_asset_node_renamed",
  "workflow_route_updated",
  "workflow_item_deleted",
  "workflow_node_layout_updated",
  "workflow_node_inline_saved",
  "node_edit_history_restored",
  "node_edit_history_deleted",
  "canvas_asset_images_resolved",
  "workflow_cinematic_script_generated",
  "director_plan_generated",
  "storyboard_image_requested",
  "storyboard_image_generated",
  "video_task_card_ready",
  "storyboard_image_edited",
  "storyboard_image_edit_completed",
  "storyboard_image_edit_failed",
  "visual_handoff_image_generated",
  "visual_handoff_cross_episode_imported",
  "visual_handoff_cross_episode_linked",
  "storyboard_result_version_activated",
  "workflow_variant_selected",
  "storyboard_version_deleted",
  "workflow_batch_generated",
  "variant_quality_result_saved",
  "variant_quality_auto_reviewed",
  "shot_prompt_patched",
  "storyboard_video_requested",
  "storyboard_video_generated",
  "route_video_requested",
  "route_video_generated",
  "workflow_node_preflight_checked",
  "episode_production_status_updated",
  "agent_split_completed",
])

export const CANVAS_INCREMENTAL_OP_TYPES = new Set([
  "card_patch",
  "result_commit",
  "layout_patch",
  "structure_patch",
  "derived_refresh",
])

export const CANVAS_DOCUMENT_REPLACE_ACTIONS = new Set([
  "episode_workflow_built",
  "episode_work_chains_appended",
  "episode_workflow_relayout",
  "project_planning_outputs_deleted",
])

export const CANVAS_INCREMENTAL_CHANGED_RESOURCES = new Set([
  "canvas_document",
  "canvas_documents",
  "canvas_node",
  "canvas_nodes",
  "canvas_edge",
  "canvas_edges",
  "canvas_route",
  "canvas_routes",
  "canvas_work_chain",
  "canvas_work_chains",
  "canvas_version",
  "canvas_versions",
  "canvas_task",
  "canvas_tasks",
  "canvas_projection",
  "canvas_projections",
  "variant_quality_results",
  "visual_handoff",
  "node_edit_history",
])

export const ADD_ASSET_KIND_CONFIG: Record<AddAssetKind, AddAssetKindConfig> = {
  character: {
    title: "添加资产",
    tabLabel: "角色",
    noun: "角色",
    sourceType: "asset",
    assetType: "characters",
  },
  creature: {
    title: "添加资产",
    tabLabel: "生物",
    noun: "生物",
    sourceType: "asset",
    assetType: "creatures",
  },
  scene: {
    title: "添加资产",
    tabLabel: "场景",
    noun: "场景",
    sourceType: "asset",
    assetType: "scenes",
  },
  prop: {
    title: "添加资产",
    tabLabel: "道具",
    noun: "道具",
    sourceType: "asset",
    assetType: "props",
  },
  media: {
    title: "添加资产",
    tabLabel: "上传资产",
    noun: "媒体",
    sourceType: "media",
  },
}

export function storedAddAssetKind(): AddAssetKind {
  if (typeof window === "undefined") return "character"
  try {
    const value = window.localStorage.getItem(ADD_ASSET_LAST_KIND_KEY)
    if (
      value === "creature" ||
      value === "scene" ||
      value === "prop" ||
      value === "media"
    )
      return value
  } catch {
    // localStorage may be unavailable in restricted webviews.
  }
  return "character"
}

export function rememberAddAssetKind(kind: AddAssetKind) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(ADD_ASSET_LAST_KIND_KEY, kind)
  } catch {
    // Best-effort UI preference.
  }
}

export function defaultMediaPurposeForAddAssetKind(
  kind: AddAssetKind
): ExternalMediaPurpose {
  if (kind === "creature") return "creature_reference"
  if (kind === "scene") return "scene_reference"
  if (kind === "prop") return "prop_reference"
  return "character_reference"
}

export function mediaPurposeUsesVoiceStyle(purpose?: string | null) {
  return purpose === "character_reference" || purpose === "creature_reference"
}

export function mediaPurposeVoiceStyleLabel(purpose?: string | null) {
  return purpose === "creature_reference" ? "生物语气" : "角色语气"
}

export function workflowNodeId(prefix: string) {
  const raw =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}_${raw.replace(/[^a-zA-Z0-9]+/g, "_").slice(0, 18)}`
}

export function workflowTaskResultNodeType(nodeType: string) {
  if (isWorkflowVideoTaskType(nodeType)) return "video.result"
  return ""
}

export function assetDesignPromptForCanvas(item: AssetItem) {
  const prompts = recordValue(item.prompts)
  return String(
    prompts.imagePrompt ??
      prompts.designPrompt ??
      prompts.prompt ??
      prompts.visual ??
      item.desc ??
      ""
  ).trim()
}

export function assetMediaVersionRows(item: AssetItem) {
  return (item.mediaVersions ?? []).filter((version) => version.media)
}

export function defaultAssetMediaVersionId(item: AssetItem) {
  const rows = assetMediaVersionRows(item)
  if (!rows.length) return ""
  if (item.activeMediaVersionId) {
    const version = rows.find((entry) => entry.id === item.activeMediaVersionId)
    if (version) return version.id
  }
  return ""
}

export function activeAssetMedia(
  item: AssetItem,
  selectedMediaVersionId?: string | null
): MediaAsset | null {
  const selectedVersionId = String(selectedMediaVersionId ?? "").trim()
  if (selectedVersionId && item.mediaVersions?.length) {
    const version = item.mediaVersions.find(
      (entry) => entry.id === selectedVersionId
    )
    if (version?.media) return version.media
  }
  if (item.activeMediaVersionId && item.mediaVersions?.length) {
    const version = item.mediaVersions.find(
      (entry) => entry.id === item.activeMediaVersionId
    )
    if (version?.media) return version.media
  }
  return item.media ?? null
}

export type AssetMentionRange = {
  start: number
  end: number
  query: string
}

export function activeAssetMentionRange(
  text: string,
  caret: number = text.length
): AssetMentionRange | null {
  const safeCaret = Math.min(Math.max(0, caret), text.length)
  const textBeforeCaret = text.slice(0, safeCaret)
  const lastAsciiAt = textBeforeCaret.lastIndexOf("@")
  const lastFullWidthAt = textBeforeCaret.lastIndexOf("＠")
  const lastAt = Math.max(lastAsciiAt, lastFullWidthAt)
  if (lastAt < 0) return null
  const suffix = textBeforeCaret.slice(lastAt + 1)
  if (suffix.includes("]") || suffix.includes("\n") || suffix.includes("\t") || (!suffix.startsWith("[") && suffix.includes(" "))) {
    return null
  }
  return { start: lastAt, end: safeCaret, query: suffix.startsWith("[") ? suffix.slice(1) : suffix }
}

export function insertAssetMention(
  text: string,
  assetName: string,
  range: AssetMentionRange | null = activeAssetMentionRange(text)
) {
  const mention = `@[${assetName.trim()}]`
  if (!mention.trim()) return text
  if (range) {
    return `${text.slice(0, range.start)}${mention}${text.slice(range.end)}`
  }
  if (!text.trim()) return mention
  return `${text.trimEnd()} ${mention}`
}

export function canvasAssetCardState(kind: "asset" | "media", hasMedia = true) {
  const compact = !hasMedia
  return {
    size: {
      width: 240,
      height: compact ? 190 : kind === "media" ? 260 : 280,
      minWidth: 220,
      minHeight: compact ? 160 : 220,
    },
  }
}

export function defaultWorkflowCardSize(nodeType: string): WorkflowCardSize {
  if (nodeType === "source.text") {
    return {
      width: 340,
      height: 160,
      minWidth: 320,
      minHeight: 140,
      maxWidth: 380,
      maxHeight: 190,
    }
  }
  if (nodeType === "asset.image" || nodeType === "media.external") {
    return {
      width: 240,
      height: 300,
      minWidth: 220,
      minHeight: 220,
      maxWidth: 520,
      maxHeight: 640,
    }
  }
  if (nodeType === "storyboard.image") {
    return {
      width: 320,
      height: 300,
      minWidth: 280,
      minHeight: 240,
      maxWidth: 720,
      maxHeight: 760,
    }
  }
  if (nodeType === "video.result" || isWorkflowVideoTaskType(nodeType)) {
    return {
      width: 360,
      height: 300,
      minWidth: 320,
      minHeight: 240,
      maxWidth: 760,
      maxHeight: 780,
    }
  }
  if (nodeType === "prompt.storyboard") {
    return {
      width: 340,
      height: 280,
      minWidth: 300,
      minHeight: 240,
      maxWidth: 680,
      maxHeight: 760,
    }
  }
  if (isDirectorBoardNodeType(nodeType)) {
    return {
      width: 380,
      height: 360,
      minWidth: 340,
      minHeight: 300,
      maxWidth: 740,
      maxHeight: 820,
    }
  }
  return {
    width: 320,
    height: 360,
    minWidth: 280,
    minHeight: 260,
    maxWidth: 640,
    maxHeight: 720,
  }
}

export function numberRecordValue(value: unknown, fallback: number) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

export function workflowCardSize(data: WorkflowNodeData): WorkflowCardSize {
  const fallback = defaultWorkflowCardSize(data.eyebrow)
  if (data.eyebrow === "source.text") return fallback
  const cardState = recordValue(data.cardState)
  const size = recordValue(cardState.size)
  const minWidth = numberRecordValue(size.minWidth, fallback.minWidth)
  const minHeight = numberRecordValue(size.minHeight, fallback.minHeight)
  const maxWidth = numberRecordValue(size.maxWidth, fallback.maxWidth ?? 900)
  const maxHeight = numberRecordValue(size.maxHeight, fallback.maxHeight ?? 900)
  return {
    width: Math.min(
      maxWidth,
      Math.max(minWidth, numberRecordValue(size.width, fallback.width))
    ),
    height: Math.min(
      maxHeight,
      Math.max(minHeight, numberRecordValue(size.height, fallback.height))
    ),
    minWidth,
    minHeight,
    maxWidth,
    maxHeight,
  }
}

export function clampWorkflowCardSize(size: WorkflowCardSize): WorkflowCardSize {
  const maxWidth = size.maxWidth ?? 900
  const maxHeight = size.maxHeight ?? 900
  return {
    ...size,
    width: Math.min(maxWidth, Math.max(size.minWidth, size.width)),
    height: Math.min(maxHeight, Math.max(size.minHeight, size.height)),
    maxWidth,
    maxHeight,
  }
}

export function parseAspectRatioValue(value?: string | null) {
  const text = String(value ?? "").trim()
  if (!text) return 0
  const pair = text.match(/^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$/)
  if (pair) {
    const width = Number(pair[1])
    const height = Number(pair[2])
    return width > 0 && height > 0 ? width / height : 0
  }
  const numeric = Number(text)
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0
}

export function mediaDimensionValue(...values: unknown[]) {
  for (const value of values) {
    const parsed = Number(value)
    if (Number.isFinite(parsed) && parsed > 0) return parsed
  }
  return 0
}

export function workflowMediaAspectRatio(
  data: WorkflowNodeData,
  media?: MediaAsset | null
) {
  const mediaRecord = recordValue(media)
  const width = mediaDimensionValue(data.width, mediaRecord.width)
  const height = mediaDimensionValue(data.height, mediaRecord.height)
  if (width > 0 && height > 0) return width / height
  return (
    parseAspectRatioValue(data.aspectRatio) ||
    parseAspectRatioValue(String(mediaRecord.aspectRatio ?? "")) ||
    (workflowMediaKind(data, media) === "video" ? 16 / 9 : 4 / 3)
  )
}

export function workflowMediaKind(
  data: WorkflowNodeData,
  media?: MediaAsset | null
): "image" | "video" {
  const mimeType = String(media?.mimeType ?? "").toLowerCase()
  if (media?.kind === "video" || mimeType.startsWith("video/")) return "video"
  const mediaPath = String(
    media?.path ??
      media?.file ??
      media?.url ??
      media?.preview ??
      media?.thumbnail ??
      ""
  ).trim()
  if (/\.(mp4|m4v|mov|webm|avi|mkv)(?:[?#].*)?$/i.test(mediaPath))
    return "video"
  if (/\.(png|jpe?g|webp|gif|bmp|tiff?|avif)(?:[?#].*)?$/i.test(mediaPath))
    return "image"
  for (const value of [
    data.mediaKind,
    data.media_kind,
    data.mediaType,
    data.media_type,
  ]) {
    if (isVideoReferenceMediaType(value)) return "video"
    if (isImageReferenceMediaType(value)) return "image"
  }
  const mediaPurpose = String(
    data.mediaPurpose ??
      data.preferredTargetSlot ??
      data.assetKind ??
      data.assetType ??
      ""
  ).trim()
  if (mediaPurpose === "video_result") return "video"
  if (data.eyebrow.startsWith("video.")) return "video"
  return "image"
}

export function workflowAssetRenameKind(
  node?: StoryboardNode | null
): RenameAssetKind | "" {
  if (!node || !isWorkflowAssetNodeType(node.data.eyebrow)) return ""
  const media = canvasMediaReference(
    node.data.media ?? node.data.storage ?? null
  )
  return workflowMediaKind(node.data, media) === "video" ? "video" : "image"
}

export function normalizeRenameImageMediaPurpose(
  value?: unknown
): ExternalMediaPurpose | "" {
  const raw = String(value ?? "").trim()
  if (raw === "frame_image" || raw === "frame_reference") return "frame_image"
  if (!raw || raw === "auto") return ""
  const normalized =
    raw === "visual_reference"
      ? "storyboard_image"
      : raw === "visual_handoff_reference"
        ? "visual_handoff"
        : raw
  if (
    RENAME_IMAGE_MEDIA_PURPOSE_OPTIONS.some(
      (option) => option.value === normalized
    )
  ) {
    return normalized as ExternalMediaPurpose
  }
  const slot = assetTargetSlotForAssetType(raw)
  if (slot === "visual_handoff_reference") return "visual_handoff"
  if (
    RENAME_IMAGE_MEDIA_PURPOSE_OPTIONS.some((option) => option.value === slot)
  ) {
    return slot as ExternalMediaPurpose
  }
  return ""
}

export function renameImageMediaPurposeFromNode(
  node?: StoryboardNode | null
): ExternalMediaPurpose {
  const data = recordValue(node?.data)
  for (const value of [
    data.mediaPurpose,
    data.media_purpose,
    data.preferredTargetSlot,
    data.preferred_target_slot,
    data.assetKind,
    data.asset_kind,
    data.assetType,
    data.asset_type,
  ]) {
    const mediaPurpose = normalizeRenameImageMediaPurpose(value)
    if (mediaPurpose) return mediaPurpose
  }
  return "storyboard_image"
}

export function renameAssetTitleFromNode(node?: StoryboardNode | null) {
  return String(
    node?.data.assetName ?? node?.data.title ?? node?.data.sourceFileName ?? ""
  ).trim()
}

export function inputMediaFileKind(file?: InputImageFile | null): "image" | "video" {
  const mimeType = String(file?.mimeType ?? "").toLowerCase()
  if (file?.kind === "video" || mimeType.startsWith("video/")) return "video"
  return "image"
}

export function focusedElementAcceptsTextInput(target: EventTarget | null) {
  if (!(target instanceof Element)) return false
  const editable = target.closest(
    "input, textarea, [contenteditable='true'], [contenteditable='plaintext-only']"
  )
  return Boolean(editable)
}

export function readBlobAsDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ""))
    reader.onerror = () =>
      reject(reader.error || new Error("读取剪贴板图片失败"))
    reader.readAsDataURL(blob)
  })
}

export const CLIPBOARD_IMAGE_EXTENSION_MIME: Array<[RegExp, string]> = [
  [/\.(png)$/i, "image/png"],
  [/\.(jpe?g)$/i, "image/jpeg"],
  [/\.(webp)$/i, "image/webp"],
  [/\.(gif)$/i, "image/gif"],
]

export function clipboardImageMimeType(
  file: File,
  typeHint?: string | null
): string | null {
  const mimeType = String(typeHint || file.type || "").toLowerCase()
  if (mimeType.startsWith("image/")) return mimeType
  const name = String(file.name || "")
  return (
    CLIPBOARD_IMAGE_EXTENSION_MIME.find(([pattern]) =>
      pattern.test(name)
    )?.[1] ?? null
  )
}

export function clipboardImageFile(
  event: ClipboardEvent
): { file: File; mimeType: string } | null {
  const items = Array.from(event.clipboardData?.items ?? [])
  for (const item of items) {
    if (item.kind !== "file") continue
    const file = item.getAsFile()
    if (!file) continue
    const mimeType = clipboardImageMimeType(file, item.type)
    if (mimeType) return { file, mimeType }
  }
  const files = Array.from(event.clipboardData?.files ?? [])
  for (const file of files) {
    const mimeType = clipboardImageMimeType(file)
    if (mimeType) return { file, mimeType }
  }
  return null
}

export async function clipboardImageInputFile(
  event: ClipboardEvent
): Promise<InputImageFile | null> {
  const image = clipboardImageFile(event)
  if (!image) return null
  const { file, mimeType } = image
  const rawDataUrl = await readBlobAsDataUrl(file)
  const commaIndex = rawDataUrl.indexOf(",")
  const dataUrl =
    rawDataUrl.startsWith("data:image/") || commaIndex < 0
      ? rawDataUrl
      : `data:${mimeType};base64,${rawDataUrl.slice(commaIndex + 1)}`
  if (!dataUrl.startsWith("data:image/")) return null
  const fallbackExt = mimeType.includes("jpeg")
    ? "jpg"
    : mimeType.includes("webp")
      ? "webp"
      : "png"
  return {
    name: file.name || `粘贴图片.${fallbackExt}`,
    kind: "image",
    mimeType,
    size: file.size,
    dataUrl,
    preview: dataUrl,
  }
}

export function mediaDetailRows(id: string, data: WorkflowNodeData) {
  const prompts = recordValue(data.prompts)
  const designPrompt = String(
    prompts.assetImagePrompt ?? prompts.imagePrompt ?? ""
  ).trim()
  return [
    ["节点", id],
    ["标题", data.title],
    ["类型", data.eyebrow],
    ["状态", workflowNodeGenerationStatusLabel(data)],
    ["摘要", data.summary],
    ["内容", sourceTextForNode(data)],
    ["提示词", promptTextForNode(data)],
    ["资产", data.assetName ?? data.assetId],
    ["媒体", data.sourceFileName ?? data.mediaId],
    ["设计图提示词", designPrompt],
    ["角色语气", data.voiceStyle],
    ["模型", data.model],
    ["规格", data.metric],
    ["时长", data.duration],
    ["工作链", data.workChainId],
    ["路线", data.routeLabel ?? data.routeId],
    ["尺寸", data.width && data.height ? `${data.width} x ${data.height}` : ""],
  ].filter((row): row is [string, string] => Boolean(row[1]))
}

export function isCanvasAssetNode(node: StoryboardNode) {
  return (
    node.data.eyebrow === "asset.image" ||
    node.data.eyebrow === "media.external"
  )
}

export type WorkflowCanvasRect = {
  x: number
  y: number
  width: number
  height: number
}

export type CanvasAssetLayoutDirection = "down" | "up" | "right" | "left"

export function workflowNodeRect(node: StoryboardNode): WorkflowCanvasRect {
  const size = workflowCardSize(node.data)
  return {
    x: node.position.x,
    y: node.position.y,
    width: size.width,
    height: size.height,
  }
}

export function workflowCanvasRect(
  position: { x: number; y: number },
  size: Pick<WorkflowCardSize, "width" | "height">
): WorkflowCanvasRect {
  return {
    x: position.x,
    y: position.y,
    width: size.width,
    height: size.height,
  }
}

export function inflateCanvasRect(
  rect: WorkflowCanvasRect,
  padding: number
): WorkflowCanvasRect {
  return {
    x: rect.x - padding,
    y: rect.y - padding,
    width: rect.width + padding * 2,
    height: rect.height + padding * 2,
  }
}

export function rectsOverlap(a: WorkflowCanvasRect, b: WorkflowCanvasRect) {
  return (
    a.x < b.x + b.width &&
    a.x + a.width > b.x &&
    a.y < b.y + b.height &&
    a.y + a.height > b.y
  )
}

export function rectInsideBounds(
  rect: WorkflowCanvasRect,
  bounds: WorkflowCanvasRect,
  margin = 0
) {
  return (
    rect.x >= bounds.x + margin &&
    rect.y >= bounds.y + margin &&
    rect.x + rect.width <= bounds.x + bounds.width - margin &&
    rect.y + rect.height <= bounds.y + bounds.height - margin
  )
}

export function canvasAssetLinePositions(
  anchor: { x: number; y: number },
  count: number,
  size: Pick<WorkflowCardSize, "width" | "height">,
  direction: CanvasAssetLayoutDirection
) {
  const horizontalStep = size.width + CANVAS_ASSET_HORIZONTAL_GAP
  const verticalStep = size.height + CANVAS_ASSET_VERTICAL_GAP
  const stepX =
    direction === "right"
      ? horizontalStep
      : direction === "left"
        ? -horizontalStep
        : 0
  const stepY =
    direction === "down" ? verticalStep : direction === "up" ? -verticalStep : 0
  return Array.from({ length: Math.max(0, count) }, (_, index) => ({
    x: anchor.x + stepX * index,
    y: anchor.y + stepY * index,
  }))
}

export function canvasAssetLayoutScore(
  positions: Array<{ x: number; y: number }>,
  size: Pick<WorkflowCardSize, "width" | "height">,
  obstacleRects: WorkflowCanvasRect[],
  bounds: WorkflowCanvasRect | null
) {
  return positions.reduce(
    (score, position) => {
      const rect = workflowCanvasRect(position, size)
      if (obstacleRects.some((obstacle) => rectsOverlap(rect, obstacle))) {
        score.collisions += 1
      }
      if (
        bounds &&
        !rectInsideBounds(rect, bounds, CANVAS_ASSET_LAYOUT_VIEWPORT_MARGIN)
      ) {
        score.boundsMisses += 1
      }
      return score
    },
    { collisions: 0, boundsMisses: 0 }
  )
}

export function canvasAssetBatchPositions({
  anchor,
  count,
  nodes,
  visibleNodes,
  nodeType = "asset.image",
  bounds = null,
}: {
  anchor: { x: number; y: number }
  count: number
  nodes: StoryboardNode[]
  visibleNodes: StoryboardNode[]
  nodeType?: string
  bounds?: WorkflowCanvasRect | null
}) {
  const assetSize = defaultWorkflowCardSize(nodeType)
  const obstacleNodes = visibleNodes.length ? visibleNodes : nodes
  const obstacleRects = obstacleNodes.map((node) =>
    inflateCanvasRect(workflowNodeRect(node), 20)
  )
  const directions: CanvasAssetLayoutDirection[] = [
    "down",
    "up",
    "right",
    "left",
  ]
  const candidates = directions.map((direction) => {
    const positions = canvasAssetLinePositions(
      anchor,
      count,
      assetSize,
      direction
    )
    return {
      direction,
      positions,
      score: canvasAssetLayoutScore(
        positions,
        assetSize,
        obstacleRects,
        bounds
      ),
    }
  })
  const fits = (candidate: (typeof candidates)[number]) =>
    candidate.score.collisions === 0 && candidate.score.boundsMisses === 0

  const verticalFit = candidates
    .filter(
      (candidate) =>
        candidate.direction === "down" || candidate.direction === "up"
    )
    .find(fits)
  if (verticalFit) return verticalFit.positions

  const candidatesWithoutBounds = candidates.map((candidate) => ({
    ...candidate,
    score: canvasAssetLayoutScore(
      candidate.positions,
      assetSize,
      obstacleRects,
      null
    ),
  }))
  const verticalFitWithoutBounds = candidatesWithoutBounds
    .filter(
      (candidate) =>
        candidate.direction === "down" || candidate.direction === "up"
    )
    .find((candidate) => candidate.score.collisions === 0)
  if (verticalFitWithoutBounds) return verticalFitWithoutBounds.positions

  const horizontalFit = candidates
    .filter(
      (candidate) =>
        candidate.direction === "right" || candidate.direction === "left"
    )
    .find(fits)
  if (horizontalFit) return horizontalFit.positions

  const horizontalFitWithoutBounds = candidatesWithoutBounds
    .filter(
      (candidate) =>
        candidate.direction === "right" || candidate.direction === "left"
    )
    .find((candidate) => candidate.score.collisions === 0)
  if (horizontalFitWithoutBounds) return horizontalFitWithoutBounds.positions

  const [bestCandidate] = [...candidates].sort((a, b) => {
    const aPenalty = a.score.collisions * 10 + a.score.boundsMisses
    const bPenalty = b.score.collisions * 10 + b.score.boundsMisses
    return aPenalty - bPenalty
  })
  return bestCandidate?.positions ?? []
}

export function nextCanvasAssetPosition(
  nodes: StoryboardNode[],
  visibleNodes: StoryboardNode[],
  selectedWorkChainId: string,
  selectedWorkChainRouteIds: Set<string> = new Set()
) {
  const assetSize = defaultWorkflowCardSize("asset.image")
  const matchesCurrentWorkChain = (node: StoryboardNode) => {
    if (selectedWorkChainId === "all") return true
    const routeId = node.data.routeId
    const workChainId = node.data.workChainId
    return (
      workChainId === selectedWorkChainId ||
      (routeId ? selectedWorkChainRouteIds.has(routeId) : false)
    )
  }
  const scopedAssets = nodes.filter(
    (node) =>
      isCanvasAssetNode(node) &&
      !node.data.routeId &&
      matchesCurrentWorkChain(node)
  )
  const scopedContentNodes = nodes.filter(
    (node) => !isCanvasAssetNode(node) && matchesCurrentWorkChain(node)
  )
  const contentNodes = scopedContentNodes.length
    ? scopedContentNodes
    : visibleNodes.filter((node) => !isCanvasAssetNode(node))

  if (contentNodes.length) {
    const minX = Math.min(...contentNodes.map((node) => node.position.x))
    const minY = Math.min(...contentNodes.map((node) => node.position.y))
    const rowY = minY - assetSize.height - CANVAS_ASSET_VERTICAL_GAP
    const rowAssets = scopedAssets.filter((node) => {
      const size = workflowCardSize(node.data)
      return (
        node.position.y < rowY + assetSize.height + CANVAS_ASSET_VERTICAL_GAP &&
        node.position.y + size.height > rowY - CANVAS_ASSET_VERTICAL_GAP
      )
    })
    if (rowAssets.length) {
      const right = Math.max(
        ...rowAssets.map(
          (node) => node.position.x + workflowCardSize(node.data).width
        )
      )
      return {
        x: right + CANVAS_ASSET_HORIZONTAL_GAP,
        y: rowY,
      }
    }
    return {
      x: minX,
      y: rowY,
    }
  }
  if (scopedAssets.length) {
    const minY = Math.min(...scopedAssets.map((node) => node.position.y))
    const right = Math.max(
      ...scopedAssets.map(
        (node) => node.position.x + workflowCardSize(node.data).width
      )
    )
    return {
      x: right + CANVAS_ASSET_HORIZONTAL_GAP,
      y: minY,
    }
  }
  const assetCount = nodes.filter(isCanvasAssetNode).length
  return {
    x: 80 + (assetCount % 4) * 280,
    y: 80 + Math.floor(assetCount / 4) * 230,
  }
}

export function workflowWorkChainDisplayName(
  workChain: WorkflowWorkChain,
  index: number
) {
  const raw = String(workChain.label ?? workChain.title ?? "").trim()
  if (!raw) return `第 ${index + 1} 条工作链`
  const stripped = raw
    .replace(
      /^(?:(?:锚点|工作链)\s*[一二三四五六七八九十百千万零〇两\d]+\s*)+/u,
      ""
    )
    .replace(/^[:：、,，/／|·•>\-\s]+/u, "")
    .trim()
  return stripped || raw
}

export function storyboardVersionHistoryDescription(
  node: StoryboardNode,
  workChains: WorkflowWorkChain[],
  routes: WorkflowRoute[]
) {
  if (node.data.eyebrow === "asset.image") {
    return node.data.title ? `${node.data.title}设计图` : "当前设计图"
  }
  if (node.data.eyebrow === "media.external") {
    return node.data.title ? `${node.data.title}图片` : "当前图片"
  }
  if (
    node.data.eyebrow === "storyboard.image" &&
    !isWorkChainStoryboardResultImageNode(node)
  ) {
    return node.data.title ? `${node.data.title}图片` : "当前图片"
  }
  const routeId = node.data.routeId
  const route = routeId ? routes.find((item) => item.id === routeId) : undefined
  const workChainId = node.data.workChainId ?? route?.workChainId
  const workChain =
    workChains.find((item) => item.id === workChainId) ??
    (routeId
      ? workChains.find((item) => item.routeIds?.includes(routeId))
      : undefined)
  const workChainIndex = workChain
    ? workChains.findIndex((item) => item.id === workChain.id)
    : -1
  const baseLabel = (
    workChain
      ? workflowWorkChainDisplayName(workChain, Math.max(workChainIndex, 0))
      : (node.data.routeLabel ?? route?.label ?? node.data.title)
  ).trim()
  const cleanLabel = baseLabel.replace(/(?:历史版本|分镜图)$/u, "").trim()
  return cleanLabel ? `${cleanLabel}分镜图` : "当前分镜图"
}

export function isWorkflowImageNodeType(value?: string | null) {
  const type = value ?? ""
  return (
    type === "asset.image" ||
    type === "media.external" ||
    type === "storyboard.image"
  )
}

export function isWorkflowAssetNodeType(value?: string | null) {
  const type = value ?? ""
  return isWorkflowImageNodeType(type) || type === "video.result"
}

export function isStoryboardResultImageData(data?: WorkflowNodeData | null) {
  return workflowNodeDataIsWorkChainStoryboardResult(data)
}

export function isStoryboardResultImageNode(node?: StoryboardNode | null) {
  return isStoryboardResultImageData(node?.data)
}

export function isWorkChainStoryboardResultImageNode(node?: StoryboardNode | null) {
  return workflowNodeDataIsWorkChainStoryboardResult(node?.data)
}

export function isEditableCanvasImageNode(node?: StoryboardNode | null) {
  if (!node || !isWorkflowImageNodeType(node.data.eyebrow)) return false
  if (node.data.eyebrow !== "media.external") return true
  const media = canvasMediaReference(
    node.data.media ?? node.data.storage ?? null
  )
  const mediaRecord = (media ?? {}) as MediaAsset & { mediaType?: string }
  const mediaKind = String(mediaRecord.kind ?? mediaRecord.mediaType ?? "")
    .trim()
    .toLowerCase()
  return mediaKind !== "video"
}

export function canOpenCanvasImageEditor(node?: StoryboardNode | null) {
  if (!node || !isEditableCanvasImageNode(node)) return false
  if (canvasImageNodeHasEditableOriginal(node)) return true
  if (isWorkChainStoryboardResultImageNode(node) || workflowNodeIsVisualHandoffAsset(node)) return false
  return Boolean(canvasProjectAssetTypeFromNode(node)) || ["storyboard_image", "custom_image"].includes(String(node.data.mediaPurpose))
}

export function workflowNodeDataHasEditableOriginalImage(
  data?: WorkflowNodeDataLookup | null
) {
  const media = canvasMediaReference(data?.media ?? data?.storage ?? null)
  return Boolean(mediaPreviewSrc(media))
}

export function workflowNodeDataHasCurrentMediaReference(
  data?: WorkflowNodeDataLookup | null
) {
  const media = canvasMediaReference(data?.media ?? data?.storage ?? null)
  const record = (data ?? {}) as Record<string, unknown>
  return Boolean(
    mediaPreviewSrc(media) ||
    optionalString(data?.mediaId) ||
    workflowNodeDataCurrentVersionId(data) ||
    optionalString(record.preview) ||
    optionalString(record.previewUrl) ||
    optionalString(record.preview_url) ||
    optionalString(record.previewSrc) ||
    optionalString(record.preview_src) ||
    optionalString(record.url) ||
    optionalString(record.thumbnail) ||
    optionalString(record.thumbnailUrl) ||
    optionalString(record.thumbnail_url) ||
    optionalString(record.dataUrl) ||
    optionalString(record.data_url)
  )
}

export function storyboardVersionHasActiveFlag(version?: StoryboardVersion | null) {
  if (!version) return false
  const row = version as Record<string, unknown>
  return ["active", "isActive", "activeVersion", "active_version"].some(
    (key) => row[key] !== undefined && row[key] !== null
  )
}

export function storyboardVersionIsActive(version?: StoryboardVersion | null) {
  if (!version) return false
  const row = version as Record<string, unknown>
  return Boolean(
    row.active === true ||
    row.isActive === true ||
    row.activeVersion === true ||
    row.active_version === true
  )
}

export function workflowNodeDataHasConcreteMediaReference(
  data?: WorkflowNodeDataLookup | null
) {
  const media = canvasMediaReference(data?.media ?? data?.storage ?? null)
  const record = (data ?? {}) as Record<string, unknown>
  return Boolean(
    mediaPreviewSrc(media) ||
    optionalString(data?.mediaId) ||
    optionalString(record.preview) ||
    optionalString(record.previewUrl) ||
    optionalString(record.preview_url) ||
    optionalString(record.previewSrc) ||
    optionalString(record.preview_src) ||
    optionalString(record.url) ||
    optionalString(record.thumbnail) ||
    optionalString(record.thumbnailUrl) ||
    optionalString(record.thumbnail_url) ||
    optionalString(record.dataUrl) ||
    optionalString(record.data_url) ||
    optionalString(record.path) ||
    optionalString(record.filePath) ||
    optionalString(record.file_path) ||
    optionalString(record.file) ||
    optionalString(record.pngFile) ||
    optionalString(record.relativePath) ||
    optionalString(record.relative_path)
  )
}

export function workflowNodeDataIsVisualHandoffAsset(
  data?: WorkflowNodeDataLookup | null
) {
  const values = [
    data?.mediaPurpose,
    data?.assetKind,
    data?.assetType,
    data?.preferredTargetSlot,
  ].map((value) => String(value ?? "").trim())
  return values.some(
    (value) =>
      value === "visual_handoff" || value === "visual_handoff_reference"
  )
}

export function workflowNodeIsVisualHandoffAsset(node?: StoryboardNode | null) {
  return Boolean(node && workflowNodeDataIsVisualHandoffAsset(node.data))
}

export function workflowNodeVersionStorageNodeId(
  nodeId: string,
  data?: WorkflowNodeDataLookup | null
) {
  if (
    isWorkflowGeneratedMediaType(String(data?.eyebrow ?? "")) ||
    workflowNodeDataIsVisualHandoffAsset(data)
  ) {
    return nodeId
  }
  return optionalString(data?.resultOfNodeId) || nodeId
}

export function canvasImageNodeHasEditableOriginal(node?: StoryboardNode | null) {
  return Boolean(node && workflowNodeDataHasEditableOriginalImage(node.data))
}

export function isEditableVideoResultNode(node?: StoryboardNode | null) {
  if (!node || node.data.eyebrow !== "video.result") return false
  if (node.data.sourceType === "version" || node.data.copiedFromNodeId)
    return false
  return workflowNodeDataHasConcreteMediaReference(node.data)
}

export function isWorkflowResultNodeType(value?: string | null) {
  return isWorkflowResultImageType(value) || value === "video.result"
}

export function isWorkflowTaskNodeType(value?: string | null) {
  return (
    value === "prompt.storyboard" ||
    isDirectorBoardNodeType(value) ||
    isStoryboardCardNodeType(value) ||
    isWorkflowVideoTaskType(value)
  )
}

export function workflowNodeUsesStoryboardTemplate(value?: string | null) {
  return isStoryboardCardNodeType(value)
}

export function materialTargetSlotsForNodeType(nodeType?: string | null) {
  const type = nodeType ?? ""
  if (type === "video.character_replace") {
    return new Set(["character_reference", "creature_reference", "custom_image", "reference_video"])
  }
  if (isDirectorBoardNodeType(type) || isStoryboardCardNodeType(type)) {
    return new Set([
      "character_reference",
      "creature_reference",
      "scene_reference",
      "prop_reference",
      "visual_handoff_reference",
      "frame_reference",
      "custom_image",
    ])
  }
  if (isWorkflowVideoTaskType(type)) {
    return new Set([
      "character_reference",
      "creature_reference",
      "scene_reference",
      "prop_reference",
      "storyboard_image",
      "reference_video",
      "visual_handoff_reference",
      "frame_reference",
      "custom_image",
    ])
  }
  return new Set<string>()
}

export function isWorkflowAssetInputHandle(handle?: string | null) {
  return Boolean(canonicalWorkflowInputHandle(handle))
}

export function materialTargetHandleAllowedForConnection(
  targetNode: StoryboardNode,
  requestedHandle?: string | null
) {
  const targetType = targetNode.data.eyebrow
  const requested = String(requestedHandle ?? "").trim()
  const requestedInputHandle = canonicalWorkflowInputHandle(requested)
  if (!requested) return true
  if (isDirectorBoardNodeType(targetType) || isStoryboardCardNodeType(targetType)) {
    return requestedInputHandle === WORKFLOW_ASSET_INPUT_HANDLE
  }
  if (isWorkflowVideoTaskType(targetType)) {
    const taskScope = workflowVideoTaskScope(targetNode)
    if (!taskScope) return false
    if (taskScope === "standalone") {
      return (
        Boolean(requestedInputHandle) ||
        materialTargetSlotsForNodeType(targetType).has(
          canonicalTargetSlot(requested)
        )
      )
    }
    if (requestedInputHandle === WORKFLOW_ASSET_INPUT_HANDLE) return true
    if (requestedInputHandle === WORKFLOW_VIDEO_INPUT_HANDLE) {
      return false
    }
    return false
  }
  return true
}

export function materialTargetHandleConnectionError(targetNode: StoryboardNode) {
  if (isDirectorBoardNodeType(targetNode.data.eyebrow) || isStoryboardCardNodeType(targetNode.data.eyebrow)) {
    return "左侧只用于工作链主线，资产请连接顶部入口"
  }
  if (isDefaultWorkChainVideoTaskNode(targetNode)) {
    return "工作链视频生成左侧只用于工作链分镜图，资产请连接顶部入口"
  }
  if (isWorkflowVideoTaskType(targetNode.data.eyebrow)) {
    return "独立视频生成只能从左侧或顶部接入资产"
  }
  return "该位置不能接入资产"
}

export function materialTargetSlotForConnection(
  sourceNode: StoryboardNode,
  targetNode: StoryboardNode,
  requestedHandle?: string | null
) {
  const sourceType = sourceNode.data.eyebrow
  const targetSlots = materialTargetSlotsForNodeType(targetNode.data.eyebrow)
  const requestedSlot = canonicalTargetSlot(requestedHandle)
  const sourceMediaKind = workflowMediaKind(
    sourceNode.data,
    canvasMediaReference(sourceNode.data.media ?? sourceNode.data.storage ?? null)
  )
  if (
    isWorkflowVideoTaskType(targetNode.data.eyebrow) &&
    (sourceType === "video.result" || sourceMediaKind === "video")
  ) {
    return "reference_video"
  }
  if (isFrameImage(sourceNode.data)) return "frame_reference"
  if (sourceNode.data.mediaPurpose === "custom_image") return "custom_image"
  if (workflowNodeDataIsVisualHandoffAsset(sourceNode.data)) {
    return "visual_handoff_reference"
  }
  if (
    requestedHandle &&
    !isWorkflowAssetInputHandle(requestedHandle) &&
    targetSlots.has(requestedSlot)
  ) {
    return requestedSlot
  }

  if (sourceType === "asset.image" || isWorkflowResultImageType(sourceType)) {
    return assetTargetSlotForAssetType(
      sourceNode.data.rootAssetType ??
        sourceNode.data.assetType ??
        sourceNode.data.assetKind ??
        sourceNode.data.preferredTargetSlot ??
        sourceNode.data.mediaPurpose
    )
  }
  if (sourceType === "media.external") {
    return (
      mediaPurposeMaterialSlot(
        sourceNode.data.mediaPurpose ??
          sourceNode.data.preferredTargetSlot ??
          sourceNode.data.assetKind ??
          sourceNode.data.assetType
      ) ||
      assetTargetSlotForAssetType(
        sourceNode.data.assetKind ??
          sourceNode.data.assetType ??
          sourceNode.data.preferredTargetSlot ??
          sourceNode.data.mediaPurpose
      )
    )
  }
  return targetSlots.has(requestedSlot) ? requestedSlot : "storyboard_image"
}

export function assetTargetSlotForAssetType(assetType?: string | null) {
  const value = String(assetType ?? "")
    .trim()
    .toLowerCase()
  if (value === "frame_image") return "frame_reference"
  if (value === "custom_image") return "custom_image"
  if (value === "characters" || value === "character")
    return "character_reference"
  if (
    value === "creatures" ||
    value === "creature" ||
    value === "monsters" ||
    value === "monster" ||
    value === "beasts" ||
    value === "beast"
  )
    return "creature_reference"
  if (value === "scenes" || value === "scene") return "scene_reference"
  if (value === "props" || value === "prop") return "prop_reference"
  if (value === "storyboard" || value === "storyboard_image")
    return "storyboard_image"
  if (
    value === "visual_handoff" ||
    value === "visual_handoff_reference" ||
    value === "handoff" ||
    value === "continuity"
  )
    return "visual_handoff_reference"
  if (value === "visual_reference" || value === "visual")
    return "storyboard_image"
  return "storyboard_image"
}

export function workflowMaterialSourceHandle(
  node: StoryboardNode,
  requestedHandle?: string | null
) {
  const requested = String(requestedHandle ?? "").trim()
  const nodeType = node.data.eyebrow
  if (nodeType === "asset.image") {
    return requested === "asset_bottom" ? "asset_bottom" : "asset"
  }
  if (nodeType === "media.external") {
    const defaultHandle =
      workflowMediaKind(node.data, node.data.media ?? node.data.storage) ===
      "video"
        ? "video"
        : "media"
    return requested === `${defaultHandle}_bottom` ? requested : defaultHandle
  }
  if (isWorkflowResultImageType(nodeType)) {
    return workflowNodeDataIsIndependentImageAsset(node.data) &&
      requested === "image_bottom"
      ? "image_bottom"
      : "image"
  }
  if (nodeType === "video.result") {
    return requested === "video_bottom" ? "video_bottom" : "video"
  }
  return requested || "image"
}

export function materialConnectionAllowed(
  sourceNode: StoryboardNode,
  targetNode: StoryboardNode,
  targetSlot: string
) {
  const sourceType = sourceNode.data.eyebrow
  const targetType = targetNode.data.eyebrow
  const allowedSlots = materialTargetSlotsForNodeType(targetType)
  if (!allowedSlots.has(targetSlot)) return false
  if (
    (isDirectorBoardNodeType(targetType) || isStoryboardCardNodeType(targetType)) &&
    !allowedSlots.has(materialTargetSlotForConnection(sourceNode, targetNode))
  ) {
    return false
  }
  const targetVideoTaskScope = isWorkflowVideoTaskType(targetType)
    ? workflowVideoTaskScope(targetNode)
    : ""
  if (isWorkflowVideoTaskType(targetType) && !targetVideoTaskScope) return false
  if (
    targetSlot === "visual_handoff_reference" &&
    workflowMediaKind(
      sourceNode.data,
      canvasMediaReference(
        sourceNode.data.media ?? sourceNode.data.storage ?? null
      )
    ) === "video"
  ) {
    return false
  }
  const sourceMediaKind = workflowMediaKind(
    sourceNode.data,
    canvasMediaReference(sourceNode.data.media ?? sourceNode.data.storage ?? null)
  )
  const sourceIsVideo = sourceType === "video.result" || sourceMediaKind === "video"
  if (sourceIsVideo && (isDirectorBoardNodeType(targetType) || isStoryboardCardNodeType(targetType))) return false
  if (
    (isWorkflowVideoTaskType(targetType) || isDirectorBoardNodeType(targetType) || isStoryboardCardNodeType(targetType)) &&
    !sourceIsVideo &&
    !workflowNodeCanSupplyImageReference(sourceNode)
  ) {
    return false
  }
  if (
    isWorkChainStoryboardResultImageNode(sourceNode) &&
    !isWorkflowVideoTaskType(targetType)
  ) {
    return false
  }
  if (sourceType === "asset.image") {
    return (
      isDirectorBoardNodeType(targetType) || isStoryboardCardNodeType(targetType) || isWorkflowVideoTaskType(targetType)
    )
  }
  if (sourceType === "media.external") {
    return (
      isDirectorBoardNodeType(targetType) || isStoryboardCardNodeType(targetType) || isWorkflowVideoTaskType(targetType)
    )
  }
  if (isWorkflowResultImageType(sourceType)) {
    if (isDirectorBoardNodeType(targetType) || isStoryboardCardNodeType(targetType)) return true
    return isWorkflowVideoTaskType(targetType)
  }
  if (sourceType === "video.result") return isWorkflowVideoTaskType(targetType)
  return false
}

export function materialConnectionError(
  sourceNode: StoryboardNode,
  targetNode: StoryboardNode,
  targetSlot: string
) {
  const sourceType = sourceNode.data.eyebrow
  const targetType = targetNode.data.eyebrow
  const targetVideoTaskScope = isWorkflowVideoTaskType(targetType)
    ? workflowVideoTaskScope(targetNode)
    : ""
  if (isWorkflowVideoTaskType(targetType) && !targetVideoTaskScope) {
    return WORKFLOW_VIDEO_TASK_SCOPE_MISSING_MESSAGE
  }
  if (isDirectorBoardNodeType(targetType) || isStoryboardCardNodeType(targetType)) {
    if (sourceType === "video.result") return "分镜脚本和分镜单元只能关联图片资产"
    if (!workflowNodeCanSupplyImageReference(sourceNode))
      return "分镜脚本和分镜单元只能关联图片资产"
    if (
      !materialTargetSlotsForNodeType(targetType).has(targetSlot) ||
      !materialTargetSlotsForNodeType(targetType).has(
        materialTargetSlotForConnection(sourceNode, targetNode)
      )
    ) return "分镜脚本和分镜单元只能关联角色、场景、道具、生物和视觉交接图，分镜图请关联视频生成"
  }
  if (!materialTargetSlotsForNodeType(targetType).has(targetSlot)) {
    return "该任务卡不支持这个素材输入槽"
  }
  if (
    targetSlot === "visual_handoff_reference" &&
    workflowMediaKind(
      sourceNode.data,
      canvasMediaReference(
        sourceNode.data.media ?? sourceNode.data.storage ?? null
      )
    ) === "video"
  ) {
    return "视觉交接必须使用图片，不能链接视频资产"
  }
  const sourceMediaKind = workflowMediaKind(
    sourceNode.data,
    canvasMediaReference(sourceNode.data.media ?? sourceNode.data.storage ?? null)
  )
  const sourceIsVideo = sourceType === "video.result" || sourceMediaKind === "video"
  if (isWorkflowVideoTaskType(targetType) && sourceIsVideo) {
    return ""
  }
  if (
    isWorkflowVideoTaskType(targetType) &&
    !sourceIsVideo &&
    !workflowNodeCanSupplyImageReference(sourceNode)
  ) {
    if (sourceType === "video.result") {
      return "当前不支持生成视频作为视频生成输入"
    }
    return "视频生成只能关联图片资产作为参考"
  }
  if (
    isWorkChainStoryboardResultImageNode(sourceNode) &&
    !isWorkflowVideoTaskType(targetType)
  ) {
    return "分镜图只能关联视频生成"
  }
  if (sourceType === "asset.image") return "图片资产只能连接分镜脚本、分镜单元或视频生成"
  if (sourceType === "media.external") {
    return "导入图片可连接分镜脚本、分镜单元或视频生成；导入视频仅可连接视频生成"
  }
  if (isWorkflowResultImageType(sourceType)) {
    return "生成图片可作为图片资产连接分镜脚本、分镜单元或视频生成"
  }
  if (sourceType === "video.result") {
    return "当前不支持生成视频作为视频生成输入"
  }
  return "资产只能连接任务卡"
}

export function materialSourceType(node: StoryboardNode) {
  if (node.data.eyebrow === "asset.image") return "asset"
  if (node.data.eyebrow === "media.external") return "external_media"
  if (isWorkflowResultImageType(node.data.eyebrow)) return "generated_media"
  if (node.data.eyebrow === "video.result") return "generated_video"
  const sourceType = String(node.data.sourceType ?? "").trim()
  if (sourceType === "media") return "external_media"
  if (sourceType === "version" || sourceType === "generated")
    return "generated_media"
  return sourceType || "external_media"
}

export function materialTargetHandleForDisplay(
  targetNode: StoryboardNode,
  targetSlot: string,
  requestedHandle?: string | null
) {
  const requested = String(requestedHandle ?? "").trim()
  const requestedInputHandle = canonicalWorkflowInputHandle(requested)
  if (isDirectorBoardNodeType(targetNode.data.eyebrow) || isStoryboardCardNodeType(targetNode.data.eyebrow)) {
    return WORKFLOW_ASSET_INPUT_HANDLE
  }
  if (isWorkflowVideoTaskType(targetNode.data.eyebrow)) {
    if (
      requestedInputHandle === WORKFLOW_VIDEO_INPUT_HANDLE &&
      workflowVideoTaskScope(targetNode) === "standalone"
    ) {
      return WORKFLOW_VIDEO_INPUT_HANDLE
    }
    return WORKFLOW_ASSET_INPUT_HANDLE
  }
  if (requestedInputHandle) return requestedInputHandle
  if (requested) return requested
  return targetSlot
}

export function storyboardBackendEdgeId(edge: Pick<StoryboardEdge, "id" | "data">) {
  return String(edge.data?.workflowEdgeId ?? edge.id ?? "").trim()
}

export function storyboardEdgesSameIdentity(
  first: Pick<StoryboardEdge, "id" | "data">,
  second: Pick<StoryboardEdge, "id" | "data">
) {
  if (first.id === second.id) return true
  const firstBackendId = storyboardBackendEdgeId(first)
  const secondBackendId = storyboardBackendEdgeId(second)
  return Boolean(
    firstBackendId && secondBackendId && firstBackendId === secondBackendId
  )
}

export function upsertStoryboardEdgeLocally(
  edges: StoryboardEdge[],
  edge: StoryboardEdge
) {
  const nextEdges = edges.filter(
    (item) => !storyboardEdgesSameIdentity(item, edge)
  )
  return [...nextEdges, edge]
}

export function mergeTargetInputLink(
  node: StoryboardNode,
  inputLink: Record<string, unknown>
): StoryboardNode {
  const nextLinks = [
    ...(Array.isArray(node.data.inputLinks) ? node.data.inputLinks : []),
    inputLink,
  ]
  const isReferenceVideo = canonicalTargetSlot(
    String(inputLink.targetSlot ?? inputLink.target_slot ?? inputLink.slot ?? "")
  ) === "reference_video"
  const nextAssetThumbnails = isReferenceVideo
    ? node.data.assetThumbnails
    : appendInputLinkThumbnailRows(node.data.assetThumbnails, inputLink)
  const nextReferenceVideoThumbnails = isReferenceVideo
    ? appendInputLinkThumbnailRows(node.data.referenceVideoThumbnails, inputLink)
    : node.data.referenceVideoThumbnails
  const nextReferenceMediaIds = inputLinkReferenceMediaIds(inputLink)
  return {
    ...node,
    data: {
      ...node.data,
      status: statusAfterInputLinkChange(node.data.status),
      inputLinks: nextLinks,
      referenceVideoThumbnails: nextReferenceVideoThumbnails,
      assetThumbnails: nextAssetThumbnails,
      referenceMediaIds: [
        ...new Set(
          [
            ...(node.data.referenceMediaIds ?? []),
            ...nextReferenceMediaIds,
          ].filter(Boolean)
        ),
      ],
      generationConfig: recordValue(node.data.generationConfig),
    },
  }
}

export function removeInputLinksFromNode(
  node: StoryboardNode,
  inputLinkIds: Set<string>,
  _changeReason: string,
  _changeAt: string
): StoryboardNode {
  const inputLinks = Array.isArray(node.data.inputLinks)
    ? node.data.inputLinks
    : []
  const removedLinks = inputLinks.filter((link) =>
    inputLinkMatchesAnyDirectId(recordValue(link), inputLinkIds)
  )
  if (!removedLinks.length) return node

  const nextLinks = inputLinks.filter(
    (link) => !inputLinkMatchesAnyDirectId(recordValue(link), inputLinkIds)
  )
  const removedMediaIds = new Set(
    removedLinks.flatMap(inputLinkReferenceMediaIds)
  )
  const remainingMediaIds = new Set(
    nextLinks.flatMap(inputLinkReferenceMediaIds)
  )
  const nextReferenceMediaIds = removedMediaIds.size
    ? (node.data.referenceMediaIds ?? []).filter(
        (mediaId) =>
          !removedMediaIds.has(mediaId) || remainingMediaIds.has(mediaId)
      )
    : node.data.referenceMediaIds
  const nextAssetReferenceMediaIds = filterRemovedInputLinkIds(
    node.data.assetReferenceMediaIds,
    removedLinks,
    nextLinks
  )
  const nextAssetThumbnails = filterRemovedInputLinkRows(
    node.data.assetThumbnails,
    removedLinks,
    nextLinks
  )
  const nextReferenceThumbnails = filterRemovedInputLinkRows(
    node.data.referenceThumbnails,
    removedLinks,
    nextLinks
  )
  const nextReferenceVideoThumbnails = filterRemovedInputLinkRows(
    node.data.referenceVideoThumbnails,
    removedLinks,
    nextLinks
  )
  const nextAssetRefs = filterRemovedInputAssetRefs(
    node.data.assetRefs,
    removedLinks,
    nextLinks
  )

  return {
    ...node,
    data: {
      ...node.data,
      status: statusAfterInputLinkChange(node.data.status),
      inputLinks: nextLinks,
      referenceMediaIds: nextReferenceMediaIds,
      assetReferenceMediaIds: nextAssetReferenceMediaIds,
      assetThumbnails: nextAssetThumbnails,
      referenceThumbnails: nextReferenceThumbnails,
      referenceVideoThumbnails: nextReferenceVideoThumbnails,
      assetRefs: nextAssetRefs,
      generationConfig: recordValue(node.data.generationConfig),
    },
  }
}

export function applyInputLinkChangeLocally(
  node: StoryboardNode,
  _changeReason: string,
  _changeAt: string
): StoryboardNode {
  return {
    ...node,
    data: {
      ...node.data,
      status: statusAfterInputLinkChange(node.data.status),
      generationConfig: recordValue(node.data.generationConfig),
    },
  }
}

export function inputChangeReasonForCanvasAction(action: string) {
  if (action === "workflow_input_unlinked") return "input_link_unlinked"
  if (action === "workflow_item_deleted") return "linked_item_deleted"
  return "input_link_changed"
}

export type NodeHandleSpec = {
  id: string
  label: string
  top: string
  position?: Position
}

export function nodeHandlePosition(
  handle: NodeHandleSpec,
  fallback: Position.Left | Position.Right
) {
  return handle.position ?? fallback
}

export function nodeHandleStyle(handle: NodeHandleSpec, position: Position) {
  if (position === Position.Top) {
    return { left: handle.top, top: 0 }
  }
  if (position === Position.Bottom) {
    return { left: handle.top, bottom: 0 }
  }
  return { top: handle.top }
}

export function nodeHandleTooltipSide(position: Position) {
  if (position === Position.Top) return "top" as const
  if (position === Position.Bottom) return "bottom" as const
  if (position === Position.Right) return "right" as const
  return "left" as const
}

export function nodeHandleClassName(type: "source" | "target", _position: Position) {
  return cn(
    "!size-2.5 !border-white/95 !opacity-85 !shadow-[0_1px_4px_rgba(15,23,42,0.22)] transition-[background-color,border-color,box-shadow,opacity] hover:!opacity-100 hover:!shadow-[0_2px_8px_rgba(15,23,42,0.28)] dark:!border-[#26262b]",
    type === "target"
      ? "!bg-indigo-500 hover:!bg-indigo-400 dark:!bg-indigo-400"
      : "!bg-emerald-500 hover:!bg-emerald-400 dark:!bg-emerald-400"
  )
}

export function getNodeHandleSpecs(
  eyebrow: string,
  data?: WorkflowNodeDataLookup | null
): {
  targets: NodeHandleSpec[]
  sources: NodeHandleSpec[]
} {
  if (eyebrow === "source.text") {
    return {
      targets: [],
      sources: [{ id: "output", label: "分集原文输出", top: "50%" }],
    }
  }

  if (eyebrow.startsWith("asset.")) {
    const visualHandoffAsset = workflowNodeDataIsVisualHandoffAsset(data)
    return {
      targets: visualHandoffAsset
        ? [
            {
              id: "asset_context",
              label: "视觉交接生成写入",
              top: "50%",
              position: Position.Top,
            },
          ]
        : [],
      sources: [
        { id: "asset", label: "图片资产", top: "50%" },
        {
          id: "asset_bottom",
          label: "图片资产",
          top: "50%",
          position: Position.Bottom,
        },
      ],
    }
  }

  if (eyebrow === "media.external") {
    const mediaData = { ...(data ?? {}), eyebrow } as WorkflowNodeData
    const mediaKind = workflowMediaKind(
      mediaData,
      (mediaData.media as MediaAsset | null | undefined) ??
        (mediaData.storage as MediaAsset | null | undefined)
    )
    const sourceId = mediaKind === "video" ? "video" : "media"
    const sourceLabel = mediaKind === "video" ? "导入视频" : "导入图片"
    return {
      targets: [],
      sources: [
        { id: sourceId, label: sourceLabel, top: "50%" },
        {
          id: `${sourceId}_bottom`,
          label: sourceLabel,
          top: "50%",
          position: Position.Bottom,
        },
      ],
    }
  }

  if (isDirectorBoardNodeType(eyebrow)) {
    return {
      targets: [
        { id: "story", label: "剧情片段", top: "50%" },
        { id: WORKFLOW_ASSET_INPUT_HANDLE, label: "资产输入", top: "50%", position: Position.Top },
      ],
      sources: [{ id: "plan", label: "分镜分配", top: "50%" }],
    }
  }

  if (isStoryboardCardNodeType(eyebrow)) {
    return {
      targets: [
        { id: "story", label: "导演镜头", top: "50%" },
        { id: WORKFLOW_ASSET_INPUT_HANDLE, label: "资产输入", top: "50%", position: Position.Top },
      ],
      sources: [
        { id: "storyboard", label: "分镜输出", top: "50%" },
        { id: "visual_handoff", label: "视觉交接图", top: "50%", position: Position.Bottom },
      ],
    }
  }

  if (eyebrow === "prompt.storyboard") {
    return {
      targets: [{ id: "story", label: "分集原文", top: "50%" }],
      sources: [{ id: "prompt", label: "影视化剧本", top: "50%" }],
    }
  }

  if (eyebrow === "storyboard.image") {
    const isWorkChainStoryboardResult =
      workflowNodeDataIsWorkChainStoryboardResult(data)
    return {
      targets: isWorkChainStoryboardResult
        ? [{ id: "generates", label: "分镜生成写入", top: "50%" }]
        : [],
      sources: isWorkChainStoryboardResult
        ? [{ id: "image", label: "分镜图", top: "50%" }]
        : [
            { id: "image", label: "分镜图", top: "50%" },
            {
              id: "image_bottom",
              label: "分镜图",
              top: "50%",
              position: Position.Bottom,
            },
          ],
    }
  }

  if (eyebrow === "video.result") {
    return {
      targets: [{ id: "generates", label: "视频生成输出", top: "50%" }],
      sources: [{ id: "video", label: "视频片段输出", top: "50%" }],
    }
  }

  if (isWorkflowVideoTaskType(eyebrow)) {
    return {
      targets: [
        { id: WORKFLOW_VIDEO_INPUT_HANDLE, label: "文本/分镜输入", top: "50%" },
        {
          id: WORKFLOW_ASSET_INPUT_HANDLE,
          label: "资产输入",
          top: "50%",
          position: Position.Top,
        },
      ],
      sources: [{ id: "video", label: "视频片段输出", top: "50%" }],
    }
  }

  return {
    targets: [{ id: "note_input", label: "备注输入", top: "50%" }],
    sources: [{ id: "note_output", label: "备注输出", top: "50%" }],
  }
}

export function isWorkflowTaskCardType(nodeType: string) {
  return (
    nodeType === "prompt.storyboard" ||
    isDirectorBoardNodeType(nodeType) ||
    isStoryboardCardNodeType(nodeType) ||
    isWorkflowVideoTaskType(nodeType)
  )
}

export function workflowNodePrimaryDisplayStatus(
  data: WorkflowNodeData
): WorkflowNodeData["status"] {
  if (!isWorkflowTaskCardType(data.eyebrow)) return data.status
  if (
    workflowTaskIsRunningForPrimaryDisplay(data.activeTask) &&
    workflowTaskMatchesTaskCardPrimaryState(data, data.activeTask)
  ) {
    return "running"
  }
  if (data.status === "succeeded") return "succeeded"
  if (data.status === "ready") return "ready"
  return "draft"
}

export function workflowNodeGenerationStatusLabel(
  data: WorkflowNodeData,
  displayStatus: WorkflowNodeData["status"] = workflowNodePrimaryDisplayStatus(
    data
  )
) {
  if (data.eyebrow === "prompt.storyboard" && displayStatus === "blocked") return "待复核"
  if (isWorkflowTaskCardType(data.eyebrow)) {
    if (displayStatus === "succeeded") return "已完成"
    if (displayStatus === "running" || displayStatus === "processing") {
      return "运行中"
    }
    if (displayStatus === "ready") return "就绪"
    return "待生成"
  }
  if (displayStatus === "succeeded")
    return workflowNodeStatusLabel(displayStatus)
  if (displayStatus === "running" || displayStatus === "processing") {
    if (data.eyebrow === "prompt.storyboard") return "剧本生成中"
    if (isDirectorBoardNodeType(data.eyebrow)) return "分镜脚本生成中"
    if (data.eyebrow === "storyboard.image") return "分镜生成中"
    if (isWorkflowVideoTaskType(data.eyebrow)) return "视频生成中"
    return workflowNodeStatusLabel(displayStatus)
  }
  if (displayStatus === "failed") return "生成失败"
  return workflowNodeStatusLabel(displayStatus)
}

export const WORKFLOW_VIDEO_TASK_SCOPE_MISSING_MESSAGE =
  "视频生成缺少作用域标识，请重新创建任务卡"

export function isDefaultWorkChainVideoTaskNode(node?: WorkflowNodeLike | null) {
  return workflowVideoTaskScope(node) === "work_chain"
}

export function isWorkflowGeneratedMediaType(nodeType: string) {
  return isWorkflowResultImageType(nodeType) || nodeType === "video.result"
}

export function workflowNodeStatusLabel(status: string | undefined) {
  if (status === "ready") return "就绪"
  if (status === "draft") return "草稿"
  if (status === "waiting") return "等待"
  if (status === "waiting_upstream") return "等待上游"
  if (status === "running") return "运行中"
  if (status === "processing") return "处理中"
  if (status === "blocked") return "阻塞"
  if (status === "preflight_failed") return "预检失败"
  if (status === "queued") return "排队中"
  if (status === "cancelled" || status === "canceled") return "已取消"
  if (status === "succeeded") return "已完成"
  if (status === "failed") return "失败"
  return "草稿"
}


export type StoryboardVersionChangeKind =
  | "active"
  | "winner"
  | "winner-cleared"
  | "deleted"

export type StoryboardVersionActivationMode = "workflow" | "local"

export type StoryboardVersionDeleteMode = "workflow" | "none"

export type StoryboardVersionCanvasDrop = {
  version: StoryboardVersion
  sourceNode: StoryboardNode
  screenPosition: { x: number; y: number }
  label: string
}

export type StoryboardVersionCanvasCopy = Omit<
  StoryboardVersionCanvasDrop,
  "screenPosition"
>

export type StoryboardVersionCanvasPlacement = StoryboardVersionCanvasCopy & {
  position: { x: number; y: number }
}

export function isWorkflowGeneratedMediaResultNode(node?: StoryboardNode | null) {
  return Boolean(
    node &&
    (isWorkflowGeneratedMediaType(node.data.eyebrow) ||
      workflowNodeIsVisualHandoffAsset(node))
  )
}

export function isWorkflowVersionHistoryVisible(node: StoryboardNode) {
  const nodeType = node.data.eyebrow
  if (isWorkflowResultImageType(nodeType)) {
    return (
      isStoryboardResultImageData(node.data) || isEditableCanvasImageNode(node)
    )
  }
  return (
    isWorkflowGeneratedMediaResultNode(node) || isEditableCanvasImageNode(node)
  )
}

export function workflowNodeVersionActivationMode(
  node: StoryboardNode
): StoryboardVersionActivationMode {
  if (node.data.eyebrow === "video.result") return "workflow"
  if (isWorkChainStoryboardResultImageNode(node)) return "workflow"
  if (workflowNodeIsVisualHandoffAsset(node)) return "workflow"
  return "local"
}

export function workflowNodeVersionDeleteMode(
  node: StoryboardNode
): StoryboardVersionDeleteMode {
  return workflowNodeVersionActivationMode(node) === "workflow"
    ? "workflow"
    : "none"
}

export function workflowNodeCurrentVersionId(node: StoryboardNode) {
  return workflowNodeDataCurrentVersionId(node.data)
}

export function workflowCanDragVersionToCanvas(node: StoryboardNode) {
  return (
    isWorkflowGeneratedMediaResultNode(node) || isEditableCanvasImageNode(node)
  )
}

export function workflowVideoTaskCardIsReady(node?: StoryboardNode | null) {
  return workflowVideoTaskCardDataIsReady(node?.data)
}
