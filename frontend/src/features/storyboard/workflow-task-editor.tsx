import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import type { ComponentType, ReactNode } from "react"
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type WheelEvent,
} from "react"
import { createPortal } from "react-dom"
import { toast } from "sonner"
import {
  type DirectorPlanShotDraft,
  type DirectorPlanSpeakerRosterDraft,
} from "./director-plan-editor"
import { bindPromptMentions, promptMentionOptions, rebasePromptMentions, PROMPT_MENTION_COLORS, PROMPT_MENTION_TYPE_LABELS, type PromptMentionOption } from "./video-prompt-mentions"
import { createVideoPromptHistory, editVideoPromptHistory, sameVideoPromptDraft, stepVideoPromptHistory, type VideoPromptDraft } from "./video-prompt-history"
import {
  collectInlineAssetTags,
  inlineAssetDisplayRefs,
  inlineAssetDisplayMentionRows,
} from "./inline-asset-tags"
import {
  activeAssetMentionRange,
  insertAssetMention,
  type AssetMentionRange,
} from "./workflow-canvas-asset-model"
import {
  isDirectorBoardNodeType,
  isWorkflowVideoTaskType,
  promptTextForNode,
  storyboardStoryTextForNode,
  type ManualSaveOptions,
  type WorkflowNodeData,
} from "./workflow-canvas-model"
import {
  InlineSaveControls,
  WorkflowCompactParameterMenu,
} from "./workflow-inline-controls"
import { InlineGenerationControls } from "./workflow-inline-generation-controls"
import { InlinePromptEditor } from "./workflow-inline-prompt-editor"
import { VideoTaskVoiceSettings } from "./video-task-voice-settings"
import { videoVoiceSettingsFromCard, videoVoiceSettingsKey } from "./video-task-voice-model"
import {
  directorPlanShotDraftsForNode,
  directorPlanShotRecordsForNode,
  directorPlanShotsForSave,
  directorPlanShotValidationIssue,
  directorPlanSoundSourceOptionsForNode,
  directorPlanTextFromStructuredShots,
  directorPlanSpeakerRosterDraftForNode,
  directorRuleValueForNode,
  fixedCompactWorkflowTextareaClassName,
  fixedWorkflowTextareaHeightStyle,
  nextPromptValue,
  normalizeDirectorPlanShotDraftsForSave,
  normalizeDirectorPlanSpeakerRosterForSave,
  promptCharacterCount,
  storyboardPromptEditDataPatch,
  storyboardScriptEditorTextareaLayout,
  storyboardScriptTemplateValue,
  storyboardSourceFactTextForNode,
  videoPromptAssetNameMapKey,
  videoPromptEditorDraftKey,
  videoTaskFinalPromptDataPatch,
  workflowDirectorRuleOptions,
  workflowLibraryTemplateDescription,
  workflowLibraryTemplateName,
  workflowScriptAdaptationTemplates,
  workflowTaskEditorPlaceholder,
} from "./workflow-prompt-node-model"

export type WorkflowTaskAssetLinksProps = {
  id: string
  data: WorkflowNodeData
  reserveSpace?: boolean
  compact?: boolean
  trailing?: ReactNode
}
export type WorkflowTaskAssetLinksLoadingProps = { active?: boolean; compact?: boolean }

function directorPlanEditorDraftKey(value: { shots: DirectorPlanShotDraft[]; speakerRoster: DirectorPlanSpeakerRosterDraft }) {
  return JSON.stringify({
    shots: normalizeDirectorPlanShotDraftsForSave(value.shots),
    speakerRoster: normalizeDirectorPlanSpeakerRosterForSave(value.speakerRoster),
  })
}

type StoryboardNodeLike = { id: string; data: WorkflowNodeData }

type AssetMentionAnchor = { left: number; top: number }

function recordValue(value: unknown): Record<string, any> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, any>) : {}
}

function useWorkflowSavedDraft<T>(id: string, savedDraft: T, serialize: (value: T) => string | undefined = JSON.stringify) {
  const [draft, setDraft] = useState(savedDraft)
  const savedKey = serialize(savedDraft)
  const baseline = useRef({ id, savedKey })
  useEffect(() => {
    const previous = baseline.current
    if (previous.id === id && previous.savedKey === savedKey) return
    baseline.current = { id, savedKey }
    setDraft((current) => previous.id !== id || serialize(current) === previous.savedKey ? savedDraft : current)
  }, [id, savedKey, savedDraft, serialize])
  return [draft, setDraft] as const
}

function useVideoPromptEditorDraft(id: string, savedDraft: VideoPromptDraft) {
  const [history, setHistory] = useState(() => createVideoPromptHistory(savedDraft))
  const savedKey = videoPromptEditorDraftKey(savedDraft)
  const baseline = useRef({ id, savedKey, displayedSavedDraft: savedDraft })
  const pendingAgentSaveKey = useRef<string | null>(null)
  useEffect(() => {
    const previous = baseline.current
    if (previous.id === id && previous.savedKey === savedKey) return
    const displayedSavedKey = videoPromptEditorDraftKey(previous.displayedSavedDraft)
    baseline.current = { id, savedKey, displayedSavedDraft: savedDraft }
    setHistory((current) => {
      const currentKey = videoPromptEditorDraftKey(current.present)
      const matchesAgentSubmission = pendingAgentSaveKey.current === currentKey
      pendingAgentSaveKey.current = null
      return previous.id !== id || matchesAgentSubmission || [previous.savedKey, displayedSavedKey].includes(currentKey)
        ? createVideoPromptHistory(savedDraft) : current
    })
  }, [id, savedKey, savedDraft])
  const edit = useCallback((update: VideoPromptDraft | ((current: VideoPromptDraft) => VideoPromptDraft)) => {
    setHistory((current) => editVideoPromptHistory(current, typeof update === "function" ? update(current.present) : update))
  }, [])
  const sync = useCallback((options: PromptMentionOption[]) => {
    // Preserve the baseline's resolved identities when a later result changes references.
    const saved = baseline.current.displayedSavedDraft
    baseline.current.displayedSavedDraft = { ...saved, ...rebasePromptMentions(saved.text, saved.promptBindings, options, [saved.soundPrompt ?? ""]) }
    const draft = { ...history.present, ...rebasePromptMentions(history.present.text, history.present.promptBindings, options, [history.present.soundPrompt ?? ""]) }
    if (sameVideoPromptDraft(history.present, draft)) return
    setHistory((current) => {
      const draft = { ...current.present, ...rebasePromptMentions(current.present.text, current.present.promptBindings, options, [current.present.soundPrompt ?? ""]) }
      return sameVideoPromptDraft(current.present, draft) ? current : { ...current, present: draft }
    })
  }, [history.present])
  const move = useCallback((direction: "undo" | "redo", options: PromptMentionOption[]) => {
    setHistory((current) => {
      const next = stepVideoPromptHistory(current, direction)
      if (next === current) return current
      return { ...next, present: { ...next.present, ...rebasePromptMentions(next.present.text, next.present.promptBindings, options, [next.present.soundPrompt ?? ""]) } }
    })
  }, [])
  const reset = useCallback((draft: VideoPromptDraft) => setHistory(createVideoPromptHistory(draft)), [])
  const expectAgentSave = useCallback(() => {
    pendingAgentSaveKey.current = videoPromptEditorDraftKey(history.present)
  }, [history.present])
  return { draft: history.present, displayedSavedDraft: baseline.current.displayedSavedDraft,
           edit, sync, move, reset, expectAgentSave }
}

const WORKFLOW_INLINE_PARAMETER_BAR_CLASS = "sticky bottom-0 z-10 border-t border-gray-200/80 bg-transparent pt-2 dark:border-white/[0.08]"
const WORKFLOW_INLINE_PARAMETER_ROW_CLASS = "flex min-h-8 flex-wrap items-center gap-1.5"

function stopCardWheel(event: WheelEvent<HTMLElement>) {
  event.stopPropagation()
  event.nativeEvent.stopImmediatePropagation?.()
}
function WorkflowTaskEditor({
  id,
  data,
  maxHeight,
  maximized = false,
  AssetLinks: InlineAssetLinks,
  AssetLinksLoadingSlot: InlineAssetLinksLoadingSlot,
}: {
  id: string
  data: WorkflowNodeData
  maxHeight?: number
  maximized?: boolean
  AssetLinks: ComponentType<WorkflowTaskAssetLinksProps>
  AssetLinksLoadingSlot: ComponentType<WorkflowTaskAssetLinksLoadingProps>
}) {
  const savedPromptBody = promptTextForNode(data)
  const isStoryboardPrompt = data.eyebrow === "prompt.storyboard"
  const isDirectorBoard = isDirectorBoardNodeType(data.eyebrow)
  const isVideoPrompt = isWorkflowVideoTaskType(data.eyebrow)
  const showsVoiceSettings = isVideoPrompt && data.eyebrow !== "video.character_replace"
  const promptValue = savedPromptBody
  const showsInlineAssetLinks = isVideoPrompt
  const supportsAssetMention = isVideoPrompt
  const usesResolvedAssetDetails = showsInlineAssetLinks
  const sourceFactValue = isStoryboardPrompt
    ? storyboardSourceFactTextForNode(data)
    : ""
  const scriptTemplatesForNode = isStoryboardPrompt
    ? workflowScriptAdaptationTemplates(data)
    : []
  const savedScriptTemplateId = isStoryboardPrompt
    ? storyboardScriptTemplateValue(data)
    : ""
  const directorRuleOptions = isDirectorBoard
    ? workflowDirectorRuleOptions(data)
    : []
  const savedDirectorRuleId = isDirectorBoard
    ? directorRuleValueForNode(data)
    : ""
  const savedDirectorRhythmMultiplier =
    typeof data.rhythmMultiplier === "number" && Number.isFinite(data.rhythmMultiplier) && data.rhythmMultiplier >= 1
      ? String(data.rhythmMultiplier)
      : ""
  const savedDirectorShotDrafts = useMemo(
    () => (isDirectorBoard ? directorPlanShotDraftsForNode(data) : []),
    [
      isDirectorBoard,
      isDirectorBoard ? data.directorPlanShots : null,
    ]
  )
  const savedDirectorSpeakerRoster = useMemo(
    () =>
      isDirectorBoard
        ? directorPlanSpeakerRosterDraftForNode(data)
        : [],
    [
      isDirectorBoard,
      isDirectorBoard ? data.speakerRoster : null,
    ]
  )
  const savedPromptAssetNameMap = isVideoPrompt
    ? recordValue(recordValue(data.videoTaskCard).assetNameMap) as Record<string, string>
    : {}
  const savedPromptBindings = isVideoPrompt
    ? recordValue(recordValue(data.videoTaskCard).promptBindings) as Record<string, string>
    : {}
  const { draft: promptEditorDraft, displayedSavedDraft: savedVisiblePromptDraft,
    edit: setPromptEditorDraft, sync: syncPromptMentions, move: movePromptHistory,
    reset: resetPromptDraft, expectAgentSave } = useVideoPromptEditorDraft(id, {
    text: promptValue,
    soundPrompt: isVideoPrompt ? String(recordValue(data.videoTaskCard).soundPrompt ?? "") : "",
    voiceSettings: isVideoPrompt ? videoVoiceSettingsFromCard(recordValue(data.videoTaskCard)) : undefined,
    assetNameMap: savedPromptAssetNameMap,
    promptBindings: savedPromptBindings,
  })
  const promptDraft = promptEditorDraft.text
  const soundPromptDraft = promptEditorDraft.soundPrompt ?? ""
  const voiceSettingsDraft = promptEditorDraft.voiceSettings ?? videoVoiceSettingsFromCard()
  const voiceSettingsDirty = isVideoPrompt && videoVoiceSettingsKey(promptEditorDraft.voiceSettings) !== videoVoiceSettingsKey(savedVisiblePromptDraft.voiceSettings)
  const videoPromptCharacterCount = isVideoPrompt
    ? promptCharacterCount(promptDraft)
    : undefined
  const [directorDraft, setDirectorDraft] = useWorkflowSavedDraft(id, {
    shots: savedDirectorShotDrafts,
    speakerRoster: savedDirectorSpeakerRoster,
  }, directorPlanEditorDraftKey)
  const directorShotDrafts = directorDraft.shots
  const directorSpeakerRoster = directorDraft.speakerRoster
  const [directorPendingEdit, setDirectorPendingEdit] = useState(false)
  const setDirectorShotDrafts = (shots: DirectorPlanShotDraft[]) =>
    setDirectorDraft((current) => ({ ...current, shots }))
  const setDirectorSpeakerRoster = (speakerRoster: DirectorPlanSpeakerRosterDraft) =>
    setDirectorDraft((current) => ({ ...current, speakerRoster }))
  const [sourceFactDraft, setSourceFactDraft] = useState(() => sourceFactValue)
  const [scriptTemplateId, setScriptTemplateId] = useState(
    () => savedScriptTemplateId
  )
  const [directorRuleId, setDirectorRuleId] = useState(
    () => savedDirectorRuleId
  )
  const [directorRhythmMultiplier, setDirectorRhythmMultiplier] = useState(
    () => String(savedDirectorRhythmMultiplier)
  )
  const [saving, setSaving] = useState(false)
  const [assetMentionOpen, setAssetMentionOpen] = useState(false)
  const [assetMentionRange, setAssetMentionRange] =
    useState<AssetMentionRange | null>(null)
  const [assetMentionAnchor, setAssetMentionAnchor] =
    useState<AssetMentionAnchor | null>(null)
  const directorSoundSourceOptions = useMemo(
    () => (isDirectorBoard ? directorPlanSoundSourceOptionsForNode(data) : []),
    [
      isDirectorBoard,
      data.inputLinks,
      data.referenceVideoThumbnails,
      data.referenceThumbnails,
      data.assetThumbnails,
      data.assetRefs,
    ]
  )
  const promptSaveReason = isVideoPrompt
    ? "inline_final_video_prompt_saved"
    : isDirectorBoard
      ? "inline_director_plan_saved"
      : "inline_storyboard_prompt_saved"

  useEffect(() => { setSourceFactDraft(sourceFactValue) }, [id, sourceFactValue])
  useEffect(() => { setDirectorPendingEdit(false) }, [id])
  useEffect(() => { setScriptTemplateId(savedScriptTemplateId) }, [id, savedScriptTemplateId])
  useEffect(() => { setDirectorRuleId(savedDirectorRuleId) }, [id, savedDirectorRuleId])
  useEffect(() => { setDirectorRhythmMultiplier(String(savedDirectorRhythmMultiplier)) }, [id, savedDirectorRhythmMultiplier])
  useEffect(() => {
    setAssetMentionOpen(false)
    setAssetMentionRange(null)
    setAssetMentionAnchor(null)
  }, [id, promptValue])

  const normalizedDirectorShotDrafts = useMemo(
    () => normalizeDirectorPlanShotDraftsForSave(directorShotDrafts),
    [directorShotDrafts]
  )
  const savedNormalizedDirectorShotDrafts = useMemo(
    () => normalizeDirectorPlanShotDraftsForSave(savedDirectorShotDrafts),
    [savedDirectorShotDrafts]
  )
  const directorPlanDraft = isDirectorBoard
    ? directorPlanTextFromStructuredShots(normalizedDirectorShotDrafts)
    : promptDraft
  const savedDirectorPlanDraft = isDirectorBoard
    ? directorPlanTextFromStructuredShots(savedNormalizedDirectorShotDrafts)
    : promptValue
  const promptTextDirty = isDirectorBoard
    ? JSON.stringify(normalizedDirectorShotDrafts) !==
      JSON.stringify(savedNormalizedDirectorShotDrafts)
    : isVideoPrompt
      ? promptDraft.trim() !== savedVisiblePromptDraft.text.trim()
    : directorPlanDraft.trim() !== savedDirectorPlanDraft.trim()
  const sourceFactDirty =
    isStoryboardPrompt && sourceFactDraft.trim() !== sourceFactValue.trim()
  const scriptTemplateDirty =
    isStoryboardPrompt && scriptTemplateId !== savedScriptTemplateId
  const directorRuleDirty =
    isDirectorBoard && directorRuleId !== savedDirectorRuleId
  const directorRhythmDirty =
    isDirectorBoard && directorRhythmMultiplier !== savedDirectorRhythmMultiplier
  const directorSpeakerRosterDirty =
    isDirectorBoard &&
    JSON.stringify(normalizeDirectorPlanSpeakerRosterForSave(directorSpeakerRoster)) !==
      JSON.stringify(normalizeDirectorPlanSpeakerRosterForSave(savedDirectorSpeakerRoster))
  const promptAssetNameMapDirty = isVideoPrompt && (
    videoPromptAssetNameMapKey(promptEditorDraft.assetNameMap) !== videoPromptAssetNameMapKey(savedVisiblePromptDraft.assetNameMap) ||
    videoPromptAssetNameMapKey(promptEditorDraft.promptBindings) !== videoPromptAssetNameMapKey(savedVisiblePromptDraft.promptBindings)
  )
  const videoPromptSyncing = isVideoPrompt && Boolean(data.videoPromptSyncing)
  const editorLocked = saving || videoPromptSyncing || (isVideoPrompt && !data.workflowCardDetailLoaded)
  const selectedScriptTemplate = scriptTemplatesForNode.find(
    (template: any) => template.id === scriptTemplateId
  )
  const scriptTemplateName =
    workflowLibraryTemplateName(selectedScriptTemplate) || scriptTemplateId
  const promptDirty =
    promptTextDirty ||
    (isVideoPrompt && soundPromptDraft !== (savedVisiblePromptDraft.soundPrompt ?? "")) ||
    voiceSettingsDirty ||
    (isDirectorBoard && directorPendingEdit) ||
    sourceFactDirty ||
    scriptTemplateDirty ||
    directorRuleDirty ||
    directorRhythmDirty ||
    directorSpeakerRosterDirty ||
    promptAssetNameMapDirty
  const promptEditorTextareaMaxHeight =
    typeof maxHeight === "number"
      ? isStoryboardPrompt
        ? maximized
          ? Math.max(240, Math.min(560, maxHeight - 118))
          : Math.max(170, Math.min(360, maxHeight - 118))
        : isDirectorBoard
          ? maximized
            ? Math.max(240, Math.min(560, maxHeight - 150))
            : Math.max(240, Math.min(420, maxHeight - 190))
          : maximized
            ? Math.max(160, Math.min(480, maxHeight - 150))
            : Math.max(92, Math.min(280, maxHeight - 190))
      : undefined
  const inlineAssetRows = useMemo(() => {
    if (!showsInlineAssetLinks) return []
    return inlineAssetDisplayMentionRows(data)
  }, [
    showsInlineAssetLinks,
    data.referenceDisplayRows,
    data.assetRefs,
    data.assetThumbnails,
    data.eyebrow,
    data.inputLinks,
    data.referenceVideoThumbnails,
    data.referenceThumbnails,
    data.referenceManifest,
  ])
  const linkedAssetTags = useMemo(() => {
    if (!supportsAssetMention) return []
    return collectInlineAssetTags(inlineAssetRows, inlineAssetDisplayRefs(data))
      .tags
  }, [inlineAssetRows, supportsAssetMention, data.assetRefs, data.eyebrow])
  const mentionAssetTags = useMemo(
    () => promptMentionOptions(data.referenceManifest ?? [], linkedAssetTags),
    [linkedAssetTags, data.referenceManifest]
  )
  useLayoutEffect(() => {
    if (!isVideoPrompt || !data.workflowCardDetailLoaded) return
    syncPromptMentions(mentionAssetTags)
  }, [isVideoPrompt, data.workflowCardDetailLoaded, mentionAssetTags, promptEditorDraft.text, promptEditorDraft.promptBindings, syncPromptMentions])
  const mentionQuery = assetMentionRange?.query ?? ""
  const [mentionIndex, setMentionIndex] = useState(0)
  const mentionListRef = useRef<HTMLDivElement>(null)
  useEffect(() => setMentionIndex(0), [mentionQuery])
  const filteredLinkedAssetTags = useMemo(() => {
    const keyword = mentionQuery.trim().toLocaleLowerCase()
    if (!keyword) return mentionAssetTags
    return mentionAssetTags.filter((tag) =>
      `${tag.label} ${tag.title}`.toLocaleLowerCase().includes(keyword)
    )
  }, [mentionAssetTags, mentionQuery])
  const visibleLinkedAssetTags = filteredLinkedAssetTags
  const waitForWorkflowCardDetails =
    usesResolvedAssetDetails &&
    !data.workflowCardDetailLoaded &&
    inlineAssetRows.length === 0
  const activeMentionKey = visibleLinkedAssetTags[mentionIndex]?.key
  useLayoutEffect(() => {
    if (!assetMentionOpen || waitForWorkflowCardDetails) return
    const list = mentionListRef.current
    const selected = list?.querySelector<HTMLElement>('[aria-selected="true"]')
    if (!list || !selected) return
    // Only selection changes may scroll the menu; ordinary renders preserve wheel position.
    const bounds = list.getBoundingClientRect()
    const item = selected.getBoundingClientRect()
    const top = bounds.top + list.clientTop
    const bottom = top + list.clientHeight
    if (item.top < top) list.scrollTop += item.top - top
    else if (item.bottom > bottom) list.scrollTop += item.bottom - bottom
  }, [assetMentionOpen, mentionIndex, mentionQuery, activeMentionKey, waitForWorkflowCardDetails])

  const handlePromptDraftChange = (
    value: string,
    caret?: number,
    anchor?: AssetMentionAnchor
  ) => {
    const nextRange = activeAssetMentionRange(value, caret ?? value.length)
    setPromptEditorDraft((current) => ({ ...current, text: value,
      promptBindings: bindPromptMentions(value, current.promptBindings, mentionAssetTags, [current.soundPrompt ?? ""]),
    }))
    setAssetMentionRange(nextRange)
    setAssetMentionAnchor(nextRange ? (anchor ?? null) : null)
    setAssetMentionOpen(Boolean(supportsAssetMention && nextRange))
  }

  const handleOpenAssetPicker = useCallback(
    (value: string, caret?: number, anchor?: AssetMentionAnchor) => {
      if (!supportsAssetMention) return
      const nextRange = activeAssetMentionRange(value, caret ?? value.length)
      if (!nextRange) {
        setAssetMentionRange(null)
        setAssetMentionAnchor(null)
        setAssetMentionOpen(false)
        return
      }
      setAssetMentionRange(nextRange)
      setAssetMentionAnchor(anchor ?? null)
      setAssetMentionOpen(true)
    },
    [supportsAssetMention]
  )

  const handleSelectLinkedAsset = (
    event: { stopPropagation: () => void },
    tag: PromptMentionOption
  ) => {
    event.stopPropagation()
    const input = document.activeElement
    const caret = assetMentionRange ? assetMentionRange.start + tag.label.length + 3 : undefined
    setPromptEditorDraft((current) => {
      const selected = mentionAssetTags.find((option) => option.key === tag.key)
      if (!selected) return current
      const text = insertAssetMention(current.text, selected.label, assetMentionRange)
      return {
        ...current,
        text,
        promptBindings: bindPromptMentions(text, { ...current.promptBindings, [selected.label]: selected.key }, mentionAssetTags, [current.soundPrompt ?? ""]),
        assetNameMap:
          selected.key.startsWith("asset:")
            ? { ...current.assetNameMap, [selected.assetId]: selected.label }
            : current.assetNameMap,
      }
    })
    setAssetMentionRange(null)
    setAssetMentionAnchor(null)
    setAssetMentionOpen(false)
    if (input instanceof HTMLTextAreaElement && caret !== undefined) {
      requestAnimationFrame(() => { input.focus(); input.setSelectionRange(caret, caret) })
    }
  }

  const assetMentionPopover =
    supportsAssetMention &&
    !editorLocked &&
    !waitForWorkflowCardDetails &&
    assetMentionOpen &&
    visibleLinkedAssetTags.length > 0 &&
    typeof document !== "undefined"
      ? createPortal(
          <div
            ref={mentionListRef}
            role="listbox"
            aria-label="关联资产"
            className="nodrag nopan nowheel fixed z-[320] max-h-44 w-[min(18rem,calc(100vw-1rem))] overflow-y-auto overscroll-contain rounded-md border border-gray-200 bg-white/95 p-1.5 shadow-xl shadow-gray-950/15 backdrop-blur-xl dark:border-white/10 dark:bg-[#1f1f1f]/96"
            style={{
              left: assetMentionAnchor?.left ?? 8,
              top: assetMentionAnchor?.top ?? 8,
            }}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => event.stopPropagation()}
            onWheel={stopCardWheel}
            onWheelCapture={stopCardWheel}
          >
            <div className="grid gap-1">
              {visibleLinkedAssetTags.map((tag, index) => (
                <button
                  key={tag.key}
                  type="button"
                  title={tag.title}
                  role="option"
                  aria-label={`${PROMPT_MENTION_TYPE_LABELS[tag.kind]}：${tag.label}`}
                  aria-selected={index === mentionIndex}
                  className={cn("flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-left text-[11px] text-gray-700 transition-colors hover:bg-gray-100 dark:text-white/75 dark:hover:bg-white/[0.08]", index === mentionIndex && "bg-gray-100 dark:bg-white/10")}
                  onMouseDown={(event) => {
                    event.preventDefault()
                    event.stopPropagation()
                  }}
                  onClick={(event) => handleSelectLinkedAsset(event, tag)}
                >
                  {tag.previewSrc && <img src={tag.previewSrc} alt="" className="h-7 w-7 shrink-0 rounded-sm object-cover" />}
                  <span className="block min-w-0 flex-1 break-words">{tag.label}</span>
                  <span className={cn("shrink-0 rounded-sm px-1 py-0.5 text-[10px]", PROMPT_MENTION_COLORS[tag.kind])}>{PROMPT_MENTION_TYPE_LABELS[tag.kind]}</span>
                </button>
              ))}
            </div>
          </div>,
          document.body
        )
      : null

  const handleCancelPrompt = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    resetPromptDraft(savedVisiblePromptDraft)
    setDirectorShotDrafts(savedDirectorShotDrafts)
    setDirectorSpeakerRoster(savedDirectorSpeakerRoster)
    setDirectorPendingEdit(false)
    setSourceFactDraft(sourceFactValue)
    setScriptTemplateId(savedScriptTemplateId)
    setDirectorRuleId(savedDirectorRuleId)
    setDirectorRhythmMultiplier(String(savedDirectorRhythmMultiplier))
    setAssetMentionRange(null)
    setAssetMentionAnchor(null)
    setAssetMentionOpen(false)
  }

  const templateDescription = (templateId: string) =>
    workflowLibraryTemplateDescription(
      scriptTemplatesForNode.find((template: any) => template.id === templateId)
    )

  const storyboardPromptPatch = () =>
    storyboardPromptEditDataPatch(data, promptDraft, {
      sourceFactText: sourceFactDraft,
      scriptTemplateId,
      scriptTemplateLabel: scriptTemplateName,
      scriptEdited: promptTextDirty,
    })

  const directorPromptPatch = (): Partial<WorkflowNodeData> => ({
    ...(promptTextDirty ? { directorPlanShots: directorPlanShotsForSave(directorShotDrafts, directorPlanShotRecordsForNode(data)) } : {}),
    ...(directorSpeakerRosterDirty
      ? { speakerRoster: normalizeDirectorPlanSpeakerRosterForSave(directorSpeakerRoster) }
      : {}),
    ...(directorRuleDirty ? {
      directorRuleId: directorRuleId.trim() || null,
      directorRuleSelectionMode: directorRuleId.trim() ? "manual" as const : "auto" as const,
    } : {}),
    ...(directorRhythmDirty ? { rhythmMultiplier: directorRhythmMultiplier ? Number(directorRhythmMultiplier) : null } : {}),
  })

  const scriptRuleControl =
    isStoryboardPrompt && scriptTemplatesForNode.length ? (
      <WorkflowCompactParameterMenu
        label="创作策略"
        value={scriptTemplateId}
        options={scriptTemplatesForNode.map((template: any) => template.id)}
        emptyLabel="标准忠实影视化"
        formatLabel={(templateId) =>
          workflowLibraryTemplateName(
            scriptTemplatesForNode.find(
              (template: any) => template.id === templateId
            )
          ) || templateId
        }
        formatDescription={templateDescription}
        disabled={saving}
        onChange={setScriptTemplateId}
      />
    ) : null

  const directorRuleControl =
    isDirectorBoard ? (
      <WorkflowCompactParameterMenu
        label="导演规则"
        value={directorRuleId}
        options={directorRuleOptions.map((option: any) => option.value)}
        emptyLabel="自动选择"
        allowUnset
        unsetLabel="自动选择"
        formatLabel={(value) =>
          directorRuleOptions.find((option: any) => option.value === value)?.label ||
          value
        }
        formatDescription={(value) =>
          directorRuleOptions.find((option: any) => option.value === value)?.description || ""
        }
        disabled={saving}
        onChange={setDirectorRuleId}
      />
    ) : null

  const directorRhythmControl = isDirectorBoard ? (
    <label className="flex shrink-0 items-center gap-1.5 rounded-sm border border-gray-200/80 px-2 py-1 text-[11px] text-gray-600 dark:border-white/[0.12] dark:text-white/60" title="默认跟随项目视频节奏；单独选择后覆盖项目设置">
      镜头节奏
      <select
        value={directorRhythmMultiplier}
        disabled={saving}
        onChange={(event) => setDirectorRhythmMultiplier(event.target.value)}
        onPointerDown={(event) => event.stopPropagation()}
        aria-label="镜头节奏倍率"
        className="bg-transparent text-right text-[11px] font-medium text-gray-800 outline-none dark:text-white/85"
      >
        <option value="">跟随项目设置</option>
        {Array.from({ length: 10 }, (_, index) => (1.1 + index / 10).toFixed(1)).map((value) => <option key={value} value={value}>{value} 倍</option>)}
      </select>
    </label>
  ) : null

  const handleSavePrompt = (
    event: MouseEvent<HTMLButtonElement>,
    options?: ManualSaveOptions
  ) => {
    event.stopPropagation()
    if (isDirectorBoard && promptTextDirty) {
      const issue = directorPlanShotValidationIssue(directorShotDrafts)
      if (issue) { toast.error(issue); return }
    }
    const promptPatch = isStoryboardPrompt
      ? storyboardPromptPatch()
      : isDirectorBoard
        ? directorPromptPatch()
        : isVideoPrompt
          ? videoTaskFinalPromptDataPatch(
              data,
              promptDraft,
              false,
              promptEditorDraft.assetNameMap,
              promptEditorDraft.promptBindings,
              soundPromptDraft,
              voiceSettingsDraft,
            )
          : { prompt: nextPromptValue(data, promptDraft) }
    return data.onUpdateNodeData?.(id, promptPatch, promptSaveReason, options)
  }

  const promptEditorBody = (
    <>
      {maximized && showsVoiceSettings ? <div className="mb-2 shrink-0 text-xs font-medium text-gray-700 dark:text-gray-200">视频提示词</div> : null}
      <InlinePromptEditor
        data={data}
        draft={isDirectorBoard ? directorPlanDraft : promptDraft}
        sourceFactDraft={sourceFactDraft}
        directorShotDrafts={directorShotDrafts}
        directorSpeakerRoster={directorSpeakerRoster}
        directorSoundSourceOptions={directorSoundSourceOptions}
        onSourceFactDraftChange={setSourceFactDraft}
        onDirectorShotDraftsChange={setDirectorShotDrafts}
        onDirectorSpeakerRosterChange={setDirectorSpeakerRoster}
        onDirectorPendingChange={setDirectorPendingEdit}
        onDraftChange={handlePromptDraftChange}
        onMentionTrigger={handleOpenAssetPicker}
        promptMaxHeight={promptEditorTextareaMaxHeight}
        maximized={maximized}
        readOnly={editorLocked}
        mentionOptions={mentionAssetTags}
        promptBindings={promptEditorDraft.promptBindings}
        onHistoryAction={(direction) => {
          if (editorLocked || !data.workflowCardDetailLoaded) return
          movePromptHistory(direction, mentionAssetTags)
          setAssetMentionRange(null)
          setAssetMentionAnchor(null)
          setAssetMentionOpen(false)
        }}
        onMentionKeyDown={(event) => {
          if (!assetMentionOpen || !visibleLinkedAssetTags.length || event.nativeEvent.isComposing) return
          if (event.key === "Escape") { event.preventDefault(); setAssetMentionOpen(false) }
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault()
            setMentionIndex((index) => (index + (event.key === "ArrowDown" ? 1 : -1) + visibleLinkedAssetTags.length) % visibleLinkedAssetTags.length)
          }
          if (event.key === "Enter") {
            event.preventDefault()
            handleSelectLinkedAsset(event, visibleLinkedAssetTags[Math.min(mentionIndex, visibleLinkedAssetTags.length - 1)])
          }
        }}
      />
    </>
  )
  const promptEditor = (
    <div className={cn("relative", maximized && (
      showsVoiceSettings
        ? "grid h-full min-h-0 flex-1 grid-cols-[minmax(220px,0.75fr)_minmax(0,2fr)] gap-4 overflow-hidden"
        : "flex h-full min-h-0 flex-col overflow-y-auto"
    ))}>
      {maximized && showsVoiceSettings ? (
        <aside className="min-h-0 min-w-0 overflow-y-auto overscroll-contain rounded-lg border border-gray-200/80 bg-white/70 p-3 dark:border-white/[0.07] dark:bg-[#18181b]">
          <VideoTaskVoiceSettings id={id} data={data} soundPrompt={soundPromptDraft} settings={voiceSettingsDraft}
            readOnly={editorLocked} onSettingsChange={(voiceSettings, soundPrompt) =>
              setPromptEditorDraft((current) => ({ ...current, voiceSettings, soundPrompt,
                promptBindings: bindPromptMentions(current.text, current.promptBindings, mentionAssetTags, [soundPrompt]),
              }))} />
        </aside>
      ) : null}
      <div className={maximized && showsVoiceSettings
        ? "flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-gray-200/80 bg-white/70 p-3 dark:border-white/[0.07] dark:bg-[#18181b]"
        : "contents"}>
        {promptEditorBody}
      </div>
    </div>
  )
  const linkedAssets = showsInlineAssetLinks ? (
    waitForWorkflowCardDetails ? (
      <InlineAssetLinksLoadingSlot
        active={data.isHydratingWorkflowCard}
        compact={maximized}
      />
    ) : (
      <InlineAssetLinks
        id={id}
        data={data}
        reserveSpace={supportsAssetMention}
        compact={maximized}
      />
    )
  ) : null
  const generationControls = isDirectorBoard ? (
    <div className={cn("nodrag nopan nowheel", maximized ? "shrink-0" : "mt-3", WORKFLOW_INLINE_PARAMETER_BAR_CLASS, maximized && "border-t-0 pt-0")}>
      <div className={WORKFLOW_INLINE_PARAMETER_ROW_CLASS}>
        {directorRuleControl}{directorRhythmControl}
        <InlineSaveControls
          dirty={promptDirty}
          onRestore={handleCancelPrompt}
          onSave={handleSavePrompt}
          saving={editorLocked}
          maximized={maximized}
        />
      </div>
    </div>
  ) : (
    <InlineGenerationControls
      id={id}
      data={data}
      promptDraft={isVideoPrompt ? promptDraft : undefined}
      soundPromptDraft={isVideoPrompt ? soundPromptDraft : undefined}
      promptAssetNameMap={isVideoPrompt ? promptEditorDraft.assetNameMap : undefined}
      promptBindings={isVideoPrompt ? promptEditorDraft.promptBindings : undefined}
      onOptimizationQueued={isVideoPrompt ? expectAgentSave : undefined}
      onPrepareOptimization={voiceSettingsDirty ? async () => {
        if (!data.onUpdateNodeData) throw new Error("声音设置暂时无法保存")
        await data.onUpdateNodeData(id, { videoTaskCard: voiceSettingsDraft }, "更新任务声音设置")
      } : undefined}
      promptDirty={promptDirty}
      promptPatch={
        promptDirty
          ? isDirectorBoard
            ? directorPromptPatch()
            : isVideoPrompt
              ? videoTaskFinalPromptDataPatch(
                  data,
                  promptDraft,
                  false,
                  promptEditorDraft.assetNameMap,
                  promptEditorDraft.promptBindings,
                  soundPromptDraft,
                  voiceSettingsDraft,
                )
              : { prompt: nextPromptValue(data, promptDraft) }
          : undefined
      }
      promptReason={promptSaveReason}
      extraParameterControls={
        typeof videoPromptCharacterCount === "number"
            ? (
                <span className="shrink-0 text-[11px] font-medium tabular-nums text-gray-400 dark:text-white/35">
                  {videoPromptCharacterCount}字
                </span>
              )
            : null
      }
      saving={editorLocked}
      onSavingChange={setSaving}
      onCancelPrompt={handleCancelPrompt}
      onSavePrompt={handleSavePrompt}
      maximized={maximized}
    />
  )
  const storyboardControls = (
    <div
      className={cn(
        "nodrag nopan nowheel",
        maximized ? "shrink-0" : "mt-3",
        WORKFLOW_INLINE_PARAMETER_BAR_CLASS,
        maximized && "border-t-0 pt-0"
      )}
    >
      <div className={WORKFLOW_INLINE_PARAMETER_ROW_CLASS}>
        {scriptRuleControl}
        <InlineSaveControls
          dirty={promptDirty}
          onRestore={handleCancelPrompt}
          onSave={handleSavePrompt}
          saving={saving}
          maximized={maximized}
        />
      </div>
    </div>
  )
  const editorContent = (
    <>
      {data.eyebrow === "video.character_replace" ? (
        <p className="mb-2 text-[11px] leading-relaxed text-gray-500 dark:text-white/45">
          关联一段源视频和角色图，沿用原片表演、镜头与原声。多角色按图号指定替换对应关系；建议一次替换 3–4 个主要角色。源视频建议覆盖输出时长，并与输出画幅一致。
        </p>
      ) : null}
      {promptEditor}
      {assetMentionPopover}
      {!maximized ? linkedAssets : null}
    </>
  )
  return (
    <div className={maximized ? "flex h-full min-h-0 flex-col overflow-hidden" : "contents"}>
      <div className={maximized
        ? showsVoiceSettings ? "flex min-h-0 flex-1 flex-col overflow-hidden" : "min-h-0 flex-1 overflow-y-auto pr-1"
        : "contents"}>
        {editorContent}
      </div>
      <div className={maximized ? "absolute inset-x-0 bottom-0 z-20 border-t border-gray-200/80 bg-white dark:border-white/[0.07] dark:bg-[#18181b]" : "contents"}>
        <div className={maximized ? "px-5 py-3" : "contents"}>
          {isStoryboardPrompt ? storyboardControls : generationControls}
        </div>
      </div>
    </div>
  )
}

export function StoryboardTaskDetailsEditor({
  node,
  maxHeight,
}: {
  node: StoryboardNodeLike
  maxHeight?: number
}) {
  const { id, data } = node
  const sourceFactText = storyboardSourceFactTextForNode(data)
  const savedScriptText = storyboardStoryTextForNode(data)
  const savedScriptTemplateId = storyboardScriptTemplateValue(data)
  const scriptTemplatesForNode = workflowScriptAdaptationTemplates(data)
  const [sourceFactDraft, setSourceFactDraft] = useState(() => sourceFactText)
  const [scriptDraft, setScriptDraft] = useState(() => savedScriptText)
  const [scriptTemplateId, setScriptTemplateId] = useState(
    () => savedScriptTemplateId
  )
  const [saving, setSaving] = useState(false)

  useEffect(() => { setSourceFactDraft(sourceFactText) }, [id, sourceFactText])
  useEffect(() => { setScriptDraft(savedScriptText) }, [id, savedScriptText])
  useEffect(() => { setScriptTemplateId(savedScriptTemplateId) }, [id, savedScriptTemplateId])

  const selectedScriptTemplate = scriptTemplatesForNode.find(
    (template: any) => template.id === scriptTemplateId
  )
  const scriptTemplateName =
    workflowLibraryTemplateName(selectedScriptTemplate) || scriptTemplateId
  const sourceFactDirty = sourceFactDraft.trim() !== sourceFactText.trim()
  const scriptDirty = scriptDraft.trim() !== savedScriptText.trim()
  const templateDirty = scriptTemplateId !== savedScriptTemplateId
  const dirty = sourceFactDirty || scriptDirty || templateDirty
  const continuityReview = data.scriptContinuityReview
  const confirmContinuity = async (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    if (saving || dirty || !continuityReview || !data.onUpdateNodeData) return
    setSaving(true)
    try {
      await data.onUpdateNodeData(id, { scriptContinuityReview: continuityReview },
        "storyboard_script_continuity_reviewed", { successMessage: "剧本衔接已确认，保留当前剧本" })
    } catch {
      // The save callback owns user-facing error toasts.
    } finally {
      setSaving(false)
    }
  }
  const detailTextareaLayout = storyboardScriptEditorTextareaLayout(
    typeof maxHeight === "number"
      ? Math.max(170, Math.min(360, maxHeight - 176))
      : undefined
  )
  const templateDescription = (templateId: string) =>
    workflowLibraryTemplateDescription(
      scriptTemplatesForNode.find((template: any) => template.id === templateId)
    )

  const handleRestore = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    setSourceFactDraft(sourceFactText)
    setScriptDraft(savedScriptText)
    setScriptTemplateId(savedScriptTemplateId)
  }

  const saveDrafts = async (options?: ManualSaveOptions) => {
    if (!dirty) return true
    if (!data.onUpdateNodeData) return false
    await data.onUpdateNodeData(
      id,
      storyboardPromptEditDataPatch(data, scriptDraft, {
        scriptTemplateId,
        scriptTemplateLabel: scriptTemplateName,
        sourceFactText: sourceFactDraft,
        scriptEdited: scriptDirty,
      }),
      "storyboard_detail_script_saved",
      options
    )
    return true
  }

  const handleSave = async (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    if (saving || !dirty) return
    setSaving(true)
    try {
      await saveDrafts({ successMessage: "片段剧本已保存" })
    } catch {
      // The save callback owns user-facing error toasts.
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="grid min-h-0 gap-3">
      <div className="grid min-h-0 items-stretch gap-3 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="flex h-full min-h-0 min-w-0 flex-col">
          <div className="mb-2 text-[11px] font-semibold text-gray-500 dark:text-white/50">
            原文事实
          </div>
          <Textarea
            value={sourceFactDraft}
            onChange={(event) => setSourceFactDraft(event.target.value)}
            onPointerDown={(event) => event.stopPropagation()}
            onWheel={stopCardWheel}
            onWheelCapture={stopCardWheel}
            placeholder="这里保存从原文拆分出的事实内容"
            aria-label="原文事实"
            className={fixedCompactWorkflowTextareaClassName()}
            style={fixedWorkflowTextareaHeightStyle(
              detailTextareaLayout.sourceFactHeight
            )}
            spellCheck={false}
          />
        </div>
        <div className="flex min-h-0 min-w-0 flex-col border-t border-gray-200 pt-3 xl:border-t-0 xl:border-l xl:pt-0 xl:pl-3 dark:border-white/[0.08]">
          <div className="mb-2 text-[11px] font-semibold text-gray-500 dark:text-white/50">
            影视化剧本
          </div>
          <Textarea
            value={scriptDraft}
            onChange={(event) => setScriptDraft(event.target.value)}
            onPointerDown={(event) => event.stopPropagation()}
            onWheel={stopCardWheel}
            onWheelCapture={stopCardWheel}
            placeholder={workflowTaskEditorPlaceholder(data)}
            aria-label="影视化剧本"
            className={fixedCompactWorkflowTextareaClassName()}
            style={fixedWorkflowTextareaHeightStyle(
              detailTextareaLayout.scriptHeight
            )}
            spellCheck={false}
          />
        </div>
      </div>
      <div
        className={cn(
          "-mx-3 -mb-3 px-3 py-2",
          WORKFLOW_INLINE_PARAMETER_BAR_CLASS
        )}
      >
        <div className={WORKFLOW_INLINE_PARAMETER_ROW_CLASS}>
          {continuityReview && (
            <button
              type="button"
              onClick={(event) => void confirmContinuity(event)}
              disabled={saving || dirty || !data.onUpdateNodeData || Boolean(data.locked || data.lockedByUser) || data.status === "running"}
              title={dirty ? "请先保存或撤销修改，再确认衔接" : "已核对与前一片段的衔接，保留当前剧本"}
              className="shrink-0 rounded-md border border-amber-300 px-2 py-1 text-xs text-amber-700 disabled:opacity-40 dark:border-amber-500/40 dark:text-amber-300"
            >确认衔接</button>
          )}
          {scriptTemplatesForNode.length ? (
            <WorkflowCompactParameterMenu
              label="创作策略"
              value={scriptTemplateId}
              options={scriptTemplatesForNode.map((template: any) => template.id)}
              emptyLabel="标准忠实影视化"
              formatLabel={(templateId) =>
                workflowLibraryTemplateName(
                  scriptTemplatesForNode.find(
                    (template: any) => template.id === templateId
                  )
                ) || templateId
              }
              formatDescription={templateDescription}
              onChange={setScriptTemplateId}
            />
          ) : (
            <span className="rounded-sm bg-gray-100 px-2 py-1 text-[11px] text-gray-500 dark:bg-white/[0.06] dark:text-white/45">
              暂无剧本模板
            </span>
          )}
          <InlineSaveControls
            dirty={dirty && Boolean(data.onUpdateNodeData)}
            onRestore={handleRestore}
            onSave={handleSave}
            saving={saving}
          />
        </div>
      </div>
    </div>
  )
}

export { WorkflowTaskEditor }
