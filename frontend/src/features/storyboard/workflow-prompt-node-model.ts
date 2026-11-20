import type { ScriptAdaptationTemplateOption } from "@/backend"
import {
  type EpisodeSourceText,
  type EpisodeWorkflow,
  type WorkflowWorkChain,
} from "@/backend"
import { cn } from "@/lib/utils"
import type {
  DirectorPlanShotDraft,
  DirectorPlanShotAssets,
  DirectorPlanSoundEventDraft,
  DirectorPlanSoundSourceOption,
} from "./director-plan-editor"
import { type DirectorPlanSpeakerRosterDraft } from "./director-plan-editor"
import {
  collectInlineAssetTags,
  inlineAssetDisplayRows,
  inlineAssetTagIdentity,
} from "./inline-asset-tags"
import {
  type StoryboardNode,
  type WorkflowNodeData,
  canonicalTargetSlot,
  compactReadableValue,
  isDirectorBoardNodeType,
  isWorkflowVideoTaskType,
  recordValue,
  storyboardStoryTextForNode,
} from "./workflow-canvas-model"

export function storyboardScriptTemplateValue(data: WorkflowNodeData) {
  const selected = String(data.scriptTemplateId ?? "").trim() || "faithful_cinematic"
  const templates = data.scriptAdaptationTemplates
  return templates?.length && !templates.some((template) => template.id === selected)
    ? "faithful_cinematic"
    : selected
}

export function storyboardScriptUserInstructionForNode(data: WorkflowNodeData) {
  const taskCard = recordValue(data.storyboardTaskCard)
  const prompt = recordValue(data.prompt)
  return compactReadableValue(
    data.scriptUserInstruction ??
      data.script_user_instruction ??
      taskCard.scriptUserInstruction ??
      taskCard.script_user_instruction ??
      prompt.scriptUserInstruction ??
      prompt.script_user_instruction
  )
}

export function storyboardCinematicScriptTextForNode(data: WorkflowNodeData) {
  return storyboardStoryTextForNode(data)
}

export function storyboardCinematicScriptReadyForNode(data: WorkflowNodeData) {
  return Boolean(storyboardCinematicScriptTextForNode(data).trim())
}

export function storyboardShootableContentTextForNode(data: WorkflowNodeData) {
  return (
    storyboardCinematicScriptTextForNode(data).trim() ||
    storyboardSourceFactTextForNode(data).trim()
  )
}

export function storyboardShootableContentReadyForNode(data: WorkflowNodeData) {
  return Boolean(storyboardShootableContentTextForNode(data))
}

export function workflowSameScopeNode(
  nodes: StoryboardNode[],
  baseNode: StoryboardNode,
  predicate: (node: StoryboardNode) => boolean
) {
  const workChainId = String(baseNode.data.workChainId ?? "").trim()
  if (!workChainId) return undefined
  const routeId = String(baseNode.data.routeId ?? "").trim()
  return nodes.find((node) => predicate(node) &&
    String(node.data.workChainId ?? "").trim() === workChainId &&
    (!routeId || String(node.data.routeId ?? "").trim() === routeId))
}

export function workflowScriptCreationNodeForScope(
  nodes: StoryboardNode[],
  baseNode: StoryboardNode
) {
  return workflowSameScopeNode(
    nodes,
    baseNode,
    (node) => node.data.eyebrow === "prompt.storyboard"
  )
}

export function storyboardSourceFactTextForNode(data: WorkflowNodeData) {
  return compactReadableValue(data.sourceFactText)
}

export function directorPlanShotRecordsForNode(data: WorkflowNodeData) {
  return Array.isArray(data.directorPlanShots)
    ? data.directorPlanShots.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item)
      )
    : []
}

export function directorPlanSpeakerRosterForNode(data: WorkflowNodeData) {
  return Array.isArray(data.speakerRoster) ? data.speakerRoster : []
}

export function directorPlanSpeakerRosterDraftFromRecords(
  value: unknown
): DirectorPlanSpeakerRosterDraft {
  return Array.isArray(value)
    ? value.map((item) => {
        const speaker = recordValue(item)
        return {
          speakerId: compactReadableValue(speaker.speakerId),
          displayName: compactReadableValue(speaker.displayName),
          identityDescription: compactReadableValue(speaker.identityDescription),
        }
      })
    : []
}

export function directorPlanSpeakerRosterDraftForNode(data: WorkflowNodeData) {
  return directorPlanSpeakerRosterDraftFromRecords(directorPlanSpeakerRosterForNode(data))
}

export function normalizeDirectorPlanSpeakerRosterForSave(
  value: DirectorPlanSpeakerRosterDraft
): Array<Record<string, unknown>> {
  return value
    .map((speaker) => ({
      speakerId: speaker.speakerId.trim(),
      displayName: speaker.displayName.trim(),
      identityDescription: speaker.identityDescription.trim(),
    }))
    .filter((speaker) =>
      Boolean(speaker.speakerId || speaker.displayName || speaker.identityDescription)
    )
}

export function directorRuleValueForNode(data: WorkflowNodeData) {
  return data.directorRuleSelectionMode === "auto" ? "" : compactReadableValue(data.directorRuleId)
}

export function workflowDirectorRuleOptions(data: WorkflowNodeData) {
  return (data.directorRuleOptions ?? []).map((rule) => ({
    value: rule.id,
    label: rule.title || rule.id,
    description: rule.description,
  }))
}

export function videoTaskFinalPromptDataPatch(
  data: WorkflowNodeData,
  text: string,
  dynamicPrompt = false,
  assetNameMap = recordValue(recordValue(data.videoTaskCard).assetNameMap),
  promptBindings = recordValue(recordValue(data.videoTaskCard).promptBindings),
  soundPrompt = String(recordValue(data.videoTaskCard).soundPrompt ?? ""),
  voiceSettings?: Record<string, unknown>
): Partial<WorkflowNodeData> {
  const finalPrompt = String(text ?? "")
  const card = recordValue(data.videoTaskCard)
  const source = dynamicPrompt
    ? String(card.source ?? "programmatic_final_provider_prompt")
    : "manual_final_provider_prompt"
  return {
    videoTaskCard: {
      promptKind: "final_provider_prompt",
      videoPromptKind: "final_provider_prompt",
      source,
      finalVideoPrompt: finalPrompt,
      soundPrompt,
      ...(voiceSettings ?? {}),
      assetNameMap: { ...assetNameMap },
      promptBindings: { ...promptBindings },
      manualEdited: !dynamicPrompt,
      dynamicPrompt,
    },
  }
}

export function mergeLocalGenerationConfigPatch(
  current: unknown,
  patch?: Record<string, unknown>
) {
  const next = { ...recordValue(current) }
  Object.entries(patch ?? {}).forEach(([key, value]) => {
    if (value === null || value === undefined) {
      delete next[key]
    } else {
      next[key] = value
    }
  })
  return next
}

export const WORKFLOW_INLINE_NESTED_DATA_PATCH_KEYS = new Set([
  "prompt",
  "prompts",
  "cardState",
  "card_state",
  "storyboardTaskCard",
  "storyboard_task_card",
  "directorTaskCard",
  "videoTaskCard",
])

export function mergeWorkflowInlineDataPatches(
  ...patches: Array<Partial<WorkflowNodeData> | undefined>
): Partial<WorkflowNodeData> | undefined {
  const next: Record<string, unknown> = {}
  patches.forEach((patch) => {
    if (!patch) return
    Object.entries(patch as Record<string, unknown>).forEach(([key, value]) => {
      const previousRecord = recordValue(next[key])
      const incomingRecord = recordValue(value)
      if (
        WORKFLOW_INLINE_NESTED_DATA_PATCH_KEYS.has(key) &&
        Object.keys(previousRecord).length &&
        Object.keys(incomingRecord).length
      ) {
        next[key] = { ...previousRecord, ...incomingRecord }
        return
      }
      next[key] = value
    })
  })
  return Object.keys(next).length
    ? (next as Partial<WorkflowNodeData>)
    : undefined
}

export function nextPromptValue(
  data: WorkflowNodeData,
  text: string,
  sourceFactTextOverride?: string,
  scriptManualEdited = false
) {
  if (typeof data.prompt === "string") return text
  const record = recordValue(data.prompt)
  if (data.eyebrow === "prompt.storyboard") {
    const canonicalRecord = { ...record }
    for (const key of [
      "dialogueText",
      "dialogue_text",
      "userNotes",
      "user_notes",
      "sceneBrief",
      "scene_brief",
      "storyboardImagePrompt",
      "imagePrompt",
      "visualPrompt",
      "sourceFactText",
      "source_fact_text",
      "scriptUserInstruction",
      "script_user_instruction",
      "storyboardAnalysis",
      "storyboardAnalysisStoryTextHash",
      "storyboard_analysis_story_text_hash",
      "storyboardPlanHash",
      "storyboard_plan_hash",
      "storyboardPlanState",
      "storyboard_plan_state",
      "visualBeats",
      "panels",
      "shots",
      "shotIds",
      "shotTimingPlan",
      "shot_timing_plan",
    ]) {
      delete canonicalRecord[key]
    }
    const sourceFactText =
      sourceFactTextOverride ?? storyboardSourceFactTextForNode(data)
    return {
      ...canonicalRecord,
      cinematicStoryText: text,
      scriptManualEdited,
      script_manual_edited: scriptManualEdited,
      sourceFactText,
    }
  }
  if (isWorkflowVideoTaskType(data.eyebrow)) {
    return text
  }
  if (isDirectorBoardNodeType(data.eyebrow)) {
    return { ...record, directorPlan: text }
  }
  return text
}

export function storyboardPromptEditDataPatch(
  data: WorkflowNodeData,
  text: string,
  options: {
    scriptTemplateId?: string
    scriptTemplateLabel?: string
    sourceFactText?: string
    scriptUserInstruction?: string
    scriptEdited?: boolean
  } = {}
): Partial<WorkflowNodeData> {
  const patch: Partial<WorkflowNodeData> = {}
  const card: Record<string, unknown> = {}
  const prompt: Record<string, unknown> = {}
  if (options.scriptEdited ?? text.trim() !== storyboardStoryTextForNode(data).trim()) {
    const ready = Boolean(text.trim())
    Object.assign(patch, { cinematicStoryText: text, scriptManualEdited: ready, script_manual_edited: ready })
    Object.assign(prompt, { cinematicStoryText: text, scriptManualEdited: ready, script_manual_edited: ready })
    Object.assign(card, { cinematicStoryText: text, state: ready ? "ready" : "pending_script", scriptState: ready ? "ready" : "pending_script", scriptManualEdited: ready, script_manual_edited: ready })
  }
  if (options.sourceFactText !== undefined && options.sourceFactText.trim() !== storyboardSourceFactTextForNode(data).trim()) {
    patch.sourceFactText = options.sourceFactText
    prompt.sourceFactText = options.sourceFactText
    card.sourceFactText = options.sourceFactText
  }
  if (options.scriptTemplateId !== undefined && options.scriptTemplateId.trim() !== storyboardScriptTemplateValue(data)) {
    patch.scriptTemplateId = options.scriptTemplateId.trim()
    patch.scriptTemplateLabel = options.scriptTemplateLabel ?? ""
  }
  if (options.scriptUserInstruction !== undefined && options.scriptUserInstruction.trim() !== storyboardScriptUserInstructionForNode(data).trim()) {
    const fields = { scriptUserInstruction: options.scriptUserInstruction.trim(), script_user_instruction: options.scriptUserInstruction.trim() }
    Object.assign(patch, fields)
    Object.assign(prompt, fields)
    Object.assign(card, fields)
  }
  if (Object.keys(prompt).length) patch.prompt = prompt
  if (Object.keys(card).length) patch.storyboardTaskCard = card
  return patch
}

export function sourceSplitSeedsForWorkflow(
  sourceNodeId: string,
  nodes: StoryboardNode[],
  workChains: WorkflowWorkChain[]
) {
  return [...workChains]
    .filter((chain) => (chain.origin?.kind === "source_split" || chain.origin?.kind === "independent_source") && chain.origin.sourceNodeId === sourceNodeId)
    .sort((left, right) => (left.order ?? 0) - (right.order ?? 0))
    .map((chain) => {
      const script = nodes
        .filter((node) => node.data.workChainId === chain.id && node.data.eyebrow === "prompt.storyboard")
        .sort((left, right) => (left.position.y ?? 0) - (right.position.y ?? 0))[0]
      return {
        id: chain.id,
        text: script ? storyboardSourceFactTextForNode(script.data) : "",
      }
    })
}

export function workflowWithEpisodeSourceText(
  workflow: EpisodeWorkflow,
  sourceText: EpisodeSourceText | null | undefined
): EpisodeWorkflow {
  if (!sourceText) return workflow
  let changed = false
  const nodes = (workflow.nodes ?? []).map((node) => {
    const data = node.data ?? {}
    const type = String(node.type ?? data.eyebrow ?? "")
    if (data.sourceMode === "independent") return node
    if (type !== "source.text" && data.eyebrow !== "source.text") return node
    changed = true
    return {
      ...node,
      data: {
        ...data,
        episodeId: sourceText.episodeId,
        title: sourceText.title || data.title,
        sourceText: sourceText.text,
        summary: "",
      },
    }
  })
  return changed ? { ...workflow, nodes } : workflow
}

export function isInlineNodeDataSaveReason(reason: string) {
  return (
    reason === "inline_storyboard_prompt_saved" ||
    reason === "inline_manual_video_prompt_saved" ||
    reason === "inline_final_video_prompt_saved" ||
    reason === "inline_anchor_text_saved"
  )
}

export function isNarrowNodeDataSaveReason(reason: string) {
  return (
    isInlineNodeDataSaveReason(reason) ||
    reason === "node_card_resized" ||
    reason === "input_link_locked" ||
    reason === "input_link_unlocked"
  )
}

export const RESULT_FRAME_SLOT_OPTIONS = [
  { slot: "storyboard_image", nodeType: "storyboard.image", label: "分镜图" },
] as const

export function resultFrameSlotFromNode(data: WorkflowNodeData) {
  const configured = canonicalTargetSlot(String(data.frameSlot ?? "").trim())
  if (configured) return configured
  return "storyboard_image"
}

export function stopCardWheel(event: React.WheelEvent<HTMLElement>) {
  const target = event.target
  if (
    target instanceof Element &&
    target.closest("[data-media-lightbox='true']")
  ) {
    return
  }
  event.stopPropagation()
  event.nativeEvent.stopImmediatePropagation?.()
}

export function compactWorkflowTextareaClassName(className?: string) {
  return cn(
    "nowheel block w-full min-h-[92px] max-h-[min(36vh,280px)] resize-none overflow-y-auto rounded-none border-0 bg-transparent px-0 py-0 text-[13px] leading-relaxed text-gray-900 shadow-none outline-none caret-gray-900 placeholder:text-gray-500 focus:border-transparent focus:ring-0 focus-visible:border-transparent focus-visible:ring-0 focus-visible:ring-offset-0 dark:text-white/90 dark:caret-white dark:placeholder:text-white/40",
    className
  )
}

export function fixedCompactWorkflowTextareaClassName(className?: string) {
  return cn(
    "nowheel block w-full field-sizing-fixed resize-none overflow-y-auto rounded-none border-0 bg-transparent px-0 py-0 text-[13px] leading-relaxed text-gray-900 shadow-none outline-none caret-gray-900 placeholder:text-gray-500 focus:border-transparent focus:ring-0 focus-visible:border-transparent focus-visible:ring-0 focus-visible:ring-offset-0 dark:text-white/90 dark:caret-white dark:placeholder:text-white/40",
    className
  )
}

export function clampWorkflowTextareaHeight(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.round(value)))
}

export function fixedWorkflowTextareaHeightStyle(height: number) {
  return {
    height,
    minHeight: height,
    maxHeight: height,
  }
}

export function storyboardScriptEditorTextareaLayout(
  maxHeight?: number,
  expanded = false
) {
  const leftChromeHeight = 124
  const rightChromeHeight = 24
  const minSourceFactHeight = 28
  const minUserInstructionHeight = 18
  const maxEditorHeight = expanded ? 560 : 360
  const maxSourceFactHeight = expanded ? 340 : 160
  const maxUserInstructionHeight = expanded ? 150 : 76
  const minEditorHeight =
    leftChromeHeight + minSourceFactHeight + minUserInstructionHeight
  const editorHeight =
    typeof maxHeight === "number"
      ? clampWorkflowTextareaHeight(maxHeight, minEditorHeight, maxEditorHeight)
      : undefined
  const defaultSourceFactHeight = 160
  const defaultUserInstructionHeight = 76
  const defaultEditorHeight =
    leftChromeHeight + defaultSourceFactHeight + defaultUserInstructionHeight
  if (!editorHeight) {
    return {
      editorHeight: defaultEditorHeight,
      sourceFactHeight: defaultSourceFactHeight,
      userInstructionHeight: defaultUserInstructionHeight,
      scriptHeight: defaultEditorHeight - rightChromeHeight,
    }
  }
  const leftTextHeight = Math.max(
    minSourceFactHeight + minUserInstructionHeight,
    editorHeight - leftChromeHeight
  )
  const userInstructionHeight = clampWorkflowTextareaHeight(
    leftTextHeight * 0.32,
    minUserInstructionHeight,
    maxUserInstructionHeight
  )
  const sourceFactHeight = clampWorkflowTextareaHeight(
    leftTextHeight - userInstructionHeight,
    minSourceFactHeight,
    maxSourceFactHeight
  )
  const actualEditorHeight =
    leftChromeHeight + sourceFactHeight + userInstructionHeight
  return {
    editorHeight: actualEditorHeight,
    sourceFactHeight,
    userInstructionHeight,
    scriptHeight: clampWorkflowTextareaHeight(
      actualEditorHeight - rightChromeHeight,
      100,
      maxEditorHeight - rightChromeHeight
    ),
  }
}

export function workflowLibraryTemplateName(template?: ScriptAdaptationTemplateOption) {
  return String(template?.name ?? template?.id ?? "").trim()
}

export function workflowLibraryTemplateDescription(
  template?: ScriptAdaptationTemplateOption
) {
  return String(template?.desc ?? template?.description ?? "").trim()
}

export function workflowScriptAdaptationTemplates(data?: WorkflowNodeData) {
  return data?.scriptAdaptationTemplates?.length
    ? data.scriptAdaptationTemplates
    : []
}

export function directorPlanSoundSourceOptionsForNode(
  data: WorkflowNodeData
): DirectorPlanSoundSourceOption[] {
  const inputRows = [
    ...inlineAssetDisplayRows(data),
    ...(Array.isArray(data.inputLinks) ? data.inputLinks : []),
  ]
  const { tags } = collectInlineAssetTags(
    inputRows,
    {}
  )
  const options = new Map<string, DirectorPlanSoundSourceOption>()
  tags.forEach((tag) => {
    if (tag.kind !== "character" && tag.kind !== "creature") return
    const label = tag.label.trim()
    const identity = inlineAssetTagIdentity(tag)
    if (!label || !identity) return
    const key = `asset:${identity}`
    if (options.has(key)) return
    options.set(key, {
      value: key,
      label,
      description: tag.kind === "creature" ? "生物资产" : "角色资产",
    })
  })
  return Array.from(options.values())
}

export function directorPlanShotField(
  shot: Record<string, unknown>,
  ...keys: string[]
) {
  for (const key of keys) {
    const text = compactReadableValue(shot[key])
    if (text) return text
  }
  return ""
}

export function directorPlanNumberText(value: unknown) {
  const text = compactReadableValue(value)
  if (!text) return ""
  const number = Number(text)
  if (!Number.isFinite(number)) return text
  return text
}

export function directorPlanNumberValue(value: unknown) {
  const text = compactReadableValue(value)
  if (!text) return null
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(text)) return text
  const number = Number(text)
  return Number.isFinite(number) ? number : text
}

export function directorPlanSoundEventDraftFromRecord(
  value: unknown
): DirectorPlanSoundEventDraft {
  const event = recordValue(value)
  const kind = compactReadableValue(event.kind).toLocaleLowerCase() || "voice"
  const override = recordValue(event.deliveryOverride)
  const overrideSeconds = directorPlanNumberValue(override.durationSec)
  const deliveryOverride = kind === "voice" && typeof overrideSeconds === "number" && overrideSeconds > 0
    && compactReadableValue(override.evidenceSource) && compactReadableValue(override.evidenceText)
    && compactReadableValue(override.reason)
    ? {
        durationSec: overrideSeconds,
        evidenceSource: compactReadableValue(override.evidenceSource),
        evidenceText: compactReadableValue(override.evidenceText),
        reason: compactReadableValue(override.reason),
      }
    : undefined
  const voiceType =
    compactReadableValue(event.voiceType).toLocaleLowerCase() ||
    (kind === "voice" ? "dialogue" : "")
  return {
    kind,
    voiceType,
    speakerId: compactReadableValue(event.speakerId),
    sourceName: compactReadableValue(event.sourceName),
    content: compactReadableValue(event.content),
    expressionNotes: compactReadableValue(event.expressionNotes),
    timing: compactReadableValue(event.timing),
    durationSec: kind === "voice" ? "" : directorPlanNumberText(event.durationSec),
    deliveryOverride,
  }
}

export function directorPlanShotDraftFromRecord(
  shot: Record<string, unknown>,
  index: number
): DirectorPlanShotDraft {
  const soundEvents = Array.isArray(shot.soundEvents) ? shot.soundEvents : []
  const screenTextEvents = Array.isArray(shot.screenTextEvents) ? shot.screenTextEvents : []
  const presentation = recordValue(shot.presentation)
  return {
    shotNo: index + 1,
    sourceShotNo: index + 1,
    durationSec: directorPlanNumberText(shot.durationSec) || "0",
    normalDurationSec: directorPlanNumberText(shot.normalDurationSec) || undefined,
    visualPurpose: directorPlanShotField(shot, "visualPurpose"),
    storyboardFrame: directorPlanShotField(
      shot,
      "storyboardFrame",
    ),
    videoExecution: directorPlanShotField(
      shot,
      "videoExecution"
    ),
    endState: directorPlanShotField(shot, "endState"),
    assets: directorPlanShotAssetsFromRecord(shot.assets),
    visibleAssets: directorPlanShotAssetsFromRecord(shot.visibleAssets),
    startVisibleAssets: directorPlanShotAssetsFromRecord(shot.startVisibleAssets),
    groupBreakBefore: shot.groupBreakBefore === true,
    entryBoundaryKind: typeof shot.entryBoundaryKind === "string" ? shot.entryBoundaryKind : "",
    audioBoundaryKind: typeof shot.audioBoundaryKind === "string" ? shot.audioBoundaryKind : "",
    nonOverlappingBeats: Array.isArray(shot.nonOverlappingBeats)
      ? shot.nonOverlappingBeats.map((beat) => {
          const row = recordValue(beat)
          return {
            description: compactReadableValue(row.description),
            durationSec: directorPlanNumberText(row.durationSec),
          }
        })
      : [],
    screenTextEvents: screenTextEvents.map((event) => {
      const row = recordValue(event)
      return {
        content: compactReadableValue(row.content),
        medium: compactReadableValue(row.medium),
        authorLabel: compactReadableValue(row.authorLabel),
        timing: compactReadableValue(row.timing),
        visibleAtStart: row.visibleAtStart === true,
      }
    }),
    presentation: Object.keys(presentation).length ? {
      segmentId: compactReadableValue(presentation.segmentId),
      modes: Array.isArray(presentation.modes) ? presentation.modes.map(compactReadableValue).filter(Boolean) : [],
      sourcePerspective: compactReadableValue(presentation.sourcePerspective),
      certainty: compactReadableValue(presentation.certainty),
      timeRelation: compactReadableValue(presentation.timeRelation),
      entryCue: compactReadableValue(presentation.entryCue),
      exitCue: compactReadableValue(presentation.exitCue),
      ...(Object.keys(recordValue(presentation.eventLabel)).length ? { eventLabel: {
        content: compactReadableValue(recordValue(presentation.eventLabel).content),
        sourceQuote: compactReadableValue(recordValue(presentation.eventLabel).sourceQuote),
        visibleAtStart: recordValue(presentation.eventLabel).visibleAtStart === true,
      } } : {}),
    } : undefined,
    soundEvents: soundEvents.map(directorPlanSoundEventDraftFromRecord),
  }
}

function directorPlanShotAssetsFromRecord(value: unknown): DirectorPlanShotAssets | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined
  const row = value as Record<string, unknown>
  return Object.fromEntries((["characters", "creatures", "scenes", "props"] as const).map((kind) => [
    kind, Array.isArray(row[kind]) ? row[kind].filter((id): id is string => typeof id === "string") : [],
  ])) as DirectorPlanShotAssets
}

export function directorPlanShotDraftsForNode(data: WorkflowNodeData) {
  return directorPlanShotRecordsForNode(data).map(
    directorPlanShotDraftFromRecord
  )
}

export function directorPlanNormalizedSoundEventsForSave(
  events: DirectorPlanSoundEventDraft[]
) {
  return events
    .map((event) => {
      const kind = (event.kind || "voice").trim().toLocaleLowerCase()
      const voiceType = (event.voiceType || (kind === "voice" ? "dialogue" : ""))
        .trim()
        .toLocaleLowerCase()
      const content = event.content.trim()
      const expressionNotes = event.expressionNotes.trim()
      if (!content && !expressionNotes) return null
      const row: Record<string, unknown> = {
        kind,
        content,
        expressionNotes,
      }
      if (kind === "voice") {
        row.voiceType = voiceType || "dialogue"
        const speakerId = event.speakerId.trim()
        if (speakerId) row.speakerId = speakerId
        if (event.deliveryOverride) row.deliveryOverride = { ...event.deliveryOverride }
      }
      const sourceName = event.sourceName.trim()
      if (sourceName) row.sourceName = sourceName
      const timing = event.timing.trim()
      if (timing) row.timing = timing
      const durationSec = directorPlanNumberValue(event.durationSec)
      if (kind !== "voice" && typeof durationSec === "number" && durationSec > 0) {
        row.durationSec = durationSec
      }
      return row
    })
    .filter((event): event is Record<string, unknown> => Boolean(event))
}

export function normalizeDirectorPlanShotDraftsForSave(
  shots: DirectorPlanShotDraft[]
) {
  return shots.map((shot, index) => {
    const row: Record<string, unknown> = {
      shotNo: index + 1,
      entryBoundaryKind: shot.entryBoundaryKind ?? "",
      audioBoundaryKind: shot.audioBoundaryKind ?? "",
      storyboardFrame: shot.storyboardFrame.trim(),
      videoExecution: shot.videoExecution.trim(),
      screenTextEvents: shot.screenTextEvents
        .filter((event) => event.content.trim() || event.medium.trim() || event.authorLabel.trim() || event.timing.trim())
        .map((event) => ({
          content: event.content.trim(),
          medium: event.medium.trim(),
          ...(event.authorLabel.trim() ? { authorLabel: event.authorLabel.trim() } : {}),
          ...(event.timing.trim() ? { timing: event.timing.trim() } : {}),
          visibleAtStart: event.visibleAtStart,
        })),
      soundEvents: directorPlanNormalizedSoundEventsForSave(shot.soundEvents),
    }
    const durationSec = directorPlanNumberValue(shot.durationSec)
    row.durationSec = typeof durationSec === "number" && durationSec > 0 ? durationSec : 0
    if (shot.normalDurationSec) {
      const normalDurationSec = directorPlanNumberValue(shot.normalDurationSec)
      if (typeof normalDurationSec === "number" && normalDurationSec > 0) row.normalDurationSec = normalDurationSec
    }
    if (shot.visualPurpose?.trim()) row.visualPurpose = shot.visualPurpose.trim()
    if (shot.endState?.trim()) row.endState = shot.endState.trim()
    if (shot.groupBreakBefore) row.groupBreakBefore = true
    if (shot.assets || shot.visibleAssets || shot.startVisibleAssets) {
      const kinds = ["characters", "creatures", "scenes", "props"] as const
      const assets = Object.fromEntries(kinds.map((kind) => [kind, [...new Set(shot.assets?.[kind] ?? [])]])) as DirectorPlanShotAssets
      const visibleAssets = Object.fromEntries(kinds.map((kind) => [kind,
        [...new Set(shot.visibleAssets?.[kind] ?? [])].filter((id) => assets[kind].includes(id)),
      ])) as DirectorPlanShotAssets
      row.assets = assets
      row.visibleAssets = visibleAssets
      if (shot.startVisibleAssets) row.startVisibleAssets = Object.fromEntries(kinds.map((kind) => [kind,
        [...new Set(shot.startVisibleAssets?.[kind] ?? [])].filter((id) => visibleAssets[kind].includes(id)),
      ])) as DirectorPlanShotAssets
    }
    if (shot.nonOverlappingBeats?.length) {
      row.nonOverlappingBeats = shot.nonOverlappingBeats.map((beat) => ({
        description: beat.description.trim(),
        durationSec: directorPlanNumberValue(beat.durationSec) ?? 0,
      }))
    }
    if (shot.presentation) {
      row.presentation = {
        segmentId: shot.presentation.segmentId.trim(),
        modes: shot.presentation.modes.map((mode) => mode.trim()).filter(Boolean),
        sourcePerspective: shot.presentation.sourcePerspective.trim(),
        certainty: shot.presentation.certainty.trim(),
        timeRelation: shot.presentation.timeRelation.trim(),
        ...(shot.presentation.entryCue.trim() ? { entryCue: shot.presentation.entryCue.trim() } : {}),
        ...(shot.presentation.exitCue.trim() ? { exitCue: shot.presentation.exitCue.trim() } : {}),
        ...(shot.presentation.eventLabel?.content.trim() ? { eventLabel: {
          content: shot.presentation.eventLabel.content.trim(),
          sourceQuote: shot.presentation.eventLabel.sourceQuote.trim(),
          visibleAtStart: shot.presentation.eventLabel.visibleAtStart,
        } } : {}),
      }
    }
    return row
  })
}

export function directorPlanShotValidationIssue(shots: DirectorPlanShotDraft[]) {
  const entryKinds = new Set(["direct_continuation", "spatial_cut", "ordinary_cut", "time_space_jump"])
  const audioKinds = new Set(["continuous_ambience", "dialogue_overlap", "hard_cut", "intentional_silence"])
  for (const [index, shot] of shots.entries()) {
    // Review reminders are advisory; saving editable fields does not require
    // reconfirming unchanged assets or independent beats.
    if (!entryKinds.has(shot.entryBoundaryKind ?? "")) {
      return `镜头 ${String(index + 1).padStart(2, "0")} 请选择画面接续类型`
    }
    if (!audioKinds.has(shot.audioBoundaryKind ?? "")) {
      return `镜头 ${String(index + 1).padStart(2, "0")} 请选择声音交接类型`
    }
    const durationSec = directorPlanNumberValue(shot.durationSec)
    if (typeof durationSec !== "number" || durationSec <= 0 || durationSec > 3600) {
      return `镜头 ${String(index + 1).padStart(2, "0")} 的时长须大于 0 且不超过 3600 秒，最多保留两位小数`
    }
    let independentCentiseconds = 0
    for (const [beatIndex, beat] of (shot.nonOverlappingBeats ?? []).entries()) {
      const beatSeconds = directorPlanNumberValue(beat.durationSec)
      if (!beat.description.trim() || typeof beatSeconds !== "number" || beatSeconds <= 0 || beatSeconds > 3600) {
        return `镜头 ${String(index + 1).padStart(2, "0")} 的独立时段 ${beatIndex + 1} 须填写动作和有效秒数`
      }
      independentCentiseconds += Math.round(beatSeconds * 100)
    }
    if (independentCentiseconds > Math.round(durationSec * 100)) {
      return `镜头 ${String(index + 1).padStart(2, "0")} 的独立时段合计不能超过镜头时长`
    }
  }
  return null
}

export function directorPlanShotsForSave(
  drafts: DirectorPlanShotDraft[],
  originals: Array<Record<string, unknown>>,
) {
  const issue = directorPlanShotValidationIssue(drafts)
  if (issue) throw new Error(issue)
  const editableFields = new Set([
    "shotNo", "durationSec", "normalDurationSec", "visualPurpose", "storyboardFrame",
    "videoExecution", "endState", "assets", "visibleAssets", "startVisibleAssets",
    "groupBreakBefore", "entryBoundaryKind", "audioBoundaryKind", "nonOverlappingBeats",
    "screenTextEvents", "presentation", "soundEvents",
  ])
  return normalizeDirectorPlanShotDraftsForSave(drafts).map((shot, index) => {
    const sourceNo = drafts[index]?.sourceShotNo
    const original = sourceNo ? originals[sourceNo - 1] : undefined
    if (!original) return shot
    // Keep fields the editor does not expose. Editable optional fields come
    // entirely from the draft so clearing one never restores the old value.
    const preserved = Object.fromEntries(Object.entries(original).filter(([field]) => !editableFields.has(field)))
    if (Array.isArray(preserved.publicAssetLabels)) {
      const visible = shot.visibleAssets as DirectorPlanShotAssets | undefined
      preserved.publicAssetLabels = preserved.publicAssetLabels.filter((label) => {
        const row = recordValue(label)
        const kind = String(row.assetType || "") as keyof DirectorPlanShotAssets
        return visible?.[kind]?.includes(String(row.assetId || "")) === true
      })
    }
    const saved = { ...preserved, ...shot }
    if (original.normalDurationSec !== undefined && ["durationSec", "videoExecution", "nonOverlappingBeats", "soundEvents"]
      .some((field) => JSON.stringify(original[field] ?? null) !== JSON.stringify(saved[field] ?? null))) {
      delete saved.normalDurationSec
    }
    return saved
  })
}

export function directorPlanTextFromStructuredShots(
  shots: Array<Record<string, unknown>>
) {
  return directorPlanDisplayTextFromStructuredShots(shots)
}

export function directorPlanSoundEventText(value: unknown) {
  const event = recordValue(value)
  if (!Object.keys(event).length) return compactReadableValue(value)
  const sourceName = compactReadableValue(event.sourceName)
  const content = compactReadableValue(event.content)
  const expressionNotes = compactReadableValue(event.expressionNotes)
  const timing = compactReadableValue(event.timing)
  const source = sourceName
  const main = source && content ? `${source}：${content}` : content || source
  const details = [expressionNotes, timing].filter(Boolean)
  if (!main) return details.join("，")
  return details.length ? `${main}（${details.join("，")}）` : main
}

export function directorPlanSoundEventsText(value: unknown) {
  const events = Array.isArray(value) ? value : []
  return events
    .map((event) => directorPlanSoundEventText(event))
    .filter(Boolean)
    .join("；")
}

export function directorPlanDisplayTextFromStructuredShots(
  shots: Array<Record<string, unknown>>
) {
  const lines: string[] = []
  for (const [index, shot] of shots.entries()) {
    const fields: Array<[string, string]> = [
      [
        "分镜画面",
        directorPlanShotField(shot, "storyboardFrame"),
      ],
      [
        "视频执行",
        directorPlanShotField(shot, "videoExecution"),
      ],
      [
        "画面文字",
        (Array.isArray(shot.screenTextEvents) ? shot.screenTextEvents : [])
          .map((event) => {
            const row = recordValue(event)
            return [compactReadableValue(row.medium), compactReadableValue(row.authorLabel), compactReadableValue(row.content)].filter(Boolean).join("：")
          })
          .filter(Boolean)
          .join("；"),
      ],
      [
        "声音事件",
        directorPlanSoundEventsText(shot.soundEvents),
      ],
    ]
    const body = fields
      .map(([label, text]) => (text ? `${label}：${text}` : ""))
      .filter(Boolean)
      .join("；")
    if (body) {
      lines.push(
        `镜头 ${String(index + 1).padStart(2, "0")}：${body}`
      )
    }
  }
  return lines.join("\n")
}

export function workflowTaskEditorPlaceholder(data: WorkflowNodeData) {
  if (data.eyebrow === "source.text") {
    return "粘贴或编辑分集原文..."
  }
  if (data.eyebrow === "prompt.storyboard") {
    return "写清场景、人物行动与对白；必要时用旁白补充信息，可用 @ 引用资产..."
  }
  if (isDirectorBoardNodeType(data.eyebrow)) {
    return "填写或编辑分镜脚本..."
  }
  if (isWorkflowVideoTaskType(data.eyebrow)) {
    return "编辑视频提示词；提交时自动适配模型标识并补充画面约束。"
  }
  return "输入内容..."
}

export function videoPromptAssetNameMapKey(value: Record<string, string>) {
  return JSON.stringify(Object.keys(value).sort().map((identity) => [identity, value[identity]]))
}

export function videoPromptEditorDraftKey(value: {
  text: string
  soundPrompt?: string
  voiceSettings?: Record<string, unknown>
  assetNameMap: Record<string, string>
  promptBindings?: Record<string, string>
}) {
  return JSON.stringify([value.text.trim(), value.soundPrompt ?? "", value.voiceSettings ?? null, videoPromptAssetNameMapKey(value.assetNameMap), videoPromptAssetNameMapKey(value.promptBindings ?? {})])
}

export function promptCharacterCount(value: string) {
  return Array.from(value).length
}
