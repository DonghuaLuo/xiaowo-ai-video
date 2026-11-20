import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { AlertCircle, CheckCircle2, ChevronDown, Clock3, ListChecks, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { isAssistantScrollNearBottom } from "./assistant-message-model"
import { assistantDispatchDetailItems, isInternalDispatchActivity, summarizeAssistantDispatch } from "./assistant-dispatch-model"
import {
  ASSISTANT_LIVE_ACTIVITY_HISTORY_LIMIT,
  type AssistantLiveActivityItem,
} from "./assistant-session-normalization"

type AssistantDispatchPanelProps = {
  taskTitle?: string
  sessionKey: string
  active: boolean
  waitingForInput: boolean
  items: AssistantLiveActivityItem[]
  elapsedText?: string
  resetKey: number
}

function DispatchStatusIcon({ status }: { status: "running" | "completed" | "waiting" | "revision" | "error" }) {
  if (status === "completed") return <CheckCircle2 className="size-3.5 shrink-0 text-emerald-500" />
  if (status === "waiting") return <Clock3 className="size-3.5 shrink-0 text-amber-500" />
  if (status === "revision") return <AlertCircle className="size-3.5 shrink-0 text-amber-500" />
  if (status === "error") return <AlertCircle className="size-3.5 shrink-0 text-rose-500" />
  // 旋转后的 SVG 外接范围会增加滚动溢出，短列表因此会反复出现 1px 滚动条。
  return (
    <span className="flex size-3.5 shrink-0 overflow-hidden">
      <Loader2 className="size-3.5 shrink-0 animate-spin text-indigo-500" />
    </span>
  )
}

function activityIdentity(item: AssistantLiveActivityItem): string {
  if (item.toolUseId && (item.kind === "tool_use" || item.kind === "tool_result")) {
    return `${item.kind}:${item.toolUseId}`
  }
  return `${item.kind || "activity"}:${item.text}`
}

export function AssistantDispatchPanel({
  taskTitle,
  sessionKey,
  active,
  waitingForInput,
  items,
  elapsedText,
  resetKey,
}: AssistantDispatchPanelProps) {
  const listRef = useRef<HTMLDivElement | null>(null)
  const seenEventsRef = useRef<Set<string>>(new Set())
  const nextEventIdRef = useRef(0)
  const [autoScroll, setAutoScroll] = useState(true)
  const [expanded, setExpanded] = useState(true)
  const [detailsExpanded, setDetailsExpanded] = useState(false)
  const [history, setHistory] = useState<AssistantLiveActivityItem[]>([])
  const stages = useMemo(() => summarizeAssistantDispatch(history, waitingForInput), [history, waitingForInput])

  useEffect(() => {
    setAutoScroll(true)
    setExpanded(true)
    setDetailsExpanded(false)
    setHistory([])
    seenEventsRef.current.clear()
    nextEventIdRef.current = 0
  }, [resetKey, sessionKey])

  useEffect(() => {
    if (!active && !waitingForInput) {
      seenEventsRef.current.clear()
      setHistory([])
      nextEventIdRef.current = 0
      return
    }
    const visibleItems = items.filter((item) => !isInternalDispatchActivity(item))
    const appended = visibleItems.flatMap((item) => {
      const identity = activityIdentity(item)
      if (seenEventsRef.current.has(identity)) return []
      seenEventsRef.current.add(identity)
      return [{ ...item, id: `dispatch-${++nextEventIdRef.current}` }]
    })
    if (appended.length) {
      setHistory((current) => [...current, ...appended].slice(-ASSISTANT_LIVE_ACTIVITY_HISTORY_LIMIT))
    }
  }, [active, waitingForInput, items, resetKey, sessionKey])

  useEffect(() => {
    if (!autoScroll || !expanded || !detailsExpanded) return
    const element = listRef.current
    if (!element) return
    const bottom = element.scrollHeight - element.clientHeight
    if (bottom > 1 && bottom - element.scrollTop > 1) {
      element.scrollTop = bottom
    }
  }, [history, autoScroll, expanded, detailsExpanded])

  const handleScroll = useCallback(() => {
    if (listRef.current) setAutoScroll(isAssistantScrollNearBottom(listRef.current))
  }, [])

  const jumpToLatest = useCallback(() => {
    const element = listRef.current
    if (element) element.scrollTo({ top: element.scrollHeight, behavior: "smooth" })
    setAutoScroll(true)
  }, [])

  if (!active && !waitingForInput) return null

  const panelTitle = taskTitle || "智能体正在运行中"
  const toolOutcomes = new Map(history.filter((item) => item.kind === "tool_result" && item.toolUseId)
    .map((item) => [item.toolUseId as string,
      item.outcome === "revision_required" ? "revision" : item.isError ? "error" : "completed"] as const))
  // A tool result updates its matching call; showing both creates two failure rows for one attempt.
  const detailItems = assistantDispatchDetailItems(history)

  return (
    <section
      aria-label={panelTitle}
      className="mx-3 mb-2 shrink-0 overflow-hidden rounded-lg border border-indigo-200/80 bg-white/85 shadow-sm shadow-indigo-950/[0.03] dark:border-indigo-300/20 dark:bg-white/[0.055] dark:shadow-none"
    >
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-indigo-50/60 dark:hover:bg-indigo-400/[0.08]"
      >
        <ListChecks className="size-3.5 shrink-0 text-indigo-500" />
        <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-gray-800 dark:text-gray-100">
          {panelTitle}
        </span>
        {waitingForInput ? <span className="shrink-0 text-[10px] text-amber-600 dark:text-amber-300">等待你的回复</span> : null}
        {elapsedText && !waitingForInput ? (
          <span className="shrink-0 text-[10px] text-gray-500 dark:text-gray-400">{elapsedText}</span>
        ) : null}
        <ChevronDown className={cn("size-3.5 shrink-0 text-gray-400 transition-transform", !expanded && "-rotate-90")} />
      </button>
      {expanded ? (
        <div className="border-t border-indigo-100/80 px-3 py-2 dark:border-white/10">
          <div className="space-y-1.5" aria-label="关键执行阶段" aria-live="polite">
            {stages.length ? stages.map((stage) => (
              <div key={stage.key} className="flex min-w-0 items-center gap-2 text-[11.5px] leading-relaxed">
                <DispatchStatusIcon status={stage.status} />
                <span className={cn(
                  "min-w-0 flex-1 truncate",
                  stage.status === "completed" ? "text-gray-500 dark:text-gray-400" : "text-gray-800 dark:text-gray-100"
                )}>{stage.label}</span>
                {stage.operations > 1 ? (
                  <span className="shrink-0 text-[10px] text-gray-400 dark:text-gray-500">{stage.operations} 次操作</span>
                ) : null}
              </div>
            )) : (
              <p className="text-[11.5px] text-gray-500 dark:text-gray-400">等待智能体返回执行阶段…</p>
            )}
          </div>
          {detailItems.length ? (
            <div className="mt-2 pt-1.5">
              <button
                type="button"
                aria-expanded={detailsExpanded}
                onClick={() => setDetailsExpanded((value) => !value)}
                className="flex w-full items-center gap-1.5 text-left text-[10.5px] text-gray-500 hover:text-indigo-700 dark:text-gray-400 dark:hover:text-indigo-200"
              >
                <ChevronDown className={cn("size-3 shrink-0 transition-transform", !detailsExpanded && "-rotate-90")} />
                执行明细（{detailItems.length}）
              </button>
              {detailsExpanded ? (
                <>
                  <div
                    ref={listRef}
                    onScroll={handleScroll}
                    role="log"
                    aria-label="完整执行记录"
                    aria-live="off"
                    className="mt-1.5 max-h-44 space-y-1.5 overflow-y-auto pr-1 [scrollbar-gutter:stable]"
                  >
                    {detailItems.map((item, index) => {
                      const toolOutcome = item.kind === "tool_use" && item.toolUseId
                        ? toolOutcomes.get(item.toolUseId) : undefined
                      const status = item.kind === "tool_result"
                        ? item.outcome === "revision_required" ? "revision" : item.isError ? "error" : "completed"
                        : toolOutcome ?? (item.isError ? "error"
                        : item.kind === "tool_use" && active ? "running"
                        : index === detailItems.length - 1 && active ? "running" : "completed")
                      const resultLabel = item.kind === "tool_use" && toolOutcome === "revision"
                        ? " · 校验未通过，正在修订"
                        : item.kind === "tool_use" && toolOutcome === "error"
                          ? " · 执行失败" : ""
                      return (
                        <div key={item.id} className="flex min-w-0 items-start gap-2 text-[11px] leading-relaxed">
                          <span className="mt-0.5"><DispatchStatusIcon status={status} /></span>
                          <span className="min-w-0 break-words text-gray-600 dark:text-gray-300">{item.text}{resultLabel}</span>
                        </div>
                      )
                    })}
                  </div>
                  {!autoScroll ? (
                    <button type="button" onClick={jumpToLatest} className="mt-1.5 text-[10.5px] text-indigo-600 hover:underline dark:text-indigo-300">
                      查看最新执行记录
                    </button>
                  ) : null}
                </>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
