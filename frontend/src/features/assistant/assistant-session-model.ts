import type { ProjectEpisodeEntry } from "@/features/workspace/episodes"
import { AssistantConversationScope } from "./assistant-session-normalization"

export const ASSISTANT_COMPLETION_RENDER_HOLD_FALLBACK_MS = 5000

export const ASSISTANT_COMPLETION_RENDER_POLL_MS = 400

export const ASSISTANT_LAST_SESSION_STORAGE_KEY =
  "ai_video_assistant_last_session_by_context"

export function getAssistantEpisodeTitle(
  episode: ProjectEpisodeEntry | undefined,
  fallbackId: string
) {
  return episode?.title?.trim() || episode?.id || fallbackId || "当前绘画"
}

export function assistantSessionContextKey(
  projectId: string,
  scope: AssistantConversationScope,
  episodeId: string
) {
  return `${projectId}:${scope}:${scope === "episode" ? episodeId || "E01" : "project"}`
}

export function readLastAssistantSessionId(contextKey: string) {
  if (typeof window === "undefined") return null
  try {
    const raw = window.localStorage.getItem(ASSISTANT_LAST_SESSION_STORAGE_KEY)
    const data = raw ? (JSON.parse(raw) as Record<string, unknown>) : {}
    const value = data[contextKey]
    return typeof value === "string" && value ? value : null
  } catch {
    return null
  }
}

export function writeLastAssistantSessionId(contextKey: string, sessionId: string) {
  if (typeof window === "undefined" || !sessionId) return
  try {
    const raw = window.localStorage.getItem(ASSISTANT_LAST_SESSION_STORAGE_KEY)
    const data = raw ? (JSON.parse(raw) as Record<string, unknown>) : {}
    data[contextKey] = sessionId
    window.localStorage.setItem(ASSISTANT_LAST_SESSION_STORAGE_KEY, JSON.stringify(data))
  } catch {
    // ignore
  }
}

export function clearLastAssistantSessionId(contextKey: string, sessionId: string) {
  if (typeof window === "undefined" || !sessionId) return
  try {
    const raw = window.localStorage.getItem(ASSISTANT_LAST_SESSION_STORAGE_KEY)
    const data = raw ? (JSON.parse(raw) as Record<string, unknown>) : {}
    if (data[contextKey] === sessionId) {
      delete data[contextKey]
      window.localStorage.setItem(
        ASSISTANT_LAST_SESSION_STORAGE_KEY,
        JSON.stringify(data)
      )
    }
  } catch {
    // ignore
  }
}
