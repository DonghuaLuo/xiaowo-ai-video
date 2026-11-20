import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import {
  deleteVideoClipResults,
  extractVideoFrame,
  listVideoClipResults,
  trimVideoClip,
  type VideoClipMediaResult,
} from "@/backend"
import type { useBackend } from "@/hooks/useBackend"
import { errMsg } from "@/shared/backend-result"
import {
  type VideoClipCanvasResult,
  type VideoClipDialogSource,
  videoClipCanvasResultFromMediaResult,
  videoClipCanvasResultFromRecord,
} from "./video-clip-model"
import { useVideoClipActivation } from "./use-video-clip-activation"
export function useVideoClipResults({
  backend,
  projectId,
  episodeId,
  source,
  onCopyAsset,
}: { projectId: string; episodeId: string; source: VideoClipDialogSource } & {
  backend: Pick<ReturnType<typeof useBackend>, "backendReady" | "callBackend">
  onCopyAsset: (result: VideoClipCanvasResult) => Promise<void> | void
}) {
  const { backendReady, callBackend } = backend
  const activation = useVideoClipActivation(projectId, episodeId, source)
  const isCurrent = activation.isCurrent
  const resultMutationInFlightRef = useRef(false)
  const loadRequestRef = useRef(0)
  const resultRevisionRef = useRef(0)

  const [loadingResults, setLoadingResults] = useState(false)

  const [workingAction, setWorkingAction] = useState<"trim" | "frame" | null>(
    null
  )

  const [results, setResults] = useState<VideoClipCanvasResult[]>([])

  const [resultMenu, setResultMenu] = useState<{
    resultId: string
    x: number
    y: number
  } | null>(null)

  const [copyingResultId, setCopyingResultId] = useState<string | null>(null)

  const [resultSelectionMode, setResultSelectionMode] = useState(false)

  const [selectedResultIds, setSelectedResultIds] = useState<string[]>([])

  const [deletingResultIds, setDeletingResultIds] = useState<string[]>([])

  const activeResult = resultMenu
    ? results.find((item) => item.id === resultMenu.resultId)
    : null

  const selectedResultIdSet = useMemo(
    () => new Set(selectedResultIds),
    [selectedResultIds]
  )

  const deletingResultIdSet = useMemo(
    () => new Set(deletingResultIds),
    [deletingResultIds]
  )

  const someResultsSelected = selectedResultIds.length > 0

  const deletingResults = deletingResultIds.length > 0

  const resultMutationBusy = Boolean(workingAction || deletingResults)

  useEffect(() => {
    if (!resultMenu) return
    const closeResultMenu = (event: PointerEvent) => {
      const target = event.target
      if (
        target instanceof Element &&
        target.closest("[data-video-clip-result-menu='true']")
      ) {
        return
      }
      setResultMenu(null)
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setResultMenu(null)
    }
    window.addEventListener("pointerdown", closeResultMenu, true)
    window.addEventListener("keydown", handleKeyDown)
    return () => {
      window.removeEventListener("pointerdown", closeResultMenu, true)
      window.removeEventListener("keydown", handleKeyDown)
    }
  }, [resultMenu])

  const loadClipResults = useCallback(async () => {
    if (!isCurrent()) return
    const request = ++loadRequestRef.current
    const revision = resultRevisionRef.current
    const canApply = () =>
      isCurrent() &&
      request === loadRequestRef.current &&
      revision === resultRevisionRef.current
    if (!backendReady) {
      setResults([])
      setLoadingResults(false)
      return
    }
    setLoadingResults(true)
    try {
      const list = await listVideoClipResults(
        callBackend,
        projectId,
        episodeId,
        {
          media: source.media,
        }
      )
      if (!canApply()) return
      const hydrated = await Promise.all(
        (list.results ?? []).map((item) =>
          videoClipCanvasResultFromRecord(projectId, item)
        )
      )
      if (!canApply()) return
      setResults(hydrated.filter(Boolean) as VideoClipCanvasResult[])
    } catch (error) {
      if (!canApply()) return
      toast.error(errMsg(error, "加载剪辑结果失败"))
      setResults([])
    } finally {
      if (isCurrent() && request === loadRequestRef.current)
        setLoadingResults(false)
    }
  }, [backendReady, callBackend, episodeId, projectId, source.media, isCurrent])

  useEffect(() => {
    setSelectedResultIds((current) => {
      if (!current.length) return current
      const existingIds = new Set(results.map((item) => item.id))
      const next = current.filter((id) => existingIds.has(id))
      return next.length === current.length ? current : next
    })
    if (!results.length) {
      setResultSelectionMode(false)
      setResultMenu(null)
    }
  }, [results])

  const appendResult = async (result: VideoClipMediaResult, title: string) => {
    const next = await videoClipCanvasResultFromMediaResult(
      projectId,
      result,
      title
    )
    if (!isCurrent()) return
    if (!next) {
      await loadClipResults()
      if (!isCurrent()) return
      return
    }
    setResults((current) => [
      next,
      ...current.filter((item) => item.id !== next.id),
    ])
  }

  const handleCopyResultAsset = async (result: VideoClipCanvasResult) => {
    setCopyingResultId(result.id)
    try {
      await onCopyAsset(result)
      if (!isCurrent()) return
      setResultMenu(null)
    } finally {
      if (isCurrent()) setCopyingResultId(null)
    }
  }

  const openResultContextMenu = (
    event: React.MouseEvent<HTMLDivElement>,
    result: VideoClipCanvasResult
  ) => {
    event.preventDefault()
    event.stopPropagation()
    setResultMenu({
      resultId: result.id,
      x: event.clientX,
      y: event.clientY,
    })
  }

  const toggleResultSelected = (resultId: string, checked: boolean) => {
    setResultSelectionMode(true)
    setSelectedResultIds((current) => {
      if (checked) {
        return current.includes(resultId) ? current : [...current, resultId]
      }
      return current.filter((id) => id !== resultId)
    })
  }

  const selectAllResults = () => {
    setResultSelectionMode(true)
    setSelectedResultIds(results.map((item) => item.id))
    setResultMenu(null)
  }

  const clearAllResultSelection = () => {
    setResultSelectionMode(true)
    setSelectedResultIds([])
    setResultMenu(null)
  }

  const cancelResultSelection = () => {
    setResultSelectionMode(false)
    setSelectedResultIds([])
    setResultMenu(null)
  }

  const handleDeleteResults = async (
    resultIds: string[],
    beforeDelete: (ids: string[]) => void
  ) => {
    if (!isCurrent()) return
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    if (resultMutationInFlightRef.current || resultMutationBusy) {
      toast.info("请等待当前操作完成")
      return
    }
    const existingIds = new Set(results.map((item) => item.id))
    const ids = Array.from(new Set(resultIds)).filter((id) =>
      existingIds.has(id)
    )
    if (!ids.length) return
    beforeDelete(ids)
    resultMutationInFlightRef.current = true
    resultRevisionRef.current += 1
    setDeletingResultIds(ids)
    try {
      const response = await deleteVideoClipResults(
        callBackend,
        projectId,
        episodeId,
        {
          media: source.media,
          resultIds: ids,
        }
      )
      if (!isCurrent()) return
      const hydrated = await Promise.all(
        (response.results ?? []).map((item) =>
          videoClipCanvasResultFromRecord(projectId, item)
        )
      )
      if (!isCurrent()) return
      setResults(hydrated.filter(Boolean) as VideoClipCanvasResult[])
      setSelectedResultIds((current) =>
        current.filter((id) => !ids.includes(id))
      )
      setResultMenu(null)
      toast.success("剪辑结果已删除")
    } catch (error) {
      if (!isCurrent()) return
      toast.error(errMsg(error, "删除剪辑结果失败"))
    } finally {
      if (isCurrent()) {
        setDeletingResultIds([])
        resultMutationInFlightRef.current = false
      }
    }
  }
  const runGeneration = async (
    action: "trim" | "frame",
    operation: () => Promise<VideoClipMediaResult>,
    title: string
  ) => {
    if (!isCurrent()) return
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    if (resultMutationInFlightRef.current || resultMutationBusy) {
      toast.info("请等待当前操作完成")
      return
    }
    resultMutationInFlightRef.current = true
    resultRevisionRef.current += 1
    setWorkingAction(action)
    try {
      const result = await operation()
      if (!isCurrent()) return
      await appendResult(result, title)
      if (!isCurrent()) return
      toast.success(
        action === "trim" ? result.warning || "视频已剪切" : "帧画面已截取"
      )
    } catch (error) {
      if (isCurrent())
        toast.error(
          errMsg(error, action === "trim" ? "剪切视频失败" : "截取帧画面失败")
        )
    } finally {
      if (isCurrent()) {
        resultMutationInFlightRef.current = false
        setWorkingAction(null)
      }
    }
  }
  const trim = (request: Parameters<typeof trimVideoClip>[3] | null) =>
    request
      ? runGeneration(
          "trim",
          () => trimVideoClip(callBackend, projectId, episodeId, request),
          request.title || ""
        )
      : Promise.resolve()
  const extractFrame = (request: Parameters<typeof extractVideoFrame>[3]) =>
    runGeneration(
      "frame",
      () => extractVideoFrame(callBackend, projectId, episodeId, request),
      request.title || ""
    )
  const closeResultMenu = () => setResultMenu(null)
  useEffect(() => {
    setResults([])
    setLoadingResults(false)
    setWorkingAction(null)
    setDeletingResultIds([])
    setCopyingResultId(null)
    setResultMenu(null)
    setSelectedResultIds([])
    setResultSelectionMode(false)
    resultMutationInFlightRef.current = false
  }, [activation])

  return {
    loadClipResults,
    trim,
    extractFrame,
    closeResultMenu,
    handleDeleteResults,
    resultSelectionMode,
    deletingResults,
    selectedResultIdSet,
    toggleResultSelected,
    resultMutationBusy,
    workingAction,
    selectedResultIds,
    clearAllResultSelection,
    someResultsSelected,
    results,
    deletingResultIdSet,
    openResultContextMenu,
    loadingResults,
    resultMenu,
    activeResult,
    handleCopyResultAsset,
    copyingResultId,
    selectAllResults,
    cancelResultSelection,
  }
}
export type VideoClipResults = ReturnType<typeof useVideoClipResults>
