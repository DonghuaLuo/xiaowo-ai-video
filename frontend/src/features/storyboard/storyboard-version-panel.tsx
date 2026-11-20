import { createPortal } from "react-dom"
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
} from "react"
import { toast } from "sonner"
import {
  CheckCircle2,
  Copy,
  Loader2,
  RefreshCcw,
  Trash2,
} from "lucide-react"
import {
  deleteStoryboardVersion,
  listStoryboardVersions,
  setStoryboardResultActiveVersion,
  type MediaAsset,
  type StoryboardVersion,
} from "@/backend"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import { errMsg } from "@/shared/backend-result"
import {
  UnifiedMediaFrame,
  mediaDownloadSource,
} from "@/shared/unified-media-frame"
import { ConfirmDialog } from "@/shared/confirm-dialog"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { mediaPreviewSrc } from "@/shared/media"

export type StoryboardVersionPanelNode = {
  id: string
  type: "storyboardNode"
  position: { x: number; y: number }
  data: {
    title: string
    eyebrow: string
    summary: string
    status: any
    tone: string
    [key: string]: any
  }
}

export type StoryboardVersionChangeKind =
  | "active"
  | "winner"
  | "winner-cleared"
  | "deleted"

export type StoryboardVersionActivationMode = "workflow" | "local"
export type StoryboardVersionDeleteMode = "workflow" | "none"

export type StoryboardVersionCanvasDrop = {
  version: StoryboardVersion
  sourceNode: StoryboardVersionPanelNode
  screenPosition: { x: number; y: number }
  label: string
}

export type StoryboardVersionCanvasCopy = Omit<
  StoryboardVersionCanvasDrop,
  "screenPosition"
>

type StoryboardVersionDragState = StoryboardVersionCanvasDrop & {
  scope: object
  token: object
  pointerId: number
  startX: number
  startY: number
  previewSrc: string
  active: boolean
}

type StoryboardVersionDragPreview = {
  x: number
  y: number
  label: string
  previewSrc: string
  kind: "image" | "video"
}

function versionCurrentId(data?: Record<string, any> | null) {
  return (
    String(data?.activeVersionId ?? "").trim() ||
    String(data?.activeMediaVersionId ?? "").trim() ||
    String(data?.mediaVersionId ?? "").trim() ||
    null
  )
}

function versionStorageNodeId(nodeId: string, data?: Record<string, any> | null) {
  const type = String(data?.eyebrow ?? "").trim()
  const role = String(data?.canvasNodeRole ?? data?.mediaPurpose ?? "").trim()
  if (
    type === "video.result" ||
    type === "storyboard.image" ||
    role === "visual_handoff" ||
    role === "visual_handoff_reference"
  ) {
    return nodeId
  }
  return String(data?.resultOfNodeId ?? "").trim() || nodeId
}

function storyboardVersionPreviewSrc(version: StoryboardVersion) {
  return mediaPreviewSrc(version.media, version.preview)
}

function storyboardVersionPreviewKind(version: StoryboardVersion): "image" | "video" {
  const src = storyboardVersionPreviewSrc(version)
  if (
    version.media?.kind === "video" ||
    version.media?.mimeType?.startsWith("video/") ||
    (src && (/^data:video\//.test(src) || /\.(mp4|webm|mov)(\?|$)/i.test(src)))
  ) {
    return "video"
  }
  return "image"
}

function storyboardVersionDisplayMedia(version: StoryboardVersion) {
  const media: MediaAsset = {
    ...(version.media ?? {}),
    id: version.media?.id || `storyboard-version-${version.id}`,
    kind: storyboardVersionPreviewKind(version),
    preview: version.media?.preview ?? version.preview ?? undefined,
  }
  return mediaPreviewSrc(media) ? media : null
}

function storyboardVersionDisplayLabel(index: number, count: number) {
  return `修改版本 ${count - index}`
}

function formatVersionDateTime(value: unknown) {
  const raw = String(value ?? "").trim()
  if (!raw) return ""
  const numeric = Number(raw)
  const timestamp = Number.isFinite(numeric)
    ? numeric < 10_000_000_000
      ? numeric * 1000
      : numeric
    : Date.parse(raw)
  if (!Number.isFinite(timestamp)) return raw
  const date = new Date(timestamp)
  const pad = (item: number) => String(item).padStart(2, "0")
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function versionIsGeneratedResultNode(node?: StoryboardVersionPanelNode | null) {
  if (!node) return false
  const type = String(node.data?.eyebrow ?? "").trim()
  const role = String(node.data?.canvasNodeRole ?? node.data?.mediaPurpose ?? "").trim()
  return (
    type === "video.result" ||
    type === "storyboard.image" ||
    role === "visual_handoff" ||
    role === "visual_handoff_reference"
  )
}

export function StoryboardVersionPanel({
  projectId,
  episodeId,
  node,
  onChanged,
  onWorkflowVersionChanged,
  onWorkflowMutationCommitted,
  onCreateCanvasAsset,
  onCopyCanvasAsset,
  activationMode = "workflow",
  deleteMode = "workflow",
  activeVersionIdOverride,
  versionNodeIdOverride,
  compact = false,
}: {
  projectId: string
  episodeId: string
  node: StoryboardVersionPanelNode
  onChanged: (
    version?: StoryboardVersion | null,
    changeKind?: StoryboardVersionChangeKind
  ) => Promise<void> | void
  onWorkflowVersionChanged?: (workflowVersion: unknown) => void
  onWorkflowMutationCommitted?: (payload: Record<string, unknown>) => void
  onCreateCanvasAsset?: (
    payload: StoryboardVersionCanvasDrop
  ) => Promise<void> | void
  onCopyCanvasAsset?: (
    payload: StoryboardVersionCanvasCopy
  ) => Promise<void> | void
  activationMode?: StoryboardVersionActivationMode
  deleteMode?: StoryboardVersionDeleteMode
  activeVersionIdOverride?: string | null
  versionNodeIdOverride?: string
  compact?: boolean
}) {
  const { backendReady, callBackend } = useBackend()
  const [versions, setVersions] = useState<StoryboardVersion[]>([])
  const [loading, setLoading] = useState(false)
  const [switchingVersionId, setSwitchingVersionId] = useState<string | null>(
    null
  )
  const [deleteTarget, setDeleteTarget] = useState<StoryboardVersion | null>(
    null
  )
  const [deletingVersionId, setDeletingVersionId] = useState<string | null>(
    null
  )
  const versionDragRef = useRef<StoryboardVersionDragState | null>(null)
  const versionDragCleanupRef = useRef<(() => void) | null>(null)
  const [versionDragPreview, setVersionDragPreview] =
    useState<StoryboardVersionDragPreview | null>(null)
  const [versionPreviewRequest, setVersionPreviewRequest] = useState<{
    versionId: string
    token: number
  } | null>(null)
  const [versionContextMenu, setVersionContextMenu] = useState<{
    versionId: string
    label: string
    x: number
    y: number
  } | null>(null)
  const versionNodeId =
    versionNodeIdOverride ||
    versionStorageNodeId(node.id, node.data)
  const activeVersionId =
    activeVersionIdOverride ?? versionCurrentId(node.data)

  const scopeKey = JSON.stringify([projectId, episodeId, versionNodeId, node.id])
  const scopeRef = useRef({ key: scopeKey, active: true })
  if (scopeRef.current.key !== scopeKey) {
    scopeRef.current = { key: scopeKey, active: true }
  }
  const scope = scopeRef.current
  const versionsScopeRef = useRef<object | null>(null)
  const isCurrent = useCallback(
    () => scopeRef.current === scope && scope.active,
    [scope]
  )
  useEffect(() => {
    scope.active = true
    setLoading(false)
    setSwitchingVersionId(null)
    setDeletingVersionId(null)
    setDeleteTarget(null)
    setVersionContextMenu(null)
    setVersionPreviewRequest(null)
    setVersionDragPreview(null)
    return () => {
      scope.active = false
      if (versionDragRef.current?.scope === scope) {
        versionDragCleanupRef.current?.()
      }
    }
  }, [scope])

  const loadVersions = useCallback(async () => {
    if (!backendReady || !isCurrent()) return []
    setLoading(true)
    try {
      const next = await listStoryboardVersions(
        callBackend,
        projectId,
        episodeId,
        versionNodeId
      )
      if (!isCurrent()) return []
      versionsScopeRef.current = scope
      setVersions(next)
      return next
    } catch (error) {
      if (!isCurrent()) return []
      toast.error(errMsg(error, "加载版本失败"))
      setVersions([])
      return []
    } finally {
      if (isCurrent()) setLoading(false)
    }
  }, [backendReady, callBackend, episodeId, projectId, versionNodeId, isCurrent])

  useEffect(() => {
    setVersions([])
    void loadVersions()
  }, [loadVersions])

  const displayVersions = useMemo(
    () => versionsScopeRef.current === scope ? [...versions].reverse() : [],
    [versions, scope]
  )
  const contextMenuVersion = versionContextMenu
    ? displayVersions.find(
        (version) => version.id === versionContextMenu.versionId
      )
    : undefined

  useEffect(() => {
    if (!versionContextMenu) return
    const closeVersionContextMenu = (event: PointerEvent) => {
      if (!isCurrent()) return
      const target = event.target
      if (
        target instanceof Element &&
        target.closest("[data-version-context-menu='true']")
      ) {
        return
      }
      setVersionContextMenu(null)
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!isCurrent()) return
      if (event.key === "Escape") setVersionContextMenu(null)
    }
    window.addEventListener("pointerdown", closeVersionContextMenu, true)
    window.addEventListener("keydown", handleKeyDown)
    return () => {
      window.removeEventListener("pointerdown", closeVersionContextMenu, true)
      window.removeEventListener("keydown", handleKeyDown)
    }
  }, [versionContextMenu, isCurrent])

  const openVersionContextMenu = (
    event: MouseEvent<HTMLElement>,
    version: StoryboardVersion,
    label: string
  ) => {
    if (!isCurrent()) return
    if (!onCopyCanvasAsset || !storyboardVersionDisplayMedia(version)) return
    event.preventDefault()
    event.stopPropagation()
    setVersionContextMenu({
      versionId: version.id,
      label,
      x: event.clientX,
      y: event.clientY,
    })
  }

  const handleUseVersion = async (version: StoryboardVersion) => {
    if (!isCurrent() || versionsScopeRef.current !== scope) return
    setSwitchingVersionId(version.id)
    try {
      if (activationMode === "local") {
        await onChanged(version, "active")
        if (!isCurrent()) return
        toast.success("已切换当前版本")
        return
      }
      const result = await setStoryboardResultActiveVersion(
        callBackend,
        projectId,
        episodeId,
        {
          nodeId: versionNodeId,
          versionId: version.id,
          resultNodeId: versionIsGeneratedResultNode(node)
            ? node.id
            : undefined,
        }
      )
      if (!isCurrent()) return
      toast.success("已切换当前版本")
      if (
        result.workflowVersion !== undefined &&
        result.workflowVersion !== null
      ) {
        onWorkflowVersionChanged?.(result.workflowVersion)
      }
      if (!isCurrent()) return
      await onChanged(result.version ?? version, "active")
    } catch (error) {
      if (!isCurrent()) return
      toast.error(errMsg(error, "切换版本失败"))
    } finally {
      if (isCurrent()) setSwitchingVersionId(null)
    }
  }

  const handleConfirmDeleteVersion = async () => {
    if (!isCurrent() || versionsScopeRef.current !== scope || !deleteTarget) return
    if (deleteMode !== "workflow") {
      setDeleteTarget(null)
      return
    }
    setDeletingVersionId(deleteTarget.id)
    try {
      const result = await deleteStoryboardVersion(
        callBackend,
        projectId,
        episodeId,
        versionNodeId,
        deleteTarget.id
      )
      if (!isCurrent()) return
      toast.success("已删除版本")
      setVersions((current) =>
        current.filter((version) => version.id !== deleteTarget.id)
      )
      if (onWorkflowMutationCommitted) {
        onWorkflowMutationCommitted({
          ...result,
          action: "storyboard_version_deleted",
          projectId,
          episodeId,
          nodeId: versionNodeId,
          versionId: deleteTarget.id,
        })
      } else if (
        result.workflowVersion !== undefined &&
        result.workflowVersion !== null
      ) {
        onWorkflowVersionChanged?.(result.workflowVersion)
      }
      if (!isCurrent()) return
      setDeleteTarget(null)
      await onChanged(null, "deleted")
    } catch (error) {
      if (!isCurrent()) return
      toast.error(errMsg(error, "删除版本失败"))
    } finally {
      if (isCurrent()) setDeletingVersionId(null)
    }
  }

  const handleVersionPointerDown = (
    event: React.PointerEvent<HTMLDivElement>,
    version: StoryboardVersion,
    label: string,
    previewSrc: string | null
  ) => {
    if (!isCurrent() || !onCreateCanvasAsset || !previewSrc || event.button !== 0) return
    event.preventDefault()
    event.stopPropagation()

    versionDragCleanupRef.current?.()
    const dragToken = {}
    versionDragRef.current = {
      scope,
      token: dragToken,
      version,
      sourceNode: node,
      screenPosition: { x: event.clientX, y: event.clientY },
      label,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      previewSrc,
      active: false,
    }

    let clearDragListeners: () => void = () => undefined
    const handlePointerMove = (pointerEvent: PointerEvent) => {
      const drag = versionDragRef.current
      if (!isCurrent() || !drag || drag.token !== dragToken || drag.pointerId !== pointerEvent.pointerId) return
      const distance = Math.hypot(
        pointerEvent.clientX - drag.startX,
        pointerEvent.clientY - drag.startY
      )
      const active = drag.active || distance >= 8
      const nextDrag: StoryboardVersionDragState = {
        ...drag,
        screenPosition: { x: pointerEvent.clientX, y: pointerEvent.clientY },
        active,
      }
      versionDragRef.current = nextDrag
      if (active) {
        pointerEvent.preventDefault()
        setVersionDragPreview({
          x: pointerEvent.clientX,
          y: pointerEvent.clientY,
          label: drag.label,
          previewSrc: drag.previewSrc,
          kind: storyboardVersionPreviewKind(drag.version),
        })
      }
    }

    const handlePointerEnd = (pointerEvent: PointerEvent) => {
      const drag = versionDragRef.current
      if (!isCurrent() || !drag || drag.token !== dragToken || drag.pointerId !== pointerEvent.pointerId) return
      clearDragListeners()
      versionDragCleanupRef.current = null
      versionDragRef.current = null
      setVersionDragPreview(null)
      if (pointerEvent.type === "pointercancel") return
      if (!drag.active) {
        setVersionPreviewRequest((current) => ({
          versionId: drag.version.id,
          token: (current?.token ?? 0) + 1,
        }))
        return
      }
      pointerEvent.preventDefault()
      void onCreateCanvasAsset({
        version: drag.version,
        sourceNode: drag.sourceNode,
        label: drag.label,
        screenPosition: {
          x: pointerEvent.clientX,
          y: pointerEvent.clientY,
        },
      })
    }

    clearDragListeners = () => {
      window.removeEventListener("pointermove", handlePointerMove)
      window.removeEventListener("pointerup", handlePointerEnd)
      window.removeEventListener("pointercancel", handlePointerEnd)
    }

    const cleanupDrag = () => {
      clearDragListeners()
      if (versionDragRef.current?.token === dragToken) {
        versionDragRef.current = null
        if (isCurrent()) setVersionDragPreview(null)
      }
      if (versionDragCleanupRef.current === cleanupDrag) {
        versionDragCleanupRef.current = null
      }
    }
    versionDragCleanupRef.current = cleanupDrag
    window.addEventListener("pointermove", handlePointerMove, {
      passive: false,
    })
    window.addEventListener("pointerup", handlePointerEnd, { passive: false })
    window.addEventListener("pointercancel", handlePointerEnd, {
      passive: false,
    })
  }

  return (
    <>
      <div className="min-h-0 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-[11px] text-gray-500 dark:text-gray-400">
            {loading ? "正在加载版本..." : `${displayVersions.length} 个版本`}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 gap-1 text-[11px]"
            disabled={loading}
            onClick={() => void loadVersions()}
          >
            <RefreshCcw className={cn("size-3", loading && "animate-spin")} />
            刷新
          </Button>
        </div>
        {displayVersions.length === 0 ? (
          <div className="rounded-lg border border-dashed border-gray-300/80 px-4 py-10 text-center text-sm text-gray-400 dark:border-white/15">
            {loading ? "正在加载版本..." : "暂无版本，运行节点后会生成。"}
          </div>
        ) : (
          <div
            className={cn(
              "[scrollbar-gutter:stable] overflow-y-auto pr-1",
              compact ? "max-h-52" : "max-h-[min(62dvh,620px)]"
            )}
          >
            <div className="grid [grid-template-columns:repeat(auto-fill,minmax(198px,1fr))] gap-3">
              {displayVersions.map((version, index) => {
                const active = version.id === activeVersionId
                const previewSrc = storyboardVersionPreviewSrc(version)
                const label = storyboardVersionDisplayLabel(
                  index,
                  displayVersions.length
                )
                const deleteDisabled =
                  deleteMode !== "workflow" ||
                  active ||
                  displayVersions.length <= 1 ||
                  switchingVersionId !== null ||
                  deletingVersionId !== null
                const deleteTip =
                  deleteMode !== "workflow"
                    ? "项目资产版本请在资产页管理"
                    : active
                      ? "当前版本不能删除"
                      : displayVersions.length <= 1
                        ? "至少保留一个版本"
                        : "删除版本"
                return (
                  <article
                    key={version.id}
                    className={cn(
                      "rounded-xl border p-3 text-left transition-colors",
                      active
                        ? "border-emerald-200 bg-emerald-50/70 dark:border-emerald-900/60 dark:bg-emerald-950/20"
                        : "border-gray-200/70 bg-white/70 hover:border-indigo-200 hover:bg-indigo-50/45 dark:border-white/10 dark:bg-white/[0.035] dark:hover:border-indigo-900/60 dark:hover:bg-indigo-950/20"
                    )}
                    onContextMenu={(event) =>
                      openVersionContextMenu(event, version, label)
                    }
                  >
                    <div
                      role={
                        onCreateCanvasAsset && previewSrc ? "button" : undefined
                      }
                      tabIndex={
                        onCreateCanvasAsset && previewSrc ? 0 : undefined
                      }
                      aria-label={
                        onCreateCanvasAsset && previewSrc
                          ? `${label} 预览或拖到画布`
                          : undefined
                      }
                      className={cn(
                        "relative",
                        onCreateCanvasAsset && previewSrc
                          ? "cursor-grab active:cursor-grabbing"
                          : null
                      )}
                      onPointerDownCapture={(event) =>
                        handleVersionPointerDown(
                          event,
                          version,
                          label,
                          previewSrc
                        )
                      }
                      onKeyDown={(event) => {
                        if (!isCurrent()) return
                        if (!onCreateCanvasAsset) return
                        if (!previewSrc) return
                        if (event.key !== "Enter" && event.key !== " ") return
                        event.preventDefault()
                        event.stopPropagation()
                        setVersionPreviewRequest((current) => ({
                          versionId: version.id,
                          token: (current?.token ?? 0) + 1,
                        }))
                      }}
                    >
                      <UnifiedMediaFrame
                        src={previewSrc}
                        alt={label}
                        title={label}
                        kind={storyboardVersionPreviewKind(version)}
                        className="aspect-video rounded-md"
                        fit="cover"
                        interactive={
                          !onCreateCanvasAsset && Boolean(previewSrc)
                        }
                        showActions={Boolean(previewSrc)}
                        downloadSource={mediaDownloadSource(version.media)}
                        fallbackMinHeight={false}
                        previewOpenSignal={
                          versionPreviewRequest?.versionId === version.id
                            ? versionPreviewRequest.token
                            : 0
                        }
                      />
                    </div>
                    <div className="mt-2 flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
                          {label}
                        </div>
                        <div className="mt-1 truncate text-[11px] text-gray-500 dark:text-gray-400">
                          {formatVersionDateTime(
                            (
                              version as StoryboardVersion & {
                                completedAt?: unknown
                                updatedAt?: unknown
                              }
                            ).completedAt ??
                              (
                                version as StoryboardVersion & {
                                  updatedAt?: unknown
                                }
                              ).updatedAt ??
                              version.createdAt
                          ) || "未知时间"}
                        </div>
                      </div>
                      {active ? (
                        <span
                          className="grid size-5 shrink-0 place-items-center rounded-full bg-emerald-600 text-white"
                          aria-label="当前版本"
                          title="当前版本"
                        >
                          <CheckCircle2 className="size-3" />
                        </span>
                      ) : null}
                    </div>
                    <div className="mt-2.5 flex items-center justify-end gap-1.5">
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className={cn(
                          "h-7 min-w-[52px] rounded-full border px-2.5 text-[11px] font-medium shadow-none transition-colors",
                          active
                            ? "border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-50 disabled:opacity-100 dark:border-emerald-400/30 dark:bg-emerald-400/10 dark:text-emerald-200 dark:hover:bg-emerald-400/10"
                            : "border-indigo-200 bg-white text-indigo-700 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-800 disabled:opacity-55 dark:border-indigo-400/25 dark:bg-indigo-400/10 dark:text-indigo-200 dark:hover:border-indigo-300/45 dark:hover:bg-indigo-400/15 dark:hover:text-indigo-100",
                          switchingVersionId === version.id &&
                            "border-indigo-300 bg-indigo-50 text-indigo-800 dark:border-indigo-300/45 dark:bg-indigo-400/15 dark:text-indigo-100"
                        )}
                        disabled={
                          active ||
                          switchingVersionId !== null ||
                          deletingVersionId !== null
                        }
                        onClick={() => void handleUseVersion(version)}
                      >
                        {switchingVersionId === version.id ? (
                          <Loader2 className="size-3 animate-spin" />
                        ) : active ? (
                          <CheckCircle2 className="size-3" />
                        ) : null}
                        {active
                          ? "当前"
                          : switchingVersionId === version.id
                            ? "切换中"
                            : "切换"}
                      </Button>
                      {deleteMode === "workflow" ? (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="inline-flex">
                              <Button
                                type="button"
                                size="icon"
                                variant="ghost"
                                aria-label="删除版本"
                                className={cn(
                                  "size-8 rounded-full text-rose-600 hover:bg-rose-50 hover:text-rose-700 dark:text-rose-300 dark:hover:bg-rose-950/30 dark:hover:text-rose-200",
                                  deleteDisabled
                                    ? "text-gray-400 hover:bg-transparent hover:text-gray-400 disabled:opacity-60 dark:text-gray-500 dark:hover:text-gray-500"
                                    : ""
                                )}
                                disabled={deleteDisabled}
                                onClick={(event) => {
                                  if (!isCurrent()) return
                                  event.stopPropagation()
                                  setDeleteTarget(version)
                                }}
                              >
                                {deletingVersionId === version.id ? (
                                  <Loader2 className="size-4 animate-spin" />
                                ) : (
                                  <Trash2 className="size-4" />
                                )}
                              </Button>
                            </span>
                          </TooltipTrigger>
                          <TooltipContent>{deleteTip}</TooltipContent>
                        </Tooltip>
                      ) : null}
                    </div>
                  </article>
                )
              })}
            </div>
          </div>
        )}
      </div>
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="删除版本"
        description={
          deleteTarget
            ? "确认删除这个版本？当前版本和最后一个版本会被保护。"
            : undefined
        }
        confirmLabel="删除版本"
        loadingLabel="删除中"
        loading={Boolean(deletingVersionId)}
        onConfirm={handleConfirmDeleteVersion}
        onCancel={() => { if (isCurrent()) setDeleteTarget(null) }}
      />
      {versionContextMenu &&
      contextMenuVersion &&
      onCopyCanvasAsset &&
      typeof document !== "undefined"
        ? createPortal(
            <div
              data-version-context-menu="true"
              className="pointer-events-auto fixed z-[620] min-w-36 overflow-hidden rounded-lg border border-gray-200 bg-white p-1 text-[12px] text-gray-700 shadow-2xl shadow-gray-950/20 dark:border-white/10 dark:bg-[#18181b] dark:text-gray-100"
              style={{ left: versionContextMenu.x, top: versionContextMenu.y }}
              onContextMenu={(event) => {
                event.preventDefault()
                event.stopPropagation()
              }}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => event.stopPropagation()}
            >
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
                onClick={() => {
                  if (!isCurrent()) return
                  void onCopyCanvasAsset({
                    version: contextMenuVersion,
                    sourceNode: node,
                    label: versionContextMenu.label,
                  })
                  setVersionContextMenu(null)
                }}
              >
                <Copy className="size-3.5" />
                复制资产
              </button>
            </div>,
            document.body
          )
        : null}
      {versionDragPreview && typeof document !== "undefined"
        ? createPortal(
            <div
              className="pointer-events-none fixed z-[520] overflow-hidden rounded-lg border border-white/70 bg-white/90 p-1 shadow-2xl shadow-gray-950/25 dark:border-white/15 dark:bg-[#202025]/95"
              style={{
                left: versionDragPreview.x,
                top: versionDragPreview.y,
                transform: "translate(-50%, -50%)",
              }}
            >
              <UnifiedMediaFrame
                src={versionDragPreview.previewSrc}
                alt={versionDragPreview.label}
                title={versionDragPreview.label}
                kind={versionDragPreview.kind}
                className="h-24 w-36 rounded-md"
                fit="cover"
                fallbackMinHeight={false}
              />
            </div>,
            document.body
          )
        : null}
    </>
  )
}

