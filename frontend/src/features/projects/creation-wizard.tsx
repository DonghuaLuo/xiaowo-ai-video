import { useEffect, useMemo, useState } from "react"
import {
  AlertTriangle,
  CheckCircle2,
  Star,
} from "lucide-react"

import {
  analyzeStyleImage,
  type InputImageFile,
} from "@/backend"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import {
  creationStyleModeTabs,
  styleTemplateOptions,
  videoRatioOptions,
} from "@/features/styles/catalog"
import { styleFilePayloadFromStyleTemplate } from "@/features/styles/media"
import type {
  CreationStyleMode,
  StyleCategory,
  StyleFilePayload,
} from "@/features/styles/types"
import type { ProjectRow } from "@/features/projects/types"
import {
  creationModelReadinessMessage,
  fallbackCreationOptions,
  MODEL_CONFIG_REQUIRED_MESSAGE,
  normalizeCreationOptions,
  type ProjectCreationOptions,
} from "@/features/projects/creation-options"
import { ModalShell } from "@/shared/page-shell"
import { imagePayloadPreviewSrc } from "@/shared/media"
import { isBackendFailure } from "@/shared/backend-result"
import {CustomStyleEditor,GeneralStyleTemplatePanel,StyleCategoryTabs,StyleModeTabs,StylePromptPreview,StyleTemplateGrid} from '@/features/settings/style-editors'
import {
  defaultVisualTypeTag,
  isGeneralStyleTemplate,
  normalizeVisualTypeTag,
  styleTemplatePrompt,
} from "@/features/styles/general-style"
import type { SettingsSection } from "@/navigation"
import { resolveStyleTemplateThumbnailUrl } from "@/utils/style-thumbnails"

const PROJECT_NAME_EXISTS_MESSAGE = "当前项目名称已经存在，请修改其他名字"
const CUSTOM_STYLE_REQUIRED_MESSAGE = "请上传风格参考图和风格描述"
function normalizeProjectName(value: string) {
  return value.trim().replace(/\s+/g, " ").toLocaleLowerCase()
}

export function CreateProjectWizard({
  onClose,
  onCreated,
  onConfigurePrerequisite,
  existingProjects = [],
}: {
  onClose: () => void
  onCreated: (project: ProjectRow) => void
  onConfigurePrerequisite: (
    section: SettingsSection,
    providerAction?: "add"
  ) => void
  existingProjects?: ProjectRow[]
}) {
  const { backendReady, callBackend } = useBackend()
  const [step, setStep] = useState(1)
  const [options, setOptions] = useState<ProjectCreationOptions>(
    fallbackCreationOptions
  )
  const [projectTitle, setProjectTitle] = useState("新故事版视频")
  const [titleError, setTitleError] = useState("")
  const [sourceLanguage, setSourceLanguage] = useState("zh-CN")
  const contentMode = "drama"
  const [aspectRatio, setAspectRatio] = useState("16:9")
  const [styleMode, setStyleMode] = useState<CreationStyleMode>("template")
  const [styleCategory, setStyleCategory] = useState<StyleCategory>("all")
  const [styleTemplate, setStyleTemplate] = useState(
    styleTemplateOptions[0]?.id ?? ""
  )
  const [stylePrompt, setStylePrompt] = useState(
    styleTemplateOptions[0]?.prompt ?? ""
  )
  const [styleVisualTypeTag, setStyleVisualTypeTag] = useState(
    defaultVisualTypeTag()
  )
  const [customStylePrompt, setCustomStylePrompt] = useState("")
  const [customCharacterStylePrompt, setCustomCharacterStylePrompt] =
    useState("")
  const [customCreatureStylePrompt, setCustomCreatureStylePrompt] =
    useState("")
  const [customStyleFile, setCustomStyleFile] =
    useState<StyleFilePayload | null>(null)
  const [analyzingStyle, setAnalyzingStyle] = useState(false)
  const [creating, setCreating] = useState(false)
  const [submitError, setSubmitError] = useState("")
  const [submitErrorTone, setSubmitErrorTone] = useState<"error" | "warning">(
    "error"
  )
  const presetStyleTemplates = useMemo(
    () =>
      options.styleTemplates.filter(
        (template) => template.category !== "favorite"
      ),
    [options.styleTemplates]
  )
  const favoriteStyleTemplates = useMemo(
    () =>
      options.styleTemplates.filter(
        (template) => template.category === "favorite"
      ),
    [options.styleTemplates]
  )
  const currentStyleTemplate = (
    styleMode === "favorite" ? favoriteStyleTemplates : presetStyleTemplates
  ).find((template) => template.id === styleTemplate)
  const generalStyleTemplate = presetStyleTemplates.find(isGeneralStyleTemplate)
  const currentStylePreviewPrompt =
    styleMode === "custom"
      ? ""
      : styleTemplatePrompt(
          currentStyleTemplate,
          "global",
          normalizeVisualTypeTag(styleVisualTypeTag, currentStyleTemplate)
        )
  const creationPresetStyleCategories = useMemo(
    () => [
      { id: "all" as const, label: "全部" },
      ...options.styleCategories.filter(
        (category) => category.id !== "all" && category.id !== "favorite"
      ),
    ],
    [options.styleCategories]
  )
  useEffect(() => {
    if (!backendReady) return
    let cancelled = false
    void (async () => {
      try {
        const result = await callBackend<
          ProjectCreationOptions | { success: false; message: string }
        >("get_project_creation_options")
        if (cancelled || isBackendFailure(result)) {
          return
        }
        const normalized = normalizeCreationOptions(result as ProjectCreationOptions)
        setOptions(normalized)
        const normalizedPresetStyles = normalized.styleTemplates.filter(
          (template) => template.category !== "favorite"
        )
        const defaults = normalized.defaults
        const nextStyleTemplate =
          defaults?.style_template_id ?? normalizedPresetStyles[0]?.id ?? ""
        const nextStyle = normalizedPresetStyles.find(
          (template) => template.id === nextStyleTemplate
        )
        setSourceLanguage(defaults?.source_language ?? "zh-CN")
        setAspectRatio(defaults?.aspect_ratio === "9:16" ? "9:16" : "16:9")
        setStyleTemplate(nextStyleTemplate)
        setStyleCategory("all")
        setStyleVisualTypeTag(defaultVisualTypeTag(nextStyle))
        setStylePrompt(
          styleTemplatePrompt(
            nextStyle,
            "global",
            defaultVisualTypeTag(nextStyle)
          )
        )
      } catch (error) {
        console.warn("加载创建项目选项失败，使用本地默认选项:", error)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [backendReady, callBackend])

  useEffect(() => {
    if (styleMode === "custom") return
    const templates =
      styleMode === "favorite" ? favoriteStyleTemplates : presetStyleTemplates
    const template = templates.find((item) => item.id === styleTemplate)
    if (isGeneralStyleTemplate(template)) {
      setStyleVisualTypeTag((current) =>
        normalizeVisualTypeTag(current, template)
      )
    }
    setStylePrompt(
      styleTemplatePrompt(template, "global", styleVisualTypeTag)
    )
  }, [
    favoriteStyleTemplates,
    presetStyleTemplates,
    styleMode,
    styleTemplate,
    styleVisualTypeTag,
  ])

  const stepTitle = step === 1 ? "基础信息" : "视觉风格"
  const isDuplicateTitleError = titleError === PROJECT_NAME_EXISTS_MESSAGE
  const modelConfigSubmitError =
    submitErrorTone === "warning" ? submitError : ""
  const clearSubmitError = () => {
    setSubmitError("")
    setSubmitErrorTone("error")
  }
  const showSubmitError = (
    message: string,
    tone: "error" | "warning" = "error"
  ) => {
    setSubmitErrorTone(tone)
    setSubmitError(message)
  }
  const refreshCreationOptions = async () => {
    if (!backendReady) {
      throw new Error("后端正在启动，请稍后再创建项目")
    }
    const result = await callBackend<
      ProjectCreationOptions | { success: false; message: string }
    >("get_project_creation_options")
    if (isBackendFailure(result)) {
      throw new Error(result.message || "读取全局模型配置失败")
    }
    const normalized = normalizeCreationOptions(result as ProjectCreationOptions)
    setOptions(normalized)
    return normalized
  }
  const handleConfigurePrerequisite = async () => {
    try {
      const latestOptions = await refreshCreationOptions()
      const providerCount = latestOptions.modelReadiness?.providerCount ?? 0
      onConfigurePrerequisite(
        providerCount > 0 ? "media" : "providers",
        providerCount > 0 ? undefined : "add"
      )
    } catch (error) {
      showSubmitError(
        error instanceof Error ? error.message : "读取全局模型配置失败",
        "warning"
      )
    }
  }
  const changeStyleCategory = (category: StyleCategory) => {
    setStyleMode("template")
    setStyleCategory(category)
    const nextTemplate =
      category === "all"
        ? (presetStyleTemplates.find(
            (template) => template.id === styleTemplate
          ) ?? presetStyleTemplates[0])
        : presetStyleTemplates.find(
            (template) => template.category === category
    )
    if (nextTemplate) {
      const nextVisualTypeTag = defaultVisualTypeTag(nextTemplate)
      setStyleTemplate(nextTemplate.id)
      setStyleVisualTypeTag(nextVisualTypeTag)
      setStylePrompt(
        styleTemplatePrompt(
          nextTemplate,
          "global",
          nextVisualTypeTag
        )
      )
    }
  }
  const changeStyleMode = (nextMode: CreationStyleMode) => {
    setStyleMode(nextMode)
    clearSubmitError()
    if (nextMode === "template") {
      setStyleCategory(styleCategory === "favorite" ? "all" : styleCategory)
      const nextTemplate =
        presetStyleTemplates.find(
          (template) => template.id === styleTemplate
        ) ?? presetStyleTemplates[0]
      if (nextTemplate) {
        const nextVisualTypeTag = defaultVisualTypeTag(nextTemplate)
        setStyleTemplate(nextTemplate.id)
        setStyleVisualTypeTag(nextVisualTypeTag)
        setStylePrompt(
          styleTemplatePrompt(
            nextTemplate,
            "global",
            nextVisualTypeTag
          )
        )
      }
      return
    }
    if (nextMode === "favorite") {
      setStyleCategory("favorite")
      const nextTemplate =
        favoriteStyleTemplates.find(
          (template) => template.id === styleTemplate
        ) ?? favoriteStyleTemplates[0]
      if (nextTemplate) {
        setStyleTemplate(nextTemplate.id)
        setStylePrompt(
          styleTemplatePrompt(
            nextTemplate,
            "global",
            styleVisualTypeTag
          )
        )
      }
    }
  }
  const handleCustomStyleFileSelected = (file: InputImageFile) => {
    clearSubmitError()
    setStyleMode("custom")
    setCustomStyleFile(file)
  }
  const copyCurrentStyleToCustom = async () => {
    if (!currentStyleTemplate) {
      showSubmitError("请先选择一个视觉风格")
      return
    }
    let preview: string | null = null
    try {
      preview = await resolveStyleTemplateThumbnailUrl(currentStyleTemplate)
    } catch (error) {
      console.warn("解析风格缩略图失败，继续复制风格引用:", error)
    }
    const styleFile = styleFilePayloadFromStyleTemplate(
      currentStyleTemplate,
      preview
    )
    if (!styleFile) {
      showSubmitError("当前风格没有可复制的参考图")
      return
    }
    setStyleMode("custom")
    setStyleCategory("all")
    const nextVisualTypeTag = normalizeVisualTypeTag(
      styleVisualTypeTag,
      currentStyleTemplate
    )
    setCustomStylePrompt(
      styleTemplatePrompt(
        currentStyleTemplate,
        "global",
        nextVisualTypeTag
      ).trim()
    )
    setCustomCharacterStylePrompt(
      styleTemplatePrompt(
        currentStyleTemplate,
        "character",
        nextVisualTypeTag
      ).trim()
    )
    setCustomCreatureStylePrompt(
      styleTemplatePrompt(
        currentStyleTemplate,
        "creature",
        nextVisualTypeTag
      ).trim()
    )
    setCustomStyleFile(styleFile)
    clearSubmitError()
  }
  const handleAnalyzeCustomStyle = async () => {
    if (!customStyleFile) {
      showSubmitError("请先上传风格参考图")
      return
    }
    setAnalyzingStyle(true)
    clearSubmitError()
    try {
      const result = await analyzeStyleImage(callBackend, customStyleFile)
      const description = result.style_description ?? ""
      setCustomStylePrompt(description)
      setCustomCharacterStylePrompt("")
      setCustomCreatureStylePrompt("")
    } catch (error) {
      showSubmitError(error instanceof Error ? error.message : "风格分析失败")
    } finally {
      setAnalyzingStyle(false)
    }
  }
  const handlePrimaryClick = async () => {
    const normalizedTitle = normalizeProjectName(projectTitle)
    if (step === 1 && !normalizedTitle) {
      setTitleError("请输入项目标题")
      return
    }
    if (
      step === 1 &&
      existingProjects.some(
        (project) => normalizeProjectName(project.name) === normalizedTitle
      )
    ) {
      setTitleError(PROJECT_NAME_EXISTS_MESSAGE)
      return
    }
    if (step < 2) {
      setStep(step + 1)
      return
    }
    if (
      styleMode === "custom" &&
      (!customStyleFile || !customStylePrompt.trim())
    ) {
      showSubmitError(CUSTOM_STYLE_REQUIRED_MESSAGE)
      return
    }
    setCreating(true)
    clearSubmitError()
    try {
      if (styleMode === "favorite" && !currentStyleTemplate) {
        throw new Error("暂无可用收藏风格")
      }
      const refreshedOptions = await refreshCreationOptions()
      const modelReadinessMessage =
        creationModelReadinessMessage(refreshedOptions)
      if (modelReadinessMessage) {
        showSubmitError(modelReadinessMessage, "warning")
        return
      }
      const selectedStyleVisualTypeTag =
        styleMode === "custom" || !isGeneralStyleTemplate(currentStyleTemplate)
          ? ""
          : normalizeVisualTypeTag(styleVisualTypeTag, currentStyleTemplate)
      const resolvedStylePrompt =
        styleMode === "custom"
          ? customStylePrompt.trim()
          : styleTemplatePrompt(
              currentStyleTemplate,
              "global",
              selectedStyleVisualTypeTag
            ) || stylePrompt
      const resolvedCharacterStylePrompt =
        styleMode === "custom"
          ? customCharacterStylePrompt.trim()
          : styleTemplatePrompt(
              currentStyleTemplate,
              "character",
              selectedStyleVisualTypeTag
            ).trim()
      const resolvedCreatureStylePrompt =
        styleMode === "custom"
          ? customCreatureStylePrompt.trim()
          : styleTemplatePrompt(
              currentStyleTemplate,
              "creature",
              selectedStyleVisualTypeTag
            ).trim()
      const result = await callBackend<{
        success?: boolean
        code?: string
        field?: string
        message?: string
        project?: ProjectRow
      }>("create_project", {
        project: {
          name: projectTitle.trim(),
          pipelineMode: "storyboard_video",
          pipeline_mode: "storyboard_video",
          contentMode,
          sourceLanguage,
          aspectRatio,
          episodePreset: "E01 · 第一集",
          episodeCount: 1,
          styleMode,
          styleCategory,
          styleTemplateId: styleMode === "custom" ? null : styleTemplate,
          stylePrompt: resolvedStylePrompt,
          styleAssetPrompt: resolvedStylePrompt,
          styleVisualTypeTag: selectedStyleVisualTypeTag,
          characterAssetPrompt: resolvedCharacterStylePrompt,
          creatureAssetPrompt: resolvedCreatureStylePrompt,
          styleFile: styleMode === "custom" ? customStyleFile : null,
        },
      })
      if (result.success === false || !result.project) {
        if (
          result.code === "project_name_exists" ||
          result.field === "name" ||
          result.message === PROJECT_NAME_EXISTS_MESSAGE
        ) {
          setStep(1)
          setTitleError(PROJECT_NAME_EXISTS_MESSAGE)
          clearSubmitError()
          return
        }
        if (result.code === "model_config_required") {
          showSubmitError(
            result.message || MODEL_CONFIG_REQUIRED_MESSAGE,
            "warning"
          )
          return
        }
        throw new Error(result.message || "创建项目失败")
      }
      onCreated(result.project)
    } catch (error) {
      showSubmitError(error instanceof Error ? error.message : "创建项目失败")
    } finally {
      setCreating(false)
    }
  }

  return (
    <ModalShell
      title={`创建项目 · ${stepTitle}`}
      description="两步完成基础信息和视觉风格；模型参数自动跟随全局设置。"
      onClose={onClose}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          {step > 1 ? (
            <Button variant="outline" onClick={() => setStep(step - 1)}>
              上一步
            </Button>
          ) : null}
          <Button
            className="bg-gradient-to-r from-indigo-600 via-sky-600 to-emerald-500 text-white"
            onClick={handlePrimaryClick}
            disabled={creating}
          >
            {creating ? "创建中" : step < 2 ? "下一步" : "创建项目"}
          </Button>
        </>
      }
    >
      <div
        className="mb-5 rounded-xl border border-gray-200/70 bg-white/55 px-4 py-3 dark:border-white/10 dark:bg-white/[0.03]"
        aria-label="创建项目进度"
      >
        <div className="flex items-center gap-3">
          <div className="flex shrink-0 items-center gap-2.5">
            <span
              className={cn(
                "grid size-7 place-items-center rounded-full border text-xs font-semibold",
                step > 1
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-300"
                  : "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
              )}
            >
              {step > 1 ? <CheckCircle2 className="size-3.5" /> : "1"}
            </span>
            <div>
              <div className="text-xs font-semibold text-gray-950 dark:text-gray-50">
                基础信息
              </div>
              <div className="mt-0.5 text-[11px] text-gray-400 dark:text-gray-500">
                {step > 1 ? "已完成" : "当前步骤"}
              </div>
            </div>
          </div>
          <div
            className={cn(
              "h-px min-w-8 flex-1",
              step > 1
                ? "bg-emerald-200 dark:bg-emerald-900/60"
                : "bg-gray-200 dark:bg-white/10"
            )}
          />
          <div className="flex shrink-0 items-center gap-2.5">
            <span
              className={cn(
                "grid size-7 place-items-center rounded-full border text-xs font-semibold",
                step === 2
                  ? "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
                  : "border-gray-200 bg-white/70 text-gray-400 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-500"
              )}
            >
              2
            </span>
            <div>
              <div className="text-xs font-semibold text-gray-950 dark:text-gray-50">
                视觉风格
              </div>
              <div className="mt-0.5 text-[11px] text-gray-400 dark:text-gray-500">
                {step === 2 ? "当前步骤" : "下一步"}
              </div>
            </div>
          </div>
        </div>
      </div>

      {step === 1 ? (
        <div className="space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
                项目名称
              </span>
              <Input
                value={projectTitle}
                onChange={(event) => {
                  setProjectTitle(event.target.value)
                  setTitleError("")
                }}
                className="h-9 w-full bg-white/70"
              />
              {titleError ? (
                <div
                  className={cn(
                    "mt-2 flex items-start gap-2 rounded-lg border px-3 py-2 text-[11px] leading-relaxed shadow-sm",
                    isDuplicateTitleError
                      ? "border-amber-200/80 bg-amber-50/80 text-amber-700 shadow-amber-950/[0.03] dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-200"
                      : "border-rose-200/70 bg-rose-50/70 text-rose-600 shadow-rose-950/[0.03] dark:border-rose-900/50 dark:bg-rose-950/15 dark:text-rose-200"
                  )}
                >
                  <AlertTriangle
                    className={cn(
                      "mt-0.5 size-3.5 shrink-0",
                      isDuplicateTitleError
                        ? "text-amber-500 dark:text-amber-300"
                        : "text-rose-400 dark:text-rose-300"
                    )}
                  />
                  <span>{titleError}</span>
                </div>
              ) : null}
            </label>
            <label className="block">
              <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
                语言地区
              </span>
              <Select value={sourceLanguage} onValueChange={setSourceLanguage}>
                <SelectTrigger className="h-9 w-full bg-white/70">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="zh-CN">中文 / 中国大陆</SelectItem>
                  <SelectItem value="zh-TW">中文 / 繁体</SelectItem>
                  <SelectItem value="en-US">English / US</SelectItem>
                </SelectContent>
              </Select>
            </label>
          </div>

          <div>
            <div className="mb-2 text-xs font-medium text-gray-500 dark:text-gray-400">
              视频比例
            </div>
            <div className="grid gap-2 md:grid-cols-2">
              {videoRatioOptions.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className={cn(
                    "rounded-xl border p-3 text-left transition-colors",
                    aspectRatio === option.id
                      ? "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
                      : "border-gray-200/70 bg-white/70 text-gray-500 hover:border-indigo-200 hover:text-gray-950 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400"
                  )}
                  onClick={() => setAspectRatio(option.id)}
                >
                  <span className="block text-sm font-semibold">
                    {option.name}
                  </span>
                  <span className="mt-1 block text-xs leading-relaxed opacity-75">
                    {option.description}
                  </span>
                </button>
              ))}
            </div>
          </div>

        </div>
      ) : null}

      {step === 2 ? (
        <div className="space-y-4">
          {modelConfigSubmitError ? (
            <div className="sticky top-0 z-40 flex w-full min-w-0 flex-col gap-2 rounded-xl border border-amber-200/80 bg-amber-50/95 px-3 py-2.5 text-xs leading-relaxed text-amber-700 shadow-lg shadow-amber-950/[0.08] backdrop-blur sm:flex-row sm:items-center dark:border-amber-900/50 dark:bg-amber-950/90 dark:text-amber-100">
              <div className="flex min-w-0 flex-1 items-start gap-2">
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-500 dark:text-amber-300" />
                <span className="min-w-0 flex-1 break-words whitespace-normal">
                  {modelConfigSubmitError}
                </span>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 shrink-0 self-start border-amber-200 bg-white/85 px-3 text-xs text-amber-700 hover:bg-white hover:text-gray-950 sm:self-center dark:border-amber-800/70 dark:bg-amber-950/40 dark:text-amber-100 dark:hover:bg-amber-900/40 dark:hover:text-white"
                onClick={() => void handleConfigurePrerequisite()}
              >
                去配置供应商
              </Button>
            </div>
          ) : null}
          <StyleModeTabs
            value={styleMode}
            onChange={changeStyleMode}
            modes={creationStyleModeTabs}
          />
          {styleMode === "template" ? (
            <div className="space-y-3">
              <StyleCategoryTabs
                value={styleCategory}
                onChange={changeStyleCategory}
                categories={creationPresetStyleCategories}
                templates={presetStyleTemplates}
              />
              {styleCategory === "general" ? (
                <GeneralStyleTemplatePanel
                  template={generalStyleTemplate}
                  value={styleTemplate}
                  onChange={(next) => {
                    setStyleTemplate(next)
                    const template = presetStyleTemplates.find(
                      (item) => item.id === next
                    )
                    if (isGeneralStyleTemplate(template)) {
                      setStyleCategory("general")
                    }
                    setStylePrompt(
                      styleTemplatePrompt(
                        template,
                        "global",
                        styleVisualTypeTag
                      )
                    )
                  }}
                  visualTypeTag={styleVisualTypeTag}
                  onVisualTypeTagChange={(next) => {
                    setStyleVisualTypeTag(next)
                    clearSubmitError()
                  }}
                />
              ) : (
                <StyleTemplateGrid
                  category={styleCategory}
                  value={styleTemplate}
                  onChange={(next) => {
                    setStyleTemplate(next)
                    const template = presetStyleTemplates.find(
                      (item) => item.id === next
                    )
                    if (isGeneralStyleTemplate(template)) {
                      setStyleCategory("general")
                    }
                    setStylePrompt(
                      styleTemplatePrompt(
                        template,
                        "global",
                        styleVisualTypeTag
                      )
                    )
                  }}
                  templates={presetStyleTemplates}
                  bounded
                  showFavoriteDelete={false}
                />
              )}
            </div>
          ) : styleMode === "favorite" ? (
            favoriteStyleTemplates.length > 0 ? (
              <StyleTemplateGrid
                category="favorite"
                value={styleTemplate}
                onChange={(next) => {
                  setStyleTemplate(next)
                  const template = favoriteStyleTemplates.find(
                    (item) => item.id === next
                  )
                  setStylePrompt(template?.prompt ?? "")
                }}
                templates={favoriteStyleTemplates}
                bounded
                showFavoriteDelete={false}
              />
            ) : (
              <div className="flex min-h-[260px] flex-col items-center justify-center rounded-xl border border-dashed border-gray-300/80 bg-white/45 p-8 text-center dark:border-white/15 dark:bg-white/[0.035]">
                <Star className="size-7 text-indigo-600 dark:text-indigo-300" />
                <div className="mt-3 text-sm font-semibold text-gray-950 dark:text-gray-50">
                  暂无收藏风格
                </div>
                <p className="mt-1 max-w-[360px] text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                  可在项目设置的自定义风格中上传图片和提示词后收藏。
                </p>
              </div>
            )
          ) : (
            <CustomStyleEditor
              stylePrompt={customStylePrompt}
              characterStylePrompt={customCharacterStylePrompt}
              creatureStylePrompt={customCreatureStylePrompt}
              uploadedName={customStyleFile?.name ?? null}
              uploadedPreview={imagePayloadPreviewSrc(customStyleFile)}
              onStylePromptChange={(prompt) => {
                setCustomStylePrompt(prompt)
                clearSubmitError()
              }}
              onCharacterStylePromptChange={(prompt) => {
                setCustomCharacterStylePrompt(prompt)
                clearSubmitError()
              }}
              onCreatureStylePromptChange={(prompt) => {
                setCustomCreatureStylePrompt(prompt)
                clearSubmitError()
              }}
              onFileSelected={handleCustomStyleFileSelected}
              onClearFile={() => {
                setCustomStyleFile(null)
                clearSubmitError()
              }}
              onAnalyze={() => void handleAnalyzeCustomStyle()}
              analyzing={analyzingStyle}
              uploadLabel="上传风格参考图"
            />
          )}
          {styleMode !== "custom" ? (
            <StylePromptPreview
              prompt={currentStylePreviewPrompt}
              onEdit={copyCurrentStyleToCustom}
            />
          ) : null}
          {submitError && !modelConfigSubmitError ? (
            <div
              className={cn(
                "rounded-xl border p-3 text-xs leading-relaxed",
                submitErrorTone === "warning"
                  ? "border-amber-200/80 bg-amber-50/80 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-200"
                  : "border-red-200 bg-red-50/80 text-red-700 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-300"
              )}
            >
              {submitError}
            </div>
          ) : null}
        </div>
      ) : null}
    </ModalShell>
  )
}
