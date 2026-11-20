import {
  latestExpandableAssistantTurnIds,
  pruneAssistantMessageIdSet,
  buildAssistantTurnCompletionMetaById,
  isAssistantScrollNearBottom,
} from "./assistant-message-model"
import { AssistantChatMessage } from "./assistant-messages"
import { pendingDecisionSendOptions } from "./assistant-pending-decision"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { ArrowDown, Bot } from "lucide-react"
import { Button } from "@/components/ui/button"
import type {
  AssistantTurn,
  AssistantRecommendationSelect,
  AssistantConfirmableCandidateBlock,
  AssistantPendingInteraction,
} from "./assistant-session-normalization"
import type { AssistantSendOptions } from "./use-assistant-composer"
export function AssistantTimeline({
  allTurns,
  currentSessionId,
  pendingInteractions,
  sessionsLoading,
  backendReady,
  inputLocked,
  handleSend,
  handleRecommendationSelect,
  resetKey,
}: {
  allTurns: AssistantTurn[]
  currentSessionId: string | null
  pendingInteractions: AssistantPendingInteraction[]
  sessionsLoading: boolean
  backendReady: boolean
  inputLocked: boolean
  handleSend: (message?: string, options?: AssistantSendOptions) => Promise<void>
  handleRecommendationSelect: AssistantRecommendationSelect
  resetKey: number
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const [autoScrollEnabled, setAutoScrollEnabled] = useState(true)

  const [expandedMessageIds, setExpandedMessageIds] = useState<Set<string>>(
    () => new Set()
  )

  const [collapsedMessageIds, setCollapsedMessageIds] = useState<Set<string>>(
    () => new Set()
  )

  const assistantTurnCompletionMetaById = useMemo(
    () => buildAssistantTurnCompletionMetaById(allTurns),
    [allTurns]
  )

  const autoExpandedMessageIds = useMemo(
    () => latestExpandableAssistantTurnIds(allTurns),
    [allTurns]
  )
  const latestTurnBySession = useMemo(() => new Map(allTurns.map((turn) =>
    [turn.sourceSessionId ?? currentSessionId, turn.uuid])), [allTurns, currentSessionId])

  useEffect(() => {
    const validIds = new Set(allTurns.map((turn) => turn.uuid))
    setExpandedMessageIds((current) => pruneAssistantMessageIdSet(current, validIds))
    setCollapsedMessageIds((current) => pruneAssistantMessageIdSet(current, validIds))
  }, [allTurns])

  const scrollToAssistantBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const element = scrollRef.current
    if (!element) return
    const bottom = element.scrollHeight - element.clientHeight
    if (bottom - element.scrollTop > 1) {
      element.scrollTo({ top: bottom, behavior })
    }
    setAutoScrollEnabled(true)
  }, [])

  const handleAssistantScroll = useCallback(() => {
    const element = scrollRef.current
    if (!element) return
    setAutoScrollEnabled(isAssistantScrollNearBottom(element))
  }, [])

  const showJumpToBottom = !autoScrollEnabled && allTurns.length > 0

  useEffect(() => {
    if (!autoScrollEnabled) return
    const frame = window.requestAnimationFrame(() => {
      scrollToAssistantBottom("auto")
    })
    const timers = [
      window.setTimeout(() => scrollToAssistantBottom("auto"), 80),
      window.setTimeout(() => scrollToAssistantBottom("auto"), 180),
    ]
    return () => {
      window.cancelAnimationFrame(frame)
      timers.forEach((timer) => window.clearTimeout(timer))
    }
  }, [
    allTurns,
    autoScrollEnabled,
    scrollToAssistantBottom,
  ])

  const toggleMessage = useCallback(
    (id: string, currentlyExpanded: boolean, autoExpanded: boolean) => {
      if (autoExpanded) {
        setCollapsedMessageIds((current) => {
          const next = new Set(current)
          if (currentlyExpanded) next.add(id)
          else next.delete(id)
          return next
        })
        if (currentlyExpanded) {
          setExpandedMessageIds((current) => {
            if (!current.has(id)) return current
            const next = new Set(current)
            next.delete(id)
            return next
          })
        }
        return
      }

      setExpandedMessageIds((current) => {
        const next = new Set(current)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
      })
    },
    []
  )
  useEffect(() => {
    setAutoScrollEnabled(true)
    setExpandedMessageIds(new Set())
    setCollapsedMessageIds(new Set())
  }, [resetKey])

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={scrollRef}
        onScroll={handleAssistantScroll}
        data-testid="assistant-messages-scroll"
        className="h-full min-w-0 overflow-x-hidden overflow-y-auto px-3 py-2.5"
      >
        {allTurns.length === 0 && !sessionsLoading ? (
          <div className="flex h-full min-h-52 flex-col items-center justify-center text-center">
            <div className="mb-3 grid size-12 place-items-center rounded-lg border border-indigo-100 bg-indigo-50/75 shadow-sm shadow-indigo-950/[0.04] dark:border-indigo-900/50 dark:bg-indigo-950/20">
              <Bot className="size-5 text-indigo-500 dark:text-indigo-300" />
            </div>
            <p className="text-[14px] font-semibold text-gray-800 dark:text-gray-100">
              直接输入你的问题
            </p>
            <p className="mt-1 text-[11.5px] text-gray-500 dark:text-gray-400">
              输入 / 查看可用技能，或先检查当前项目进度。
            </p>
            <Button
              type="button"
              size="sm"
              className="mt-3 h-7 bg-gradient-to-r from-indigo-600 via-sky-600 to-emerald-500 px-3 text-[12px] text-white shadow-sm hover:opacity-90"
              disabled={!backendReady || inputLocked}
              onClick={() =>
                void handleSend("查看当前进度", {
                  preferredTaskType: "project_status",
                  quickPromptId: "next_step",
                  controlOnly: true,
                  displayMessage: "查看当前进度",
                })
              }
            >
              检查当前阶段
            </Button>
          </div>
        ) : (
          <div className="space-y-2.5">
            {allTurns.map((turn) => {
              const sourceSessionId = turn.sourceSessionId ?? currentSessionId
              const sourceSelected = sourceSessionId === currentSessionId
              const latestForSource = latestTurnBySession.get(sourceSessionId) === turn.uuid
              const candidateInteraction = (block: AssistantConfirmableCandidateBlock) =>
                pendingInteractions.find((item) => item.sessionId === currentSessionId &&
                  item.candidateId === block.candidateId &&
                  ((block.type === "episode_boundary_candidate" && item.kind === "episode_boundary") ||
                   (block.type === "asset_range_candidate" && item.kind === "asset_range")))
              const displayTurn: AssistantTurn = {
                ...turn,
                content: turn.content.map((block) => {
                  if (block.type === "text" && block.actionFooter?.label === "需要确认") {
                    return { ...block, actionFooter: undefined }
                  }
                  if ((block.type !== "episode_boundary_candidate" && block.type !== "asset_range_candidate") ||
                      block.status !== "pending_confirmation") return block
                  const interaction = candidateInteraction(block)
                  if (!interaction) return { ...block, status: "stale" as const }
                  return {
                    ...block,
                    runId: interaction.runId || block.runId,
                    candidateDigest: interaction.candidateDigest || block.candidateDigest,
                    candidateVersion: interaction.candidateVersion || block.candidateVersion,
                    status: !interaction.active ? "stale" as const
                      : interaction.operationStatus === "committing" ? "committing" as const
                      : interaction.operationStatus === "commit_unknown" ? "commit_unknown" as const
                      : block.status,
                  }
                }),
              }
              const autoExpanded = autoExpandedMessageIds.has(turn.uuid)
              const expanded =
                expandedMessageIds.has(turn.uuid) ||
                (autoExpanded && !collapsedMessageIds.has(turn.uuid))

              return (
                <AssistantChatMessage
                  key={turn.uuid}
                  turn={displayTurn}
                  expanded={expanded}
                  onToggle={() => toggleMessage(turn.uuid, expanded, autoExpanded)}
                  completionMetaText={assistantTurnCompletionMetaById.get(turn.uuid)}
                  recommendationsDisabled={!backendReady || (sourceSelected && inputLocked) || !latestForSource}
                  candidateDisabled={inputLocked || !backendReady}
                  onRecommendationSelect={(item) => handleRecommendationSelect({
                    ...item, sourceSessionId: sourceSessionId ?? undefined,
                  })}
                  onCandidateConfirm={(block: AssistantConfirmableCandidateBlock) => {
                    const interaction = candidateInteraction(block)
                    if (inputLocked || !backendReady || !interaction?.active || !interaction.canConfirm) return
                    void handleSend(interaction.title, pendingDecisionSendOptions(interaction, "confirm"))
                  }}
                  onCandidateCancel={(block: AssistantConfirmableCandidateBlock) => {
                    const interaction = candidateInteraction(block)
                    if (inputLocked || !backendReady || !interaction?.active || !interaction.canCancel) return
                    void handleSend("取消这版候选", pendingDecisionSendOptions(interaction, "cancel"))
                  }}
                />
              )
            })}
          </div>
        )}
      </div>
      {showJumpToBottom ? (
        <button
          type="button"
          data-testid="assistant-scroll-bottom"
          className="absolute right-4 bottom-4 flex items-center gap-1.5 rounded-lg border border-gray-200/80 bg-white/90 px-3 py-1.5 text-[11.5px] text-gray-600 shadow-lg shadow-gray-950/10 transition hover:border-indigo-200 hover:text-indigo-600 dark:border-white/10 dark:bg-[#24242a]/95 dark:text-gray-300 dark:hover:text-indigo-200"
          onClick={() => scrollToAssistantBottom("smooth")}
          aria-label="回到底部"
          title="回到底部"
        >
          <ArrowDown className="size-3.5" />
          <span>回到底部</span>
        </button>
      ) : null}
    </div>
  )
}
