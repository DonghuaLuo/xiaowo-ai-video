import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import AnthropicMono from "@lobehub/icons/es/Anthropic/components/Mono"
import BailianColor from "@lobehub/icons/es/Bailian/components/Color"
import DeepSeekColor from "@lobehub/icons/es/DeepSeek/components/Color"
import GeminiColor from "@lobehub/icons/es/Gemini/components/Color"
import OpenAIMono from "@lobehub/icons/es/OpenAI/components/Mono"
import ViduColor from "@lobehub/icons/es/Vidu/components/Color"
import VolcengineColor from "@lobehub/icons/es/Volcengine/components/Color"
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  ExternalLink,
  Image as ImageIcon,
  Loader2,
  Pencil,
  Plus,
  RefreshCcw,
  Save,
  Sparkles,
  Trash2,
  Video,
  type LucideIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import { ProviderCapabilityGroupBadges } from "@/features/settings/provider-badges"
import { ProviderCapabilitySelector } from "./provider-capability-selector"
import { useProviderProbeProgress } from "./use-provider-probe-progress"
import {
  fallbackProviders,
  getProviderAdapterId,
  mergeProviderPresets,
  normalizeProvider,
  providerAdapterLabels,
  providerCapabilityGroupLabels,
  providerCapabilityGroupOptions,
  providerDiscoveryUrlPreview,
  reconcileProviderCapabilities,
  providerStatusView,
  type ProviderRow,
  type ProviderTestResult,
} from "@/features/settings/provider-model"
import { ModalShell, SectionPanel } from "@/shared/page-shell"

function ProviderBrandIcon({
  provider,
  size = 22,
}: {
  provider: ProviderRow
  size?: number
}) {
  const iconKey = provider.iconKey || provider.logo || provider.id
  if (iconKey === "OpenAI" || provider.id.includes("openai")) {
    return <OpenAIMono size={size} />
  }
  if (
    iconKey === "Volcengine" ||
    provider.id.includes("ark") ||
    provider.id.includes("seedance")
  ) {
    return <VolcengineColor size={size} />
  }
  if (iconKey === "DeepSeek" || provider.id.includes("deepseek")) {
    return <DeepSeekColor size={size} />
  }
  if (iconKey === "MiniMax" || provider.id.includes("minimax")) {
    return <span className="font-mono text-[11px] font-semibold">MM</span>
  }
  if (iconKey === "Anthropic" || provider.id.includes("anthropic")) {
    return <AnthropicMono size={size} />
  }
  if (iconKey === "Gemini" || provider.id.includes("gemini")) {
    return <GeminiColor size={size} />
  }
  if (
    iconKey === "Bailian" ||
    iconKey === "DashScope" ||
    provider.id.includes("dashscope")
  ) {
    return <BailianColor size={size} />
  }
  if (iconKey === "Vidu" || provider.id.includes("vidu")) {
    return <ViduColor size={size} />
  }
  return (
    <span className="font-mono text-[11px] font-semibold">
      {(provider.logo || provider.title || "?").slice(0, 3).toUpperCase()}
    </span>
  )
}

function ProviderLogoFrame({
  provider,
  className,
  iconSize = 22,
}: {
  provider: ProviderRow
  className?: string
  iconSize?: number
}) {
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-lg border border-gray-200/70 bg-white text-gray-950 shadow-sm dark:border-white/10 dark:bg-white/90 dark:text-gray-950",
        className
      )}
      title={provider.title}
    >
      <ProviderBrandIcon provider={provider} size={iconSize} />
    </span>
  )
}

const providerShortDescriptions: Record<string, string> = {
  "custom-provider": "自定义供应商：用于 sub2api、new-api 等中转平台。",
  "ark-seedance": "火山方舟：图片、智能体、文本和视频模型。",
  "ark-agent-plan": "火山方舟智能体接口。",
  deepseek: "DeepSeek 文本与智能体接口。",
  minimax: "MiniMax：图片、智能体、文本和视频生成。",
  metaso: "秘塔：MiniMax H3 视频，支持参考图/视频和原生首尾帧。",
  "autodl-comfyui": "AutoDL ComfyUI：H3 多参考图、升级画质和首尾帧视频。",
  dashscope: "阿里百炼：图片、智能体、文本和视频生成。",
  anthropic: "Anthropic/Claude 兼容文本接口。",
  gemini: "Gemini：图片和文本模型。",
  vidu: "Vidu：图片和视频生成。",
  grok: "xAI 图片生成。Grok 视频当前不作为故事版视频预设。",
}

const adapterShortDescriptions: Record<string, string> = {
  "openai-compatible": "OpenAI 格式接口：用于自定义中转平台的请求。",
  "anthropic-compatible": "Anthropic/Claude 兼容文本接口。",
  "autodl-comfyui": "AutoDL 托管的 ComfyUI 视频工作流。",
  "gemini-compatible": "Gemini：图片和文本模型。",
  "ark-seedance": "火山方舟：图片、智能体、文本和视频模型。",
  dashscope: "阿里百炼：图片、智能体、文本和视频生成。",
  vidu: "Vidu：图片和视频生成。",
  grok: "xAI 图片生成。Grok 视频当前不作为故事版视频预设。",
}

function getProviderShortDescription(provider: ProviderRow) {
  const presetId = provider.presetId || provider.preset_id || ""
  const adapterId = getProviderAdapterId(provider)
  return (
    providerShortDescriptions[presetId] ||
    providerShortDescriptions[provider.id] ||
    adapterShortDescriptions[adapterId] ||
    provider.description ||
    "供应商实例。"
  )
}

function hasUnresolvedBaseUrlTemplate(value: string) {
  return /\{[^{}]+\}/.test(value)
}

function RecommendedModelTag({
  icon: Icon,
  mediaType,
  model,
  className,
}: {
  icon: LucideIcon
  mediaType: string
  model: string
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex min-h-7 max-w-full items-center gap-1.5 rounded-md border px-2 py-1 shadow-sm",
        className
      )}
    >
      <span className="inline-flex shrink-0 items-center gap-1 text-[10px] leading-none font-semibold">
        <Icon className="size-3.5" />
        <span>{mediaType}</span>
      </span>
      <span className="min-w-0 text-[11px] leading-tight font-semibold break-words">
        {model}
      </span>
    </span>
  )
}

function ProviderAddRecommendation() {
  const apiLinks = [
    {
      label: "GPT Image 2",
      href: "https://codex.xiaowoai.com",
    },
    {
      label: "火山方舟",
      href: "https://console.volcengine.com/ark/region:cn-beijing/openManagement",
    },
  ]

  return (
    <div className="space-y-2.5 rounded-xl border border-indigo-200/70 bg-white/80 px-3 py-2.5 text-gray-700 shadow-sm ring-1 ring-indigo-100/70 break-words dark:border-indigo-500/30 dark:bg-white/[0.045] dark:text-gray-200 dark:ring-indigo-500/10">
      <div className="flex flex-wrap items-center gap-1.5 md:flex-nowrap">
        <Badge
          variant="outline"
          className="min-h-7 border-indigo-200 bg-indigo-50 px-2 text-indigo-700 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-200"
        >
          <Sparkles className="size-3" />
          推荐组合
        </Badge>
        <RecommendedModelTag
          icon={ImageIcon}
          mediaType="图片"
          model="GPT Image 2"
          className="border-sky-200 bg-sky-50 text-sky-900 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100"
        />
        <ArrowRight className="size-4 shrink-0 text-gray-400 dark:text-gray-500" />
        <RecommendedModelTag
          icon={Video}
          mediaType="视频"
          model="火山方舟 Seedance 2.0+"
          className="border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-100"
        />
      </div>
      <div className="grid gap-2">
        {apiLinks.map((link) => (
          <a
            key={link.href}
            href={link.href}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-w-0 items-center gap-2 rounded-lg border border-gray-200/70 bg-white/75 px-2.5 py-2 text-gray-700 shadow-sm transition-colors hover:border-indigo-300 hover:text-indigo-700 dark:border-white/10 dark:bg-white/[0.045] dark:text-gray-300 dark:hover:border-indigo-500/50 dark:hover:text-indigo-200"
          >
            <ExternalLink className="size-3.5 shrink-0" />
            <span className="inline-flex min-h-6 w-fit shrink-0 items-center justify-center whitespace-nowrap rounded-md border border-indigo-200 bg-indigo-50 px-2 text-[11px] font-semibold text-indigo-700 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-200">
              {link.label}
            </span>
            <span className="min-w-0 font-mono text-[11px] font-medium break-all text-gray-900 dark:text-gray-100">
              {link.href}
            </span>
          </a>
        ))}
      </div>
    </div>
  )
}

function ProviderEndpointSelector({
  provider,
  baseUrl,
  setBaseUrl,
}: {
  provider: ProviderRow
  baseUrl: string
  setBaseUrl: (value: string) => void
}) {
  const options = provider.baseUrlOptions ?? []
  const exactIndex = options.findIndex((option) => option.baseUrl === baseUrl)
  const selectedIndex = Math.max(
    0,
    exactIndex >= 0
      ? exactIndex
      : options.findIndex((option) => {
          const template = option.baseUrlTemplate
          if (!template?.includes("{WorkspaceId}")) return false
          const [prefix, suffix] = template.split("{WorkspaceId}")
          return baseUrl.startsWith(prefix) && baseUrl.endsWith(suffix)
        })
  )
  const option = options[selectedIndex] ?? options[0]
  const template = option?.baseUrlTemplate ?? ""
  const prefix = template.split("{WorkspaceId}")[0]
  const suffix = template.split("{WorkspaceId}")[1] ?? ""
  const workspaceId = template
    ? baseUrl !== template && baseUrl.startsWith(prefix) && baseUrl.endsWith(suffix)
      ? baseUrl.slice(prefix.length, baseUrl.length - suffix.length)
      : ""
    : ""

  const selectOption = (nextIndex: number) => {
    const next = options[nextIndex]
    if (next?.baseUrl) setBaseUrl(next.baseUrl)
    else if (next?.baseUrlTemplate) setBaseUrl(next.baseUrlTemplate)
  }

  return (
    <div className="space-y-1.5">
      <span className="block text-xs text-gray-500 dark:text-gray-400">请求区域</span>
      <select
        value={selectedIndex}
        onChange={(event) => selectOption(Number(event.target.value))}
        className="h-9 w-full rounded-md border border-gray-200/70 bg-white/70 px-2 text-sm text-gray-900 outline-none focus:border-indigo-400 dark:border-white/10 dark:bg-white/[0.045] dark:text-gray-100"
      >
        {options.map((item, optionIndex) => (
          <option key={`${item.label}:${optionIndex}`} value={optionIndex}>
            {item.label}
          </option>
        ))}
      </select>
      {template ? (
        <Input
          value={workspaceId}
          onChange={(event) => {
            const value = event.target.value.trim()
            setBaseUrl(value ? template.replace("{WorkspaceId}", value) : template)
          }}
          placeholder="Workspace ID"
          className="bg-white/70"
        />
      ) : null}
    </div>
  )
}

export function ProviderSettings({
  openAddOnMount = false,
  onConfigureModels,
}: {
  openAddOnMount?: boolean
  onConfigureModels: () => void
}) {
  const { backendReady, callBackend } = useBackend()
  const [providers, setProviders] = useState<ProviderRow[]>([])
  const [presets, setPresets] = useState<ProviderRow[]>(mergeProviderPresets())
  const [selectedId, setSelectedId] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [addOpen, setAddOpen] = useState(false)
  const [editingProvider, setEditingProvider] = useState<ProviderRow | null>(
    null
  )
  const [deletingProvider, setDeletingProvider] = useState<ProviderRow | null>(
    null
  )
  const [busyId, setBusyId] = useState<string | null>(null)
  const [testedId, setTestedId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null)

  const selectedProvider =
    providers.find((provider) => provider.id === selectedId) ?? providers[0]
  const selectedProviderModels = selectedProvider?.models?.filter((model) => {
    const adapterId = getProviderAdapterId(selectedProvider)
    const isRelayModel = adapterId === "openai-compatible" || adapterId === "newapi-video"
    return !isRelayModel || model.type !== "video" || model.routing_status === "ready"
  }) ?? []
  const hasProviders = providers.length > 0

  const loadProviders = useCallback(async () => {
    if (!backendReady) return
    setLoading(true)
    setError("")
    try {
      const result = await callBackend<{
        providers?: ProviderRow[]
        presets?: ProviderRow[]
        success?: false
        message?: string
      }>("list_providers")
      if (result.success === false) {
        throw new Error(result.message || "加载供应商失败")
      }
      const nextProviders = (result.providers ?? []).map(normalizeProvider)
      const nextPresets = mergeProviderPresets(result.presets)
      setProviders(nextProviders)
      setPresets(nextPresets)
      setSelectedId((currentId) =>
        nextProviders.some((provider) => provider.id === currentId)
          ? currentId
          : (nextProviders[0]?.id ?? "")
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载供应商失败")
    } finally {
      setLoading(false)
    }
  }, [backendReady, callBackend])

  useEffect(() => {
    void loadProviders()
  }, [loadProviders])

  useEffect(() => {
    if (openAddOnMount) {
      setAddOpen(true)
    }
  }, [openAddOnMount])

  const handleAddProvider = async (payload: Record<string, unknown>) => {
    const result = await callBackend<{
      success: boolean
      provider?: ProviderRow
      message?: string
    }>("add_provider", payload)
    if (!result.success || !result.provider) {
      throw new Error(result.message || "添加供应商失败")
    }
    const provider = normalizeProvider(result.provider)
    setProviders((rows) => [
      ...rows.filter((row) => row.id !== provider.id),
      provider,
    ])
    setSelectedId(provider.id)
    setAddOpen(false)
    setTestedId(provider.id)
    setTestResult(provider.lastTest ?? null)
  }

  const handleTestProviderDraft = async (payload: Record<string, unknown>) => {
    const result = await callBackend<{
      success: boolean
      provider?: ProviderRow
      result?: ProviderTestResult
      message?: string
    }>("test_provider_connection", payload)
    if (result.result) {
      return result.result
    }
    return {
      overall: result.success ? "ok" : "fail",
      status: result.success ? "connected" : "failed",
      message: result.message || (result.success ? "模型目录已获取" : "获取模型失败"),
      error: result.success ? "" : result.message,
    } satisfies ProviderTestResult
  }

  const handleUpdateProvider = async (payload: Record<string, unknown>) => {
    const result = await callBackend<{
      success: boolean
      provider?: ProviderRow
      message?: string
    }>("update_provider", payload)
    if (!result.success || !result.provider) {
      throw new Error(result.message || "保存供应商失败")
    }
    const provider = normalizeProvider(result.provider)
    setProviders((rows) =>
      rows.map((row) => (row.id === provider.id ? provider : row))
    )
    setSelectedId(provider.id)
    setEditingProvider(null)
    setTestedId(null)
    setTestResult(null)
  }

  const handleDeleteProvider = async (providerId: string) => {
    const result = await callBackend<{
      success: boolean
      providerId?: string
      message?: string
    }>("delete_provider", { providerId })
    if (!result.success) {
      throw new Error(result.message || "删除供应商失败")
    }
    setProviders((rows) => {
      const nextRows = rows.filter((row) => row.id !== providerId)
      setSelectedId((currentId) =>
        currentId === providerId ? (nextRows[0]?.id ?? "") : currentId
      )
      return nextRows
    })
    setDeletingProvider(null)
    setTestedId(null)
    setTestResult(null)
  }

  const handleTestProvider = async (providerId: string) => {
    if (!backendReady) return
    setBusyId(providerId)
    setTestedId(providerId)
    setTestResult(null)
    try {
      const result = await callBackend<{
        success: boolean
        provider?: ProviderRow
        result?: ProviderTestResult
        message?: string
      }>("test_provider_connection", { providerId })
      if (result.provider) {
        const provider = normalizeProvider(result.provider)
        setProviders((rows) =>
          rows.map((row) => (row.id === provider.id ? provider : row))
        )
      }
      if (result.result) {
        setTestResult(result.result)
      } else if (!result.success) {
        setTestResult({
          overall: "fail",
          status: "failed",
          message: result.message || "获取模型失败",
          error: result.message,
        })
      }
    } catch (err) {
      setTestResult({
        overall: "fail",
        status: "failed",
        message: err instanceof Error ? err.message : "获取模型失败",
        error: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <SectionPanel
        eyebrow="Providers"
        title="供应商配置"
        className="mb-6 flex h-[calc(100dvh-192px)] min-h-[420px] flex-col"
        bodyClassName="flex min-h-0 flex-1 flex-col"
      >
        <div className="mb-4 flex shrink-0 flex-wrap items-center justify-between gap-3">
          <div className="flex-1" />
          <div className="flex items-center gap-2">
            {hasProviders ? (
              <Button type="button" variant="outline" size="sm" className="gap-2" onClick={onConfigureModels}>
                <ArrowRight className="size-4" />去选择模型
              </Button>
            ) : null}
            {error ? (
              <Badge
                variant="outline"
                className="rounded-full border-rose-200 text-rose-600 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200"
              >
                {error}
              </Badge>
            ) : null}
            <Button
              variant="gradient"
              className="gap-2"
              size="sm"
              onClick={() => setAddOpen(true)}
            >
              <Plus className="size-4" />
              添加供应商
            </Button>
          </div>
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 items-stretch gap-4 overflow-hidden",
            hasProviders
              ? "xl:grid-cols-[minmax(0,1fr)_440px]"
              : "grid-cols-1"
          )}
        >
          <div className="min-h-0 space-y-2 overflow-y-auto overscroll-contain pr-1 [contain:layout_paint] [overflow-anchor:none] [scrollbar-gutter:stable]">
            {loading ? (
              <div className="flex items-center gap-2 rounded-xl border border-gray-200/70 bg-white/60 px-4 py-5 text-sm text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
                <Loader2 className="size-4 animate-spin text-indigo-500" />
                正在加载供应商
              </div>
            ) : null}
            {!loading && providers.length === 0 ? (
              <button
                type="button"
                className="flex min-h-[180px] w-full cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-gray-300/80 bg-white/45 px-5 py-8 text-center transition-colors hover:border-indigo-300 hover:bg-indigo-50/35 dark:border-white/15 dark:bg-white/[0.035] dark:hover:border-indigo-800/70 dark:hover:bg-indigo-950/20"
                onClick={() => setAddOpen(true)}
              >
                <Plus className="size-6 text-indigo-500" />
                <div className="mt-3 text-sm font-semibold text-gray-950 dark:text-gray-50">
                  暂无已添加供应商
                </div>
                <p className="mt-1 max-w-md text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                  点击这里或右上角“添加供应商”，确认保存后才会写入全局配置并显示在这里。
                </p>
              </button>
            ) : null}
            {providers.map((provider) => {
              const status =
                providerStatusView[
                  provider.connectionStatus ??
                    (provider.configured ? "untested" : "unconfigured")
                ]
              const active = selectedProvider?.id === provider.id
              const showResult = testedId === provider.id && testResult
              return (
                <div key={provider.id}>
                  <div
                    role="button"
                    tabIndex={0}
                    className={cn(
                      "flex min-h-[76px] w-full cursor-pointer items-center gap-3 rounded-xl border bg-white/70 px-3 py-3 text-left transition-colors dark:bg-white/[0.035]",
                      active
                        ? "border-indigo-200 bg-indigo-50/55 dark:border-indigo-900/60 dark:bg-indigo-950/20"
                        : "border-gray-200/70 hover:border-indigo-200 dark:border-white/10 dark:hover:border-indigo-800/60",
                      showResult ? "rounded-b-none" : undefined
                    )}
                    onClick={() => setSelectedId(provider.id)}
                    onMouseDown={(event) => {
                      if ((event.target as HTMLElement).closest("button"))
                        return
                      event.preventDefault()
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault()
                        setSelectedId(provider.id)
                      }
                    }}
                  >
                    <ProviderLogoFrame
                      provider={provider}
                      className="size-10"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex min-h-[24px] items-center gap-2 overflow-hidden">
                        <span className="truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
                          {provider.title}
                        </span>
                      </span>
                      <ProviderCapabilityGroupBadges
                        provider={provider}
                        className="mt-1 min-h-[22px] overflow-hidden"
                      />
                    </span>
                    <span className="flex shrink-0 flex-wrap justify-end gap-1.5">
                      <Badge
                        variant="outline"
                        className="shrink-0 rounded-full text-[11px]"
                      >
                        {provider.configured ? "已配置" : "未配置"}
                      </Badge>
                      <Badge
                        variant="outline"
                        className={cn(
                          "shrink-0 rounded-full text-[11px]",
                          status.className
                        )}
                      >
                        {status.label}
                      </Badge>
                    </span>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="shrink-0 gap-1.5"
                      disabled={!backendReady}
                      onClick={(event) => {
                        event.stopPropagation()
                        setEditingProvider(provider)
                      }}
                    >
                      <Pencil className="size-3.5" />
                      编辑
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="size-8 shrink-0"
                      title={busyId === provider.id ? "正在获取模型" : "刷新模型"}
                      aria-label={`刷新${provider.title}模型`}
                      disabled={busyId === provider.id || !backendReady}
                      onClick={(event) => {
                        event.stopPropagation()
                        void handleTestProvider(provider.id)
                      }}
                    >
                      {busyId === provider.id ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        <RefreshCcw className="size-3.5" />
                      )}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="shrink-0 gap-1.5 border-rose-200 text-rose-600 hover:bg-rose-50 hover:text-rose-700 dark:border-rose-900/60 dark:text-rose-300 dark:hover:bg-rose-950/25"
                      disabled={!backendReady}
                      onClick={(event) => {
                        event.stopPropagation()
                        setDeletingProvider(provider)
                      }}
                    >
                      <Trash2 className="size-3.5" />
                      删除
                    </Button>
                  </div>
                  {showResult ? (
                    <ProviderTestResultPanel result={testResult} />
                  ) : null}
                </div>
              )
            })}
          </div>

          {selectedProvider ? (
            <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-gray-200/70 bg-white/60 p-4 dark:border-white/10 dark:bg-white/[0.03]">
              <div className="flex items-start gap-3">
                <ProviderLogoFrame
                  provider={selectedProvider}
                  className="size-11"
                  iconSize={24}
                />
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-gray-950 dark:text-gray-50">
                    {selectedProvider.title}
                  </h3>
                  <p className="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                    {getProviderShortDescription(selectedProvider)}
                  </p>
                </div>
              </div>
              <div className="mt-4 shrink-0 space-y-3">
                <InfoRow
                  label="协议适配器"
                  value={
                    providerAdapterLabels[
                      getProviderAdapterId(selectedProvider)
                    ] ?? getProviderAdapterId(selectedProvider)
                  }
                />
                <InfoRow
                  label="Base URL"
                  value={selectedProvider.baseUrl || "未填写"}
                />
                <InfoRow
                  label="密钥"
                  value={
                    selectedProvider.apiKeyMasked ||
                    selectedProvider.keyLabel ||
                    "API_KEY"
                  }
                />
                <InfoRow
                  label="模型数"
                  value={`${selectedProviderModels.length} 个`}
                />
              </div>
              <div className="mt-4 min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain pr-1 [scrollbar-gutter:stable]">
                {selectedProviderModels.map((model) => (
                  <div
                    key={model.id}
                    className="rounded-lg border border-gray-200/70 bg-white/75 p-3 dark:border-white/10 dark:bg-white/[0.035]"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
                        {model.label}
                      </div>
                      <Badge
                        variant="outline"
                        className="rounded-full text-[11px]"
                      >
                        {model.type}
                      </Badge>
                    </div>
                    <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                      {model.usage || "模型能力"}
                    </div>
                  </div>
                ))}
                {selectedProviderModels.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-gray-200/70 p-3 text-xs text-gray-500 dark:border-white/10 dark:text-gray-400">
                    暂无已适配模型
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      </SectionPanel>
      {addOpen ? (
        <ProviderAddDialog
          presets={presets}
          onClose={() => setAddOpen(false)}
          onTest={handleTestProviderDraft}
          onSubmit={handleAddProvider}
        />
      ) : null}
      {editingProvider ? (
        <ProviderEditDialog
          provider={editingProvider}
          onClose={() => setEditingProvider(null)}
          onTest={handleTestProviderDraft}
          onSubmit={handleUpdateProvider}
        />
      ) : null}
      {deletingProvider ? (
        <ProviderDeleteDialog
          provider={deletingProvider}
          onClose={() => setDeletingProvider(null)}
          onSubmit={handleDeleteProvider}
        />
      ) : null}
    </>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <span className="text-gray-500 dark:text-gray-400">{label}</span>
      <span className="min-w-0 truncate font-mono text-gray-700 dark:text-gray-300">
        {value}
      </span>
    </div>
  )
}

function failedProviderTest(error: unknown, capabilities: string[]): ProviderTestResult {
  return {
    overall: "fail",
    status: "failed",
    message: "获取模型失败",
    error: error instanceof Error ? error.message : String(error),
    capabilityResults: Object.fromEntries(
      providerCapabilityGroupOptions
        .filter((option) => option.capabilities.some((capability) => capabilities.includes(capability)))
        .map((option) => [option.id, { status: "failed" as const, message: "获取模型失败", modelCount: 0 }])
    ),
  }
}

function ProviderTestResultPanel({
  result,
  attached = true,
}: {
  result: ProviderTestResult
  attached?: boolean
}) {
  const partial = result.overall === "warn" || (result.overall === "ok" && (
    result.catalogComplete === false || result.configurationPreserved === true
  ))
  const ok = result.overall === "ok" && !partial
  const successfulGroups = Object.values(result.capabilityResults ?? {}).filter((probe) => probe.status === "ok")
  const presetOnly = successfulGroups.length > 0 && successfulGroups.every((probe) => probe.modelSource === "preset")
  const errorMessage = result.error || (
    result.overall === "fail" && !result.configurationPreserved ? result.message : ""
  )
  const showAgentProbe =
    Boolean(result.capabilities?.includes("agent")) ||
    result.probeSummary?.agentRouteReady === true
  return (
    <div
      className={cn(
        attached ? "rounded-b-xl border border-t-0" : "rounded-xl border",
        "px-4 py-3 text-xs",
        ok
          ? "border-emerald-200 bg-emerald-50/75 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200"
          : partial
            ? "border-amber-200 bg-amber-50/75 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-200"
            : "border-rose-200 bg-rose-50/75 text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200"
      )}
    >
      <div className="flex items-start gap-2 leading-relaxed font-semibold">
        {ok ? (
          <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
        ) : (
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        )}
        <span className="min-w-0 flex-1 break-words">{ok ? (presetOnly ? "预置目录已载入" : "模型目录已获取") : partial ? "部分模型获取失败" : "获取模型失败"}</span>
      </div>
      {result.configurationPreserved ? <div className="mt-2">已保留原配置</div> : null}
      {ok && presetOnly && result.probeSummary?.auth === "unknown" ? (
        <div className="mt-2">已载入预置模型目录；API Key、账户权限及生成结果尚未验证。</div>
      ) : null}
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        <div className="font-mono text-[11px] opacity-80">
          耗时：{result.latencyMs ?? 0} ms
        </div>
        <div className="font-mono text-[11px] opacity-80">
          模型：{result.remoteModelIds?.length ?? result.availableModels?.length ?? 0} 个
        </div>
        {result.probeSummary?.relayPlatform ? (
          <div className="font-mono text-[11px] opacity-80 md:col-span-2">
            平台基座：{result.probeSummary.relayPlatform === "new-api" ? "New API" : result.probeSummary.relayPlatform}
          </div>
        ) : null}
        {showAgentProbe && !result.capabilityResults ? (
          <div className="font-mono text-[11px] opacity-80 md:col-span-2">
            智能体路由：{result.probeSummary?.agentRouteReady ? "已配置" : "未配置"}
          </div>
        ) : null}
      </div>
      {result.capabilityResults ? (
        <div className="mt-3 space-y-2">
          {Object.entries(result.capabilityResults).map(([group, probe]) => (
            <div key={group} className="flex items-start gap-2">
              {probe.status === "ok" ? (
                <CheckCircle2 className="mt-0.5 size-3.5 shrink-0" />
              ) : (
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-600 dark:text-amber-300" />
              )}
              <span className="min-w-0 break-words">
                {providerCapabilityGroupLabels[group] ?? group}：
                {probe.status === "ok" ? `${probe.modelCount} 个模型` : probe.status === "unknown" ? `未确认（${probe.modelCount} 个模型）` : "未获取"}
                {probe.status === "ok" && probe.modelSource ? (
                  <span className="ml-2 opacity-80">
                    {probe.modelSource === "preset" ? "预置目录" : probe.modelSource === "mixed" ? "接口 + 预置" : "接口获取"}
                  </span>
                ) : null}
                {probe.status === "ok" && (probe.pendingModelCount ?? 0) > 0 ? (
                  <span className="ml-2 text-amber-600 dark:text-amber-300">{probe.pendingModelCount} 个待适配</span>
                ) : null}
                {group === "text" && probe.status === "ok" && result.probeSummary?.nativeJsonSchema && result.probeSummary.nativeJsonSchema !== "unknown" ? (
                  <span className="ml-2 opacity-80" title={result.probeSummary?.nativeJsonSchemaModel ?? "结构化输出"}>
                    {result.probeSummary.nativeJsonSchema === "supported" ? "结构化支持" : "结构化不支持"}
                  </span>
                ) : null}
              </span>
            </div>
          ))}
        </div>
      ) : null}
      {result.capabilityResults ? (
        <details className="mt-3">
          <summary className="cursor-pointer opacity-80">获取详情</summary>
          <div className="mt-2 max-h-40 space-y-1 overflow-auto break-words">
            {Object.entries(result.capabilityResults).filter(([, probe]) => probe.status !== "ok").map(([group, probe]) => (
              <div key={group}>{providerCapabilityGroupLabels[group] ?? group}：{probe.message}</div>
            ))}
            {Object.entries(result.capabilityResults).filter(([, probe]) => probe.modelSource === "preset").map(([group]) => (
              <div key={`source:${group}`}>{providerCapabilityGroupLabels[group] ?? group}：本地模型目录，非在线模型列表</div>
            ))}
            {Object.entries(result.capabilityResults).filter(([, probe]) => probe.modelSource === "mixed").map(([group]) => (
              <div key={`source:${group}`}>{providerCapabilityGroupLabels[group] ?? group}：含官方目录模型，未逐模型验证 Key 权限</div>
            ))}
            {(result.probes ?? []).filter((probe) => probe.model || probe.error).map((probe, index) => (
              <div key={`${probe.name}:${index}`}>
                {probe.model ? <span className="font-mono">{probe.model}：</span> : null}
                {probe.status === "ok" ? "通过" : probe.status === "unsupported" ? "不支持" : "待验证"}
                {probe.error ? <div className="opacity-80">{probe.attempts?.join("；") || probe.error}</div> : null}
              </div>
            ))}
          </div>
        </details>
      ) : null}
      {result.pendingModels?.length ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-amber-700 dark:text-amber-300">
            待适配模型（{result.pendingModels.length}）
          </summary>
          <div className="mt-2 max-h-40 space-y-1 overflow-auto">
            {result.pendingModels.map((model) => (
              <div key={`${model.type}:${model.id}`} className="break-all">
                {model.id}：{model.reason}
              </div>
            ))}
          </div>
        </details>
      ) : null}
      {errorMessage ? (
        <pre className="mt-2 max-h-32 overflow-auto rounded-lg bg-white/70 p-2 font-mono text-[11px] break-all whitespace-pre-wrap dark:bg-black/20">
          {errorMessage}
        </pre>
      ) : null}
    </div>
  )
}

function ProviderAddDialog({
  presets,
  onClose,
  onTest,
  onSubmit,
}: {
  presets: ProviderRow[]
  onClose: () => void
  onTest: (payload: Record<string, unknown>) => Promise<ProviderTestResult>
  onSubmit: (payload: Record<string, unknown>) => Promise<void>
}) {
  const [presetId, setPresetId] = useState(presets[0]?.id ?? "custom-provider")
  const [apiKey, setApiKey] = useState("")
  const [baseUrl, setBaseUrl] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [capabilities, setCapabilities] = useState<string[]>(["agent"])
  const [submitting, setSubmitting] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null)
  const [testedFingerprint, setTestedFingerprint] = useState("")
  const [error, setError] = useState("")
  const testPanelRef = useRef<HTMLDivElement | null>(null)

  const selected =
    presets.find((preset) => preset.id === presetId) ?? presets[0]
  const adapterId = getProviderAdapterId(selected ?? {})
  const defaultDisplayName =
    selected?.title || providerAdapterLabels[adapterId] || "供应商"
  const draftPayload = useMemo(
    () => ({
      presetId: selected?.presetId || presetId,
      adapterId,
      apiKey,
      baseUrl,
      title: displayName.trim() || defaultDisplayName,
      capabilities,
    }),
    [
      adapterId,
      apiKey,
      baseUrl,
      capabilities,
      defaultDisplayName,
      displayName,
      presetId,
      selected?.presetId,
    ]
  )
  const draftFingerprint = useMemo(
    () => JSON.stringify(draftPayload),
    [draftPayload]
  )
  const currentDraftFingerprint = useRef(draftFingerprint)
  currentDraftFingerprint.current = draftFingerprint
  const probeProgress = useProviderProbeProgress(draftFingerprint)
  const canTest = Boolean(
    apiKey.trim() && baseUrl.trim() && !hasUnresolvedBaseUrlTemplate(baseUrl) &&
    capabilities.length
  )
  const testPassed =
    Boolean(testResult && testResult.overall === "ok") &&
    testedFingerprint === draftFingerprint
  const discoveryPreview = selected
    ? providerDiscoveryUrlPreview(selected, baseUrl)
    : ""

  useEffect(() => {
    setBaseUrl(selected?.baseUrl ?? "")
    setCapabilities(
      selected?.capabilities?.length ? selected.capabilities : ["agent"]
    )
    setDisplayName("")
  }, [selected?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (testedFingerprint !== draftFingerprint) {
      setTestResult(null)
      setTestedFingerprint("")
    }
  }, [draftFingerprint, testedFingerprint])

  useEffect(() => {
    if (!testResult) return
    const frame = window.requestAnimationFrame(() => {
      testPanelRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "end",
      })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [testResult])

  const handleTest = async () => {
    if (!canTest) {
      setError(selected?.id === "custom-provider"
        ? "请填写完整 Base URL、API Key，并至少选择一类能力"
        : "请填写完整请求地址、API Key，并至少选择一类能力")
      return
    }
    setTesting(true)
    setError("")
    setTestResult(null)
    setTestedFingerprint("")
    const requestId = probeProgress.begin(capabilities)
    try {
      const result = await onTest({ ...draftPayload, probeRequestId: requestId })
      if (currentDraftFingerprint.current !== draftFingerprint) return
      const nextCapabilities = reconcileProviderCapabilities(capabilities, result)
      setCapabilities(nextCapabilities)
      setTestResult(result)
      setTestedFingerprint(JSON.stringify({ ...draftPayload, capabilities: nextCapabilities }))
    } catch (err) {
      if (currentDraftFingerprint.current !== draftFingerprint) return
      setTestResult(failedProviderTest(err, capabilities))
      setTestedFingerprint(draftFingerprint)
    } finally {
      probeProgress.finish(requestId)
      setTesting(false)
    }
  }

  const handleSubmit = async () => {
    if (!testPassed) {
      setError("请先获取模型")
      return
    }
    setSubmitting(true)
    setError("")
    try {
      const testedModels = testResult?.availableModels
      await onSubmit({
        ...draftPayload,
        capabilities,
        ...(testedModels ? { models: testedModels } : {}),
        connectionTestPassed: true,
        lastTest: testResult,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "添加供应商失败")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ModalShell
      title="添加供应商"
      className="max-w-[1170px]"
      onClose={onClose}
      footer={
        <>
          <Button type="button" variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            type="button"
            variant={testPassed ? "outline" : "default"}
            className="gap-2"
            disabled={testing || submitting || !canTest}
            onClick={handleTest}
          >
            {testing ? <Loader2 className="size-4 animate-spin" /> : <RefreshCcw className="size-4" />}
            {testing ? "正在获取" : testPassed ? "重新获取" : "获取模型"}
          </Button>
          {testPassed ? (
            <Button
              type="button"
              className="gap-2"
              disabled={submitting}
              onClick={handleSubmit}
            >
              {submitting ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Save className="size-4" />
              )}
              添加供应商
            </Button>
          ) : null}
        </>
      }
    >
      <div className="grid items-stretch gap-5 md:h-[70dvh] md:max-h-[720px] md:min-h-0 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:grid-cols-[minmax(480px,1fr)_minmax(500px,1fr)]">
        <aside className="flex min-h-0 min-w-0 flex-col gap-3">
          <ProviderAddRecommendation />

          <div className="flex min-h-0 flex-1 flex-col gap-2">
            <div className="text-xs font-medium text-gray-500 dark:text-gray-400">
              供应商列表
            </div>
            <div className="max-h-[220px] [scrollbar-gutter:stable] overflow-y-auto overscroll-contain pr-1 sm:max-h-[260px] md:min-h-0 md:max-h-none md:flex-1">
              <div className="grid gap-2">
                {presets.map((preset) => {
                  const active = preset.id === presetId
                  return (
                    <button
                      key={preset.id}
                      type="button"
                      className={cn(
                        "flex w-full items-center gap-2.5 rounded-xl border px-2.5 py-2 text-left transition-colors",
                        active
                          ? "border-indigo-300 bg-indigo-50/80 dark:border-indigo-800/60 dark:bg-indigo-950/25"
                          : "border-gray-200/70 bg-white/70 hover:border-indigo-200 dark:border-white/10 dark:bg-white/[0.035]"
                      )}
                      onClick={() => setPresetId(preset.id)}
                    >
                      <ProviderLogoFrame
                        provider={preset}
                        className="size-9 shrink-0"
                      />
                      <span className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_max-content] items-center gap-3">
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
                            {preset.title}
                          </span>
                          <span className="mt-0.5 line-clamp-1 text-[11px] leading-relaxed text-gray-500 dark:text-gray-400">
                            {preset.description}
                          </span>
                        </span>
                        <ProviderCapabilityGroupBadges
                          provider={active && testResult?.capabilityResults
                            ? {
                              ...preset,
                              capabilities,
                              models: testResult.availableModels ?? [],
                            }
                            : preset}
                          agentMode="candidate"
                          className="ml-auto flex-nowrap items-center justify-end"
                        />
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          </div>
        </aside>

        <section className="min-h-0 min-w-0 space-y-5 md:overflow-y-auto md:border-l md:border-gray-200/70 md:pr-1 md:pl-5 dark:md:border-white/10">
          <label className="block">
            <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
              自定义名称
            </span>
            <Input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder={`默认：${defaultDisplayName}`}
              className="bg-white/70"
            />
          </label>

          <div className="space-y-3">
            {selected?.id === "custom-provider" ? (
              <div className="block">
                <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
                  Base URL
                </span>
                <Input
                  value={baseUrl}
                  onChange={(event) => setBaseUrl(event.target.value)}
                  placeholder={selected?.baseUrl || "https://api.example.com/v1"}
                  className="bg-white/70"
                />
                {discoveryPreview ? (
                  <div className="mt-1.5 rounded-lg border border-gray-200/70 bg-white/60 px-2.5 py-2 text-[11px] text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
                    <span className="mr-2">探测地址</span>
                    <span className="font-mono break-all text-gray-700 dark:text-gray-300">
                      {discoveryPreview}
                    </span>
                  </div>
                ) : null}
              </div>
            ) : null}
            {selected && selected.id !== "custom-provider" && selected.baseUrlOptions?.length ? (
              <ProviderEndpointSelector
                key={selected.id}
                provider={selected}
                baseUrl={baseUrl}
                setBaseUrl={setBaseUrl}
              />
            ) : null}
            <label className="block">
              <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
                API Key
              </span>
              <Input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={selected?.keyLabel || "API_KEY"}
                className="bg-white/70"
              />
            </label>
          </div>

          <ProviderCapabilitySelector
            capabilities={capabilities}
            setCapabilities={setCapabilities}
            progress={testResult?.capabilityResults ?? probeProgress.progress}
            supportedCapabilities={selected?.id === "custom-provider" ? undefined : selected?.capabilities}
          />

          <div
            ref={testPanelRef}
            className="space-y-3 rounded-xl border border-gray-200/70 bg-white/55 p-3 dark:border-white/10 dark:bg-white/[0.035]"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              {!testResult ? (
                <div className="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                  {testing ? "正在获取模型" : "尚未获取模型"}
                </div>
              ) : null}
            </div>
            {testResult ? (
              <ProviderTestResultPanel result={testResult} attached={false} />
            ) : null}
          </div>

          {error ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-300">
              {error}
            </div>
          ) : null}
        </section>
      </div>
    </ModalShell>
  )
}

function ProviderEditDialog({
  provider,
  onClose,
  onTest,
  onSubmit,
}: {
  provider: ProviderRow
  onClose: () => void
  onTest: (payload: Record<string, unknown>) => Promise<ProviderTestResult>
  onSubmit: (payload: Record<string, unknown>) => Promise<void>
}) {
  const [apiKey, setApiKey] = useState(provider.apiKey ?? "")
  const [showApiKey, setShowApiKey] = useState(false)
  const [baseUrl, setBaseUrl] = useState(provider.baseUrl ?? "")
  const [title, setTitle] = useState(provider.title ?? "")
  const [capabilities, setCapabilities] = useState<string[]>(
    provider.capabilities ?? []
  )
  const [submitting, setSubmitting] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null)
  const [testedFingerprint, setTestedFingerprint] = useState("")
  const [error, setError] = useState("")
  const adapterId = getProviderAdapterId(provider)
  const preset = fallbackProviders.find(
    (item) => item.id === (provider.presetId || provider.preset_id || provider.id)
  )
  const draftPayload = useMemo(
    () => ({
      providerId: provider.id,
      id: provider.id,
      adapterId,
      apiKey,
      baseUrl,
      title,
      capabilities,
      models: provider.models,
    }),
    [
      adapterId,
      apiKey,
      baseUrl,
      capabilities,
      provider.id,
      provider.models,
      title,
    ]
  )
  const draftFingerprint = useMemo(
    () => JSON.stringify(draftPayload),
    [draftPayload]
  )
  const canTest = Boolean(
    (apiKey.trim() || provider.configured) && baseUrl.trim() &&
    !hasUnresolvedBaseUrlTemplate(baseUrl) && capabilities.length
  )
  const currentDraftFingerprint = useRef(draftFingerprint)
  currentDraftFingerprint.current = draftFingerprint
  const testPassed =
    Boolean(testResult && testResult.overall === "ok") &&
    testedFingerprint === draftFingerprint
  const discoveryPreview = providerDiscoveryUrlPreview(provider, baseUrl)
  const isPresetProvider = fallbackProviders.some(
    (preset) => preset.id !== "custom-provider" &&
      preset.id === (provider.presetId || provider.preset_id || provider.id)
  )
  const usesEditableBaseUrl = !isPresetProvider || adapterId === "newapi-video"
  const probeProgress = useProviderProbeProgress(draftFingerprint)

  useEffect(() => {
    if (testedFingerprint !== draftFingerprint) {
      setTestResult(null)
      setTestedFingerprint("")
    }
  }, [draftFingerprint, testedFingerprint])

  const handleTest = async () => {
    if (!canTest) {
      setError("请填写完整请求地址、API Key，并至少选择一类能力")
      return
    }
    setTesting(true)
    setError("")
    setTestResult(null)
    setTestedFingerprint("")
    const requestId = probeProgress.begin(capabilities)
    try {
      const result = await onTest({ ...draftPayload, probeRequestId: requestId })
      if (currentDraftFingerprint.current !== draftFingerprint) return
      const nextCapabilities = reconcileProviderCapabilities(capabilities, result)
      setCapabilities(nextCapabilities)
      setTestResult(result)
      setTestedFingerprint(JSON.stringify({ ...draftPayload, capabilities: nextCapabilities }))
    } catch (err) {
      if (currentDraftFingerprint.current !== draftFingerprint) return
      setTestResult(failedProviderTest(err, capabilities))
      setTestedFingerprint(draftFingerprint)
    } finally {
      probeProgress.finish(requestId)
      setTesting(false)
    }
  }

  const handleSubmit = async () => {
    if (!testPassed) {
      setError("请先获取模型")
      return
    }
    setSubmitting(true)
    setError("")
    try {
      const testedModels = testResult?.availableModels ?? provider.models
      await onSubmit({
        ...draftPayload,
        capabilities,
        ...(testedModels ? { models: testedModels } : {}),
        connectionTestPassed: true,
        lastTest: testResult,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存供应商失败")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ModalShell
      title="编辑供应商"
      onClose={onClose}
      footer={
        <>
          <Button type="button" variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            type="button"
            className="gap-2"
            disabled={submitting || !testPassed}
            onClick={handleSubmit}
          >
            {submitting ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Save className="size-4" />
            )}
            保存配置
          </Button>
        </>
      }
    >
      <div className="max-h-[calc(100dvh-12rem)] [scrollbar-gutter:stable] overflow-y-auto overscroll-contain pr-2 sm:max-h-[calc(100dvh-14rem)]">
        <div className="space-y-5">
          <div className="flex items-start gap-3 rounded-xl border border-gray-200/70 bg-white/70 p-3 dark:border-white/10 dark:bg-white/[0.035]">
            <ProviderLogoFrame provider={provider} className="size-10" />
            <div className="min-w-0">
              <div className="text-sm font-semibold text-gray-950 dark:text-gray-50">
                {provider.title}
              </div>
              <p className="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                {getProviderShortDescription(provider)}
              </p>
              <ProviderCapabilityGroupBadges
                provider={provider}
                className="mt-2"
              />
            </div>
          </div>

          <label className="block">
            <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
              自定义名称
            </span>
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={`默认：${provider.officialTitle || provider.title}`}
              className="bg-white/70"
            />
          </label>

          {isPresetProvider && provider.baseUrlOptions?.length ? (
            <ProviderEndpointSelector
              key={provider.id}
              provider={provider}
              baseUrl={baseUrl}
              setBaseUrl={setBaseUrl}
            />
          ) : usesEditableBaseUrl ? (
            <div className="block">
              <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
                Base URL
              </span>
              <Input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder={provider.baseUrl || "https://api.example.com/v1"}
                className="bg-white/70"
              />
              {discoveryPreview ? (
                <div className="mt-1.5 rounded-lg border border-gray-200/70 bg-white/60 px-2.5 py-2 text-[11px] text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
                  <span className="mr-2">探测地址</span>
                  <span className="font-mono break-all text-gray-700 dark:text-gray-300">
                    {discoveryPreview}
                  </span>
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="block">
            <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
              API Key
            </span>
            <div className="relative">
              <Input
                type={showApiKey ? "text" : "password"}
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={
                  provider.apiKeyMasked
                    ? `当前 Key：${provider.apiKeyMasked}`
                    : provider.keyLabel || "API_KEY"
                }
                className="bg-white/70 pr-10"
              />
              <button
                type="button"
                className="absolute inset-y-0 right-0 grid w-10 place-items-center text-gray-400 transition-colors hover:text-gray-700 dark:hover:text-gray-200"
                onClick={() => setShowApiKey((visible) => !visible)}
                aria-label={showApiKey ? "隐藏 API Key" : "显示 API Key"}
                title={showApiKey ? "隐藏 API Key" : "显示 API Key"}
              >
                {showApiKey ? (
                  <EyeOff className="size-4" />
                ) : (
                  <Eye className="size-4" />
                )}
              </button>
            </div>
          </div>

          <ProviderCapabilitySelector
            capabilities={capabilities}
            setCapabilities={setCapabilities}
            progress={testResult?.capabilityResults ?? probeProgress.progress}
            supportedCapabilities={isPresetProvider ? preset?.capabilities : undefined}
          />

          <div className="space-y-3 rounded-xl border border-gray-200/70 bg-white/55 p-3 dark:border-white/10 dark:bg-white/[0.035]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              {!testResult ? (
                <div className="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                  {testing ? "正在获取模型" : "尚未刷新模型"}
                </div>
              ) : null}
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 gap-2 bg-white/70"
                disabled={testing || submitting || !canTest}
                onClick={handleTest}
              >
                {testing ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : testPassed ? (
                  <CheckCircle2 className="size-3.5" />
                ) : (
                  <RefreshCcw className="size-3.5" />
                )}
                {testing ? "正在获取" : testPassed ? "重新获取" : "获取模型"}
              </Button>
            </div>
            {testResult ? (
              <ProviderTestResultPanel result={testResult} attached={false} />
            ) : null}
          </div>

          {error ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-300">
              {error}
            </div>
          ) : null}
        </div>
      </div>
    </ModalShell>
  )
}

function ProviderDeleteDialog({
  provider,
  onClose,
  onSubmit,
}: {
  provider: ProviderRow
  onClose: () => void
  onSubmit: (providerId: string) => Promise<void>
}) {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")

  const handleSubmit = async () => {
    setSubmitting(true)
    setError("")
    try {
      await onSubmit(provider.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除供应商失败")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ModalShell
      title="删除供应商"
      description="删除后会从全局配置中移除该供应商的密钥、连接状态和自定义配置。"
      onClose={onClose}
      footer={
        <>
          <Button type="button" variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            type="button"
            className="gap-2 bg-rose-600 text-white hover:bg-rose-700"
            disabled={submitting}
            onClick={handleSubmit}
          >
            {submitting ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Trash2 className="size-4" />
            )}
            确认删除
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="flex items-start gap-3 rounded-xl border border-rose-200 bg-rose-50/75 p-3 text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200">
          <ProviderLogoFrame provider={provider} className="size-10" />
          <div className="min-w-0">
            <div className="text-sm font-semibold">{provider.title}</div>
            <p className="mt-1 text-xs leading-relaxed opacity-80">
              这个操作只删除用户配置，不会删除系统内置的供应商目录。
            </p>
          </div>
        </div>
        {error ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-300">
            {error}
          </div>
        ) : null}
      </div>
    </ModalShell>
  )
}
