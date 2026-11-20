import type { AgentTargetContext } from "@/backend"

export type CanvasAgentTaskRequest = {
  requestId: number
  taskType:
    | "workflow_cinematic_script_generation"
    | "director_plan_generation"
    | "video_prompt_generation"
    | "video_prompt_standalone_generation"
    | "video_prompt_optimization"
  projectId: string
  episodeId: string
  canvasKind: "work_chain" | "custom"
  canvasId?: string
  canvasTitle?: string
  nodeId: string
  routeId?: string
  workChainId?: string
  nodeType?: "video.storyboard" | "video.keyframe"
  scriptTemplateId?: string
  userInstruction?: string
  reworkRecordIds?: string[]
  draftText?: string
  soundPrompt?: string
  assetNameMap?: Record<string, string>
  promptBindings?: Record<string, string>
}

export type CanvasAgentTaskCanvasRequest = Omit<
  CanvasAgentTaskRequest,
  "requestId"
>

const CANVAS_AGENT_TASK_TYPES = new Set([
  "workflow_cinematic_script_generation",
  "director_plan_generation",
  "video_prompt_generation",
  "video_prompt_standalone_generation",
  "video_prompt_optimization",
])

export function canvasAgentRequestForTarget(
  taskType: string | undefined,
  target: AgentTargetContext | null | undefined,
  projectId: string,
  episodeId: string
): CanvasAgentTaskRequest | null {
  if (
    !taskType ||
    !CANVAS_AGENT_TASK_TYPES.has(taskType) ||
    !target?.nodeId ||
    (target.episodeId && target.episodeId !== episodeId)
  )
    return null
  return {
    requestId: Date.now(),
    taskType: taskType as CanvasAgentTaskRequest["taskType"],
    projectId,
    episodeId,
    canvasKind: target.canvasKind === "custom" ? "custom" : "work_chain",
    canvasId: target.canvasId,
    canvasTitle: target.canvasTitle,
    nodeId: target.nodeId,
    routeId: target.routeId,
    workChainId: target.workChainId,
    nodeType:
      target.nodeType === "video.keyframe" ? "video.keyframe" : undefined,
  }
}
