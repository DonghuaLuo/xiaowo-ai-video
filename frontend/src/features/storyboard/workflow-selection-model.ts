import type { StoryboardEdge, StoryboardNode } from "./workflow-canvas-model"
import { isWorkflowItemLocked } from "./workflow-canvas-model"
import { isWorkflowTaskResultEdge } from "./workflow-document-model"
import {
  isCopiedWorkflowAssetNode, isStandaloneWorkflowTaskNode,
  isWorkflowContextDeleteVisible, isWorkflowVisualHandoffOutputEdge,
} from "./workflow-node-relations"

export function canvasSelectionDeleteState(selected: StoryboardNode[], nodes: StoryboardNode[], edges: StoryboardEdge[]) {
  const deleteIds = new Set(selected.map(node => node.id))
  let reason = selected.length ? "" : "请先选择卡片"
  for (const node of selected) {
    if (!isWorkflowContextDeleteVisible(node)) reason ||= "选中卡片中包含不能单独删除的卡片"
    if (isWorkflowItemLocked(node.data)) reason ||= "选中卡片中有已锁定的卡片"
    if (node.data.creationPending) reason ||= "请等待卡片创建完成"
    if (isStandaloneWorkflowTaskNode(node)) {
      for (const result of nodes) {
        if (result.data.resultOfNodeId === node.id && !isCopiedWorkflowAssetNode(result)) deleteIds.add(result.id)
      }
    }
  }
  for (const node of nodes.filter(node => deleteIds.has(node.id))) {
    if (isWorkflowItemLocked(node.data)) reason ||= "关联卡片中有已锁定的卡片"
    if (node.data.activeTask || ["running", "queued", "pending", "cancelling"].includes(String(node.data.status))) {
      reason ||= "选中卡片或关联结果仍有任务执行"
    }
  }
  for (const edge of edges) {
    if (!deleteIds.has(edge.source) && !deleteIds.has(edge.target)) continue
    if (!isWorkflowTaskResultEdge(edge, nodes)) continue
    if (isWorkflowVisualHandoffOutputEdge(edge, nodes) && deleteIds.has(edge.target)) continue
    if (!(deleteIds.has(edge.source) && deleteIds.has(edge.target))) reason ||= "选中卡片包含受保护的系统链接"
  }
  return { reason, totalCount: deleteIds.size }
}

export function isCanvasTextInput(target: EventTarget | null) {
  return target instanceof Element && Boolean(target.closest("input, textarea, select, [contenteditable='true'], [role='textbox']"))
}
