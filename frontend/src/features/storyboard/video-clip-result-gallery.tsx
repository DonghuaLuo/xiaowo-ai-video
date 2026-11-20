import { createPortal } from "react-dom"
import {
  CheckCircle2,
  Copy,
  ImageIcon,
  Loader2,
  Trash2,
  Video,
  X,
} from "lucide-react"
import { cn } from "@/lib/utils"
import {
  UnifiedMediaFrame,
  mediaDownloadSource,
} from "@/shared/unified-media-frame"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import type { VideoClipResults } from "./use-video-clip-results"
import type { VideoClipResultDrag } from "./use-video-clip-result-drag"
export function VideoClipResultGallery({
  library,
  drag,
  handleDeleteResults,
}: {
  library: Pick<
    VideoClipResults,
    | "selectedResultIds"
    | "resultSelectionMode"
    | "clearAllResultSelection"
    | "someResultsSelected"
    | "resultMutationBusy"
    | "deletingResults"
    | "results"
    | "selectedResultIdSet"
    | "deletingResultIdSet"
    | "openResultContextMenu"
    | "toggleResultSelected"
    | "loadingResults"
    | "resultMenu"
    | "activeResult"
    | "handleCopyResultAsset"
    | "copyingResultId"
    | "selectAllResults"
    | "cancelResultSelection"
  >
  drag: Pick<
    VideoClipResultDrag,
    | "handleResultPointerDown"
    | "handleResultClickCapture"
    | "handleResultClick"
    | "resultDragPreview"
  >
  handleDeleteResults: (ids: string[]) => Promise<void>
}) {
  return (
    <>
      <div
        className="relative flex min-h-0 flex-col self-stretch overflow-hidden border-t border-gray-200/80 bg-gray-50/75 p-4 lg:border-t-0 lg:border-l dark:border-white/10 dark:bg-black/20"
        style={{ contain: "size" }}
      >
        <div className="mb-3 flex h-7 items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
            <span>已选 {library.selectedResultIds.length}</span>
            {library.resultSelectionMode ? (
              <button
                type="button"
                className="h-6 rounded-[5px] border border-gray-200 bg-white px-2 text-[11px] text-gray-500 transition hover:border-gray-300 hover:bg-gray-50 hover:text-gray-700 dark:border-white/10 dark:bg-white/[0.04] dark:text-gray-400 dark:hover:border-white/20 dark:hover:bg-white/[0.08] dark:hover:text-gray-200"
                onClick={library.clearAllResultSelection}
              >
                取消全选
              </button>
            ) : null}
          </div>
          {library.someResultsSelected ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 gap-1.5 px-2 text-xs text-rose-600 hover:bg-rose-50 hover:text-rose-700 dark:text-rose-300 dark:hover:bg-rose-500/10 dark:hover:text-rose-200"
              disabled={library.resultMutationBusy}
              onClick={() =>
                void handleDeleteResults(library.selectedResultIds)
              }
            >
              {library.deletingResults ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Trash2 className="size-3.5" />
              )}
              删除
            </Button>
          ) : null}
        </div>
        <div className="grid min-h-0 flex-1 [scrollbar-gutter:stable] grid-cols-2 content-start gap-3 overflow-y-auto pr-1">
          {library.results.map((result) => {
            const selected = library.selectedResultIdSet.has(result.id)
            const deleting = library.deletingResultIdSet.has(result.id)
            return (
              <div
                key={result.id}
                className={cn(
                  "group cursor-grab rounded-md transition hover:-translate-y-0.5",
                  deleting && "pointer-events-none opacity-55"
                )}
                onPointerDownCapture={(event) =>
                  drag.handleResultPointerDown(event, result)
                }
                onClickCapture={(event) =>
                  drag.handleResultClickCapture(event, result)
                }
                onClick={(event) => drag.handleResultClick(event, result)}
                onContextMenuCapture={(event) =>
                  library.openResultContextMenu(event, result)
                }
              >
                <div className="relative">
                  {result.kind === "video" ? (
                    <div className="aspect-square overflow-hidden rounded-md bg-black">
                      <video
                        src={result.src}
                        className="pointer-events-none h-full w-full object-cover"
                        muted
                        playsInline
                        preload="metadata"
                        draggable={false}
                      />
                    </div>
                  ) : (
                    <UnifiedMediaFrame
                      src={result.src}
                      alt={result.title}
                      title={result.title}
                      kind={result.kind}
                      className="aspect-square rounded-md"
                      fit="cover"
                      interactive
                      showActions
                      downloadSource={mediaDownloadSource(result.media)}
                    />
                  )}
                  <span
                    className={cn(
                      "pointer-events-none absolute top-2 left-2 grid size-6 place-items-center rounded-full border border-white/80 bg-white/90 shadow-sm backdrop-blur dark:border-white/15 dark:bg-black/55",
                      result.kind === "video"
                        ? "text-indigo-600 dark:text-indigo-300"
                        : "text-emerald-600 dark:text-emerald-300"
                    )}
                  >
                    {result.kind === "video" ? (
                      <Video className="size-3.5" />
                    ) : (
                      <ImageIcon className="size-3.5" />
                    )}
                  </span>
                  {library.resultSelectionMode ? (
                    <span
                      data-video-clip-result-control
                      className="absolute top-2 right-2 z-20"
                      onPointerDown={(event) => event.stopPropagation()}
                      onClick={(event) => event.stopPropagation()}
                    >
                      <Checkbox
                        checked={selected}
                        disabled={library.deletingResults}
                        aria-label="选择剪辑结果"
                        className="border-white/80 bg-white/90 shadow-sm dark:border-white/70 dark:bg-black/55"
                        onCheckedChange={(checked) =>
                          library.toggleResultSelected(
                            result.id,
                            checked === true
                          )
                        }
                      />
                    </span>
                  ) : null}
                </div>
              </div>
            )
          })}
          {library.loadingResults ? (
            <div className="col-span-2 rounded-lg border border-dashed border-gray-300/80 px-3 py-8 text-center text-xs text-gray-500 dark:border-white/15 dark:text-gray-400">
              正在加载...
            </div>
          ) : !library.results.length ? (
            <div className="col-span-2 rounded-lg border border-dashed border-gray-300/80 px-3 py-8 text-center text-xs text-gray-500 dark:border-white/15 dark:text-gray-400">
              剪切或截帧后显示结果
            </div>
          ) : null}
        </div>
      </div>
    </>
  )
}

export function VideoClipResultOverlays({
  library,
  drag,
  handleDeleteResults,
}: {
  library: Pick<
    VideoClipResults,
    | "selectedResultIds"
    | "resultSelectionMode"
    | "clearAllResultSelection"
    | "someResultsSelected"
    | "resultMutationBusy"
    | "deletingResults"
    | "results"
    | "selectedResultIdSet"
    | "deletingResultIdSet"
    | "openResultContextMenu"
    | "toggleResultSelected"
    | "loadingResults"
    | "resultMenu"
    | "activeResult"
    | "handleCopyResultAsset"
    | "copyingResultId"
    | "selectAllResults"
    | "cancelResultSelection"
  >
  drag: Pick<
    VideoClipResultDrag,
    | "handleResultPointerDown"
    | "handleResultClickCapture"
    | "handleResultClick"
    | "resultDragPreview"
  >
  handleDeleteResults: (ids: string[]) => Promise<void>
}) {
  const activeResult = library.activeResult
  return (
    <>
      {library.resultMenu && activeResult && typeof document !== "undefined"
        ? createPortal(
            <div
              data-video-clip-result-menu="true"
              className="pointer-events-auto fixed z-[620] min-w-36 overflow-hidden rounded-lg border border-gray-200 bg-white p-1 text-[12px] text-gray-700 shadow-2xl shadow-gray-950/20 dark:border-white/10 dark:bg-[#18181b] dark:text-gray-100"
              style={{ left: library.resultMenu.x, top: library.resultMenu.y }}
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
                onClick={() => void library.handleCopyResultAsset(activeResult)}
                disabled={
                  library.copyingResultId === activeResult.id ||
                  library.deletingResultIdSet.has(activeResult.id)
                }
              >
                {library.copyingResultId === activeResult.id ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Copy className="size-3.5" />
                )}
                复制资产
              </button>
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
                onClick={library.selectAllResults}
                disabled={
                  library.deletingResults ||
                  !library.results.length ||
                  library.selectedResultIds.length === library.results.length
                }
              >
                <CheckCircle2 className="size-3.5" />
                全选
              </button>
              {library.resultSelectionMode ? (
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
                  onClick={library.cancelResultSelection}
                  disabled={library.deletingResults}
                >
                  <X className="size-3.5" />
                  取消
                </button>
              ) : null}
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-rose-600 transition-colors hover:bg-rose-50 dark:text-rose-300 dark:hover:bg-rose-500/10"
                onClick={() => void handleDeleteResults([activeResult.id])}
                disabled={
                  library.resultMutationBusy ||
                  library.deletingResultIdSet.has(activeResult.id)
                }
              >
                {library.deletingResultIdSet.has(activeResult.id) ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Trash2 className="size-3.5" />
                )}
                删除
              </button>
            </div>,
            document.body
          )
        : null}
      {drag.resultDragPreview && typeof document !== "undefined"
        ? createPortal(
            <div
              className="pointer-events-none fixed z-[520] w-32 -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-lg border border-white/70 bg-white/90 p-1.5 shadow-2xl shadow-black/25 backdrop-blur dark:border-white/15 dark:bg-black/75"
              style={{
                left: drag.resultDragPreview.x,
                top: drag.resultDragPreview.y,
              }}
            >
              <UnifiedMediaFrame
                src={drag.resultDragPreview.result.src}
                alt={drag.resultDragPreview.result.title}
                title={drag.resultDragPreview.result.title}
                kind={drag.resultDragPreview.result.kind}
                className="aspect-square rounded-md"
                fit="cover"
                interactive={false}
                showActions={false}
              />
              <div
                className={cn(
                  "pointer-events-none absolute top-3 left-3 grid size-6 place-items-center rounded-full border border-white/80 bg-white/90 shadow-sm dark:border-white/15 dark:bg-black/55",
                  drag.resultDragPreview.result.kind === "video"
                    ? "text-indigo-600 dark:text-indigo-300"
                    : "text-emerald-600 dark:text-emerald-300"
                )}
              >
                {drag.resultDragPreview.result.kind === "video" ? (
                  <Video className="size-3.5" />
                ) : (
                  <ImageIcon className="size-3.5" />
                )}
              </div>
              <div className="mt-1 truncate text-center text-[11px] text-gray-700 dark:text-gray-200">
                {drag.resultDragPreview.result.title}
              </div>
            </div>,
            document.body
          )
        : null}
    </>
  )
}
