import { isWorkflowVideoTaskType } from "./workflow-video-task-types"
import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react"
import { Loader2, WandSparkles } from "lucide-react"
import { toast } from "sonner"
import { errMsg } from "@/shared/backend-result"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { storyboardTemplateDisplayDescription } from "@/features/settings/storyboard-templates"
import {
  InlineSaveControls,
  WorkflowCompactParameterMenu,
} from "./workflow-inline-controls"
import {
  VIDEO_DURATION_OPTIONS,
  workflowPreferredVideoDurationValue,
  workflowVideoTaskDefaultDurationValue,
  providerFromModelId,
  configPrivateStringValue,
  workflowSnapshotConfiguredModelId,
  presetOptions,
  normalizedPresetSet,
  limitedOptionReason,
  workflowMatchedResolutionOption,
  workflowModelCapabilityId,
  workflowModelCapabilityProviderId,
  workflowModelCapabilityRows,
  workflowModelUnavailableReason,
  workflowVideoModelSupportsTask,
  workflowModelDurationOptions,
  workflowModelLabelFormatter,
  workflowModelOptionGroups,
  workflowModelResolutionDescription,
  workflowModelResolutionLabel,
  workflowResolutionOptionMatches,
} from "./workflow-model-capabilities"
import {
  workflowHasImageReferenceInputLinks,
  workflowVideoTaskSelectedDurationValue,
} from "./workflow-input-readiness"
import { filterImageResolutionOptionsForAspect, storyboardSizeIsPromptOnlyForGptRelay } from "@/utils/model-resolution"
import type { StoryboardTemplateOption } from "@/backend"

type WorkflowNodeData = {
  [key: string]: any
  eyebrow?: string
  status: any
  generationConfig?: unknown
  resolvedConfig?: unknown
  modelCapabilitiesSnapshot?: any
  prompt?: unknown
  durationSeconds?: unknown
  videoTaskCard?: unknown
}

const WORKFLOW_SAVE_BUTTON_CLASS = "h-8 gap-1.5 bg-white/55 text-xs dark:bg-white/5"
const WORKFLOW_INLINE_PARAMETER_BAR_CLASS = "sticky bottom-0 z-10 border-t border-gray-200/80 bg-transparent pt-2 dark:border-white/[0.08]"
const WORKFLOW_INLINE_PARAMETER_ROW_CLASS = "flex min-h-8 flex-wrap items-center gap-1.5"

type ManualSaveOptions = {
  successMessage?: string
  showSuccess?: boolean
}

function recordValue(value: unknown): Record<string, any> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, any>)
    : {}
}

function compactReadableValue(value: unknown) {
  if (value == null) return ""
  if (typeof value === "string") return value.trim()
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  return ""
}


function isDirectorBoardNodeType(value?: string | null) {
  return value === "director.board"
}

function workflowNodeOwnsGenerationConfig(value?: string | null) {
  return isDirectorBoardNodeType(value) || value === "storyboard.card" || isWorkflowVideoTaskType(value)
}

function workflowNodeUsesStoryboardTemplate(value?: string | null) {
  return value === "storyboard.card"
}

function stringArrayValue(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item ?? "").trim()).filter(Boolean) : []
}

function workflowStoryboardTemplates(data: WorkflowNodeData) {
  return Array.isArray(data.storyboardTemplates) && data.storyboardTemplates.length
    ? data.storyboardTemplates
    : []
}

function storyboardTemplateId(value: unknown, templates: any[] = []) {
  const text = String(value ?? "").trim()
  if (!text) return String(templates[0]?.id ?? "")
  const normalized = text.toLocaleLowerCase()
  const matched = templates.find((template) =>
    [template.id, template.label, template.name].some(
      (candidate) => String(candidate ?? "").trim().toLocaleLowerCase() === normalized
    )
  )
  return String(matched?.id ?? text)
}

function storyboardTemplateValue(data: WorkflowNodeData, templates = workflowStoryboardTemplates(data)) {
  const cardState = recordValue(data.cardState)
  const configured = compactReadableValue(
    data.storyboardTemplate ??
      cardState.template ??
      cardState.templateId ??
      data.storyboardTemplateLabel
  )
  return configured || compactReadableValue(templates[0]?.id)
}

function storyboardTemplateLabel(value: string, templates: any[]) {
  const id = storyboardTemplateId(value, templates)
  const match = templates.find((template) => String(template?.id ?? template?.value ?? "") === id)
  return compactReadableValue(match?.label ?? match?.name ?? value)
}

function storyboardTemplateDescription(value: unknown, templates: StoryboardTemplateOption[] = []) {
  const id = storyboardTemplateId(value, templates)
  const template = templates.find((option) => option.id === id)
  return template ? storyboardTemplateDisplayDescription(template) : ""
}

function workflowVideoTaskInputDurationValue(data?: WorkflowNodeData | null) {
  if (!data) return ""
  const card = recordValue(data.videoTaskCard)
  const value = Number(data.durationSeconds ?? card.durationSeconds)
  return Number.isFinite(value) && value > 0 ? String(value) : ""
}

function mergeWorkflowInlineDataPatches(...patches: Array<Record<string, any> | undefined>) {
  return Object.assign({}, ...patches.filter(Boolean))
}

function InlineGenerationControls({
  id,
  data,
  promptDirty = false,
  promptError = "",
  promptPatch,
  promptReason,
  extraParameterControls,
  extraEditDirty = false,
  onCancelExtraEdit,
  onSaveExtraEdit,
  saving: externalSaving = false,
  onSavingChange,
  onCancelPrompt,
  onSavePrompt,
  promptDraft,
  soundPromptDraft,
  promptAssetNameMap = {},
  promptBindings = {},
  onOptimizationQueued,
  onPrepareOptimization,
  maximized = false,
}: {
  id: string
  data: WorkflowNodeData
  promptDirty?: boolean
  promptError?: string
  promptPatch?: Partial<WorkflowNodeData>
  promptReason?: string
  promptDraft?: string
  soundPromptDraft?: string
  promptAssetNameMap?: Record<string, string>
  promptBindings?: Record<string, string>
  onOptimizationQueued?: () => void
  onPrepareOptimization?: () => Promise<void>
  extraParameterControls?: ReactNode
  extraEditDirty?: boolean
  onCancelExtraEdit?: () => void
  onSaveExtraEdit?: () => Promise<void> | void
  saving?: boolean
  onSavingChange?: (saving: boolean) => void
  onCancelPrompt?: (event: MouseEvent<HTMLButtonElement>) => void
  onSavePrompt?: (
    event: MouseEvent<HTMLButtonElement>,
    options?: ManualSaveOptions
  ) => Promise<void> | void
  maximized?: boolean
}) {
  const [localSaving, setLocalSaving] = useState(false)
  const [optimizing, setOptimizing] = useState(false)
  const optimizationEpoch = useRef(0)
  useEffect(() => {
    optimizationEpoch.current++
    setOptimizing(false)
    return () => { optimizationEpoch.current++ }
  }, [id])
  const saving = externalSaving || localSaving
  const setSavingState = (nextSaving: boolean) => {
    setLocalSaving(nextSaving)
    onSavingChange?.(nextSaving)
  }
  const canConfigure = workflowNodeOwnsGenerationConfig(data.eyebrow)
  const config = recordValue(data.generationConfig)
  const resolvedConfig = recordValue(data.resolvedConfig)
  const isVideo = isWorkflowVideoTaskType(data.eyebrow)
  const isReplacement = data.eyebrow === "video.character_replace"
  const savedReplacementSubject = String(config.replacementSubject || "person").trim() || "person"
  const [replacementSubject, setReplacementSubject] = useState(savedReplacementSubject)
  const normalizedReplacementSubject = replacementSubject.trim() || "person"
  useEffect(() => { setReplacementSubject(savedReplacementSubject) }, [id, savedReplacementSubject])
  const isDirectorBoard = isDirectorBoardNodeType(data.eyebrow)
  const mediaType = isVideo ? "video" : "image"
  const [modelId, setModelId] = useState(() =>
    configPrivateStringValue(config, ["modelId", "model_id"])
  )
  const [providerId, setProviderId] = useState(() => {
    const initialModelId = configPrivateStringValue(config, [
      "modelId",
      "model_id",
    ])
    return (
      configPrivateStringValue(config, ["providerId", "provider_id"]) ||
      providerFromModelId(initialModelId)
    )
  })
  const [resolution, setResolution] = useState(() =>
    configPrivateStringValue(config, isVideo ? ["resolution"] : ["resolution", "size"])
  )
  const [duration, setDuration] = useState(() =>
    workflowVideoTaskSelectedDurationValue(data)
  )
  const storyboardTemplatesForNode = workflowStoryboardTemplates(data)
  const [storyboardTemplate, setStoryboardTemplate] = useState(() =>
    storyboardTemplateValue(data, storyboardTemplatesForNode)
  )
  const savedModelId = configPrivateStringValue(config, ["modelId", "model_id"])
  const savedProviderId = configPrivateStringValue(config, ["providerId", "provider_id"]) || providerFromModelId(savedModelId)
  const savedResolution = configPrivateStringValue(config, isVideo ? ["resolution"] : ["resolution", "size"])
  const savedDuration = workflowVideoTaskSelectedDurationValue(data)
  const savedTemplate = storyboardTemplateValue(data, storyboardTemplatesForNode)

  useEffect(() => { setModelId(savedModelId) }, [id, savedModelId])
  useEffect(() => { setProviderId(savedProviderId) }, [id, savedProviderId])
  useEffect(() => { setResolution(savedResolution) }, [id, savedResolution])
  useEffect(() => { setDuration(savedDuration) }, [id, savedDuration])
  useEffect(() => { setStoryboardTemplate(savedTemplate) }, [id, savedTemplate])

  if (!canConfigure) return null

  const allModelCapabilityRows = workflowModelCapabilityRows(
    data.modelCapabilitiesSnapshot,
    mediaType
  )
  const modelCapabilityRows = allModelCapabilityRows.filter((row) =>
    !isVideo || workflowVideoModelSupportsTask(row, data.eyebrow)
  )
  const modelProviderById = new Map<string, string>()
  modelCapabilityRows.forEach((row) => {
    const id = workflowModelCapabilityId(row)
    const provider = workflowModelCapabilityProviderId(row)
    if (id && provider) modelProviderById.set(id, provider)
  })
  const formatModelLabel = workflowModelLabelFormatter(
    data.modelCapabilitiesSnapshot,
    mediaType
  )
  const modelOptions = modelCapabilityRows.map(workflowModelCapabilityId)
  const modelOptionGroups = workflowModelOptionGroups(
    modelOptions,
    modelCapabilityRows,
    mediaType,
    formatModelLabel
  )
  const fallbackModelId = workflowSnapshotConfiguredModelId(data.modelCapabilitiesSnapshot, mediaType, data.eyebrow)
  const effectiveModelId = modelId || fallbackModelId
  const selectedModelCapability = effectiveModelId
    ? modelCapabilityRows.find(
        (row) => workflowModelCapabilityId(row) === effectiveModelId
      )
    : undefined
  const storyboardSizePromptOnly =
    data.eyebrow === "storyboard.card" &&
    storyboardSizeIsPromptOnlyForGptRelay(
      effectiveModelId,
      modelProviderById.get(effectiveModelId) ?? providerFromModelId(effectiveModelId),
      selectedModelCapability?.adapterId
    )
  const hasImageReferenceInputs =
    !isVideo &&
    (stringArrayValue(data.referenceMediaIds).length > 0 ||
      stringArrayValue(config.referenceMediaIds).length > 0 ||
      stringArrayValue(config.reference_media_ids).length > 0 ||
      stringArrayValue(resolvedConfig.referenceMediaIds).length > 0 ||
      stringArrayValue(resolvedConfig.reference_media_ids).length > 0 ||
      workflowHasImageReferenceInputLinks(data.inputLinks))
  const rawModelResolutionOptions = stringArrayValue(
    selectedModelCapability?.resolutions
  )
  const modelResolutionOptions = isVideo
    ? rawModelResolutionOptions
    : filterImageResolutionOptionsForAspect(rawModelResolutionOptions, "16:9", {
        model: selectedModelCapability,
        hasReferenceImages: hasImageReferenceInputs,
        includeAllAspects: data.eyebrow === "storyboard.card",
      })
  const resolutionOptions = isVideo
    ? presetOptions(resolution, modelResolutionOptions)
    : modelResolutionOptions
  const displayResolution =
    workflowMatchedResolutionOption(
      mediaType,
      modelCapabilityRows,
      modelId,
      resolutionOptions,
      resolution
    ) || (isVideo ? resolution : "")
  const resolutionLimitSet = normalizedPresetSet(modelResolutionOptions)
  const modelDurationOptions = workflowModelDurationOptions(
    selectedModelCapability, data.eyebrow === "video.keyframe"
  )
  const durationOptions = modelDurationOptions.length
    ? modelDurationOptions
    : VIDEO_DURATION_OPTIONS
  const durationLimitSet = normalizedPresetSet(modelDurationOptions)
  const defaultVideoDuration = isVideo
    ? workflowVideoTaskDefaultDurationValue(data)
    : ""
  const savedStoryboardTemplate = storyboardTemplateValue(
    data,
    storyboardTemplatesForNode
  )
  const parametersDirty =
    modelId !== savedModelId ||
    providerId !== savedProviderId ||
    resolution !== savedResolution ||
    (isReplacement && normalizedReplacementSubject !== savedReplacementSubject)
  const durationDirty = isVideo && duration !== savedDuration
  const templateDirty =
    workflowNodeUsesStoryboardTemplate(data.eyebrow) &&
    storyboardTemplate !== savedStoryboardTemplate

  const handleReset = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    setModelId(savedModelId)
    setProviderId(savedProviderId)
    setResolution(savedResolution)
    setDuration(savedDuration)
    setStoryboardTemplate(savedStoryboardTemplate)
    setReplacementSubject(savedReplacementSubject)
  }

  const buildGenerationConfigPatch = (
    overrides: Partial<{
      modelId: string
      providerId: string
      resolution: string
    }> = {}
  ) => {
    const draftModelId = overrides.modelId ?? modelId
    const draftProviderId = overrides.providerId ?? providerId
    const effectiveDraftModelId = draftModelId || fallbackModelId
    const effectiveDraftProviderId = draftProviderId ||
      modelProviderById.get(effectiveDraftModelId) || providerFromModelId(effectiveDraftModelId)
    const draftModelCapability = modelCapabilityRows.find(
      (row) => workflowModelCapabilityId(row) === effectiveDraftModelId
    )
    const draftResolution = data.eyebrow === "storyboard.card" &&
      storyboardSizeIsPromptOnlyForGptRelay(
        effectiveDraftModelId, effectiveDraftProviderId,
        draftModelCapability?.adapterId
      )
      ? ""
      : overrides.resolution ?? resolution
    const nextConfig: Record<string, unknown> = {}
    if (isReplacement) {
      nextConfig.replacementSubject = normalizedReplacementSubject
      if (!draftModelId && effectiveDraftModelId) nextConfig.modelId = effectiveDraftModelId
    }
    if (draftModelId !== savedModelId) {
      if (draftModelId.trim()) {
        nextConfig.modelId = draftModelId.trim()
      } else {
        nextConfig.modelId = null
        nextConfig.model_id = null
      }
    }
    if (
      draftProviderId !== savedProviderId ||
      (draftModelId !== savedModelId && !draftModelId.trim())
    ) {
      if (draftProviderId.trim() && draftModelId.trim()) {
        nextConfig.providerId = draftProviderId.trim()
      } else {
        nextConfig.providerId = null
        nextConfig.provider_id = null
      }
    }
    if (draftResolution !== savedResolution) {
      if (draftResolution.trim()) {
        nextConfig.resolution = draftResolution.trim()
        if (!isVideo) nextConfig.size = draftResolution.trim()
      } else {
        nextConfig.resolution = null
        if (!isVideo) nextConfig.size = null
      }
    }
    return nextConfig
  }

  const buildDurationPatch = () => {
    if (!isVideo || (!durationDirty && workflowVideoTaskInputDurationValue(data))) return undefined
    const trimmedDuration = duration.trim()
    const selectedDuration =
      trimmedDuration || workflowVideoTaskDefaultDurationValue(data)
    const numericDuration = Number(selectedDuration)
    const selectedDurationValue =
      Number.isFinite(numericDuration) && numericDuration > 0
        ? numericDuration
        : selectedDuration
    return {
      durationSeconds: selectedDurationValue,
      videoTaskCard: {
        durationSeconds: selectedDurationValue,
      },
    }
  }

  const handleResetAll = (event: MouseEvent<HTMLButtonElement>) => {
    if (parametersDirty || durationDirty || templateDirty) {
      handleReset(event)
    } else {
      event.stopPropagation()
    }
    if (promptDirty) onCancelPrompt?.(event)
    if (extraEditDirty) onCancelExtraEdit?.()
  }

  const handleSaveAll = async (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    const unavailableReason = modelId.trim()
      ? workflowModelUnavailableReason(data.modelCapabilitiesSnapshot, mediaType, modelId)
      : ""
    if (parametersDirty && unavailableReason) {
      toast.error(unavailableReason)
      return
    }
    if (promptDirty && promptError) {
      toast.error(promptError)
      return
    }
    if (
      saving ||
      (!parametersDirty && !durationDirty && !promptDirty && !templateDirty && !extraEditDirty)
    )
      return
    setSavingState(true)
    try {
      const durationPatch = buildDurationPatch()
      const generationConfigPatch = parametersDirty || durationPatch
        ? {
            ...(parametersDirty ? buildGenerationConfigPatch() : {}),
            ...(durationPatch ? { durationSeconds: durationPatch.durationSeconds } : {}),
          }
        : undefined
      const templatePatch: Partial<WorkflowNodeData> | undefined = templateDirty
        ? {
            storyboardTemplate,
            storyboardTemplateLabel: storyboardTemplateLabel(
              storyboardTemplate,
              storyboardTemplatesForNode
            ),
            cardState: {
              template: storyboardTemplate,
              templateLabel: storyboardTemplateLabel(
                storyboardTemplate,
                storyboardTemplatesForNode
              ),
            },
            ...(isDirectorBoard
              ? {
                  directorTaskCard: {
                    storyboardTemplate,
                    storyboardTemplateLabel: storyboardTemplateLabel(
                      storyboardTemplate,
                      storyboardTemplatesForNode
                    ),
                    template: storyboardTemplate,
                    templateLabel: storyboardTemplateLabel(
                      storyboardTemplate,
                      storyboardTemplatesForNode
                    ),
                  },
                }
              : {}),
          }
        : undefined
      const dataPatch = mergeWorkflowInlineDataPatches(
        promptDirty && promptPatch ? promptPatch : undefined,
        templatePatch,
        durationPatch
      )
      if (data.onSaveInlineEdit && (generationConfigPatch || dataPatch)) {
        const backgroundSave = isDirectorBoard || data.eyebrow === "storyboard.card"
        const save = data.onSaveInlineEdit(
          id,
          {
            data: dataPatch,
            generationConfig: generationConfigPatch,
            reason: promptDirty
              ? promptReason
              : templateDirty
                ? "inline_storyboard_template_saved"
                : durationDirty
                  ? "inline_video_duration_saved"
                  : "inline_generation_config_saved",
          },
          backgroundSave ? { showSuccess: false } : { successMessage: "修改已保存" }
        )
        if (backgroundSave) {
          // These cards acknowledge their optimistic patch immediately. The
          // canvas write queue owns persistence, reconciliation and failures.
          void Promise.resolve(save).catch(() => undefined)
        } else {
          await save
        }
      } else {
        if (promptDirty) {
          await onSavePrompt?.(event, { successMessage: "修改已保存" })
        }
      }
      if (extraEditDirty) await onSaveExtraEdit?.()
    } catch {
      // The save callbacks own user-facing error toasts.
    } finally {
      setSavingState(false)
    }
  }

  const handleOptimize = async (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    if (optimizing || saving || !promptDraft?.trim() || !data.onOptimizeVideoPrompt) return
    const epoch = optimizationEpoch.current
    setOptimizing(true)
    try {
      await onPrepareOptimization?.()
      if (epoch !== optimizationEpoch.current) return
      const accepted = await data.onOptimizeVideoPrompt(id, {
        draftText: promptDraft,
        soundPrompt: soundPromptDraft,
        assetNameMap: promptAssetNameMap,
        promptBindings,
      })
      if (accepted && epoch === optimizationEpoch.current) onOptimizationQueued?.()
    } catch (error) {
      const notified = error instanceof Error && "taskFailureNotified" in error && error.taskFailureNotified
      if (epoch === optimizationEpoch.current && !notified) toast.error(errMsg(error, "优化提示词失败"))
    } finally {
      if (epoch === optimizationEpoch.current) setOptimizing(false)
    }
  }

  return (
    <div className={cn("nodrag nopan", maximized ? "shrink-0" : "mt-2")}>
      <div
        className={cn(
          WORKFLOW_INLINE_PARAMETER_BAR_CLASS,
          maximized && "border-t-0 pt-0"
        )}
      >
        <div className={WORKFLOW_INLINE_PARAMETER_ROW_CLASS}>
          <WorkflowCompactParameterMenu
            label={isReplacement ? "替换模式" : "模型"}
            value={modelId}
            options={modelOptions}
            optionGroups={modelOptionGroups}
            includeCurrentValue={false}
            emptyLabel={effectiveModelId ? formatModelLabel(effectiveModelId) : "未配置"}
            allowUnset={!isReplacement}
            unsetLabel="自动跟随全局设置"
            formatLabel={formatModelLabel}
            disabledReason={(value) => value ? workflowModelUnavailableReason(data.modelCapabilitiesSnapshot, mediaType, value) : ""}
            disabled={saving}
            onChange={(nextModelId) => {
              setModelId(nextModelId)
              const nextProviderId = nextModelId.trim()
                ? modelProviderById.get(nextModelId) ?? providerFromModelId(nextModelId)
                : ""
              setProviderId(nextProviderId)
              const nextEffectiveModelId = nextModelId.trim() || fallbackModelId
              const nextModelCapability = modelCapabilityRows.find(
                (row) => workflowModelCapabilityId(row) === nextEffectiveModelId
              )
              const rawNextResolutions = stringArrayValue(
                nextModelCapability?.resolutions
              )
              const nextResolutions = isVideo
                ? rawNextResolutions
                : filterImageResolutionOptionsForAspect(
                    rawNextResolutions,
                    "16:9",
                    {
                      model: nextModelCapability,
                      hasReferenceImages: hasImageReferenceInputs,
                      includeAllAspects: data.eyebrow === "storyboard.card",
                    }
                  )
              if (nextResolutions.length && (isVideo || resolution)) {
                const matchedCurrent = nextResolutions.find((option) =>
                  workflowResolutionOptionMatches(
                    mediaType,
                    modelCapabilityRows,
                    nextEffectiveModelId,
                    option,
                    resolution
                  )
                )
                if (!matchedCurrent) {
                  const defaultResolution = String(
                    nextModelCapability?.defaultResolution ?? ""
                  ).trim()
                  const matchedDefault = nextResolutions.find((option) =>
                    workflowResolutionOptionMatches(
                      mediaType,
                      modelCapabilityRows,
                      nextEffectiveModelId,
                      option,
                      defaultResolution
                    )
                  )
                  setResolution(matchedDefault ?? nextResolutions[0])
                } else if (isVideo) {
                  // Persist the model's API option, not a matching display alias.
                  setResolution(matchedCurrent)
                }
              } else if (isVideo || resolution) {
                setResolution("")
              }
              const nextDurations =
                workflowModelDurationOptions(nextModelCapability, data.eyebrow === "video.keyframe")
              const nextDurationLimitSet = normalizedPresetSet(nextDurations)
              const currentDurationSupported =
                !nextDurations.length ||
                nextDurationLimitSet.has(duration.trim().toLowerCase())
              if (!duration.trim() || !currentDurationSupported) {
                setDuration(
                  workflowPreferredVideoDurationValue(
                    nextDurations.length
                      ? nextDurations
                      : VIDEO_DURATION_OPTIONS
                  )
                )
              }
            }}
          />
          {isReplacement && Number(selectedModelCapability?.maxReferenceImages) > 1 ? (
            <label className="flex items-center gap-1 text-[11px] text-gray-500 dark:text-white/50">
              替换对象
              <input aria-label="替换对象" title="识别源视频中要替换的对象类型，默认 person（人物）"
                className="nodrag w-20 rounded border bg-transparent px-1.5 py-1" maxLength={100}
                value={replacementSubject} disabled={saving}
                onChange={(event) => setReplacementSubject(event.target.value)} />
            </label>
          ) : null}
          {workflowNodeUsesStoryboardTemplate(data.eyebrow) ? (
            <WorkflowCompactParameterMenu
              label="版式"
              value={storyboardTemplate}
              options={presetOptions(
                storyboardTemplate,
                storyboardTemplatesForNode.map((template) => template.id)
              )}
              formatLabel={(templateId) =>
                storyboardTemplateLabel(templateId, storyboardTemplatesForNode)
              }
              formatDescription={(templateId) =>
                storyboardTemplateDescription(
                  templateId,
                  storyboardTemplatesForNode
                )
              }
              disabled={saving || !storyboardTemplatesForNode.length}
              emptyLabel="未加载版式"
              onChange={(nextValue) => {
                const nextTemplate = storyboardTemplateId(
                  nextValue,
                  storyboardTemplatesForNode
                )
                setStoryboardTemplate(nextTemplate)
              }}
            />
          ) : null}
          {!storyboardSizePromptOnly ? (
            <WorkflowCompactParameterMenu
              label={isVideo || isDirectorBoard ? "分辨率" : "尺寸"}
              value={displayResolution}
              options={resolutionOptions}
              includeCurrentValue={false}
              emptyLabel="跟随全局设置"
              allowUnset
              unsetLabel="跟随全局设置"
              disabled={saving}
              formatLabel={(option) =>
                workflowModelResolutionLabel(
                  isVideo ? "video" : "image",
                  modelCapabilityRows,
                  effectiveModelId,
                  option
                )
              }
              formatDescription={(option) =>
                workflowModelResolutionDescription(
                  isVideo ? "video" : "image",
                  modelCapabilityRows,
                  effectiveModelId,
                  option
                )
              }
              disabledReason={(option) =>
                option ? limitedOptionReason(option, resolutionLimitSet) : ""
              }
              onChange={(nextResolution) => {
                setResolution(nextResolution)
              }}
            />
          ) : null}
          {isVideo ? (
            <WorkflowCompactParameterMenu
              label="时长"
              value={duration}
              options={durationOptions}
              emptyLabel={`${defaultVideoDuration || workflowPreferredVideoDurationValue(durationOptions)}s`}
              allowUnset={false}
              formatLabel={(option) => `${option}s`}
              disabledReason={(option) =>
                option ? limitedOptionReason(option, durationLimitSet) : ""
              }
              disabled={saving}
              onChange={(nextDuration) => {
                setDuration(nextDuration)
              }}
            />
          ) : null}
          {extraParameterControls}
          <InlineSaveControls
            dirty={
              parametersDirty || durationDirty || promptDirty || templateDirty || extraEditDirty
            }
            onRestore={handleResetAll}
            onSave={handleSaveAll}
            saving={saving}
            maximized={maximized}
            restoreLabel={extraEditDirty ? "撤销修改" : undefined}
            beforeSave={isVideo && !isReplacement && !data.workChainId ? (
              <Button type="button" variant="outline" size="sm" className={cn(WORKFLOW_SAVE_BUTTON_CLASS, "min-w-24")}
                disabled={saving || optimizing || Boolean(promptError) || data.videoPromptSyncing || !promptDraft?.trim() || !data.onOptimizeVideoPrompt}
                onClick={(event) => void handleOptimize(event)}>
                {optimizing ? <Loader2 className="size-3.5 animate-spin" /> : <WandSparkles className="size-3.5" />}
                {optimizing ? "优化中" : "优化提示词"}
              </Button>
            ) : undefined}
          />
        </div>
      </div>
    </div>
  )
}

export { InlineGenerationControls }
