import { isWorkflowVideoTaskType } from "./workflow-video-task-types"
import {
  canvasPlainObject,
  canvasProjectionRows,
  canvasProjectionText,
} from "./workflow-canvas-mutation-model"
import { compactReadableValue, recordValue } from "./workflow-canvas-model"
import type { NodeEditHistoryItem } from "@/backend"

export type NodeEditHistoryContentColumns = {
  middleTitle: string
  middleText: string
  rightTitle: string
  rightText: string
}

export function nodeEditHistoryDisplayText(value: {
  present: boolean
  text: string
}) {
  if (!value.present) return "暂无记录"
  return value.text || "（已清空）"
}

export function nodeEditHistoryVersionField(
  field: unknown,
  fallbackTitle: string
) {
  const record = recordValue(field)
  if (!Object.keys(record).length) {
    return {
      title: fallbackTitle,
      text: "",
      present: false,
    }
  }
  const hasText = Object.prototype.hasOwnProperty.call(record, "text")
  return {
    title: compactReadableValue(record.title) || fallbackTitle,
    text: compactReadableValue(record.text),
    present: record.present === true || (record.present !== false && hasText),
  }
}

export function nodeEditHistoryVersionColumns(
  item?: NodeEditHistoryItem | null
): NodeEditHistoryContentColumns | null {
  const version = recordValue(item?.version)
  if (!Object.keys(version).length) return null
  const fallback = nodeEditHistoryColumnTitles(item)
  const middle = nodeEditHistoryVersionField(
    version.middle,
    fallback.middleTitle
  )
  const right = nodeEditHistoryVersionField(version.right, fallback.rightTitle)
  return {
    middleTitle: middle.title,
    middleText: nodeEditHistoryDisplayText(middle),
    rightTitle: right.title,
    rightText: nodeEditHistoryDisplayText(right),
  }
}

export function nodeEditHistoryColumnTitles(item?: NodeEditHistoryItem | null) {
  if (item?.nodeType === "prompt.storyboard") {
    return { middleTitle: "原文事实", rightTitle: "影视化剧本" }
  }
  if (item?.nodeType === "director.board") {
    return { middleTitle: "分镜脚本", rightTitle: "参数记录" }
  }
  if (isWorkflowVideoTaskType(item?.nodeType)) {
    return { middleTitle: "参数记录", rightTitle: "视频提示词" }
  }
  return { middleTitle: "修改内容", rightTitle: "提示词记录" }
}

export function nodeEditHistoryContentColumns(
  item?: NodeEditHistoryItem | null
): NodeEditHistoryContentColumns {
  const versionColumns = nodeEditHistoryVersionColumns(item)
  if (versionColumns) return versionColumns
  const titles = nodeEditHistoryColumnTitles(item)
  return {
    middleTitle: titles.middleTitle,
    middleText: "暂无记录",
    rightTitle: titles.rightTitle,
    rightText: "暂无记录",
  }
}

export function nodeEditHistoryParameterTags(
  item?: NodeEditHistoryItem | null
) {
  const parameters = Array.isArray(item?.version?.parameters)
    ? item.version.parameters
    : []
  const tags: string[] = []
  const pushTag = (tag: string) => {
    const text = tag.trim()
    if (text && !tags.includes(text)) tags.push(text)
  }
  parameters.forEach((parameter) => {
    const label = compactReadableValue(parameter.label || parameter.key)
    const value = compactReadableValue(
      parameter.displayValue ?? parameter.value
    )
    if (label) pushTag(value ? `${label} ${value}` : label)
  })
  return tags
}


export function stringArrayValue(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item ?? "").trim()).filter(Boolean)
  }
  if (typeof value === "string" && value.trim()) return [value.trim()]
  return []
}

export function uniqueStringValues(...values: unknown[]): string[] {
  return Array.from(new Set(values.flatMap((value) => stringArrayValue(value))))
}

export function preflightIssueText(value: unknown) {
  if (value && typeof value === "object") {
    const issue = value as Record<string, unknown>
    return String(
      issue.message ??
        issue.title ??
        issue.reason ??
        issue.summary ??
        issue.detail ??
        ""
    ).trim()
  }
  return String(value ?? "").trim()
}

export function isReferenceLimitPreflightIssue(value: unknown) {
  const text = preflightIssueText(value)
  return (
    text.includes("超过模型上限") &&
    (text.includes("参考图") ||
      text.includes("参考素材") ||
      text.includes("资产参考图"))
  )
}

export function canvasNodeEditHistoryProjectionRows(payload: unknown) {
  return canvasProjectionRows(payload)
    .map((row) => {
      const projectionText = canvasProjectionText(row)
      const cacheKey = String(
        row.key ?? row.id ?? row.cacheKey ?? row.cache_key ?? ""
      ).trim()
      if (
        !projectionText.includes("node_edit_history") &&
        !cacheKey.includes("edit_history")
      ) {
        return null
      }
      const keyNodeId = cacheKey.match(/^node:([^:]+):edit_history$/)?.[1]
      const projectionPayload = row.payload
      const payloadRow = canvasPlainObject(projectionPayload)
      const nodeId = String(
        row.nodeId ??
          row.node_id ??
          payloadRow?.nodeId ??
          payloadRow?.node_id ??
          keyNodeId ??
          ""
      ).trim()
      const rawItems = Array.isArray(projectionPayload)
        ? projectionPayload
        : Array.isArray(payloadRow?.items)
          ? payloadRow.items
          : []
      const items = rawItems
        .map(nodeEditHistoryItemFromUnknown)
        .filter((item): item is NodeEditHistoryItem => Boolean(item))
      return nodeId ? { nodeId, items } : null
    })
    .filter(
      (
        row
      ): row is {
        nodeId: string
        items: NodeEditHistoryItem[]
      } => Boolean(row)
    )
}

export function nodeEditHistoryItemFromUnknown(
  value: unknown
): NodeEditHistoryItem | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  const record = value as Record<string, unknown>
  const id = String(record.id ?? "").trim()
  const nodeId = String(record.nodeId ?? record.node_id ?? "").trim()
  const nodeType = String(record.nodeType ?? record.node_type ?? "").trim()
  const version = canvasPlainObject(record.version)
  const restorePatch = canvasPlainObject(record.restorePatch)
  if (
    !id ||
    !nodeId ||
    !nodeType ||
    record.schemaVersion !== 2 ||
    !version ||
    !restorePatch
  ) {
    return null
  }
  return {
    ...(record as unknown as NodeEditHistoryItem),
    id,
    schemaVersion: 2,
    nodeId,
    nodeType,
    version: version as NodeEditHistoryItem["version"],
    restorePatch,
  }
}

export function nodeEditHistoryItemsFromPayload(payload: unknown) {
  const source = canvasPlainObject(payload) ?? {}
  const result = canvasPlainObject(source.result)
  const task = canvasPlainObject(source.task)
  const taskResult = canvasPlainObject(task?.result)
  const candidates = [
    source.editHistory,
    source.edit_history,
    source.editHistoryItems,
    source.edit_history_items,
    result?.editHistory,
    result?.edit_history,
    result?.editHistoryItems,
    result?.edit_history_items,
    taskResult?.editHistory,
    taskResult?.edit_history,
    taskResult?.editHistoryItems,
    taskResult?.edit_history_items,
  ]
  return candidates
    .flatMap((candidate) =>
      Array.isArray(candidate) ? candidate : [candidate]
    )
    .map(nodeEditHistoryItemFromUnknown)
    .filter((item): item is NodeEditHistoryItem => Boolean(item))
}

export function nodeEditHistorySortValue(item: NodeEditHistoryItem) {
  const raw = String(item.createdAt ?? item.displayTime ?? "").trim()
  const parsed = Date.parse(raw)
  return Number.isFinite(parsed) ? parsed : 0
}

export function mergeNodeEditHistoryItems(
  current: NodeEditHistoryItem[],
  incoming: NodeEditHistoryItem[]
) {
  const byId = new Map<string, NodeEditHistoryItem>()
  current.forEach((item) => byId.set(item.id, item))
  incoming.forEach((item) => byId.set(item.id, item))
  return Array.from(byId.values()).sort(
    (a, b) => nodeEditHistorySortValue(b) - nodeEditHistorySortValue(a)
  )
}
