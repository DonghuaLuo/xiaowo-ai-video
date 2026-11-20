import {
  presetOptions,
} from "./workflow-model-capabilities"
import { useRef, useState, type MouseEvent, type ReactNode } from "react"
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Loader2,
  Save,
  Search,
  Undo2,
  WandSparkles,
  X,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"

const WORKFLOW_INLINE_BUTTON_CLASS =
  "h-7 rounded-md px-2.5 text-[11px] shadow-none"
const WORKFLOW_SAVE_BUTTON_CLASS = WORKFLOW_INLINE_BUTTON_CLASS

type WorkflowCompactParameterOption = {
  value: string
  label: string
  description?: string
  badges?: string[]
  disabledReason?: string
}

type WorkflowCompactParameterGroup = {
  label: string
  options: WorkflowCompactParameterOption[]
}
function InlineEditActionBar({
  visible,
  onCancel,
  onSave,
  saving = false,
  className,
}: {
  visible: boolean
  onCancel: (event: MouseEvent<HTMLButtonElement>) => void
  onSave: (event: MouseEvent<HTMLButtonElement>) => Promise<void> | void
  saving?: boolean
  className?: string
}) {
  const [localSaving, setLocalSaving] = useState(false)
  const isSaving = saving || localSaving
  const handleSave = async (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    if (isSaving) return
    setLocalSaving(true)
    try {
      await onSave(event)
    } catch {
      // The save callback owns user-facing error toasts.
    } finally {
      setLocalSaving(false)
    }
  }
  if (!visible) return null
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-2 rounded-md border border-gray-200 bg-white/75 px-2.5 py-1.5 text-[11px] text-gray-700 shadow-none backdrop-blur-xl dark:border-white/[0.08] dark:bg-white/[0.06] dark:text-white/75",
        className
      )}
    >
      <div className="flex items-center gap-1.5 font-medium">
        <AlertTriangle className="size-3 shrink-0 text-amber-300" />
        <span>是否保存修改？</span>
      </div>
      <div className="flex items-center gap-1.5">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className={WORKFLOW_INLINE_BUTTON_CLASS}
          onClick={onCancel}
          disabled={isSaving}
        >
          取消
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className={WORKFLOW_SAVE_BUTTON_CLASS}
          onClick={handleSave}
          disabled={isSaving}
        >
          {isSaving ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Save className="size-3.5" />
          )}
          保存
        </Button>
      </div>
    </div>
  )
}

function InlineSaveControls({
  dirty,
  onRestore,
  onSave,
  saving = false,
  maximized = false,
  alignRight = true,
  className,
  beforeSave,
  restoreLabel,
}: {
  dirty: boolean
  onRestore: (event: MouseEvent<HTMLButtonElement>) => void
  onSave: (event: MouseEvent<HTMLButtonElement>) => Promise<void> | void
  saving?: boolean
  maximized?: boolean
  alignRight?: boolean
  className?: string
  beforeSave?: ReactNode
  restoreLabel?: string
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-end gap-2",
        alignRight && "ml-auto",
        className
      )}
    >
      {dirty ? (
        <button
          type="button"
          className="inline-flex h-8 items-center gap-1.5 px-2 text-xs font-medium text-gray-600 transition-colors hover:text-gray-950 focus-visible:ring-2 focus-visible:ring-gray-900/15 focus-visible:outline-none disabled:opacity-50 dark:text-white/65 dark:hover:text-white dark:focus-visible:ring-white/20"
          onClick={onRestore}
          disabled={saving}
        >
          {!maximized ? <Undo2 className="size-3.5" /> : null}
          {maximized ? (restoreLabel ?? "恢复") : "撤销"}
        </button>
      ) : null}
      {beforeSave}
      <Button
        type="button"
        variant={maximized ? "default" : "outline"}
        size="sm"
        className={
          maximized
            ? "h-8 gap-1.5 text-xs"
            : "h-7 gap-1 rounded-sm border-gray-200/80 bg-gray-100/70 px-2 text-[11px] text-gray-600 shadow-none hover:border-gray-300 hover:bg-gray-200/70 hover:text-gray-800 dark:border-white/[0.07] dark:bg-white/[0.06] dark:text-white/60 dark:hover:border-white/[0.11] dark:hover:bg-white/[0.09] dark:hover:text-white/80"
        }
        onClick={onSave}
        disabled={!dirty || saving}
      >
        {saving ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : (
          <Save className="size-3.5" />
        )}
        保存
      </Button>
    </div>
  )
}


function WorkflowCompactParameterMenu({
  label,
  value,
  options,
  optionGroups,
  onChange,
  formatLabel,
  formatDescription,
  disabledReason,
  sourceLabel,
  contentClassName,
  disabled = false,
  includeCurrentValue = true,
  emptyLabel = "未配置",
  allowUnset = false,
  unsetLabel,
}: {
  label: string
  value: string
  options: string[]
  optionGroups?: WorkflowCompactParameterGroup[]
  onChange: (value: string) => void
  formatLabel?: (value: string) => string
  formatDescription?: (value: string) => string
  disabledReason?: (value: string) => string
  sourceLabel?: string
  contentClassName?: string
  disabled?: boolean
  includeCurrentValue?: boolean
  emptyLabel?: string
  allowUnset?: boolean
  unsetLabel?: string
}) {
  const [searchQuery, setSearchQuery] = useState("")
  const searchInputRef = useRef<HTMLInputElement>(null)
  const entries: WorkflowCompactParameterOption[] = []
  const entryByValue = new Map<string, WorkflowCompactParameterOption>()
  const seen = new Set<string>()
  const addEntry = (
    nextValue: string,
    nextLabel?: string,
    badges?: string[],
    description?: string
  ) => {
    const normalized = nextValue.trim()
    if (!normalized) return
    if (seen.has(normalized)) return
    seen.add(normalized)
    const entry: WorkflowCompactParameterOption = {
      value: normalized,
      label: nextLabel ?? formatLabel?.(normalized) ?? normalized,
      description: description ?? formatDescription?.(normalized),
      badges,
    }
    entries.push(entry)
    entryByValue.set(normalized, entry)
  }

  for (const option of includeCurrentValue
    ? presetOptions(value, options)
    : options) {
    addEntry(option)
  }

  const normalizedGroups = (optionGroups ?? [])
    .map((group) => {
      const groupEntries = group.options
        .map((option): WorkflowCompactParameterOption | null => {
          const normalized = option.value.trim()
          if (!normalized) return null
          const fallback = entryByValue.get(normalized)
          return {
            ...(fallback ?? {
              value: normalized,
              label: formatLabel?.(normalized) ?? normalized,
            }),
            label: option.label || fallback?.label || normalized,
            description:
              option.description ||
              fallback?.description ||
              formatDescription?.(normalized),
            badges: option.badges,
            disabledReason: option.disabledReason,
          }
        })
        .filter((entry): entry is WorkflowCompactParameterOption =>
          Boolean(entry)
        )
      return { label: group.label, options: groupEntries }
    })
    .filter((group) => group.options.length > 0)
  const groupedValues = new Set(
    normalizedGroups.flatMap((group) =>
      group.options.map((entry) => entry.value)
    )
  )
  const fallbackEntries = entries.filter(
    (entry) => !groupedValues.has(entry.value)
  )
  const displayGroups = normalizedGroups.length
    ? [
        ...normalizedGroups,
        ...(fallbackEntries.length
          ? [{ label: "其他", options: fallbackEntries }]
          : []),
      ]
    : []

  const currentLabel =
    entries.find((entry) => entry.value === value)?.label ??
    (value ? (formatLabel?.(value) ?? value) : emptyLabel)
  const title = `${label}: ${currentLabel}${sourceLabel ? `（${sourceLabel}）` : ""}`
  const groupsToRender = displayGroups.length
    ? displayGroups
    : [{ label: "", options: entries }]
  const isModelMenu = label === "模型"
  const resetLabel = unsetLabel ?? emptyLabel
  const resetReason = disabledReason?.("") ?? ""
  const searchTerms = isModelMenu
    ? searchQuery.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
    : []
  const visibleGroups = groupsToRender
    .map((group) => ({
      ...group,
      options: group.options.filter((entry) => {
        const searchable = `${group.label} ${entry.label} ${entry.value}`.toLocaleLowerCase()
        return searchTerms.every((term) => searchable.includes(term))
      }),
    }))
    .filter((group) => group.options.length > 0)
  const showUnset = allowUnset && searchTerms.every((term) =>
    resetLabel.toLocaleLowerCase().includes(term)
  )

  return (
    <DropdownMenu onOpenChange={(open) => {
      if (open && isModelMenu) {
        requestAnimationFrame(() => searchInputRef.current?.focus())
      } else if (!open) {
        setSearchQuery("")
      }
    }}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex h-8 max-w-[10.5rem] items-center gap-1.5 rounded-sm bg-transparent px-1.5 text-[11px] font-medium text-gray-700 transition-colors hover:bg-gray-100 hover:text-gray-950 focus-visible:ring-2 focus-visible:ring-gray-900/15 focus-visible:outline-none dark:text-white/75 dark:hover:bg-white/[0.07] dark:hover:text-white dark:focus-visible:ring-white/20",
            isModelMenu && "max-w-[14rem]",
            disabled && "cursor-not-allowed opacity-55 hover:bg-transparent"
          )}
          disabled={disabled}
          title={title}
          aria-label={title}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => event.stopPropagation()}
        >
          {isModelMenu ? (
            <WandSparkles className="size-3.5 shrink-0 text-gray-700 dark:text-white/[0.85]" />
          ) : (
            <span className="shrink-0 text-gray-500 dark:text-white/40">
              {label}
            </span>
          )}
          <span className="min-w-0 truncate">{currentLabel}</span>
          {sourceLabel ? (
            <span className="shrink-0 rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-500 dark:bg-white/[0.08] dark:text-white/[0.35]">
              {sourceLabel}
            </span>
          ) : null}
          <ChevronDown className="size-3 shrink-0 text-gray-500 dark:text-white/40" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className={cn(
          "z-[360] max-h-72 w-max max-w-[calc(100vw-2rem)] min-w-[var(--radix-dropdown-menu-trigger-width)] overflow-y-auto border-gray-200 bg-white text-xs text-gray-800 shadow-xl shadow-gray-950/20 dark:border-white/10 dark:bg-[#232323] dark:text-white/[0.85] dark:shadow-black/30",
          isModelMenu && "pt-0",
          contentClassName
        )}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => event.stopPropagation()}
      >
        {isModelMenu ? (
          <div className="sticky top-0 z-10 mb-1 flex items-center gap-2 border-b border-gray-200 bg-white px-2 py-1 dark:border-white/10 dark:bg-[#232323]">
            <Search className="size-3.5 shrink-0 text-gray-400 dark:text-white/40" />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              onKeyDown={(event) => {
                if (
                  event.nativeEvent.isComposing ||
                  event.key.length === 1 ||
                  ["Backspace", "Delete", "ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
                ) event.stopPropagation()
              }}
              placeholder="搜索供应商或模型"
              aria-label="搜索供应商或模型"
              className="h-7 min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-gray-400 dark:placeholder:text-white/40"
            />
            {searchQuery ? (
              <button type="button" aria-label="清除搜索文字" title="清除搜索文字"
                onPointerDown={(event) => { event.preventDefault(); event.stopPropagation() }}
                onClick={(event) => { event.stopPropagation(); setSearchQuery(""); searchInputRef.current?.focus() }}
                className="flex size-6 shrink-0 items-center justify-center rounded text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:text-white/40 dark:hover:bg-white/10 dark:hover:text-white">
                <X aria-hidden="true" className="size-3.5" />
              </button>
            ) : null}
          </div>
        ) : null}
        {showUnset ? (
          <>
            <DropdownMenuItem
              disabled={disabled || Boolean(resetReason)}
              title={resetReason || undefined}
              onClick={(event) => {
                event.stopPropagation()
                if (!disabled && !resetReason) onChange("")
              }}
              className="min-h-9 gap-2 py-1.5 text-[11px] whitespace-nowrap text-gray-700 focus:bg-gray-100 focus:text-gray-950 dark:text-white/[0.85] dark:focus:bg-white/[0.08] dark:focus:text-white"
            >
              <span className="flex size-3.5 shrink-0 items-center justify-center text-indigo-500 dark:text-indigo-300">
                {!value && !resetReason ? <CheckCircle2 className="size-3" /> : null}
              </span>
              <span className="max-w-80 truncate">{resetLabel}{resetReason ? ` (${resetReason})` : ""}</span>
            </DropdownMenuItem>
            {visibleGroups.length ? <DropdownMenuSeparator /> : null}
          </>
        ) : null}
        {visibleGroups.map((group, groupIndex) => (
          <div key={`${label}-${group.label || "flat"}-${groupIndex}`}>
            {displayGroups.length ? (
              <>
                {groupIndex > 0 ? <DropdownMenuSeparator /> : null}
                <DropdownMenuLabel className="px-2 py-1 text-[10px] font-semibold text-gray-400 dark:text-white/[0.35]">
                  {group.label}
                </DropdownMenuLabel>
              </>
            ) : null}
            {group.options.map((entry) => {
              const reason = entry.disabledReason || disabledReason?.(entry.value) || ""
              const selected = entry.value === value && !reason
              return (
                <DropdownMenuItem
                  key={`${label}-${entry.value || "default"}`}
                  disabled={disabled || Boolean(reason)}
                  title={reason || entry.description}
                  onClick={(event) => {
                    event.stopPropagation()
                    if (!disabled && !reason) onChange(entry.value)
                  }}
                  className="min-h-9 items-start gap-2 py-1.5 text-[11px] whitespace-nowrap text-gray-700 focus:bg-gray-100 focus:text-gray-950 disabled:text-gray-400 dark:text-white/[0.85] dark:focus:bg-white/[0.08] dark:focus:text-white dark:disabled:text-white/[0.35]"
                >
                  <span className="mt-0.5 flex size-3.5 shrink-0 items-center justify-center text-indigo-500 dark:text-indigo-300">
                    {selected ? <CheckCircle2 className="size-3" /> : null}
                  </span>
                  <span className="flex min-w-0 flex-col gap-1">
                    <span className="max-w-80 truncate">{entry.label}</span>
                    {reason || entry.description ? (
                      <span className="max-w-80 truncate text-[10px] font-normal text-gray-500 dark:text-white/[0.45]">
                        {reason || entry.description}
                      </span>
                    ) : null}
                    {entry.badges?.length ? (
                      <span className="flex flex-wrap gap-1">
                        {entry.badges.map((badge) => (
                          <span
                            key={`${entry.value}-${badge}`}
                            className="rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-500 dark:bg-white/[0.06] dark:text-gray-400"
                          >
                            {badge}
                          </span>
                        ))}
                      </span>
                    ) : null}
                  </span>
                </DropdownMenuItem>
              )
            })}
          </div>
        ))}
        {isModelMenu && !visibleGroups.length ? (
          <div className="px-2 py-2 text-[11px] text-gray-500 dark:text-white/45">
            {searchTerms.length ? "没有匹配的模型" : "暂无已适配模型"}
          </div>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export { InlineEditActionBar, InlineSaveControls, WorkflowCompactParameterMenu }
