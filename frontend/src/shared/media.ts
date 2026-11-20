import { PluginSDK } from "xiaowo-sdk"

import type { InputImageFile, MediaAsset } from "@/backend"

interface ImagePayloadLike {
  path?: string | null
  filePath?: string | null
  preview?: string | null
  dataUrl?: string | null
}

type ImageMediaMetadata = Pick<MediaAsset, "width" | "height" | "aspectRatio">

export function createLocalId(prefix: string) {
  const id =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}-${id}`
}

export function mediaAssetFromImageFile(file: InputImageFile): MediaAsset {
  const localPath = file.filePath ?? file.file_path ?? file.path
  const mimeType =
    file.mimeType ||
    (isVideoPath(localPath ?? file.name)
      ? inferVideoMimeFromPath(localPath ?? file.name)
      : isAudioPath(localPath ?? file.name)
        ? inferAudioMimeFromPath(localPath ?? file.name)
        : inferImageMimeFromPath(localPath ?? file.name))
  const kind = file.kind ?? (
    mimeType.startsWith("video/") ? "video" : mimeType.startsWith("audio/") ? "audio" : "image"
  )
  return {
    id: file.id ?? createLocalId("media"),
    kind,
    originalName: file.name,
    mimeType,
    dataUrl: file.dataUrl,
    path: localPath,
    filePath: localPath,
    relativePath: file.relativePath,
    relative_path: file.relative_path,
    file: file.file,
    preview:
      file.preview ??
      file.dataUrl ??
      (localPath ? PluginSDK.convertFileSrc(localPath) : undefined),
  }
}

export function aspectRatioFromSize(width?: number, height?: number) {
  const normalizedWidth = Math.trunc(Number(width))
  const normalizedHeight = Math.trunc(Number(height))
  if (
    !Number.isFinite(normalizedWidth) ||
    !Number.isFinite(normalizedHeight) ||
    normalizedWidth <= 0 ||
    normalizedHeight <= 0
  ) {
    return undefined
  }
  const divisor = greatestCommonDivisor(normalizedWidth, normalizedHeight)
  return `${normalizedWidth / divisor}:${normalizedHeight / divisor}`
}

export async function readImageMediaMetadata(
  src?: string | null
): Promise<ImageMediaMetadata> {
  if (!src || typeof Image === "undefined") return {}
  return new Promise((resolve) => {
    const image = new Image()
    let settled = false
    let timeout: ReturnType<typeof globalThis.setTimeout> | undefined
    const finish = (metadata: ImageMediaMetadata) => {
      if (settled) return
      settled = true
      if (timeout !== undefined) globalThis.clearTimeout(timeout)
      image.onload = null
      image.onerror = null
      resolve(metadata)
    }
    timeout = globalThis.setTimeout(() => finish({}), 2500)
    image.onload = () => {
      const width = image.naturalWidth || image.width
      const height = image.naturalHeight || image.height
      finish({
        width,
        height,
        aspectRatio: aspectRatioFromSize(width, height),
      })
    }
    image.onerror = () => finish({})
    image.src = src
  })
}

export function imagePayloadPreviewSrc(file?: ImagePayloadLike | null) {
  if (!file) return null
  const localPath = file.filePath ?? file.path
  if (localPath && isAbsoluteLocalPath(localPath)) {
    return file.preview ?? PluginSDK.convertFileSrc(localPath)
  }
  return file.preview ?? file.dataUrl ?? null
}

export function inferImageMimeFromPath(path?: string | null) {
  const ext = extensionFromName(path)
  if (ext === "jpg" || ext === "jpeg") return "image/jpeg"
  if (ext === "webp") return "image/webp"
  return "image/png"
}

export function inferVideoMimeFromPath(path?: string | null) {
  const ext = extensionFromName(path)
  if (ext === "webm") return "video/webm"
  if (ext === "mov") return "video/quicktime"
  if (ext === "mkv") return "video/x-matroska"
  if (ext === "avi") return "video/x-msvideo"
  if (ext === "m4v") return "video/x-m4v"
  return "video/mp4"
}

export function inferAudioMimeFromPath(path?: string | null) {
  const ext = extensionFromName(path)
  if (ext === "mp3") return "audio/mpeg"
  if (ext === "m4a") return "audio/mp4"
  if (ext === "aac") return "audio/aac"
  if (ext === "ogg" || ext === "oga") return "audio/ogg"
  if (ext === "flac") return "audio/flac"
  if (ext === "wma") return "audio/x-ms-wma"
  return "audio/wav"
}

export function isAudioPath(path?: string | null) {
  const ext = extensionFromName(path)
  return ["wav", "mp3", "m4a", "aac", "ogg", "oga", "flac", "wma"].includes(ext ?? "")
}

export function isVideoPath(path?: string | null) {
  const ext = extensionFromName(path)
  return ["mp4", "webm", "mov", "mkv", "avi", "m4v"].includes(ext ?? "")
}

export function mediaPreviewSrc(
  media?: MediaAsset | null,
  fallback?: string | null
) {
  const localSrc = localMediaFileSrc(media)
  if (localSrc) return localSrc
  return (
    media?.url ??
    media?.outputPngDataUrl ??
    media?.pngDataUrl ??
    media?.preview ??
    media?.dataUrl ??
    fallback ??
    null
  )
}

export function mediaThumbnailSrc(
  media?: MediaAsset | null,
  fallback?: string | null
) {
  if (!media) return fallback ?? null
  const thumbnailPath =
    media.thumbnailPath ??
    (media as MediaAsset & { thumbnail_path?: string }).thumbnail_path
  if (thumbnailPath && isAbsoluteLocalPath(thumbnailPath)) {
    try {
      return PluginSDK.convertFileSrc(thumbnailPath.trim())
    } catch {
      // Fall through to an inline or remote thumbnail.
    }
  }
  const thumbnail =
    media.thumbnail ??
    (media as MediaAsset & { thumbnailUrl?: string; thumbnail_url?: string }).thumbnailUrl ??
    (media as MediaAsset & { thumbnailUrl?: string; thumbnail_url?: string }).thumbnail_url
  if (thumbnail && /^(data:|https?:|blob:)/i.test(thumbnail)) {
    return thumbnail.trim()
  }
  const kind = String(media.kind ?? media.mimeType ?? "").toLowerCase()
  return kind === "video" || kind.startsWith("video/")
    ? fallback ?? null
    : mediaPreviewSrc(media, fallback)
}

export function isAbsoluteLocalPath(value?: string | null) {
  const path = value?.trim()
  if (!path) return false
  return (
    /^[A-Za-z]:[\\/]/.test(path) ||
    path.startsWith("\\\\") ||
    path.startsWith("/")
  )
}

export function localMediaFileSrc(media?: MediaAsset | null) {
  const localPath = media?.filePath ?? media?.path
  if (!isAbsoluteLocalPath(localPath)) return null
  try {
    return PluginSDK.convertFileSrc(localPath!.trim())
  } catch {
    return null
  }
}

export function extensionFromName(name?: string | null) {
  const clean = (name ?? "").split(/[?#]/)[0] ?? ""
  const match = clean.match(/\.([a-z0-9]+)$/i)
  return match ? match[1].toLowerCase() : null
}

export function filenameFromPath(path?: string | null) {
  const clean = (path ?? "").split(/[?#]/)[0] ?? ""
  const last = clean.split(/[\\/]/).filter(Boolean).pop()
  if (!last) return null
  try {
    return decodeURIComponent(last)
  } catch {
    return last
  }
}

function greatestCommonDivisor(left: number, right: number): number {
  let a = Math.abs(left)
  let b = Math.abs(right)
  while (b) {
    const next = a % b
    a = b
    b = next
  }
  return a || 1
}
