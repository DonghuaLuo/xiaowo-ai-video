import {
  type AssistantContentBlock,
  type AssistantTurn,
  assistantActionFooterText,
} from "./assistant-session-normalization"
export function getAssistantTurnContentBlocks(
  turn: AssistantTurn
): AssistantContentBlock[] {
  if (turn.content?.length || !turn.text.trim()) {
    return turn.content ?? []
  }
  return [{ type: "text", text: turn.text } satisfies AssistantContentBlock]
}

export const ASSISTANT_AUTO_EXPANDED_ASSISTANT_TURNS = 2

export function assistantContentBlockCanCollapse(block: AssistantContentBlock) {
  if (
    block.type === "text" ||
    block.type === "thinking" ||
    block.type === "skill_content"
  ) {
    return assistantTextCanCollapse(block.text)
  }
  return false
}

export function isRenderableAssistantContentBlock(block: AssistantContentBlock) {
  if (block.type === "task_progress") {
    return Boolean(block.title?.trim()) || Boolean(block.steps?.length)
  }
  if (block.type === "text") {
    return Boolean(block.text.trim() || assistantActionFooterText(block.actionFooter))
  }
  return true
}

export function isVisibleAssistantChatBlock(block: AssistantContentBlock) {
  if (!isRenderableAssistantContentBlock(block)) return false
  if (block.type === "task_progress") return false
  if (block.type === "recommendations") return Boolean(block.origin)
  if (block.type === "thinking" || block.type === "skill_content") return false
  if (block.type === "tool_use" && !block.is_error) return false
  if (block.type === "tool_result") return false
  return true
}

export function normalizeVisibleAssistantChatBlocks(
  blocks: AssistantContentBlock[]
): AssistantContentBlock[] {
  const result: AssistantContentBlock[] = []
  const textBlocks: string[] = []

  const flushText = () => {
    if (!textBlocks.length) return
    result.push({ type: "text", text: textBlocks.join("\n\n") })
    textBlocks.length = 0
  }

  for (const block of blocks) {
    if (block.type === "text") {
      const text = block.text.trim()
      if (assistantActionFooterText(block.actionFooter)) {
        flushText()
        result.push({
          type: "text",
          text,
          actionFooter: block.actionFooter!,
        })
        continue
      }
      if (!text) continue
      textBlocks.push(text)
      continue
    }
    flushText()
    result.push(block)
  }
  flushText()
  return result
}

export function assistantTurnHasVisibleContent(turn: AssistantTurn) {
  const contentBlocks = normalizeVisibleAssistantChatBlocks(
    getAssistantTurnContentBlocks(turn).filter(isVisibleAssistantChatBlock)
  )
  return Boolean(contentBlocks.length || turn.attachments?.length)
}

export function latestExpandableAssistantTurnIds(turns: AssistantTurn[]) {
  const ids: string[] = []
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index]
    if (!turn) continue
    if (turn.type === "user" || turn.type === "system") continue
    if (!assistantTurnHasVisibleContent(turn)) continue
    ids.push(turn.uuid)
    if (ids.length >= ASSISTANT_AUTO_EXPANDED_ASSISTANT_TURNS) break
  }
  return new Set(ids)
}

export function pruneAssistantMessageIdSet(current: Set<string>, validIds: Set<string>) {
  let changed = false
  const next = new Set<string>()
  current.forEach((id) => {
    if (validIds.has(id)) {
      next.add(id)
    } else {
      changed = true
    }
  })
  return changed ? next : current
}

export function parseAssistantTimestampMs(value?: string | number | null) {
  if (value === null || value === undefined) return null
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null
    return value < 1_000_000_000_000 ? value * 1000 : value
  }
  const text = value.trim()
  if (!text || text === "刚刚") return null
  if (/^\d+$/.test(text)) {
    const numberValue = Number(text)
    if (!Number.isFinite(numberValue)) return null
    return numberValue < 1_000_000_000_000 ? numberValue * 1000 : numberValue
  }
  const timestamp = Date.parse(text)
  return Number.isFinite(timestamp) ? timestamp : null
}

export function formatAssistantSessionDateTime(value?: string | number | null) {
  const timestamp = parseAssistantTimestampMs(value)
  if (timestamp === null) {
    return typeof value === "string" && value.trim() ? value.trim() : "刚刚"
  }
  const date = new Date(timestamp)
  const pad = (part: number) => String(part).padStart(2, "0")
  const day = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  const clock = `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(
    date.getSeconds()
  )}`
  return `${day} ${clock}`
}

export function formatAssistantDuration(milliseconds: number) {
  const totalSeconds = Math.max(1, Math.floor(Math.max(0, milliseconds) / 1000))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) {
    return `${hours}小时${minutes > 0 ? `${minutes}分` : ""}`
  }
  if (minutes > 0) {
    return `${minutes}分${seconds > 0 ? `${seconds}秒` : ""}`
  }
  return `${seconds}秒`
}

export function formatAssistantCompletionTime(timestampMs: number) {
  const date = new Date(timestampMs)
  const now = new Date()
  const hours = String(date.getHours()).padStart(2, "0")
  const minutes = String(date.getMinutes()).padStart(2, "0")
  const clock = `${hours}:${minutes}`
  if (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  ) {
    return clock
  }
  return `${date.getMonth() + 1}月${date.getDate()}日 ${clock}`
}

export function latestUserTurnTimestampMs(turns: AssistantTurn[]) {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index]
    if (turn.type !== "user") continue
    const timestampMs = parseAssistantTimestampMs(turn.timestamp)
    if (timestampMs !== null) return timestampMs
  }
  return null
}

export function buildAssistantTurnCompletionMetaById(turns: AssistantTurn[]) {
  const metaById = new Map<string, string>()
  const timelineTurns = turns
    .map((turn, index) => ({
      turn,
      index,
      timestampMs: parseAssistantTimestampMs(turn.timestamp),
    }))
    .sort((left, right) => {
      if (left.timestampMs !== right.timestampMs) {
        if (left.timestampMs === null) return 1
        if (right.timestampMs === null) return -1
        return left.timestampMs - right.timestampMs
      }
      return left.index - right.index
    })
  let currentRunStartedAtMs: number | null = null
  let latestAssistantTurn: {
    uuid: string
    finishedAtMs: number
  } | null = null

  const commitLatestAssistantTurn = () => {
    if (
      currentRunStartedAtMs === null ||
      !latestAssistantTurn ||
      latestAssistantTurn.finishedAtMs < currentRunStartedAtMs
    ) {
      return
    }
    metaById.set(
      latestAssistantTurn.uuid,
      `结束 ${formatAssistantCompletionTime(
        latestAssistantTurn.finishedAtMs
      )} · 用时 ${formatAssistantDuration(
        latestAssistantTurn.finishedAtMs - currentRunStartedAtMs
      )}`
    )
  }

  for (const { turn, timestampMs } of timelineTurns) {
    if (turn.type === "user") {
      commitLatestAssistantTurn()
      currentRunStartedAtMs = timestampMs
      latestAssistantTurn = null
      continue
    }
    if (
      turn.type === "assistant" &&
      currentRunStartedAtMs !== null &&
      timestampMs !== null
    ) {
      latestAssistantTurn = {
        uuid: turn.uuid,
        finishedAtMs: timestampMs,
      }
    }
  }
  commitLatestAssistantTurn()

  return metaById
}

export const ASSISTANT_SCROLL_BOTTOM_THRESHOLD = 96

export function isAssistantScrollNearBottom(element: HTMLElement) {
  return (
    element.scrollHeight - element.scrollTop - element.clientHeight <=
    ASSISTANT_SCROLL_BOTTOM_THRESHOLD
  )
}

export const ASSISTANT_TEXT_COLLAPSE_LIMIT = 180

export function assistantTextCanCollapse(text: string) {
  const normalized = text.replace(/\r\n/g, "\n").trim()
  if (!normalized) return false
  const visibleLineCount = normalized.split("\n").filter((line) => line.trim()).length
  return normalized.length > ASSISTANT_TEXT_COLLAPSE_LIMIT || visibleLineCount > 3
}
