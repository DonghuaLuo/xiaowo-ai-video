import { useEffect, useRef, useState } from "react"
import { convertFileSrc } from "xiaowo-sdk"
import WaveSurfer from "wavesurfer.js"
import RegionsPlugin, { type Region } from "wavesurfer.js/plugins/regions"
import ZoomPlugin from "wavesurfer.js/plugins/zoom"
import { Loader2, Pause, Play, Scissors, Square } from "lucide-react"

import {
  cleanupReferenceAudio,
  cropReferenceAudio,
  prepareReferenceAudio,
  type BackendCaller,
  type InputImageFile,
} from "@/backend"
import { Button } from "@/components/ui/button"
import { localMediaFileFromPath } from "@/shared/image-picker"
import { mediaAssetFromImageFile } from "@/shared/media"
import { ModalShell } from "@/shared/page-shell"

const MAX_SELECTION_SECONDS = 15
const DEFAULT_SELECTION_SECONDS = 10
const MIN_SELECTION_SECONDS = 2

function isAbortLikeError(error: unknown) {
  if (error instanceof DOMException && error.name === "AbortError") return true
  return (
    error instanceof Error &&
    (error.name === "AbortError" ||
      error.message.toLowerCase().includes("aborted"))
  )
}

async function cleanupReferenceAudioPaths(
  callBackend: BackendCaller,
  paths: Array<string | null | undefined>
) {
  const uniquePaths = Array.from(
    new Set(paths.filter((path): path is string => Boolean(path)))
  )
  if (!uniquePaths.length) return
  try {
    await cleanupReferenceAudio(callBackend, uniquePaths)
  } catch {
    // Cleanup is best-effort. The backend also removes stale preview files
    // during its periodic temporary-file cleanup.
  }
}

type CropRange = { start: number; end: number }

function scrollRangeIntoView(wave: WaveSurfer, start: number, end: number) {
  const scrollContainer = wave.getWrapper().parentElement
  const duration = wave.getDuration()
  if (!scrollContainer || duration <= 0) return

  const viewportWidth = scrollContainer.clientWidth
  const contentWidth = scrollContainer.scrollWidth
  if (viewportWidth <= 0 || contentWidth <= viewportWidth) return

  const startPx = (start / duration) * contentWidth
  const endPx = (end / duration) * contentWidth
  const visibleStart = scrollContainer.scrollLeft
  const visibleEnd = visibleStart + viewportWidth
  let nextScroll = visibleStart

  if (startPx < visibleStart) {
    nextScroll = startPx
  } else if (endPx > visibleEnd) {
    nextScroll = endPx - viewportWidth
  }

  const maxScroll = contentWidth - viewportWidth
  wave.setScroll(Math.max(0, Math.min(maxScroll, nextScroll)))
}

export function ReferenceAudioCropDialog({
  open,
  sourceFile,
  callBackend,
  title = "处理参考音频",
  onClose,
  onConfirm,
}: {
  open: boolean
  sourceFile: InputImageFile | null
  callBackend: BackendCaller
  title?: string
  onClose: () => void
  onConfirm: (file: InputImageFile) => void | Promise<void>
}) {
  const [preparedPath, setPreparedPath] = useState<string | null>(null)
  const [duration, setDuration] = useState(0)
  const [preparing, setPreparing] = useState(false)
  const [cropping, setCropping] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selection, setSelection] = useState<CropRange | null>(null)
  const [isReady, setIsReady] = useState(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [zoomLevel, setZoomLevel] = useState(60)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const waveRef = useRef<WaveSurfer | null>(null)
  const regionsRef = useRef<RegionsPlugin | null>(null)
  const regionRef = useRef<Region | null>(null)
  const regionRangeRef = useRef<CropRange | null>(null)
  const preparedPathRef = useRef<string | null>(null)
  const croppedPathRef = useRef<string | null>(null)

  useEffect(() => {
    const stalePaths = [preparedPathRef.current, croppedPathRef.current]
    preparedPathRef.current = null
    croppedPathRef.current = null
    void cleanupReferenceAudioPaths(callBackend, stalePaths)

    if (!open || !sourceFile) {
      setPreparedPath(null)
      setDuration(0)
      setSelection(null)
      regionRangeRef.current = null
      setIsReady(false)
      setError(null)
      return
    }
    let cancelled = false
    setPreparing(true)
    setPreparedPath(null)
    setDuration(0)
    setSelection(null)
    regionRangeRef.current = null
    setIsReady(false)
    setError(null)
    void prepareReferenceAudio(callBackend, mediaAssetFromImageFile(sourceFile))
      .then((result) => {
        if (cancelled) {
          void cleanupReferenceAudioPaths(callBackend, [result.processedPath])
          return
        }
        preparedPathRef.current = result.processedPath
        setPreparedPath(result.processedPath)
        setDuration(result.duration)
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "音频预处理失败")
        }
      })
      .finally(() => {
        if (!cancelled) setPreparing(false)
      })
    return () => {
      cancelled = true
      const paths = [preparedPathRef.current, croppedPathRef.current]
      preparedPathRef.current = null
      croppedPathRef.current = null
      void cleanupReferenceAudioPaths(callBackend, paths)
    }
  }, [callBackend, open, sourceFile])

  useEffect(() => {
    if (!open || !preparedPath || !containerRef.current) return
    const regions = RegionsPlugin.create()
    const zoom = ZoomPlugin.create({
      scale: 0.15,
      maxZoom: 1200,
      deltaThreshold: 1,
      exponentialZooming: false,
      iterations: 24,
    })
    const wave = WaveSurfer.create({
      container: containerRef.current,
      waveColor: "#94a3b8",
      progressColor: "#6366f1",
      cursorColor: "#4338ca",
      cursorWidth: 2,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      height: 84,
      interact: true,
      dragToSeek: true,
      autoCenter: false,
      minPxPerSec: 60,
      fillParent: true,
      normalize: true,
      hideScrollbar: false,
      plugins: [regions, zoom],
    })
    waveRef.current = wave
    regionsRef.current = regions
    regionRef.current = null
    setIsReady(false)
    setIsPlaying(false)
    setCurrentTime(0)
    setZoomLevel(60)
    const syncRegion = (region: Region | null) => {
      const nextRange = region ? { start: region.start, end: region.end } : null
      regionRangeRef.current = nextRange
      setSelection(nextRange)
    }
    const unsubscribers = [
      wave.on("ready", (nextDuration) => {
        setIsReady(true)
        setDuration(nextDuration)
      }),
      wave.on("play", () => setIsPlaying(true)),
      wave.on("pause", () => setIsPlaying(false)),
      wave.on("finish", () => setIsPlaying(false)),
      wave.on("timeupdate", (time) => setCurrentTime(time)),
      wave.on("zoom", (nextZoom) => setZoomLevel(nextZoom)),
      regions.on("region-created", (region) => {
        if (regionRef.current && regionRef.current.id !== region.id) {
          regionRef.current.remove()
        }
        regionRef.current = region
        syncRegion(region)
      }),
      regions.on("region-update", (region, side) => {
        if (!side) {
          const previous = regionRangeRef.current
          const duration = wave.getDuration()
          const previousLength = previous ? previous.end - previous.start : 0
          if (previousLength > 0 && duration > 0) {
            const maxStart = Math.max(0, duration - previousLength)
            const nextStart = Math.max(0, Math.min(maxStart, region.start))
            const nextEnd = nextStart + previousLength
            if (
              Math.abs(region.end - region.start - previousLength) > 0.001 ||
              Math.abs(region.start - nextStart) > 0.001
            ) {
              region.setOptions({ start: nextStart, end: nextEnd })
            }
          }
        }
        syncRegion(region)
      }),
      regions.on("region-updated", (region) => {
        regionRef.current = region
        syncRegion(region)
      }),
      regions.on("region-removed", (region) => {
        if (regionRef.current?.id === region.id) {
          regionRef.current = null
          syncRegion(null)
        }
      }),
      wave.on("error", (reason) => {
        if (isAbortLikeError(reason)) return
        setError(reason instanceof Error ? reason.message : "波形加载失败")
      }),
    ]
    void wave
      .load(`${convertFileSrc(preparedPath)}?t=${Date.now()}`)
      .catch((reason: unknown) => {
        if (isAbortLikeError(reason)) return
        setError(reason instanceof Error ? reason.message : "波形加载失败")
      })
    return () => {
      unsubscribers.forEach((unsubscribe) => unsubscribe())
      waveRef.current = null
      regionsRef.current = null
      regionRef.current = null
      wave.destroy()
    }
  }, [open, preparedPath])

  const toggleSelection = () => {
    const wave = waveRef.current
    const regions = regionsRef.current
    if (!wave || !regions || !isReady) return
    if (regionRef.current) {
      regionRef.current.remove()
      return
    }
    const total = wave.getDuration()
    if (!total) return
    const end = Math.min(total, DEFAULT_SELECTION_SECONDS)
    const region = regions.addRegion({
      start: 0,
      end,
      color: "rgba(99, 102, 241, 0.22)",
      drag: true,
      resize: true,
      minLength: Math.min(MIN_SELECTION_SECONDS, total),
      maxLength: Math.min(MAX_SELECTION_SECONDS, total),
    })
    regionRef.current = region
    const range = {
      start: region.start,
      end: region.end,
    }
    regionRangeRef.current = range
    window.requestAnimationFrame(() => {
      const currentRegion = regionRef.current
      if (currentRegion) {
        scrollRangeIntoView(wave, currentRegion.start, currentRegion.end)
      }
    })
  }

  const togglePlay = async () => {
    const wave = waveRef.current
    if (!wave || !isReady || cropping) return
    try {
      if (isPlaying) {
        wave.pause()
        return
      }
      if (regionRef.current) {
        await wave.play(regionRef.current.start, regionRef.current.end)
      } else {
        await wave.play()
      }
    } catch (reason) {
      if (!isAbortLikeError(reason)) {
        setError(reason instanceof Error ? reason.message : "音频播放失败")
      }
    }
  }

  const handleConfirm = async () => {
    if (!preparedPath || preparing || cropping) return
    setCropping(true)
    setError(null)
    let confirmed = false
    try {
      const result = await cropReferenceAudio(
        callBackend,
        preparedPath,
        selection
      )
      croppedPathRef.current = result.processedPath
      await onConfirm(localMediaFileFromPath(result.processedPath))
      confirmed = true
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "音频截取失败")
    } finally {
      const paths: Array<string | null> = [croppedPathRef.current]
      croppedPathRef.current = null
      if (confirmed) {
        paths.push(preparedPathRef.current)
        preparedPathRef.current = null
      }
      await cleanupReferenceAudioPaths(callBackend, paths)
      if (confirmed) {
        setPreparedPath(null)
        onClose()
      }
      setCropping(false)
    }
  }

  const handleClose = () => {
    if (cropping) return
    const paths = [preparedPathRef.current, croppedPathRef.current]
    preparedPathRef.current = null
    croppedPathRef.current = null
    setPreparedPath(null)
    void cleanupReferenceAudioPaths(callBackend, paths)
    onClose()
  }

  const selectedDuration = selection ? selection.end - selection.start : 0
  const fileName = sourceFile?.name || "参考音频"

  if (!open) return null
  return (
    <ModalShell
      title={title}
      description="先将音频统一转为 WAV 并准备最多 10 分钟预览。确认后才会保存到项目目录。"
      className="max-w-[820px]"
      bodyClassName="min-w-0"
      scrollClassName="ai-video-reference-audio-scroll-area"
      onClose={handleClose}
      footer={
        <>
          <Button
            type="button"
            variant="outline"
            onClick={handleClose}
            disabled={cropping}
          >
            取消
          </Button>
          <Button
            type="button"
            onClick={() => void handleConfirm()}
            disabled={
              !preparedPath ||
              !isReady ||
              preparing ||
              cropping ||
              (duration > 0 && duration < MIN_SELECTION_SECONDS)
            }
          >
            {cropping ? (
              <Loader2 className="mr-1.5 size-3.5 animate-spin" />
            ) : null}
            {cropping ? "截取并保存中" : "确认使用"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3 text-xs text-gray-500 dark:text-gray-400">
          <span className="min-w-0 truncate">{fileName}</span>
          <span className="shrink-0">{duration.toFixed(2)} 秒</span>
        </div>
        {preparing ? (
          <div className="flex h-36 items-center justify-center rounded-xl border border-dashed border-gray-300 bg-gray-50/70 text-xs text-gray-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-gray-400">
            <Loader2 className="mr-2 size-4 animate-spin text-indigo-500" />{" "}
            正在准备音频波形…
          </div>
        ) : (
          <div className="w-full max-w-full min-w-0 overflow-hidden rounded-xl border border-gray-200 bg-white/80 px-3 pt-3 pb-3 dark:border-white/10 dark:bg-white/[0.03]">
            <div ref={containerRef} className="w-full min-w-0" />
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-gray-500 dark:text-gray-400">
              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => void togglePlay()}
                  disabled={!isReady || cropping}
                >
                  {isPlaying ? (
                    <Pause className="size-3.5" />
                  ) : (
                    <Play className="size-3.5" />
                  )}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => {
                    waveRef.current?.stop()
                    setIsPlaying(false)
                  }}
                  disabled={!isReady || cropping}
                >
                  <Square className="size-3.5" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 gap-1 px-2 text-[11px]"
                  onClick={toggleSelection}
                  disabled={!isReady || cropping}
                >
                  <Scissors className="size-3.5" />
                  {selection ? "清除截取范围" : "调整截取范围"}
                </Button>
              </div>
              <span>
                缩放 {zoomLevel.toFixed(0)} · 当前 {currentTime.toFixed(2)} 秒
                {selection
                  ? ` · 已选 ${selectedDuration.toFixed(2)} 秒`
                  : " · 未手动选择，确认后自动寻找平滑停顿点"}
              </span>
            </div>
          </div>
        )}
        <p className="text-[11px] leading-relaxed text-gray-500 dark:text-gray-400">
          可拖动或调整蓝色范围，时长 2–15 秒。未手动调整时，后端会在 15
          秒上限附近寻找较安静的边界，并添加极短淡入淡出以避免硬切噪声。
        </p>
        {error ? (
          <p className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-600 dark:bg-rose-950/25 dark:text-rose-300">
            {error}
          </p>
        ) : null}
      </div>
    </ModalShell>
  )
}
