import { useEffect, useState } from "react"

export const WORKFLOW_FLOATING_EDITOR_WIDTH = 800

export const WORKFLOW_FLOATING_EDIT_PANEL_WIDTH = 700

export const WORKFLOW_FLOATING_TASK_PANEL_WIDTH =
  WORKFLOW_FLOATING_EDIT_PANEL_WIDTH + 80

export const WORKFLOW_FLOATING_EDITOR_MARGIN = 16

export const WORKFLOW_FLOATING_EDITOR_GAP = 14

export const WORKFLOW_FLOATING_EDITOR_MIN_HEIGHT = 260

export const WORKFLOW_FLOATING_EDITOR_MAX_HEIGHT = 760

export const WORKFLOW_FLOATING_TASK_EDITOR_PREFERRED_HEIGHT = 560

export const WORKFLOW_FLOATING_DIRECTOR_EDITOR_PREFERRED_HEIGHT = 750

export const WORKFLOW_CENTERED_TASK_EDITOR_CONTENT_HEIGHT = 680

export type WorkflowFloatingPanelRect = {
  left: number
  top: number
  width: number
  maxHeight: number
  transform: string
}

export function workflowFloatingPanelRectForAnchor(
  anchor: HTMLElement,
  widthLimit: number,
  preferredHeight = WORKFLOW_FLOATING_TASK_EDITOR_PREFERRED_HEIGHT
): WorkflowFloatingPanelRect {
  const rect = anchor.getBoundingClientRect()
  const maxAvailableWidth = Math.max(
    320,
    window.innerWidth - WORKFLOW_FLOATING_EDITOR_MARGIN * 2
  )
  const width = Math.min(widthLimit, maxAvailableWidth)
  const minLeft = WORKFLOW_FLOATING_EDITOR_MARGIN + width / 2
  const maxLeft = Math.max(
    minLeft,
    window.innerWidth - WORKFLOW_FLOATING_EDITOR_MARGIN - width / 2
  )
  const left = Math.min(Math.max(rect.left + rect.width / 2, minLeft), maxLeft)
  const viewportHeight = Math.max(
    WORKFLOW_FLOATING_EDITOR_MIN_HEIGHT,
    window.innerHeight - WORKFLOW_FLOATING_EDITOR_MARGIN * 2
  )
  const maxPanelHeight = Math.min(
    WORKFLOW_FLOATING_EDITOR_MAX_HEIGHT,
    viewportHeight
  )
  const targetFullHeight = Math.min(maxPanelHeight, preferredHeight)
  const belowTop = rect.bottom + WORKFLOW_FLOATING_EDITOR_GAP
  const belowSpace =
    window.innerHeight - belowTop - WORKFLOW_FLOATING_EDITOR_MARGIN
  const aboveSpace =
    rect.top - WORKFLOW_FLOATING_EDITOR_GAP - WORKFLOW_FLOATING_EDITOR_MARGIN
  const belowAvailableHeight = Math.max(0, Math.min(maxPanelHeight, belowSpace))
  const aboveAvailableHeight = Math.max(0, Math.min(maxPanelHeight, aboveSpace))
  const halfTargetFullHeight = targetFullHeight / 2
  const openAbove =
    belowAvailableHeight < halfTargetFullHeight &&
    aboveAvailableHeight > belowAvailableHeight
  const availableHeight = openAbove
    ? aboveAvailableHeight
    : belowAvailableHeight
  const maxHeight = Math.min(targetFullHeight, Math.max(1, availableHeight))
  const top = openAbove
    ? Math.max(
        WORKFLOW_FLOATING_EDITOR_MARGIN,
        rect.top - WORKFLOW_FLOATING_EDITOR_GAP
      )
    : Math.min(
        Math.max(WORKFLOW_FLOATING_EDITOR_MARGIN, belowTop),
        Math.max(
          WORKFLOW_FLOATING_EDITOR_MARGIN,
          window.innerHeight - WORKFLOW_FLOATING_EDITOR_MARGIN - maxHeight
        )
      )
  return {
    left,
    top,
    width,
    maxHeight,
    transform: openAbove ? "translate(-50%, -100%)" : "translateX(-50%)",
  }
}

export function workflowViewportBoundFloatingStyle(
  x: number,
  y: number,
  widthLimit: number,
  maxHeightLimit = WORKFLOW_FLOATING_EDITOR_MAX_HEIGHT
) {
  const viewportWidth =
    typeof window === "undefined"
      ? widthLimit + WORKFLOW_FLOATING_EDITOR_MARGIN * 2
      : window.innerWidth
  const viewportHeight =
    typeof window === "undefined"
      ? maxHeightLimit + WORKFLOW_FLOATING_EDITOR_MARGIN * 2
      : window.innerHeight
  const width = Math.min(
    widthLimit,
    Math.max(320, viewportWidth - WORKFLOW_FLOATING_EDITOR_MARGIN * 2)
  )
  const maxHeight = Math.min(
    maxHeightLimit,
    Math.max(
      WORKFLOW_FLOATING_EDITOR_MIN_HEIGHT,
      viewportHeight - WORKFLOW_FLOATING_EDITOR_MARGIN * 2
    )
  )
  const left = Math.min(
    Math.max(WORKFLOW_FLOATING_EDITOR_MARGIN, x),
    Math.max(
      WORKFLOW_FLOATING_EDITOR_MARGIN,
      viewportWidth - width - WORKFLOW_FLOATING_EDITOR_MARGIN
    )
  )
  const top = Math.min(
    Math.max(WORKFLOW_FLOATING_EDITOR_MARGIN, y),
    Math.max(
      WORKFLOW_FLOATING_EDITOR_MARGIN,
      viewportHeight - maxHeight - WORKFLOW_FLOATING_EDITOR_MARGIN
    )
  )
  return { left, top, width, maxHeight }
}

export function useWorkflowFloatingPanelRect(
  enabled: boolean,
  widthLimit: number,
  getAnchor: () => HTMLElement | null,
  depsKey: string,
  preferredHeight = WORKFLOW_FLOATING_TASK_EDITOR_PREFERRED_HEIGHT
) {
  const [panelRect, setPanelRect] = useState<WorkflowFloatingPanelRect | null>(
    null
  )

  useEffect(() => {
    if (!enabled || typeof window === "undefined") {
      setPanelRect(null)
      return
    }
    let frame = 0
    const updatePanelRect = () => {
      const anchor = getAnchor()
      if (!anchor) {
        setPanelRect(null)
        return
      }
      setPanelRect(
        workflowFloatingPanelRectForAnchor(anchor, widthLimit, preferredHeight)
      )
    }
    const requestPanelRectUpdate = () => {
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(updatePanelRect)
    }

    requestPanelRectUpdate()
    window.addEventListener("resize", requestPanelRectUpdate)
    window.addEventListener("scroll", requestPanelRectUpdate, true)
    const interval = window.setInterval(requestPanelRectUpdate, 250)
    return () => {
      window.cancelAnimationFrame(frame)
      window.clearInterval(interval)
      window.removeEventListener("resize", requestPanelRectUpdate)
      window.removeEventListener("scroll", requestPanelRectUpdate, true)
    }
  }, [enabled, widthLimit, getAnchor, depsKey, preferredHeight])

  return panelRect
}
