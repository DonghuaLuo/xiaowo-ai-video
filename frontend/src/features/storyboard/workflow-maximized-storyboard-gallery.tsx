import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent, type ReactNode, type WheelEvent } from "react"
import { createPortal } from "react-dom"
import { ImageIcon, Loader2, Play } from "lucide-react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { errMsg } from "@/shared/backend-result"
import { localMediaFileSrc } from "@/shared/media"
import {
  MediaContextMenu,
  copyMediaSource,
  downloadMediaSource,
  mediaDownloadSource,
} from "@/shared/unified-media-frame"
import { resolveProjectMediaUrl } from "@/utils/style-thumbnails"
import type { InlineAssetTag } from "./inline-asset-tags"
import { isStoryboardCardNodeType, type WorkflowNodeData } from "./workflow-canvas-model"
import { useWorkflowOutputPreviews, type WorkflowOutputPreview } from "./use-workflow-output-previews"
import { selectWorkflowPreview, type PreviewSelection } from "./workflow-preview-selection"
import { StoryboardConsistencyReportPanel, useStoryboardConsistencyReport } from "./storyboard-consistency-report"

function OutputThumbnail({ item }: { item: WorkflowOutputPreview }) {
  const [failed, setFailed] = useState(false)
  const thumbnail = item.thumbnail || (item.kind === "image" ? item.src : "")
  useEffect(() => { setFailed(false) }, [item.src, thumbnail])
  return (
    <span className="relative flex size-full items-center justify-center overflow-hidden rounded-md bg-gray-100 dark:bg-white/5">
      {!failed && thumbnail ? (
        <img src={thumbnail} alt={item.label} className="size-full object-cover" draggable={false} onError={() => setFailed(true)} />
      ) : !failed && item.src && item.kind === "video" ? (
        <video src={item.src} className="size-full object-cover" muted playsInline preload="metadata" onError={() => setFailed(true)} />
      ) : item.kind === "video" ? <Play className="size-5 text-gray-400" /> : <ImageIcon className="size-5 text-gray-400" />}
      <span className="absolute right-0 bottom-0 flex h-3.5 min-w-3.5 items-center justify-center rounded-tl-sm bg-black/65 px-0.5 text-[9px] leading-none font-semibold text-white">
        {{ storyboard: "分", handoff: "交", video: "视" }[item.category]}
      </span>
    </span>
  )
}

export function WorkflowMaximizedStoryboardReferenceGallery({
  data,
  renderInputs,
}: {
  data: WorkflowNodeData
  renderInputs: (props: {
    selectedKey?: string
    onSelect: (tag: InlineAssetTag) => void
    onItemsChange: (tags: InlineAssetTag[]) => void
  }) => ReactNode
}) {
  const { items: outputs, loading: outputsLoading } = useWorkflowOutputPreviews(data)
  const [inputs, setInputs] = useState<InlineAssetTag[]>([])
  const [selection, setSelection] = useState<PreviewSelection | null>(null)
  const preview = selectWorkflowPreview(isStoryboardCardNodeType(data.eyebrow), inputs, outputs, selection)
  const selected = preview?.item
  const selectedSide = preview?.side
  const mediaKey = JSON.stringify([data.projectId, selectedSide, selected?.key, selected?.src, selected?.media])
  const [resolved, setResolved] = useState<{ key: string; src: string } | null>(null)
  const [failed, setFailed] = useState(false)
  const [viewport, setViewport] = useState({ scale: 1, x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null)
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; originX: number; originY: number } | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const inputStripRef = useRef<HTMLElement>(null)
  const outputStripRef = useRef<HTMLElement>(null)
  const thumbnailStripRef = useRef<HTMLDivElement>(null)
  const [videoInset, setVideoInset] = useState(0)
  const isVideo = selected?.kind === "video"
  const projectId = String(data.projectId ?? "")
  const selectedMedia = selected?.media
  const selectedSrc = selected?.src ?? ""
  const selectedStoryboard = isStoryboardCardNodeType(data.eyebrow) && selectedSide === "output"
    ? outputs.find((item) => item.key === selected?.key && item.nodeType === "storyboard.image")
    : undefined
  const consistencyReport = useStoryboardConsistencyReport(
    projectId,
    String(data.episodeId ?? ""),
    selectedStoryboard?.key ?? "",
    selectedStoryboard?.versionId ?? "",
  )

  useLayoutEffect(() => {
    if (!isVideo) return
    const inputStrip = inputStripRef.current
    const outputStrip = outputStripRef.current
    if (!inputStrip || !outputStrip) return
    const measure = () => {
      const width = Math.max(
        inputs.length ? inputStrip.getBoundingClientRect().width : 0,
        outputs.length ? outputStrip.getBoundingClientRect().width : 0,
      )
      // Match the strip's 8px outer inset and keep a 12px gap on both sides.
      setVideoInset(width > 0 ? Math.ceil(width) + 20 : 0)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(inputStrip)
    observer.observe(outputStrip)
    return () => observer.disconnect()
  }, [isVideo, inputs.length, outputs.length])

  useEffect(() => {
    let cancelled = false
    setFailed(false)
    setViewport({ scale: 1, x: 0, y: 0 })
    setContextMenu(null)
    dragRef.current = null
    setDragging(false)
    void resolveProjectMediaUrl(projectId, selectedMedia).then((src) => {
      if (!cancelled) setResolved({ key: mediaKey, src: localMediaFileSrc(selectedMedia) || src || selectedSrc })
    }).catch(() => {
      if (!cancelled) setResolved({ key: mediaKey, src: selectedSrc })
    })
    return () => { cancelled = true }
  }, [mediaKey, projectId, selectedMedia, selectedSrc])

  useEffect(() => {
    if (!contextMenu) return
    const dismiss = (event: globalThis.PointerEvent) => {
      if (event.target instanceof Node && menuRef.current?.contains(event.target)) return
      setContextMenu(null)
    }
    document.addEventListener("pointerdown", dismiss, true)
    return () => document.removeEventListener("pointerdown", dismiss, true)
  }, [contextMenu])

  const src = resolved?.key === mediaKey ? resolved.src : selected?.kind === "image" ? selectedSrc : ""
  useEffect(() => { setFailed(false) }, [src])
  const isImage = selected?.kind === "image"
  const resetViewport = () => {
    setViewport({ scale: 1, x: 0, y: 0 })
    setContextMenu(null)
  }
  const handleWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (!isImage || !src) return
    event.preventDefault()
    event.stopPropagation()
    setContextMenu(null)
    const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12
    setViewport((current) => ({ ...current, scale: Math.min(8, Math.max(0.25, current.scale * factor)) }))
  }
  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (!isImage || !src || event.button !== 0) return
    event.preventDefault()
    event.stopPropagation()
    setContextMenu(null)
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, originX: viewport.x, originY: viewport.y }
    setDragging(true)
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }
  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    event.preventDefault()
    event.stopPropagation()
    setViewport((current) => ({ ...current, x: drag.originX + event.clientX - drag.startX, y: drag.originY + event.clientY - drag.startY }))
  }
  const stopDragging = (event: PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return
    dragRef.current = null
    setDragging(false)
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }
  const handleCopy = async () => {
    if (!src) return
    try {
      await copyMediaSource(src)
      toast.success("媒体已复制")
    } catch (error) {
      toast.error(errMsg(error, "复制失败"))
    } finally {
      setContextMenu(null)
    }
  }
  const handleDownload = async () => {
    if (!selected || !src) return
    const filename = (selected.label || "ai-video-media").replace(/[\\/:*?"<>|]+/g, "-")
    try {
      const saved = await downloadMediaSource(
        filename + (isImage ? ".png" : ".mp4"),
        selected.kind,
        mediaDownloadSource(selected.media),
      )
      if (saved) toast.success("媒体已保存")
    } catch (error) {
      toast.error(errMsg(error, "下载失败"))
    } finally {
      setContextMenu(null)
    }
  }
  return (
    <section data-workflow-image-browser className="flex min-h-0 min-w-0 flex-1 basis-0 flex-col overflow-hidden rounded-lg border border-gray-200/80 bg-white dark:border-white/[0.07] dark:bg-[#18181b]"
      onContextMenuCapture={(event) => {
        const strip = thumbnailStripRef.current
        if (!strip || strip.contains(event.target as Node)) return
        // Empty strip space passes pointer events through to the preview so video
        // controls remain clickable. Shield only right clicks within that space.
        const rect = strip.getBoundingClientRect()
        if (event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom) {
          event.preventDefault()
          event.stopPropagation()
        }
      }}
    >
      <div className="flex shrink-0 items-center gap-2 border-b border-gray-200/80 px-3 py-2 dark:border-white/10">
        <span className="shrink-0 text-[11px] font-semibold text-gray-600 dark:text-white/60">媒体浏览</span>
        <span className="min-w-0 truncate text-[10px] text-gray-400 dark:text-white/40">{selected?.label}</span>
      </div>
      <div className="relative flex min-h-0 flex-1">
        <div
          className={cn("relative min-h-0 min-w-0 flex-1 overflow-hidden bg-black", isImage && src && (dragging ? "cursor-grabbing touch-none" : "cursor-grab touch-none"))}
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={stopDragging}
          onPointerCancel={stopDragging}
          onLostPointerCapture={() => { dragRef.current = null; setDragging(false) }}
          onContextMenu={(event) => {
            if (!src) return
            event.preventDefault()
            event.stopPropagation()
            setContextMenu({ x: event.clientX, y: event.clientY })
          }}
        >
          {src && !failed ? isImage ? (
            <img key={mediaKey} src={src} alt={selected?.label} draggable={false} className="absolute inset-0 m-auto max-h-full max-w-full select-none object-contain" style={{ transform: `translate3d(${viewport.x}px, ${viewport.y}px, 0) scale(${viewport.scale})`, transformOrigin: "center center" }} onError={() => setFailed(true)} />
          ) : (
            <div className="absolute inset-y-0 flex min-w-0 items-center justify-center" style={{ left: videoInset, right: videoInset }}>
              <video key={mediaKey} src={src} aria-label={selected?.label} className="h-auto max-h-full w-auto min-w-0 max-w-full object-contain" controls playsInline preload="metadata" onError={() => setFailed(true)} />
            </div>
          ) : (
            <div className="flex h-full min-h-0 items-center justify-center gap-2 p-2 text-center text-xs text-gray-400">
              {!failed && (outputsLoading || resolved?.key !== mediaKey) ? <><Loader2 className="size-4 shrink-0 animate-spin" />加载中</> : failed ? "媒体加载失败" : selected ? "暂无可预览媒体" : "暂无媒体"}
            </div>
          )}
        </div>
        <div ref={thumbnailStripRef} className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex items-end justify-between gap-4 p-2"
          onContextMenu={(event) => { event.preventDefault(); event.stopPropagation() }}
        >
          <aside ref={inputStripRef} aria-label="输入素材预览" className={cn("pointer-events-auto min-w-0 overflow-x-auto overflow-y-hidden p-1", isVideo ? "max-w-[25%]" : "max-w-[48%]")}>
            {renderInputs({
              selectedKey: selectedSide === "input" ? selected?.key : undefined,
              onSelect: (tag) => setSelection({ side: "input", key: tag.key }),
              onItemsChange: setInputs,
            })}
          </aside>
          <aside ref={outputStripRef} aria-label="输出结果预览" className={cn("pointer-events-auto min-w-0 overflow-x-auto overflow-y-hidden p-1", isVideo ? "max-w-[25%]" : "max-w-[48%]")}>
            <div className="flex w-max min-w-full items-center justify-end gap-2">
              {outputs.map((item) => (
                <button key={item.key} type="button" title={item.label} aria-label={`预览${item.label}`} aria-pressed={selectedSide === "output" && selected?.key === item.key} className={cn("size-9 shrink-0 rounded-md border border-gray-200 outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 dark:border-white/10", selectedSide === "output" && selected?.key === item.key && "ring-2 ring-indigo-500 ring-offset-1 dark:ring-offset-[#18181b]")} onClick={() => setSelection({ side: "output", key: item.key })}>
                  <OutputThumbnail item={item} />
                </button>
              ))}
            </div>
          </aside>
        </div>
      </div>
      {selectedStoryboard && consistencyReport && (consistencyReport.enabled || consistencyReport.checking || consistencyReport.report || consistencyReport.error || consistencyReport.loadError || consistencyReport.correction?.status === "running") && (
        <StoryboardConsistencyReportPanel key={JSON.stringify([projectId, data.episodeId, selectedStoryboard.key, selectedStoryboard.versionId])} state={consistencyReport} scope={{ projectId, episodeId: String(data.episodeId ?? ""), nodeId: selectedStoryboard.key, versionId: selectedStoryboard.versionId }} />
      )}
      {contextMenu && typeof document !== "undefined" ? createPortal(
        <div ref={menuRef}>
          <MediaContextMenu x={contextMenu.x} y={contextMenu.y} onReset={isImage ? resetViewport : undefined} onCopy={handleCopy} onDownload={handleDownload} />
        </div>,
        document.body,
      ) : null}
    </section>
  )
}
