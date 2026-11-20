import { useProjectSettings } from "@/features/project-settings/use-project-settings"
import { ProjectStyleSettings } from "@/features/project-settings/project-style-settings"

import { AlertTriangle, ImagePlus, Loader2, Save, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

import { sourceLanguageOptions } from "@/features/styles/catalog"

import type { ProjectRow } from "@/features/projects/types"

import { cn } from "@/lib/utils"

import { pickLocalImageFile } from "@/shared/image-picker"

import { PageHeader, SectionPanel } from "@/shared/page-shell"
import { ScrollArea } from "@/components/ui/scroll-area"
import { UnifiedMediaFrame } from "@/shared/unified-media-frame"

export function ProjectSettingsPage({
  project,
  onBack,
  onProjectSaved,
}: {
  project: ProjectRow
  onBack: () => void
  onProjectSaved: (projectId: string, patch: Partial<ProjectRow>) => void
}) {
  const editor = useProjectSettings({ project, onProjectSaved })
  const {
    projectTitleDraft,
    setProjectTitleDraft,
    style,
    sourceLanguage,
    setSourceLanguage,
    episodeTargetUnits,
    setEpisodeTargetUnits,
    assetExtractionTargetUnits,
    setAssetExtractionTargetUnits,
    storyboardRhythmMultiplier,
    setStoryboardRhythmMultiplier,
    storyboardClipMaxSeconds,
    setStoryboardClipMaxSeconds,
    projectCoverPreview,
    videoGenerationDebugBlockEnabled,
    setVideoGenerationDebugBlockEnabled,
    storyboardConsistencyReportEnabled,
    setStoryboardConsistencyReportEnabled,
    savingProjectSettings,
    hasUnsavedProjectSettings,
    projectVideoRatioOption,
    handleProjectCoverSelected,
    handleClearProjectCover,
    handleSaveProjectSettings,
    handleDiscardProjectSettings,
  } = editor
  const clipMaxOptions = Array.from({ length: 26 }, (_, index) => index + 5)

  return (
    <>
      <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <PageHeader eyebrow="Project Settings" title="项目设置" onBack={onBack} />
        {hasUnsavedProjectSettings ? (
          <div className="border-b border-indigo-100/80 bg-white/90 px-7 py-2.5 text-gray-700 shadow-sm shadow-indigo-950/[0.04] backdrop-blur-xl dark:border-white/10 dark:bg-[#202025]/90 dark:text-gray-200">
            <div className="mx-auto flex max-w-[1120px] flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-medium">
                <AlertTriangle className="size-4 shrink-0 text-indigo-500 dark:text-indigo-300" />
                <span>项目信息已修改，是否保存？</span>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-8 border-gray-200/80 bg-white/70 px-3 text-gray-600 hover:border-indigo-500 hover:bg-indigo-500 hover:text-white dark:border-white/10 dark:bg-white/[0.04] dark:text-gray-300 dark:hover:border-white/15 dark:hover:bg-white/[0.08] dark:hover:text-white"
                  onClick={handleDiscardProjectSettings}
                  disabled={savingProjectSettings}
                >
                  放弃修改
                </Button>
                <Button
                  type="button"
                  size="sm"
                  className="h-8 gap-1.5 bg-indigo-600 px-3 text-white shadow-sm shadow-indigo-950/10 hover:bg-indigo-500 dark:bg-indigo-500 dark:text-white dark:hover:bg-indigo-400"
                  onClick={() => void handleSaveProjectSettings()}
                  disabled={savingProjectSettings}
                >
                  {savingProjectSettings ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : (
                    <Save className="size-3.5" />
                  )}
                  保存
                </Button>
              </div>
            </div>
          </div>
        ) : null}
        <ScrollArea className="min-h-0 flex-1">
          <div className="mx-auto max-w-[1120px] space-y-5 px-7 pt-6 pb-20">
            <SectionPanel eyebrow="Basic" title="基本信息">
              <div className="grid gap-2.5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
                <label className="block min-w-0">
                  <span className="mb-1.5 block text-xs font-medium text-gray-500 dark:text-gray-400">
                    项目名称
                  </span>
                  <Input
                    value={projectTitleDraft}
                    onChange={(event) => setProjectTitleDraft(event.target.value)}
                    placeholder="输入项目名称"
                    className="h-9 bg-white/65 font-medium dark:bg-white/[0.04]"
                  />
                </label>
                <div className="flex h-9 flex-wrap items-center gap-2">
                  <span
                    data-basic-meta="video-ratio"
                    className="inline-flex h-9 shrink-0 items-center gap-2 rounded-md border border-gray-200/80 bg-white/65 px-3 text-sm shadow-sm shadow-gray-950/[0.02] dark:border-white/10 dark:bg-white/[0.04]"
                  >
                    <span className="size-1.5 rounded-full bg-cyan-500 shadow-[0_0_0_3px_rgba(6,182,212,0.12)]" />
                    <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                      视频比例
                    </span>
                    <span className="font-semibold whitespace-nowrap text-gray-900 dark:text-gray-100">
                      {projectVideoRatioOption.name}
                    </span>
                  </span>
                </div>
              </div>
              <div className="mt-4 grid gap-4 md:grid-cols-[minmax(0,1fr)_220px_220px]">
                <fieldset>
                  <legend className="mb-2 block text-xs font-medium text-gray-500 dark:text-gray-400">
                    语言地区
                  </legend>
                  <div className="flex flex-wrap gap-2">
                    {sourceLanguageOptions.map((option) => (
                      <label
                        key={option.id}
                        className={cn(
                          "inline-flex min-w-[112px] cursor-pointer flex-col rounded-lg border px-3 py-2 transition-colors",
                          sourceLanguage === option.id
                            ? "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
                            : "border-gray-200/70 bg-white/65 text-gray-500 hover:border-indigo-200 hover:text-gray-950 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400 dark:hover:text-gray-50"
                        )}
                      >
                        <input
                          type="radio"
                          name="projectSourceLanguage"
                          value={option.id}
                          checked={sourceLanguage === option.id}
                          onChange={() => setSourceLanguage(option.id)}
                          className="sr-only"
                        />
                        <span className="text-sm font-semibold">{option.label}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
                <label className="block">
                  <span className="mb-2 block text-xs font-medium text-gray-500 dark:text-gray-400">
                    每集分割字数
                  </span>
                  <Input
                    type="number"
                    min={1}
                    step={1}
                    value={episodeTargetUnits}
                    onChange={(event) => setEpisodeTargetUnits(event.target.value)}
                    className="h-9 bg-white/70 dark:bg-white/[0.04]"
                  />
                </label>
                <label className="block">
                  <span className="mb-2 block text-xs font-medium text-gray-500 dark:text-gray-400">
                    资产拆分字数
                  </span>
                  <Input
                    type="number"
                    min={1}
                    step={1}
                    value={assetExtractionTargetUnits}
                    onChange={(event) =>
                      setAssetExtractionTargetUnits(event.target.value)
                    }
                    className="h-9 bg-white/70 dark:bg-white/[0.04]"
                  />
                </label>
              </div>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div className="block min-w-0">
                  <span className="mb-2 block text-xs font-medium text-gray-500 dark:text-gray-400">分镜节奏</span>
                  <Select value={storyboardRhythmMultiplier} onValueChange={setStoryboardRhythmMultiplier}>
                    <SelectTrigger aria-label="分镜节奏" className="w-full bg-white/70 dark:bg-[#24242a]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent
                      className="w-[var(--radix-select-trigger-width)]"
                      hideScrollButtons
                      viewportClassName="ai-video-scrollbar h-auto max-h-72 w-full overflow-y-auto overscroll-contain [scrollbar-gutter:stable]"
                    >
                      {Array.from({ length: 11 }, (_, index) => (1 + index / 10).toFixed(1)).map((value) => (
                        <SelectItem key={value} value={value} className="py-2.5">{value} 倍</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <span className="mt-1 block text-xs text-gray-500">用于估算对白语速和镜头时长；分镜脚本卡可单独设置。</span>
                </div>
                <div className="block min-w-0">
                  <span className="mb-2 block text-xs font-medium text-gray-500 dark:text-gray-400">镜头组时长上限</span>
                  <Select value={storyboardClipMaxSeconds} onValueChange={setStoryboardClipMaxSeconds}>
                    <SelectTrigger aria-label="镜头组时长上限" className="w-full bg-white/70 dark:bg-[#24242a]">
                      <SelectValue placeholder="选择时长上限">{storyboardClipMaxSeconds} 秒</SelectValue>
                    </SelectTrigger>
                    {/* 由视口独立滚动，避免上下箭头动态显隐撑高菜单。 */}
                    <SelectContent
                      className="w-[min(32rem,calc(100vw-2rem))]"
                      hideScrollButtons
                      viewportClassName="ai-video-scrollbar h-auto max-h-72 w-full overflow-y-auto overscroll-contain [scrollbar-gutter:stable]"
                    >
                      {clipMaxOptions.map((seconds) => (
                        <SelectItem key={seconds} value={String(seconds)} className="py-2.5">
                          {seconds} 秒
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <span className="mt-1 block text-xs text-gray-500">镜头分组时，每组正式预估时长不超过此值。</span>
                </div>
              </div>
              <div
                role="button"
                tabIndex={0}
                className="relative mt-4 flex min-h-[260px] cursor-pointer flex-col items-center justify-center gap-3 overflow-hidden rounded-md border border-dashed border-indigo-300 bg-indigo-50/60 p-5 text-center text-indigo-700 transition-colors hover:bg-indigo-50 focus-visible:ring-2 focus-visible:ring-indigo-400/60 focus-visible:outline-none dark:border-indigo-900/60 dark:bg-indigo-950/20 dark:text-indigo-300 dark:hover:bg-indigo-950/30"
                onClick={async () => {
                  const file = await pickLocalImageFile("上传项目封面")
                  if (file) handleProjectCoverSelected(file)
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault()
                    void (async () => {
                      const file = await pickLocalImageFile("上传项目封面")
                      if (file) handleProjectCoverSelected(file)
                    })()
                  }
                }}
              >
                {projectCoverPreview ? (
                  <>
                    <UnifiedMediaFrame
                      src={projectCoverPreview}
                      alt="项目封面"
                      title="项目封面"
                      className="absolute inset-0 rounded-none border-0"
                      interactive={false}
                      showActions={false}
                    />
                    <span className="absolute inset-0 bg-gradient-to-t from-black/10 via-transparent to-black/10" />
                    <button
                      type="button"
                      aria-label="移除项目封面"
                      className="absolute top-2 right-2 grid size-7 place-items-center rounded-full bg-black/55 text-white backdrop-blur-sm transition-colors hover:bg-black/70"
                      onClick={(event) => {
                        event.preventDefault()
                        event.stopPropagation()
                        handleClearProjectCover()
                      }}
                    >
                      <X className="size-3.5" />
                    </button>
                  </>
                ) : (
                  <>
                    <ImagePlus className="size-6" />
                    <span className="text-sm font-semibold">上传项目封面</span>
                    <span className="max-w-[180px] truncate text-xs opacity-75">
                      支持 png / jpg / webp
                    </span>
                  </>
                )}
              </div>
            </SectionPanel>
            <ProjectStyleSettings style={style} />
            <SectionPanel eyebrow="Advanced" title="高级设置">
              <label className="flex min-h-16 cursor-pointer items-center justify-between gap-4 rounded-lg border border-gray-200/70 bg-white/65 px-4 py-3 transition-colors hover:border-indigo-200 hover:bg-white/90 dark:border-white/10 dark:bg-white/[0.035] dark:hover:bg-white/[0.06]">
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-gray-900 dark:text-gray-100">
                    分镜脚本与分镜图一致性检查报告
                  </span>
                  <span className="mt-1 block text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                    开启后，新生成的分镜图会调用当前项目的智能体模型自动核对分镜脚本，并生成参考报告。可在分镜脚本最大化编辑页的图片下方查看，报告不阻止继续使用图片。
                  </span>
                </span>
                <input
                  type="checkbox"
                  role="switch"
                  checked={storyboardConsistencyReportEnabled}
                  disabled={savingProjectSettings}
                  onChange={(event) => setStoryboardConsistencyReportEnabled(event.target.checked)}
                  className="peer sr-only"
                />
                <span className="relative h-6 w-11 shrink-0 rounded-full bg-gray-300 transition-colors after:absolute after:left-0.5 after:top-0.5 after:size-5 after:rounded-full after:bg-white after:shadow-sm after:transition-transform peer-checked:bg-indigo-600 peer-checked:after:translate-x-5 peer-focus-visible:ring-2 peer-focus-visible:ring-indigo-500 peer-focus-visible:ring-offset-2 dark:bg-white/20 dark:peer-checked:bg-indigo-500" />
              </label>
              <label className="mt-3 flex min-h-16 cursor-pointer items-center justify-between gap-4 rounded-lg border border-gray-200/70 bg-white/65 px-4 py-3 transition-colors hover:border-indigo-200 hover:bg-white/90 dark:border-white/10 dark:bg-white/[0.035] dark:hover:bg-white/[0.06]">
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-gray-900 dark:text-gray-100">
                    视频生成阻断调试模式
                  </span>
                  <span className="mt-1 block text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                    开启后视频生成只记录即将发送给供应商 API
                    的请求数据，不真正请求视频模型；其他环节照常执行并自动写日志。
                  </span>
                </span>
                <input
                  type="checkbox"
                  checked={videoGenerationDebugBlockEnabled}
                  onChange={(event) =>
                    setVideoGenerationDebugBlockEnabled(event.target.checked)
                  }
                  className="sr-only peer"
                />
                <span className="relative h-6 w-11 shrink-0 rounded-full bg-gray-300 transition-colors after:absolute after:left-0.5 after:top-0.5 after:size-5 after:rounded-full after:bg-white after:shadow-sm after:transition-transform peer-checked:bg-indigo-600 peer-checked:after:translate-x-5 dark:bg-white/20 dark:peer-checked:bg-indigo-500" />
              </label>
            </SectionPanel>
          </div>
        </ScrollArea>
      </main>
    </>
  )
}
