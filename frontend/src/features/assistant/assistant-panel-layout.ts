import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react"
export const ASSISTANT_PANEL_DEFAULT_WIDTH = 385

export const ASSISTANT_PANEL_MIN_WIDTH = 300

export const ASSISTANT_PANEL_MAX_WIDTH = 560

export const ASSISTANT_PANEL_WIDTH_STORAGE_KEY = "ai_video_assistant_panel_width_v2"

export function clampAssistantPanelWidth(value: number) {
  if (!Number.isFinite(value)) return ASSISTANT_PANEL_DEFAULT_WIDTH
  return Math.min(
    ASSISTANT_PANEL_MAX_WIDTH,
    Math.max(ASSISTANT_PANEL_MIN_WIDTH, Math.round(value))
  )
}

export function readPersistedAssistantPanelWidth() {
  if (typeof window === "undefined") return ASSISTANT_PANEL_DEFAULT_WIDTH
  try {
    const raw = window.localStorage.getItem(ASSISTANT_PANEL_WIDTH_STORAGE_KEY)
    if (!raw) return ASSISTANT_PANEL_DEFAULT_WIDTH
    const parsed = Number.parseInt(raw, 10)
    if (Number.isNaN(parsed)) return ASSISTANT_PANEL_DEFAULT_WIDTH
    return clampAssistantPanelWidth(parsed)
  } catch {
    return ASSISTANT_PANEL_DEFAULT_WIDTH
  }
}

export function persistAssistantPanelWidth(width: number) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(
      ASSISTANT_PANEL_WIDTH_STORAGE_KEY,
      String(clampAssistantPanelWidth(width))
    )
  } catch {
    // localStorage may be unavailable; the in-memory width still works.
  }
}

export function useAssistantPanelLayout(
  onCollapsedChange: (collapsed: boolean) => void
) {
  const [panelWidth, setPanelWidth] = useState(readPersistedAssistantPanelWidth)

  const [draftWidth, setDraftWidth] = useState<number | null>(null)

  const draftWidthRef = useRef<number | null>(null)

  const dragStateRef = useRef<{ startX: number; startWidth: number } | null>(null)

  const restoreBodyStyleRef = useRef<{
    cursor: string
    userSelect: string
  } | null>(null)

  const isResizingPanel = draftWidth !== null

  const displayedPanelWidth = draftWidth ?? panelWidth

  const updateDraftWidth = useCallback((next: number | null) => {
    draftWidthRef.current = next
    setDraftWidth(next)
  }, [])

  const restoreBodyStyle = useCallback(() => {
    const saved = restoreBodyStyleRef.current
    if (!saved) return
    document.body.style.cursor = saved.cursor
    document.body.style.userSelect = saved.userSelect
    restoreBodyStyleRef.current = null
  }, [])

  const handleResizeMouseDown = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      if (event.button !== 0) return
      event.preventDefault()
      dragStateRef.current = {
        startX: event.clientX,
        startWidth: panelWidth,
      }
      restoreBodyStyleRef.current = {
        cursor: document.body.style.cursor,
        userSelect: document.body.style.userSelect,
      }
      document.body.style.cursor = "col-resize"
      document.body.style.userSelect = "none"
      updateDraftWidth(panelWidth)
    },
    [panelWidth, updateDraftWidth]
  )

  const handleResizeDoubleClick = useCallback(() => {
    setPanelWidth(ASSISTANT_PANEL_DEFAULT_WIDTH)
    persistAssistantPanelWidth(ASSISTANT_PANEL_DEFAULT_WIDTH)
  }, [])

  useEffect(() => {
    if (!isResizingPanel) return

    const finishResize = () => {
      dragStateRef.current = null
      restoreBodyStyle()
      const finalWidth = draftWidthRef.current
      updateDraftWidth(null)
      if (finalWidth == null) return
      const nextWidth = clampAssistantPanelWidth(finalWidth)
      setPanelWidth(nextWidth)
      persistAssistantPanelWidth(nextWidth)
    }

    const handleMouseMove = (event: MouseEvent) => {
      const drag = dragStateRef.current
      if (!drag) return
      if ((event.buttons & 1) === 0) {
        finishResize()
        return
      }
      updateDraftWidth(
        clampAssistantPanelWidth(drag.startWidth + (drag.startX - event.clientX))
      )
    }

    window.addEventListener("mousemove", handleMouseMove)
    window.addEventListener("mouseup", finishResize)
    window.addEventListener("blur", finishResize)
    return () => {
      window.removeEventListener("mousemove", handleMouseMove)
      window.removeEventListener("mouseup", finishResize)
      window.removeEventListener("blur", finishResize)
      restoreBodyStyle()
    }
  }, [isResizingPanel, restoreBodyStyle, updateDraftWidth])
  return {
    updateCollapsed: onCollapsedChange,
    isResizingPanel,
    displayedPanelWidth,
    handleResizeMouseDown,
    handleResizeDoubleClick,
  }
}
