import {
  type InputImageFile,
  type MediaAsset,
  type VideoClipMediaResult,
  type VideoClipResultItem,
} from "@/backend"
import { mediaPreviewSrc } from "@/shared/media"
import { resolveProjectMediaUrl } from "@/utils/style-thumbnails"

export type VideoClipDialogSource = {
  nodeId: string
  title: string
  media: MediaAsset
  src: string
  position: { x: number; y: number }
}

export type VideoClipCropBox = {
  x: number
  y: number
  width: number
  height: number
}

export type VideoClipEditingSource = {
  id: string
  title: string
  media: MediaAsset
  src: string
  resultId?: string
}

export type VideoClipCanvasResult = {
  id: string
  kind: "image" | "video"
  title: string
  media: MediaAsset
  src: string
  start?: number
  end?: number
  duration?: number
  time?: number
  frameIndex?: number
  crop?: VideoClipCropBox
  createdAt?: string
  updatedAt?: string
}

export function formatClipTime(value: number) {
  const totalSeconds = Math.max(0, Number.isFinite(value) ? value : 0)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.floor(totalSeconds % 60)
  const milliseconds = Math.floor((totalSeconds % 1) * 1000)
  return `${minutes}:${String(seconds).padStart(2, "0")}.${String(milliseconds).padStart(3, "0")}`
}

function formatClipFileTime(value: number) {
  const totalMilliseconds = Math.max(
    0,
    Math.round((Number.isFinite(value) ? value : 0) * 1000)
  )
  const milliseconds = totalMilliseconds % 1000
  const totalSeconds = Math.floor(totalMilliseconds / 1000)
  const seconds = totalSeconds % 60
  const totalMinutes = Math.floor(totalSeconds / 60)
  const minutes = totalMinutes % 60
  const hours = Math.floor(totalMinutes / 60)
  const timeBody =
    hours > 0
      ? `${hours}h${String(minutes).padStart(2, "0")}m${String(seconds).padStart(2, "0")}s`
      : `${totalMinutes}m${String(seconds).padStart(2, "0")}s`
  return `${timeBody}${String(milliseconds).padStart(3, "0")}`
}

export function videoClipTimeRangeTitle(
  start: number,
  end: number,
  cropped = false
) {
  return `${formatClipFileTime(start)}-${formatClipFileTime(end)}${cropped ? "-crop" : ""}.mp4`
}

function videoClipFrameTimeTitle(time: number) {
  return `${formatClipFileTime(time)}.png`
}

export function videoClipFrameIndexTitle(frameIndex: number, time: number) {
  return `frame-${String(Math.max(0, Math.floor(frameIndex))).padStart(6, "0")}-${formatClipFileTime(time)}.png`
}

export function clampVideoClipFrameIndex(
  frameIndex: number,
  frameCount: number
) {
  const safeIndex = Math.max(
    0,
    Math.floor(Number.isFinite(frameIndex) ? frameIndex : 0)
  )
  const safeCount = Math.max(
    0,
    Math.floor(Number.isFinite(frameCount) ? frameCount : 0)
  )
  return safeCount > 0 ? Math.min(safeIndex, safeCount - 1) : safeIndex
}

export function videoClipFrameIndexFromTime(
  time: number,
  fps: number,
  frameCount: number,
  duration = 0
) {
  if (fps > 0) {
    return clampVideoClipFrameIndex(
      Math.round(Math.max(0, time) * fps),
      frameCount
    )
  }
  const safeCount = Math.max(
    0,
    Math.floor(Number.isFinite(frameCount) ? frameCount : 0)
  )
  const safeDuration = Math.max(0, Number.isFinite(duration) ? duration : 0)
  if (safeCount > 0 && safeDuration > 0) {
    return clampVideoClipFrameIndex(
      Math.round((Math.max(0, time) / safeDuration) * (safeCount - 1)),
      safeCount
    )
  }
  return 0
}

export function videoClipTimeFromFrameIndex(
  frameIndex: number,
  fps: number,
  duration: number,
  frameCount = 0
) {
  if (fps > 0) {
    return Math.max(0, frameIndex / fps)
  }
  const safeCount = Math.max(
    0,
    Math.floor(Number.isFinite(frameCount) ? frameCount : 0)
  )
  const safeDuration = Math.max(0, Number.isFinite(duration) ? duration : 0)
  if (safeCount > 1 && safeDuration > 0) {
    return Math.max(
      0,
      Math.min(safeDuration, (frameIndex / (safeCount - 1)) * safeDuration)
    )
  }
  return Math.max(0, Math.min(safeDuration, frameIndex))
}

export function clipSecondsToHms(value: number) {
  const secondsValue = Math.max(
    0,
    Math.floor(Number.isFinite(value) ? value : 0)
  )
  return {
    hours: Math.floor(secondsValue / 3600),
    minutes: Math.floor((secondsValue % 3600) / 60),
    seconds: secondsValue % 60,
  }
}

export function clipHmsToSeconds(
  hours: number,
  minutes: number,
  seconds: number
) {
  return Math.max(0, hours * 3600 + minutes * 60 + seconds)
}

export function isFullVideoClipCrop(
  crop: VideoClipCropBox,
  sourceWidth: number,
  sourceHeight: number
) {
  if (!sourceWidth || !sourceHeight || !crop.width || !crop.height) return false
  return (
    crop.x <= 0 &&
    crop.y <= 0 &&
    crop.width >= sourceWidth - 1 &&
    crop.height >= sourceHeight - 1
  )
}

export function cleanVideoClipSourceTitle(value?: string | null) {
  return String(value ?? "")
    .replace(/视频生成/g, "")
    .replace(/^[\s:：·\-—_]+|[\s:：·\-—_]+$/g, "")
    .trim()
}

function videoClipResultDisplayTitle(record: VideoClipResultItem) {
  const start = Number(record.start)
  const end = Number(record.end)
  const time = Number(record.time)
  if (
    record.kind === "video" &&
    Number.isFinite(start) &&
    Number.isFinite(end) &&
    end > start
  ) {
    return videoClipTimeRangeTitle(start, end, Boolean(record.crop))
  }
  if (record.kind === "image" && Number.isFinite(time)) {
    return videoClipFrameTimeTitle(time)
  }
  return String(record.title || record.media.originalName || "剪辑结果")
    .replace(/视频生成/g, "")
    .replace(/^\s*(剪辑|截帧)\s*/g, "")
    .trim()
}

export function videoClipMediaKind(
  media?: MediaAsset | null
): "image" | "video" {
  const mediaKind = String(media?.kind ?? "").toLowerCase()
  const mimeType = String(media?.mimeType ?? "").toLowerCase()
  return mediaKind === "video" || mimeType.startsWith("video/")
    ? "video"
    : "image"
}

export async function videoClipCanvasResultFromRecord(
  projectId: string,
  record: VideoClipResultItem
): Promise<VideoClipCanvasResult | null> {
  if (!record || !record.media) return null
  const kind = record.kind || videoClipMediaKind(record.media)
  const src =
    (await resolveProjectMediaUrl(projectId, record.media)) ||
    mediaPreviewSrc(record.media) ||
    ""
  if (!src) return null
  return {
    id: String(record.id || record.media.id || `clip-result-${Date.now()}`),
    kind,
    title: videoClipResultDisplayTitle({ ...record, kind }),
    media: record.media,
    src,
    start: record.start,
    end: record.end,
    duration: record.duration,
    time: record.time,
    frameIndex: record.frameIndex,
    crop: record.crop,
    createdAt: record.createdAt,
    updatedAt: record.updatedAt,
  }
}

export async function videoClipCanvasResultFromMediaResult(
  projectId: string,
  result: VideoClipMediaResult,
  fallbackTitle: string
): Promise<VideoClipCanvasResult | null> {
  if (result.result) {
    return videoClipCanvasResultFromRecord(projectId, {
      ...result.result,
      title: result.result.title || fallbackTitle,
    })
  }
  const media = result.media
  const kind = videoClipMediaKind(media)
  const src =
    (await resolveProjectMediaUrl(projectId, media)) ||
    mediaPreviewSrc(media) ||
    ""
  if (!src) return null
  return {
    id: String(media.id || `clip-result-${Date.now()}`),
    kind,
    title: fallbackTitle,
    media,
    src,
    start: result.start,
    end: result.end,
    duration: result.duration,
    time: result.time,
    frameIndex: result.frameIndex,
    crop: result.crop,
  }
}

export function mediaAssetInputFile(
  media: MediaAsset,
  title: string,
  kind: "image" | "video",
  preview?: string
): InputImageFile {
  return {
    id: media.id,
    assetType: media.assetType,
    frameOrigin: media.frameOrigin,
    name: title,
    kind,
    mimeType: media.mimeType || (kind === "video" ? "video/mp4" : "image/png"),
    size: media.size,
    path: media.path,
    filePath: media.filePath || media.path,
    file_path: media.filePath || media.path,
    relativePath: media.relativePath,
    relative_path: media.relative_path,
    file: media.file,
    preview: preview || media.preview,
  }
}

export function videoClipResultInputFile(
  result: VideoClipCanvasResult
): InputImageFile {
  return {
    ...mediaAssetInputFile(result.media, result.title, result.kind, result.src),
    id: result.media.id || result.id,
  }
}

export function videoClipRootEditingSource(
  source: VideoClipDialogSource
): VideoClipEditingSource {
  return {
    id: `root:${source.nodeId}`,
    title: source.title,
    media: source.media,
    src: source.src,
  }
}
