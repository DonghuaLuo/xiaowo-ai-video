import type {
  StyleFilePayload,
  StyleTemplateOption,
} from "@/features/styles/types"
import { filenameFromPath, inferImageMimeFromPath } from "@/shared/media"

export function styleFilePayloadFromStyleTemplate(
  template?: StyleTemplateOption | null,
  preview?: string | null
): StyleFilePayload | null {
  if (!template) return null

  const path =
    template.filePath ??
    template.file_path ??
    template.thumbnailPath ??
    template.thumbnail_path ??
    template.path ??
    undefined
  const relativePath =
    template.relativePath ?? template.relative_path ?? template.file ?? undefined
  const thumbnailFile =
    template.thumbnailFile ?? template.thumbnail_file ?? undefined
  const isFavoriteStyle =
    template.category === "favorite" || template.source === "favorite_style"
  const styleThumbnailFile = isFavoriteStyle ? undefined : thumbnailFile
  const hasImageSource = Boolean(
    path ||
      relativePath ||
      thumbnailFile ||
      (template.thumbnailUrl && template.thumbnailUrl.startsWith("data:image/"))
  )

  if (!hasImageSource) return null

  const sourceName =
    path ??
    relativePath ??
    thumbnailFile ??
    template.thumbnailUrl ??
    template.name ??
    template.id
  const name =
    filenameFromPath(sourceName) ??
    `${template.id || "style-reference"}.png`

  return {
    id: template.id,
    name,
    originalName: name,
    mimeType: inferImageMimeFromPath(sourceName),
    source: isFavoriteStyle ? "favorite_style" : "visual_style",
    path,
    filePath: path,
    file_path: path,
    relativePath,
    relative_path: relativePath,
    file: template.file ?? relativePath,
    thumbnailFile,
    thumbnail_file: thumbnailFile,
    thumbnailPath: template.thumbnailPath ?? undefined,
    thumbnail_path: template.thumbnail_path ?? undefined,
    styleThumbnailFile,
    style_thumbnail_file: styleThumbnailFile,
    preview: preview ?? template.thumbnailUrl ?? undefined,
    dataUrl: template.thumbnailUrl?.startsWith("data:image/")
      ? template.thumbnailUrl
      : undefined,
  }
}
