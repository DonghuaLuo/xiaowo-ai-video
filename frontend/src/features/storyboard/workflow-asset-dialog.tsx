import type { WorkflowAssetPicker } from "./use-workflow-asset-picker"
import {
  activeAssetMedia,
  assetDesignPromptForCanvas,
  defaultAssetMediaVersionId,
  EXTERNAL_MEDIA_PURPOSE_OPTIONS,
  externalMediaTitleFieldLabel,
  externalMediaTitleFieldPlaceholder,
  mediaPurposeUsesVoiceStyle,
  mediaPurposeVoiceStyleLabel,
} from "./workflow-canvas-asset-model"
import { canvasProjectAssetTypeLabel } from "./workflow-canvas-assets"

export type WorkflowAssetDialogProps = {
  picker: WorkflowAssetPicker
  savingAsset: boolean
  handleAddAssetToCanvas: () => Promise<void>
  backendReady: boolean
}

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { mediaPreviewSrc } from "@/shared/media"
import {
  mediaDownloadSource,
  UnifiedMediaFrame,
} from "@/shared/unified-media-frame"
import { CheckCircle2, ImagePlus, Loader2, Search, Video } from "lucide-react"

export function WorkflowAssetDialog({
  picker, savingAsset, handleAddAssetToCanvas, backendReady,
}: WorkflowAssetDialogProps) {
  const {
    assetDraft, activeAddAssetConfig, addAssetKinds, setAssetDraft,
    handlePickExternalMediaFile, assetDraftMediaPreview, assetDraftMediaKind,
    assetDraftHasDuplicateProjectName, assetDraftDuplicateNameType, assetQuery,
    assetRows, selectedAssetIds, assetPickerLoading, filteredAssetRows,
    handleAssetPickerScroll, visibleAssetRows, selectedAssetIdSet,
    toggleAssetSelection, hasMoreAssetRows, assetDraftRequiresMediaFile,
  } = picker
  return (
    <Dialog
      open={Boolean(assetDraft)}
      onOpenChange={(open) => {
        if (!open && !savingAsset) setAssetDraft(null)
      }}
    >
      {assetDraft && activeAddAssetConfig ? (
        <DialogContent className="grid max-h-[min(90dvh,920px)] !w-[min(1180px,calc(100vw-1.5rem))] !max-w-none grid-rows-[auto,minmax(0,1fr),auto] overflow-hidden sm:!max-w-none">
          <DialogHeader>
            <DialogTitle>{activeAddAssetConfig.title}</DialogTitle>
            <DialogDescription>
              {activeAddAssetConfig.sourceType === "asset"
                ? "可一次选择多个资产生成画布图片节点。添加后通过画布拖线接入分镜脚本、分镜单元或视频生成。"
                : "图片可仅填写名称创建空资产。添加后通过画布拖线接入分镜脚本、分镜单元或视频生成。"}
            </DialogDescription>
          </DialogHeader>
          <div className="grid min-h-[min(62dvh,620px)] [scrollbar-gutter:stable] auto-rows-max content-start gap-4 overflow-y-auto py-1 pr-1">
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-gray-200/70 bg-white/65 p-1 dark:border-white/10 dark:bg-white/[0.035]">
              {addAssetKinds.map(([kind, config]) => {
                const selected = assetDraft.kind === kind
                return (
                  <Button
                    key={kind}
                    type="button"
                    size="sm"
                    variant={selected ? "secondary" : "ghost"}
                    className="h-8 px-3 text-xs"
                    onClick={() => {
                      picker.selectKind(kind)
                    }}
                    disabled={savingAsset}
                  >
                    {config.tabLabel}
                  </Button>
                )
              })}
            </div>

            {activeAddAssetConfig.sourceType === "media" ? (
              <div className="grid gap-3">
                <div className="grid gap-2">
                  <div className="text-xs font-semibold text-gray-600 dark:text-gray-300">
                    资产类型
                  </div>
                  <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
                    {EXTERNAL_MEDIA_PURPOSE_OPTIONS.map((option) => {
                      const selected = assetDraft.mediaPurpose === option.value
                      return (
                        <button
                          key={option.value}
                          type="button"
                          className={cn(
                            "rounded-lg border px-3 py-2 text-center text-xs font-semibold transition-colors",
                            selected
                              ? "border-indigo-300 bg-indigo-50 text-indigo-800 dark:border-indigo-800 dark:bg-indigo-950/35 dark:text-indigo-200"
                              : "border-gray-200/70 bg-white/70 text-gray-600 hover:border-indigo-200 hover:bg-indigo-50/50 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-300 dark:hover:border-indigo-900/60 dark:hover:bg-indigo-950/20"
                          )}
                          onClick={() =>
                            picker.selectPurpose(option.value)
                          }
                          disabled={savingAsset}
                        >
                          {option.label}
                        </button>
                      )
                    })}
                  </div>
                </div>
                <button
                  type="button"
                  className={cn(
                    "group relative overflow-hidden rounded-xl border border-dashed border-indigo-200 bg-indigo-50/35 text-indigo-700 transition-colors hover:border-indigo-300 hover:bg-indigo-50/55 focus-visible:ring-2 focus-visible:ring-indigo-400/50 focus-visible:outline-none dark:border-indigo-900/60 dark:bg-indigo-950/15 dark:text-indigo-200 dark:hover:border-indigo-700 dark:hover:bg-indigo-950/25",
                    assetDraftMediaPreview
                      ? "border-solid bg-white/70 dark:bg-white/[0.035]"
                      : "grid min-h-64 place-items-center"
                  )}
                  onClick={() => void handlePickExternalMediaFile()}
                  disabled={savingAsset}
                >
                  {assetDraftMediaPreview ? (
                    <>
                      <UnifiedMediaFrame
                        src={assetDraftMediaPreview}
                        alt={assetDraft.mediaFile?.name || "导入媒体预览"}
                        title={assetDraft.mediaFile?.name || "导入媒体"}
                        kind={assetDraftMediaKind === "audio" ? undefined : assetDraftMediaKind}
                        className="h-64 rounded-none border-0"
                        fit="contain"
                        interactive={false}
                        showActions={false}
                      />
                      <span className="pointer-events-none absolute inset-0 grid place-items-center bg-black/0 text-sm font-semibold text-white opacity-0 transition group-hover:bg-black/35 group-hover:opacity-100">
                        {assetDraft.mediaPurpose === "video"
                          ? "更换视频"
                          : "更换图片"}
                      </span>
                    </>
                  ) : (
                    <span className="flex flex-col items-center justify-center gap-2 px-4 text-center">
                      {assetDraft.mediaPurpose === "video" ? (
                        <Video className="size-8" />
                      ) : (
                        <ImagePlus className="size-8" />
                      )}
                      <span className="text-sm font-semibold">
                        {assetDraft.mediaPurpose === "video"
                          ? "点击添加视频"
                          : "点击添加图片"}
                      </span>
                    </span>
                  )}
                </button>
                {assetDraft.mediaPurpose === "video" ? (
                  <p className="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                    支持 MP4、MOV、WebM、MKV、AVI、M4V。超过 30 分钟仅保留前 30
                    分钟；非 MP4 自动转换为 MP4。
                  </p>
                ) : null}
                <div className="grid gap-1.5">
                  <div className="text-xs font-semibold text-gray-600 dark:text-gray-300">
                    {externalMediaTitleFieldLabel(assetDraft.mediaPurpose)}
                  </div>
                  <Input
                    value={assetDraft.title}
                    onChange={(event) =>
                      setAssetDraft((current) =>
                        current
                          ? {
                              ...current,
                              title: event.target.value,
                            }
                          : current
                      )
                    }
                    placeholder={externalMediaTitleFieldPlaceholder(
                      assetDraft.mediaPurpose
                    )}
                    className="h-9 rounded-lg border-gray-200/80 bg-white/70 text-[12px] dark:border-white/10 dark:bg-white/[0.035]"
                    disabled={savingAsset}
                  />
                  {assetDraftHasDuplicateProjectName &&
                  assetDraftDuplicateNameType ? (
                    <div className="text-[11px] text-amber-600 dark:text-amber-300">
                      项目中已存在同名
                      {canvasProjectAssetTypeLabel(assetDraftDuplicateNameType)}
                      ， 请更换名称。
                    </div>
                  ) : null}
                </div>
                {mediaPurposeUsesVoiceStyle(assetDraft.mediaPurpose) ? (
                  <div className="grid gap-1.5">
                    <div className="text-xs font-semibold text-gray-600 dark:text-gray-300">
                      {mediaPurposeVoiceStyleLabel(assetDraft.mediaPurpose)}
                    </div>
                    <Textarea
                      value={assetDraft.voiceStyle}
                      onChange={(event) =>
                        setAssetDraft((current) =>
                          current
                            ? {
                                ...current,
                                voiceStyle: event.target.value,
                              }
                            : current
                        )
                      }
                      placeholder={`${mediaPurposeVoiceStyleLabel(assetDraft.mediaPurpose)} / 音色提示`}
                      className="min-h-20 resize-none rounded-lg border-gray-200/80 bg-white/70 text-[12px] dark:border-white/10 dark:bg-white/[0.035]"
                      disabled={savingAsset}
                    />
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="grid gap-4">
                <div className="flex flex-wrap items-center gap-3">
                  <div className="relative min-w-[240px] flex-1">
                    <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-gray-400" />
                    <Input
                      value={assetQuery}
                      onChange={(event) => {
                        picker.setQuery(event.target.value)
                      }}
                      placeholder={`搜索${activeAddAssetConfig.noun}名称 / 设计图提示词`}
                      className="h-9 rounded-md border-gray-200/80 bg-white/70 pl-9 text-[12px] dark:border-white/10 dark:bg-white/[0.035]"
                    />
                  </div>
                  <Badge variant="outline" className="rounded-full text-[11px]">
                    当前项目 {assetRows.length}
                  </Badge>
                  {selectedAssetIds.length ? (
                    <Badge className="rounded-full bg-indigo-600 text-[11px] text-white hover:bg-indigo-600">
                      已选 {selectedAssetIds.length}
                    </Badge>
                  ) : null}
                </div>
                {assetPickerLoading ? (
                  <div className="rounded-xl border border-gray-200/70 bg-white/70 px-4 py-12 text-center text-sm text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
                    正在加载{activeAddAssetConfig.noun}...
                  </div>
                ) : filteredAssetRows.length === 0 ? (
                  <div className="rounded-xl border border-gray-200/70 bg-white/70 px-4 py-12 text-center text-sm text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
                    没有匹配的{activeAddAssetConfig.noun}，请修改搜索词。
                  </div>
                ) : (
                  <div
                    className="max-h-[min(62dvh,620px)] [scrollbar-gutter:stable] overflow-y-auto pr-1"
                    onScroll={handleAssetPickerScroll}
                  >
                    <div className="grid [grid-template-columns:repeat(auto-fill,minmax(198px,1fr))] gap-3">
                      {visibleAssetRows.map((item) => {
                        const selected = selectedAssetIdSet.has(item.id)
                        const mediaVersionId =
                          assetDraft.selectedMediaVersionIds?.[item.id] ||
                          (assetDraft.selectedAssetId === item.id
                            ? assetDraft.selectedMediaVersionId
                            : "") ||
                          defaultAssetMediaVersionId(item)
                        const media = activeAssetMedia(item, mediaVersionId)
                        const mediaSrc = mediaPreviewSrc(media)
                        const hasDesign = Boolean(mediaSrc)
                        return (
                          <div
                            key={item.id}
                            role="button"
                            tabIndex={0}
                            aria-pressed={selected}
                            className={cn(
                              "rounded-xl border p-3 text-left transition-colors",
                              selected
                                ? "cursor-pointer border-indigo-200 bg-indigo-50/80 dark:border-indigo-900/60 dark:bg-indigo-950/25"
                                : "cursor-pointer border-gray-200/70 bg-white/70 hover:border-indigo-200 hover:bg-indigo-50/45 dark:border-white/10 dark:bg-white/[0.035] dark:hover:border-indigo-900/60 dark:hover:bg-indigo-950/20"
                            )}
                            onClick={() => {
                              toggleAssetSelection(item)
                            }}
                            onKeyDown={(event) => {
                              if (event.key !== "Enter" && event.key !== " ")
                                return
                              event.preventDefault()
                              toggleAssetSelection(item)
                            }}
                          >
                            {hasDesign ? (
                              <div className="group/asset-thumb relative overflow-hidden rounded-md border border-gray-200/70 dark:border-white/10">
                                <UnifiedMediaFrame
                                  src={mediaSrc}
                                  alt={`${item.name}${activeAddAssetConfig.noun}图`}
                                  title={item.name}
                                  className="aspect-video rounded-none border-0"
                                  downloadSource={mediaDownloadSource(media)}
                                  fallbackClassName={item.accent}
                                  fallbackMinHeight={false}
                                  interactive
                                  showActions
                                />
                                <div className="pointer-events-none absolute inset-0 grid place-items-center bg-black/20 opacity-0 transition-opacity group-focus-within/asset-thumb:opacity-100 group-hover/asset-thumb:opacity-100">
                                  <span className="grid size-8 place-items-center rounded-full bg-black/60 text-white shadow-sm backdrop-blur-sm">
                                    <Search className="size-4" />
                                  </span>
                                </div>
                              </div>
                            ) : null}
                            <div
                              className={cn(
                                "flex items-start justify-between gap-2",
                                hasDesign ? "mt-2" : ""
                              )}
                            >
                              <div className="min-w-0">
                                <div className="truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
                                  {item.name}
                                </div>
                                <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                                  {assetDesignPromptForCanvas(item) ||
                                    "暂无描述"}
                                </div>
                              </div>
                              {selected ? (
                                <span
                                  className="grid size-5 shrink-0 place-items-center rounded-full bg-indigo-600 text-white"
                                  aria-hidden
                                >
                                  <CheckCircle2 className="size-3" />
                                </span>
                              ) : null}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                    {hasMoreAssetRows ? (
                      <div className="mt-4 text-center text-[11px] text-gray-400 dark:text-gray-500">
                        继续向下滚动加载剩余{" "}
                        {filteredAssetRows.length - visibleAssetRows.length} 个
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setAssetDraft(null)}
              disabled={savingAsset}
            >
              取消
            </Button>
            <Button
              type="button"
              onClick={() => void handleAddAssetToCanvas()}
              disabled={
                !backendReady ||
                savingAsset ||
                (activeAddAssetConfig.sourceType === "asset" &&
                  selectedAssetIds.length === 0) ||
                (activeAddAssetConfig.sourceType === "media" &&
                  (!assetDraft.title.trim() ||
                    assetDraftHasDuplicateProjectName ||
                    Boolean(
                      assetDraftDuplicateNameType && assetPickerLoading
                    ) ||
                    (assetDraftRequiresMediaFile && !assetDraft.mediaFile)))
              }
            >
              {savingAsset ? (
                <Loader2 className="mr-2 size-4 animate-spin" />
              ) : null}
              {activeAddAssetConfig.sourceType === "asset" &&
              selectedAssetIds.length > 1
                ? `添加 ${selectedAssetIds.length} 个到画布`
                : "添加到画布"}
            </Button>
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  )
}
