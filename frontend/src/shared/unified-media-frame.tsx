import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { PluginSDK } from "xiaowo-sdk"
import { toast } from "sonner"
import {
  Copy,
  Download,
  Image,
  Maximize2,
  Play,
  RefreshCcw,
  Video,
  X,
} from "lucide-react"

import type { MediaAsset } from "@/backend"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { TooltipWrap } from "@/shared/tooltip-wrap"

export type MediaDownloadSource = {
  path?: string | null
  name?: string | null
  mimeType?: string | null
}

function errMsg(err: unknown, fallback = "操作失败"): string {
  if (err instanceof Error) return err.message
  if (typeof err === "string") return err
  return fallback
}

async function copyText(text: string): Promise<void> {
  try {
    await PluginSDK.clipboard.writeText(text)
    return
  } catch {
    // Fall back to browser APIs in dev mode.
  }

  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text)
  }

  const textarea = document.createElement("textarea")
  textarea.value = text
  textarea.style.position = "fixed"
  textarea.style.opacity = "0"
  document.body.appendChild(textarea)
  try {
    textarea.select()
    const copied = document.execCommand("copy")
    if (!copied) throw new Error("复制到剪贴板失败")
  } finally {
    document.body.removeChild(textarea)
  }
}

export async function copyMediaSource(src: string) {
  try {
    const response = await fetch(src)
    const blob = await response.blob()
    const ClipboardItemCtor = window.ClipboardItem
    if (navigator.clipboard?.write && ClipboardItemCtor) {
      await navigator.clipboard.write([
        new ClipboardItemCtor({ [blob.type || "image/png"]: blob }),
      ])
      return
    }
  } catch {
    // Fall back to copying the URL/data URL text below.
  }
  await copyText(src)
}

const INVALID_FILENAME_CHARS = new Set([
  "<",
  ">",
  ":",
  '"',
  "/",
  "\\",
  "|",
  "?",
  "*",
])

function isAbsoluteLocalPath(value?: string | null) {
  const path = value?.trim()
  if (!path) return false
  return (
    /^[A-Za-z]:[\\/]/.test(path) ||
    path.startsWith("\\\\") ||
    path.startsWith("/")
  )
}

function extensionFromName(name?: string | null) {
  const clean = (name ?? "").split(/[?#]/)[0] ?? ""
  const match = clean.match(/\.([a-z0-9]+)$/i)
  return match ? match[1].toLowerCase() : null
}

function extensionFromMime(mimeType?: string | null) {
  const value = mimeType?.toLowerCase() ?? ""
  if (value.includes("png")) return "png"
  if (value.includes("jpeg") || value.includes("jpg")) return "jpg"
  if (value.includes("webp")) return "webp"
  if (value.includes("gif")) return "gif"
  if (value.includes("webm")) return "webm"
  if (value.includes("quicktime")) return "mov"
  if (value.includes("mp4")) return "mp4"
  return null
}

function filenameFromPath(path?: string | null) {
  const clean = (path ?? "").split(/[?#]/)[0] ?? ""
  const last = clean.split(/[\\/]/).filter(Boolean).pop()
  if (!last) return null
  try {
    return decodeURIComponent(last)
  } catch {
    return last
  }
}

function sanitizeBaseName(value: string, fallback: string) {
  const trimmed = value.trim().replace(/\.[a-z0-9]+$/i, "")
  const safe = Array.from(trimmed, (char) =>
    char.charCodeAt(0) < 32 || INVALID_FILENAME_CHARS.has(char) ? "_" : char
  )
    .join("")
    .replace(/\s+/g, " ")
  return safe || fallback
}

export function mediaDownloadSource(
  media?: MediaAsset | null
): MediaDownloadSource | null {
  if (!media) return null
  const localPath = media.filePath ?? media.path
  if (isAbsoluteLocalPath(localPath)) {
    return {
      path: localPath!.trim(),
      name: media.originalName ?? filenameFromPath(localPath),
      mimeType: media.mimeType,
    }
  }
  return null
}

export async function downloadMediaSource(
  filename: string,
  kind: "image" | "video",
  source?: MediaDownloadSource | null
) {
  const sourceName = source?.name ?? filenameFromPath(source?.path) ?? filename
  const fallbackBase = kind === "video" ? "ai-video-media" : "ai-video-image"
  const ext =
    extensionFromName(sourceName) ??
    extensionFromMime(source?.mimeType) ??
    extensionFromName(filename) ??
    (kind === "video" ? "mp4" : "png")
  const savePath = await PluginSDK.dialog.save({
    title: kind === "video" ? "保存视频" : "保存图片",
    defaultPath: `${sanitizeBaseName(sourceName, fallbackBase)}.${ext}`,
    filters: [
      kind === "video"
        ? { name: "Videos", extensions: ["mp4", "webm", "mov"] }
        : { name: "Images", extensions: ["png", "jpg", "jpeg", "webp", "gif"] },
    ],
  })
  if (!savePath) return null

  const sourcePath = source?.path?.trim()
  if (!sourcePath) {
    throw new Error("当前媒体没有可复制的本地文件")
  }
  await PluginSDK.fs.copyFile(sourcePath, savePath)
  return savePath
}

export function MediaContextMenu({
  x,
  y,
  onReset,
  onCopy,
  onDownload,
}: {
  x: number
  y: number
  onReset?: () => void
  onCopy: () => Promise<void> | void
  onDownload: () => Promise<void> | void
}) {
  return (
    <div
      className="fixed z-[620] min-w-32 overflow-hidden rounded-lg border border-white/10 bg-slate-950/95 p-1 text-[12px] text-white shadow-2xl shadow-black/50 backdrop-blur"
      style={{ left: x, top: y }}
      onClick={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.stopPropagation()}
    >
      {onReset ? (
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-white/10"
          onClick={onReset}
        >
          <RefreshCcw className="size-3.5" />
          恢复默认
        </button>
      ) : null}
      <button
        type="button"
        className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-white/10"
        onClick={() => void onCopy()}
      >
        <Copy className="size-3.5" />
        复制
      </button>
      <button
        type="button"
        className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-white/10"
        onClick={() => void onDownload()}
      >
        <Download className="size-3.5" />
        下载
      </button>
    </div>
  )
}

export function UnifiedMediaFrame({
  src,
  alt,
  kind = "image",
  title,
  className,
  fallbackClassName,
  fit = "cover",
  interactive = true,
  showActions = true,
  downloadSource,
  naturalSize = false,
  fallbackMinHeight = true,
  previewOpenSignal,
  compactVideoPreview = false,
}: {
  src?: string | null
  alt: string
  kind?: "image" | "video"
  title?: string
  className?: string
  fallbackClassName?: string
  fit?: "cover" | "contain"
  interactive?: boolean
  showActions?: boolean
  downloadSource?: MediaDownloadSource | null
  naturalSize?: boolean
  fallbackMinHeight?: boolean
  previewOpenSignal?: number
  compactVideoPreview?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [lightboxMenu, setLightboxMenu] = useState<{
    x: number
    y: number
  } | null>(null)
  const [viewport, setViewport] = useState({ scale: 1, x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const dragRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    originX: number
    originY: number
  } | null>(null)
  const handledPreviewOpenSignalRef = useRef(0)
  const canPreview = Boolean(src)
  const filename = `${(title || alt || "ai-video-media").replace(/[\\/:*?"<>|]+/g, "-")}.${kind === "video" ? "mp4" : "png"}`
  const showPreviewActions = Boolean(canPreview && showActions)
  const showPreviewExpandButton = Boolean(
    canPreview && interactive && showActions && kind === "video" && !compactVideoPreview
  )
  const showVideoPlayOverlay = Boolean(
    canPreview && interactive && showActions && kind === "video"
  )

  useEffect(() => {
    if (!open) {
      setViewport({ scale: 1, x: 0, y: 0 })
      setLightboxMenu(null)
      return
    }
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false)
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener("keydown", handleKeyDown)
    }
  }, [open])

  useEffect(() => {
    const signal = previewOpenSignal ?? 0
    if (!signal) {
      handledPreviewOpenSignalRef.current = 0
      return
    }
    if (!src || signal === handledPreviewOpenSignalRef.current) return
    handledPreviewOpenSignalRef.current = signal
    setOpen(true)
  }, [previewOpenSignal, src])

  const handleCopy = async () => {
    if (!src) return
    try {
      await copyMediaSource(src)
      toast.success("媒体已复制")
    } catch (error) {
      toast.error(errMsg(error, "复制失败"))
    } finally {
      setLightboxMenu(null)
    }
  }

  const handleDownload = async () => {
    if (!src) return
    try {
      const savedPath = await downloadMediaSource(filename, kind, downloadSource)
      if (savedPath) {
        toast.success("媒体已保存")
      }
    } catch (error) {
      toast.error(errMsg(error, "下载失败"))
    } finally {
      setLightboxMenu(null)
    }
  }

  const openLightboxContextMenu = (event: React.MouseEvent) => {
    if (!src || !showPreviewActions) return
    event.preventDefault()
    event.stopPropagation()
    setLightboxMenu({ x: event.clientX, y: event.clientY })
  }

  const stopLightboxContextMenu = (event: React.MouseEvent) => {
    event.stopPropagation()
  }

  const resetImageViewport = () => {
    setViewport({ scale: 1, x: 0, y: 0 })
    setLightboxMenu(null)
  }

  const handleWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (kind !== "image") return
    event.preventDefault()
    event.stopPropagation()
    setLightboxMenu(null)
    const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12
    setViewport((current) => {
      const nextScale = current.scale * factor
      if (!Number.isFinite(nextScale) || nextScale <= 0) return current
      return { ...current, scale: nextScale }
    })
  }

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (kind !== "image" || event.button !== 0) return
    event.preventDefault()
    event.stopPropagation()
    setLightboxMenu(null)
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: viewport.x,
      originY: viewport.y,
    }
    setDragging(true)
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId)
    } catch {
      // Synthetic or interrupted pointer streams may not be capturable.
    }
  }

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    event.preventDefault()
    event.stopPropagation()
    setViewport((current) => ({
      ...current,
      x: drag.originX + event.clientX - drag.startX,
      y: drag.originY + event.clientY - drag.startY,
    }))
  }

  const stopDragging = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    event.preventDefault()
    event.stopPropagation()
    dragRef.current = null
    setDragging(false)
    try {
      event.currentTarget.releasePointerCapture?.(event.pointerId)
    } catch {
      // Pointer capture may already be gone if the drag was cancelled.
    }
  }

  const handlePreviewClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!src || !interactive) return
    event.stopPropagation()
    setOpen(true)
  }

  const handlePreviewKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!src || !interactive) return
    if (event.key !== "Enter" && event.key !== " ") return
    event.preventDefault()
    event.stopPropagation()
    setOpen(true)
  }

  const handlePreviewButtonClick = (
    event: React.MouseEvent<HTMLButtonElement>
  ) => {
    if (!src || !interactive) return
    event.preventDefault()
    event.stopPropagation()
    setOpen(true)
  }

  const previewContent = src ? (
    <div
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-label={interactive ? `${alt} 预览` : undefined}
      className={cn(
        naturalSize ? "block w-full" : "block h-full w-full",
        interactive
          ? cn(
              "focus:ring-2 focus:ring-indigo-300/70 focus:outline-none",
              kind === "video" ? "cursor-pointer" : "cursor-zoom-in"
            )
          : ""
      )}
      onClick={handlePreviewClick}
      onKeyDown={handlePreviewKeyDown}
    >
      {kind === "video" ? (
        <video
          src={src}
          className={cn(
            naturalSize ? "block h-auto w-full" : "h-full w-full",
            !naturalSize && (fit === "contain" ? "object-contain" : "object-cover")
          )}
          muted
          playsInline
          preload="metadata"
        />
      ) : (
        <img
          src={src}
          alt={alt}
          className={cn(
            naturalSize ? "block h-auto w-full" : "h-full w-full",
            !naturalSize && (fit === "contain" ? "object-contain" : "object-cover")
          )}
          draggable={false}
          loading="lazy"
          decoding="async"
        />
      )}
      {showVideoPlayOverlay ? (
        <div className="pointer-events-none absolute inset-0 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          <span className="absolute inset-0 grid place-items-center bg-black/20">
            <span
              className={cn(
                "grid place-items-center rounded-full border border-white/20 bg-black/60 text-white shadow-lg backdrop-blur-sm",
                compactVideoPreview ? "size-7" : "size-11"
              )}
            >
              <Play
                className={cn(
                  "ml-0.5 fill-current",
                  compactVideoPreview ? "size-3.5" : "size-5"
                )}
              />
            </span>
          </span>
        </div>
      ) : null}
    </div>
  ) : null

  const lightboxLayer = open && src ? (
    <div
      data-media-lightbox="true"
      role="dialog"
      aria-modal="true"
      aria-label={`${alt} ${kind === "video" ? "全屏播放" : "全屏预览"}`}
      className="pointer-events-auto fixed inset-0 z-[500] flex items-center justify-center bg-slate-950/94 p-5 backdrop-blur-sm sm:p-8"
      onClick={() => setOpen(false)}
      onContextMenu={stopLightboxContextMenu}
    >
      <TooltipWrap content="关闭">
        <button
          type="button"
          className="absolute top-5 right-5 z-20 grid size-10 place-items-center rounded-full border border-white/10 bg-black/55 text-white shadow-lg backdrop-blur-sm transition hover:bg-black/75"
          onClick={() => setOpen(false)}
        >
          <X className="size-5" />
        </button>
      </TooltipWrap>
      {showPreviewActions ? (
        <div
          className="absolute top-5 right-[4.5rem] z-20 flex gap-2"
          onContextMenu={stopLightboxContextMenu}
        >
          <TooltipWrap content="复制">
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              className="size-10 rounded-full border border-white/10 bg-black/55 text-white backdrop-blur-sm hover:bg-black/75 hover:text-white"
              onClick={(event) => {
                event.stopPropagation()
                void handleCopy()
              }}
            >
              <Copy className="size-4" />
            </Button>
          </TooltipWrap>
          <TooltipWrap content="下载">
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              className="size-10 rounded-full border border-white/10 bg-black/55 text-white backdrop-blur-sm hover:bg-black/75 hover:text-white"
              onClick={(event) => {
                event.stopPropagation()
                void handleDownload()
              }}
            >
              <Download className="size-4" />
            </Button>
          </TooltipWrap>
        </div>
      ) : null}
      <div
        className={cn(
          "relative z-10 flex max-h-full max-w-full touch-none items-center justify-center select-none",
          kind === "image" ? (dragging ? "cursor-grabbing" : "cursor-grab") : ""
        )}
        onClick={(event) => event.stopPropagation()}
        onContextMenu={openLightboxContextMenu}
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={stopDragging}
        onPointerCancel={stopDragging}
      >
        {kind === "video" ? (
          <video
            src={src}
            className="max-h-[calc(100vh-4rem)] max-w-[calc(100vw-3rem)] rounded-xl border border-white/10 bg-black object-contain shadow-[0_30px_120px_rgba(0,0,0,0.55)]"
            controls
            autoPlay
            playsInline
            preload="metadata"
            onContextMenu={openLightboxContextMenu}
          />
        ) : (
          <img
            src={src}
            alt={alt}
            className="max-h-[calc(100vh-3rem)] max-w-[calc(100vw-2rem)] rounded-2xl border border-white/10 bg-black/35 object-contain shadow-[0_30px_120px_rgba(0,0,0,0.55)] sm:max-h-[calc(100vh-5rem)] sm:max-w-[calc(100vw-4rem)]"
            draggable={false}
            onContextMenu={openLightboxContextMenu}
            style={{
              transform: `translate3d(${viewport.x}px, ${viewport.y}px, 0) scale(${viewport.scale})`,
              transformOrigin: "center center",
            }}
          />
        )}
      </div>
      {lightboxMenu ? (
        <MediaContextMenu
          x={lightboxMenu.x}
          y={lightboxMenu.y}
          onReset={kind === "image" ? resetImageViewport : undefined}
          onCopy={handleCopy}
          onDownload={handleDownload}
        />
      ) : null}
    </div>
  ) : null

  return (
    <>
      <div
        className={cn(
          "group relative overflow-hidden rounded-md border border-gray-200/70 bg-gray-950/5 dark:border-white/10 dark:bg-white/[0.035]",
          className
        )}
      >
        {src && previewContent ? (
          kind === "video" ? (
            <TooltipWrap
              content={interactive && !compactVideoPreview ? "点击全屏播放" : undefined}
            >
              {previewContent}
            </TooltipWrap>
          ) : (
            previewContent
          )
        ) : (
          <div
            className={cn(
              "flex h-full flex-col items-center justify-center gap-2 bg-gradient-to-br px-3 text-center text-white/85",
              fallbackMinHeight ? "min-h-[160px]" : "min-h-0",
              fallbackClassName || "from-indigo-600 via-sky-600 to-emerald-500"
            )}
          >
            {kind === "video" ? (
              <Video className="size-7" />
            ) : (
              <Image className="size-7" />
            )}
            <span className="text-xs font-semibold">{alt}</span>
          </div>
        )}
        {showPreviewExpandButton ? (
          <TooltipWrap content="全屏播放">
            <button
              type="button"
              aria-label={`${alt} 全屏播放`}
              className="absolute top-2 right-2 z-10 grid size-7 place-items-center rounded-full bg-black/60 text-white opacity-0 shadow-sm backdrop-blur-sm transition hover:bg-black/75 focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-white/70 group-hover:opacity-100 group-focus-within:opacity-100"
              onClick={handlePreviewButtonClick}
            >
              <Maximize2 className="size-3.5" />
            </button>
          </TooltipWrap>
        ) : null}
      </div>
      {lightboxLayer && typeof document !== "undefined"
        ? createPortal(lightboxLayer, document.body)
        : null}
    </>
  )
}
