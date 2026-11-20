import type { VideoCapabilityMetadata } from "@/utils/video-model-capabilities"
import type { ModelAvailability } from "@/shared/model-availability"

export type ProviderConnectionStatus =
  | "unconfigured"
  | "untested"
  | "connected"
  | "failed"

export type ProviderModelInfo = VideoCapabilityMetadata & ModelAvailability & {
  id: string
  label: string
  type: "image" | "video" | "text"
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
  endpoint?: string
  media_type?: "image" | "video" | "text"
  display_name?: string
  resolutions?: string[]
  default_resolution?: string
  image_output_formats?: string[]
  durations?: number[]
  duration_resolution_constraints?: Record<string, number[]>
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
  usage?: string
  routing_status?: "ready" | "pending"
  routing_note?: string
}

export type ProviderAdapterId =
  | "openai-compatible"
  | "anthropic-compatible"
  | "minimax-compatible"
  | "autodl-comfyui"
  | "gemini-compatible"
  | "ark-seedance"
  | "dashscope"
  | "vidu"
  | "grok"
  | "newapi-video"
  | string

export type ProviderProbeSummary = {
  auth?: "ok" | "failed" | "unknown"
  modelsList?: "ok" | "warn" | "failed" | "unsupported" | "unknown"
  nativeJsonSchema?: "supported" | "unsupported" | "unknown"
  nativeJsonSchemaModel?: string
  endpoints?: Record<string, string>
  claudeAgentSdk?: "supported" | "unsupported" | "unknown"
  agentRouteReady?: boolean
  claudeAgentBaseUrl?: string
  relayPlatform?: "new-api" | "sub2api" | string
}

export type ProviderRow = {
  id: string
  adapterId?: ProviderAdapterId
  adapter_id?: ProviderAdapterId
  presetId?: string
  preset_id?: string
  title: string
  name?: string
  officialTitle?: string
  official_title?: string
  logo?: string
  iconKey?: string
  description?: string
  baseUrl?: string
  baseUrlOptions?: Array<{
    label: string
    baseUrl?: string
    baseUrlTemplate?: string
  }>
  baseUrlNote?: string
  defaultBaseUrl?: string
  docsUrl?: string
  keyLabel?: string
  capabilities?: string[]
  models?: ProviderModelInfo[]
  configured?: boolean
  apiKey?: string
  apiKeyMasked?: string
  connectionStatus?: ProviderConnectionStatus
  lastTest?: ProviderTestResult | null
  probeSummary?: ProviderProbeSummary
  nativeStructuredOutput?: "supported" | "unsupported" | "unknown"
  userAdded?: boolean
  addedAt?: string | null
}

export type ProviderTestResult = {
  overall: "ok" | "warn" | "fail"
  catalogComplete?: boolean
  configurationPreserved?: boolean
  status: "connected" | "failed"
  message: string
  error?: string
  checkedAt?: string
  latencyMs?: number
  availableModels?: ProviderModelInfo[]
  remoteModels?: ProviderModelInfo[]
  remoteModelIds?: string[]
  capabilities?: string[]
  verifiedCapabilities?: string[]
  probeSummary?: ProviderProbeSummary
  capabilityResults?: Record<string, {
    status: "ok" | "failed" | "unsupported" | "unknown"
    message: string
    modelCount: number
    pendingModelCount?: number
    modelSource?: "remote" | "preset" | "mixed"
  }>
  pendingModels?: Array<{ id: string; type: string; reason: string }>
  probes?: Array<{
    name: string
    status: string
    message?: string
    error?: string
    model?: string
    attempts?: string[]
  }>
}

export const providerCapabilityLabels: Record<string, string> = {
  storyboard_image: "故事板分镜图片",
  asset_image: "角色/生物/场景/道具图",
  storyboard_video: "故事版视频",
  agent: "智能体",
  text_generation: "文本生成",
}

const providerCapabilityValues = new Set(Object.keys(providerCapabilityLabels))

function normalizeProviderCapabilities(value?: string[]) {
  const rows: string[] = []
  for (const item of value ?? []) {
    const capability = String(item ?? "").trim()
    if (capability && providerCapabilityValues.has(capability)) {
      rows.push(capability)
    }
  }
  return Array.from(new Set(rows))
}

export function reconcileProviderCapabilities(
  selected: string[],
  result?: Pick<ProviderTestResult, "overall" | "verifiedCapabilities">
) {
  const selectedCapabilities = normalizeProviderCapabilities(selected)
  if (result?.overall !== "ok") return selectedCapabilities

  const verified = new Set(normalizeProviderCapabilities(result.verifiedCapabilities))
  if (!verified.size) return selectedCapabilities

  const reconciled = selectedCapabilities.filter((capability) => verified.has(capability))
  return reconciled.length ? reconciled : selectedCapabilities
}

export const providerCapabilityGroupLabels: Record<string, string> = {
  image: "图片",
  video: "视频",
  text: "文本",
  agent: "智能体",
}

export const providerCapabilityGroupOrder = ["image", "agent", "text", "video"]

export const providerCapabilityGroupStyles: Record<string, string> = {
  image:
    "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900/60 dark:bg-sky-950/35 dark:text-sky-300",
  video:
    "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700 dark:border-fuchsia-900/60 dark:bg-fuchsia-950/35 dark:text-fuchsia-300",
  text: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/35 dark:text-amber-300",
  agent:
    "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/35 dark:text-emerald-300",
}

export const providerCapabilityGroupOptions = [
  {
    id: "image",
    capabilities: ["storyboard_image", "asset_image"],
  },
  {
    id: "agent",
    capabilities: ["agent"],
  },
  {
    id: "text",
    capabilities: ["text_generation"],
  },
  {
    id: "video",
    capabilities: ["storyboard_video"],
  },
]

export const providerAdapterLabels: Record<string, string> = {
  "openai-compatible": "OpenAI 格式接口",
  "anthropic-compatible": "Anthropic 兼容",
  "minimax-compatible": "MiniMax H3 视频接口",
  "autodl-comfyui": "AutoDL ComfyUI 工作流接口",
  "gemini-compatible": "Gemini 兼容",
  "ark-seedance": "火山 Ark / Seedance",
  dashscope: "阿里 DashScope",
  vidu: "Vidu",
  grok: "Grok",
  "newapi-video": "NewAPI 视频",
}

export function providerDiscoveryUrlPreview(
  provider: ProviderRow,
  rawBaseUrl: string
) {
  let trimmed = rawBaseUrl.trim().replace(/\/+$/, "")
  if (!trimmed) return ""
  if (trimmed.endsWith("/models")) {
    trimmed = trimmed.slice(0, -"/models".length).replace(/\/+$/, "")
  }
  const adapterId = getProviderAdapterId(provider)
  if (adapterId === "autodl-comfyui") return `${trimmed}/workflows/{workflow_id}`
  if (adapterId === "minimax-compatible") return `${trimmed}/v1/models`
  if (adapterId === "gemini-compatible") {
    const base = trimmed.replace(/\/v\d+\w*$/, "")
    return `${base}/v1beta/models`
  }
  if (adapterId === "anthropic-compatible") {
    const base = trimmed.endsWith("/v1") ? trimmed : `${trimmed}/v1`
    return `${base}/models`
  }
  if (adapterId === "newapi-video") {
    const root = trimmed
      .replace(/\/video\/generations$/i, "")
      .replace(/\/+$/, "")
    const base = /\/v\d+$/.test(root) ? root : `${root}/v1`
    return `${base}/models`
  }
  const base = /\/v\d+$/.test(trimmed) ? trimmed : `${trimmed}/v1`
  return `${base}/models`
}

export function inferProviderAdapterId(
  provider: Partial<ProviderRow>
): ProviderAdapterId {
  const raw =
    provider.adapterId ??
    provider.adapter_id ??
    provider.presetId ??
    provider.preset_id ??
    provider.id ??
    ""
  const value = String(raw).trim()
  if (value === "openai") return "openai-compatible"
  if (value === "metaso") return "minimax-compatible"
  if (
    value === "anthropic" ||
    value === "deepseek" ||
    value === "minimax" ||
    value === "ark-agent-plan"
  ) {
    return "anthropic-compatible"
  }
  if (value === "gemini") return "gemini-compatible"
  if (value === "newapi" || value === "v2-video-generations")
    return "newapi-video"
  return value || "openai-compatible"
}

export function getProviderAdapterId(
  provider: Partial<ProviderRow>
): ProviderAdapterId {
  return inferProviderAdapterId(provider)
}

export function getProviderCapabilityGroups(
  provider: Pick<ProviderRow, "capabilities" | "models">
) {
  const groups = new Set<string>()
  for (const capability of normalizeProviderCapabilities(provider.capabilities)) {
    if (capability.includes("image")) groups.add("image")
    if (capability.includes("video")) groups.add("video")
    if (capability === "agent") groups.add("agent")
    if (capability.includes("text")) groups.add("text")
  }
  if (!groups.size) {
    for (const model of provider.models ?? []) {
      if (model.type === "image") groups.add("image")
      if (model.type === "video") groups.add("video")
      if (model.type === "text") groups.add("text")
    }
  }
  return providerCapabilityGroupOrder.filter((group) => groups.has(group))
}

export const providerStatusView: Record<
  ProviderConnectionStatus,
  { label: string; className: string }
> = {
  unconfigured: {
    label: "未配置",
    className:
      "border-gray-200 bg-gray-50 text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400",
  },
  untested: {
    label: "待获取模型",
    className:
      "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300",
  },
  connected: {
    label: "已获取模型",
    className:
      "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300",
  },
  failed: {
    label: "获取失败",
    className:
      "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300",
  },
}

export const fallbackProviders: ProviderRow[] = [
  {
    id: "custom-provider",
    presetId: "custom-provider",
    adapterId: "openai-compatible",
    title: "自定义供应商",
    logo: "API",
    description: "用于 sub2api、new-api 等中转平台，可接入其中的多个官方模型。",
    baseUrl: "",
    keyLabel: "API_KEY",
    capabilities: [
      "storyboard_image",
      "asset_image",
      "agent",
      "text_generation",
      "storyboard_video",
    ],
    configured: false,
    connectionStatus: "unconfigured",
  },
  {
    id: "ark-seedance",
    adapterId: "ark-seedance",
    title: "火山方舟",
    logo: "SD",
    iconKey: "Volcengine",
    description: "火山方舟：图片、智能体、文本和视频模型。",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    keyLabel: "ARK_API_KEY",
    capabilities: [
      "storyboard_image",
      "asset_image",
      "agent",
      "storyboard_video",
      "text_generation",
    ],
    configured: false,
    connectionStatus: "unconfigured",
  },
  {
    id: "ark-agent-plan",
    adapterId: "anthropic-compatible",
    title: "火山方舟 Agent Plan",
    logo: "ARK",
    iconKey: "Volcengine",
    description: "火山方舟 Agent Plan 智能体接口。",
    baseUrl: "https://ark.cn-beijing.volces.com/api/plan",
    keyLabel: "ARK_API_KEY",
    capabilities: ["agent"],
    configured: false,
    connectionStatus: "unconfigured",
  },
  {
    id: "deepseek",
    adapterId: "anthropic-compatible",
    title: "DeepSeek",
    logo: "DS",
    iconKey: "DeepSeek",
    description: "DeepSeek 文本与智能体接口。",
    baseUrl: "https://api.deepseek.com/anthropic",
    docsUrl: "https://api-docs.deepseek.com",
    keyLabel: "DEEPSEEK_API_KEY",
    capabilities: ["text_generation", "agent"],
    configured: false,
    connectionStatus: "unconfigured",
  },
  {
    id: "minimax",
    adapterId: "anthropic-compatible",
    title: "MiniMax",
    logo: "MM",
    iconKey: "MiniMax",
    description: "MiniMax：图片、智能体、文本和视频生成。",
    baseUrl: "https://api.minimax.cn/anthropic",
    docsUrl: "https://platform.minimax.cn/docs/api-reference/text-anthropic-api",
    keyLabel: "MINIMAX_API_KEY",
    capabilities: ["storyboard_image", "asset_image", "agent", "text_generation", "storyboard_video"],
    configured: false,
    connectionStatus: "unconfigured",
  },
  {
    id: "autodl-comfyui",
    adapterId: "autodl-comfyui",
    title: "autodl ComfyUI",
    logo: "AD",
    description: "AutoDL ComfyUI：MiniMax H3 多参考图、升级画质和首尾帧视频生成。",
    baseUrl: "https://autodl.art/api/v1/comfyui",
    docsUrl: "https://autodl.art/docs/comfyui_api/",
    keyLabel: "AUTODL_API_KEY",
    capabilities: ["storyboard_video"],
    configured: false,
    connectionStatus: "unconfigured",
  },
  {
    id: "metaso",
    adapterId: "minimax-compatible",
    title: "秘塔（Metaso）",
    logo: "秘塔",
    iconKey: "Metaso",
    description: "秘塔部署的 MiniMax H3，支持参考图/视频和原生首尾帧视频生成。",
    baseUrl: "https://metaso.cn/api/minimax",
    docsUrl: "https://metaso.cn/minimax-h3",
    keyLabel: "METASO_API_KEY",
    capabilities: ["storyboard_video"],
    configured: false,
    connectionStatus: "unconfigured",
  },
  {
    id: "dashscope",
    adapterId: "dashscope",
    title: "阿里百炼",
    logo: "ALI",
    iconKey: "Bailian",
    description: "阿里百炼：图片、智能体、文本和视频生成。",
    baseUrl: "https://dashscope.aliyuncs.com",
    baseUrlOptions: [
      { label: "公共接口", baseUrl: "https://dashscope.aliyuncs.com" },
      { label: "Workspace（北京）", baseUrlTemplate: "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com" },
    ],
    keyLabel: "DASHSCOPE_API_KEY",
    capabilities: [
      "storyboard_image",
      "asset_image",
      "agent",
      "storyboard_video",
      "text_generation",
    ],
    configured: false,
    connectionStatus: "unconfigured",
  },
  {
    id: "gemini",
    adapterId: "gemini-compatible",
    title: "Gemini",
    logo: "G",
    iconKey: "Gemini",
    description: "Gemini：图片和文本模型。",
    baseUrl: "https://generativelanguage.googleapis.com",
    keyLabel: "GEMINI_API_KEY",
    capabilities: [
      "storyboard_image",
      "asset_image",
      "text_generation",
    ],
    configured: false,
    connectionStatus: "unconfigured",
  },
  {
    id: "vidu",
    adapterId: "vidu",
    title: "Vidu",
    logo: "VD",
    iconKey: "Vidu",
    description: "Vidu 图片与视频生成。",
    baseUrl: "https://api.vidu.cn/ent/v2",
    baseUrlOptions: [
      { label: "中国区域", baseUrl: "https://api.vidu.cn/ent/v2" },
      { label: "海外区域", baseUrl: "https://api.vidu.com/ent/v2" },
    ],
    keyLabel: "VIDU_API_KEY",
    capabilities: ["storyboard_image", "asset_image", "storyboard_video"],
    configured: false,
    connectionStatus: "unconfigured",
  },
  {
    id: "qiniu",
    adapterId: "openai-compatible",
    title: "七牛云",
    logo: "七牛",
    description: "七牛云：图片、智能体、文本和视频模型。",
    baseUrl: "https://api.qnaigc.com/v1",
    docsUrl: "https://developer.qiniu.com/aitokenapi",
    keyLabel: "QINIU_API_KEY",
    capabilities: ["storyboard_image", "asset_image", "agent", "text_generation", "storyboard_video"],
    configured: false,
    connectionStatus: "unconfigured",
  },
]

export function normalizeProvider(
  raw: Partial<ProviderRow> & { default_base_url?: string }
): ProviderRow {
  const adapterId = inferProviderAdapterId(raw)
  const baseUrl = raw.baseUrl ?? ""
  const probeSummary =
    raw.probeSummary ?? raw.lastTest?.probeSummary ?? undefined
  const preset = fallbackProviders.find((item) => item.id === (raw.presetId ?? raw.preset_id ?? raw.id))
  const capabilities = normalizeProviderCapabilities(raw.capabilities)
  return {
    id: raw.id ?? "provider",
    adapterId,
    adapter_id: adapterId,
    presetId: raw.presetId ?? raw.preset_id,
    preset_id: raw.preset_id ?? raw.presetId,
    title: raw.title ?? raw.name ?? raw.id ?? "供应商",
    name: raw.name,
    officialTitle: raw.officialTitle ?? raw.official_title,
    official_title: raw.official_title ?? raw.officialTitle,
    logo: raw.logo ?? (raw.title ?? raw.name ?? "?").slice(0, 2).toUpperCase(),
    iconKey: raw.iconKey ?? raw.logo ?? "",
    description: raw.description ?? "",
    baseUrl,
    baseUrlOptions: raw.baseUrlOptions ?? [],
    baseUrlNote: raw.baseUrlNote ?? "",
    defaultBaseUrl: raw.defaultBaseUrl ?? raw.default_base_url ?? baseUrl,
    docsUrl: raw.docsUrl ?? "",
    keyLabel: raw.keyLabel ?? "API_KEY",
    capabilities: preset ? capabilities.filter((capability) => (preset.capabilities ?? []).includes(capability)) : capabilities,
    models: raw.models ?? [],
    configured: Boolean(raw.configured),
    apiKey: raw.apiKey ?? "",
    apiKeyMasked: raw.apiKeyMasked ?? "",
    connectionStatus:
      raw.connectionStatus ?? (raw.configured ? "untested" : "unconfigured"),
    lastTest: raw.lastTest ?? null,
    probeSummary,
    nativeStructuredOutput:
      raw.nativeStructuredOutput ?? probeSummary?.nativeJsonSchema ?? "unknown",
    userAdded: Boolean(raw.userAdded),
    addedAt: raw.addedAt ?? null,
  }
}

export function mergeProviderPresets(raw?: ProviderRow[]) {
  const byId = new Map((raw ?? []).map((provider) => [provider.id, provider]))
  return fallbackProviders.map((preset) =>
    normalizeProvider({
      ...preset,
      ...byId.get(preset.id),
      title: preset.title,
      description: preset.description,
      capabilities: preset.capabilities,
      logo: preset.logo,
      iconKey: preset.iconKey,
    })
  )
}
