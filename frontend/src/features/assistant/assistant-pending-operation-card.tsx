import type { AssistantPendingInteraction } from "./assistant-session-normalization"

export function AssistantPendingOperationCard({
  interaction,
  disabled,
  onDecision,
}: {
  interaction: AssistantPendingInteraction
  disabled: boolean
  onDecision: (decision: "confirm" | "cancel") => void
}) {
  const waiting = interaction.active && !["committing", "commit_unknown"].includes(interaction.operationStatus)
  const buttonOnly = interaction.confirmationMode === "button_only"
  const statusLabel = !interaction.active ? "已失效"
    : interaction.operationStatus === "commit_unknown" ? "写入状态待核实"
    : interaction.operationStatus === "committing" ? "正在写入"
    : "等待确认"
  return (
    <section className="mx-3 mb-2 rounded-lg border border-amber-300/60 bg-amber-50/70 p-3 text-xs text-gray-700 dark:border-amber-300/20 dark:bg-amber-400/[0.07] dark:text-gray-200"
      aria-label="待确认操作">
      <div className="flex items-center justify-between gap-2">
        <strong className="text-gray-900 dark:text-gray-100">{interaction.title}</strong>
        <span className="shrink-0 text-[10px] text-amber-700 dark:text-amber-200">
          {statusLabel}
        </span>
      </div>
      {buttonOnly && interaction.description ? (
        <p className="mt-2 leading-relaxed">{interaction.description}</p>
      ) : null}
      {interaction.message && interaction.message !== interaction.description ? (
        <p className="mt-1.5 leading-relaxed">{interaction.message}</p>
      ) : null}
      {!interaction.active && interaction.staleReason ? <p className="mt-2">{interaction.staleReason}</p> : null}
      {waiting ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {interaction.canConfirm ? (
            <button type="button" disabled={disabled} onClick={() => onDecision("confirm")}
              className="rounded-md bg-indigo-600 px-3 py-1.5 font-medium text-white disabled:cursor-not-allowed disabled:opacity-50">
              {buttonOnly ? interaction.title : "确认"}
            </button>
          ) : null}
          {interaction.canCancel ? (
            <button type="button" disabled={disabled} onClick={() => onDecision("cancel")}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-gray-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-white/20 dark:text-gray-200">
              取消这次操作
            </button>
          ) : null}
          {!buttonOnly ? <span className="self-center text-[11px] text-gray-500 dark:text-gray-400">如需修改，直接在下方说明。</span> : null}
        </div>
      ) : null}
    </section>
  )
}
