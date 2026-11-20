import { assistantTextCanCollapse } from "./assistant-message-model"
import React, { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { CheckCircle2, Copy } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  AssistantActionFooter,
  copyAssistantTextToClipboard,
} from "./assistant-session-normalization"

export const ASSISTANT_TEXT_COLLAPSED_RENDER_LIMIT = 1400

export function assistantDisplayText(text: string, expanded: boolean) {
  if (expanded || text.length <= ASSISTANT_TEXT_COLLAPSED_RENDER_LIMIT) {
    return text
  }
  return `${text.slice(0, ASSISTANT_TEXT_COLLAPSED_RENDER_LIMIT).trimEnd()}...`
}

export function renderAssistantInlineText(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return (
        <strong
          key={`${index}-${part}`}
          className="font-semibold text-gray-900 dark:text-white"
        >
          {part.slice(2, -2)}
        </strong>
      )
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code
          key={`${index}-${part}`}
          className="rounded border border-gray-200/70 bg-gray-100 px-1 py-0.5 font-mono text-[0.92em] text-gray-800 dark:border-white/10 dark:bg-[#32333b] dark:text-gray-50"
        >
          {part.slice(1, -1)}
        </code>
      )
    }
    return <React.Fragment key={`${index}-${part}`}>{part}</React.Fragment>
  })
}

export function isAssistantMarkdownBlockquote(line: string) {
  return /^\s{0,3}>\s?/.test(line)
}

export function AssistantMarkdownBlockquote({ text }: { text: string }) {
  return (
    <blockquote className="border-l-2 border-gray-300 pl-3 text-[13px] leading-relaxed text-gray-700 dark:border-white/20 dark:text-gray-200">
      {renderAssistantInlineText(text)}
    </blockquote>
  )
}

export function useAssistantCopyText(text: string) {
  const cleanText = text.replace(/\s+$/g, "")
  const [copied, setCopied] = useState(false)
  const copiedResetTimerRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (copiedResetTimerRef.current !== null) {
        window.clearTimeout(copiedResetTimerRef.current)
      }
    }
  }, [])

  const handleCopy = useCallback(async () => {
    if (!cleanText) return
    try {
      await copyAssistantTextToClipboard(cleanText)
      if (copiedResetTimerRef.current !== null) {
        window.clearTimeout(copiedResetTimerRef.current)
      }
      setCopied(true)
      copiedResetTimerRef.current = window.setTimeout(() => {
        setCopied(false)
        copiedResetTimerRef.current = null
      }, 1200)
      toast.success("已复制")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "复制失败")
    }
  }, [cleanText])

  return { cleanText, copied, handleCopy }
}

export function AssistantCopyableCodeBlock({ text }: { text: string }) {
  const { cleanText, copied, handleCopy } = useAssistantCopyText(text)

  if (!cleanText) {
    return null
  }

  if (cleanText.includes("\n")) {
    return (
      <div className="group relative rounded-md bg-gray-100/60 px-2.5 py-2 pr-8 text-[11.5px] leading-relaxed text-gray-800 dark:bg-white/[0.06] dark:text-gray-100">
        <pre className="whitespace-pre-wrap break-words font-mono">{cleanText}</pre>
        <button
          type="button"
          onClick={handleCopy}
          className={cn(
            "absolute top-1.5 right-1.5 inline-flex size-6 items-center justify-center rounded opacity-70 transition hover:bg-white focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-indigo-400/40 focus-visible:outline-none group-hover:opacity-100 dark:hover:bg-white/10",
            copied
              ? "text-emerald-500 dark:text-emerald-300"
              : "text-gray-400 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-100"
          )}
          title={copied ? "已复制" : "复制"}
          aria-label={copied ? "已复制" : "复制"}
        >
          {copied ? <CheckCircle2 className="size-3.5" /> : <Copy className="size-3.5" />}
        </button>
      </div>
    )
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={cn(
        "block w-full cursor-copy rounded-sm py-1 text-left text-[11.5px] leading-relaxed transition focus-visible:ring-2 focus-visible:ring-indigo-400/40 focus-visible:outline-none",
        copied
          ? "text-emerald-600 dark:text-emerald-300"
          : "text-gray-800 hover:text-indigo-700 dark:text-gray-100 dark:hover:text-indigo-200"
      )}
      title={copied ? "已复制" : "复制"}
      aria-label={copied ? "已复制" : "复制"}
    >
      <span className="whitespace-pre-wrap break-words font-mono">{cleanText}</span>
      {copied ? (
        <CheckCircle2 className="ml-1 inline-block size-3.5 align-[-2px] text-emerald-500 dark:text-emerald-300" />
      ) : (
        <Copy className="ml-1 inline-block size-3.5 align-[-2px] text-gray-400 dark:text-gray-500" />
      )}
    </button>
  )
}

export function AssistantCopyableInlineReply({ text }: { text: string }) {
  const { cleanText, copied, handleCopy } = useAssistantCopyText(text)

  if (!cleanText) {
    return null
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={cn(
        "inline-flex min-w-0 cursor-copy items-center gap-1 rounded-sm px-0.5 py-0.5 align-baseline text-left text-[11.5px] leading-relaxed transition focus-visible:ring-2 focus-visible:ring-indigo-400/40 focus-visible:outline-none",
        copied
          ? "text-emerald-600 dark:text-emerald-300"
          : "text-gray-800 hover:text-indigo-700 dark:text-gray-100 dark:hover:text-indigo-200"
      )}
      title={copied ? "已复制" : "复制回复内容"}
      aria-label={copied ? "已复制" : "复制回复内容"}
    >
      <span className="min-w-0 break-words font-mono">{cleanText}</span>
      {copied ? (
        <CheckCircle2 className="size-3.5 shrink-0 text-emerald-500 dark:text-emerald-300" />
      ) : (
        <Copy className="size-3.5 shrink-0 text-gray-400 dark:text-gray-500" />
      )}
    </button>
  )
}

export function assistantMarkdownTableCells(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim())
}

export function isAssistantMarkdownTable(lines: string[]) {
  if (lines.length < 2) return false
  const separator = lines[1].trim()
  return (
    lines[0].includes("|") &&
    /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(separator)
  )
}

export function isAssistantMarkdownDivider(line: string) {
  return /^\s{0,3}(-{3,}|\*{3,}|_{3,})\s*$/.test(line)
}

export function isAssistantMarkdownHeading(line: string) {
  return /^\s{0,3}#{1,6}\s+/.test(line)
}

export function isAssistantUnorderedListItem(line: string) {
  return /^\s*[-*+•]\s+/.test(line)
}

export function assistantOrderedListMatch(line: string) {
  return line.match(/^\s*(\d+)[.)、]\s+(.+)$/)
}

export function isAssistantOrderedListItem(line: string) {
  return Boolean(assistantOrderedListMatch(line))
}

export function assistantJoinParagraphLines(lines: string[]) {
  return lines.reduce((text, line) => {
    if (!text) return line
    if (
      /[\u4e00-\u9fff）】」』”’。，！？；：]$/.test(text) ||
      /^[\u4e00-\u9fff（【「『“‘]/.test(line)
    ) {
      return `${text}${line}`
    }
    return `${text} ${line}`
  }, "")
}

export function assistantMarkdownParagraphsFromLines(lines: string[]) {
  const paragraphs: string[] = []
  let current: string[] = []

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) {
      if (current.length) {
        paragraphs.push(assistantJoinParagraphLines(current))
        current = []
      }
      continue
    }
    current.push(trimmed)
  }

  if (current.length) {
    paragraphs.push(assistantJoinParagraphLines(current))
  }

  return paragraphs
}

export function assistantCleanOrderedListTitle(text: string) {
  const normalized = text
    .trim()
    .replace(/\s*[：:]\s*(\*\*)\s*$/, "$1")
    .replace(/\s*[：:]\s*$/, "")
  const strongMatch = normalized.match(/^\*\*(.+)\*\*$/)
  return (strongMatch?.[1] || normalized).trim()
}

export function isAssistantOrderedListContinuationBoundary(
  lines: string[],
  index: number
) {
  const line = lines[index] ?? ""
  if (!line.trim()) return false
  if (line.trim().startsWith("```")) return true
  if (isAssistantMarkdownDivider(line)) return true
  if (isAssistantMarkdownHeading(line)) return true
  if (isAssistantMarkdownBlockquote(line)) return true
  if (isAssistantUnorderedListItem(line)) return true
  if (
    index + 1 < lines.length &&
    isAssistantMarkdownTable(lines.slice(index, index + 2))
  ) {
    return true
  }
  return false
}

export function isAssistantMarkdownBoundary(lines: string[], index: number) {
  const line = lines[index] ?? ""
  if (!line.trim()) return true
  if (line.trim().startsWith("```")) return true
  if (isAssistantMarkdownDivider(line)) return true
  if (isAssistantMarkdownHeading(line)) return true
  if (isAssistantMarkdownBlockquote(line)) return true
  if (isAssistantUnorderedListItem(line)) return true
  if (isAssistantOrderedListItem(line)) return true
  if (
    index + 1 < lines.length &&
    isAssistantMarkdownTable(lines.slice(index, index + 2))
  ) {
    return true
  }
  return false
}

export function AssistantActionFooterBlock({
  footer,
}: {
  footer: AssistantActionFooter
}) {
  const reply = footer.reply || ""
  const label = footer.label || ""
  const title = footer.title || ""
  const description = footer.description || ""
  const heading = title || label
  const showLabelBadge = Boolean(label && title)
  const hasStructuredContent = Boolean(
    footer.label || footer.title || footer.description || footer.reply
  )

  if (!hasStructuredContent) {
    return null
  }

  return (
    <div className="ai-video-assistant-action-footer select-text cursor-text rounded-lg border border-indigo-100/80 bg-indigo-50/55 px-2.5 py-2 text-left shadow-sm shadow-indigo-950/[0.025] dark:border-indigo-300/15 dark:bg-indigo-400/[0.08] dark:shadow-none">
      <div className="min-w-0">
        {heading ? (
          <div className="flex min-w-0 items-center gap-2">
            <span className="grid size-5 shrink-0 place-items-center rounded-md bg-indigo-600 text-white dark:bg-indigo-400 dark:text-indigo-950">
              <CheckCircle2 className="size-3.5" />
            </span>
            <span className="min-w-0 flex-1 truncate text-[12px] leading-snug font-semibold text-gray-800 dark:text-gray-100">
              {renderAssistantInlineText(heading)}
            </span>
            {showLabelBadge ? (
              <span className="shrink-0 rounded-full bg-indigo-100 px-1.5 py-0.5 text-[10px] leading-none font-semibold text-indigo-700 dark:bg-indigo-300/15 dark:text-indigo-100">
                {label}
              </span>
            ) : null}
          </div>
        ) : null}
        {description ? (
          <div
            className={cn(
              "mt-1 text-[11.5px] leading-relaxed whitespace-pre-line text-gray-600 dark:text-gray-300",
              heading ? "pl-7" : ""
            )}
          >
            {renderAssistantInlineText(description)}
          </div>
        ) : null}
        {reply ? (
          <div
            className={cn(
              "mt-1.5 flex min-w-0 flex-wrap items-baseline gap-x-1 text-[11.5px] leading-relaxed text-gray-600 dark:text-gray-300",
              heading ? "pl-7" : ""
            )}
          >
            <span className="font-semibold text-indigo-600 dark:text-indigo-200">
              回复：
            </span>
            <AssistantCopyableInlineReply text={reply} />
          </div>
        ) : null}
      </div>
    </div>
  )
}

export function AssistantFormattedText({
  text,
  expanded,
  compact = false,
}: {
  text: string
  expanded: boolean
  compact?: boolean
}) {
  const collapsed = !expanded && assistantTextCanCollapse(text)
  const displayText = assistantDisplayText(text, expanded)
  const normalized = displayText.replace(/\r\n/g, "\n").trim()
  if (!normalized) return null
  const lines = normalized.split("\n")
  const rendered: React.ReactNode[] = []

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    if (!line.trim()) continue

    if (line.trim().startsWith("```")) {
      const codeLines: string[] = []
      index += 1
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index])
        index += 1
      }
      rendered.push(
        <AssistantCopyableCodeBlock
          key={`code-${index}-${rendered.length}`}
          text={codeLines.join("\n")}
        />
      )
      continue
    }

    if (isAssistantMarkdownBlockquote(line)) {
      const quoteLines: string[] = []
      while (index < lines.length && isAssistantMarkdownBlockquote(lines[index])) {
        quoteLines.push(lines[index].replace(/^\s{0,3}>\s?/, "").trim())
        index += 1
      }
      index -= 1
      rendered.push(
        <AssistantMarkdownBlockquote
          key={`blockquote-${index}-${rendered.length}`}
          text={quoteLines.join("\n")}
        />
      )
      continue
    }

    if (isAssistantMarkdownDivider(line)) {
      rendered.push(
        <hr
          key={`hr-${index}-${rendered.length}`}
          className="my-2 border-0 border-t border-gray-200/80 dark:border-white/10"
        />
      )
      continue
    }

    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/)
    if (heading) {
      const level = heading[1].length
      rendered.push(
        <div
          key={`heading-${index}-${rendered.length}`}
          className={cn(
            "pt-0.5 font-semibold text-gray-900 dark:text-white",
            level <= 1 ? "text-[14px]" : level === 2 ? "text-[13.5px]" : "text-[13px]"
          )}
        >
          {renderAssistantInlineText(heading[2].trim())}
        </div>
      )
      continue
    }

    if (
      index + 1 < lines.length &&
      isAssistantMarkdownTable(lines.slice(index, index + 2))
    ) {
      const tableLines = [lines[index], lines[index + 1]]
      index += 2
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        tableLines.push(lines[index])
        index += 1
      }
      index -= 1
      const headers = assistantMarkdownTableCells(tableLines[0])
      const rows = tableLines.slice(2).map(assistantMarkdownTableCells)
      rendered.push(
        <div
          key={`table-${index}-${rendered.length}`}
          className="overflow-x-auto rounded-lg border border-gray-200/70 bg-white/80 dark:border-white/10 dark:bg-[#25262d]"
        >
          <table className="min-w-full border-collapse text-left text-[11.5px]">
            <thead className="bg-gray-50 text-gray-500 dark:bg-white/[0.06] dark:text-gray-200">
              <tr>
                {headers.map((header, headerIndex) => (
                  <th
                    key={`${index}-th-${headerIndex}`}
                    className="px-2 py-1.5 font-semibold"
                  >
                    {renderAssistantInlineText(header)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr
                  key={`${index}-tr-${rowIndex}`}
                  className="odd:bg-white even:bg-gray-50/60 dark:odd:bg-transparent dark:even:bg-white/[0.035]"
                >
                  {headers.map((_, cellIndex) => (
                    <td
                      key={`${index}-td-${rowIndex}-${cellIndex}`}
                      className="px-2 py-1.5 align-top"
                    >
                      {renderAssistantInlineText(row[cellIndex] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
      continue
    }

    if (isAssistantUnorderedListItem(line)) {
      const items: string[] = []
      while (index < lines.length && isAssistantUnorderedListItem(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*+•]\s+/, "").trim())
        index += 1
      }
      index -= 1
      rendered.push(
        <ul key={`ul-${index}-${rendered.length}`} className="space-y-1 pl-0">
          {items.map((item, itemIndex) => (
            <li key={`${index}-ul-${itemIndex}`} className="flex gap-2">
              <span className="mt-[0.72em] size-1 shrink-0 rounded-full bg-gray-400 dark:bg-gray-500" />
              <span className="min-w-0">{renderAssistantInlineText(item)}</span>
            </li>
          ))}
        </ul>
      )
      continue
    }

    if (isAssistantOrderedListItem(line)) {
      const items: Array<{
        number: string
        text: string
        paragraphs: string[]
      }> = []
      let hasContinuation = false

      while (index < lines.length && isAssistantOrderedListItem(lines[index])) {
        const match = assistantOrderedListMatch(lines[index])
        if (!match) break

        const detailLines: string[] = []
        index += 1
        while (
          index < lines.length &&
          !isAssistantOrderedListItem(lines[index]) &&
          !isAssistantOrderedListContinuationBoundary(lines, index)
        ) {
          detailLines.push(lines[index])
          index += 1
        }

        const paragraphs = assistantMarkdownParagraphsFromLines(detailLines)
        if (paragraphs.length) hasContinuation = true
        items.push({
          number: match[1],
          text: match[2].trim(),
          paragraphs,
        })
      }
      index -= 1

      if (hasContinuation) {
        rendered.push(
          <div key={`ol-rich-${index}-${rendered.length}`} className="space-y-1">
            {items.map((item, itemIndex) => (
              <section
                key={`${index}-ol-rich-${itemIndex}`}
                className={cn(
                  "py-1.5 pr-1",
                  itemIndex > 0 &&
                    "border-t border-gray-200/70 pt-2.5 dark:border-white/10"
                )}
              >
                <div className="flex min-w-0 items-start gap-2.5">
                  <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded bg-indigo-50 font-mono text-[10.5px] font-semibold text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-200">
                    {item.number}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[12.5px] font-semibold break-words text-indigo-600 dark:text-indigo-200">
                      {renderAssistantInlineText(
                        assistantCleanOrderedListTitle(item.text)
                      )}
                    </div>
                    {item.paragraphs.length ? (
                      <div className="mt-1.5 space-y-1.5 text-[12px] leading-[1.65] text-gray-700 dark:text-gray-200">
                        {item.paragraphs.map((paragraph, paragraphIndex) => (
                          <p key={`${index}-ol-rich-${itemIndex}-${paragraphIndex}`}>
                            {renderAssistantInlineText(paragraph)}
                          </p>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
              </section>
            ))}
          </div>
        )
      } else {
        rendered.push(
          <ol key={`ol-${index}-${rendered.length}`} className="space-y-1 pl-0">
            {items.map((item, itemIndex) => (
              <li key={`${index}-ol-${itemIndex}`} className="flex gap-2">
                <span className="w-5 shrink-0 text-right font-mono text-[11px] text-gray-400 dark:text-gray-500">
                  {item.number}.
                </span>
                <span className="min-w-0">{renderAssistantInlineText(item.text)}</span>
              </li>
            ))}
          </ol>
        )
      }
      continue
    }

    const paragraphLines = [line.trim()]
    index += 1
    while (index < lines.length && !isAssistantMarkdownBoundary(lines, index)) {
      paragraphLines.push(lines[index].trim())
      index += 1
    }
    index -= 1
    rendered.push(
      <p key={`p-${index}-${rendered.length}`} className="whitespace-pre-line">
        {renderAssistantInlineText(paragraphLines.join("\n"))}
      </p>
    )
  }

  const content = (
    <div
      className={cn(
        "ai-video-assistant-markdown space-y-2 break-words text-gray-700 dark:text-gray-100",
        compact ? "text-[11.5px] leading-relaxed" : "text-[12.5px] leading-[1.72]"
      )}
    >
      {rendered}
    </div>
  )

  if (!collapsed) return content

  return (
    <div className="relative max-h-[4.75rem] overflow-hidden pr-5">
      {content}
      <span
        aria-hidden="true"
        className="absolute right-0 bottom-0 text-[13px] leading-none font-semibold text-gray-400 dark:text-gray-500"
      >
        ...
      </span>
    </div>
  )
}
