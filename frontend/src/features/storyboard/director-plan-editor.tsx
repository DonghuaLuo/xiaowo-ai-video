import { useEffect, useRef, useState, type ReactNode, type WheelEvent } from "react"
import { toast } from "sonner"
import { ChevronDown, ListCollapse, Plus, Trash2 } from "lucide-react"
import { Checkbox } from "@/components/ui/checkbox"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { cn } from "@/lib/utils"
import { getDirectorPlanAssetCatalog, type DirectorPlanAssetCatalog } from "@/backend"
import { useBackend } from "@/hooks/useBackend"
import "./director-plan-editor.css"

export type DirectorPlanSoundEventDraft = {
  kind: string
  voiceType: string
  speakerId: string
  sourceName: string
  content: string
  expressionNotes: string
  timing: string
  durationSec: string
  deliveryOverride?: {
    durationSec: number
    evidenceSource: string
    evidenceText: string
    reason: string
  }
}

export type DirectorPlanScreenTextEventDraft = {
  content: string
  medium: string
  authorLabel: string
  timing: string
  visibleAtStart: boolean
}

export type DirectorPlanIndependentBeatDraft = {
  description: string
  durationSec: string
}

export type DirectorPlanPresentationDraft = {
  segmentId: string
  modes: string[]
  sourcePerspective: string
  certainty: string
  timeRelation: string
  entryCue: string
  exitCue: string
  eventLabel?: { content: string; sourceQuote: string; visibleAtStart: boolean }
}

export type DirectorPlanShotDraft = {
  shotNo: number
  sourceShotNo?: number
  durationSec: string
  normalDurationSec?: string
  visualPurpose?: string
  storyboardFrame: string
  videoExecution: string
  endState?: string
  assets?: DirectorPlanShotAssets
  visibleAssets?: DirectorPlanShotAssets
  startVisibleAssets?: DirectorPlanShotAssets
  assetReviewRequired?: boolean
  groupBreakBefore?: boolean
  entryBoundaryKind?: string
  audioBoundaryKind?: string
  nonOverlappingBeats?: DirectorPlanIndependentBeatDraft[]
  independentBeatsNeedReview?: boolean
  screenTextEvents: DirectorPlanScreenTextEventDraft[]
  presentation?: DirectorPlanPresentationDraft
  soundEvents: DirectorPlanSoundEventDraft[]
}

export type DirectorPlanShotAssets = Record<"characters" | "creatures" | "scenes" | "props", string[]>

const SHOT_ASSET_KINDS = ["characters", "creatures", "scenes", "props"] as const
const ENTRY_BOUNDARY_OPTIONS = [
  { value: "", label: "待判断" },
  { value: "direct_continuation", label: "无切镜直续" },
  { value: "spatial_cut", label: "同空间换机位" },
  { value: "ordinary_cut", label: "普通切镜" },
  { value: "time_space_jump", label: "跳时或换场" },
]
const AUDIO_BOUNDARY_OPTIONS = [
  { value: "", label: "待判断" },
  { value: "continuous_ambience", label: "环境声延续" },
  { value: "dialogue_overlap", label: "对白跨切口" },
  { value: "hard_cut", label: "声音硬切" },
  { value: "intentional_silence", label: "有意静默" },
]
const SHOT_ASSET_KIND_LABELS = { characters: "角色", creatures: "生物", scenes: "场景", props: "道具" }
const emptyDirectorPlanShotAssets = (): DirectorPlanShotAssets => ({ characters: [], creatures: [], scenes: [], props: [] })

export function setDirectorPlanShotAssetState(
  shot: DirectorPlanShotDraft,
  kind: keyof DirectorPlanShotAssets,
  assetId: string,
  state: "unused" | "offscreen" | "visible" | "start",
): DirectorPlanShotDraft {
  const copy = (value?: DirectorPlanShotAssets): DirectorPlanShotAssets => Object.fromEntries(
    SHOT_ASSET_KINDS.map((key) => [key, [...(value?.[key] ?? [])]]),
  ) as DirectorPlanShotAssets
  const assets = copy(shot.assets)
  const visibleAssets = copy(shot.visibleAssets)
  const startVisibleAssets = copy(shot.startVisibleAssets ?? shot.visibleAssets)
  for (const rows of [assets, visibleAssets, startVisibleAssets]) {
    rows[kind] = rows[kind].filter((id) => id !== assetId)
  }
  if (state !== "unused") assets[kind].push(assetId)
  if (state === "visible" || state === "start") visibleAssets[kind].push(assetId)
  if (state === "start") startVisibleAssets[kind].push(assetId)
  return { ...shot, assets, visibleAssets, startVisibleAssets }
}

export type DirectorPlanSpeakerDraft = {
  speakerId: string
  displayName: string
  identityDescription: string
}

export type DirectorPlanSpeakerRosterDraft = DirectorPlanSpeakerDraft[]

export const DIRECTOR_PLAN_SOUND_KIND_OPTIONS = [
  { value: "voice", label: "人声" },
  { value: "ambient", label: "环境声" },
  { value: "sfx", label: "音效" },
  { value: "music", label: "音乐" },
]

export const DIRECTOR_PLAN_VOICE_TYPE_OPTIONS = [
  { value: "dialogue", label: "对白" },
  { value: "self_talk", label: "自述" },
  { value: "inner_thought", label: "内心独白" },
  { value: "crowd", label: "群众声" },
  { value: "narration", label: "旁白" },
]

const PRESENTATION_MODE_OPTIONS = [
  { value: "chronological_compression", label: "顺时压缩" },
  { value: "process_montage", label: "过程蒙太奇" },
  { value: "memory", label: "角色回忆" },
  { value: "dream", label: "梦境" },
  { value: "imagination", label: "想象" },
  { value: "inner", label: "内心" },
  { value: "character_account", label: "人物讲述" },
  { value: "reported", label: "转述" },
  { value: "mediated", label: "媒介影像" },
  { value: "parallel", label: "并行行动" },
  { value: "perceptual_distortion", label: "感知失真" },
  { value: "romantic_ambiguity", label: "暧昧" },
  { value: "time_jump", label: "时间跳跃" },
  { value: "normal", label: "普通现场" },
]

function presentationModeLabel(value: string) {
  return PRESENTATION_MODE_OPTIONS.find((option) => option.value === value)?.label ?? value
}

export function togglePresentationMode(currentModes: string[], mode: string) {
  const allowedModes = new Set(PRESENTATION_MODE_OPTIONS
    .filter((option) => option.value !== "normal")
    .map((option) => option.value))
  if (!allowedModes.has(mode)) return currentModes
  const selected = [...new Set(currentModes.filter((value) => allowedModes.has(value)))]
  if (selected.includes(mode)) return selected.length > 1
    ? selected.filter((value) => value !== mode)
    : selected
  return [...selected, mode]
}

function DirectorPlanPresentationModeSelect({
  modes,
  readOnly,
  onChange,
}: {
  modes: string[]
  readOnly: boolean
  onChange: (modes: string[]) => void
}) {
  const options = PRESENTATION_MODE_OPTIONS.filter((option) => option.value !== "normal")
  const label = modes.map(presentationModeLabel).join("、") || "选择类型"
  return <div className="director-plan-field min-w-0 pl-[6ch] -indent-[6ch] text-[13px] leading-[20.2px]">
    <span className={cn("font-medium", syntaxColor.field)}>表达类型</span>
    <span className={syntaxColor.punctuation}>: </span>
    {readOnly ? <span className={syntaxColor.choice}>{label}</span> : <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="选择表达类型"
          onPointerDown={(event) => event.stopPropagation()}
          className="inline-flex max-w-full items-center gap-1 align-baseline text-left text-[#7138a8] underline decoration-dotted underline-offset-2 dark:text-[#c792ea]"
        >
          <span className="min-w-0 break-words">{label}</span>
          <ChevronDown className="size-3 shrink-0" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={4}
        onPointerDown={(event) => event.stopPropagation()}
        className="z-[400] max-h-72 w-52 overflow-y-auto p-1.5 text-xs"
      >
        <div role="group" aria-label="表达类型选项">
          {options.map((option) => {
            const checked = modes.includes(option.value)
            return <label key={option.value} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-slate-100 dark:hover:bg-white/10">
              <input
                type="checkbox"
                value={option.value}
                checked={checked}
                disabled={checked && modes.length === 1}
                onChange={() => onChange(togglePresentationMode(modes, option.value))}
                className="accent-violet-700 disabled:cursor-not-allowed"
              />
              <span>{option.label}</span>
            </label>
          })}
        </div>
      </PopoverContent>
    </Popover>}
  </div>
}

export type DirectorPlanSoundSourceOption = {
  value: string
  label: string
  description?: string
}

const syntaxColor = {
  heading: "text-[#245fc7] dark:text-[#6ea8ff]",
  shot: "text-[#245fc7] dark:text-[#6ea8ff]",
  group: "text-[#626b79] dark:text-[#8b949e]",
  field: "text-[#626b79] dark:text-[#8b949e]",
  string: "text-[#242b37] dark:text-[#d6dce6]",
  number: "text-[#126f8c] dark:text-[#65c7e8]",
  choice: "text-[#7138a8] dark:text-[#c792ea]",
  source: "text-[#087879] dark:text-[#3fc6c8]",
  punctuation: "text-[#717986] dark:text-[#707784]",
  muted: "text-[#626b79] dark:text-[#8b949e]",
} as const

function stopCardWheel(event: WheelEvent<HTMLElement>) {
  event.stopPropagation()
  event.nativeEvent.stopImmediatePropagation?.()
}

function workflowNodeId(prefix: string) {
  const raw =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}_${raw.replace(/[^a-zA-Z0-9]+/g, "_").slice(0, 18)}`
}

function editorTextareaHeight(maxHeight?: number, expanded = false) {
  const defaultHeight = expanded ? 420 : 320
  const maxEditorHeight = expanded ? 560 : 420
  if (typeof maxHeight !== "number") return defaultHeight
  return Math.min(maxEditorHeight, Math.max(150, Math.round(maxHeight)))
}

function compactValue(value: unknown) {
  if (value == null) return ""
  return String(value).replace(/\s+/g, " ").trim()
}

export function parseDirectorPlanDuration(text: string, required = false) {
  const trimmed = text.trim()
  if (!trimmed) return required ? null : ""
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(trimmed)) return null
  const seconds = Number(trimmed)
  return Number.isFinite(seconds) && seconds > 0 && seconds <= 3600 ? trimmed : null
}

function emptyShotDraft(index: number): DirectorPlanShotDraft {
  return {
    shotNo: index + 1,
    durationSec: "",
    storyboardFrame: "",
    videoExecution: "",
    assets: emptyDirectorPlanShotAssets(),
    visibleAssets: emptyDirectorPlanShotAssets(),
    startVisibleAssets: emptyDirectorPlanShotAssets(),
    nonOverlappingBeats: [],
    screenTextEvents: [],
    soundEvents: [],
  }
}

function renumberShotDrafts(shots: DirectorPlanShotDraft[]) {
  return shots.map((shot, index) => ({ ...shot, shotNo: index + 1 }))
}

export function updateSharedPresentationDrafts(
  shots: DirectorPlanShotDraft[],
  shotIndex: number,
  patch: Partial<Pick<DirectorPlanPresentationDraft, "modes" | "sourcePerspective" | "certainty" | "timeRelation">>,
) {
  const segmentId = shots[shotIndex]?.presentation?.segmentId
  if (!segmentId) return shots
  return shots.map((shot) => shot.presentation && shot.presentation.segmentId === segmentId
    ? { ...shot, presentation: { ...shot.presentation, ...patch } }
    : shot)
}

export function joinPreviousPresentationDrafts(shots: DirectorPlanShotDraft[], shotIndex: number) {
  const previous = shots[shotIndex - 1]?.presentation
  const current = shots[shotIndex]?.presentation
  if (!previous?.segmentId || !shots[shotIndex] || current?.segmentId === previous.segmentId) return shots
  const oldSegmentId = current?.segmentId
  let endIndex = shotIndex + 1
  if (oldSegmentId) {
    while (endIndex < shots.length && shots[endIndex].presentation?.segmentId === oldSegmentId) endIndex += 1
  }
  return shots.map((shot, index) => {
    if (index < shotIndex || index >= endIndex) return shot
    const presentation = shot.presentation
    return {
      ...shot,
      presentation: {
        segmentId: previous.segmentId,
        modes: [...previous.modes],
        sourcePerspective: previous.sourcePerspective,
        certainty: previous.certainty,
        timeRelation: previous.timeRelation,
        entryCue: presentation?.entryCue ?? "",
        exitCue: presentation?.exitCue ?? "",
        ...(presentation?.eventLabel ? { eventLabel: presentation.eventLabel } : {}),
      },
    }
  })
}

function soundEventTreeSummary(event: DirectorPlanSoundEventDraft) {
  const kind = DIRECTOR_PLAN_SOUND_KIND_OPTIONS.find((option) => option.value === event.kind)?.label || event.kind
  const voiceType = event.kind === "voice"
    ? DIRECTOR_PLAN_VOICE_TYPE_OPTIONS.find((option) => option.value === event.voiceType)?.label
    : ""
  const excerpt = (value: unknown, limit: number) => {
    const chars = Array.from(compactValue(value))
    return chars.length > limit ? `${chars.slice(0, limit).join("")}…` : chars.join("")
  }
  const parts = [
    { text: voiceType || kind, color: syntaxColor.choice },
    { text: excerpt(event.sourceName, 12), color: syntaxColor.source },
    { text: excerpt(event.content, 24), color: syntaxColor.string },
  ].filter((part) => part.text)
  return <span className="block max-w-full overflow-hidden text-ellipsis whitespace-nowrap">
    {parts.map((part, index) => (
      <span key={index}>
        {index > 0 ? <span className={syntaxColor.punctuation}> · </span> : null}
        <span className={part.color}>{part.text}</span>
      </span>
    ))}
  </span>
}

function DirectorPlanInlineValue({
  value,
  displayValue = value,
  onChange,
  onPendingChange,
  readOnly,
  quoted = true,
  multiline = false,
  parse,
  placeholder,
  ariaLabel,
  valueTone = "string",
}: {
  value: string
  displayValue?: string
  onChange: (value: string) => void
  onPendingChange?: (pending: boolean) => void
  readOnly: boolean
  quoted?: boolean
  multiline?: boolean
  parse?: (value: string) => string | null
  placeholder?: string
  ariaLabel?: string
  valueTone?: "string" | "number" | "source" | "muted"
}) {
  const valueRef = useRef<HTMLSpanElement>(null)
  const canceled = useRef(false)
  const shownText = displayValue || placeholder || "\u00a0"
  const quoteColor = syntaxColor.punctuation
  return (
    <span
      className={cn(syntaxColor[valueTone], !readOnly && "cursor-text")}
      onClick={() => {
        if (!readOnly && !displayValue) valueRef.current?.focus()
      }}
    >
      {quoted ? <span className={quoteColor}>"</span> : null}
      <span
        ref={valueRef}
        contentEditable={readOnly ? false : "plaintext-only"}
        suppressContentEditableWarning
        spellCheck={false}
        aria-label={ariaLabel}
        data-empty={!displayValue || undefined}
        onInput={(event) => {
          const element = event.currentTarget
          element.dataset.empty = String(!element.textContent)
          const raw = element.innerText.replace(/\r\n/g, "\n")
          const edited = raw === "\u00a0" ? "" : raw
          const next = parse ? parse(edited) : edited
          onPendingChange?.(next !== null && next !== value)
        }}
        onFocus={(event) => {
          if (!displayValue) {
            const element = event.currentTarget
            element.textContent = ""
            const range = element.ownerDocument.createRange()
            range.selectNodeContents(element)
            range.collapse(true)
            const selection = element.ownerDocument.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
          }
        }}
        onBlur={(event) => {
          const element = event.currentTarget
          element.dataset.empty = String(!displayValue)
          if (!canceled.current) {
            const raw = element.innerText.replace(/\r\n/g, "\n")
            const edited = raw === "\u00a0" ? "" : raw
            const next = parse ? parse(edited) : edited
            if (next === null) {
              element.textContent = shownText
              toast.error("字段值无效，已恢复原值")
            } else if (next !== value) {
              onChange(next)
            } else {
              element.textContent = shownText
            }
          }
          canceled.current = false
          onPendingChange?.(false)
        }}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return
          if (event.key === "Escape") {
            event.preventDefault()
            canceled.current = true
            event.currentTarget.textContent = shownText
            event.currentTarget.blur()
          } else if (event.key === "Enter" && (!multiline || event.ctrlKey || event.metaKey)) {
            event.preventDefault()
            event.currentTarget.blur()
          }
        }}
        className={cn("director-plan-inline-value cursor-text whitespace-pre-wrap break-words outline-none", !readOnly && "hover:underline focus:underline decoration-dotted decoration-sky-500/60 underline-offset-2")}
      >
        {shownText}
      </span>
      {quoted ? <span className={quoteColor}>"</span> : null}
    </span>
  )
}

function DirectorPlanTreeNode({
  label,
  detail,
  children,
  actions,
  initiallyOpen = true,
  expanded,
  onExpandedChange,
  collapsible = true,
  tone = "default",
  rootless = false,
  highlightRowOnHover = false,
  contentClassName,
}: {
  label: ReactNode
  detail?: ReactNode
  children: ReactNode
  actions?: ReactNode
  initiallyOpen?: boolean
  expanded?: boolean
  onExpandedChange?: (expanded: boolean) => void
  collapsible?: boolean
  tone?: "root" | "shot" | "group" | "default"
  rootless?: boolean
  highlightRowOnHover?: boolean
  contentClassName?: string
}) {
  const [localOpen, setLocalOpen] = useState(initiallyOpen)
  const open = expanded ?? localOpen
  if (rootless) return <>{children}</>
  const isShotHeading = tone === "shot"
  const rowContent = isShotHeading ? (
    <>
      <span className="h-4 w-0.5 shrink-0 rounded-full bg-[#245fc7] dark:bg-[#6ea8ff]" />
      <span className={cn("inline-flex h-6 shrink-0 items-center whitespace-nowrap text-[10px] font-semibold leading-none", syntaxColor.heading)}>{label}</span>
      {detail ? <span className={cn("inline-flex h-6 min-w-0 items-center whitespace-nowrap text-[10px] font-normal leading-none", syntaxColor.muted)}>预计 {detail}</span> : null}
    </>
  ) : (
    <>
      {collapsible ? <span className={cn("w-[1.5ch] shrink-0", syntaxColor.muted)}>{open ? "▾" : "▸"}</span> : null}
      <span className={cn(
        "shrink-0 whitespace-nowrap",
        tone === "root" && cn("font-semibold", syntaxColor.heading),
        tone === "group" && cn("font-medium", syntaxColor.group),
        tone === "default" && syntaxColor.shot
      )}>{label}</span>
      <span className={cn("shrink-0 whitespace-pre", syntaxColor.punctuation)}>: </span>
      {detail ? <span className={cn("min-w-0 flex-1 whitespace-pre-wrap break-words font-normal", tone === "default" ? syntaxColor.source : syntaxColor.number)}>{detail}</span> : null}
    </>
  )
  return (
    <div className={cn("min-w-0 text-[13px] leading-[20.2px]", tone === "shot" && "mt-[3px]")}>
      <div className={cn(
        "group/tree relative min-w-0",
        highlightRowOnHover && "director-plan-row-highlight"
      )}>
        {collapsible ? <button
          type="button"
          aria-expanded={open}
          onClick={(event) => {
            event.stopPropagation()
            if (onExpandedChange) onExpandedChange(!open)
            else setLocalOpen((current) => !current)
          }}
          onPointerDown={(event) => event.stopPropagation()}
          className={cn("flex min-h-6 w-full min-w-0 pr-8 text-left outline-none focus-visible:underline", isShotHeading ? "items-center gap-2" : "items-baseline")}
        >
          {rowContent}
        </button> : <div className={cn(
          "flex min-h-6 w-full min-w-0 pr-8",
          isShotHeading ? "items-center gap-2" : "items-baseline"
        )}>
          {rowContent}
        </div>}
        {actions ? <div className={cn(
          "absolute flex items-center group-hover/tree:opacity-100 group-focus-within/tree:opacity-100",
          highlightRowOnHover ? "inset-y-0 right-0 w-8 justify-center" : "right-0 top-0",
          tone === "shot" || tone === "default" ? "opacity-0" : "opacity-60"
        )}>{actions}</div> : null}
      </div>
      {open || !collapsible ? <div className={cn("min-w-0", contentClassName ?? "pl-[2ch]")}>{children}</div> : null}
    </div>
  )
}

export function DirectorPlanStructuredEditor({
  shots,
  speakerRoster,
  onChange,
  onSpeakerRosterChange,
  onPendingChange,
  soundSourceOptions,
  maxHeight,
  maximized = false,
  readOnly = false,
  selectedShotGroupIds,
  onToggleShotGroup,
  shotGroups,
  flatRoot = false,
  flatRootTitle = "导演镜头",
  scrollInParent = false,
  shotNumberOffset = 0,
  projectId,
  episodeId,
  nodeId,
}: {
  shots: DirectorPlanShotDraft[]
  speakerRoster: DirectorPlanSpeakerRosterDraft
  onChange: (shots: DirectorPlanShotDraft[]) => void
  onSpeakerRosterChange: (value: DirectorPlanSpeakerRosterDraft) => void
  onPendingChange?: (pending: boolean) => void
  soundSourceOptions?: DirectorPlanSoundSourceOption[]
  maxHeight?: number
  maximized?: boolean
  readOnly?: boolean
  selectedShotGroupIds?: string[]
  onToggleShotGroup?: (groupId: string) => void
  shotGroups?: Array<{ id: string; shotNos: number[] }>
  flatRoot?: boolean
  flatRootTitle?: string
  scrollInParent?: boolean
  shotNumberOffset?: number
  projectId?: string
  episodeId?: string
  nodeId?: string
}) {
  const { backendReady, callBackend } = useBackend()
  const [assetCatalog, setAssetCatalog] = useState<DirectorPlanAssetCatalog | null>(null)
  const [assetCatalogError, setAssetCatalogError] = useState(false)
  const [assetCatalogAttempt, setAssetCatalogAttempt] = useState(0)
  useEffect(() => {
    if (!backendReady || !projectId || !episodeId || !nodeId || !shots.length) return
    let active = true
    setAssetCatalog(null)
    setAssetCatalogError(false)
    void getDirectorPlanAssetCatalog(callBackend, projectId, episodeId, nodeId)
      .then((catalog) => { if (active) setAssetCatalog(catalog) })
      .catch(() => { if (active) setAssetCatalogError(true) })
    return () => { active = false }
  }, [backendReady, callBackend, projectId, episodeId, nodeId, shots.length > 0, assetCatalogAttempt])
  const editorHeight = editorTextareaHeight(maxHeight, maximized)
  const autoCreatedSpeakerIds = useRef(new Set<string>())
  const [soundDetailOpen, setSoundDetailOpen] = useState<Record<string, boolean>>({})
  const [screenTextDetailOpen, setScreenTextDetailOpen] = useState<Record<string, boolean>>({})
  const [emptyGroupDetailOpen, setEmptyGroupDetailOpen] = useState<Record<string, boolean>>({})
  const soundDetailKey = (shotNo: number, eventIndex: number) => `${shotNo}:${eventIndex}`
  const screenTextDetailKey = (shotNo: number, eventIndex: number) => `${shotNo}:${eventIndex}`
  const speakerOptionRows: DirectorPlanSoundSourceOption[] = [
    { value: "project:narrator", label: "旁白", description: "项目旁白" },
    ...(soundSourceOptions ?? []),
    ...speakerRoster.filter((speaker) => speaker.speakerId && speaker.displayName.trim()).map((speaker) => ({
      value: speaker.speakerId,
      label: speaker.displayName,
      description: speaker.identityDescription || "本段临时说话者",
    })),
  ]
  const speakerOptions = Array.from(new Map(
    speakerOptionRows.map((option) => [option.value, option] as const)
  ).values())
  const applyShotChanges = (
    nextShots: DirectorPlanShotDraft[],
    nextSpeakerRoster = speakerRoster
  ) => {
    const referencedIds = new Set(nextShots.flatMap((shot) =>
      shot.soundEvents.filter((event) => event.kind === "voice").map((event) => event.speakerId)
    ))
    // Only discard unused entries created by typing a source in this editor session.
    const unusedIds = new Set([...autoCreatedSpeakerIds.current].filter((id) => !referencedIds.has(id)))
    if (unusedIds.size) {
      nextSpeakerRoster = nextSpeakerRoster.filter((speaker) => !unusedIds.has(speaker.speakerId))
      unusedIds.forEach((id) => autoCreatedSpeakerIds.current.delete(id))
    }
    if (nextSpeakerRoster !== speakerRoster) onSpeakerRosterChange(nextSpeakerRoster)
    onChange(nextShots)
  }
  const updateShot = (
    shotIndex: number,
    patch: Partial<DirectorPlanShotDraft>
  ) => {
    if (readOnly) return
    const beatsNeedReview = Boolean(shots[shotIndex].nonOverlappingBeats?.length)
      && (patch.videoExecution !== undefined && patch.videoExecution !== shots[shotIndex].videoExecution
        || patch.durationSec !== undefined && patch.durationSec !== shots[shotIndex].durationSec
        || patch.soundEvents !== undefined)
    const timingChanged = patch.videoExecution !== undefined && patch.videoExecution !== shots[shotIndex].videoExecution
      || patch.durationSec !== undefined && patch.durationSec !== shots[shotIndex].durationSec
      || patch.nonOverlappingBeats !== undefined || patch.soundEvents !== undefined
    if (beatsNeedReview) {
      toast.info("镜头动作、声音或时长已改变，请核对下方独立时段")
    }
    applyShotChanges(
      shots.map((shot, index) =>
        index === shotIndex ? { ...shot, ...patch,
          ...(patch.storyboardFrame !== undefined && patch.storyboardFrame !== shot.storyboardFrame
            ? { assetReviewRequired: true } : {}),
          ...(timingChanged ? { normalDurationSec: undefined } : {}),
          ...(beatsNeedReview ? { independentBeatsNeedReview: true } : {}) } : shot
      )
    )
  }
  const updateSharedPresentation = (
    shotIndex: number,
    patch: Partial<Pick<DirectorPlanPresentationDraft, "modes" | "sourcePerspective" | "certainty" | "timeRelation">>,
  ) => {
    if (readOnly) return
    applyShotChanges(updateSharedPresentationDrafts(shots, shotIndex, patch))
  }
  const joinPreviousPresentation = (shotIndex: number) => {
    if (readOnly) return
    applyShotChanges(joinPreviousPresentationDrafts(shots, shotIndex))
    toast.info("已沿用上一镜的表达类型、来源和时间关系，请核对本镜入出提示")
  }
  const updateIndependentBeat = (
    shotIndex: number,
    beatIndex: number,
    patch: Partial<DirectorPlanIndependentBeatDraft>,
  ) => {
    const beats = shots[shotIndex].nonOverlappingBeats ?? []
    updateShot(shotIndex, {
      nonOverlappingBeats: beats.map((beat, index) => index === beatIndex ? { ...beat, ...patch } : beat),
    })
  }
  const updateSoundEvent = (
    shotIndex: number,
    eventIndex: number,
    patch: Partial<DirectorPlanSoundEventDraft>,
    nextSpeakerRoster = speakerRoster
  ) => {
    if (readOnly) return
    if (patch.content !== undefined) {
      const key = soundDetailKey(shotIndex + 1, eventIndex)
      setSoundDetailOpen((current) => key in current ? current : {
        ...current,
        [key]: !shots[shotIndex].soundEvents[eventIndex].content,
      })
    }
    applyShotChanges(
      shots.map((shot, index) => {
        if (index !== shotIndex) return shot
        return {
          ...shot,
          ...((patch.content !== undefined || patch.kind !== undefined || patch.deliveryOverride !== undefined)
            ? { normalDurationSec: undefined,
                ...(shot.nonOverlappingBeats?.length ? { independentBeatsNeedReview: true } : {}) }
            : {}),
          soundEvents: shot.soundEvents.map((event, currentEventIndex) => {
            if (currentEventIndex !== eventIndex) return event
            const updated = { ...event, ...patch }
            if ((patch.content !== undefined && patch.content !== event.content)
                || (patch.kind !== undefined && patch.kind !== "voice")) {
              delete updated.deliveryOverride
            }
            return updated
          }),
        }
      }),
      nextSpeakerRoster
    )
  }
  const handleAddShot = (afterIndex?: number) => {
    if (readOnly) return
    setSoundDetailOpen({})
    setScreenTextDetailOpen({})
    const insertIndex =
      typeof afterIndex === "number" ? afterIndex + 1 : shots.length
    const nextShots = [
      ...shots.slice(0, insertIndex),
      emptyShotDraft(insertIndex),
      ...shots.slice(insertIndex),
    ]
    applyShotChanges(renumberShotDrafts(nextShots))
  }
  const handleDeleteShot = (shotIndex: number) => {
    if (readOnly || shots.length <= 1) return
    setSoundDetailOpen({})
    setScreenTextDetailOpen({})
    applyShotChanges(
      renumberShotDrafts(
        shots.filter((_, index) => index !== shotIndex)
      )
    )
  }
  const handleAddSoundEvent = (shotIndex: number) => {
    if (readOnly) return
    updateShot(shotIndex, {
      soundEvents: [
        ...shots[shotIndex].soundEvents,
        {
          kind: "voice",
          voiceType: "dialogue",
          speakerId: "",
          sourceName: "",
          content: "",
          expressionNotes: "",
          timing: "",
          durationSec: "",
        },
      ],
    })
  }
  const updateScreenTextEvent = (shotIndex: number, eventIndex: number, patch: Partial<DirectorPlanScreenTextEventDraft>) => {
    if (readOnly) return
    if (patch.content !== undefined) {
      const key = screenTextDetailKey(shotIndex + 1, eventIndex)
      setScreenTextDetailOpen((current) => key in current ? current : {
        ...current,
        [key]: !shots[shotIndex].screenTextEvents[eventIndex].content,
      })
    }
    updateShot(shotIndex, {
      screenTextEvents: shots[shotIndex].screenTextEvents.map((event, index) =>
        index === eventIndex ? { ...event, ...patch } : event
      ),
    })
  }
  const handleAddScreenTextEvent = (shotIndex: number) => {
    if (readOnly) return
    updateShot(shotIndex, {
      screenTextEvents: [
        ...shots[shotIndex].screenTextEvents,
        { content: "", medium: "画面文字", authorLabel: "", timing: "", visibleAtStart: false },
      ],
    })
  }
  const handleDeleteScreenTextEvent = (shotIndex: number, eventIndex: number) => {
    if (readOnly) return
    setScreenTextDetailOpen((current) => {
      const next = { ...current }
      for (let index = eventIndex; index < shots[shotIndex].screenTextEvents.length; index += 1) {
        const key = screenTextDetailKey(shotIndex + 1, index)
        const followingKey = screenTextDetailKey(shotIndex + 1, index + 1)
        if (followingKey in current) next[key] = current[followingKey]
        else delete next[key]
      }
      return next
    })
    updateShot(shotIndex, {
      screenTextEvents: shots[shotIndex].screenTextEvents.filter((_, index) => index !== eventIndex),
    })
  }
  const updateSpeaker = (
    speakerIndex: number,
    patch: Partial<DirectorPlanSpeakerDraft>
  ) => {
    if (readOnly) return
    autoCreatedSpeakerIds.current.delete(speakerRoster[speakerIndex].speakerId)
    onSpeakerRosterChange(
      speakerRoster.map((speaker, index) =>
        index === speakerIndex ? { ...speaker, ...patch } : speaker
      )
    )
    if (patch.displayName !== undefined) {
      const speakerId = speakerRoster[speakerIndex].speakerId
      onChange(shots.map((shot) => ({
        ...shot,
        soundEvents: shot.soundEvents.map((event) =>
          event.kind === "voice" && event.speakerId === speakerId
            ? { ...event, sourceName: patch.displayName! }
            : event
        ),
      })))
    }
  }
  const addSpeaker = () => {
    if (readOnly) return
    onSpeakerRosterChange([
      ...speakerRoster,
      { speakerId: workflowNodeId("speaker"), displayName: "", identityDescription: "" },
    ])
  }
  const deleteSpeaker = (speakerIndex: number) => {
    if (readOnly) return
    const speakerId = speakerRoster[speakerIndex].speakerId
    const usedInShots = shots.filter((shot) => shot.soundEvents.some(
      (event) => event.kind === "voice" && event.speakerId === speakerId
    ))
    if (usedInShots.length) {
      toast.error(`该说话者仍被镜头 ${usedInShots.map((shot) => String(shot.shotNo + shotNumberOffset).padStart(2, "0")).join("、")} 使用，请先更换声源或删除对应声音事件`)
      return
    }
    autoCreatedSpeakerIds.current.delete(speakerId)
    onSpeakerRosterChange(speakerRoster.filter((_, index) => index !== speakerIndex))
  }
  const updateSoundSourceText = (shotIndex: number, eventIndex: number, value: string) => {
    if (readOnly) return
    const event = shots[shotIndex].soundEvents[eventIndex]
    if (event.kind !== "voice" || !value.trim()) {
      updateSoundEvent(shotIndex, eventIndex, { sourceName: value, speakerId: "" })
      return
    }
    const nameMatches = speakerOptions.filter((option) => option.label.trim() === value.trim())
    const matchedOption = nameMatches.find((option) => option.value === event.speakerId)
      ?? (nameMatches.length === 1 ? nameMatches[0] : undefined)
    if (matchedOption) {
      updateSoundEvent(shotIndex, eventIndex, {
        sourceName: matchedOption.label,
        speakerId: matchedOption.value,
      })
      return
    }
    const speakerIndex = speakerRoster.findIndex((speaker) => speaker.speakerId === event.speakerId)
    const usedByAnotherEvent = shots.some((shot, currentShotIndex) =>
      shot.soundEvents.some((other, currentEventIndex) =>
        (currentShotIndex !== shotIndex || currentEventIndex !== eventIndex) &&
        other.kind === "voice" && other.speakerId === event.speakerId
      )
    )
    if (speakerIndex >= 0 && !usedByAnotherEvent) {
      updateSoundEvent(shotIndex, eventIndex, { sourceName: value },
        speakerRoster.map((speaker, index) =>
          index === speakerIndex ? { ...speaker, displayName: value } : speaker
        )
      )
      return
    }
    const speakerId = workflowNodeId("speaker")
    autoCreatedSpeakerIds.current.add(speakerId)
    updateSoundEvent(shotIndex, eventIndex, { sourceName: value, speakerId }, [
      ...speakerRoster,
      { speakerId, displayName: value, identityDescription: "" },
    ])
  }
  const handleDeleteSoundEvent = (shotIndex: number, eventIndex: number) => {
    if (readOnly) return
    setSoundDetailOpen((current) => {
      const next = { ...current }
      for (let index = eventIndex; index < shots[shotIndex].soundEvents.length; index += 1) {
        const key = soundDetailKey(shotIndex + 1, index)
        const followingKey = soundDetailKey(shotIndex + 1, index + 1)
        if (followingKey in current) next[key] = current[followingKey]
        else delete next[key]
      }
      return next
    })
    updateShot(shotIndex, {
      soundEvents: shots[shotIndex].soundEvents.filter(
        (_, index) => index !== eventIndex
      ),
      normalDurationSec: undefined,
      ...(shots[shotIndex].nonOverlappingBeats?.length ? { independentBeatsNeedReview: true } : {}),
    })
  }
  const renderField = (
    label: string,
    value: string,
    onValueChange: (value: string) => void,
    options: {
      displayValue?: string
      quoted?: boolean
      multiline?: boolean
      parse?: (value: string) => string | null
      valueTone?: "string" | "number" | "source" | "muted"
    } = {}
  ) => (
    <div className="director-plan-field min-w-0 whitespace-pre-wrap break-words pl-[6ch] -indent-[6ch] text-[13px] leading-[20.2px]">
      <span className={cn("font-medium", syntaxColor.field)}>{label}</span>
      <span className={syntaxColor.punctuation}>: </span>
      <DirectorPlanInlineValue
        value={value}
        displayValue={options.displayValue}
        onChange={onValueChange}
        onPendingChange={onPendingChange}
        readOnly={readOnly}
        quoted={options.quoted}
        multiline={options.multiline}
        parse={options.parse}
        valueTone={options.valueTone}
      />
    </div>
  )

  const renderChoice = (
    label: string,
    value: string,
    options: { value: string; label: string }[],
    onValueChange: (value: string) => void,
    valueTone: "choice" | "source" = "choice"
  ) => (
    <div className="director-plan-field min-w-0 text-[13px] leading-[20.2px]">
      <span className={cn("font-medium", syntaxColor.field)}>{label}</span>
      <span className={syntaxColor.punctuation}>: </span>
      <select
        value={value}
        disabled={readOnly}
        aria-label={label}
        onChange={(event) => onValueChange(event.target.value)}
        onPointerDown={(event) => event.stopPropagation()}
        className={cn("director-plan-native-select", valueTone === "source" && "director-plan-native-select--source")}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  )

  const renderBoolean = (
    label: string,
    checked: boolean,
    onValueChange: (checked: boolean) => void,
  ) => (
    <div className="director-plan-field flex min-w-0 items-center gap-1 text-[13px] leading-[20.2px]">
      <span className={cn("font-medium", syntaxColor.field)}>{label}</span>
      <span className={syntaxColor.punctuation}>: </span>
      <Checkbox
        aria-label={label}
        checked={checked}
        disabled={readOnly}
        onCheckedChange={(value) => onValueChange(value === true)}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => event.stopPropagation()}
        className="size-3.5 shrink-0"
      />
      <span className={syntaxColor.choice}>{checked ? "是" : "否"}</span>
    </div>
  )

  const renderDuration = (
    label: string,
    value: string,
    onValueChange: (value: string) => void,
    required = false,
  ) => renderField(`${label}（秒）`, value, onValueChange, {
    quoted: false,
    valueTone: "number",
    parse: (text) => parseDirectorPlanDuration(text, required),
  })

  const renderSource = (shotIndex: number, eventIndex: number, event: DirectorPlanSoundEventDraft) => {
    if (event.kind !== "voice") {
      return renderField("声源", event.sourceName, (text) =>
        updateSoundSourceText(shotIndex, eventIndex, text),
        { valueTone: "source" }
      )
    }

    const selectedOption = speakerOptions.find((option) => option.value === event.speakerId)
    const nameMatches = !event.speakerId && event.sourceName.trim()
      ? speakerOptions.filter((option) => option.label.trim() === event.sourceName.trim())
      : []
    const matchedOption = selectedOption ?? (nameMatches.length === 1 ? nameMatches[0] : undefined)
    const currentValue = matchedOption?.value || event.speakerId || (event.sourceName ? `current-source:${event.sourceName}` : "")
    const options = [{ value: "", label: "未指定" }, ...speakerOptions]
    // Keep an existing source visible even if its role is no longer in the available options.
    if (currentValue && !matchedOption) {
      options.push({ value: currentValue, label: event.sourceName || "当前说话者" })
    }

    return (
      <div className="director-plan-field director-plan-source-field min-w-0 text-[13px] leading-[20.2px]">
        <span className={cn("font-medium", syntaxColor.field)}>声源</span>
        <span className={syntaxColor.punctuation}>: </span>
        <span className="director-plan-source-control">
          <DirectorPlanInlineValue
            value={event.sourceName}
            onChange={(text) => updateSoundSourceText(shotIndex, eventIndex, text)}
            onPendingChange={onPendingChange}
            readOnly={readOnly}
            quoted={false}
            valueTone="source"
            placeholder="未指定"
            ariaLabel="声源名称"
          />
          {!readOnly ? (
            <select
              value={currentValue}
              aria-label="选择声源"
              title="选择已有说话者"
              onChange={(changeEvent) => {
                const speakerId = changeEvent.target.value
                if (!speakerId) {
                  updateSoundEvent(shotIndex, eventIndex, { sourceName: "", speakerId: "" })
                  return
                }
                const option = speakerOptions.find((item) => item.value === speakerId)
                if (option) updateSoundEvent(shotIndex, eventIndex, { sourceName: option.label, speakerId: option.value })
              }}
              onPointerDown={(pointerEvent) => pointerEvent.stopPropagation()}
              className="director-plan-native-select director-plan-native-select--source director-plan-source-picker"
            >
              {options.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          ) : null}
        </span>
      </div>
    )
  }

  const treeAction = (label: string, title: string, symbol: string, onClick: () => void, disabled = false) => (
    <button
      type="button"
      aria-label={label}
      title={title}
      disabled={readOnly || disabled}
      onClick={(event) => {
        event.stopPropagation()
        onClick()
      }}
      onPointerDown={(event) => event.stopPropagation()}
      className={cn(
        "inline-flex size-6 items-center justify-center rounded-[4px] outline-none hover:bg-slate-200/70 focus-visible:ring-1 focus-visible:ring-sky-500 disabled:cursor-default disabled:opacity-30 dark:hover:bg-white/[0.08]",
        syntaxColor.muted,
        symbol === "+" ? "hover:text-sky-700 dark:hover:text-[#6ea8ff]" : "hover:text-rose-600 dark:hover:text-rose-300"
      )}
    >
      {symbol === "+" ? <Plus className="size-4" /> : <Trash2 className="size-4" />}
    </button>
  )

  const shotGroupByNumber = new Map<number, { id: string; groupIndex: number; shotNos: number[] }>()
  shotGroups?.forEach((group, groupIndex) => {
    group.shotNos.forEach((shotNo) => shotGroupByNumber.set(shotNo, { id: group.id, groupIndex, shotNos: group.shotNos }))
  })
  const allSoundEvents = shots.flatMap((shot, shotIndex) =>
    shot.soundEvents.map((event, eventIndex) => ({ shotNo: shotIndex + 1, event, eventIndex }))
  )
  const allScreenTextEvents = shots.flatMap((shot, shotIndex) =>
    shot.screenTextEvents.map((event, eventIndex) => ({ shotNo: shotIndex + 1, event, eventIndex }))
  )
  const emptyDetailGroups = shotGroups?.filter((group) => group.shotNos.every((number) =>
    (shots[number - 1]?.soundEvents.length ?? 0) + (shots[number - 1]?.screenTextEvents.length ?? 0) === 0
  )) ?? []
  const hasDetailControls = allSoundEvents.length > 0 || allScreenTextEvents.length > 0 || emptyDetailGroups.length > 0
  const allDetailsExpanded = hasDetailControls
    && allSoundEvents.every(({ shotNo, event, eventIndex }) =>
      soundDetailOpen[soundDetailKey(shotNo, eventIndex)] ?? !event.content
    )
    && allScreenTextEvents.every(({ shotNo, event, eventIndex }) =>
      screenTextDetailOpen[screenTextDetailKey(shotNo, eventIndex)] ?? !event.content
    )
    && emptyDetailGroups.every((group) => emptyGroupDetailOpen[group.id] === true)

  return (
    <div
      className={cn("nodrag nopan nowheel min-h-0 overflow-x-hidden bg-transparent pr-1 text-[13px] leading-[20.2px]", !scrollInParent && "overflow-y-auto", maximized && "h-full")}
      style={{ fontFamily: 'Consolas, "Microsoft YaHei UI", "Microsoft YaHei", monospace', ...(maximized || scrollInParent ? {} : { maxHeight: editorHeight }) }}
      onWheel={stopCardWheel}
      onWheelCapture={stopCardWheel}
      data-director-plan-scroll="true"
    >
      {flatRoot && maximized ? <div className="mb-2 flex min-h-6 items-center justify-between text-xs text-slate-500 dark:text-slate-400">
        <span>{flatRootTitle ? `${flatRootTitle} · ` : ""}共 {shots.length} 个镜头</span>
        {maximized ? <span className="inline-flex items-center gap-1">
          <button
            type="button"
            aria-label={`${allDetailsExpanded ? "收起" : "展开"}所有镜头的画面文字和声音详情`}
            title={`${allDetailsExpanded ? "收起" : "展开"}所有画面文字和声音详情`}
            aria-expanded={allDetailsExpanded}
            disabled={!hasDetailControls}
            onClick={(event) => {
              event.stopPropagation()
              setEmptyGroupDetailOpen((current) => ({
                ...current,
                ...Object.fromEntries(emptyDetailGroups.map((group) => [group.id, !allDetailsExpanded])),
              }))
              setSoundDetailOpen((current) => {
                const next = { ...current }
                allSoundEvents.forEach(({ shotNo, eventIndex }) => {
                  next[soundDetailKey(shotNo, eventIndex)] = !allDetailsExpanded
                })
                return next
              })
              setScreenTextDetailOpen((current) => {
                const next = { ...current }
                allScreenTextEvents.forEach(({ shotNo, eventIndex }) => {
                  next[screenTextDetailKey(shotNo, eventIndex)] = !allDetailsExpanded
                })
                return next
              })
            }}
            onPointerDown={(event) => event.stopPropagation()}
            className="inline-flex size-6 items-center justify-center text-slate-500 hover:text-indigo-600 disabled:opacity-30 dark:text-slate-400 dark:hover:text-indigo-300"
          >
            <ListCollapse className={cn("size-4", allDetailsExpanded && "text-indigo-600 dark:text-indigo-300")} />
          </button>
          {treeAction("新增镜头", "新增镜头", "+", () => handleAddShot())}
        </span> : null}
      </div> : null}
      <DirectorPlanTreeNode
        label="分镜脚本"
        collapsible={false}
        tone="root"
        rootless={flatRoot}
        actions={flatRoot ? undefined : treeAction("新增镜头", "新增镜头", "+", () => handleAddShot())}
      >
        {shots.map((shot, shotIndex) => {
          const shotNo = shotIndex + 1
          const groupInfo = shotGroupByNumber.get(shotNo)
          const groupNumber = (groupInfo?.groupIndex ?? 0) + 1
          const shotNos = groupInfo?.shotNos ?? []
          const isGroupStart = shotNos[0] === shotNo
          const isGroupEnd = shotNos[shotNos.length - 1] === shotNo
          const isMergedGroup = shotNos.length > 1
          const groupSoundEvents = shotNos.flatMap((number) =>
            (shots[number - 1]?.soundEvents ?? []).map((event, eventIndex) => ({ number, event, eventIndex }))
          )
          const groupScreenTextEvents = shotNos.flatMap((number) =>
            (shots[number - 1]?.screenTextEvents ?? []).map((event, eventIndex) => ({ number, event, eventIndex }))
          )
          const groupHasDetails = groupSoundEvents.length + groupScreenTextEvents.length > 0
          const groupDetailsExpanded = groupHasDetails
            ? groupSoundEvents.every(({ number, event, eventIndex }) =>
              soundDetailOpen[soundDetailKey(number, eventIndex)] ?? !event.content
            ) && groupScreenTextEvents.every(({ number, event, eventIndex }) =>
              screenTextDetailOpen[screenTextDetailKey(number, eventIndex)] ?? !event.content
            )
            : Boolean(groupInfo && emptyGroupDetailOpen[groupInfo.id])
          const selectedAssetCount = SHOT_ASSET_KINDS.reduce((count, kind) => count + (shot.assets?.[kind].length ?? 0), 0)
          return <div
            key={shotIndex}
            className={cn(
              "min-w-0",
              groupInfo && "border-x px-2",
              isGroupStart && "mt-2 rounded-t-md border-t pt-1.5",
              isGroupEnd && "rounded-b-md border-b pb-1.5",
              groupInfo && (isMergedGroup
                ? "border-indigo-200 bg-indigo-50/60 dark:border-indigo-400/25 dark:bg-indigo-400/[0.07]"
                : "border-slate-200 bg-slate-50/50 dark:border-white/10 dark:bg-white/[0.03]")
            )}
          >
          {isGroupStart ? <div className={cn("mb-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 border-b pb-1.5 text-[11px]", isMergedGroup ? "border-indigo-200/80 dark:border-indigo-400/20" : "border-slate-200/80 dark:border-white/10")}>
            <label className={cn("inline-flex min-h-6 min-w-0 items-center gap-2", onToggleShotGroup && !readOnly && "cursor-pointer")}>
              {groupInfo && onToggleShotGroup ? <Checkbox
                aria-label={`选择分组 ${groupNumber}`}
                checked={selectedShotGroupIds?.includes(groupInfo.id) ?? false}
                disabled={readOnly}
                onCheckedChange={() => onToggleShotGroup(groupInfo.id)}
                onPointerDown={(event) => event.stopPropagation()}
                onClick={(event) => event.stopPropagation()}
                className="size-4"
              /> : null}
              <span className={cn("shrink-0 font-semibold", isMergedGroup ? "text-indigo-700 dark:text-indigo-300" : "text-slate-600 dark:text-slate-300")}>分组 {groupNumber}</span>
              <span className="text-slate-500 dark:text-slate-400">镜头 {String(shotNos[0] + shotNumberOffset).padStart(2, "0")}{isMergedGroup ? `–${String(shotNos[shotNos.length - 1] + shotNumberOffset).padStart(2, "0")}` : ""} · 共 {shotNos.length} 个镜头</span>
            </label>
            {groupInfo ? <span className="ml-auto inline-flex shrink-0 items-center gap-1">
              <button
                type="button"
                aria-label={`${groupDetailsExpanded ? "收起" : "展开"}分组 ${groupNumber} 的画面文字和声音详情`}
                title={`${groupDetailsExpanded ? "收起" : "展开"}本组画面文字和声音详情`}
                aria-expanded={groupDetailsExpanded}
                onClick={(event) => {
                  event.stopPropagation()
                  if (!groupHasDetails && groupInfo) {
                    setEmptyGroupDetailOpen((current) => ({ ...current, [groupInfo.id]: !groupDetailsExpanded }))
                  }
                  setSoundDetailOpen((current) => {
                    const next = { ...current }
                    groupSoundEvents.forEach(({ number, eventIndex }) => {
                      next[soundDetailKey(number, eventIndex)] = !groupDetailsExpanded
                    })
                    return next
                  })
                  setScreenTextDetailOpen((current) => {
                    const next = { ...current }
                    groupScreenTextEvents.forEach(({ number, eventIndex }) => {
                      next[screenTextDetailKey(number, eventIndex)] = !groupDetailsExpanded
                    })
                    return next
                  })
                }}
                className="inline-flex size-6 items-center justify-center text-slate-500 hover:text-indigo-600 dark:text-slate-400 dark:hover:text-indigo-300"
              >
                <ListCollapse className={cn("size-4", groupDetailsExpanded && "text-indigo-600 dark:text-indigo-300")} />
              </button>
            </span> : null}
          </div> : null}
          <DirectorPlanTreeNode
            label={"镜头 " + String(shotIndex + 1 + shotNumberOffset).padStart(2, "0")}
            collapsible={false}
            tone="shot"
            actions={treeAction("删除镜头 " + (shotIndex + 1 + shotNumberOffset), "删除镜头", "×", () => handleDeleteShot(shotIndex), shots.length <= 1)}
          >
            {renderDuration("时长", shot.durationSec, (value) => updateShot(shotIndex, { durationSec: value }), true)}
            {renderField("视觉目的", shot.visualPurpose ?? "", (value) => updateShot(shotIndex, { visualPurpose: value }), { multiline: true })}
            {renderField("画面", shot.storyboardFrame, (value) => updateShot(shotIndex, { storyboardFrame: value }), { multiline: true })}
            {renderField("执行", shot.videoExecution, (value) => updateShot(shotIndex, { videoExecution: value }), { multiline: true })}
            {shot.nonOverlappingBeats?.length ? <DirectorPlanTreeNode
              label="独立时段"
              detail={`${shot.nonOverlappingBeats.length} 条`}
              tone="group"
              collapsible={false}
              actions={treeAction("新增独立时段", "新增独立时段", "+", () => updateShot(shotIndex, {
                nonOverlappingBeats: [...(shot.nonOverlappingBeats ?? []), { description: "", durationSec: "" }],
              }))}
            >
              <p className="text-[11px] text-slate-500 dark:text-slate-400">与台词或其他动作不能同时完成；修改执行或镜头时长后请核对。</p>
              {shot.independentBeatsNeedReview ? <button
                type="button"
                disabled={readOnly}
                onClick={() => updateShot(shotIndex, { independentBeatsNeedReview: false })}
                onPointerDown={(event) => event.stopPropagation()}
                className="text-xs font-medium text-amber-700 underline disabled:opacity-40 dark:text-amber-400"
              >请核对独立时段后点击确认</button> : null}
              {shot.nonOverlappingBeats.map((beat, beatIndex) => <DirectorPlanTreeNode
                key={beatIndex}
                label={`时段 ${String(beatIndex + 1).padStart(2, "0")}`}
                tone="group"
                collapsible={false}
                actions={treeAction(`删除独立时段 ${beatIndex + 1}`, "删除独立时段", "×", () => updateShot(shotIndex, {
                  nonOverlappingBeats: (shot.nonOverlappingBeats ?? []).filter((_, index) => index !== beatIndex),
                }))}
              >
                {renderField("动作说明", beat.description, (value) => updateIndependentBeat(shotIndex, beatIndex, { description: value }), { multiline: true })}
                {renderDuration("时长", beat.durationSec, (value) => updateIndependentBeat(shotIndex, beatIndex, { durationSec: value }), true)}
              </DirectorPlanTreeNode>)}
            </DirectorPlanTreeNode> : <button
              type="button"
              disabled={readOnly}
              onClick={() => updateShot(shotIndex, { nonOverlappingBeats: [{ description: "", durationSec: "" }] })}
              onPointerDown={(event) => event.stopPropagation()}
              className="text-xs text-slate-500 underline disabled:opacity-40"
            >添加独立时段</button>}
            {renderField("结束状态", shot.endState ?? "", (value) => updateShot(shotIndex, { endState: value }), { multiline: true })}
            {renderChoice("画面接续", shot.entryBoundaryKind ?? "", ENTRY_BOUNDARY_OPTIONS,
              (value) => updateShot(shotIndex, { entryBoundaryKind: value }))}
            {renderChoice("声音交接", shot.audioBoundaryKind ?? "", AUDIO_BOUNDARY_OPTIONS,
              (value) => updateShot(shotIndex, { audioBoundaryKind: value }))}
            {shotIndex > 0 ? renderBoolean("本镜前另起视频段", shot.groupBreakBefore === true,
              (checked) => updateShot(shotIndex, { groupBreakBefore: checked })) : null}
            <DirectorPlanTreeNode
              label="镜头资产"
              detail={`${selectedAssetCount} 项${shot.assetReviewRequired ? " · 待核对" : ""}`}
              tone="group"
              initiallyOpen={false}
            >
              <p className="text-[11px] text-slate-500 dark:text-slate-400">镜外使用包含声音；镜内入画表示稍后出现；起始可见决定首帧参考图。</p>
              {assetCatalog ? <button type="button" disabled={readOnly} onClick={() => setAssetCatalogAttempt((value) => value + 1)} className="text-xs text-slate-500 underline disabled:opacity-40">刷新可选资产</button> : null}
              {assetCatalogError ? <button type="button" onClick={() => setAssetCatalogAttempt((value) => value + 1)} className="text-xs text-amber-700 underline dark:text-amber-400">资产目录加载失败，点击重试</button> : null}
              {!assetCatalog && !assetCatalogError ? <span className="text-xs text-slate-500">正在加载可选资产…</span> : null}
              {assetCatalog ? SHOT_ASSET_KINDS.map((kind) => {
                const catalogRows = assetCatalog[kind] ?? []
                const selectedIds = [...new Set([
                  ...(shot.assets?.[kind] ?? []),
                  ...(shot.visibleAssets?.[kind] ?? []),
                  ...(shot.startVisibleAssets?.[kind] ?? []),
                ])]
                const missingIds = selectedIds.filter((id) => !catalogRows.some((row) => row.id === id))
                const rows = [
                  ...catalogRows.map((row) => ({ ...row, missing: false })),
                  ...missingIds.map((id, index) => ({ id, name: `已失效关联 ${index + 1}`, description: undefined, missing: true })),
                ]
                if (!rows.length) return null
                return <div key={kind} className="mt-1.5">
                  <div className="text-xs font-medium text-slate-500">{SHOT_ASSET_KIND_LABELS[kind]}</div>
                  {rows.map((row) => {
                    const usedByVoice = (kind === "characters" || kind === "creatures")
                      && shot.soundEvents.some((event) => event.kind === "voice" && event.speakerId === `asset:${row.id}`)
                    const state = (shot.startVisibleAssets ?? shot.visibleAssets)?.[kind].includes(row.id) ? "start"
                      : shot.visibleAssets?.[kind].includes(row.id) ? "visible"
                      : shot.assets?.[kind].includes(row.id) ? "offscreen" : "unused"
                    return <label key={row.id} className="flex min-h-6 items-center gap-2 text-xs">
                      <span className={cn("min-w-0 flex-1 truncate", row.missing && "text-amber-700 dark:text-amber-400")} title={row.description}>{row.name}</span>
                      <select
                        aria-label={`${row.name}在镜头 ${shotNo + shotNumberOffset} 的状态`}
                        title={usedByVoice ? "该角色正在发声，移除前请先更换声源" : undefined}
                        value={state}
                        disabled={readOnly}
                        onChange={(event) => {
                          const next = setDirectorPlanShotAssetState(shot, kind, row.id, event.target.value as "unused" | "offscreen" | "visible" | "start")
                          updateShot(shotIndex, { assets: next.assets, visibleAssets: next.visibleAssets, startVisibleAssets: next.startVisibleAssets })
                        }}
                        onPointerDown={(event) => event.stopPropagation()}
                        className="director-plan-native-select"
                      >
                        <option value="unused" disabled={usedByVoice}>不使用</option>
                        {row.missing && state !== "unused" ? <option value={state} disabled>已失效，请移除</option> : null}
                        {!row.missing ? <option value="offscreen">镜外使用</option> : null}
                        {!row.missing ? <option value="visible">镜内入画</option> : null}
                        {!row.missing ? <option value="start">起始可见</option> : null}
                      </select>
                    </label>
                  })}</div>
              }) : null}
              {shot.assetReviewRequired && assetCatalog ? <button
                type="button"
                disabled={readOnly || SHOT_ASSET_KINDS.some((kind) => (shot.assets?.[kind] ?? []).some((id) =>
                  !(assetCatalog[kind] ?? []).some((row) => row.id === id)))}
                onClick={() => updateShot(shotIndex, {
                  assets: shot.assets ?? emptyDirectorPlanShotAssets(),
                  visibleAssets: shot.visibleAssets ?? emptyDirectorPlanShotAssets(),
                  startVisibleAssets: shot.startVisibleAssets ?? shot.visibleAssets ?? emptyDirectorPlanShotAssets(),
                  assetReviewRequired: false,
                })}
                className="mt-1 text-xs font-medium text-amber-700 underline disabled:opacity-40 dark:text-amber-400"
              >确认本镜资产与起始画格</button> : null}
            </DirectorPlanTreeNode>
            <DirectorPlanTreeNode
              label="画面段落"
              detail={shot.presentation ? "特殊表达" : "普通连续戏"}
              tone="group"
              collapsible={false}
              actions={shot.presentation
                ? treeAction("清除画面段落", "清除画面段落", "×", () => updateShot(shotIndex, { presentation: undefined }))
                : treeAction("新增画面段落", "新增画面段落", "+", () => updateShot(shotIndex, {
                    presentation: { segmentId: workflowNodeId("segment"), modes: ["chronological_compression"],
                      sourcePerspective: "", certainty: "", timeRelation: "", entryCue: "", exitCue: "" },
                  }))}
            >
              {shot.presentation ? <>
                {shots[shotIndex - 1]?.presentation?.segmentId
                  && shots[shotIndex - 1]?.presentation?.segmentId !== shot.presentation.segmentId
                  ? <button type="button" disabled={readOnly} onClick={() => joinPreviousPresentation(shotIndex)} onPointerDown={(event) => event.stopPropagation()} className="text-xs text-slate-500 underline disabled:opacity-40">与上一镜合为同一段落</button>
                  : null}
                <DirectorPlanPresentationModeSelect modes={shot.presentation.modes} readOnly={readOnly} onChange={(modes) => updateSharedPresentation(shotIndex, { modes })} />
                {renderField("来源视角", shot.presentation.sourcePerspective, (value) => updateSharedPresentation(shotIndex, { sourcePerspective: value }))}
                {renderField("事实确定度", shot.presentation.certainty, (value) => updateSharedPresentation(shotIndex, { certainty: value }))}
                {renderField("时间关系", shot.presentation.timeRelation, (value) => updateSharedPresentation(shotIndex, { timeRelation: value }))}
                {renderField("进入提示", shot.presentation.entryCue, (value) => updateShot(shotIndex, { presentation: { ...shot.presentation!, entryCue: value } }))}
                {renderField("返回提示", shot.presentation.exitCue, (value) => updateShot(shotIndex, { presentation: { ...shot.presentation!, exitCue: value } }))}
                {shot.presentation.eventLabel ? <>
                  {renderField("事件短标识", shot.presentation.eventLabel.content, (value) => updateShot(shotIndex, { presentation: { ...shot.presentation!, eventLabel: { ...shot.presentation!.eventLabel!, content: value } } }))}
                  {renderField("来源引文", shot.presentation.eventLabel.sourceQuote, (value) => updateShot(shotIndex, { presentation: { ...shot.presentation!, eventLabel: { ...shot.presentation!.eventLabel!, sourceQuote: value } } }))}
                  {renderBoolean("起点可见", shot.presentation.eventLabel.visibleAtStart, (checked) => updateShot(shotIndex, { presentation: { ...shot.presentation!, eventLabel: { ...shot.presentation!.eventLabel!, visibleAtStart: checked } } }))}
                </> : null}
                <button type="button" disabled={readOnly} onClick={() => updateShot(shotIndex, { presentation: { ...shot.presentation!, eventLabel: shot.presentation!.eventLabel ? undefined : { content: "", sourceQuote: "", visibleAtStart: true } } })} className="text-xs text-slate-500 underline disabled:opacity-40">
                  {shot.presentation.eventLabel ? "移除事件短标识" : "添加事件短标识"}
                </button>
              </> : shots[shotIndex - 1]?.presentation?.segmentId
                ? <button type="button" disabled={readOnly} onClick={() => joinPreviousPresentation(shotIndex)} onPointerDown={(event) => event.stopPropagation()} className="text-xs text-slate-500 underline disabled:opacity-40">沿用上一镜段落</button>
                : null}
            </DirectorPlanTreeNode>
            <DirectorPlanTreeNode
              label="画面文字"
              detail={"[" + shot.screenTextEvents.length + " 条]"}
              collapsible={false}
              tone="group"
              actions={treeAction("新增画面文字", "新增画面文字", "+", () => handleAddScreenTextEvent(shotIndex))}
            >
              {shot.screenTextEvents.map((textEvent, eventIndex) => (
                <DirectorPlanTreeNode
                  key={eventIndex}
                  label={"文字 " + String(eventIndex + 1).padStart(2, "0")}
                  expanded={screenTextDetailOpen[screenTextDetailKey(shotNo, eventIndex)] ?? !textEvent.content}
                  contentClassName="director-plan-event-details"
                  onExpandedChange={(expanded) => setScreenTextDetailOpen((current) => ({
                    ...current,
                    [screenTextDetailKey(shotNo, eventIndex)]: expanded,
                  }))}
                  actions={treeAction("删除画面文字 " + (eventIndex + 1), "删除画面文字", "×", () => handleDeleteScreenTextEvent(shotIndex, eventIndex))}
                >
                  {renderField("内容", textEvent.content, (value) => updateScreenTextEvent(shotIndex, eventIndex, { content: value }), { multiline: true })}
                  {renderField("载体", textEvent.medium, (value) => updateScreenTextEvent(shotIndex, eventIndex, { medium: value }))}
                  {renderField("署名", textEvent.authorLabel, (value) => updateScreenTextEvent(shotIndex, eventIndex, { authorLabel: value }))}
                  {renderField("位置", textEvent.timing, (value) => updateScreenTextEvent(shotIndex, eventIndex, { timing: value }))}
                  {renderBoolean("起始画格可见", textEvent.visibleAtStart, (checked) => updateScreenTextEvent(shotIndex, eventIndex, { visibleAtStart: checked }))}
                </DirectorPlanTreeNode>
              ))}
            </DirectorPlanTreeNode>
            <DirectorPlanTreeNode
              label="声音"
              detail={"[" + shot.soundEvents.length + " 条]"}
              collapsible={false}
              tone="group"
              actions={treeAction("新增声音事件", "新增声音事件", "+", () => handleAddSoundEvent(shotIndex))}
            >
              {shot.soundEvents.map((soundEvent, eventIndex) => {
                const expanded = soundDetailOpen[soundDetailKey(shotNo, eventIndex)] ?? !soundEvent.content
                return (
                <DirectorPlanTreeNode
                  key={eventIndex}
                  label={"声音 " + String(eventIndex + 1).padStart(2, "0")}
                  detail={expanded ? undefined : soundEventTreeSummary(soundEvent)}
                  expanded={expanded}
                  contentClassName="director-plan-event-details"
                  onExpandedChange={(expanded) => setSoundDetailOpen((current) => ({
                    ...current,
                    [soundDetailKey(shotNo, eventIndex)]: expanded,
                  }))}
                  highlightRowOnHover
                  actions={treeAction("删除声音事件 " + (eventIndex + 1), "删除声音事件", "×", () => handleDeleteSoundEvent(shotIndex, eventIndex))}
                >
                  <div className="director-plan-sound-meta">
                    {renderChoice("类型", soundEvent.kind, DIRECTOR_PLAN_SOUND_KIND_OPTIONS, (kind) => updateSoundEvent(shotIndex, eventIndex, {
                      kind,
                      speakerId: kind === "voice" ? soundEvent.speakerId : "",
                      voiceType: kind === "voice" ? soundEvent.voiceType || "dialogue" : "",
                    }))}
                    {soundEvent.kind === "voice" ? renderChoice("人声", soundEvent.voiceType || "dialogue", DIRECTOR_PLAN_VOICE_TYPE_OPTIONS, (voiceType) => updateSoundEvent(shotIndex, eventIndex, { voiceType })) : null}
                    {renderSource(shotIndex, eventIndex, soundEvent)}
                    {soundEvent.kind === "voice"
                      ? <span className="text-[11px] text-slate-500 dark:text-slate-400">{soundEvent.deliveryOverride ? `慢说例外 ${soundEvent.deliveryOverride.durationSec} 秒` : "时长按镜头节奏计算"}</span>
                      : renderDuration("时长", soundEvent.durationSec, (value) => updateSoundEvent(shotIndex, eventIndex, { durationSec: value }))}
                  </div>
                  {soundEvent.kind === "voice" && soundEvent.deliveryOverride ? (
                    <div className="flex items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400">
                      <span title={soundEvent.deliveryOverride.reason}>依据：{soundEvent.deliveryOverride.evidenceText}</span>
                      {!readOnly ? <button type="button" onClick={() => updateSoundEvent(shotIndex, eventIndex, { deliveryOverride: undefined })} className="text-sky-600 hover:underline dark:text-sky-400">移除例外</button> : null}
                    </div>
                  ) : null}
                  {renderField("内容", soundEvent.content, (value) => updateSoundEvent(shotIndex, eventIndex, { content: value }), { multiline: true })}
                  {renderField("位置", soundEvent.timing, (value) => updateSoundEvent(shotIndex, eventIndex, { timing: value }), { valueTone: "muted" })}
                  {renderField("表达", soundEvent.expressionNotes, (value) => updateSoundEvent(shotIndex, eventIndex, { expressionNotes: value }), { multiline: true, valueTone: "muted" })}
                </DirectorPlanTreeNode>
                )
              })}
            </DirectorPlanTreeNode>
          </DirectorPlanTreeNode>
          </div>
        })}
        {speakerRoster.length > 0 || !readOnly ? <section aria-label="临时说话者" className="mt-6">
          <div className="mb-2 flex min-h-6 items-center justify-between text-xs text-slate-500 dark:text-slate-400">
            <span>临时说话者 · 共 {speakerRoster.length} 位</span>
            {treeAction("新增临时说话者", "新增临时说话者", "+", addSpeaker)}
          </div>
          <div className="min-w-0 rounded-md border border-slate-200 bg-slate-50/50 px-2 py-1.5 dark:border-white/10 dark:bg-white/[0.03]">
            {speakerRoster.length === 0 ? <p className="py-1 text-xs text-slate-500 dark:text-slate-400">暂无临时说话者</p> : speakerRoster.map((speaker, speakerIndex) => (
              <DirectorPlanTreeNode
                key={speaker.speakerId}
                label={"说话者 " + (speakerIndex + 1)}
                highlightRowOnHover
                actions={treeAction("删除说话者 " + (speakerIndex + 1), "删除说话者", "×", () => deleteSpeaker(speakerIndex))}
              >
                {renderField("名称", speaker.displayName, (value) => updateSpeaker(speakerIndex, { displayName: value }), { valueTone: "source" })}
                {renderField("身份", speaker.identityDescription, (value) => updateSpeaker(speakerIndex, { identityDescription: value }), { multiline: true })}
              </DirectorPlanTreeNode>
            ))}
          </div>
        </section> : null}
      </DirectorPlanTreeNode>
    </div>
  )
}
