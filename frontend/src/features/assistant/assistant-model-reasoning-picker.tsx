import { useMemo, useRef, useState } from "react"
import { Check, ChevronDown, RotateCcw, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { cn } from "@/lib/utils"
import {
  getModelDisplayName,
  groupModelsByProvider,
} from "@/features/settings/model-config-model"
import type { AssistantModelSelectionController, AssistantReasoningEffort } from "./use-assistant-model-selection"

const reasoningOptions: { value: AssistantReasoningEffort; label: string }[] = [
  { value: "low", label: "低" },
  { value: "medium", label: "中" },
  { value: "high", label: "高" },
  { value: "xhigh", label: "极高" },
  { value: "max", label: "极高" },
]

export function AssistantModelReasoningPicker({
  selection,
  disabled,
}: {
  selection: AssistantModelSelectionController
  disabled: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const searchInputRef = useRef<HTMLInputElement>(null)
  const busy = disabled || selection.loading || selection.saving
  const availableReasoningOptions = reasoningOptions.filter((option) =>
    selection.availableReasoningEfforts.includes(option.value)
  )
  const effortLabel = !selection.effectiveModelId
    ? "未配置"
    : !selection.reasoningSupported
      ? "不可调"
      : availableReasoningOptions.find((option) => option.value === selection.effectiveReasoningEffort)?.label || "不可调"
  const modelLabel = selection.effectiveModelName || "未配置模型"
  const groups = useMemo(
    () => groupModelsByProvider(
      selection.models,
      selection.providers,
    ),
    [selection.models, selection.providers, selection.selectedModelId],
  )
  const search = query.trim().toLocaleLowerCase()
  const showGlobal = !search || `自动跟随全局设置 ${selection.globalModelName}`.toLocaleLowerCase().includes(search)

  return (
    <Popover open={open} onOpenChange={(next) => { setOpen(next); if (!next) setQuery("") }}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={busy}
          aria-label={`${modelLabel}，推理能力${effortLabel}，选择模型和推理能力`}
          title={`${modelLabel} · 推理能力${effortLabel}`}
          className="h-7 max-w-full min-w-0 gap-1 rounded-md px-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-white/10"
        >
          <span className="min-w-0 truncate">{modelLabel}</span>
          <span className="shrink-0 text-indigo-600 dark:text-indigo-300">{effortLabel}</span>
          <ChevronDown aria-hidden="true" className="size-3 shrink-0 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" sideOffset={10} className="w-72 max-w-[calc(100vw-1rem)] overflow-hidden rounded-xl p-0 shadow-xl">
        <div className="space-y-2 border-b px-3 py-3">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium">推理能力</span>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">{effortLabel}</span>
              <button
                type="button"
                aria-label="恢复模型默认推理能力"
                title="恢复模型默认推理能力"
                disabled={busy || !selection.selectedReasoningEffort}
                onClick={() => void selection.selectReasoningEffort("")}
                className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
              >
                <RotateCcw aria-hidden="true" className="size-3.5" />
              </button>
            </div>
          </div>
          {selection.reasoningSupported && availableReasoningOptions.length ? <div role="group" aria-label="推理能力" className={cn("grid gap-1 rounded-lg bg-muted/70 p-1", availableReasoningOptions.length === 2 ? "grid-cols-2" : availableReasoningOptions.length === 3 ? "grid-cols-3" : "grid-cols-4")}>
            {availableReasoningOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={selection.effectiveReasoningEffort === option.value}
                disabled={busy || !selection.reasoningSupported}
                onClick={() => void selection.selectReasoningEffort(option.value)}
                className={cn(
                  "h-8 rounded-md text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                  selection.effectiveReasoningEffort === option.value
                    ? "bg-blue-500 font-semibold text-white shadow-sm"
                    : "text-muted-foreground hover:bg-background hover:text-foreground",
                )}
              >
                {option.label}
              </button>
            ))}
          </div> : null}
          {!selection.reasoningSupported && selection.effectiveModelId ? (
            <p className="text-[11px] text-muted-foreground">当前模型不能手动调节推理档位</p>
          ) : null}
        </div>
        <div className="px-3 pt-2 text-xs font-medium">选择模型</div>
        <div className="relative px-2 py-2">
          <input
            ref={searchInputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索模型或供应商"
            aria-label="搜索模型或供应商"
            className="h-8 w-full rounded-md border bg-transparent py-1 pl-2 pr-8 text-xs outline-none focus:border-indigo-400"
          />
          {query ? (
            <button type="button" aria-label="清除搜索文字" title="清除搜索文字"
              onPointerDown={(event) => event.preventDefault()}
              onClick={() => { setQuery(""); searchInputRef.current?.focus() }}
              className="absolute right-3 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground">
              <X aria-hidden="true" className="size-3.5" />
            </button>
          ) : null}
        </div>
        <div className="ai-video-scrollbar max-h-64 overflow-y-auto px-1.5 pb-2">
          {showGlobal ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void selection.selectModel("")}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-muted disabled:opacity-50"
            >
              <Check aria-hidden="true" className={cn("size-3.5 shrink-0", selection.selectedModelId ? "opacity-0" : "opacity-100")} />
              <span className="min-w-0">
                <span className="block">自动跟随全局设置</span>
                <span className="block truncate text-[11px] text-muted-foreground">{selection.globalModelName || "未配置"}</span>
              </span>
            </button>
          ) : null}
          {groups.map((group) => {
            const models = group.models.filter((model) =>
              `${model.id} ${getModelDisplayName(model)} ${group.providerName}`.toLocaleLowerCase().includes(search)
            )
            if (!models.length) return null
            return (
              <div key={group.providerId} className="mt-1 border-t pt-1">
                <div className="px-2 py-1 text-[11px] text-muted-foreground">{group.providerName}</div>
                {models.map((model) => {
                  return (
                    <button
                      key={model.id}
                      type="button"
                      disabled={busy}
                      onClick={() => void selection.selectModel(model.id)}
                      title={getModelDisplayName(model)}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50",
                        selection.selectedModelId === model.id && "bg-muted",
                      )}
                    >
                      <Check aria-hidden="true" className={cn("size-3.5 shrink-0", selection.selectedModelId === model.id ? "opacity-100" : "opacity-0")} />
                      <span className="min-w-0 truncate">{getModelDisplayName(model)}</span>
                    </button>
                  )
                })}
              </div>
            )
          })}
        </div>
      </PopoverContent>
    </Popover>
  )
}
