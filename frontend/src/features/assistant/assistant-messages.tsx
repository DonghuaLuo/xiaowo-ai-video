import {
  getAssistantTurnContentBlocks,
  assistantContentBlockCanCollapse,
  isRenderableAssistantContentBlock,
  isVisibleAssistantChatBlock,
  normalizeVisibleAssistantChatBlocks,
} from "./assistant-message-model"
import { ChevronRight } from "lucide-react"
import { cn } from "@/lib/utils"
import { mediaPreviewSrc } from "@/shared/media"
import { UnifiedMediaFrame, mediaDownloadSource } from "@/shared/unified-media-frame"
import {
  AssistantContentBlock,
  AssistantConfirmableCandidateBlock,
  AssistantRecommendationSelect,
  AssistantTurn,
} from "./assistant-session-normalization"

import {
  UserContentBlockRenderer,
  AssistantContentBlockRenderer,
} from "./assistant-message-blocks"

export function AssistantMessageBubble({
  turn,
  block,
  expanded,
  canCollapse,
  onToggle,
  showAttachments,
  completionMetaText,
  recommendationsDisabled,
  candidateDisabled,
  onRecommendationSelect,
  onCandidateConfirm,
  onCandidateCancel,
}: {
  turn: AssistantTurn
  block: AssistantContentBlock | null
  expanded: boolean
  canCollapse: boolean
  onToggle: () => void
  showAttachments: boolean
  completionMetaText?: string
  recommendationsDisabled: boolean
  candidateDisabled: boolean
  onRecommendationSelect: AssistantRecommendationSelect
  onCandidateConfirm: (block: AssistantConfirmableCandidateBlock) => void
  onCandidateCancel: (block: AssistantConfirmableCandidateBlock) => void
}) {
  const isUser = turn.type === "user"
  const isSystem = turn.type === "system"
  const isAssistant = !isUser && !isSystem
  const label = isUser ? "你" : isSystem ? "系统" : "智能体"
  const bubbleClassName = cn(
    "min-w-0 rounded-lg border px-2.5 py-1.5 text-[12.5px] leading-[1.55] transition-colors",
    isUser
      ? "ml-auto w-fit max-w-[85%] border-indigo-200 bg-indigo-50/75 text-gray-800 dark:border-white/[0.12] dark:bg-[#2f3036] dark:text-gray-100"
      : isSystem
        ? "mx-1 border-amber-200 bg-amber-50/75 text-amber-800 dark:border-amber-500/25 dark:bg-amber-500/[0.12] dark:text-amber-50"
        : "w-full border-gray-200/80 bg-white/70 text-gray-700 shadow-sm shadow-gray-950/[0.03] dark:border-white/[0.12] dark:bg-[#26272d] dark:text-gray-100 dark:shadow-none"
  )
  const titleClassName = cn(
    isAssistant
      ? "mb-2 -mx-2.5 -mt-1.5 flex w-[calc(100%+1.25rem)] items-center justify-between gap-2 rounded-t-lg px-3 py-2 text-left transition-colors"
      : "mb-2 -mx-1 flex w-[calc(100%+0.5rem)] items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-[10px] font-semibold text-gray-400",
    isAssistant
      ? canCollapse
        ? "cursor-pointer hover:bg-gray-50/80 focus-visible:ring-2 focus-visible:ring-indigo-400/50 focus-visible:outline-none dark:hover:bg-white/[0.05]"
        : ""
      : canCollapse
        ? "cursor-pointer bg-gray-50/80 text-gray-500 shadow-sm shadow-gray-950/[0.025] transition-colors hover:bg-indigo-50/80 hover:text-indigo-700 focus-visible:ring-2 focus-visible:ring-indigo-400/50 focus-visible:outline-none dark:bg-white/[0.055] dark:text-gray-300 dark:hover:bg-indigo-950/20 dark:hover:text-indigo-100"
        : ""
  )
  const titleContent = isAssistant ? (
    <>
      <span className="flex min-w-0 items-center gap-2">
        <span
          aria-hidden="true"
          className="relative flex size-2 shrink-0 rounded-full bg-emerald-400"
        />
        <span className="min-w-0 truncate text-[12px] text-gray-700 dark:text-gray-100">
          {label}
        </span>
      </span>
      <span className="flex min-w-0 items-center justify-end gap-2">
        {completionMetaText ? (
          <span className="min-w-0 truncate text-[11px] font-normal text-gray-400 dark:text-gray-500">
            {completionMetaText}
          </span>
        ) : null}
        {canCollapse ? (
          <ChevronRight
            className={cn(
              "size-3 shrink-0 text-gray-400 transition-transform",
              expanded && "rotate-90"
            )}
          />
        ) : null}
      </span>
    </>
  ) : (
    <>
      <span className="flex min-w-0 items-center gap-1.5">
        <span
          aria-hidden="true"
          className={cn(
            "size-1.5 shrink-0 rounded-full",
            isUser ? "bg-indigo-400" : "bg-amber-400"
          )}
        />
        <span className="truncate">{label}</span>
      </span>
      {canCollapse ? (
        <span
          aria-hidden="true"
          className="pointer-events-none grid size-5 shrink-0 place-items-center rounded-lg bg-white/90 text-gray-500 shadow-sm dark:bg-[#343844] dark:text-gray-200"
        >
          <ChevronRight
            className={cn("size-3.5 transition-transform", expanded && "rotate-90")}
          />
        </span>
      ) : null}
    </>
  )

  return (
    <div className={bubbleClassName}>
      {!isUser ? (
        canCollapse ? (
          <button
            type="button"
            className={titleClassName}
            aria-expanded={expanded}
            aria-label={expanded ? "折叠消息" : "展开消息"}
            onClick={onToggle}
          >
            {titleContent}
          </button>
        ) : (
          <div className={titleClassName}>{titleContent}</div>
        )
      ) : null}
      {showAttachments && turn.attachments?.length ? (
        <div className="mb-2 flex flex-wrap gap-2">
          {turn.attachments.map((item) => (
            <UnifiedMediaFrame
              key={item.id}
              src={mediaPreviewSrc(item.media)}
              alt={item.name}
              title={item.name}
              className="h-14 w-14"
              downloadSource={mediaDownloadSource(item.media)}
            />
          ))}
        </div>
      ) : null}
      {block ? (
        isUser ? (
          <UserContentBlockRenderer block={block} />
        ) : (
          <AssistantContentBlockRenderer
            block={block}
            expanded={expanded}
            recommendationsDisabled={recommendationsDisabled}
            candidateDisabled={candidateDisabled}
            onRecommendationSelect={onRecommendationSelect}
            onCandidateConfirm={onCandidateConfirm}
            onCandidateCancel={onCandidateCancel}
          />
        )
      ) : null}
    </div>
  )
}

export function AssistantChatMessage({
  turn,
  expanded,
  onToggle,
  completionMetaText,
  recommendationsDisabled,
  candidateDisabled,
  onRecommendationSelect,
  onCandidateConfirm,
  onCandidateCancel,
}: {
  turn: AssistantTurn
  expanded: boolean
  onToggle: () => void
  completionMetaText?: string
  recommendationsDisabled: boolean
  candidateDisabled: boolean
  onRecommendationSelect: AssistantRecommendationSelect
  onCandidateConfirm: (block: AssistantConfirmableCandidateBlock) => void
  onCandidateCancel: (block: AssistantConfirmableCandidateBlock) => void
}) {
  const rawBlocks = getAssistantTurnContentBlocks(turn)
  const progressSummary = rawBlocks.find(
    (block) => block.type === "recommendations" && block.origin === "progress_query"
  )
  const progressSummaryText = progressSummary?.type === "recommendations"
    ? progressSummary.summary?.trim()
    : undefined
  const contentBlocks = normalizeVisibleAssistantChatBlocks(
    rawBlocks.filter(
      (block) =>
        isVisibleAssistantChatBlock(block) &&
        !(block.type === "text" && progressSummaryText && block.text.trim() === progressSummaryText)
    )
  )
  const visibleBlocks =
    contentBlocks.length || turn.attachments?.length
      ? contentBlocks
      : ([{ type: "text", text: turn.text } satisfies AssistantContentBlock].filter(
          isRenderableAssistantContentBlock
        ) as AssistantContentBlock[])

  if (!visibleBlocks.length && !turn.attachments?.length) return null

  return (
    <div className="space-y-1.5">
      {(visibleBlocks.length ? visibleBlocks : [null]).map((block, index) => (
        <AssistantMessageBubble
          key={block ? `${block.type}-${index}` : `attachments-${index}`}
          turn={turn}
          block={block}
          expanded={expanded}
          canCollapse={block ? assistantContentBlockCanCollapse(block) : false}
          onToggle={onToggle}
          showAttachments={index === 0}
          completionMetaText={index === 0 ? completionMetaText : undefined}
          recommendationsDisabled={recommendationsDisabled}
          candidateDisabled={candidateDisabled}
          onRecommendationSelect={onRecommendationSelect}
          onCandidateConfirm={onCandidateConfirm}
          onCandidateCancel={onCandidateCancel}
        />
      ))}
    </div>
  )
}
