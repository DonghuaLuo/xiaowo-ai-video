import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { toast } from "sonner"
import { CircleHelp, Image, Loader2, Plug, Save, Search, Video, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import { SectionPanel } from "@/shared/page-shell"
import { ModelPicker } from "./model-picker"
import {
  filterImageResolutionOptionsForAspect,
  resolveImageAspectRatioForModel,
  storyboardSizeIsPromptOnlyForGptRelay,
} from "@/utils/model-resolution"
import type { ProviderRow } from "@/features/settings/provider-model"
import {
  buildResolutionDescriptions,
  buildResolutionDisplayLabels,
  cloneModelConfig,
  fallbackModelConfig,
  getModelProviderId,
  imageOutputFormatLabel,
  imageOutputFormatOptionsForModel,
  MAX_OVERVIEW_EXCERPT_CHARS,
  mergeModelConfigResponse,
  MIN_OVERVIEW_EXCERPT_CHARS,
  modelConfigFingerprint,
  modelConfigUnavailableSections,
  normalizeImageOutputFormat,
  normalizeModelConfigForCapabilities,
  normalizeOverviewExcerptChars,
  pickImageOutputFormat,
  pickStringOption,
  type ImageOutputFormatValue,
  type ModelCapability,
  type ModelConfigPayload,
  type ModelConfigResponse,
} from "@/features/settings/model-config-model"

const UNCONFIGURED_MODEL_VALUE = "__unconfigured__"

export function ModelConfigSettings({ onManageProviders }: { onManageProviders: () => void }) {
  const { backendReady, callBackend } = useBackend()
  const [modelState, setModelState] =
    useState<ModelConfigResponse>(fallbackModelConfig)
  const [unadaptedCapabilities, setUnadaptedCapabilities] = useState<ModelConfigResponse["capabilities"]>(
    fallbackModelConfig.capabilities
  )
  const [savedConfig, setSavedConfig] = useState<ModelConfigPayload>(
    cloneModelConfig(fallbackModelConfig.config)
  )
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState("")
  const loadRequestIdRef = useRef(0)

  const config = modelState.config
  const unavailableModelSections = useMemo(
    () => modelConfigUnavailableSections(config, modelState.capabilities),
    [config, modelState.capabilities]
  )
  const visibleImageModels = modelState.capabilities.image
  const visibleConfigModels = modelState.capabilities
  const imageModel = modelState.capabilities.image.find(
    (model) => model.id === config.image.model_id
  )
  const storyboardSizePromptOnly = Boolean(
    imageModel && storyboardSizeIsPromptOnlyForGptRelay(
      imageModel.id, getModelProviderId(imageModel), imageModel.adapter_id ?? imageModel.adapterId
    )
  )
  const storyboardSizeAutoPreset =
    (imageModel?.image_resolution_schema?.size_mode ??
      imageModel?.imageResolutionSchema?.sizeMode) === "explicit_pixels"
  const videoModel = modelState.capabilities.video.find(
    (model) => model.id === config.video.model_id
  )
  const hasImageModels = visibleImageModels.length > 0 || Boolean(config.image.model_id)
  const hasVideoModels = visibleConfigModels.video.length > 0
  const imageResolutions = imageModel?.resolutions ?? []
  const characterAspectRatio = useMemo(
    () => resolveImageAspectRatioForModel(imageModel, imageResolutions, "16:9"),
    [imageModel, imageResolutions]
  )
  const sceneAspectRatio = useMemo(
    () => resolveImageAspectRatioForModel(imageModel, imageResolutions, "3:2"),
    [imageModel, imageResolutions]
  )
  const propAspectRatio = useMemo(
    () => resolveImageAspectRatioForModel(imageModel, imageResolutions, "2:1"),
    [imageModel, imageResolutions]
  )
  const characterImageResolutions = useMemo(
    () =>
      filterImageResolutionOptionsForAspect(
        imageResolutions,
        characterAspectRatio,
        { model: imageModel }
      ),
    [characterAspectRatio, imageModel, imageResolutions]
  )
  const sceneImageResolutions = useMemo(
    () =>
      filterImageResolutionOptionsForAspect(
        imageResolutions,
        sceneAspectRatio,
        { model: imageModel }
      ),
    [imageModel, imageResolutions, sceneAspectRatio]
  )
  const propImageResolutions = useMemo(
    () =>
      filterImageResolutionOptionsForAspect(imageResolutions, propAspectRatio, {
        model: imageModel,
      }),
    [imageModel, imageResolutions, propAspectRatio]
  )
  const storyboardImageResolutions = useMemo(
    () =>
      filterImageResolutionOptionsForAspect(imageResolutions, "16:9", {
        model: imageModel,
      }),
    [imageModel, imageResolutions]
  )
  const videoResolutions = videoModel?.resolutions ?? []
  const imageOutputFormatOptions = useMemo(
    () => imageOutputFormatOptionsForModel(imageModel),
    [imageModel]
  )
  const sceneResolutionLabels = useMemo(
    () =>
      buildResolutionDisplayLabels(
        "image",
        imageModel,
        sceneImageResolutions,
        sceneAspectRatio
      ),
    [imageModel, sceneAspectRatio, sceneImageResolutions]
  )
  const sceneResolutionDescriptions = useMemo(
    () =>
      buildResolutionDescriptions(
        "image",
        imageModel,
        sceneImageResolutions,
        sceneAspectRatio
      ),
    [imageModel, sceneAspectRatio, sceneImageResolutions]
  )
  const characterResolutionLabels = useMemo(
    () =>
      buildResolutionDisplayLabels(
        "image",
        imageModel,
        characterImageResolutions,
        characterAspectRatio
      ),
    [characterAspectRatio, imageModel, characterImageResolutions]
  )
  const characterResolutionDescriptions = useMemo(
    () =>
      buildResolutionDescriptions(
        "image",
        imageModel,
        characterImageResolutions,
        characterAspectRatio
      ),
    [characterAspectRatio, imageModel, characterImageResolutions]
  )
  const propResolutionLabels = useMemo(
    () =>
      buildResolutionDisplayLabels(
        "image",
        imageModel,
        propImageResolutions,
        propAspectRatio
      ),
    [imageModel, propAspectRatio, propImageResolutions]
  )
  const propResolutionDescriptions = useMemo(
    () =>
      buildResolutionDescriptions(
        "image",
        imageModel,
        propImageResolutions,
        propAspectRatio
      ),
    [imageModel, propAspectRatio, propImageResolutions]
  )
  const storyboardResolutionLabels = useMemo(
    () =>
      buildResolutionDisplayLabels(
        "image",
        imageModel,
        storyboardImageResolutions,
        "16:9"
      ),
    [imageModel, storyboardImageResolutions]
  )
  const storyboardResolutionDescriptions = useMemo(
    () =>
      buildResolutionDescriptions(
        "image",
        imageModel,
        storyboardImageResolutions,
        "16:9"
      ),
    [imageModel, storyboardImageResolutions]
  )
  const videoResolutionLabels = useMemo(
    () => buildResolutionDisplayLabels("video", videoModel, videoResolutions),
    [videoModel, videoResolutions]
  )
  const videoResolutionDescriptions = useMemo(
    () => buildResolutionDescriptions("video", videoModel, videoResolutions),
    [videoModel, videoResolutions]
  )
  const isDirty =
    modelConfigFingerprint(config) !== modelConfigFingerprint(savedConfig)

  const loadConfig = useCallback(async (): Promise<boolean> => {
    if (!backendReady) return false
    const requestId = ++loadRequestIdRef.current
    setLoading(true)
    setMessage("")
    void callBackend<ModelConfigResponse & { success?: false; message?: string }>(
      "list_models", { status: "unadapted" }
    ).then((unadapted) => {
      if (loadRequestIdRef.current !== requestId) return
      if (unadapted.success === false) throw new Error(unadapted.message || "加载未适配模型失败")
      setUnadaptedCapabilities(unadapted.capabilities)
    }).catch((error) => {
      if (loadRequestIdRef.current !== requestId) return
      setUnadaptedCapabilities(fallbackModelConfig.capabilities)
      setMessage(error instanceof Error ? error.message : "加载未适配模型失败")
    })
    try {
      const result = await callBackend<ModelConfigResponse & { success?: false; message?: string }>(
        "list_models", { status: "adapted" }
      )
      if (loadRequestIdRef.current !== requestId) return false
      if (result.success === false)
        throw new Error(result.message || "加载模型配置失败")
      const nextState = mergeModelConfigResponse(result)
      setModelState(nextState)
      setSavedConfig(cloneModelConfig(nextState.config))
      return true
    } catch (err) {
      if (loadRequestIdRef.current === requestId)
        setMessage(err instanceof Error ? err.message : "加载模型配置失败")
      return false
    } finally {
      if (loadRequestIdRef.current === requestId) setLoading(false)
    }
  }, [backendReady, callBackend])

  useEffect(() => {
    void loadConfig()
    return () => { loadRequestIdRef.current += 1 }
  }, [loadConfig])

  const updateModelConfig = (next: ModelConfigPayload) => {
    setMessage("")
    setModelState((state) => ({
      ...state,
      config: normalizeModelConfigForCapabilities(next, state.capabilities),
    }))
  }

  const updateImage = (patch: Partial<ModelConfigPayload["image"]>) => {
    updateModelConfig({
      ...config,
      image: { ...config.image, ...patch },
    })
  }

  const updateVideo = (patch: Partial<ModelConfigPayload["video"]>) => {
    updateModelConfig({
      ...config,
      video: { ...config.video, ...patch },
    })
  }

  const updateAgent = (patch: Partial<ModelConfigPayload["agent"]>) => {
    updateModelConfig({
      ...config,
      agent: { ...config.agent, ...patch },
    })
  }

  const updateText = (patch: Partial<ModelConfigPayload["text"]>) => {
    updateModelConfig({
      ...config,
      text: { ...config.text, ...patch },
    })
  }

  const handleReset = () => {
    setMessage("")
    setModelState((state) => ({
      ...state,
      config: cloneModelConfig(savedConfig),
    }))
  }

  const handleSave = async () => {
    if (!backendReady || !isDirty) return
    if (unavailableModelSections.length) {
      setMessage("当前配置含不可用模型，请更换或清空后再保存")
      return
    }
    setSaving(true)
    setMessage("")
    try {
      const result = await callBackend<
        ModelConfigResponse & { success?: boolean; message?: string }
      >("save_model_config", { config, expectedConfigVersion: modelState.configVersion })
      if (result.success === false)
        throw new Error(result.message || "保存模型配置失败")
      const nextState = mergeModelConfigResponse(result)
      setModelState(nextState)
      setSavedConfig(cloneModelConfig(nextState.config))
      setMessage("模型配置已保存")
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "保存模型配置失败"
      if (errorMessage.includes("全局模型配置已变化")) {
        const refreshed = await loadConfig()
        setMessage(refreshed
          ? "全局模型配置已变化，已刷新最新设置，请重新选择"
          : "全局模型配置已变化，重新加载失败，请重试")
      } else {
        setMessage(errorMessage)
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <SectionPanel
        eyebrow="Model Config"
        title="模型配置"
        description="全局默认负责模型、档位和供应商输出格式分派；画布卡片与项目智能体可以单独选择模型。"
      >
        <div className="mb-4 flex justify-end">
          <Button type="button" variant="outline" size="sm" className="gap-2"
            disabled={isDirty || saving} title={isDirty ? "请先保存或取消修改" : undefined} onClick={onManageProviders}>
            <Plug className="size-4" />管理供应商
          </Button>
        </div>
        {isDirty ? (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-indigo-100/80 bg-white/90 px-3 py-2.5 text-xs text-gray-700 shadow-sm shadow-indigo-950/[0.04] backdrop-blur-xl dark:border-white/10 dark:bg-[#202025]/90 dark:text-gray-200">
            <span>
              {unavailableModelSections.length
                ? "当前配置含不可用模型，请更换或清空后再保存。"
                : "检测到模型配置修改，保存后才会写入全局配置。"}
            </span>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                className="h-8 bg-white/70"
                disabled={saving || loading}
                onClick={handleReset}
              >
                取消恢复
              </Button>
              <Button
                size="sm"
                className="h-8 gap-2"
                disabled={saving || loading || !backendReady || unavailableModelSections.length > 0}
                onClick={handleSave}
              >
                {saving ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Save className="size-4" />
                )}
                保存修改
              </Button>
            </div>
          </div>
        ) : null}
        {loading ? (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-gray-200/70 bg-white/70 px-3 py-2 text-xs text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-300">
            <Loader2 className="size-3.5 animate-spin" />
            正在加载模型配置
          </div>
        ) : null}
        {message ? (
          <div className="mb-4 rounded-lg border border-gray-200/70 bg-white/70 px-3 py-2 text-xs text-gray-600 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-300">
            {message}
          </div>
        ) : null}
        <div className={cn("grid auto-rows-fr items-stretch gap-4 xl:grid-cols-2", (loading || !backendReady) && "hidden")}>
          <ModelSectionCard
            icon={Image}
            title="图片模型"
            headerAction={
              <UnadaptedModelList sections={[["图片模型", unadaptedCapabilities.image]]} />
            }
          >
            {hasImageModels ? (
              <>
                <ModelSelect
                  label="图片模型"
                  value={config.image.model_id}
                  models={visibleImageModels}
                  providers={modelState.providers}
                  onChange={(modelId) => {
                    if (!modelId) {
                      updateImage({ model_id: "" })
                      return
                    }
                    const model = modelState.capabilities.image.find(
                      (item) => item.id === modelId
                    )
                    const resolutions = model?.resolutions?.length
                      ? model.resolutions
                      : imageResolutions
                    const nextCharacterAspectRatio =
                      resolveImageAspectRatioForModel(
                        model,
                        resolutions,
                        "16:9"
                      )
                    const nextSceneAspectRatio =
                      resolveImageAspectRatioForModel(model, resolutions, "3:2")
                    const nextPropAspectRatio = resolveImageAspectRatioForModel(
                      model,
                      resolutions,
                      "2:1"
                    )
                    const characterResolutions =
                      filterImageResolutionOptionsForAspect(
                        resolutions,
                        nextCharacterAspectRatio,
                        { model }
                      )
                    const sceneResolutions =
                      filterImageResolutionOptionsForAspect(
                        resolutions,
                        nextSceneAspectRatio,
                        { model }
                      )
                    const propResolutions =
                      filterImageResolutionOptionsForAspect(
                        resolutions,
                        nextPropAspectRatio,
                        { model }
                      )
                    const storyboardResolutions =
                      filterImageResolutionOptionsForAspect(
                        resolutions,
                        "16:9",
                        { model }
                      )
                    updateImage({
                      model_id: modelId,
                      character_resolution: pickStringOption(
                        characterResolutions,
                        undefined,
                        "2K",
                        model?.default_resolution
                      ),
                      scene_resolution: pickStringOption(
                        sceneResolutions,
                        undefined,
                        "2K",
                        model?.default_resolution
                      ),
                      prop_resolution: pickStringOption(
                        propResolutions,
                        undefined,
                        "1K",
                        model?.default_resolution
                      ),
                      asset_resolution: pickStringOption(
                        storyboardResolutions,
                        undefined,
                        "2K",
                        model?.default_resolution
                      ),
                      storyboard_resolution: pickStringOption(
                        storyboardResolutions,
                        undefined,
                        "2K",
                        model?.default_resolution
                      ),
                      image_output_format: pickImageOutputFormat(
                        model,
                        config.image.image_output_format
                      ),
                    })
                  }}
                />
                {imageModel ? (
                  <div className="space-y-3">
                    <ResolutionSelect
                      label="角色图/生物图"
                      value={config.image.character_resolution}
                      options={characterImageResolutions}
                      labels={characterResolutionLabels}
                      descriptions={characterResolutionDescriptions}
                      onChange={(value) =>
                        updateImage({ character_resolution: value })
                      }
                    />
                    <ResolutionSelect
                      label="场景图"
                      value={config.image.scene_resolution}
                      options={sceneImageResolutions}
                      labels={sceneResolutionLabels}
                      descriptions={sceneResolutionDescriptions}
                      onChange={(value) =>
                        updateImage({ scene_resolution: value })
                      }
                    />
                    <ResolutionSelect
                      label="道具图"
                      value={config.image.prop_resolution}
                      options={propImageResolutions}
                      labels={propResolutionLabels}
                      descriptions={propResolutionDescriptions}
                      onChange={(value) =>
                        updateImage({ prop_resolution: value })
                      }
                    />
                    {storyboardSizePromptOnly ? (
                      <ModelFieldMessage
                        label="分镜图"
                        message="分辨率由模型决定，排版和比例通过提示词约束"
                      />
                    ) : storyboardSizeAutoPreset ? (
                      <ModelFieldMessage
                        label="分镜图"
                        message="尺寸按工作页自动匹配；可在分镜节点选择模型支持的具体尺寸"
                      />
                    ) : (
                      <ResolutionSelect
                        label="分镜图"
                        value={config.image.storyboard_resolution}
                        options={storyboardImageResolutions}
                        labels={storyboardResolutionLabels}
                        descriptions={storyboardResolutionDescriptions}
                        onChange={(value) =>
                          updateImage({ storyboard_resolution: value })
                        }
                      />
                    )}
                    <ImageOutputFormatSelect
                      value={config.image.image_output_format}
                      options={imageOutputFormatOptions}
                      onChange={(value) =>
                        updateImage({ image_output_format: value })
                      }
                    />
                  </div>
                ) : (
                  <ModelUnavailable message="请选择图片模型" />
                )}
              </>
            ) : (
              <ModelUnavailable message="暂无已适配的图片模型" />
            )}
          </ModelSectionCard>

          <ModelSectionCard
            icon={Video}
            title="模型配置"
            headerAction={
              <UnadaptedModelList sections={[
                ["视频模型", unadaptedCapabilities.video],
                ["智能体模型", unadaptedCapabilities.agent],
                ["文本模型", unadaptedCapabilities.text],
              ]} />
            }
          >
            <div className="space-y-3">
              <ModelSelect
                label="视频模型"
                value={config.video.model_id}
                models={visibleConfigModels.video}
                providers={modelState.providers}
                onChange={(modelId) => {
                  if (!modelId) {
                    updateVideo({ model_id: "" })
                    return
                  }
                  const model = modelState.capabilities.video.find(
                    (item) => item.id === modelId
                  )
                  const resolutions = model?.resolutions?.length
                    ? model.resolutions
                    : videoResolutions
                  const nextResolution = pickStringOption(
                    resolutions,
                    config.video.resolution,
                    "720p",
                    model?.default_resolution
                  )
                  updateVideo({
                    model_id: modelId,
                    resolution: nextResolution,
                  })
                }}
              />
              {videoModel ? (
                <ResolutionSelect
                  label="视频分辨率"
                  value={config.video.resolution}
                  options={videoResolutions}
                  labels={videoResolutionLabels}
                  descriptions={videoResolutionDescriptions}
                  onChange={(value) => updateVideo({ resolution: value })}
                />
              ) : (
                <ModelFieldMessage
                  label="视频分辨率"
                  message={
                    hasVideoModels ? "请选择视频模型" : "暂无可用视频模型"
                  }
                />
              )}
              <ModelSelect
                label="智能体模型"
                value={config.agent.model_id}
                models={visibleConfigModels.agent}
                providers={modelState.providers}
                onChange={(modelId) =>
                  updateAgent({
                    model_id: modelId,
                  })
                }
              />
              <ModelSelect
                label="文本模型"
                value={config.text.model_id}
                models={visibleConfigModels.text}
                providers={modelState.providers}
                onChange={(modelId) => updateText({ model_id: modelId })}
              />
            </div>
          </ModelSectionCard>
        </div>
      </SectionPanel>
    </>
  )
}

function ModelSectionCard({
  icon: Icon,
  title,
  headerAction,
  children,
}: {
  icon: typeof Image
  title: string
  headerAction?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="flex h-full min-h-[400px] flex-col space-y-4 rounded-xl border border-gray-200/70 bg-white/70 p-4 dark:border-white/10 dark:bg-white/[0.035]">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="size-5 text-indigo-600 dark:text-indigo-300" />
          <h3 className="text-sm font-semibold text-gray-950 dark:text-gray-50">
            {title}
          </h3>
        </div>
        {headerAction}
      </div>
      {children}
    </div>
  )
}

function UnadaptedModelList({
  sections,
}: {
  sections: [string, ModelCapability[]][]
}) {
  const [query, setQuery] = useState("")
  const searchInputRef = useRef<HTMLInputElement>(null)
  const count = sections.reduce((total, [, models]) => total + models.length, 0)
  const keyword = query.trim().toLocaleLowerCase()
  const filteredSections = sections.map(([label, models]) => [
    label,
    models.filter((model) =>
      `${model.label || ""} ${model.id}`.toLocaleLowerCase().includes(keyword)
    ),
  ] as [string, ModelCapability[]])
  const filteredCount = filteredSections.reduce((total, [, models]) => total + models.length, 0)
  return (
    <Popover onOpenChange={(open) => { if (!open) setQuery("") }}>
      <PopoverTrigger asChild>
        <button type="button" className="inline-flex shrink-0 items-center gap-1 text-xs text-gray-500 hover:text-indigo-600 focus-visible:rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 dark:text-gray-400 dark:hover:text-indigo-300"
          aria-label={`查看未适配模型，共 ${count} 个`}>
          未适配 <CircleHelp aria-hidden="true" className="size-3.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 max-w-[calc(100vw-2rem)] p-0">
        <div className="border-b px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-200">未适配模型（{count}）</div>
        <div className="relative px-3 pt-2">
          <Search aria-hidden="true" className="pointer-events-none absolute left-5 top-4 size-3.5 text-gray-400" />
          <Input ref={searchInputRef} value={query} onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索模型名称或 ID" aria-label="搜索未适配模型"
            className="h-8 pl-8 pr-8 text-xs" />
          {query ? (
            <button type="button" aria-label="清除搜索文字" title="清除搜索文字"
              onPointerDown={(event) => event.preventDefault()}
              onClick={() => { setQuery(""); searchInputRef.current?.focus() }}
              className="absolute right-4 top-3 flex size-6 items-center justify-center rounded text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-white/10 dark:hover:text-gray-200">
              <X aria-hidden="true" className="size-3.5" />
            </button>
          ) : null}
        </div>
        <div className="ai-video-scrollbar max-h-80 overflow-y-auto px-3 py-2">
          {filteredCount === 0 ? <p className="py-3 text-xs text-gray-500">{count === 0 ? "暂无未适配模型" : "没有匹配的模型"}</p> : filteredSections.map(([label, models]) =>
            models.length > 0 ? (
              <div key={label} className="py-1.5">
                <div className="mb-1 text-[11px] font-medium text-gray-500 dark:text-gray-400">{label}</div>
                {models.map((model) => (
                  <div key={model.id} className="break-words py-1 text-xs text-gray-700 dark:text-gray-200">
                    {model.label || model.id}
                  </div>
                ))}
              </div>
            ) : null
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}

function ModelUnavailable({ message }: { message: string }) {
  return (
    <div className="flex min-h-[180px] flex-1 items-center justify-center rounded-lg border border-dashed border-gray-200/80 bg-white/45 px-4 py-6 text-center text-xs leading-relaxed text-gray-500 dark:border-white/10 dark:bg-white/[0.025] dark:text-gray-400">
      {message}
    </div>
  )
}

function ModelFieldMessage({
  label,
  message,
}: {
  label: string
  message: string
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
        {label}
      </span>
      <div className="flex h-10 items-center rounded-md border border-dashed border-gray-200/80 bg-white/45 px-3 text-xs text-gray-500 dark:border-white/10 dark:bg-white/[0.025] dark:text-gray-400">
        {message}
      </div>
    </label>
  )
}

function ModelSelect({
  label,
  value,
  models,
  providers,
  onChange,
}: {
  label: string
  value: string
  models: ModelCapability[]
  providers: ProviderRow[]
  onChange: (value: string) => void
}) {
  return (
    <ModelPicker label={label} value={value || UNCONFIGURED_MODEL_VALUE}
      models={models} providers={providers}
      defaultOption={{ value: UNCONFIGURED_MODEL_VALUE, label: "未配置" }}
      onChange={(nextValue) => onChange(nextValue === UNCONFIGURED_MODEL_VALUE ? "" : nextValue)} />
  )
}

export function OverviewExcerptCharsInput({
  value,
  onChange,
}: {
  value: number
  onChange: (value: number) => void
}) {
  const normalizedValue = normalizeOverviewExcerptChars(value)
  const [draft, setDraft] = useState(String(normalizedValue))

  useEffect(() => {
    setDraft(String(normalizedValue))
  }, [normalizedValue])

  const commit = () => {
    const next = normalizeOverviewExcerptChars(draft)
    setDraft(String(next))
    const parsed = Number(draft)
    if (Number.isFinite(parsed) && parsed > MAX_OVERVIEW_EXCERPT_CHARS) {
      toast.info("项目概述截取字数最多 50000，已自动调整为 50000")
    } else if (
      draft.trim() &&
      Number.isFinite(parsed) &&
      parsed < MIN_OVERVIEW_EXCERPT_CHARS
    ) {
      toast.info(
        `项目概述截取字数最少 ${MIN_OVERVIEW_EXCERPT_CHARS}，已自动调整`
      )
    }
    if (next !== value) onChange(next)
  }

  return (
    <label className="block">
      <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
        项目概述截取字数
      </span>
      <Input
        type="number"
        min={MIN_OVERVIEW_EXCERPT_CHARS}
        max={MAX_OVERVIEW_EXCERPT_CHARS}
        step={1000}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.currentTarget.blur()
          }
        }}
      />
    </label>
  )
}

function ResolutionSelect({
  label,
  value,
  options,
  labels,
  descriptions,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  labels?: Record<string, string>
  descriptions?: Record<string, string>
  onChange: (value: string) => void
}) {
  if (options.length === 0) {
    return (
      <label className="block">
        <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
          {label}
        </span>
        <div className="flex h-10 items-center rounded-md border border-dashed border-gray-200/80 bg-white/45 px-3 text-xs text-gray-500 dark:border-white/10 dark:bg-white/[0.025] dark:text-gray-400">
          该模型未提供可选参数
        </div>
      </label>
    )
  }
  const selectedValue = options.includes(value) ? value : options[0]
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
        {label}
      </span>
      <Select value={selectedValue} onValueChange={onChange}>
        <SelectTrigger className="w-full bg-white/70">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem
              key={option}
              value={option}
              textValue={labels?.[option] || option}
            >
              <div className="flex flex-col items-start gap-0.5 py-0.5">
                <span data-select-option-title>
                  {labels?.[option] || option}
                </span>
                {descriptions?.[option] ? (
                  <span
                    data-select-description
                    className="line-clamp-1 text-[11px] leading-relaxed text-gray-500 dark:text-gray-400"
                  >
                    {descriptions[option]}
                  </span>
                ) : null}
              </div>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  )
}

function ImageOutputFormatSelect({
  value,
  options,
  onChange,
}: {
  value: string
  options: ImageOutputFormatValue[]
  onChange: (value: string) => void
}) {
  const normalizedOptions: ImageOutputFormatValue[] = options.length
    ? options
    : ["auto"]
  if (normalizedOptions.length === 1 && normalizedOptions[0] === "auto") return null
  const normalizedValue = normalizeImageOutputFormat(value)
  const selectedValue = normalizedOptions.includes(normalizedValue)
    ? normalizedValue
    : "auto"
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
        供应商图片输出格式
      </span>
      <Select value={selectedValue} onValueChange={onChange}>
        <SelectTrigger className="w-full bg-white/70">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {normalizedOptions.map((option) => (
            <SelectItem key={option} value={option}>
              <div className="flex flex-col items-start gap-0.5 py-0.5">
                <span data-select-option-title>
                  {imageOutputFormatLabel(option)}
                </span>
                <span
                  data-select-description
                  className="line-clamp-1 text-[11px] leading-relaxed text-gray-500 dark:text-gray-400"
                >
                  {option === "auto"
                    ? "由供应商按模型默认值决定，生成后仍统一保存为 PNG。"
                    : `请求供应商以 ${option.toUpperCase()} 输出，生成后仍统一保存为 PNG。`}
                </span>
              </div>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  )
}
