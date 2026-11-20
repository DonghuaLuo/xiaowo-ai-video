import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { type VideoClipCanvasResult } from "./video-clip-model"
import type { VideoClipResults } from "./use-video-clip-results"
export function useVideoClipResultDrag({
  activation,
  resultSelectionMode,
  deletingResults,
  selectedResultIdSet,
  toggleResultSelected,
  onEditResult,
  onDropToCanvas,
}: Pick<
  VideoClipResults,
  | "resultSelectionMode"
  | "deletingResults"
  | "selectedResultIdSet"
  | "toggleResultSelected"
> & {
  activation: unknown
  onEditResult: (result: VideoClipCanvasResult) => void
  onDropToCanvas: (
    result: VideoClipCanvasResult,
    position: { x: number; y: number }
  ) => Promise<void> | void
}) {
  const scopeRef = useRef({ activation, active: true })
  if (scopeRef.current.activation !== activation) {
    scopeRef.current.active = false
    scopeRef.current = { activation, active: true }
  }
  const scope = scopeRef.current
  const isCurrent = () => scopeRef.current === scope && scope.active
  const resultDragRef = useRef<{
    result: VideoClipCanvasResult
    pointerId: number
    startX: number
    startY: number
    x: number
    y: number
    active: boolean
  } | null>(null)

  const resultDragCleanupRef = useRef<(() => void) | null>(null)

  const resultDragSuppressClickUntilRef = useRef(0)

  const [resultDragPreview, setResultDragPreview] = useState<{
    x: number
    y: number
    result: VideoClipCanvasResult
  } | null>(null)

  useEffect(() => {
    scope.active = true
    return () => {
      scope.active = false
      resultDragCleanupRef.current?.()
      resultDragCleanupRef.current = null
      resultDragRef.current = null
    }
  }, [scope])

  const isResultControlTarget = (target: EventTarget | null) =>
    target instanceof Element &&
    Boolean(target.closest("[data-video-clip-result-control]"))

  const isScreenPointInsideDialog = (x: number, y: number) => {
    const rect = document
      .querySelector<HTMLElement>("[data-video-clip-dialog='true']")
      ?.getBoundingClientRect()
    return Boolean(
      rect &&
      x >= rect.left &&
      x <= rect.right &&
      y >= rect.top &&
      y <= rect.bottom
    )
  }

  const isScreenPointInsideFlow = (x: number, y: number) => {
    const flowElement = document.querySelector<HTMLElement>(".react-flow")
    const rect = flowElement?.getBoundingClientRect()
    return Boolean(
      rect &&
      x >= rect.left &&
      x <= rect.right &&
      y >= rect.top &&
      y <= rect.bottom
    )
  }

  const handleResultPointerDown = (
    event: React.PointerEvent<HTMLDivElement>,
    result: VideoClipCanvasResult
  ) => {
    if (!isCurrent()) return
    if (event.button !== 0) return
    if (resultSelectionMode) return
    if (
      isResultControlTarget(event.target) ||
      (event.target instanceof Element &&
        event.target.closest("button,a,input,textarea,select"))
    ) {
      return
    }
    resultDragCleanupRef.current?.()
    resultDragRef.current = {
      result,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      x: event.clientX,
      y: event.clientY,
      active: false,
    }
    let cleanup = () => undefined
    const handleMove = (pointerEvent: PointerEvent) => {
      if (!isCurrent()) return
      const drag = resultDragRef.current
      if (!drag || drag.pointerId !== pointerEvent.pointerId) return
      const distance = Math.hypot(
        pointerEvent.clientX - drag.startX,
        pointerEvent.clientY - drag.startY
      )
      const active = drag.active || distance >= 8
      resultDragRef.current = {
        ...drag,
        x: pointerEvent.clientX,
        y: pointerEvent.clientY,
        active,
      }
      if (active) {
        pointerEvent.preventDefault()
        setResultDragPreview({
          x: pointerEvent.clientX,
          y: pointerEvent.clientY,
          result: drag.result,
        })
      }
    }
    const handleEnd = (pointerEvent: PointerEvent) => {
      if (!isCurrent()) return
      const drag = resultDragRef.current
      if (!drag || drag.pointerId !== pointerEvent.pointerId) return
      cleanup()
      resultDragCleanupRef.current = null
      resultDragRef.current = null
      setResultDragPreview(null)
      if (!drag.active) return
      resultDragSuppressClickUntilRef.current = Date.now() + 250
      pointerEvent.preventDefault()
      const x = pointerEvent.clientX
      const y = pointerEvent.clientY
      if (isScreenPointInsideDialog(x, y) || !isScreenPointInsideFlow(x, y)) {
        toast.info("请拖到画布区域后松开")
        return
      }
      void onDropToCanvas(drag.result, { x, y })
    }
    const handleCancel = (event: PointerEvent) => {
      if (resultDragRef.current?.pointerId !== event.pointerId) return
      resultDragCleanupRef.current?.()
      resultDragCleanupRef.current = null
      resultDragRef.current = null
    }
    cleanup = () => {
      window.removeEventListener("pointermove", handleMove)
      window.removeEventListener("pointerup", handleEnd)
      window.removeEventListener("pointercancel", handleCancel)
    }
    resultDragCleanupRef.current = () => {
      cleanup()
      setResultDragPreview(null)
    }
    window.addEventListener("pointermove", handleMove, { passive: false })
    window.addEventListener("pointerup", handleEnd, { passive: false })
    window.addEventListener("pointercancel", handleCancel, { passive: false })
  }

  const handleResultClickCapture = (
    event: React.MouseEvent<HTMLDivElement>,
    result: VideoClipCanvasResult
  ) => {
    if (isResultControlTarget(event.target)) {
      return
    }
    if (resultSelectionMode) {
      event.preventDefault()
      event.stopPropagation()
      if (!deletingResults) {
        toggleResultSelected(result.id, !selectedResultIdSet.has(result.id))
      }
      return
    }
    if (Date.now() <= resultDragSuppressClickUntilRef.current) {
      event.preventDefault()
      event.stopPropagation()
      return
    }
    if (result.kind === "video") {
      handleResultClick(event, result)
    }
  }

  const handleResultClick = (
    event: React.MouseEvent<HTMLDivElement>,
    result: VideoClipCanvasResult
  ) => {
    if (isResultControlTarget(event.target)) return
    if (result.kind !== "video") return
    if (Date.now() <= resultDragSuppressClickUntilRef.current) return
    event.preventDefault()
    event.stopPropagation()
    onEditResult(result)
  }
  return {
    handleResultPointerDown,
    handleResultClickCapture,
    handleResultClick,
    resultDragPreview,
  }
}
export type VideoClipResultDrag = ReturnType<typeof useVideoClipResultDrag>
