import {
  DEFAULT_STORYBOARD_TEMPLATES,
  isStoryboardCardNodeType,
  isWorkflowVideoTaskType,
  recordValue,
  storyboardTemplateId,
  storyboardTemplateLabel,
  workflowVideoTaskSelectedDurationValue,
  type WorkflowNodeData,
} from "./workflow-canvas-model"
import {
  configPrivateStringValue,
  workflowModelCapabilityRows,
  workflowModelLabelFormatter,
  workflowModelResolutionLabel,
  workflowSnapshotConfiguredModelId,
} from "./workflow-model-capabilities"
import {
  directorRuleValueForNode,
  storyboardScriptTemplateValue,
  workflowDirectorRuleOptions,
  workflowLibraryTemplateName,
  workflowScriptAdaptationTemplates,
} from "./workflow-prompt-node-model"

type SummaryEntry = [label: string, value: string]

function CardParameterSummary({ values }: { values: SummaryEntry[] }) {
  return (
    <div className="grid grid-cols-2 gap-1.5">
      {values.map(([label, value]) => (
        <div
          key={label}
          className="min-w-0 rounded-md bg-gray-50/80 px-2 py-1.5 text-[11px] dark:bg-white/[0.035]"
        >
          <div className="text-[9px] text-gray-400 dark:text-gray-500">{label}</div>
          <div
            className="mt-0.5 truncate font-medium text-gray-700 dark:text-gray-200"
            title={value}
          >
            {value}
          </div>
        </div>
      ))}
    </div>
  )
}

export function WorkflowCardConfig({ data }: { data: WorkflowNodeData }) {
  let values: SummaryEntry[]

  if (data.eyebrow === "prompt.storyboard") {
    const templates = workflowScriptAdaptationTemplates(data)
    const selected = storyboardScriptTemplateValue(data)
    const name = workflowLibraryTemplateName(templates.find((item) => item.id === selected))
    values = [["创作策略", name || data.scriptTemplateLabel || "标准忠实影视化"]]
  } else if (data.eyebrow === "director.board") {
    const selected = directorRuleValueForNode(data)
    const rule = workflowDirectorRuleOptions(data).find((item) => item.value === selected)
    const appliedRule = data.directorRuleSelectionMode === "auto"
      ? workflowDirectorRuleOptions(data).find((item) => item.value === data.directorRuleId)
      : undefined
    const rhythm = typeof data.rhythmMultiplier === "number" &&
      Number.isFinite(data.rhythmMultiplier) && data.rhythmMultiplier >= 1
      ? `${data.rhythmMultiplier} 倍`
      : "跟随项目设置"
    const shotCount = data.directorPlanShots?.length || new Set(
      data.storyboardAllocation?.groups.flatMap((group) => group.shotNos) ?? []
    ).size
    values = [
      ["导演规则", rule?.label || selected || (appliedRule ? `自动选择 · ${appliedRule.label}` : "自动选择")],
      ["镜头节奏", rhythm],
      ["镜头数量", String(shotCount) + " 个"],
    ]
  } else if (isStoryboardCardNodeType(data.eyebrow) || isWorkflowVideoTaskType(data.eyebrow)) {
    const isVideo = isWorkflowVideoTaskType(data.eyebrow)
    const mediaType = isVideo ? "video" : "image"
    const config = recordValue(data.generationConfig)
    const modelId = configPrivateStringValue(config, ["modelId", "model_id"])
    const modelRows = workflowModelCapabilityRows(data.modelCapabilitiesSnapshot, mediaType)
    const effectiveModelId = modelId ||
      workflowSnapshotConfiguredModelId(data.modelCapabilitiesSnapshot, mediaType, data.eyebrow)
    const resolution = configPrivateStringValue(config, ["resolution", "size"])
    const resolutionLabel = resolution
      ? workflowModelResolutionLabel(mediaType, modelRows, effectiveModelId, resolution)
      : "跟随全局设置"
    const modelLabel = effectiveModelId
      ? workflowModelLabelFormatter(data.modelCapabilitiesSnapshot, mediaType)(effectiveModelId)
      : "未配置"

    if (isVideo) {
      const duration = workflowVideoTaskSelectedDurationValue(data)
      values = [
        ["视频模型", modelLabel],
        ["分辨率", resolutionLabel],
        ["时长", duration ? String(duration) + "s" : "未设置"],
        ["生成方式", data.eyebrow === "video.character_replace" ? "角色替换 · 沿用源视频原声" : data.eyebrow === "video.keyframe" ? "首尾帧" : "分镜图"],
      ]
    } else {
      const templates = data.storyboardTemplates?.length
        ? data.storyboardTemplates
        : DEFAULT_STORYBOARD_TEMPLATES
      const cardState = recordValue(data.cardState)
      const template = storyboardTemplateId(
        data.storyboardTemplate ?? cardState.template ?? cardState.templateId ??
          data.storyboardTemplateLabel,
        templates
      )
      const shotCount = data.shotNos?.length || data.directorPlanShots?.length || 0
      values = [
        ["镜头数量", String(shotCount) + " 个"],
        ["分镜版式", storyboardTemplateLabel(template, templates)],
        ["图片模型", modelLabel],
        ["图片尺寸", resolutionLabel],
      ]
    }
  } else {
    return null
  }

  return <CardParameterSummary values={values} />
}
