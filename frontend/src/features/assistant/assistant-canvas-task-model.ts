import type {
  AssistantSessionSummary,
  AssistantTurn,
} from "./assistant-session-normalization"

export function isActiveCanvasTask(task: AssistantSessionSummary) {
  if (
    !task.canvasTask ||
    task.status === "error" ||
    task.status === "interrupted"
  )
    return false
  return (
    task.status === "running" ||
    (task.status === "idle" && task.canvasTask.starting === true)
  )
}

export function canvasConversationActivity(sessions: AssistantSessionSummary[]) {
  const activity = new Map<string, {
    activeTasks: AssistantSessionSummary[]
    runningCount: number
    waitingForInputCount: number
    waitingForConfirmationCount: number
  }>()
  for (const row of sessions) {
    const parentId = row.canvasTask?.parentSessionId ?? row.id
    let summary = activity.get(parentId)
    if (!summary) {
      summary = { activeTasks: [], runningCount: 0, waitingForInputCount: 0, waitingForConfirmationCount: 0 }
      activity.set(parentId, summary)
    }
    if (row.status === "error" || row.status === "interrupted") continue
    if (row.canvasTask) {
      if (!isActiveCanvasTask(row)) continue
      summary.activeTasks.push(row)
      summary.runningCount += 1
      continue
    }
    if (row.waitingForInput) summary.waitingForInputCount += 1
    else if (row.waitingForConfirmation || row.pendingCandidateCount) summary.waitingForConfirmationCount += 1
    else if (row.status === "running") summary.runningCount += 1
  }
  return activity
}

// A conversation's own interaction and unsent drafts remain reachable even
// when its single active task has no task-list entry.
export function resolveCanvasSessionSelection(
  sessions: AssistantSessionSummary[],
  sessionId: string | null,
  rememberedTaskId?: string,
  draftSessionIds: ReadonlySet<string> = new Set()
) {
  const selected = sessions.find((row) => row.id === sessionId)
  if (!selected || selected.canvasTask) return sessionId
  if (selected.status === "running" || selected.waitingForInput ||
      selected.waitingForConfirmation || selected.pendingCandidateCount || draftSessionIds.has(selected.id))
    return sessionId
  const children = sessions.filter(
    (row) => row.canvasTask?.parentSessionId === sessionId
  )
  const draft = children.find((row) => row.id === rememberedTaskId && draftSessionIds.has(row.id)) ??
    children.find((row) => draftSessionIds.has(row.id))
  if (draft) return draft.id
  const active = children.filter(isActiveCanvasTask)
  return active.find((row) => row.id === rememberedTaskId)?.id ?? active[0]?.id ?? sessionId
}

// Final reports are saved in the ordinary conversation by the backend. Only
// the selected running task contributes temporary messages alongside it.
export function composeCanvasConversationTurns(
  sessions: AssistantSessionSummary[],
  currentSessionId: string | null,
  currentTurns: AssistantTurn[],
  savedTurns: ReadonlyMap<string, AssistantTurn[]>
) {
  const selected = sessions.find((row) => row.id === currentSessionId)
  const parentId = selected?.canvasTask?.parentSessionId ?? currentSessionId
  if (!selected?.canvasTask || !parentId) return currentTurns
  const sourceTurns = (id: string) =>
    (id === currentSessionId ? currentTurns : (savedTurns.get(id) ?? [])).map(
      (turn) => ({ ...turn, sourceSessionId: id })
    )
  const completed = sourceTurns(parentId)
  return selected?.canvasTask && isActiveCanvasTask(selected)
    ? [...completed, ...sourceTurns(selected.id)]
    : completed
}
