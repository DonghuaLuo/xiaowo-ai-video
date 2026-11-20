export const WORKFLOW_VIDEO_TASK_TYPES: ReadonlySet<string> = new Set([
  "video.storyboard",
  "video.keyframe",
  "video.character_replace",
])

export function isWorkflowVideoTaskType(value?: string | null) {
  return WORKFLOW_VIDEO_TASK_TYPES.has((value ?? "").trim())
}
