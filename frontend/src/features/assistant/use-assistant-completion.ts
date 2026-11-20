import {
  ASSISTANT_COMPLETION_RENDER_HOLD_FALLBACK_MS,
  ASSISTANT_COMPLETION_RENDER_POLL_MS,
} from "./assistant-session-model"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  hasAssistantResponseAfterUserTurn,
  latestAssistantTurnSignature,
  latestUserTurnSignature,
} from "./assistant-session-normalization"
import type { AssistantTurn } from "./assistant-session-normalization"
export function useAssistantCompletion({
  currentSessionId,
  pendingQuestionWaiting,
  currentSessionFinished,
  turns,
  refreshSnapshot,
}: {
  currentSessionId: string | null
  pendingQuestionWaiting: boolean
  currentSessionFinished: boolean
  turns: AssistantTurn[]
  refreshSnapshot: (sessionId: string) => void
}) {
  const [completionRenderHold, setCompletionRenderHold] = useState<{
    sessionId: string
    token: number
    initialResponseSignature: string
    userTurnSignature: string
    startedAt: number
  } | null>(null)

  const completionRenderHoldTokenRef = useRef(0)

  const latestAssistantResponseSignatureRef = useRef("")

  const latestUserTurnSignatureRef = useRef("")

  const completionRenderHolding = Boolean(
    completionRenderHold &&
    completionRenderHold.sessionId === currentSessionId &&
    !pendingQuestionWaiting &&
    !currentSessionFinished
  )

  const latestAssistantResponseSignature = useMemo(
    () => latestAssistantTurnSignature(turns),
    [turns]
  )

  const latestUserResponseSignature = useMemo(
    () => latestUserTurnSignature(turns),
    [turns]
  )

  useEffect(() => {
    latestAssistantResponseSignatureRef.current = latestAssistantResponseSignature
  }, [latestAssistantResponseSignature])

  useEffect(() => {
    latestUserTurnSignatureRef.current = latestUserResponseSignature
  }, [latestUserResponseSignature])

  useEffect(() => {
    if (!completionRenderHold) return
    if (completionRenderHold.sessionId !== currentSessionId) {
      setCompletionRenderHold(null)
      return
    }
    const token = completionRenderHold.token
    const responseReady = completionRenderHold.userTurnSignature
      ? hasAssistantResponseAfterUserTurn(turns, completionRenderHold.userTurnSignature)
      : Boolean(latestAssistantResponseSignature) &&
        latestAssistantResponseSignature !== completionRenderHold.initialResponseSignature
    if (!responseReady) {
      const elapsedMs = Date.now() - completionRenderHold.startedAt
      const fallbackDelay = Math.max(
        0,
        ASSISTANT_COMPLETION_RENDER_HOLD_FALLBACK_MS - elapsedMs
      )
      void refreshSnapshot(completionRenderHold.sessionId)
      const pollTimer = window.setInterval(() => {
        void refreshSnapshot(completionRenderHold.sessionId)
      }, ASSISTANT_COMPLETION_RENDER_POLL_MS)
      const fallbackTimer = window.setTimeout(() => {
        setCompletionRenderHold((current) => (current?.token === token ? null : current))
      }, fallbackDelay)
      return () => {
        window.clearInterval(pollTimer)
        window.clearTimeout(fallbackTimer)
      }
    }
    let frame = 0
    let secondFrame = 0
    let timer = 0
    frame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => {
        timer = window.setTimeout(() => {
          setCompletionRenderHold((current) =>
            current?.token === token ? null : current
          )
        }, 160)
      })
    })
    return () => {
      window.cancelAnimationFrame(frame)
      window.cancelAnimationFrame(secondFrame)
      window.clearTimeout(timer)
    }
  }, [completionRenderHold, currentSessionId, latestAssistantResponseSignature, turns])

  const beginCompletionRenderHold = useCallback((sessionId: string) => {
    const normalizedSessionId = sessionId.trim()
    if (!normalizedSessionId) return
    const token = completionRenderHoldTokenRef.current + 1
    completionRenderHoldTokenRef.current = token
    setCompletionRenderHold((current) => {
      if (current?.sessionId === normalizedSessionId) return current
      return {
        sessionId: normalizedSessionId,
        token,
        initialResponseSignature: latestAssistantResponseSignatureRef.current,
        userTurnSignature: latestUserTurnSignatureRef.current,
        startedAt: Date.now(),
      }
    })
  }, [])
  const clear = useCallback(() => setCompletionRenderHold(null), [])
  const clearForSession = useCallback(
    (id: string) =>
      setCompletionRenderHold((current) => (current?.sessionId === id ? null : current)),
    []
  )

  return {
    holding: completionRenderHolding,
    begin: beginCompletionRenderHold,
    clear,
    clearForSession,
  }
}
