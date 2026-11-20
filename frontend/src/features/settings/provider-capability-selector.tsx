import { useId, type Dispatch, type SetStateAction } from "react"
import { AlertTriangle, CheckCircle2, Clock3, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { Checkbox } from "@/components/ui/checkbox"
import {
  providerCapabilityGroupLabels,
  providerCapabilityGroupOptions,
  providerCapabilityGroupStyles,
} from "./provider-model"
import type { ProviderProbeProgress } from "./use-provider-probe-progress"

const capabilityDescriptions: Record<string, string> = {
  image: "分镜图、资产图",
  video: "参考图视频、首尾帧视频",
  agent: "Anthropic 兼容",
  text: "文本生成",
}

const probeStatusLabels = {
  pending: "等待获取",
  testing: "正在获取模型",
  ok: "已获取模型",
  failed: "获取失败",
  unsupported: "不支持",
  unknown: "待验证",
}

export function ProviderCapabilitySelector({
  capabilities,
  setCapabilities,
  progress,
  supportedCapabilities,
}: {
  capabilities: string[]
  setCapabilities: Dispatch<SetStateAction<string[]>>
  progress: ProviderProbeProgress
  supportedCapabilities?: string[]
}) {
  const id = useId()
  return (
    <div>
      <div className="mb-2 text-xs text-gray-500 dark:text-gray-400">
        模型类型
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {providerCapabilityGroupOptions.map((option) => {
          const status = progress[option.id]?.status
          const presetSupports = supportedCapabilities
            ? option.capabilities.some((capability) => supportedCapabilities.includes(capability))
            : true
          const active = presetSupports && option.capabilities.some((capability) => capabilities.includes(capability))
          const unsupported = !presetSupports
          return (
            <label
              key={option.id}
              htmlFor={`${id}-${option.id}`}
              title={unsupported ? "此预设不提供该类模型" : undefined}
              className={cn(
                "flex min-h-14 min-w-0 cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 text-left text-xs transition-colors",
                active
                  ? providerCapabilityGroupStyles[option.id]
                  : "border-gray-200/70 bg-white/70 text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400",
                unsupported && "cursor-not-allowed opacity-45"
              )}
            >
              <Checkbox id={`${id}-${option.id}`} checked={active} disabled={unsupported}
                aria-label={providerCapabilityGroupLabels[option.id]}
                className="shrink-0 border-gray-500 bg-transparent text-white dark:border-white/45 dark:bg-transparent dark:data-[state=checked]:border-indigo-300 dark:data-[state=checked]:bg-indigo-500 dark:data-[state=checked]:text-white"
                onCheckedChange={(checked) => setCapabilities((items) => checked === true
                  ? Array.from(new Set([...items, ...option.capabilities]))
                  : items.filter((item) => !option.capabilities.includes(item)))} />
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{providerCapabilityGroupLabels[option.id]}</span>
                <span className="mt-1 block text-[11px] leading-relaxed opacity-75">
                  {capabilityDescriptions[option.id]}
                </span>
              </span>
              <span
                role="status"
                aria-label={status ? probeStatusLabels[status] : undefined}
                title={status ? probeStatusLabels[status] : undefined}
                className="flex size-5 shrink-0 items-center justify-center"
              >
                {status === "pending" || status === "unknown" ? <Clock3 aria-hidden="true" className="size-4 opacity-60" /> : null}
                {status === "testing" ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : null}
                {status === "ok" ? <CheckCircle2 aria-hidden="true" className="size-4 text-emerald-600 dark:text-emerald-400" /> : null}
                {status === "failed" || status === "unsupported" ? <AlertTriangle aria-hidden="true" className="size-4 text-amber-600 dark:text-amber-400" /> : null}
              </span>
            </label>
          )
        })}
      </div>
    </div>
  )
}
