import { AssistantComposer } from "./assistant-composer"
import { useAssistantSession } from "./use-assistant-session"
import { AssistantTimeline } from "./assistant-timeline"
import { useAssistantComposer } from "./use-assistant-composer"
import { useAssistantModelSelection } from "./use-assistant-model-selection"
import { useAssistantPanelLayout } from "./assistant-panel-layout"
import { AssistantErrorLogs } from "./assistant-error-logs"

import { AssistantDispatchPanel } from "./assistant-dispatch-panel"
import { AssistantCanvasTasks } from "./assistant-canvas-tasks"
import { canvasConversationActivity } from "./assistant-canvas-task-model"
import { AssistantPendingOperationCard } from "./assistant-pending-operation-card"
import { pendingDecisionSendOptions } from "./assistant-pending-decision"
import { formatAssistantSessionDateTime } from "./assistant-message-model"

import {
  getAssistantEpisodeTitle,
  assistantSessionContextKey,
} from "./assistant-session-model"
import { AssistantPendingQuestionWizard } from "./assistant-question-wizard"
import {
  ASSISTANT_PANEL_MIN_WIDTH,
  ASSISTANT_PANEL_MAX_WIDTH,
} from "./assistant-panel-layout"
import { Fragment, useEffect, useMemo, useRef, useState } from "react"
import {
  ArrowUpRight,
  Bot,
  ChevronRight,
  CheckCircle2,
  Film,
  History,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react"

import { type AgentTargetContext } from "@/backend"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import type { ProjectRow } from "@/features/projects/types"
import { buildProjectEpisodes, episodeStatusLabel } from "@/features/workspace/episodes"
import { ICON_GHOST_BTN_CLS } from "@/shared/button-styles"

import { TooltipWrap } from "@/shared/tooltip-wrap"
import { ConfirmDialog } from "@/shared/confirm-dialog"

import {
  AssistantConversationScope,
  assistantSessionScopeLabel,
} from "./assistant-session-normalization"
import type { WorkspaceSection } from "@/navigation"
import type { CanvasAgentTaskRequest } from "./assistant-task-request"

export function AssistantPanel({
  project,
  episodeId,
  canvasTitle,
  scope = "episode",
  collapsed,
  onCollapsedChange,
  activeTarget = null,
  canvasAgentTaskRequest = null,
  onCanvasAgentTaskRequestHandled,
  onNavigate,
  onOpenProjectConversation,
  onProjectChanged,
}: {
  project: ProjectRow
  episodeId: string
  canvasTitle?: string
  scope?: AssistantConversationScope
  collapsed: boolean
  onCollapsedChange: (collapsed: boolean) => void
  activeTarget?: AgentTargetContext | null
  canvasAgentTaskRequest?: CanvasAgentTaskRequest | null
  onCanvasAgentTaskRequestHandled?: (requestId: number) => void
  onNavigate: (section: WorkspaceSection, episodeId?: string) => void
  onOpenProjectConversation: () => void
  onProjectChanged: () => Promise<void>
}) {
  const { backendReady, callBackend, onBackendEvent } = useBackend()
  const assistantModelSelection = useAssistantModelSelection({
    projectId: project.id,
    backendReady,
    callBackend,
    onBackendEvent,
  })
  const assistantScope: AssistantConversationScope =
    scope === "project" ? "project" : "episode"
  const {
    updateCollapsed,
    isResizingPanel,
    displayedPanelWidth,
    handleResizeMouseDown,
    handleResizeDoubleClick,
  } = useAssistantPanelLayout(onCollapsedChange)
  const projectEpisodes = useMemo(() => buildProjectEpisodes(project), [project.episodes])
  const assistantStepsEpisodeId =
    episodeId || project.currentEpisodeId || projectEpisodes[0]?.id || "E01"
  const scopedEpisodeId = assistantScope === "episode" ? episodeId : ""
  const sessionFilterEpisodeId = assistantScope === "episode" ? episodeId : "__project__"
  const assistantRequestEpisodeId =
    assistantScope === "episode" ? episodeId : "__project__"
  const assistantWorkflowId =
    assistantScope === "episode"
      ? `episode:${episodeId}:workflow`
      : `project:${project.id}`
  const scopedActiveTarget = useMemo<AgentTargetContext | null>(() => {
    if (!activeTarget) return null
    if (assistantScope === "project") {
      if (activeTarget.section === "episode") {
        return null
      }
      const projectTarget = { ...activeTarget }
      delete projectTarget.episodeId
      delete projectTarget.canvasKind
      delete projectTarget.canvasId
      delete projectTarget.canvasTitle
      delete projectTarget.nodeId
      delete projectTarget.nodeType
      delete projectTarget.routeId
      delete projectTarget.segmentId
      delete projectTarget.workChainId
      return projectTarget
    }
    if (activeTarget.section !== "episode") {
      return null
    }
    return activeTarget
  }, [activeTarget, assistantScope])
  const activeEpisodeEntry = useMemo(
    () =>
      projectEpisodes.find((episode) => episode.id === assistantStepsEpisodeId) ??
      projectEpisodes[0],
    [assistantStepsEpisodeId, projectEpisodes]
  )
  const activeEpisodeTitle =
    assistantScope === "project"
      ? "项目会话"
      : canvasTitle || getAssistantEpisodeTitle(activeEpisodeEntry, episodeId)
  const assistantContextKey = assistantSessionContextKey(
    project.id,
    assistantScope,
    scopedEpisodeId
  )
  const composer = useAssistantComposer({
    projectId: project.id,
    episodeId,
    assistantScope,
    assistantRequestEpisodeId,
    assistantWorkflowId,
    backendReady,
    callBackend,
    scopeKey: assistantContextKey,
  })
  const session = useAssistantSession({
    context: {
      projectId: project.id,
      episodeId,
      assistantScope,
      sessionFilterEpisodeId,
      assistantRequestEpisodeId,
      assistantWorkflowId,
      scopedActiveTarget,
      assistantContextKey,
    },
    backendReady,
    callBackend,
    onBackendEvent,
    composer,
    onNavigate,
    onOpenProjectConversation,
    onProjectChanged,
  })
  const {
    presentationResetKey,
    requestPending,
    pendingQuestion,
    pendingInteractions,
    sessions,
    currentSessionId,
    sessionsLoading,
    sessionsLoaded,
    assistantError,
    otherRunningSession,
    pendingQuestionWaiting,
    activeSessionRunning,
    completionRenderHolding,
    assistantRuntimeRunning,
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
    handleQuestionAnswersSubmit,
    handleSend,
    handleRecommendationSelect,
  } = session
  const conversationSessionId = session.currentCanvasTask?.parentSessionId ?? currentSessionId
  const conversationActivity = useMemo(() => canvasConversationActivity(sessions), [sessions])
  const selectedSession = sessions.find((item) => item.id === currentSessionId)
  const selectedWaiting = selectedSession && !["error", "interrupted"].includes(selectedSession.status) &&
    Boolean(selectedSession.waitingForInput || selectedSession.waitingForConfirmation || selectedSession.pendingCandidateCount)
  const backgroundWaitingCount = [...conversationActivity.values()].reduce((count, activity) =>
    count + activity.waitingForInputCount + activity.waitingForConfirmationCount, 0) - Number(Boolean(selectedWaiting))
  const [deleteSessionDraft, setDeleteSessionDraft] = useState<{
    contextKey: string
    sessionId: string | null
    title: string
  } | null>(null)
  const [deleteSessionLoading, setDeleteSessionLoading] = useState(false)
  const handledCanvasAgentTaskRequestRef = useRef<number | null>(null)
  useEffect(() => setDeleteSessionDraft(null), [assistantContextKey])
  useEffect(() => {
    const request = canvasAgentTaskRequest
    if (!request || handledCanvasAgentTaskRequestRef.current === request.requestId) return
    if (request.projectId !== project.id) {
      handledCanvasAgentTaskRequestRef.current = request.requestId
      onCanvasAgentTaskRequestHandled?.(request.requestId)
      return
    }
    if (assistantScope !== "episode" || episodeId !== request.episodeId) return
    if (!backendReady || !sessionsLoaded || sessionsLoading) return
    handledCanvasAgentTaskRequestRef.current = request.requestId
    onCanvasAgentTaskRequestHandled?.(request.requestId)
    updateCollapsed(false)
    void handleStartCanvasTask(request)
  }, [canvasAgentTaskRequest, project.id, assistantScope, episodeId, backendReady,
    sessionsLoaded, sessionsLoading, onCanvasAgentTaskRequestHandled,
    handleStartCanvasTask, updateCollapsed])
  const pendingInteractionWaiting = pendingInteractions.some((item) =>
    item.active && item.sessionId === currentSessionId &&
    !["committing", "commit_unknown"].includes(item.operationStatus)
  )

  const assistantRunningActivityLabel = completionRenderHolding
    ? "正在显示最终回复"
    : displayedAssistantLiveActivityItems[displayedAssistantLiveActivityItems.length - 1]
        ?.text || "等待智能体返回实时执行事件"
  const assistantHeaderSubtitle = requestPending
    ? `正在发送：${activeEpisodeTitle}`
    : pendingQuestionWaiting
      ? `等待补充：${activeEpisodeTitle}`
      : activeSessionRunning
        ? `正在处理：${assistantRunningActivityLabel} · ${activeEpisodeTitle}`
        : pendingInteractionWaiting
          ? `等待确认：${activeEpisodeTitle}`
          : `${activeEpisodeTitle} · 可直接输入消息或 / 技能`

  const panelHandleClassName =
    "absolute top-3 -left-3 z-20 size-6 rounded-lg border border-gray-200/80 bg-white/90 text-gray-500 shadow-sm backdrop-blur transition-colors hover:border-indigo-500 hover:bg-indigo-500 hover:text-white dark:border-white/10 dark:bg-[#24242a]/95 dark:text-gray-400 dark:hover:border-white/15 dark:hover:bg-white/10 dark:hover:text-gray-100"

  if (collapsed) {
    return (
      <aside className="ai-video-edge-x relative w-12 shrink-0 border-x border-gray-200/70 bg-white/45 dark:border-r-0 dark:border-white/10 dark:bg-white/[0.035]">
        <div className="flex h-full flex-col items-center gap-3 py-4">
          <TooltipWrap content="展开助手">
            <button
              type="button"
              className="grid size-9 place-items-center rounded-lg bg-gradient-to-r from-indigo-600 via-sky-600 to-emerald-500 text-white shadow-sm transition hover:scale-[1.03] hover:shadow-md focus-visible:ring-2 focus-visible:ring-indigo-400/60 focus-visible:outline-none"
              aria-label="展开助手"
              onClick={() => updateCollapsed(false)}
            >
              <Bot className="size-4" />
            </button>
          </TooltipWrap>
        </div>
      </aside>
    )
  }

  return (
    <aside
      className={cn(
        "ai-video-edge-x relative shrink-0 border-x border-gray-200/70 bg-white/45 dark:border-r-0 dark:border-white/10 dark:bg-white/[0.035]",
        isResizingPanel ? "" : "transition-[width] duration-200 ease-out"
      )}
      style={{ width: displayedPanelWidth }}
    >
      <TooltipWrap content="调整助手面板宽度，双击恢复默认">
        <div
          role="separator"
          aria-orientation="vertical"
          aria-valuemin={ASSISTANT_PANEL_MIN_WIDTH}
          aria-valuemax={ASSISTANT_PANEL_MAX_WIDTH}
          aria-valuenow={displayedPanelWidth}
          aria-label="调整助手面板宽度，双击恢复默认"
          onMouseDown={handleResizeMouseDown}
          onDoubleClick={handleResizeDoubleClick}
          className="group absolute inset-y-0 left-0 z-10 w-1 -translate-x-1/2 cursor-col-resize select-none"
        >
          <div
            className={cn(
              "absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors duration-150",
              isResizingPanel
                ? "bg-indigo-500"
                : "bg-transparent group-hover:bg-indigo-500"
            )}
          />
        </div>
      </TooltipWrap>
      <TooltipWrap content="收起助手">
        <Button
          variant="ghost"
          size="icon-sm"
          className={panelHandleClassName}
          aria-label="收起助手"
          onClick={() => updateCollapsed(true)}
        >
          <ChevronRight className="size-3.5" />
        </Button>
      </TooltipWrap>
      <div className="relative isolate flex h-full flex-col">
        <div className="ai-video-edge-b flex h-14 shrink-0 items-center gap-2 border-b border-gray-200/70 bg-white/70 px-3 shadow-sm backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.035]">
          <div className="flex min-w-0 flex-1 items-center gap-2.5">
            <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-gradient-to-r from-indigo-600 via-sky-600 to-emerald-500 text-white shadow-sm">
              <Bot className="size-3.5" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
                  智能体
                </span>
                {assistantRuntimeRunning ? (
                  <span className="flex shrink-0 items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-[10.5px] whitespace-nowrap text-indigo-600 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-200">
                    <span className="size-1.5 animate-pulse rounded-full bg-indigo-500" />
                    思考中
                  </span>
                ) : null}
              </div>
              <p className="mt-0.5 truncate text-[11px] leading-none text-gray-500 dark:text-gray-400">
                {assistantHeaderSubtitle}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <AssistantErrorLogs
              projectId={project.id}
              backendReady={backendReady}
              callBackend={callBackend}
              activeSessionRunning={activeSessionRunning}
            />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className={cn(ICON_GHOST_BTN_CLS, "relative")}
                  title={backgroundWaitingCount ? `智能体会话列表 · ${backgroundWaitingCount} 项待处理` : "智能体会话列表"}
                  disabled={sessionsLoading}
                >
                  <History className="size-3.5" />
                  {backgroundWaitingCount > 0 && (
                    <span aria-label={`${backgroundWaitingCount} 项后台任务待处理`} className="absolute right-0.5 top-0.5 size-1.5 rounded-full bg-amber-500" />
                  )}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="end"
                className="z-[11000] max-h-[calc(100vh-9rem)] w-80 overflow-y-auto rounded-lg border-gray-200/80 bg-white/95 p-1.5 shadow-xl shadow-gray-950/10 dark:border-white/10 dark:bg-[#24242a]"
              >
                <DropdownMenuLabel className="px-2.5 py-2 font-mono text-[11px] tracking-[0.14em] text-gray-400 uppercase dark:text-gray-500">
                  智能体会话
                </DropdownMenuLabel>
                <DropdownMenuSeparator className="bg-gray-200/70 dark:bg-white/10" />
                {sessions.length === 0 ? (
                  <div className="px-2.5 py-3 text-[11.5px] text-gray-500 dark:text-gray-400">
                    还没有保存的会话，发送第一条消息后会自动创建。
                  </div>
                ) : (
                  sessions.filter((item) => !item.canvasTask).map((session) => {
                    const active = session.id === conversationSessionId
                    const activity = conversationActivity.get(session.id)
                    const waiting = Boolean(activity && (activity.waitingForInputCount || activity.waitingForConfirmationCount))
                    const soleTask = activity?.activeTasks.length === 1 ? activity.activeTasks[0] : null
                    return (
                      <Fragment key={session.id}>
                      <DropdownMenuItem
                        className={cn(
                          "cursor-pointer items-start gap-3 rounded-lg px-2.5 py-2 focus:bg-indigo-50 focus:text-indigo-700 dark:focus:bg-indigo-950/30 dark:focus:text-indigo-100",
                          active
                            ? "bg-indigo-50/80 text-indigo-700 dark:bg-indigo-950/20 dark:text-indigo-100"
                            : ""
                        )}
                        disabled={sessionsLoading}
                        onSelect={() => void handleSwitchSession(session.id, { resumeTask: false })}
                      >
                        <span
                          className={cn(
                            "mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full",
                            waiting
                              ? "bg-amber-500"
                              : activity?.runningCount
                              ? "bg-indigo-500"
                              : session.status === "completed"
                                ? "bg-emerald-500"
                                : session.status === "error"
                                  ? "bg-rose-500"
                                  : session.status === "interrupted"
                                    ? "bg-amber-400"
                                    : "bg-gray-300 dark:bg-gray-600"
                          )}
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[12px] font-medium text-gray-700 dark:text-gray-100">
                            {session.title}
                          </span>
                          <span className="mt-0.5 block truncate text-[11px] text-gray-500 dark:text-gray-400">
                            {assistantSessionScopeLabel(session.episodeId)} ·{" "}
                            {formatAssistantSessionDateTime(
                              session.updatedAt || session.createdAt
                            )}
                          </span>
                          {session.pendingCandidateCount ? (
                            <span className="mt-1 block text-[10.5px] text-amber-600 dark:text-amber-300">
                              {session.pendingCandidateCount} 个候选待处理
                            </span>
                          ) : null}
                          {activity && (activity.runningCount > 0 || waiting) && (
                            <span className={cn("mt-1 block text-[10.5px]", waiting ? "text-amber-600 dark:text-amber-300" : "text-indigo-600 dark:text-indigo-300")}>
                              {[
                                activity.runningCount ? `${activity.runningCount} 项执行中` : "",
                                activity.waitingForInputCount ? `${activity.waitingForInputCount} 项待回答` : "",
                                activity.waitingForConfirmationCount ? `${activity.waitingForConfirmationCount} 项待确认` : "",
                              ].filter(Boolean).join(" · ")}
                            </span>
                          )}
                        </span>
                        <button
                          type="button"
                          className="grid size-6 shrink-0 place-items-center rounded-lg text-gray-300 transition hover:bg-rose-50 hover:text-rose-500 dark:text-gray-600 dark:hover:bg-rose-950/25 dark:hover:text-rose-300"
                          disabled={requestPending || session.status === "running" || Boolean(activity?.activeTasks.length)}
                          onClick={(event) => {
                            event.preventDefault()
                            event.stopPropagation()
                            setDeleteSessionDraft({ contextKey: assistantContextKey, sessionId: session.id, title: session.title })
                          }}
                          aria-label={`删除会话 ${session.title}`}
                        >
                          <Trash2 className="size-3.5" />
                        </button>
                      </DropdownMenuItem>
                      {soleTask && (
                        <DropdownMenuItem
                          disabled={sessionsLoading}
                          onSelect={() => void handleSwitchSession(soleTask.id)}
                          className="ml-5 cursor-pointer gap-2 rounded-lg text-[11px]"
                        >
                          <Loader2 className="size-3.5 shrink-0 animate-spin text-indigo-500" />
                          <span className="truncate" title={soleTask.title}>{soleTask.title}</span>
                          <span className="ml-auto shrink-0 text-[10px] text-gray-500">
                            执行中
                          </span>
                        </DropdownMenuItem>
                      )}
                      </Fragment>
                    )
                  })
                )}
              </DropdownMenuContent>
            </DropdownMenu>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className={ICON_GHOST_BTN_CLS}
                  title="当前绘画列表"
                >
                  <Film className="size-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="end"
                className="z-[11000] max-h-[calc(100vh-9rem)] w-72 overflow-y-auto rounded-lg border-gray-200/80 bg-white/95 p-1.5 shadow-xl shadow-gray-950/10 dark:border-white/10 dark:bg-[#24242a]"
              >
                <DropdownMenuLabel className="px-2.5 py-2 font-mono text-[11px] tracking-[0.14em] text-gray-400 uppercase dark:text-gray-500">
                  当前绘画列表
                </DropdownMenuLabel>
                <DropdownMenuSeparator className="bg-gray-200/70 dark:bg-white/10" />
                {projectEpisodes.map((episode) => {
                  const active = episode.id === episodeId
                  return (
                    <DropdownMenuItem
                      key={episode.id}
                      className="cursor-pointer items-start gap-3 rounded-lg px-2.5 py-2 focus:bg-indigo-50 focus:text-indigo-700 dark:focus:bg-indigo-950/30 dark:focus:text-indigo-100"
                      onSelect={() => handleSelectEpisode(episode.id)}
                    >
                      <span
                        className={cn(
                          "mt-0.5 grid h-6 min-w-10 shrink-0 place-items-center rounded-lg border px-2 font-mono text-[10.5px] font-semibold",
                          active
                            ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200"
                            : "border-gray-200/80 bg-white/80 text-gray-500 dark:border-white/10 dark:bg-white/[0.04] dark:text-gray-400"
                        )}
                      >
                        {episode.id}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[12px] font-medium text-gray-700 dark:text-gray-100">
                          {episode.title}
                        </span>
                        <span className="mt-0.5 block truncate text-[11px] text-gray-500 dark:text-gray-400">
                          {episodeStatusLabel(episode.status)}
                        </span>
                      </span>
                      {active ? (
                        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-500" />
                      ) : (
                        <ArrowUpRight className="mt-0.5 size-4 shrink-0 text-gray-300 dark:text-gray-600" />
                      )}
                    </DropdownMenuItem>
                  )
                })}
              </DropdownMenuContent>
            </DropdownMenu>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className={ICON_GHOST_BTN_CLS}
                  aria-label="会话操作"
                  title="会话操作"
                >
                  <Plus className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="end"
                className="z-[11000] max-h-[calc(100vh-9rem)] w-44 overflow-y-auto rounded-lg border-gray-200/80 bg-white/95 p-1.5 shadow-xl shadow-gray-950/10 dark:border-white/10 dark:bg-[#24242a]"
              >
                <DropdownMenuItem
                  className="cursor-pointer rounded-lg px-2.5 py-2 text-gray-700 focus:bg-gray-100 focus:text-gray-900 dark:text-gray-100 dark:focus:bg-white/10 dark:focus:text-white"
                  disabled={sessionsLoading}
                  onSelect={handleCreateConversation}
                >
                  <Plus className="size-3.5" />
                  新建会话
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="cursor-pointer rounded-lg px-2.5 py-2 text-rose-600 focus:bg-rose-50 focus:text-rose-700 dark:text-rose-200 dark:focus:bg-rose-950/35 dark:focus:text-rose-100"
                  disabled={requestPending || activeSessionRunning || Boolean(conversationActivity.get(conversationSessionId ?? "")?.activeTasks.length)}
                  onSelect={() => setDeleteSessionDraft({
                    contextKey: assistantContextKey,
                    sessionId: conversationSessionId,
                    title: sessions.find((item) => item.id === conversationSessionId)?.title || "当前会话",
                  })}
                >
                  <Trash2 className="size-3.5" />
                  {currentSessionId ? "删除当前会话" : "清空会话"}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        <AssistantCanvasTasks
          sessions={sessions}
          currentSessionId={currentSessionId}
          loading={sessionsLoading}
          onSelect={(id) => void handleSwitchSession(id)}
        />

        {otherRunningSession && !otherRunningSession.canvasTask ? (
          <div className="border-b border-amber-200 bg-amber-50/80 px-3 py-2 text-[11px] leading-[1.5] text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-200">
            {`当前还有会话「${otherRunningSession.title}」正在执行。切回后仍会看到它的运行状态。`}
          </div>
        ) : null}

        <AssistantTimeline
          allTurns={allTurns}
          currentSessionId={currentSessionId}
          pendingInteractions={pendingInteractions}
          sessionsLoading={sessionsLoading}
          backendReady={backendReady}
          inputLocked={inputLocked}
          handleSend={handleSend}
          handleRecommendationSelect={handleRecommendationSelect}
          resetKey={presentationResetKey}
        />

        <AssistantDispatchPanel
          sessionKey={`${assistantContextKey}:${currentSessionId ?? ""}:${sessions.find((item) => item.id === currentSessionId)?.execution?.id ?? ""}`}
          taskTitle={session.currentCanvasTask ? sessions.find((item) => item.id === currentSessionId)?.title : undefined}
          active={assistantRuntimeRunning}
          waitingForInput={pendingQuestionWaiting}
          items={displayedAssistantLiveActivityItems}
          elapsedText={runningElapsedText}
          resetKey={presentationResetKey}
        />

        {pendingInteractions.filter((item) => item.sessionId === currentSessionId &&
          (!item.active || !["episode_boundary", "asset_range"].includes(item.kind))).map((interaction) => (
          <AssistantPendingOperationCard
            key={`${interaction.operationType}:${interaction.createdAt}:${interaction.candidateId}`}
            interaction={interaction}
            disabled={inputLocked || !backendReady}
            onDecision={(decision) => void handleSend(
              decision === "confirm" ? interaction.title : "取消这次操作",
              pendingDecisionSendOptions(interaction, decision)
            )}
          />
        ))}

        {pendingQuestion ? (
          <AssistantPendingQuestionWizard
            pendingQuestion={pendingQuestion}
            disabled={!backendReady || sessionsLoading}
            submitting={requestPending}
            onSubmit={(questionId, answers) =>
              void handleQuestionAnswersSubmit(questionId, answers)
            }
          />
        ) : null}

        {!pendingQuestion && assistantError ? (
          <div
            role="alert"
            aria-live="assertive"
            className="border-t border-rose-200 bg-rose-50/85 px-3 py-2 text-[11.5px] leading-[1.5] text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/20 dark:text-rose-100"
          >
            {assistantError}
          </div>
        ) : null}

        <AssistantComposer
          composer={composer}
          session={{ ...session, inputLocked: composerLocked }}
          backendReady={backendReady}
          modelSelection={assistantModelSelection}
        />
      </div>
      <ConfirmDialog
        open={Boolean(deleteSessionDraft && deleteSessionDraft.contextKey === assistantContextKey)}
        title={deleteSessionDraft?.sessionId ? "删除智能体会话" : "清空当前会话"}
        description={deleteSessionDraft?.sessionId
          ? `确认删除「${deleteSessionDraft.title}」及其聊天记录和待确认任务？项目创作数据不会因此删除。`
          : "确认清空当前未保存的会话内容？"}
        confirmLabel={deleteSessionDraft?.sessionId ? "确认删除" : "确认清空"}
        loadingLabel="处理中"
        loading={deleteSessionLoading}
        onCancel={() => { if (!deleteSessionLoading) setDeleteSessionDraft(null) }}
        onConfirm={async () => {
          if (!deleteSessionDraft || deleteSessionDraft.contextKey !== assistantContextKey) return
          setDeleteSessionLoading(true)
          try {
            if (deleteSessionDraft.sessionId) {
              if (await handleDeleteSession(deleteSessionDraft.sessionId)) setDeleteSessionDraft(null)
            } else {
              handleClearConversation()
              setDeleteSessionDraft(null)
            }
          } finally {
            setDeleteSessionLoading(false)
          }
        }}
      />
    </aside>
  )
}
