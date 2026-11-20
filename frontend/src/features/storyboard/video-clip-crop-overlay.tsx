import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent,
} from "react"
import { cn } from "@/lib/utils"
import { type VideoClipCropBox } from "./video-clip-model"

type VideoClipCropHandle =
  | "move"
  | "nw"
  | "n"
  | "ne"
  | "e"
  | "se"
  | "s"
  | "sw"
  | "w"

export function VideoClipCropOverlay({
  displayWidth,
  displayHeight,
  videoWidth,
  videoHeight,
  cropBox,
  disabled,
  onCropChange,
}: {
  displayWidth: number
  displayHeight: number
  videoWidth: number
  videoHeight: number
  cropBox: VideoClipCropBox
  disabled?: boolean
  onCropChange: (crop: VideoClipCropBox) => void
}) {
  const overlayRef = useRef<HTMLDivElement | null>(null)
  const [measuredDisplaySize, setMeasuredDisplaySize] = useState({
    width: 0,
    height: 0,
  })
  const dragRef = useRef<{
    handle: VideoClipCropHandle
    startX: number
    startY: number
    initialBox: VideoClipCropBox
  } | null>(null)
  const dragCleanupRef = useRef<(() => void) | null>(null)
  const effectiveDisplayWidth = Math.max(
    0,
    displayWidth || measuredDisplaySize.width
  )
  const effectiveDisplayHeight = Math.max(
    0,
    displayHeight || measuredDisplaySize.height
  )
  const safeDisplayWidth = Math.max(1, effectiveDisplayWidth)
  const safeDisplayHeight = Math.max(1, effectiveDisplayHeight)
  const safeVideoWidth = Math.max(1, videoWidth || safeDisplayWidth)
  const safeVideoHeight = Math.max(1, videoHeight || safeDisplayHeight)
  const safeCropBox =
    cropBox.width > 0 && cropBox.height > 0
      ? cropBox
      : { x: 0, y: 0, width: safeVideoWidth, height: safeVideoHeight }
  const scaleX = safeDisplayWidth / safeVideoWidth
  const scaleY = safeDisplayHeight / safeVideoHeight
  const displayBox = {
    x: safeCropBox.x * scaleX,
    y: safeCropBox.y * scaleY,
    width: safeCropBox.width * scaleX,
    height: safeCropBox.height * scaleY,
  }
  const clampDisplayBox = useCallback(
    (box: VideoClipCropBox) => {
      const minSize = 20
      let { x, y, width, height } = box
      width = Math.max(minSize, Math.min(width, safeDisplayWidth))
      height = Math.max(minSize, Math.min(height, safeDisplayHeight))
      x = Math.max(0, Math.min(x, safeDisplayWidth - width))
      y = Math.max(0, Math.min(y, safeDisplayHeight - height))
      return { x, y, width, height }
    },
    [safeDisplayHeight, safeDisplayWidth]
  )
  const toVideoCropBox = useCallback(
    (box: VideoClipCropBox) => {
      const next = {
        x: Math.round(box.x / scaleX),
        y: Math.round(box.y / scaleY),
        width: Math.round(box.width / scaleX),
        height: Math.round(box.height / scaleY),
      }
      next.x = Math.max(0, Math.min(next.x, safeVideoWidth - 1))
      next.y = Math.max(0, Math.min(next.y, safeVideoHeight - 1))
      next.width = Math.max(1, Math.min(next.width, safeVideoWidth - next.x))
      next.height = Math.max(1, Math.min(next.height, safeVideoHeight - next.y))
      return next
    },
    [safeVideoHeight, safeVideoWidth, scaleX, scaleY]
  )
  const beginCropDrag = useCallback(
    (event: MouseEvent<HTMLDivElement>, handle: VideoClipCropHandle) => {
      if (disabled) return
      event.preventDefault()
      event.stopPropagation()
      dragCleanupRef.current?.()
      dragRef.current = {
        handle,
        startX: event.clientX,
        startY: event.clientY,
        initialBox: displayBox,
      }
      const handleMove = (moveEvent: globalThis.MouseEvent) => {
        const drag = dragRef.current
        if (!drag) return
        const dx = moveEvent.clientX - drag.startX
        const dy = moveEvent.clientY - drag.startY
        const initial = drag.initialBox
        let next = { ...initial }
        if (drag.handle === "move") {
          next.x = initial.x + dx
          next.y = initial.y + dy
        } else {
          if (drag.handle.includes("w")) {
            next.x = initial.x + dx
            next.width = initial.width - dx
          }
          if (drag.handle.includes("e")) {
            next.width = initial.width + dx
          }
          if (drag.handle.includes("n")) {
            next.y = initial.y + dy
            next.height = initial.height - dy
          }
          if (drag.handle.includes("s")) {
            next.height = initial.height + dy
          }
        }
        onCropChange(toVideoCropBox(clampDisplayBox(next)))
      }
      const cleanup = () => {
        dragRef.current = null
        window.removeEventListener("mousemove", handleMove)
        window.removeEventListener("mouseup", handleEnd)
      }
      const handleEnd = () => {
        cleanup()
        dragCleanupRef.current = null
      }
      window.addEventListener("mousemove", handleMove)
      window.addEventListener("mouseup", handleEnd)
      dragCleanupRef.current = cleanup
    },
    [clampDisplayBox, disabled, displayBox, onCropChange, toVideoCropBox]
  )
  useEffect(() => {
    const element = overlayRef.current
    if (!element) return
    const updateSize = () => {
      setMeasuredDisplaySize({
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
    return () => {
      dragCleanupRef.current?.()
      dragCleanupRef.current = null
    }
  }, [])
  const handleClass =
    "absolute size-3 rounded-sm border-2 border-indigo-500 bg-white pointer-events-auto"
  return (
    <div
      ref={overlayRef}
      className="pointer-events-none absolute inset-0 z-[25]"
    >
      {effectiveDisplayWidth && effectiveDisplayHeight ? (
        <>
          <div
            className="absolute top-0 right-0 left-0 bg-black/50"
            style={{ height: displayBox.y }}
          />
          <div
            className="absolute left-0 bg-black/50"
            style={{
              top: displayBox.y,
              width: displayBox.x,
              height: displayBox.height,
            }}
          />
          <div
            className="absolute right-0 bg-black/50"
            style={{
              top: displayBox.y,
              left: displayBox.x + displayBox.width,
              height: displayBox.height,
            }}
          />
          <div
            className="absolute right-0 bottom-0 left-0 bg-black/50"
            style={{ top: displayBox.y + displayBox.height }}
          />
          <div
            className={cn(
              "absolute",
              disabled ? "" : "pointer-events-auto cursor-move"
            )}
            style={{
              left: displayBox.x,
              top: displayBox.y,
              width: displayBox.width,
              height: displayBox.height,
              boxShadow: "inset 0 0 0 2px rgba(99, 102, 241, 0.95)",
            }}
            onMouseDown={(event) => beginCropDrag(event, "move")}
          >
            <div className="pointer-events-none absolute inset-0">
              <div className="absolute top-0 bottom-0 left-1/3 w-px bg-white/55" />
              <div className="absolute top-0 bottom-0 left-2/3 w-px bg-white/55" />
              <div className="absolute top-1/3 right-0 left-0 h-px bg-white/55" />
              <div className="absolute top-2/3 right-0 left-0 h-px bg-white/55" />
            </div>
            {!disabled ? (
              <>
                <div
                  className={`${handleClass} top-0 left-0 cursor-nw-resize`}
                  onMouseDown={(event) => beginCropDrag(event, "nw")}
                />
                <div
                  className={`${handleClass} top-0 left-1/2 -translate-x-1/2 cursor-n-resize`}
                  onMouseDown={(event) => beginCropDrag(event, "n")}
                />
                <div
                  className={`${handleClass} top-0 right-0 cursor-ne-resize`}
                  onMouseDown={(event) => beginCropDrag(event, "ne")}
                />
                <div
                  className={`${handleClass} top-1/2 right-0 -translate-y-1/2 cursor-e-resize`}
                  onMouseDown={(event) => beginCropDrag(event, "e")}
                />
                <div
                  className={`${handleClass} right-0 bottom-0 cursor-se-resize`}
                  onMouseDown={(event) => beginCropDrag(event, "se")}
                />
                <div
                  className={`${handleClass} bottom-0 left-1/2 -translate-x-1/2 cursor-s-resize`}
                  onMouseDown={(event) => beginCropDrag(event, "s")}
                />
                <div
                  className={`${handleClass} bottom-0 left-0 cursor-sw-resize`}
                  onMouseDown={(event) => beginCropDrag(event, "sw")}
                />
                <div
                  className={`${handleClass} top-1/2 left-0 -translate-y-1/2 cursor-w-resize`}
                  onMouseDown={(event) => beginCropDrag(event, "w")}
                />
              </>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  )
}
