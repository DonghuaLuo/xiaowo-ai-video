import type {
  WorkflowRoute,
  WorkflowWorkChain,
  ProjectPlanningSummary,
  GenerationConfigCheck,
  ModelCapabilitiesSnapshot,
  WorkflowNode,
  WorkflowEdge,
  EpisodeWorkflow,
  CanvasVersionRef,
  CanvasMutationRecords,
  CanvasRecordPayload,
  CanvasDocumentRecord,
  CanvasChangesResult,
  CanvasSnapshotResult,
  CanvasRecordsResult,
  CustomCanvasEntry,
  WorkflowPreflightResult,
  EpisodeProductionStatus,
  WorkflowMediaImportPayload,
  WorkflowInputLinkPayload,
  WorkflowInputLinkResult,
  WorkflowNodeInputsResult,
  WorkflowBatchResult,
  WorkflowMutationResult,
  VariantQualityResultPayload,
  VariantQualityResultResponse,
  WorkflowExternalMediaImportResult,
  ClipboardImageMediaResult,
  VideoClipInfoResult,
  VideoClipResultsListResult,
  VideoClipDeleteResultsResult,
  VideoClipMediaResult,
  WorkflowMediaListResult,
} from "./backend-workflow-types"

export type {
  WorkflowNodeStatus,
  GenerationStrategy,
  StoryboardTemplateId,
  WorkflowRoute,
  WorkflowWorkChain,
  ProjectPlanningSummary,
  GenerationConfigCheck,
  WorkflowSlotSchema,
  WorkflowModelCapability,
  ModelCapabilitiesSnapshot,
  WorkflowNode,
  WorkflowEdge,
  EpisodeWorkflow,
  CanvasChangeRecord,
  CanvasRecordRef,
  CanvasVersionRef,
  CanvasMutationRecords,
  CanvasRecordPayload,
  CanvasDocumentRecord,
  CanvasChangesResult,
  CanvasSnapshotResult,
  CanvasRecordsResult,
  CustomCanvasEntry,
  WorkflowPreflightResult,
  EpisodeProductionStep,
  EpisodeProductionRouteState,
  EpisodeProductionStatus,
  WorkflowMediaImportPayload,
  WorkflowInputLinkPayload,
  WorkflowInputLinkResult,
  WorkflowNodeInputsResult,
  WorkflowBatchResult,
  WorkflowMutationResult,
  VariantQualityResultPayload,
  VariantQualityResultResponse,
  WorkflowExternalMediaImportResult,
  ClipboardImageMediaResult,
  VideoClipInfoResult,
  VideoClipResultItem,
  VideoClipResultsListResult,
  VideoClipDeleteResultsResult,
  VideoClipMediaResult,
  WorkflowMediaRecord,
  WorkflowMediaListResult,
} from "./backend-workflow-types"

import type { ImageResolutionSchema } from "@/utils/model-resolution"
import type { VideoCapabilityMetadata } from "@/utils/video-model-capabilities"
import type { ModelAvailability } from "@/shared/model-availability"

export type ProjectStatus = "running" | "completed" | "draft"

export type ProjectThumbnailRef = {
  id?: string | null
  name?: string | null
  source?: string | null
  url?: string | null
  path?: string | null
  relativePath?: string | null
  relative_path?: string | null
  styleThumbnailFile?: string | null
  style_thumbnail_file?: string | null
}

export type ProjectRow = {
  id: string
  name: string
  updatedAt: string
  updatedAtRank: number
  episodeCount: number
  episodes?: Array<{
    id: string
    title: string
    status: string
  }>
  sourceCount: number
  characterCount?: number
  creatureCount?: number
  sceneCount?: number
  propCount?: number
  status: string
  statusType: ProjectStatus
  aspectRatio: string
  summary: string
  wordCount?: number | string | null
  word_count?: number | string | null
  contentMode?: ContentMode
  content_mode?: ContentMode
  overview?: {
    excerptSummary?: string
    excerpt_summary?: string
    genreContext?: string
    genre_context?: string
    themeVisualContext?: string
    theme_visual_context?: string
    narratorVoiceDesignPrompt?: string
    narrator_voice_design_prompt?: string
    narratorReferenceAudio?: MediaAsset | null
    narrator_reference_audio?: MediaAsset | null
    source?: string
    modelId?: string
    modelLabel?: string
    providerId?: string
    sourceId?: string
    sourceTitle?: string
    contentPath?: string
    relativePath?: string
    excerptChars?: number
    error?: string
  } | null
  sourceFile?: {
    id?: string
    title?: string
    contentPath?: string
    relativePath?: string
    rawFilename?: string
    wordCount?: number | string
    word_count?: number | string
    charCount?: number | string
    char_count?: number | string
  } | null
  accent: string
  currentEpisodeId: string
  thumbnail?: ProjectThumbnailRef | null
  thumbnailUrl?: string | null
  thumbnailPath?: string | null
  thumbnailRelativePath?: string | null
  thumbnailStyleFile?: string | null
  thumbnailSource?: string | null
}

export type DashboardStats = {
  total: number
  running: number
  completed: number
}

export type DashboardResponse = {
  projects: ProjectRow[]
  stats: DashboardStats
  featuredProjectId: string | null
}

export type ContentMode = "drama"

export type ScriptAdaptationTemplateOption = {
  id: string
  name: string
  desc?: string
  description?: string
  badge?: string
  source?: string
  prompt?: string
  rules?: string[]
  recommended_use?: string
  recommendedUse?: string
}

export type TextReplacementRuleOption = {
  from: string
  to: string
}

export type StoryboardTemplateOption = {
  id: string
  title?: string
  label?: string
  name?: string
  desc?: string
  description?: string
  summary?: string
  badge?: string
  source?: string
  prompt?: string
  effectivePrompt?: string
  base_template_id?: string
  derived_from_template_id?: string
  layoutSlots?: string
  layout_slots?: string
  fixedShotSlots?: number
  fixed_shot_slots?: number
  minShotSlots?: number
  min_shot_slots?: number
  maxShotSlots?: number
  max_shot_slots?: number
  layoutSpec?: Record<string, unknown>
  layout_spec?: Record<string, unknown>
  requiredSections?: string[]
  required_sections?: string[]
}

export type DirectorRuleOption = {
  id: string
  title: string
  description: string
  content: string
  defaultDescription?: string
  defaultContent?: string
  source?: string
  customized?: boolean
  updatedAt?: string
}

export type StyleCategory =
  | "all"
  | "general"
  | "live_action"
  | "two_d"
  | "three_d"
  | "favorite"

export type StyleTemplateOption = {
  id: string
  name: string
  desc: string
  category: StyleCategory
  categoryLabel: string
  accent: string
  prompt?: string
  assetPrompt?: string
  asset_prompt?: string
  characterAssetPrompt?: string
  character_asset_prompt?: string
  creatureAssetPrompt?: string
  creature_asset_prompt?: string
  phaseVisuals?: Array<{
    id: string
    name: string
    prompt: string
  }>
  phase_visuals?: Array<{
    id: string
    name: string
    prompt: string
  }>
  activePhaseVisualId?: string | null
  active_phase_visual_id?: string | null
  visualTypeTags?: string[]
  visual_type_tags?: string[]
  defaultVisualTypeTag?: string
  default_visual_type_tag?: string
  source?: string
}

export type ProjectCreationOptions = {
  contentModes?: Array<{
    id: ContentMode
    name: string
    description: string
  }>
  aspectRatios: string[]
  scriptAdaptationTemplates?: ScriptAdaptationTemplateOption[]
  textReplacementRules?: TextReplacementRuleOption[]
  styleCategories: Array<{ id: StyleCategory; label: string }>
  styleTemplates: StyleTemplateOption[]
  defaults?: Record<string, unknown>
}

export type ProviderSetting = {
  id: string
  title?: string
  name?: string
  logo?: string
  iconKey?: string
  description?: string
  baseUrl?: string
  docsUrl?: string
  keyLabel?: string
  capabilities?: string[]
  models?: ProviderModelInfo[]
  configured?: boolean
  apiKey?: string
  apiKeyMasked?: string
  connectionStatus?: "unconfigured" | "untested" | "connected" | "failed"
  lastTest?: ProviderTestResult | null
  custom?: boolean
}

export type ProviderModelInfo = VideoCapabilityMetadata & {
  id: string
  label: string
  type: "image" | "video" | "text"
  endpoint?: string
  media_type?: "image" | "video" | "text"
  display_name?: string
  resolutions?: string[]
  default_resolution?: string
  image_resolution_schema?: ImageResolutionSchema
  imageResolutionSchema?: ImageResolutionSchema
  resolution_descriptions?: Record<string, Record<string, string>>
  resolutionDescriptions?: Record<string, Record<string, string>>
  duration_resolution_constraints?: Record<string, number[]>
  image_output_formats?: string[]
  durations?: number[]
  audio?: boolean
  max_reference_images?: number
  reference_image_limit_source?: string
  reference_image_limit_source_url?: string
  reference_image_limit_note?: string
  referenceImageLimitSource?: string
  referenceImageLimitSourceUrl?: string
  referenceImageLimitNote?: string
  reference_image_transport_verified?: boolean
  reference_image_transport_unverified?: boolean
  usage?: string
}

export type ProviderTestResult = {
  catalogComplete?: boolean
  configurationPreserved?: boolean
  overall: "ok" | "warn" | "fail"
  status: "connected" | "failed"
  message: string
  error?: string
  checkedAt?: string
  latencyMs?: number
  availableModels?: ProviderModelInfo[]
  remoteModels?: ProviderModelInfo[]
  remoteModelIds?: string[]
  capabilities?: string[]
}

export type ModelCapability = VideoCapabilityMetadata & ModelAvailability & {
  id: string
  provider_id?: string
  provider_preset_id?: string
  providerPresetId?: string
  label: string
  model_vendor?: string
  vendor_source?: string
  classification_source?: string
  classification_rule?: string
  agent_route?: {
    baseUrl?: string
    authMode?: string
    source?: string
  }
  agent_support_source?: string
  agent_note?: string
  agent_only?: boolean
  reasoning_default_mode?: "low" | "medium" | "high" | "xhigh" | "max"
  reasoning_levels?: ("low" | "medium" | "high" | "xhigh" | "max")[]
  reasoning_supported?: boolean
  endpoint?: string
  resolutions?: string[]
  default_resolution?: string
  image_resolution_schema?: ImageResolutionSchema
  imageResolutionSchema?: ImageResolutionSchema
  duration_resolution_constraints?: Record<string, number[]>
  image_output_formats?: string[]
  durations?: number[]
  audio?: boolean
  max_reference_images?: number
  reference_image_limit_source?: string
  reference_image_limit_source_url?: string
  reference_image_limit_note?: string
  referenceImageLimitSource?: string
  referenceImageLimitSourceUrl?: string
  referenceImageLimitNote?: string
  reference_image_transport_verified?: boolean
  reference_image_transport_unverified?: boolean
  supports?: string[]
}

export type ModelConfigPayload = {
  image: {
    model_id: string
    character_resolution: string
    scene_resolution: string
    prop_resolution: string
    asset_resolution: string
    storyboard_resolution: string
    image_output_format: string
  }
  video: {
    model_id: string
    resolution: string
    duration_seconds: number
    generate_audio: boolean
  }
  agent: {
    model_id: string
    temperature?: number
    max_tokens?: number
  }
  text: {
    model_id: string
    overview_excerpt_chars: number
  }
}

export type ModelConfigResponse = {
  config: ModelConfigPayload
  capabilities: {
    image: ModelCapability[]
    video: ModelCapability[]
    agent: ModelCapability[]
    text: ModelCapability[]
  }
  providers: ProviderSetting[]
}

export type AssetItem = {
  id: string
  name: string
  desc: string
  lifecycleStatus?: "active" | "offline"
  lifecycle_status?: "active" | "offline"
  offlineAt?: string
  offline_at?: string
  lifecycleChangedAt?: string
  lifecycle_changed_at?: string
  tag?: string
  stateTag?: string
  stateTags?: string[]
  accent?: string
  voiceStyle?: string
  canSpeak?: boolean
  version?: string
  hideTurnaroundHeads?: boolean
  locked?: boolean
  lockedByUser?: boolean
  preserveOnReplan?: boolean
  media?: MediaAsset | null
  referenceMedia?: MediaAsset | null
  referenceMediaRole?: "original" | "reference" | null
  voiceReferenceAudio?: MediaAsset | null
  mediaVersions?: AssetMediaVersion[]
  activeMediaVersionId?: string | null
  aliases?: string[]
  assetRangeId?: string
  asset_range_id?: string
  firstEpisodeId?: string
  first_episode_id?: string
  sourceRangeLabel?: string
  source_range_label?: string
  sourceRangeSummary?: string
  source_range_summary?: string
  sourceRefs?: Array<Record<string, unknown>>
  visualSpec?: Record<string, unknown>
  continuity?: Record<string, unknown>
  prompts?: Record<string, unknown>
  generation?: Record<string, unknown>
}

export type MediaAsset = {
  assetType?: string
  frameOrigin?: Record<string, unknown>
  id?: string
  kind?: "image" | "video" | "audio"
  originalName?: string
  mimeType?: string
  width?: number
  height?: number
  aspectRatio?: string
  size?: number
  duration?: number | string
  format?: string
  fps?: number | string
  dataUrl?: string
  pngFile?: string
  path?: string
  file?: string
  filePath?: string
  relativePath?: string
  relative_path?: string
  url?: string
  pngDataUrl?: string
  outputPngDataUrl?: string
  preview?: string
  thumbnail?: string
  thumbnailPath?: string
  thumbnailFile?: string
  thumbnailRelativePath?: string
  codec?: string
  sampleRate?: number
  channels?: number
  sourceDuration?: number | string
}

export type InputImageFile = {
  assetType?: string
  frameOrigin?: Record<string, unknown>
  id?: string
  name: string
  kind?: "image" | "video" | "audio"
  mimeType: string
  size?: number
  path?: string
  filePath?: string
  file_path?: string
  relativePath?: string
  relative_path?: string
  file?: string
  preview?: string
  dataUrl?: string
}

export type AssetMediaVersion = {
  id: string
  title?: string
  createdAt?: string
  status?: string
  media?: MediaAsset | null
  desc?: string
  prompts?: Record<string, unknown>
  canSpeak?: boolean
  voiceStyle?: string
  stateTag?: string
  stateTags?: string[]
}

export type AssetLibrary = {
  characters: AssetItem[]
  creatures: AssetItem[]
  scenes: AssetItem[]
  props: AssetItem[]
  styles: AssetItem[]
}

export type DirectorPlanAssetCatalog = Record<"characters" | "creatures" | "scenes" | "props", Array<{
  id: string
  name: string
  description?: string
}>>

export async function getDirectorPlanAssetCatalog(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  nodeId: string,
): Promise<DirectorPlanAssetCatalog> {
  const result = ensureSuccess(await callBackend<BackendResult<{ assetCatalog: DirectorPlanAssetCatalog }>>(
    "get_director_plan_asset_catalog", { projectId, episodeId, nodeId },
  ))
  return result.assetCatalog
}

export type AssetType = keyof AssetLibrary

export type ProjectAssetCounts = {
  characters: number
  creatures: number
  scenes: number
  props: number
}

export type SourceFile = {
  id: string
  title: string
  kind: string
  sourceGroup?: "novel" | "supplemental" | string
  source_group?: "novel" | "supplemental" | string
  status: "ready" | "draft" | "failed"
  wordCount: number
  excerpt: string
  createdAt: string
  rawFilename?: string
  contentPath?: string
  relativePath?: string
  appendSegments?: SourceSegment[]
  append_segments?: SourceSegment[]
  totalTextHash?: string
  total_text_hash?: string
  currentTotalTextHash?: string
  current_total_text_hash?: string
  totalTextHashStatus?: string
  total_text_hash_status?: string
  needsRestore?: boolean
  needs_restore?: boolean
  hasTotalTextBackup?: boolean
  has_total_text_backup?: boolean
}

export type SourceSegment = {
  id: string
  sourceId?: string
  source_id?: string
  kind?: string
  title?: string
  rawFilename?: string
  raw_filename?: string
  charStart?: number
  char_start?: number
  charEnd?: number
  char_end?: number
  charCount?: number
  char_count?: number
  lineStart?: number
  line_start?: number
  lineEnd?: number
  line_end?: number
  lineCount?: number
  line_count?: number
  wordCount?: number
  word_count?: number
  textHash?: string
  text_hash?: string
  createdAt?: string
  created_at?: string
  updatedAt?: string
  updated_at?: string
}

export type SourceText = {
  sourceId: string
  title?: string
  text: string
  charCount: number
  wordCount?: number
  contentPath?: string
  relativePath?: string
  rawFilename?: string
  appendSegments?: SourceSegment[]
  append_segments?: SourceSegment[]
  totalTextHash?: string
  currentTotalTextHash?: string
  totalTextHashStatus?: string
  needsRestore?: boolean
  hasTotalTextBackup?: boolean
}

export type EpisodeSourceFile = {
  episodeId: string
  title?: string
  sourceId: string
  absoluteStart: number
  absoluteEnd: number
  charCount: number
  boundaryReason?: string
  status?: string
  relativePath?: string
  excerpt?: string
  sourceRef?: Record<string, unknown>
}

export type SourceCoverage = {
  sourceId: string
  episodeCursor?: {
    nextOffset?: number
    targetUnits?: number
    lastEpisodeId?: string | null
  }
  assetCursor?: {
    nextOffset?: number
    targetUnits?: number
    lastRangeId?: string | null
  }
  episodeRanges?: Array<Record<string, unknown>>
  assetRanges?: Array<Record<string, unknown>>
  pendingProposal?: Record<string, unknown> | null
}

export type DeleteProjectPlanningOutputsResult = {
  success: true
  message?: string
  targets?: string[]
  episodeIds?: string[]
  deletedCanvasDocumentCount?: number
  deletedCanvasRecordCount?: number
  deletedCanvasRecords?: Record<
    string,
    {
      success?: boolean
      episodeId?: string
      deleted?: boolean
      deletedCount?: number
      deletedRecords?: Record<string, number>
      changedResources?: string[]
    }
  >
  changedResources?: string[]
  projectChanged?: boolean
  focusTarget?: {
    section?: string
    episodeId?: string
    nodeId?: string
    assetTab?: string
  } | null
}

export type AssetSplitRecordType = Exclude<AssetType, "styles">

export type AssetSplitBatchAsset = AssetItem & {
  assetType?: AssetSplitRecordType | string
  createdInRange?: boolean
}

export type AssetSplitBatch = {
  index: number
  batchLabel?: string
  rangeId: string
  sourceId?: string
  sourceTitle?: string
  absoluteStart?: number
  absoluteEnd?: number
  rangeLabel?: string
  targetUnits?: number | string | null
  actualUnits?: number
  status?: string
  analysisStatus?: string
  summary?: string
  storyUnitSummary?: string
  excerpt?: string
  sourceText?: string
  sourceTextCharCount?: number
  sourceTextTruncated?: boolean
  createdAt?: string
  assetCounts?: Partial<Record<AssetSplitRecordType, number>>
  totalAssetCount?: number
  newAssetCount?: number
  activeAssetCount?: number
  offlineAssetCount?: number
  orphanAssetIds?: string[]
  assets?: Partial<Record<AssetSplitRecordType, AssetSplitBatchAsset[]>>
}

export type AssetSplitBatchSourceText = {
  projectId: string
  sourceId?: string
  sourceTitle?: string
  rangeId: string
  rangeLabel?: string
  absoluteStart?: number
  absoluteEnd?: number
  actualUnits?: number
  sourceText: string
  sourceTextCharCount?: number
  sourceTextTruncated?: boolean
}

export type EpisodeSourceText = {
  episodeId: string
  available?: boolean
  title?: string
  text: string
  charCount: number
  relativePath?: string
  sourceRef?: Record<string, unknown>
  message?: string
}

export type FileLocationResult = {
  success: true
  message?: string
  path: string
  openedPath: string
  relativePath?: string
  sourceId?: string
  episodeId?: string
}

export type CreateProjectPayload = {
  name: string
  contentMode?: ContentMode
  sourceLanguage?: string
  aspectRatio: string
  episodeCount: number
  episodePreset?: string
  styleMode?: "template" | "favorite" | "custom"
  styleCategory?: StyleCategory
  styleTemplateId?: string | null
  stylePrompt?: string
  styleAssetPrompt?: string
  styleVisualTypeTag?: string
  characterAssetPrompt?: string
  creatureAssetPrompt?: string
  phaseVisuals?: Array<{
    id: string
    name: string
    prompt: string
  }>
  activePhaseVisualId?: string | null
  styleFile?: InputImageFile | null
  sourceTitle?: string
  sourceText?: string
}

export type AssetPayload = {
  name: string
  desc: string
  lifecycleStatus?: "active" | "offline"
  lifecycle_status?: "active" | "offline"
  tag?: string
  canSpeak?: boolean
  voiceStyle?: string
  hideTurnaroundHeads?: boolean
  stateTag?: string
  stateTags?: string[]
  prompts?: Record<string, unknown>
  media?: MediaAsset | null
  referenceMedia?: MediaAsset | null
  referenceMediaRole?: "original" | "reference" | null
  voiceReferenceAudio?: MediaAsset | null
  mediaVersions?: Array<Record<string, unknown>>
  activeMediaVersionId?: string | null
  activeVersionId?: string | null
  mediaVersionId?: string | null
  sourceVersionId?: string | null
  overwrite?: boolean
}

export type SourcePayload = {
  title: string
  content: string
  kind?: string
  sourceGroup?: "novel" | "supplemental" | string
  source_group?: "novel" | "supplemental" | string
  rawFilename?: string
}

export type ProjectSettings = {
  projectConfigRevision?: number
  pipelineMode: "storyboard_video"
  contentMode?: ContentMode
  aspectRatio: string
  sourceLanguage?: string
  source_language?: string
  episodeTargetUnits?: number
  episode_target_units?: number
  assetExtractionTargetUnits?: number
  asset_extraction_target_units?: number
  agentModelId?: string
  agentReasoningEffort?: "" | "low" | "medium" | "high" | "xhigh" | "max"
  styleMode?: "template" | "favorite" | "custom"
  style_mode?: "template" | "favorite" | "custom"
  styleCategory?: string
  style_category?: string
  styleTemplateId?: string | null
  style_template_id?: string | null
  stylePrompt?: string
  style_prompt?: string
  styleAssetPrompt?: string
  style_asset_prompt?: string
  styleVisualTypeTag?: string
  style_visual_type_tag?: string
  characterAssetPrompt?: string
  character_asset_prompt?: string
  creatureAssetPrompt?: string
  creature_asset_prompt?: string
  phaseVisuals?: Array<{
    id: string
    name: string
    prompt: string
  }>
  phase_visuals?: Array<{
    id: string
    name: string
    prompt: string
  }>
  activePhaseVisualId?: string | null
  active_phase_visual_id?: string | null
  styleFile?: InputImageFile | null
  coverImage?: ProjectThumbnailRef | null
  cover_image?: ProjectThumbnailRef | null
  styleReference?: ProjectThumbnailRef | null
  style_reference?: ProjectThumbnailRef | null
  thumbnail?: ProjectThumbnailRef | null
  coverFile?: InputImageFile | null
  clearCoverImage?: boolean
  panelCount: number
  storyboardRhythmMultiplier: number
  storyboardClipMaxSeconds: number
  allowManualStoryboard: boolean
}


























































































export type TaskRow = {
  promptOperation?: "generate" | "optimize"
  id: string
  type: string
  projectId: string
  episodeId?: string | null
  nodeId?: string | null
  nodeType?: string
  clientRequestId?: string
  idempotencyKey?: string
  reused?: boolean
  generationTaskType?: string
  canvasStageStatus?: "running" | "completed"
  generationTaskNodeId?: string
  realTaskId?: string
  resultNodeId?: string | null
  outputNodeId?: string | null
  versionNodeId?: string | null
  versionId?: string | null
  routeId?: string
  routeLabel?: string
  workChainId?: string
  workChainLabel?: string
  workChainTitle?: string
  workChainName?: string
  segmentId?: string
  strategy?: string
  modelId?: string
  providerId?: string
  estimatedCost?: number | string | null
  consumedCost?: number | string | null
  elapsedMs?: number | string | null
  durationMs?: number | string | null
  startedAt?: number | string | null
  updatedAt?: number | string | null
  completedAt?: number | string | null
  failedAt?: number | string | null
  failureReason?: string | null
  errorSummary?: string | null
  providerResponseSummary?: string | null
  errorDebug?: string | null
  traceback?: string | null
  stackTrace?: string | null
  inputSnapshot?: Record<string, unknown> | null
  preflight?: Record<string, unknown> | null
  budget?: Record<string, unknown> | null
  assetType?: AssetType | string
  assetId?: string
  assetName?: string
  status:
    | "created"
    | "queued"
    | "waiting"
    | "ready"
    | "running"
    | "completed"
    | "succeeded"
    | "failed"
    | "blocked"
    | "preflight_failed"
    | "paused"
    | "cancelled"
    | string
  progress: number
  message?: string
  error?: string | null
  agentAction?: string
  workerName?: string
  workerRunId?: string
  sessionId?: string
  assetRangeId?: string
  workerRun?: Record<string, unknown> | null
  notice?: string
  notificationClearedAt?: number | string | null
  focusTarget?: {
    section?: string
    episodeId?: string
    assetTab?: string
    nodeId?: string
    versionId?: string
  } | null
  projectEffect?: {
    action?: string
    changedResources?: string[]
    focusTarget?: {
      section?: string
      episodeId?: string
      assetTab?: string
      nodeId?: string
      versionId?: string
    } | null
    notice?: string
  } | null
  result?: {
    nodeId?: string
    node?: WorkflowNode | Record<string, unknown>
    resultNode?: WorkflowNode | Record<string, unknown>
    assetId?: string
    assetType?: AssetType | string
    asset?: AssetItem | Record<string, unknown>
    media?: MediaAsset | Record<string, unknown>
    workflowVersion?: number | string | null
    skipped?: boolean
    [key: string]: unknown
  } | null
  version?: StoryboardVersion | null
  createdAt: number | string
}

export type ListTasksOptions = {
  projectId?: string
  project_id?: string
  episodeId?: string
  episode_id?: string
  sessionId?: string
  nodeId?: string
  node_id?: string
  type?: string
  taskType?: string
  task_type?: string
  types?: string[]
  taskTypes?: string[]
  task_types?: string[]
  status?: string
  statuses?: string[]
  taskStatus?: string
  taskStatuses?: string[]
  task_status?: string
  task_statuses?: string[]
  assetType?: AssetType | string
  asset_type?: AssetType | string
  limit?: number
  compact?: boolean
  summary?: boolean
  lightweight?: boolean
  globalOnly?: boolean
  global_only?: boolean
  workspaceDockOnly?: boolean
  workspace_dock_only?: boolean
  dockOnly?: boolean
  dock_only?: boolean
  notificationOnly?: boolean
  notification_only?: boolean
  unreadNotificationsOnly?: boolean
  unread_notifications_only?: boolean
}

export type WorkflowTaskCostSummary = {
  estimatedCost?: number
  queuedCost?: number
  runningCost?: number
  consumedCost?: number
  failedCost?: number
}

export type AgentConversationScope = "project" | "episode"

export type AgentTargetContext = {
  source?: string
  intent?: "focus" | "create" | "update" | "generate" | "delete" | string
  section?: string
  episodeId?: string | null
  canvasKind?: "work_chain" | "custom" | string
  canvasId?: string
  canvasTitle?: string
  assetTab?: AssetType | string
  assetType?: AssetType | string
  assetId?: string
  assetName?: string
  nodeId?: string
  nodeType?: string
  routeId?: string
  segmentId?: string
  workChainId?: string
  cardTitle?: string
  field?: string
}

export type AgentConversationRow = {
  id?: string
  title?: string
  episodeId?: string | null
  createdAt?: string
  updatedAt?: string
  status?: string
  [key: string]: unknown
}

export type AgentConversationContext = {
  success: true
  projectId: string
  episodeId?: string | null
  scope: AgentConversationScope | string
  sessionId?: string
  context?: Record<string, unknown>
  activeTarget?: AgentTargetContext | null
}

export type AgentConversationContextPayload = {
  scope?: AgentConversationScope
  sessionId?: string
  workflowId?: string
  activeTarget?: AgentTargetContext | null
}

export type AgentConversationListResult = {
  success: true
  scope: AgentConversationScope | string
  episodeId?: string | null
  conversations: AgentConversationRow[]
  sessions?: AgentConversationRow[]
}

export type EnsureEpisodeAgentConversationResult = {
  success: true
  conversation?: AgentConversationRow
  session?: Record<string, unknown>
  context?: AgentConversationContext
}

export type StoryboardVersion = {
  id: string
  nodeId?: string
  title: string
  status: string
  active?: boolean
  createdAt: string
  preview?: string | null
  media?: MediaAsset | null
  summary?: string
  source?: string
  model?: string
  provider?: string
  generationError?: string
  payload?: Record<string, unknown>
  winner?: boolean
  selectionReason?: string
  selectedAt?: string
  selectionProvenance?: Record<string, unknown>
  qualityResult?: Record<string, unknown>
}

export type ExportScope =
  | "sources"
  | "assets"
  | "storyboard_plan"
  | "storyboard_image"
  | "final_video"
  | "diagnostics"
  | "usage"

export type HomeGlobalExportScope =
  | "providers"
  | "models"
  | "scriptAdaptationTemplates"
  | "directorRules"
  | "textReplacementRules"
  | "storyboardTemplates"

export type HomeAssetExportScope =
  | "characters"
  | "creatures"
  | "scenes"
  | "props"
  | "styles"

export type JianyingExportEpisode = {
  id: string
  canvasId?: string
  storageKey?: string
  title: string
  order: number
  canvasCount: number
  workChainCount: number
  workChainVideoCount: number
  otherVideoCount: number
  generatedVideoCount: number
  staleAllocationCount?: number
  missingAllocationCount?: number
  unreadableVideoCount?: number
  eligible: boolean
  clips?: Array<{
    nodeId: string
    versionId: string
    workChainId: string
    shotGroupId: string
    durationSec: number
    boundaryKind: string
    audioBoundaryKind: string
    mustKeepTail: boolean
  }>
}

export type JianyingExportInfo = {
  success: true
  projectId: string
  episodes: JianyingExportEpisode[]
  sources?: {
    workChain?: {
      entries: JianyingExportEpisode[]
    }
    custom?: {
      entries: JianyingExportEpisode[]
    }
  }
}

export type UsageSummary = {
  monthCost: number
  storyboardImages: number
  storyboardVideos: number
  assetImages?: number
  failedTasks: number
}

export type BackendResult<T> =
  | T
  | {
      success: false
      message: string
    }

export type BackendCaller = <T = unknown>(
  method: string,
  params?: Record<string, unknown>
) => Promise<T>

function ensureSuccess<T>(result: BackendResult<T>): T {
  if (
    result &&
    typeof result === "object" &&
    "success" in result &&
    result.success === false
  ) {
    throw new Error(result.message || "后端调用失败")
  }
  return result as T
}

export async function getDashboard(
  callBackend: BackendCaller
): Promise<DashboardResponse> {
  return ensureSuccess(
    await callBackend<BackendResult<DashboardResponse>>("get_dashboard")
  )
}

export async function getProjectCreationOptions(
  callBackend: BackendCaller
): Promise<ProjectCreationOptions> {
  return ensureSuccess(
    await callBackend<BackendResult<ProjectCreationOptions>>(
      "get_project_creation_options"
    )
  )
}

export async function createProject(
  callBackend: BackendCaller,
  project: CreateProjectPayload
): Promise<ProjectRow> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; project: ProjectRow }>>(
      "create_project",
      { project }
    )
  )
  return result.project
}

export async function analyzeStyleImage(
  callBackend: BackendCaller,
  file: InputImageFile,
  projectId?: string
): Promise<{ style_description: string }> {
  return ensureSuccess(
    await callBackend<BackendResult<{ style_description: string }>>(
      "analyze_style_image",
      projectId ? { file, projectId } : { file }
    )
  )
}

export async function uploadStyleImage(
  callBackend: BackendCaller,
  projectId: string,
  file: InputImageFile,
  styleDescription?: string
): Promise<void> {
  ensureSuccess(
    await callBackend<BackendResult<{ success: true }>>("upload_style_image", {
      projectId,
      file,
      styleDescription,
    })
  )
}

export async function importProject(
  callBackend: BackendCaller,
  project: CreateProjectPayload
): Promise<ProjectRow> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; project: ProjectRow }>>(
      "import_project",
      { project }
    )
  )
  return result.project
}

export async function deleteProject(
  callBackend: BackendCaller,
  projectId: string
): Promise<void> {
  ensureSuccess(
    await callBackend<BackendResult<{ success: true }>>("delete_project", {
      projectId,
    })
  )
}

export async function listProviders(
  callBackend: BackendCaller
): Promise<{ providers: ProviderSetting[]; presets: ProviderSetting[] }> {
  return ensureSuccess(
    await callBackend<
      BackendResult<{
        providers: ProviderSetting[]
        presets: ProviderSetting[]
      }>
    >("list_providers")
  )
}

export async function addProvider(
  callBackend: BackendCaller,
  payload: Record<string, unknown>
): Promise<ProviderSetting> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{ success: true; provider: ProviderSetting }>
    >("add_provider", payload)
  )
  return result.provider
}

export async function testProviderConnection(
  callBackend: BackendCaller,
  providerId: string
): Promise<{ provider: ProviderSetting; result: ProviderTestResult }> {
  const result = await callBackend<{
    success: boolean
    provider: ProviderSetting
    result: ProviderTestResult
    message?: string
  }>("test_provider_connection", { providerId })
  if (!result.result) {
    throw new Error(result.message || "供应商连接测试失败")
  }
  return { provider: result.provider, result: result.result }
}

export async function getScriptAdaptationTemplates(
  callBackend: BackendCaller
): Promise<ScriptAdaptationTemplateOption[]> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{ templates: ScriptAdaptationTemplateOption[] }>
    >("get_script_adaptation_templates")
  )
  return result.templates
}

export async function saveScriptAdaptationTemplate(
  callBackend: BackendCaller,
  template: Record<string, unknown>
): Promise<ScriptAdaptationTemplateOption[]> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{
        success: true
        templates: ScriptAdaptationTemplateOption[]
      }>
    >("save_script_adaptation_template", { template })
  )
  return result.templates
}

export async function deleteScriptAdaptationTemplate(
  callBackend: BackendCaller,
  templateId: string
): Promise<ScriptAdaptationTemplateOption[]> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{
        success: true
        templates: ScriptAdaptationTemplateOption[]
      }>
    >("delete_script_adaptation_template", { templateId })
  )
  return result.templates
}

export async function getTextReplacementRules(
  callBackend: BackendCaller
): Promise<TextReplacementRuleOption[]> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ rules: TextReplacementRuleOption[] }>>(
      "get_text_replacement_rules"
    )
  )
  return result.rules
}

export async function saveTextReplacementRules(
  callBackend: BackendCaller,
  rules: TextReplacementRuleOption[]
): Promise<TextReplacementRuleOption[]> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{ success: true; rules: TextReplacementRuleOption[] }>
    >("save_text_replacement_rules", { rules })
  )
  return result.rules
}

export async function getStoryboardTemplates(
  callBackend: BackendCaller
): Promise<StoryboardTemplateOption[]> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ templates: StoryboardTemplateOption[] }>>(
      "get_storyboard_templates"
    )
  )
  return result.templates
}

export async function saveStoryboardTemplate(
  callBackend: BackendCaller,
  template: Record<string, unknown>
): Promise<StoryboardTemplateOption[]> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{ success: true; templates: StoryboardTemplateOption[] }>
    >("save_storyboard_template", { template })
  )
  return result.templates
}

export async function deleteStoryboardTemplate(
  callBackend: BackendCaller,
  templateId: string
): Promise<StoryboardTemplateOption[]> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{ success: true; templates: StoryboardTemplateOption[] }>
    >("delete_storyboard_template", { templateId })
  )
  return result.templates
}

export async function getDirectorRules(
  callBackend: BackendCaller
): Promise<DirectorRuleOption[]> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ rules: DirectorRuleOption[] }>>(
      "get_director_rules"
    )
  )
  return result.rules
}

export async function saveDirectorRule(
  callBackend: BackendCaller,
  rule: Pick<DirectorRuleOption, "id" | "description" | "content">
): Promise<DirectorRuleOption[]> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{ success: true; rules: DirectorRuleOption[] }>
    >("save_director_rule", { rule })
  )
  return result.rules
}

export async function resetDirectorRule(
  callBackend: BackendCaller,
  id: string
): Promise<DirectorRuleOption[]> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{ success: true; rules: DirectorRuleOption[] }>
    >("reset_director_rule", { id })
  )
  return result.rules
}

export async function listAssets(
  callBackend: BackendCaller,
  scope: "global" | "project" = "global",
  projectId?: string,
  options: {
    includeSourceMetadata?: boolean
    assetType?: AssetType
    lifecycleStatus?: "active" | "offline" | "all"
  } = {}
): Promise<AssetLibrary> {
  return ensureSuccess(
    await callBackend<BackendResult<AssetLibrary>>("list_assets", {
      scope,
      projectId,
      assetType: options.assetType,
      lifecycleStatus: options.lifecycleStatus,
      includeSourceMetadata: options.includeSourceMetadata ?? false,
    })
  )
}

export async function getProjectAssetCounts(
  callBackend: BackendCaller,
  projectId: string
): Promise<ProjectAssetCounts> {
  return ensureSuccess(
    await callBackend<BackendResult<ProjectAssetCounts>>(
      "get_project_asset_counts",
      { projectId }
    )
  )
}

export async function createAsset(
  callBackend: BackendCaller,
  assetType: AssetType,
  asset: AssetPayload,
  scope: "global" | "project" = "global",
  projectId?: string,
): Promise<AssetItem> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; asset: AssetItem }>>(
      "create_asset",
      {
        assetType,
        asset,
        scope,
        projectId,
      }
    )
  )
  return result.asset
}

export async function deleteAsset(
  callBackend: BackendCaller,
  assetType: AssetType,
  assetId: string,
  scope: "global" | "project" = "global",
  projectId?: string
): Promise<void> {
  ensureSuccess(
    await callBackend<BackendResult<{ success: true }>>("delete_asset", {
      assetType,
      assetId,
      scope,
      projectId,
    })
  )
}

export async function updateAsset(
  callBackend: BackendCaller,
  assetType: AssetType,
  assetId: string,
  asset: Partial<AssetPayload>,
  scope: "global" | "project" = "global",
  projectId?: string,
): Promise<AssetItem> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; asset: AssetItem }>>(
      "update_asset",
      {
        assetType,
        assetId,
        asset,
        scope,
        projectId,
      }
    )
  )
  return result.asset
}

export async function setActiveAssetMediaVersion(
  callBackend: BackendCaller,
  assetType: AssetType,
  assetId: string,
  versionId: string,
  scope: "global" | "project" = "global",
  projectId?: string,
): Promise<AssetItem> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; asset: AssetItem }>>(
      "set_active_asset_media_version",
      {
        assetType,
        assetId,
        versionId,
        scope,
        projectId,
      }
    )
  )
  return result.asset
}

export async function updateAssetMediaVersion(
  callBackend: BackendCaller,
  assetType: AssetType,
  assetId: string,
  versionId: string,
  patch: Partial<Pick<AssetMediaVersion, "stateTag" | "stateTags">>,
  scope: "global" | "project" = "global",
  projectId?: string
): Promise<AssetItem> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; asset: AssetItem }>>(
      "update_asset_media_version",
      { assetType, assetId, versionId, patch, scope, projectId }
    )
  )
  return result.asset
}

export async function deleteAssetMediaVersion(
  callBackend: BackendCaller,
  assetType: AssetType,
  assetId: string,
  versionId: string,
  scope: "global" | "project" = "global",
  projectId?: string
): Promise<AssetItem> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; asset: AssetItem }>>(
      "delete_asset_media_version",
      { assetType, assetId, versionId, scope, projectId }
    )
  )
  return result.asset
}

export async function generateAssetMedia(
  callBackend: BackendCaller,
  assetType: AssetType,
  assetId: string,
  scope: "global" | "project" = "project",
  projectId?: string,
  options?: { episodeId?: string; episodeIds?: string[]; hideTurnaroundHeads?: boolean }
): Promise<{
  asset?: AssetItem
  media?: MediaAsset
  task?: TaskRow
  tasks?: TaskRow[]
  backgroundStarted?: boolean
  message?: string
}> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{
        success: true
        asset?: AssetItem
        media?: MediaAsset
        task?: TaskRow
        tasks?: TaskRow[]
        backgroundStarted?: boolean
        message?: string
      }>
    >("generate_asset_media", {
      assetType,
      assetId,
      scope,
      projectId,
      episodeId: options?.episodeId,
      episodeIds: options?.episodeIds,
      hideTurnaroundHeads: options?.hideTurnaroundHeads,
    })
  )
  return result
}

export async function listSources(
  callBackend: BackendCaller,
  projectId: string
): Promise<SourceFile[]> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ sources: SourceFile[] }>>(
      "list_sources",
      { projectId }
    )
  )
  return result.sources
}

export async function getSourceText(
  callBackend: BackendCaller,
  projectId: string,
  sourceId: string
): Promise<SourceText> {
  return ensureSuccess(
    await callBackend<BackendResult<SourceText>>("get_source_text", {
      projectId,
      sourceId,
    })
  )
}

export async function openSourceFileLocation(
  callBackend: BackendCaller,
  projectId: string,
  sourceId: string
): Promise<FileLocationResult> {
  return ensureSuccess(
    await callBackend<BackendResult<FileLocationResult>>(
      "open_source_file_location",
      { projectId, sourceId }
    )
  )
}

export async function saveSourceText(
  callBackend: BackendCaller,
  projectId: string,
  sourceId: string,
  payload: { text: string; title?: string; reason?: string }
): Promise<SourceText> {
  return ensureSuccess(
    await callBackend<BackendResult<SourceText>>("save_source_text", {
      projectId,
      sourceId,
      ...payload,
    })
  )
}

export async function appendNovelSourceFiles(
  callBackend: BackendCaller,
  projectId: string,
  sourceId: string,
  files: SourcePayload[]
): Promise<{ source?: SourceFile; segments?: SourceSegment[] }> {
  return ensureSuccess(
    await callBackend<
      BackendResult<{
        success: true
        source?: SourceFile
        segments?: SourceSegment[]
      }>
    >("append_novel_source_files", {
      projectId,
      sourceId,
      files,
    })
  )
}

export async function deleteSourceSegment(
  callBackend: BackendCaller,
  projectId: string,
  sourceId: string,
  segmentId: string
): Promise<{ source?: SourceFile; deletedSegment?: SourceSegment }> {
  return ensureSuccess(
    await callBackend<
      BackendResult<{
        success: true
        source?: SourceFile
        deletedSegment?: SourceSegment
      }>
    >("delete_source_segment", {
      projectId,
      sourceId,
      segmentId,
    })
  )
}

export async function createSource(
  callBackend: BackendCaller,
  projectId: string,
  source: SourcePayload,
  options?: { onConflict?: "fail" | "replace" | "rename" }
): Promise<SourceFile> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; source: SourceFile }>>(
      "create_source",
      { projectId, source, onConflict: options?.onConflict }
    )
  )
  return result.source
}

export async function replaceSources(
  callBackend: BackendCaller,
  projectId: string,
  sources: SourcePayload[]
): Promise<SourceFile[]> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; sources: SourceFile[] }>>(
      "replace_sources",
      { projectId, sources }
    )
  )
  return result.sources
}

export async function getSourceCoverage(
  callBackend: BackendCaller,
  projectId: string
): Promise<{ coverage: SourceCoverage; episodeSources: EpisodeSourceFile[] }> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{
        success: true
        coverage: SourceCoverage
        episodeSources: EpisodeSourceFile[]
      }>
    >("get_source_coverage", { projectId })
  )
  return {
    coverage: result.coverage,
    episodeSources: result.episodeSources ?? [],
  }
}

export async function listAssetSplitBatches(
  callBackend: BackendCaller,
  projectId: string,
  options: { sourceId?: string; sourceTextLimit?: number } = {}
): Promise<{
  projectId: string
  sourceId?: string
  sourceTextLimit?: number
  batches: AssetSplitBatch[]
  totalBatches: number
}> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{
        success: true
        projectId: string
        sourceId?: string
        sourceTextLimit?: number
        batches: AssetSplitBatch[]
        totalBatches: number
      }>
    >("list_asset_split_batches", {
      projectId,
      sourceId: options.sourceId,
      sourceTextLimit: options.sourceTextLimit,
    })
  )
  return {
    projectId: result.projectId,
    sourceId: result.sourceId,
    sourceTextLimit: result.sourceTextLimit,
    batches: result.batches ?? [],
    totalBatches: result.totalBatches ?? result.batches?.length ?? 0,
  }
}

export async function getAssetSplitBatchSourceText(
  callBackend: BackendCaller,
  projectId: string,
  options: { rangeId: string; sourceId?: string }
): Promise<AssetSplitBatchSourceText> {
  const result = ensureSuccess(
    await callBackend<BackendResult<AssetSplitBatchSourceText>>(
      "get_asset_split_batch_source_text",
      {
        projectId,
        rangeId: options.rangeId,
        sourceId: options.sourceId,
      }
    )
  )
  return {
    projectId: result.projectId,
    sourceId: result.sourceId,
    sourceTitle: result.sourceTitle,
    rangeId: result.rangeId,
    rangeLabel: result.rangeLabel,
    absoluteStart: result.absoluteStart,
    absoluteEnd: result.absoluteEnd,
    actualUnits: result.actualUnits,
    sourceText: result.sourceText ?? "",
    sourceTextCharCount: result.sourceTextCharCount,
    sourceTextTruncated: Boolean(result.sourceTextTruncated),
  }
}

export async function getEpisodeSourceText(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string
): Promise<EpisodeSourceText> {
  return ensureSuccess(
    await callBackend<BackendResult<EpisodeSourceText>>(
      "get_episode_source_text",
      { projectId, episodeId }
    )
  )
}

export async function openEpisodeSourceFileLocation(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string
): Promise<FileLocationResult> {
  return ensureSuccess(
    await callBackend<BackendResult<FileLocationResult>>(
      "open_episode_source_file_location",
      { projectId, episodeId }
    )
  )
}

export async function saveEpisodeSourceText(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: { text: string; title?: string; reason?: string }
): Promise<EpisodeSourceText> {
  return ensureSuccess(
    await callBackend<BackendResult<EpisodeSourceText>>(
      "save_episode_source_text",
      { projectId, episodeId, ...payload }
    )
  )
}

export async function deleteProjectPlanningOutputs(
  callBackend: BackendCaller,
  projectId: string,
  payload: {
    episodeIds?: string[]
    targets?: string[]
    confirmDeleteAll: true
    userInstruction: string
    reason?: string
  }
): Promise<DeleteProjectPlanningOutputsResult> {
  return ensureSuccess(
    await callBackend<BackendResult<DeleteProjectPlanningOutputsResult>>(
      "delete_project_planning_outputs",
      {
        projectId,
        ...payload,
      }
    )
  )
}

export async function getAgentConversationContext(
  callBackend: BackendCaller,
  projectId: string,
  options: { episodeId?: string; scope?: AgentConversationScope } = {}
): Promise<AgentConversationContext> {
  return ensureSuccess(
    await callBackend<BackendResult<AgentConversationContext>>(
      "get_agent_conversation_context",
      {
        projectId,
        episodeId: options.episodeId,
        scope: options.scope,
      }
    )
  )
}

export async function setAgentConversationContext(
  callBackend: BackendCaller,
  projectId: string,
  payload: AgentConversationContextPayload & { episodeId?: string }
): Promise<AgentConversationContext> {
  return ensureSuccess(
    await callBackend<BackendResult<AgentConversationContext>>(
      "set_agent_conversation_context",
      {
        projectId,
        episodeId: payload.episodeId,
        scope: payload.scope,
        sessionId: payload.sessionId,
        workflowId: payload.workflowId,
        activeTarget: payload.activeTarget,
      }
    )
  )
}

export async function listAgentConversations(
  callBackend: BackendCaller,
  projectId: string,
  options: { episodeId?: string; scope?: AgentConversationScope } = {}
): Promise<AgentConversationRow[]> {
  const result = ensureSuccess(
    await callBackend<BackendResult<AgentConversationListResult>>(
      "list_agent_conversations",
      {
        projectId,
        episodeId: options.episodeId,
        scope: options.scope,
      }
    )
  )
  return result.conversations ?? result.sessions ?? []
}

export async function ensureEpisodeAgentConversation(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: { sessionId?: string; title?: string; workflowId?: string } = {}
): Promise<EnsureEpisodeAgentConversationResult> {
  return ensureSuccess(
    await callBackend<BackendResult<EnsureEpisodeAgentConversationResult>>(
      "ensure_episode_agent_conversation",
      {
        projectId,
        episodeId,
        sessionId: payload.sessionId,
        title: payload.title,
        workflowId: payload.workflowId,
      }
    )
  )
}

export async function analyzeProjectOverview(
  callBackend: BackendCaller,
  projectId: string,
  sourceId?: string,
  options?: { excerptChars?: number }
): Promise<{
  overview?: string
  episodes?: Array<{ id: string; title: string; status?: string }>
  project?: ProjectRow
}> {
  return ensureSuccess(
    await callBackend<
      BackendResult<{
        overview?: string
        episodes?: Array<{ id: string; title: string; status?: string }>
        project?: ProjectRow
      }>
    >("analyze_project_overview", {
      projectId,
      sourceId,
      excerptChars: options?.excerptChars,
    })
  )
}

export type ProjectOverviewUpdatePayload = Partial<{
  excerpt_summary: string
  genre_context: string
  theme_visual_context: string
  narrator_voice_design_prompt: string
}>

export async function updateProjectOverview(
  callBackend: BackendCaller,
  projectId: string,
  overview: ProjectOverviewUpdatePayload
): Promise<ProjectRow> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; project: ProjectRow }>>(
      "update_project_overview",
      {
        projectId,
        overview,
      }
    )
  )
  return result.project
}

export async function saveProjectNarratorReferenceAudio(
  callBackend: BackendCaller,
  projectId: string,
  media: MediaAsset | null,
): Promise<ProjectRow> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; project: ProjectRow }>>(
      "save_project_narrator_reference_audio",
      { projectId, media },
    )
  )
  return result.project
}

export type ReferenceAudioPrepareResult = {
  success: true
  processedPath: string
  duration: number
  originalDuration?: number | null
  sourceName?: string
}

export type ReferenceAudioCropResult = {
  success: true
  processedPath: string
  duration: number
  start: number
  end: number
  sourceDuration?: number
}

export async function prepareReferenceAudio(
  callBackend: BackendCaller,
  media: MediaAsset,
): Promise<ReferenceAudioPrepareResult> {
  return ensureSuccess(
    await callBackend<BackendResult<ReferenceAudioPrepareResult>>(
      "prepare_reference_audio",
      { media, maxSeconds: 600 },
    ),
  )
}

export async function cropReferenceAudio(
  callBackend: BackendCaller,
  audioPath: string,
  range?: { start: number; end: number } | null,
): Promise<ReferenceAudioCropResult> {
  return ensureSuccess(
    await callBackend<BackendResult<ReferenceAudioCropResult>>(
      "crop_reference_audio",
      {
        audioPath,
        start: range?.start,
        end: range?.end,
        maxSeconds: 15,
      },
    ),
  )
}

export async function cleanupReferenceAudio(
  callBackend: BackendCaller,
  paths: string | string[],
): Promise<void> {
  ensureSuccess(
    await callBackend<BackendResult<{ success: true }>>(
      "cleanup_reference_audio",
      { paths: Array.isArray(paths) ? paths : [paths] },
    ),
  )
}

export async function deleteSource(
  callBackend: BackendCaller,
  projectId: string,
  sourceId: string
): Promise<void> {
  ensureSuccess(
    await callBackend<BackendResult<{ success: true }>>("delete_source", {
      projectId,
      sourceId,
    })
  )
}

export async function getProjectSettings(
  callBackend: BackendCaller,
  projectId: string
): Promise<ProjectSettings> {
  return ensureSuccess(
    await callBackend<BackendResult<ProjectSettings>>("get_project_settings", {
      projectId,
    })
  )
}

export async function saveProjectSettings(
  callBackend: BackendCaller,
  projectId: string,
  settings: ProjectSettings
): Promise<ProjectSettings> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{ success: true; settings: ProjectSettings }>
    >("save_project_settings", {
      projectId,
      settings,
    })
  )
  return result.settings
}

function canvasRecordArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? ([...value] as T[]) : []
}

function normalizeCanvasViewport(value: unknown): EpisodeWorkflow["viewport"] {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const row = value as Record<string, unknown>
    const x = Number(row.x)
    const y = Number(row.y)
    const zoom = Number(row.zoom)
    return {
      x: Number.isFinite(x) ? x : 0,
      y: Number.isFinite(y) ? y : 0,
      zoom: Number.isFinite(zoom) ? zoom : 0.82,
    }
  }
  return { x: 0, y: 0, zoom: 0.82 }
}

export function workflowFromCanvasSnapshot(
  snapshot: CanvasSnapshotResult
): EpisodeWorkflow {
  const document: CanvasDocumentRecord = snapshot.document ?? {
    episodeId: snapshot.episodeId,
    schemaVersion: snapshot.schemaVersion,
    revision: snapshot.revision,
    currentRevision: snapshot.currentRevision,
  }
  const records: Partial<CanvasRecordPayload> = snapshot.records ?? {}
  const state =
    document.state &&
    typeof document.state === "object" &&
    !Array.isArray(document.state)
      ? document.state
      : {
          kind: "canvas",
          reason: "loaded",
        }
  const version = Number(
    document.currentRevision ??
      document.revision ??
      snapshot.currentRevision ??
      snapshot.revision ??
      0
  )
  const workflow: EpisodeWorkflow = {
    episodeId: String(document.episodeId || snapshot.episodeId),
    schemaVersion: Number(document.schemaVersion || snapshot.schemaVersion || 4),
    version: Number.isFinite(version) ? version : 0,
    viewport: normalizeCanvasViewport(document.viewport),
    nodes: canvasRecordArray<WorkflowNode>(records.nodes),
    edges: canvasRecordArray<WorkflowEdge>(records.edges),
    routes: canvasRecordArray<WorkflowRoute>(records.routes),
    workChains: canvasRecordArray<WorkflowWorkChain>(records.workChains),
    state,
  }
  if (
    document.productionStatus &&
    typeof document.productionStatus === "object" &&
    !Array.isArray(document.productionStatus)
  ) {
    workflow.productionStatus = { ...document.productionStatus }
  }
  if (document.build && typeof document.build === "object" && !Array.isArray(document.build)) {
    workflow.build = { ...document.build }
  }
  return workflow
}

export type CanvasReferenceView = {
  nodeId: string
  data: Record<string, unknown>
}

export async function getCanvasReferenceViews(
  callBackend: BackendCaller, projectId: string, episodeId: string
): Promise<{ revision: number; views: CanvasReferenceView[] }> {
  return ensureSuccess(await callBackend<BackendResult<{ success: true; revision: number; views: CanvasReferenceView[] }>>(
    "get_canvas_reference_views", { projectId, episodeId }
  ))
}

export type CanvasAssetImagesResult = {
  success: true
  episodeId: string
  nodes: WorkflowNode[]
  boundNodeIds: string[]
  workflowVersion?: number
}

export async function resolveCanvasAssetImages(
  callBackend: BackendCaller, projectId: string, episodeId: string, nodeIds: string[]
): Promise<CanvasAssetImagesResult> {
  return ensureSuccess(await callBackend<BackendResult<CanvasAssetImagesResult>>(
    "resolve_canvas_asset_images", { projectId, episodeId, nodeIds }
  ))
}

export async function getCanvasChanges(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  sinceRevision = 0
): Promise<CanvasChangesResult> {
  return ensureSuccess(
    await callBackend<BackendResult<CanvasChangesResult>>("get_canvas_changes", {
      projectId,
      episodeId,
      sinceRevision,
    })
  )
}

export async function getCanvasSnapshot(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  options?: {
    detail?: "full" | "summary"
    includeVersions?: boolean
    includeTasks?: boolean
    includeProjections?: boolean
  }
): Promise<CanvasSnapshotResult> {
  return ensureSuccess(
    await callBackend<BackendResult<CanvasSnapshotResult>>("get_canvas_snapshot", {
      projectId,
      episodeId,
      ...options,
    })
  )
}

export async function getCanvasRecords(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  options: {
    detail?: "full" | "summary"
    ids?: {
      nodeIds?: string[]
      edgeIds?: string[]
      routeIds?: string[]
      workChainIds?: string[]
      versionRefs?: CanvasVersionRef[]
      taskIds?: string[]
      projectionKeys?: string[]
    }
  }
): Promise<CanvasRecordsResult> {
  return ensureSuccess(
    await callBackend<BackendResult<CanvasRecordsResult>>("get_canvas_records", {
      projectId,
      episodeId,
      ...options,
    })
  )
}

function normalizeCustomCanvasEntry(raw: unknown): CustomCanvasEntry | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null
  const row = raw as Record<string, unknown>
  const canvasId = String(row.canvasId ?? row.canvas_id ?? "").trim()
  const storageKey = String(row.storageKey ?? row.storage_key ?? "").trim()
  if (!canvasId || !storageKey) return null
  return {
    canvasId,
    kind: "custom",
    title: String(row.title ?? "").trim() || "自定义画布",
    storageKey,
    sortIndex: Number(row.sortIndex ?? row.sort_index ?? 0) || 0,
    createdAt: String(row.createdAt ?? row.created_at ?? "").trim() || undefined,
    updatedAt: String(row.updatedAt ?? row.updated_at ?? "").trim() || undefined,
  }
}

export async function listProjectCustomCanvases(
  callBackend: BackendCaller,
  projectId: string
): Promise<CustomCanvasEntry[]> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{ success: true; customCanvases?: unknown[] }>
    >("list_project_custom_canvases", {
      projectId,
    })
  )
  return Array.isArray(result.customCanvases)
    ? (result.customCanvases
        .map(normalizeCustomCanvasEntry)
        .filter(Boolean) as CustomCanvasEntry[])
    : []
}

export async function createCustomCanvas(
  callBackend: BackendCaller,
  projectId: string,
  payload: { title?: string } = {}
): Promise<CustomCanvasEntry> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; canvas: unknown }>>(
      "create_custom_canvas",
      {
        projectId,
        ...payload,
      }
    )
  )
  const canvas = normalizeCustomCanvasEntry(result.canvas)
  if (!canvas) throw new Error("创建自定义画布失败：返回数据无效")
  return canvas
}

export async function renameCustomCanvas(
  callBackend: BackendCaller,
  projectId: string,
  canvasId: string,
  title: string
): Promise<CustomCanvasEntry> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; canvas: unknown }>>(
      "rename_custom_canvas",
      {
        projectId,
        canvasId,
        title,
      }
    )
  )
  const canvas = normalizeCustomCanvasEntry(result.canvas)
  if (!canvas) throw new Error("重命名自定义画布失败：返回数据无效")
  return canvas
}

export async function deleteCustomCanvas(
  callBackend: BackendCaller,
  projectId: string,
  canvasId: string
): Promise<{ success: true; canvasId: string; deletedCount?: number }> {
  return ensureSuccess(
    await callBackend<
      BackendResult<{ success: true; canvasId: string; deletedCount?: number }>
    >("delete_custom_canvas", {
      projectId,
      canvasId,
    })
  )
}

export async function buildEpisodeWorkflowFromWorkChainPlan(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  options?: { source?: string; reason?: string }
): Promise<EpisodeWorkflow> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{ success: true; workflow: EpisodeWorkflow }>
    >("build_episode_workflow_from_work_chain_plan", {
      projectId,
      episodeId,
      ...options,
    })
  )
  return result.workflow
}


export async function relayoutEpisodeWorkflow(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  options?: { saveVersion?: boolean; source?: string; reason?: string }
): Promise<WorkflowMutationResult> {
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowMutationResult>>(
      "relayout_episode_workflow",
      {
        projectId,
        episodeId,
        ...options,
      }
    )
  )
}

export async function getProjectPlanningSummary(
  callBackend: BackendCaller,
  projectId: string,
  episodeId?: string
): Promise<ProjectPlanningSummary> {
  return ensureSuccess(
    await callBackend<BackendResult<ProjectPlanningSummary>>(
      "get_project_planning_summary",
      {
        projectId,
        episodeId,
      }
    )
  )
}

function canvasMutationPayload<T extends Record<string, unknown>>(payload: T): T {
  const next = { ...payload } as Record<string, unknown>
  delete next.returnWorkflow
  delete next.return_workflow
  delete next.includeWorkflow
  delete next.include_workflow
  return next as T
}

type CanvasTaskRequestPayload = object & {
  clientRequestId?: string
  client_request_id?: string
}

function createCanvasTaskClientRequestId(
  kind: string,
  projectId: string,
  episodeId: string,
  nodeId?: string
) {
  const randomId =
    typeof globalThis.crypto?.randomUUID === "function"
      ? globalThis.crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  return ["canvas-task", kind, projectId, episodeId, nodeId, randomId]
    .map((item) => String(item ?? "").trim())
    .filter(Boolean)
    .join(":")
}

function withCanvasTaskClientRequestId<T extends CanvasTaskRequestPayload>(
  kind: string,
  projectId: string,
  episodeId: string,
  nodeId: string | undefined,
  payload: T
): T & { clientRequestId: string } {
  const existing = String(
    payload.clientRequestId ?? payload.client_request_id ?? ""
  ).trim()
  return {
    ...payload,
    clientRequestId:
      existing ||
      createCanvasTaskClientRequestId(kind, projectId, episodeId, nodeId),
  }
}

export async function importWorkflowMedia(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: WorkflowMediaImportPayload
): Promise<WorkflowExternalMediaImportResult> {
  const returnProductionStatus =
    payload.returnProductionStatus ??
    payload.return_production_status ??
    payload.includeProductionStatus ??
    payload.include_production_status ??
    false
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowExternalMediaImportResult>>(
      "import_workflow_media",
      {
        projectId,
        episodeId,
        ...canvasMutationPayload(payload),
        returnProductionStatus,
      }
    )
  )
}

export async function saveClipboardImageMedia(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    file: InputImageFile
    mediaPurpose?: string
    media_purpose?: string
    assetScope?: string
    asset_scope?: string
    mediaId?: string
    media_id?: string
  }
): Promise<ClipboardImageMediaResult> {
  return ensureSuccess(
    await callBackend<BackendResult<ClipboardImageMediaResult>>(
      "save_clipboard_image_media",
      {
        projectId,
        episodeId,
        ...payload,
      }
    )
  )
}

export async function getVideoClipInfo(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: { media: MediaAsset | Record<string, unknown> }
): Promise<VideoClipInfoResult> {
  return ensureSuccess(
    await callBackend<BackendResult<VideoClipInfoResult>>("get_video_clip_info", {
      projectId,
      episodeId,
      ...payload,
    })
  )
}

export async function listVideoClipResults(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: { media: MediaAsset | Record<string, unknown> }
): Promise<VideoClipResultsListResult> {
  return ensureSuccess(
    await callBackend<BackendResult<VideoClipResultsListResult>>(
      "list_video_clip_results",
      {
        projectId,
        episodeId,
        ...payload,
      }
    )
  )
}

export async function extractVideoFramePreview(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    media: MediaAsset | Record<string, unknown>
    time: number
    frameIndex?: number
  }
): Promise<VideoClipMediaResult> {
  return ensureSuccess(
    await callBackend<BackendResult<VideoClipMediaResult>>(
      "extract_video_frame_preview",
      {
        projectId,
        episodeId,
        ...payload,
      }
    )
  )
}

export async function extractVideoFrame(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    media: MediaAsset | Record<string, unknown>
    inputMedia?: MediaAsset | Record<string, unknown>
    time: number
    frameIndex?: number
    title?: string
    mediaId?: string
    tailFrame?: boolean
  }
): Promise<VideoClipMediaResult> {
  return ensureSuccess(
    await callBackend<BackendResult<VideoClipMediaResult>>("extract_video_frame", {
      projectId,
      episodeId,
      ...payload,
    })
  )
}

export async function trimVideoClip(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    media: MediaAsset | Record<string, unknown>
    inputMedia?: MediaAsset | Record<string, unknown>
    start: number
    end: number
    title?: string
    mediaId?: string
    crop?: {
      x: number
      y: number
      width: number
      height: number
    }
    cropX?: number
    cropY?: number
    cropWidth?: number
    cropHeight?: number
  }
): Promise<VideoClipMediaResult> {
  return ensureSuccess(
    await callBackend<BackendResult<VideoClipMediaResult>>("trim_video_clip", {
      projectId,
      episodeId,
      ...payload,
    })
  )
}

export async function deleteVideoClipResults(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    media: MediaAsset | Record<string, unknown>
    resultId?: string
    resultIds?: string[]
  }
): Promise<VideoClipDeleteResultsResult> {
  return ensureSuccess(
    await callBackend<BackendResult<VideoClipDeleteResultsResult>>(
      "delete_video_clip_results",
      {
        projectId,
        episodeId,
        ...payload,
      }
    )
  )
}

export async function linkWorkflowInput(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: WorkflowInputLinkPayload
): Promise<WorkflowInputLinkResult> {
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowInputLinkResult>>(
      "link_workflow_input",
      {
        projectId,
        episodeId,
        ...canvasMutationPayload(payload),
      }
    )
  )
}

export async function setWorkflowReferenceUsage(
  callBackend: BackendCaller, projectId: string, episodeId: string,
  payload: WorkflowInputLinkPayload & { enabled?: boolean }
): Promise<WorkflowInputLinkResult> {
  return ensureSuccess(await callBackend<BackendResult<WorkflowInputLinkResult>>(
    "set_workflow_reference_usage", { projectId, episodeId, ...canvasMutationPayload(payload) }
  ))
}

export async function unlinkWorkflowInput(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: WorkflowInputLinkPayload
): Promise<WorkflowInputLinkResult> {
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowInputLinkResult>>(
      "unlink_workflow_input",
      {
        projectId,
        episodeId,
        ...canvasMutationPayload(payload),
      }
    )
  )
}

export async function listWorkflowMedia(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string
): Promise<WorkflowMediaListResult> {
  const result = ensureSuccess(
    await callBackend<BackendResult<WorkflowMediaListResult>>(
      "list_workflow_media",
      { projectId, episodeId }
    )
  )
  return {
    ...result,
    items: Array.isArray(result.items) ? result.items : [],
  }
}

export async function listWorkflowInputs(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: Pick<
    WorkflowInputLinkPayload,
    "scope" | "visibilityScope" | "nodeId" | "routeId"
  > & { nodeId: string }
): Promise<Array<Record<string, unknown>>> {
  const result = ensureSuccess(
    await callBackend<BackendResult<WorkflowInputLinkResult>>(
      "list_workflow_inputs",
      {
        projectId,
        episodeId,
        ...payload,
      }
    )
  )
  return result.inputs ?? []
}

export async function resolveWorkflowNodeInputs(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  nodeId: string
): Promise<WorkflowNodeInputsResult> {
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowNodeInputsResult>>(
      "resolve_workflow_node_inputs",
      {
        projectId,
        episodeId,
        nodeId,
      }
    )
  )
}

export async function runWorkflowBatch(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    nodeId: string
    variantCount?: number
    userInstruction?: string
    confirmedHighCost?: boolean
    returnProductionStatus?: boolean
    return_production_status?: boolean
  }
): Promise<WorkflowBatchResult> {
  const returnProductionStatus =
    payload.returnProductionStatus ?? payload.return_production_status ?? false
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowBatchResult>>(
      "run_workflow_batch",
      {
        projectId,
        episodeId,
        ...canvasMutationPayload(payload),
        returnProductionStatus,
      }
    )
  )
}

export async function saveVariantQualityResult(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: VariantQualityResultPayload
): Promise<VariantQualityResultResponse> {
  const returnProductionStatus =
    payload.returnProductionStatus ?? payload.return_production_status ?? false
  return ensureSuccess(
    await callBackend<BackendResult<VariantQualityResultResponse>>(
      "save_variant_quality_result",
      {
        projectId,
        episodeId,
        ...canvasMutationPayload(payload),
        returnProductionStatus,
      }
    )
  )
}

export async function createWorkflowNode(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  nodeType: string,
  node?: Partial<WorkflowNode>
): Promise<WorkflowNode> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; node: WorkflowNode }>>(
      "create_workflow_node",
      { projectId, episodeId, nodeType, node }
    )
  )
  return result.node
}

export type WorkflowTaskCardCreateResult = {
  success: true
  episodeId: string
  node: WorkflowNode
  resultNode?: WorkflowNode | null
  edge?: WorkflowEdge | null
  workflowVersion?: number
  changedResources?: string[]
}

export async function createWorkflowTaskCard(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    nodeType: string
    nodeId?: string
    resultNodeId?: string
    position?: { x: number; y: number }
    resultPosition?: { x: number; y: number }
    title?: string
    summary?: string
    status?: string
    data?: Record<string, unknown>
    generationConfig?: Record<string, unknown>
    size?: Record<string, unknown>
    prompt?: string
  }
): Promise<WorkflowTaskCardCreateResult> {
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowTaskCardCreateResult>>(
      "create_workflow_task_card",
      {
        projectId,
        episodeId,
        ...canvasMutationPayload(payload),
      }
    )
  )
}

export type WorkflowChainCreateResult = {
  success: true
  episodeId: string
  workChainId: string
  segmentId: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  routes: WorkflowRoute[]
  workChains: WorkflowWorkChain[]
  workflowVersion?: number
  records?: CanvasMutationRecords
  changedResources?: string[]
  focusTarget?: { section?: string; episodeId?: string; nodeId?: string }
}

export async function createManualWorkflowChain(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: { workChainId: string; position: { x: number; y: number } }
): Promise<WorkflowChainCreateResult> {
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowChainCreateResult>>(
      "create_manual_workflow_chain",
      { projectId, episodeId, ...payload }
    )
  )
}

export type VideoPromptDraftRequest = {
  draftText: string
  soundPrompt?: string
  assetNameMap: Record<string, string>
  promptBindings?: Record<string, string>
}

export type WorkflowAssetNodesCreateResult = {
  success: true
  episodeId: string
  nodes: WorkflowNode[]
  workflowVersion?: number
  changedResources?: string[]
}

export async function addWorkflowAssetNodes(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    nodes: WorkflowNode[]
    reason?: string
  }
): Promise<WorkflowAssetNodesCreateResult> {
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowAssetNodesCreateResult>>(
      "add_workflow_asset_nodes",
      {
        projectId,
        episodeId,
        ...canvasMutationPayload(payload),
      }
    )
  )
}

export async function pasteWorkflowAssetNode(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    sourceProjectId?: string
    sourceEpisodeId: string
    sourceNodeId: string
    sourceNodeType?: string
    position: { x: number; y: number }
    reason?: string
  }
): Promise<WorkflowAssetNodesCreateResult> {
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowAssetNodesCreateResult>>(
      "paste_workflow_asset_node",
      {
        projectId,
        episodeId,
        ...canvasMutationPayload(payload),
      }
    )
  )
}

export type WorkflowRouteUpdateResult = {
  success: true
  episodeId: string
  route: WorkflowRoute
  workflowVersion?: number
  changedResources?: string[]
}

export async function updateWorkflowRoute(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    routeId: string
    route?: Partial<WorkflowRoute>
    locked?: boolean
    lockedByUser?: boolean
    preserveOnReplan?: boolean
    lockedReason?: string | null
    reason?: string
  }
): Promise<WorkflowRouteUpdateResult> {
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowRouteUpdateResult>>(
      "update_workflow_route",
      {
        projectId,
        episodeId,
        ...canvasMutationPayload(payload),
      }
    )
  )
}





export type WorkflowNodeDeleteResult = {
  success: true
  episodeId: string
  itemType?: string
  itemId?: string
  deletedNodeIds?: string[]
  deletedRouteIds?: string[]
  deletedWorkChainIds?: string[]
  deletedEdgeIds?: string[]
  removedInputLinkIds?: string[]
  inputDirtyNodeIds?: string[]
  syncedVideoTaskNodeIds?: string[]
  nodes?: WorkflowNode[]
  routes?: WorkflowRoute[]
  workChains?: WorkflowWorkChain[]
  workflowVersion?: number
  skippedLocked?: boolean
  message?: string
  changedResources?: string[]
  node?: WorkflowNode
  route?: WorkflowRoute
  edge?: WorkflowEdge
  removedEdgeIds?: string[]
}

export async function deleteWorkflowNode(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  nodeId: string,
  options?: { reason?: string }
): Promise<WorkflowNodeDeleteResult> {
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowNodeDeleteResult>>(
      "delete_workflow_node",
      {
        projectId,
        episodeId,
        nodeId,
        reason: options?.reason,
      }
    )
  )
}

export async function deleteWorkflowChain(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  workChainId: string
): Promise<WorkflowNodeDeleteResult> {
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowNodeDeleteResult>>("delete_workflow_node", {
      projectId,
      episodeId,
      itemType: "workChain",
      itemId: workChainId,
    })
  )
}

export async function deleteWorkflowNodes(
  callBackend: BackendCaller, projectId: string, episodeId: string,
  nodeIds: string[], expectedRevision: number,
): Promise<WorkflowNodeDeleteResult> {
  return ensureSuccess(await callBackend<BackendResult<WorkflowNodeDeleteResult>>("delete_workflow_nodes", {
    projectId, episodeId, nodeIds, expectedRevision,
  }))
}

export async function updateWorkflowNodesLayout(
  callBackend: BackendCaller, projectId: string, episodeId: string,
  positions: Array<{ nodeId: string; position: { x: number; y: number } }>,
): Promise<WorkflowNodeDeleteResult> {
  return ensureSuccess(await callBackend<BackendResult<WorkflowNodeDeleteResult>>("update_workflow_nodes_layout", {
    projectId, episodeId, positions,
  }))
}

export type SourceSplitWorkflowResult = {
  success: true
  episodeId: string
  sourceNodeId: string
  segmentCount: number
  workflowVersion?: number
  records?: CanvasMutationRecords
  changedResources?: string[]
  projectChanged?: boolean
}

export async function createIndependentSourceCard(
  callBackend: BackendCaller, projectId: string, episodeId: string,
  position: { x: number; y: number },
): Promise<Omit<SourceSplitWorkflowResult, "segmentCount"> & { node: WorkflowNode }> {
  return ensureSuccess(await callBackend<BackendResult<Omit<SourceSplitWorkflowResult, "segmentCount"> & { node: WorkflowNode }>>(
    "create_independent_source_card", { projectId, episodeId, position },
  ))
}

export async function applyIndependentSourceWorkflow(
  callBackend: BackendCaller, projectId: string, episodeId: string,
  payload: {
    sourceNodeId: string
    sourceText: string
    expectedSourceText: string
    segments: Array<{ text: string; workChainId?: string; templateWorkChainId?: string }>
    workChainIds: string[]
  },
): Promise<SourceSplitWorkflowResult> {
  return ensureSuccess(await callBackend<BackendResult<SourceSplitWorkflowResult>>(
    "apply_independent_source_workflow", { projectId, episodeId, ...canvasMutationPayload(payload) },
  ))
}

export async function adjustSourceSplitWorkflow(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    sourceNodeId: string
    segments: Array<{ text: string; workChainId?: string; templateWorkChainId?: string }>
    workChainIds: string[]
  }
): Promise<SourceSplitWorkflowResult> {
  return ensureSuccess(
    await callBackend<BackendResult<SourceSplitWorkflowResult>>(
      "adjust_source_split_workflow",
      {
        projectId,
        episodeId,
        ...canvasMutationPayload(payload),
      }
    )
  )
}

export type StoryboardShotGroup = {
  id: string
  shotNos: number[]
  order?: number
  reason?: string
}

export type StoryboardAllocationResult = {
  success: true
  episodeId: string
  directorNodeId: string
  groups: StoryboardShotGroup[]
  productionWarnings?: Array<{ groupId: string; shotNos: number[]; code: string; message: string }>
  node?: { data?: Record<string, unknown> }
  editHistoryWarning?: string
  workflowVersion?: number
  records?: CanvasMutationRecords
  changedResources?: string[]
  projectChanged?: boolean
}

export async function applyStoryboardAllocation(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    directorNodeId: string
    directorPlanShots: Array<Record<string, unknown>>
    groups: StoryboardShotGroup[]
    directorPlanPatch?: {
      directorPlanShots?: Array<Record<string, unknown>>
      speakerRoster?: Array<Record<string, unknown>>
      directorRuleId?: string
      directorRuleSelectionMode?: "auto" | "manual"
      rhythmMultiplier?: number | null
    }
    expectedSpeakerRoster?: Array<Record<string, unknown>>
    expectedGroups?: StoryboardShotGroup[]
    sourceShotNos?: Array<number | null>
    invalidateGenerated?: boolean
  }
): Promise<StoryboardAllocationResult> {
  return ensureSuccess(
    await callBackend<BackendResult<StoryboardAllocationResult>>(
      "apply_storyboard_allocation",
      {
        projectId,
        episodeId,
        ...canvasMutationPayload({
          directorNodeId: payload.directorNodeId,
          expectedShots: payload.directorPlanShots,
          groups: payload.groups,
          ...(payload.directorPlanPatch ? { directorPlanPatch: payload.directorPlanPatch } : {}),
          ...(payload.expectedSpeakerRoster ? { expectedSpeakerRoster: payload.expectedSpeakerRoster } : {}),
          ...(payload.expectedGroups ? { expectedGroups: payload.expectedGroups } : {}),
          ...(payload.sourceShotNos ? { sourceShotNos: payload.sourceShotNos } : {}),
          invalidateGenerated: payload.invalidateGenerated === true,
        }),
      }
    )
  )
}

export type WorkflowNodeUpsertResult = {
  success: true
  episodeId: string
  itemType: "node" | "route"
  item?: Record<string, unknown>
  workflowVersion?: number
  skippedLocked?: boolean
  message?: string
  changedResources?: string[]
}

export async function upsertWorkflowNode(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    node: Record<string, unknown> & { id: string }
    saveVersion?: boolean
    source?: string
    reason?: string
  }
): Promise<WorkflowNodeUpsertResult> {
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowNodeUpsertResult>>(
      "upsert_workflow_node",
      {
        projectId,
        episodeId,
        itemType: "node",
        ...canvasMutationPayload(payload),
      }
    )
  )
}

export type WorkflowAssetNodeRenameResult = WorkflowNodeUpsertResult & {
  nodeId: string
  node?: WorkflowNode
  protected?: boolean
}

export async function renameWorkflowAssetNode(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    nodeId: string
    title: string
    kind: "image" | "video"
    mediaPurpose?: string
    voiceStyle?: string
    expectedRevision?: number
    source?: string
    reason?: string
  }
): Promise<WorkflowAssetNodeRenameResult> {
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowAssetNodeRenameResult>>(
      "rename_workflow_asset_node",
      {
        projectId,
        episodeId,
        ...canvasMutationPayload(payload),
      }
    )
  )
}

export type WorkflowNodeInlineEditResult = {
  success: true
  txId?: string
  revision?: number
  productionStatusRefreshFailed?: boolean
  productionStatusWarning?: string
  productionStatusMutation?: Record<string, unknown>
  episodeId: string
  nodeId: string
  node?: WorkflowNode
  nodes?: WorkflowNode[]
  edges?: WorkflowEdge[]
  editHistory?: NodeEditHistoryItem | null
  editHistoryItems?: NodeEditHistoryItem[]
  editHistoryWarning?: string
  reworkRecordWarning?: string
  videoDurationSyncWarning?: string
  videoDurationSyncWarnings?: Array<string | Record<string, unknown>>
  storyboardAllocationWarning?: string
  allocationNeedsSave?: boolean
  structureChanged?: boolean
  workflowVersion?: number
  skippedLocked?: boolean
  message?: string
  dirtyNodeIds?: string[]
  changedResources?: string[]
  productionStatus?: EpisodeProductionStatus | null
}

export type WorkflowNodeLayoutResult = {
  success: true
  episodeId: string
  nodeId: string
  node?: WorkflowNode
  workflowVersion?: number
  skippedLocked?: boolean
  message?: string
  changedResources?: string[]
}


export type NodeEditHistoryItem = {
  id: string
  schemaVersion?: number
  nodeId: string
  nodeType: string
  title?: string
  summary?: string
  createdAt?: string
  displayTime?: string
  reason?: string
  source?: "user" | "model" | "restore" | "system" | string
  subject?: "script" | "director" | "source" | "node" | string
  version?: {
    middle?: {
      key?: string
      title?: string
      text?: string
      present?: boolean
    }
    right?: {
      key?: string
      title?: string
      text?: string
      present?: boolean
    }
    parameters?: Array<{
      key?: string
      label?: string
      value?: unknown
      displayValue?: string
      scope?: string
    }>
  }
  restorePatch?: Record<string, unknown>
  meta?: Record<string, unknown>
}

export type NodeEditHistoryListResult = {
  success: true
  episodeId: string
  items: NodeEditHistoryItem[]
  activeId?: string
}

export type NodeEditHistoryRestoreResult = {
  success: true
  episodeId: string
  nodeId: string
  nodeType: string
  version?: NodeEditHistoryItem
  node?: WorkflowNode
  nodes?: WorkflowNode[]
  workflowVersion?: number
  sourceText?: EpisodeSourceText
  changedResources?: string[]
}

export type NodeEditHistoryDeleteResult = {
  success: true
  episodeId: string
  nodeId: string
  versionId: string
  deleted?: boolean
  workflowVersion?: number
  txId?: string
  seq?: number
  revision?: number
  baseRevision?: number
  opType?: string
  records?: CanvasMutationRecords
  projection?: Record<string, unknown>
  changedResources?: string[]
}

export async function saveWorkflowNodeInlineEdit(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    nodeId: string
    data?: Record<string, unknown>
    generationConfig?: Record<string, unknown>
    source?: string
    reason?: string
    returnProductionStatus?: boolean
    return_production_status?: boolean
  }
): Promise<WorkflowNodeInlineEditResult> {
  const returnProductionStatus =
    payload.returnProductionStatus ?? payload.return_production_status ?? false
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowNodeInlineEditResult>>(
      "save_workflow_node_inline_edit",
      {
        projectId,
        episodeId,
        ...canvasMutationPayload(payload),
        returnProductionStatus,
      }
    )
  )
}

export async function updateWorkflowNodeLayout(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    nodeId: string
    position?: { x: number; y: number }
    size?: Record<string, unknown>
    cardSize?: Record<string, unknown>
    reason?: string
  }
): Promise<WorkflowNodeLayoutResult> {
  return ensureSuccess(
    await callBackend<BackendResult<WorkflowNodeLayoutResult>>(
      "update_workflow_node_layout",
      {
        projectId,
        episodeId,
        ...canvasMutationPayload(payload),
      }
    )
  )
}

export async function listNodeEditHistory(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  nodeId: string
): Promise<NodeEditHistoryListResult> {
  return ensureSuccess(
    await callBackend<BackendResult<NodeEditHistoryListResult>>(
      "list_node_edit_history",
      { projectId, episodeId, nodeId }
    )
  )
}

export async function restoreNodeEditHistory(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    nodeId: string
    versionId: string
  }
): Promise<NodeEditHistoryRestoreResult> {
  return ensureSuccess(
    await callBackend<BackendResult<NodeEditHistoryRestoreResult>>(
      "restore_node_edit_history",
      {
        projectId,
        episodeId,
        ...payload,
      }
    )
  )
}

export async function deleteNodeEditHistory(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    nodeId: string
    versionId: string
  }
): Promise<NodeEditHistoryDeleteResult> {
  return ensureSuccess(
    await callBackend<BackendResult<NodeEditHistoryDeleteResult>>(
      "delete_node_edit_history",
      {
        projectId,
        episodeId,
        ...payload,
      }
    )
  )
}

export async function getEpisodeProductionStatus(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string
): Promise<EpisodeProductionStatus> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{ success: true; status: EpisodeProductionStatus }>
    >("get_episode_production_status", { projectId, episodeId })
  )
  return result.status
}

export async function listModelCapabilities(
  callBackend: BackendCaller,
  projectId: string,
  episodeId?: string,
  payload: {
    mediaType?: "image" | "video"
    status?: "all" | "adapted" | "unadapted"
  } = {}
): Promise<ModelCapabilitiesSnapshot> {
  return ensureSuccess(
    await callBackend<BackendResult<ModelCapabilitiesSnapshot>>(
      "list_models",
      {
        projectId,
        episodeId,
        ...payload,
      }
    )
  )
}

export async function resolveGenerationConfig(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    routeId?: string
    nodeId?: string
    nodeType?: string
    mediaType?: "image" | "video"
    strategy?: string
    referenceMediaIds?: string[]
    generationConfig?: Record<string, unknown>
  }
): Promise<GenerationConfigCheck> {
  const result = await callBackend<BackendResult<GenerationConfigCheck>>(
    "resolve_generation_config",
    {
      projectId,
      episodeId,
      ...payload,
    }
  )
  if (
    result &&
    typeof result === "object" &&
    "success" in result &&
    result.success === false &&
    ("blockingIssues" in result || "resolvedConfig" in result)
  ) {
    return result as GenerationConfigCheck
  }
  return ensureSuccess(result)
}

export async function preflightWorkflowNode(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    routeId?: string
    nodeId: string
    nodeType?: string
    mediaType?: "image" | "video"
    strategy?: string
    referenceMediaIds?: string[]
    generationConfig?: Record<string, unknown>
    reason?: string
    writeBack?: boolean
    write_back?: boolean
    commitPreflight?: boolean
    commit_preflight?: boolean
    persistPreflight?: boolean
    persist_preflight?: boolean
    returnProductionStatus?: boolean
    return_production_status?: boolean
  }
): Promise<WorkflowPreflightResult> {
  const returnProductionStatus =
    payload.returnProductionStatus ?? payload.return_production_status ?? false
  const result = await callBackend<BackendResult<WorkflowPreflightResult>>(
    "preflight_workflow_node",
    {
      projectId,
      episodeId,
      ...canvasMutationPayload(payload),
      returnProductionStatus,
    }
  )
  if (
    result &&
    typeof result === "object" &&
    "success" in result &&
    result.success === false &&
    ("blockingIssues" in result || "preflight" in result)
  ) {
    return result as WorkflowPreflightResult
  }
  return ensureSuccess(result)
}

export async function runNodeGeneration(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  node: WorkflowNode
): Promise<TaskRow> {
  if (!["video.storyboard", "video.keyframe", "video.character_replace"].includes(node.type)) {
    throw new Error("该节点不是可执行任务卡")
  }
  const method = "generate_route_video"
  const routeId = node.routeId ?? node.data.routeId
  const workChainId = node.workChainId
  const segmentId = node.segmentId ?? node.data.segmentId
  const videoTaskScope = workChainId ? "work_chain" : "standalone"
  const standaloneVideoTask = videoTaskScope === "standalone"
  const keyframeVideoTask = node.type === "video.keyframe"
  const standaloneInputMode = node.type === "video.character_replace" ? "character_replace" : keyframeVideoTask ? "native_keyframe" : "image_reference"
  const standaloneStrategy = `${standaloneInputMode}_video`
  const generationConfig = standaloneVideoTask
    ? {
        ...(node.data.generationConfig ?? {}),
        strategy: standaloneStrategy,
        videoInputMode: standaloneInputMode,
        inputMode: standaloneInputMode,
        referenceMode: standaloneInputMode,
      }
    : node.data.generationConfig
  const payload = withCanvasTaskClientRequestId(
    method,
    projectId,
    episodeId,
    node.id,
    {
      nodeId: node.id,
      nodeType: node.type,
      routeId,
      workChainId,
      segmentId,
      strategy: standaloneVideoTask
        ? standaloneStrategy
        : node.strategy ?? node.data.strategy,
      videoTaskScope: videoTaskScope || undefined,
      videoInputMode: standaloneVideoTask ? standaloneInputMode : undefined,
      referenceMode: standaloneVideoTask ? standaloneInputMode : undefined,
      storyboardTemplate:
        node.storyboardTemplate ?? node.data.storyboardTemplate,
      storyboardTemplateLabel:
        node.storyboardTemplateLabel ?? node.data.storyboardTemplateLabel,
      title: node.data.title,
      summary: node.data.summary,
      prompt: node.data.prompt,
      videoTaskCard: node.data.videoTaskCard,
      directorPlan: node.data.directorPlan,
      directorTaskCard: node.data.directorTaskCard,
      screenplay: node.data.screenplay,
      dialogue: node.data.dialogue,
      assetRefs: node.data.assetRefs,
      quality: node.data.quality,
      generationConfig,
      resolvedConfig: node.data.resolvedConfig,
      durationSeconds: node.data.durationSeconds,
      referenceMediaIds: node.data.referenceMediaIds,
      submitRealProvider: true,
    }
  )
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; task: TaskRow }>>(method, {
      projectId,
      episodeId,
      ...payload,
    })
  )
  return result.task
}

export async function generateStoryboardImage(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  node: WorkflowNode
): Promise<TaskRow> {
  if (node.type !== "director.board" && node.type !== "storyboard.image") {
    throw new Error("请选择分镜脚本或已分配的分镜图")
  }
  const routeId = node.routeId ?? node.data.routeId
  const segmentId = node.segmentId ?? node.data.segmentId
  const payload = withCanvasTaskClientRequestId(
    "generate_storyboard_image",
    projectId,
    episodeId,
    node.id,
    {
      nodeId: node.id,
      nodeType: node.type,
      routeId,
      segmentId,
      strategy: node.strategy ?? node.data.strategy,
      storyboardTemplate:
        node.storyboardTemplate ?? node.data.storyboardTemplate,
      storyboardTemplateLabel:
        node.storyboardTemplateLabel ?? node.data.storyboardTemplateLabel,
      title: node.data.title,
      summary: node.data.summary,
      prompt: node.data.prompt,
      directorPlan: node.data.directorPlan,
      directorTaskCard: node.data.directorTaskCard,
      screenplay: node.data.screenplay,
      dialogue: node.data.dialogue,
      assetRefs: node.data.assetRefs,
      quality: node.data.quality,
      referenceMediaIds: node.data.referenceMediaIds,
      submitRealProvider: false,
    }
  )
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; task: TaskRow }>>(
      "generate_storyboard_image",
      {
        projectId,
        episodeId,
        ...payload,
      }
    )
  )
  return result.task
}

export async function generateVisualHandoffImage(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  node: WorkflowNode
): Promise<TaskRow> {
  if (node.type !== "storyboard.image" || !node.data.shotGroupId) {
    throw new Error("请选择已分配的分镜单元生成视觉交接图")
  }
  const routeId = node.routeId ?? node.data.routeId
  const segmentId = node.segmentId ?? node.data.segmentId
  const payload = withCanvasTaskClientRequestId(
    "generate_visual_handoff_image",
    projectId,
    episodeId,
    node.id,
    {
      nodeId: node.id,
      nodeType: node.type,
      routeId,
      segmentId,
      strategy: node.strategy ?? node.data.strategy,
      storyboardTemplate:
        node.storyboardTemplate ?? node.data.storyboardTemplate,
      storyboardTemplateLabel:
        node.storyboardTemplateLabel ?? node.data.storyboardTemplateLabel,
      title: node.data.title,
      summary: node.data.summary,
      prompt: node.data.prompt,
      directorPlan: node.data.directorPlan,
      directorTaskCard: node.data.directorTaskCard,
      screenplay: node.data.screenplay,
      dialogue: node.data.dialogue,
      assetRefs: node.data.assetRefs,
      quality: node.data.quality,
      referenceMediaIds: node.data.referenceMediaIds,
    }
  )
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; task: TaskRow }>>(
      "generate_visual_handoff_image",
      {
        projectId,
        episodeId,
        ...payload,
      }
    )
  )
  return result.task
}

export async function runWorkflowFromNode(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  nodeId: string
): Promise<TaskRow> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; task: TaskRow }>>(
      "run_workflow_from_node",
      {
        projectId,
        episodeId,
        ...withCanvasTaskClientRequestId(
          "run_workflow_from_node",
          projectId,
          episodeId,
          nodeId,
          { nodeId }
        ),
      }
    )
  )
  return result.task
}

export async function listStoryboardVersions(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  nodeId: string
): Promise<StoryboardVersion[]> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ versions: StoryboardVersion[] }>>(
      "list_storyboard_versions",
      { projectId, episodeId, nodeId }
    )
  )
  return result.versions
}

export async function setStoryboardResultActiveVersion(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    nodeId: string
    versionId: string
    resultNodeId?: string
    result_node_id?: string
  }
): Promise<{
  success: true
  episodeId?: string
  nodeId?: string
  resultNodeId?: string
  version?: StoryboardVersion
  workflowVersion?: number | Record<string, unknown>
  changedResources?: string[]
}> {
  return ensureSuccess(
    await callBackend<
      BackendResult<{
        success: true
        episodeId?: string
        nodeId?: string
        resultNodeId?: string
        version?: StoryboardVersion
        workflowVersion?: number | Record<string, unknown>
        changedResources?: string[]
      }>
    >("set_storyboard_result_active_version", {
      projectId,
      episodeId,
      ...payload,
      resultNodeId: payload.resultNodeId ?? payload.result_node_id,
    })
  )
}

export async function uploadStoryboardImage(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    nodeId: string
    file: InputImageFile
    title?: string
    returnProductionStatus?: boolean
    return_production_status?: boolean
  }
): Promise<{
  success: true
  episodeId: string
  nodeId: string
  version?: StoryboardVersion
  workflowVersion?: number | Record<string, unknown>
  productionStatus?: EpisodeProductionStatus | null
  changedResources?: string[]
}> {
  const returnProductionStatus =
    payload.returnProductionStatus ?? payload.return_production_status ?? false
  return ensureSuccess(
    await callBackend<
      BackendResult<{
        success: true
        episodeId: string
        nodeId: string
        version?: StoryboardVersion
        workflowVersion?: number | Record<string, unknown>
        productionStatus?: EpisodeProductionStatus | null
        changedResources?: string[]
      }>
    >("upload_storyboard_image", {
      projectId,
      episodeId,
      ...canvasMutationPayload(payload),
      returnProductionStatus,
    })
  )
}

export async function editStoryboardImage(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    nodeId: string
    storyboardTemplate?: string
    useOriginal?: boolean
    hideTurnaroundHeads?: boolean
    useProjectVisual?: boolean
    prompt?: string
    baseVersionId?: string | null
    assetType?: AssetType | string
    asset_type?: AssetType | string
    assetName?: string
    asset_name?: string
    modelId?: string
    model_id?: string
    providerId?: string
    provider_id?: string
    resolution?: string
    size?: string
    resolvedConfig?: Record<string, unknown>
    resolved_config?: Record<string, unknown>
    generationConfig?: Record<string, unknown>
    generation_config?: Record<string, unknown>
    allowGenerationConfigOverride?: boolean
    allow_generation_config_override?: boolean
    referenceFiles?: InputImageFile[]
    returnProductionStatus?: boolean
    return_production_status?: boolean
  }
): Promise<{
  success: true
  episodeId: string
  nodeId: string
  requestedNodeId?: string
  version?: StoryboardVersion
  media?: MediaAsset
  task?: TaskRow
  workflowVersion?: number | Record<string, unknown>
  productionStatus?: EpisodeProductionStatus | null
  changedResources?: string[]
}> {
  const returnProductionStatus =
    payload.returnProductionStatus ?? payload.return_production_status ?? false
  return ensureSuccess(
    await callBackend<
      BackendResult<{
        success: true
        episodeId: string
        nodeId: string
        requestedNodeId?: string
        version?: StoryboardVersion
        media?: MediaAsset
        task?: TaskRow
        workflowVersion?: number | Record<string, unknown>
        productionStatus?: EpisodeProductionStatus | null
        changedResources?: string[]
      }>
    >("edit_storyboard_image", {
      projectId,
      episodeId,
      ...canvasMutationPayload(payload),
      returnProductionStatus,
    })
  )
}

export async function selectWorkflowVariant(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    nodeId: string
    versionId: string
    reason?: string
    returnProductionStatus?: boolean
    return_production_status?: boolean
  }
): Promise<{
  success: true
  workflowVersion?: number | Record<string, unknown>
  version?: StoryboardVersion
  node?: WorkflowNode
  nodes?: WorkflowNode[]
  productionStatus?: EpisodeProductionStatus | null
  changedResources?: string[]
}> {
  const returnProductionStatus =
    payload.returnProductionStatus ?? payload.return_production_status ?? false
  return ensureSuccess(
    await callBackend<
      BackendResult<{
        success: true
        workflowVersion?: number | Record<string, unknown>
        version?: StoryboardVersion
        node?: WorkflowNode
        nodes?: WorkflowNode[]
        productionStatus?: EpisodeProductionStatus | null
        changedResources?: string[]
      }>
    >("select_workflow_variant", {
      projectId,
      episodeId,
      ...canvasMutationPayload(payload),
      returnProductionStatus,
    })
  )
}

export async function deleteStoryboardVersion(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  nodeId: string,
  versionId: string
): Promise<{
  success: true
  episodeId?: string
  nodeId?: string
  versionId?: string
  nodes?: WorkflowNode[]
  workflowVersion?: number | Record<string, unknown>
  txId?: string
  seq?: number
  revision?: number
  baseRevision?: number
  opType?: string
  records?: CanvasMutationRecords
  changedResources?: string[]
}> {
  return ensureSuccess(
    await callBackend<
      BackendResult<{
        success: true
        episodeId?: string
        nodeId?: string
        versionId?: string
        nodes?: WorkflowNode[]
        workflowVersion?: number | Record<string, unknown>
        txId?: string
        seq?: number
        revision?: number
        baseRevision?: number
        opType?: string
        records?: CanvasMutationRecords
        changedResources?: string[]
      }>
    >(
      "delete_storyboard_version",
      { projectId, episodeId, nodeId, versionId }
    )
  )
}

export async function diagnoseStoryboardTask(
  callBackend: BackendCaller,
  taskId: string
): Promise<{ level: string; message: string; createdAt: string }> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{
        success: true
        diagnosis: { level: string; message: string; createdAt: string }
      }>
    >("diagnose_storyboard_task", { taskId })
  )
  return result.diagnosis
}

export async function listTasks(
  callBackend: BackendCaller,
  options: ListTasksOptions = {}
): Promise<TaskRow[]> {
  const payload = {
    compact: true,
    ...options,
  }
  const result = ensureSuccess(
    await callBackend<BackendResult<{ tasks: TaskRow[] }>>(
      "list_tasks",
      payload
    )
  )
  return result.tasks
}

export async function clearTaskNotifications(
  callBackend: BackendCaller,
  projectId: string
): Promise<{ cleared: number }> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; cleared: number }>>(
      "clear_task_notifications",
      { projectId }
    )
  )
  return { cleared: result.cleared ?? 0 }
}

export async function listWorkflowTasks(
  callBackend: BackendCaller,
  projectId: string,
  episodeId: string,
  payload: {
    routeId?: string
    nodeId?: string
    status?: string
    lightweight?: boolean
    compact?: boolean
    summary?: boolean
  } = {}
): Promise<{ tasks: TaskRow[]; costSummary?: WorkflowTaskCostSummary }> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{
        success: true
        tasks: TaskRow[]
        costSummary?: WorkflowTaskCostSummary
      }>
    >("list_workflow_tasks", {
      projectId,
      episodeId,
      lightweight: true,
      ...payload,
    })
  )
  return { tasks: result.tasks, costSummary: result.costSummary }
}



export async function cancelTask(
  callBackend: BackendCaller,
  taskId: string
): Promise<TaskRow> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; task: TaskRow }>>(
      "cancel_task",
      { taskId }
    )
  )
  return result.task
}

export async function getUsageSummary(
  callBackend: BackendCaller
): Promise<UsageSummary> {
  return ensureSuccess(
    await callBackend<BackendResult<UsageSummary>>("get_usage_summary")
  )
}

export async function exportProjectAssets(
  callBackend: BackendCaller,
  projectId: string,
  scopes: ExportScope[] = [
    "sources",
    "assets",
    "storyboard_image",
    "final_video",
  ]
): Promise<TaskRow> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; task: TaskRow }>>(
      "export_project_assets",
      { projectId, scopes }
    )
  )
  return result.task
}

export async function startHomeArchiveExport(
  callBackend: BackendCaller,
  payload: {
    projectIds: string[]
    globalScopes: HomeGlobalExportScope[]
    assetScopes?: HomeAssetExportScope[]
    exportPath: string
  }
): Promise<{ task: TaskRow; exportPath: string }> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{ success: true; task: TaskRow; exportPath: string }>
    >("start_home_archive_export", payload)
  )
  return { task: result.task, exportPath: result.exportPath }
}

export async function startHomeArchiveImport(
  callBackend: BackendCaller,
  payload: {
    archivePath: string
    conflictPolicy: "rename" | "skip" | "overwrite"
  }
): Promise<{ task: TaskRow; archivePath: string }> {
  const result = ensureSuccess(
    await callBackend<
      BackendResult<{ success: true; task: TaskRow; archivePath: string }>
    >("start_home_archive_import", payload)
  )
  return { task: result.task, archivePath: result.archivePath }
}

export async function getJianyingExportInfo(
  callBackend: BackendCaller,
  projectId: string
): Promise<JianyingExportInfo> {
  return ensureSuccess(
    await callBackend<BackendResult<JianyingExportInfo>>(
      "get_jianying_export_info",
      { projectId }
    )
  )
}

export async function detectJianyingDraftRoot(
  callBackend: BackendCaller
): Promise<string> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; path: string }>>(
      "detect_jianying_draft_root"
    )
  )
  return result.path
}

export async function startJianyingDraftExport(
  callBackend: BackendCaller,
  payload: {
    projectId: string
    sourceMode?: "work_chain" | "custom"
    episodeIds?: string[]
    customCanvasIds?: string[]
    draftPath: string
    jianyingVersion?: string
    clipEdits?: Array<{
      canvasId: string
      nodeId: string
      versionId: string
      inSec: number
      outSec: number
    }>
  }
): Promise<TaskRow> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; task: TaskRow }>>(
      "start_jianying_draft_export",
      payload
    )
  )
  return result.task
}

export async function startVideoFilesExport(
  callBackend: BackendCaller,
  payload: {
    projectId: string
    sourceMode?: "work_chain" | "custom"
    episodeIds?: string[]
    customCanvasIds?: string[]
    destinationPath: string
  }
): Promise<TaskRow> {
  const result = ensureSuccess(
    await callBackend<BackendResult<{ success: true; task: TaskRow }>>(
      "start_video_files_export",
      payload
    )
  )
  return result.task
}
