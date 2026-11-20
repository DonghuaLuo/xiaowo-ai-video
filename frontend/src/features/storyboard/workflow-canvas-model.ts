import { WORKFLOW_VIDEO_TASK_TYPES, isWorkflowVideoTaskType } from "./workflow-video-task-types"
export { WORKFLOW_VIDEO_TASK_TYPES, isWorkflowVideoTaskType } from "./workflow-video-task-types"
import {
  type DirectorRuleOption,
  type EpisodeWorkflow,
  type InputImageFile,
  type MediaAsset,
  type ModelCapabilitiesSnapshot,
  type ScriptAdaptationTemplateOption,
  type TaskRow,
  type VideoPromptDraftRequest,
  type WorkflowEdge,
  type WorkflowNode,
  type WorkflowRoute,
} from "@/backend"
import {
  storyboardTemplateDisplayName,
  type StoryboardTemplateOption,
} from "@/features/settings/storyboard-templates"
import { type Edge, type Node } from "@xyflow/react"
import { type FrameReferenceOptions } from "./frame-reference-menu"
import {
  workflowVideoTaskDefaultDurationValue,
} from "./workflow-model-capabilities"

export type WorkflowNodeData = {
  storyboardSaveFailed?: boolean
  storyboardFailedSaveKind?: "settings" | "plan"
  onDiscardStoryboardSave?: (nodeId: string) => WorkflowNodeData | undefined
  sourceMode?: "independent"
  useProjectVisual?: boolean
  creationPending?: boolean
  projectId?: string
  episodeId?: string
  episodeTitle?: string
  nodeId?: string
  title: string
  eyebrow: string
  summary: string
  status:
    | "ready"
    | "draft"
    | "waiting"
    | "running"
    | "blocked"
    | "preflight_failed"
    | "queued"
    | "processing"
    | "waiting_upstream"
    | "cancelled"
    | "canceled"
    | "succeeded"
    | "failed"
  model?: string
  metric?: string
  action?: string
  cost?: string
  duration?: string
  tone: string
  activeVersionId?: string | null
  sourceVersionId?: string | null
  activeMediaVersionId?: string | null
  panels?: Array<Record<string, unknown>>
  storyboardAnalysis?: Record<string, unknown> | null
  storyboardAnalysisStoryTextHash?: string
  storyboard_analysis_story_text_hash?: string
  storyboardPlanHash?: string
  storyboard_plan_hash?: string
  storyboardPlanState?: string
  storyboard_plan_state?: string
  scriptManualEdited?: boolean
  script_manual_edited?: boolean
  workChainId?: string
  routeId?: string
  routeLabel?: string
  routeStatus?: string
  locked?: boolean
  lockedByUser?: boolean
  preserveOnReplan?: boolean
  lockedReason?: string
  segmentId?: string
  segmentOrder?: number
  strategy?: string
  durationSeconds?: number | string | null
  storyboardTemplate?: string
  storyboardTemplateLabel?: string
  cinematicStoryText?: string
  scriptContinuityReview?: { previousScriptHash: string; scriptHash: string }
  cinematic_story_text?: string
  sourceFactText?: string
  source_fact_text?: string
  content?: string
  prompt?: string | Record<string, unknown>
  prompts?: Record<string, unknown>
  scriptTemplateId?: string
  scriptTemplateLabel?: string
  scriptUserInstruction?: string
  script_user_instruction?: string
  adaptationStyle?: Record<string, unknown>
  adaptation_style?: Record<string, unknown>
  directorPlan?: string | Record<string, unknown>
  directorPlanShots?: Array<Record<string, unknown>>
  storyboardAllocation?: {
    schemaVersion: number
    directorPlanHash: string
    groups: Array<{ id: string; shotNos: number[]; order: number; reason?: string }>
  }
  shotGroupId?: string
  shotGroupOrder?: number
  shotNos?: number[]
  speakerRoster?: Array<Record<string, unknown>>
  speechBudgetNote?: string
  rhythmMultiplier?: number | null
  directorRuleId?: string | null
  directorRuleSelectionMode?: "auto" | "manual" | null
  directorRuleOptions?: Array<Pick<DirectorRuleOption, "id" | "title" | "description">>
  voiceStyle?: string
  sourceText?: string
  videoTaskNodeId?: string
  episodeScript?: string
  anchorText?: string
  anchorSource?: string
  screenplay?: Record<string, unknown>
  dialogue?: Array<Record<string, unknown>> | Record<string, unknown>
  assetRefs?: Array<Record<string, unknown>> | Record<string, unknown>
  missingAssetRefs?: Array<Record<string, unknown>>
  missingAssetRefsConfirmed?: Record<string, unknown> | boolean
  sourceRefs?: Array<Record<string, unknown>>
  referencePlan?: Record<string, unknown>
  inputLinks?: Array<Record<string, unknown>>
  referenceVideoThumbnails?: Array<Record<string, unknown>>
  referenceManifest?: Array<Record<string, unknown>>
  referenceDisplayRows?: Array<Record<string, unknown>>
  referenceUsage?: Record<string, boolean>
  referenceThumbnails?: Array<Record<string, unknown>>
  assetThumbnails?: Array<Record<string, unknown>>
  assetReferenceMediaIds?: string[]
  inputContract?: Record<string, unknown>
  needsRelink?: Array<Record<string, unknown>>
  storyboardTaskCard?: Record<string, unknown>
  directorTaskCard?: Record<string, unknown>
  videoTaskCard?: Record<string, unknown>
  frameSlot?: string
  shots?: Array<Record<string, unknown>>
  shotIds?: string[]
  shotTimingPlan?: Record<string, unknown> | null
  sourceNodeId?: string
  resultOfNodeId?: string
  quality?: Record<string, unknown>
  modelSelection?: Record<string, unknown>
  capabilityRequirements?: Record<string, unknown>
  capabilityCheck?: Record<string, unknown>
  generationConfig?: Record<string, unknown>
  resolvedConfig?: Record<string, unknown>
  modelCapabilitiesSnapshot?: ModelCapabilitiesSnapshot | null
  referenceMediaIds?: string[]
  winnerVersionId?: string | null
  selectionReason?: string | null
  selectedAt?: string | null
  variantSelection?: Record<string, unknown>
  cardState?: Record<string, unknown>
  visibilityScope?: "node" | "route" | "workChain" | "global" | string
  sourceType?: "asset" | "media" | "version" | string
  canvasNodeRole?: "image_asset" | string
  assetScope?: "reusable" | "result" | string
  assetKind?: string
  rootAssetId?: string
  rootAssetType?: string
  rootAssetProjectId?: string
  assetId?: string
  assetVersionId?: string
  assetType?: string
  assetName?: string
  mediaId?: string
  mediaVersionId?: string
  media?: MediaAsset | null
  storage?: MediaAsset | null
  mediaKind?: "image" | "video" | string
  media_kind?: string
  mediaType?: string
  media_type?: string
  mediaPurpose?: string
  preferredTargetSlot?: string
  width?: number
  height?: number
  aspectRatio?: string
  sourceFileName?: string
  copiedFromNodeId?: string
  provenance?: Record<string, unknown>
  storyboardTemplates?: StoryboardTemplateOption[]
  scriptAdaptationTemplates?: ScriptAdaptationTemplateOption[]
  onRun?: (nodeId: string) => void
  onSaveInlineEdit?: (
    nodeId: string,
    patch: WorkflowInlineEditPatch,
    options?: ManualSaveOptions
  ) => Promise<void> | void
  onUpdateNodeData?: (
    nodeId: string,
    patch: Partial<WorkflowNodeData>,
    reason: string,
    options?: ManualSaveOptions
  ) => Promise<void> | void
  onSaveStoryboardUnitShots?: (
    nodeId: string,
    shots: Array<Record<string, unknown>>,
    speakerRoster: Array<Record<string, unknown>>,
    expectedShots: Array<Record<string, unknown>>,
    expectedSpeakerRoster: Array<Record<string, unknown>>,
    sourceShotNos?: Array<number | null>,
  ) => Promise<void> | void
  onUpdateReferenceUsage?: (nodeId: string, sourceNodeId: string, enabled: boolean) => void
  onUpdateFrameReference?: (nodeId: string, sourceNodeId: string, options: FrameReferenceOptions) => void
  onRemoveInputLink?: (nodeId: string, inputLinkId: string) => void
  onFocusNode?: (nodeId: string) => void
  onSubmitStoryboardImageEdit?: (
    nodeId: string,
    prompt: string,
    referenceFiles: InputImageFile[],
    options?: WorkflowImageEditOptions
  ) => Promise<boolean | void> | boolean | void
  onGenerateCinematicScript?: (
    nodeId: string,
    options?: {
      scriptTemplateId?: string
      userInstruction?: string
    }
  ) => Promise<void> | void
  onGenerateFinalVideoPrompt?: (nodeId: string) => Promise<void> | void
  onOptimizeVideoPrompt?: (nodeId: string, request: VideoPromptDraftRequest) => Promise<boolean>
  hideTaskParameterPanel?: boolean
  workflowCardDetailLoaded?: boolean
  isHydratingWorkflowCard?: boolean
  videoTaskAttachedToWorkChain?: boolean
  videoPromptSyncing?: boolean
  focusToken?: number
  activeTask?: TaskRow | null
}

export type ManualSaveOptions = {
  successMessage?: string
  showSuccess?: boolean
}

export type WorkflowInlineEditPatch = {
  data?: Partial<WorkflowNodeData>
  generationConfig?: Record<string, unknown>
  reason?: string
}

export type WorkflowImageEditOptions = {
  useOriginal?: boolean
  hideTurnaroundHeads?: boolean
  useProjectVisual?: boolean
  storyboardTemplate?: string
  modelId?: string
  providerId?: string
  resolution?: string
  resolvedConfig?: Record<string, unknown>
  allowGenerationConfigOverride?: boolean
}

export type WorkflowNodeActions = {
  projectId: string
  episodeId: string
  episodeTitle?: string
  onRun: (nodeId: string) => void
  onSaveInlineEdit: (
    nodeId: string,
    patch: WorkflowInlineEditPatch,
    options?: ManualSaveOptions
  ) => Promise<void> | void
  onUpdateNodeData: (
    nodeId: string,
    patch: Partial<WorkflowNodeData>,
    reason: string,
    options?: ManualSaveOptions
  ) => Promise<void> | void
  onSaveStoryboardUnitShots: (
    nodeId: string,
    shots: Array<Record<string, unknown>>,
    speakerRoster: Array<Record<string, unknown>>,
    expectedShots: Array<Record<string, unknown>>,
    expectedSpeakerRoster: Array<Record<string, unknown>>,
    sourceShotNos?: Array<number | null>,
  ) => Promise<void> | void
  onDiscardStoryboardSave?: (nodeId: string) => WorkflowNodeData | undefined
  onUpdateReferenceUsage: (nodeId: string, sourceNodeId: string, enabled: boolean) => void
  onUpdateFrameReference: (nodeId: string, sourceNodeId: string, options: FrameReferenceOptions) => void
  onRemoveInputLink: (nodeId: string, inputLinkId: string) => void
  onFocusNode: (nodeId: string) => void
  onSubmitStoryboardImageEdit: (
    nodeId: string,
    prompt: string,
    referenceFiles: InputImageFile[],
    options?: WorkflowImageEditOptions
  ) => Promise<boolean | void> | boolean | void
  modelCapabilitiesSnapshot?: ModelCapabilitiesSnapshot | null
  storyboardTemplates?: StoryboardTemplateOption[]
  scriptAdaptationTemplates?: ScriptAdaptationTemplateOption[]
  onGenerateCinematicScript?: (
    nodeId: string,
    options?: {
      scriptTemplateId?: string
      userInstruction?: string
    }
  ) => Promise<void> | void
  onGenerateFinalVideoPrompt?: (nodeId: string) => Promise<void> | void
  onOptimizeVideoPrompt?: (nodeId: string, request: VideoPromptDraftRequest) => Promise<boolean>
}

export const DEFAULT_STORYBOARD_TEMPLATES: StoryboardTemplateOption[] = []

export function storyboardTemplateId(
  value: unknown,
  templates: StoryboardTemplateOption[] = DEFAULT_STORYBOARD_TEMPLATES
): string {
  const text = String(value ?? "").trim()
  if (!text) return templates[0]?.id ?? ""
  const normalized = text.toLocaleLowerCase()
  const matched = templates.find((template) =>
    [
      template.id,
      template.label,
      template.name,
      storyboardTemplateDisplayName(template),
    ].some(
      (candidate) =>
        String(candidate ?? "")
          .trim()
          .toLocaleLowerCase() === normalized
    )
  )
  return matched?.id ?? text
}

export function storyboardTemplateLabel(
  value: unknown,
  templates: StoryboardTemplateOption[] = DEFAULT_STORYBOARD_TEMPLATES
) {
  const id = storyboardTemplateId(value, templates)
  const template = templates.find((option) => option.id === id)
  if (template) return storyboardTemplateDisplayName(template)
  return id || "未加载版式"
}

export type StoryboardNode = Node<WorkflowNodeData, "storyboardNode">

export type StoryboardEdgeData = {
  workflowEdgeId?: string
  kind?: "material" | "dependency" | string
  role: string
  inputLinkId?: string
  sourceType?: string
  sourceNodeType?: string
  targetNodeType?: string
  targetSlot?: string
  workChainId?: string
  routeId?: string
  segmentId?: string
  locked?: boolean
  lockedByUser?: boolean
  preserveOnReplan?: boolean
  lockedReason?: string
}

export type StoryboardEdge = Edge<StoryboardEdgeData>

export function isInlineMediaSource(value?: string | null) {
  return value?.trim().toLowerCase().startsWith("data:") ?? false
}

export function canvasMediaReference(media?: MediaAsset | null): MediaAsset | null {
  if (!media) return null
  const preview =
    media.preview && !isInlineMediaSource(media.preview)
      ? media.preview
      : undefined
  const url =
    media.url && !isInlineMediaSource(media.url) ? media.url : undefined
  const reference: MediaAsset = {
    id: media.id,
    assetType: media.assetType,
    frameOrigin: media.frameOrigin,
    kind: media.kind,
    originalName: media.originalName,
    mimeType: media.mimeType,
    width: media.width,
    height: media.height,
    aspectRatio: media.aspectRatio,
    duration: media.duration,
    size: media.size,
    format: media.format,
    fps: media.fps,
    path: media.path,
    filePath: media.filePath,
    file: media.file,
    pngFile: media.pngFile,
    relativePath: media.relativePath,
    relative_path: media.relative_path,
    thumbnail: media.thumbnail,
    thumbnailPath: media.thumbnailPath,
    thumbnailFile: media.thumbnailFile,
    thumbnailRelativePath: media.thumbnailRelativePath,
    url,
    preview,
  }
  return reference
}

export const CANVAS_NODE_ROLE_IMAGE_ASSET = "image_asset"

export const WORKFLOW_ASSET_INPUT_HANDLE = "asset_input"

export const WORKFLOW_VIDEO_INPUT_HANDLE = "video_input"

export const OBSOLETE_WORKFLOW_NODE_TYPES = new Set(["workflow.run", "chain.run"])

export function isObsoleteWorkflowNodeType(value?: string | null) {
  return OBSOLETE_WORKFLOW_NODE_TYPES.has(value ?? "")
}

export function isWorkflowResultImageType(value?: string | null) {
  const type = value ?? ""
  return type === "storyboard.image"
}

export function workflowCanvasNodeRole(data?: { canvasNodeRole?: unknown } | null) {
  return optionalString(data?.canvasNodeRole)
}

export function workflowNodeDataIsIndependentImageAsset(
  data?: { canvasNodeRole?: unknown } | null
) {
  return workflowCanvasNodeRole(data) === CANVAS_NODE_ROLE_IMAGE_ASSET
}

export function workflowNodeDataIsWorkChainStoryboardResult(
  data?: { eyebrow?: unknown; canvasNodeRole?: unknown } | null
) {
  return Boolean(
    data &&
    isWorkflowResultImageType(String(data.eyebrow ?? "")) &&
    !workflowNodeDataIsIndependentImageAsset(data)
  )
}

export type WorkflowNodeDataLookup = Record<string, unknown> & {
  activeMediaVersionId?: unknown
  activeVersionId?: unknown
  assetKind?: unknown
  assetType?: unknown
  eyebrow?: unknown
  media?: MediaAsset | null
  mediaPurpose?: unknown
  mediaVersionId?: unknown
  preferredTargetSlot?: unknown
  storage?: MediaAsset | null
}

export function workflowNodeDataCurrentVersionId(
  data?: WorkflowNodeDataLookup | null
) {
  return (
    optionalString(data?.activeVersionId) ||
    optionalString(data?.activeMediaVersionId) ||
    optionalString(data?.mediaVersionId) ||
    null
  )
}

export function isDirectorBoardNodeType(value?: string | null) {
  return value === "director.board"
}

export function isStoryboardCardNodeType(value?: string | null) {
  return value === "storyboard.card"
}

export function workflowNodeOwnsGenerationConfig(value?: string | null) {
  return isDirectorBoardNodeType(value) || isStoryboardCardNodeType(value) || isWorkflowVideoTaskType(value)
}

export function canonicalWorkflowInputHandle(handle?: string | null) {
  const value = String(handle ?? "")
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[\s:-]+/g, "_")
    .toLowerCase()
  if (!value) return ""
  const matches = (target: string) =>
    value === target ||
    value.startsWith(`${target}_`) ||
    value.endsWith(`_${target}`) ||
    value.includes(`_${target}_`)
  if (matches(WORKFLOW_ASSET_INPUT_HANDLE)) return WORKFLOW_ASSET_INPUT_HANDLE
  if (matches(WORKFLOW_VIDEO_INPUT_HANDLE)) return WORKFLOW_VIDEO_INPUT_HANDLE
  return ""
}

export function canonicalTargetSlot(handle?: string | null) {
  const value = (handle ?? "")
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[\s-]+/g, "_")
    .toLowerCase()
  if (canonicalWorkflowInputHandle(value)) {
    return "storyboard_image"
  }
  if (value === "character") return "character_reference"
  if (value === "creature") return "creature_reference"
  if (value === "scene") return "scene_reference"
  if (value === "prop") return "prop_reference"
  if (value === "asset") return "storyboard_image"
  if (value === "reference") return "storyboard_image"
  if (
    value === "visual_handoff" ||
    value === "visual_handoff_reference" ||
    value === "handoff" ||
    value === "continuity"
  )
    return "visual_handoff_reference"
  if (value === "visual" || value === "visual_reference")
    return "storyboard_image"
  if (value === "video_reference") return "reference_video"
  if (value === "image") return "storyboard_image"
  if (value === "frame_image") return "frame_reference"
  return value || "storyboard_image"
}

export function optionalString(value: unknown) {
  const text = String(value ?? "").trim()
  return text || undefined
}

export const initialNodes: StoryboardNode[] = []

export const initialEdges: StoryboardEdge[] = []

export function detailPreview(value: unknown) {
  if (value == null) return ""
  if (typeof value === "string") return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

export function compactReadableValue(value: unknown) {
  if (value == null) return ""
  if (typeof value === "string") return value.trim()
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value)
  }
  return ""
}

export function storyboardStoryTextForNode(data: WorkflowNodeData) {
  return compactReadableValue(data.cinematicStoryText)
}

export function directorPlanTextForNode(data: WorkflowNodeData) {
  return compactReadableValue(data.directorPlan)
}

export function promptTextForNode(data: WorkflowNodeData) {
  const prompt = data.prompt
  if (data.eyebrow === "source.text") {
    return sourceTextForNode(data)
  }
  if (data.eyebrow === "prompt.storyboard") {
    return storyboardStoryTextForNode(data)
  }
  if (isDirectorBoardNodeType(data.eyebrow)) {
    return directorPlanTextForNode(data)
  }
  if (isWorkflowVideoTaskType(data.eyebrow)) {
    const card = recordValue(data.videoTaskCard)
    const value = card.finalVideoPrompt
    return compactReadableValue(value)
  }
  if (typeof prompt === "string") return prompt
  return detailPreview(prompt)
}

export function sourceTextForNode(data: WorkflowNodeData) {
  return String(data.sourceText ?? "").trim()
}

export function numberInputValue(value: unknown) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? String(parsed) : ""
}

export function workflowVideoTaskInputDurationValue(data?: WorkflowNodeData | null) {
  if (!data) return ""
  const taskCard = recordValue(data.videoTaskCard)
  return numberInputValue(data.durationSeconds ?? taskCard.durationSeconds)
}

export function workflowVideoTaskResolvedDurationValue(
  data?: WorkflowNodeData | null
) {
  if (!data) return ""
  if (!promptTextForNode(data).trim()) return ""
  const taskCard = recordValue(data.videoTaskCard)
  const generatedDuration = numberInputValue(
    data.durationSeconds ?? taskCard.durationSeconds
  )
  return generatedDuration || workflowVideoTaskSelectedDurationValue(data)
}

export function workflowVideoTaskSelectedDurationValue(
  data?: WorkflowNodeData | null
) {
  return (
    workflowVideoTaskInputDurationValue(data) ||
    workflowVideoTaskDefaultDurationValue(data)
  )
}

export type WorkflowVideoTaskActionOptions = {
  videoTaskReady?: boolean
  activeTaskType?: string
}

export function workflowTone(nodeType: string) {
  if (nodeType === "source.text") return "from-indigo-500 to-sky-400"
  if (isDirectorBoardNodeType(nodeType)) return "from-cyan-500 to-blue-400"
  if (isStoryboardCardNodeType(nodeType)) return "from-sky-500 to-cyan-400"
  if (nodeType === "prompt.storyboard") return "from-violet-500 to-fuchsia-400"
  if (nodeType === "storyboard.image") return "from-sky-500 to-emerald-400"
  if (nodeType === "video.result" || WORKFLOW_VIDEO_TASK_TYPES.has(nodeType))
    return "from-emerald-500 to-teal-400"
  return "from-slate-500 to-sky-400"
}

export function workflowAction(
  nodeType: string,
  _options: WorkflowVideoTaskActionOptions = {}
) {
  if (isDirectorBoardNodeType(nodeType)) return "生成分镜脚本"
  if (nodeType === "prompt.storyboard") return "生成片段剧本"
  if (WORKFLOW_VIDEO_TASK_TYPES.has(nodeType)) {
    return "生成视频"
  }
  return ""
}

export type WorkflowNodeLike = {
  type?: unknown
  workChainId?: unknown
  routeId?: unknown
  data?: unknown
}

export function workflowNodeLikeData(node?: WorkflowNodeLike | null) {
  return recordValue(node?.data)
}

export function workflowNodeTypeValue(node?: WorkflowNodeLike | null) {
  const data = workflowNodeLikeData(node)
  return optionalString(data.eyebrow) || optionalString(node?.type)
}

export function workflowNodeWorkChainId(node?: WorkflowNodeLike | null) {
  const data = workflowNodeLikeData(node)
  // Backend records own this field; React Flow exposes it through the data projection.
  return node?.type && node.type !== "storyboardNode"
    ? optionalString(node.workChainId)
    : optionalString(data.workChainId)
}

export type WorkflowVideoTaskScope = "work_chain" | "standalone"

export function workflowVideoTaskScope(node?: WorkflowNodeLike | null): WorkflowVideoTaskScope | "" {
  if (!node || !isWorkflowVideoTaskType(workflowNodeTypeValue(node))) return ""
  return workflowNodeWorkChainId(node) ? "work_chain" : "standalone"
}

export function workflowTaskResultEdgeByTypes(
  edge: {
    data?: Partial<StoryboardEdgeData> | null
    targetHandle?: string | null
  },
  sourceType?: string | null,
  targetType?: string | null
) {
  const source = sourceType ?? ""
  const target = targetType ?? ""
  const role = edge.data?.role ?? ""
  const targetSlot = edge.data?.targetSlot ?? edge.targetHandle ?? ""
  if (isStoryboardCardNodeType(source) && isWorkflowResultImageType(target)) {
    return role === "generates" || targetSlot === "generates" || !role
  }
  if (isWorkflowVideoTaskType(source) && target === "video.result") {
    return (
      role === "generates" ||
      targetSlot === "generates" ||
      targetSlot === "video_result" ||
      !role
    )
  }
  return false
}

export function workflowSourceStoryboardEdgeByTypes(
  edge: {
    data?: Partial<StoryboardEdgeData> | null
    targetHandle?: string | null
  },
  sourceType?: string | null,
  targetType?: string | null
) {
  const source = sourceType ?? ""
  const target = targetType ?? ""
  const role = edge.data?.role ?? ""
  const targetSlot = edge.data?.targetSlot ?? edge.targetHandle ?? ""
  return (
    source === "source.text" &&
    target === "prompt.storyboard" &&
    (role === "context" || targetSlot === "story" || !role)
  )
}

export function workflowSourceVideoTextEdgeByTypes(
  edge: {
    data?: Partial<StoryboardEdgeData> | null
    targetHandle?: string | null
  },
  sourceType?: string | null,
  targetType?: string | null
) {
  const source = sourceType ?? ""
  const target = targetType ?? ""
  const role = edge.data?.role ?? ""
  const targetSlot = edge.data?.targetSlot ?? edge.targetHandle ?? ""
  return (
    source === "source.text" &&
    isWorkflowVideoTaskType(target) &&
    (role === "context" ||
      targetSlot === "story" ||
      targetSlot === WORKFLOW_VIDEO_INPUT_HANDLE ||
      !role)
  )
}

export function workflowVideoTaskCardDataIsReady(data?: WorkflowNodeData | null) {
  if (!data || !isWorkflowVideoTaskType(data.eyebrow)) return false
  return Boolean(
    promptTextForNode(data).trim() &&
    workflowVideoTaskResolvedDurationValue(data)
  )
}

export function isWorkflowItemLocked(item?: unknown) {
  const record = recordValue(item)
  return Boolean(
    record.locked || record.lockedByUser || record.preserveOnReplan
  )
}

export function workflowNodeStatus(
  value: string | undefined
): WorkflowNodeData["status"] {
  if (
    value === "ready" ||
    value === "waiting" ||
    value === "running" ||
    value === "blocked" ||
    value === "preflight_failed" ||
    value === "queued" ||
    value === "processing" ||
    value === "waiting_upstream" ||
    value === "cancelled" ||
    value === "canceled" ||
    value === "succeeded" ||
    value === "failed"
  )
    return value
  return "draft"
}

export function isGenericSourceTextTitle(title: unknown, episodeId?: unknown) {
  const trimmed = String(title ?? "").trim()
  const normalized = trimmed.replace(/\s+/g, "").toLowerCase()
  const episodeCode = sourceCardEpisodeCode(episodeId)
  const episodeNumber = episodeCode.match(/\d+/)?.[0]
  const genericTitles = new Set(
    [
      episodeCode,
      episodeNumber ? `E${Number(episodeNumber)}` : "",
      episodeNumber ? `第${Number(episodeNumber)}集` : "",
      episodeNumber ? `第${Number(episodeNumber)}集原文` : "",
      episodeNumber ? `Episode${Number(episodeNumber)}` : "",
      episodeNumber ? `EP${Number(episodeNumber)}` : "",
      "分集原文",
      "本集原文",
      "原文",
    ]
      .map((item) => item.replace(/\s+/g, "").toLowerCase())
      .filter(Boolean)
  )
  return (
    !trimmed ||
    genericTitles.has(normalized) ||
    /^第\s*\d+\s*集原文$/.test(trimmed) ||
    /^第\s*\d+\s*集$/.test(trimmed) ||
    /^第[零〇一二三四五六七八九十百千万两]+\s*集原文$/.test(trimmed) ||
    /^第[零〇一二三四五六七八九十百千万两]+\s*集$/.test(trimmed)
  )
}

export function sourceCardEpisodeCode(episodeId: unknown) {
  const raw = String(episodeId ?? "").trim()
  if (!raw) return "E01"
  const explicit = raw.match(/^E\s*0*(\d+)$/i)
  if (explicit) {
    return `E${String(Number(explicit[1])).padStart(2, "0")}`
  }
  const digits = raw.match(/\d+/)?.[0]
  if (digits) {
    return `E${String(Number(digits)).padStart(2, "0")}`
  }
  return raw.toUpperCase()
}

export function sourceCardDisplayTitle(title: unknown, episodeId?: unknown) {
  const trimmed = String(title ?? "").trim()
  if (isGenericSourceTextTitle(trimmed, episodeId)) return ""
  const withoutPrefix = trimmed
    .replace(/^E\s*0*\d+\s*[·:：\-—_ ]+/, "")
    .replace(/^EP\s*0*\d+\s*[·:：\-—_ ]+/i, "")
    .replace(/^Episode\s*0*\d+\s*[·:：\-—_ ]+/i, "")
    .replace(
      /^第\s*[\d零〇一二三四五六七八九十百千万两]+\s*集\s*[·:：\-—_ ]+/,
      ""
    )
    .trim()
  if (isGenericSourceTextTitle(withoutPrefix, episodeId)) return ""
  return withoutPrefix
}

export function toStoryboardNodes(
  workflow: EpisodeWorkflow,
  actions: WorkflowNodeActions
): StoryboardNode[] {
  const routes = new Map(
    (workflow.routes ?? []).map((route) => [route.id, route] as const)
  )
  const segmentOrderById = new Map<string, number>()
  for (const route of workflow.routes ?? []) {
    if (route.segmentId && !segmentOrderById.has(route.segmentId)) {
      segmentOrderById.set(route.segmentId, segmentOrderById.size + 1)
    }
  }
  for (const chain of workflow.workChains ?? []) {
    for (const segmentId of chain.segmentIds ?? []) {
      if (!segmentOrderById.has(segmentId)) {
        segmentOrderById.set(segmentId, segmentOrderById.size + 1)
      }
    }
  }
  for (const node of workflow.nodes ?? []) {
    const segmentId = node.segmentId ?? node.data.segmentId
    if (segmentId && !segmentOrderById.has(segmentId)) {
      segmentOrderById.set(segmentId, segmentOrderById.size + 1)
    }
  }
  return (workflow.nodes ?? [])
    .filter((node) => !isObsoleteWorkflowNodeType(node.type))
    .map((node) => {
      const routeId = node.routeId ?? node.data.routeId
      const route = routeId ? routes.get(routeId) : undefined
      const workChainId = node.workChainId
      const segmentId =
        node.segmentId ?? node.data.segmentId ?? route?.segmentId
      const strategy = node.strategy ?? node.data.strategy ?? route?.strategy
      const routeStoryboardTemplate = route
        ? (route as WorkflowRoute & {
            storyboardTemplate?: string
            storyboardTemplateLabel?: string
          })
        : undefined
      const episodeTitle =
        sourceCardDisplayTitle(actions.episodeTitle, actions.episodeId) ||
        sourceCardDisplayTitle(node.data.episodeTitle, actions.episodeId)
      const sourceTextTitle = sourceCardDisplayTitle(
        node.data.title,
        actions.episodeId
      )
      const title =
        node.type === "source.text" && node.data.sourceMode !== "independent"
          ? episodeTitle || sourceTextTitle || ""
          : node.data.title
      const isVideoTaskNode = isWorkflowVideoTaskType(node.type)
      const videoTaskReady = isVideoTaskNode
        ? workflowVideoTaskCardDataIsReady({
            ...node.data,
            eyebrow: node.type,
          } as WorkflowNodeData)
        : false
      const nodeLocked = Boolean(
        node.locked ||
        node.data.locked ||
        node.lockedByUser ||
        node.data.lockedByUser ||
        node.preserveOnReplan ||
        node.data.preserveOnReplan
      )
      const referenceThumbnails = node.data.referenceThumbnails
      const assetThumbnails = node.data.assetThumbnails
      const canvasNodeRole = node.data.canvasNodeRole
      return {
        id: node.id,
        type: "storyboardNode",
        position: node.position,
        draggable: !nodeLocked,
        connectable: true,
        selectable: true,
        style: undefined,
        data: {
          creationPending: node.data.creationPending,
          sourceMode: node.data.sourceMode,
          projectId: actions.projectId,
          episodeId: actions.episodeId,
          episodeTitle:
            node.type === "source.text" && node.data.sourceMode !== "independent"
              ? episodeTitle || sourceTextTitle
              : node.data.episodeTitle,
          nodeId: node.id,
          title,
          eyebrow: node.type,
          summary:
            isVideoTaskNode &&
            node.data.summary === "生成候选视频，并为当前分镜选择 winner。"
              ? ""
              : (node.data.summary ?? ""),
          status: workflowNodeStatus(node.data.status),
          model: node.data.model,
          metric: node.data.metric,
          action: workflowAction(node.type, {
            videoTaskReady,
          }),
          tone: workflowTone(node.type),
          activeVersionId: workflowNodeDataCurrentVersionId(node.data),
          sourceVersionId: node.data.sourceVersionId,
          winnerVersionId: node.data.winnerVersionId,
          selectionReason: node.data.selectionReason,
          selectedAt: node.data.selectedAt,
          variantSelection: node.data.variantSelection,
          panels: Array.isArray(node.data.panels)
            ? node.data.panels
            : undefined,
          storyboardAnalysis: node.data.storyboardAnalysis,
          storyboardAnalysisStoryTextHash:
            node.data.storyboardAnalysisStoryTextHash,
          storyboard_analysis_story_text_hash:
            node.data.storyboard_analysis_story_text_hash,
          storyboardPlanHash: node.data.storyboardPlanHash,
          storyboard_plan_hash: node.data.storyboard_plan_hash,
          storyboardPlanState: node.data.storyboardPlanState,
          storyboard_plan_state: node.data.storyboard_plan_state,
          scriptManualEdited: node.data.scriptManualEdited,
          script_manual_edited: node.data.script_manual_edited,
          workChainId,
          routeId,
          routeLabel: route?.label,
          routeStatus: route?.status,
          locked: Boolean(node.locked ?? node.data.locked),
          lockedByUser: Boolean(node.lockedByUser ?? node.data.lockedByUser),
          preserveOnReplan: Boolean(
            node.preserveOnReplan ?? node.data.preserveOnReplan
          ),
          lockedReason: optionalString(
            node.lockedReason ?? node.data.lockedReason
          ),
          segmentId,
          segmentOrder: segmentId ? segmentOrderById.get(segmentId) : undefined,
          strategy,
          storyboardTemplate:
            node.data.storyboardTemplate ??
            routeStoryboardTemplate?.storyboardTemplate,
          storyboardTemplateLabel:
            node.data.storyboardTemplateLabel ??
            routeStoryboardTemplate?.storyboardTemplateLabel,
          cinematicStoryText: node.data.cinematicStoryText,
          cinematic_story_text: node.data.cinematic_story_text,
          sourceFactText: node.data.sourceFactText,
          source_fact_text: node.data.source_fact_text,
          content: node.data.content,
          prompt: node.data.prompt,
          prompts: node.data.prompts,
          directorPlan: node.data.directorPlan,
          directorPlanShots: node.data.directorPlanShots,
          storyboardAllocation: node.data.storyboardAllocation,
          shotGroupId: node.data.shotGroupId,
          shotGroupOrder: node.data.shotGroupOrder,
          shotNos: node.data.shotNos,
          speakerRoster: Array.isArray(node.data.speakerRoster) ? node.data.speakerRoster : [],
          speechBudgetNote: node.data.speechBudgetNote,
          rhythmMultiplier: node.data.rhythmMultiplier,
          directorRuleId: node.data.directorRuleId,
          directorRuleSelectionMode: node.data.directorRuleSelectionMode,
          directorTaskCard: node.data.directorTaskCard,
          scriptTemplateId: node.data.scriptTemplateId,
          scriptUserInstruction: node.data.scriptUserInstruction,
          script_user_instruction: node.data.script_user_instruction,
          adaptationStyle: node.data.adaptationStyle,
          adaptation_style: node.data.adaptation_style,
          voiceStyle: node.data.voiceStyle,
          sourceText: node.data.sourceText,
          videoTaskNodeId: node.data.videoTaskNodeId,
          durationSeconds: node.data.durationSeconds,
          episodeScript: node.data.episodeScript,
          anchorText: node.data.anchorText,
          anchorSource: node.data.anchorSource,
          screenplay: node.data.screenplay,
          dialogue: node.data.dialogue,
          assetRefs: node.data.assetRefs,
          missingAssetRefs: node.data.missingAssetRefs,
          missingAssetRefsConfirmed: node.data.missingAssetRefsConfirmed,
          sourceRefs: node.data.sourceRefs,
          referencePlan: node.data.referencePlan,
          inputLinks: node.data.inputLinks,
          referenceVideoThumbnails: node.data.referenceVideoThumbnails,
          referenceManifest: node.data.referenceManifest,
          referenceDisplayRows: node.data.referenceDisplayRows,
          referenceUsage: node.data.referenceUsage,
          referenceThumbnails,
          assetThumbnails,
          storyboardTaskCard: node.data.storyboardTaskCard,
          videoTaskCard: node.data.videoTaskCard,
          frameSlot: node.data.frameSlot,
          shots: node.data.shots,
          shotIds: node.data.shotIds,
          shotTimingPlan: node.data.shotTimingPlan,
          sourceNodeId: node.data.sourceNodeId,
          resultOfNodeId: node.data.resultOfNodeId,
          quality: node.data.quality,
          modelSelection: node.data.modelSelection,
          capabilityRequirements: node.data.capabilityRequirements,
          capabilityCheck: node.data.capabilityCheck,
          generationConfig: workflowNodeOwnsGenerationConfig(node.type)
            ? node.data.generationConfig
            : undefined,
          resolvedConfig: workflowNodeOwnsGenerationConfig(node.type)
            ? node.data.resolvedConfig
            : undefined,
          modelCapabilitiesSnapshot: actions.modelCapabilitiesSnapshot ?? null,
          referenceMediaIds: node.data.referenceMediaIds,
          cardState: node.data.cardState,
          visibilityScope: node.data.visibilityScope,
          sourceType: node.data.sourceType,
          canvasNodeRole,
          assetScope: node.data.assetScope,
          assetKind: node.data.assetKind,
          rootAssetId: node.data.rootAssetId,
          rootAssetType: node.data.rootAssetType,
          rootAssetProjectId: node.data.rootAssetProjectId,
          assetId: node.data.assetId,
          assetVersionId: node.data.assetVersionId,
          assetType: node.data.assetType,
          assetName: node.data.assetName,
          mediaId: node.data.mediaId,
          mediaVersionId: node.data.mediaVersionId,
          activeMediaVersionId: node.data.activeMediaVersionId,
          mediaPurpose: node.data.mediaPurpose,
          useProjectVisual: node.data.useProjectVisual,
          preferredTargetSlot: node.data.preferredTargetSlot,
          media: canvasMediaReference(node.data.media),
          storage: canvasMediaReference(node.data.storage ?? node.data.media),
          width: node.data.width,
          height: node.data.height,
          aspectRatio: node.data.aspectRatio,
          sourceFileName: node.data.sourceFileName,
          copiedFromNodeId: node.data.copiedFromNodeId,
          provenance: node.data.provenance,
          storyboardTemplates: actions.storyboardTemplates,
          scriptAdaptationTemplates: actions.scriptAdaptationTemplates,
          onRun: actions.onRun,
          onSaveInlineEdit: actions.onSaveInlineEdit,
          onUpdateNodeData: actions.onUpdateNodeData,
          onSaveStoryboardUnitShots: actions.onSaveStoryboardUnitShots,
          onDiscardStoryboardSave: actions.onDiscardStoryboardSave,
          onUpdateReferenceUsage: actions.onUpdateReferenceUsage,
          onUpdateFrameReference: actions.onUpdateFrameReference,
          onRemoveInputLink: actions.onRemoveInputLink,
          onFocusNode: actions.onFocusNode,
          onSubmitStoryboardImageEdit: actions.onSubmitStoryboardImageEdit,
          onGenerateCinematicScript: actions.onGenerateCinematicScript,
          onGenerateFinalVideoPrompt: actions.onGenerateFinalVideoPrompt,
          onOptimizeVideoPrompt: actions.onOptimizeVideoPrompt,
        },
      }
    })
}

export function toStoryboardEdges(workflow: EpisodeWorkflow): StoryboardEdge[] {
  const visibleNodeIds = new Set(
    (workflow.nodes ?? [])
      .filter((node) => !isObsoleteWorkflowNodeType(node.type))
      .map((node) => node.id)
  )
  const nodeTypeById = new Map(
    (workflow.nodes ?? [])
      .filter((node) => !isObsoleteWorkflowNodeType(node.type))
      .map((node) => [node.id, node.type])
  )
  const nodeById = new Map(
    (workflow.nodes ?? [])
      .filter((node) => !isObsoleteWorkflowNodeType(node.type))
      .map((node) => [node.id, node])
  )
  const usedEdgeIds = new Set<string>()
  const edges = (workflow.edges ?? [])
    .filter(
      (edge) =>
        visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)
    )
    .map((edge) => {
      const sourceType =
        nodeTypeById.get(edge.source) || edge.data?.sourceNodeType
      const targetType =
        nodeTypeById.get(edge.target) || edge.data?.targetNodeType
      const role = edge.data?.role ?? ""
      const targetSlot = edge.data?.targetSlot ?? edge.targetHandle ?? ""
      const sourceNode = nodeById.get(edge.source)
      const targetNode = nodeById.get(edge.target)
      const sourceNodeData = recordValue(sourceNode?.data)
      const targetNodeData = recordValue(nodeById.get(edge.target)?.data)
      const targetIsWorkChainStoryboardResult =
        workflowNodeDataIsWorkChainStoryboardResult({
          ...targetNodeData,
          eyebrow: targetType,
        })
      const taskResultEdgeByType = workflowTaskResultEdgeByTypes(
        edge,
        sourceType,
        targetType
      )
      const taskResultEdge =
        taskResultEdgeByType &&
        !(
          isStoryboardCardNodeType(sourceType) &&
          targetType === "storyboard.image" &&
          !targetIsWorkChainStoryboardResult
        )
      const targetMediaPurpose = String(
        targetNodeData.mediaPurpose ??
          targetNodeData.preferredTargetSlot ??
          targetNodeData.assetKind ??
          ""
      ).trim()
      const storyboardDirectorEdge =
        sourceType === "prompt.storyboard" &&
        targetType === "director.board" &&
        (!role ||
          role === "context" ||
          role === "generates" ||
          targetSlot === "story")
      const directorStoryboardCardEdge =
        sourceType === "director.board" &&
        targetType === "storyboard.card" &&
        (!role || role === "context")
      const visualHandoffEdge =
        sourceType === "storyboard.card" &&
        targetType === "asset.image" &&
        targetMediaPurpose === "visual_handoff" &&
        (!role ||
          role === "generates" ||
          role === "dependency" ||
          !targetSlot ||
          targetSlot === "asset_context" ||
          targetSlot === "visual_handoff_reference")
      const sourceWorkChainId = optionalString(
        sourceNode?.workChainId ?? sourceNodeData.workChainId
      )
      const targetWorkChainId = optionalString(
        targetNode?.workChainId ?? targetNodeData.workChainId
      )
      const sourceRouteId = optionalString(
        sourceNode?.routeId ?? sourceNodeData.routeId
      )
      const targetRouteId = optionalString(
        targetNode?.routeId ?? targetNodeData.routeId
      )
      const targetIsStandaloneVideoTask =
        workflowVideoTaskScope(targetNode) === "standalone"
      const storyboardVideoEdge =
        sourceType === "storyboard.image" &&
        isWorkflowVideoTaskType(targetType) &&
        (!edge.data?.kind || edge.data.kind === "material") &&
        workflowNodeDataIsWorkChainStoryboardResult({
          ...sourceNodeData,
          eyebrow: sourceType,
        }) &&
        Boolean(sourceWorkChainId) &&
        sourceWorkChainId === targetWorkChainId &&
        !targetIsStandaloneVideoTask &&
        (!sourceRouteId || !targetRouteId || sourceRouteId === targetRouteId)
      const directorStoryboardResultEdge =
        isStoryboardCardNodeType(sourceType) &&
        targetType === "storyboard.image" &&
        targetIsWorkChainStoryboardResult &&
        role === "generates" &&
        Boolean(sourceWorkChainId) &&
        sourceWorkChainId === targetWorkChainId &&
        (!sourceRouteId || !targetRouteId || sourceRouteId === targetRouteId)
      const videoResultEdge =
        isWorkflowVideoTaskType(sourceType) &&
        targetType === "video.result" &&
        (role === "generates" ||
          targetSlot === "generates" ||
          targetSlot === "video_result")
      const lockedSystemEdge =
        workflowSourceStoryboardEdgeByTypes(edge, sourceType, targetType) ||
        workflowSourceVideoTextEdgeByTypes(edge, sourceType, targetType) ||
        storyboardDirectorEdge ||
        directorStoryboardCardEdge ||
        visualHandoffEdge ||
        storyboardVideoEdge ||
        directorStoryboardResultEdge ||
        videoResultEdge
      const workflowEdgeId = workflowEdgeStableId(edge)
      return {
        id: uniqueStoryboardEdgeUiId(workflowEdgeId, usedEdgeIds),
        source: edge.source,
        target: edge.target,
        sourceHandle: normalizeStoryboardEdgeSourceHandle(
          edge,
          nodeTypeById,
          nodeById
        ),
        targetHandle: normalizeStoryboardEdgeTargetHandle(edge, nodeById),
        deletable:
          !lockedSystemEdge &&
          !taskResultEdge &&
          !isWorkflowItemLocked(edge) &&
          !isWorkflowItemLocked(edge.data),
        data: {
          workflowEdgeId,
          kind: edge.data?.kind,
          role: edge.data?.role ?? "manual_link",
          inputLinkId: edge.data?.inputLinkId,
          sourceType: edge.data?.sourceType,
          sourceNodeType: edge.data?.sourceNodeType,
          targetNodeType: edge.data?.targetNodeType,
          targetSlot: edge.data?.targetSlot,
          workChainId: edge.data?.workChainId,
          routeId: edge.data?.routeId,
          segmentId: edge.data?.segmentId,
          locked: Boolean(edge.locked ?? edge.data?.locked),
          lockedByUser: Boolean(edge.lockedByUser ?? edge.data?.lockedByUser),
          preserveOnReplan: Boolean(
            edge.preserveOnReplan ?? edge.data?.preserveOnReplan
          ),
          lockedReason:
            edge.lockedReason ??
            edge.data?.lockedReason ??
            (lockedSystemEdge
              ? "locked_system_edge"
              : taskResultEdge
                ? "task_result_edge"
                : undefined),
        },
      }
    })
  // Partial mutation replies carry only changed edges. Missing edges in that
  // reply are not missing graph relations; never invent links between cards.
  return edges
}

export function partialWorkflowForCanvas(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  routes: WorkflowRoute[] = []
): EpisodeWorkflow {
  return {
    episodeId: "",
    version: 0,
    viewport: { x: 0, y: 0, zoom: 1 },
    nodes,
    edges,
    routes,
  }
}

export function toStoryboardNodesFromBackend(
  nodes: WorkflowNode[],
  actions: WorkflowNodeActions,
  routes: WorkflowRoute[]
) {
  return toStoryboardNodes(partialWorkflowForCanvas(nodes, [], routes), actions)
}

export function toStoryboardEdgesFromBackend(
  edges: WorkflowEdge[],
  currentNodes: StoryboardNode[],
  backendNodes: WorkflowNode[],
  routes: WorkflowRoute[]
) {
  const nodeById = new Map<string, WorkflowNode>()
  currentNodes.forEach((node) => {
    nodeById.set(node.id, toBackendNode(node))
  })
  backendNodes.forEach((node) => {
    nodeById.set(node.id, node)
  })
  return toStoryboardEdges(
    partialWorkflowForCanvas(Array.from(nodeById.values()), edges, routes)
  )
}

export function upsertStoryboardNodesLocally(
  current: StoryboardNode[],
  incoming: StoryboardNode[]
) {
  if (!incoming.length) return current
  const incomingById = new Map(incoming.map((node) => [node.id, node] as const))
  const currentIds = new Set(current.map((node) => node.id))
  const preserveIfMissing = (
    nextData: WorkflowNodeData,
    currentData: WorkflowNodeData,
    key: keyof WorkflowNodeData
  ) => {
    if (nextData[key] !== undefined) return
    if (currentData[key] === undefined) return
    ;(nextData as Record<string, unknown>)[key] = currentData[key]
  }
  return [
    ...current.map((node) => {
      const nextNode = incomingById.get(node.id)
      if (!nextNode) return node
      const nextData: WorkflowNodeData = { ...nextNode.data }
      const materialSnapshotKeys: Array<keyof WorkflowNodeData> = [
        "inputLinks",
        "referenceVideoThumbnails",
        "referenceManifest",
        "referenceDisplayRows",
        "referenceUsage",
        "referenceThumbnails",
        "assetThumbnails",
        "referenceMediaIds",
        "assetReferenceMediaIds",
        "assetRefs",
        "inputContract",
        "needsRelink",
      ]
      materialSnapshotKeys.forEach((key) =>
        preserveIfMissing(nextData, node.data, key)
      )
      return {
        ...nextNode,
        data: nextData,
        position: nextNode.position ?? node.position,
        selected: node.selected,
      }
    }),
    ...Array.from(incomingById.values()).filter((node) => !currentIds.has(node.id)),
  ]
}

export function mergeCreatedWorkflowNodesLocally(
  current: StoryboardNode[],
  incoming: StoryboardNode[]
) {
  const incomingById = new Map(incoming.map((node) => [node.id, node] as const))
  const currentIds = new Set(current.map((node) => node.id))
  return current.map((node) => {
    const nextNode = incomingById.get(node.id)
    if (!nextNode || !node.data.creationPending) return node
    return { ...nextNode, data: { ...nextNode.data, creationPending: false }, selected: node.selected }
  })
    .concat(incoming.filter((node) => !currentIds.has(node.id)))
}

export function workflowCanvasNodeInteractionState(node: StoryboardNode) {
  const creationPending = Boolean(node.data.creationPending)
  return {
    draggable: creationPending ? false : node.draggable,
    connectable: creationPending ? false : node.connectable,
    selectable: creationPending ? false : node.selectable,
    style: creationPending
      ? { ...(node.style ?? {}), pointerEvents: "none" as const, opacity: 0.6 }
      : node.style,
  }
}

export function workflowEdgeStableId(edge: WorkflowEdge) {
  const edgeId = String(edge.id ?? "").trim()
  if (edgeId) return edgeId
  const targetSlot = edge.targetHandle || edge.data?.targetSlot || "edge"
  return `${edge.source}-${edge.target}-${targetSlot}`
}

export function uniqueStoryboardEdgeUiId(edgeId: string, usedEdgeIds: Set<string>) {
  const baseId = edgeId || "workflow-edge"
  let nextId = baseId
  let suffix = 2
  while (usedEdgeIds.has(nextId)) {
    nextId = `${baseId}__ui_${suffix}`
    suffix += 1
  }
  usedEdgeIds.add(nextId)
  return nextId
}

export function normalizeStoryboardEdgeSourceHandle(
  edge: EpisodeWorkflow["edges"][number],
  nodeTypeById: Map<string, string>,
  nodeById?: Map<string, WorkflowNode>
) {
  const sourceType =
    nodeTypeById.get(edge.source) || edge.data?.sourceNodeType || ""
  const requestedHandle = String(edge.sourceHandle ?? "").trim()
  if (sourceType === "asset.image") {
    return requestedHandle === "asset_bottom" ? "asset_bottom" : "asset"
  }
  if (sourceType === "media.external") {
    if (requestedHandle === "video" || requestedHandle === "video_bottom") {
      return requestedHandle
    }
    return requestedHandle === "media_bottom" ? "media_bottom" : "media"
  }
  if (sourceType === "source.text")
    return "output"
  if (isDirectorBoardNodeType(sourceType)) return "plan"
  if (isStoryboardCardNodeType(sourceType))
    return requestedHandle === "visual_handoff" ? "visual_handoff" : "storyboard"
  if (sourceType === "prompt.storyboard") return "prompt"
  if (isWorkflowResultImageType(sourceType)) {
    const sourceNode = edge.source ? nodeById?.get(edge.source) : undefined
    if (
      sourceNode &&
      !workflowNodeDataIsIndependentImageAsset(sourceNode.data)
    ) {
      return "image"
    }
    return requestedHandle === "image_bottom" ? "image_bottom" : "image"
  }
  if (sourceType === "video.result") return "video"
  if (isWorkflowVideoTaskType(sourceType)) return "video"
  return edge.sourceHandle
}

export function normalizeStoryboardEdgeTargetHandle(
  edge: {
    source?: string | null
    target: string
    targetHandle?: string | null
    data?: Partial<StoryboardEdgeData> | null
  },
  nodeById?: Map<string, WorkflowNode>
) {
  const sourceNode = edge.source ? nodeById?.get(edge.source) : undefined
  const targetNode = edge.target ? nodeById?.get(edge.target) : undefined
  const sourceType = sourceNode?.type ?? edge.data?.sourceNodeType ?? ""
  const targetType = targetNode?.type ?? edge.data?.targetNodeType ?? ""
  if (
    (sourceType === "source.text" && targetType === "prompt.storyboard") ||
    (sourceType === "prompt.storyboard" && targetType === "director.board") ||
    (sourceType === "director.board" && targetType === "storyboard.card")
  ) {
    return "story"
  }
  if (
    isStoryboardCardNodeType(sourceType) &&
    targetType === "storyboard.image" &&
    workflowNodeDataIsWorkChainStoryboardResult({
      ...recordValue(targetNode?.data),
      eyebrow: targetType,
    })
  ) {
    return "generates"
  }
  if (isWorkflowVideoTaskType(sourceType) && targetType === "video.result") {
    return "generates"
  }
  if (
    edge.data?.kind === "dependency" &&
    edge.data?.role === "generates" &&
    (edge.targetHandle === "prompt" || edge.targetHandle === "reference")
  ) {
    return "generates"
  }
  if (edge.targetHandle === "reference_image") {
    return "storyboard_image"
  }
  if (targetType === "video.result" && edge.targetHandle === "video_result") {
    return "generates"
  }
  if (edge.data?.kind === "material") {
    const edgeData = recordValue(edge.data)
    const requestedHandle = String(edge.targetHandle ?? "").trim()
    const requestedInputHandle = canonicalWorkflowInputHandle(requestedHandle)
    const targetSlot = canonicalTargetSlot(
      String(edgeData.targetSlot ?? edgeData.slot ?? edge.targetHandle ?? "")
    )
    if (targetType === "director.board" || isStoryboardCardNodeType(targetType)) {
      return WORKFLOW_ASSET_INPUT_HANDLE
    }
    if (isWorkflowVideoTaskType(targetType)) {
      const sourceIsWorkChainStoryboardResult =
        workflowNodeDataIsWorkChainStoryboardResult({
          ...recordValue(sourceNode?.data),
          eyebrow: sourceType,
        })
      const sourceWorkChainId = optionalString(
        sourceNode?.workChainId ?? sourceNode?.data.workChainId
      )
      const targetWorkChainId = optionalString(
        targetNode?.workChainId ?? targetNode?.data.workChainId
      )
      const lockedWorkflowStoryboardInput =
        (Boolean(edge.data?.locked) ||
          edge.data?.lockedReason ===
            "workflow_chain_storyboard_video_input") &&
        targetSlot === "storyboard_image" &&
        sourceIsWorkChainStoryboardResult &&
        Boolean(sourceWorkChainId) &&
        sourceWorkChainId === targetWorkChainId
      if (
        requestedInputHandle === WORKFLOW_VIDEO_INPUT_HANDLE &&
        workflowVideoTaskScope(targetNode) === "standalone"
      ) {
        return WORKFLOW_VIDEO_INPUT_HANDLE
      }
      return lockedWorkflowStoryboardInput
        ? WORKFLOW_VIDEO_INPUT_HANDLE
        : WORKFLOW_ASSET_INPUT_HANDLE
    }
    if (requestedInputHandle) return requestedInputHandle
  }
  return edge.targetHandle ?? undefined
}

export function normalizeWorkflowVersion(value: unknown) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.max(0, Math.trunc(parsed)) : 0
}

export function toBackendNode(node: StoryboardNode): WorkflowNode {
  return {
    id: node.id,
    type: node.data.eyebrow,
    workChainId: node.data.workChainId,
    routeId: node.data.routeId,
    segmentId: node.data.segmentId,
    strategy: node.data.strategy,
    storyboardTemplate: node.data.storyboardTemplate,
    storyboardTemplateLabel: node.data.storyboardTemplateLabel,
    locked: node.data.locked,
    lockedByUser: node.data.lockedByUser,
    preserveOnReplan: node.data.preserveOnReplan,
    lockedReason: node.data.lockedReason,
    position: node.position,
    data: {
      title: node.data.title,
      status: toBackendWorkflowNodeStatus(node.data.status),
      summary: node.data.summary,
      model: node.data.model,
      activeVersionId: workflowNodeDataCurrentVersionId(node.data),
      sourceVersionId: node.data.sourceVersionId,
      winnerVersionId: node.data.winnerVersionId,
      selectionReason: node.data.selectionReason,
      selectedAt: node.data.selectedAt,
      variantSelection: node.data.variantSelection,
      metric: node.data.metric,
      panels: node.data.panels,
      storyboardAnalysis: node.data.storyboardAnalysis,
      storyboardAnalysisStoryTextHash:
        node.data.storyboardAnalysisStoryTextHash,
      storyboard_analysis_story_text_hash:
        node.data.storyboard_analysis_story_text_hash,
      storyboardPlanHash: node.data.storyboardPlanHash,
      storyboard_plan_hash: node.data.storyboard_plan_hash,
      storyboardPlanState: node.data.storyboardPlanState,
      storyboard_plan_state: node.data.storyboard_plan_state,
      scriptManualEdited: node.data.scriptManualEdited,
      script_manual_edited: node.data.script_manual_edited,
      workChainId: node.data.workChainId,
      routeId: node.data.routeId,
      segmentId: node.data.segmentId,
      strategy: node.data.strategy,
      storyboardTemplate: node.data.storyboardTemplate,
      storyboardTemplateLabel: node.data.storyboardTemplateLabel,
      locked: node.data.locked,
      lockedByUser: node.data.lockedByUser,
      preserveOnReplan: node.data.preserveOnReplan,
      lockedReason: node.data.lockedReason,
      prompt: node.data.prompt,
      prompts: node.data.prompts,
      directorPlan: node.data.directorPlan,
      directorPlanShots: node.data.directorPlanShots,
      storyboardAllocation: node.data.storyboardAllocation,
      shotGroupId: node.data.shotGroupId,
      shotGroupOrder: node.data.shotGroupOrder,
      shotNos: node.data.shotNos,
      speakerRoster: node.data.speakerRoster,
      speechBudgetNote: node.data.speechBudgetNote,
      rhythmMultiplier: node.data.rhythmMultiplier,
      directorRuleId: node.data.directorRuleId,
      directorRuleSelectionMode: node.data.directorRuleSelectionMode,
      directorTaskCard: node.data.directorTaskCard,
      cinematicStoryText: node.data.cinematicStoryText,
      cinematic_story_text: node.data.cinematic_story_text,
      sourceFactText: node.data.sourceFactText,
      source_fact_text: node.data.source_fact_text,
      content: node.data.content,
      scriptTemplateId: node.data.scriptTemplateId,
      scriptUserInstruction: node.data.scriptUserInstruction,
      script_user_instruction: node.data.script_user_instruction,
      adaptationStyle: node.data.adaptationStyle,
      adaptation_style: node.data.adaptation_style,
      voiceStyle: node.data.voiceStyle,
      sourceText: node.data.sourceText,
      sourceMode: node.data.sourceMode,
      videoTaskNodeId: node.data.videoTaskNodeId,
      durationSeconds: node.data.durationSeconds,
      episodeScript: node.data.episodeScript,
      anchorText: node.data.anchorText,
      anchorSource: node.data.anchorSource,
      screenplay: node.data.screenplay,
      dialogue: node.data.dialogue,
      assetRefs: node.data.assetRefs,
      missingAssetRefs: node.data.missingAssetRefs,
      missingAssetRefsConfirmed: node.data.missingAssetRefsConfirmed,
      sourceRefs: node.data.sourceRefs,
      referencePlan: node.data.referencePlan,
      inputLinks: node.data.inputLinks,
      referenceVideoThumbnails: node.data.referenceVideoThumbnails,
      referenceManifest: node.data.referenceManifest,
      referenceDisplayRows: node.data.referenceDisplayRows,
      referenceUsage: node.data.referenceUsage,
      referenceThumbnails: node.data.referenceThumbnails,
      assetThumbnails: node.data.assetThumbnails,
      storyboardTaskCard: node.data.storyboardTaskCard,
      videoTaskCard: node.data.videoTaskCard,
      frameSlot: node.data.frameSlot,
      shots: node.data.shots,
      shotIds: node.data.shotIds,
      shotTimingPlan: node.data.shotTimingPlan,
      sourceNodeId: node.data.sourceNodeId,
      resultOfNodeId: node.data.resultOfNodeId,
      quality: node.data.quality,
      modelSelection: node.data.modelSelection,
      capabilityRequirements: node.data.capabilityRequirements,
      capabilityCheck: node.data.capabilityCheck,
      generationConfig: workflowNodeOwnsGenerationConfig(node.data.eyebrow)
        ? node.data.generationConfig
        : undefined,
      resolvedConfig: workflowNodeOwnsGenerationConfig(node.data.eyebrow)
        ? node.data.resolvedConfig
        : undefined,
      referenceMediaIds: node.data.referenceMediaIds,
      cardState: node.data.cardState,
      visibilityScope: node.data.visibilityScope,
      sourceType: node.data.sourceType,
      canvasNodeRole: node.data.canvasNodeRole,
      assetScope: node.data.assetScope,
      assetKind: node.data.assetKind,
      rootAssetId: node.data.rootAssetId,
      rootAssetType: node.data.rootAssetType,
      rootAssetProjectId: node.data.rootAssetProjectId,
      assetId: node.data.assetId,
      assetVersionId: node.data.assetVersionId,
      assetType: node.data.assetType,
      assetName: node.data.assetName,
      mediaId: node.data.mediaId,
      mediaVersionId: node.data.mediaVersionId,
      activeMediaVersionId: node.data.activeMediaVersionId,
      mediaPurpose: node.data.mediaPurpose,
      useProjectVisual: node.data.useProjectVisual,
      preferredTargetSlot: node.data.preferredTargetSlot,
      media: canvasMediaReference(node.data.media),
      storage: canvasMediaReference(node.data.storage ?? node.data.media),
      sourceFileName: node.data.sourceFileName,
      copiedFromNodeId: node.data.copiedFromNodeId,
      provenance: node.data.provenance,
    },
  }
}

export function toBackendWorkflowNodeStatus(
  status: WorkflowNodeData["status"]
): WorkflowNode["data"]["status"] {
  return status === "canceled" ? "cancelled" : status
}

export function toBackendEdge(edge: StoryboardEdge): WorkflowEdge {
  const data: Partial<StoryboardEdgeData> = edge.data ?? { role: "manual_link" }
  return {
    id: String(data.workflowEdgeId ?? edge.id),
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle ?? undefined,
    targetHandle: edge.targetHandle ?? undefined,
    locked: edge.deletable === false ? true : data.locked,
    lockedByUser: data.lockedByUser,
    preserveOnReplan: data.preserveOnReplan,
    lockedReason: data.lockedReason,
    deletable: edge.deletable,
    data: {
      kind: data.kind,
      role: data.role,
      inputLinkId: data.inputLinkId,
      sourceType: data.sourceType,
      sourceNodeType: data.sourceNodeType,
      targetNodeType: data.targetNodeType,
      targetSlot: data.targetSlot,
      workChainId: data.workChainId,
      routeId: data.routeId,
      segmentId: data.segmentId,
      locked: data.locked,
      lockedByUser: data.lockedByUser,
      preserveOnReplan: data.preserveOnReplan,
      lockedReason: data.lockedReason,
    },
  }
}

export function toBackendWorkflow(
  episodeId: string,
  nodes: StoryboardNode[],
  edges: StoryboardEdge[],
  routes: WorkflowRoute[] = [],
  version = 0,
  extras: Partial<EpisodeWorkflow> = {}
): EpisodeWorkflow {
  return {
    ...extras,
    episodeId,
    version: normalizeWorkflowVersion(version),
    viewport: { x: 0, y: 0, zoom: 0.85 },
    workChains: (extras.workChains ?? []).map((workChain) => ({
      ...workChain,
    })),
    routes: routes.map((route) => ({ ...route })),
    nodes: nodes.map(toBackendNode),
    edges: edges.map(toBackendEdge),
  }
}

export function initialEpisodeWorkflow(episodeId: string): EpisodeWorkflow {
  return toBackendWorkflow(episodeId, initialNodes, initialEdges)
}


export function hasInlineTaskParameterPanel(nodeType: string) {
  return (
    nodeType === "prompt.storyboard" ||
    isDirectorBoardNodeType(nodeType) ||
    isStoryboardCardNodeType(nodeType) ||
    isWorkflowVideoTaskType(nodeType)
  )
}

export function workflowAssetCategoryLabel(
  data?: Pick<WorkflowNodeData, "assetType" | "mediaPurpose">
) {
  const assetType = String(data?.assetType ?? "")
    .trim()
    .toLowerCase()
  const mediaPurpose = String(data?.mediaPurpose ?? "").trim()
  if (
    assetType === "characters" ||
    assetType === "character" ||
    mediaPurpose === "character_reference"
  ) {
    return "角色"
  }
  if (
    assetType === "creatures" ||
    assetType === "creature" ||
    assetType === "monsters" ||
    assetType === "monster" ||
    assetType === "beasts" ||
    assetType === "beast" ||
    mediaPurpose === "creature_reference"
  ) {
    return "生物"
  }
  if (
    assetType === "scenes" ||
    assetType === "scene" ||
    mediaPurpose === "scene_reference"
  ) {
    return "场景"
  }
  if (
    assetType === "props" ||
    assetType === "prop" ||
    mediaPurpose === "prop_reference"
  ) {
    return "道具"
  }
  if (
    assetType === "storyboard" ||
    assetType === "storyboard_image" ||
    mediaPurpose === "storyboard_image" ||
    mediaPurpose === "visual_reference"
  ) {
    return "分镜图"
  }
  if (
    assetType === "visual_handoff" ||
    assetType === "visual_handoff_reference" ||
    mediaPurpose === "visual_handoff" ||
    mediaPurpose === "visual_handoff_reference"
  ) {
    return "视觉交接"
  }
  if (assetType === "frame_image" || mediaPurpose === "frame_image") return "帧画面"
  if (assetType === "custom_image" || mediaPurpose === "custom_image") return "自定义图片"
  if (assetType === "video" || mediaPurpose === "video_result") {
    return "视频"
  }
  return ""
}

export function workflowCardTypeLabel(eyebrow: string, data?: WorkflowNodeData) {
  if (eyebrow === "source.text") return data?.sourceMode === "independent" ? "独立原文" : "分集原文"
  if (isDirectorBoardNodeType(eyebrow)) return "分镜脚本"
  if (isStoryboardCardNodeType(eyebrow)) return "分镜单元"
  if (eyebrow === "prompt.storyboard") return "片段剧本"
  if (eyebrow === "storyboard.image") return "分镜图"
  if (eyebrow === "video.character_replace") return "角色替换视频生成"
  if (eyebrow === "video.storyboard" || eyebrow === "video.keyframe") return "视频生成"
  if (eyebrow === "video.result") return "视频片段"
  if (eyebrow === "asset.image")
    return workflowAssetCategoryLabel(data) || "资产"
  if (eyebrow === "media.external") {
    return workflowAssetCategoryLabel(data) || "导入媒体"
  }
  if (eyebrow.startsWith("asset.")) return "资产"
  return eyebrow
}

const WORKFLOW_HEADER_TYPES = new Set([
  "prompt.storyboard", "director.board", "storyboard.card", "storyboard.image",
  "video.storyboard", "video.keyframe", "video.character_replace", "video.result",
])

export function workflowCardHeaderLocator(data: WorkflowNodeData) {
  if (data.eyebrow === "source.text") {
    if (data.sourceMode === "independent") return ""
    const rawEpisodeId = String(data.episodeId ?? "").trim()
    const episodeNumber = rawEpisodeId.match(/^(?:E|EP|episode)[_-]?0*(\d+)$/i)?.[1]
      ?? rawEpisodeId.match(/^0*(\d+)$/)?.[1]
      ?? String(data.episodeTitle ?? "").match(/第\s*0*(\d+)\s*集/)?.[1]
    return episodeNumber ? `第${episodeNumber.padStart(2, "0")}集` : ""
  }
  if (!WORKFLOW_HEADER_TYPES.has(data.eyebrow)) return workflowCardTitleSuffix(data)
  if (!data.segmentId && !data.routeId && !data.workChainId) return workflowCardTitleSuffix(data)
  const segment = `片段${String(data.segmentOrder ?? 1).padStart(2, "0")}`
  if (data.eyebrow === "prompt.storyboard" || data.eyebrow === "director.board") return segment
  const shotNos = (data.shotNos ?? []).filter((value) => Number.isInteger(value) && value > 0).sort((a, b) => a - b)
  if (!shotNos.length) return segment
  const first = String(shotNos[0]).padStart(2, "0")
  const last = String(shotNos[shotNos.length - 1]).padStart(2, "0")
  return `${segment} / 镜头${first}${shotNos.length > 1 ? `–${last}` : ""}`
}

export function cleanWorkflowCardTitle(title: string, typeLabel: string) {
  const trimmed = title.trim()
  if (!trimmed) return ""
  const genericTitles = new Set([
    typeLabel,
    "资产",
    "资产图",
    "图片资产",
    "导入图片",
    "分镜",
    "片段剧本",
    "分镜脚本",
    "分镜单元",
    "角色资产",
    "生物资产",
    "场景资产",
    "道具资产",
    "分镜图",
    "分镜图资产",
    "分镜结果图",
    "分镜图结果卡",
    "故事板分镜图",
    "当前分镜图",
    "视频",
    "视频生成",
    "视频片段",
    "故事版视频",
    "最终视频",
    "当前视频",
  ])
  if (genericTitles.has(trimmed)) return ""
  return trimmed.replace(
    /^(资产|资产图|图片资产|导入图片|角色资产|生物资产|场景资产|道具资产|分镜|片段剧本|分镜脚本|分镜单元|分镜图|分镜图资产|分镜结果图|分镜图结果卡|故事板分镜图|当前分镜图|视频|视频生成|视频片段|故事版视频|最终视频|当前视频)\s*[·:：-]\s*/,
    ""
  )
}

export function firstCleanWorkflowCardTitle(
  typeLabel: string,
  ...titles: Array<unknown>
) {
  for (const title of titles) {
    const cleaned = cleanWorkflowCardTitle(String(title ?? ""), typeLabel)
    if (cleaned) return cleaned
  }
  return ""
}

export function workflowCardTitleSuffix(data: WorkflowNodeData) {
  const typeLabel = workflowCardTypeLabel(data.eyebrow, data)
  if (data.eyebrow === "source.text") return ""
  if (data.eyebrow === "asset.image") {
    return firstCleanWorkflowCardTitle(typeLabel, data.assetName, data.title)
  }
  if (data.eyebrow === "media.external") {
    return firstCleanWorkflowCardTitle(
      typeLabel,
      data.title,
      data.sourceFileName
    )
  }
  if (data.eyebrow === "storyboard.image" || data.eyebrow === "video.result") {
    return firstCleanWorkflowCardTitle(
      typeLabel,
      data.assetName,
      data.title,
      data.sourceFileName
    )
  }
  return firstCleanWorkflowCardTitle(typeLabel, data.title)
}
