import { Scissors } from "lucide-react"
import { useBackend } from "@/hooks/useBackend"
import {
  UnifiedMediaFrame,
  mediaDownloadSource,
} from "@/shared/unified-media-frame"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  cleanVideoClipSourceTitle,
  type VideoClipCanvasResult,
  type VideoClipDialogSource,
} from "./video-clip-model"
import { useVideoClipEditor } from "./use-video-clip-editor"
import { useVideoClipResults } from "./use-video-clip-results"
import { useVideoClipResultDrag } from "./use-video-clip-result-drag"
import { VideoClipPlayer } from "./video-clip-player"
import { VideoClipControls } from "./video-clip-controls"
import {
  VideoClipResultGallery,
  VideoClipResultOverlays,
} from "./video-clip-result-gallery"
export function VideoClipDialog({
  projectId,
  episodeId,
  source,
  onClose,
  onCopyAsset,
  onDropToCanvas,
}: {
  projectId: string
  episodeId: string
  source: VideoClipDialogSource
  onClose: () => void
  onCopyAsset: (result: VideoClipCanvasResult) => Promise<void> | void
  onDropToCanvas: (
    result: VideoClipCanvasResult,
    screenPosition: { x: number; y: number }
  ) => Promise<void> | void
}) {
  const backend = useBackend()
  const library = useVideoClipResults({
    backend,
    projectId,
    episodeId,
    source,
    onCopyAsset,
  })
  const editor = useVideoClipEditor({
    backend,
    projectId,
    episodeId,
    source,
    loadClipResults: library.loadClipResults,
  })
  const drag = useVideoClipResultDrag({
    activation: library.loadClipResults,
    resultSelectionMode: library.resultSelectionMode,
    deletingResults: library.deletingResults,
    selectedResultIdSet: library.selectedResultIdSet,
    toggleResultSelected: library.toggleResultSelected,
    onEditResult: (result) => {
      library.closeResultMenu()
      editor.editResult(result)
    },
    onDropToCanvas,
  })
  const handleRestoreMainVideo = () => {
    library.closeResultMenu()
    editor.handleRestoreMainVideo()
  }
  const handleDeleteResults = (ids: string[]) =>
    library.handleDeleteResults(ids, (deleted) => {
      if (
        editor.editingSource.resultId &&
        deleted.includes(editor.editingSource.resultId)
      )
        handleRestoreMainVideo()
    })
  const handleTrim = () => library.trim(editor.createTrimRequest())
  const handleExtractFrame = () =>
    library.extractFrame(editor.createFrameRequest())
  const sourceDisplayTitle = cleanVideoClipSourceTitle(source.title)

  return (
    <>
      <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
        <DialogContent
          data-video-clip-dialog="true"
          className="grid max-h-[min(90dvh,860px)] !w-[min(1140px,calc(100vw-1.5rem))] !max-w-none grid-rows-[auto,minmax(0,1fr)] gap-0 overflow-hidden p-0"
        >
          <DialogHeader className="border-b border-gray-200/80 px-5 py-4 dark:border-white/10">
            <DialogTitle className="flex items-center gap-2 text-base">
              <Scissors className="size-4 text-indigo-500" />
              视频剪辑
            </DialogTitle>
            {sourceDisplayTitle ? (
              <DialogDescription className="truncate">
                {sourceDisplayTitle}
              </DialogDescription>
            ) : null}
          </DialogHeader>
          <div className="grid min-h-0 items-stretch gap-0 overflow-hidden lg:grid-cols-[minmax(0,1fr)_280px]">
            <div className="flex min-h-0 min-w-0 flex-col gap-3 p-5">
              <VideoClipPlayer editor={editor} />
              <VideoClipControls
                editor={editor}
                library={library}
                handleRestoreMainVideo={handleRestoreMainVideo}
                handleTrim={handleTrim}
                handleExtractFrame={handleExtractFrame}
              />
            </div>
            <VideoClipResultGallery
              library={library}
              drag={drag}
              handleDeleteResults={handleDeleteResults}
            />
          </div>
          <UnifiedMediaFrame
            src={editor.editingSource.src}
            alt={editor.editingSource.title}
            title={editor.editingSource.title}
            kind="video"
            className="hidden"
            interactive
            showActions
            downloadSource={mediaDownloadSource(editor.editingSource.media)}
            previewOpenSignal={editor.mainVideoPreviewSignal}
          />
        </DialogContent>
      </Dialog>
      <VideoClipResultOverlays
        library={library}
        drag={drag}
        handleDeleteResults={handleDeleteResults}
      />
    </>
  )
}
export type {
  VideoClipCanvasResult,
  VideoClipDialogSource,
} from "./video-clip-model"

export {
  mediaAssetInputFile,
  videoClipMediaKind,
  videoClipResultInputFile,
} from "./video-clip-model"
