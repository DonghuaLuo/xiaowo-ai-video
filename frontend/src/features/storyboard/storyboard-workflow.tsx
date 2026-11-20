import { useWorkflowCanvasEvents } from "./use-workflow-canvas-events"
import {
  buildWorkChainProgressSteps,
  buildWorkflowTaskResultRelationIndex,
  activeWorkflowTaskForCanvasNode,
  workflowNodeCanvasDisplayStatus,
  workflowNodeScriptContinuityReview,
  fallbackWorkflowNodeStatusAfterMissingTask,
  workflowVideoTaskPromptIsSyncing,
} from "./workflow-task-projection"
import { useWorkflowStructureActions } from "./use-workflow-structure-actions"
import { useWorkflowProjectAssets } from "./use-workflow-project-assets"
import { useWorkflowNodeEditing } from "./use-workflow-node-editing"
import { useWorkflowGenerationPreflight } from "./use-workflow-generation-preflight"
import { useWorkflowNodeGeneration } from "./use-workflow-node-generation"

import { useWorkflowCanvasDocument } from "./use-workflow-canvas-document"
import { useWorkflowDocumentSync } from "./use-workflow-document-sync"

import { useWorkflowMediaExchange } from "./use-workflow-media-exchange"
import { useWorkflowStageGeneration } from "./use-workflow-stage-generation"
import { useWorkflowTaskLifecycle } from "./use-workflow-task-lifecycle"
import { useWorkflowCanvasInputs } from "./use-workflow-canvas-inputs"
import { isWorkflowLockedSystemEdge } from "./workflow-node-relations"
import { useWorkflowAssetImports } from "./use-workflow-asset-imports"

import {
  useWorkflowAssetPersistence,
  type WorkflowAssetWriteback,
} from "./use-workflow-asset-persistence"
import { useWorkflowCanvasDetails } from "./use-workflow-canvas-details"
import { useWorkflowNodeLayout } from "./use-workflow-node-layout"
import { useWorkflowCanvasSelection } from "./use-workflow-canvas-selection"
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react"
import {
  AssetReferenceMenu,
  frameNativeConstraint,
  frameTransportSelection,
  supportsNativeFrame,
  type FrameReferenceOptions,
} from "./frame-reference-menu"
import {
  collectInlineAssetTags,
  inlineAssetDisplayRefs,
  inlineAssetDisplayRows,
  inlineAssetTagReferenceMatches,
  inlineAssetTagPrefix,
  inlineAssetTagStyle,
  type InlineAssetTag,
} from "./inline-asset-tags"
import { createStoryboardNodeTypes } from "./storyboard-node-card"
import { WorkflowCardConfig } from "./workflow-card-config"
import { DirectorWorkspaceDialog } from "./director-workspace-dialog"
import { createStoryboardPlanSaver } from "./storyboard-plan-saving"
import { StoryboardUnitShotEditor } from "./storyboard-unit-shot-editor"

import type { WorkflowAssetDialogProps } from "./workflow-asset-dialog"
import {
  isDefaultWorkChainVideoTaskNode,
  canOpenCanvasImageEditor,
  isWorkflowTaskCardType,
  mediaDetailRows,
  workflowNodeRect,
  workflowWorkChainDisplayName,
  type CanvasContextMenuState,
  type EdgeContextMenuState,
  type NodeContextMenuState,
  type NodeDetailsState,
  type WorkflowCanvasRect,
} from "./workflow-canvas-asset-model"

import {
  hasInlineTaskParameterPanel,
  isDirectorBoardNodeType,
  isStoryboardCardNodeType,
  isWorkflowItemLocked,
  isWorkflowVideoTaskType,
  recordValue,
  sourceTextForNode,
  toStoryboardEdges,
  toStoryboardNodes,
  toStoryboardNodesFromBackend,
  upsertStoryboardNodesLocally,
  workflowCanvasNodeInteractionState,
  workflowCardHeaderLocator,
  workflowCardTypeLabel,
  type ManualSaveOptions,
  type StoryboardEdge,
  type StoryboardNode,
  type WorkflowImageEditOptions,
  type WorkflowInlineEditPatch,
  type WorkflowNodeActions,
  type WorkflowNodeData,
} from "./workflow-canvas-model"
import type { WorkflowCanvasViewProps } from "./workflow-canvas-view"
import { WorkflowCanvasView } from "./workflow-canvas-view"
import { buildWorkflowNodeContextMenu } from "./workflow-context-menu-model"
import { uniqueStringValues } from "./workflow-edit-history-model"
import {
  WORKFLOW_FLOATING_EDITOR_WIDTH,
  workflowViewportBoundFloatingStyle,
} from "./workflow-floating-panel"
import { inputLinkMatchesDirectId } from "./workflow-input-readiness"
import { WorkflowMaximizedStoryboardReferenceGallery as ExtractedStoryboardGallery } from "./workflow-maximized-storyboard-gallery"
import {
  configPrivateStringValue,
  workflowSnapshotConfiguredModelId,
  workflowModelCapabilityId,
  workflowModelCapabilityLabel,
  workflowModelCapabilityRows,
} from "./workflow-model-capabilities"
import type { WorkflowNodeContextMenuActions } from "./workflow-node-context-menu"

import {
  RESULT_FRAME_SLOT_OPTIONS,
  compactWorkflowTextareaClassName,
  fixedWorkflowTextareaHeightStyle,
  resultFrameSlotFromNode,
  stopCardWheel,
} from "./workflow-prompt-node-model"
import { WorkflowTaskEditor as ExtractedWorkflowTaskEditor } from "./workflow-task-editor"
import {
  isStaleWorkflowNodeTaskStatus,
  withBackendReadTimeout,
} from "./workflow-task-status"

import type { VideoVisualInputCapabilities } from "@/utils/video-model-capabilities"
import {
  applyEdgeChanges,
  type EdgeChange,
  type NodeChange,
  type NodeTypes,
  type ReactFlowInstance,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { AlertTriangle, CheckCircle2, Maximize2, Minimize2 } from "lucide-react"
import { toast } from "sonner"
import {
  type ProductionStatusPopoverRow,
  type WorkChainProgressStep,
} from "./production-status-popover"

import {
  applyStoryboardAllocation,
  getCanvasSnapshot,
  getCanvasRecords,
  getDirectorRules,
  getScriptAdaptationTemplates,
  getStoryboardTemplates,
  relayoutEpisodeWorkflow,
  workflowFromCanvasSnapshot,
  type AgentTargetContext,
  type InputImageFile,
  type ScriptAdaptationTemplateOption,
  type TaskRow,
  type VideoPromptDraftRequest,
  type WorkflowNode,
} from "@/backend"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { ProjectRow } from "@/features/projects/types"
import type { CanvasAgentTaskCanvasRequest } from "@/features/assistant/assistant-task-request"
import {
  normalizeStoryboardTemplate,
  type StoryboardTemplateOption,
} from "@/features/settings/storyboard-templates"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import { errMsg } from "@/shared/backend-result"
import { mediaThumbnailSrc } from "@/shared/media"

import { canvasInputMutations } from "./canvas-input-mutations"


function SourceTextTaskEditor({
  data,
  text,
  maxHeight,
}: {
  data: WorkflowNodeData
  text: string
  maxHeight?: number
}) {
  const textareaMaxHeight =
    typeof maxHeight === "number" ? Math.max(180, maxHeight - 24) : undefined
  return (
    <div className="nodrag nopan nowheel">
      <Textarea
        value={text || sourceTextForNode(data)}
        readOnly
        onPointerDown={(event) => event.stopPropagation()}
        onWheel={stopCardWheel}
        onWheelCapture={stopCardWheel}
        placeholder={data.sourceMode === "independent" ? "输入独立剧情后，点击应用生成工作链" : "暂无分集原文"}
        aria-label={data.sourceMode === "independent" ? "独立剧情原文" : "分集原文"}
        className={compactWorkflowTextareaClassName(
          "max-h-[min(70vh,640px)] min-h-[180px] cursor-text"
        )}
        style={
          textareaMaxHeight
            ? fixedWorkflowTextareaHeightStyle(textareaMaxHeight)
            : undefined
        }
        spellCheck={false}
      />
    </div>
  )
}

function WorkflowEditWindowToggleButton({
  maximized,
  onToggle,
}: {
  maximized: boolean
  onToggle: () => void
}) {
  const label = maximized ? "缩小窗口" : "放大窗口"
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      className="h-7 w-7 bg-transparent text-gray-500 shadow-none hover:bg-transparent hover:text-gray-900 dark:bg-transparent dark:text-gray-400 dark:hover:bg-transparent dark:hover:text-gray-100"
      aria-label={label}
      onClick={(event) => {
        event.stopPropagation()
        onToggle()
      }}
    >
      {maximized ? (
        <Minimize2 className="size-3.5" />
      ) : (
        <Maximize2 className="size-3.5" />
      )}
    </Button>
  )
}

function WorkflowTaskEditorShell({
  data,
  title,
  width,
  maxHeight,
  maximized,
  onToggleMaximized,
  children,
}: {
  data: WorkflowNodeData
  title: string
  width: number
  maxHeight?: number
  maximized: boolean
  onToggleMaximized?: () => void
  children: ReactNode
}) {
  const showStoryboardGallery = isStoryboardCardNodeType(data.eyebrow) || isWorkflowVideoTaskType(data.eyebrow)
  const reserveTopControlSpace = !maximized && isWorkflowVideoTaskType(data.eyebrow)

  return (
    <div
      data-workflow-source-text-panel={
        data.eyebrow === "source.text" ? true : undefined
      }
      role={maximized ? "dialog" : undefined}
      aria-modal={maximized ? true : undefined}
      className={cn(
        "nodrag nopan nowheel relative overflow-hidden text-xs text-gray-900 dark:text-white/[0.85]",
        maximized
          ? "flex h-full w-full min-h-0 flex-col bg-slate-50 dark:bg-[#111113]"
          : cn(
              "box-border rounded-md border border-gray-300 bg-white p-3 shadow-2xl shadow-gray-950/15 backdrop-blur-sm dark:border-white/[0.10] dark:bg-[#262626]/[0.98] dark:shadow-black/25",
              isStoryboardCardNodeType(data.eyebrow) && "pt-2",
              reserveTopControlSpace && "pt-[18px]"
            )
      )}
      style={maximized ? undefined : { width, maxHeight }}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => event.stopPropagation()}
      onWheel={stopCardWheel}
    >
      <div
        className={
          maximized
            ? "flex shrink-0 items-center justify-between gap-4 border-b border-gray-200/80 bg-white px-5 py-3 shadow-none dark:border-white/[0.07] dark:bg-[#18181b]"
            : "absolute top-0.5 right-0.5 z-20"
        }
      >
        {maximized ? (
          <h2 className="min-w-0 truncate text-base font-semibold text-gray-950 dark:text-gray-50">
            {title}
          </h2>
        ) : null}
        {onToggleMaximized ? (
          <div className="flex shrink-0 items-center gap-1.5">
            <WorkflowEditWindowToggleButton
              maximized={maximized}
              onToggle={onToggleMaximized}
            />
          </div>
        ) : null}
      </div>
      <div
        className={
          maximized
            ? cn(
                "min-h-0 flex-1 overflow-hidden bg-slate-50 p-4 dark:bg-[#151517] lg:p-5",
                "pb-16 lg:pb-16"
              )
            : "contents"
        }
      >
        <div
          className={
            maximized
              ? cn(
                  "flex h-full min-h-0 gap-4",
                  isStoryboardCardNodeType(data.eyebrow) ? "flex-row" : "flex-col"
                )
              : "contents"
          }
        >
          {maximized && showStoryboardGallery ? (
            <ExtractedStoryboardGallery
              key={`${data.projectId}:${data.episodeId}:${data.nodeId}`}
              data={data}
              renderInputs={({ selectedKey, onSelect, onItemsChange }) => (
                <InlineAssetLinks
                  id={String(data.nodeId ?? "")}
                  data={data}
                  compact
                  selectedPreviewKey={selectedKey}
                  onPreview={onSelect}
                  onPreviewItemsChange={onItemsChange}
                />
              )}
            />
          ) : null}
          <div className={maximized ? "min-h-0 flex-1 basis-0 overflow-hidden" : "contents"}>
            {children}
          </div>
        </div>
      </div>
    </div>
  )
}

function WorkflowTaskParameterPanel({
  id,
  data,
  width,
  maxHeight,
  sourceDraft,
  maximized = false,
  onToggleMaximized,
}: {
  id: string
  data: WorkflowNodeData
  width: number
  maxHeight?: number
  sourceDraft?: string
  maximized?: boolean
  onToggleMaximized?: () => void
}) {
  const isSourceTextPanel = data.eyebrow === "source.text"
  if (isDirectorBoardNodeType(data.eyebrow) || (!isSourceTextPanel && !hasInlineTaskParameterPanel(data.eyebrow)))
    return null
  const effectiveMaxHeight = maximized ? undefined : maxHeight
  const editor = isStoryboardCardNodeType(data.eyebrow) ? (
    <StoryboardUnitShotEditor
      id={id}
      data={data}
      maxHeight={effectiveMaxHeight}
      maximized={maximized}
      AssetLinks={InlineAssetLinks}
    />
  ) : isSourceTextPanel ? (
    <SourceTextTaskEditor
      data={data}
      text={sourceDraft ?? ""}
      maxHeight={effectiveMaxHeight}
    />
  ) : (
    <ExtractedWorkflowTaskEditor
      id={id}
      data={data}
      maxHeight={effectiveMaxHeight}
      maximized={maximized}
      AssetLinks={InlineAssetLinks}
      AssetLinksLoadingSlot={InlineAssetLinksLoadingSlot}
    />
  )
  return (
    <WorkflowTaskEditorShell
      data={data}
      title={[
        workflowCardTypeLabel(data.eyebrow, data),
        workflowCardHeaderLocator(data),
      ].filter(Boolean).join(" · ")}
      width={width}
      maxHeight={maxHeight}
      maximized={maximized}
      onToggleMaximized={onToggleMaximized}
    >
      {editor}
    </WorkflowTaskEditorShell>
  )
}

export function InlinePreflightStatus({ data }: { data: WorkflowNodeData }) {
  const quality = recordValue(data.quality)
  const modelPreflight = recordValue(quality.modelPreflight)
  const capabilityCheck = recordValue(data.capabilityCheck)
  const blockingIssues = uniqueStringValues(
    modelPreflight.blockingIssues,
    capabilityCheck.blockingIssues
  )
  const warnings = uniqueStringValues(
    modelPreflight.warnings,
    capabilityCheck.warnings
  )
  const success =
    typeof modelPreflight.success === "boolean"
      ? modelPreflight.success
      : typeof capabilityCheck.success === "boolean"
        ? capabilityCheck.success
        : undefined
  const hasPreflight =
    success !== undefined || blockingIssues.length > 0 || warnings.length > 0
  if (!hasPreflight) return null

  const blocked = blockingIssues.length > 0 || success === false
  const visibleMessages = [...blockingIssues, ...warnings].slice(0, 3)

  return (
    <div
      className={cn(
        "nodrag nopan mt-2 rounded-lg border px-2.5 py-2 text-[11px] leading-relaxed",
        blocked
          ? "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200"
          : warnings.length
            ? "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200"
            : "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200"
      )}
    >
      <div className="flex items-center gap-1.5 font-medium">
        {blocked ? (
          <AlertTriangle className="size-3.5 shrink-0" />
        ) : (
          <CheckCircle2 className="size-3.5 shrink-0" />
        )}
        <span>
          {blocked ? "预检未通过" : warnings.length ? "预检提醒" : "预检通过"}
        </span>
      </div>
      {visibleMessages.length ? (
        <div className="mt-1 space-y-0.5">
          {visibleMessages.map((message, index) => (
            <div key={`${message}-${index}`} className="line-clamp-2">
              {message}
            </div>
          ))}
          {blockingIssues.length + warnings.length > visibleMessages.length ? (
            <div className="font-medium">
              还有{" "}
              {blockingIssues.length + warnings.length - visibleMessages.length}{" "}
              项
            </div>
          ) : null}
        </div>
      ) : (
        <div className="mt-1 line-clamp-2">
          模型能力和输入 slot 已通过后端预检
        </div>
      )}
    </div>
  )
}

function inlineAssetThumbnailTooltip(tag: InlineAssetTag, reference?: Record<string, unknown>) {
  const referenceLabel = String(reference?.referenceLabel || "").trim()
  if (reference?.transportRole === "first_frame" || reference?.transportRole === "last_frame") {
    return referenceLabel
  }
  const name = tag.kind === "frame"
    ? tag.frameRole === "last_frame" ? "尾帧" : "首帧"
    : tag.kind === "storyboard" ? "分镜图"
      : tag.kind === "handoff" ? "视觉交接图" : tag.label
  return referenceLabel ? `${referenceLabel}：${name}` : name
}

function InlineAssetThumbnailTag({ tag, reference }: {
  tag: InlineAssetTag
  reference?: Record<string, unknown>
}) {
  const label = tag.label
  const prefix = inlineAssetTagPrefix(tag.kind)
  const tooltip = inlineAssetThumbnailTooltip(tag, reference)
  const videoReferenceIndex = tag.kind === "video" ? Number(reference?.index) || undefined : undefined
  const preview =
    mediaThumbnailSrc(tag.media, tag.previewSrc) || tag.previewSrc || ""
  const [imageLoaded, setImageLoaded] = useState(false)
  const fallbackText = (label.trim()[0] || prefix[0] || "@").toLocaleUpperCase()

  useEffect(() => {
    setImageLoaded(false)
  }, [preview])

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          role="img"
          aria-label={tooltip}
          className={cn(
            "relative flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-md border border-white/70 bg-white text-[13px] font-semibold shadow-sm ring-1 ring-black/5 dark:border-white/10 dark:bg-white/[0.06] dark:ring-white/10",
            !preview ? inlineAssetTagStyle(tag.kind) : ""
          )}
        >
          {preview ? (
            <>
              <span className="absolute inset-0 bg-slate-100 dark:bg-white/[0.08]" />
              <img
                src={preview}
                alt={label}
                className={cn(
                  "relative size-full object-cover transition-opacity duration-150",
                  imageLoaded ? "opacity-100" : "opacity-0"
                )}
                draggable={false}
                onLoad={() => setImageLoaded(true)}
                onError={() => setImageLoaded(false)}
              />
            </>
          ) : (
            <span>{fallbackText}</span>
          )}
          <span className="absolute right-0 bottom-0 flex h-3.5 min-w-3.5 items-center justify-center rounded-tl-sm bg-black/65 px-0.5 text-[9px] leading-none font-semibold text-white">
            {reference?.replacementLabel ? String(reference.replacementLabel) : tag.kind === "video"
              ? `视${videoReferenceIndex || ""}`
              : tag.kind === "frame"
                ? tag.frameRole === "last_frame"
                  ? "尾"
                  : "首"
                : tag.kind === "handoff"
                  ? "交"
                : inlineAssetTagPrefix(tag.kind)[0]}
          </span>
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" sideOffset={6} className="z-[10000]">
        {tooltip}
      </TooltipContent>
    </Tooltip>
  )
}

function InlineAssetLinksLoadingSlot({
  active = false,
  compact = false,
}: {
  active?: boolean
  compact?: boolean
}) {
  if (!active) return null
  return (
    <div
      className={cn("nodrag nopan h-9 overflow-hidden", !compact && "mt-3")}
      aria-label="正在加载关联资产"
    >
      <div className="flex h-full items-center gap-1.5">
        {[0, 1, 2].map((item) => (
          <span
            key={item}
            className="h-9 w-14 shrink-0 animate-pulse rounded-md bg-slate-100/80 dark:bg-white/[0.06]"
          />
        ))}
      </div>
    </div>
  )
}

function InlineAssetLinks({
  id,
  data,
  reserveSpace = false,
  compact = false,
  trailing,
  selectedPreviewKey,
  onPreview,
  onPreviewItemsChange,
}: {
  id: string
  data: WorkflowNodeData
  reserveSpace?: boolean
  compact?: boolean
  trailing?: ReactNode
  selectedPreviewKey?: string
  onPreview?: (tag: InlineAssetTag) => void
  onPreviewItemsChange?: (tags: InlineAssetTag[]) => void
}) {
  const referenceManifest = data.referenceManifest ?? []
  const referenceVideoManifest = referenceManifest.filter(
    (row) => String(row.kind ?? row.referenceType ?? "").trim() === "video"
  )
  const assetTags = useMemo(() => {
    const referenceVideoRows = Array.isArray(data.referenceVideoThumbnails)
      ? data.referenceVideoThumbnails
      : []
    const { tags } = collectInlineAssetTags(
      [...inlineAssetDisplayRows(data), ...referenceVideoRows],
      inlineAssetDisplayRefs(data)
    )
    // Thumbnail positions follow all associated assets, independent of which
    // references are currently enabled and numbered for generation.
    return tags
  }, [data.referenceDisplayRows, data.eyebrow, data.assetRefs, data.assetThumbnails, data.inputLinks, data.referenceThumbnails, data.referenceVideoThumbnails])
  useEffect(() => { onPreviewItemsChange?.(assetTags) }, [assetTags, onPreviewItemsChange])
  const config = recordValue(data.generationConfig)
  const modelId =
    configPrivateStringValue(config, ["modelId", "model_id"]) ||
    workflowSnapshotConfiguredModelId(data.modelCapabilitiesSnapshot, "video", data.eyebrow)
  const model = workflowModelCapabilityRows(
    data.modelCapabilitiesSnapshot,
    "video"
  ).find((row) => workflowModelCapabilityId(row) === modelId)
  const nativeRequired = data.eyebrow === "video.keyframe"
  const visual = recordValue(model?.adapter_capabilities)[nativeRequired ? "keyframe_visual_inputs" : "visual_inputs"] as
    | VideoVisualInputCapabilities
    | undefined
  const isVideo = isWorkflowVideoTaskType(data.eyebrow)
  const selection = frameTransportSelection(assetTags, visual, nativeRequired)
  const availableNativeFrames = frameTransportSelection(
    assetTags.map((row) => ({ ...row, useNativeFrame: true })),
    visual,
    nativeRequired
  ).native
  if (!assetTags.length && !trailing && !reserveSpace) {
    return null
  }
  return (
    <div
      className={cn(
        "nodrag nopan",
        onPreview && "w-max",
        !compact && "mt-3",
        reserveSpace ? "min-h-9" : null
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className={cn("flex min-w-0 flex-1 gap-1.5", onPreview ? "flex-nowrap items-center" : "flex-wrap")}>
          {assetTags.map((tag, index) => {
            const videoReference = tag.kind === "video"
              ? referenceVideoManifest.find((row) => {
                  return inlineAssetTagReferenceMatches(tag, row)
                })
              : undefined
            const imageReference = tag.kind !== "video"
              ? referenceManifest.find((row) => {
                  return row.kind === "image" && inlineAssetTagReferenceMatches(tag, row)
                })
              : undefined
            const thumbnail = (
              <InlineAssetThumbnailTag
                tag={tag}
                reference={data.eyebrow === "video.character_replace" && (videoReference || imageReference)
                  ? { ...(videoReference || imageReference),
                      replacementLabel: videoReference ? "源" : `图${imageReference?.index ?? ""}`,
                      referenceLabel: videoReference ? "源视频" : `图${imageReference?.index ?? ""}` }
                  : videoReference || imageReference}
              />
            )
            if (!tag.sourceNodeId) return <span key={tag.key}>{thumbnail}</span>
            return (
              <AssetReferenceMenu
                key={tag.key}
                referenceLabel={data.eyebrow === "video.character_replace" ? (tag.kind === "video" ? "源视频" : `替换角色图${imageReference?.index ?? ""}`) : {
                  character: "角色图参考",
                  creature: "生物图参考",
                  scene: "场景图参考",
                  prop: "道具图参考",
                  storyboard: "分镜图参考",
                  handoff: "视觉交接图参考",
                  frame: "帧画面参考",
                  video: "视频参考",
                  custom_image: "自定义图片参考",
                }[tag.kind]}
                frame={tag.kind === "frame"}
                enabled={tag.enabled !== false}
                onEnabledChange={(enabled) => data.onUpdateReferenceUsage?.(id, tag.sourceNodeId!, enabled)}
                selected={selectedPreviewKey === tag.key}
                onPreview={onPreview ? () => onPreview(tag) : undefined}
                value={{
                  frameRole: tag.frameRole ?? "first_frame",
                  useNativeFrame: tag.useNativeFrame !== false,
                }}
                video={isVideo}
                modelLabel={
                  model ? workflowModelCapabilityLabel(model) : undefined
                }
                combinationValid={!visual || selection.valid}
                constraint={frameNativeConstraint(assetTags, index, visual, nativeRequired)}
                nativeAvailable={tag.enabled === false
                  ? supportsNativeFrame(tag.frameRole ?? "first_frame", visual, nativeRequired)
                  : availableNativeFrames.has(index)}
                nativeActive={selection.native.has(index)}
                unavailableRoles={assetTags
                  .filter(
                    (other) =>
                      other.enabled !== false && other.kind === "frame" &&
                      other.sourceNodeId !== tag.sourceNodeId
                  )
                  .map((other) => other.frameRole ?? "first_frame")}
                unsupportedRoles={nativeRequired && visual
                  ? (["first_frame", "last_frame"] as const).filter((role) => !supportsNativeFrame(role, visual, true))
                  : []}
                nativeControlsAspectRatio={
                  visual?.native_frame_controls_aspect_ratio === true
                }
                nativeRequired={nativeRequired}
                onChange={(options) =>
                  data.onUpdateFrameReference?.(id, tag.sourceNodeId!, options)
                }
              >
                {thumbnail}
              </AssetReferenceMenu>
            )
          })}
        </div>
        {trailing ? (
          <div className="shrink-0 text-[11px] leading-4 font-medium text-gray-400 tabular-nums dark:text-white/35">
            {trailing}
          </div>
        ) : null}
      </div>
    </div>
  )
}

export function ResultFrameSlotControls({
  id,
  data,
}: {
  id: string
  data: WorkflowNodeData
}) {
  const isResultImage = data.eyebrow === "storyboard.image"
  if (!isResultImage) return null
  const currentSlot = resultFrameSlotFromNode(data)
  return (
    <div className="nodrag nopan mt-3 rounded-lg border border-gray-200/70 bg-white/70 p-2 dark:border-white/10 dark:bg-white/[0.035]">
      <div className="mb-1.5 text-[11px] font-semibold text-gray-500 dark:text-gray-400">
        图片用途
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        {RESULT_FRAME_SLOT_OPTIONS.map((option) => {
          const active = currentSlot === option.slot
          return (
            <Button
              key={option.slot}
              type="button"
              size="sm"
              variant={active ? "default" : "outline"}
              className="h-7 px-2 text-[11px]"
              disabled={active || !data.onUpdateNodeData}
              onClick={(event) => {
                event.stopPropagation()
                data.onUpdateNodeData?.(
                  id,
                  {
                    eyebrow: option.nodeType,
                    frameSlot: option.slot,
                  },
                  "result_frame_slot_set"
                )
              }}
            >
              {active ? "当前" : "设为"}
              {option.label}
            </Button>
          )
        })}
      </div>
    </div>
  )
}

const STORYBOARD_NODE_TYPES: NodeTypes = createStoryboardNodeTypes({
  TaskConfigSummary: WorkflowCardConfig,
  TaskParameterPanel: WorkflowTaskParameterPanel,
})

export function StoryboardWorkflowCanvas({
  project,
  episodeId,
  canvasKind = "work_chain",
  canvasTitle,
  workspaceTasks = [],
  agentFocusNodeId,
  agentFocusEpisodeId,
  agentFocusToken,
  onAgentTargetChange,
  onRequestCanvasAgentTask,
}: {
  project: ProjectRow
  episodeId: string
  canvasKind?: "work_chain" | "custom"
  canvasTitle?: string
  workspaceTasks?: TaskRow[]
  agentFocusNodeId?: string
  agentFocusEpisodeId?: string
  agentFocusToken?: number
  onAgentTargetChange?: (target: AgentTargetContext | null) => void
  onRequestCanvasAgentTask?: (request: CanvasAgentTaskCanvasRequest) => boolean
}) {
  const { backendReady, callBackend, onBackendEvent } = useBackend()
  const isCustomCanvas = canvasKind === "custom"
  const canvasScopeKey = `${project.id}\u0000${episodeId}`
  const canvasRequestScopeRef = useRef({ key: canvasScopeKey })
  if (canvasRequestScopeRef.current.key !== canvasScopeKey)
    canvasRequestScopeRef.current = { key: canvasScopeKey }
  useEffect(() => {
    if (canvasRequestScopeRef.current.key !== canvasScopeKey)
      canvasRequestScopeRef.current = { key: canvasScopeKey }
    return () => {
      canvasRequestScopeRef.current = { key: "" }
    }
  }, [canvasScopeKey])

  const canvasDocument = useWorkflowCanvasDocument(canvasScopeKey)
  const storyboardPlanSaverRef = useRef<ReturnType<typeof createStoryboardPlanSaver> | null>(null)
  const {
    nodes,
    edges,
    routes,
    selectedNodeId,
    selectedWorkChainId,
    loading,
    loadedCanvasScopeKey,
    workflowState,
    workflowRootExtras,
  } = canvasDocument.read()
  const generationPreflight = useWorkflowGenerationPreflight({
    projectId: project.id,
    episodeId,
    callBackend,
    canvasDocument,
  })
  const { cacheCapabilities } = generationPreflight
  const handleNodesChange = useCallback(
    (changes: NodeChange<StoryboardNode>[]) => {
      if (changes.some((change) => change.type === "remove")) {
        toast.info("请使用节点右键菜单删除可删除的资产节点")
      }
      canvasDocument.applyNodeChanges(
        changes.filter((change) => change.type !== "remove")
      )
    },
    [canvasDocument.applyNodeChanges]
  )

  const [storyboardTemplates, setStoryboardTemplates] = useState<
    StoryboardTemplateOption[]
  >([])
  const [directorRuleOptions, setDirectorRuleOptions] = useState<
    NonNullable<WorkflowNodeData["directorRuleOptions"]>
  >([])
  const [scriptAdaptationTemplates, setScriptAdaptationTemplates] = useState<
    ScriptAdaptationTemplateOption[]
  >([])

  const [nodeContextMenu, setNodeContextMenu] =
    useState<NodeContextMenuState | null>(null)
  const [directorWorkspace, setDirectorWorkspace] = useState<StoryboardNode | null>(null)
  useEffect(() => setDirectorWorkspace(null), [canvasScopeKey])
  const [canvasContextMenu, setCanvasContextMenu] =
    useState<CanvasContextMenuState | null>(null)
  const [edgeContextMenu, setEdgeContextMenu] =
    useState<EdgeContextMenuState | null>(null)
  const [nodeDetails, setNodeDetails] = useState<NodeDetailsState | null>(null)

  const [statusPopoverOpen, setStatusPopoverOpen] = useState(false)
  const [canvasViewportDragging, setCanvasViewportDragging] = useState(false)

  const nodeLayout = useWorkflowNodeLayout({
    backendReady,
    callBackend,
    projectId: project.id,
    episodeId,
    setNodes: canvasDocument.updateNodes,
    onVersionConfirmed: canvasDocument.confirmRevision,
  })
  const {
    onDrag: handleNodeDrag,
    onDragStart: handleNodeDragStart,
    onDragStop: handleNodeDragStop,
  } = nodeLayout
  const runNodeRef = useRef<(nodeId: string) => void>(() => undefined)
  const lastAgentFocusTokenRef = useRef<number | undefined>(undefined)
  const submitStoryboardImageEditRef = useRef<
    (
      nodeId: string,
      prompt: string,
      referenceFiles: InputImageFile[],
      options?: WorkflowImageEditOptions
    ) => Promise<boolean | void> | boolean | void
  >(() => undefined)
  const generateCinematicScriptRef = useRef<
    (
      nodeId: string,
      options?: {
        scriptTemplateId?: string
        userInstruction?: string
      }
    ) => Promise<void> | void
  >(() => undefined)
  const generateFinalVideoPromptRef = useRef<
    (nodeId: string) => Promise<void> | void
  >(() => undefined)
  const saveInlineEditRef = useRef<
    (
      nodeId: string,
      patch: WorkflowInlineEditPatch,
      options?: ManualSaveOptions
    ) => Promise<void> | void
  >(() => undefined)
  const updateNodeDataRef = useRef<
    (
      nodeId: string,
      patch: Partial<WorkflowNodeData>,
      reason: string,
      options?: ManualSaveOptions
    ) => Promise<void> | void
  >(() => undefined)
  const updateReferenceUsageRef = useRef<(nodeId: string, sourceNodeId: string, enabled: boolean) => void>(() => undefined)
  const saveStoryboardUnitShotsRef = useRef<WorkflowNodeActions["onSaveStoryboardUnitShots"]>(async () => undefined)
  const updateFrameReferenceRef = useRef<
    (
      nodeId: string,
      sourceNodeId: string,
      options: FrameReferenceOptions
    ) => void
  >(() => undefined)
  const removeInputLinkRef = useRef<
    (nodeId: string, inputLinkId: string) => void
  >(() => undefined)
  const focusWorkflowNodeRef = useRef<
    (nodeId: string, options?: { silentMissing?: boolean }) => boolean
  >(() => false)
  const flowInstanceRef = useRef<ReactFlowInstance<
    StoryboardNode,
    StoryboardEdge
  > | null>(null)
  const buildCanvasAgentTarget = useCallback(
    (
      node?: StoryboardNode | null,
      intent: AgentTargetContext["intent"] = "focus"
    ): AgentTargetContext => ({
      source: "storyboard_canvas",
      intent,
      section: "episode",
      episodeId,
      nodeId: node?.id,
      nodeType: node?.data.eyebrow,
      routeId: node?.data.routeId,
      segmentId: node?.data.segmentId,
      workChainId: node?.data.workChainId,
      cardTitle: node?.data.title,
    }),
    [episodeId]
  )
  const publishCanvasAgentTarget = useCallback(
    (
      nodeId?: string | null,
      intent: AgentTargetContext["intent"] = "focus"
    ) => {
      if (!onAgentTargetChange) return
      const node = nodeId
        ? canvasDocument.read().nodes.find((item) => item.id === nodeId)
        : null
      onAgentTargetChange(buildCanvasAgentTarget(node, intent))
    },
    [buildCanvasAgentTarget, onAgentTargetChange]
  )
  useEffect(() => {
    if (!selectedNodeId) return
    publishCanvasAgentTarget(selectedNodeId, "focus")
  }, [publishCanvasAgentTarget, selectedNodeId])
  const currentCanvasFlowBounds = useCallback((): WorkflowCanvasRect | null => {
    if (typeof document === "undefined") return null
    const instance = flowInstanceRef.current
    const flowElement = document.querySelector<HTMLElement>(".react-flow")
    const rect = flowElement?.getBoundingClientRect()
    if (!instance || !rect || rect.width <= 0 || rect.height <= 0) return null
    const topLeft = instance.screenToFlowPosition({
      x: rect.left,
      y: rect.top,
    })
    const bottomRight = instance.screenToFlowPosition({
      x: rect.right,
      y: rect.bottom,
    })
    return {
      x: Math.min(topLeft.x, bottomRight.x),
      y: Math.min(topLeft.y, bottomRight.y),
      width: Math.abs(bottomRight.x - topLeft.x),
      height: Math.abs(bottomRight.y - topLeft.y),
    }
  }, [])
  const contextMenuNode = nodeContextMenu
    ? nodes.find((node) => node.id === nodeContextMenu.nodeId)
    : undefined
  const contextMenuEdge = edgeContextMenu
    ? edges.find((edge) => edge.id === edgeContextMenu.edgeId)
    : undefined
  const contextMenuEdgeTarget = contextMenuEdge
    ? nodes.find((node) => node.id === contextMenuEdge.target)
    : undefined
  const reconcileStaleCanvasNodes = useCallback(
    (
      retainedActiveTaskByNodeId: Map<string, TaskRow>,
      freshLocalNodeIds: Set<string>
    ) => {
      canvasDocument.updateNodes((current) => {
        let changed = false
        const next = current.map((node) => {
          if (!isStaleWorkflowNodeTaskStatus(node.data.status)) return node
          if (
            retainedActiveTaskByNodeId.has(node.id) ||
            freshLocalNodeIds.has(node.id)
          ) {
            return node
          }
          const nextStatus = fallbackWorkflowNodeStatusAfterMissingTask(
            node,
            current,
            edges
          )
          if (nextStatus === node.data.status) return node
          changed = true
          return {
            ...node,
            data: {
              ...node.data,
              status: nextStatus,
            },
          }
        })
        return changed ? next : current
      })
    },
    [edges, canvasDocument.updateNodes]
  )
  const taskLifecycle = useWorkflowTaskLifecycle({
    projectId: project.id,
    episodeId,
    backendReady,
    callBackend,
    nodes,
    edges,
    workspaceTasks,
    onStaleNodes: reconcileStaleCanvasNodes,
  })
  const {
    tasks: workflowStatusTasks,
    activeTaskByNodeId: activeWorkflowTaskByNodeId,
    launchingNodeIds: runningNodeIds,
  } = taskLifecycle

  const contextMenuEdgeInputLink =
    contextMenuEdge?.data?.inputLinkId && contextMenuEdgeTarget
      ? (Array.isArray(contextMenuEdgeTarget.data.inputLinks)
          ? contextMenuEdgeTarget.data.inputLinks
          : []
        ).find((link) =>
          inputLinkMatchesDirectId(
            recordValue(link),
            String(contextMenuEdge.data?.inputLinkId ?? "")
          )
        )
      : undefined
  const contextMenuEdgeIsMaterial = contextMenuEdge?.data?.kind === "material"
  const contextMenuEdgeProtected = isWorkflowLockedSystemEdge(
    contextMenuEdge,
    nodes
  )
  const contextMenuEdgeLocked =
    contextMenuEdgeProtected ||
    (!contextMenuEdgeIsMaterial &&
      (isWorkflowItemLocked(contextMenuEdge) ||
        isWorkflowItemLocked(contextMenuEdge?.data) ||
        isWorkflowItemLocked(contextMenuEdgeTarget?.data))) ||
    isWorkflowItemLocked(contextMenuEdgeInputLink)

  const selectedDetailNode = nodeDetails
    ? nodes.find((node) => node.id === nodeDetails.nodeId)
    : undefined
  const detailNode = selectedDetailNode ? {
    ...selectedDetailNode,
    data: { ...selectedDetailNode.data, scriptContinuityReview: workflowNodeScriptContinuityReview(selectedDetailNode, workflowRootExtras.productionStatus) },
  } : undefined

  const workChains = useMemo(() => {
    const configured = workflowRootExtras.workChains ?? []
    return configured
  }, [workflowRootExtras.workChains])
  const productionStatusRows = useMemo<ProductionStatusPopoverRow[]>(
    () =>
      workChains.map((workChain, index) => ({
        id: workChain.id,
        label: workflowWorkChainDisplayName(workChain, index),
        originLabel:
          workChain.origin?.kind === "independent_source" ? "独立剧情" : workChain.origin?.kind === "independent" ? "独立创建" : "原文拆分",
        steps: buildWorkChainProgressSteps(
          workChain,
          routes,
          nodes,
          workflowRootExtras.productionStatus,
          activeWorkflowTaskByNodeId
        ),
      })),
    [
      activeWorkflowTaskByNodeId,
      nodes,
      routes,
      workChains,
      workflowRootExtras.productionStatus,
    ]
  )
  const selectedWorkChain = workChains.find(
    (workChain) => workChain.id === selectedWorkChainId
  )
  const workChainFilterActive =
    selectedWorkChainId !== "all" && Boolean(selectedWorkChain)
  const selectedWorkChainRouteIds = new Set(
    selectedWorkChain?.routeIds?.length
      ? selectedWorkChain.routeIds
      : routes
          .filter(
            (route) =>
              route.workChainId === selectedWorkChainId ||
              route.id === selectedWorkChainId
          )
          .map((route) => route.id)
  )

  const visibleNodes = workChainFilterActive
    ? nodes.filter((node) => {
        const routeId = node.data.routeId
        const workChainId = node.data.workChainId
        return (
          (!routeId &&
            !workChainId &&
            (node.data.eyebrow !== "source.text" ||
              node.id === selectedWorkChain?.origin?.sourceNodeId)) ||
          workChainId === selectedWorkChainId ||
          (routeId ? selectedWorkChainRouteIds.has(routeId) : false)
        )
      })
    : nodes
  const visibleNodeIds = new Set(visibleNodes.map((node) => node.id))
  const visibleEdges = workChainFilterActive
    ? edges.filter((edge) => {
        const routeId = edge.data?.routeId
        const workChainId = edge.data?.workChainId
        return (
          visibleNodeIds.has(edge.source) &&
          visibleNodeIds.has(edge.target) &&
          ((!routeId && !workChainId) ||
            workChainId === selectedWorkChainId ||
            (routeId ? selectedWorkChainRouteIds.has(routeId) : false))
        )
      })
    : edges
  const workflowTaskResultRelationIndex = useMemo(
    () => buildWorkflowTaskResultRelationIndex(nodes, edges),
    [edges, nodes]
  )
  const canvasScopeLoaded = loadedCanvasScopeKey === canvasScopeKey
  const hasScopedNodes =
    nodes.length > 0 &&
    nodes.some((node) => {
      const nodeProjectId = String(node.data.projectId ?? "").trim()
      const nodeEpisodeId = String(node.data.episodeId ?? "").trim()
      return Boolean(nodeProjectId || nodeEpisodeId)
    })
  const nodesMatchCanvasScope =
    hasScopedNodes &&
    nodes.every((node) => {
      const nodeProjectId = String(node.data.projectId ?? "").trim()
      const nodeEpisodeId = String(node.data.episodeId ?? "").trim()
      return (
        (!nodeProjectId || nodeProjectId === project.id) &&
        (!nodeEpisodeId || nodeEpisodeId === episodeId)
      )
    })
  const hasRealWorkflow =
    nodes.length > 0 && (canvasScopeLoaded || nodesMatchCanvasScope)
  const canvasScopeSwitching = loadedCanvasScopeKey !== canvasScopeKey
  const canvasLoading = (loading || canvasScopeSwitching) && !hasRealWorkflow
  const showWorkflowEmptyState =
    !isCustomCanvas && (!hasRealWorkflow || (loading && nodes.length === 0))
  const showCustomCanvasEmptyHint =
    isCustomCanvas && canvasScopeLoaded && !loading && nodes.length === 0
  const currentEpisodeTitle = useMemo(() => {
    if (isCustomCanvas) return String(canvasTitle ?? "").trim()
    return String(
      project.episodes?.find((episode) => episode.id === episodeId)?.title ?? ""
    ).trim()
  }, [canvasTitle, episodeId, isCustomCanvas, project.episodes])
  const bindRunNode = useCallback(
    (nodeId: string) => runNodeRef.current(nodeId),
    []
  )
  const bindSaveInlineEdit = useCallback(
    (
      nodeId: string,
      patch: WorkflowInlineEditPatch,
      options?: ManualSaveOptions
    ) => saveInlineEditRef.current(nodeId, patch, options),
    []
  )
  const bindUpdateNodeData = useCallback(
    (
      nodeId: string,
      patch: Partial<WorkflowNodeData>,
      reason: string,
      options?: ManualSaveOptions
    ) => updateNodeDataRef.current(nodeId, patch, reason, options),
    []
  )
  const bindUpdateReferenceUsage = useCallback((nodeId: string, sourceNodeId: string, enabled: boolean) => {
    updateReferenceUsageRef.current(nodeId, sourceNodeId, enabled)
  }, [])
  const bindSaveStoryboardUnitShots = useCallback<WorkflowNodeActions["onSaveStoryboardUnitShots"]>(
    (...args) => saveStoryboardUnitShotsRef.current(...args),
    [],
  )
  const bindDiscardStoryboardSave = useCallback((nodeId: string) => storyboardPlanSaverRef.current?.discardFailed(nodeId), [])
  const bindUpdateFrameReference = useCallback(
    (nodeId: string, sourceNodeId: string, options: FrameReferenceOptions) => {
      updateFrameReferenceRef.current(nodeId, sourceNodeId, options)
    },
    []
  )
  const bindRemoveInputLink = useCallback(
    (nodeId: string, inputLinkId: string) =>
      removeInputLinkRef.current(nodeId, inputLinkId),
    []
  )
  const bindFocusWorkflowNode = useCallback(
    (nodeId: string) => focusWorkflowNodeRef.current(nodeId),
    []
  )
  const bindSubmitStoryboardImageEdit = useCallback(
    (
      nodeId: string,
      prompt: string,
      referenceFiles: InputImageFile[],
      options?: WorkflowImageEditOptions
    ) =>
      submitStoryboardImageEditRef.current(
        nodeId,
        prompt,
        referenceFiles,
        options
      ),
    []
  )
  const bindGenerateCinematicScript = useCallback(
    (
      nodeId: string,
      options?: {
        scriptTemplateId?: string
        userInstruction?: string
      }
    ) => generateCinematicScriptRef.current(nodeId, options),
    []
  )
  const bindGenerateFinalVideoPrompt = useCallback(
    (nodeId: string) => generateFinalVideoPromptRef.current(nodeId),
    []
  )
  const optimizeVideoPrompt = useCallback(
    async (nodeId: string, request: VideoPromptDraftRequest) => {
      if (!backendReady) throw new Error("后端尚未就绪")
      const node = canvasDocument.read().nodes.find((item) => item.id === nodeId)
      if (!node || (node.data.eyebrow !== "video.storyboard" && node.data.eyebrow !== "video.keyframe"))
        throw new Error("请选择视频提示词卡片")
      if (node.data.workChainId) throw new Error("请在工作链视频节点使用生成视频提示词")
      if (!onRequestCanvasAgentTask) throw new Error("当前画布尚未连接智能体会话")
      return onRequestCanvasAgentTask({
        taskType: "video_prompt_optimization",
        projectId: project.id,
        episodeId,
        canvasKind,
        nodeId,
        nodeType: node.data.eyebrow,
        draftText: request.draftText,
        soundPrompt: request.soundPrompt,
        assetNameMap: { ...request.assetNameMap },
        promptBindings: { ...request.promptBindings },
      })
    },
    [backendReady, canvasKind, episodeId, onRequestCanvasAgentTask, project.id]
  )
  const workflowNodeActions = useMemo<WorkflowNodeActions>(
    () => ({
      projectId: project.id,
      episodeId,
      episodeTitle: currentEpisodeTitle,
      onRun: bindRunNode,
      onSaveInlineEdit: bindSaveInlineEdit,
      onUpdateNodeData: bindUpdateNodeData,
      onSaveStoryboardUnitShots: bindSaveStoryboardUnitShots,
      onDiscardStoryboardSave: bindDiscardStoryboardSave,
      onUpdateReferenceUsage: bindUpdateReferenceUsage,
      onUpdateFrameReference: bindUpdateFrameReference,
      onRemoveInputLink: bindRemoveInputLink,
      onFocusNode: bindFocusWorkflowNode,
      onSubmitStoryboardImageEdit: bindSubmitStoryboardImageEdit,
      onGenerateCinematicScript: bindGenerateCinematicScript,
      onGenerateFinalVideoPrompt: bindGenerateFinalVideoPrompt,
      onOptimizeVideoPrompt: optimizeVideoPrompt,
      storyboardTemplates,
      scriptAdaptationTemplates,
      get modelCapabilitiesSnapshot() {
        return generationPreflight.readCapabilities()
      },
    }),
    [
      bindFocusWorkflowNode,
      optimizeVideoPrompt,
      bindUpdateReferenceUsage,
      bindUpdateFrameReference,
      bindRemoveInputLink,
      bindRunNode,
      bindGenerateCinematicScript,
      bindGenerateFinalVideoPrompt,
      bindSaveInlineEdit,
      bindSubmitStoryboardImageEdit,
      bindUpdateNodeData,
      bindSaveStoryboardUnitShots,
      bindDiscardStoryboardSave,
      currentEpisodeTitle,
      episodeId,
      project.id,
      scriptAdaptationTemplates,
      storyboardTemplates,
    ]
  )

  const handleAssetWriteback = useCallback(
    (event: WorkflowAssetWriteback) => {
      if (event.type === "rollback") {
        const ids = new Set(event.nodeIds)
        canvasDocument.updateNodes((current) =>
          current.filter((node) => !ids.has(node.id))
        )
        canvasDocument.selectNode((current) =>
          current && ids.has(current) ? null : current
        )
        return
      }
      if (event.nodes.length)
        canvasDocument.updateNodes((current) =>
          upsertStoryboardNodesLocally(current, event.nodes)
        )
      if (event.revision !== undefined && event.revision !== null)
        canvasDocument.confirmRevision(event.revision)
      if (event.selectedNodeId !== undefined)
        canvasDocument.selectNode(event.selectedNodeId)
    },
    [canvasDocument.updateNodes, canvasDocument.confirmRevision]
  )
  const adaptAssetNodes = useCallback(
    (rows: WorkflowNode[]) =>
      toStoryboardNodesFromBackend(rows, workflowNodeActions, routes),
    [routes, workflowNodeActions]
  )
  const assetPersistence = useWorkflowAssetPersistence({
    projectId: project.id,
    episodeId,
    callBackend,
    layout: nodeLayout,
    adaptNodes: adaptAssetNodes,
    onWriteback: handleAssetWriteback,
  })

  const assetImports = useWorkflowAssetImports({
    backendReady,
    callBackend,
    projectId: project.id,
    episodeId,
    workflowNodeActions,
    assetPersistence,
    placement: {
      nodes,
      visibleNodes,
      workChainId: workChainFilterActive ? selectedWorkChainId : "",
      routeIds: selectedWorkChainRouteIds,
      bounds: currentCanvasFlowBounds,
    },
  })
  const {
    picker: assetPicker,
    saving: savingAsset,
    addToCanvas: handleAddAssetToCanvas,
  } = assetImports
  const { lastAddAssetKind, open: openAddAssetDialog } = assetPicker

  const readExchangeNodes = useCallback(() => canvasDocument.read().nodes, [])
  const readExchangeFlow = useCallback(() => flowInstanceRef.current, [])
  const dismissMediaExchangeUi = useCallback(
    (reason: "paste" | "clip" | "clipboard-image") => {
      if (reason === "paste" || reason === "clipboard-image")
        setCanvasContextMenu(null)
      if (reason === "clip" || reason === "clipboard-image")
        setNodeContextMenu(null)
      if (reason === "clip") setNodeDetails(null)
      if (reason === "clipboard-image") setEdgeContextMenu(null)
    },
    []
  )
  const mediaExchange = useWorkflowMediaExchange({
    projectId: project.id,
    episodeId,
    backendReady,
    callBackend,
    readNodes: readExchangeNodes,
    getFlowInstance: readExchangeFlow,
    assetPersistence,
    assetPicker,
    dismiss: dismissMediaExchangeUi,
    graph: {
      workChains,
      routes,
      workflowNodeActions,
      visibleNodes,
      workChainId: workChainFilterActive ? selectedWorkChainId : "",
      routeIds: selectedWorkChainRouteIds,
    },
  })
  const {
    acceptCopied: setCopiedAssetClipboard,
    openClip: handleOpenVideoClipDialog,
  } = mediaExchange

  const canvasDetails = useWorkflowCanvasDetails({
    backendReady,
    callBackend,
    projectId: project.id,
    episodeId,
    document: canvasDocument,
    workflowNodeActions,
    routes,
  })
  const {
    loadingIds: hydratingWorkflowCardIds,
    isLoaded: isWorkflowCardLoaded,
    hydrate: hydrateWorkflowCard,
  } = canvasDetails

  const historyMutationRef = useRef<(payload: unknown) => boolean>(() => false)
  const consumeHistoryMutation = useCallback(
    (payload: unknown) => historyMutationRef.current(payload),
    []
  )

  const documentSync = useWorkflowDocumentSync({
    canvasDocument,
    projectId: project.id,
    episodeId,
    backendReady,
    callBackend,
    onBackendEvent,
    workflowNodeActions,
    canvasDetails,
    taskLifecycle,
    onHistoryMutation: consumeHistoryMutation,
    cacheCapabilities,
  })
  const {
    load: loadWorkflow,
    reconcile: reconcileCanvasSnapshot,
    applyMutation: applyWorkflowMutationEventToCanvas,
  } = documentSync

  const canvasEvents = useWorkflowCanvasEvents({
    projectId: project.id,
    episodeId,
    backendReady,
    onBackendEvent,
    canvasDocument,
    canvasDetails,
    documentSync,
    taskLifecycle,
  })
  const applyWorkflowTaskResultToCanvas = canvasEvents.acceptTask
  const closeVersionMenu = useCallback(() => setNodeContextMenu(null), [])
  const nodeEditing = useWorkflowNodeEditing({
    projectId: project.id,
    episodeId,
    backendReady,
    callBackend,
    canvasDocument,
    canvasDetails,
    documentSync,
    workflowNodeActions,
    workChains,
    onOpenVersion: closeVersionMenu,
  })
  const {
    editHistory,
    setImageEdit: setStoryboardImageEdit,
    submitImageEdit: submitStoryboardImageEdit,
    saveInline: handleSaveInlineNodeEdit,
    updateData: handleUpdateInlineNodeData,
    openVersion: handleOpenNodeVersionHistory,
  } = nodeEditing
  const dismissStructureUi = useCallback(
    (reason: "create" | "delete") => {
      if (reason === "create") {
        setCanvasContextMenu(null)
        return
      }
      setNodeContextMenu(null)
      setNodeDetails(null)
      setStoryboardImageEdit(null)
      publishCanvasAgentTarget(null, "focus")
    },
    [setStoryboardImageEdit, publishCanvasAgentTarget]
  )
  const centerStructureViewport = useCallback(
    (x: number, y: number, options: { zoom: number; duration: number }) =>
      flowInstanceRef.current?.setCenter(x, y, options),
    []
  )
  const structureActions = useWorkflowStructureActions({
    projectId: project.id,
    episodeId,
    backendReady,
    callBackend,
    canvasDocument,
    documentSync,
    workflowNodeActions,
    dismiss: dismissStructureUi,
    centerViewport: centerStructureViewport,
  })
  const {
    deleteNode: handleDeleteContextNode,
    setDeleteTarget: setDeleteChainTarget,
    sourceSplitEditor,
  } = structureActions
  const sourceSplitEditorNode = sourceSplitEditor
    ? nodes.find((node) => node.id === sourceSplitEditor.nodeId)
    : undefined
  const canvasSelection = useWorkflowCanvasSelection({
    projectId: project.id, episodeId, backendReady, callBackend, canvasDocument, documentSync,
    waitForWrites: async () => {
      await structureActions.waitForWrites()
      await nodeEditing.waitForWrites()
      await nodeLayout.waitForWrites()
      await canvasInputMutations.waitForCanvas(canvasScopeKey)
    },
    disabled: Boolean(sourceSplitEditor) || nodeLayout.batchSaving,
    viewKey: selectedWorkChainId,
  })
  const selectionMovementBlocked = canvasSelection.selected.some(node => node.draggable === false || node.data.creationPending)
  const getFreshWorkflowForRun = useCallback(async () => {
    await storyboardPlanSaverRef.current?.waitForWrites()
    await structureActions.waitForWrites()
    await nodeEditing.waitForWrites()
    await canvasInputMutations.waitForCanvas(canvasScopeKey)
    const workflow = await withBackendReadTimeout(
      getCanvasSnapshot(callBackend, project.id, episodeId, {
        detail: "summary",
        includeVersions: false,
      }).then(workflowFromCanvasSnapshot),
      "刷新最新工作流超时"
    )
    const freshNodes = toStoryboardNodes(workflow, workflowNodeActions)
    const freshEdges = toStoryboardEdges(workflow)
    return { workflow, nodes: freshNodes, edges: freshEdges }
  }, [
    callBackend,
    canvasScopeKey,
    episodeId,
    project.id,
    workflowNodeActions,
    nodeEditing.waitForWrites,
    structureActions.waitForWrites,
  ])

  const storyboardSaveOperationsRef = useRef({ documentSync })
  storyboardSaveOperationsRef.current = { documentSync }
  const storyboardPlanSaver = useMemo(() => createStoryboardPlanSaver({
    document: canvasDocument, callBackend, projectId: project.id, episodeId,
    // Capture the destination of accepted writes; navigation only detaches UI.
    readNodes: async (nodeIds) => {
      const result = await getCanvasRecords(callBackend, project.id, episodeId, { detail: "full", ids: { nodeIds } })
      return toStoryboardNodesFromBackend(result.records.nodes ?? [], workflowNodeActions, [])
    },
    beforeWrite: async () => {
      await nodeEditing.waitForWrites()
      await structureActions.waitForWrites()
      await canvasInputMutations.waitForCanvas(canvasScopeKey)
    },
    applyMutation: async (result) => {
      const requestScope = canvasDocument.scope
      const sync = storyboardSaveOperationsRef.current.documentSync
      // Fetch changed card/edge records before acknowledging the transaction;
      // allocation replies carry record IDs, not every updated unit's data.
      await sync.sync(result)
      if (canvasDocument.scope !== requestScope) return
      // A reply includes IDs for unit/edge changes. Never acknowledge those IDs
      // from the director-only reply when the record read has failed.
      if (!canvasDocument.hasTransaction(result as { txId?: unknown })
        && canvasDocument.read().workflowVersion < Number((result as { workflowVersion?: number }).workflowVersion ?? 0)) {
        sync.scheduleBackfill(result)
      }
    },
    onFailure: (error) => toast.error(errMsg(error, "保存分镜修改失败，请重试")),
    onWarning: (message) => toast.warning(message),
  }), [canvasDocument, canvasDocument.scope, callBackend, project.id, episodeId])
  storyboardPlanSaverRef.current = storyboardPlanSaver

  historyMutationRef.current = editHistory.consumeMutation

  const dismissProjectAssetUi = useCallback(
    (reason: "rename" | "added") => {
      setNodeContextMenu(null)
      if (reason === "rename") {
        setNodeDetails(null)
        nodeEditing.setImageEdit(null)
      }
    },
    [nodeEditing.setImageEdit]
  )
  const projectAssets = useWorkflowProjectAssets({
    projectId: project.id,
    episodeId,
    backendReady,
    callBackend,
    canvasDocument,
    documentSync,
    contextNode: contextMenuNode,
    dismiss: dismissProjectAssetUi,
  })
  const {
    openRename: handleOpenRenameAssetDialog,
    addToLibrary: handleAddContextNodeToAssetLibrary,
  } = projectAssets
  const nodeContextMenuModel = buildWorkflowNodeContextMenu({
    node: contextMenuNode,
    nodes,
    tasks: workflowStatusTasks,
    launchingNodeIds: runningNodeIds,
    backendReady,
    assetRowsByType: projectAssets.projectAssets,
    addingAssetLibraryNodeId: projectAssets.addingNodeId,
    workChains: workflowRootExtras.workChains,
  })

  const readGenerationNodes = useCallback(() => canvasDocument.read().nodes, [])
  const closeGenerationMenu = useCallback(() => setNodeContextMenu(null), [])
  const {
    generateStoryboardImage: handleGenerateStoryboardImageFromDirector,
    generateVisualHandoffImage: handleGenerateVisualHandoffImage,
    generateCinematicScript: handleGenerateCinematicScript,
    generateDirectorPlan: handleGenerateDirectorPlan,
    generateFinalVideoPrompt: handleGenerateFinalVideoPrompt,
  } = useWorkflowStageGeneration({
    projectId: project.id,
    episodeId,
    backendReady,
    callBackend,
    readNodes: readGenerationNodes,
    taskLifecycle,
    canvasDetails,
    prepareWorkflow: getFreshWorkflowForRun,
    applyMutation: applyWorkflowMutationEventToCanvas,
    onTaskAccepted: applyWorkflowTaskResultToCanvas,
    onLaunch: closeGenerationMenu,
    onRequestCanvasAgentTask: onRequestCanvasAgentTask
      ? (request) => onRequestCanvasAgentTask({ ...request, canvasKind })
      : undefined,
  })

  const { run: runNode } = useWorkflowNodeGeneration({
    projectId: project.id,
    episodeId,
    backendReady,
    callBackend,
    canvasDocument,
    canvasDetails,
    taskLifecycle,
    preflight: generationPreflight,
    prepareWorkflow: getFreshWorkflowForRun,
    onTaskAccepted: applyWorkflowTaskResultToCanvas,
    generateScript: handleGenerateCinematicScript,
    generateDirectorPlan: handleGenerateDirectorPlan,
  })

  useEffect(() => {
    generateCinematicScriptRef.current = (
      nodeId: string,
      options?: {
        scriptTemplateId?: string
        userInstruction?: string
      }
    ) => handleGenerateCinematicScript(nodeId, options)
  }, [handleGenerateCinematicScript])

  useEffect(() => {
    runNodeRef.current = (nodeId: string) => {
      void runNode(nodeId)
    }
  }, [runNode])

  useEffect(() => {
    void loadWorkflow()
  }, [backendReady, episodeId, project.id])

  useEffect(() => {
    if (!selectedNodeId) return
    const selectedNode = nodes.find((node) => node.id === selectedNodeId)
    if (!selectedNode) return
    const isTaskCard = isWorkflowTaskCardType(selectedNode.data.eyebrow)
    if (isTaskCard && isWorkflowCardLoaded(selectedNodeId)) {
      return
    }
    void hydrateWorkflowCard(selectedNodeId, { force: isTaskCard })
  }, [hydrateWorkflowCard, nodes, selectedNodeId])

  useEffect(() => {
    let cancelled = false
    const loadStoryboardTemplates = async () => {
      try {
        if (!backendReady) {
          if (!cancelled) setStoryboardTemplates([])
          return
        }
        const nextTemplates = (await getStoryboardTemplates(callBackend)).map(
          normalizeStoryboardTemplate
        )
        if (cancelled) return
        setStoryboardTemplates(nextTemplates)
      } catch (error) {
        if (!cancelled) {
          console.warn("加载分镜图版式失败:", error)
          setStoryboardTemplates([])
        }
      }
    }
    void loadStoryboardTemplates()
    return () => {
      cancelled = true
    }
  }, [backendReady, callBackend])

  useEffect(() => {
    let cancelled = false
    const loadDirectorRuleOptions = async () => {
      if (cancelled) return
      if (!backendReady) {
        setDirectorRuleOptions([])
        return
      }
      try {
        const rules = await getDirectorRules(callBackend)
        if (cancelled) return
        setDirectorRuleOptions(
          rules
            .filter((rule) => rule.id.trim())
            .map((rule) => ({
              id: rule.id.trim(),
              title: rule.title.trim() || rule.id.trim(),
              description: rule.description,
            }))
        )
      } catch (error) {
        if (cancelled) return
        setDirectorRuleOptions([])
        toast.error(errMsg(error, "加载导演规则失败"), {
          action: {
            label: "重试",
            onClick: () => void loadDirectorRuleOptions(),
          },
        })
      }
    }
    void loadDirectorRuleOptions()
    return () => {
      cancelled = true
    }
  }, [backendReady, callBackend])

  useEffect(() => {
    let cancelled = false
    const loadScriptAdaptationTemplates = async () => {
      try {
        const nextTemplates = backendReady
          ? await getScriptAdaptationTemplates(callBackend)
          : []
        if (cancelled) return
        setScriptAdaptationTemplates(nextTemplates)
      } catch (error) {
        if (!cancelled) {
          console.warn("加载片段剧本策略失败:", error)
        }
      }
    }
    void loadScriptAdaptationTemplates()
    return () => {
      cancelled = true
    }
  }, [backendReady, callBackend])

  useEffect(() => {
    canvasDocument.updateNodes((current) =>
      current.map((node) => ({
        ...node,
        data: {
          ...node.data,
          storyboardTemplates,
          scriptAdaptationTemplates,
        },
      }))
    )
  }, [
    scriptAdaptationTemplates,
    canvasDocument.updateNodes,
    storyboardTemplates,
  ])

  useEffect(() => {
    if (
      !nodeContextMenu &&
      !canvasContextMenu &&
      !edgeContextMenu &&
      !nodeDetails
    ) {
      return
    }
    const closeFloatingCanvasUi = () => {
      setNodeContextMenu(null)
      setCanvasContextMenu(null)
      setEdgeContextMenu(null)
      setNodeDetails(null)
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeFloatingCanvasUi()
    }
    window.addEventListener("pointerdown", closeFloatingCanvasUi)
    window.addEventListener("keydown", handleKeyDown)
    return () => {
      window.removeEventListener("pointerdown", closeFloatingCanvasUi)
      window.removeEventListener("keydown", handleKeyDown)
    }
  }, [canvasContextMenu, edgeContextMenu, nodeContextMenu, nodeDetails])

  const handleFocusWorkflowNode = useCallback(
    (nodeId: string, options: { silentMissing?: boolean } = {}) => {
      const node = canvasDocument
        .read()
        .nodes.find((item) => item.id === nodeId)
      if (!node) {
        if (!options.silentMissing) {
          toast.info("来源节点不在当前画布中")
        }
        return false
      }
      canvasDocument.selectNode(node.id)
      publishCanvasAgentTarget(node.id, "focus")
      window.setTimeout(() => {
        flowInstanceRef.current?.setCenter(
          node.position.x + 160,
          node.position.y + 80,
          { zoom: 0.9, duration: 420 }
        )
      }, 180)
      return true
    },
    [publishCanvasAgentTarget]
  )
  useEffect(() => {
    focusWorkflowNodeRef.current = (
      nodeId: string,
      options?: { silentMissing?: boolean }
    ) => handleFocusWorkflowNode(nodeId, options)
  }, [handleFocusWorkflowNode])

  useEffect(() => {
    if (!agentFocusNodeId || !agentFocusToken) return
    if (agentFocusEpisodeId && agentFocusEpisodeId !== episodeId) return
    if (lastAgentFocusTokenRef.current === agentFocusToken) return
    const resolvedNodeId = agentFocusNodeId
    if (!resolvedNodeId) return
    lastAgentFocusTokenRef.current = agentFocusToken
    if (handleFocusWorkflowNode(resolvedNodeId, { silentMissing: true })) {
      return
    }
    let cancelled = false
    void reconcileCanvasSnapshot("agent_focus_missing_node")
      .then(() => {
        if (cancelled) return
        window.setTimeout(() => {
          if (cancelled) return
          const focused = focusWorkflowNodeRef.current(resolvedNodeId, {
            silentMissing: true,
          })
          if (!focused) {
            toast.info("来源节点不在当前画布中")
          }
        }, 0)
      })
      .catch(() => {
        if (!cancelled) {
          toast.info("来源节点不在当前画布中")
        }
      })
    return () => {
      cancelled = true
    }
  }, [
    agentFocusEpisodeId,
    agentFocusNodeId,
    agentFocusToken,
    episodeId,
    handleFocusWorkflowNode,
    reconcileCanvasSnapshot,
  ])

  useEffect(() => {
    submitStoryboardImageEditRef.current = submitStoryboardImageEdit
  }, [submitStoryboardImageEdit])

  useEffect(() => {
    generateFinalVideoPromptRef.current = (nodeId: string) =>
      handleGenerateFinalVideoPrompt(nodeId)
  }, [handleGenerateFinalVideoPrompt])

  useEffect(() => {
    saveInlineEditRef.current = (
      nodeId: string,
      patch: WorkflowInlineEditPatch,
      options?: ManualSaveOptions
    ) => handleSaveInlineNodeEdit(nodeId, patch, options)
  }, [handleSaveInlineNodeEdit])

  useEffect(() => {
    updateNodeDataRef.current = (
      nodeId: string,
      patch: Partial<WorkflowNodeData>,
      reason: string,
      options?: ManualSaveOptions
    ) => handleUpdateInlineNodeData(nodeId, patch, reason, options)
  }, [handleUpdateInlineNodeData])

  const readInputGraph = useCallback(
    () => canvasDocument.read(),
    []
  )
  const handleInputUnlinked = useCallback((nodeId: string) => {
    setNodeDetails((current) => (current?.nodeId === nodeId ? null : current))
  }, [])
  const handleInputPresentationEdges = useCallback(
    (changes: EdgeChange<StoryboardEdge>[]) => {
      canvasDocument.updateEdges((current) =>
        applyEdgeChanges(changes, current)
      )
    },
    [canvasDocument.updateEdges]
  )
  const canvasInputs = useWorkflowCanvasInputs({
    projectId: project.id,
    episodeId,
    backendReady,
    canvasLoaded: loadedCanvasScopeKey === canvasScopeKey,
    callBackend,
    readGraph: readInputGraph,
    applyMutation: applyWorkflowMutationEventToCanvas,
    reconcile: reconcileCanvasSnapshot,
    onUnlinked: handleInputUnlinked,
    onPresentationEdgesChange: handleInputPresentationEdges,
  })
  const {
    connect: onConnect,
    removeLink: handleRemoveInputLink,
    edgesChanged: handleEdgesChange,
  } = canvasInputs
  useEffect(() => {
    updateReferenceUsageRef.current = canvasInputs.updateReferenceUsage
    updateFrameReferenceRef.current = canvasInputs.updateFrameReference
    removeInputLinkRef.current = handleRemoveInputLink
  }, [canvasInputs.updateReferenceUsage, canvasInputs.updateFrameReference, handleRemoveInputLink])

  const visibleFlowNodes = useMemo(
    () =>
      visibleNodes.map((node) => {
        const activeTask = activeWorkflowTaskForCanvasNode(
          node,
          workflowTaskResultRelationIndex,
          activeWorkflowTaskByNodeId
        )
        const videoTaskAttachedToWorkChain = isWorkflowVideoTaskType(
          node.data.eyebrow
        )
          ? isDefaultWorkChainVideoTaskNode(node)
          : undefined
        return {
          ...node,
          ...workflowCanvasNodeInteractionState(node),
          selected: canvasSelection.active ? Boolean(node.selected) : node.id === selectedNodeId,
          draggable: canvasSelection.ctrlPressed || canvasSelection.selecting || canvasSelection.deleting || nodeLayout.batchSaving
            || (node.selected && selectionMovementBlocked) ? false : workflowCanvasNodeInteractionState(node).draggable,
          data: {
            ...canvasInputs.decorateNode(node),
            videoTaskAttachedToWorkChain,
            directorRuleOptions: isDirectorBoardNodeType(node.data.eyebrow)
              ? directorRuleOptions
              : undefined,
            videoPromptSyncing: isWorkflowVideoTaskType(node.data.eyebrow)
              ? workflowVideoTaskPromptIsSyncing(
                  node,
                  activeWorkflowTaskByNodeId
                )
              : undefined,
            storyboardTemplates,
            activeTask,
            scriptContinuityReview: workflowNodeScriptContinuityReview(node, workflowRootExtras.productionStatus),
            status: workflowNodeCanvasDisplayStatus(
              node,
              nodes,
              edges,
              workflowRootExtras.productionStatus
            ),
            summary: node.data.summary,
            hideTaskParameterPanel:
              canvasViewportDragging || Boolean(sourceSplitEditor) ||
              canvasSelection.active || canvasSelection.ctrlPressed || canvasSelection.selecting,
            workflowCardDetailLoaded: isWorkflowCardLoaded(node.id),
            isHydratingWorkflowCard: hydratingWorkflowCardIds.has(node.id),
          },
        }
      }),
    [
      activeWorkflowTaskByNodeId,
      canvasInputs.decorateNode,
      canvasScopeKey,
      canvasViewportDragging,
      sourceSplitEditor,
      hydratingWorkflowCardIds,
      selectedNodeId,
      canvasSelection.active,
      canvasSelection.ctrlPressed,
      canvasSelection.selecting,
      canvasSelection.deleting,
      nodeLayout.batchSaving,
      selectionMovementBlocked,
      storyboardTemplates,
      directorRuleOptions,
      visibleNodes,
      edges,
      nodes,
      workflowTaskResultRelationIndex,
      workflowRootExtras.productionStatus,
    ]
  )
  const handleRemoveContextEdge = useCallback(
    (edgeId: string) => {
      handleEdgesChange([{ id: edgeId, type: "remove" }])
      setEdgeContextMenu(null)
    },
    [handleEdgesChange]
  )

  const handleFitView = useCallback(() => {
    flowInstanceRef.current?.fitView({ padding: 0.18, duration: 300 })
  }, [])

  const openCanvasContextMenu = useCallback(
    (event: MouseEvent<Element> | globalThis.MouseEvent) => {
      event.preventDefault()
      const flowPosition = flowInstanceRef.current?.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      }) ?? { x: event.clientX, y: event.clientY }
      setNodeContextMenu(null)
      setEdgeContextMenu(null)
      setNodeDetails(null)
      setStoryboardImageEdit(null)
      setStatusPopoverOpen(false)
      setCanvasContextMenu({
        x: event.clientX,
        y: event.clientY,
        flowPosition,
      })
    },
    []
  )

  const handleOpenNodeEditHistory = useCallback(
    async (nodeId: string) => {
      setNodeContextMenu(null)
      await editHistory.open(nodeId)
    },
    [editHistory.open]
  )

  const workChainNodesForFocus = useCallback(
    (workChainId: string) => {
      const workChain = workChains.find((item) => item.id === workChainId)
      const routeIds = new Set([
        ...(workChain?.routeIds ?? []),
        ...routes
          .filter(
            (route) =>
              route.workChainId === workChainId || route.id === workChainId
          )
          .map((route) => route.id),
      ])
      return nodes.filter((node) => {
        const routeId = String(node.data.routeId ?? "")
        return (
          node.data.workChainId === workChainId ||
          (routeId && routeIds.has(routeId))
        )
      })
    },
    [nodes, routes, workChains]
  )

  const handleShowAllWorkChains = useCallback(() => {
    canvasDocument.selectWorkChain("all")
    canvasDocument.selectNode(null)
    setStatusPopoverOpen(true)
    window.setTimeout(() => {
      flowInstanceRef.current?.fitView({ padding: 0.18, duration: 420 })
    }, 180)
  }, [])

  const handleFocusWorkChain = useCallback(
    (workChainId: string) => {
      const chainNodes = workChainNodesForFocus(workChainId)
      if (!chainNodes.length) {
        toast.info("这条工作链暂无可定位节点")
        return
      }
      canvasDocument.selectWorkChain(workChainId)
      canvasDocument.selectNode(null)
      onAgentTargetChange?.({
        source: "storyboard_canvas",
        intent: "focus",
        section: "episode",
        episodeId,
        workChainId,
      })
      setNodeContextMenu(null)
      setCanvasContextMenu(null)
      setEdgeContextMenu(null)
      setNodeDetails(null)
      setStoryboardImageEdit(null)
      setStatusPopoverOpen(false)
      window.setTimeout(() => {
        flowInstanceRef.current?.fitView({
          nodes: chainNodes.map((node) => ({ id: node.id })),
          padding: 0.24,
          duration: 420,
        })
      }, 180)
    },
    [episodeId, onAgentTargetChange, workChainNodesForFocus]
  )

  const handleFocusWorkChainStep = useCallback(
    (_workChainId: string, nodeId?: string) => {
      if (!nodeId) {
        toast.info("当前节点暂不可定位")
        return
      }
      const node = nodes.find((item) => item.id === nodeId)
      if (!node) {
        toast.info("这个节点不在当前画布中")
        return
      }
      const rect = workflowNodeRect(node)
      canvasDocument.selectWorkChain("all")
      canvasDocument.selectNode(node.id)
      publishCanvasAgentTarget(node.id, "focus")
      setNodeContextMenu(null)
      setCanvasContextMenu(null)
      setEdgeContextMenu(null)
      setNodeDetails(null)
      setStoryboardImageEdit(null)
      setStatusPopoverOpen(false)
      window.setTimeout(() => {
        flowInstanceRef.current?.setCenter(
          rect.x + rect.width / 2,
          rect.y + rect.height / 2,
          { zoom: 0.9, duration: 420 }
        )
      }, 180)
    },
    [nodes, publishCanvasAgentTarget]
  )

  const handleRunWorkChainStep = useCallback(
    (_workChainId: string, step: WorkChainProgressStep) => {
      const targetNodeIds = step.actionTargetNodeIds ?? (
        step.actionTargetNodeId ? [step.actionTargetNodeId] : []
      )
      if (!targetNodeIds.length) {
        toast.info(step.actionDisabledText ?? "当前环节缺少可执行任务卡")
        return
      }
      void (async () => {
        const agentStage = step.stageId === "cinematic_script.generated" ||
          step.stageId === "director_plan.generated"
        for (const nodeId of agentStage ? targetNodeIds.slice(0, 1) : targetNodeIds) {
          if (step.stageId === "cinematic_script.generated") {
            await handleGenerateCinematicScript(nodeId)
          } else if (step.stageId === "director_plan.generated") {
            await handleGenerateDirectorPlan(nodeId)
          } else if (step.stageId === "storyboard.generated") {
            await handleGenerateStoryboardImageFromDirector(nodeId)
          } else if (step.stageId === "video_prompt.ready") {
            await handleGenerateFinalVideoPrompt(nodeId)
          } else if (step.stageId === "visual_handoff.generated") {
            await handleGenerateVisualHandoffImage(nodeId)
          } else {
            await runNode(nodeId)
          }
        }
      })().catch((error) => toast.error(errMsg(error, "提交工作链任务失败")))
    },
    [
      handleGenerateCinematicScript,
      handleGenerateDirectorPlan,
      handleGenerateFinalVideoPrompt,
      handleGenerateStoryboardImageFromDirector,
      handleGenerateVisualHandoffImage,
      runNode,
    ]
  )

  const handleRelayoutWorkChains = useCallback(async () => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    const requestScope = canvasRequestScopeRef.current
    try {
      const result = await relayoutEpisodeWorkflow(callBackend, project.id, episodeId)
      if (canvasRequestScopeRef.current !== requestScope) return
      applyWorkflowMutationEventToCanvas(result)
      await loadWorkflow()
      toast.success("工作链布局已整理")
    } catch (error) {
      if (canvasRequestScopeRef.current === requestScope)
        toast.error(errMsg(error, "整理工作链布局失败"))
    }
  }, [backendReady, callBackend, project.id, episodeId, applyWorkflowMutationEventToCanvas, loadWorkflow])

  const detailRows = detailNode
    ? mediaDetailRows(detailNode.id, detailNode.data)
    : []
  const nodeDetailsPanelStyle = nodeDetails
    ? workflowViewportBoundFloatingStyle(
        nodeDetails.x,
        nodeDetails.y,
        WORKFLOW_FLOATING_EDITOR_WIDTH
      )
    : undefined

  const assetDialogProps = {
    picker: assetPicker,
    savingAsset,
    handleAddAssetToCanvas,
    backendReady,
  } satisfies WorkflowAssetDialogProps

  const autoAllocationAttemptsRef = useRef(new Set<string>())
  const autoAllocationRunningRef = useRef(false)
  useEffect(() => {
    if (!backendReady || loading || loadedCanvasScopeKey !== canvasScopeKey || autoAllocationRunningRef.current || directorWorkspace) return
    const director = nodes.find((node) => {
      if (!isDirectorBoardNodeType(node.data.eyebrow) || (!node.data.directorPlan && !node.data.directorPlanShots?.length)) return false
      if (node.data.storyboardAllocation?.groups?.length) return false
      if (node.data.status === "running" || node.data.status === "processing") return false
      const branches = nodes.filter((item) => item.data.workChainId === node.data.workChainId && item.data.eyebrow === "storyboard.card")
      return branches.length > 0 && branches.every((item) => !item.data.activeVersionId && !item.data.activeMediaVersionId && !item.data.mediaVersionId)
    })
    if (!director) return
    const key = `${canvasScopeKey}:${director.id}:${JSON.stringify(director.data.directorPlan ?? director.data.directorPlanShots)}`
    if (autoAllocationAttemptsRef.current.has(key)) return
    autoAllocationAttemptsRef.current.add(key)
    autoAllocationRunningRef.current = true
    const requestScope = canvasRequestScopeRef.current
    void (async () => {
      try {
        const hydrated = await canvasDetails.hydrateForRun(director)
        if (canvasRequestScopeRef.current !== requestScope) return
        if (hydrated.data.storyboardAllocation?.groups?.length) return
        const shots = hydrated.data.directorPlanShots ?? []
        if (!shots.length) return
        const result = await applyStoryboardAllocation(callBackend, project.id, episodeId, {
          directorNodeId: hydrated.id,
          directorPlanShots: shots,
          groups: shots.map((_, index) => ({ id: `group_${String(index + 1).padStart(3, "0")}`, shotNos: [index + 1] })),
          invalidateGenerated: false,
        })
        if (canvasRequestScopeRef.current !== requestScope) return
        applyWorkflowMutationEventToCanvas(result)
        await loadWorkflow()
      } catch (error) {
        if (canvasRequestScopeRef.current === requestScope) toast.warning(errMsg(error, "自动分配导演镜头失败"))
      } finally {
        autoAllocationRunningRef.current = false
      }
    })()
  }, [backendReady, loading, loadedCanvasScopeKey, canvasScopeKey, directorWorkspace, nodes, canvasDetails.hydrateForRun, callBackend, project.id, episodeId, applyWorkflowMutationEventToCanvas, loadWorkflow])

  const openDirectorWorkspace = async (nodeId: string) => {
    setNodeContextMenu(null)
    try {
      const fresh = await getFreshWorkflowForRun()
      const node = fresh.nodes.find((item) => item.id === nodeId)
      if (!node || !isDirectorBoardNodeType(node.data.eyebrow)) {
        toast.info("请选择分镜脚本")
        return
      }
      const hydrated = await canvasDetails.hydrateForRun(node)
      setDirectorWorkspace(hydrated)
    } catch (error) {
      toast.error(errMsg(error, "打开分镜脚本失败"))
    }
  }

  const saveStoryboardUnitShots: WorkflowNodeActions["onSaveStoryboardUnitShots"] = (...args) => {
    storyboardPlanSaver.saveUnit(...args)
  }
  useEffect(() => {
    saveStoryboardUnitShotsRef.current = saveStoryboardUnitShots
  }, [saveStoryboardUnitShots])

  const nodeContextMenuActions: WorkflowNodeContextMenuActions = {
    close: () => setNodeContextMenu(null),
    showDetails: (details) => {
      setNodeDetails(details)
      setStoryboardImageEdit(null)
      setNodeContextMenu(null)
    },
    editImage: (nodeId) => {
      if (!canOpenCanvasImageEditor(nodes.find((node) => node.id === nodeId))) {
        toast.info("当前卡片没有可编辑的图片，请先通过对应生成入口生成")
        return
      }
      canvasDocument.selectNode(nodeId)
      setStoryboardImageEdit({ nodeId })
      setNodeDetails(null)
      setNodeContextMenu(null)
    },
    openEditHistory: handleOpenNodeEditHistory,
    openVersionHistory: handleOpenNodeVersionHistory,
    clipVideo: handleOpenVideoClipDialog,
    renameAsset: handleOpenRenameAssetDialog,
    generateVideoPrompt: handleGenerateFinalVideoPrompt,
    runNode,
    addToAssetLibrary: handleAddContextNodeToAssetLibrary,
    assetCopied: setCopiedAssetClipboard,
    focusNode: handleFocusWorkflowNode,
    generateCinematicScript: handleGenerateCinematicScript,
    generateStoryboardImage: handleGenerateStoryboardImageFromDirector,
    generateVisualHandoff: handleGenerateVisualHandoffImage,
    requestDeleteChain: setDeleteChainTarget,
    deleteNode: handleDeleteContextNode,
  }

  const canvasViewModel = {
    canvasSelection,
    selectionMovementBlocked,
    layoutSaving: nodeLayout.batchSaving,
    nodeEditing,
    structureActions,
    projectAssets,
    generationPreflight,
    mediaExchange,
    canvasDetails,
    documentSync,
    canvasDocument,
    STORYBOARD_NODE_TYPES,
    assetDialogProps,
    canvasContextMenu,
    canvasLoading,
    canvasViewportDragging,
    contextMenuEdge,
    contextMenuEdgeLocked,
    detailNode,
    detailRows,
    edgeContextMenu,
    episodeId,
    flowInstanceRef,
    handleEdgesChange,
    handleFitView,
    handleFocusWorkChain,
    handleFocusWorkChainStep,
    handleNodeDrag,
    handleNodeDragStart,
    handleNodeDragStop,
    handleNodesChange,
    handleRemoveContextEdge,
    handleRunWorkChainStep,
    handleRelayoutWorkChains,
    handleShowAllWorkChains,
    hasRealWorkflow,
    lastAddAssetKind,
    nodeContextMenu,
    nodeDetails,
    nodeDetailsPanelStyle,
    openDirectorWorkspace,
    onConnect,
    openAddAssetDialog,
    openCanvasContextMenu,
    productionStatusRows,
    project,
    publishCanvasAgentTarget,
    setCanvasContextMenu,
    setCanvasViewportDragging,
    setEdgeContextMenu,
    setNodeContextMenu,
    setNodeDetails,
    setStatusPopoverOpen,
    showCustomCanvasEmptyHint,
    showWorkflowEmptyState,
    sourceSplitEditorNode,
    statusPopoverOpen,
    visibleEdges,
    visibleFlowNodes,
    workflowState,
    nodeContextMenuModel,
    nodeContextMenuActions,
  } satisfies WorkflowCanvasViewProps
  return (
    <>
      <WorkflowCanvasView {...canvasViewModel} />
      {directorWorkspace ? (
        <DirectorWorkspaceDialog
          key={directorWorkspace.id}
          director={{ ...directorWorkspace, data: {
            ...directorWorkspace.data,
            ...(nodes.find((item) => item.id === directorWorkspace.id)?.data ?? {}),
          } }}
          directorRuleOptions={directorRuleOptions}
          projectId={project.id}
          episodeId={episodeId}
          assetLinks={<InlineAssetLinks id={directorWorkspace.id} data={{
            ...directorWorkspace.data,
            ...(nodes.find((item) => item.id === directorWorkspace.id)?.data ?? {}),
            onUpdateReferenceUsage: bindUpdateReferenceUsage,
          }} compact />}
          onSave={storyboardPlanSaver.saveDirector}
          onDiscardFailed={storyboardPlanSaver.discardFailed}
          onClose={() => setDirectorWorkspace(null)}
        />
      ) : null}
    </>
  )
}
