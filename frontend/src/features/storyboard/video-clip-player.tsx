import { Maximize2, Pause, Play } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { VideoClipCropOverlay } from "./video-clip-crop-overlay"
import type { VideoClipEditor } from "./use-video-clip-editor"
export function VideoClipPlayer({
  editor,
}: {
  editor: Pick<
    VideoClipEditor,
    | "hasSourceVideoSize"
    | "videoFrameRef"
    | "videoFrameStyle"
    | "editingSource"
    | "videoRef"
    | "playing"
    | "framePreviewVisible"
    | "previewSrc"
    | "isMuted"
    | "handleVideoLoadedMetadata"
    | "handleVideoCanPlay"
    | "finishPlayTransition"
    | "handleVideoPause"
    | "handleVideoEnded"
    | "handleVideoTimeUpdate"
    | "playTransitioning"
    | "cropEnabled"
    | "cropDisplayWidth"
    | "cropDisplayHeight"
    | "sourceVideoWidth"
    | "sourceVideoHeight"
    | "cropBox"
    | "duration"
    | "loadingInfo"
    | "setCropBox"
    | "setMainVideoPreviewSignal"
    | "handlePlayToggle"
    | "previewLoading"
  >
}) {
  const playButtonClass =
    "size-10 cursor-pointer rounded-full border border-indigo-500 bg-indigo-600 p-0 text-white shadow-sm shadow-indigo-500/20 transition-all hover:border-indigo-600 hover:bg-indigo-700 hover:shadow-md hover:shadow-indigo-500/25 active:scale-95 active:bg-indigo-800 disabled:cursor-not-allowed dark:border-indigo-400/70 dark:bg-indigo-500 dark:hover:border-indigo-300 dark:hover:bg-indigo-400 dark:active:bg-indigo-600"
  return (
    <>
      <div
        className={cn(
          "relative flex w-full flex-none items-center justify-center overflow-hidden",
          editor.hasSourceVideoSize ? "" : "min-h-[280px]"
        )}
      >
        <div
          ref={editor.videoFrameRef}
          className={cn(
            "group/video relative overflow-hidden bg-black shadow-sm",
            editor.hasSourceVideoSize ? "" : "aspect-video min-h-[280px] w-full"
          )}
          style={editor.hasSourceVideoSize ? editor.videoFrameStyle : undefined}
        >
          <video
            key={editor.editingSource.id}
            ref={editor.videoRef}
            src={editor.editingSource.src}
            className={cn(
              "pointer-events-none absolute inset-0 h-full w-full transition-opacity duration-150",
              editor.hasSourceVideoSize ? "object-fill" : "object-contain",
              editor.playing ||
                !editor.framePreviewVisible ||
                !editor.previewSrc
                ? "opacity-100"
                : "opacity-0"
            )}
            controls={false}
            disablePictureInPicture
            muted={editor.isMuted}
            playsInline
            preload="auto"
            tabIndex={-1}
            onLoadedMetadata={editor.handleVideoLoadedMetadata}
            onCanPlay={editor.handleVideoCanPlay}
            onPlaying={editor.finishPlayTransition}
            onPause={editor.handleVideoPause}
            onEnded={editor.handleVideoEnded}
            onTimeUpdate={editor.handleVideoTimeUpdate}
          />
          {editor.framePreviewVisible &&
          editor.previewSrc &&
          (!editor.playing || editor.playTransitioning) ? (
            <img
              src={editor.previewSrc}
              alt="当前帧预览"
              className={cn(
                "absolute inset-0 h-full w-full transition-opacity duration-150",
                editor.hasSourceVideoSize ? "object-fill" : "object-contain"
              )}
              draggable={false}
            />
          ) : null}
          {editor.cropEnabled ? (
            <VideoClipCropOverlay
              displayWidth={editor.cropDisplayWidth}
              displayHeight={editor.cropDisplayHeight}
              videoWidth={editor.sourceVideoWidth}
              videoHeight={editor.sourceVideoHeight}
              cropBox={editor.cropBox}
              disabled={!editor.duration || editor.loadingInfo}
              onCropChange={editor.setCropBox}
            />
          ) : null}
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            className="absolute top-3 right-3 z-[40] grid size-8 place-items-center rounded-full border border-white/15 bg-black/55 p-0 text-white opacity-0 shadow-sm backdrop-blur-sm transition group-hover/video:opacity-100 hover:bg-black/75 hover:text-white focus:opacity-100 focus:ring-2 focus:ring-white/70"
            aria-label="放大播放"
            onClick={() =>
              editor.setMainVideoPreviewSignal((current) => current + 1)
            }
          >
            <Maximize2 className="size-3.5" />
          </Button>
          <Button
            type="button"
            size="icon-sm"
            className={cn(
              "absolute right-3 bottom-3 z-[40]",
              playButtonClass,
              editor.playing
                ? "opacity-0 group-hover/video:opacity-100"
                : "opacity-100"
            )}
            disabled={!editor.duration}
            onClick={editor.handlePlayToggle}
          >
            {editor.playing ? (
              <Pause className="size-4 fill-current" />
            ) : (
              <Play className="ml-0.5 size-4 fill-current" />
            )}
          </Button>
          {editor.previewLoading && !editor.playing ? (
            <div className="absolute top-3 left-3 rounded-full bg-black/55 px-2.5 py-1 text-[11px] text-white backdrop-blur">
              取帧中
            </div>
          ) : null}
        </div>
      </div>
    </>
  )
}
