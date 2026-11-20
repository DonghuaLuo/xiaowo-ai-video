import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react"
import { toast } from "sonner"
import {
  extractVideoFramePreview,
  getVideoClipInfo,
  type VideoClipInfoResult,
} from "@/backend"
import type { useBackend } from "@/hooks/useBackend"
import { errMsg } from "@/shared/backend-result"
import { mediaPreviewSrc } from "@/shared/media"
import { resolveProjectMediaUrl } from "@/utils/style-thumbnails"
import {
  clampVideoClipFrameIndex,
  clipHmsToSeconds,
  clipSecondsToHms,
  isFullVideoClipCrop,
  type VideoClipCanvasResult,
  type VideoClipCropBox,
  type VideoClipDialogSource,
  type VideoClipEditingSource,
  videoClipFrameIndexFromTime,
  videoClipFrameIndexTitle,
  videoClipRootEditingSource,
  videoClipTimeFromFrameIndex,
  videoClipTimeRangeTitle,
} from "./video-clip-model"
import { useVideoClipActivation } from "./use-video-clip-activation"
export function useVideoClipEditor({
  backend,
  projectId,
  episodeId,
  source,
  loadClipResults,
}: { projectId: string; episodeId: string; source: VideoClipDialogSource } & {
  backend: Pick<ReturnType<typeof useBackend>, "backendReady" | "callBackend">
  loadClipResults: () => Promise<void>
}) {
  const { backendReady, callBackend } = backend
  const activation = useVideoClipActivation(projectId, episodeId, source)
  const rootIsCurrent = activation.isCurrent
  const videoRef = useRef<HTMLVideoElement | null>(null)

  const videoFrameRef = useRef<HTMLDivElement | null>(null)

  const previewRequestRef = useRef(0)

  const playTransitionTimerRef = useRef<number | null>(null)

  const rootInfoRef = useRef<VideoClipInfoResult | null>(null)

  const skipNextRootResultsLoadRef = useRef(false)

  const fastRestoreRootRef = useRef(false)

  const [editingSource, setEditingSource] = useState<VideoClipEditingSource>(
    () => videoClipRootEditingSource(source)
  )
  const editingSourceRef = useRef(editingSource)
  editingSourceRef.current = editingSource
  const isCurrent = useCallback(
    () => rootIsCurrent() && editingSourceRef.current === editingSource,
    [rootIsCurrent, editingSource]
  )

  const [info, setInfo] = useState<VideoClipInfoResult | null>(null)

  const [loadingInfo, setLoadingInfo] = useState(false)

  const [currentTime, setCurrentTime] = useState(0)

  const [currentFrameIndex, setCurrentFrameIndex] = useState(0)

  const [frameStep, setFrameStep] = useState(1)

  const [rangeStart, setRangeStart] = useState(0)

  const [rangeEnd, setRangeEnd] = useState(0)

  const [cropBox, setCropBox] = useState<VideoClipCropBox>({
    x: 0,
    y: 0,
    width: 0,
    height: 0,
  })

  const [browserVideoSize, setBrowserVideoSize] = useState({
    width: 0,
    height: 0,
  })

  const [videoFrameSize, setVideoFrameSize] = useState({ width: 0, height: 0 })

  const [previewSrc, setPreviewSrc] = useState<string | null>(null)

  const [mainVideoPreviewSignal, setMainVideoPreviewSignal] = useState(0)

  const [previewLoading, setPreviewLoading] = useState(false)

  const [framePreviewVisible, setFramePreviewVisible] = useState(false)

  const [playing, setPlaying] = useState(false)

  const [playTransitioning, setPlayTransitioning] = useState(false)

  const [volume, setVolume] = useState(1)

  const [isMuted, setIsMuted] = useState(false)

  const [cropEnabled, setCropEnabled] = useState(false)

  const duration = Math.max(0, Number(info?.duration ?? 0))

  const fps = Math.max(0, Number(info?.fps ?? 0))

  const frameCount = Math.max(0, Math.floor(Number(info?.frameCount ?? 0)))

  const lastFrameIndex = Math.max(
    0,
    Math.floor(
      Number(info?.lastFrameIndex ?? (frameCount > 0 ? frameCount - 1 : 0))
    )
  )

  const frameTotal = frameCount > 0 ? frameCount : lastFrameIndex + 1

  const safeCurrentFrameIndex = clampVideoClipFrameIndex(
    currentFrameIndex,
    frameTotal
  )

  const frameStepValue = Math.max(1, Math.floor(Number(frameStep) || 1))

  const frameControlsDisabled = !duration || loadingInfo || frameTotal <= 0

  const selectedDuration = Math.max(0, rangeEnd - rangeStart)

  const sourceVideoWidth = Math.max(
    0,
    browserVideoSize.width || Number(info?.width ?? 0)
  )

  const sourceVideoHeight = Math.max(
    0,
    browserVideoSize.height || Number(info?.height ?? 0)
  )

  const videoFrameStyle = useMemo<CSSProperties>(() => {
    const viewportHeight =
      typeof window !== "undefined" ? window.innerHeight : 860
    const maxHeight = Math.min(540, Math.max(280, viewportHeight * 0.5))
    if (!sourceVideoWidth || !sourceVideoHeight) {
      return {}
    }
    const ratio = sourceVideoWidth / sourceVideoHeight
    return {
      aspectRatio: `${sourceVideoWidth} / ${sourceVideoHeight}`,
      width: `min(100%, ${Math.max(1, Math.round(maxHeight * ratio))}px)`,
      maxHeight,
    }
  }, [sourceVideoHeight, sourceVideoWidth])

  const hasSourceVideoSize = sourceVideoWidth > 0 && sourceVideoHeight > 0

  const cropDisplayWidth = videoFrameSize.width

  const cropDisplayHeight = videoFrameSize.height

  const cropIsFullFrame = isFullVideoClipCrop(
    cropBox,
    sourceVideoWidth,
    sourceVideoHeight
  )

  const startHms = clipSecondsToHms(rangeStart)

  const endHms = clipSecondsToHms(rangeEnd)

  const editingSourceIsRoot = !editingSource.resultId

  const clearPlayTransitionTimer = useCallback(() => {
    if (playTransitionTimerRef.current === null) return
    window.clearTimeout(playTransitionTimerRef.current)
    playTransitionTimerRef.current = null
  }, [])

  const finishPlayTransition = useCallback(() => {
    clearPlayTransitionTimer()
    if (!isCurrent()) return
    const video = videoRef.current as
      | (HTMLVideoElement & {
          requestVideoFrameCallback?: (callback: () => void) => number
        })
      | null
    if (video?.requestVideoFrameCallback) {
      video.requestVideoFrameCallback(() => {
        if (!isCurrent()) return
        setPlayTransitioning(false)
        setFramePreviewVisible(false)
      })
      return
    }
    playTransitionTimerRef.current = window.setTimeout(() => {
      if (!isCurrent()) return
      playTransitionTimerRef.current = null
      setPlayTransitioning(false)
      setFramePreviewVisible(false)
    }, 80)
  }, [clearPlayTransitionTimer, isCurrent])

  useEffect(() => {
    const element = videoFrameRef.current
    if (!element) return
    const updateSize = () => {
      setVideoFrameSize({
        width: element.clientWidth,
        height: element.clientHeight,
      })
    }
    updateSize()
    const observer =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(updateSize)
        : null
    observer?.observe(element)
    window.addEventListener("resize", updateSize)
    return () => {
      observer?.disconnect()
      window.removeEventListener("resize", updateSize)
    }
  }, [])

  useEffect(() => {
    rootInfoRef.current = null
    fastRestoreRootRef.current = false
    skipNextRootResultsLoadRef.current = false
    setEditingSource(videoClipRootEditingSource(source))
    setCropEnabled(false)
    setFramePreviewVisible(false)
  }, [
    projectId,
    episodeId,
    source.media.filePath,
    source.media.id,
    source.media.path,
    source.media.relativePath,
    source.media.relative_path,
    source.nodeId,
    source.src,
    source.title,
  ])

  useEffect(() => {
    let cancelled = false
    const cachedRootInfo =
      !editingSource.resultId && fastRestoreRootRef.current
        ? rootInfoRef.current
        : null
    if (cachedRootInfo) {
      fastRestoreRootRef.current = false
      skipNextRootResultsLoadRef.current = false
      const nextDuration = Math.max(0, Number(cachedRootInfo.duration || 0))
      setInfo(cachedRootInfo)
      setBrowserVideoSize({ width: 0, height: 0 })
      setPreviewSrc(null)
      setFramePreviewVisible(false)
      setCurrentTime(0)
      setCurrentFrameIndex(0)
      setRangeStart(0)
      setRangeEnd(nextDuration)
      setCropBox({
        x: 0,
        y: 0,
        width: Math.max(0, Number(cachedRootInfo.width || 0)),
        height: Math.max(0, Number(cachedRootInfo.height || 0)),
      })
      setPlaying(false)
      setPlayTransitioning(false)
      clearPlayTransitionTimer()
      setLoadingInfo(false)
      return () => {
        cancelled = true
      }
    }
    fastRestoreRootRef.current = false
    setInfo(null)
    setBrowserVideoSize({ width: 0, height: 0 })
    setPreviewSrc(null)
    setFramePreviewVisible(false)
    setCurrentTime(0)
    setCurrentFrameIndex(0)
    setRangeStart(0)
    setRangeEnd(0)
    setCropBox({ x: 0, y: 0, width: 0, height: 0 })
    setPlaying(false)
    setPlayTransitioning(false)
    clearPlayTransitionTimer()
    setLoadingInfo(true)
    if (!backendReady) {
      setLoadingInfo(false)
      return () => {
        cancelled = true
      }
    }
    void getVideoClipInfo(callBackend, projectId, episodeId, {
      media: editingSource.media,
    })
      .then((result) => {
        if (cancelled || !isCurrent()) return
        const nextDuration = Math.max(0, Number(result.duration || 0))
        setInfo(result)
        setCurrentTime(0)
        setCurrentFrameIndex(0)
        setRangeStart(0)
        setRangeEnd(nextDuration)
        setCropBox({
          x: 0,
          y: 0,
          width: Math.max(0, Number(result.width || 0)),
          height: Math.max(0, Number(result.height || 0)),
        })
        if (!editingSource.resultId) {
          rootInfoRef.current = result
          if (skipNextRootResultsLoadRef.current) {
            skipNextRootResultsLoadRef.current = false
          } else {
            void loadClipResults()
          }
        }
      })
      .catch((error) => {
        if (!cancelled && isCurrent())
          toast.error(errMsg(error, "读取视频信息失败"))
      })
      .finally(() => {
        if (!cancelled && isCurrent()) setLoadingInfo(false)
      })
    return () => {
      cancelled = true
    }
  }, [
    backendReady,
    callBackend,
    editingSource.media,
    editingSource.resultId,
    episodeId,
    loadClipResults,
    projectId,
    clearPlayTransitionTimer,
    isCurrent,
  ])

  useEffect(() => {
    if (!cropEnabled || !sourceVideoWidth || !sourceVideoHeight) return
    setCropBox((current) => {
      const matchesDisplayFallback =
        videoFrameSize.width > 0 &&
        videoFrameSize.height > 0 &&
        current.x <= 0 &&
        current.y <= 0 &&
        Math.abs(current.width - videoFrameSize.width) <= 1 &&
        Math.abs(current.height - videoFrameSize.height) <= 1
      const outOfBounds =
        current.width <= 0 ||
        current.height <= 0 ||
        current.x < 0 ||
        current.y < 0 ||
        current.x + current.width > sourceVideoWidth ||
        current.y + current.height > sourceVideoHeight
      if (!outOfBounds && !matchesDisplayFallback) return current
      return {
        x: 0,
        y: 0,
        width: sourceVideoWidth,
        height: sourceVideoHeight,
      }
    })
  }, [
    cropEnabled,
    sourceVideoHeight,
    sourceVideoWidth,
    videoFrameSize.height,
    videoFrameSize.width,
  ])

  useEffect(
    () => () => {
      clearPlayTransitionTimer()
    },
    [clearPlayTransitionTimer]
  )

  useEffect(() => {
    if (!backendReady || !duration || playing || !framePreviewVisible) return
    const requestId = previewRequestRef.current + 1
    previewRequestRef.current = requestId
    setPreviewLoading(true)
    const timer = window.setTimeout(() => {
      void extractVideoFramePreview(callBackend, projectId, episodeId, {
        media: editingSource.media,
        time: currentTime,
        frameIndex: safeCurrentFrameIndex,
      })
        .then(async (result) => {
          if (!isCurrent() || previewRequestRef.current !== requestId) return
          const src =
            (await resolveProjectMediaUrl(projectId, result.media)) ||
            mediaPreviewSrc(result.media)
          if (!isCurrent() || previewRequestRef.current !== requestId) return
          setPreviewSrc(src)
        })
        .catch((error) => {
          if (isCurrent() && previewRequestRef.current === requestId) {
            console.warn("视频帧预览失败:", error)
            setPreviewSrc(null)
          }
        })
        .finally(() => {
          if (isCurrent() && previewRequestRef.current === requestId)
            setPreviewLoading(false)
        })
    }, 45)
    return () => {
      window.clearTimeout(timer)
      if (isCurrent() && previewRequestRef.current === requestId) {
        previewRequestRef.current += 1
      }
    }
  }, [
    backendReady,
    callBackend,
    currentTime,
    duration,
    episodeId,
    editingSource.media,
    framePreviewVisible,
    playing,
    projectId,
    safeCurrentFrameIndex,
    isCurrent,
  ])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const nextMuted = isMuted || volume <= 0
    video.muted = nextMuted
    video.volume = nextMuted ? 0 : Math.max(0, Math.min(volume, 1))
  }, [editingSource.id, isMuted, volume])

  const handleCurrentTimeChange = (value: number) => {
    const next = Math.max(0, Math.min(value, duration || value))
    setPreviewSrc(null)
    setFramePreviewVisible(true)
    setCurrentTime(next)
    setCurrentFrameIndex(
      videoClipFrameIndexFromTime(next, fps, frameTotal, duration)
    )
    setPlayTransitioning(false)
    clearPlayTransitionTimer()
    const video = videoRef.current
    if (video) video.currentTime = next
  }

  const handleFrameIndexChange = (frameIndex: number) => {
    const nextFrameIndex = clampVideoClipFrameIndex(frameIndex, frameTotal)
    const nextTime = Math.min(
      duration || Number.MAX_SAFE_INTEGER,
      videoClipTimeFromFrameIndex(nextFrameIndex, fps, duration, frameTotal)
    )
    setPreviewSrc(null)
    setFramePreviewVisible(true)
    setCurrentFrameIndex(nextFrameIndex)
    setCurrentTime(nextTime)
    setPlayTransitioning(false)
    clearPlayTransitionTimer()
    const video = videoRef.current
    if (video) video.currentTime = nextTime
  }

  const handlePreviousFrame = () =>
    handleFrameIndexChange(safeCurrentFrameIndex - frameStepValue)

  const handleNextFrame = () =>
    handleFrameIndexChange(safeCurrentFrameIndex + frameStepValue)

  const handleJumpToTailFrame = () => handleFrameIndexChange(lastFrameIndex)

  const handleRangeChange = (start: number, end: number, focusTime: number) => {
    setRangeStart(Math.max(0, Math.min(start, duration)))
    setRangeEnd(Math.max(0, Math.min(end, duration)))
    handleCurrentTimeChange(focusTime)
  }

  const handleTimeInputChange =
    (
      target: "start" | "end",
      field: "hours" | "minutes" | "seconds",
      maxValue: number
    ) =>
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const value = Math.min(
        maxValue,
        Math.max(
          0,
          Math.floor(Number(event.target.value.replace(/\D/g, "")) || 0)
        )
      )
      const base = target === "start" ? startHms : endHms
      const nextTime = clipHmsToSeconds(
        field === "hours" ? value : base.hours,
        field === "minutes" ? value : base.minutes,
        field === "seconds" ? value : base.seconds
      )
      if (target === "start") {
        const nextStart = Math.max(
          0,
          Math.min(nextTime, Math.max(0, rangeEnd - 0.04))
        )
        handleRangeChange(nextStart, rangeEnd, nextStart)
        return
      }
      const nextEnd = Math.min(duration, Math.max(nextTime, rangeStart + 0.04))
      handleRangeChange(rangeStart, nextEnd, nextEnd)
    }

  const resetTimeRange = () => {
    setRangeStart(0)
    setRangeEnd(duration)
    handleCurrentTimeChange(0)
  }

  const resetCropBox = () => {
    const nextWidth = sourceVideoWidth || cropDisplayWidth
    const nextHeight = sourceVideoHeight || cropDisplayHeight
    if (!nextWidth || !nextHeight) return
    setCropBox({
      x: 0,
      y: 0,
      width: nextWidth,
      height: nextHeight,
    })
  }

  const handleCropEnabledChange = (checked: boolean) => {
    if (!duration) return
    setCropEnabled(checked)
    if (checked) {
      resetCropBox()
    }
  }

  const handleRestoreMainVideo = () => {
    const video = videoRef.current
    if (video) video.pause()
    setPlaying(false)
    setPlayTransitioning(false)
    clearPlayTransitionTimer()
    setPreviewSrc(null)
    setPreviewLoading(false)
    setFramePreviewVisible(false)
    previewRequestRef.current += 1
    skipNextRootResultsLoadRef.current = true
    fastRestoreRootRef.current = true
    setEditingSource(videoClipRootEditingSource(source))
    setCropEnabled(false)
  }

  const handleVolumeChange = (value: number[]) => {
    const nextVolume = Math.max(0, Math.min(value[0] ?? 0, 1))
    setVolume(nextVolume)
    if (videoRef.current) {
      videoRef.current.volume = nextVolume
      videoRef.current.muted = nextVolume <= 0
    }
    setIsMuted(nextVolume <= 0)
  }

  const toggleMute = () => {
    const nextMuted = !isMuted
    setIsMuted(nextMuted)
    if (videoRef.current) {
      videoRef.current.muted = nextMuted
      videoRef.current.volume = nextMuted ? 0 : volume
    }
  }

  const handlePlayToggle = () => {
    const video = videoRef.current
    if (!video) {
      setPlaying(true)
      return
    }
    if (playing) {
      video.pause()
      setPlaying(false)
      setPlayTransitioning(false)
      setFramePreviewVisible(false)
      setPreviewLoading(false)
      previewRequestRef.current += 1
      clearPlayTransitionTimer()
      return
    }
    const nextTime =
      currentTime < rangeStart || currentTime >= rangeEnd
        ? rangeStart
        : currentTime
    const nextMuted = isMuted || volume <= 0
    video.muted = nextMuted
    video.volume = nextMuted ? 0 : Math.max(0, Math.min(volume, 1))
    video.currentTime = nextTime
    setCurrentTime(nextTime)
    setCurrentFrameIndex(
      videoClipFrameIndexFromTime(nextTime, fps, frameTotal, duration)
    )
    setPreviewLoading(false)
    previewRequestRef.current += 1
    setPlayTransitioning(Boolean(framePreviewVisible && previewSrc))
    setPlaying(true)
    void video
      .play()
      .then(finishPlayTransition)
      .catch(() => {
        if (!isCurrent()) return
        setPlaying(false)
        setPlayTransitioning(false)
        setFramePreviewVisible(false)
        clearPlayTransitionTimer()
      })
  }

  const handleVideoLoadedMetadata = (
    event: React.SyntheticEvent<HTMLVideoElement>
  ) => {
    const nextMuted = isMuted || volume <= 0
    event.currentTarget.muted = nextMuted
    event.currentTarget.volume = nextMuted ? 0 : volume
    const naturalWidth = Math.max(0, event.currentTarget.videoWidth || 0)
    const naturalHeight = Math.max(0, event.currentTarget.videoHeight || 0)
    if (naturalWidth > 0 && naturalHeight > 0) {
      setBrowserVideoSize({
        width: naturalWidth,
        height: naturalHeight,
      })
      setInfo((current) => {
        if (
          !current ||
          (Number(current.width || 0) === naturalWidth &&
            Number(current.height || 0) === naturalHeight)
        ) {
          return current
        }
        const next = {
          ...current,
          width: naturalWidth,
          height: naturalHeight,
        }
        if (!editingSource.resultId) rootInfoRef.current = next
        return next
      })
      setCropBox((current) => {
        const currentWasFull = isFullVideoClipCrop(
          current,
          sourceVideoWidth,
          sourceVideoHeight
        )
        const outOfBounds =
          current.width <= 0 ||
          current.height <= 0 ||
          current.x < 0 ||
          current.y < 0 ||
          current.x + current.width > naturalWidth ||
          current.y + current.height > naturalHeight
        if (!currentWasFull && !outOfBounds) return current
        return {
          x: 0,
          y: 0,
          width: naturalWidth,
          height: naturalHeight,
        }
      })
    }
  }

  const handleVideoCanPlay = () => {
    if (playing) finishPlayTransition()
  }

  const handleVideoPause = () => {
    setPlaying(false)
    setPlayTransitioning(false)
    setFramePreviewVisible(false)
    setPreviewLoading(false)
    previewRequestRef.current += 1
    clearPlayTransitionTimer()
  }

  const handleVideoEnded = () => {
    setPlaying(false)
    setPlayTransitioning(false)
    setFramePreviewVisible(false)
    setPreviewLoading(false)
    previewRequestRef.current += 1
    clearPlayTransitionTimer()
  }

  const handleVideoTimeUpdate = (
    event: React.SyntheticEvent<HTMLVideoElement>
  ) => {
    const next = event.currentTarget.currentTime
    setCurrentTime(next)
    setCurrentFrameIndex(
      videoClipFrameIndexFromTime(next, fps, frameTotal, duration)
    )
    if (rangeEnd > 0 && next >= rangeEnd) {
      event.currentTarget.pause()
      event.currentTarget.currentTime = rangeEnd
      setCurrentTime(rangeEnd)
      setCurrentFrameIndex(
        videoClipFrameIndexFromTime(rangeEnd, fps, frameTotal, duration)
      )
      setPlaying(false)
      setPlayTransitioning(false)
      setFramePreviewVisible(false)
      setPreviewLoading(false)
      previewRequestRef.current += 1
      clearPlayTransitionTimer()
    }
  }
  const editResult = (result: VideoClipCanvasResult) => {
    const video = videoRef.current
    if (video) video.pause()
    setPlaying(false)
    setPlayTransitioning(false)
    clearPlayTransitionTimer()
    setPreviewSrc(null)
    setPreviewLoading(false)
    setFramePreviewVisible(false)
    previewRequestRef.current += 1
    setEditingSource({
      id: `result:${result.id}`,
      title: result.title,
      media: result.media,
      src: result.src,
      resultId: result.id,
    })
  }

  const createTrimRequest = () => {
    if (selectedDuration <= 0) {
      toast.info("请先选择有效的剪切范围")
      return null
    }
    const crop =
      sourceVideoWidth <= 0 ||
      sourceVideoHeight <= 0 ||
      cropBox.width <= 0 ||
      cropBox.height <= 0 ||
      !cropEnabled ||
      cropIsFullFrame
        ? undefined
        : {
            x: cropBox.x,
            y: cropBox.y,
            width: cropBox.width,
            height: cropBox.height,
          }
    const title = videoClipTimeRangeTitle(rangeStart, rangeEnd, Boolean(crop))
    return {
      media: source.media,
      ...(!editingSourceIsRoot ? { inputMedia: editingSource.media } : {}),
      start: rangeStart,
      end: rangeEnd,
      title,
      ...(crop ? { crop } : {}),
    }
  }
  const createFrameRequest = (frameIndex = safeCurrentFrameIndex) => {
    const safeFrameIndex = clampVideoClipFrameIndex(frameIndex, frameTotal)
    const safeTime = Math.min(
      duration || Number.MAX_SAFE_INTEGER,
      videoClipTimeFromFrameIndex(safeFrameIndex, fps, duration, frameTotal)
    )
    return {
      media: source.media,
      ...(!editingSourceIsRoot ? { inputMedia: editingSource.media } : {}),
      time: safeTime,
      ...(editingSourceIsRoot && safeFrameIndex === frameTotal - 1
        ? { tailFrame: true }
        : { frameIndex: safeFrameIndex }),
      title: videoClipFrameIndexTitle(safeFrameIndex, safeTime),
    }
  }

  return {
    createTrimRequest,
    createFrameRequest,
    editResult,
    handleRestoreMainVideo,
    editingSource,
    hasSourceVideoSize,
    videoFrameRef,
    videoFrameStyle,
    videoRef,
    playing,
    framePreviewVisible,
    previewSrc,
    isMuted,
    handleVideoLoadedMetadata,
    handleVideoCanPlay,
    finishPlayTransition,
    handleVideoPause,
    handleVideoEnded,
    handleVideoTimeUpdate,
    playTransitioning,
    cropEnabled,
    cropDisplayWidth,
    cropDisplayHeight,
    sourceVideoWidth,
    sourceVideoHeight,
    cropBox,
    duration,
    loadingInfo,
    setCropBox,
    setMainVideoPreviewSignal,
    handlePlayToggle,
    previewLoading,
    startHms,
    handleTimeInputChange,
    endHms,
    resetTimeRange,
    selectedDuration,
    handleCropEnabledChange,
    resetCropBox,
    fps,
    currentTime,
    rangeStart,
    rangeEnd,
    handleCurrentTimeChange,
    handleRangeChange,
    toggleMute,
    volume,
    handleVolumeChange,
    editingSourceIsRoot,
    frameTotal,
    safeCurrentFrameIndex,
    frameControlsDisabled,
    handlePreviousFrame,
    frameStep,
    setFrameStep,
    lastFrameIndex,
    handleNextFrame,
    handleJumpToTailFrame,
    mainVideoPreviewSignal,
  }
}
export type VideoClipEditor = ReturnType<typeof useVideoClipEditor>
