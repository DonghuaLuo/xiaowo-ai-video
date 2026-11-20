import { useEffect, type RefObject } from "react"

type BackendEventUnsubscribe = (() => void) | void
type BackendEventSubscriber = (
  eventName: string,
  callback: (payload: unknown) => void
) => BackendEventUnsubscribe

type AgentSessionEventPayload = {
  projectId?: string
  project_id?: string
  sessionId?: string
  episodeId?: string
  episode_id?: string
  scope?: string
  contextScope?: string
  context_scope?: string
  sessions?: unknown[]
  snapshot?: {
    sessionId?: string
    session?: {
      id?: string
      episodeId?: string
      episode_id?: string
      scope?: string
      contextScope?: string
      context_scope?: string
    }
  }
  session?: {
    id?: string
    episodeId?: string
    episode_id?: string
    scope?: string
    contextScope?: string
    context_scope?: string
  }
}

type AgentTerminalTaskEventName =
  | "task_completed"
  | "task_failed"
  | "task_cancelled"

type AgentTerminalTaskPayload = {
  executionId?: string
  type?: string
  projectId?: string
  project_id?: string
  sessionId?: string
  task?: AgentTerminalTaskPayload
}

type AgentTerminalTaskEvent = {
  eventName: AgentTerminalTaskEventName
  sessionId: string
  task: AgentTerminalTaskPayload
}

export function useAgentSessionEvents({
  projectId,
  episodeId,
  currentSessionIdRef,
  onBackendEvent,
  onSessions,
  onSnapshot,
  onSession,
  onTerminalTask,
  onAnySession,
}: {
  projectId: string
  episodeId: string
  currentSessionIdRef: RefObject<string | null>
  onBackendEvent: BackendEventSubscriber
  onSessions: (sessions: unknown[]) => void
  onSnapshot: (snapshot: unknown) => void
  onSession: (session: unknown) => void
  onAnySession?: (session: unknown) => void
  onTerminalTask?: (event: AgentTerminalTaskEvent) => void
}) {
  useEffect(() => {
    const applyPayload = (rawPayload: unknown) => {
      if (!rawPayload || typeof rawPayload !== "object") return
      const payload = rawPayload as AgentSessionEventPayload
      if ((payload.projectId ?? payload.project_id) !== projectId) return
      const payloadScope = String(
        payload.scope ??
          payload.contextScope ??
          payload.context_scope ??
          payload.session?.scope ??
          payload.session?.contextScope ??
          payload.session?.context_scope ??
          payload.snapshot?.session?.scope ??
          payload.snapshot?.session?.contextScope ??
          payload.snapshot?.session?.context_scope ??
          ""
      ).trim()
      const payloadEpisodeId = String(
        payload.episodeId ??
          payload.episode_id ??
          payload.session?.episodeId ??
          payload.session?.episode_id ??
          payload.snapshot?.session?.episodeId ??
          payload.snapshot?.session?.episode_id ??
          ""
      ).trim()
      const expectedScope = episodeId === "__project__" ? "project" : "episode"
      if (payloadScope && payloadScope !== expectedScope) return
      if (expectedScope === "episode" && payloadEpisodeId && payloadEpisodeId !== episodeId) return
      if (expectedScope === "project" && !payloadScope &&
          payloadEpisodeId && !["__project__", "project"].includes(payloadEpisodeId)) return

      if (Array.isArray(payload.sessions)) {
        onSessions(payload.sessions)
      }
      const detail = payload.snapshot?.session ?? payload.session
      if (detail) onAnySession?.(detail)

      const activeSessionId = currentSessionIdRef.current

      if (payload.snapshot) {
        const snapshotSessionId = String(
          payload.snapshot.session?.id ||
            payload.snapshot.sessionId ||
            payload.sessionId ||
            ""
        ).trim()
        if (!snapshotSessionId) return
        if (!activeSessionId || snapshotSessionId !== activeSessionId) return
        onSnapshot(payload.snapshot)
        return
      }

      if (!payload.session) return
      const sessionId = String(payload.session.id || "").trim()
      if (!sessionId) return
      if (!activeSessionId || sessionId !== activeSessionId) return
      onSession(payload.session)
    }

    const applyTerminalTaskPayload = (
      rawPayload: unknown,
      eventName: AgentTerminalTaskEventName
    ) => {
      if (!onTerminalTask || !rawPayload || typeof rawPayload !== "object") {
        return
      }
      const payload = rawPayload as AgentTerminalTaskPayload
      const task =
        payload.task && typeof payload.task === "object"
          ? payload.task
          : payload
      const taskType = String(task.type ?? payload.type ?? "").trim()
      if (taskType === "agent_turn") {
        return
      }
      if (
        (task.projectId ?? task.project_id ?? payload.projectId ?? payload.project_id) !==
        projectId
      ) {
        return
      }

      const taskSessionId = String(
        task.sessionId ?? payload.sessionId ?? ""
      ).trim()
      if (!taskSessionId) return
      const activeSessionId = currentSessionIdRef.current
      if (!activeSessionId || taskSessionId !== activeSessionId) return

      onTerminalTask({
        eventName,
        sessionId: taskSessionId,
        task,
      })
    }

    const unsubscribeUpdated = onBackendEvent(
      "agent_session_updated",
      applyPayload
    )
    const unsubscribeSnapshot = onBackendEvent(
      "agent_session_snapshot",
      applyPayload
    )
    const unsubscribeTaskCompleted = onBackendEvent(
      "task_completed",
      (payload) => applyTerminalTaskPayload(payload, "task_completed")
    )
    const unsubscribeTaskFailed = onBackendEvent(
      "task_failed",
      (payload) => applyTerminalTaskPayload(payload, "task_failed")
    )
    const unsubscribeTaskCancelled = onBackendEvent(
      "task_cancelled",
      (payload) => applyTerminalTaskPayload(payload, "task_cancelled")
    )
    return () => {
      unsubscribeUpdated?.()
      unsubscribeSnapshot?.()
      unsubscribeTaskCompleted?.()
      unsubscribeTaskFailed?.()
      unsubscribeTaskCancelled?.()
    }
  }, [
    currentSessionIdRef,
    onBackendEvent,
    onSession,
    onSessions,
    onSnapshot,
    onTerminalTask,
    onAnySession,
    episodeId,
    projectId,
  ])
}
