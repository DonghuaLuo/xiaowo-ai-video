import type { AssistantLiveActivityItem } from "./assistant-session-normalization"

export type AssistantDispatchStage = {
  key: string
  label: string
  status: "running" | "completed" | "waiting" | "revision" | "error"
  operations: number
}

const STAGE_LABELS: Record<string, string> = {
  understand: "理解任务",
  skill: "准备执行方法",
  read: "读取相关资料",
  work: "分析与修订",
  validate: "生成并核验候选",
  write: "更新项目数据",
  tool: "执行任务操作",
  report: "整理结果报告",
  waiting: "等待你的补充",
}

export function isInternalDispatchActivity(item: AssistantLiveActivityItem): boolean {
  return item.text.trimStart().startsWith("Base directory for this skill:")
}

export function assistantDispatchDetailItems(items: AssistantLiveActivityItem[]): AssistantLiveActivityItem[] {
  const toolUseIds = new Set(items.filter((item) => item.kind === "tool_use" && item.toolUseId)
    .map((item) => item.toolUseId as string))
  return items.filter((item) => item.kind !== "tool_result"
    || !item.toolUseId || !toolUseIds.has(item.toolUseId))
}

function stageForTool(name: string): string {
  const tool = name.trim().replace(/^mcp__ai_video__/, "").toLowerCase()
  if (tool === "skill") return "skill"
  if (/^(get|read|search|list)_/.test(tool)) return "read"
  if (/^(submit|propose|validate|review|check)_/.test(tool)) return "validate"
  if (/^(commit|save|update|upsert|patch|delete|create|link|unlink)_/.test(tool)) return "write"
  return "tool"
}

export function summarizeAssistantDispatch(
  items: AssistantLiveActivityItem[],
  waitingForInput: boolean
): AssistantDispatchStage[] {
  const stages: AssistantDispatchStage[] = []
  const toolStages = new Map<string, string>()
  let currentKey = ""
  let lastToolKey = ""

  const touch = (key: string, countOperation = false) => {
    if (currentKey && currentKey !== key) {
      const previous = stages.find((stage) => stage.key === currentKey)
      if (previous?.status === "running") previous.status = "completed"
    }
    const existingIndex = stages.findIndex((stage) => stage.key === key)
    const stage = existingIndex >= 0
      ? stages.splice(existingIndex, 1)[0]
      : { key, label: STAGE_LABELS[key], status: "running" as const, operations: 0 }
    stage.status = "running"
    if (countOperation) stage.operations += 1
    stages.push(stage)
    currentKey = key
  }

  for (const item of items) {
    if (isInternalDispatchActivity(item)) continue
    if (item.kind === "phase") {
      touch(item.phase === "finalizing" ? "report" : "understand")
    } else if (item.kind === "tool_use") {
      const key = stageForTool(item.toolName || "")
      touch(key, true)
      lastToolKey = key
      if (item.toolUseId) toolStages.set(item.toolUseId, key)
    } else if (item.kind === "tool_result") {
      const key = toolStages.get(item.toolUseId || "") || lastToolKey
      const stage = stages.find((row) => row.key === key)
      if (stage) {
        stage.status = item.outcome === "revision_required" ? "revision" : item.isError ? "error" : "completed"
        if (currentKey === key) currentKey = ""
      }
    } else if (item.kind === "thought") {
      touch("work")
    } else {
      touch("tool")
    }
  }

  if (waitingForInput) {
    touch("waiting")
    stages[stages.length - 1].status = "waiting"
  }
  return stages.slice(-4)
}
