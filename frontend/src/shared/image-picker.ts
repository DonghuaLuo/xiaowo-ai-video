import { PluginSDK } from "xiaowo-sdk"

import type { InputImageFile } from "@/backend"
import {
  extensionFromName,
  filenameFromPath,
  inferImageMimeFromPath,
  inferAudioMimeFromPath,
  inferVideoMimeFromPath,
  isAbsoluteLocalPath,
  isAudioPath,
  isVideoPath,
} from "@/shared/media"

const IMAGE_FILE_FILTERS = [
  { name: "Images", extensions: ["png", "jpg", "jpeg", "webp"] },
]
const VIDEO_FILE_FILTERS = [
  { name: "Videos", extensions: ["mp4", "webm", "mov", "mkv", "avi", "m4v"] },
]
const AUDIO_FILE_FILTERS = [
  { name: "Audio", extensions: ["wav", "mp3", "m4a", "aac", "ogg", "oga", "flac", "wma"] },
]
const AUDIO_OR_VIDEO_FILE_FILTERS = [...AUDIO_FILE_FILTERS, ...VIDEO_FILE_FILTERS]
const MEDIA_FILE_FILTERS = [...IMAGE_FILE_FILTERS, ...VIDEO_FILE_FILTERS]

export function isImageLocalPath(path?: string | null) {
  const ext = extensionFromName(path)
  return ext === "png" || ext === "jpg" || ext === "jpeg" || ext === "webp"
}

export function isVideoLocalPath(path?: string | null) {
  return isVideoPath(path)
}

export function localMediaFileFromPath(path: string): InputImageFile {
  const cleanPath = path.trim()
  const video = isVideoLocalPath(cleanPath)
  const audio = isAudioPath(cleanPath)
  const name = filenameFromPath(cleanPath) ?? (video ? "video" : audio ? "audio" : "image")
  return {
    name,
    kind: video ? "video" : audio ? "audio" : "image",
    mimeType: video
      ? inferVideoMimeFromPath(cleanPath)
      : audio
        ? inferAudioMimeFromPath(cleanPath)
        : inferImageMimeFromPath(cleanPath),
    path: cleanPath,
    filePath: cleanPath,
    preview: PluginSDK.convertFileSrc(cleanPath),
  }
}

export function localImageFileFromPath(path: string): InputImageFile {
  return localMediaFileFromPath(path)
}

export function localImageFileFromFile(file: File): InputImageFile | null {
  const sourcePath = String(
    (file as File & { path?: string; filePath?: string }).path ??
      (file as File & { path?: string; filePath?: string }).filePath ??
      ""
  ).trim()
  if (!isAbsoluteLocalPath(sourcePath) || !isImageLocalPath(sourcePath)) {
    return null
  }
  return {
    ...localImageFileFromPath(sourcePath),
    name: file.name || filenameFromPath(sourcePath) || "image",
    mimeType: file.type || inferImageMimeFromPath(sourcePath),
  }
}

export async function pickLocalImageFiles(
  options: {
    title?: string
    multiple?: boolean
  } = {}
): Promise<InputImageFile[]> {
  const selected = await PluginSDK.dialog.open({
    title: options.title,
    multiple: Boolean(options.multiple),
    directory: false,
    filters: IMAGE_FILE_FILTERS,
  })
  const paths = Array.isArray(selected) ? selected : selected ? [selected] : []
  return paths
    .filter((path) => isAbsoluteLocalPath(path) && isImageLocalPath(path))
    .map(localImageFileFromPath)
}

export async function pickLocalImageFile(
  title?: string
): Promise<InputImageFile | null> {
  const files = await pickLocalImageFiles({ title, multiple: false })
  return files[0] ?? null
}

export async function pickLocalMediaFiles(
  options: {
    title?: string
    multiple?: boolean
    kind?: "image" | "video" | "audio" | "media"
  } = {}
): Promise<InputImageFile[]> {
  const kind = options.kind ?? "media"
  const selected = await PluginSDK.dialog.open({
    title: options.title,
    multiple: Boolean(options.multiple),
    directory: false,
    filters:
      kind === "image"
        ? IMAGE_FILE_FILTERS
        : kind === "video"
          ? VIDEO_FILE_FILTERS
          : kind === "audio"
            ? AUDIO_OR_VIDEO_FILE_FILTERS
          : MEDIA_FILE_FILTERS,
  })
  const paths = Array.isArray(selected) ? selected : selected ? [selected] : []
  return paths
    .filter(
      (path) =>
        isAbsoluteLocalPath(path) &&
        (kind === "video"
          ? isVideoLocalPath(path)
          : kind === "audio"
            ? isAudioPath(path) || isVideoLocalPath(path)
          : kind === "image"
            ? isImageLocalPath(path)
            : isImageLocalPath(path) || isVideoLocalPath(path))
    )
    .map(localMediaFileFromPath)
}

export async function pickLocalMediaFile(
  title?: string,
  kind: "image" | "video" | "audio" | "media" = "media"
): Promise<InputImageFile | null> {
  const files = await pickLocalMediaFiles({ title, multiple: false, kind })
  return files[0] ?? null
}
