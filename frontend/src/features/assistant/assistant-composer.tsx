import React from "react"
import { AssistantQuickPromptBar } from "./assistant-activity"
import { ASSISTANT_MAX_ATTACHMENTS } from "./assistant-composer-model"
import { useCallback } from "react"
import { AlertCircle, Loader2, Paperclip, Send, Square, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { ICON_GHOST_BTN_CLS } from "@/shared/button-styles"
import { mediaPreviewSrc } from "@/shared/media"
import { TooltipWrap } from "@/shared/tooltip-wrap"
import { UnifiedMediaFrame, mediaDownloadSource } from "@/shared/unified-media-frame"
import type { AssistantComposerController } from "./use-assistant-composer"
import type { AssistantSessionController } from "./use-assistant-session"
import type { AssistantModelSelectionController } from "./use-assistant-model-selection"
import { AssistantModelReasoningPicker } from "./assistant-model-reasoning-picker"

export function AssistantComposer({
  composer,
  session,
  backendReady,
  modelSelection,
}: {
  composer: AssistantComposerController
  session: Pick<
    AssistantSessionController,
    | "pendingQuestionWaiting"
    | "completionRenderHolding"
    | "assistantRuntimeRunning"
    | "canStopAssistantRuntime"
    | "requestPending"
    | "inputLocked"
    | "handleSend"
    | "handleInterruptAssistantRuntime"
    | "handleQuickPromptSelect"
  >
  backendReady: boolean
  modelSelection: AssistantModelSelectionController
}) {
  const {
    input,
    attachments,
    attachmentError,
    inputFocused,
    setInputFocused,
    textareaRef,
    assistantInputFormRef,
    assistantRunButtonRef,
    slashMenuOpen,
    setSlashMenuOpen,
    slashActiveIndex,
    setSlashActiveIndex,
    filteredSlashCommands,
    assistantQuickPrompts,
    handlePickAttachments,
    handlePaste,
    handleInputChange,
    selectSlashCommand,
  } = composer
  const {
    pendingQuestionWaiting,
    completionRenderHolding,
    assistantRuntimeRunning,
    canStopAssistantRuntime,
    requestPending,
    inputLocked,
    handleSend,
    handleInterruptAssistantRuntime,
    handleQuickPromptSelect,
  } = session
  const assistantRunButtonLabel = assistantRuntimeRunning
    ? input.trim() && canStopAssistantRuntime
      ? "补充要求并重新执行"
      : canStopAssistantRuntime
      ? "停止当前智能体执行"
      : "正在显示最终回复"
    : requestPending
      ? "发送中"
      : "发送"

  const handleInputShellMouseDown = useCallback(
    (event: React.MouseEvent<HTMLButtonElement>) => {
      if (inputLocked) return
      event.preventDefault()
      textareaRef.current?.focus()
    },
    [inputLocked]
  )

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (slashMenuOpen && !assistantRuntimeRunning) {
        if (event.key === "Escape") {
          event.preventDefault()
          setSlashMenuOpen(false)
          return
        }
        if (filteredSlashCommands.length > 0) {
          if (event.key === "ArrowDown") {
            event.preventDefault()
            setSlashActiveIndex((current) => (current + 1) % filteredSlashCommands.length)
            return
          }
          if (event.key === "ArrowUp") {
            event.preventDefault()
            setSlashActiveIndex(
              (current) =>
                (current - 1 + filteredSlashCommands.length) %
                filteredSlashCommands.length
            )
            return
          }
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault()
            selectSlashCommand(
              filteredSlashCommands[
                Math.min(slashActiveIndex, filteredSlashCommands.length - 1)
              ]
            )
            return
          }
        }
      }
      if (event.key !== "Enter" || event.shiftKey) return
      if (event.nativeEvent.isComposing) return
      event.preventDefault()
      void handleSend()
    },
    [
      filteredSlashCommands,
      assistantRuntimeRunning,
      handleSend,
      selectSlashCommand,
      slashActiveIndex,
      slashMenuOpen,
    ]
  )

  const handleInputFormSubmit = useCallback(
    (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      if (canStopAssistantRuntime && !input.trim()) {
        void handleInterruptAssistantRuntime()
        return
      }
      void handleSend()
    },
    [canStopAssistantRuntime, handleInterruptAssistantRuntime, handleSend, input]
  )
  return (
    <div className="relative border-t border-gray-200/70 p-2.5 dark:border-white/10">
      {attachmentError ? (
        <div
          role="alert"
          aria-live="polite"
          className="mb-2 flex min-w-0 items-start gap-2 rounded-lg border border-rose-200 bg-rose-50/80 px-2.5 py-2 text-[11.5px] leading-relaxed text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/20 dark:text-rose-100"
        >
          <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
          <span className="min-w-0">{attachmentError}</span>
        </div>
      ) : null}
      {attachments.length ? (
        <div className="mb-2 flex flex-wrap gap-2">
          {attachments.map((item) => (
            <div
              key={item.id}
              className="group relative h-16 w-16 overflow-hidden rounded-lg border border-gray-200/80 bg-white/70 dark:border-white/10"
            >
              <UnifiedMediaFrame
                src={mediaPreviewSrc(item.media)}
                alt={item.name}
                title={item.name}
                className="h-full w-full rounded-none border-0"
                downloadSource={mediaDownloadSource(item.media)}
              />
              <button
                type="button"
                className="absolute top-1 right-1 grid size-5 place-items-center rounded-full bg-black/60 text-white opacity-0 transition group-hover:opacity-100"
                onClick={() => composer.removeAttachment(item.id)}
              >
                <X className="size-3" />
              </button>
            </div>
          ))}
        </div>
      ) : null}
      {attachments.length ? (
        <div className="mb-1.5 flex justify-end text-[10px] text-gray-500 dark:text-gray-400">
          {attachments.length}/{ASSISTANT_MAX_ATTACHMENTS}
        </div>
      ) : null}
      <form
        ref={assistantInputFormRef}
        className="contents"
        onSubmit={handleInputFormSubmit}
      >
        <AssistantQuickPromptBar
          prompts={assistantQuickPrompts.filter((prompt) => prompt.id !== "confirm" && prompt.id !== "continue")}
          disabled={!backendReady || inputLocked || assistantRuntimeRunning}
          onSelect={handleQuickPromptSelect}
        />
        <div
          className={cn(
            "relative mb-[5px] min-h-[96px] rounded-lg border pt-2 pr-0 pb-10 pl-3 transition-colors",
            inputFocused
              ? "border-indigo-400 bg-white/85 shadow-sm dark:border-indigo-500 dark:bg-white/[0.06]"
              : "border-gray-200/70 bg-white/70 dark:border-white/10 dark:bg-white/[0.035]"
          )}
          onFocus={() => setInputFocused(true)}
          onBlur={(event) => {
            const next = event.relatedTarget
            if (!(next instanceof Node) || !event.currentTarget.contains(next)) {
              setInputFocused(false)
            }
          }}
        >
          <button
            type="button"
            tabIndex={-1}
            aria-hidden="true"
            data-testid="assistant-input-shell-focus"
            onMouseDown={handleInputShellMouseDown}
            className="absolute inset-0 z-0 cursor-text rounded-lg border-0 bg-transparent p-0"
            disabled={inputLocked}
          />
          <textarea
            ref={textareaRef}
            role="combobox"
            value={input}
            rows={1}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder={
              pendingQuestionWaiting
                ? "可直接补充说明，或在上方选择后提交..."
                : completionRenderHolding
                  ? "正在显示最终回复..."
                  : assistantRuntimeRunning
                    ? "输入补充要求后发送，将停止当前步骤并重新执行..."
                    : "输入消息，输入 / 查看快捷指令"
            }
            aria-label="助手输入"
            aria-expanded={slashMenuOpen}
            className="relative z-10 block max-h-[50vh] w-full resize-none overflow-hidden bg-transparent pb-1 text-[13px] leading-5 text-gray-700 outline-none placeholder:text-gray-400 dark:text-gray-200"
            disabled={inputLocked}
          />

          {slashMenuOpen && !assistantRuntimeRunning && filteredSlashCommands.length ? (
            <div className="absolute right-2 bottom-11 left-2 z-20 overflow-hidden rounded-lg border border-gray-200/80 bg-white p-1 text-xs shadow-xl shadow-gray-950/10 dark:border-white/10 dark:bg-[#24242a]">
              {filteredSlashCommands.map((command, index) => {
                const active = index === slashActiveIndex
                return (
                  <button
                    key={`${command.source || "command"}-${command.id}`}
                    type="button"
                    role="option"
                    aria-selected={active}
                    className={cn(
                      "flex w-full items-start justify-between gap-3 rounded-lg px-2.5 py-2 text-left transition",
                      active
                        ? "bg-indigo-500 text-white"
                        : "text-gray-700 hover:bg-indigo-50 hover:text-indigo-700 dark:text-gray-200 dark:hover:bg-white/[0.06] dark:hover:text-white"
                    )}
                    onMouseDown={(event) => event.preventDefault()}
                    onMouseEnter={() => setSlashActiveIndex(index)}
                    onClick={() => selectSlashCommand(command)}
                  >
                    <span className="min-w-0">
                      <span className="flex min-w-0 items-center gap-1.5">
                        <span className="truncate font-medium">{command.label}</span>
                      </span>
                      {command.description ? (
                        <span
                          className={cn(
                            "mt-0.5 block truncate text-[11px]",
                            active ? "text-white/80" : "text-gray-500 dark:text-gray-400"
                          )}
                        >
                          {command.description}
                        </span>
                      ) : null}
                    </span>
                  </button>
                )
              })}
            </div>
          ) : null}

          <div className="absolute bottom-2 left-2 z-10 max-w-[calc(100%-80px)]">
            <AssistantModelReasoningPicker
              selection={modelSelection}
              disabled={!backendReady || assistantRuntimeRunning}
            />
          </div>
          <div className="absolute right-2 bottom-2 z-10 flex items-center gap-1">
            <TooltipWrap content="添加附件">
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className={cn(ICON_GHOST_BTN_CLS, "size-7 dark:hover:text-gray-100")}
                onClick={() => void handlePickAttachments()}
                disabled={inputLocked || assistantRuntimeRunning || attachments.length >= ASSISTANT_MAX_ATTACHMENTS}
              >
                <Paperclip className="size-3.5" />
              </Button>
            </TooltipWrap>
            <TooltipWrap content={assistantRunButtonLabel}>
              <Button
                ref={assistantRunButtonRef}
                type={canStopAssistantRuntime && !input.trim() ? "button" : "submit"}
                size="icon-sm"
                className="size-7 bg-gradient-to-r from-indigo-600 via-sky-600 to-emerald-500 text-white shadow-sm hover:opacity-90"
                aria-label={assistantRunButtonLabel}
                title={assistantRunButtonLabel}
                onClick={(event) => {
                  if (!canStopAssistantRuntime || input.trim()) return
                  event.preventDefault()
                  void handleInterruptAssistantRuntime()
                }}
                disabled={
                  assistantRuntimeRunning
                    ? requestPending || !canStopAssistantRuntime
                    : inputLocked || (!input.trim() && attachments.length === 0)
                }
              >
                {canStopAssistantRuntime && !input.trim() ? (
                  <Square className="size-3.5" />
                ) : assistantRuntimeRunning ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Send className="size-3.5" />
                )}
              </Button>
            </TooltipWrap>
          </div>
        </div>
      </form>
    </div>
  )
}
