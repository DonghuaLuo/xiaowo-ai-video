import { createPortal } from "react-dom"
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type PointerEvent, type ReactNode, type WheelEvent } from "react"
import { ImagePlus, Loader2, Maximize2, Minimize2, Plus, Send, Shirt, UserRound, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { mediaAssetFromImageFile, mediaPreviewSrc } from "@/shared/media"
import { pickLocalImageFiles } from "@/shared/image-picker"
import type { InputImageFile, StoryboardTemplateOption } from "@/backend"
import { storyboardTemplateDisplayName, storyboardTemplateDisplayDescription } from "@/features/settings/storyboard-templates"
import { workflowNodeDataIsWorkChainStoryboardResult, type WorkflowImageEditOptions } from "./workflow-canvas-model"
import { workflowNodeDataIsVisualHandoffAsset } from "./workflow-canvas-asset-model"
import { isFrameImage } from "./frame-reference-menu"
import {
  canvasProjectAssetAspectRatio,
  canvasProjectAssetResolutionKeys,
  canvasProjectAssetTypeFromData,
} from "./workflow-canvas-assets"
import {
  configPrivateStringValue,
  workflowSnapshotConfiguredModelId,
  normalizedPresetSet,
  limitedOptionReason,
  presetOptions,
  providerFromModelId,
  workflowMatchedResolutionOption,
  workflowModelCapabilityId,
  workflowModelCapabilityProviderId,
  workflowModelCapabilityRows,
  workflowModelUnavailableReason,
  workflowModelLabelFormatter,
  workflowModelOptionGroups,
  workflowModelResolutionDescription,
  workflowModelResolutionLabel,
  workflowResolutionOptionMatches,
} from "./workflow-model-capabilities"
import { WorkflowCompactParameterMenu } from "./workflow-inline-controls"
import { filterImageResolutionOptionsForAspect, storyboardSizeIsPromptOnlyForGptRelay } from "@/utils/model-resolution"

type ImageEditDraftStorageValue = {
  [key: string]: any
  prompt?: string
  useProjectVisual?: boolean
  submittedUseProjectVisual?: boolean
  submittedUseOriginal?: boolean
  hideTurnaroundHeads?: boolean
  submittedHideTurnaroundHeads?: boolean
  modelId?: string
  resolution?: string
  storyboardTemplate?: string
  submittedPrompt?: string
  submittedModelId?: string
  submittedResolution?: string
}

type WorkflowNodeData = {
  [key: string]: any
  eyebrow?: string
  projectId?: string
  episodeId?: string
  title?: string
  width?: number
  height?: number
  metric?: string
  media?: any
  storage?: any
}

type StoryboardNodeLike = { id: string; data: WorkflowNodeData }

type WorkflowFloatingPanelRect = {
  left: number
  top: number
  width: number
  maxHeight: number
  transform: string
}

const IMAGE_EDIT_DRAFT_STORAGE_PREFIX = "ai-video:image-edit-draft:v1"
const WORKFLOW_FLOATING_EDITOR_MARGIN = 16
const WORKFLOW_FLOATING_EDITOR_GAP = 14
const WORKFLOW_FLOATING_EDITOR_MIN_HEIGHT = 260
const WORKFLOW_FLOATING_EDITOR_MAX_HEIGHT = 760
const WORKFLOW_FLOATING_EDIT_PANEL_WIDTH = 700
const WORKFLOW_FLOATING_IMAGE_EDITOR_PREFERRED_HEIGHT = 320
const WORKFLOW_CENTERED_IMAGE_EDITOR_CONTENT_HEIGHT = 520
const WORKFLOW_CENTERED_IMAGE_EDITOR_MIN_HEIGHT = 440

function recordValue(value: unknown): Record<string, any> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, any>)
    : {}
}

function stopCardWheel(event: WheelEvent<HTMLElement>) {
  event.stopPropagation()
  event.nativeEvent.stopImmediatePropagation?.()
}

function compactWorkflowTextareaClassName(className?: string) {
  return cn(
    "nowheel block w-full min-h-[92px] max-h-[min(36vh,280px)] resize-none overflow-y-auto rounded-none border-0 bg-transparent px-0 py-0 text-[13px] leading-relaxed text-gray-900 shadow-none outline-none caret-gray-900 placeholder:text-gray-500 focus:border-transparent focus:ring-0 focus-visible:border-transparent focus-visible:ring-0 focus-visible:ring-offset-0 dark:text-white/90 dark:caret-white dark:placeholder:text-white/40",
    className
  )
}

function fixedWorkflowTextareaHeightStyle(height: number) {
  return { height, minHeight: height, maxHeight: height }
}

function imageEditDraftStoragePart(value: unknown) {
  const text = String(value ?? "").trim()
  return encodeURIComponent(text || "_")
}

function imageEditDraftStorageKey(projectId: unknown, episodeId: unknown, nodeId: string) {
  return [IMAGE_EDIT_DRAFT_STORAGE_PREFIX, imageEditDraftStoragePart(projectId), imageEditDraftStoragePart(episodeId), imageEditDraftStoragePart(nodeId)].join(":")
}

function readImageEditDraftStorage(key: string): ImageEditDraftStorageValue | null {
  if (typeof window === "undefined") return null
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null
    }
    return {
      prompt: typeof parsed.prompt === "string" ? parsed.prompt : "",
      useProjectVisual: typeof parsed.useProjectVisual === "boolean" ? parsed.useProjectVisual : undefined,
      submittedUseProjectVisual: typeof parsed.submittedUseProjectVisual === "boolean" ? parsed.submittedUseProjectVisual : undefined,
      submittedUseOriginal: typeof parsed.submittedUseOriginal === "boolean" ? parsed.submittedUseOriginal : undefined,
      hideTurnaroundHeads: typeof parsed.hideTurnaroundHeads === "boolean" ? parsed.hideTurnaroundHeads : undefined,
      submittedHideTurnaroundHeads: typeof parsed.submittedHideTurnaroundHeads === "boolean" ? parsed.submittedHideTurnaroundHeads : undefined,
      modelId: typeof parsed.modelId === "string" ? parsed.modelId : undefined,
      resolution:
        typeof parsed.resolution === "string" ? parsed.resolution : undefined,
      storyboardTemplate:
        typeof parsed.storyboardTemplate === "string" ? parsed.storyboardTemplate : undefined,
      submittedPrompt:
        typeof parsed.submittedPrompt === "string"
          ? parsed.submittedPrompt
          : undefined,
      submittedModelId:
        typeof parsed.submittedModelId === "string"
          ? parsed.submittedModelId
          : undefined,
      submittedResolution:
        typeof parsed.submittedResolution === "string"
          ? parsed.submittedResolution
          : undefined,
    }
  } catch {
    return null
  }
}

function writeImageEditDraftStorage(key: string, value: ImageEditDraftStorageValue) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(key, JSON.stringify({ ...value, updatedAt: Date.now() }))
  } catch {
    // Storage can be unavailable in hardened WebView settings.
  }
}

function workflowSnapshotConfiguredResolution(snapshot: unknown, mediaType: "image" | "video") {
  const modelConfig = recordValue(recordValue(snapshot).modelConfig)
  return configPrivateStringValue(recordValue(modelConfig[mediaType]), mediaType === "image" ? ["storyboard_resolution", "storyboardResolution", "resolution", "size", "image_size", "imageSize"] : ["resolution", "size"])
}

function compactReadableValue(value: unknown) {
  if (value == null) return ""
  if (typeof value === "string") return value.trim()
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  return ""
}

function workflowSnapshotConfiguredAssetResolution(snapshot: unknown, assetType?: string) {
  const keys = canvasProjectAssetResolutionKeys(assetType as any)
  if (keys.length) {
    const modelConfig = recordValue(recordValue(snapshot).modelConfig)
    const value = configPrivateStringValue(recordValue(modelConfig.image), keys)
    if (value) return value
  }
  return workflowSnapshotConfiguredResolution(snapshot, "image")
}

function workflowImageEditConfigRecords(data: WorkflowNodeData) {
  const records: Record<string, unknown>[] = []
  const nestedKeys = [
    "image", "metadata", "payload", "generationConfig", "generation_config",
    "resolvedConfig", "resolved_config", "modelSelection", "model_selection",
  ]
  const addRecord = (value: unknown, depth = 0) => {
    const record = recordValue(value)
    if (!Object.keys(record).length) return
    records.push(record)
    const snapshot = recordValue(record.generationConfigSnapshot ?? record.generation_config_snapshot)
    if (Object.keys(snapshot).length) {
      addRecord(snapshot.merged, depth + 1)
      addRecord(snapshot.resolved, depth + 1)
    }
    if (depth >= 3) return
    nestedKeys.forEach((key) => addRecord(record[key], depth + 1))
  }
  ;[
    data.generationConfig,
    data.resolvedConfig,
    data.modelSelection,
    data.quality,
    data.provenance,
    data.media,
    data.storage,
  ].forEach((value) => addRecord(value))
  return records
}

function workflowImageEditConfigStringValue(data: WorkflowNodeData, keys: string[]) {
  for (const record of workflowImageEditConfigRecords(data)) {
    const value = configPrivateStringValue(record, keys)
    if (value) return value
  }
  return ""
}

function workflowImageEditExplicitModelId(data: WorkflowNodeData) {
  return configPrivateStringValue(recordValue(data.generationConfig), ["modelId", "model_id"])
}

function workflowImageEditDefaultModelId(data: WorkflowNodeData) {
  return workflowImageEditExplicitModelId(data)
}

function workflowImageEditModelSelection(data: WorkflowNodeData, modelId: string) {
  const effectiveModelId = modelId.trim() || workflowSnapshotConfiguredModelId(data.modelCapabilitiesSnapshot, "image")
  return {
    modelId: effectiveModelId,
    unavailableReason: workflowModelUnavailableReason(data.modelCapabilitiesSnapshot, "image", modelId) ||
      (effectiveModelId ? "" : "请先配置图片模型"),
  }
}

function workflowImageEditDefaultResolution(data: WorkflowNodeData) {
  const explicit = workflowImageEditConfigStringValue(data, ["resolution", "size", "storyboardResolution", "storyboard_resolution", "imageSize", "image_size"])
  if (explicit) return explicit
  if (workflowImageEditExplicitModelId(data)) {
    const width = Number(data.width)
    const height = Number(data.height)
    if (Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0) return `${Math.round(width)}x${Math.round(height)}`
    const metric = compactReadableValue(data.metric)
    if (metric && /\d/.test(metric)) return metric
  }
  const assetType = canvasProjectAssetTypeFromData(data)
  return assetType
    ? workflowSnapshotConfiguredAssetResolution(data.modelCapabilitiesSnapshot, assetType)
    : workflowSnapshotConfiguredResolution(data.modelCapabilitiesSnapshot, "image")
}

function workflowNodeDataHasEditableOriginalImage(data: WorkflowNodeData) {
  return Boolean(mediaPreviewSrc(data.media ?? data.storage ?? null))
}

function stringArrayValue(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item ?? "").trim()).filter(Boolean) : []
}

function workflowFloatingPanelRectForAnchor(anchor: HTMLElement, widthLimit: number, preferredHeight: number): WorkflowFloatingPanelRect {
  const rect = anchor.getBoundingClientRect()
  const width = Math.min(widthLimit, Math.max(320, window.innerWidth - WORKFLOW_FLOATING_EDITOR_MARGIN * 2))
  const left = Math.min(Math.max(rect.left + rect.width / 2, WORKFLOW_FLOATING_EDITOR_MARGIN + width / 2), Math.max(WORKFLOW_FLOATING_EDITOR_MARGIN + width / 2, window.innerWidth - WORKFLOW_FLOATING_EDITOR_MARGIN - width / 2))
  const maxHeight = Math.min(WORKFLOW_FLOATING_EDITOR_MAX_HEIGHT, Math.max(WORKFLOW_FLOATING_EDITOR_MIN_HEIGHT, window.innerHeight - WORKFLOW_FLOATING_EDITOR_MARGIN * 2))
  const belowTop = rect.bottom + WORKFLOW_FLOATING_EDITOR_GAP
  const belowSpace = window.innerHeight - belowTop - WORKFLOW_FLOATING_EDITOR_MARGIN
  const aboveSpace = rect.top - WORKFLOW_FLOATING_EDITOR_GAP - WORKFLOW_FLOATING_EDITOR_MARGIN
  const openAbove = belowSpace < preferredHeight / 2 && aboveSpace > belowSpace
  const available = Math.max(1, Math.min(maxHeight, openAbove ? aboveSpace : belowSpace))
  return { left, top: openAbove ? Math.max(WORKFLOW_FLOATING_EDITOR_MARGIN, rect.top - WORKFLOW_FLOATING_EDITOR_GAP) : Math.min(Math.max(WORKFLOW_FLOATING_EDITOR_MARGIN, belowTop), Math.max(WORKFLOW_FLOATING_EDITOR_MARGIN, window.innerHeight - WORKFLOW_FLOATING_EDITOR_MARGIN - available)), width, maxHeight: Math.min(preferredHeight, available), transform: openAbove ? "translate(-50%, -100%)" : "translateX(-50%)" }
}

function useWorkflowFloatingPanelRect(enabled: boolean, widthLimit: number, getAnchor: () => HTMLElement | null, depsKey: string, preferredHeight: number) {
  const [panelRect, setPanelRect] = useState<WorkflowFloatingPanelRect | null>(null)
  useEffect(() => {
    if (!enabled || typeof window === "undefined") { setPanelRect(null); return }
    let frame = 0
    const update = () => { const anchor = getAnchor(); setPanelRect(anchor ? workflowFloatingPanelRectForAnchor(anchor, widthLimit, preferredHeight) : null) }
    const request = () => { window.cancelAnimationFrame(frame); frame = window.requestAnimationFrame(update) }
    request(); window.addEventListener("resize", request); window.addEventListener("scroll", request, true)
    return () => { window.cancelAnimationFrame(frame); window.removeEventListener("resize", request); window.removeEventListener("scroll", request, true) }
  }, [enabled, widthLimit, getAnchor, depsKey, preferredHeight])
  return panelRect
}

function WorkflowEditWindowToggleButton({ maximized, onToggle }: { maximized: boolean; onToggle: () => void }) {
  const label = maximized ? "缩小窗口" : "放大窗口"
  return <Button type="button" variant="ghost" size="icon-sm" className="h-7 w-7 bg-transparent text-gray-500 shadow-none hover:bg-transparent hover:text-gray-900 dark:bg-transparent dark:text-gray-400 dark:hover:bg-transparent dark:hover:text-gray-100" aria-label={label} onClick={(event) => { event.stopPropagation(); onToggle() }}>{maximized ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}</Button>
}

function WorkflowEditPanelFrame({ maximized = false, width, maxHeight, minHeight, centeredClassName, onToggleMaximized, children }: { maximized?: boolean; width: number; maxHeight?: number; minHeight?: number; centeredClassName?: string; onToggleMaximized?: () => void; children: ReactNode }) {
  return <div role={maximized ? "dialog" : undefined} aria-modal={maximized ? true : undefined} className={cn("nodrag nopan nowheel relative box-border overflow-hidden rounded-md border border-gray-300 bg-white p-3 text-xs text-gray-900 shadow-2xl shadow-gray-950/15 backdrop-blur-sm dark:border-white/[0.10] dark:bg-[#262626]/[0.98] dark:text-white/[0.85] dark:shadow-black/25", maximized ? (centeredClassName ?? "w-[min(1040px,calc(100vw-1.5rem))]") : null)} style={maximized ? { minHeight, maxHeight } : { width, maxHeight }} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()} onWheel={stopCardWheel}>{onToggleMaximized ? <div className="absolute top-0.5 right-0.5 z-20"><WorkflowEditWindowToggleButton maximized={maximized} onToggle={onToggleMaximized} /></div> : null}{children}</div>
}
function WorkflowStoryboardImageEditPanel({
  id,
  data,
  sourceModelId,
  width,
  maxHeight,
  maximized = false,
  onToggleMaximized,
}: {
  id: string
  data: WorkflowNodeData
  sourceModelId: string
  width: number
  maxHeight?: number
  maximized?: boolean
  onToggleMaximized?: () => void
}) {
  const storageKey = useMemo(
    () =>
      imageEditDraftStorageKey(
        data.projectId,
        data.episodeId,
        id
      ),
    [data.episodeId, data.projectId, id]
  )
  const hasEditableOriginal = workflowNodeDataHasEditableOriginalImage(data)
  const isWorkChainStoryboard = workflowNodeDataIsWorkChainStoryboardResult(data)
  const isStoryboardImage = isWorkChainStoryboard || data.mediaPurpose === "storyboard_image"
  const isVisualHandoff = workflowNodeDataIsVisualHandoffAsset(data)
  const isFrameImageAsset = isFrameImage(data)
  const isCustomImage = data.mediaPurpose === "custom_image"
  const storyboardTemplates: StoryboardTemplateOption[] = Array.isArray(data.storyboardTemplates)
    ? data.storyboardTemplates
    : []
  const imageEditDefaultModelId = useMemo(
    () => workflowImageEditDefaultModelId(data),
    [data]
  )
  const imageEditDefaultResolution = useMemo(
    () => workflowImageEditDefaultResolution(data),
    [data]
  )
  const imageEditAssetType = useMemo(
    () => isVisualHandoff || isFrameImageAsset || isCustomImage ? "" : canvasProjectAssetTypeFromData(data),
    [data, isVisualHandoff, isFrameImageAsset, isCustomImage]
  )
  const initialDraftState = useMemo(() => {
    const stored = readImageEditDraftStorage(storageKey)
    return {
      prompt: stored?.prompt ?? "",
      useOriginal: true,
      hideTurnaroundHeads: stored?.hideTurnaroundHeads ?? false,
      submittedHideTurnaroundHeads: stored?.submittedHideTurnaroundHeads ?? stored?.hideTurnaroundHeads ?? false,
      useProjectVisual: stored?.useProjectVisual ?? data.useProjectVisual ?? true,
      submittedUseProjectVisual:
        stored?.submittedUseProjectVisual ?? data.useProjectVisual ?? true,
      submittedUseOriginal: stored?.submittedUseOriginal ?? true,
      modelId: stored?.modelId ?? imageEditDefaultModelId,
      resolution: stored?.resolution ?? imageEditDefaultResolution,
      storyboardTemplate: stored?.storyboardTemplate ?? "",
      submittedPrompt: stored?.submittedPrompt ?? "",
      submittedModelId:
        stored?.submittedModelId ?? stored?.modelId ?? imageEditDefaultModelId,
      submittedResolution:
        stored?.submittedResolution ??
        stored?.resolution ??
        imageEditDefaultResolution,
    }
  }, [
    imageEditDefaultModelId,
    imageEditDefaultResolution,
    storageKey,
    data.useProjectVisual,
  ])
  const [draft, setDraft] = useState(initialDraftState.prompt)
  const [useOriginal, setUseOriginal] = useState(initialDraftState.useOriginal)
  const [hideTurnaroundHeads, setHideTurnaroundHeads] = useState(initialDraftState.hideTurnaroundHeads)
  const [useProjectVisual, setUseProjectVisual] = useState<boolean>(initialDraftState.useProjectVisual)
  const effectiveUseOriginal = hasEditableOriginal && useOriginal
  const [referenceFiles, setReferenceFiles] = useState<InputImageFile[]>([])
  const showStoryboardTemplate =
    isStoryboardImage && !effectiveUseOriginal
  const canGenerateEmptyImage = Boolean(imageEditAssetType || isStoryboardImage || isVisualHandoff || isFrameImageAsset || isCustomImage)
  const [imageModelId, setImageModelId] = useState(initialDraftState.modelId)
  const [storyboardTemplate, setStoryboardTemplate] = useState(initialDraftState.storyboardTemplate)
  const selectedStoryboardTemplate = storyboardTemplates.find((template) => template.id === storyboardTemplate)
    ?? storyboardTemplates[0]
  const originalMedia = data.media ?? data.storage
  const originalAspectRatio = originalMedia?.width && originalMedia?.height
    ? `${originalMedia.width}:${originalMedia.height}`
    : String(data.aspectRatio || "16:9")
  const imageEditAspectRatio = effectiveUseOriginal
    ? originalAspectRatio
    : showStoryboardTemplate
      ? String(selectedStoryboardTemplate?.layoutSpec?.sheetAspectRatio || "16:9")
      : canvasProjectAssetAspectRatio(imageEditAssetType) || originalAspectRatio
  const [imageResolution, setImageResolution] = useState(
    initialDraftState.resolution
  )
  const [saving, setSaving] = useState(false)
  const submittedStateRef = useRef({
    useProjectVisual: initialDraftState.submittedUseProjectVisual,
    useOriginal: initialDraftState.submittedUseOriginal,
    hideTurnaroundHeads: initialDraftState.submittedHideTurnaroundHeads,
    prompt: initialDraftState.submittedPrompt.trim(),
    modelId: initialDraftState.submittedModelId.trim(),
    resolution: initialDraftState.submittedResolution.trim(),
  })
  useEffect(() => {
    setDraft(initialDraftState.prompt)
    setUseOriginal(initialDraftState.useOriginal)
    setHideTurnaroundHeads(initialDraftState.hideTurnaroundHeads)
    setUseProjectVisual(initialDraftState.useProjectVisual)
    setImageModelId(initialDraftState.modelId)
    setStoryboardTemplate(initialDraftState.storyboardTemplate)
    setImageResolution(initialDraftState.resolution)
    setReferenceFiles([])
    setSaving(false)
    submittedStateRef.current = {
      useProjectVisual: initialDraftState.submittedUseProjectVisual,
      useOriginal: initialDraftState.submittedUseOriginal,
      hideTurnaroundHeads: initialDraftState.submittedHideTurnaroundHeads,
      prompt: initialDraftState.submittedPrompt.trim(),
      modelId: initialDraftState.submittedModelId.trim(),
      resolution: initialDraftState.submittedResolution.trim(),
    }
  }, [initialDraftState, storageKey])
  useEffect(() => {
    writeImageEditDraftStorage(storageKey, {
      prompt: draft,
      useProjectVisual,
      submittedUseProjectVisual: submittedStateRef.current.useProjectVisual,
      submittedUseOriginal: submittedStateRef.current.useOriginal,
      hideTurnaroundHeads,
      submittedHideTurnaroundHeads: submittedStateRef.current.hideTurnaroundHeads,
      modelId: imageModelId,
      resolution: imageResolution,
      storyboardTemplate,
      submittedPrompt: submittedStateRef.current.prompt,
      submittedModelId: submittedStateRef.current.modelId,
      submittedResolution: submittedStateRef.current.resolution,
    })
  }, [
    draft,
    hideTurnaroundHeads,
    useProjectVisual,
    imageModelId,
    imageResolution,
    storyboardTemplate,
    storageKey,
  ])
  const filePreviews = useMemo(
    () =>
      referenceFiles.map((file, index) => ({
        id: `${file.filePath ?? file.file_path ?? file.path ?? file.name}-${index}`,
        file,
        preview: mediaPreviewSrc(mediaAssetFromImageFile(file)),
      })),
    [referenceFiles]
  )
  const hasEditPrompt = Boolean(draft.trim())
  const modelCapabilityRows = workflowModelCapabilityRows(
    data.modelCapabilitiesSnapshot,
    "image"
  )
  const modelProviderById = new Map<string, string>()
  modelCapabilityRows.forEach((row) => {
    const modelId = workflowModelCapabilityId(row)
    const providerId = workflowModelCapabilityProviderId(row)
    if (modelId && providerId) modelProviderById.set(modelId, providerId)
  })
  const formatModelLabel = workflowModelLabelFormatter(
    data.modelCapabilitiesSnapshot,
    "image"
  )
  const imageModelOptions = modelCapabilityRows.map(workflowModelCapabilityId)
  const imageModelOptionGroups = workflowModelOptionGroups(
    imageModelOptions,
    modelCapabilityRows,
    "image",
    formatModelLabel
  )
  const imageModelSelection = workflowImageEditModelSelection(data, imageModelId || sourceModelId)
  const effectiveImageModelId = imageModelSelection.modelId
  const selectedImageModelCapability = effectiveImageModelId
    ? modelCapabilityRows.find(
        (row) => workflowModelCapabilityId(row) === effectiveImageModelId
      )
    : undefined
  const hasImageReferenceInputs =
    referenceFiles.length > 0 || effectiveUseOriginal
  const rawImageResolutionOptions = stringArrayValue(
    selectedImageModelCapability?.resolutions
  )
  const modelResolutionOptions = filterImageResolutionOptionsForAspect(
    rawImageResolutionOptions,
    imageEditAspectRatio,
    {
      model: selectedImageModelCapability,
      hasReferenceImages: hasImageReferenceInputs,
    }
  )
  useEffect(() => {
    if (!imageResolution || !modelResolutionOptions.length) return
    if (!modelResolutionOptions.some((option) =>
      workflowResolutionOptionMatches("image", modelCapabilityRows, effectiveImageModelId, option, imageResolution)
    )) {
      setImageResolution(modelResolutionOptions[0])
    }
  }, [imageResolution, modelResolutionOptions, modelCapabilityRows, effectiveImageModelId])
  const imageResolutionOptions = presetOptions(
    imageResolution,
    modelResolutionOptions
  )
  const displayImageResolution =
    workflowMatchedResolutionOption(
      "image",
      modelCapabilityRows,
      effectiveImageModelId,
      imageResolutionOptions,
      imageResolution
    ) || imageResolution
  const resolutionLimitSet = normalizedPresetSet(modelResolutionOptions)
  const imageModelProviderId = effectiveImageModelId
    ? (modelProviderById.get(effectiveImageModelId) ?? providerFromModelId(effectiveImageModelId))
    : ""
  const storyboardSizePromptOnly =
    isStoryboardImage &&
    storyboardSizeIsPromptOnlyForGptRelay(
      effectiveImageModelId, imageModelProviderId,
      selectedImageModelCapability?.adapterId
    )
  const imageEditResolvedConfig = useMemo(() => {
    const modelId = effectiveImageModelId
    const providerId = imageModelProviderId.trim()
    const resolution = storyboardSizePromptOnly ? "" : imageResolution.trim()
    const config: Record<string, unknown> = {}
    if (imageModelId.trim()) {
      config.modelId = modelId
      if (providerId) config.providerId = providerId
    }
    if (resolution) {
      config.resolution = resolution
      config.size = resolution
      config.storyboardResolution = resolution
      config.storyboard_resolution = resolution
    }
    return config
  }, [effectiveImageModelId, imageModelId, imageModelProviderId, imageResolution, storyboardSizePromptOnly])
  const hasImageEditResolvedConfig =
    Object.keys(imageEditResolvedConfig).length > 0
  const imageEditOptions = useMemo<WorkflowImageEditOptions>(
    () => ({
      useOriginal: effectiveUseOriginal,
      hideTurnaroundHeads: imageEditAssetType === "characters" ? hideTurnaroundHeads : undefined,
      useProjectVisual: isCustomImage ? useProjectVisual : undefined,
      storyboardTemplate: showStoryboardTemplate ? selectedStoryboardTemplate?.id : undefined,
      modelId: imageModelId.trim() || undefined,
      providerId: imageModelId.trim() ? imageModelProviderId.trim() || undefined : undefined,
      resolution: storyboardSizePromptOnly ? undefined : imageResolution.trim() || undefined,
      resolvedConfig: hasImageEditResolvedConfig
        ? imageEditResolvedConfig
        : undefined,
      allowGenerationConfigOverride: hasImageEditResolvedConfig || undefined,
    }),
    [
      hasImageEditResolvedConfig,
      effectiveUseOriginal,
      imageEditAssetType,
      hideTurnaroundHeads,
      isCustomImage,
      useProjectVisual,
      imageEditResolvedConfig,
      effectiveImageModelId,
      imageModelProviderId,
      imageResolution,
      storyboardSizePromptOnly,
      showStoryboardTemplate,
      selectedStoryboardTemplate?.id,
    ]
  )
  const hasEditChanges =
    !effectiveUseOriginal ||
    useOriginal !== submittedStateRef.current.useOriginal ||
    (imageEditAssetType === "characters" && hideTurnaroundHeads !== submittedStateRef.current.hideTurnaroundHeads) ||
    (isCustomImage && useProjectVisual !== submittedStateRef.current.useProjectVisual) ||
    draft.trim() !== submittedStateRef.current.prompt ||
    imageModelId.trim() !== submittedStateRef.current.modelId ||
    imageResolution.trim() !== submittedStateRef.current.resolution ||
    referenceFiles.length > 0
  const unavailableModelReason = imageModelSelection.unavailableReason
  const canSendEdit = hasEditPrompt && hasEditChanges && !saving && !unavailableModelReason
    && (effectiveUseOriginal || canGenerateEmptyImage)
    && (!showStoryboardTemplate || Boolean(selectedStoryboardTemplate))
  const effectiveMaxHeight = maximized
    ? WORKFLOW_CENTERED_IMAGE_EDITOR_CONTENT_HEIGHT
    : maxHeight
  const imageEditChromeHeight = filePreviews.length > 0 ? 210 : 150
  const imageEditTextareaSize =
    typeof effectiveMaxHeight === "number"
      ? maximized
        ? fixedWorkflowTextareaHeightStyle(
            Math.max(
              148,
              Math.min(460, effectiveMaxHeight - imageEditChromeHeight)
            )
          )
        : {
            maxHeight: Math.max(
              96,
              Math.min(220, effectiveMaxHeight - imageEditChromeHeight)
            ),
          }
      : undefined
  const handlePickFiles = useCallback(async () => {
    const files = await pickLocalImageFiles({
      title: "添加图片",
      multiple: true,
    })
    if (!files.length) return
    setReferenceFiles((current) => {
      const seen = new Set<string>()
      return [...current, ...files].filter((file) => {
        const key = String(file.filePath || file.path || "").replace(/\\/g, "/")
        if (!key) return true
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })
    })
  }, [])
  const handleRemoveFile = useCallback((index: number) => {
    setReferenceFiles((current) =>
      current.filter((_, currentIndex) => currentIndex !== index)
    )
  }, [])
  const handleSend = useCallback(
    async (event: MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation()
      if (!canSendEdit) return
      setSaving(true)
      try {
        if (!data.onSubmitStoryboardImageEdit) return
        const submitResult = await data.onSubmitStoryboardImageEdit(
          id,
          draft.trim(),
          referenceFiles,
          imageEditOptions
        )
        if (submitResult === false) return
        submittedStateRef.current = {
          useOriginal,
          hideTurnaroundHeads,
          useProjectVisual,
          prompt: draft.trim(),
          modelId: imageModelId.trim(),
          resolution: imageResolution.trim(),
        }
        writeImageEditDraftStorage(storageKey, {
          prompt: draft,
          useProjectVisual,
          submittedUseProjectVisual: useProjectVisual,
          submittedUseOriginal: useOriginal,
          hideTurnaroundHeads,
          submittedHideTurnaroundHeads: hideTurnaroundHeads,
          modelId: imageModelId,
          resolution: imageResolution,
          storyboardTemplate,
          submittedPrompt: draft.trim(),
          submittedModelId: imageModelId.trim(),
          submittedResolution: imageResolution.trim(),
        })
        setReferenceFiles([])
      } catch {
        // The submit callback owns user-facing error toasts.
      } finally {
        setSaving(false)
      }
    },
    [
      data,
      draft,
      useOriginal,
      hideTurnaroundHeads,
      useProjectVisual,
      canSendEdit,
      id,
      imageEditOptions,
      imageModelId,
      imageResolution,
      storyboardTemplate,
      referenceFiles,
      storageKey,
    ]
  )

  return (
    <WorkflowEditPanelFrame
      maximized={maximized}
      width={width}
      maxHeight={maxHeight}
      minHeight={
        maximized ? WORKFLOW_CENTERED_IMAGE_EDITOR_MIN_HEIGHT : undefined
      }
      centeredClassName="w-[min(820px,calc(100vw-1.5rem))]"
      onToggleMaximized={onToggleMaximized}
    >
      <div className="flex min-h-0 flex-col gap-2">
        <div className="flex min-w-0 items-center gap-2 pr-8">
          <button
            type="button"
            className="inline-flex h-6 shrink-0 items-center gap-0.5 rounded-[10px] bg-gray-100 px-2 text-[11px] font-medium text-gray-700 transition-colors hover:bg-gray-200 hover:text-gray-950 dark:bg-white/[0.08] dark:text-white/[0.78] dark:hover:bg-white/[0.12] dark:hover:text-white"
            onClick={() => void handlePickFiles()}
          >
            <Plus className="size-3" />
            <span>参考</span>
          </button>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="inline-flex shrink-0" tabIndex={!hasEditableOriginal || saving ? 0 : undefined}>
                <button
                  type="button"
                  aria-label="使用原图"
                  aria-pressed={effectiveUseOriginal}
                  disabled={!hasEditableOriginal || saving}
                  className={cn(
                    "inline-flex h-6 shrink-0 items-center gap-0.5 rounded-[10px] px-2 text-[11px] font-medium transition-colors disabled:pointer-events-none disabled:opacity-60",
                    effectiveUseOriginal
                      ? "bg-indigo-600 text-white hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400"
                      : "bg-gray-100 text-gray-700 hover:bg-gray-200 hover:text-gray-950 dark:bg-white/[0.08] dark:text-white/[0.78] dark:hover:bg-white/[0.12] dark:hover:text-white"
                  )}
                  onClick={() => setUseOriginal((current) => !current)}
                >
                  <ImagePlus className="size-3" />
                  {effectiveUseOriginal ? "参考原图" : "独立新图"}
                </button>
              </span>
            </TooltipTrigger>
            <TooltipContent side="top" sideOffset={6} className="z-[360]">
              {effectiveUseOriginal
                ? "基于原图按描述修改，保留未要求修改的内容。"
                : hasEditableOriginal ? "按描述生成新图片。" : "当前没有原图，按描述生成新图片。"}
            </TooltipContent>
          </Tooltip>
          {imageEditAssetType === "characters" ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex shrink-0" tabIndex={saving ? 0 : undefined}>
                  <button
                    type="button"
                    aria-label="三视图显示头部"
                    aria-pressed={!hideTurnaroundHeads}
                    disabled={saving}
                    className={cn(
                      "inline-flex h-6 shrink-0 items-center gap-0.5 rounded-[10px] px-2 text-[11px] font-medium transition-colors disabled:pointer-events-none disabled:opacity-60",
                      !hideTurnaroundHeads
                        ? "bg-indigo-600 text-white hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400"
                        : "bg-gray-100 text-gray-700 hover:bg-gray-200 hover:text-gray-950 dark:bg-white/[0.08] dark:text-white/[0.78] dark:hover:bg-white/[0.12] dark:hover:text-white"
                    )}
                    onClick={() => setHideTurnaroundHeads((current) => !current)}
                  >
                    {hideTurnaroundHeads ? <Shirt className="size-3" /> : <UserRound className="size-3" />}
                    {hideTurnaroundHeads ? "无头" : "有头"}
                  </button>
                </span>
              </TooltipTrigger>
              <TooltipContent side="top" sideOffset={6} className="z-[360]">
                {hideTurnaroundHeads
                  ? "三视图仅去掉头部，保留颈部及以下；左侧主图不变。"
                  : "三视图保留完整头部和颈部。"}
              </TooltipContent>
            </Tooltip>
          ) : null}
          {isCustomImage && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  aria-label="使用项目视觉"
                  aria-pressed={useProjectVisual}
                  disabled={saving}
                  className={cn(
                    "inline-flex h-6 shrink-0 items-center rounded-[10px] px-2 text-[11px] font-medium transition-colors disabled:opacity-60",
                    useProjectVisual
                      ? "bg-indigo-600 text-white hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400"
                      : "bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-white/[0.08] dark:text-white/[0.78] dark:hover:bg-white/[0.12]"
                  )}
                  onClick={() => setUseProjectVisual((current) => !current)}
                >
                  项目视觉
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" sideOffset={6} className="z-[360]">
                开启后使用当前项目的主题视觉和视觉风格；关闭后按本次要求和所选图片生成
              </TooltipContent>
            </Tooltip>
          )}
        </div>
        {filePreviews.length > 0 ? (
          <div className="flex min-w-0 items-center gap-2 overflow-x-auto pb-1">
            {filePreviews.map((item, index) => (
              <div
                key={item.id}
                className="group relative size-14 shrink-0 overflow-hidden rounded-md border border-gray-200 bg-gray-100 dark:border-white/10 dark:bg-black/30"
              >
                {item.preview ? (
                  <img
                    src={item.preview}
                    alt={item.file.name || "参考图"}
                    className="h-full w-full object-cover"
                    draggable={false}
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-[10px] text-gray-400">
                    图片
                  </div>
                )}
                <button
                  type="button"
                  className="absolute top-1 right-1 flex size-5 items-center justify-center rounded-full bg-black/65 text-white opacity-90 transition hover:bg-black"
                  onClick={() => handleRemoveFile(index)}
                >
                  <X className="size-3" />
                </button>
              </div>
            ))}
          </div>
        ) : null}
        <Textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onPointerDown={(event) => event.stopPropagation()}
          onWheel={stopCardWheel}
          onWheelCapture={stopCardWheel}
          placeholder={
            showStoryboardTemplate
              ? "描述分镜内容、镜头数量和画面要求，将按所选版式生成"
              : effectiveUseOriginal ? "描述要修改的内容" : "描述图片生成要求"
          }
          aria-label={effectiveUseOriginal ? "修改图片" : "生成图片"}
          className={compactWorkflowTextareaClassName("min-h-[116px]")}
          style={imageEditTextareaSize}
          spellCheck={false}
        />
        <div className="flex min-h-9 items-center justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            {showStoryboardTemplate ? (
              <WorkflowCompactParameterMenu
                label="版式"
                value={selectedStoryboardTemplate?.id ?? ""}
                options={storyboardTemplates.map((template) => template.id)}
                formatLabel={(templateId) => storyboardTemplateDisplayName(storyboardTemplates.find((template) => template.id === templateId))}
                formatDescription={(templateId) => storyboardTemplateDisplayDescription(storyboardTemplates.find((template) => template.id === templateId))}
                disabled={saving || !storyboardTemplates.length}
                emptyLabel="未加载版式"
                onChange={(templateId) => {
                  setStoryboardTemplate(templateId)
                  const nextTemplate = storyboardTemplates.find((template) => template.id === templateId)
                  const nextResolutions = filterImageResolutionOptionsForAspect(
                    rawImageResolutionOptions,
                    String(nextTemplate?.layoutSpec?.sheetAspectRatio || "16:9"),
                    {
                      model: selectedImageModelCapability,
                      hasReferenceImages: hasImageReferenceInputs,
                    }
                  )
                  if (imageResolution && !nextResolutions.some((option) =>
                    workflowResolutionOptionMatches("image", modelCapabilityRows, effectiveImageModelId, option, imageResolution)
                  )) {
                    setImageResolution(nextResolutions[0] ?? "")
                  }
                }}
              />
            ) : null}
            <WorkflowCompactParameterMenu
              label="模型"
              value={imageModelId}
              options={imageModelOptions}
              optionGroups={imageModelOptionGroups}
              includeCurrentValue={false}
              emptyLabel={effectiveImageModelId ? formatModelLabel(effectiveImageModelId) : "未配置"}
              allowUnset
              unsetLabel={sourceModelId ? "自动跟随来源卡片" : "自动跟随全局设置"}
              formatLabel={formatModelLabel}
              disabledReason={(value) => value ? workflowImageEditModelSelection(data, value).unavailableReason : ""}
              onChange={(nextModelId) => {
                setImageModelId(nextModelId)
                if (!nextModelId.trim()) return
                const nextModelCapability = modelCapabilityRows.find(
                  (row) => workflowModelCapabilityId(row) === nextModelId
                )
                const rawNextResolutions = stringArrayValue(
                  nextModelCapability?.resolutions
                )
                const nextResolutions = filterImageResolutionOptionsForAspect(
                  rawNextResolutions,
                  imageEditAspectRatio,
                  {
                    model: nextModelCapability,
                    hasReferenceImages: hasImageReferenceInputs,
                  }
                )
                if (imageResolution && nextResolutions.length) {
                  const currentSupported = nextResolutions.some((option) =>
                    workflowResolutionOptionMatches(
                      "image",
                      modelCapabilityRows,
                      nextModelId,
                      option,
                      imageResolution
                    )
                  )
                  if (!currentSupported) {
                    const defaultResolution = String(
                      nextModelCapability?.defaultResolution ?? ""
                    ).trim()
                    const matchedDefault = nextResolutions.find((option) =>
                      workflowResolutionOptionMatches(
                        "image",
                        modelCapabilityRows,
                        nextModelId,
                        option,
                        defaultResolution
                      )
                    )
                    setImageResolution(matchedDefault ?? nextResolutions[0])
                  }
                }
              }}
            />
            {!storyboardSizePromptOnly ? (
              <WorkflowCompactParameterMenu
                label="尺寸"
                value={displayImageResolution}
                options={imageResolutionOptions}
                emptyLabel="跟随全局设置"
                allowUnset
                unsetLabel="跟随全局设置"
                formatLabel={(option) =>
                  workflowModelResolutionLabel(
                    "image",
                    modelCapabilityRows,
                    effectiveImageModelId,
                    option
                  )
                }
                formatDescription={(option) =>
                  workflowModelResolutionDescription(
                    "image",
                    modelCapabilityRows,
                    effectiveImageModelId,
                    option
                  )
                }
                disabledReason={(option) =>
                  option ? limitedOptionReason(option, resolutionLimitSet) : ""
                }
                onChange={(nextResolution) => {
                  setImageResolution(nextResolution)
                }}
              />
            ) : null}
          </div>
          <button
            type="button"
            aria-label={saving ? "正在运行" : "发送修改"}
            className="flex size-9 shrink-0 items-center justify-center rounded-md bg-gray-950 text-white transition-colors hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500 dark:bg-white dark:text-gray-950 dark:hover:bg-gray-100 dark:disabled:bg-white/15 dark:disabled:text-white/35"
            disabled={!canSendEdit}
            title={unavailableModelReason || undefined}
            onClick={(event) => void handleSend(event)}
          >
            {saving ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Send className="size-4" />
            )}
          </button>
        </div>
      </div>
    </WorkflowEditPanelFrame>
  )
}

function cssAttributeValue(value: string) {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')
}

function StoryboardImageEditFloatingPanel({
  node,
  sourceModelId,
  hidden,
}: {
  node?: StoryboardNodeLike
  sourceModelId: string
  hidden: boolean
}) {
  const nodeId = node?.id ?? ""
  const [maximized, setMaximized] = useState(false)
  const getAnchor = useCallback(() => {
    if (!nodeId || typeof document === "undefined") return null
    return document.querySelector<HTMLElement>(
      `.react-flow__node[data-id="${cssAttributeValue(nodeId)}"]`
    )
  }, [nodeId])
  const panelRect = useWorkflowFloatingPanelRect(
    Boolean(node && !hidden),
    WORKFLOW_FLOATING_EDIT_PANEL_WIDTH,
    getAnchor,
    nodeId,
    WORKFLOW_FLOATING_IMAGE_EDITOR_PREFERRED_HEIGHT
  )

  useEffect(() => {
    setMaximized(false)
  }, [nodeId])

  if (!node || typeof document === "undefined") return null

  const panelWidth = panelRect?.width ?? WORKFLOW_FLOATING_EDIT_PANEL_WIDTH
  const panelMaxHeight = maximized
    ? WORKFLOW_CENTERED_IMAGE_EDITOR_CONTENT_HEIGHT
    : panelRect?.maxHeight
  const handlePanelBackdropPointerDown = (
    event: PointerEvent<HTMLDivElement>
  ) => {
    event.stopPropagation()
    if (maximized && event.target === event.currentTarget) {
      setMaximized(false)
    }
  }

  return createPortal(
    <div
      data-workflow-task-parameter-panel
      className={cn(
        "nodrag nopan nowheel fixed",
        maximized
          ? "inset-0 z-[300] flex items-center justify-center bg-black/45 p-3 backdrop-blur-sm sm:p-5"
          : "z-[130]"
      )}
      style={{
        // Temporary canvas movement hides the panel without ending its edit session.
        display: hidden || (!maximized && !panelRect) ? "none" : undefined,
        ...(!maximized && panelRect
          ? {
              left: panelRect.left,
              top: panelRect.top,
              width: panelRect.width,
              transform: panelRect.transform,
            }
          : {}),
      }}
      onPointerDown={handlePanelBackdropPointerDown}
      onClick={(event) => event.stopPropagation()}
      onWheel={stopCardWheel}
      onWheelCapture={stopCardWheel}
    >
      <WorkflowStoryboardImageEditPanel
        key={node.id}
        id={node.id}
        data={node.data}
        sourceModelId={sourceModelId}
        width={panelWidth}
        maxHeight={panelMaxHeight}
        maximized={maximized}
        onToggleMaximized={() => setMaximized((current) => !current)}
      />
    </div>,
    document.body
  )
}

export { WorkflowStoryboardImageEditPanel, StoryboardImageEditFloatingPanel }
