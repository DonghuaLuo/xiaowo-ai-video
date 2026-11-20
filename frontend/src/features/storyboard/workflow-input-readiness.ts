import { isWorkflowVideoTaskType } from "./workflow-video-task-types"
import { mediaPreviewSrc } from "@/shared/media"
import type { ModelCapabilitiesSnapshot } from "@/backend"
import {
  workflowVideoTaskDefaultDurationValue,
} from "./workflow-model-capabilities"

type WorkflowNodeData = {
  [key: string]: any
  generationConfig?: unknown
  modelCapabilitiesSnapshot?: ModelCapabilitiesSnapshot | null
  status: WorkflowStatus
  eyebrow?: string
  prompt?: unknown
  videoTaskCard?: unknown
  durationSeconds?: unknown
  videoPromptSyncing?: unknown
}

type WorkflowStatus =
  | "ready"
  | "draft"
  | "waiting"
  | "running"
  | "blocked"
  | "preflight_failed"
  | "queued"
  | "processing"
  | "waiting_upstream"
  | "cancelled"
  | "canceled"
  | "succeeded"
  | "failed"

type StoryboardNodeLike = {
  id: string
  data: WorkflowNodeData
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function optionalString(value: unknown) {
  const text = String(value ?? "").trim()
  return text || undefined
}

function compactReadableValue(value: unknown) {
  if (value == null) return ""
  if (typeof value === "string") return value.trim()
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  return ""
}


function isWorkflowResultImageType(value?: string | null) {
  return (value ?? "") === "storyboard.image"
}

function isImageReferenceMediaType(value: unknown) {
  const text = String(value ?? "").trim().toLowerCase()
  return text === "image" || text.startsWith("image/")
}

function isVideoReferenceMediaType(value: unknown) {
  const text = String(value ?? "").trim().toLowerCase()
  return text === "video" || text.startsWith("video/")
}

const WORKFLOW_ASSET_INPUT_HANDLE = "asset_input"
const WORKFLOW_VIDEO_INPUT_HANDLE = "video_input"

function canonicalWorkflowInputHandle(handle?: string | null) {
  const value = String(handle ?? "")
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[\s:-]+/g, "_")
    .toLowerCase()
  if (!value) return ""
  const matches = (target: string) =>
    value === target ||
    value.startsWith(`${target}_`) ||
    value.endsWith(`_${target}`) ||
    value.includes(`_${target}_`)
  if (matches(WORKFLOW_ASSET_INPUT_HANDLE)) return WORKFLOW_ASSET_INPUT_HANDLE
  if (matches(WORKFLOW_VIDEO_INPUT_HANDLE)) return WORKFLOW_VIDEO_INPUT_HANDLE
  return ""
}

function canonicalTargetSlot(handle?: string | null) {
  const value = (handle ?? "")
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[\s-]+/g, "_")
    .toLowerCase()
  if (canonicalWorkflowInputHandle(value)) return "storyboard_image"
  if (value === "character") return "character_reference"
  if (value === "creature") return "creature_reference"
  if (value === "scene") return "scene_reference"
  if (value === "prop") return "prop_reference"
  if (value === "asset" || value === "reference") return "storyboard_image"
  if (
    value === "visual_handoff" ||
    value === "visual_handoff_reference" ||
    value === "handoff" ||
    value === "continuity"
  ) return "visual_handoff_reference"
  if (value === "visual" || value === "visual_reference") return "storyboard_image"
  if (value === "video_reference") return "reference_video"
  if (value === "image") return "storyboard_image"
  if (value === "frame_image") return "frame_reference"
  return value || "storyboard_image"
}

function isInlineMediaSource(value?: unknown) {
  return String(value ?? "").trim().toLowerCase().startsWith("data:")
}

function canvasMediaReference(media: unknown) {
  const source = recordValue(media)
  if (!Object.keys(source).length) return null
  const reference = { ...source }
  if (isInlineMediaSource(reference.preview)) delete reference.preview
  if (isInlineMediaSource(reference.url)) delete reference.url
  return reference as Parameters<typeof mediaPreviewSrc>[0]
}

function workflowNodeDataCurrentVersionId(data?: Record<string, unknown> | null) {
  return (
    optionalString(data?.activeVersionId) ||
    optionalString(data?.activeMediaVersionId) ||
    optionalString(data?.mediaVersionId) ||
    null
  )
}

function workflowNodeDataHasConcreteMediaReference(
  data?: Record<string, unknown> | null
) {
  const media = canvasMediaReference(data?.media ?? data?.storage ?? null)
  const record = data ?? {}
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

function promptTextForNode(data: WorkflowNodeData) {
  if (isWorkflowVideoTaskType(data.eyebrow)) {
    return compactReadableValue(recordValue(data.videoTaskCard).finalVideoPrompt)
  }
  return compactReadableValue(data.prompt)
}

function numberInputValue(value: unknown) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? String(parsed) : ""
}

function workflowVideoTaskSelectedDurationValue(data?: WorkflowNodeData | null) {
  if (!data) return ""
  const taskCard = recordValue(data.videoTaskCard)
  return (
    numberInputValue(data.durationSeconds ?? taskCard.durationSeconds) ||
    workflowVideoTaskDefaultDurationValue(data)
  )
}

function workflowVideoTaskResolvedDurationValue(data?: WorkflowNodeData | null) {
  if (!data || !promptTextForNode(data).trim()) return ""
  return workflowVideoTaskSelectedDurationValue(data)
}

function workflowNodeStatus(value: string | undefined): WorkflowStatus {
  const allowed = new Set([
    "ready",
    "waiting",
    "running",
    "blocked",
    "preflight_failed",
    "queued",
    "processing",
    "waiting_upstream",
    "cancelled",
    "canceled",
    "succeeded",
    "failed",
  ])
  return allowed.has(value ?? "") ? (value as WorkflowStatus) : "draft"
}
function inputLinkDirectIds(link: Record<string, unknown>) {
  return [
    link.id,
    link.linkId,
    link.link_id,
    link.inputLinkId,
    link.input_link_id,
  ]
    .map((value) => String(value ?? "").trim())
    .filter(Boolean)
}

function inputLinkSourceSignature(link: Record<string, unknown>) {
  const sourceNodeId = String(
    link.sourceNodeId ?? link.source_node_id ?? ""
  ).trim()
  if (!sourceNodeId) return ""
  const targetSlot = canonicalTargetSlot(
    String(link.targetSlot ?? link.target_slot ?? link.slot ?? "")
  )
  return `${sourceNodeId}|${targetSlot}`
}

function inputLinkReferenceMediaIds(link: Record<string, unknown>) {
  const media = recordValue(link.media)
  const storage = recordValue(link.storage)
  const values = [
    link.mediaVersionId,
    link.media_version_id,
    link.sourceVersionId,
    link.source_version_id,
    link.versionId,
    link.version_id,
    link.mediaId,
    link.media_id,
    media.id,
    media.mediaId,
    media.media_id,
    media.mediaVersionId,
    media.media_version_id,
    media.sourceVersionId,
    media.source_version_id,
    media.versionId,
    media.version_id,
    storage.id,
    storage.mediaId,
    storage.media_id,
    storage.mediaVersionId,
    storage.media_version_id,
    storage.sourceVersionId,
    storage.source_version_id,
    storage.versionId,
    storage.version_id,
  ]
  return [
    ...new Set(
      values.map((value) => String(value ?? "").trim()).filter(Boolean)
    ),
  ]
}

function inputLinkMatchesDirectId(
  link: Record<string, unknown>,
  inputLinkId: string
) {
  const normalizedInputLinkId = String(inputLinkId ?? "").trim()
  if (!normalizedInputLinkId) return false
  return inputLinkDirectIds(link).includes(normalizedInputLinkId)
}

function inputLinkMatchesAnyDirectId(
  link: Record<string, unknown>,
  inputLinkIds: Set<string>
) {
  if (!inputLinkIds.size) return false
  return inputLinkDirectIds(link).some((id) => inputLinkIds.has(id))
}

function appendInputLinkThumbnailRows(
  rows: Array<Record<string, unknown>> | undefined,
  inputLink: Record<string, unknown>
) {
  const currentRows = Array.isArray(rows) ? rows : []
  const nextDirectIds = new Set(inputLinkDirectIds(inputLink))
  const nextSourceSignature = inputLinkSourceSignature(inputLink)
  const filteredRows = currentRows.filter((row) => {
    const record = recordValue(row)
    const directIds = inputLinkDirectIds(record)
    if (directIds.some((id) => nextDirectIds.has(id))) return false
    const sourceSignature = inputLinkSourceSignature(record)
    return !nextSourceSignature || sourceSignature !== nextSourceSignature
  })
  return [...filteredRows, inputLink]
}

function filterRemovedInputLinkRows(
  rows: Array<Record<string, unknown>> | undefined,
  removedLinks: Record<string, unknown>[],
  remainingLinks: Record<string, unknown>[]
) {
  if (!Array.isArray(rows) || !removedLinks.length) return rows
  const removedDirectIds = new Set(removedLinks.flatMap(inputLinkDirectIds))
  const remainingDirectIds = new Set(remainingLinks.flatMap(inputLinkDirectIds))
  const removedSourceSignatures = new Set(
    removedLinks.map(inputLinkSourceSignature).filter(Boolean)
  )
  const remainingSourceSignatures = new Set(
    remainingLinks.map(inputLinkSourceSignature).filter(Boolean)
  )
  return rows.filter((row) => {
    const record = recordValue(row)
    const directIds = inputLinkDirectIds(record)
    if (
      directIds.some(
        (id) => removedDirectIds.has(id) && !remainingDirectIds.has(id)
      )
    ) {
      return false
    }
    const sourceSignature = inputLinkSourceSignature(record)
    if (
      sourceSignature &&
      removedSourceSignatures.has(sourceSignature) &&
      !remainingSourceSignatures.has(sourceSignature)
    ) {
      return false
    }
    return true
  })
}

function filterRemovedInputLinkIds(
  values: string[] | undefined,
  removedLinks: Record<string, unknown>[],
  remainingLinks: Record<string, unknown>[]
) {
  if (!Array.isArray(values) || !removedLinks.length) return values
  const removedMediaIds = new Set(
    removedLinks.flatMap(inputLinkReferenceMediaIds)
  )
  const remainingMediaIds = new Set(
    remainingLinks.flatMap(inputLinkReferenceMediaIds)
  )
  if (!removedMediaIds.size) return values
  return values.filter((value) => {
    const text = String(value ?? "").trim()
    return !text || !removedMediaIds.has(text) || remainingMediaIds.has(text)
  })
}

function filterRemovedInputAssetRefs(
  assetRefs: WorkflowNodeData["assetRefs"],
  removedLinks: Record<string, unknown>[],
  remainingLinks: Record<string, unknown>[]
): WorkflowNodeData["assetRefs"] {
  if (!Array.isArray(assetRefs)) return assetRefs
  return filterRemovedInputLinkRows(assetRefs, removedLinks, remainingLinks)
}

const IMAGE_REFERENCE_FILE_PATTERN =
  /\.(png|jpe?g|webp|gif|bmp|tiff?|avif)(?:[?#].*)?$/i
const VIDEO_REFERENCE_FILE_PATTERN = /\.(mp4|m4v|mov|webm|avi|mkv)(?:[?#].*)?$/i
const VIDEO_IMAGE_REFERENCE_TARGET_SLOTS = new Set([
  "custom_image",
  "storyboard_image",
  "character_reference",
  "creature_reference",
  "scene_reference",
  "prop_reference",
  "visual_handoff_reference",
])

function workflowInputLinkPath(link: Record<string, unknown>) {
  const media = recordValue(link.media)
  const storage = recordValue(link.storage)
  for (const record of [link, media, storage]) {
    for (const key of [
      "path",
      "file",
      "filePath",
      "file_path",
      "relativePath",
      "relative_path",
      "url",
      "preview",
      "previewUrl",
      "preview_url",
      "previewSrc",
      "preview_src",
      "thumbnail",
      "thumbnailUrl",
      "thumbnail_url",
      "dataUrl",
      "data_url",
    ]) {
      const value = optionalString(record[key])
      if (value) return value
    }
  }
  return ""
}

function workflowInputLinkMediaKind(
  link: Record<string, unknown>
): "image" | "video" | "" {
  const media = recordValue(link.media)
  const storage = recordValue(link.storage)
  for (const record of [link, media, storage]) {
    for (const key of [
      "mediaKind",
      "media_kind",
      "mediaType",
      "media_type",
      "kind",
      "mimeType",
      "mime_type",
    ]) {
      const value = record[key]
      if (isVideoReferenceMediaType(value)) return "video"
      if (isImageReferenceMediaType(value)) return "image"
    }
  }
  const path = workflowInputLinkPath(link)
  if (VIDEO_REFERENCE_FILE_PATTERN.test(path)) return "video"
  if (IMAGE_REFERENCE_FILE_PATTERN.test(path)) return "image"
  return ""
}

function workflowNodeCanSupplyImageReference(node?: StoryboardNodeLike | null) {
  if (!node) return false
  const nodeType = node.data.eyebrow
  if (nodeType === "video.result" || isWorkflowVideoTaskType(nodeType))
    return false
  if (nodeType === "asset.image" || isWorkflowResultImageType(nodeType))
    return true
  if (nodeType === "media.external") {
    return workflowInputLinkMediaKind(recordValue(node.data)) === "image"
  }
  return false
}

function workflowInputLinkHasMediaReference(link: Record<string, unknown>) {
  const media = recordValue(link.media)
  const storage = recordValue(link.storage)
  if (
    optionalString(link.mediaId) ||
    optionalString(link.media_id) ||
    optionalString(link.mediaVersionId) ||
    optionalString(link.media_version_id) ||
    optionalString(link.sourceVersionId) ||
    optionalString(link.source_version_id) ||
    optionalString(link.activeMediaVersionId) ||
    optionalString(link.active_media_version_id) ||
    optionalString(link.activeVersionId) ||
    optionalString(link.active_version_id) ||
    optionalString(link.versionId) ||
    optionalString(link.version_id) ||
    workflowInputLinkPath(link) ||
    workflowInputLinkPath(media) ||
    workflowInputLinkPath(storage)
  ) {
    return true
  }
  return [media, storage].some((record) =>
    Boolean(
      optionalString(record.id) ||
      optionalString(record.mediaId) ||
      optionalString(record.media_id) ||
      optionalString(record.mediaVersionId) ||
      optionalString(record.media_version_id) ||
      optionalString(record.sourceVersionId) ||
      optionalString(record.source_version_id) ||
      optionalString(record.activeMediaVersionId) ||
      optionalString(record.active_media_version_id) ||
      optionalString(record.activeVersionId) ||
      optionalString(record.active_version_id) ||
      optionalString(record.versionId) ||
      optionalString(record.version_id)
    )
  )
}

function workflowNodeHasCurrentImageReference(node?: StoryboardNodeLike | null) {
  return Boolean(
    workflowNodeCanSupplyImageReference(node) &&
    workflowNodeDataHasConcreteMediaReference(node?.data)
  )
}

function workflowInputLinkHasImageReference(
  link: Record<string, unknown>,
  nodes?: StoryboardNodeLike[]
) {
  const slot = canonicalTargetSlot(
    String(link.slot ?? link.targetSlot ?? link.target_slot ?? "")
  )
  if (slot && !VIDEO_IMAGE_REFERENCE_TARGET_SLOTS.has(slot)) return false
  const sourceNodeId = String(
    link.sourceNodeId ?? link.source_node_id ?? ""
  ).trim()
  const sourceNode = sourceNodeId
    ? nodes?.find((node) => node.id === sourceNodeId)
    : undefined
  if (sourceNode) {
    return workflowNodeHasCurrentImageReference(sourceNode)
  }
  const sourceNodeType = String(
    link.sourceNodeType ?? link.source_node_type ?? ""
  ).trim()
  if (
    sourceNodeType === "video.result" ||
    isWorkflowVideoTaskType(sourceNodeType)
  ) {
    return false
  }
  if (
    sourceNodeType === "asset.image" ||
    isWorkflowResultImageType(sourceNodeType)
  ) {
    const mediaKind = workflowInputLinkMediaKind(link)
    if (mediaKind === "video") return false
    return mediaKind === "image" || workflowInputLinkHasMediaReference(link)
  }
  const mediaKind = workflowInputLinkMediaKind(link)
  if (mediaKind === "video") return false
  if (mediaKind === "image") return true
  if (
    isImageReferenceMediaType(link.mediaType) ||
    isImageReferenceMediaType(link.media_type) ||
    isImageReferenceMediaType(link.kind)
  ) {
    return true
  }
  const mimeType = String(link.mimeType ?? link.mime_type ?? "")
    .trim()
    .toLowerCase()
  if (mimeType.startsWith("image/")) return true
  const media = recordValue(link.media)
  const storage = recordValue(link.storage)
  if (
    isImageReferenceMediaType(media.kind) ||
    isImageReferenceMediaType(media.mediaType) ||
    isImageReferenceMediaType(media.media_type) ||
    isImageReferenceMediaType(storage.kind) ||
    isImageReferenceMediaType(storage.mediaType) ||
    isImageReferenceMediaType(storage.media_type)
  ) {
    return true
  }
  const path = workflowInputLinkPath(link)
  return IMAGE_REFERENCE_FILE_PATTERN.test(path)
}

function workflowHasImageReferenceInputLinks(inputLinks: unknown) {
  return Array.isArray(inputLinks)
    ? inputLinks.some((link) =>
        workflowInputLinkHasImageReference(recordValue(link))
      )
    : false
}

function workflowRowsHaveImageReference(
  rows: unknown,
  nodes?: StoryboardNodeLike[]
) {
  return Array.isArray(rows)
    ? rows.some((row) => {
        const record = recordValue(row)
        return workflowInputLinkHasImageReference(record, nodes)
      })
    : false
}

function workflowVideoTaskHasManualPrompt(node?: StoryboardNodeLike | null) {
  if (node?.data.eyebrow === "video.character_replace") return true
  return Boolean(node && promptTextForNode(node.data).trim())
}

function workflowVideoTaskHasManualImageReference(
  node?: StoryboardNodeLike | null,
  nodes?: StoryboardNodeLike[]
) {
  const data = node?.data
  if (!data) return false
  if (data.eyebrow === "video.character_replace") {
    const links = Array.isArray(data.inputLinks) ? data.inputLinks.map(recordValue).filter((row) => row.enabled !== false) : []
    const images = links.filter((row) => ["character_reference", "creature_reference", "custom_image"].includes(
      canonicalTargetSlot(String(row.slot ?? row.targetSlot ?? ""))))
    const videos = links.filter((row) => canonicalTargetSlot(String(row.slot ?? row.targetSlot ?? "")) === "reference_video")
    return links.length === images.length + videos.length &&
      images.length > 0 && images.every((row) => workflowInputLinkHasImageReference(row, nodes)) &&
      videos.length === 1 && (() => {
        const sourceId = String(videos[0].sourceNodeId ?? videos[0].source_node_id ?? "")
        const source = nodes?.find((row) => row.id === sourceId)
        return source ? workflowNodeDataHasConcreteMediaReference(source.data) : workflowInputLinkHasMediaReference(videos[0])
      })()
  }
  if (data.eyebrow === "video.keyframe") {
    return Array.isArray(data.inputLinks) && data.inputLinks.some((row) => {
      const link = recordValue(row)
      const slot = canonicalTargetSlot(String(link.slot ?? link.targetSlot ?? link.target_slot ?? ""))
      return slot === "frame_reference" && link.frameRole !== "last_frame" &&
        link.useNativeFrame !== false && workflowInputLinkHasImageReference({ ...link, slot: "storyboard_image" }, nodes)
    })
  }
  return workflowRowsHaveImageReference(data.inputLinks, nodes)
}

function workflowVideoTaskHasDurationSetting(
  node?: StoryboardNodeLike | null,
  _standaloneVideoTask?: boolean
) {
  return Boolean(node && workflowVideoTaskSelectedDurationValue(node.data))
}

function workflowVideoTaskCardHasStandaloneVideoInputs(
  node?: StoryboardNodeLike | null,
  standaloneVideoTask?: boolean,
  nodes?: StoryboardNodeLike[]
) {
  return Boolean(
    node &&
    isWorkflowVideoTaskType(node.data.eyebrow) &&
    workflowVideoTaskHasManualPrompt(node) &&
    workflowVideoTaskHasManualImageReference(node, nodes) &&
    workflowVideoTaskHasDurationSetting(node, standaloneVideoTask)
  )
}

function workflowVideoTaskStandaloneInputNotReadyMessage(
  node?: StoryboardNodeLike | null,
  nodes?: StoryboardNodeLike[]
) {
  if (!workflowVideoTaskHasManualImageReference(node, nodes)) {
    if (node?.data.eyebrow === "video.character_replace") return "请关联一段可用源视频与角色图"
    return node?.data.eyebrow === "video.keyframe" ? "请先关联并开启原生首帧" : "请先关联至少一张图片资产"
  }
  if (!workflowVideoTaskHasManualPrompt(node)) {
    return "请先填写并保存视频提示词"
  }
  if (!workflowVideoTaskHasDurationSetting(node)) {
    return "请先设置时长"
  }
  return "请补齐独立视频生成输入"
}

function workflowVideoTaskFinalPromptNotReadyMessage(
  node?: StoryboardNodeLike | null
) {
  if (node?.data.videoPromptSyncing) {
    return "视频生成最终提示词正在更新，请稍后再生成"
  }
  if (!node || !promptTextForNode(node.data).trim()) {
    return "请先在视频生成右键菜单中点击生成提示词"
  }
  if (!workflowVideoTaskResolvedDurationValue(node.data)) {
    return "请先设置时长"
  }
  return "请先在视频生成右键菜单中点击生成提示词"
}

function workflowVideoTaskWorkChainPromptNotReadyMessage(
  node: StoryboardNodeLike,
  _nodes: StoryboardNodeLike[]
) {
  return workflowVideoTaskFinalPromptNotReadyMessage(node)
}

function statusAfterInputLinkChange(
  status?: string | null
): WorkflowNodeData["status"] {
  const current = String(status ?? "")
  return workflowNodeStatus(current || undefined)
}

export {
  appendInputLinkThumbnailRows,
  filterRemovedInputLinkRows,
  filterRemovedInputLinkIds,
  filterRemovedInputAssetRefs,
  inputLinkDirectIds,
  inputLinkReferenceMediaIds,
  inputLinkMatchesDirectId,
  inputLinkMatchesAnyDirectId,
  statusAfterInputLinkChange,
  workflowInputLinkHasImageReference,
  workflowInputLinkHasMediaReference,
  workflowInputLinkMediaKind,
  workflowInputLinkPath,
  isImageReferenceMediaType,
  isVideoReferenceMediaType,
  workflowNodeCanSupplyImageReference,
  workflowNodeHasCurrentImageReference,
  workflowHasImageReferenceInputLinks,
  workflowRowsHaveImageReference,
  workflowVideoTaskHasManualPrompt,
  workflowVideoTaskHasManualImageReference,
  workflowVideoTaskHasDurationSetting,
  workflowVideoTaskCardHasStandaloneVideoInputs,
  workflowVideoTaskStandaloneInputNotReadyMessage,
  workflowVideoTaskFinalPromptNotReadyMessage,
  workflowVideoTaskWorkChainPromptNotReadyMessage,
  workflowVideoTaskSelectedDurationValue,
}
