import { isWorkflowVideoTaskType } from "./workflow-video-task-types"
import type { KeyboardEvent, WheelEvent } from "react"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { VideoMentionTextarea } from "./video-mention-textarea"
import type { PromptBindings, PromptMentionOption } from "./video-prompt-mentions"
import {
  DirectorPlanStructuredEditor,
  type DirectorPlanShotDraft,
  type DirectorPlanSoundSourceOption,
  type DirectorPlanSpeakerRosterDraft,
} from "./director-plan-editor"

const WORKFLOW_MAX_EDITOR_SURFACE_CLASS =
  "rounded-lg border border-gray-200/80 bg-white/70 dark:border-white/[0.07] dark:bg-[#18181b]"

type WorkflowNodeData = {
  [key: string]: any
  eyebrow?: string
  prompt?: unknown
  sourceFactText?: unknown
}

type AssetMentionAnchor = { left: number; top: number }

const ASSET_MENTION_POPOVER_WIDTH = 288

function clampNumber(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), Math.max(min, max))
}

function textareaCaretMentionAnchor(
  element: HTMLTextAreaElement,
  caret: number = element.selectionStart ?? element.value.length
): AssetMentionAnchor {
  if (typeof document === "undefined" || typeof window === "undefined") {
    return { left: 0, top: 0 }
  }
  const style = window.getComputedStyle(element)
  const mirror = document.createElement("div")
  const mirroredProperties = [
    "box-sizing", "font-family", "font-size", "font-weight", "font-style",
    "letter-spacing", "text-transform", "word-spacing", "line-height",
    "padding-top", "padding-right", "padding-bottom", "padding-left",
    "border-top-width", "border-right-width", "border-bottom-width",
    "border-left-width", "word-break",
  ]
  mirroredProperties.forEach((property) => mirror.style.setProperty(property, style.getPropertyValue(property)))
  mirror.style.position = "absolute"
  mirror.style.visibility = "hidden"
  mirror.style.pointerEvents = "none"
  mirror.style.whiteSpace = "pre-wrap"
  mirror.style.overflowWrap = "break-word"
  mirror.style.overflow = "hidden"
  mirror.style.width = `${element.clientWidth}px`
  mirror.textContent = element.value.slice(0, Math.min(Math.max(0, caret), element.value.length))
  const marker = document.createElement("span")
  marker.textContent = "\u200b"
  mirror.appendChild(marker)
  document.body.appendChild(mirror)
  const mirrorRect = mirror.getBoundingClientRect()
  const markerRect = marker.getBoundingClientRect()
  const elementRect = element.getBoundingClientRect()
  const lineHeight = Number.parseFloat(style.lineHeight) || 18
  const popoverWidth = Math.min(ASSET_MENTION_POPOVER_WIDTH, Math.max(160, element.clientWidth - 8))
  const caretLeft = clampNumber(markerRect.left - mirrorRect.left - element.scrollLeft, 0, element.clientWidth - popoverWidth)
  const caretTop = clampNumber(markerRect.top - mirrorRect.top - element.scrollTop + lineHeight + 6, 6, Math.max(6, element.clientHeight - 2))
  const left = clampNumber(elementRect.left + caretLeft, 8, Math.max(8, window.innerWidth - popoverWidth - 8))
  const top = clampNumber(elementRect.top + caretTop, 8, Math.max(8, window.innerHeight - 184))
  document.body.removeChild(mirror)
  return { left, top }
}

function stopCardWheel(event: WheelEvent<HTMLElement>) {
  const target = event.target
  if (target instanceof Element && target.closest("[data-media-lightbox='true']")) return
  event.stopPropagation()
  event.nativeEvent.stopImmediatePropagation?.()
}

function compactReadableValue(value: unknown) {
  if (value == null) return ""
  if (typeof value === "string") return value.trim()
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  return ""
}

function isDirectorBoardNodeType(value?: string | null) {
  return value === "director.board"
}


function storyboardSourceFactTextForNode(data: WorkflowNodeData) {
  return compactReadableValue(data.sourceFactText)
}

function compactWorkflowTextareaClassName(className?: string) {
  return cn(
    "nowheel block w-full min-h-[92px] max-h-[min(36vh,280px)] resize-none overflow-y-auto rounded-none border-0 bg-transparent px-0 py-0 text-[13px] leading-relaxed text-gray-900 shadow-none outline-none caret-gray-900 placeholder:text-gray-500 focus:border-transparent focus:ring-0 focus-visible:border-transparent focus-visible:ring-0 focus-visible:ring-offset-0 dark:text-white/90 dark:caret-white dark:placeholder:text-white/40",
    className
  )
}

function fixedCompactWorkflowTextareaClassName(className?: string) {
  return cn(
    "nowheel block w-full field-sizing-fixed resize-none overflow-y-auto rounded-none border-0 bg-transparent px-0 py-0 text-[13px] leading-relaxed text-gray-900 shadow-none outline-none caret-gray-900 placeholder:text-gray-500 focus:border-transparent focus:ring-0 focus-visible:border-transparent focus-visible:ring-0 focus-visible:ring-offset-0 dark:text-white/90 dark:caret-white dark:placeholder:text-white/40",
    className
  )
}

function fixedWorkflowTextareaHeightStyle(height: number) {
  return { height, minHeight: height, maxHeight: height }
}

function clampWorkflowTextareaHeight(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.round(value)))
}

function storyboardScriptEditorTextareaLayout(maxHeight?: number, expanded = false) {
  const leftChromeHeight = 36
  const rightChromeHeight = 24
  const minSourceFactHeight = 80
  const maxEditorHeight = expanded ? 560 : 360
  const minEditorHeight = leftChromeHeight + minSourceFactHeight
  const editorHeight = typeof maxHeight === "number" ? clampWorkflowTextareaHeight(maxHeight, minEditorHeight, maxEditorHeight) : undefined
  const actualEditorHeight = editorHeight ?? 240
  return {
    editorHeight: actualEditorHeight,
    sourceFactHeight: actualEditorHeight - leftChromeHeight,
    scriptHeight: clampWorkflowTextareaHeight(actualEditorHeight - rightChromeHeight, 100, maxEditorHeight - rightChromeHeight),
  }
}

function workflowTaskEditorPlaceholder(data: WorkflowNodeData) {
  if (data.eyebrow === "video.character_replace") return "替换说明可留空。可写图1替换哪个角色、哪些角色保留，以及需要保留的细节；图片编号见下方素材。"
  if (data.eyebrow === "source.text") return "粘贴或编辑分集原文..."
  if (data.eyebrow === "prompt.storyboard") return "填写影视化剧本，可包含剧情、对白、自述、心理活动、群众声音、角色动作和场景要求，可用 @ 引用资产..."
  if (isDirectorBoardNodeType(data.eyebrow)) return "填写或编辑分镜脚本..."
  if (isWorkflowVideoTaskType(data.eyebrow)) return "编辑视频提示词；提交时自动适配模型标识并补充画面约束。"
  return "输入内容..."
}
function InlinePromptEditor({
  data,
  draft,
  sourceFactDraft,
  directorShotDrafts,
  directorSpeakerRoster,
  directorSoundSourceOptions,
  onSourceFactDraftChange,
  onDirectorShotDraftsChange,
  onDirectorSpeakerRosterChange,
  onDirectorPendingChange,
  onDraftChange,
  onMentionTrigger,
  promptMaxHeight,
  maximized = false,
  readOnly = false,
  mentionOptions = [],
  promptBindings = {},
  onMentionKeyDown,
  onHistoryAction,
}: {
  data: WorkflowNodeData
  draft: string
  sourceFactDraft?: string
  directorShotDrafts?: DirectorPlanShotDraft[]
  directorSpeakerRoster?: DirectorPlanSpeakerRosterDraft
  directorSoundSourceOptions?: DirectorPlanSoundSourceOption[]
  onSourceFactDraftChange?: (value: string) => void
  onDirectorShotDraftsChange?: (value: DirectorPlanShotDraft[]) => void
  onDirectorSpeakerRosterChange?: (value: DirectorPlanSpeakerRosterDraft) => void
  onDirectorPendingChange?: (pending: boolean) => void
  onDraftChange: (
    value: string,
    caret?: number,
    anchor?: AssetMentionAnchor
  ) => void
  onMentionTrigger?: (
    value: string,
    caret?: number,
    anchor?: AssetMentionAnchor
  ) => void
  promptMaxHeight?: number
  maximized?: boolean
  readOnly?: boolean
  mentionOptions?: PromptMentionOption[]
  promptBindings?: PromptBindings
  onMentionKeyDown?: (event: KeyboardEvent<HTMLTextAreaElement>) => void
  onHistoryAction?: (direction: "undo" | "redo") => void
}) {
  const isVideoPrompt = isWorkflowVideoTaskType(data.eyebrow)
  const isStoryboardPrompt = data.eyebrow === "prompt.storyboard"
  const isDirectorBoard = isDirectorBoardNodeType(data.eyebrow)
  const editable = isStoryboardPrompt || isDirectorBoard || isVideoPrompt
  const sourceFactText =
    sourceFactDraft ?? storyboardSourceFactTextForNode(data)
  const promptTextareaStyle = promptMaxHeight
    ? isVideoPrompt || isDirectorBoard
      ? maximized
        ? fixedWorkflowTextareaHeightStyle(promptMaxHeight)
        : { maxHeight: promptMaxHeight }
      : { maxHeight: promptMaxHeight }
    : undefined
  const storyboardTextareaLayout = storyboardScriptEditorTextareaLayout(
    promptMaxHeight,
    maximized
  )
  const storyboardEditorStyle = !maximized && storyboardTextareaLayout.editorHeight
    ? { height: storyboardTextareaLayout.editorHeight }
    : undefined

  if (!editable) return null

  if (isStoryboardPrompt) {
    return (
      <div
        className={cn(
          "nodrag nopan nowheel grid min-h-0 items-stretch gap-3 overflow-hidden lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]",
          maximized && "h-full"
        )}
        style={storyboardEditorStyle}
      >
        <div
          className={cn(
            "flex h-full min-h-0 min-w-0 flex-col overflow-hidden",
            maximized && `${WORKFLOW_MAX_EDITOR_SURFACE_CLASS} p-3`
          )}
        >
          <div className="mb-2 text-[11px] font-semibold text-gray-500 dark:text-white/50">
            原文事实
          </div>
          <Textarea
            value={sourceFactText}
            onChange={(event) => onSourceFactDraftChange?.(event.target.value)}
            onPointerDown={(event) => event.stopPropagation()}
            onWheel={stopCardWheel}
            onWheelCapture={stopCardWheel}
            placeholder="这里保存从原文拆分出的事实内容"
            aria-label="原文事实"
            className={fixedCompactWorkflowTextareaClassName(
              cn(
                maximized && "min-h-0 flex-1",
                maximized && "dark:!bg-transparent"
              )
            )}
            style={
              maximized
                ? undefined
                : fixedWorkflowTextareaHeightStyle(
                    storyboardTextareaLayout.sourceFactHeight
                  )
            }
            spellCheck={false}
          />
        </div>
        <div
          className={cn(
            "flex min-h-0 min-w-0 flex-col overflow-hidden",
            maximized
              ? `${WORKFLOW_MAX_EDITOR_SURFACE_CLASS} p-3`
              : "border-t border-gray-200 pt-3 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-3 dark:border-white/[0.08]"
          )}
        >
          <div className="mb-2 text-[11px] font-semibold text-gray-500 dark:text-white/50">
            影视化剧本
          </div>
          <Textarea
            value={draft}
            onChange={(event) => {
              const caret =
                event.currentTarget.selectionStart ??
                event.currentTarget.value.length
              onDraftChange(
                event.target.value,
                caret,
                textareaCaretMentionAnchor(event.currentTarget, caret)
              )
            }}
            onKeyUp={(event) => {
              if (event.key === "@" || event.key === "＠") {
                const caret =
                  event.currentTarget.selectionStart ??
                  event.currentTarget.value.length
                onMentionTrigger?.(
                  event.currentTarget.value,
                  caret,
                  textareaCaretMentionAnchor(event.currentTarget, caret)
                )
              }
            }}
            onPointerDown={(event) => event.stopPropagation()}
            onWheel={stopCardWheel}
            onWheelCapture={stopCardWheel}
            placeholder={workflowTaskEditorPlaceholder(data)}
            aria-label="影视化剧本"
            className={fixedCompactWorkflowTextareaClassName(
              cn("min-h-0", maximized && "flex-1", maximized && "dark:!bg-transparent")
            )}
            style={
              maximized
                ? undefined
                : fixedWorkflowTextareaHeightStyle(
                    storyboardTextareaLayout.scriptHeight
                  )
            }
            spellCheck={false}
          />
        </div>
      </div>
    )
  }

  if (isDirectorBoard) {
    return (
      <DirectorPlanStructuredEditor
        shots={directorShotDrafts ?? []}
        speakerRoster={directorSpeakerRoster ?? []}
        onChange={(nextShots) => onDirectorShotDraftsChange?.(nextShots)}
        onSpeakerRosterChange={(nextSpeakerRoster) =>
          onDirectorSpeakerRosterChange?.(nextSpeakerRoster)
        }
        onPendingChange={onDirectorPendingChange}
        soundSourceOptions={directorSoundSourceOptions}
        maxHeight={promptMaxHeight}
        maximized={maximized}
        readOnly={readOnly}
        projectId={data.projectId}
        episodeId={data.episodeId}
        nodeId={data.nodeId}
      />
    )
  }

  return (
    <div
      className={cn(
        "nodrag nopan nowheel",
        maximized && "flex h-full min-h-0 flex-col"
      )}
    >
      <VideoMentionTextarea
        onHistoryAction={onHistoryAction}
        mentionOptions={mentionOptions}
        promptBindings={promptBindings}
        onKeyDown={onMentionKeyDown}
        value={draft}
        readOnly={readOnly}
        onChange={(event) => {
          if (readOnly) return
          const caret =
            event.currentTarget.selectionStart ??
            event.currentTarget.value.length
          onDraftChange(
            event.target.value,
            caret,
            textareaCaretMentionAnchor(event.currentTarget, caret)
          )
        }}
        onKeyUp={(event) => {
          if (readOnly) return
          if (event.key === "@" || event.key === "＠") {
            const caret =
              event.currentTarget.selectionStart ??
              event.currentTarget.value.length
            onMentionTrigger?.(
              event.currentTarget.value,
              caret,
              textareaCaretMentionAnchor(event.currentTarget, caret)
            )
          }
        }}
        onPointerDown={(event) => event.stopPropagation()}
        onWheel={stopCardWheel}
        onWheelCapture={stopCardWheel}
        placeholder={workflowTaskEditorPlaceholder(data)}
        aria-label={
          isVideoPrompt
            ? data.eyebrow === "video.character_replace" ? "替换说明（可选）" : "视频提示词"
            : isDirectorBoard
              ? "分镜脚本"
              : "剧本内容"
        }
        className={compactWorkflowTextareaClassName(
          maximized
            ? "h-full min-h-0 max-h-none flex-1 field-sizing-fixed dark:!bg-transparent"
            : undefined
        )}
        style={promptTextareaStyle}
        spellCheck={false}
      />
    </div>
  )
}



export { InlinePromptEditor }
