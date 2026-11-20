import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { AlertCircle, ChevronRight, Copy, Loader2, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import { ICON_GHOST_BTN_CLS } from "@/shared/button-styles"
import { isBackendFailure } from "@/shared/backend-result"
import {
  AssistantAgentLogEntry,
  assistantAgentLogFullText,
  assistantAgentLogStageLabel,
  assistantAgentLogTitle,
  copyAssistantTextToClipboard,
  formatAssistantAgentLogTime,
  normalizeAssistantAgentLogEntries,
} from "./assistant-session-normalization"
import type { BackendCaller } from "@/backend"
type AssistantErrorLogsProps = {
  projectId: string
  backendReady: boolean
  callBackend: BackendCaller
  activeSessionRunning: boolean
}
export function useAssistantErrorLogs({
  projectId,
  backendReady,
  callBackend,
  activeSessionRunning,
}: AssistantErrorLogsProps) {
  const scopeRef = useRef({ projectId })
  if (scopeRef.current.projectId !== projectId) scopeRef.current = { projectId }
  useEffect(() => {
    scopeRef.current = { projectId }
    const scope = scopeRef.current
    return () => {
      if (scopeRef.current === scope) scopeRef.current = { projectId: "" }
    }
  }, [projectId])
  const [agentLogsOpen, setAgentLogsOpen] = useState(false)

  const [agentLogs, setAgentLogs] = useState<AssistantAgentLogEntry[]>([])

  const [agentLogsLoading, setAgentLogsLoading] = useState(false)

  const [agentLogsClearing, setAgentLogsClearing] = useState(false)

  const [agentLogsError, setAgentLogsError] = useState<string | null>(null)

  const agentLogsLoadingRef = useRef(false)

  const agentLogsClearingRef = useRef(false)

  const loadAgentErrorLogs = useCallback(async () => {
    if (!backendReady || agentLogsLoadingRef.current || agentLogsClearingRef.current) {
      return
    }
    const requestScope = scopeRef.current
    const currentScope = () => scopeRef.current === requestScope
    agentLogsLoadingRef.current = true
    setAgentLogsLoading(true)
    setAgentLogsError(null)
    try {
      const result = await callBackend<{
        success?: boolean
        logs?: unknown[]
        message?: string
      }>("list_agent_error_logs", {
        projectId: projectId,
        limit: 80,
        days: 7,
      })
      if (!currentScope()) return
      if (isBackendFailure(result)) {
        throw new Error(result.message || "读取智能体错误日志失败")
      }
      setAgentLogs(normalizeAssistantAgentLogEntries(result.logs))
    } catch (error) {
      if (!currentScope()) return
      setAgentLogsError(error instanceof Error ? error.message : "读取智能体错误日志失败")
    } finally {
      if (!currentScope()) return
      agentLogsLoadingRef.current = false
      setAgentLogsLoading(false)
    }
  }, [backendReady, callBackend, projectId])

  useEffect(() => {
    if (!agentLogsOpen || !backendReady) return
    void loadAgentErrorLogs()
    const refreshMs = activeSessionRunning ? 5000 : 12000
    const timer = window.setInterval(() => {
      void loadAgentErrorLogs()
    }, refreshMs)
    return () => window.clearInterval(timer)
  }, [activeSessionRunning, agentLogsOpen, backendReady, loadAgentErrorLogs])

  const clearAgentErrorLogs = useCallback(async () => {
    if (!backendReady || agentLogsClearingRef.current) return
    const requestScope = scopeRef.current
    const currentScope = () => scopeRef.current === requestScope
    agentLogsClearingRef.current = true
    setAgentLogsClearing(true)
    setAgentLogsError(null)
    try {
      const result = await callBackend<{
        success?: boolean
        cleared?: number
        message?: string
      }>("clear_agent_error_logs", {
        projectId: projectId,
      })
      if (!currentScope()) return
      if (isBackendFailure(result)) {
        throw new Error(result.message || "清空智能体错误日志失败")
      }
      setAgentLogs([])
      toast.success(
        result.cleared && result.cleared > 0
          ? `已清空 ${result.cleared} 条错误日志`
          : "智能体错误日志已清空"
      )
    } catch (error) {
      if (!currentScope()) return
      const message = error instanceof Error ? error.message : "清空智能体错误日志失败"
      setAgentLogsError(message)
      toast.error(message)
    } finally {
      if (!currentScope()) return
      agentLogsClearingRef.current = false
      setAgentLogsClearing(false)
    }
  }, [backendReady, callBackend, projectId])

  const copyAgentErrorLog = useCallback(async (log: AssistantAgentLogEntry) => {
    try {
      await copyAssistantTextToClipboard(assistantAgentLogFullText(log))
      toast.success("错误信息已复制")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "复制错误信息失败")
    }
  }, [])

  useEffect(() => {
    setAgentLogs([])
    setAgentLogsError(null)
    setAgentLogsOpen(false)
    setAgentLogsLoading(false)
    setAgentLogsClearing(false)
    agentLogsLoadingRef.current = false
    agentLogsClearingRef.current = false
  }, [projectId])
  return {
    agentLogsOpen,
    agentLogs,
    agentLogsLoading,
    agentLogsClearing,
    agentLogsError,
    setAgentLogsOpen,
    loadAgentErrorLogs,
    clearAgentErrorLogs,
    copyAgentErrorLog,
  }
}
export function AssistantErrorLogs(props: AssistantErrorLogsProps) {
  const { backendReady } = props
  const {
    agentLogsOpen,
    agentLogs,
    agentLogsLoading,
    agentLogsClearing,
    agentLogsError,
    setAgentLogsOpen,
    clearAgentErrorLogs,
    copyAgentErrorLog,
  } = useAssistantErrorLogs(props)
  return (
    <DropdownMenu open={agentLogsOpen} onOpenChange={setAgentLogsOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          className={cn(
            ICON_GHOST_BTN_CLS,
            agentLogs.length > 0
              ? "text-rose-500 hover:text-rose-600 dark:text-rose-300"
              : ""
          )}
          title="智能体错误日志"
          disabled={!backendReady}
        >
          {agentLogsLoading ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <AlertCircle className="size-3.5" />
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        collisionPadding={{ top: 16, right: 16, bottom: 28, left: 16 }}
        className="z-[11000] max-h-[var(--radix-dropdown-menu-content-available-height)] w-96 max-w-[calc(100vw-2rem)] overflow-y-auto rounded-lg border-gray-200/80 bg-white/95 p-1.5 shadow-xl shadow-gray-950/10 dark:border-white/10 dark:bg-[#24242a]"
      >
        <div className="flex items-center justify-between gap-2 px-2.5 py-2">
          <DropdownMenuLabel className="p-0 font-mono text-[11px] tracking-[0.14em] text-gray-400 uppercase dark:text-gray-500">
            智能体错误日志
          </DropdownMenuLabel>
          <button
            type="button"
            className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11px] text-rose-500 transition hover:bg-rose-50 hover:text-rose-700 disabled:cursor-not-allowed disabled:opacity-45 dark:text-rose-300 dark:hover:bg-rose-950/30 dark:hover:text-rose-100"
            disabled={agentLogsLoading || agentLogsClearing || agentLogs.length === 0}
            onClick={(event) => {
              event.preventDefault()
              event.stopPropagation()
              void clearAgentErrorLogs()
            }}
          >
            <Trash2 className="size-3" />
            {agentLogsClearing ? "清空中" : "清空全部"}
          </button>
        </div>
        <DropdownMenuSeparator className="bg-gray-200/70 dark:bg-white/10" />
        {agentLogsError ? (
          <div className="mx-1.5 my-2 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-2 text-[11.5px] leading-relaxed text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/20 dark:text-rose-100">
            {agentLogsError}
          </div>
        ) : agentLogsLoading && agentLogs.length === 0 ? (
          <div className="px-2.5 py-3 text-[11.5px] text-gray-500 dark:text-gray-400">
            正在读取当前项目的智能体错误日志...
          </div>
        ) : agentLogs.length === 0 ? (
          <div className="px-2.5 py-3 text-[11.5px] leading-relaxed text-gray-500 dark:text-gray-400">
            最近没有记录到智能体执行错误。
          </div>
        ) : (
          <div className="max-h-[calc(var(--radix-dropdown-menu-content-available-height)_-_4.75rem)] space-y-1 overflow-y-auto pr-1">
            {agentLogs.map((log) => {
              const title = assistantAgentLogTitle(log)
              const timeText = formatAssistantAgentLogTime(log.timestamp)
              const stageText = assistantAgentLogStageLabel(log.stage)
              const fullText = assistantAgentLogFullText(log)
              return (
                <details
                  key={log.id}
                  className="group rounded-lg border border-gray-200/80 bg-white/70 px-2.5 py-2 text-[11.5px] leading-relaxed text-gray-700 dark:border-white/10 dark:bg-white/[0.045] dark:text-gray-200"
                  onClick={(event) => event.stopPropagation()}
                >
                  <summary className="flex cursor-pointer list-none items-start gap-2 marker:hidden [&::-webkit-details-marker]:hidden">
                    <span className="mt-1 size-1.5 shrink-0 rounded-full bg-rose-500" />
                    <span className="min-w-0 flex-1">
                      <span className="block break-words font-medium text-gray-900 dark:text-gray-50">
                        {title}
                      </span>
                      <span className="mt-1 flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-[10.5px] text-gray-400 dark:text-gray-500">
                        <span>记录时间：{timeText}</span>
                        <span>发生环节：{stageText}</span>
                      </span>
                    </span>
                    <ChevronRight className="mt-0.5 size-3.5 shrink-0 text-gray-300 transition-transform group-open:rotate-90 dark:text-gray-500" />
                  </summary>
                  <div className="mt-2 border-t border-gray-200/70 pt-2 dark:border-white/10">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] text-gray-400 dark:text-gray-500">
                        完整错误信息
                      </span>
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-gray-500 transition hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-white/10 dark:hover:text-gray-100"
                        onClick={(event) => {
                          event.preventDefault()
                          event.stopPropagation()
                          void copyAgentErrorLog(log)
                        }}
                      >
                        <Copy className="size-3" />
                        复制
                      </button>
                    </div>
                    <pre className="mt-1 overflow-x-auto rounded-md bg-gray-950/[0.04] p-2 text-[10.5px] leading-relaxed whitespace-pre-wrap text-gray-600 dark:bg-white/[0.06] dark:text-gray-300">
                      {fullText}
                    </pre>
                  </div>
                </details>
              )
            })}
          </div>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
