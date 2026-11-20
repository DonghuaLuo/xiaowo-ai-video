import { PluginSDK } from "xiaowo-sdk"

const STYLE_THUMBNAIL_RESOURCE_DIR = "backend/public/style-imgs"
const STYLE_THUMBNAIL_DEV_PREFIX = "/style-imgs"
const PROJECT_FILES_RESOURCE_DIR = "backend/data/projects"
const PROJECT_FILES_DEV_PREFIX = "/project-files"
const GLOBAL_FILES_RESOURCE_DIR = "backend/data/global"
const GLOBAL_FILES_DEV_PREFIX = "/global-files"
const IMAGE_FILE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".webp"])
const MEDIA_FILE_EXTENSIONS = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".mp4",
  ".webm",
  ".mov",
])

type TauriBridgeWindow = Window &
  typeof globalThis & {
    __TAURI__?: {
      core?: {
        invoke?: unknown
        convertFileSrc?: unknown
      }
    }
  }

let pluginResourceRoot: string | null | undefined
let pluginResourceRootPromise: Promise<string | null> | null = null
let pluginDirRoot: string | null | undefined
let pluginDirRootPromise: Promise<string | null> | null = null

function hasTauriBridge(): boolean {
  if (typeof window === "undefined") return false
  const tauriWindow = window as TauriBridgeWindow
  return (
    typeof tauriWindow.__TAURI__?.core?.invoke === "function" &&
    typeof tauriWindow.__TAURI__?.core?.convertFileSrc === "function"
  )
}

function normalizeLocalPath(path: string): string {
  return path.replace(/\\/g, "/").replace(/\/+$/, "")
}

function cleanRelativePath(path: string): string | null {
  const normalized = path.replace(/\\/g, "/").replace(/^\/+/, "")
  const parts = normalized.split("/").filter(Boolean)
  if (parts.some((part) => part === "." || part === "..")) return null
  return parts.join("/")
}

function joinLocalPath(root: string, ...segments: string[]): string | null {
  const cleaned = segments.map(cleanRelativePath)
  if (cleaned.some((segment) => segment == null)) return null
  return [normalizeLocalPath(root), ...(cleaned as string[])]
    .filter(Boolean)
    .join("/")
}

function getPathExtension(path: string): string {
  const cleanPath = path.split(/[?#]/, 1)[0] ?? ""
  const fileName = cleanPath.replace(/\\/g, "/").split("/").pop() ?? ""
  const match = /(\.[^.]+)$/.exec(fileName)
  return match?.[1]?.toLowerCase() ?? ""
}

function isImagePath(path: string): boolean {
  return IMAGE_FILE_EXTENSIONS.has(getPathExtension(path))
}

function isMediaPath(path: string): boolean {
  return MEDIA_FILE_EXTENSIONS.has(getPathExtension(path))
}

function isAbsoluteLocalPath(path?: string | null): boolean {
  const value = path?.trim()
  if (!value) return false
  return (
    /^[A-Za-z]:[\\/]/.test(value) ||
    value.startsWith("\\\\") ||
    value.startsWith("/")
  )
}

function isInlineOrRemoteImageUrl(url: string): boolean {
  const value = url.trim()
  return (
    value.startsWith("data:image/") ||
    value.startsWith("http://") ||
    value.startsWith("https://")
  )
}

function isInlineOrRemoteMediaUrl(url: string): boolean {
  const value = url.trim()
  return (
    isInlineOrRemoteImageUrl(value) ||
    value.startsWith("data:video/") ||
    value.startsWith("http://") ||
    value.startsWith("https://")
  )
}

export function getStyleThumbnailDevUrl(fileName: string): string | null {
  const cleanFileName = cleanRelativePath(fileName)
  if (!cleanFileName || !isImagePath(cleanFileName)) return null
  return `${STYLE_THUMBNAIL_DEV_PREFIX}/${cleanFileName}`
}

async function ensurePluginResourceRoot(): Promise<string | null> {
  if (pluginResourceRoot !== undefined) return pluginResourceRoot
  if (pluginResourceRootPromise) return pluginResourceRootPromise
  if (!hasTauriBridge()) return null

  pluginResourceRootPromise = PluginSDK.getInfo()
    .then((info) => {
      const pluginDir = info.plugin_dir?.trim()
      pluginResourceRoot = pluginDir
        ? joinLocalPath(pluginDir, STYLE_THUMBNAIL_RESOURCE_DIR)
        : null
      return pluginResourceRoot
    })
    .catch(() => {
      pluginResourceRoot = null
      return pluginResourceRoot
    })
    .finally(() => {
      pluginResourceRootPromise = null
    })

  return pluginResourceRootPromise
}

async function ensurePluginDirRoot(): Promise<string | null> {
  if (pluginDirRoot !== undefined) return pluginDirRoot
  if (pluginDirRootPromise) return pluginDirRootPromise
  if (!hasTauriBridge()) return null

  pluginDirRootPromise = PluginSDK.getInfo()
    .then((info) => {
      pluginDirRoot = info.plugin_dir?.trim() || null
      return pluginDirRoot
    })
    .catch(() => {
      pluginDirRoot = null
      return pluginDirRoot
    })
    .finally(() => {
      pluginDirRootPromise = null
    })

  return pluginDirRootPromise
}

export async function resolveStyleThumbnailUrl(
  fileName: string
): Promise<string | null> {
  const cleanFileName = cleanRelativePath(fileName)
  if (!cleanFileName || !isImagePath(cleanFileName)) return null
  if (!hasTauriBridge()) return getStyleThumbnailDevUrl(cleanFileName)

  const root = await ensurePluginResourceRoot()
  if (!root) return null

  const localPath = joinLocalPath(root, cleanFileName)
  return localPath ? PluginSDK.convertFileSrc(localPath) : null
}

export type StyleTemplateThumbnailRef = {
  source?: string | null
  thumbnailUrl?: string | null
  thumbnailFile?: string | null
  thumbnail_file?: string | null
  thumbnailPath?: string | null
  thumbnail_path?: string | null
  filePath?: string | null
  file_path?: string | null
  path?: string | null
  relativePath?: string | null
  relative_path?: string | null
  file?: string | null
}

export type ProjectThumbnailRef = {
  id?: string | null
  name?: string | null
  source?: string | null
  url?: string | null
  path?: string | null
  filePath?: string | null
  file_path?: string | null
  relativePath?: string | null
  relative_path?: string | null
  file?: string | null
  styleThumbnailFile?: string | null
  style_thumbnail_file?: string | null
}

export function getProjectFileDevUrl(
  projectId: string,
  relativePath: string
): string | null {
  const cleanProjectId = cleanRelativePath(projectId)
  const cleanPath = cleanRelativePath(relativePath)
  if (!cleanProjectId || !cleanPath || !isMediaPath(cleanPath)) return null
  return `${PROJECT_FILES_DEV_PREFIX}/${cleanProjectId}/${cleanPath}`
}

export async function resolveProjectFileUrl(
  projectId: string,
  relativePath: string,
  absolutePath?: string | null
): Promise<string | null> {
  const cleanProjectId = cleanRelativePath(projectId)
  const cleanPath = cleanRelativePath(relativePath)
  if (!cleanProjectId || !cleanPath || !isMediaPath(cleanPath)) return null
  if (!hasTauriBridge()) return getProjectFileDevUrl(cleanProjectId, cleanPath)
  if (isAbsoluteLocalPath(absolutePath) && isMediaPath(absolutePath || "")) {
    return PluginSDK.convertFileSrc(absolutePath!.trim())
  }

  const root = await ensurePluginDirRoot()
  const localPath = root
    ? joinLocalPath(root, PROJECT_FILES_RESOURCE_DIR, cleanProjectId, cleanPath)
    : null
  return localPath ? PluginSDK.convertFileSrc(localPath) : null
}

export function getGlobalFileDevUrl(relativePath: string): string | null {
  const cleanPath = cleanRelativePath(relativePath)
  if (!cleanPath || !isMediaPath(cleanPath)) return null
  return `${GLOBAL_FILES_DEV_PREFIX}/${cleanPath}`
}

export async function resolveGlobalFileUrl(
  relativePath: string,
  absolutePath?: string | null
): Promise<string | null> {
  const cleanPath = cleanRelativePath(relativePath)
  if (!cleanPath || !isMediaPath(cleanPath)) return null
  if (!hasTauriBridge()) return getGlobalFileDevUrl(cleanPath)
  if (isAbsoluteLocalPath(absolutePath) && isMediaPath(absolutePath || "")) {
    return PluginSDK.convertFileSrc(absolutePath!.trim())
  }

  const root = await ensurePluginDirRoot()
  const localPath = root
    ? joinLocalPath(root, GLOBAL_FILES_RESOURCE_DIR, cleanPath)
    : null
  return localPath ? PluginSDK.convertFileSrc(localPath) : null
}

export async function resolveStyleTemplateThumbnailUrl(
  template?: StyleTemplateThumbnailRef | null
): Promise<string | null> {
  if (!template) return null
  if (template.thumbnailUrl && isInlineOrRemoteImageUrl(template.thumbnailUrl)) {
    return template.thumbnailUrl.trim()
  }
  const absolutePath =
    template.thumbnailPath ??
    template.thumbnail_path ??
    template.filePath ??
    template.file_path ??
    template.path
  const relativePath =
    template.relativePath ?? template.relative_path ?? template.file
  if (relativePath) return resolveGlobalFileUrl(relativePath, absolutePath)
  if (isAbsoluteLocalPath(absolutePath) && isImagePath(absolutePath || "")) {
    if (!hasTauriBridge()) return null
    return PluginSDK.convertFileSrc(absolutePath!.trim())
  }
  const fileName = template.thumbnailFile ?? template.thumbnail_file
  return fileName ? resolveStyleThumbnailUrl(fileName) : null
}

export async function resolveProjectThumbnailUrl(
  projectId: string,
  thumbnail?: ProjectThumbnailRef | null
): Promise<string | null> {
  if (!thumbnail) return null
  const styleFile = thumbnail.styleThumbnailFile ?? thumbnail.style_thumbnail_file
  if (styleFile) return resolveStyleThumbnailUrl(styleFile)
  const relativePath =
    thumbnail.relativePath ?? thumbnail.relative_path ?? thumbnail.file
  const absolutePath = thumbnail.path ?? thumbnail.filePath ?? thumbnail.file_path
  if (
    thumbnail.source === "favorite_style" ||
    thumbnail.source === "global_style"
  ) {
    return relativePath ? resolveGlobalFileUrl(relativePath, absolutePath) : null
  }
  if (relativePath) {
    return resolveProjectFileUrl(projectId, relativePath, absolutePath)
  }
  if (thumbnail.url && isInlineOrRemoteImageUrl(thumbnail.url)) {
    return thumbnail.url.trim()
  }
  return null
}

export async function resolveProjectMediaUrl(
  projectId: string,
  media?: {
    url?: string | null
    preview?: string | null
    relativePath?: string | null
    relative_path?: string | null
    file?: string | null
    path?: string | null
  } | null
): Promise<string | null> {
  if (!media) return null
  const relativePath = media.relativePath ?? media.relative_path ?? media.file
  if (relativePath) return resolveProjectFileUrl(projectId, relativePath, media.path)
  const inline = media.url ?? media.preview
  if (inline && isInlineOrRemoteMediaUrl(inline)) return inline.trim()
  return null
}
