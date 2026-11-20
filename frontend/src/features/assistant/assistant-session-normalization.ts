import { PluginSDK } from "xiaowo-sdk"
import type { AgentTargetContext, MediaAsset, TaskRow } from "@/backend"
import type { ProjectRow } from "@/features/projects/types"
import type { AgentProjectEffect } from "@/features/workspace/types"
import type { WorkspaceSection } from "@/navigation"
import { createLocalId } from "@/shared/media"

export type AssistantMessageRole = "assistant" | "user"
export type AssistantStepStatus = "idle" | "running" | "done" | "failed"
export type AssistantConversationScope = "project" | "episode"

export type AssistantAttachment = {
  id: string
  name: string
  mimeType: string
  media: MediaAsset
}

export type AssistantRecommendationItem = {
  sourceSessionId?: string
  id: string
  label: string
  description?: string
  mode: "action" | "prompt" | "navigation"
  destination?: "project_session"
  prompt: string
  action?: string
  taskType?: string
  controlOnly?: boolean
  recommended?: boolean
  targetContext?: AgentTargetContext
}

export type AssistantRecommendationSelect = (
  item: AssistantRecommendationItem
) => void

export type AssistantActionFooter = {
  label?: string
  title?: string
  description?: string
  reply?: string
}

export type AssistantContentBlock =
  | {
      type: "text"
      text: string
      actionFooter?: AssistantActionFooter
    }
  | {
      type: "task_progress"
      title?: string
      status?: "idle" | "running" | "completed" | "failed"
      steps?: AssistantStep[]
    }
  | {
      type: "thinking" | "skill_content"
      title?: string
      text: string
    }
  | {
      type: "tool_use"
      id?: string
      name: string
      input?: Record<string, unknown>
      result?: string
      is_error?: boolean
      skill_content?: string
    }
  | {
      type: "tool_result"
      tool_use_id?: string
      content: string
      is_error?: boolean
      outcome?: "revision_required"
    }
  | {
      type: "source_text"
      title?: string
      text: string
      meta?: string
      episodeId?: string
      sourceId?: string
    }
  | {
      type: "plot_split_preview"
      candidateId: string
      candidateVersion: number
      status: "pending_confirmation" | "superseded" | "committed" | "cancelled"
      episodeTitle: string
      segments: {
        index: number
        title: string
        text: string
        charCount: number
        splitReason: string
        assets: { label: string; names: string[] }[]
      }[]
    }
  | {
      type: "episode_boundary_candidate"
      candidateId: string
      runId?: string
      candidateDigest?: string
      candidateVersion?: number
      status: "pending_confirmation" | "committing" | "commit_unknown" | "committed" | "superseded" | "cancelled" | "stale"
      episodeId: string
      title: string
      startOffset: number
      endOffset: number
      targetUnits?: number
      actualUnits?: number
      boundaryEndText: string
      reason: string
      riskNotes: string[]
    }
  | {
      type: "asset_range_candidate"
      candidateId: string
      runId?: string
      candidateDigest?: string
      candidateVersion?: number
      status: "pending_confirmation" | "committing" | "commit_unknown" | "committed" | "superseded" | "cancelled" | "stale"
      rangeId: string
      sourceId: string
      absoluteStart: number
      absoluteEnd: number
      targetUnits?: number
      actualUnits?: number
      assetTypes: string[]
      phaseVisualContexts: { name: string; visualPrompt: string; visualChangeReason?: string }[]
      boundaryEndText: string
      reason: string
      riskNotes: string[]
    }
  | {
      type: "interrupt_notice"
      text: string
    }
  | {
      type: "attachment_error"
      kind?: "image" | "file" | string
      text: string
      name?: string
      mimeType?: string
      media_type?: string
    }
  | {
      type: "recommendations"
      title?: string
      origin?: "progress_query" | "task_completion" | "task_feedback"
      summary?: string
      items: AssistantRecommendationItem[]
    }
  | {
      type: "image"
      source?: {
        type?: string
        media_type?: string
        mimeType?: string
        name?: string
        path?: string
        filePath?: string
        file?: string
        relativePath?: string
        relative_path?: string
      }
    }
  | {
      type: "file"
      source?: {
        type?: string
        media_type?: string
        mimeType?: string
        name?: string
        path?: string
        filePath?: string
        file?: string
        relativePath?: string
        relative_path?: string
        size?: number
      }
    }

export type AssistantConfirmableCandidateBlock = Extract<
  AssistantContentBlock,
  { type: "episode_boundary_candidate" | "asset_range_candidate" }
>

export type AssistantMessage = {
  id: string
  role: AssistantMessageRole
  text: string
  createdAt: string
  attachments?: AssistantAttachment[]
  content?: AssistantContentBlock[]
}

export type AssistantTurn = {
  sourceSessionId?: string
  type: AssistantMessageRole | "system"
  uuid: string
  timestamp: string
  text: string
  attachments?: AssistantAttachment[]
  content: AssistantContentBlock[]
}

export type AssistantStep = {
  id: string
  label: string
  status: AssistantStepStatus
}

export type AssistantQuestionOption = {
  value?: string
  label: string
  description: string
  recommended?: boolean
}

export type AssistantPendingQuestionItem = {
  header?: string
  question: string
  options: AssistantQuestionOption[]
  multiSelect?: boolean
}

export type AssistantPendingQuestion = {
  question_id: string
  questionId?: string
  questions: AssistantPendingQuestionItem[]
}

export type AssistantSkillCommand = {
  id: string
  name: string
  label: string
  description: string
  prompt: string
  taskType?: string
  controlOnly?: boolean
  source?: "agent_action" | "agent_ops_skill" | string
  execution?: string
}

export type AssistantQuickPrompt = {
  id: string
  label: string
  prompt: string
  taskType?: string
  controlOnly?: boolean
}

export type AssistantLiveActivityItem = {
  id: string
  text: string
  kind?: "phase" | "thought" | "tool_use" | "tool_result"
  phase?: "start" | "thinking" | "finalizing"
  goal?: string
  toolName?: string
  toolUseId?: string
  isError?: boolean
  outcome?: "revision_required"
}

export const ASSISTANT_CONTROL_ONLY_QUICK_PROMPT_IDS = new Set([
  "confirm",
  "continue",
])

export function isAssistantControlOnlyQuickPromptId(id?: string) {
  return ASSISTANT_CONTROL_ONLY_QUICK_PROMPT_IDS.has(String(id || "").trim())
}

export const ASSISTANT_LIVE_ACTIVITY_HISTORY_LIMIT = 120

export type AssistantClientAction = {
  type: "navigate"
  section: WorkspaceSection
  episodeId?: string
}

export type AssistantBackendSuccess = {
  success: true
  message: string
  steps?: AssistantStep[]
  project?: ProjectRow
  pendingQuestion?: AssistantPendingQuestion | null
  clientAction?: AssistantClientAction | null
  projectChanged?: boolean
  echoLabel?: string
  session?: AssistantSessionDetail
  sessions?: AssistantSessionSummary[]
  sessionId?: string
  snapshot?: AssistantSessionSnapshot
  task?: TaskRow | null
  tasks?: TaskRow[]
  cancelledTasks?: TaskRow[]
  uncancelledTasks?: TaskRow[]
  uncancelledTaskIds?: string[]
  uncancelledTaskReasons?: Array<{
    taskId?: string
    reason?: string
    message?: string
  }>
  partialFailure?: boolean
  cancelErrors?: Array<{ taskId?: string; message?: string }>
  projectEffect?: AgentProjectEffect | null
}

export type AssistantSessionSummary = {
  canvasTask?: {
    parentSessionId: string
    taskType: string
    requestKey: string
    starting?: boolean
    target: AgentTargetContext
  }
  stateRevision?: number
  execution?: { id?: string }
  runningTaskType?: string
  waitingForInput?: boolean
  waitingForConfirmation?: boolean
  pendingCandidateCount?: number
  id: string
  title: string
  episodeId: string
  status: "idle" | "running" | "completed" | "error" | "interrupted"
  createdAt: string
  updatedAt: string
}

export type AssistantSessionAttachment = {
  id: string
  name: string
  mimeType: string
  path?: string
  filePath?: string
  file?: string
  relativePath?: string
  relative_path?: string
  size?: number
}

export type AssistantSessionDetail = AssistantSessionSummary & {
  messages: AssistantMessage[]
  steps?: AssistantStep[]
  pendingQuestion?: AssistantPendingQuestion | null
  pendingInteractions?: AssistantPendingInteraction[]
  sdkSessionId?: string
  providerInstanceId?: string
  adapterId?: string
  toolsUsed?: string[]
}

export type AssistantPendingInteraction = {
  active: boolean
  status: string
  operationStatus: string
  sessionId: string
  operationType: string
  pendingOperationId: string
  kind: string
  createdAt: string
  candidateId: string
  runId: string
  candidateDigest: string
  candidateVersion?: number
  title: string
  description: string
  message: string
  staleReason: string
  highRisk: boolean
  confirmationMode: "button_only" | "message_or_button"
  canConfirm: boolean
  canCancel: boolean
}

export function normalizeAssistantPendingInteraction(raw: unknown): AssistantPendingInteraction | null {
  if (!raw || typeof raw !== "object") return null
  const row = raw as Record<string, unknown>
  const sessionId = String(row.sessionId || "").trim()
  const operationType = String(row.operationType || "").trim()
  if (!sessionId || !operationType) return null
  const version = Number(row.candidateVersion)
  return {
    active: row.active === true,
    status: String(row.status || "stale"),
    operationStatus: String(row.operationStatus || ""),
    sessionId,
    operationType,
    pendingOperationId: String(row.pendingOperationId || ""),
    kind: String(row.kind || ""),
    createdAt: String(row.createdAt || ""),
    candidateId: String(row.candidateId || ""),
    runId: String(row.runId || ""),
    candidateDigest: String(row.candidateDigest || ""),
    candidateVersion: Number.isSafeInteger(version) && version > 0 ? version : undefined,
    title: String(row.title || "确认当前操作"),
    description: String(row.description || ""),
    message: String(row.message || ""),
    staleReason: String(row.staleReason || ""),
    highRisk: row.highRisk === true,
    confirmationMode: row.confirmationMode === "button_only" || row.highRisk === true
      ? "button_only" : "message_or_button",
    canConfirm: row.canConfirm === true,
    canCancel: row.canCancel === true,
  }
}

export type AssistantSessionSummaryInput = Partial<AssistantSessionSummary> & {
  episode_id?: string
  created_at?: string
  updated_at?: string
}

export type AssistantSessionSnapshot = {
  sessionId?: string
  status?: AssistantSessionSummary["status"]
  turns?: unknown[]
  draft_turn?: unknown
  pending_questions?: AssistantPendingQuestion[]
  session?: AssistantSessionDetail
  live_activity?: Array<AssistantLiveActivityItem | string>
  liveActivity?: Array<AssistantLiveActivityItem | string>
}

export type AssistantAgentLogEntry = {
  id: string
  timestamp: string
  severity: string
  category: string
  stage: string
  source: string
  tool: string
  action: string
  message: string
  error: string
  errorType: string
  file: string
  traceback: string
  details?: Record<string, unknown> | null
}

export const ASSISTANT_OTHER_OPTION_VALUE = "__assistant_option_other__"
export const ASSISTANT_OTHER_OPTION_LABEL = "其他"
export const ASSISTANT_STATIC_IMAGE_MIME_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
])

export function assistantSessionEpisodeId(
  raw?: AssistantSessionSummaryInput | null
) {
  return String(raw?.episodeId ?? raw?.episode_id ?? "").trim()
}

export function normalizeAssistantSessionSummary(
  raw?: AssistantSessionSummaryInput | null,
  fallbackEpisodeId = "E01"
): AssistantSessionSummary {
  const episodeId = assistantSessionEpisodeId(raw) || fallbackEpisodeId
  return {
    stateRevision: Number.isSafeInteger(raw?.stateRevision) ? raw!.stateRevision : 0,
    execution: raw?.execution,
    canvasTask: raw?.canvasTask?.parentSessionId ? raw.canvasTask : undefined,
    runningTaskType: raw?.runningTaskType,
    waitingForInput: Boolean(raw?.waitingForInput),
    waitingForConfirmation: Boolean(raw?.waitingForConfirmation),
    pendingCandidateCount: Math.max(0, Number(raw?.pendingCandidateCount) || 0),
    id: raw?.id ?? "",
    title: raw?.title?.trim() || "新会话",
    episodeId,
    status:
      raw?.status === "running" ||
      raw?.status === "completed" ||
      raw?.status === "error" ||
      raw?.status === "interrupted"
        ? raw.status
        : "idle",
    createdAt: raw?.createdAt ?? raw?.created_at ?? "",
    updatedAt:
      raw?.updatedAt ??
      raw?.updated_at ??
      raw?.createdAt ??
      raw?.created_at ??
      "",
  }
}

export function acceptsAssistantSessionVersion(
  incoming: AssistantSessionSummary,
  current?: AssistantSessionSummary,
  allowInitialRevisionZero = false
) {
  const revision = incoming.stateRevision ?? 0
  if (!Number.isSafeInteger(revision) || revision < 0) return false
  if (revision === 0 && !current) return allowInitialRevisionZero
  const previous = current?.stateRevision ?? 0
  if (revision < previous) return false
  if (revision === previous) {
    return incoming.status === current?.status &&
      incoming.execution?.id === current?.execution?.id
  }
  return true
}

export function normalizeAssistantSessionSummaries(
  rawSessions: unknown,
  episodeId?: string
) {
  if (!Array.isArray(rawSessions)) return []
  return rawSessions
    .map((session) => session as AssistantSessionSummaryInput)
    .filter((session) => {
      const sessionEpisodeId = assistantSessionEpisodeId(session)
      return !episodeId || !sessionEpisodeId || sessionEpisodeId === episodeId
    })
    .map((session) =>
      normalizeAssistantSessionSummary(session, episodeId || "E01")
    )
}

export function assistantSessionScopeLabel(episodeId: string) {
  return ["", "__project__", "project"].includes(episodeId)
    ? "项目会话"
    : episodeId
}

export function normalizeAssistantAgentLogEntries(rawLogs: unknown) {
  if (!Array.isArray(rawLogs)) return []
  return rawLogs
    .map((item, index): AssistantAgentLogEntry | null => {
      if (!item || typeof item !== "object") return null
      const row = item as Record<string, unknown>
      const details =
        row.details &&
        typeof row.details === "object" &&
        !Array.isArray(row.details)
          ? (row.details as Record<string, unknown>)
          : null
      return {
        id: String(row.id || `agent-log-${index + 1}`),
        timestamp: String(row.timestamp || ""),
        severity: String(row.severity || "error"),
        category: String(row.category || ""),
        stage: String(row.stage || ""),
        source: String(row.source || ""),
        tool: String(row.tool || ""),
        action: String(row.action || ""),
        message: String(row.message || ""),
        error: String(row.error || ""),
        errorType: String(row.errorType || ""),
        file: String(row.file || ""),
        traceback: String(row.traceback || ""),
        details,
      }
    })
    .filter(Boolean) as AssistantAgentLogEntry[]
}

export const ASSISTANT_AGENT_LOG_GENERIC_TITLES = new Set([
  "智能体执行异常",
  "智能体 SDK 执行失败",
  "智能体 SDK 未返回成功结果",
  "智能体工具调用异常",
  "智能体工具返回失败结果",
  "工具调用失败",
  "SDK 未返回成功结果",
  "读取智能体错误日志失败",
])

export const ASSISTANT_AGENT_LOG_NOISE_KEYS = new Set([
  "id",
  "uuid",
  "pid",
  "projectid",
  "episodeid",
  "sessionid",
  "conversationid",
  "workflowid",
  "taskid",
  "jobid",
  "workid",
  "workerid",
  "workerrunid",
  "processid",
  "streamtoolid",
  "requestid",
  "traceid",
  "runid",
  "sdkid",
  "sdksessionid",
  "providerinstanceid",
  "adapterid",
])

export const ASSISTANT_AGENT_LOG_SKIP_DETAIL_KEYS = new Set([
  "args",
  "input",
  "payload",
  "events",
  "sdkevents",
  "lasttoolcall",
])

export function assistantAgentLogKeyName(key: string) {
  return key.replace(/[\s_-]/g, "").toLowerCase()
}

export function assistantAgentLogIsNoiseKey(key: string) {
  const normalized = assistantAgentLogKeyName(key)
  return (
    ASSISTANT_AGENT_LOG_NOISE_KEYS.has(normalized) ||
    /^(task|job|work|worker|process|session|conversation|workflow|project|episode|request|trace|run).*(id|ids)$/.test(
      normalized
    )
  )
}

export function assistantAgentLogTextValue(value: unknown) {
  if (typeof value === "string") return value.trim()
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value)
  }
  return ""
}

export function assistantAgentLogCleanLine(value: string) {
  const lines = value
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
  const line =
    lines.find(
      (item) =>
        !item.startsWith("Traceback") &&
        !item.startsWith("File ") &&
        !item.startsWith("{")
    ) ??
    lines[0] ??
    ""
  return line
    .replace(/^(Error|Exception|RuntimeError|ValueError):\s*/i, "")
    .trim()
}

export function assistantAgentLogShortText(value: string, limit = 96) {
  const text = assistantAgentLogCleanLine(value)
  if (!text) return ""
  return text.length > limit ? `${text.slice(0, limit).trimEnd()}...` : text
}

export function assistantAgentLogCollectDetailText(
  value: unknown,
  output: string[] = [],
  depth = 0
) {
  if (!value || depth > 3 || output.length >= 8) return output
  if (Array.isArray(value)) {
    for (const item of value.slice(0, 5)) {
      assistantAgentLogCollectDetailText(item, output, depth + 1)
      if (output.length >= 8) break
    }
    return output
  }
  if (typeof value !== "object") return output

  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    if (assistantAgentLogIsNoiseKey(key)) continue
    const normalized = assistantAgentLogKeyName(key)
    if (["error", "message", "reason", "cause"].includes(normalized)) {
      const text = assistantAgentLogShortText(assistantAgentLogTextValue(item))
      if (text) output.push(text)
    }
    if (
      item &&
      typeof item === "object" &&
      !ASSISTANT_AGENT_LOG_SKIP_DETAIL_KEYS.has(normalized)
    ) {
      assistantAgentLogCollectDetailText(item, output, depth + 1)
    }
    if (output.length >= 8) break
  }
  return output
}

export function assistantAgentLogTitle(log: AssistantAgentLogEntry) {
  const candidates = [
    log.error,
    ...assistantAgentLogCollectDetailText(log.details),
    log.message,
  ]
    .map((item) => assistantAgentLogShortText(item))
    .filter(Boolean)

  return (
    candidates.find((item) => !ASSISTANT_AGENT_LOG_GENERIC_TITLES.has(item)) ??
    candidates[0] ??
    "智能体执行异常"
  )
}

export function formatAssistantAgentLogTime(value: string) {
  if (!value) return "未知时间"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
}

export function assistantAgentLogStageLabel(stage: string) {
  const normalized = stage.trim()
  if (!normalized) return "未知环节"
  if (normalized === "agent_sdk_turn") return "模型调用"
  if (normalized === "mcp_tool_call") return "工具调用"
  if (normalized === "mcp_tool_result") return "工具执行结果"
  if (normalized === "requirement_extractor") return "关键需求提炼"
  if (normalized.includes("attachment")) return "附件处理"
  if (normalized.includes("image")) return "图片处理"
  if (normalized.includes("file")) return "文件处理"
  if (normalized.startsWith("handle_")) return "后端接口处理"
  return normalized.replace(/_/g, " ")
}

export function assistantAgentLogFullText(log: AssistantAgentLogEntry) {
  const title = assistantAgentLogTitle(log)
  const sections: string[] = []
  const seen = new Set<string>()
  const pushSection = (value: string) => {
    const text = value.trim()
    if (!text || seen.has(text)) return
    seen.add(text)
    sections.push(text)
  }

  const errorSummary = assistantAgentLogShortText(log.error)
  if (
    log.error.trim() &&
    (!ASSISTANT_AGENT_LOG_GENERIC_TITLES.has(errorSummary) ||
      errorSummary === title)
  ) {
    pushSection(log.error)
  }

  const message = log.message.trim()
  if (
    message &&
    (!ASSISTANT_AGENT_LOG_GENERIC_TITLES.has(message) || message === title)
  ) {
    pushSection(message)
  }

  for (const detailText of assistantAgentLogCollectDetailText(log.details)) {
    pushSection(detailText)
  }

  if (!sections.length && log.traceback.trim()) {
    pushSection(`调用栈：\n${log.traceback.trim()}`)
  }

  return sections.join("\n\n") || title
}

export async function copyAssistantTextToClipboard(
  text: string
): Promise<void> {
  try {
    await PluginSDK.clipboard.writeText(text)
    return
  } catch {
    // Fall back to browser APIs in dev mode.
  }

  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }

  const textarea = document.createElement("textarea")
  textarea.value = text
  textarea.style.position = "fixed"
  textarea.style.opacity = "0"
  document.body.appendChild(textarea)
  try {
    textarea.select()
    const copied = document.execCommand("copy")
    if (!copied) throw new Error("复制到剪贴板失败")
  } finally {
    document.body.removeChild(textarea)
  }
}

export function assistantSessionAttachmentToUi(
  attachment: AssistantSessionAttachment
): AssistantAttachment {
  return {
    id: attachment.id,
    name: attachment.name,
    mimeType: attachment.mimeType,
    media: {
      id: attachment.id,
      kind: "image",
      originalName: attachment.name,
      mimeType: attachment.mimeType,
      path: attachment.path,
      filePath: attachment.filePath,
      file: attachment.file,
      relativePath: attachment.relativePath,
      relative_path: attachment.relative_path,
      preview: attachment.path
        ? PluginSDK.convertFileSrc(attachment.path)
        : undefined,
    },
  }
}

export function cleanAssistantActionText(value: unknown) {
  return String(value ?? "")
    .replace(/&#x20;|&#32;|&nbsp;/gi, " ")
    .replace(/\u00a0/g, " ")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .join("\n")
    .trim()
}

export function cleanAssistantActionInlineText(value: unknown) {
  return cleanAssistantActionText(value).replace(/\s+/g, " ").trim()
}

export function normalizeAssistantActionFooter(
  raw: unknown
): AssistantActionFooter | undefined {
  if (!raw) return undefined
  if (typeof raw !== "object" || Array.isArray(raw)) return undefined
  const row = raw as Record<string, unknown>
  const footer: AssistantActionFooter = {}
  const label = cleanAssistantActionInlineText(row.label)
  const title = cleanAssistantActionInlineText(row.title)
  const description = cleanAssistantActionText(row.description)
  const reply = cleanAssistantActionInlineText(row.reply)
  if (label) footer.label = label
  if (title) footer.title = title
  if (description) footer.description = description
  if (reply) footer.reply = reply
  return Object.keys(footer).length ? footer : undefined
}

export function assistantActionFooterText(footer?: AssistantActionFooter) {
  if (!footer) return ""
  return [
    footer.label ? `${footer.label}:` : "",
    footer.title,
    footer.description,
    footer.reply ? `回复:\n${footer.reply}` : "",
  ]
    .filter(Boolean)
    .join("\n")
    .trim()
}

export function isAssistantTruthyFlag(value: unknown): boolean {
  return (
    value === true ||
    String(value || "")
      .trim()
      .toLowerCase() === "true"
  )
}

export function normalizeAssistantContentBlocks(
  raw: unknown,
  fallbackText = ""
): AssistantContentBlock[] {
  if (!Array.isArray(raw)) {
    return fallbackText.trim()
      ? [{ type: "text", text: fallbackText.trim() }]
      : []
  }
  const blocks = raw
    .map((block): AssistantContentBlock | null => {
      if (!block || typeof block !== "object") return null
      const row = block as Record<string, unknown>
      const type = String(row.type || "text")
      if (type === "text") {
        const text = String(row.text || "").trim()
        const actionFooter = normalizeAssistantActionFooter(
          row.actionFooter || row.action_footer
        )
        return text || actionFooter
          ? {
              type: "text",
              text,
              ...(actionFooter ? { actionFooter } : {}),
            }
          : null
      }
      if (type === "task_progress") {
        const rawSteps = Array.isArray(row.steps)
          ? (row.steps as AssistantStep[])
          : []
        const status = String(row.status || "idle")
        return {
          type: "task_progress",
          title: String(row.title || "创建项目拆分流程"),
          status:
            status === "running" ||
            status === "completed" ||
            status === "failed"
              ? status
              : "idle",
          steps: rawSteps,
        }
      }
      if (type === "thinking" || type === "skill_content") {
        const text = String(row.text || "").trim()
        return text
          ? {
              type,
              title: String(
                row.title || (type === "thinking" ? "思考过程" : "技能输出")
              ),
              text,
            }
          : null
      }
      if (type === "tool_use") {
        const name = String(row.name || "Tool").trim()
        const input =
          row.input &&
          typeof row.input === "object" &&
          !Array.isArray(row.input)
            ? (row.input as Record<string, unknown>)
            : {}
        return {
          type: "tool_use",
          id: String(row.id || row.tool_use_id || ""),
          name,
          input,
          result: String(row.result || "").trim() || undefined,
          is_error: Boolean(row.is_error),
          skill_content: String(row.skill_content || "").trim() || undefined,
        }
      }
      if (type === "tool_result") {
        const content = String(row.content || row.result || "").trim()
        return content
          ? {
              type: "tool_result",
              tool_use_id: String(row.tool_use_id || row.id || ""),
              content,
              is_error: Boolean(row.is_error),
              outcome: row.outcome === "revision_required" ? "revision_required" : undefined,
            }
          : null
      }
      if (type === "source_text" || type === "sourceText") {
        const text = String(
          row.text || row.content || row.sourceText || row.source_text || ""
        )
          .replace(/\r\n/g, "\n")
          .replace(/\r/g, "\n")
        return text.trim()
          ? {
              type: "source_text",
              title: String(row.title || "本集原文").trim() || undefined,
              text,
              meta:
                String(row.meta || row.description || "").trim() || undefined,
              episodeId:
                String(row.episodeId || row.episode_id || "").trim() ||
                undefined,
              sourceId:
                String(row.sourceId || row.source_id || "").trim() || undefined,
            }
          : null
      }
      if (type === "plot_split_preview") {
        const candidateId = String(row.candidateId || "").trim()
        if (!candidateId) return null
        const segments = Array.isArray(row.segments)
          ? row.segments.flatMap((rawSegment, index) => {
              if (!rawSegment || typeof rawSegment !== "object") return []
              const segment = rawSegment as Record<string, unknown>
              const text = String(segment.text || "").replace(/\r\n?/g, "\n")
              const assets = Array.isArray(segment.assets)
                ? segment.assets.flatMap((rawAsset) => {
                    if (!rawAsset || typeof rawAsset !== "object") return []
                    const asset = rawAsset as Record<string, unknown>
                    const label = String(asset.label || "").trim()
                    const names = Array.isArray(asset.names)
                      ? asset.names.map((name) => String(name).trim()).filter(Boolean)
                      : []
                    return label && names.length ? [{ label, names }] : []
                  })
                : []
              return [{
                index: Number.isSafeInteger(Number(segment.index)) ? Number(segment.index) : index + 1,
                title: String(segment.title || "").trim(),
                text,
                charCount: Number.isSafeInteger(Number(segment.charCount)) && Number(segment.charCount) >= 0
                  ? Number(segment.charCount)
                  : Array.from(text).length,
                splitReason: String(segment.splitReason || "").trim(),
                assets,
              }]
            })
          : []
        return segments.length ? {
          type: "plot_split_preview",
          candidateId,
          candidateVersion: Number.isSafeInteger(Number(row.candidateVersion)) && Number(row.candidateVersion) > 0
            ? Number(row.candidateVersion) : 1,
          status: row.status === "superseded" || row.status === "committed" || row.status === "cancelled"
            ? row.status : "pending_confirmation",
          episodeTitle: String(row.episodeTitle || "").trim(),
          segments,
        } : null
      }
      if (type === "episode_boundary_candidate") {
        const candidateId = String(row.candidateId || "").trim()
        const episodeId = String(row.episodeId || "").trim()
        const startOffset = Number(row.startOffset)
        const endOffset = Number(row.endOffset)
        if (!candidateId || !episodeId || !Number.isFinite(startOffset) || !Number.isFinite(endOffset)) return null
        return {
          type: "episode_boundary_candidate",
          candidateId,
          runId: String(row.runId || "").trim() || undefined,
          candidateDigest: String(row.candidateDigest || "").trim() || undefined,
          candidateVersion: Number.isSafeInteger(Number(row.candidateVersion)) ? Number(row.candidateVersion) : undefined,
          status: row.status === "committing" || row.status === "commit_unknown" || row.status === "committed" || row.status === "superseded" || row.status === "cancelled" || row.status === "stale" ? row.status : "pending_confirmation",
          episodeId,
          title: String(row.title || "").trim(),
          startOffset,
          endOffset,
          targetUnits: Number.isFinite(Number(row.targetUnits)) ? Number(row.targetUnits) : undefined,
          actualUnits: Number.isFinite(Number(row.actualUnits)) ? Number(row.actualUnits) : undefined,
          boundaryEndText: String(row.boundaryEndText || "").trim(),
          reason: String(row.reason || "").trim(),
          riskNotes: Array.isArray(row.riskNotes) ? row.riskNotes.map(String).filter(Boolean) : [],
        }
      }
      if (type === "asset_range_candidate") {
        const candidateId = String(row.candidateId || "").trim()
        const rangeId = String(row.rangeId || "").trim()
        const absoluteStart = Number(row.absoluteStart)
        const absoluteEnd = Number(row.absoluteEnd)
        if (!candidateId || !rangeId || !Number.isFinite(absoluteStart) || !Number.isFinite(absoluteEnd)) return null
        const phaseVisualContexts = Array.isArray(row.phaseVisualContexts)
          ? row.phaseVisualContexts.flatMap((item) => {
              if (!item || typeof item !== "object") return []
              const visual = item as Record<string, unknown>
              const visualPrompt = String(visual.visualPrompt || "").trim()
              if (!visualPrompt) return []
              return [{
                name: String(visual.name || "阶段视觉").trim(),
                visualPrompt,
                visualChangeReason: String(visual.visualChangeReason || "").trim() || undefined,
              }]
            })
          : []
        return {
          type: "asset_range_candidate",
          candidateId,
          runId: String(row.runId || "").trim() || undefined,
          candidateDigest: String(row.candidateDigest || "").trim() || undefined,
          candidateVersion: Number.isSafeInteger(Number(row.candidateVersion)) && Number(row.candidateVersion) > 0 ? Number(row.candidateVersion) : undefined,
          status: row.status === "committing" || row.status === "commit_unknown" || row.status === "committed" || row.status === "superseded" || row.status === "cancelled" || row.status === "stale" ? row.status : "pending_confirmation",
          rangeId,
          sourceId: String(row.sourceId || "").trim(),
          absoluteStart,
          absoluteEnd,
          targetUnits: Number.isFinite(Number(row.targetUnits)) && Number(row.targetUnits) > 0 ? Number(row.targetUnits) : undefined,
          actualUnits: Number.isFinite(Number(row.actualUnits)) ? Number(row.actualUnits) : undefined,
          assetTypes: Array.isArray(row.assetTypes) ? row.assetTypes.map(String).filter(Boolean) : [],
          phaseVisualContexts,
          boundaryEndText: String(row.boundaryEndText || "").trim(),
          reason: String(row.reason || "").trim(),
          riskNotes: Array.isArray(row.riskNotes) ? row.riskNotes.map(String).filter(Boolean) : [],
        }
      }
      if (type === "interrupt_notice") {
        const text = String(row.text || row.content || "").trim()
        return text ? { type: "interrupt_notice", text } : null
      }
      if (type === "attachment_error") {
        const text = String(row.text || row.content || "").trim()
        return text
          ? {
              type: "attachment_error",
              kind: String(row.kind || "file"),
              text,
              name: String(row.name || "").trim() || undefined,
              mimeType:
                String(row.mimeType || row.media_type || "").trim() ||
                undefined,
              media_type:
                String(row.media_type || row.mimeType || "").trim() ||
                undefined,
            }
          : null
      }
      if (type === "recommendations") {
        const rawItems = Array.isArray(row.items)
          ? row.items
          : Array.isArray(row.options)
            ? row.options
            : []
        let projectNavigationAdded = false
        const items = rawItems
          .map((item, index): AssistantRecommendationItem | null => {
            if (!item || typeof item !== "object") return null
            const recommendation = item as Record<string, unknown>
            if (recommendation.mode === "navigation") {
              if (recommendation.destination !== "project_session") return null
              if (projectNavigationAdded) return null
              projectNavigationAdded = true
              return {
                id: "open_project_conversation",
                label: "前往项目会话",
                description: String(recommendation.description || "").trim() || undefined,
                mode: "navigation",
                destination: "project_session",
                prompt: "",
                recommended: isAssistantTruthyFlag(recommendation.recommended),
              }
            }
            const label = String(recommendation.label || "").trim()
            const prompt = String(recommendation.prompt || label).trim()
            const action = String(recommendation.action || "").trim()
            const taskType = String(
              recommendation.taskType || recommendation.task_type || ""
            ).trim()
            const rawMode = String(recommendation.mode || "").trim()
            const mode: AssistantRecommendationItem["mode"] =
              rawMode === "action" || action ? "action" : "prompt"
            const rawRecommended =
              recommendation.recommended ??
              recommendation.isRecommended ??
              recommendation.primary
            const rawControlOnly =
              recommendation.controlOnly ?? recommendation.control_only
            const recommended =
              isAssistantTruthyFlag(rawRecommended) ||
              String(recommendation.priority || "")
                .trim()
                .toLowerCase() === "recommended"
            const controlOnly = isAssistantTruthyFlag(rawControlOnly)
            if (!label || !prompt) return null
            return {
              id:
                String(
                  recommendation.id || action || `recommendation-${index}`
                ).trim() || `recommendation-${index}`,
              label,
              description:
                String(recommendation.description || "").trim() || undefined,
              mode,
              prompt,
              action: action || undefined,
              taskType: taskType || undefined,
              controlOnly,
              recommended,
              targetContext:
                recommendation.targetContext &&
                typeof recommendation.targetContext === "object" &&
                !Array.isArray(recommendation.targetContext)
                  ? (recommendation.targetContext as AgentTargetContext)
                  : undefined,
            }
          })
          .filter(Boolean) as AssistantRecommendationItem[]
        return items.length
          ? {
              type: "recommendations",
              title: String(row.title || "下一步建议").trim(),
              origin: ["progress_query", "task_completion", "task_feedback"].includes(String(row.origin || ""))
                ? row.origin as "progress_query" | "task_completion" | "task_feedback"
                : undefined,
              summary: String(row.summary || "").trim() || undefined,
              items,
            }
          : null
      }
      if (type === "image") {
        const source =
          row.source && typeof row.source === "object"
            ? (row.source as {
                type?: string
                media_type?: string
                mimeType?: string
                name?: string
                path?: string
                filePath?: string
                file?: string
                relativePath?: string
                relative_path?: string
              })
            : undefined
        return source ? { type: "image", source } : null
      }
      if (type === "file") {
        const source =
          row.source && typeof row.source === "object"
            ? (row.source as {
                type?: string
                media_type?: string
                mimeType?: string
                name?: string
                path?: string
                filePath?: string
                file?: string
                relativePath?: string
                relative_path?: string
                size?: number
              })
            : undefined
        return source ? { type: "file", source } : null
      }
      return null
    })
    .filter(Boolean) as AssistantContentBlock[]
  return blocks.length || !fallbackText.trim()
    ? blocks
    : [{ type: "text", text: fallbackText.trim() }]
}

export function normalizeAssistantSessionDetail(
  raw?: Partial<AssistantSessionDetail> | null
): AssistantSessionDetail {
  const base = normalizeAssistantSessionSummary(raw)
  const rawMessages = Array.isArray((raw as any)?.messages)
    ? ((raw as any).messages as Array<Record<string, any>>)
    : []
  const messages: AssistantMessage[] = rawMessages.map((message) => ({
    id: message.id ?? createLocalId("assistant-message"),
    role:
      message.role === "assistant"
        ? ("assistant" as AssistantMessageRole)
        : ("user" as AssistantMessageRole),
    text: message.text ?? "",
    createdAt: String(message.createdAt || message.created_at || ""),
    content: normalizeAssistantContentBlocks(
      message.content,
      message.text ?? ""
    ),
    attachments: Array.isArray(message.attachments)
      ? (message.attachments as AssistantSessionAttachment[]).map(
          assistantSessionAttachmentToUi
        )
      : undefined,
  }))
  return {
    ...base,
    messages,
    waitingForInput: base.waitingForInput || Boolean(raw?.pendingQuestion),
    waitingForConfirmation: base.waitingForConfirmation || Boolean(raw?.pendingInteractions?.some((item) => item.active)),
    steps: Array.isArray(raw?.steps) ? raw.steps : [],
    pendingQuestion:
      base.status === "running"
        ? normalizeAssistantPendingQuestion(
            (raw as any)?.pendingQuestion ?? (raw as any)?.pending_question
          )
        : null,
    pendingInteractions: Array.isArray((raw as any)?.pendingInteractions)
      ? (raw as any).pendingInteractions.map(normalizeAssistantPendingInteraction)
          .filter((item: AssistantPendingInteraction | null): item is AssistantPendingInteraction => item !== null)
      : [],
    sdkSessionId: String(
      (raw as any)?.sdkSessionId ?? (raw as any)?.sdk_session_id ?? ""
    ),
    providerInstanceId: String(
      (raw as any)?.providerInstanceId ??
        (raw as any)?.provider_instance_id ??
        ""
    ),
    adapterId: String(
      (raw as any)?.adapterId ?? (raw as any)?.adapter_id ?? ""
    ),
    toolsUsed: Array.isArray(
      (raw as any)?.toolsUsed ?? (raw as any)?.tools_used
    )
      ? (
          ((raw as any)?.toolsUsed ?? (raw as any)?.tools_used) as unknown[]
        ).map(String)
      : [],
  }
}

export function normalizeAssistantPendingQuestion(
  raw: unknown
): AssistantPendingQuestion | null {
  if (!raw || typeof raw !== "object") return null
  const row = raw as Record<string, unknown>
  const questionId = String(row.questionId || row.question_id || "").trim()
  const rawQuestions = Array.isArray(row.questions) ? row.questions : []
  if (!questionId || rawQuestions.length === 0) return null
  const questions = rawQuestions
    .map((question): AssistantPendingQuestionItem | null => {
      if (!question || typeof question !== "object") return null
      const questionRow = question as Record<string, unknown>
      const prompt = String(questionRow.question || "").trim()
      const options = Array.isArray(questionRow.options)
        ? questionRow.options
        : []
      if (!prompt || options.length === 0) return null
      const normalizedOptions = options
        .map((option): AssistantQuestionOption | null => {
          if (!option || typeof option !== "object") return null
          const optionRow = option as Record<string, unknown>
          const label = String(optionRow.label || "").trim()
          if (!label) return null
          return {
            value: String(optionRow.value || "").trim() || undefined,
            label,
            description: String(optionRow.description || "").trim(),
            recommended: Boolean(optionRow.recommended),
          }
        })
        .filter(Boolean) as AssistantQuestionOption[]
      if (!normalizedOptions.length) return null
      return {
        header: String(questionRow.header || "").trim() || undefined,
        question: prompt,
        options: normalizedOptions,
        multiSelect: Boolean(
          questionRow.multiSelect || questionRow.multi_select
        ),
      }
    })
    .filter(Boolean) as AssistantPendingQuestionItem[]
  return questions.length
    ? { question_id: questionId, questionId, questions }
    : null
}

export function normalizeAssistantSnapshotPendingQuestion(
  snapshot?: AssistantSessionSnapshot | null
): AssistantPendingQuestion | null {
  if (snapshot?.status && snapshot.status !== "running") return null
  const pendingQuestions = Array.isArray(snapshot?.pending_questions)
    ? snapshot?.pending_questions
    : []
  for (const question of pendingQuestions) {
    const normalized = normalizeAssistantPendingQuestion(question)
    if (normalized) return normalized
  }
  return null
}

export function compactAssistantLiveText(text: string, limit = 86) {
  const normalized = text.replace(/\s+/g, " ").trim()
  return normalized.length > limit
    ? `${normalized.slice(0, Math.max(0, limit - 3))}...`
    : normalized
}

export function normalizeAssistantLiveActivity(
  raw: unknown
): AssistantLiveActivityItem[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map((item, index): AssistantLiveActivityItem | null => {
      if (typeof item === "string") {
        const text = compactAssistantLiveText(item)
        return text ? { id: `live-${index + 1}`, text } : null
      }
      if (!item || typeof item !== "object") return null
      const row = item as Record<string, unknown>
      const text = compactAssistantLiveText(
        String(row.text || row.label || "").trim()
      )
      if (!text) return null
      return {
        id: String(row.id || `live-${index + 1}`).trim() || `live-${index + 1}`,
        text,
        kind: ["phase", "thought", "tool_use", "tool_result"].includes(String(row.kind || ""))
          ? row.kind as AssistantLiveActivityItem["kind"]
          : undefined,
        phase: ["start", "thinking", "finalizing"].includes(String(row.phase || ""))
          ? row.phase as AssistantLiveActivityItem["phase"]
          : undefined,
        goal: String(row.goal || "").trim() || undefined,
        toolName: String(row.toolName || "").trim() || undefined,
        toolUseId: String(row.toolUseId || "").trim() || undefined,
        isError: typeof row.isError === "boolean" ? row.isError : undefined,
        outcome: row.outcome === "revision_required" ? "revision_required" : undefined,
      }
    })
    .filter(Boolean)
    .slice(
      -ASSISTANT_LIVE_ACTIVITY_HISTORY_LIMIT
    ) as AssistantLiveActivityItem[]
}

export function assistantLiveActivityFromDraftTurn(
  draftTurn: AssistantTurn | null
): AssistantLiveActivityItem[] {
  if (!draftTurn) return []
  const rows: AssistantLiveActivityItem[] = []
  for (const block of draftTurn.content) {
    if (block.type === "thinking" || block.type === "skill_content") {
      rows.push({ id: `draft-${rows.length}`, text: block.text, kind: "thought" })
    } else if (block.type === "tool_use") {
      const summary = assistantToolInputSummary(block)
      rows.push(
        {
          id: `draft-${rows.length}`,
          text: summary
            ? `正在调用 ${assistantToolDisplayName(block.name)}：${summary}`
            : `正在调用 ${assistantToolDisplayName(block.name)}`,
          kind: "tool_use",
          toolName: block.name,
          toolUseId: block.id,
        }
      )
    } else if (block.type === "tool_result") {
      rows.push(
        {
          id: `draft-${rows.length}`,
          text: block.outcome === "revision_required"
            ? "校验未通过，正在修订候选"
            : block.is_error ? "工具返回异常，正在调整处理方式" : "已收到工具结果，正在继续分析",
          kind: "tool_result",
          toolUseId: block.tool_use_id,
          isError: Boolean(block.is_error),
          outcome: block.outcome,
        }
      )
    } else if (block.type === "text") {
      rows.push({ id: `draft-${rows.length}`, text: block.text, kind: "thought" })
    }
  }
  return normalizeAssistantLiveActivity(rows)
}

export function mergeAssistantLiveActivityItems(
  liveItems: AssistantLiveActivityItem[],
  draftItems: AssistantLiveActivityItem[]
): AssistantLiveActivityItem[] {
  if (!liveItems.length) return draftItems
  if (!draftItems.length) return liveItems
  const compact = (item: AssistantLiveActivityItem) => {
    const text = compactAssistantLiveText(item.text)
    return text ? { ...item, text } : null
  }
  const combined = [...liveItems, ...draftItems]
    .map(compact)
    .filter(Boolean) as AssistantLiveActivityItem[]
  const seen = new Set<string>()
  const merged: AssistantLiveActivityItem[] = []
  for (let index = combined.length - 1; index >= 0; index -= 1) {
    const item = combined[index]
    const identity = item.toolUseId && (item.kind === "tool_use" || item.kind === "tool_result")
      ? `${item.kind}:${item.toolUseId}`
      : item.text
    if (seen.has(identity)) continue
    seen.add(identity)
    merged.unshift(item)
  }
  return merged.slice(-ASSISTANT_LIVE_ACTIVITY_HISTORY_LIMIT)
}

export function normalizeAssistantTurnAttachment(
  raw: unknown
): AssistantAttachment | null {
  if (!raw || typeof raw !== "object") return null
  const row = raw as Partial<
    AssistantAttachment & AssistantSessionAttachment
  > & {
    media?: MediaAsset
  }
  const id = String(row.id || createLocalId("assistant-attachment"))
  const media =
    row.media && typeof row.media === "object"
      ? (row.media as MediaAsset)
      : null
  const name = String(row.name || media?.originalName || "附件")
  const mimeType = String(row.mimeType || media?.mimeType || "image/png")
  if (media) {
    return {
      id,
      name,
      mimeType,
      media,
    }
  }
  return assistantSessionAttachmentToUi({
    id,
    name,
    mimeType,
    path: row.path,
    filePath: row.filePath,
    file: row.file,
    relativePath: row.relativePath,
    relative_path: row.relative_path,
    size: row.size,
  })
}

export function assistantContentText(blocks: AssistantContentBlock[]) {
  return blocks
    .map((block) =>
      block.type === "text"
        ? block.text
        : block.type === "source_text"
          ? ""
          : "text" in block
            ? block.text
            : ""
    )
    .filter(Boolean)
    .join("\n")
    .trim()
}

export function normalizeAssistantTurn(
  raw: unknown,
  fallbackId: string
): AssistantTurn | null {
  if (!raw || typeof raw !== "object") return null
  const row = raw as Record<string, unknown>
  const rawType = String(row.type || row.role || "assistant")
  const type: AssistantTurn["type"] =
    rawType === "user" ? "user" : rawType === "system" ? "system" : "assistant"
  const text = String(row.text || row.message || "").trim()
  const content = normalizeAssistantContentBlocks(row.content, text)
  const attachments = Array.isArray(row.attachments)
    ? (row.attachments
        .map(normalizeAssistantTurnAttachment)
        .filter(Boolean) as AssistantAttachment[])
    : []
  return {
    type,
    uuid: String(row.uuid || row.id || fallbackId),
    timestamp: String(row.timestamp || row.createdAt || row.created_at || ""),
    text: text || assistantContentText(content),
    attachments: attachments.length ? attachments : undefined,
    content,
  }
}

export function normalizeAssistantTurns(
  rawTurns: unknown,
  fallbackPrefix: string
) {
  if (!Array.isArray(rawTurns)) return []
  const turns: AssistantTurn[] = []
  rawTurns.forEach((turn, index) => {
    const normalized = normalizeAssistantTurn(
      turn,
      `${fallbackPrefix}-${index + 1}`
    )
    if (normalized) turns.push(normalized)
  })
  return turns
}

export function normalizeAssistantSnapshotTurns(
  snapshot?: AssistantSessionSnapshot | null,
  fallbackSession?: AssistantSessionDetail | null
) {
  const turns = normalizeAssistantTurns(snapshot?.turns, "assistant-turn")
  return turns.length
    ? turns
    : (fallbackSession?.messages.map(assistantMessageToTurn) ?? [])
}

export function normalizeAssistantDraftTurn(
  snapshot?: AssistantSessionSnapshot | null
) {
  return normalizeAssistantTurn(snapshot?.draft_turn, "assistant-draft")
}

export function isAssistantInterruptTurn(turn: AssistantTurn) {
  return (
    turn.type === "system" &&
    turn.content.some((block) => block.type === "interrupt_notice")
  )
}

export function composeAssistantTurns(
  turns: AssistantTurn[],
  draftTurn: AssistantTurn | null
) {
  if (!draftTurn) return turns
  if (turns.some((turn) => turn.uuid === draftTurn.uuid)) return turns
  const lastTurn = turns[turns.length - 1]
  if (lastTurn && isAssistantInterruptTurn(lastTurn)) {
    return [...turns.slice(0, -1), draftTurn, lastTurn]
  }
  return [...turns, draftTurn]
}

export function assistantTurnTextSignature(turn: AssistantTurn | null) {
  if (!turn) return ""
  const contentText = turn.content
    .filter((block) => block.type === "text")
    .map((block) =>
      [block.text, assistantActionFooterText(block.actionFooter)]
        .filter(Boolean)
        .join("")
    )
    .join("")
  const text = contentText || turn.text
  const attachmentNames =
    turn.attachments?.map((item) => item.name).join("|") || ""
  return `${turn.type}:${text.trim()}:${attachmentNames}`
}

export function latestAssistantTurnSignature(turns: AssistantTurn[]) {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index]
    if (turn.type === "assistant") {
      return `${turn.uuid}:${assistantTurnTextSignature(turn)}`
    }
  }
  return ""
}

export function latestUserTurnSignature(turns: AssistantTurn[]) {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index]
    if (turn.type === "user") {
      return assistantTurnTextSignature(turn)
    }
  }
  return ""
}

export function assistantTurnHasRenderableResponse(turn: AssistantTurn) {
  if (turn.type !== "assistant") return false
  if (turn.text.trim()) return true
  return turn.content.some((block) => {
    switch (block.type) {
      case "text":
        return Boolean(
          block.text?.trim() || assistantActionFooterText(block.actionFooter)
        )
      case "thinking":
      case "skill_content":
      case "interrupt_notice":
      case "attachment_error":
        return Boolean(block.text?.trim())
      case "tool_use":
        return Boolean(block.result?.trim() || block.skill_content?.trim())
      case "tool_result":
        return Boolean(block.content?.trim())
      case "source_text":
        return Boolean(block.text?.trim())
      case "episode_boundary_candidate":
      case "asset_range_candidate":
        return Boolean(block.candidateId)
      case "task_progress":
        return Boolean(block.title?.trim() || block.steps?.length)
      case "recommendations":
        return block.items.length > 0
      case "image":
      case "file":
        return Boolean(block.source)
      default:
        return false
    }
  })
}

export function hasAssistantResponseAfterUserTurn(
  turns: AssistantTurn[],
  userTurnSignature: string
) {
  if (!userTurnSignature) return false
  let userTurnIndex = -1
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index]
    if (
      turn.type === "user" &&
      assistantTurnTextSignature(turn) === userTurnSignature
    ) {
      userTurnIndex = index
      break
    }
  }
  if (userTurnIndex < 0) return false
  for (let index = userTurnIndex + 1; index < turns.length; index += 1) {
    if (assistantTurnHasRenderableResponse(turns[index])) return true
  }
  return false
}

export function findLatestAssistantUserTurn(turns: AssistantTurn[]) {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    if (turns[index].type === "user") return turns[index]
  }
  return null
}

export function findLatestOptimisticAssistantUserTurn(turns: AssistantTurn[]) {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index]
    if (turn.type === "user" && turn.uuid?.startsWith("optimistic-")) {
      return turn
    }
  }
  return null
}

export function shouldPreserveLocalUserTurn(
  snapshotTurns: AssistantTurn[],
  currentTurns: AssistantTurn[]
) {
  const localUserTurn = findLatestOptimisticAssistantUserTurn(currentTurns)
  if (!localUserTurn) return false
  const snapshotUserTurn = findLatestAssistantUserTurn(snapshotTurns)
  return (
    assistantTurnTextSignature(localUserTurn) !==
    assistantTurnTextSignature(snapshotUserTurn)
  )
}

export function isAssistantSessionRunning(
  session?: Pick<AssistantSessionSummary, "status"> | null
) {
  return session?.status === "running"
}

export function isAssistantTerminalSessionStatus(
  status?: AssistantSessionSummary["status"] | null
) {
  return (
    status === "completed" || status === "error" || status === "interrupted"
  )
}

export function isAssistantFinishedSessionStatus(
  status?: AssistantSessionSummary["status"] | null
) {
  return isAssistantTerminalSessionStatus(status) || status === "idle"
}

export function assistantToolDisplayName(name: string) {
  if (name === "ai_video_storyboard_action") return "ai-video"
  return name || "Tool"
}

export function assistantToolInputSummary(
  block: Extract<AssistantContentBlock, { type: "tool_use" }>
) {
  const input = block.input ?? {}
  const label = typeof input.label === "string" ? input.label.trim() : ""
  if (label) return label
  const action = typeof input.action === "string" ? input.action.trim() : ""
  if (action) return action
  const command = typeof input.command === "string" ? input.command.trim() : ""
  if (command)
    return command.length > 60 ? `${command.slice(0, 60)}...` : command
  const raw = Object.keys(input).length ? JSON.stringify(input) : ""
  return raw.length > 54 ? `${raw.slice(0, 54)}...` : raw
}

export function getAssistantMessageContentBlocks(
  message: AssistantMessage
): AssistantContentBlock[] {
  if (message.content?.length || !message.text.trim()) {
    return message.content ?? []
  }
  return [{ type: "text", text: message.text } satisfies AssistantContentBlock]
}

export function assistantMessageToTurn(
  message: AssistantMessage
): AssistantTurn {
  return {
    type: message.role,
    uuid: message.id,
    timestamp: message.createdAt,
    text: message.text,
    attachments: message.attachments,
    content: getAssistantMessageContentBlocks(message),
  }
}
