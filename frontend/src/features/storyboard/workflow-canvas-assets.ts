import type {
  AssetItem,
  AssetType,
  MediaAsset,
  StoryboardVersion,
  WorkflowMediaRecord,
} from "@/backend"
import { mediaPreviewSrc } from "@/shared/media"

type WorkflowNodeData = Record<string, any>
type StoryboardNodeLike = { id: string; data: Record<string, any> }

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function optionalString(value: unknown) {
  const text = String(value ?? "").trim()
  return text || undefined
}

function canvasMediaReference(media?: MediaAsset | null): MediaAsset | null {
  if (!media) return null
  const isInlineMediaSource = (value?: string | null) =>
    value?.trim().toLowerCase().startsWith("data:") ?? false
  const preview =
    media.preview && !isInlineMediaSource(media.preview)
      ? media.preview
      : undefined
  const url =
    media.url && !isInlineMediaSource(media.url) ? media.url : undefined
  return { ...media, url, preview }
}

function workflowNodeDataCurrentVersionId(data?: WorkflowNodeData | null) {
  return (
    optionalString(data?.activeVersionId) ||
    optionalString(data?.activeMediaVersionId) ||
    optionalString(data?.mediaVersionId) ||
    null
  )
}

function storyboardVersionIsActive(version?: StoryboardVersion | null) {
  if (!version) return false
  const row = version as Record<string, unknown>
  return Boolean(
    row.active === true ||
      row.isActive === true ||
      row.activeVersion === true ||
      row.active_version === true
  )
}

function storyboardVersionPreviewSrc(version: StoryboardVersion) {
  return mediaPreviewSrc(version.media, version.preview)
}

function storyboardVersionPreviewKind(
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

function storyboardVersionCanvasMedia(version: StoryboardVersion) {
  const media: MediaAsset = version.media ?? {}
  return canvasMediaReference({
    ...media,
    id: media.id || "storyboard-version-" + version.id,
    kind: storyboardVersionPreviewKind(version),
    preview: media.preview ?? version.preview ?? undefined,
  })
}
function mediaPurposeTargetSlot(purpose?: string | null) {
  const value = String(purpose ?? "").trim()
  if (value === "custom_image") return value
  if (value === "frame_image" || value === "frame_reference") return "frame_reference"
  if (
    value === "storyboard_image" ||
    value === "visual_handoff" ||
    value === "visual_handoff_reference"
  ) {
    return value === "visual_handoff" ? "visual_handoff_reference" : value
  }
  return ""
}

function mediaPurposeMaterialSlot(purpose?: string | null) {
  const value = String(purpose ?? "").trim()
  if (value === "custom_image") return value
  if (value === "frame_image" || value === "frame_reference") return "frame_reference"
  if (value === "visual_reference") return "storyboard_image"
  if (value === "visual_handoff" || value === "visual_handoff_reference") {
    return "visual_handoff_reference"
  }
  if (
    value === "character_reference" ||
    value === "creature_reference" ||
    value === "scene_reference" ||
    value === "prop_reference" ||
    value === "storyboard_image"
  ) {
    return value
  }
  return ""
}

function mediaPurposeAssetType(purpose?: string | null) {
  const value = String(purpose ?? "").trim()
  if (value === "custom_image") return value
  if (value === "video") return "video"
  if (value === "frame_image" || value === "frame_reference") return "frame_image"
  if (value === "character_reference") return "characters"
  if (value === "creature_reference") return "creatures"
  if (value === "scene_reference") return "scenes"
  if (value === "prop_reference") return "props"
  if (value === "storyboard_image" || value === "visual_reference")
    return "storyboard_image"
  if (value === "visual_handoff" || value === "visual_handoff_reference") {
    return "visual_handoff"
  }
  return ""
}

type CanvasProjectAssetType = Extract<
  AssetType,
  "characters" | "creatures" | "scenes" | "props"
>

function mediaPurposeProjectAssetType(
  purpose?: string | null
): CanvasProjectAssetType | "" {
  const assetType = mediaPurposeAssetType(purpose)
  return assetType === "characters" ||
    assetType === "creatures" ||
    assetType === "scenes" ||
    assetType === "props"
    ? assetType
    : ""
}

function canvasAssetNameKey(value?: string | null) {
  return String(value ?? "")
    .trim()
    .replace(/\s+/g, " ")
    .toLocaleLowerCase()
}

function canvasProjectAssetNameExists(rows: AssetItem[], name: string) {
  const target = canvasAssetNameKey(name)
  if (!target) return false
  return rows.some((row) => canvasAssetNameKey(row.name) === target)
}

const CANVAS_PROJECT_ASSET_TYPE_VALUES = new Set<CanvasProjectAssetType>([
  "characters",
  "creatures",
  "scenes",
  "props",
])

function canvasProjectAssetTypeFromValue(
  value: unknown
): CanvasProjectAssetType | "" {
  const text = String(value ?? "")
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[\s-]+/g, "_")
    .toLowerCase()
  if (!text) return ""
  if (CANVAS_PROJECT_ASSET_TYPE_VALUES.has(text as CanvasProjectAssetType)) {
    return text as CanvasProjectAssetType
  }
  if (text === "character" || text === "character_reference") {
    return "characters"
  }
  if (
    text === "creature" ||
    text === "creature_reference" ||
    text === "monster" ||
    text === "monsters" ||
    text === "beast" ||
    text === "beasts"
  ) {
    return "creatures"
  }
  if (text === "scene" || text === "scene_reference") {
    return "scenes"
  }
  if (text === "prop" || text === "prop_reference") {
    return "props"
  }
  return ""
}

function canvasProjectAssetTypeFromData(
  data?: unknown
): CanvasProjectAssetType | "" {
  const record = recordValue(data)
  return (
    canvasProjectAssetTypeFromValue(record.rootAssetType) ||
    canvasProjectAssetTypeFromValue(record.assetType) ||
    canvasProjectAssetTypeFromValue(record.asset_type) ||
    canvasProjectAssetTypeFromValue(record.assetKind) ||
    canvasProjectAssetTypeFromValue(record.asset_kind) ||
    canvasProjectAssetTypeFromValue(record.mediaPurpose) ||
    canvasProjectAssetTypeFromValue(record.media_purpose) ||
    canvasProjectAssetTypeFromValue(record.preferredTargetSlot) ||
    canvasProjectAssetTypeFromValue(record.preferred_target_slot)
  )
}

function canvasProjectAssetTypeFromNode(
  node?: StoryboardNodeLike | null
): CanvasProjectAssetType | "" {
  return canvasProjectAssetTypeFromData(node?.data)
}

function canvasProjectAssetAspectRatio(
  assetType?: CanvasProjectAssetType | ""
) {
  if (assetType === "scenes") return "3:2"
  if (assetType === "props") return "2:1"
  if (assetType === "characters" || assetType === "creatures") return "16:9"
  return ""
}

function canvasProjectAssetResolutionKeys(
  assetType?: CanvasProjectAssetType | ""
) {
  if (assetType === "characters" || assetType === "creatures") {
    return ["character_resolution", "characterResolution"]
  }
  if (assetType === "scenes") return ["scene_resolution", "sceneResolution"]
  if (assetType === "props") return ["prop_resolution", "propResolution"]
  return []
}

function canvasAssetNodeLibraryName(node?: StoryboardNodeLike | null) {
  return String(node?.data.assetName ?? node?.data.title ?? "").trim()
}

function canvasAssetNodeProjectAssetIdentity(node?: StoryboardNodeLike | null) {
  if (!node)
    return { assetType: "" as CanvasProjectAssetType | "", assetId: "" }
  const data = recordValue(node.data)
  const rootAssetId = optionalString(data.rootAssetId)
  const rootAssetType = canvasProjectAssetTypeFromValue(data.rootAssetType)
  return {
    assetType: rootAssetType,
    assetId: rootAssetId && rootAssetType ? rootAssetId : "",
  }
}

function canvasRootAssetFields({
  assetId,
  assetType,
  projectId,
}: {
  assetId?: string
  assetType?: string
  projectId?: string
}) {
  const normalizedAssetId = optionalString(assetId)
  const normalizedAssetType = canvasProjectAssetTypeFromValue(assetType)
  const normalizedProjectId = optionalString(projectId)
  if (!normalizedAssetId || !normalizedAssetType) return {}
  return {
    rootAssetId: normalizedAssetId,
    rootAssetType: normalizedAssetType,
    ...(normalizedProjectId ? { rootAssetProjectId: normalizedProjectId } : {}),
  }
}

function canvasAssetNodeRootFields(
  node?: StoryboardNodeLike | null,
  projectId?: string
) {
  const identity = canvasAssetNodeProjectAssetIdentity(node)
  return canvasRootAssetFields({
    assetId: identity.assetId,
    assetType: identity.assetType,
    projectId:
      optionalString(node?.data.rootAssetProjectId) ||
      optionalString(projectId),
  })
}

function canvasAssetNodeInProjectLibrary(
  node: StoryboardNodeLike | null | undefined,
  rows?: AssetItem[]
) {
  if (!node) return false
  const { assetType, assetId } = canvasAssetNodeProjectAssetIdentity(node)
  if (!assetType || !assetId) return false
  if (!rows) {
    const sourceType = String(node.data.sourceType ?? "")
      .trim()
      .toLowerCase()
    return sourceType === "asset"
  }
  if (!rows?.length) return false
  return rows.some((row) => String(row.id ?? "").trim() === assetId)
}

function assetRangeBindingValueExists(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(assetRangeBindingValueExists)
  if (value && typeof value === "object") {
    const record = recordValue(value)
    return Boolean(
      optionalString(record.id) ||
      optionalString(record.rangeId) ||
      optionalString(record.range_id) ||
      optionalString(record.assetRangeId) ||
      optionalString(record.asset_range_id)
    )
  }
  return Boolean(optionalString(value))
}

function sourceRefRangeBindingValueExists(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(sourceRefRangeBindingValueExists)
  if (value && typeof value === "object") {
    const record = recordValue(value)
    return Boolean(
      optionalString(record.assetRangeId) ||
      optionalString(record.asset_range_id) ||
      optionalString(record.rangeId) ||
      optionalString(record.range_id)
    )
  }
  return false
}

function assetItemHasSplitRangeBinding(item?: AssetItem | null) {
  const record = recordValue(item)
  return (
    [
      record.assetRangeId,
      record.asset_range_id,
      record.assetRangeIds,
      record.asset_range_ids,
    ].some(assetRangeBindingValueExists) ||
    [record.sourceRefs, record.source_refs].some(
      sourceRefRangeBindingValueExists
    )
  )
}

function canvasAssetNodeReferencesSplitAsset(
  node: StoryboardNodeLike | null | undefined,
  rows?: AssetItem[]
) {
  if (!node) return false
  const assetId = String(node.data.assetId ?? "").trim()
  if (node.data.sourceType !== "asset" || !assetId) return false
  const row = rows?.find((item) => String(item.id ?? "").trim() === assetId)
  return assetItemHasSplitRangeBinding(row)
}

const CANVAS_PROJECT_ASSET_REFERENCE_KEYS = [
  "assetId",
  "asset_id",
  "sourceVersionId",
  "source_version_id",
  "assetVersionId",
  "asset_version_id",
  "mediaVersionId",
  "media_version_id",
  "activeMediaVersionId",
  "active_media_version_id",
  "activeVersionId",
  "active_version_id",
  "winnerVersionId",
  "winner_version_id",
] as const

function detachCanvasProjectAssetReference(data: WorkflowNodeData) {
  const record = data as Record<string, unknown>
  record.sourceType = "asset_copy"
  delete record.source_type
  for (const key of CANVAS_PROJECT_ASSET_REFERENCE_KEYS) {
    delete record[key]
  }
  record.mediaBindingMode = "pinned"
}

function canvasAssetPromptForLibrary(node: StoryboardNodeLike) {
  const data = node.data
  const prompts = recordValue(data.prompts)
  return (
    [
      prompts.assetImagePrompt,
      prompts.designPrompt,
      prompts.imagePrompt,
      prompts.visualPrompt,
      typeof data.prompt === "string" ? data.prompt : "",
      data.summary,
      data.content,
      data.title,
    ]
      .map((value) => String(value ?? "").trim())
      .find(Boolean) ?? ""
  )
}

function canvasAssetMediaKey(media?: MediaAsset | null) {
  const record = recordValue(media)
  return (
    [
      media?.id,
      media?.relativePath,
      media?.relative_path,
      media?.file,
      media?.path,
      media?.filePath,
      media?.url,
      media?.preview,
      record.pngFile,
    ]
      .map((value) => String(value ?? "").trim())
      .find(Boolean) ?? ""
  )
}

function canvasWorkflowMediaRecordForNode(
  records: WorkflowMediaRecord[],
  node: StoryboardNodeLike
): WorkflowMediaRecord | null {
  const mediaId = String(node.data.mediaId ?? "").trim()
  return (
    records.find((record) => {
      const recordNodeId = String(
        record.nodeId ?? record.canvasNodeId ?? record.canvas_node_id ?? ""
      ).trim()
      const recordId = String(record.id ?? "").trim()
      return (
        Boolean(recordNodeId && recordNodeId === node.id) ||
        Boolean(mediaId && recordId === mediaId)
      )
    }) ?? null
  )
}

function canvasAssetVersionPayloadsFromNode(
  node: StoryboardNodeLike,
  versions: StoryboardVersion[] = [],
  workflowMediaRecord?: WorkflowMediaRecord | null
) {
  const rows: Array<Record<string, unknown>> = []
  const seenVersionIds = new Set<string>()
  const seenMediaKeys = new Set<string>()
  const addVersion = (value: {
    id?: string | null
    title?: string | null
    createdAt?: string | null
    status?: string | null
    summary?: string | null
    source?: string | null
    preview?: string | null
    media?: MediaAsset | null
    payload?: Record<string, unknown> | null
    model?: string | null
    provider?: string | null
    generationError?: string | null
    generationDebug?: unknown
    active?: boolean | null
  }) => {
    const media = canvasMediaReference(value.media ?? null)
    if (!media || !mediaPreviewSrc(media, value.preview)) return
    const mediaKey = canvasAssetMediaKey(media)
    const versionId = String(
      value.id || media.id || `canvas-version-${rows.length + 1}`
    ).trim()
    if (versionId && seenVersionIds.has(versionId)) return
    if (mediaKey && seenMediaKeys.has(mediaKey)) return
    if (versionId) seenVersionIds.add(versionId)
    if (mediaKey) seenMediaKeys.add(mediaKey)
    const sourcePayload = recordValue(value.payload)
    const payload = {
      ...sourcePayload,
      versionSource:
        String(sourcePayload.versionSource ?? value.source ?? "").trim() ||
        "canvas_node",
      sourceNodeId: String(sourcePayload.sourceNodeId ?? "").trim() || node.id,
    }
    rows.push({
      id: versionId,
      title: value.title || node.data.title || "画布版本",
      status: value.status || "ready",
      summary: value.summary || "",
      source: value.source || "canvas-node-version",
      payload,
      media,
      ...(value.createdAt ? { createdAt: value.createdAt } : {}),
      ...(value.preview ? { preview: value.preview } : {}),
      ...(value.model ? { model: value.model } : {}),
      ...(value.provider ? { provider: value.provider } : {}),
      ...(value.generationError
        ? { generationError: value.generationError }
        : {}),
      ...(value.generationDebug
        ? { generationDebug: value.generationDebug }
        : {}),
      ...(value.active ? { active: true } : {}),
    })
  }

  const recordMedia = canvasMediaReference(
    (workflowMediaRecord?.media as MediaAsset | undefined) ??
      (workflowMediaRecord?.storage as MediaAsset | undefined) ??
      null
  )
  if (recordMedia) {
    addVersion({
      id: workflowMediaRecord?.id
        ? `import-${String(workflowMediaRecord.id)}`
        : `import-${node.id}`,
      title: String(
        workflowMediaRecord?.title ??
          workflowMediaRecord?.assetName ??
          node.data.assetName ??
          node.data.title ??
          "导入原图"
      ),
      createdAt: String(workflowMediaRecord?.createdAt ?? ""),
      source: "external_media_imported",
      summary: String(workflowMediaRecord?.note ?? node.data.summary ?? ""),
      media: recordMedia,
      payload: {
        versionSource: "workflow_media",
        workflowMediaId: workflowMediaRecord?.id,
      },
    })
  }

  versions.forEach((version) => {
    const media = storyboardVersionCanvasMedia(version)
    const rawVersion = version as Record<string, unknown>
    addVersion({
      id: version.id,
      title: version.title,
      createdAt: version.createdAt,
      status: version.status,
      summary: version.summary,
      source: version.source,
      preview: version.preview,
      media,
      payload: version.payload,
      model: version.model,
      provider: version.provider,
      generationError: version.generationError,
      generationDebug: rawVersion.generationDebug,
      active: storyboardVersionIsActive(version),
    })
  })

  const currentMedia = canvasMediaReference(
    node.data.media ?? node.data.storage ?? null
  )
  if (currentMedia) {
    addVersion({
      id:
        workflowNodeDataCurrentVersionId(node.data) ||
        currentMedia.id ||
        `current-${node.id}`,
      title: `${node.data.title || node.data.assetName || "当前图片"} 当前版本`,
      source: "canvas_node_current",
      summary: node.data.summary,
      media: currentMedia,
      payload: {
        versionSource: "canvas_node_current",
        sourceNodeId: node.id,
      },
    })
  }

  return rows
}

function canvasAssetActiveMediaVersionId(
  data: WorkflowNodeData,
  media: MediaAsset | null,
  mediaVersions: Array<Record<string, unknown>>
) {
  const currentVersionId = workflowNodeDataCurrentVersionId(data)
  if (currentVersionId) return currentVersionId

  const activeVersionId = String(
    mediaVersions.find((version) =>
      storyboardVersionIsActive(version as StoryboardVersion)
    )?.id ?? ""
  ).trim()
  if (activeVersionId) return activeVersionId

  const currentMediaKey = canvasAssetMediaKey(media)
  if (currentMediaKey) {
    const matchingVersionId = String(
      mediaVersions.find((version) => {
        const versionMedia = canvasMediaReference(
          (version.media as MediaAsset | undefined) ?? null
        )
        return (
          versionMedia && canvasAssetMediaKey(versionMedia) === currentMediaKey
        )
      })?.id ?? ""
    ).trim()
    if (matchingVersionId) return matchingVersionId
  }

  return mediaVersions.length === 1
    ? String(mediaVersions[0]?.id ?? "").trim()
    : ""
}

function canvasAssetPayloadFromNode(
  node: StoryboardNodeLike,
  versions: StoryboardVersion[] = [],
  workflowMediaRecord?: WorkflowMediaRecord | null
) {
  const data = node.data
  const name = canvasAssetNodeLibraryName(node)
  const designPrompt = canvasAssetPromptForLibrary(node)
  const prompts = {
    ...recordValue(data.prompts),
    ...(designPrompt ? { assetImagePrompt: designPrompt } : {}),
  }
  const media = canvasMediaReference(data.media ?? data.storage ?? null)
  const mediaVersions = canvasAssetVersionPayloadsFromNode(
    node,
    versions,
    workflowMediaRecord
  )
  const activeMediaVersionId = canvasAssetActiveMediaVersionId(
    data,
    media,
    mediaVersions
  )
  return {
    name,
    desc: designPrompt || data.summary || "",
    prompts,
    ...(mediaPreviewSrc(media) ? { media } : {}),
    ...(mediaVersions.length
      ? {
          mediaVersions,
          ...(activeMediaVersionId
            ? {
                activeMediaVersionId,
                activeVersionId: activeMediaVersionId,
                mediaVersionId: activeMediaVersionId,
                sourceVersionId: activeMediaVersionId,
              }
            : {}),
        }
      : {}),
    ...(data.voiceStyle ? { voiceStyle: data.voiceStyle } : {}),
  }
}

function canvasProjectAssetTypeLabel(assetType: CanvasProjectAssetType) {
  if (assetType === "characters") return "角色"
  if (assetType === "creatures") return "生物"
  if (assetType === "scenes") return "场景"
  return "道具"
}

export type { CanvasProjectAssetType }
export { mediaPurposeTargetSlot, mediaPurposeMaterialSlot, mediaPurposeAssetType, mediaPurposeProjectAssetType, canvasAssetNameKey, canvasProjectAssetNameExists, canvasProjectAssetTypeFromValue, canvasProjectAssetTypeFromData, canvasProjectAssetTypeFromNode, canvasProjectAssetAspectRatio, canvasProjectAssetResolutionKeys, canvasAssetNodeLibraryName, canvasAssetNodeProjectAssetIdentity, canvasRootAssetFields, canvasAssetNodeRootFields, canvasAssetNodeInProjectLibrary, assetRangeBindingValueExists, sourceRefRangeBindingValueExists, assetItemHasSplitRangeBinding, canvasAssetNodeReferencesSplitAsset, detachCanvasProjectAssetReference, canvasAssetPromptForLibrary, canvasAssetMediaKey, canvasWorkflowMediaRecordForNode, canvasAssetVersionPayloadsFromNode, canvasAssetActiveMediaVersionId, canvasAssetPayloadFromNode, canvasProjectAssetTypeLabel }
