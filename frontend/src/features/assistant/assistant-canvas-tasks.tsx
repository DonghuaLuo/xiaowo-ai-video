import { Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"
import type { AssistantSessionSummary } from "./assistant-session-normalization"
import { isActiveCanvasTask } from "./assistant-canvas-task-model"

export function AssistantCanvasTasks({
  sessions,
  currentSessionId,
  loading,
  onSelect,
}: {
  sessions: AssistantSessionSummary[]
  currentSessionId: string | null
  loading: boolean
  onSelect: (sessionId: string) => void
}) {
  const selected = sessions.find((row) => row.id === currentSessionId)
  const main =
    sessions.find((row) => row.id === selected?.canvasTask?.parentSessionId) ??
    sessions.find((row) => row.id === currentSessionId && !row.canvasTask)
  const active = sessions.filter(
    (row) =>
      row.canvasTask?.parentSessionId === main?.id && isActiveCanvasTask(row)
  )
  if (active.length <= 1) return null
  const taskButton = (task: AssistantSessionSummary) => {
    return (
      <button
        key={task.id}
        type="button"
        disabled={loading}
        aria-pressed={task.id === currentSessionId}
        onClick={() => onSelect(task.id)}
        className={cn(
          "flex h-8 w-full items-center gap-2 rounded-lg px-2 text-left text-[11px] transition-colors hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-white/5",
          task.id === currentSessionId &&
            "bg-indigo-50 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-200"
        )}
      >
        <Loader2 className="size-3.5 shrink-0 animate-spin" />
        <span className="min-w-0 flex-1 truncate" title={task.title}>
          {task.title}
        </span>
        <span className="shrink-0 text-[10px] text-gray-500 dark:text-gray-400">
          执行中
        </span>
      </button>
    )
  }
  return (
    <div
      className="shrink-0 border-b border-gray-200/70 px-2 py-2 dark:border-white/10"
      aria-label="画布智能体任务"
    >
      {active.length > 5 && (
        <div className="mb-1 px-2 text-[11px] text-gray-500 dark:text-gray-400">
          当前会话共{active.length}个任务
        </div>
      )}
      <div className={active.length > 5 ? "max-h-40 overflow-y-auto" : undefined}>
        {active.map(taskButton)}
      </div>
    </div>
  )
}
