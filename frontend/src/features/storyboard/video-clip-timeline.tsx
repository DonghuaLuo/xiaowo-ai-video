import { useCallback, useRef } from "react"
import { cn } from "@/lib/utils"
import { formatClipTime } from "./video-clip-model"

type VideoClipTimelineDragMode = "seek" | "start" | "end" | "range"

export function VideoClipRangeTimeline({
  duration,
  fps,
  currentTime,
  rangeStart,
  rangeEnd,
  disabled,
  onSeek,
  onRangeChange,
}: {
  duration: number
  fps?: number
  currentTime: number
  rangeStart: number
  rangeEnd: number
  disabled?: boolean
  onSeek: (time: number) => void
  onRangeChange: (start: number, end: number, focusTime: number) => void
}) {
  const trackRef = useRef<HTMLDivElement | null>(null)
  const dragRef = useRef<{
    mode: VideoClipTimelineDragMode
    pointerId: number
    startX: number
    initialStart: number
    initialEnd: number
    moved: boolean
  } | null>(null)
  const minGap = Math.max(0.04, fps && fps > 0 ? 1 / fps : 0.04)
  const safeDuration = Math.max(0, duration)
  const startPercent = safeDuration ? (rangeStart / safeDuration) * 100 : 0
  const endPercent = safeDuration ? (rangeEnd / safeDuration) * 100 : 0
  const playPercent = safeDuration ? (currentTime / safeDuration) * 100 : 0

  const timeFromClientX = useCallback(
    (clientX: number) => {
      const rect = trackRef.current?.getBoundingClientRect()
      if (!rect || !safeDuration) return 0
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
      return ratio * safeDuration
    },
    [safeDuration]
  )

  const applyDrag = useCallback(
    (clientX: number) => {
      const drag = dragRef.current
      if (!drag || !trackRef.current || !safeDuration) return
      const rect = trackRef.current.getBoundingClientRect()
      const delta =
        ((clientX - drag.startX) / Math.max(1, rect.width)) * safeDuration
      if (Math.abs(clientX - drag.startX) >= 3) {
        drag.moved = true
      }
      if (drag.mode === "seek") {
        onSeek(timeFromClientX(clientX))
        return
      }
      if (drag.mode === "start") {
        const nextStart = Math.max(
          0,
          Math.min(drag.initialStart + delta, drag.initialEnd - minGap)
        )
        onRangeChange(nextStart, drag.initialEnd, nextStart)
        return
      }
      if (drag.mode === "end") {
        const nextEnd = Math.min(
          safeDuration,
          Math.max(drag.initialEnd + delta, drag.initialStart + minGap)
        )
        onRangeChange(drag.initialStart, nextEnd, nextEnd)
        return
      }
      const width = Math.max(minGap, drag.initialEnd - drag.initialStart)
      const nextStart = Math.max(
        0,
        Math.min(drag.initialStart + delta, safeDuration - width)
      )
      const nextEnd = nextStart + width
      const focusTime = Math.max(
        nextStart,
        Math.min(nextEnd, timeFromClientX(clientX))
      )
      onRangeChange(nextStart, nextEnd, focusTime)
    },
    [minGap, onRangeChange, onSeek, safeDuration, timeFromClientX]
  )

  const beginDrag = useCallback(
    (
      event: React.PointerEvent<HTMLDivElement>,
      mode: VideoClipTimelineDragMode
    ) => {
      if (disabled || !safeDuration || event.button !== 0) return
      event.preventDefault()
      event.stopPropagation()
      dragRef.current = {
        mode,
        pointerId: event.pointerId,
        startX: event.clientX,
        initialStart: rangeStart,
        initialEnd: rangeEnd,
        moved: false,
      }
      if (mode === "range") {
        onSeek(timeFromClientX(event.clientX))
      } else if (mode === "seek") {
        applyDrag(event.clientX)
      }
      const handleMove = (pointerEvent: PointerEvent) => {
        if (dragRef.current?.pointerId !== pointerEvent.pointerId) return
        pointerEvent.preventDefault()
        applyDrag(pointerEvent.clientX)
      }
      const handleEnd = (pointerEvent: PointerEvent) => {
        const drag = dragRef.current
        if (drag?.pointerId !== pointerEvent.pointerId) return
        if (drag.mode !== "seek" && !drag.moved) {
          pointerEvent.preventDefault()
          onSeek(timeFromClientX(pointerEvent.clientX))
        }
        dragRef.current = null
        window.removeEventListener("pointermove", handleMove)
        window.removeEventListener("pointerup", handleEnd)
        window.removeEventListener("pointercancel", handleEnd)
      }
      window.addEventListener("pointermove", handleMove, { passive: false })
      window.addEventListener("pointerup", handleEnd, { passive: false })
      window.addEventListener("pointercancel", handleEnd, { passive: false })
    },
    [
      applyDrag,
      disabled,
      onSeek,
      rangeEnd,
      rangeStart,
      safeDuration,
      timeFromClientX,
    ]
  )

  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
        <span>{formatClipTime(currentTime)}</span>
        <span>{formatClipTime(duration)}</span>
      </div>
      <div
        ref={trackRef}
        className={cn(
          "relative h-12 overflow-hidden border border-gray-200 bg-white shadow-inner select-none dark:border-white/10 dark:bg-gray-950",
          disabled ? "opacity-60" : "cursor-crosshair"
        )}
        onPointerDown={(event) => beginDrag(event, "seek")}
      >
        <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(17,24,39,0.12)_1px,transparent_1px)] bg-[length:24px_100%] opacity-60 dark:bg-[linear-gradient(90deg,rgba(255,255,255,0.14)_1px,transparent_1px)] dark:opacity-50" />
        <div
          className="absolute top-0 bottom-0 bg-indigo-400/25 ring-1 ring-indigo-300/70 ring-inset"
          style={{
            left: `${startPercent}%`,
            width: `${Math.max(0, endPercent - startPercent)}%`,
          }}
          onPointerDown={(event) => beginDrag(event, "range")}
        >
          <div className="pointer-events-none absolute inset-0 grid grid-cols-3">
            <span className="border-r border-white/25" />
            <span className="border-r border-white/25" />
            <span />
          </div>
        </div>
        <div
          className="absolute top-0 bottom-0 z-10 w-1 -translate-x-1/2 cursor-ew-resize bg-white shadow-[0_0_0_1px_rgba(79,70,229,0.85)]"
          style={{ left: `${startPercent}%` }}
          onPointerDown={(event) => beginDrag(event, "start")}
        >
          <span className="absolute top-1/2 left-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow" />
        </div>
        <div
          className="absolute top-0 bottom-0 z-10 w-1 -translate-x-1/2 cursor-ew-resize bg-white shadow-[0_0_0_1px_rgba(79,70,229,0.85)]"
          style={{ left: `${endPercent}%` }}
          onPointerDown={(event) => beginDrag(event, "end")}
        >
          <span className="absolute top-1/2 left-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow" />
        </div>
        <div
          className="absolute top-0 bottom-0 z-20 w-px bg-rose-400"
          style={{ left: `${playPercent}%` }}
        />
      </div>
      <div className="flex items-center justify-between text-[11px] text-gray-500 dark:text-gray-400">
        <span>{formatClipTime(rangeStart)}</span>
        <span>
          剪切时长 {formatClipTime(Math.max(0, rangeEnd - rangeStart))}
        </span>
        <span>{formatClipTime(rangeEnd)}</span>
      </div>
    </div>
  )
}
