import {
  describeModelResolutionOption,
  filterImageResolutionOptionsForAspect,
  getModelResolutionDisplayLabel,
  resolveImageAspectRatioForModel,
  type ImageResolutionSchema,
} from "@/utils/model-resolution"
import {
  fallbackProviders,
  normalizeProvider,
  type ProviderRow,
} from "@/features/settings/provider-model"
import type { VideoCapabilityMetadata } from "@/utils/video-model-capabilities"
import type { ModelAvailability } from "@/shared/model-availability"

export type ModelCapability = VideoCapabilityMetadata & ModelAvailability & {
  id: string
  provider_id?: string
  provider_preset_id?: string
  providerPresetId?: string
  adapter_id?: string
  adapterId?: string
  label: string
  model_vendor?: string
  vendor_source?: string
  classification_source?: string
  classification_rule?: string
  agent_route?: {
    baseUrl?: string
    authMode?: string
    source?: string
  }
  agent_support_source?: string
  agent_note?: string
  agent_only?: boolean
  reasoning_default_mode?: "low" | "medium" | "high" | "xhigh" | "max"
  reasoning_levels?: ("low" | "medium" | "high" | "xhigh" | "max")[]
  reasoning_supported?: boolean
  endpoint?: string
  resolutions?: string[]
  default_resolution?: string
  image_resolution_schema?: ImageResolutionSchema
  imageResolutionSchema?: ImageResolutionSchema
  resolution_descriptions?: Record<string, Record<string, string>>
  resolutionDescriptions?: Record<string, Record<string, string>>
  image_output_formats?: string[]
  durations?: number[]
  duration_resolution_constraints?: Record<string, number[]>
  fps?: number[]
  frameRates?: number[]
  frame_rates?: number[]
  audio?: boolean
  max_reference_images?: number
  supports_storyboard_reference_image?: boolean
  supportsStoryboardReferenceImage?: boolean
  supports_multi_reference_images?: boolean
  supportsMultiReferenceImages?: boolean
  supports_native_audio?: boolean
  supportsNativeAudio?: boolean
  recommended_prompt_chars?: number
  recommendedPromptChars?: number
  prompt_hard_limit_chars?: number
  promptHardLimitChars?: number
  capability_source?: string
  capabilitySource?: string
  capability_source_url?: string
  capabilitySourceUrl?: string
  capability_note?: string
  capabilityNote?: string
  reference_image_limit_source?: string
  reference_image_limit_source_url?: string
  reference_image_limit_note?: string
  referenceImageLimitSource?: string
  referenceImageLimitSourceUrl?: string
  referenceImageLimitNote?: string
  reference_image_transport_verified?: boolean
  reference_image_transport_unverified?: boolean
  supports?: string[]
}

export type ModelConfigPayload = {
  image: {
    model_id: string
    character_resolution: string
    scene_resolution: string
    prop_resolution: string
    asset_resolution: string
    storyboard_resolution: string
    image_output_format: string
  }
  video: {
    model_id: string
    resolution: string
    duration_seconds: number
    generate_audio: boolean
  }
  agent: {
    model_id: string
    temperature?: number
    max_tokens?: number
  }
  text: {
    model_id: string
    overview_excerpt_chars: number
  }
}

export type ModelConfigResponse = {
  config: ModelConfigPayload
  configVersion: string
  capabilities: {
    image: ModelCapability[]
    video: ModelCapability[]
    agent: ModelCapability[]
    text: ModelCapability[]
  }
  providers: ProviderRow[]
}

export const fallbackModelConfig: ModelConfigResponse = {
  configVersion: "",
  config: {
    image: {
      model_id: "",
      character_resolution: "",
      scene_resolution: "",
      prop_resolution: "",
      asset_resolution: "",
      storyboard_resolution: "",
      image_output_format: "auto",
    },
    video: {
      model_id: "",
      resolution: "",
      duration_seconds: 8,
      generate_audio: true,
    },
    agent: {
      model_id: "",
      temperature: 0.4,
      max_tokens: 8192,
    },
    text: {
      model_id: "",
      overview_excerpt_chars: 10000,
    },
  },
  capabilities: {
    image: [],
    video: [],
    agent: [],
    text: [],
  },
  providers: [],
}

export const DEFAULT_OVERVIEW_EXCERPT_CHARS = 10000
export const MIN_OVERVIEW_EXCERPT_CHARS = 1000
export const MAX_OVERVIEW_EXCERPT_CHARS = 50000

export function normalizeOverviewExcerptChars(value: unknown) {
  if (value == null) return DEFAULT_OVERVIEW_EXCERPT_CHARS
  if (typeof value === "string" && value.trim() === "") {
    return DEFAULT_OVERVIEW_EXCERPT_CHARS
  }
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return DEFAULT_OVERVIEW_EXCERPT_CHARS
  return Math.max(
    MIN_OVERVIEW_EXCERPT_CHARS,
    Math.min(MAX_OVERVIEW_EXCERPT_CHARS, Math.round(parsed))
  )
}

export function cloneModelConfig(
  config: ModelConfigPayload
): ModelConfigPayload {
  return JSON.parse(JSON.stringify(config)) as ModelConfigPayload
}

export function mergeModelConfig(
  base: ModelConfigPayload,
  incoming?: Partial<ModelConfigPayload>
): ModelConfigPayload {
  return {
    image: { ...base.image, ...(incoming?.image ?? {}) },
    video: { ...base.video, ...(incoming?.video ?? {}) },
    agent: { ...base.agent, ...(incoming?.agent ?? {}) },
    text: { ...base.text, ...(incoming?.text ?? {}) },
  }
}

export function modelConfigFingerprint(config: ModelConfigPayload) {
  return JSON.stringify(config)
}

export function modelConfigUnavailableSections(
  config: ModelConfigPayload,
  capabilities: ModelConfigResponse["capabilities"]
) {
  const sections = [
    ["image", config.image.model_id, capabilities.image],
    ["video", config.video.model_id, capabilities.video],
    ["agent", config.agent.model_id, capabilities.agent],
    ["text", config.text.model_id, capabilities.text],
  ] as const
  return sections
    .filter(([, modelId, models]) => {
      if (!modelId) return false
      const selected = models.find((model) => model.id === modelId)
      return !selected || selected.available === false
    })
    .map(([section]) => section)
}

export function normalizeModelConfigForCapabilities(
  config: ModelConfigPayload,
  capabilities: ModelConfigResponse["capabilities"]
): ModelConfigPayload {
  const imageModel = capabilities.image.find(
    (model) => model.id === config.image.model_id
  )
  const videoModel = capabilities.video.find(
    (model) => model.id === config.video.model_id
  )
  const agentModel = capabilities.agent.find(
    (model) => model.id === config.agent.model_id
  )
  const textModel = capabilities.text.find(
    (model) => model.id === config.text.model_id
  )
  const imageOutputFormat = pickImageOutputFormat(
    imageModel,
    config.image.image_output_format
  )
  const imageResolutions = imageModel?.resolutions ?? []
  const characterAspectRatio = resolveImageAspectRatioForModel(
    imageModel,
    imageResolutions,
    "16:9"
  )
  const sceneAspectRatio = resolveImageAspectRatioForModel(
    imageModel,
    imageResolutions,
    "3:2"
  )
  const propAspectRatio = resolveImageAspectRatioForModel(
    imageModel,
    imageResolutions,
    "2:1"
  )
  const characterResolution = pickStringOption(
    filterImageResolutionOptionsForAspect(
      imageResolutions,
      characterAspectRatio,
      {
        model: imageModel,
      }
    ),
    config.image.character_resolution,
    "2K",
    imageModel?.default_resolution
  )
  const sceneResolution = pickStringOption(
    filterImageResolutionOptionsForAspect(imageResolutions, sceneAspectRatio, {
      model: imageModel,
    }),
    config.image.scene_resolution,
    "2K",
    imageModel?.default_resolution
  )
  const propResolution = pickStringOption(
    filterImageResolutionOptionsForAspect(imageResolutions, propAspectRatio, {
      model: imageModel,
    }),
    config.image.prop_resolution,
    "1K",
    imageModel?.default_resolution
  )
  const assetResolution = pickStringOption(
    filterImageResolutionOptionsForAspect(imageResolutions, "16:9", {
      model: imageModel,
    }),
    config.image.asset_resolution,
    "2K",
    imageModel?.default_resolution
  )
  const storyboardResolution = pickStringOption(
    filterImageResolutionOptionsForAspect(imageResolutions, "16:9", {
      model: imageModel,
    }),
    config.image.storyboard_resolution,
    "2K",
    imageModel?.default_resolution
  )
  const overviewExcerptChars = normalizeOverviewExcerptChars(
    config.text.overview_excerpt_chars
  )
  return {
    ...config,
    image: imageModel && imageModel.available !== false
      ? {
          ...config.image,
          model_id: imageModel.id,
          character_resolution: characterResolution,
          scene_resolution: sceneResolution,
          prop_resolution: propResolution,
          asset_resolution: assetResolution,
          storyboard_resolution: storyboardResolution,
          image_output_format: imageOutputFormat,
        }
      : { ...config.image },
    video: videoModel && videoModel.available !== false
      ? {
          ...config.video,
          model_id: videoModel.id,
          resolution: pickStringOption(
            videoModel.resolutions ?? [],
            config.video.resolution,
            "720p",
            videoModel.default_resolution
          ),
          duration_seconds: pickNumberOption(
            normalizeModelDurations(videoModel, config.video.resolution),
            config.video.duration_seconds,
            8
          ),
          generate_audio: Boolean(videoModel.audio),
        }
      : { ...config.video },
    agent: {
      ...config.agent,
      model_id: agentModel?.id ?? config.agent.model_id,
    },
    text: {
      ...config.text,
      model_id: textModel?.id ?? config.text.model_id,
      overview_excerpt_chars: overviewExcerptChars,
    },
  }
}

export const IMAGE_RESOLUTION_ALIASES: Record<string, string[]> = {
  "512px": ["512x512"],
  "1k": ["1024x1024"],
  "2k": ["2048x1152"],
  "3k": ["3072x1728"],
  "4k": ["3840x2160", "4096x2304"],
}

export function pickStringOption(
  options: string[],
  current: string | undefined,
  preferred: string,
  fallback?: string
) {
  const normalizedOptions = options.filter(Boolean)
  for (const candidate of [current, preferred, fallback]) {
    if (!candidate) continue
    const exact = normalizedOptions.find((option) => option === candidate)
    if (exact) return exact
    const normalized = candidate.toLowerCase()
    const matched = normalizedOptions.find(
      (option) => option.toLowerCase() === normalized
    )
    if (matched) return matched
    const aliases = IMAGE_RESOLUTION_ALIASES[normalized] ?? []
    for (const alias of aliases) {
      const aliasMatched = normalizedOptions.find(
        (option) => option.toLowerCase() === alias.toLowerCase()
      )
      if (aliasMatched) return aliasMatched
    }
  }
  return options[0] ?? current ?? fallback ?? preferred
}

export function pickNumberOption(
  options: number[],
  current: number | undefined,
  preferred: number
) {
  const normalizedCurrent = Number(current)
  if (options.includes(normalizedCurrent)) return normalizedCurrent
  if (options.includes(preferred)) return preferred
  return options[0] ?? preferred
}

export function normalizeModelDurations(
  model?: ModelCapability,
  resolution?: string
) {
  const constraints = model?.duration_resolution_constraints
  const matchedConstraintKey =
    resolution && constraints
      ? Object.keys(constraints).find(
          (key) => key.toLowerCase() === resolution.toLowerCase()
        )
      : undefined
  const constrainedDurations = matchedConstraintKey
    ? constraints?.[matchedConstraintKey]
    : undefined
  const durations = constrainedDurations?.length
    ? constrainedDurations
    : model?.durations?.length
      ? model.durations
      : [8]
  return Array.from(
    new Set(
      durations
        .map((duration) => Number(duration))
        .filter((duration) => Number.isFinite(duration) && duration > 0)
    )
  ).sort((a, b) => a - b)
}

export type SupplierImageOutputFormat = "png" | "jpg" | "webp"
export type ImageOutputFormatValue = "auto" | SupplierImageOutputFormat

export const supplierImageOutputFormats: SupplierImageOutputFormat[] = [
  "png",
  "jpg",
  "webp",
]

export function normalizeImageOutputFormat(
  value: unknown
): ImageOutputFormatValue {
  const raw = String(value ?? "")
    .trim()
    .toLowerCase()
  const normalized = raw === "jpeg" ? "jpg" : raw
  if (
    normalized === "auto" ||
    normalized === "png" ||
    normalized === "jpg" ||
    normalized === "webp"
  ) {
    return normalized
  }
  return "auto"
}

export function supplierImageOutputFormatsForModel(
  model?: ModelCapability
): SupplierImageOutputFormat[] {
  if (!modelSupportsConfigurableImageOutputFormat(model)) return []
  const supported = new Set(
    (model?.image_output_formats ?? [])
      .map(normalizeImageOutputFormat)
      .filter(
        (format): format is SupplierImageOutputFormat => format !== "auto"
      )
  )
  return supplierImageOutputFormats.filter((format) => supported.has(format))
}

export function imageOutputFormatOptionsForModel(
  model?: ModelCapability
): ImageOutputFormatValue[] {
  return ["auto", ...supplierImageOutputFormatsForModel(model)]
}

export function pickImageOutputFormat(
  model?: ModelCapability,
  current?: unknown
): ImageOutputFormatValue {
  const normalized = normalizeImageOutputFormat(current)
  if (normalized === "auto") return "auto"
  return supplierImageOutputFormatsForModel(model).includes(normalized)
    ? normalized
    : "auto"
}

export function imageOutputFormatLabel(value: ImageOutputFormatValue) {
  return value === "auto" ? "自动" : value.toUpperCase()
}

export function modelSupportsConfigurableImageOutputFormat(
  model?: ModelCapability
) {
  if (!model) return false
  const providerId = getModelProviderPresetId(model)
  const modelName = getModelApiName(model).toLowerCase()
  return (
    modelName === "gpt-image-2" &&
    (providerId === "openai" || Boolean(model.image_output_formats?.length))
  )
}

export function buildResolutionDescriptions(
  mediaType: "image" | "video",
  model: ModelCapability | undefined,
  options: string[],
  aspectRatio?: string
) {
  return Object.fromEntries(
    options.map((option) => [
      option,
      modelResolutionDescription(model, option, aspectRatio) ||
        describeModelResolutionOption({
          mediaType,
          model,
          resolution: option,
          aspectRatio,
        }),
    ])
  ) as Record<string, string>
}

function modelResolutionDescription(
  model: ModelCapability | undefined,
  resolution: string,
  aspectRatio?: string
) {
  const descriptions =
    model?.resolutionDescriptions ?? model?.resolution_descriptions
  if (!descriptions) return ""
  const keys = [
    aspectRatio,
    aspectRatio === "16:9" ? "character" : "",
    aspectRatio === "2:1" ? "prop" : "",
    aspectRatio === "3:2" ? "scene" : "",
    aspectRatio === "16:9" ? "storyboard" : "",
    aspectRatio === "16:9" ? "asset" : "",
  ].filter((key): key is string => Boolean(key))
  for (const key of keys) {
    const value = descriptions[key]?.[resolution]
    if (value) return value
  }
  return ""
}

export function buildResolutionDisplayLabels(
  mediaType: "image" | "video",
  model: ModelCapability | undefined,
  options: string[],
  aspectRatio?: string
) {
  return Object.fromEntries(
    options.map((option) => [
      option,
      getModelResolutionDisplayLabel({
        mediaType,
        model,
        resolution: option,
        aspectRatio,
      }),
    ])
  ) as Record<string, string>
}

export function getModelProviderId(model: ModelCapability) {
  if (model.provider_id) return model.provider_id
  const separatorIndex = model.id.search(/[:/]/)
  return separatorIndex > 0 ? model.id.slice(0, separatorIndex) : "other"
}

export function getModelProviderPresetId(model: ModelCapability) {
  return (
    model.provider_preset_id ??
    model.providerPresetId ??
    model.provider_id ??
    model.id.split(":")[0] ??
    ""
  ).trim()
}

export function getModelApiName(model: ModelCapability) {
  const separatorIndex = model.id.search(/[:/]/)
  return separatorIndex >= 0 ? model.id.slice(separatorIndex + 1) : model.id
}

export function getProviderTitle(providerId: string, providers: ProviderRow[]) {
  const provider = [...providers, ...fallbackProviders].find(
    (item) => item.id === providerId
  )
  if (provider) return provider.title
  return providerId
}

export function getModelDisplayName(model: ModelCapability) {
  const label = model.label || model.id
  const parts = label.split(" / ").filter(Boolean)
  return parts.length > 1 ? parts[parts.length - 1] : label
}

export function groupModelsByProvider(
  models: ModelCapability[],
  providers: ProviderRow[]
) {
  const groups = new Map<
    string,
    { providerId: string; providerName: string; models: ModelCapability[] }
  >()
  for (const model of models) {
    const providerId = getModelProviderId(model)
    const group = groups.get(providerId) ?? {
      providerId,
      providerName: getProviderTitle(providerId, providers),
      models: [],
    }
    group.models.push(model)
    groups.set(providerId, group)
  }
  return Array.from(groups.values())
}

export function mergeModelConfigResponse(
  result?: Partial<ModelConfigResponse>
): ModelConfigResponse {
  const capabilities = {
    ...fallbackModelConfig.capabilities,
    ...(result?.capabilities ?? {}),
  }
  const config = normalizeModelConfigForCapabilities(
    mergeModelConfig(fallbackModelConfig.config, result?.config),
    capabilities
  )
  return {
    ...fallbackModelConfig,
    ...(result ?? {}),
    config,
    capabilities,
    providers: (result?.providers ?? fallbackModelConfig.providers).map(
      normalizeProvider
    ),
  }
}
