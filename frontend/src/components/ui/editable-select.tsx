import * as React from "react"
import { ChevronDownIcon, CheckIcon } from "lucide-react"
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover"
import { cn } from "@/lib/utils"

type EditableSelectOption =
  | string
  | {
      value: string
      label?: string
      description?: string
    }

interface EditableSelectProps {
  value: string
  onValueChange: (value: string) => void
  onOptionSelect?: (value: string) => void
  selectedOptionValue?: string
  options: EditableSelectOption[]
  disabled?: boolean
  className?: string
  contentClassName?: string
  inputClassName?: string
  placeholder?: string
  emptyLabel?: string
  /** 单位后缀，如 "k"。输入框只显示数字，对外输出时自动拼接后缀 */
  suffix?: string
}

/** 去除字符串末尾的后缀 */
function stripSuffix(val: string, suffix: string): string {
  if (suffix && val.endsWith(suffix)) {
    return val.slice(0, -suffix.length)
  }
  return val
}

/** 确保字符串末尾有后缀（值非空时） */
function ensureSuffix(val: string, suffix: string): string {
  if (!val) return val
  if (suffix && !val.endsWith(suffix)) {
    return val + suffix
  }
  return val
}

function EditableSelect({
  value,
  onValueChange,
  onOptionSelect,
  selectedOptionValue,
  options,
  disabled = false,
  className,
  contentClassName,
  inputClassName,
  placeholder,
  emptyLabel = "暂无可选项",
  suffix,
}: EditableSelectProps) {
  const [open, setOpen] = React.useState(false)
  const anchorRef = React.useRef<HTMLDivElement | null>(null)

  // 输入框内部只显示不带后缀的数字部分
  const displayValue = suffix ? stripSuffix(value, suffix) : value
  const [inputValue, setInputValue] = React.useState(displayValue)

  React.useEffect(() => {
    if (disabled) setOpen(false)
  }, [disabled])

  React.useEffect(() => {
    setInputValue(suffix ? stripSuffix(value, suffix) : value)
  }, [value, suffix])

  // 选项的显示值（去掉后缀）
  const displayOptions = React.useMemo(() => {
    return options
      .map((option) => {
        const raw = typeof option === "string" ? option : option.value
        const label =
          typeof option === "string" ? option : option.label || option.value
        const display = suffix ? stripSuffix(label, suffix) : label
        return {
          raw,
          display,
          description:
            typeof option === "string" ? "" : option.description || "",
        }
      })
      .filter((option) => option.raw.trim())
  }, [options, suffix])

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value
    // 只允许输入数字
    if (suffix && raw !== "" && !/^\d+$/.test(raw)) return
    setInputValue(raw)
    // 对外输出时拼接后缀
    onValueChange(suffix ? ensureSuffix(raw, suffix) : raw)
  }

  const handleSelect = (rawOption: string) => {
    if (onOptionSelect) {
      setInputValue(displayOptions.find((option) => option.raw === rawOption)?.display ?? rawOption)
      onOptionSelect(rawOption)
      setOpen(false)
      return
    }
    const display = suffix ? stripSuffix(rawOption, suffix) : rawOption
    setInputValue(display)
    onValueChange(rawOption)
    setOpen(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      setOpen(false)
    } else if (e.key === "Escape") {
      setOpen(false)
    } else if (e.key === "ArrowDown") {
      setOpen(true)
    }
  }

  const isAnchorEventTarget = (event: Event) => {
    const originalEvent = (
      event as CustomEvent<{ originalEvent?: Event }>
    ).detail?.originalEvent
    const target = originalEvent?.target ?? event.target
    return target instanceof Node && Boolean(anchorRef.current?.contains(target))
  }

  return (
    <Popover
      open={open}
      onOpenChange={(nextOpen) => !disabled && setOpen(nextOpen)}
    >
      <PopoverAnchor asChild>
        <div
          ref={anchorRef}
          className={cn(
            "border-input dark:bg-input/30 flex h-9 w-full items-center rounded-md border bg-transparent shadow-xs",
            "focus-within:border-indigo-400 dark:focus-within:border-indigo-500",
            disabled && "cursor-not-allowed opacity-50",
            className
          )}
          onPointerDown={(event) => event.stopPropagation()}
        >
          <div className="flex flex-1 items-center overflow-hidden px-3 py-1">
            <input
              type="text"
              value={inputValue}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              onFocus={() => !disabled && setOpen(true)}
              onClick={() => !disabled && setOpen(true)}
              disabled={disabled}
              placeholder={placeholder}
              style={
                suffix && inputValue
                  ? { width: `${Math.max(inputValue.length, 1)}ch` }
                  : undefined
              }
              className={cn(
                "h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed",
                inputClassName
              )}
            />
            {suffix && inputValue && (
              <span className="text-sm text-muted-foreground">{suffix}</span>
            )}
          </div>
          <button
            type="button"
            disabled={disabled}
            aria-label="展开选项"
            className="flex h-full w-8 shrink-0 items-center justify-center text-muted-foreground disabled:cursor-not-allowed"
            onPointerDown={(event) => {
              event.preventDefault()
              event.stopPropagation()
              if (!disabled) setOpen((current) => !current)
            }}
            onClick={(event) => event.stopPropagation()}
          >
            <ChevronDownIcon className="size-4 opacity-50" />
          </button>
        </div>
      </PopoverAnchor>
      <PopoverContent
        className={cn(
          "w-[var(--radix-popover-trigger-width)] p-1",
          contentClassName
        )}
        align="start"
        sideOffset={4}
        onOpenAutoFocus={(e) => e.preventDefault()}
        onCloseAutoFocus={(e) => e.preventDefault()}
        onInteractOutside={(event) => {
          if (isAnchorEventTarget(event)) event.preventDefault()
        }}
        onPointerDown={(event) => event.stopPropagation()}
      >
        <div className="max-h-[200px] overflow-y-auto">
          {displayOptions.length ? (
            displayOptions.map(({ raw, display, description }) => (
              <div
                key={raw}
                className={cn(
                  "relative flex cursor-pointer items-center rounded-sm px-2 py-1.5 text-sm select-none hover:bg-accent hover:text-accent-foreground",
                  (selectedOptionValue ?? value) === raw && "bg-accent/50"
                )}
                onClick={() => handleSelect(raw)}
              >
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate">
                    {display}
                    {suffix ? suffix : ""}
                  </span>
                  {description ? (
                    <span className="truncate text-[10px] text-muted-foreground">
                      {description}
                    </span>
                  ) : null}
                </span>
                {(selectedOptionValue ?? value) === raw && (
                  <CheckIcon className="ml-2 size-4 shrink-0" />
                )}
              </div>
            ))
          ) : (
            <div className="px-2 py-2 text-xs text-muted-foreground">
              {emptyLabel}
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}

export { EditableSelect }
export type { EditableSelectOption }
