import type { ImageResolutionSchema } from "@/utils/model-resolution"
import type { VideoCapabilityMetadata } from "@/utils/video-model-capabilities"
import type { ModelAvailability } from "@/shared/model-availability"
import type {
  AssetType,
  InputImageFile,
  MediaAsset,
  StoryboardVersion,
  TaskRow,
} from "@/backend"

export type WorkflowNodeStatus =
  | "ready"
  | "draft"
  | "waiting"
  | "waiting_upstream"
  | "running"
  | "processing"
  | "blocked"
  | "preflight_failed"
  | "queued"
  | "cancelled"
  | "input_dirty"
  | "succeeded"
  | "failed"

export type GenerationStrategy =
  | "storyboard_multi_shot"
  | "single_image_to_video"
  | "text_to_video_draft"
  | "manual"
  | string

export type StoryboardTemplateId =
  | "narrative_storyboard"
  | "blocking_storyboard"
  | "image_grid_storyboard"
  | "numbered_grid_storyboard"
  | "filmstrip_storyboard"
  | string

export type WorkflowRoute = {
  id: string
  label?: string
  workChainId?: string
  segmentId?: string
  strategy?: GenerationStrategy
  storyboardTemplate?: StoryboardTemplateId
  storyboardTemplateLabel?: string
  status?: WorkflowNodeStatus | string
  shotIds?: string[]
  shotCount?: number
  laneIndex?: number
  locked?: boolean
  lockedByUser?: boolean
  preserveOnReplan?: boolean
  lockedReason?: string
  modelRequirements?: Record<string, unknown>
  generationConfig?: Record<string, unknown>
  quality?: Record<string, unknown>
}

export type WorkflowWorkChain = {
  id: string
  origin:
    | { kind: "source_split"; sourceNodeId: string }
    | { kind: "independent_source"; sourceNodeId: string }
    | { kind: "independent"; sourceNodeId: null }
  label?: string
  title?: string
  continuity?: string
  segmentIds?: string[]
  shotIds?: string[]
  routeIds?: string[]
  order?: number
  layout?: Record<string, unknown>
  status?: WorkflowNodeStatus | string
  locked?: boolean
  lockedByUser?: boolean
  preserveOnReplan?: boolean
  lockedReason?: string
}

export type ProjectPlanningSummary = {
  success: true
  projectId: string
  episodeId: string
  storyWorld: {
    ready: boolean
    updatedAt?: string | null
    summary?: string
    counts: {
      characters: number
      creatures: number
      scenes: number
      props: number
    }
  }
  boundaryPlan: {
    ready: boolean
    updatedAt?: string | null
    summary?: string
    candidateCount: number
  }
  workChainPlan: {
    ready: boolean
    updatedAt?: string | null
    summary?: string
    segmentCount: number
    shotCount: number
  }
  workflow: {
    ready: boolean
    routeCount: number
    nodeCount: number
    edgeCount: number
    lockedRouteCount: number
    lockedNodeCount: number
    versionCount: number
  }
}

export type GenerationConfigCheck = {
  success: boolean
  projectId: string
  episodeId: string
  routeId?: string
  nodeId?: string
  mediaType: string
  strategy: string
  resolvedConfig: Record<string, unknown>
  route?: Record<string, unknown>
  node?: Record<string, unknown>
  model?: Record<string, unknown> | null
  warnings: string[]
  blockingIssues: string[]
  qualityGates?: Record<string, unknown>
}

export type WorkflowSlotSchema = {
  id: string
  label?: string
  required?: boolean
  cardinality?: "one" | "many" | string
}

export type WorkflowModelCapability = VideoCapabilityMetadata & ModelAvailability & {
  id?: string
  label?: string
  type?: "image" | "video" | string
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
  providerId?: string
  providerPresetId?: string
  adapterId?: string
  endpoint?: string
  defaultResolution?: string
  resolutions?: string[]
  providerResolutions?: string[]
  image_resolution_schema?: ImageResolutionSchema
  imageResolutionSchema?: ImageResolutionSchema
  resolutionLabels?: Record<string, string>
  resolutionDescriptions?: Record<string, Record<string, string>>
  resolution_descriptions?: Record<string, Record<string, string>>
  durations?: Array<number | string>
  aspectRatios?: string[]
  maxReferenceImages?: number
  referenceImageLimitSource?: string
  referenceImageLimitSourceUrl?: string
  referenceImageLimitNote?: string
  supports?: Record<string, unknown>
  rawSupports?: string[]
}

export type ModelCapabilitiesSnapshot = {
  success: true
  projectId: string
  episodeId?: string | null
  modelConfig: Record<string, unknown>
  modelOptions: Record<string, unknown>
  models: Partial<Record<"image" | "video", WorkflowModelCapability[]>>
  slotSchema: Partial<Record<"image" | "video", WorkflowSlotSchema[]>>
}

export type WorkflowNode = {
  id: string
  type: string
  workChainId?: string
  routeId?: string
  segmentId?: string
  strategy?: GenerationStrategy
  storyboardTemplate?: StoryboardTemplateId
  storyboardTemplateLabel?: string
  locked?: boolean
  lockedByUser?: boolean
  preserveOnReplan?: boolean
  lockedReason?: string
  position: {
    x: number
    y: number
  }
  data: {
    // Client-only draft state; creation requests send IDs and position, not this data.
    creationPending?: boolean
    nodeId?: string
    title: string
    episodeTitle?: string
    eyebrow?: string
    status: WorkflowNodeStatus
    summary?: string
    model?: string
    activeVersionId?: string | null
    sourceVersionId?: string | null
    activeMediaVersionId?: string | null
    winnerVersionId?: string | null
    selectionReason?: string | null
    selectedAt?: string | null
    variantSelection?: Record<string, unknown>
    taskId?: string
    metric?: string
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
    segmentId?: string
    strategy?: GenerationStrategy
    storyboardTemplate?: StoryboardTemplateId
    storyboardTemplateLabel?: string
    locked?: boolean
    lockedByUser?: boolean
    preserveOnReplan?: boolean
    lockedReason?: string | null
    durationSeconds?: number | string | null
    sourceFactText?: string
    source_fact_text?: string
    cinematicStoryText?: string
    cinematic_story_text?: string
    content?: string
    prompt?: string | Record<string, unknown>
    prompts?: Record<string, unknown>
    scriptTemplateId?: string
    script_template_id?: string
    scriptTemplateLabel?: string
    script_template_label?: string
    scriptUserInstruction?: string
    script_user_instruction?: string
    scriptTemplateRecommendation?: Record<string, unknown>
    script_template_recommendation?: Record<string, unknown>
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
    directorTaskCard?: Record<string, unknown>
    directorRuleOptions?: Array<Record<string, unknown>>
    voiceStyle?: string
    sourceText?: string
    sourceMode?: "independent"
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
    storyboardTaskCard?: Record<string, unknown>
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
    referenceMediaIds?: string[]
    cardState?: Record<string, unknown>
    visibilityScope?: "node" | "route" | "workChain" | "global" | string
    sourceType?: "asset" | "media" | "version" | string
    canvasNodeRole?: "work_chain_storyboard_result" | "image_asset" | string
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
    sourceFileName?: string
    mediaPurpose?: string
    useProjectVisual?: boolean
    preferredTargetSlot?: string
    width?: number
    height?: number
    aspectRatio?: string
    copiedFromNodeId?: string
    provenance?: Record<string, unknown>
  }
}

export type WorkflowEdge = {
  id: string
  source: string
  target: string
  sourceHandle?: string
  targetHandle?: string
  locked?: boolean
  lockedByUser?: boolean
  preserveOnReplan?: boolean
  lockedReason?: string
  deletable?: boolean
  data?: {
    kind?: "material" | "dependency" | string
    role?: string
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
}

export type EpisodeWorkflow = {
  canvasKind?: "work_chain" | "custom"
  autoWorkflowInitialized?: boolean
  episodeId: string
  schemaVersion?: number
  version: number
  viewport: {
    x: number
    y: number
    zoom: number
  }
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  workChains?: WorkflowWorkChain[]
  routes?: WorkflowRoute[]
  productionStatus?: EpisodeProductionStatus | null
  build?: Record<string, unknown>
  state?: {
    kind?: "ready" | "empty" | string
    reason?: string
    sourceReady?: boolean
    workChainPlanReady?: boolean
    workflowChainReady?: boolean
    nextAction?: string
  }
}

export type CanvasChangeRecord = {
  txId: string
  seq?: number
  opType: string
  baseRevision: number
  revision: number
  records?: CanvasMutationRecords
  changedResources?: string[]
  payload?: Record<string, unknown>
  createdAt?: string
}

export type CanvasRecordRef = {
  type: string
  id: string
  nodeId?: string
  active?: boolean
  [key: string]: unknown
}

export type CanvasVersionRef = {
  nodeId: string
  versionId: string
}

export type CanvasMutationRecords = {
  added?: CanvasRecordRef[]
  updated?: CanvasRecordRef[]
  removed?: CanvasRecordRef[]
}

export type CanvasRecordPayload = {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  routes: WorkflowRoute[]
  workChains: WorkflowWorkChain[]
  versions: Record<string, unknown>[]
  tasks: Record<string, unknown>[]
  projections: Record<string, unknown>[]
}

export type CanvasDocumentRecord = {
  canvasKind?: "work_chain" | "custom"
  autoWorkflowInitialized?: boolean
  episodeId: string
  schemaVersion: number
  revision: number
  currentRevision?: number
  viewport?: EpisodeWorkflow["viewport"]
  state?: EpisodeWorkflow["state"] & Record<string, unknown>
  productionStatus?: EpisodeProductionStatus | null
  build?: Record<string, unknown>
  updatedAt?: string | null
}

export type CanvasChangesResult = {
  success: true
  episodeId: string
  currentRevision: number
  snapshotRequired?: boolean
  changes: CanvasChangeRecord[]
  records?: Partial<CanvasRecordPayload>
  nodes?: WorkflowNode[]
}

export type CanvasSnapshotResult = {
  success: true
  productionStatusNeedsRefresh?: boolean
  productionStatusRefreshFailed?: boolean
  productionStatusWarning?: string
  episodeId: string
  schemaVersion: number
  revision: number
  currentRevision: number
  detail: "full" | "summary"
  document: CanvasDocumentRecord
  records: CanvasRecordPayload
}

export type CanvasRecordsResult = {
  success: true
  episodeId: string
  currentRevision: number
  detail: "full" | "summary"
  records: Partial<CanvasRecordPayload>
}

export type CustomCanvasEntry = {
  canvasId: string
  kind: "custom"
  title: string
  storageKey: string
  sortIndex: number
  createdAt?: string
  updatedAt?: string
}

export type WorkflowPreflightResult = GenerationConfigCheck & {
  preflight?: Record<string, unknown>
  workflowVersion?: number
  changedResources?: string[]
  writeBack?: boolean
  projectChanged?: boolean
}

export type EpisodeProductionStep = {
  id: string
  label?: string
  completed?: boolean
  skipped?: boolean
  status?: "completed" | "current" | "pending" | "blocked" | "skipped" | string
  blockers?: Array<Record<string, unknown>>
  warnings?: Array<Record<string, unknown>>
  blockerCount?: number
  warningCount?: number
  routeStatuses?: Array<Record<string, unknown>>
  nextAction?: string
}

export type EpisodeProductionRouteState = {
  routeId?: string | null
  workChainId?: string | null
  segmentId?: string | null
  strategy?: string
  completedStates?: string[]
  skippedStates?: string[]
  blockedStates?: string[]
  completedPreconditions?: string[]
  skippedPreconditions?: string[]
  blockedPreconditions?: string[]
  blockedBy?: Array<Record<string, unknown>>
}

export type EpisodeProductionStatus = {
  independentWorkChains?: Record<string, EpisodeProductionStatus>
  schemaVersion?: number
  projectId?: string
  episodeId: string
  currentState?: string
  nextAction?: string
  overallStatus?: "in_progress" | "blocked" | "ready" | string
  sourceReady?: boolean
  workflowReady?: boolean
  currentRouteId?: string | null
  currentWorkChainId?: string | null
  currentSegmentId?: string | null
  completedStates?: string[]
  skippedStates?: string[]
  completedPreconditions?: string[]
  skippedPreconditions?: string[]
  blockedBy?: Array<Record<string, unknown>>
  routeStates?: EpisodeProductionRouteState[]
  routePreconditions?: EpisodeProductionRouteState[]
  progress?: {
    completed?: number
    total?: number
    percent?: number
  }
  preconditionProgress?: {
    completed?: number
    total?: number
    percent?: number
  }
  preconditions?: EpisodeProductionStep[]
  steps: EpisodeProductionStep[]
  updatedAt?: string
}

export type WorkflowMediaImportPayload = {
  file?: InputImageFile | null
  media?: Record<string, unknown> | null
  sourceType?: "asset" | "media" | "version" | string
  sourceId?: string
  mediaId?: string
  scope?: "node" | "route" | "workChain" | "global"
  visibilityScope?: "node" | "route" | "workChain" | "global"
  slot?: string
  targetSlot?: string
  mediaPurpose?: string
  media_purpose?: string
  preferredTargetSlot?: string
  preferred_target_slot?: string
  mediaKind?: "image" | "video" | string
  mediaNodeId?: string
  media_node_id?: string
  title?: string
  name?: string
  assetName?: string
  canvasNodeRole?: "work_chain_storyboard_result" | "image_asset" | string
  assetScope?: "reusable" | "result" | string
  assetKind?: string
  assetType?: AssetType | string
  asset_type?: AssetType | string
  rootAssetId?: string
  rootAssetType?: AssetType | string
  rootAssetProjectId?: string
  position?: { x: number; y: number }
  action?: "append" | "replace_slot" | "relink_slot"
  linkAction?: "append" | "replace_slot" | "relink_slot"
  locked?: boolean
  lockedByUser?: boolean
  note?: string
  voiceStyle?: string
  targetNodeId?: string
  nodeId?: string
  workChainId?: string
  routeId?: string
  segmentId?: string
  inputDirtyNodeIds?: string[]
  versionId?: string
  returnProductionStatus?: boolean
  return_production_status?: boolean
  includeProductionStatus?: boolean
  include_production_status?: boolean
}

export type WorkflowInputLinkPayload = WorkflowMediaImportPayload & {
  frameRole?: "first_frame" | "last_frame"
  useNativeFrame?: boolean
  linkId?: string
  label?: string
  sourceType?: "asset" | "media" | "version" | string
  source_id?: string
  sourceNodeId?: string
  source_node_id?: string
  sourceNodeType?: string
  sourceHandle?: string
  source_handle?: string
  targetNodeType?: string
  targetHandle?: string
  target_handle?: string
  target_node_id?: string
  role?: string
  status?: string
  required?: boolean
  createdBy?: string
  provenance?: Record<string, unknown>
  sourceVersionId?: string
  assetVersionId?: string
  mediaVersionId?: string
  versionBinding?: Record<string, unknown> | string
  assetId?: string
  asset_id?: string
  assetType?: string
  asset_type?: string
  rootAssetId?: string
  rootAssetType?: string
  rootAssetProjectId?: string
  mediaId?: string
  media_id?: string
  mediaKind?: string
  mediaType?: string
  path?: string
}

export type WorkflowInputLinkResult = {
  success: true
  episodeId: string
  skippedLocked?: boolean
  message?: string
  projectChanged?: boolean
  inputLink?: Record<string, unknown>
  removedLinks?: Array<Record<string, unknown>>
  removedLinkIds?: string[]
  removedEdgeIds?: string[]
  inputDirtyNodeIds?: string[]
  syncedVideoTaskNodeIds?: string[]
  targetNodeId?: string
  node?: WorkflowNode
  nodes?: WorkflowNode[]
  edge?: WorkflowEdge
  inputs?: Array<Record<string, unknown>>
  workflowVersion?: number
  productionStatus?: EpisodeProductionStatus | null
  changedResources?: string[]
}

export type WorkflowNodeInputsResult = {
  success: true
  episodeId: string
  nodeId: string
  routeId?: string
  segmentId?: string
  inputs: Array<Record<string, unknown>>
  inputLinks: Array<Record<string, unknown>>
  groupedBySlot?: Record<string, Array<Record<string, unknown>>>
  referenceMediaIds?: string[]
  assetRefs?: Array<Record<string, unknown>>
  needsRelink?: Array<Record<string, unknown>>
}

export type WorkflowBatchResult = {
  success: true
  episodeId: string
  nodeId: string
  batchId: string
  task?: TaskRow
  versions: StoryboardVersion[]
  workflowVersion?: number | Record<string, unknown>
  productionStatus?: EpisodeProductionStatus | null
  changedResources?: string[]
}

export type WorkflowMutationResult = {
  success: true
  episodeId: string
  workflow: EpisodeWorkflow
  workflowVersion?: number | Record<string, unknown>
  productionStatus?: EpisodeProductionStatus | null
  changedResources?: string[]
}

export type VariantQualityResultPayload = {
  nodeId: string
  versionId: string
  status: "passed" | "blocked" | "failed" | "waived" | string
  score?: number
  blockers?: string[]
  warnings?: string[]
  waived?: boolean
  waiverReason?: string
  note?: string
  source?: string
  returnProductionStatus?: boolean
  return_production_status?: boolean
}

export type VariantQualityResultResponse = {
  success: true
  episodeId: string
  qualityResult: Record<string, unknown>
  version?: StoryboardVersion
  workflowVersion?: number | Record<string, unknown>
  productionStatus?: EpisodeProductionStatus | null
  changedResources?: string[]
}

export type WorkflowExternalMediaImportResult = {
  success: true
  episodeId: string
  media?: MediaAsset | Record<string, unknown>
  mediaRecord?: Record<string, unknown>
  mediaNode?: WorkflowNode | Record<string, unknown>
  inputLink?: Record<string, unknown>
  workflowMedia?: Record<string, unknown>
  workflowVersion?: number | Record<string, unknown>
  productionStatus?: EpisodeProductionStatus | null
  changedResources?: string[]
}

export type ClipboardImageMediaResult = {
  success: true
  projectId?: string
  episodeId?: string
  file: InputImageFile
  media: MediaAsset
}

export type VideoClipInfoResult = {
  success: true
  projectId?: string
  episodeId?: string
  source?: Record<string, unknown>
  sourceKey?: string
  sourcePath?: string
  duration: number
  width?: number
  height?: number
  fps?: number
  frameCount?: number
  lastFrameIndex?: number
  mimeType?: string
  name?: string
  results?: VideoClipResultItem[]
}

export type VideoClipResultItem = {
  id: string
  kind: "image" | "video"
  title: string
  media: MediaAsset
  sourceKey?: string
  time?: number
  frameIndex?: number
  start?: number
  end?: number
  duration?: number
  crop?: {
    x: number
    y: number
    width: number
    height: number
  }
  createdAt?: string
  updatedAt?: string
}

export type VideoClipResultsListResult = {
  success: true
  projectId?: string
  episodeId?: string
  source?: Record<string, unknown>
  sourceKey?: string
  results: VideoClipResultItem[]
}

export type VideoClipDeleteResultsResult = VideoClipResultsListResult & {
  deletedIds: string[]
}

export type VideoClipMediaResult = {
  success: true
  projectId?: string
  episodeId?: string
  time?: number
  frameIndex?: number
  start?: number
  end?: number
  duration?: number
  crop?: {
    x: number
    y: number
    width: number
    height: number
  }
  media: MediaAsset
  result?: VideoClipResultItem
  warning?: string
}

export type WorkflowMediaRecord = Record<string, unknown> & {
  id?: string
  nodeId?: string
  media?: MediaAsset | null
  storage?: MediaAsset | null
}

export type WorkflowMediaListResult = {
  items: WorkflowMediaRecord[]
}
