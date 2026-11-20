import {
  CheckCircle2,
  Clock3,
  ClipboardList,
  Loader2,
  Send,
  X,
} from "lucide-react"
import { cn } from "@/lib/utils"
import {
  AssistantContentBlock,
  AssistantQuickPrompt,
} from "./assistant-session-normalization"

export function AssistantQuickPromptBar({
  prompts,
  disabled,
  onSelect,
}: {
  prompts: AssistantQuickPrompt[]
  disabled: boolean
  onSelect: (prompt: AssistantQuickPrompt) => void
}) {
  if (!prompts.length) return null

  return (
    <div className="mb-2 flex min-w-0 flex-wrap gap-1.5" aria-label="快捷指令">
      {prompts.map((prompt) => {
        const label = prompt.label
        return (
          <button
            key={prompt.id}
            type="button"
            disabled={disabled}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onSelect(prompt)}
            className={cn(
              "inline-flex h-7 max-w-full items-center gap-1.5 rounded-lg border px-2.5 text-[11.5px] font-medium transition focus-visible:ring-2 focus-visible:ring-indigo-400/45 focus-visible:outline-none",
              disabled
                ? "cursor-not-allowed border-gray-200/70 bg-gray-50/70 text-gray-400 opacity-70 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-500"
                : "border-gray-200/80 bg-white/85 text-gray-600 shadow-sm shadow-gray-950/[0.025] hover:border-indigo-200 hover:bg-indigo-50/80 hover:text-indigo-700 dark:border-white/10 dark:bg-white/[0.05] dark:text-gray-300 dark:shadow-none dark:hover:border-indigo-300/30 dark:hover:bg-indigo-400/[0.12] dark:hover:text-indigo-100"
            )}
          >
            {prompt.id === "confirm" ? (
              <CheckCircle2 className="size-3.5 shrink-0" />
            ) : prompt.id === "continue" ? (
              <Send className="size-3.5 shrink-0" />
            ) : prompt.id === "next_step" ? (
              <ClipboardList className="size-3.5 shrink-0" />
            ) : null}
            <span className="min-w-0 truncate">{label}</span>
          </button>
        )
      })}
    </div>
  )
}

export function AssistantTaskProgressBlock({
  block,
}: {
  block: Extract<AssistantContentBlock, { type: "task_progress" }>
}) {
  const steps = Array.isArray(block.steps) ? block.steps : []
  const doneCount = steps.filter((step) => step.status === "done").length
  const failed =
    steps.some((step) => step.status === "failed") || block.status === "failed"
  const running =
    steps.some((step) => step.status === "running") || block.status === "running"
  const complete =
    !failed &&
    (block.status === "completed" ||
      (steps.length > 0 && steps.every((step) => step.status === "done")))
  const progress = steps.length ? Math.round((doneCount / steps.length) * 100) : 0
  const title = block.title?.trim() || "任务进度"
  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg px-2.5 py-2",
        failed
          ? "bg-rose-50/60 text-rose-800 dark:bg-rose-950/20 dark:text-rose-100"
          : complete
            ? "bg-emerald-50/55 text-emerald-800 dark:bg-emerald-950/16 dark:text-emerald-100"
            : "bg-sky-50/55 text-sky-800 dark:bg-sky-950/16 dark:text-sky-100"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          {failed ? (
            <X className="size-3.5 shrink-0" />
          ) : running ? (
            <Loader2 className="size-3.5 shrink-0 animate-spin" />
          ) : complete ? (
            <CheckCircle2 className="size-3.5 shrink-0" />
          ) : (
            <Clock3 className="size-3.5 shrink-0" />
          )}
          <span className="truncate text-[11.5px] font-semibold">{title}</span>
        </div>
        {steps.length ? (
          <span className="shrink-0 font-mono text-[10px] opacity-70">
            {doneCount}/{steps.length}
          </span>
        ) : null}
      </div>
      {steps.length ? (
        <>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/70 dark:bg-white/10">
            <div
              className={cn(
                "h-full rounded-full transition-[width]",
                failed ? "bg-rose-500" : complete ? "bg-emerald-500" : "bg-sky-500"
              )}
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="mt-1.5 space-y-0.5">
            {steps.map((step) => (
              <div
                key={step.id || step.label}
                className="flex min-w-0 items-center gap-1.5 text-[11px] opacity-85"
              >
                {step.status === "done" ? (
                  <CheckCircle2 className="size-3 shrink-0" />
                ) : step.status === "running" ? (
                  <Loader2 className="size-3 shrink-0 animate-spin" />
                ) : step.status === "failed" ? (
                  <X className="size-3 shrink-0" />
                ) : (
                  <Clock3 className="size-3 shrink-0" />
                )}
                <span className="truncate">{step.label}</span>
              </div>
            ))}
          </div>
        </>
      ) : null}
    </div>
  )
}
