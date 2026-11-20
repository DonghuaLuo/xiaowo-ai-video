import { useId, useMemo, useRef, useState } from "react"
import { Check, ChevronsUpDown, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { getModelDisplayName, groupModelsByProvider, type ModelCapability } from "./model-config-model"
import type { ProviderRow } from "./provider-model"

type DefaultOption = { value: string; label: string; disabled?: boolean }

export function ModelPicker({
  label,
  value,
  models,
  providers,
  defaultOption,
  onChange,
}: {
  label: string
  value: string
  models: ModelCapability[]
  providers: ProviderRow[]
  defaultOption: DefaultOption
  onChange: (value: string) => void
}) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const searchInputRef = useRef<HTMLInputElement>(null)
  const groups = useMemo(
    () => groupModelsByProvider(models, providers),
    [models, providers, value]
  )
  const selectedGroup = groups.find((group) => group.models.some((model) => model.id === value))
  const selectedModel = selectedGroup?.models.find((model) => model.id === value)
  const selectedLabel = value === defaultOption.value
    ? defaultOption.label
    : selectedModel
      ? `${getModelDisplayName(selectedModel)} · ${selectedGroup?.providerName}`
      : value || "未配置"
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const visibleGroups = groups.map((group) => ({
    ...group,
    models: group.models.filter((model) => {
      const searchable = `${model.id} ${model.label} ${getModelDisplayName(model)} ${group.providerName}`.toLowerCase()
      return terms.every((term) => searchable.includes(term))
    }),
  })).filter((group) => group.models.length > 0)
  const showDefault = terms.every((term) => defaultOption.label.toLowerCase().includes(term))

  const selectValue = (nextValue: string) => {
    if (nextValue === defaultOption.value) {
      if (defaultOption.disabled) return
    } else if (!models.some((model) => model.id === nextValue)) {
      return
    }
    onChange(nextValue)
    setOpen(false)
  }

  return (
    <div className="min-w-0">
      <label htmlFor={id} className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">{label}</label>
      <Popover open={open} onOpenChange={(nextOpen) => { setOpen(nextOpen); setQuery("") }}>
        <PopoverTrigger asChild>
          <Button id={id} type="button" variant="outline" role="combobox" aria-expanded={open}
            aria-label={`${label}：${selectedLabel}`} title={selectedLabel}
            className="h-9 w-full min-w-0 justify-between gap-2 rounded-md border-input bg-white/70 px-3 font-normal dark:border-white/20 dark:bg-input/30">
            <span className="min-w-0 truncate">{selectedLabel}</span>
            <ChevronsUpDown aria-hidden="true" className="size-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-[var(--radix-popover-trigger-width)] max-w-[calc(100vw-2rem)] overflow-hidden p-0">
          <Command shouldFilter={false} defaultValue={value} label={label}>
            <div className="relative">
              <CommandInput ref={searchInputRef} value={query} onValueChange={setQuery}
                placeholder="搜索模型或供应商" aria-label={`搜索${label}或供应商`}
                className="pr-8" />
              {query ? (
                <button type="button" aria-label="清除搜索文字" title="清除搜索文字"
                  onPointerDown={(event) => event.preventDefault()}
                  onClick={() => { setQuery(""); searchInputRef.current?.focus() }}
                  className="absolute right-2 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground">
                  <X aria-hidden="true" className="size-3.5" />
                </button>
              ) : null}
            </div>
            <CommandList className="ai-video-scrollbar max-h-[min(360px,calc(var(--radix-popover-content-available-height)-48px))]">
              <CommandEmpty>没有匹配的模型</CommandEmpty>
              {showDefault ? (
                <CommandGroup>
                  <CommandItem value={defaultOption.value} disabled={defaultOption.disabled} onSelect={() => selectValue(defaultOption.value)}>
                    <Check aria-hidden="true" className={`size-4 shrink-0 ${value === defaultOption.value ? "opacity-100" : "opacity-0"}`} />
                    <span className="min-w-0 break-words">{defaultOption.label}</span>
                  </CommandItem>
                </CommandGroup>
              ) : null}
              {visibleGroups.map((group) => (
                <CommandGroup key={group.providerId} heading={group.providerName} className="border-t border-border">
                  {group.models.map((model) => (
                      <CommandItem key={model.id} value={model.id}
                        onSelect={() => selectValue(model.id)} title={`${getModelDisplayName(model)} · ${group.providerName}`}>
                        <Check aria-hidden="true" className={`size-4 shrink-0 ${value === model.id ? "opacity-100" : "opacity-0"}`} />
                        <span className="flex min-w-0 flex-col">
                          <span className="truncate">{getModelDisplayName(model)}</span>
                        </span>
                      </CommandItem>
                  ))}
                </CommandGroup>
              ))}
              {!terms.length && models.length === 0 ? <div className="px-3 py-3 text-xs text-muted-foreground">暂无可选模型</div> : null}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  )
}
