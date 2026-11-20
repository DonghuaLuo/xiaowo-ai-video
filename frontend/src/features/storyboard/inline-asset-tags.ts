import { isWorkflowVideoTaskType } from "./workflow-video-task-types"
import type { MediaAsset } from "@/backend"
import { isFrameImage } from "./frame-reference-menu"
import { mediaPreviewSrc, mediaThumbnailSrc } from "@/shared/media"

type InlineAssetData = {
  eyebrow?: string | null
  assetRefs?: unknown
  inputLinks?: Array<Record<string, unknown>>
  referenceDisplayRows?: Array<Record<string, unknown>>
  referenceThumbnails?: Array<Record<string, unknown>>
  assetThumbnails?: Array<Record<string, unknown>>
  referenceVideoThumbnails?: Array<Record<string, unknown>>
  referenceManifest?: Array<Record<string, unknown>>
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function canvasMediaReference(media?: MediaAsset | null): MediaAsset | null {
  if (!media || typeof media !== "object") return null
  const isInlineMediaSource = (value?: string | null) =>
    value?.trim().toLowerCase().startsWith("data:") ?? false
  const preview =
    media.preview && !isInlineMediaSource(media.preview)
      ? media.preview
      : undefined
  const url =
    media.url && !isInlineMediaSource(media.url) ? media.url : undefined
  return {
    id: media.id,
    assetType: media.assetType,
    frameOrigin: media.frameOrigin,
    kind: media.kind,
    originalName: media.originalName,
    mimeType: media.mimeType,
    width: media.width,
    height: media.height,
    aspectRatio: media.aspectRatio,
    duration: media.duration,
    size: media.size,
    format: media.format,
    fps: media.fps,
    path: media.path,
    filePath: media.filePath,
    file: media.file,
    pngFile: media.pngFile,
    relativePath: media.relativePath,
    relative_path: media.relative_path,
    thumbnail: media.thumbnail,
    thumbnailPath: media.thumbnailPath,
    thumbnailFile: media.thumbnailFile,
    thumbnailRelativePath: media.thumbnailRelativePath,
    url,
    preview,
  }
}

function workflowNodeDataIsVisualHandoffAsset(data?: Record<string, unknown> | null) {
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

function canonicalTargetSlot(handle?: string | null) {
  const value = String(handle ?? "")
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[\s-]+/g, "_")
    .toLowerCase()
  if (!value) return "storyboard_image"
  if (value.includes("video_input") || value === "reference_video" || value === "video_reference") {
    return "reference_video"
  }
  if (value.includes("asset_input")) return "storyboard_image"
  if (value === "character") return "character_reference"
  if (value === "creature") return "creature_reference"
  if (value === "scene") return "scene_reference"
  if (value === "prop") return "prop_reference"
  if (value === "visual_handoff" || value === "visual_handoff_reference" || value === "handoff" || value === "continuity") {
    return "visual_handoff_reference"
  }
  if (value === "visual" || value === "visual_reference" || value === "asset" || value === "reference") {
    return "storyboard_image"
  }
  if (value === "image") return "storyboard_image"
  if (value === "frame_image") return "frame_reference"
  return value
}

function isWorkflowAssetInputHandle(handle?: string | null) {
  const value = String(handle ?? "").trim().toLowerCase()
  return value === "asset_input" || value.includes("asset_input_") || value.endsWith("_asset_input")
}

export type InlineAssetTagKind =
  | "custom_image"
  | "video"
  | "frame"
  | "handoff"
  | "storyboard"
  | "character"
  | "creature"
  | "scene"
  | "prop"

export type InlineAssetTag = {
  enabled?: boolean
  mediaIdentity?: string
  frameRole?: "first_frame" | "last_frame"
  useNativeFrame?: boolean
  key: string
  kind: InlineAssetTagKind
  label: string
  assetId?: string
  assetType?: string
  sourceNodeId?: string
  sourceVersionId?: string
  referenceIdentity?: string
  referenceLabel?: string
  aliases?: string[]
  media?: MediaAsset | null
  previewSrc?: string
}
function inlineInputLinkLabel(link: Record<string, unknown>, _index: number) {
  return String(
    link.label ??
      link.displayName ??
      link.display_name ??
      link.assetName ??
      link.asset_name ??
      link.name ??
      link.title ??
      link.sourceTitle ??
      ""
  ).trim()
}

function inlineAssetTagIdentity(tag: InlineAssetTag) {
  return tag.assetId?.trim() || tag.sourceNodeId?.trim() || ""
}

function inlineAssetTagReferenceIdentity(tag: InlineAssetTag) {
  // Reference images are distinct even when they depict the same semantic asset.
  return tag.sourceNodeId?.trim() || tag.media?.id?.trim()
    || tag.sourceVersionId?.trim() || tag.assetId?.trim() || ""
}

export function inlineAssetTagReferenceMatches(tag: InlineAssetTag, reference: Record<string, unknown>) {
  const identity = String(reference.sourceNodeId || reference.identity || "").trim()
  return Boolean(identity) && identity === inlineAssetTagReferenceIdentity(tag)
}

function inlineAssetTagKindFromAssetType(
  value?: string | null
): InlineAssetTagKind | null {
  const normalized = String(value ?? "")
    .trim()
    .toLowerCase()
  if (normalized === "custom_image") return "custom_image"
  if (
    normalized === "storyboard" ||
    normalized === "storyboard_image" ||
    normalized === "visual_reference"
  )
    return "storyboard"
  if (
    normalized === "visual_handoff" ||
    normalized === "visual_handoff_reference" ||
    normalized === "handoff" ||
    normalized === "continuity"
  )
    return "handoff"
  if (normalized === "characters" || normalized === "character")
    return "character"
  if (
    normalized === "creatures" ||
    normalized === "creature" ||
    normalized === "monster" ||
    normalized === "beast"
  )
    return "creature"
  if (normalized === "scenes" || normalized === "scene") return "scene"
  if (normalized === "props" || normalized === "prop") return "prop"
  return null
}

function inlineAssetTagKindFromSlot(
  value?: string | null
): InlineAssetTagKind | null {
  const valueText = String(value ?? "").trim()
  if (!valueText || isWorkflowAssetInputHandle(valueText)) return null
  const slot = canonicalTargetSlot(valueText)
  if (slot === "custom_image") return "custom_image"
  if (slot === "reference_video") return "video"
  if (slot === "frame_reference") return "frame"
  if (slot === "visual_handoff_reference") return "handoff"
  if (slot === "storyboard_image") return "storyboard"
  if (slot === "character_reference") return "character"
  if (slot === "creature_reference") return "creature"
  if (slot === "scene_reference") return "scene"
  if (slot === "prop_reference") return "prop"
  return null
}

function inlineAssetTagKindFromRefKey(key: string): InlineAssetTagKind | null {
  if (
    key === "visual_handoff" ||
    key === "visual_handoff_reference" ||
    key === "handoff" ||
    key === "continuity"
  )
    return "handoff"
  if (key === "storyboard" || key === "storyboard_image") return "storyboard"
  if (key === "characters" || key === "character") return "character"
  if (
    key === "creatures" ||
    key === "creature" ||
    key === "monsters" ||
    key === "monster" ||
    key === "beasts" ||
    key === "beast"
  )
    return "creature"
  if (key === "scenes" || key === "scene") return "scene"
  if (key === "props" || key === "prop") return "prop"
  return null
}

function inlineAssetTagKindFromLink(link: Record<string, unknown>) {
  if (isFrameImage(link)) return "frame"
  if (workflowNodeDataIsVisualHandoffAsset(link)) return "handoff"
  const assetType = String(
    link.rootAssetType ?? link.assetType ?? link.type ?? link.assetKind ?? ""
  ).trim()
  const slot = String(
    link.slot ?? link.targetSlot ?? link.target_slot ?? ""
  ).trim()
  const slotKind = inlineAssetTagKindFromSlot(slot)
  if (slotKind) return slotKind
  const sourceType = String(link.sourceType ?? link.source_type ?? "").trim()
  if (
    sourceType &&
    !["asset", "asset.image", "asset_image"].includes(sourceType)
  ) {
    return null
  }
  return inlineAssetTagKindFromAssetType(assetType)
}

function inlineAssetTagItems(value: unknown): unknown[] {
  if (!value) return []
  if (Array.isArray(value)) return value
  if (typeof value === "string" && value.trim()) return [value.trim()]
  if (typeof value === "object") return [value]
  return []
}

function inlineAssetTagLabel(value: unknown, fallback: string) {
  if (typeof value === "string" && value.trim()) return value.trim()
  const record = recordValue(value)
  const direct =
    record.name ??
    record.title ??
    record.displayName ??
    record.display_name ??
    record.label ??
    record.assetName ??
    record.asset_name ??
    record.sourceTitle
  return typeof direct === "string" && direct.trim() ? direct.trim() : fallback
}

function inlineAssetTagAssetId(value: unknown) {
  const record = recordValue(value)
  return String(record.rootAssetId ?? record.assetId ?? record.id ?? "").trim()
}

function inlineAssetTagAliases(value: unknown) {
  const record = recordValue(value)
  const aliases = record.aliases
  return Array.isArray(aliases)
    ? aliases.map((item) => String(item ?? "").trim()).filter(Boolean)
    : []
}

function inlineAssetTagMedia(value: unknown): MediaAsset | null {
  const record = recordValue(value)
  const media = record.media
  if (media && typeof media === "object" && !Array.isArray(media)) {
    const reference = canvasMediaReference(media as MediaAsset)
    if (mediaPreviewSrc(reference)) return reference
  }
  const preview = String(
    record.previewSrc ??
      record.preview_src ??
      record.preview ??
      record.previewUrl ??
      record.preview_url ??
      record.thumbnail ??
      record.thumbnailUrl ??
      record.thumbnail_url ??
      record.url ??
      record.path ??
      record.file ??
      record.filePath ??
      record.relativePath ??
      record.relative_path ??
      ""
  ).trim()
  if (!preview) return null
  return {
    id:
      String(record.mediaId ?? record.media_id ?? record.id ?? "").trim() ||
      undefined,
    preview,
    path: preview,
    file: preview,
    relativePath: preview,
    relative_path: preview,
  }
}

function inlineAssetTagSearchText(tag: InlineAssetTag) {
  return [tag.label, tag.assetId, tag.assetType, ...(tag.aliases ?? [])]
    .join(" ")
    .toLocaleLowerCase()
}

function inlineAssetTagStyle(kind: InlineAssetTagKind) {
  if (kind === "custom_image") {
    return "border-transparent bg-zinc-500/10 text-zinc-700 dark:text-zinc-300"
  }
  if (kind === "handoff") {
    return "border-transparent bg-[#ECFDF5] text-[#047857] dark:bg-[#10B981]/18 dark:text-[#D1FAE5]"
  }
  if (kind === "storyboard") {
    return "border-transparent bg-[#EFF6FF] text-[#1D4ED8] dark:bg-[#3B82F6]/18 dark:text-[#DBEAFE]"
  }
  if (kind === "character") {
    return "border-transparent bg-[#EEF2FF] text-[#3730A3] dark:bg-[#4F46E5]/18 dark:text-[#E0E7FF]"
  }
  if (kind === "creature") {
    return "border-transparent bg-[#FDF2F8] text-[#BE185D] dark:bg-[#EC4899]/16 dark:text-[#FCE7F3]"
  }
  if (kind === "scene") {
    return "border-transparent bg-[#ECFDF5] text-[#047857] dark:bg-[#10B981]/16 dark:text-[#D1FAE5]"
  }
  return "border-transparent bg-[#FFF7ED] text-[#C2410C] dark:bg-[#F97316]/16 dark:text-[#FFEDD5]"
}

function inlineAssetTagPrefix(kind: InlineAssetTagKind) {
  if (kind === "custom_image") return "自定义图片"
  if (kind === "video") return "参考视频"
  if (kind === "frame") return "帧画面"
  if (kind === "handoff") return "视觉交接图"
  if (kind === "storyboard") return "分镜图"
  if (kind === "character") return "角色"
  if (kind === "creature") return "生物"
  if (kind === "scene") return "场景"
  return "道具"
}

const INLINE_ASSET_TAG_KIND_ORDER: Record<InlineAssetTagKind, number> = {
  custom_image: 6,
  video: 6,
  frame: -1,
  handoff: 0,
  storyboard: 1,
  character: 2,
  creature: 3,
  scene: 4,
  prop: 5,
}

function isDisplayableInlineAssetTag(tag: InlineAssetTag) {
  return Boolean(tag.label.trim())
}

function collectInlineAssetTags(
  inputLinks: Array<Record<string, unknown>>,
  refs: Record<string, unknown>
) {
  const tags: InlineAssetTag[] = []

  inputLinks.forEach((link, index) => {
    const kind = inlineAssetTagKindFromLink(link)
    if (!kind) return
    const label = inlineInputLinkLabel(link, index)
    const linkId = String(link.id ?? "").trim()
    const assetId = String(link.rootAssetId ?? link.assetId ?? "").trim()
    const sourceNodeId = String(
      link.sourceNodeId ?? link.source_node_id ?? ""
    ).trim()
    const sourceVersionId = String(
      link.sourceVersionId ??
        link.source_version_id ??
        link.mediaVersionId ??
        link.media_version_id ??
        link.versionId ??
        link.version_id ??
        ""
    ).trim()
    const assetType = String(
      link.rootAssetType ?? link.assetType ?? link.type ?? link.assetKind ?? ""
    ).trim()
    const referenceLabel = String(link.referenceLabel ?? "").trim()
    const media = inlineAssetTagMedia(link)
    // Resolve identity before preview URLs are normalized. Different source
    // cards for the same reference must not duplicate thumbnails or mentions.
    const sourceMedia = recordValue(link.media)
    const storage = recordValue(link.storage)
    const version = String(link.mediaVersionId || link.sourceVersionId || link.assetVersionId || sourceMedia.versionId || "")
    const mediaId = String(link.mediaId || sourceMedia.id || storage.id || "")
    const path = String(link.path || link.relativePath || link.url || sourceMedia.path || sourceMedia.url || storage.path || "")
    const mediaIdentity = mediaId ? `media:${mediaId}:${version}`
      : path ? `path:${path}`
      : assetId ? `asset:${link.rootAssetProjectId || ""}:${assetId}:${version}`
      : sourceNodeId ? `node:${sourceNodeId}:${version}` : undefined
    const normalizedType = ({ character: "characters", creature: "creatures", scene: "scenes", prop: "props" } as Record<string, string>)[assetType] || assetType
    const referenceIdentity = String(link.referenceIdentity || JSON.stringify([
      assetId ? [String(link.rootAssetProjectId || ""), normalizedType, assetId] : [],
      `${mediaIdentity || ""}${kind === "frame" ? `:frame:${link.frameRole === "last_frame" ? "last_frame" : "first_frame"}` : ""}`,
    ]))
    tags.push({
      key: `link:${linkId || index}:${kind}:${label}`,
      mediaIdentity,
      referenceIdentity,
      frameRole: link.frameRole === "last_frame" ? "last_frame" : "first_frame",
      useNativeFrame: link.useNativeFrame !== false,
      enabled: link.enabled !== false,
      kind,
      label,
      assetId,
      assetType,
      sourceNodeId,
      sourceVersionId,
      referenceLabel: referenceLabel || undefined,
      aliases: inlineAssetTagAliases(link),
      media,
      previewSrc: mediaThumbnailSrc(media) ?? undefined,
    })
  })
  ;[
    "characters",
    "character",
    "creatures",
    "creature",
    "scenes",
    "scene",
    "props",
    "prop",
  ].forEach((key) => {
    const kind = inlineAssetTagKindFromRefKey(key)
    if (!kind) return
    inlineAssetTagItems(refs[key]).forEach((item, index) => {
      const label = inlineAssetTagLabel(item, "")
      const assetId = inlineAssetTagAssetId(item)
      if (assetId && tags.some((tag) => tag.kind === kind && tag.assetId === assetId)) return
      tags.push({
        key: `ref:${key}:${index}:${kind}:${label}`,
        kind,
        label,
        assetId,
        assetType: key,
        aliases: inlineAssetTagAliases(item),
      })
    })
  })

  const deduped = new Map<string, InlineAssetTag>()
  tags.forEach((tag) => {
    if (!isDisplayableInlineAssetTag(tag)) return
    const identity = tag.referenceIdentity || inlineAssetTagReferenceIdentity(tag)
    const key = identity
      ? `id:${identity}`
      : `${tag.kind}:label:${tag.label.trim().toLocaleLowerCase()}`
    const previous = deduped.get(key)
    if (!previous || (previous.enabled === false && tag.enabled !== false)) deduped.set(key, tag)
  })

  return {
    tags: Array.from(deduped.values()).sort(
      (left, right) =>
        INLINE_ASSET_TAG_KIND_ORDER[left.kind] -
        INLINE_ASSET_TAG_KIND_ORDER[right.kind]
    ),
  }
}

const EMPTY_INLINE_ASSET_REFS: Record<string, unknown> = {}

function usesResolvedInlineAssetRows(data: InlineAssetData) {
  return (
    data.eyebrow === "director.board" ||
    data.eyebrow === "storyboard.card" ||
    isWorkflowVideoTaskType(data.eyebrow)
  )
}

function inlineAssetDisplayRefs(data: InlineAssetData) {
  return usesResolvedInlineAssetRows(data)
    ? EMPTY_INLINE_ASSET_REFS
    : recordValue(data.assetRefs)
}

function inlineAssetDisplayRows(data: InlineAssetData) {
  if (Array.isArray(data.referenceDisplayRows)) return data.referenceDisplayRows
  const rows: Array<Record<string, unknown>> = []
  const referenceThumbnails = Array.isArray(data.referenceThumbnails)
    ? data.referenceThumbnails
    : []
  const assetThumbnails = Array.isArray(data.assetThumbnails)
    ? data.assetThumbnails
    : []
  const usesResolvedThumbnailRows = usesResolvedInlineAssetRows(data)
  // Fast saves return authoritative links without rebuilding thumbnail media.
  // Keep the cached preview, but always read frame settings from the saved link.
  const frameLinks = new Map((data.inputLinks ?? [])
    .filter(isFrameImage)
    .map((link) => [String(link.sourceNodeId ?? ""), link]))
  rows.push(...[...referenceThumbnails, ...assetThumbnails].map((row) => {
    const link = frameLinks.get(String(row.sourceNodeId ?? ""))
    return isFrameImage(row) && link
      ? { ...row, frameRole: link.frameRole, useNativeFrame: link.useNativeFrame }
      : row
  }))
  if (usesResolvedThumbnailRows) return rows
  const hasStoryboardThumbnails = referenceThumbnails.some((row) => {
    const slot = canonicalTargetSlot(
      String(row.slot ?? row.targetSlot ?? row.target_slot ?? "")
    )
    return slot === "storyboard_image"
  })
  const assetThumbnailSlots = new Set(
    assetThumbnails
      .map((row) =>
        String(row.slot ?? row.targetSlot ?? row.target_slot ?? "").trim()
      )
      .filter(Boolean)
  )
  if (Array.isArray(data.inputLinks)) {
    data.inputLinks.forEach((link) => {
      const slot = canonicalTargetSlot(
        String(link.slot ?? link.targetSlot ?? link.target_slot ?? "")
      )
      if (slot === "storyboard_image" && hasStoryboardThumbnails) return
      if (assetThumbnailSlots.has(slot)) return
      rows.push(link)
    })
  }
  return rows
}

function inlineAssetDisplayMentionRows(data: InlineAssetData) {
  const rows = inlineAssetDisplayRows(data).filter((row) => row.enabled !== false)
  const referenceManifest = Array.isArray(data.referenceManifest)
    ? data.referenceManifest
    : []
  const referenceVideoRows = Array.isArray(data.referenceVideoThumbnails)
    ? data.referenceVideoThumbnails
    : []
  const videoRows = referenceVideoRows.flatMap((row) => {
    if (row.enabled === false) return []
    const identities = [
      row.sourceNodeId,
      row.source_node_id,
      row.assetId,
      row.asset_id,
      row.mediaId,
      row.media_id,
      recordValue(row.media).id,
    ]
      .map((value) => String(value ?? "").trim())
      .filter(Boolean)
    const reference = referenceManifest.find((item) => {
      if (String(item.kind ?? item.referenceType ?? "").trim() !== "video") {
        return false
      }
      const identity = String(
        item.identity ?? item.sourceNodeId ?? item.mediaId ?? ""
      ).trim()
      return identity && identities.includes(identity)
    })
    const referenceLabel = String(reference?.referenceLabel ?? "").trim()
    return referenceLabel
      ? [{ ...row, label: referenceLabel, displayName: referenceLabel, referenceLabel }]
      : []
  })
  return [...rows, ...videoRows]
}


export { inlineInputLinkLabel, inlineAssetTagIdentity, inlineAssetTagReferenceIdentity, inlineAssetTagKindFromAssetType, inlineAssetTagKindFromSlot, inlineAssetTagKindFromRefKey, inlineAssetTagKindFromLink, inlineAssetTagItems, inlineAssetTagLabel, inlineAssetTagAssetId, inlineAssetTagAliases, inlineAssetTagMedia, inlineAssetTagSearchText, inlineAssetTagStyle, inlineAssetTagPrefix, isDisplayableInlineAssetTag, collectInlineAssetTags, inlineAssetDisplayRefs, inlineAssetDisplayRows, inlineAssetDisplayMentionRows }
