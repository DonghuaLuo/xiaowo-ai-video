import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { BackendCaller } from "@/backend"
import {
  acceptsAssistantSessionVersion,
  assistantMessageToTurn,
  normalizeAssistantSessionDetail,
  type AssistantSessionDetail,
  type AssistantSessionSummary,
  type AssistantTurn,
} from "./assistant-session-normalization"
import { composeCanvasConversationTurns } from "./assistant-canvas-task-model"

// Task selection changes the progress panel. Completed messages always come
// from the task's ordinary conversation, never from separate task histories.
export function useAssistantCanvasTimeline({
  contextKey, projectId, episodeId, backendReady, callBackend,
  sessions, currentSessionId, currentTurns,
}: {
  contextKey: string
  projectId: string
  episodeId: string
  backendReady: boolean
  callBackend: BackendCaller
  sessions: AssistantSessionSummary[]
  currentSessionId: string | null
  currentTurns: AssistantTurn[]
}) {
  const scopeRef = useRef({ key: contextKey, active: true, pending: new Set<string>() })
  if (scopeRef.current.key !== contextKey)
    scopeRef.current = { key: contextKey, active: true, pending: new Set() }
  const scope = scopeRef.current
  const [cache, setCache] = useState(new Map<string, AssistantSessionDetail>())
  useEffect(() => {
    scope.active = true
    return () => { scope.active = false }
  }, [scope])
  const rememberSession = useCallback((raw: AssistantSessionDetail) => {
    if (scopeRef.current !== scope || !scope.active) return
    const detail = normalizeAssistantSessionDetail(raw)
    if (detail.episodeId !== episodeId || detail.canvasTask) return
    const key = `${contextKey}:${detail.id}`
    setCache((previous) => {
      if (!acceptsAssistantSessionVersion(detail, previous.get(key), true)) return previous
      const next = new Map(previous)
      next.set(key, detail)
      return next
    })
  }, [contextKey, episodeId, scope])
  const selected = sessions.find((row) => row.id === currentSessionId)
  const parentId = selected?.canvasTask?.parentSessionId
  const parent = sessions.find((row) => row.id === parentId)
  const saved = parentId ? cache.get(`${contextKey}:${parentId}`) : undefined
  useEffect(() => {
    if (!backendReady || !parent || (saved &&
        (saved.stateRevision ?? 0) >= (parent.stateRevision ?? 0))) return
    const requestKey = `${parent.id}:${parent.stateRevision ?? 0}`
    if (scope.pending.has(requestKey)) return
    scope.pending.add(requestKey)
    void callBackend<{ success?: boolean; session?: AssistantSessionDetail; message?: string }>(
      "get_agent_session", { projectId, episodeId, scope: "episode", sessionId: parent.id },
    ).then((result) => {
      if (result.success === false || !result.session)
        throw new Error(result.message || "读取会话消息失败")
      rememberSession(result.session)
    }).catch((error) => console.warn("读取会话消息失败:", error))
      .finally(() => scope.pending.delete(requestKey))
  }, [backendReady, parent, saved, currentSessionId, projectId, episodeId, callBackend, rememberSession, scope])
  const savedTurns = useMemo(() => new Map(
    saved ? [[saved.id, saved.messages.map(assistantMessageToTurn)]] : [],
  ), [saved])
  return {
    rememberSession,
    allTurns: composeCanvasConversationTurns(sessions, currentSessionId, currentTurns, savedTurns),
  }
}
