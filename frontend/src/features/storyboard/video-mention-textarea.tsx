import { useLayoutEffect, useMemo, useRef, useState, type ComponentProps, type ReactNode } from "react"
import { cn } from "@/lib/utils"
import { PROMPT_MENTION_COLORS, PROMPT_MENTION_PATTERN, type PromptBindings, type PromptMentionOption } from "./video-prompt-mentions"

type Props = ComponentProps<"textarea"> & {
  value: string
  mentionOptions: PromptMentionOption[]
  promptBindings: PromptBindings
  onHistoryAction?: (direction: "undo" | "redo") => void
}

export function VideoMentionTextarea({ value, mentionOptions, promptBindings, onHistoryAction, className, onScroll, onKeyDown, onChange, ...props }: Props) {
  const overlay = useRef<HTMLDivElement>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const [hover, setHover] = useState<{ label: string; left: number; top: number } | null>(null)
  const options = useMemo(() => new Map(mentionOptions.map((option) => [option.key, option])), [mentionOptions])
  const { content, invalid } = useMemo(() => {
    const content: ReactNode[] = []
    const invalid = new Set<string>()
    let offset = 0
    for (const match of value.matchAll(PROMPT_MENTION_PATTERN)) {
      const label = match[1]
      const option = options.get(promptBindings[label])
      if (!option) invalid.add(label)
      content.push(value.slice(offset, match.index))
      content.push(<span key={match.index} data-prompt-mention={label} className={cn(
        "rounded-sm",
        option ? PROMPT_MENTION_COLORS[option.kind] : "text-red-700 bg-red-500/15 underline decoration-wavy dark:text-red-300",
      )}>{match[0]}</span>)
      offset = match.index + match[0].length
    }
    content.push(value.slice(offset), "\u200b")
    return { content, invalid: [...invalid] }
  }, [value, promptBindings, options])
  const hoveredOption = hover ? options.get(promptBindings[hover.label]) : undefined
  useLayoutEffect(() => {
    const input = textarea.current
    if (!input || !onHistoryAction) return
    const handleHistory = (event: InputEvent) => {
      if (props.readOnly || !event.cancelable) return
      if (event.inputType !== "historyUndo" && event.inputType !== "historyRedo") return
      event.preventDefault()
      onHistoryAction(event.inputType === "historyUndo" ? "undo" : "redo")
    }
    input.addEventListener("beforeinput", handleHistory)
    return () => input.removeEventListener("beforeinput", handleHistory)
  }, [onHistoryAction, props.readOnly])
  useLayoutEffect(() => {
    const input = textarea.current
    const mirror = overlay.current
    if (!input || !mirror) return
    const sync = () => {
      mirror.style.width = `${input.clientWidth}px`
      mirror.style.height = `${input.clientHeight}px`
      mirror.scrollTop = input.scrollTop
      mirror.scrollLeft = input.scrollLeft
    }
    sync()
    const observer = new ResizeObserver(sync)
    observer.observe(input)
    return () => observer.disconnect()
  }, [value])

  return <div className="relative min-h-0 w-full flex-1" onMouseLeave={() => setHover(null)} onMouseMove={(event) => {
    const spans = overlay.current?.querySelectorAll<HTMLElement>("[data-prompt-mention]")
    const span = Array.from(spans ?? []).find((item) => Array.from(item.getClientRects()).some((rect) =>
      event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom))
    if (!span) { setHover(null); return }
    const bounds = event.currentTarget.getBoundingClientRect()
    setHover({ label: span.dataset.promptMention!, left: Math.max(0, Math.min(event.clientX - bounds.left, bounds.width - 220)), top: event.clientY - bounds.top + 20 })
  }}>
    <div ref={overlay} aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words text-[13px] leading-relaxed text-gray-900 dark:text-white/90">{content}</div>
    <textarea {...props} ref={textarea} value={value} aria-invalid={invalid.length > 0 || undefined}
      className={cn("field-sizing-content", className, "relative selection:bg-sky-500/25 !text-transparent dark:!text-transparent !bg-transparent caret-gray-900 dark:caret-white")}
      onChange={(event) => {
        const inputType = (event.nativeEvent as InputEvent).inputType
        if (onHistoryAction && (inputType === "historyUndo" || inputType === "historyRedo")) {
          if (!props.readOnly) onHistoryAction(inputType === "historyUndo" ? "undo" : "redo")
          return
        }
        onChange?.(event)
      }}
      onScroll={(event) => {
        if (overlay.current) {
          overlay.current.scrollTop = event.currentTarget.scrollTop
          overlay.current.scrollLeft = event.currentTarget.scrollLeft
        }
        setHover(null)
        onScroll?.(event)
      }}
      onKeyDown={(event) => {
        const key = event.key.toLowerCase()
        if (onHistoryAction && !event.nativeEvent.isComposing && !event.altKey && (event.ctrlKey || event.metaKey)
          && (key === "z" || key === "y")) {
          event.preventDefault()
          if (!props.readOnly) onHistoryAction(key === "y" || event.shiftKey ? "redo" : "undo")
          return
        }
        onKeyDown?.(event)
        if (event.defaultPrevented || event.key !== "Backspace") return
        const input = event.currentTarget
        if (input.selectionStart !== input.selectionEnd) return
        for (const match of value.matchAll(PROMPT_MENTION_PATTERN)) {
          if (match.index + match[0].length === input.selectionStart) {
            event.preventDefault()
            input.setSelectionRange(match.index, match.index + match[0].length)
            break
          }
        }
      }} />
    {hover && <div role="tooltip" className="pointer-events-none absolute z-[330] max-w-[220px] rounded border border-gray-200 bg-white p-2 text-xs text-gray-900 shadow-md dark:border-white/15 dark:bg-[#252525] dark:text-white" style={{ left: hover.left, top: hover.top }}>
      <span className="block break-words">{hoveredOption?.title || `${hover.label}：引用已失效或未绑定`}</span>
      {hoveredOption?.previewSrc && <img src={hoveredOption.previewSrc} alt="" className="mt-1 max-h-28 w-full object-contain" />}
    </div>}
  </div>
}
