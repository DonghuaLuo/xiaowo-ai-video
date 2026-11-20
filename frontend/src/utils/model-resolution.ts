export type ImageResolutionSchema = {
  version?: number
  source?: string
  source_url?: string
  sourceUrl?: string
  parameter?: string
  value_format?: string
  valueFormat?: string
  size_mode?: string
  sizeMode?: string
  separator?: "x" | "*" | string
  native_tiers?: string[]
  nativeTiers?: string[]
  aspect_ratios?: string[]
  aspectRatios?: string[]
  round_to?: number
  roundTo?: number
  default_long_edge?: number
  defaultLongEdge?: number
  min_long_edge?: number
  minLongEdge?: number
  max_long_edge?: number
  maxLongEdge?: number
  min_total_pixels?: number
  minTotalPixels?: number
  max_total_pixels?: number
  maxTotalPixels?: number
  max_ratio?: number
  maxRatio?: number
  allow_explicit_pixels?: boolean
  allowExplicitPixels?: boolean
  explicit_pixel_constraints?: Record<string, unknown>
  explicitPixelConstraints?: Record<string, unknown>
  explicit_pixel_constraints_by_resolution?: Record<string, Record<string, unknown>>
  explicitPixelConstraintsByResolution?: Record<string, Record<string, unknown>>
  max_total_pixels_by_resolution?: Record<string, number>
  maxTotalPixelsByResolution?: Record<string, number>
  operation_constraints?: Array<Record<string, unknown>>
  operationConstraints?: Array<Record<string, unknown>>
  notes?: string
}

export type ResolutionPreviewModel = {
  id?: string
  provider_id?: string
  providerId?: string
  provider_preset_id?: string
  providerPresetId?: string
  adapter_id?: string
  adapterId?: string
  image_resolution_schema?: ImageResolutionSchema
  imageResolutionSchema?: ImageResolutionSchema
}

export function storyboardSizeIsPromptOnlyForGptRelay(
  modelId: string | undefined,
  providerId: string | undefined,
  adapterId?: string
): boolean {
  const normalizedModelId = String(modelId ?? "").trim().toLowerCase()
  const apiModelId = normalizedModelId.includes(":")
    ? normalizedModelId.split(":").slice(1).join(":")
    : normalizedModelId
  return apiModelId.startsWith("gpt-image-2") &&
    providerId !== "openai" &&
    adapterId === "openai-compatible"
}

type MediaType = "image" | "video"
type ResolutionFilterContext = {
  model?: ResolutionPreviewModel
  hasReferenceImages?: boolean
  includeAllAspects?: boolean
}

const IMAGE_TIER_SHORT_EDGE: Record<string, number> = {
  "512px": 512,
  "1K": 1024,
  "2K": 2048,
  "3K": 3072,
  "4K": 4096,
}

const IMAGE_TIER_LONG_EDGE: Record<string, number> = {
  "512px": 512,
  "1K": 1024,
  "2K": 2048,
  "3K": 3072,
  "4K": 4096,
}

const VIDEO_TIER_SHORT_EDGE: Record<string, number> = {
  "360p": 360,
  "480p": 480,
  "540p": 540,
  "720p": 720,
  "1024p": 1024,
  "1080p": 1080,
  "4K": 2160,
}

const VIDEO_SIZE_PRESETS: Record<string, Record<string, string>> = {
  "16:9": {
    "360p": "640x360",
    "480p": "848x480",
    "540p": "960x540",
    "720p": "1280x720",
    "1024p": "1792x1024",
    "1080p": "1920x1080",
    "4K": "3840x2160",
  },
  "9:16": {
    "360p": "360x640",
    "480p": "480x848",
    "540p": "540x960",
    "720p": "720x1280",
    "1024p": "1024x1792",
    "1080p": "1080x1920",
    "4K": "2160x3840",
  },
}

const SORA_SIZES_720P = ["720x1280", "1280x720"]
const SORA_SIZES_1080P = ["1080x1920", "1920x1080"]

const GPT_IMAGE_MAX_LONG_EDGE = 3840
const GPT_IMAGE_MAX_TOTAL_PIXELS = 8294400
const GPT_IMAGE_MAX_RATIO = 3
const DASHSCOPE_STANDARD_PIXEL_BUDGET = 2048 * 2048
const DASHSCOPE_FOURK_PIXEL_BUDGET = 4096 * 4096
const DASHSCOPE_EDIT_MAX_LONG_EDGE = 2048
const DASHSCOPE_MAX_RATIO = 8
const DASHSCOPE_EDIT_MAX_RATIO = 4

const DEFAULT_IMAGE_SHORT_EDGE = 1024
const DEFAULT_VIDEO_SHORT_EDGE = 720

const IMAGE_SIZE_TIER_ALIASES: Record<string, string> = {
  "1024x1024": "1K",
  "1536x1024": "1K",
  "1024x1536": "1K",
  "1280x720": "1K",
  "720x1280": "1K",
  "1024x576": "1K",
  "576x1024": "1K",
  "768x1024": "1K",
  "1024x768": "1K",
  "2048x2048": "2K",
  "2048x1152": "2K",
  "1152x2048": "2K",
  "2048x1536": "2K",
  "1536x2048": "2K",
  "2560x1440": "2K",
  "1440x2560": "2K",
  "2688x1536": "2K",
  "1536x2688": "2K",
  "2368x1728": "2K",
  "1728x2368": "2K",
  "3072x3072": "3K",
  "3072x1728": "3K",
  "1728x3072": "3K",
  "2304x3072": "3K",
  "3072x2304": "3K",
  "4096x4096": "4K",
  "4096x2304": "4K",
  "2304x4096": "4K",
  "3072x4096": "4K",
  "4096x3072": "4K",
  "3840x2160": "4K",
  "2160x3840": "4K",
}

const VIDEO_SIZE_TIER_ALIASES: Record<string, string> = {
  "640x360": "360p",
  "360x640": "360p",
  "848x480": "480p",
  "480x848": "480p",
  "960x540": "540p",
  "540x960": "540p",
  "1280x720": "720p",
  "720x1280": "720p",
  "1792x1024": "1024p",
  "1024x1792": "1024p",
  "1920x1080": "1080p",
  "1080x1920": "1080p",
  "3840x2160": "4K",
  "2160x3840": "4K",
}

function parseAspectRatio(aspectRatio?: string | null): [number, number] {
  const raw = String(aspectRatio ?? "")
    .trim()
    .replace("：", ":")
  const parts = raw.split(":")
  if (parts.length !== 2) return [9, 16]
  const width = Number(parts[0])
  const height = Number(parts[1])
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return [9, 16]
  }
  const gcd = greatestCommonDivisor(Math.trunc(width), Math.trunc(height))
  return [Math.trunc(width) / gcd, Math.trunc(height) / gcd]
}

function greatestCommonDivisor(left: number, right: number): number {
  let a = Math.abs(left)
  let b = Math.abs(right)
  while (b !== 0) {
    const next = a % b
    a = b
    b = next
  }
  return a || 1
}

function aspectRatioKey(aspectRatio?: string | null) {
  const [width, height] = parseAspectRatio(aspectRatio)
  return `${width}:${height}`
}

function resolutionKey(value?: string | null) {
  return String(value ?? "")
    .trim()
    .replace("×", "x")
    .replace("*", "x")
    .toLowerCase()
}

function canonicalTierLabel(value?: string | null) {
  const raw = String(value ?? "").trim()
  if (!raw) return ""
  const imageTier = Object.keys(IMAGE_TIER_SHORT_EDGE).find(
    (key) => key.toLowerCase() === raw.toLowerCase()
  )
  if (imageTier) return imageTier
  const videoTier = Object.keys(VIDEO_TIER_SHORT_EDGE).find(
    (key) => key.toLowerCase() === raw.toLowerCase()
  )
  if (videoTier) return videoTier
  return ""
}

function dimensionTierLabel(
  value: string | undefined,
  aliases: Record<string, string>
) {
  const key = resolutionKey(value)
  if (!key.includes("x")) return ""
  return aliases[key] ?? ""
}

function optionLabelFromOutputSize(
  mediaType: MediaType,
  size: string | undefined
) {
  return dimensionTierLabel(
    size,
    mediaType === "image" ? IMAGE_SIZE_TIER_ALIASES : VIDEO_SIZE_TIER_ALIASES
  )
}

function resolutionToShortEdge(
  resolution: string | undefined,
  tierMap: Record<string, number>,
  defaultShort: number
) {
  const raw = String(resolution ?? "").trim()
  if (!raw) return defaultShort
  const normalizedMap = Object.fromEntries(
    Object.entries(tierMap).map(([key, value]) => [key.toLowerCase(), value])
  )
  const fromTier = normalizedMap[raw.toLowerCase()]
  if (fromTier) return fromTier
  const match = raw.match(/^(\d+)\s*[xX×*]\s*(\d+)$/)
  if (match) {
    return Math.min(Number(match[1]), Number(match[2]))
  }
  if (/^\d+$/.test(raw)) return Number(raw)
  return defaultShort
}

function resolutionToLongEdge(
  resolution: string | undefined,
  tierMap: Record<string, number>,
  defaultLong: number
) {
  const raw = String(resolution ?? "").trim()
  if (!raw) return defaultLong
  const normalizedMap = Object.fromEntries(
    Object.entries(tierMap).map(([key, value]) => [key.toLowerCase(), value])
  )
  const fromTier = normalizedMap[raw.toLowerCase()]
  if (fromTier) return fromTier
  const match = raw.match(/^(\d+)\s*[xX×*]\s*(\d+)$/)
  if (match) {
    return Math.max(Number(match[1]), Number(match[2]))
  }
  if (/^\d+$/.test(raw)) return Number(raw)
  return defaultLong
}

function aspectSize(
  aspectRatio: string | undefined,
  shortEdge: number,
  options: {
    roundTo?: number
    maxLongEdge?: number
    maxTotalPixels?: number
    maxRatio?: number
  } = {}
) {
  const [widthRatio, heightRatio] = parseAspectRatio(aspectRatio)
  const roundTo = options.roundTo ?? 16
  const shortComponent = Math.min(widthRatio, heightRatio)
  const longComponent = Math.max(widthRatio, heightRatio)
  let t = Math.max(1, Math.round(shortEdge / (roundTo * shortComponent)))

  if (typeof options.maxLongEdge === "number") {
    const maxT = Math.floor(options.maxLongEdge / (roundTo * longComponent))
    t = Math.min(t, Math.max(1, maxT))
  }

  if (typeof options.maxTotalPixels === "number") {
    const denominator = widthRatio * heightRatio * roundTo * roundTo
    const maxT = denominator > 0 ? Math.floor(Math.sqrt(options.maxTotalPixels / denominator)) : 1
    t = Math.min(t, Math.max(1, maxT))
  }

  if (typeof options.maxRatio === "number") {
    const ratio = Math.max(widthRatio / heightRatio, heightRatio / widthRatio)
    if (ratio > options.maxRatio + 1e-9) {
      t = Math.max(1, t)
    }
  }

  return [widthRatio * roundTo * t, heightRatio * roundTo * t] as const
}

function aspectSizeFromLongEdge(
  aspectRatio: string | undefined,
  longEdge: number,
  options: {
    roundTo?: number
    maxLongEdge?: number
    maxTotalPixels?: number
    maxRatio?: number
  } = {}
) {
  const [widthRatio, heightRatio] = parseAspectRatio(aspectRatio)
  const roundTo = options.roundTo ?? 16
  const longComponent = Math.max(widthRatio, heightRatio)
  let t = Math.max(1, Math.round(longEdge / (roundTo * longComponent)))

  if (typeof options.maxLongEdge === "number") {
    const maxT = Math.floor(options.maxLongEdge / (roundTo * longComponent))
    t = Math.min(t, Math.max(1, maxT))
  }

  if (typeof options.maxTotalPixels === "number") {
    const denominator = widthRatio * heightRatio * roundTo * roundTo
    const maxT = denominator > 0 ? Math.floor(Math.sqrt(options.maxTotalPixels / denominator)) : 1
    t = Math.min(t, Math.max(1, maxT))
  }

  if (typeof options.maxRatio === "number") {
    const ratio = Math.max(widthRatio / heightRatio, heightRatio / widthRatio)
    if (ratio > options.maxRatio + 1e-9) {
      t = Math.max(1, t)
    }
  }

  return [widthRatio * roundTo * t, heightRatio * roundTo * t] as const
}

function genericImageSize(
  resolution: string,
  aspectRatio: string | undefined,
  options: {
    defaultShort?: number
    roundTo?: number
    maxLongEdge?: number
    maxTotalPixels?: number
    maxRatio?: number
  } = {}
) {
  const longEdge = resolutionToLongEdge(
    resolution,
    IMAGE_TIER_LONG_EDGE,
    options.defaultShort ?? DEFAULT_IMAGE_SHORT_EDGE
  )
  const [width, height] = aspectSizeFromLongEdge(aspectRatio, longEdge, {
    roundTo: options.roundTo ?? 16,
    maxLongEdge: options.maxLongEdge,
    maxTotalPixels: options.maxTotalPixels,
    maxRatio: options.maxRatio,
  })
  return `${width}x${height}`
}

function parseExplicitImageSize(resolution: string | undefined) {
  const match = String(resolution ?? "").trim().match(/^(\d+)\s*[xX×*]\s*(\d+)$/)
  if (!match) return undefined
  return [Number(match[1]), Number(match[2])] as const
}

function explicitImageSize(resolution: string | undefined) {
  const size = parseExplicitImageSize(resolution)
  if (!size) return ""
  return `${size[0]}x${size[1]}`
}

function modelImageResolutionSchema(model?: ResolutionPreviewModel) {
  return model?.image_resolution_schema ?? model?.imageResolutionSchema
}

function schemaNumber(
  schema: ImageResolutionSchema | undefined,
  snakeKey: keyof ImageResolutionSchema,
  camelKey: keyof ImageResolutionSchema,
  fallback?: number
) {
  const value = Number(schema?.[snakeKey] ?? schema?.[camelKey])
  return Number.isFinite(value) && value > 0 ? value : fallback
}

function canonicalImageResolution(value?: string | null) {
  const raw = String(value ?? "").trim()
  const lowered = raw.toLowerCase()
  if (lowered === "512" || lowered === "512px") return "512px"
  if (lowered === "1k" || lowered === "2k" || lowered === "3k" || lowered === "4k") {
    return lowered.toUpperCase()
  }
  const explicit = explicitImageSize(raw)
  return explicit || raw
}

function explicitImageSizeIsValid(
  size: readonly [number, number],
  schema?: ImageResolutionSchema,
  resolution?: string
) {
  const constraints = explicitPixelConstraints(schema, resolution)
  const [width, height] = size
  const multipleOf = Number(
    constraints.multiple_of ?? constraints.multipleOf ?? schema?.round_to ?? schema?.roundTo ?? 1
  )
  if (Number.isFinite(multipleOf) && multipleOf > 1) {
    if (width % multipleOf !== 0 || height % multipleOf !== 0) return false
  }
  const minLongEdge = Number(
    constraints.min_long_edge ?? constraints.minLongEdge ?? schema?.min_long_edge ?? schema?.minLongEdge
  )
  if (Number.isFinite(minLongEdge) && minLongEdge > 0 && Math.max(width, height) < minLongEdge) {
    return false
  }
  const minShortEdge = Number(constraints.min_short_edge ?? constraints.minShortEdge)
  if (Number.isFinite(minShortEdge) && minShortEdge > 0 && Math.min(width, height) < minShortEdge) {
    return false
  }
  const maxLongEdge = Number(
    constraints.max_long_edge ?? constraints.maxLongEdge ?? schema?.max_long_edge ?? schema?.maxLongEdge
  )
  if (Number.isFinite(maxLongEdge) && maxLongEdge > 0 && Math.max(width, height) > maxLongEdge) {
    return false
  }
  const minTotalPixels = Number(
    constraints.min_total_pixels ?? constraints.minTotalPixels ?? schema?.min_total_pixels ?? schema?.minTotalPixels
  )
  if (Number.isFinite(minTotalPixels) && minTotalPixels > 0 && width * height < minTotalPixels) {
    return false
  }
  const maxTotalPixels = Number(
    constraints.max_total_pixels ?? constraints.maxTotalPixels ?? schema?.max_total_pixels ?? schema?.maxTotalPixels
  )
  if (Number.isFinite(maxTotalPixels) && maxTotalPixels > 0 && width * height > maxTotalPixels) {
    return false
  }
  const maxRatio = Number(
    constraints.max_ratio ?? constraints.maxRatio ?? schema?.max_ratio ?? schema?.maxRatio
  )
  if (Number.isFinite(maxRatio) && maxRatio > 0 && Math.max(width / height, height / width) > maxRatio) {
    return false
  }
  return true
}

function imageResolutionDisallowedBySchema(
  schema: ImageResolutionSchema | undefined,
  resolution: string,
  hasReferenceImages?: boolean
) {
  if (typeof hasReferenceImages !== "boolean") return false
  const constraints = schema?.operation_constraints ?? schema?.operationConstraints
  if (!Array.isArray(constraints)) return false
  const key = resolutionKey(resolution).toUpperCase()
  return constraints.some((constraint) => {
    const when = constraint.when && typeof constraint.when === "object"
      ? (constraint.when as Record<string, unknown>)
      : {}
    if ("has_reference_images" in when && Boolean(when.has_reference_images) !== hasReferenceImages) {
      return false
    }
    if ("hasReferenceImages" in when && Boolean(when.hasReferenceImages) !== hasReferenceImages) {
      return false
    }
    const disallowed = constraint.disallow_resolutions ?? constraint.disallowResolutions
    return Array.isArray(disallowed) && disallowed.some((item) => resolutionKey(item).toUpperCase() === key)
  })
}

function schemaMaxTotalPixels(schema: ImageResolutionSchema | undefined, resolution: string) {
  const byResolution =
    schema?.max_total_pixels_by_resolution ?? schema?.maxTotalPixelsByResolution ?? {}
  const matched = byResolution[canonicalImageResolution(resolution)]
  if (Number.isFinite(Number(matched)) && Number(matched) > 0) return Number(matched)
  return schemaNumber(schema, "max_total_pixels", "maxTotalPixels")
}

function explicitPixelConstraints(schema: ImageResolutionSchema | undefined, resolution?: string) {
  const base = schema?.explicit_pixel_constraints ?? schema?.explicitPixelConstraints ?? {}
  const byResolution =
    schema?.explicit_pixel_constraints_by_resolution ??
    schema?.explicitPixelConstraintsByResolution ??
    {}
  const resolutionKey = canonicalImageResolution(resolution)
  const override = resolutionKey ? byResolution[resolutionKey] : undefined
  return { ...base, ...(override ?? {}) }
}

function constraintNumber(
  schema: ImageResolutionSchema | undefined,
  snakeKey: keyof ImageResolutionSchema,
  camelKey: keyof ImageResolutionSchema,
  fallback?: number,
  resolution?: string
) {
  const constraints = explicitPixelConstraints(schema, resolution)
  const value = Number(constraints[snakeKey] ?? constraints[camelKey] ?? schema?.[snakeKey] ?? schema?.[camelKey])
  return Number.isFinite(value) && value > 0 ? value : fallback
}

function schemaComputedImageSize(
  schema: ImageResolutionSchema | undefined,
  resolution: string,
  aspectRatio?: string
) {
  if (!schema) return undefined
  const constraints = explicitPixelConstraints(schema, resolution)
  const roundTo = Number(constraints.multiple_of ?? constraints.multipleOf) ||
    constraintNumber(schema, "round_to", "roundTo", 16, resolution) || 16
  const maxTotalPixels =
    constraintNumber(schema, "max_total_pixels", "maxTotalPixels", undefined, resolution) ??
    schemaMaxTotalPixels(schema, resolution)
  const initial = genericImageSize(resolution, aspectRatio, {
    roundTo,
    defaultShort: schemaNumber(schema, "default_long_edge", "defaultLongEdge", 1024),
    maxLongEdge: constraintNumber(schema, "max_long_edge", "maxLongEdge", undefined, resolution),
    maxTotalPixels,
    maxRatio: constraintNumber(schema, "max_ratio", "maxRatio", undefined, resolution),
  })
  const initialSize = parseExplicitImageSize(initial)
  if (!initialSize) return undefined

  const [widthRatio, heightRatio] = parseAspectRatio(aspectRatio)
  let t = Math.max(
    Math.floor(initialSize[0] / (widthRatio * roundTo)),
    Math.floor(initialSize[1] / (heightRatio * roundTo)),
    1
  )
  const minLongEdge = Number(constraints.min_long_edge ?? constraints.minLongEdge)
  if (Number.isFinite(minLongEdge) && minLongEdge > 0) {
    t = Math.max(t, Math.ceil(minLongEdge / (roundTo * Math.max(widthRatio, heightRatio))))
  }
  const minShortEdge = Number(constraints.min_short_edge ?? constraints.minShortEdge)
  if (Number.isFinite(minShortEdge) && minShortEdge > 0) {
    t = Math.max(t, Math.ceil(minShortEdge / (roundTo * Math.min(widthRatio, heightRatio))))
  }
  const minTotalPixels = Number(constraints.min_total_pixels ?? constraints.minTotalPixels)
  if (Number.isFinite(minTotalPixels) && minTotalPixels > 0) {
    const denominator = widthRatio * heightRatio * roundTo * roundTo
    t = Math.max(t, Math.ceil(Math.sqrt(minTotalPixels / denominator)))
  }

  const size = [widthRatio * roundTo * t, heightRatio * roundTo * t] as const
  if (!explicitImageSizeIsValid(size, schema, resolution)) return undefined
  return `${size[0]}x${size[1]}`
}

function schemaImageOutputSize(
  schema: ImageResolutionSchema | undefined,
  resolution: string,
  aspectRatio?: string
) {
  if (!schema) return undefined
  const separator = schema.separator === "*" ? "*" : "x"
  const canonicalResolution = canonicalImageResolution(resolution)
  const explicit = parseExplicitImageSize(canonicalResolution)
  const allowExplicit = Boolean(
    schema.allow_explicit_pixels ?? schema.allowExplicitPixels
  )
  if (explicit && allowExplicit) {
    if (!explicitImageSizeIsValid(explicit, schema, canonicalResolution)) return undefined
    return `${explicit[0]}${separator}${explicit[1]}`.replace("*", "x")
  }
  const sizeMode = String(schema.size_mode ?? schema.sizeMode ?? "")
  if (sizeMode === "native_tier" || sizeMode === "provider_tier") {
    if (schema.allow_explicit_pixels ?? schema.allowExplicitPixels) {
      return schemaComputedImageSize(schema, canonicalResolution, aspectRatio)
    }
    return undefined
  }
  if (sizeMode === "explicit_pixels") return undefined
  if (sizeMode === "computed_pixels") {
    return schemaComputedImageSize(schema, canonicalResolution, aspectRatio)
  }
  return undefined
}

function canonicalAspectRatio(value?: string | null) {
  const [width, height] = parseAspectRatio(value)
  return `${width}:${height}`
}

function dimensionsMatchAspect(
  size: readonly [number, number],
  aspectRatio?: string,
  tolerance = 0.03
) {
  const [targetWidth, targetHeight] = parseAspectRatio(aspectRatio)
  const target = targetWidth / targetHeight
  const actual = size[0] / size[1]
  return Math.abs(actual - target) / target <= tolerance
}

function aspectRatioWithinSchema(schema: ImageResolutionSchema | undefined, aspectRatio?: string) {
  if (!schema) return true
  const [width, height] = parseAspectRatio(aspectRatio)
  const allowed = schema.aspect_ratios ?? schema.aspectRatios
  if (allowed && !allowed.some((value) => {
    const [aw, ah] = parseAspectRatio(value)
    return aw * height === ah * width
  })) return false
  const maxRatio = schemaNumber(schema, "max_ratio", "maxRatio")
  return !maxRatio || Math.max(width / height, height / width) <= maxRatio + 1e-9
}

export function imageAspectRatioSupportedByModel(
  model: ResolutionPreviewModel | undefined,
  options: string[],
  aspectRatio: string,
  context: Pick<ResolutionFilterContext, "hasReferenceImages"> = {}
) {
  const schema = modelImageResolutionSchema(model)
  const explicitOptions = options
    .map((option) => ({ option, size: parseExplicitImageSize(option) }))
    .filter((item): item is { option: string; size: readonly [number, number] } =>
      Boolean(item.size)
    )
  if (explicitOptions.length) {
    return explicitOptions.some(({ option, size }) => {
      if (imageResolutionDisallowedBySchema(schema, option, context.hasReferenceImages)) {
        return false
      }
      const allowExplicit = Boolean(
        schema?.allow_explicit_pixels ?? schema?.allowExplicitPixels ?? !schema
      )
      return allowExplicit && explicitImageSizeIsValid(size, schema, option) && dimensionsMatchAspect(size, aspectRatio)
    })
  }
  if (!aspectRatioWithinSchema(schema, aspectRatio)) return false
  const sizeMode = String(schema?.size_mode ?? schema?.sizeMode ?? "")
  if (sizeMode === "computed_pixels") {
    const candidate = options[0] ?? "2K"
    return Boolean(schemaImageOutputSize(schema, candidate, aspectRatio))
  }
  if (sizeMode === "native_tier") {
    const nativeTiers = schema?.native_tiers ?? schema?.nativeTiers ?? []
    return Boolean((schema?.allow_explicit_pixels ?? schema?.allowExplicitPixels) || nativeTiers.length)
  }
  if (sizeMode === "explicit_pixels") {
    return Boolean(schema?.allow_explicit_pixels ?? schema?.allowExplicitPixels)
  }
  return true
}

export function resolveImageAspectRatioForModel(
  model: ResolutionPreviewModel | undefined,
  options: string[],
  aspectRatio: string,
  fallbackAspectRatio = "16:9",
  context: Pick<ResolutionFilterContext, "hasReferenceImages"> = {}
) {
  const desired = canonicalAspectRatio(aspectRatio)
  const fallback = canonicalAspectRatio(fallbackAspectRatio)
  if (imageAspectRatioSupportedByModel(model, options, desired, context)) return desired
  if (fallback !== desired && imageAspectRatioSupportedByModel(model, options, fallback, context)) {
    return fallback
  }
  return desired
}

export function filterImageResolutionOptionsForAspect(
  options: string[],
  aspectRatio: string,
  context: ResolutionFilterContext = {}
) {
  const schema = modelImageResolutionSchema(context.model)
  const [targetWidth, targetHeight] = parseAspectRatio(aspectRatio)
  const targetRatio = targetWidth / targetHeight
  const tierOptions: string[] = []
  const explicitOptions: Array<{ option: string; delta: number }> = []
  for (const option of options) {
    if (imageResolutionDisallowedBySchema(schema, option, context.hasReferenceImages)) {
      continue
    }
    const size = parseExplicitImageSize(option)
    if (!size) {
      tierOptions.push(option)
      continue
    }
    if (schema) {
      const allowExplicit = Boolean(
        schema.allow_explicit_pixels ?? schema.allowExplicitPixels
      )
      if (!allowExplicit || !explicitImageSizeIsValid(size, schema, option)) continue
    }
    const [width, height] = size
    explicitOptions.push({ option, delta: Math.abs(width / height - targetRatio) })
  }
  if (explicitOptions.length) {
    const bestDelta = Math.min(...explicitOptions.map((item) => item.delta))
    tierOptions.push(
      ...explicitOptions
        .filter((item) => context.includeAllAspects || Math.abs(item.delta - bestDelta) < 1e-9)
        .map((item) => item.option)
    )
  }
  if (tierOptions.length) return tierOptions
  return schema
    ? []
    : options.filter(
        (option) =>
          !imageResolutionDisallowedBySchema(schema, option, context.hasReferenceImages)
      )
}

function dashscopeExceedsStandardBudget(resolution: string) {
  const normalized = resolutionKey(resolution).toUpperCase()
  if (normalized === "4K") return true
  if (normalized === "1K" || normalized === "2K") return false
  if (!normalized.includes("X")) return false
  const [left, right] = normalized.split("X")
  const width = Number(left)
  const height = Number(right)
  if (!Number.isFinite(width) || !Number.isFinite(height)) return false
  return width * height > DASHSCOPE_STANDARD_PIXEL_BUDGET
}

function dashscopeImageSize(modelId: string, resolution: string, aspectRatio?: string) {
  const loweredModel = modelId.toLowerCase()
  const explicit = explicitImageSize(resolution)
  if (explicit) return explicit
  if (loweredModel.startsWith("wan")) {
    return genericImageSize(resolution || "2K", aspectRatio, {
      defaultShort: 1440,
      maxTotalPixels: dashscopeExceedsStandardBudget(resolution || "2K")
        ? DASHSCOPE_FOURK_PIXEL_BUDGET
        : DASHSCOPE_STANDARD_PIXEL_BUDGET,
      maxRatio: DASHSCOPE_MAX_RATIO,
    })
  }
  if (loweredModel.includes("qwen-image-edit")) {
    return genericImageSize(resolution || "2K", aspectRatio, {
      defaultShort: 2048,
      maxLongEdge: DASHSCOPE_EDIT_MAX_LONG_EDGE,
      maxRatio: DASHSCOPE_EDIT_MAX_RATIO,
    })
  }
  return genericImageSize(resolution || "2K", aspectRatio, {
    defaultShort: 2048,
    maxTotalPixels: DASHSCOPE_STANDARD_PIXEL_BUDGET,
    maxRatio: DASHSCOPE_MAX_RATIO,
  })
}

function soraVideoSize(modelId: string, resolution: string, aspectRatio?: string) {
  const [widthRatio, heightRatio] = parseAspectRatio(aspectRatio)
  const target = widthRatio / heightRatio
  const shortEdge = resolutionToShortEdge(
    resolution,
    VIDEO_TIER_SHORT_EDGE,
    DEFAULT_VIDEO_SHORT_EDGE
  )
  const supportedShorts = modelId.toLowerCase().includes("pro")
    ? [720, 1080]
    : [720]
  const achievedShort = [...supportedShorts].sort((left, right) => {
    const leftScore = Math.abs(left - shortEdge)
    const rightScore = Math.abs(right - shortEdge)
    if (leftScore !== rightScore) return leftScore - rightScore
    return right - left
  })[0]
  const legalSizes = achievedShort === 1080 ? SORA_SIZES_1080P : SORA_SIZES_720P
  return [...legalSizes].sort((left, right) => {
    const [lw, lh] = left.split("x").map(Number)
    const [rw, rh] = right.split("x").map(Number)
    const leftScore = Math.abs(lw / lh - target)
    const rightScore = Math.abs(rw / rh - target)
    if (leftScore !== rightScore) return leftScore - rightScore
    return rw * rh - lw * lh
  })[0]
}

function standardVideoSize(resolution: string, aspectRatio?: string) {
  const ratioKey = aspectRatioKey(aspectRatio)
  const normalizedResolution = resolutionKey(resolution)
  const presets = VIDEO_SIZE_PRESETS[ratioKey]
  if (presets) {
    const direct = Object.entries(presets).find(
      ([key]) => key.toLowerCase() === normalizedResolution
    )
    if (direct) return direct[1]
  }
  const match = String(resolution ?? "").trim().match(/^(\d+)\s*[xX×*]\s*(\d+)$/)
  if (match) {
    const width = Number(match[1])
    const height = Number(match[2])
    if (ratioKey === "16:9") {
      return width >= height ? `${width}x${height}` : `${height}x${width}`
    }
    if (ratioKey === "9:16") {
      return height >= width ? `${width}x${height}` : `${height}x${width}`
    }
    return `${width}x${height}`
  }
  const shortEdge = resolutionToShortEdge(
    resolution,
    VIDEO_TIER_SHORT_EDGE,
    DEFAULT_VIDEO_SHORT_EDGE
  )
  const [width, height] = aspectSize(aspectRatio, shortEdge, { roundTo: 8 })
  return `${width}x${height}`
}

function imageOutputSize(
  model: ResolutionPreviewModel | undefined,
  resolution: string,
  aspectRatio?: string
) {
  const schema = modelImageResolutionSchema(model)
  if (schema) {
    return schemaImageOutputSize(schema, resolution, aspectRatio)
  }
  const modelId = String(model?.id ?? "")
  const providerId = String(
    model?.provider_preset_id ??
      model?.providerPresetId ??
      model?.provider_id ??
      model?.providerId ??
      modelId.split(":")[0] ??
      ""
  ).trim()
  const normalizedModelId = modelId.includes(":") ? modelId.split(":").slice(1).join(":") : modelId
  if ((providerId === "ark-seedance" || providerId === "ark") && normalizedModelId.toLowerCase().includes("seedream")) {
    const explicit = String(resolution ?? "").trim()
    if (/^[1-4]k$/i.test(explicit)) return undefined
    if (/^\d+\s*[xX×*]\s*\d+$/.test(explicit)) {
      const [width, height] = explicit
        .replace("×", "x")
        .replace("*", "x")
        .split("x")
        .map(Number)
      return `${width}x${height}`
    }
    return genericImageSize(resolution, aspectRatio)
  }
  if (providerId === "dashscope") {
    return dashscopeImageSize(normalizedModelId, resolution, aspectRatio)
  }
  if (normalizedModelId.toLowerCase() === "gpt-image-2") {
    return genericImageSize(resolution, aspectRatio, {
      defaultShort: 1024,
      maxLongEdge: GPT_IMAGE_MAX_LONG_EDGE,
      maxTotalPixels: GPT_IMAGE_MAX_TOTAL_PIXELS,
      maxRatio: GPT_IMAGE_MAX_RATIO,
    })
  }
  return genericImageSize(resolution, aspectRatio)
}

function videoOutputSize(
  model: ResolutionPreviewModel | undefined,
  resolution: string,
  aspectRatio?: string
) {
  const modelId = String(model?.id ?? "")
  const normalizedModelId = modelId.includes(":") ? modelId.split(":").slice(1).join(":") : modelId
  if (normalizedModelId.toLowerCase().includes("sora")) {
    return soraVideoSize(normalizedModelId, resolution, aspectRatio)
  }
  return standardVideoSize(resolution, aspectRatio)
}

export function describeModelResolutionOption(params: {
  mediaType: MediaType
  model?: ResolutionPreviewModel
  resolution: string
  aspectRatio?: string
}) {
  const { mediaType, model, resolution, aspectRatio } = params
  const displayLabel = getModelResolutionDisplayLabel({
    mediaType,
    model,
    resolution,
    aspectRatio,
  })
  const rawHint =
    displayLabel && displayLabel.toLowerCase() !== String(resolution).trim().toLowerCase()
      ? `供应商值 ${resolution} · `
      : ""
  const explicitAspect = aspectRatio ? [aspectRatio] : ["16:9", "9:16"]
  const labels = explicitAspect
    .map((ratio) => {
      const size =
        mediaType === "image"
          ? imageOutputSize(model, resolution, ratio)
          : videoOutputSize(model, resolution, ratio)
      if (!size) {
        return ratio === "16:9"
          ? "16:9 由供应商按档位输出"
          : "9:16 由供应商按档位输出"
      }
      return explicitAspect.length === 1 ? size : `${ratio} ${size}`
    })
    .filter(Boolean)
  return `${rawHint}${labels.join(" / ")}`
}

export function getModelResolutionDisplayLabel(params: {
  mediaType: MediaType
  model?: ResolutionPreviewModel
  resolution: string
  aspectRatio?: string
}) {
  const { mediaType, model, resolution, aspectRatio } = params
  const canonical = canonicalTierLabel(resolution)
  if (canonical) return canonical
  const directDimensionLabel = dimensionTierLabel(
    resolution,
    mediaType === "image" ? IMAGE_SIZE_TIER_ALIASES : VIDEO_SIZE_TIER_ALIASES
  )
  if (directDimensionLabel) return directDimensionLabel
  // Estimated preview dimensions are not aliases for a provider's API values.
  // An unknown video tier must retain its identity instead of becoming 720p.
  if (mediaType === "video") return String(resolution || "").trim()
  const size = imageOutputSize(model, resolution, aspectRatio || "16:9")
  return optionLabelFromOutputSize(mediaType, size) || String(resolution || "")
}
