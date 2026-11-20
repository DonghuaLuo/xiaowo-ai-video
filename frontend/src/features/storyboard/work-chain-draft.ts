import type { EpisodeWorkflow, WorkflowChainCreateResult, WorkflowEdge, WorkflowNode } from "@/backend"

export type WorkChainDraft = Pick<WorkflowChainCreateResult, "workChainId" | "segmentId" | "nodes" | "edges" | "routes" | "workChains">

export function createWorkChainDraft(workChainId: string, position: { x: number; y: number }): WorkChainDraft {
  const routeId = `route_${workChainId}`
  const segmentId = `segment_${workChainId}`
  const roles = [
    ["script", "prompt.storyboard", "片段剧本", 340, 280],
    ["director", "director.board", "分镜脚本", 380, 360],
    ["storyboard_card", "storyboard.card", "分镜单元", 380, 300],
    ["storyboard", "storyboard.image", "分镜图", 320, 300],
    ["video", "video.storyboard", "视频生成", 360, 300],
    ["result", "video.result", "视频片段", 360, 260],
  ] as const
  const nodes: WorkflowNode[] = roles.map(([role, type, title, width, height], index) => ({
    id: `${workChainId}_${role}`, type, workChainId, routeId, segmentId,
    strategy: "storyboard_multi_shot",
    position: { x: position.x + index * 613, y: position.y },
    data: {
      title, status: "draft", summary: "保存中", creationPending: true,
      workChainId, routeId, segmentId,
      cardState: { size: { width, height } },
      ...(role === "storyboard" ? { resultOfNodeId: `${workChainId}_storyboard_card` } : {}),
      ...(role === "result" ? { resultOfNodeId: `${workChainId}_video` } : {}),
    },
  }))
  const links = [
    ["prompt", "story", "dependency", "context"],
    ["plan", "story", "dependency", "context"],
    ["storyboard", "generates", "dependency", "generates"],
    ["image", "video_input", "material", "storyboard_image"],
    ["video", "generates", "dependency", "generates"],
  ] as const
  const edges: WorkflowEdge[] = links.map(([sourceHandle, targetHandle, kind, role], index) => ({
    id: `${nodes[index].id}_to_${nodes[index + 1].id}`,
    source: nodes[index].id, target: nodes[index + 1].id, sourceHandle, targetHandle, deletable: false,
    data: { kind, role, workChainId, routeId, segmentId, locked: true, sourceNodeType: nodes[index].type, targetNodeType: nodes[index + 1].type },
  }))
  return {
    workChainId, segmentId, nodes, edges,
    routes: [{ id: routeId, workChainId, segmentId, strategy: "storyboard_multi_shot", status: "draft" }],
    workChains: [{ id: workChainId, label: "独立工作链", origin: { kind: "independent", sourceNodeId: null }, routeIds: [routeId], segmentIds: [segmentId], status: "draft" }],
  }
}

export function preservePendingWorkChains(workflow: EpisodeWorkflow, drafts: Iterable<WorkChainDraft>): EpisodeWorkflow {
  const appendMissing = <T extends { id: string }>(current: T[], incoming: T[]) => {
    const ids = new Set(current.map((item) => item.id))
    return [...current, ...incoming.filter((item) => !ids.has(item.id))]
  }
  let result = workflow
  for (const draft of drafts) {
    result = {
      ...result,
      nodes: appendMissing(result.nodes, draft.nodes),
      edges: appendMissing(result.edges, draft.edges),
      routes: appendMissing(result.routes ?? [], draft.routes),
      workChains: appendMissing(result.workChains ?? [], draft.workChains),
    }
  }
  return result
}
