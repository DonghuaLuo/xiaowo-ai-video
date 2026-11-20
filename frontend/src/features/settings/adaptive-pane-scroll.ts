import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react"

const DESKTOP_TWO_PANE_QUERY = "(min-width: 1024px)"
const BOTTOM_GAP = 24
const PANEL_BOTTOM_PADDING = 16
const MIN_SCROLL_HEIGHT = 160

type PaneScrollHeights = {
  list: number | null
  detail: number | null
}

export function useAdaptivePaneScroll() {
  const listElementRef = useRef<HTMLElement | null>(null)
  const detailElementRef = useRef<HTMLElement | null>(null)
  const [maxHeights, setMaxHeights] = useState<PaneScrollHeights>({
    list: null,
    detail: null,
  })

  const updateMaxHeights = useCallback(() => {
    if (typeof window === "undefined") return
    if (!window.matchMedia(DESKTOP_TWO_PANE_QUERY).matches) {
      setMaxHeights((current) =>
        current.list === null && current.detail === null
          ? current
          : { list: null, detail: null }
      )
      return
    }

    const measure = (element: HTMLElement | null) => {
      if (!element) return null
      const top = element.getBoundingClientRect().top
      return Math.max(
        MIN_SCROLL_HEIGHT,
        Math.floor(window.innerHeight - top - BOTTOM_GAP - PANEL_BOTTOM_PADDING)
      )
    }
    const next = {
      list: measure(listElementRef.current),
      detail: measure(detailElementRef.current),
    }
    setMaxHeights((current) =>
      current.list === next.list && current.detail === next.detail
        ? current
        : next
    )
  }, [])

  const listScrollRef = useCallback(
    (element: HTMLElement | null) => {
      listElementRef.current = element
    },
    []
  )
  const detailScrollRef = useCallback(
    (element: HTMLElement | null) => {
      detailElementRef.current = element
    },
    []
  )

  useLayoutEffect(() => {
    updateMaxHeights()
  })

  useLayoutEffect(() => {
    if (typeof window === "undefined") return
    updateMaxHeights()
    const frameId = window.requestAnimationFrame(updateMaxHeights)
    window.addEventListener("resize", updateMaxHeights)
    if (typeof document !== "undefined") {
      document.addEventListener("scroll", updateMaxHeights, true)
    }
    return () => {
      window.cancelAnimationFrame(frameId)
      window.removeEventListener("resize", updateMaxHeights)
      if (typeof document !== "undefined") {
        document.removeEventListener("scroll", updateMaxHeights, true)
      }
    }
  }, [updateMaxHeights])

  const listScrollStyle = useMemo<CSSProperties | undefined>(
    () =>
      maxHeights.list ? { maxHeight: `${maxHeights.list}px` } : undefined,
    [maxHeights.list]
  )
  const detailScrollStyle = useMemo<CSSProperties | undefined>(
    () =>
      maxHeights.detail ? { maxHeight: `${maxHeights.detail}px` } : undefined,
    [maxHeights.detail]
  )

  return {
    listScrollRef,
    detailScrollRef,
    listScrollStyle,
    detailScrollStyle,
  }
}
