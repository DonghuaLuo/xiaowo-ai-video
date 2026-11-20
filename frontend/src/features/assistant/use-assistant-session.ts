import { useAssistantCompletion } from "./use-assistant-completion"
import {
  upsertAssistantReturnedTasks,
  markWorkspaceAgentTurnTaskFinishedFromAssistantSession,
} from "./assistant-task-model"
import {
  parseAssistantTimestampMs,
  formatAssistantDuration,
  latestUserTurnTimestampMs,
} from "./assistant-message-model"

import {
  readLastAssistantSessionId,
  writeLastAssistantSessionId,
  clearLastAssistantSessionId,
} from "./assistant-session-model"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { acceptsAssistantSessionVersion } from "./assistant-session-normalization"
import { toast } from "sonner"
import { type AgentTargetContext } from "@/backend"
import { createLocalId } from "@/shared/media"
import { isBackendFailure } from "@/shared/backend-result"
import { useAgentSessionEvents } from "./use-agent-session-events"
import {
  AssistantBackendSuccess,
  AssistantClientAction,
  AssistantLiveActivityItem,
  AssistantMessage,
  AssistantPendingQuestion,
  type AssistantPendingInteraction,
  AssistantQuickPrompt,
  AssistantRecommendationItem,
  AssistantSessionDetail,
  AssistantSessionSnapshot,
  AssistantSessionSummary,
  AssistantTurn,
  assistantMessageToTurn,
  assistantLiveActivityFromDraftTurn,
  composeAssistantTurns,
  findLatestOptimisticAssistantUserTurn,
  isAssistantControlOnlyQuickPromptId,
  isAssistantFinishedSessionStatus,
  isAssistantSessionRunning,
  mergeAssistantLiveActivityItems,
  normalizeAssistantDraftTurn,
  normalizeAssistantLiveActivity,
  normalizeAssistantSessionDetail,
  normalizeAssistantSessionSummaries,
  normalizeAssistantSnapshotPendingQuestion,
  normalizeAssistantSnapshotTurns,
  shouldPreserveLocalUserTurn,
} from "./assistant-session-normalization"
import type { BackendCaller } from "@/backend"
import type { AssistantConversationScope } from "./assistant-session-normalization"
import type { AssistantComposerController } from "./use-assistant-composer"
import type { WorkspaceSection } from "@/navigation"
import type { CanvasAgentTaskRequest } from "./assistant-task-request"
import { canvasAgentRequestForTarget } from "./assistant-task-request"
import { isActiveCanvasTask, resolveCanvasSessionSelection } from "./assistant-canvas-task-model"
import { useAssistantCanvasTimeline } from "./use-assistant-canvas-timeline"
export type AssistantSessionContext = {
  projectId: string
  episodeId: string
  assistantScope: AssistantConversationScope
  sessionFilterEpisodeId: string
  assistantRequestEpisodeId: string
  assistantWorkflowId: string
  scopedActiveTarget: AgentTargetContext | null
  assistantContextKey: string
}

const RUNNING_AGENT_FEEDBACK_TASK_TYPES = new Set([
  "native_chat",
  "episode_boundary_propose",
  "asset_range_propose",
  "asset_extraction",
  "work_chain_plan_save",
  "workflow_cinematic_script_generation",
  "director_plan_generation",
  "video_prompt_generation",
  "video_prompt_optimization",
  "video_prompt_standalone_generation",
])

const CANVAS_MEDIA_METHODS = new Map([
  ["storyboard_image_generation", "generate_storyboard_image"],
  ["visual_handoff_image_generation", "generate_visual_handoff_image"],
  ["storyboard_video_generation", "generate_storyboard_video"],
])

export function useAssistantSession({
  context,
  backendReady,
  callBackend,
  onBackendEvent,
  composer,
  onNavigate,
  onOpenProjectConversation,
  onProjectChanged,
}: {
  context: AssistantSessionContext
  backendReady: boolean
  callBackend: BackendCaller
  onBackendEvent: (eventName: string, callback: (payload: unknown) => void) => () => void
  composer: AssistantComposerController
  onNavigate: (section: WorkspaceSection, episodeId?: string) => void
  onOpenProjectConversation: () => void
  onProjectChanged: () => Promise<void>
}) {
  const {
    projectId,
    episodeId,
    assistantScope,
    sessionFilterEpisodeId,
    assistantRequestEpisodeId,
    assistantWorkflowId,
    scopedActiveTarget,
    assistantContextKey,
  } = context
  const {
    input,
    assistantTaskTypes,
    assistantProgramActions,
    clearError: clearComposerError,
    reset: resetComposer,
    prepareSend,
    accept: acceptDraft,
    restore: restoreDraft,
    restoreConversationDraft,
    invalidate: invalidateComposer,
  } = composer
  // Identity changes during render: old promises/events cannot write before effect cleanup.
  const contextScopeRef = useRef({ key: assistantContextKey, active: true })
  if (contextScopeRef.current.key !== assistantContextKey)
    contextScopeRef.current = { key: assistantContextKey, active: true }
  const contextScope = contextScopeRef.current
  const conversationEpochRef = useRef(0)
  useEffect(() => {
    contextScope.active = true
    return () => {
      contextScope.active = false
    }
  }, [contextScope])
  const isCurrentContext = useCallback(
    () => contextScopeRef.current === contextScope && contextScope.active,
    [contextScope]
  )
  const captureRequest = useCallback(() => {
    const epoch = conversationEpochRef.current
    return () => isCurrentContext() && conversationEpochRef.current === epoch
  }, [isCurrentContext])
  const scopedOnBackendEvent = useCallback(
    (name: string, callback: (payload: unknown) => void) =>
      onBackendEvent(name, (payload) => {
        if (isCurrentContext()) callback(payload)
      }),
    [isCurrentContext, onBackendEvent]
  )
  const [presentationResetKey, setPresentationResetKey] = useState(0)

  const resetAssistantPresentation = useCallback(
    () => setPresentationResetKey((key) => key + 1),
    []
  )

  const assistantContextKeyRef = useRef(assistantContextKey)

  const [requestPending, setRequestPending] = useState(false)

  const [pendingQuestion, setPendingQuestion] = useState<AssistantPendingQuestion | null>(
    null
  )
  const [pendingInteractions, setPendingInteractions] = useState<AssistantPendingInteraction[]>([])

  const [sessions, setSessions] = useState<AssistantSessionSummary[]>([])

  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)

  const [currentSessionStatus, setCurrentSessionStatus] = useState<
    AssistantSessionSummary["status"] | null
  >(null)

  const [sessionsLoading, setSessionsLoading] = useState(false)
  const [loadedSessionContextKey, setLoadedSessionContextKey] = useState<string | null>(null)

  const [assistantError, setAssistantError] = useState<string | null>(null)

  const [liveActivity, setLiveActivity] = useState<AssistantLiveActivityItem[]>([])

  const currentSessionIdRef = useRef<string | null>(null)

  const pendingSessionIdRef = useRef<string | null>(null)

  const sessionLoadTokenRef = useRef(0)

  const [turns, setTurns] = useState<AssistantTurn[]>([])

  const [draftTurn, setDraftTurn] = useState<AssistantTurn | null>(null)

  const [assistantDurationTick, setAssistantDurationTick] = useState(0)

  const backendActiveSessionRunningRef = useRef(false)

  const assistantRequestInFlightRef = useRef(false)
  const latestCanvasLaunchRef = useRef(0)
  const autoReturnTaskRef = useRef<string | null>(null)
  const conversationTaskSelectionsRef = useRef(new Map<string, string>())
  const mediaLaunchesRef = useRef(new Set<string>())
  const conversationDraftsRef = useRef(new Map<string, ReturnType<typeof prepareSend>>())
  const resolveConversationSessionSelection = useCallback((rows: AssistantSessionSummary[], id: string | null) =>
    resolveCanvasSessionSelection(rows, id,
      conversationTaskSelectionsRef.current.get(`${assistantContextKey}:${id}`),
      new Set(rows.filter((row) => {
        const draft = conversationDraftsRef.current.get(`${assistantContextKey}:${row.id}`)
        return draft && (draft.text || draft.attachments.length)
      }).map((row) => row.id))), [assistantContextKey])

  const refreshAssistantSessionSnapshotRef = useRef<((sessionId: string) => void) | null>(
    null
  )

  const sessionsRef = useRef<AssistantSessionSummary[]>([])
  const sessionVersionsRef = useRef(new Map<string, AssistantSessionSummary>())
  const deletedSessionIdsRef = useRef(new Set<string>())
  const acceptSessionVersion = useCallback((row: AssistantSessionSummary, allowInitialRevisionZero = false) => {
    if (deletedSessionIdsRef.current.has(row.id)) return false
    const key = `${assistantContextKey}:${row.id}`
    const previous = sessionVersionsRef.current.get(key)
    if (!acceptsAssistantSessionVersion(row, previous, allowInitialRevisionZero)) return false
    sessionVersionsRef.current.set(key, row)
    return true
  }, [assistantContextKey])

  const currentSessionSummary =
    sessions.find((session) => session.id === currentSessionId) ?? null
  const currentCanvasTask = currentSessionSummary?.canvasTask
  useEffect(() => {
    if (currentCanvasTask && currentSessionId) {
      conversationTaskSelectionsRef.current.set(
        `${assistantContextKey}:${currentCanvasTask.parentSessionId}`, currentSessionId
      )
    }
  }, [assistantContextKey, currentCanvasTask, currentSessionId])
  const effectiveActiveTarget = currentCanvasTask?.target ?? scopedActiveTarget

  const currentSessionFinished =
    isAssistantFinishedSessionStatus(currentSessionStatus) ||
    isAssistantFinishedSessionStatus(currentSessionSummary?.status)

  const currentSessionRunning = currentSessionFinished
    ? false
    : currentSessionStatus !== null
      ? currentSessionStatus === "running"
      : isAssistantSessionRunning(currentSessionSummary)

  const otherRunningSession =
    sessions.find(
      (session) => isAssistantSessionRunning(session) && session.id !== currentSessionId
    ) ?? null

  const hasAnyRunningSession = currentSessionRunning || Boolean(otherRunningSession)

  const pendingQuestionWaiting = Boolean(pendingQuestion)

  const backendActiveSessionRunning = currentSessionRunning && !pendingQuestionWaiting

  const refreshCompletionSnapshot = useCallback(
    (sessionId: string) => refreshAssistantSessionSnapshotRef.current?.(sessionId),
    []
  )

  const completion = useAssistantCompletion({
    currentSessionId,
    pendingQuestionWaiting,
    currentSessionFinished,
    turns,
    refreshSnapshot: refreshCompletionSnapshot,
  })

  const {
    holding: completionRenderHolding,
    begin: beginCompletionRenderHold,
    clear: clearCompletion,
    clearForSession: clearSessionCompletion,
  } = completion

  const activeSessionRunning = backendActiveSessionRunning || completionRenderHolding

  const assistantRuntimeRunning = activeSessionRunning

  const canStopAssistantRuntime = Boolean(
    !sessionsLoading && !pendingSessionIdRef.current && currentSessionId && backendActiveSessionRunning
  )

  const inputLocked = sessionsLoading || requestPending || activeSessionRunning
  const runningTaskType = currentSessionSummary?.runningTaskType || ""
  const canReviseRunningTask = !currentCanvasTask && RUNNING_AGENT_FEEDBACK_TASK_TYPES.has(runningTaskType)
  const composerLocked = sessionsLoading || requestPending || completionRenderHolding ||
    (backendActiveSessionRunning && !canReviseRunningTask)

  const commitAssistantSessionSummaries = useCallback(
    (nextSessions: AssistantSessionSummary[], allowInitialRevisionZero = false) => {
      const accepted = nextSessions.flatMap((row) => {
        if (deletedSessionIdsRef.current.has(row.id)) return []
        if (acceptSessionVersion(row, allowInitialRevisionZero)) return [row]
        const previous = sessionVersionsRef.current.get(`${assistantContextKey}:${row.id}`)
        return previous ? [previous] : []
      })
      sessionsRef.current = accepted
      setSessions(accepted)
    },
    [acceptSessionVersion, assistantContextKey]
  )

  useEffect(() => {
    sessionsRef.current = sessions
  }, [sessions])

  const assistantLiveActivityItems = useMemo(() => {
    const draftItems = assistantLiveActivityFromDraftTurn(draftTurn)
    return mergeAssistantLiveActivityItems(liveActivity, draftItems)
  }, [
    draftTurn,
    liveActivity,
  ])

  const displayedAssistantLiveActivityItems = useMemo(
    () =>
      completionRenderHolding && assistantLiveActivityItems.length === 0
        ? [{ id: "rendering-final-reply", text: "正在显示最终回复" }]
        : assistantLiveActivityItems,
    [assistantLiveActivityItems, completionRenderHolding]
  )

  const showDraftTurnInChat = !(
    assistantRuntimeRunning && displayedAssistantLiveActivityItems.length > 0
  )

  const selectedTurns = useMemo(
    () => composeAssistantTurns(turns, showDraftTurnInChat ? draftTurn : null),
    [draftTurn, showDraftTurnInChat, turns]
  )
  const { allTurns, rememberSession } = useAssistantCanvasTimeline({
    contextKey: assistantContextKey, projectId, episodeId: assistantRequestEpisodeId,
    backendReady, callBackend, sessions, currentSessionId, currentTurns: selectedTurns,
  })

  const activeRunStartedAtMs = useMemo(() => {
    if (!activeSessionRunning) return null
    return (
      latestUserTurnTimestampMs(selectedTurns) ??
      parseAssistantTimestampMs(currentSessionSummary?.updatedAt) ??
      parseAssistantTimestampMs(currentSessionSummary?.createdAt)
    )
  }, [
    activeSessionRunning,
    selectedTurns,
    currentSessionSummary?.createdAt,
    currentSessionSummary?.updatedAt,
  ])

  const runningElapsedText = useMemo(() => {
    if (!assistantRuntimeRunning || activeRunStartedAtMs === null) return undefined
    return formatAssistantDuration(Date.now() - activeRunStartedAtMs)
  }, [activeRunStartedAtMs, assistantDurationTick, assistantRuntimeRunning])

  useEffect(() => {
    backendActiveSessionRunningRef.current = backendActiveSessionRunning
  }, [backendActiveSessionRunning])

  useEffect(() => {
    if (!assistantRuntimeRunning) return
    setAssistantDurationTick((current) => current + 1)
    const timer = window.setInterval(() => {
      setAssistantDurationTick((current) => current + 1)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [assistantRuntimeRunning])

  const appendAssistantMessage = useCallback((message: AssistantMessage) => {
    const turn = assistantMessageToTurn(message)

    setTurns((current) => [...current, turn])
    setDraftTurn(null)
  }, [])

  const syncAssistantSessionRunState = useCallback(
    (sessionId: string, status?: AssistantSessionSummary["status"] | null) => {
      const normalizedSessionId = sessionId.trim()
      if (!normalizedSessionId) return
      if (
        status &&
        (!currentSessionIdRef.current ||
          currentSessionIdRef.current === normalizedSessionId)
      ) {
        setCurrentSessionStatus(status)
      }
      if (status === "running") {
        backendActiveSessionRunningRef.current = true
        clearSessionCompletion(normalizedSessionId)
        return
      }
      const sessionWasRunning =
        backendActiveSessionRunningRef.current ||
        isAssistantSessionRunning(
          sessionsRef.current.find((session) => session.id === normalizedSessionId)
        )
      const sessionFinished = isAssistantFinishedSessionStatus(status)
      if (
        sessionFinished &&
        sessionWasRunning &&
        currentSessionIdRef.current === normalizedSessionId
      ) {
        markWorkspaceAgentTurnTaskFinishedFromAssistantSession(
          projectId,
          normalizedSessionId,
          status,
          sessionVersionsRef.current.get(`${assistantContextKey}:${normalizedSessionId}`)?.execution?.id
        )
        beginCompletionRenderHold(normalizedSessionId)
        void refreshAssistantSessionSnapshotRef.current?.(normalizedSessionId)
      }
      if (sessionFinished) {
        backendActiveSessionRunningRef.current = false
      }
    },
    [beginCompletionRenderHold, projectId, clearSessionCompletion, assistantContextKey]
  )

  const applyAssistantSession = useCallback(
    (
      session: AssistantSessionDetail | null,
      _mode: "default" | "new" | "clear" = "default",
      allowInitialRevisionZero = false
    ) => {
      if (!session) {
        setCurrentSessionId(null)
        currentSessionIdRef.current = null
        pendingSessionIdRef.current = null
        setCurrentSessionStatus(null)
        backendActiveSessionRunningRef.current = false
        clearCompletion()

        setTurns([])
        setDraftTurn(null)

        setPendingQuestion(null)
        setPendingInteractions([])
        setAssistantError(null)
        clearComposerError()
        setLiveActivity([])
        resetAssistantPresentation()
        return true
      }
      const normalizedSessionId = String(session.id || "").trim()
      if (!normalizedSessionId) return false
      const activeSessionId = currentSessionIdRef.current
      const pendingSessionId = pendingSessionIdRef.current
      if (
        (activeSessionId || pendingSessionId) &&
        normalizedSessionId !== activeSessionId &&
        normalizedSessionId !== pendingSessionId
      ) {
        return false
      }
      if (!acceptSessionVersion(session, allowInitialRevisionZero)) return false
      rememberSession(session)
      if (session.stateRevision) {
        commitAssistantSessionSummaries(sessionsRef.current.map((row) => row.id === session.id ? session : row))
      }
      setCurrentSessionId(session.id)
      currentSessionIdRef.current = session.id
      if (pendingSessionIdRef.current === session.id) {
        pendingSessionIdRef.current = null
      }
      setCurrentSessionStatus(session.status)
      syncAssistantSessionRunState(session.id, session.status)
      writeLastAssistantSessionId(assistantContextKey, session.id)

      setTurns(session.messages.map(assistantMessageToTurn))
      setDraftTurn(null)

      setPendingQuestion(session.pendingQuestion ?? null)
      setPendingInteractions(session.pendingInteractions ?? [])
      setAssistantError(null)
      clearComposerError()
      setLiveActivity([])
      if (isAssistantFinishedSessionStatus(session.status)) {
        backendActiveSessionRunningRef.current = false
        clearCompletion()
      }
      resetAssistantPresentation()
      return true
    },
    [
      assistantContextKey,
      assistantScope,
      projectId,
      syncAssistantSessionRunState,
      clearComposerError,
      clearCompletion,
      resetAssistantPresentation,
      acceptSessionVersion,
      commitAssistantSessionSummaries,
      rememberSession,
    ]
  )

  const applyAssistantSnapshot = useCallback(
    (snapshot: AssistantSessionSnapshot | null | undefined, allowInitialRevisionZero = false) => {
      if (!snapshot) return false
      const session = snapshot.session
        ? normalizeAssistantSessionDetail(snapshot.session)
        : null
      const sessionId = String(
        snapshot.session?.id || session?.id || snapshot.sessionId || ""
      ).trim()
      if (!sessionId) return false
      const activeSessionId = currentSessionIdRef.current
      const pendingSessionId = pendingSessionIdRef.current
      if (
        (activeSessionId || pendingSessionId) &&
        sessionId !== activeSessionId &&
        sessionId !== pendingSessionId
      ) {
        return false
      }
      const snapshotStatus = snapshot.status ?? session?.status
      if (!session || !acceptSessionVersion({ ...session, status: snapshotStatus ?? session.status }, allowInitialRevisionZero)) return false
      rememberSession(session)
      if (session?.stateRevision) {
        commitAssistantSessionSummaries(sessionsRef.current.map((row) => row.id === session.id ? session : row))
      }
      setCurrentSessionId(session.id)
      currentSessionIdRef.current = session.id
      if (pendingSessionIdRef.current === session.id) {
        pendingSessionIdRef.current = null
      }
      setCurrentSessionStatus(snapshotStatus ?? session.status)
      writeLastAssistantSessionId(assistantContextKey, session.id)
      syncAssistantSessionRunState(sessionId, snapshotStatus)
      const nextTurns = normalizeAssistantSnapshotTurns(snapshot, session)
      setTurns((currentTurns) =>
        activeSessionId === sessionId && shouldPreserveLocalUserTurn(nextTurns, currentTurns)
          ? [...nextTurns, findLatestOptimisticAssistantUserTurn(currentTurns)!]
          : nextTurns
      )
      setDraftTurn(normalizeAssistantDraftTurn(snapshot))
      setLiveActivity(
        snapshotStatus === "running"
          ? normalizeAssistantLiveActivity(
              snapshot.live_activity ?? snapshot.liveActivity
            )
          : []
      )
      if (isAssistantFinishedSessionStatus(snapshotStatus)) {
        backendActiveSessionRunningRef.current = false
        clearCompletion()
      }
      setPendingQuestion(
        normalizeAssistantSnapshotPendingQuestion(snapshot) ??
          session?.pendingQuestion ??
          null
      )
      setPendingInteractions(session?.pendingInteractions ?? [])
      setAssistantError(null)
      clearComposerError()
      return true
    },
    [
      assistantContextKey,
      assistantScope,
      projectId,
      syncAssistantSessionRunState,
      clearComposerError,
      clearCompletion,
      acceptSessionVersion,
      commitAssistantSessionSummaries,
      rememberSession,
    ]
  )

  const refreshAssistantSessionSnapshot = useCallback(
    async (sessionId: string) => {
      const normalizedSessionId = sessionId.trim()
      if (!backendReady || !normalizedSessionId) return
      const requestIsCurrent = captureRequest()
      const isCurrentRefresh = () => {
        if (!requestIsCurrent()) return false
        const activeSessionId = currentSessionIdRef.current
        return !activeSessionId || activeSessionId === normalizedSessionId
      }
      try {
        const snapshotResult = await callBackend<{
          success?: boolean
          snapshot?: AssistantSessionSnapshot
          session?: AssistantSessionDetail
          message?: string
        }>("get_agent_snapshot", {
          projectId: projectId,
          sessionId: normalizedSessionId,
          scope: assistantScope,
          episodeId: assistantRequestEpisodeId,
        })
        if (!isCurrentRefresh()) return
        if (
          !isBackendFailure(snapshotResult) &&
          snapshotResult.snapshot &&
          applyAssistantSnapshot(snapshotResult.snapshot, true)
        ) {
          return
        }

        const detailResult = await callBackend<{
          success?: boolean
          session?: AssistantSessionDetail
          message?: string
        }>("get_agent_session", {
          projectId: projectId,
          sessionId: normalizedSessionId,
          scope: assistantScope,
          episodeId: assistantRequestEpisodeId,
        })
        if (!isCurrentRefresh()) return
        if (!isBackendFailure(detailResult) && detailResult.session) {
          applyAssistantSession(normalizeAssistantSessionDetail(detailResult.session), "default", true)
        }
      } catch (error) {
        console.warn("刷新智能体最终回复失败:", error)
      }
    },
    [
      applyAssistantSession,
      applyAssistantSnapshot,
      assistantContextKey,
      assistantScope,
      assistantRequestEpisodeId,
      backendReady,
      callBackend,
      projectId,
      captureRequest,
    ]
  )

  refreshAssistantSessionSnapshotRef.current = refreshAssistantSessionSnapshot

  const resetConversation = useCallback(
    (mode: "default" | "new" | "clear" = "default") => {
      applyAssistantSession(null, mode)
      resetComposer()
      setAssistantError(null)
      resetAssistantPresentation()
    },
    [applyAssistantSession, resetComposer, resetAssistantPresentation]
  )

  const loadAssistantSessions = useCallback(
    async (
      preferredSessionId?: string | null,
      options?: { autoSelect?: boolean; quiet?: boolean }
    ) => {
      if (!backendReady) return
      const loadToken = (sessionLoadTokenRef.current += 1)
      const requestIsCurrent = captureRequest()
      const contextKeyAtRequest = assistantContextKey
      const currentSessionIdForContext =
        assistantContextKeyRef.current === contextKeyAtRequest
          ? currentSessionIdRef.current
          : null
      const isCurrentLoad = () =>
        requestIsCurrent() &&
        sessionLoadTokenRef.current === loadToken &&
        assistantContextKeyRef.current === contextKeyAtRequest
      const autoSelect = options?.autoSelect ?? true
      const quiet = options?.quiet ?? false
      if (!quiet) {
        setLoadedSessionContextKey(null)
        setSessionsLoading(true)
      }
      let targetSessionId: string | null = null
      try {
        const listResult = await callBackend<{
          success?: boolean
          conversations?: AssistantSessionSummary[]
          sessions?: AssistantSessionSummary[]
          message?: string
        }>("list_agent_conversations", {
          projectId: projectId,
          episodeId: assistantRequestEpisodeId,
          scope: assistantScope,
        })
        if (!isCurrentLoad()) return
        if (isBackendFailure(listResult)) {
          throw new Error(listResult.message || "加载智能体会话失败")
        }
        let nextSessions = normalizeAssistantSessionSummaries(
          listResult.conversations ?? listResult.sessions,
          sessionFilterEpisodeId
        )
        if (
          !nextSessions.some((row) => !row.canvasTask) &&
          assistantScope === "episode" &&
          autoSelect &&
          !preferredSessionId
        ) {
          const ensureResult = await callBackend<{
            success?: boolean
            conversation?: AssistantSessionSummary
            session?: AssistantSessionDetail
            message?: string
          }>("ensure_episode_agent_conversation", {
            projectId: projectId,
            episodeId,
            workflowId: assistantWorkflowId,
          })
          if (isBackendFailure(ensureResult)) {
            throw new Error(ensureResult.message || "创建分集会话失败")
          }
          nextSessions = normalizeAssistantSessionSummaries(
            ensureResult.conversation ? [ensureResult.conversation, ...nextSessions] : nextSessions,
            sessionFilterEpisodeId
          )
          if (!isCurrentLoad()) return
          commitAssistantSessionSummaries(nextSessions, true)
          if (ensureResult.session) {
            const ensuredSession = normalizeAssistantSessionDetail(ensureResult.session)
            const ensuredSessionId = String(ensuredSession.id || "").trim()
            if (ensuredSessionId) {
              pendingSessionIdRef.current = ensuredSessionId
            }
            applyAssistantSession(ensuredSession, "default", true)
            return
          }
        }
        if (!isCurrentLoad()) return
        commitAssistantSessionSummaries(nextSessions, true)
        if (nextSessions.length === 0) {
          if (autoSelect) {
            applyAssistantSession(null, "default")
          }
          return
        }
        if (!autoSelect && !preferredSessionId && !currentSessionIdForContext) {
          return
        }
        let savedSessionId = ""
        if (autoSelect) {
          try {
            const contextResult = await callBackend<{
              success?: boolean
              sessionId?: string
            }>("get_agent_conversation_context", {
              projectId: projectId,
              episodeId: assistantRequestEpisodeId,
              scope: assistantScope,
            })
            savedSessionId = String(contextResult.sessionId || "").trim()
          } catch (error) {
            console.warn("读取智能体会话上下文失败:", error)
          }
        }
        if (!isCurrentLoad()) return
        const lastSessionId = autoSelect
          ? readLastAssistantSessionId(assistantContextKey)
          : null
        targetSessionId =
          (preferredSessionId &&
          nextSessions.some((session) => session.id === preferredSessionId)
            ? preferredSessionId
            : currentSessionIdForContext &&
                nextSessions.some((session) => session.id === currentSessionIdForContext)
              ? currentSessionIdForContext
              : savedSessionId &&
                  nextSessions.some((session) => session.id === savedSessionId)
                ? savedSessionId
                : lastSessionId &&
                    nextSessions.some((session) => session.id === lastSessionId)
                  ? lastSessionId
                  : autoSelect
                    ? nextSessions[0]?.id
                    : null) ?? null
        if (!targetSessionId) {
          if (autoSelect) {
            applyAssistantSession(null, "default")
          }
          return
        }
        // Polling refreshes the selected view; it must not undo a deliberate
        // switch from task progress back to the ordinary conversation.
        if (!quiet) targetSessionId = resolveConversationSessionSelection(nextSessions, targetSessionId)
        // Only a selection change locks interaction; refreshing the current
        // session must leave sending and stopping available.
        if (targetSessionId !== currentSessionIdRef.current) {
          pendingSessionIdRef.current = targetSessionId
        }
        const snapshotResult = await callBackend<{
          success?: boolean
          snapshot?: AssistantSessionSnapshot
          session?: AssistantSessionDetail
          message?: string
        }>("get_agent_snapshot", {
          projectId: projectId,
          sessionId: targetSessionId,
          scope: assistantScope,
          episodeId: assistantRequestEpisodeId,
        })
        if (!isCurrentLoad()) return
        if (
          !isBackendFailure(snapshotResult) &&
          snapshotResult.snapshot &&
          applyAssistantSnapshot(snapshotResult.snapshot, true)
        ) {
          return
        }
        const detailResult = await callBackend<{
          success?: boolean
          session?: AssistantSessionDetail
          message?: string
        }>("get_agent_session", {
          projectId: projectId,
          sessionId: targetSessionId,
          scope: assistantScope,
          episodeId: assistantRequestEpisodeId,
        })
        if (isBackendFailure(detailResult) || !detailResult.session) {
          throw new Error(
            detailResult.message || snapshotResult.message || "加载智能体会话失败"
          )
        }
        if (!isCurrentLoad()) return
        const applied = applyAssistantSession(normalizeAssistantSessionDetail(detailResult.session), "default", true)
        if (!applied && pendingSessionIdRef.current === targetSessionId) {
          throw new Error("会话状态已更新，请重新选择该会话。")
        }
      } catch (error) {
        if (!isCurrentLoad()) return
        if (pendingSessionIdRef.current === targetSessionId) {
          pendingSessionIdRef.current = null
        }
        const message = error instanceof Error ? error.message : "加载智能体会话失败"
        console.warn("加载智能体会话失败:", error)
        if ((options?.autoSelect ?? true) && !currentSessionIdForContext) {
          applyAssistantSession(null, "default")
        }
        setAssistantError(message)
        if (!quiet) {
          toast.error(message)
        }
      } finally {
        if (isCurrentLoad()) {
          setSessionsLoading(false)
          if (!quiet) setLoadedSessionContextKey(contextKeyAtRequest)
        }
      }
    },
    [
      applyAssistantSession,
      applyAssistantSnapshot,
      assistantContextKey,
      assistantRequestEpisodeId,
      assistantScope,
      assistantWorkflowId,
      backendReady,
      callBackend,
      commitAssistantSessionSummaries,
      episodeId,
      projectId,
      sessionFilterEpisodeId,
      captureRequest,
      resolveConversationSessionSelection,
    ]
  )

  useEffect(() => {
    if (assistantContextKeyRef.current === assistantContextKey) return
    assistantContextKeyRef.current = assistantContextKey
    conversationEpochRef.current += 1
    assistantRequestInFlightRef.current = false
    setRequestPending(false)
    sessionLoadTokenRef.current += 1
    pendingSessionIdRef.current = null
    commitAssistantSessionSummaries([])
    setSessionsLoading(false)
    setLoadedSessionContextKey(null)
    resetConversation("default")
  }, [assistantContextKey, loadAssistantSessions, resetConversation])

  useEffect(() => {
    if (!backendReady) return
    void loadAssistantSessions()
  }, [backendReady, loadAssistantSessions])

  useEffect(() => {
    if (
      !backendReady ||
      !currentSessionId ||
      currentSessionIdRef.current !== currentSessionId
    )
      return
    void callBackend("set_agent_conversation_context", {
      projectId: projectId,
      episodeId: assistantRequestEpisodeId,
      scope: assistantScope,
      sessionId: currentSessionId,
      workflowId: assistantWorkflowId,
      activeTarget: effectiveActiveTarget,
    }).catch((error) => {
      console.warn("保存智能体会话上下文失败:", error)
    })
  }, [
    assistantScope,
    assistantRequestEpisodeId,
    assistantWorkflowId,
    backendReady,
    callBackend,
    currentSessionId,
    episodeId,
    projectId,
    effectiveActiveTarget,
  ])

  useEffect(() => {
    if (!backendReady || !hasAnyRunningSession || sessionsLoading) return
    const timer = window.setInterval(() => {
      void loadAssistantSessions(currentSessionIdRef.current, {
        autoSelect: Boolean(currentSessionIdRef.current),
        quiet: true,
      })
    }, 1800)
    return () => window.clearInterval(timer)
  }, [backendReady, hasAnyRunningSession, loadAssistantSessions, sessionsLoading])

  const handleAgentEventSessions = useCallback(
    (rawSessions: unknown[]) => {
      const nextSessions = normalizeAssistantSessionSummaries(
        rawSessions,
        sessionFilterEpisodeId
      )
      const activeSessionId = currentSessionIdRef.current
      const incomingActiveSession = nextSessions.find(
        (session) => session.id === activeSessionId
      )
      const previousActiveSession = sessionsRef.current.find(
        (session) => session.id === activeSessionId
      )
      const activeSessionWasRunning =
        backendActiveSessionRunningRef.current ||
        isAssistantSessionRunning(previousActiveSession)
      if (
        activeSessionId &&
        incomingActiveSession &&
        acceptsAssistantSessionVersion(incomingActiveSession,
          sessionVersionsRef.current.get(`${assistantContextKey}:${activeSessionId}`)) &&
        activeSessionWasRunning &&
        isAssistantFinishedSessionStatus(incomingActiveSession?.status)
      ) {
        markWorkspaceAgentTurnTaskFinishedFromAssistantSession(
          projectId,
          activeSessionId,
          incomingActiveSession.status,
          incomingActiveSession.execution?.id
        )
        beginCompletionRenderHold(activeSessionId)
      }
      // Session events have no list revision. A delayed event from task A may
      // predate task B's creation; only authoritative reloads/deletes remove B.
      const incomingIds = new Set(nextSessions.map((row) => row.id))
      const retainedTasks = sessionsRef.current.filter(
        (row) => row.canvasTask && !incomingIds.has(row.id),
      )
      commitAssistantSessionSummaries(retainedTasks.length ? [...nextSessions, ...retainedTasks] : nextSessions)
    },
    [
      beginCompletionRenderHold,
      commitAssistantSessionSummaries,
      projectId,
      sessionFilterEpisodeId,
      assistantContextKey,
    ]
  )

  const handleAgentEventSnapshot = useCallback(
    (snapshot: unknown) => {
      applyAssistantSnapshot(snapshot as AssistantSessionSnapshot)
    },
    [applyAssistantSnapshot]
  )

  const handleAgentEventSession = useCallback(
    (session: unknown) => {
      applyAssistantSession(
        normalizeAssistantSessionDetail(session as AssistantSessionDetail)
      )
    },
    [applyAssistantSession]
  )
  const handleAnySession = useCallback((raw: unknown) => {
    if (raw && typeof raw === "object") rememberSession(raw as AssistantSessionDetail)
  }, [rememberSession])

  const handleAgentTerminalTask = useCallback(
    ({
      sessionId,
      task,
    }: {
      eventName?: "task_completed" | "task_failed" | "task_cancelled"
      sessionId: string
      task: { executionId?: string }
    }) => {
      const normalizedSessionId = sessionId.trim()
      if (!normalizedSessionId) return
      const activeSessionId = currentSessionIdRef.current
      if (!activeSessionId || activeSessionId !== normalizedSessionId) return
      const executionId = sessionVersionsRef.current.get(`${assistantContextKey}:${normalizedSessionId}`)?.execution?.id
      if (!executionId || task.executionId !== executionId) return
      // A child ending does not finish its siblings or parent. Read the aggregate state.
      void refreshAssistantSessionSnapshot(normalizedSessionId)
    },
    [assistantContextKey, refreshAssistantSessionSnapshot]
  )

  useAgentSessionEvents({
    projectId: projectId,
    episodeId: sessionFilterEpisodeId,
    currentSessionIdRef,
    onBackendEvent: scopedOnBackendEvent,
    onSessions: handleAgentEventSessions,
    onSnapshot: handleAgentEventSnapshot,
    onSession: handleAgentEventSession,
    onTerminalTask: handleAgentTerminalTask,
    onAnySession: handleAnySession,
  })

  const handleCreateConversation = useCallback(async () => {
    if (!backendReady || sessionsLoading) return
    const requestIsCurrent = captureRequest()
    setSessionsLoading(true)
    try {
      const result = await callBackend<{
        success?: boolean
        session?: AssistantSessionDetail
        conversation?: AssistantSessionSummary
        message?: string
      }>("create_agent_conversation", {
        projectId,
        episodeId: assistantRequestEpisodeId,
        scope: assistantScope,
        workflowId: assistantWorkflowId,
      })
      if (!requestIsCurrent()) return
      if (isBackendFailure(result) || !result.session) {
        throw new Error(result.message || "创建会话失败")
      }
      const session = normalizeAssistantSessionDetail(result.session)
      if (currentSessionIdRef.current) {
        conversationDraftsRef.current.set(`${assistantContextKey}:${currentSessionIdRef.current}`, prepareSend())
      }
      conversationEpochRef.current += 1
      sessionLoadTokenRef.current += 1
      assistantRequestInFlightRef.current = false
      setRequestPending(false)
      resetConversation("new")
      pendingSessionIdRef.current = session.id
      commitAssistantSessionSummaries([session, ...sessionsRef.current], true)
      applyAssistantSession(session, "new", true)
    } catch (error) {
      if (requestIsCurrent()) toast.error(error instanceof Error ? error.message : "创建会话失败")
    } finally {
      setSessionsLoading(false)
    }
  }, [backendReady, sessionsLoading, captureRequest, callBackend,
      projectId, assistantRequestEpisodeId, assistantScope, assistantWorkflowId,
      resetConversation, commitAssistantSessionSummaries, applyAssistantSession, assistantContextKey, prepareSend])

  const handleClearConversation = useCallback(() => {
    if (requestPending) return
    conversationEpochRef.current += 1
    sessionLoadTokenRef.current += 1
    setSessionsLoading(false)
    setCurrentSessionId(null)
    currentSessionIdRef.current = null
    pendingSessionIdRef.current = null
    resetConversation("clear")
  }, [requestPending, resetConversation])

  const handleSwitchSession = useCallback(
    async (sessionId: string, options?: { resumeTask?: boolean }) => {
      const requestedSessionId = sessionId.trim()
      if (!backendReady || !requestedSessionId) return
      const previousSessionId = currentSessionIdRef.current
      if (previousSessionId)
        conversationDraftsRef.current.set(`${assistantContextKey}:${previousSessionId}`, prepareSend())
      const normalizedSessionId = options?.resumeTask === false
        ? requestedSessionId
        : resolveConversationSessionSelection(sessionsRef.current, requestedSessionId)
      if (!normalizedSessionId) return
      const restoreSelectedDraft = () => {
        resetComposer()
        const saved = conversationDraftsRef.current.get(`${assistantContextKey}:${normalizedSessionId}`)
        if (saved) restoreConversationDraft(saved)
      }
      conversationEpochRef.current += 1
      assistantRequestInFlightRef.current = false
      setRequestPending(false)
      invalidateComposer()
      const requestIsCurrent = captureRequest()
      const loadToken = (sessionLoadTokenRef.current += 1)
      const contextKeyAtRequest = assistantContextKey
      const isCurrentLoad = () =>
        requestIsCurrent() &&
        sessionLoadTokenRef.current === loadToken &&
        assistantContextKeyRef.current === contextKeyAtRequest
      pendingSessionIdRef.current = normalizedSessionId
      setSessionsLoading(true)
      try {
        const snapshotResult = await callBackend<{
          success?: boolean
          snapshot?: AssistantSessionSnapshot
          message?: string
        }>("get_agent_snapshot", {
          projectId: projectId,
          sessionId: normalizedSessionId,
          scope: assistantScope,
          episodeId: assistantRequestEpisodeId,
        })
        if (!isCurrentLoad()) return
        if (
          !isBackendFailure(snapshotResult) &&
          snapshotResult.snapshot &&
          applyAssistantSnapshot(snapshotResult.snapshot, true)
        ) {
          restoreSelectedDraft()
          return
        }
        const detailResult = await callBackend<{
          success?: boolean
          session?: AssistantSessionDetail
          message?: string
        }>("get_agent_session", {
          projectId: projectId,
          sessionId: normalizedSessionId,
          scope: assistantScope,
          episodeId: assistantRequestEpisodeId,
        })
        if (isBackendFailure(detailResult) || !detailResult.session) {
          throw new Error(detailResult.message || "加载智能体会话失败")
        }
        if (!isCurrentLoad()) return
        const applied = applyAssistantSession(normalizeAssistantSessionDetail(detailResult.session), "default", true)
        if (!applied && pendingSessionIdRef.current === normalizedSessionId) {
          throw new Error("会话状态已更新，请重新选择该会话。")
        }
        if (applied) restoreSelectedDraft()
      } catch (error) {
        if (!isCurrentLoad()) return
        if (pendingSessionIdRef.current === normalizedSessionId) {
          pendingSessionIdRef.current = null
        }
        toast.error(error instanceof Error ? error.message : "加载智能体会话失败")
      } finally {
        if (isCurrentLoad()) {
          setSessionsLoading(false)
        }
      }
    },
    [
      applyAssistantSession,
      applyAssistantSnapshot,
      assistantContextKey,
      backendReady,
      callBackend,
      projectId,
      captureRequest,
      invalidateComposer,
      prepareSend,
      resetComposer,
      restoreConversationDraft,
      resolveConversationSessionSelection,
    ]
  )

  const handleStartCanvasTask = useCallback(async (request: CanvasAgentTaskRequest) => {
    if (!backendReady || sessionsLoading || request.projectId !== projectId ||
      request.episodeId !== assistantRequestEpisodeId) return
    const launch = ++latestCanvasLaunchRef.current
    const mayFollowTask = captureRequest()
    const selected = sessionsRef.current.find((row) => row.id === currentSessionIdRef.current)
    const requestedParentId = selected?.canvasTask?.parentSessionId ?? selected?.id
    const parentSessionId = sessionsRef.current.find((row) => row.id === requestedParentId && !row.canvasTask)?.id
    if (!parentSessionId) {
      toast.error("画布会话尚未就绪，请稍后重试")
      return
    }
    try {
      const result = await callBackend<AssistantBackendSuccess | { success: false; message: string; blockingSessionId?: string }>(
        "run_canvas_agent_task", {
          ...request,
          parentSessionId,
          requestKey: createLocalId("canvas-agent-task"),
          taskOptions: {
            scriptTemplateId: request.scriptTemplateId,
            userInstruction: request.userInstruction,
            reworkRecordIds: request.reworkRecordIds,
            draftText: request.draftText,
            soundPrompt: request.soundPrompt,
            assetNameMap: request.assetNameMap,
            promptBindings: request.promptBindings,
          },
        }
      )
      if (!isCurrentContext()) return
      const recorded = result as Partial<AssistantBackendSuccess>
      upsertAssistantReturnedTasks(recorded as AssistantBackendSuccess, projectId)
      const detail = recorded.snapshot?.session ?? recorded.session
      if (detail) rememberSession(detail)
      const incoming = normalizeAssistantSessionSummaries(recorded.sessions ?? (recorded.session ? [recorded.session] : []), sessionFilterEpisodeId)
      if (incoming.length) {
        const ids = new Set(incoming.map((row) => row.id))
        commitAssistantSessionSummaries([...incoming, ...sessionsRef.current.filter((row) => !ids.has(row.id))], true)
      }
      if (result.success === false) {
        toast.info(result.message || "启动画布任务失败")
        const blockingTask = sessionsRef.current.find((row) => row.id === result.blockingSessionId)
        if (result.blockingSessionId && blockingTask?.canvasTask?.parentSessionId === parentSessionId &&
          mayFollowTask() && launch === latestCanvasLaunchRef.current)
          await handleSwitchSession(result.blockingSessionId)
        return
      }
      const sessionId = result.session?.id ?? result.sessionId
      const task = sessionsRef.current.find((row) => row.id === sessionId)
      // A launch must not steal focus after a manual switch, or after a newer launch.
      if (sessionId && (!task?.canvasTask || isActiveCanvasTask(task)) && mayFollowTask() && launch === latestCanvasLaunchRef.current)
        await handleSwitchSession(sessionId)
    } catch (error) {
      if (isCurrentContext()) toast.error(error instanceof Error ? error.message : "启动画布任务失败")
    }
  }, [backendReady, sessionsLoading, projectId, assistantRequestEpisodeId, captureRequest, callBackend,
    isCurrentContext, sessionFilterEpisodeId, commitAssistantSessionSummaries, handleSwitchSession, rememberSession])

  useEffect(() => {
    if (!currentSessionSummary?.canvasTask || isActiveCanvasTask(currentSessionSummary)) {
      autoReturnTaskRef.current = null
      return
    }
    if (!backendReady || sessionsLoading || requestPending) return
    const draft = prepareSend()
    // Finishing a one-shot task must not dismiss text or attachments the user
    // is still composing. Sending/clearing them makes the automatic return safe.
    if (draft.text || draft.attachments.length) return
    const taskKey = `${assistantContextKey}:${currentSessionSummary.id}:${currentSessionSummary.execution?.id ?? ""}`
    // A failed automatic switch remains manually retryable. Loading state changes
    // must not immediately start the same failed read again.
    if (autoReturnTaskRef.current === taskKey) return
    autoReturnTaskRef.current = taskKey
    void handleSwitchSession(currentSessionSummary.canvasTask.parentSessionId)
  }, [currentSessionSummary, sessionsLoading, requestPending, prepareSend,
    handleSwitchSession, backendReady, assistantContextKey])

  const handleDeleteSession = useCallback(
    async (sessionId: string): Promise<boolean> => {
      if (!backendReady || requestPending || !sessionId) return false
      const requestIsCurrent = captureRequest()
      try {
        const result = await callBackend<{
          success?: boolean
          message?: string
        }>("delete_agent_session", {
          projectId: projectId,
          sessionId,
        })
        if (!requestIsCurrent()) return false
        if (isBackendFailure(result)) {
          throw new Error(result.message || "删除智能体会话失败")
        }
        const deletedIds = new Set([sessionId, ...sessionsRef.current
          .filter((session) => session.canvasTask?.parentSessionId === sessionId)
          .map((session) => session.id)])
        for (const id of deletedIds) {
          deletedSessionIdsRef.current.add(id)
          conversationDraftsRef.current.delete(`${assistantContextKey}:${id}`)
          clearLastAssistantSessionId(assistantContextKey, id)
        }
        conversationEpochRef.current += 1
        sessionLoadTokenRef.current += 1
        const remaining = sessionsRef.current.filter(
          (session) => !deletedIds.has(session.id)
        )
        commitAssistantSessionSummaries(remaining)
        if (deletedIds.has(currentSessionIdRef.current ?? "")) {
          setCurrentSessionId(null)
          currentSessionIdRef.current = null
          pendingSessionIdRef.current = null
          resetConversation("default")
          if (remaining[0]?.id) {
            await handleSwitchSession(remaining[0].id)
          }
        }
        return true
      } catch (error) {
        if (!requestIsCurrent()) return false
        toast.error(error instanceof Error ? error.message : "删除智能体会话失败")
        return false
      }
    },
    [
      backendReady,
      callBackend,
      commitAssistantSessionSummaries,
      handleSwitchSession,
      assistantContextKey,
      projectId,
      requestPending,
      resetConversation,
      sessions,
      captureRequest,
    ]
  )

  const handleSelectEpisode = useCallback(
    (nextEpisodeId: string) => {
      onNavigate("episode", nextEpisodeId)
    },
    [onNavigate]
  )

  const applyAssistantClientAction = useCallback(
    (action: AssistantClientAction | null | undefined) => {
      if (!action || action.type !== "navigate") return
      onNavigate(action.section, action.episodeId)
    },
    [onNavigate]
  )

  const commitAssistantResult = useCallback(
    (result: AssistantBackendSuccess) => {
      upsertAssistantReturnedTasks(result, projectId)
      const detail = result.snapshot?.session ?? result.session
      if (detail) rememberSession(detail)
      if (Array.isArray(result.sessions)) {
        const incoming = normalizeAssistantSessionSummaries(result.sessions, sessionFilterEpisodeId)
        const incomingIds = new Set(incoming.map((row) => row.id))
        const retainedTasks = sessionsRef.current.filter(
          (row) => row.canvasTask && !incomingIds.has(row.id),
        )
        commitAssistantSessionSummaries(
          [...incoming, ...retainedTasks],
          true
        )
      }
      if (result.snapshot) {
        applyAssistantSnapshot(result.snapshot, true)
      } else if (result.session) {
        applyAssistantSession(normalizeAssistantSessionDetail(result.session), "default", true)
      } else {
        const activeSessionId = currentSessionIdRef.current
        if (activeSessionId) {
          beginCompletionRenderHold(activeSessionId)
        }
        backendActiveSessionRunningRef.current = false

        setPendingQuestion(null)
        appendAssistantMessage({
          id: createLocalId("assistant"),
          role: "assistant",
          text: result.message,
          createdAt: new Date().toISOString(),
        })
      }
      applyAssistantClientAction(result.clientAction)
    },
    [
      appendAssistantMessage,
      applyAssistantClientAction,
      applyAssistantSession,
      applyAssistantSnapshot,
      beginCompletionRenderHold,
      commitAssistantSessionSummaries,
      projectId,
      assistantScope,
      sessionFilterEpisodeId,
      rememberSession,
    ]
  )

  const handleInterruptSession = useCallback(async () => {
    const activeSessionId = currentSessionIdRef.current
    if (
      !backendReady ||
      sessionsLoading ||
      pendingSessionIdRef.current ||
      !activeSessionId ||
      !backendActiveSessionRunning
    ) {
      return
    }
    const requestIsCurrent = captureRequest()
    try {
      const result = await callBackend<
        AssistantBackendSuccess | { success: false; message: string }
      >("interrupt_agent_session", {
        projectId: projectId,
        episodeId: assistantRequestEpisodeId,
        scope: assistantScope,
        workflowId: assistantWorkflowId,
        sessionId: activeSessionId,
      })
      if (!requestIsCurrent()) return
      if (isBackendFailure(result)) {
        throw new Error(result.message || "停止智能体执行失败")
      }
      const successResult = result as AssistantBackendSuccess
      upsertAssistantReturnedTasks(successResult, projectId)
      if (Array.isArray(successResult.sessions)) {
        commitAssistantSessionSummaries(
          normalizeAssistantSessionSummaries(
            successResult.sessions,
            sessionFilterEpisodeId
          ),
          true
        )
      }
      if (successResult.snapshot) {
        applyAssistantSnapshot(successResult.snapshot, true)
      } else if (successResult.session) {
        applyAssistantSession(normalizeAssistantSessionDetail(successResult.session), "default", true)
      }
      const cancelErrors = Array.isArray(successResult.cancelErrors)
        ? successResult.cancelErrors
        : []
      const uncancelledTaskIds = Array.isArray(successResult.uncancelledTaskIds)
        ? successResult.uncancelledTaskIds
        : []
      const hasUncancelledTasks = uncancelledTaskIds.length > 0
      const hasCancelFailure =
        cancelErrors.length > 0 ||
        Boolean(successResult.partialFailure && !hasUncancelledTasks)
      if (hasCancelFailure) {
        const detail = cancelErrors
          .map((item) => String(item?.message || "").trim())
          .filter(Boolean)
          .slice(0, 2)
          .join("；")
        const message =
          successResult.message ||
          (detail
            ? `已停止当前智能体执行，但部分后台生成任务取消失败：${detail}`
            : "已停止当前智能体执行，但部分后台生成任务取消失败，请在任务面板查看状态。")
        setAssistantError(message)
        toast.error(message)
      } else if (hasUncancelledTasks) {
        toast.info(
          successResult.message ||
            "已停止当前智能体执行；部分后台生成任务已进入保存或结束阶段，已产生的结果会保留。"
        )
        setAssistantError(null)
      } else if (successResult.message) {
        toast.success(successResult.message)
        setAssistantError(null)
      } else {
        setAssistantError(null)
      }
    } catch (error) {
      if (!requestIsCurrent()) return
      const message = error instanceof Error ? error.message : "停止智能体执行失败"
      setAssistantError(message)
      toast.error(message)
    }
  }, [
    applyAssistantSession,
    applyAssistantSnapshot,
    assistantScope,
    assistantRequestEpisodeId,
    assistantWorkflowId,
    backendActiveSessionRunning,
    backendReady,
    callBackend,
    commitAssistantSessionSummaries,
    episodeId,
    projectId,
    sessionFilterEpisodeId,
    captureRequest,
    sessionsLoading,
  ])

  const handleInterruptAssistantRuntime = useCallback(async () => {
    await handleInterruptSession()
  }, [handleInterruptSession])

  const handleQuestionAnswersSubmit = useCallback(
    async (questionId: string, answers: Record<string, string>) => {
      const questionSessionId = currentSessionIdRef.current
      if (assistantRequestInFlightRef.current || sessionsLoading || pendingSessionIdRef.current ||
        !backendReady || !pendingQuestion || !questionSessionId) {
        return
      }
      const contextRequestIsCurrent = captureRequest()
      const requestIsCurrent = () => contextRequestIsCurrent() &&
        currentSessionIdRef.current === questionSessionId
      assistantRequestInFlightRef.current = true
      const activeQuestion = pendingQuestion
      setPendingQuestion(null)
      setAssistantError(null)
      setRequestPending(true)
      try {
        const result = await callBackend<
          AssistantBackendSuccess | { success: false; message: string }
        >("answer_agent_question", {
          projectId: projectId,
          episodeId: assistantRequestEpisodeId,
          scope: assistantScope,
          question_id: questionId,
          answers,
          workflowId: assistantWorkflowId,
          sessionId: questionSessionId,
        })
        if (!requestIsCurrent()) return
        if (isBackendFailure(result)) {
          throw new Error(result.message || "智能体应答失败")
        }
        const successResult = result as AssistantBackendSuccess
        backendActiveSessionRunningRef.current = true
        commitAssistantResult(successResult)
        if (successResult.projectChanged) {
          await onProjectChanged()
        }
      } catch (error) {
        if (!requestIsCurrent()) return
        const message =
          error instanceof Error ? error.message : "智能体应答失败，请稍后重试"
        setPendingQuestion(activeQuestion)
        setAssistantError(message)
        toast.error(message)
      } finally {
        if (requestIsCurrent()) {
          assistantRequestInFlightRef.current = false
          setRequestPending(false)
        }
      }
    },
    [
      backendReady,
      callBackend,
      commitAssistantResult,
      assistantScope,
      assistantRequestEpisodeId,
      assistantWorkflowId,
      episodeId,
      onProjectChanged,
      pendingQuestion,
      projectId,
      captureRequest,
      sessionsLoading,
    ]
  )

  const handleSend = useCallback(
    async (
      messageOverride?: string,
      options?: {
        sourceSessionId?: string
        preferredAction?: string
        preferredTaskType?: string
        quickPromptId?: string
        controlOnly?: boolean
        displayMessage?: string
        activeTarget?: AgentTargetContext
        taskOptions?: Record<string, unknown>
        candidateRef?: { runId: string; candidateId: string; candidateDigest: string; candidateVersion: number; candidateType?: "asset_range_candidate" }
      }
    ) => {
      const outgoingDraft = prepareSend(messageOverride, options)
      const {
        optimisticText,
        backendMessage,
        preferredTaskType,
        quickPromptId,
        controlOnly,
      } = outgoingDraft
      const sourceSessionId = options?.sourceSessionId ?? currentSessionIdRef.current
      const sourceSession = sessionsRef.current.find((row) => row.id === sourceSessionId)
      // Every user message starts a new round in the ordinary conversation.
      // Canvas task executions are never resumed by follow-up messages.
      const taskConversationId = sourceSession?.canvasTask && !options?.candidateRef
        ? sourceSession.canvasTask.parentSessionId : undefined
      const sendSessionId = taskConversationId ?? sourceSessionId
      const sendSession = sessionsRef.current.find((row) => row.id === sendSessionId)
      const backgroundSend = Boolean(sendSessionId && sendSessionId !== currentSessionIdRef.current)
      if (taskConversationId && isAssistantSessionRunning(sendSession)) {
        toast.info("当前会话正在处理对话，请处理后再继续")
        return
      }
      if (
        assistantRequestInFlightRef.current ||
        sessionsLoading || pendingSessionIdRef.current ||
        (backgroundSend ? isAssistantSessionRunning(sendSession) : composerLocked) ||
        (!backgroundSend && activeSessionRunning && (
          Boolean(outgoingDraft.preferredAction || preferredTaskType || quickPromptId || options?.candidateRef) ||
          outgoingDraft.attachments.length > 0
        )) ||
        (!optimisticText && outgoingDraft.attachments.length === 0)
      ) {
        return
      }
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const requestIsCurrent = captureRequest()
      assistantRequestInFlightRef.current = true
      const outgoingAttachments = outgoingDraft.attachments
      // 只有候选卡按钮携带明确的候选引用。普通文字由后端当前会话状态判定。
      const candidateRef = options?.candidateRef
      const sentAt = new Date()
      const userMessage: AssistantMessage = {
        id: `optimistic-${createLocalId("user")}`,
        role: "user",
        text: optimisticText || "继续执行项目拆分流程",
        createdAt: sentAt.toISOString(),
        attachments: outgoingAttachments,
      }
      if (!backgroundSend) {
        appendAssistantMessage(userMessage)
        setDraftTurn(null)
        setLiveActivity([])
      }
      setAssistantError(null)
      if (!outgoingDraft.override) acceptDraft()
      setRequestPending(true)

      try {
        const result = await callBackend<
          AssistantBackendSuccess | { success: false; message: string }
        >("run_agent_message", {
          projectId: projectId,
          episodeId: assistantRequestEpisodeId,
          scope: assistantScope,
          message: backendMessage,
          displayMessage: controlOnly ? userMessage.text : undefined,
          quickPromptId,
          controlOnly: controlOnly || undefined,
          sessionId: sendSessionId,
          candidateRef,
          workflowId: assistantWorkflowId,
          activeTarget:
            sourceSession?.canvasTask?.target ?? (options && "activeTarget" in options
              ? options.activeTarget
              : effectiveActiveTarget),
          taskOptions: options?.taskOptions,
          preferredAction: outgoingDraft.preferredAction,
          preferredTaskType,
          images: outgoingAttachments.map((item) => ({
            name: item.name,
            mimeType: item.media.mimeType || item.mimeType || "image/png",
            path: item.media.path,
            filePath: item.media.filePath,
            file: item.media.file,
            relativePath: item.media.relativePath,
            relative_path: item.media.relative_path,
          })),
        })
        if (!requestIsCurrent()) return
        if (isBackendFailure(result)) {
          const recordedFailure = result as unknown as Partial<AssistantBackendSuccess>
          if (recordedFailure.snapshot || recordedFailure.session) {
            commitAssistantResult(recordedFailure as AssistantBackendSuccess)
            if (!backgroundSend) setAssistantError(result.message || "智能体执行失败")
            toast.error(result.message || "智能体执行失败")
            return
          }
          throw new Error(result.message || "智能体执行失败")
        }
        const successResult = result as AssistantBackendSuccess
        if (!backgroundSend) backendActiveSessionRunningRef.current = true
        commitAssistantResult(successResult)
        if (successResult.projectChanged) {
          await onProjectChanged()
        }
      } catch (error) {
        if (!requestIsCurrent()) return
        const message =
          error instanceof Error ? error.message : "智能体执行失败，请稍后重试"

        if (!backgroundSend) setAssistantError(message)
        if (!messageOverride) {
          restoreDraft(outgoingDraft)
        }
        setTurns((current) => current.filter((turn) => turn.uuid !== userMessage.id))

        toast.error(message)
      } finally {
        if (requestIsCurrent()) {
          assistantRequestInFlightRef.current = false
          setRequestPending(false)
        }
      }
    },
    [
      appendAssistantMessage,
      backendReady,
      callBackend,
      commitAssistantResult,
      assistantScope,
      assistantRequestEpisodeId,
      assistantWorkflowId,
      episodeId,
      input,
      composerLocked,
      sessionsLoading,
      activeSessionRunning,
      onProjectChanged,
      projectId,
      currentCanvasTask,
      effectiveActiveTarget,
      captureRequest,
      prepareSend,
      acceptDraft,
      restoreDraft,
      turns,
    ]
  )

  // Explicit media actions use the existing provider task pipeline. They do not
  // occupy an Agent turn or change the selected conversation/task progress.
  const handleStartMediaTask = useCallback((taskType: string | undefined, target: AgentTargetContext | null | undefined) => {
    const method = taskType ? CANVAS_MEDIA_METHODS.get(taskType) : undefined
    if (!method || assistantScope !== "episode" || !target?.nodeId ||
      (target.episodeId && target.episodeId !== assistantRequestEpisodeId)) return false
    if (!backendReady || sessionsLoading) return true
    const key = `${assistantContextKey}:${method}:${target.nodeId}`
    if (mediaLaunchesRef.current.has(key)) return true
    mediaLaunchesRef.current.add(key)
    void (async () => {
      try {
        const result = await callBackend<AssistantBackendSuccess | { success: false; message: string }>(method, {
          projectId, episodeId: assistantRequestEpisodeId, nodeId: target.nodeId,
          clientRequestId: createLocalId("canvas-media-task"),
        })
        if (result.success === false) throw new Error(result.message || "创建生成任务失败")
        upsertAssistantReturnedTasks(result, projectId)
        if (!isCurrentContext()) return
        toast.info("生成任务已创建，可在右上角任务栏查看")
      } catch (error) {
        if (isCurrentContext()) toast.error(error instanceof Error ? error.message : "创建生成任务失败")
      } finally {
        mediaLaunchesRef.current.delete(key)
      }
    })()
    return true
  }, [assistantScope, assistantRequestEpisodeId, backendReady, sessionsLoading,
    assistantContextKey, callBackend, projectId, isCurrentContext])

  const handleRecommendationSelect = useCallback(
    (item: AssistantRecommendationItem) => {
      const source = sessionsRef.current.find((row) => row.id === item.sourceSessionId)
      const recommendationTarget = item.targetContext ?? source?.canvasTask?.target ?? effectiveActiveTarget
      const sourceLocked = source && source.id !== currentSessionIdRef.current
        ? requestPending || isAssistantSessionRunning(source) : inputLocked
      if (item.mode === "navigation") {
        if (!sourceLocked && item.destination === "project_session") {
          onOpenProjectConversation()
        }
        return
      }
      const prompt = item.prompt.trim() || item.label.trim()
      if (!prompt) return
      const action = item.action?.trim()
      const taskType = item.taskType?.trim()
      const preferredAction =
        action && (item.controlOnly || assistantProgramActions.has(action))
          ? action
          : undefined
      const preferredTaskType =
        taskType && (item.controlOnly || assistantTaskTypes.has(taskType))
          ? taskType
          : undefined
      const controlOnly = Boolean(
        item.controlOnly && (preferredAction || preferredTaskType)
      )
      const displayMessage = item.label.trim() || prompt
      if (handleStartMediaTask(preferredTaskType, recommendationTarget)) return
      const canvasRequest = assistantScope === "episode" ? canvasAgentRequestForTarget(
        preferredTaskType, recommendationTarget, projectId, assistantRequestEpisodeId,
      ) : null
      if (canvasRequest) {
        void handleStartCanvasTask(canvasRequest)
        return
      }
      void handleSend(prompt, {
        preferredAction,
        preferredTaskType,
        quickPromptId: item.id,
        controlOnly,
        displayMessage: controlOnly ? displayMessage : undefined,
        activeTarget: recommendationTarget ?? undefined,
        sourceSessionId: item.sourceSessionId,
      })
    },
    [assistantProgramActions, assistantTaskTypes, handleSend, inputLocked, requestPending, onOpenProjectConversation,
      assistantScope, effectiveActiveTarget, projectId, assistantRequestEpisodeId, handleStartCanvasTask, handleStartMediaTask]
  )

  const handleQuickPromptSelect = useCallback(
    (prompt: AssistantQuickPrompt) => {
      const message = prompt.prompt.trim()
      if (!message) return
      const taskType = prompt.taskType?.trim()
      const preferredTaskType =
        taskType && (prompt.controlOnly || assistantTaskTypes.has(taskType))
          ? taskType
          : undefined
      const controlOnly = Boolean(
        prompt.controlOnly &&
        (preferredTaskType || isAssistantControlOnlyQuickPromptId(prompt.id))
      )
      const displayMessage = prompt.label.trim() || message
      if (handleStartMediaTask(preferredTaskType, effectiveActiveTarget)) return
      const canvasRequest = assistantScope === "episode" ? canvasAgentRequestForTarget(
        preferredTaskType, effectiveActiveTarget, projectId, assistantRequestEpisodeId,
      ) : null
      if (canvasRequest) {
        void handleStartCanvasTask(canvasRequest)
        return
      }
      void handleSend(message, {
        preferredTaskType,
        quickPromptId: prompt.id,
        controlOnly,
        displayMessage: controlOnly ? displayMessage : undefined,
      })
    },
    [assistantTaskTypes, handleSend, assistantScope, effectiveActiveTarget, projectId,
      assistantRequestEpisodeId, handleStartCanvasTask, handleStartMediaTask]
  )
  return {
    presentationResetKey,
    requestPending,
    pendingQuestion,
    pendingInteractions,
    sessions,
    currentSessionId,
    currentCanvasTask,
    sessionsLoading,
    sessionsLoaded: loadedSessionContextKey === assistantContextKey,
    assistantError,
    turns,
    draftTurn,
    otherRunningSession,
    pendingQuestionWaiting,
    activeSessionRunning,
    completionRenderHolding,
    assistantRuntimeRunning,
    canStopAssistantRuntime,
    inputLocked,
    composerLocked,
    displayedAssistantLiveActivityItems,
    allTurns,
    runningElapsedText,
    handleCreateConversation,
    handleClearConversation,
    handleSwitchSession,
    handleStartCanvasTask,
    handleDeleteSession,
    handleSelectEpisode,
    handleInterruptAssistantRuntime,
    handleQuestionAnswersSubmit,
    handleSend,
    handleRecommendationSelect,
    handleQuickPromptSelect,
  }
}
export type AssistantSessionController = ReturnType<typeof useAssistantSession>
