import {
  ArrowRight,
  Clock,
  Crop,
  Flag,
  ImagePlus,
  Loader2,
  RefreshCcw,
  RotateCcw,
  Scissors,
  Volume2,
  VolumeX,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { formatClipTime } from "./video-clip-model"
import { VideoClipRangeTimeline } from "./video-clip-timeline"
import type { VideoClipEditor } from "./use-video-clip-editor"
import type { VideoClipResults } from "./use-video-clip-results"
export function VideoClipControls({
  editor,
  library,
  handleRestoreMainVideo,
  handleTrim,
  handleExtractFrame,
}: {
  editor: Pick<
    VideoClipEditor,
    | "duration"
    | "startHms"
    | "handleTimeInputChange"
    | "loadingInfo"
    | "endHms"
    | "resetTimeRange"
    | "selectedDuration"
    | "cropEnabled"
    | "handleCropEnabledChange"
    | "sourceVideoWidth"
    | "sourceVideoHeight"
    | "resetCropBox"
    | "cropBox"
    | "fps"
    | "currentTime"
    | "rangeStart"
    | "rangeEnd"
    | "handleCurrentTimeChange"
    | "handleRangeChange"
    | "toggleMute"
    | "isMuted"
    | "volume"
    | "handleVolumeChange"
    | "editingSourceIsRoot"
    | "frameTotal"
    | "safeCurrentFrameIndex"
    | "frameControlsDisabled"
    | "handlePreviousFrame"
    | "frameStep"
    | "setFrameStep"
    | "lastFrameIndex"
    | "handleNextFrame"
    | "handleJumpToTailFrame"
  >
  library: Pick<VideoClipResults, "resultMutationBusy" | "workingAction">
  handleRestoreMainVideo: () => void
  handleTrim: () => Promise<void>
  handleExtractFrame: () => Promise<void>
}) {
  const iconControlButtonClass =
    "h-8 w-8 cursor-pointer border-0 bg-transparent p-0 text-gray-600 shadow-none transition-all hover:bg-transparent hover:text-indigo-600 active:scale-95 active:bg-transparent active:text-indigo-700 disabled:cursor-not-allowed dark:bg-transparent dark:text-gray-300 dark:hover:bg-transparent dark:hover:text-indigo-300 dark:active:bg-transparent dark:active:text-indigo-200"
  const inlineResetIconButtonClass =
    "inline-flex h-6 cursor-pointer items-center justify-center gap-1 rounded-[5px] border border-gray-200 bg-white px-1.5 text-[11px] text-gray-500 shadow-none transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 active:scale-95 active:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 aria-disabled:cursor-not-allowed aria-disabled:opacity-50 dark:border-white/10 dark:bg-white/[0.04] dark:text-gray-400 dark:hover:border-indigo-400/40 dark:hover:bg-indigo-500/10 dark:hover:text-indigo-300 dark:active:text-indigo-200"
  return (
    <>
      {editor.duration > 0 ? (
        <>
          <div className="flex flex-shrink-0 items-center gap-3 text-xs">
            <div className="flex items-center gap-2">
              <div
                className="flex items-center gap-1"
                aria-label="剪切开始时间"
              >
                <Flag className="size-3.5 text-emerald-500" />
                <input
                  type="text"
                  value={String(editor.startHms.hours).padStart(2, "0")}
                  onChange={editor.handleTimeInputChange("start", "hours", 999)}
                  disabled={editor.loadingInfo}
                  aria-label="剪切开始时间小时"
                  className="h-5 w-9 rounded border border-gray-200 bg-white px-1 text-center text-[12px] dark:border-white/10 dark:bg-white/[0.04]"
                />
                <span className="text-gray-400">:</span>
                <input
                  type="text"
                  value={String(editor.startHms.minutes).padStart(2, "0")}
                  onChange={editor.handleTimeInputChange(
                    "start",
                    "minutes",
                    59
                  )}
                  disabled={editor.loadingInfo}
                  aria-label="剪切开始时间分钟"
                  className="h-5 w-9 rounded border border-gray-200 bg-white px-1 text-center text-[12px] dark:border-white/10 dark:bg-white/[0.04]"
                />
                <span className="text-gray-400">:</span>
                <input
                  type="text"
                  value={String(editor.startHms.seconds).padStart(2, "0")}
                  onChange={editor.handleTimeInputChange(
                    "start",
                    "seconds",
                    59
                  )}
                  disabled={editor.loadingInfo}
                  aria-label="剪切开始时间秒"
                  className="h-5 w-9 rounded border border-gray-200 bg-white px-1 text-center text-[12px] dark:border-white/10 dark:bg-white/[0.04]"
                />
              </div>
              <div
                className="flex items-center gap-1 text-gray-300 dark:text-gray-600"
                aria-hidden="true"
              >
                <span className="h-px w-3 bg-current" />
                <ArrowRight className="size-3.5" />
                <span className="h-px w-3 bg-current" />
              </div>
              <div
                className="flex items-center gap-1"
                aria-label="剪切结束时间"
              >
                <Flag className="size-3.5 text-rose-500" />
                <input
                  type="text"
                  value={String(editor.endHms.hours).padStart(2, "0")}
                  onChange={editor.handleTimeInputChange("end", "hours", 999)}
                  disabled={editor.loadingInfo}
                  aria-label="剪切结束时间小时"
                  className="h-5 w-9 rounded border border-gray-200 bg-white px-1 text-center text-[12px] dark:border-white/10 dark:bg-white/[0.04]"
                />
                <span className="text-gray-400">:</span>
                <input
                  type="text"
                  value={String(editor.endHms.minutes).padStart(2, "0")}
                  onChange={editor.handleTimeInputChange("end", "minutes", 59)}
                  disabled={editor.loadingInfo}
                  aria-label="剪切结束时间分钟"
                  className="h-5 w-9 rounded border border-gray-200 bg-white px-1 text-center text-[12px] dark:border-white/10 dark:bg-white/[0.04]"
                />
                <span className="text-gray-400">:</span>
                <input
                  type="text"
                  value={String(editor.endHms.seconds).padStart(2, "0")}
                  onChange={editor.handleTimeInputChange("end", "seconds", 59)}
                  disabled={editor.loadingInfo}
                  aria-label="剪切结束时间秒"
                  className="h-5 w-9 rounded border border-gray-200 bg-white px-1 text-center text-[12px] dark:border-white/10 dark:bg-white/[0.04]"
                />
              </div>
            </div>
            <div className="flex items-center gap-1.5 whitespace-nowrap">
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={() => {
                      if (editor.duration > 0) editor.resetTimeRange()
                    }}
                    aria-disabled={editor.duration === 0}
                    aria-label="重置时间"
                    className={inlineResetIconButtonClass}
                  >
                    <Clock className="size-3.5" />
                    <span>重置</span>
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" sideOffset={6}>
                  <p>重置时间</p>
                </TooltipContent>
              </Tooltip>
              <span className="text-gray-400 dark:text-gray-500">
                {formatClipTime(editor.selectedDuration)}
              </span>
            </div>
            <div className="ml-auto flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
              <button
                type="button"
                className={cn(
                  inlineResetIconButtonClass,
                  editor.cropEnabled &&
                    "border-indigo-300 bg-indigo-50 text-indigo-600 dark:border-indigo-400/40 dark:bg-indigo-500/10 dark:text-indigo-300"
                )}
                disabled={!editor.duration}
                aria-pressed={editor.cropEnabled}
                onClick={() =>
                  editor.handleCropEnabledChange(!editor.cropEnabled)
                }
              >
                <Crop className="size-3.5" />
                网格裁剪
              </button>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={() => {
                      if (
                        editor.sourceVideoWidth > 0 &&
                        editor.sourceVideoHeight > 0
                      )
                        editor.resetCropBox()
                    }}
                    aria-disabled={
                      editor.sourceVideoWidth === 0 ||
                      editor.sourceVideoHeight === 0
                    }
                    aria-label="重置裁剪范围"
                    className={inlineResetIconButtonClass}
                  >
                    <RefreshCcw className="size-3.5" />
                    <span>重置</span>
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" sideOffset={6}>
                  <p>重置裁剪范围</p>
                </TooltipContent>
              </Tooltip>
              <span className="whitespace-nowrap">
                {editor.cropBox.width}x{editor.cropBox.height} @ (
                {editor.cropBox.x}, {editor.cropBox.y})
              </span>
            </div>
          </div>
          <VideoClipRangeTimeline
            duration={editor.duration || 0}
            fps={editor.fps}
            currentTime={Math.min(
              editor.currentTime,
              editor.duration || editor.currentTime
            )}
            rangeStart={editor.rangeStart}
            rangeEnd={editor.rangeEnd}
            disabled={!editor.duration || editor.loadingInfo}
            onSeek={editor.handleCurrentTimeChange}
            onRangeChange={editor.handleRangeChange}
          />
          <div className="-mx-2 flex flex-shrink-0 items-center justify-between gap-3">
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                onClick={editor.toggleMute}
                disabled={editor.duration === 0}
                aria-label={editor.isMuted ? "取消静音" : "静音"}
                className={iconControlButtonClass}
              >
                {editor.isMuted ? (
                  <VolumeX className="size-4" />
                ) : (
                  <Volume2 className="size-4" />
                )}
              </Button>
              <Slider
                value={[editor.isMuted ? 0 : editor.volume]}
                min={0}
                max={1}
                step={0.1}
                onValueChange={editor.handleVolumeChange}
                disabled={editor.duration === 0}
                className="w-16 cursor-pointer data-[disabled]:cursor-not-allowed [&_[data-slot=slider-thumb]]:cursor-pointer [&_[data-slot=slider-thumb]]:active:scale-95 [&_[data-slot=slider-thumb]]:active:ring-4"
              />
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              {!editor.editingSourceIsRoot ? (
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  className="h-8 gap-1.5 px-3 text-xs"
                  onClick={handleRestoreMainVideo}
                >
                  <RotateCcw className="size-3.5" />
                  恢复
                </Button>
              ) : null}
              <span className="text-xs whitespace-nowrap text-gray-500 dark:text-gray-400">
                {editor.duration > 0 && editor.frameTotal > 0
                  ? `${editor.safeCurrentFrameIndex + 1}/${editor.frameTotal}`
                  : "--/--"}
              </span>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-8 px-3 text-xs"
                disabled={
                  editor.frameControlsDisabled ||
                  editor.safeCurrentFrameIndex <= 0
                }
                onClick={editor.handlePreviousFrame}
              >
                上一帧
              </Button>
              <label className="inline-flex h-8 items-center gap-1 rounded-[5px] border border-gray-200 bg-white px-2 text-xs text-gray-500 dark:border-white/10 dark:bg-white/[0.04] dark:text-gray-400">
                <input
                  type="text"
                  value={String(editor.frameStep)}
                  disabled={editor.frameControlsDisabled}
                  onChange={(event) => {
                    const raw = event.target.value.replace(/[^\d]/g, "")
                    const next = Math.max(1, Math.min(999, Number(raw || 1)))
                    editor.setFrameStep(next)
                  }}
                  className="h-5 w-10 bg-transparent text-center text-xs text-gray-700 outline-none disabled:cursor-not-allowed dark:text-gray-200"
                />
                <span>帧</span>
              </label>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-8 px-3 text-xs"
                disabled={
                  editor.frameControlsDisabled ||
                  editor.safeCurrentFrameIndex >= editor.lastFrameIndex
                }
                onClick={editor.handleNextFrame}
              >
                下一帧
              </Button>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-8 px-3 text-xs"
                disabled={
                  editor.frameControlsDisabled ||
                  editor.safeCurrentFrameIndex >= editor.lastFrameIndex
                }
                onClick={editor.handleJumpToTailFrame}
              >
                到尾帧
              </Button>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-8 gap-1.5 px-3 text-xs"
                disabled={
                  editor.frameControlsDisabled || library.resultMutationBusy
                }
                onClick={() => void handleExtractFrame()}
              >
                {library.workingAction === "frame" ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <ImagePlus className="size-3.5" />
                )}
                截图
              </Button>
              <Button
                type="button"
                size="sm"
                className="h-8 gap-1.5 px-3 text-xs"
                disabled={!editor.duration || library.resultMutationBusy}
                onClick={() => void handleTrim()}
              >
                {library.workingAction === "trim" ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Scissors className="size-3.5" />
                )}
                剪切视频
              </Button>
            </div>
          </div>
        </>
      ) : null}
    </>
  )
}
