import type { ModelCapabilitiesSnapshot, WorkflowModelCapability } from "@/backend"
import { getModelResolutionDisplayLabel } from "@/utils/model-resolution"
import { modelUnavailableReason } from "@/shared/model-availability"

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function configPrivateStringValue(
  config: Record<string, unknown>,
  keys: string[]
) {
  for (const key of keys) {
    if (!Object.prototype.hasOwnProperty.call(config, key)) continue
    const value = config[key]
    if (typeof value === "string" && value.trim()) return value.trim()
    if (typeof value === "number" && Number.isFinite(value))
      return String(value)
  }
  return ""
}

function workflowSnapshotConfiguredModelId(
  snapshot: ModelCapabilitiesSnapshot | null | undefined,
  mediaType: "image" | "video",
  taskType?: string
) {
  if (mediaType === "video" && taskType === "video.character_replace") {
    const model = workflowModelCapabilityRows(snapshot, "video").find((row) =>
      workflowVideoModelSupportsTask(row, taskType) &&
      !workflowModelUnavailableReason(snapshot, "video", workflowModelCapabilityId(row))
    )
    return model ? workflowModelCapabilityId(model) : ""
  }
  const modelConfig = recordValue(snapshot?.modelConfig)
  const mediaConfig = recordValue(modelConfig[mediaType])
  return configPrivateStringValue(mediaConfig, ["model_id", "modelId", "model"])
}

export function workflowModelUnavailableReason(
  snapshot: ModelCapabilitiesSnapshot | null | undefined,
  mediaType: "image" | "video",
  modelId: string
) {
  const config = recordValue(recordValue(snapshot?.modelConfig)[mediaType])
  const id = modelId.trim() || configPrivateStringValue(config, ["model_id", "modelId", "model"])
  if (!id) return ""
  const rows = snapshot?.models?.[mediaType]
  if (!Array.isArray(rows)) return ""
  const selected = rows.find((row) => workflowModelCapabilityId(row) === id)
  return selected
    ? modelUnavailableReason(selected)
    : "当前模型未出现在已获取的模型列表"
}

function providerFromModelId(modelId: string) {
  const [provider] = modelId.split(":")
  return provider && provider !== modelId ? provider : ""
}

function presetOptions(current: string, presets: string[]) {
  const values: string[] = []
  const seen = new Set<string>()
  for (const preset of presets) {
    const normalized = preset.trim()
    if (!normalized || seen.has(normalized)) continue
    seen.add(normalized)
    values.push(normalized)
  }
  const currentValue = current.trim()
  if (currentValue && !seen.has(currentValue)) values.push(currentValue)
  return values
}

function normalizedPresetSet(values: string[]) {
  return new Set(values.map((value) => value.trim().toLowerCase()).filter(Boolean))
}

function limitedOptionReason(option: string, supportedValues: Set<string>) {
  if (!supportedValues.size) return ""
  return supportedValues.has(option.trim().toLowerCase()) ? "" : "模型未声明"
}

const VIDEO_DURATION_OPTIONS = ["4", "5", "6", "8", "10", "12", "15"]

function workflowPreferredVideoDurationValue(options: string[]) {
  const durations = options
    .map((option) => Number(option))
    .filter((duration) => Number.isFinite(duration) && duration > 0)
  if (!durations.length) return "15"
  if (durations.some((duration) => duration === 15)) return "15"
  return String(Math.max(...durations))
}

function workflowVideoTaskDefaultDurationValue(
  data?: {
    eyebrow?: string
    generationConfig?: unknown
    modelCapabilitiesSnapshot?: ModelCapabilitiesSnapshot | null
  } | null
) {
  if (!data) return "15"
  const config = recordValue(data.generationConfig)
  const rows = workflowModelCapabilityRows(
    data.modelCapabilitiesSnapshot,
    "video"
  )
  const modelId =
    configPrivateStringValue(config, ["modelId", "model_id"]) ||
    workflowSnapshotConfiguredModelId(data.modelCapabilitiesSnapshot, "video")
  const selected = modelId
    ? rows.find((row) => workflowModelCapabilityId(row) === modelId)
    : undefined
  const options = workflowModelDurationOptions(selected, data.eyebrow === "video.keyframe")
  return workflowPreferredVideoDurationValue(
    options.length ? options : VIDEO_DURATION_OPTIONS
  )
}

function stringArrayValue(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item ?? "").trim()).filter(Boolean)
  }
  const text = String(value ?? "").trim()
  return text ? [text] : []
}
function compactModelLabel(modelId: string) {
  const trimmed = modelId.trim()
  if (!trimmed) return trimmed
  const parts = trimmed.split(":")
  return parts[parts.length - 1]?.trim() || trimmed
}

function workflowModelCapabilityRows(
  snapshot: ModelCapabilitiesSnapshot | null | undefined,
  mediaType: "image" | "video"
): WorkflowModelCapability[] {
  const rows = snapshot?.models?.[mediaType]
  return Array.isArray(rows)
    ? rows.filter((row) => row?.type === mediaType)
    : []
}

function workflowModelCapabilityId(row: WorkflowModelCapability) {
  return String(row.id ?? "").trim()
}

function workflowVideoModelSupportsTask(row: WorkflowModelCapability, task: boolean | string = false) {
  const adapter = row.adapter_capabilities
  const taskType = typeof task === "string" ? task : task ? "video.keyframe" : "video.storyboard"
  if (adapter?.task_types?.length) {
    if (!adapter.task_types.includes(taskType)) return false
  } else if (taskType === "video.character_replace") return false
  const nativeKeyframe = taskType === "video.keyframe"
  const visual = nativeKeyframe ? adapter?.keyframe_visual_inputs : adapter?.visual_inputs
  // Legacy/custom snapshots without ordinary mode metadata retain existing behavior.
  if (!visual) return !nativeKeyframe
  return Array.isArray(visual.modes) && visual.modes.length > 0
}

export { workflowVideoModelSupportsTask }

function workflowModelCapabilityLabel(row: WorkflowModelCapability) {
  const id = workflowModelCapabilityId(row)
  return String(row.label ?? "").trim() || compactModelLabel(id)
}

function workflowModelCapabilityProviderId(row: WorkflowModelCapability) {
  return String(
    row.providerId ?? row.providerPresetId ?? row.adapterId ?? ""
  ).trim()
}

function workflowModelCapabilityProviderLabel(row: WorkflowModelCapability) {
  const explicitName = String(
    (row as { providerName?: unknown; providerTitle?: unknown }).providerName ??
      (row as { providerTitle?: unknown }).providerTitle ??
      ""
  ).trim()
  if (explicitName) return explicitName
  const labelParts = workflowModelCapabilityLabel(row)
    .split(" / ")
    .map((part) => part.trim())
    .filter(Boolean)
  if (labelParts.length > 1) return labelParts[0]
  return workflowModelCapabilityProviderId(row) || "其他供应商"
}

function workflowModelCapabilityDisplayName(row: WorkflowModelCapability) {
  const labelParts = workflowModelCapabilityLabel(row)
    .split(" / ")
    .map((part) => part.trim())
    .filter(Boolean)
  return labelParts.length > 1
    ? labelParts[labelParts.length - 1]
    : (labelParts[0] ?? "")
}

function workflowModelCapabilityBadges(
  row: WorkflowModelCapability,
  mediaType: "image" | "video"
) {
  const badges: string[] = []
  const durations = Array.isArray(row.durations)
    ? row.durations.map((item) => String(item).trim()).filter(Boolean)
    : []
  if (mediaType === "video" && durations.length > 0) {
    badges.push(
      durations.length === 1
        ? `${durations[0]}s`
        : `${durations[0]}-${durations[durations.length - 1]}s`
    )
  }
  const maxReferenceImages = Number(row.maxReferenceImages)
  if (Number.isFinite(maxReferenceImages) && maxReferenceImages > 0) {
    badges.push(`参考图 ${maxReferenceImages}`)
  }
  return badges.slice(0, 3)
}

type WorkflowModelOption = {
  value: string
  label: string
  badges?: string[]
  description?: string
  disabledReason?: string
}

type WorkflowModelOptionGroup = {
  label: string
  options: WorkflowModelOption[]
}

function workflowModelOptionGroups(
  optionValues: string[],
  rows: WorkflowModelCapability[],
  mediaType: "image" | "video",
  formatModelLabel: (value: string) => string
): WorkflowModelOptionGroup[] {
  const rowById = new Map<string, WorkflowModelCapability>()
  rows.forEach((row) => {
    const id = workflowModelCapabilityId(row)
    if (id) rowById.set(id, row)
  })
  const groups = new Map<string, WorkflowModelOptionGroup>()
  const addOption = (groupLabel: string, option: WorkflowModelOption) => {
    const normalizedLabel = groupLabel.trim() || "其他供应商"
    const group = groups.get(normalizedLabel) ?? {
      label: normalizedLabel,
      options: [],
    }
    if (!group.options.some((entry) => entry.value === option.value)) {
      group.options.push(option)
    }
    groups.set(normalizedLabel, group)
  }

  for (const rawValue of optionValues) {
    const value = rawValue.trim()
    if (!value) continue
    const row = rowById.get(value)
    if (row) {
      addOption(workflowModelCapabilityProviderLabel(row), {
        value,
        label: workflowModelCapabilityDisplayName(row),
        badges: workflowModelCapabilityBadges(row, mediaType),
        ...(modelUnavailableReason(row) ? { disabledReason: modelUnavailableReason(row) } : {}),
      })
      continue
    }
    const fullLabel = formatModelLabel(value)
    const labelParts = fullLabel
      .split(" / ")
      .map((part) => part.trim())
      .filter(Boolean)
    addOption(
      labelParts.length > 1 ? labelParts[0] : providerFromModelId(value),
      {
        value,
        label:
          labelParts.length > 1 ? labelParts[labelParts.length - 1] : fullLabel,
      }
    )
  }
  return Array.from(groups.values())
}

function workflowModelDurationOptions(row?: WorkflowModelCapability, nativeKeyframe = false) {
  const keyframeDurations = row?.adapter_capabilities?.keyframe_visual_inputs?.durations
  return stringArrayValue(nativeKeyframe && keyframeDurations?.length ? keyframeDurations : row?.durations)
}

function workflowModelResolutionLabel(
  mediaType: "image" | "video",
  rows: WorkflowModelCapability[],
  modelId: string,
  resolution: string
) {
  const row = rows.find((item) => workflowModelCapabilityId(item) === modelId)
  const labels = recordValue(row?.resolutionLabels)
  const backendLabel = String(labels[resolution] ?? "").trim()
  if (backendLabel) return backendLabel
  return getModelResolutionDisplayLabel({
    mediaType,
    model: row ?? { id: modelId },
    resolution,
  })
}

function workflowModelResolutionDescription(
  mediaType: "image" | "video",
  rows: WorkflowModelCapability[],
  modelId: string,
  resolution: string
) {
  if (mediaType !== "image") return ""
  const row = rows.find((item) => workflowModelCapabilityId(item) === modelId)
  const descriptions = recordValue(
    row?.resolutionDescriptions ?? row?.resolution_descriptions
  )
  const keys = ["storyboard", "16:9", "scene", "asset"]
  for (const key of keys) {
    const descriptionMap = recordValue(descriptions[key])
    const description = String(descriptionMap[resolution] ?? "").trim()
    if (description) return description
  }
  return ""
}

function workflowResolutionKey(value: string) {
  return String(value ?? "")
    .trim()
    .replace("×", "x")
    .replace("*", "x")
    .toLowerCase()
}

function workflowResolutionOptionMatches(
  mediaType: "image" | "video",
  rows: WorkflowModelCapability[],
  modelId: string,
  option: string,
  value: string
) {
  const optionKey = workflowResolutionKey(option)
  const valueKey = workflowResolutionKey(value)
  if (!optionKey || !valueKey) return false
  if (optionKey === valueKey) return true
  const optionLabelKey = workflowResolutionKey(
    workflowModelResolutionLabel(mediaType, rows, modelId, option)
  )
  const valueLabelKey = workflowResolutionKey(
    workflowModelResolutionLabel(mediaType, rows, modelId, value)
  )
  return (
    (!!optionLabelKey && optionLabelKey === valueKey) ||
    (!!valueLabelKey && optionKey === valueLabelKey) ||
    (!!optionLabelKey && !!valueLabelKey && optionLabelKey === valueLabelKey)
  )
}

function workflowMatchedResolutionOption(
  mediaType: "image" | "video",
  rows: WorkflowModelCapability[],
  modelId: string,
  options: string[],
  value: string
) {
  const trimmed = value.trim()
  if (!trimmed) return ""
  return (
    options.find((option) =>
      workflowResolutionOptionMatches(mediaType, rows, modelId, option, trimmed)
    ) ?? ""
  )
}

function workflowModelLabelFormatter(
  snapshot: ModelCapabilitiesSnapshot | null | undefined,
  mediaType: "image" | "video"
) {
  const labels = new Map<string, string>()
  workflowModelCapabilityRows(snapshot, mediaType).forEach((row) => {
    const id = workflowModelCapabilityId(row)
    if (id) labels.set(id, workflowModelCapabilityLabel(row))
  })
  return (modelId: string) =>
    labels.get(modelId.trim()) ?? compactModelLabel(modelId)
}

export { VIDEO_DURATION_OPTIONS, workflowPreferredVideoDurationValue, workflowVideoTaskDefaultDurationValue, configPrivateStringValue, workflowSnapshotConfiguredModelId, providerFromModelId, presetOptions, normalizedPresetSet, limitedOptionReason, compactModelLabel, workflowModelCapabilityRows, workflowModelCapabilityId, workflowModelCapabilityLabel, workflowModelCapabilityProviderId, workflowModelCapabilityProviderLabel, workflowModelCapabilityDisplayName, workflowModelCapabilityBadges, workflowModelOptionGroups, workflowModelDurationOptions, workflowModelResolutionLabel, workflowModelResolutionDescription, workflowResolutionKey, workflowResolutionOptionMatches, workflowMatchedResolutionOption, workflowModelLabelFormatter }
