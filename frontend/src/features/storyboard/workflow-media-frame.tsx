import { createPortal } from "react-dom"
import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
  type WheelEvent,
} from "react"
import { toast } from "sonner"
import {
  Copy,
  Download,
  ImagePlus,
  Maximize2,
  Play,
  X,
} from "lucide-react"
import {
  listStoryboardVersions,
  type MediaAsset,
} from "@/backend"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import { errMsg } from "@/shared/backend-result"
import {
  MediaContextMenu,
  copyMediaSource,
  downloadMediaSource,
  mediaDownloadSource,
} from "@/shared/unified-media-frame"
import { mediaPreviewSrc } from "@/shared/media"
import { resolveProjectMediaUrl } from "@/utils/style-thumbnails"
import { Button } from "@/components/ui/button"

export type WorkflowMediaFrameData = {
  title: string
  eyebrow: string
  tone: string
  [key: string]: any
}

function stopCardWheel(event: WheelEvent<HTMLElement>) {
  const target = event.target
  if (target instanceof Element && target.closest("[data-media-lightbox='true']")) return
  event.stopPropagation()
  event.nativeEvent.stopImmediatePropagation?.()
}

function isResultImageType(value?: string | null) {
  return String(value ?? "").trim() === "storyboard.image"
}

function dataCurrentVersionId(data?: WorkflowMediaFrameData | null) {
  return (
    String(data?.activeVersionId ?? "").trim() ||
    String(data?.activeMediaVersionId ?? "").trim() ||
    String(data?.mediaVersionId ?? "").trim() ||
    null
  )
}

function dataHasCurrentMedia(data?: WorkflowMediaFrameData | null) {
  const media = data?.media ?? data?.storage
  return Boolean(
    mediaPreviewSrc(media) ||
      String(data?.mediaId ?? "").trim() ||
      dataCurrentVersionId(data) ||
      String(data?.preview ?? data?.previewUrl ?? data?.previewSrc ?? "").trim()
  )
}

function versionStorageNodeId(nodeId: string, data?: WorkflowMediaFrameData | null) {
  const type = String(data?.eyebrow ?? "").trim()
  const role = String(data?.canvasNodeRole ?? data?.mediaPurpose ?? "").trim()
  if (
    type === "video.result" ||
    type === "storyboard.image" ||
    role === "visual_handoff" ||
    role === "visual_handoff_reference"
  ) return nodeId
  return String(data?.resultOfNodeId ?? "").trim() || nodeId
}

function workflowMediaKind(data: WorkflowMediaFrameData, media?: MediaAsset | null): "image" | "video" {
  const mime = String(media?.mimeType ?? "").toLowerCase()
  if (media?.kind === "video" || mime.startsWith("video/")) return "video"
  const path = String(media?.path ?? media?.file ?? media?.url ?? media?.preview ?? "").trim()
  if (/\.(mp4|m4v|mov|webm|avi|mkv)(?:[?#].*)?$/i.test(path)) return "video"
  for (const value of [data.mediaKind, data.media_kind, data.mediaType, data.media_type]) {
    const normalized = String(value ?? "").trim().toLowerCase()
    if (normalized === "video") return "video"
  }
  return "image"
}

function canvasPreviewFilename(title: string | undefined, kind: "image" | "video") {
  const base = (title || (kind === "video" ? "ai-video" : "ai-image"))
    .replace(/[\\/:*?"<>|]+/g, "-")
    .trim()
  return `${base || "ai-media"}.${kind === "video" ? "mp4" : "png"}`
}

export function CanvasWorkflowMediaFrame({
  src,
  alt,
  title,
  kind,
  className,
  fallbackClassName,
  downloadSource,
}: {
  src?: string | null
  alt: string
  title?: string
  kind: "image" | "video"
  className?: string
  fallbackClassName?: string
  downloadSource?: ReturnType<typeof mediaDownloadSource>
}) {
  const [open, setOpen] = useState(false)
  const [lightboxMenu, setLightboxMenu] = useState<{
    x: number
    y: number
  } | null>(null)
  const [viewport, setViewport] = useState({ scale: 1, x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const inlineVideoRef = useRef<HTMLVideoElement | null>(null)
  const [inlineVideoPlaying, setInlineVideoPlaying] = useState(false)
  const dragRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    originX: number
    originY: number
  } | null>(null)

  useEffect(() => {
    if (!open) {
      setViewport({ scale: 1, x: 0, y: 0 })
      setDragging(false)
      setLightboxMenu(null)
      dragRef.current = null
      return
    }
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false)
    }
    window.addEventListener("keydown", onKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener("keydown", onKeyDown)
    }
  }, [open])

  useEffect(() => {
    setInlineVideoPlaying(false)
    const video = inlineVideoRef.current
    if (!video || kind !== "video") return
    const handlePlay = () => setInlineVideoPlaying(true)
    const handlePause = () => setInlineVideoPlaying(false)
    video.addEventListener("play", handlePlay)
    video.addEventListener("pause", handlePause)
    video.addEventListener("ended", handlePause)
    return () => {
      video.removeEventListener("play", handlePlay)
      video.removeEventListener("pause", handlePause)
      video.removeEventListener("ended", handlePause)
    }
  }, [kind, src])

  const handleCopy = async (event?: MouseEvent<HTMLElement>) => {
    event?.stopPropagation()
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

  const handleDownload = async (event?: MouseEvent<HTMLElement>) => {
    event?.stopPropagation()
    if (!src) return
    try {
      const savedPath = await downloadMediaSource(
        canvasPreviewFilename(downloadSource?.name ?? title ?? alt, kind),
        kind,
        downloadSource
      )
      if (savedPath) {
        toast.success("媒体已保存")
      }
    } catch (error) {
      toast.error(errMsg(error, "下载失败"))
    } finally {
      setLightboxMenu(null)
    }
  }

  const toggleInlineVideoPlayback = async () => {
    const video = inlineVideoRef.current
    if (!video) return
    try {
      if (video.paused || video.ended) {
        await video.play()
      } else {
        video.pause()
      }
    } catch (error) {
      toast.error(errMsg(error, "播放失败"))
    }
  }

  const handleInlineVideoClick = (event: MouseEvent<HTMLDivElement>) => {
    event.stopPropagation()
    void toggleInlineVideoPlayback()
  }

  const handleInlineVideoKeyDown = (
    event: KeyboardEvent<HTMLDivElement>
  ) => {
    if (event.key !== "Enter" && event.key !== " ") return
    event.preventDefault()
    event.stopPropagation()
    void toggleInlineVideoPlayback()
  }

  const handlePreviewWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (kind !== "image") return
    event.preventDefault()
    event.stopPropagation()
    setLightboxMenu(null)
    const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12
    setViewport((current) => ({
      ...current,
      scale: Math.min(8, Math.max(0.25, current.scale * factor)),
    }))
  }

  const handlePreviewPointerDown = (
    event: PointerEvent<HTMLDivElement>
  ) => {
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
      // Pointer capture can fail when the pointer stream is interrupted.
    }
  }

  const handlePreviewPointerMove = (
    event: PointerEvent<HTMLDivElement>
  ) => {
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

  const stopPreviewDrag = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    event.preventDefault()
    event.stopPropagation()
    dragRef.current = null
    setDragging(false)
    try {
      event.currentTarget.releasePointerCapture?.(event.pointerId)
    } catch {
      // Pointer capture may already be released.
    }
  }

  const stopPreviewContextMenu = (event: MouseEvent<HTMLElement>) => {
    event.stopPropagation()
  }

  const openPreviewContextMenu = (event: MouseEvent<HTMLElement>) => {
    if (!src) return
    event.preventDefault()
    event.stopPropagation()
    setLightboxMenu({ x: event.clientX, y: event.clientY })
  }

  const resetImageViewport = () => {
    setViewport({ scale: 1, x: 0, y: 0 })
    setLightboxMenu(null)
  }

  return (
    <>
      <div
        className={cn(
          "nowheel group/canvas-media relative block w-full overflow-hidden rounded-lg bg-black",
          className
        )}
        onWheel={stopCardWheel}
        onWheelCapture={stopCardWheel}
      >
        {src ? (
          kind === "video" ? (
            <>
              <div
                role="button"
                tabIndex={0}
                aria-label={`${alt} 播放或暂停`}
                className="nodrag nopan relative block w-full cursor-pointer focus:ring-2 focus:ring-indigo-300/70 focus:outline-none"
                onClick={handleInlineVideoClick}
                onKeyDown={handleInlineVideoKeyDown}
                onPointerDown={(event) => event.stopPropagation()}
              >
                <video
                  ref={inlineVideoRef}
                  src={src}
                  className="block h-auto w-full"
                  muted
                  playsInline
                  preload="metadata"
                />
                {!inlineVideoPlaying ? (
                  <div className="pointer-events-none absolute inset-0 grid place-items-center bg-black/10 opacity-0 transition-opacity group-focus-within/canvas-media:opacity-100 group-hover/canvas-media:opacity-100">
                    <span className="grid size-10 place-items-center rounded-full border border-white/20 bg-black/55 text-white shadow-lg backdrop-blur-sm">
                      <Play className="ml-0.5 size-4 fill-current" />
                    </span>
                  </div>
                ) : null}
              </div>
              <button
                type="button"
                aria-label={`${alt} 放大预览`}
                title="放大预览"
                className="absolute top-2 right-2 z-10 grid size-7 place-items-center rounded-full bg-black/60 text-white opacity-85 shadow-sm backdrop-blur-sm transition hover:bg-black/75 hover:opacity-100 focus:ring-2 focus:ring-white/70 focus:outline-none"
                onClick={(event) => {
                  event.stopPropagation()
                  inlineVideoRef.current?.pause()
                  setOpen(true)
                }}
              >
                <Maximize2 className="size-3.5" />
              </button>
            </>
          ) : (
            <div
              role="button"
              tabIndex={0}
              aria-label={`${alt} 预览`}
              className="block w-full cursor-zoom-in p-0 text-left focus:ring-2 focus:ring-indigo-300/70 focus:outline-none active:cursor-grab"
              onClick={(event) => {
                event.stopPropagation()
                setOpen(true)
              }}
              onKeyDown={(event) => {
                if (event.key !== "Enter" && event.key !== " ") return
                event.preventDefault()
                event.stopPropagation()
                setOpen(true)
              }}
            >
              <img
                src={src}
                alt={alt}
                className="block h-auto w-full select-none"
                draggable={false}
                loading="lazy"
                decoding="async"
              />
            </div>
          )
        ) : (
          <div
            className={cn(
              "flex aspect-[4/3] w-full flex-col items-center justify-center gap-2 bg-gradient-to-br text-white/85",
              fallbackClassName || "from-indigo-600 via-sky-600 to-emerald-500"
            )}
          >
            <ImagePlus className="size-7" />
            <span className="text-xs font-semibold">{alt}</span>
          </div>
        )}
      </div>
      {open && src && typeof document !== "undefined"
        ? createPortal(
            <div
              role="dialog"
              aria-modal="true"
              aria-label={`${alt} ${kind === "video" ? "视频预览" : "图片预览"}`}
              className="fixed inset-0 z-[240] flex items-center justify-center bg-slate-950/95 p-5 backdrop-blur-sm"
              onClick={() => setOpen(false)}
              onContextMenu={stopPreviewContextMenu}
            >
              <div
                className="fixed top-4 right-4 z-[250] flex gap-2"
                onClick={(event) => event.stopPropagation()}
                onContextMenu={stopPreviewContextMenu}
              >
                <Button
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  title="复制"
                  className="size-10 rounded-full border border-white/10 bg-black/55 text-white backdrop-blur-sm hover:bg-black/75 hover:text-white"
                  onClick={handleCopy}
                >
                  <Copy className="size-4" />
                </Button>
                <Button
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  title="下载"
                  className="size-10 rounded-full border border-white/10 bg-black/55 text-white backdrop-blur-sm hover:bg-black/75 hover:text-white"
                  onClick={handleDownload}
                >
                  <Download className="size-4" />
                </Button>
                <Button
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  title="关闭"
                  className="size-10 rounded-full border border-white/10 bg-black/55 text-white backdrop-blur-sm hover:bg-black/75 hover:text-white"
                  onClick={(event) => {
                    event.stopPropagation()
                    setOpen(false)
                  }}
                >
                  <X className="size-4" />
                </Button>
              </div>
              <div
                className={cn(
                  "relative z-[245] flex max-h-full max-w-full touch-none items-center justify-center select-none",
                  kind === "image"
                    ? dragging
                      ? "cursor-grabbing"
                      : "cursor-grab"
                    : ""
                )}
                onClick={(event) => event.stopPropagation()}
                onContextMenu={openPreviewContextMenu}
                onWheel={handlePreviewWheel}
                onPointerDown={handlePreviewPointerDown}
                onPointerMove={handlePreviewPointerMove}
                onPointerUp={stopPreviewDrag}
                onPointerCancel={stopPreviewDrag}
              >
                {kind === "video" ? (
                  <video
                    src={src}
                    className="max-h-[calc(100vh-4rem)] max-w-[calc(100vw-3rem)] rounded-xl border border-white/10 bg-black object-contain shadow-[0_30px_120px_rgba(0,0,0,0.55)]"
                    controls
                    autoPlay
                    playsInline
                    preload="metadata"
                    onContextMenu={openPreviewContextMenu}
                  />
                ) : (
                  <img
                    src={src}
                    alt={alt}
                    className="max-h-[calc(100vh-4rem)] max-w-[calc(100vw-3rem)] rounded-xl border border-white/10 bg-black/35 object-contain shadow-[0_30px_120px_rgba(0,0,0,0.55)]"
                    draggable={false}
                    onContextMenu={openPreviewContextMenu}
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
            </div>,
            document.body
          )
        : null}
    </>
  )
}

export function WorkflowPureMediaFrame({
  projectId,
  episodeId,
  nodeId,
  data,
  className,
}: {
  projectId?: string
  episodeId?: string
  nodeId: string
  data: WorkflowMediaFrameData
  className?: string
}) {
  const { backendReady, callBackend } = useBackend()
  const isGeneratedMediaNode =
    isResultImageType(data.eyebrow) || data.eyebrow === "video.result"
  const hasGeneratedMediaReference =
    dataHasCurrentMedia(data)
  const allowGeneratedPreview =
    !isGeneratedMediaNode || hasGeneratedMediaReference
  const directMedia = allowGeneratedPreview
    ? (data.media ?? data.storage ?? null)
    : null
  const directSrc = mediaPreviewSrc(directMedia)
  const versionNodeId = versionStorageNodeId(nodeId, data)
  const preferredVersionId = allowGeneratedPreview
    ? dataCurrentVersionId(data)
    : null
  const [versionSrc, setVersionSrc] = useState<string | null>(null)
  const [versionMedia, setVersionMedia] = useState<MediaAsset | null>(null)

  useEffect(() => {
    let cancelled = false
    setVersionSrc(null)
    setVersionMedia(null)
    if (
      !allowGeneratedPreview ||
      directSrc ||
      !preferredVersionId ||
      !backendReady ||
      !projectId ||
      !episodeId
    ) {
      return () => {
        cancelled = true
      }
    }
    void listStoryboardVersions(
      callBackend,
      projectId,
      episodeId,
      versionNodeId
    )
      .then((versions) => {
        if (cancelled) return
        const selected = versions.find(
          (version) => version.id === preferredVersionId
        )
        if (!selected) return
        setVersionMedia(selected.media ?? null)
        return resolveProjectMediaUrl(projectId, {
          ...(selected.media ?? {}),
          preview: selected.preview ?? selected.media?.preview ?? null,
        }).then((url) => {
          if (!cancelled) setVersionSrc(url ?? selected.preview ?? null)
        })
      })
      .catch(() => {
        if (!cancelled) {
          setVersionSrc(null)
          setVersionMedia(null)
        }
      })
    return () => {
      cancelled = true
    }
  }, [
    backendReady,
    callBackend,
    directSrc,
    episodeId,
    allowGeneratedPreview,
    preferredVersionId,
    projectId,
    versionNodeId,
  ])

  const media = directMedia ?? versionMedia
  const src = directSrc ?? versionSrc
  return (
    <CanvasWorkflowMediaFrame
      src={src}
      alt={data.title}
      title={data.title}
      kind={workflowMediaKind(data, media)}
      className={className}
      downloadSource={mediaDownloadSource(media)}
      fallbackClassName={data.tone}
    />
  )
}


