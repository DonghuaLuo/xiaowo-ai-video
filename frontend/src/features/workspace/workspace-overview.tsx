import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import {
  ArrowUpRight,
  CircleHelp,
  FileText,
  Film,
  Loader2,
  Pencil,
  RefreshCcw,
  Save,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react"
import {
  appendNovelSourceFiles,
  createSource,
  deleteSource,
  deleteSourceSegment,
  getEpisodeSourceText,
  getSourceCoverage,
  listSources,
  openEpisodeSourceFileLocation,
  openSourceFileLocation,
  saveProjectNarratorReferenceAudio,
  saveEpisodeSourceText,
  saveSourceText,
  updateProjectOverview,
  type EpisodeSourceText,
  type EpisodeSourceFile,
  type ProjectOverviewUpdatePayload,
} from "@/backend"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useBackend } from "@/hooks/useBackend"
import { countContentChars } from "@/lib/text-metrics"
import { cn } from "@/lib/utils"
import { cleanProjectOverview } from "@/features/projects/project-cards"
import type { ProjectRow } from "@/features/projects/types"
import {contentModeLabel} from '@/features/settings/shared-template'
import { OverviewExcerptCharsInput } from "@/features/settings/model-config"
import { ConfirmDialog } from "@/shared/confirm-dialog"
import { projectOverviewReady } from "@/features/workspace/project-readiness"
import {
  DEFAULT_OVERVIEW_EXCERPT_CHARS,
  normalizeOverviewExcerptChars,
} from "@/features/settings/model-config-model"
import { ModalShell } from "@/shared/page-shell"
import { TooltipWrap } from "@/shared/tooltip-wrap"
import { errMsg } from "@/shared/backend-result"
import { pickLocalMediaFile } from "@/shared/image-picker"
import { mediaAssetFromImageFile, mediaPreviewSrc } from "@/shared/media"
import { ReferenceAudioCropDialog } from "@/shared/reference-audio-crop-dialog"
import { ReferenceAudioPlayer } from "@/shared/reference-audio-player"
import {
  loadOverviewAnalysisConfig,
  runProjectOverviewAnalysis,
  useProjectOverviewAnalysisState,
} from "./project-overview-analysis"
import { NovelSourceGate } from "./workspace-source-gate"
import {
  SOURCE_FILE_COLUMN_DESCRIPTIONS,
  TOTAL_SOURCE_DESCRIPTION,
  episodeActionKey,
  episodeSourceExcerpt,
  episodeStoragePath,
  episodeTitleWithId,
  readNovelTextFiles,
  sortedSourceFiles,
  sourceActionKey,
  sourceFileNameForSort,
  sourceGroupOf,
  sourceRowsFromSegments,
  sourceSegmentKind,
  sourceStoragePath,
  sourceTextToSourceFile,
  type SourceFile,
  type SourceFileGroup,
  upsertSourceRows,
} from "./workspace-source-model"


type ProjectOverviewFieldKey =
  | "excerpt_summary"
  | "genre_context"
  | "theme_visual_context"
  | "narrator_voice_design_prompt"

const OVERVIEW_INLINE_EDIT_INPUT_CLS =
  "min-w-0 w-full flex-1 resize-none overflow-hidden border-0 bg-transparent px-0 py-0 text-gray-700 shadow-none outline-none placeholder:text-gray-400 focus:border-0 focus:ring-0 dark:bg-transparent dark:text-gray-200 dark:placeholder:text-gray-500"

const PROJECT_OVERVIEW_FIELD_TIP_CLS =
  "max-w-[15rem] whitespace-normal text-left leading-5 text-pretty"

const PROJECT_OVERVIEW_FIELD_TIPS: Record<ProjectOverviewFieldKey, string> = {
  excerpt_summary: "用于项目概览展示和智能体回复背景。",
  genre_context:
    "辅助分集、原文事实拆分、片段剧本和分镜脚本判断题材口味与节奏，不提供剧情事实。",
  theme_visual_context:
    "为角色、生物、场景、道具和分镜图提供统一时代地域与世界视觉基调。",
  narrator_voice_design_prompt:
    "用于统一旁白音色；有参考音频时优先使用参考音频。",
}

function projectOverviewTextValue(value: unknown) {
  return typeof value === "string" ? value.trim() : ""
}

function projectOverviewExcerptSummary(overview: ProjectRow["overview"]) {
  if (!overview) return ""
  return (
    projectOverviewTextValue(overview.excerptSummary) ||
    projectOverviewTextValue(overview.excerpt_summary)
  )
}

function projectOverviewGenreContext(overview: ProjectRow["overview"]) {
  if (!overview) return ""
  return (
    projectOverviewTextValue(overview.genreContext) ||
    projectOverviewTextValue(overview.genre_context)
  )
}

function projectOverviewThemeVisual(overview: ProjectRow["overview"]) {
  if (!overview) return ""
  return (
    projectOverviewTextValue(overview.themeVisualContext) ||
    projectOverviewTextValue(overview.theme_visual_context)
  )
}

function projectOverviewNarratorVoiceDesign(overview: ProjectRow["overview"]) {
  if (!overview) return ""
  return (
    projectOverviewTextValue(overview.narratorVoiceDesignPrompt) ||
    projectOverviewTextValue(overview.narrator_voice_design_prompt)
  )
}

function projectOverviewEditRows(key: ProjectOverviewFieldKey, value: string) {
  const length = Array.from(value || "").length
  if (key === "theme_visual_context") return 1
  if (key === "genre_context") return 1
  if (key === "narrator_voice_design_prompt") return 2
  return length > 44 ? 2 : 1
}

function projectOverviewVisibleRows(
  element: HTMLElement | null,
  fallbackRows: number
) {
  if (!element) return fallbackRows
  const style = window.getComputedStyle(element)
  const lineHeight = Number.parseFloat(style.lineHeight)
  if (!Number.isFinite(lineHeight) || lineHeight <= 0) return fallbackRows
  const rows = Math.round(element.getBoundingClientRect().height / lineHeight)
  return Math.max(1, Math.min(3, rows || fallbackRows))
}

export function OverviewPage({
  project,
  onProjectChanged,
}: {
  project: ProjectRow
  onProjectChanged: () => Promise<void>
}) {
  const { backendReady, callBackend } = useBackend()
  const novelSourceInputRef = useRef<HTMLInputElement | null>(null)
  const supplementalSourceInputRef = useRef<HTMLInputElement | null>(null)
  const overviewAnalysisState = useProjectOverviewAnalysisState(project.id)
  const analyzing = overviewAnalysisState.status === "running"
  const [regenerateConfig, setRegenerateConfig] = useState<{
    excerptChars: number
  } | null>(null)
  const [sources, setSources] = useState<SourceFile[]>([])
  const [activeSourceId, setActiveSourceId] = useState("")
  const [sourceUploadGroup, setSourceUploadGroup] =
    useState<SourceFileGroup | null>(null)
  const [sourceDeleteDraft, setSourceDeleteDraft] = useState<SourceFile | null>(
    null
  )
  const [sourceDeleteLoading, setSourceDeleteLoading] = useState(false)
  const [episodeSources, setEpisodeSources] = useState<EpisodeSourceFile[]>([])
  const [sourcesLoading, setSourcesLoading] = useState(true)
  const [sourceActionLoading, setSourceActionLoading] = useState<string | null>(
    null
  )
  const [episodeActionLoading, setEpisodeActionLoading] = useState<
    string | null
  >(null)
  const [episodePreview, setEpisodePreview] = useState<{
    source: EpisodeSourceFile
    detail: EpisodeSourceText
  } | null>(null)
  const [episodePreviewText, setEpisodePreviewText] = useState("")
  const [episodePreviewEditing, setEpisodePreviewEditing] = useState(false)
  const [episodePreviewSaving, setEpisodePreviewSaving] = useState(false)
  const overview = project.overview
  const overviewExcerptSummary =
    projectOverviewExcerptSummary(overview) || cleanProjectOverview(project)
  const overviewSynopsis = overviewExcerptSummary
  const overviewGenreContext = projectOverviewGenreContext(overview)
  const overviewThemeVisual = projectOverviewThemeVisual(overview)
  const overviewNarratorVoiceDesign = projectOverviewNarratorVoiceDesign(overview)
  const narratorReferenceAudio = overview?.narratorReferenceAudio ?? overview?.narrator_reference_audio ?? null
  const overviewFieldValues: Record<ProjectOverviewFieldKey, string> = {
    excerpt_summary: overviewExcerptSummary,
    genre_context: overviewGenreContext,
    theme_visual_context: overviewThemeVisual,
    narrator_voice_design_prompt: overviewNarratorVoiceDesign,
  }
  const [overviewEditingKey, setOverviewEditingKey] =
    useState<ProjectOverviewFieldKey | null>(null)
  const [overviewEditValue, setOverviewEditValue] = useState("")
  const [overviewEditRows, setOverviewEditRows] = useState(1)
  const [overviewSavingKey, setOverviewSavingKey] =
    useState<ProjectOverviewFieldKey | null>(null)
  const [narratorAudioSaving, setNarratorAudioSaving] = useState(false)
  const [narratorAudioCropOpen, setNarratorAudioCropOpen] = useState(false)
  const [narratorAudioCropSource, setNarratorAudioCropSource] = useState<
    Awaited<ReturnType<typeof pickLocalMediaFile>>
  >(null)
  useEffect(() => {
    if (analyzing) setOverviewEditingKey(null)
  }, [analyzing])
  const rawNovelSources = useMemo(
    () => sources.filter((source) => sourceGroupOf(source) === "novel"),
    [sources]
  )
  const rawNovelFileRows = useMemo(
    () => sourceRowsFromSegments(rawNovelSources),
    [rawNovelSources]
  )
  const novelSources = useMemo(
    () => sortedSourceFiles(rawNovelFileRows),
    [rawNovelFileRows]
  )
  const lastNovelFileRowId = rawNovelFileRows.at(-1)?.id ?? ""
  const supplementalSources = useMemo(
    () =>
      sortedSourceFiles(
        sources.filter((source) => sourceGroupOf(source) === "supplemental")
      ),
    [sources]
  )
  const primarySource =
    sources.find(
      (source) =>
        source.id === activeSourceId && sourceGroupOf(source) === "novel"
    ) ??
    sources.find((source) => sourceGroupOf(source) === "novel") ??
    null
  const primarySourcePath = primarySource
    ? sourceStoragePath(primarySource)
    : sourcesLoading
      ? "正在加载总文件路径..."
      : "暂无总文件路径"
  const primarySourceOpenKey = primarySource
    ? sourceActionKey(primarySource, "open")
    : ""

  const loadSources = useCallback(async () => {
    if (!backendReady) return
    setSourcesLoading(true)
    try {
      const [nextSources, coverageResult] = await Promise.all([
        listSources(callBackend, project.id),
        getSourceCoverage(callBackend, project.id).catch(() => ({
          coverage: { sourceId: "" },
          episodeSources: [],
        })),
      ])
      setSources(nextSources)
      setActiveSourceId(
        coverageResult.coverage.sourceId || nextSources[0]?.id || ""
      )
      setEpisodeSources(coverageResult.episodeSources)
    } catch (error) {
      toast.error(errMsg(error, "加载源文件失败"))
    } finally {
      setSourcesLoading(false)
    }
  }, [backendReady, callBackend, project.id])

  useEffect(() => {
    void loadSources()
  }, [loadSources, project.updatedAtRank])

  const handleAddSourceFiles = useCallback(
    async (files: FileList | File[] | null, sourceGroup: SourceFileGroup) => {
      const selectedFiles = Array.from(files ?? [])
      if (selectedFiles.length === 0) return
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const isNovelUpload = sourceGroup === "novel"
      setSourceUploadGroup(sourceGroup)
      try {
        const payloads = await readNovelTextFiles(selectedFiles, sourceGroup)
        if (isNovelUpload) {
          const targetSource =
            primarySource ??
            sources.find((source) => sourceGroupOf(source) === "novel") ??
            null
          if (!targetSource) {
            throw new Error("未找到可追加的原文件，请先完成项目原文导入")
          }
          const result = await appendNovelSourceFiles(
            callBackend,
            project.id,
            targetSource.id,
            payloads
          )
          const nextSource = result.source
          if (nextSource) {
            setSources((current) => upsertSourceRows(current, [nextSource]))
            setActiveSourceId((current) => current || nextSource.id)
          }
          toast.success(`已追加 ${payloads.length} 个原文件`)
          return
        }
        const sourcesByTitle = new Map(
          sources
            .filter((source) => sourceGroupOf(source) === sourceGroup)
            .map((source): [string, SourceFile] => [
              String(source.title || sourceFileNameForSort(source))
                .trim()
                .toLowerCase(),
              source,
            ])
        )
        const changedSources: SourceFile[] = []
        for (const payload of payloads) {
          const titleKey = payload.title.trim().toLowerCase()
          const existingSource = sourcesByTitle.get(titleKey)
          if (existingSource) {
            const savedText = await saveSourceText(
              callBackend,
              project.id,
              existingSource.id,
              {
                text: payload.content,
                title: payload.title,
                reason: "用户在项目概览页更新项目文件文本",
              }
            )
            const nextSource = sourceTextToSourceFile(
              existingSource,
              savedText,
              payload.content
            )
            changedSources.push(nextSource)
            sourcesByTitle.set(titleKey, nextSource)
            continue
          }
          const createdSource = await createSource(
            callBackend,
            project.id,
            payload,
            { onConflict: "rename" }
          )
          changedSources.push(createdSource)
          sourcesByTitle.set(titleKey, createdSource)
        }
        setSources((current) => upsertSourceRows(current, changedSources))
        toast.success(
          isNovelUpload
            ? `已处理 ${payloads.length} 个原文件`
            : `已处理 ${payloads.length} 个扩展资料`
        )
      } catch (error) {
        toast.error(
          errMsg(error, isNovelUpload ? "添加原文件失败" : "添加扩展资料失败")
        )
      } finally {
        setSourceUploadGroup(null)
        if (isNovelUpload && novelSourceInputRef.current) {
          novelSourceInputRef.current.value = ""
        }
        if (
          sourceGroup === "supplemental" &&
          supplementalSourceInputRef.current
        ) {
          supplementalSourceInputRef.current.value = ""
        }
      }
    },
    [backendReady, callBackend, project.id, sources, primarySource]
  )

  const handleConfirmDeleteSource = useCallback(async () => {
    if (!sourceDeleteDraft) return
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    setSourceDeleteLoading(true)
    const deleteGroup = sourceGroupOf(sourceDeleteDraft)
    try {
      if (deleteGroup === "novel") {
        if (!sourceDeleteDraft.sourceId || !sourceDeleteDraft.segmentId) {
          throw new Error("该原文件缺少可校验记录，不能在此删除")
        }
        const result = await deleteSourceSegment(
          callBackend,
          project.id,
          sourceDeleteDraft.sourceId,
          sourceDeleteDraft.segmentId
        )
        const sourceAfterDelete = result.source
        if (sourceAfterDelete) {
          setSources((current) =>
            upsertSourceRows(current, [sourceAfterDelete])
          )
        }
      } else {
        await deleteSource(callBackend, project.id, sourceDeleteDraft.id)
        setSources((current) =>
          current.filter((source) => source.id !== sourceDeleteDraft.id)
        )
      }
      setSourceDeleteDraft(null)
      toast.success(deleteGroup === "novel" ? "原文件已删除" : "扩展资料已删除")
    } catch (error) {
      toast.error(
        errMsg(
          error,
          deleteGroup === "novel" ? "删除原文件失败" : "删除扩展资料失败"
        )
      )
    } finally {
      setSourceDeleteLoading(false)
    }
  }, [backendReady, callBackend, project.id, sourceDeleteDraft])

  const handleOpenSourceLocation = useCallback(
    async (source: SourceFile) => {
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const key = sourceActionKey(source, "open")
      setSourceActionLoading(key)
      try {
        await openSourceFileLocation(
          callBackend,
          project.id,
          source.id
        )
        const isSupplemental = sourceGroupOf(source) === "supplemental"
        toast.success(isSupplemental ? "已打开文件位置" : "已打开总文件位置")
      } catch (error) {
        toast.error(
          errMsg(
            error,
            sourceGroupOf(source) === "supplemental"
              ? "打开文件位置失败"
              : "打开总文件位置失败"
          )
        )
      } finally {
        setSourceActionLoading((current) => (current === key ? null : current))
      }
    },
    [backendReady, callBackend, project.id]
  )

  const handleViewEpisodeSource = useCallback(
    async (source: EpisodeSourceFile) => {
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const key = episodeActionKey(source, "view")
      setEpisodeActionLoading(key)
      try {
        const detail = await getEpisodeSourceText(
          callBackend,
          project.id,
          source.episodeId
        )
        setEpisodePreview({ source, detail })
        setEpisodePreviewText(detail.text ?? "")
        setEpisodePreviewEditing(false)
      } catch (error) {
        toast.error(errMsg(error, "读取本集原文失败"))
      } finally {
        setEpisodeActionLoading((current) => (current === key ? null : current))
      }
    },
    [backendReady, callBackend, project.id]
  )

  const handleOpenEpisodeSourceLocation = useCallback(
    async (source: EpisodeSourceFile) => {
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const key = episodeActionKey(source, "open")
      setEpisodeActionLoading(key)
      try {
        await openEpisodeSourceFileLocation(
          callBackend,
          project.id,
          source.episodeId
        )
        toast.success("已打开分集原文位置")
      } catch (error) {
        toast.error(errMsg(error, "打开分集原文位置失败"))
      } finally {
        setEpisodeActionLoading((current) => (current === key ? null : current))
      }
    },
    [backendReady, callBackend, project.id]
  )

  const handleSaveEpisodeSource = useCallback(async () => {
    if (!episodePreview) return
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    setEpisodePreviewSaving(true)
    try {
      const nextDetail = await saveEpisodeSourceText(
        callBackend,
        project.id,
        episodePreview.source.episodeId,
        {
          text: episodePreviewText,
          title: episodePreview.detail.title || episodePreview.source.title,
          reason: "用户在项目概览页手动修改分集原文",
        }
      )
      const nextSource: EpisodeSourceFile = {
        ...episodePreview.source,
        title: nextDetail.title || episodePreview.source.title,
        charCount: nextDetail.charCount,
        excerpt: episodeSourceExcerpt(nextDetail.text),
        relativePath:
          nextDetail.relativePath || episodePreview.source.relativePath,
      }
      setEpisodePreview({ source: nextSource, detail: nextDetail })
      setEpisodePreviewText(nextDetail.text ?? "")
      setEpisodePreviewEditing(false)
      setEpisodeSources((rows) =>
        rows.map((row) =>
          row.episodeId === nextSource.episodeId
            ? { ...row, ...nextSource }
            : row
        )
      )
      toast.success("本集原文已保存")
      await loadSources()
      await onProjectChanged()
    } catch (error) {
      toast.error(errMsg(error, "保存本集原文失败"))
    } finally {
      setEpisodePreviewSaving(false)
    }
  }, [
    backendReady,
    callBackend,
    episodePreview,
    episodePreviewText,
    loadSources,
    onProjectChanged,
    project.id,
  ])

  const episodePreviewCharCount = useMemo(
    () => countContentChars(episodePreviewText),
    [episodePreviewText]
  )

  const handleOpenRegenerateDialog = useCallback(() => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    setRegenerateConfig(loadOverviewAnalysisConfig())
  }, [backendReady])

  const handleRegenerateOverview = useCallback(
    async (excerptChars: number) => {
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      try {
        setRegenerateConfig(null)
        await runProjectOverviewAnalysis(callBackend, project.id, {
          excerptChars: normalizeOverviewExcerptChars(excerptChars),
        })
        toast.success("项目概述已更新")
        await onProjectChanged()
        await loadSources()
      } catch (error) {
        toast.error(errMsg(error, "项目概述分析失败"))
      }
    },
    [backendReady, callBackend, loadSources, onProjectChanged, project.id]
  )

  const handlePickNarratorReferenceAudio = useCallback(async () => {
    if (!backendReady || narratorAudioSaving) return
    const file = await pickLocalMediaFile("上传旁白参考音频", "audio")
    if (!file) return
    setNarratorAudioCropSource(file)
    setNarratorAudioCropOpen(true)
  }, [backendReady, narratorAudioSaving])

  const handleConfirmNarratorReferenceAudio = useCallback(async (file: Awaited<ReturnType<typeof pickLocalMediaFile>>) => {
    if (!file) return
    setNarratorAudioSaving(true)
    try {
      const nextProject = await saveProjectNarratorReferenceAudio(
        callBackend,
        project.id,
        mediaAssetFromImageFile(file),
      )
      await onProjectChanged()
      if (nextProject) toast.success("旁白参考音频已保存")
    } catch (error) {
      toast.error(errMsg(error, "旁白参考音频保存失败"))
      throw error
    } finally {
      setNarratorAudioSaving(false)
    }
  }, [callBackend, onProjectChanged, project.id])

  const handleRemoveNarratorReferenceAudio = useCallback(async () => {
    if (!backendReady || narratorAudioSaving || !narratorReferenceAudio) return
    setNarratorAudioSaving(true)
    try {
      await saveProjectNarratorReferenceAudio(callBackend, project.id, null)
      await onProjectChanged()
      toast.success("旁白参考音频已移除")
    } catch (error) {
      toast.error(errMsg(error, "旁白参考音频移除失败"))
    } finally {
      setNarratorAudioSaving(false)
    }
  }, [backendReady, callBackend, narratorAudioSaving, narratorReferenceAudio, onProjectChanged, project.id])

  const handleStartOverviewFieldEdit = useCallback(
    (key: ProjectOverviewFieldKey, displayElement?: HTMLElement | null) => {
      if (!backendReady || analyzing || overviewSavingKey) return
      const value = overviewFieldValues[key] ?? ""
      setOverviewEditingKey(key)
      setOverviewEditValue(value)
      setOverviewEditRows(
        projectOverviewVisibleRows(
          displayElement ?? null,
          projectOverviewEditRows(key, value)
        )
      )
    },
    [backendReady, analyzing, overviewFieldValues, overviewSavingKey]
  )

  const handleCommitOverviewField = useCallback(
    async (key: ProjectOverviewFieldKey) => {
      const currentValue = projectOverviewTextValue(overviewFieldValues[key])
      const nextValue = overviewEditValue.trim()
      setOverviewEditingKey(null)
      if (analyzing || overviewSavingKey) return
      if (nextValue === currentValue) return
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const payload: ProjectOverviewUpdatePayload = {}
      payload[key] = nextValue
      setOverviewSavingKey(key)
      try {
        await updateProjectOverview(callBackend, project.id, payload)
        toast.success("项目概述已保存")
        await onProjectChanged()
      } catch (error) {
        toast.error(errMsg(error, "项目概述保存失败"))
      } finally {
        setOverviewSavingKey(null)
      }
    },
    [
      analyzing,
      backendReady,
      callBackend,
      onProjectChanged,
      overviewEditValue,
      overviewFieldValues,
      overviewSavingKey,
      project.id,
    ]
  )

  const renderOverviewLabel = (label: string, tip: string) => (
    <TooltipWrap
      content={tip}
      contentClassName={PROJECT_OVERVIEW_FIELD_TIP_CLS}
    >
      <span className="inline-flex shrink-0 cursor-help items-center gap-1 font-medium text-gray-700 dark:text-gray-200">
        <span>{label}</span>
        <CircleHelp className="size-3 text-gray-400 dark:text-gray-500" />
        <span>：</span>
      </span>
    </TooltipWrap>
  )

  const renderOverviewFieldTitle = (
    key: ProjectOverviewFieldKey,
    label: string
  ) => renderOverviewLabel(label, PROJECT_OVERVIEW_FIELD_TIPS[key])

  const renderOverviewEditInput = (
    key: ProjectOverviewFieldKey,
    placeholder: string,
    className?: string
  ) => (
    <textarea
      value={overviewEditValue}
      onChange={(event) => setOverviewEditValue(event.target.value)}
      onBlur={() => void handleCommitOverviewField(key)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === "Escape") {
          event.preventDefault()
          event.currentTarget.blur()
        }
      }}
      className={cn(OVERVIEW_INLINE_EDIT_INPUT_CLS, className)}
      placeholder={placeholder}
      rows={overviewEditRows}
      disabled={!backendReady || analyzing || Boolean(overviewSavingKey)}
      autoFocus
    />
  )

  const renderOverviewEditButton = (
    key: ProjectOverviewFieldKey,
    label: string,
    className?: string
  ) => (
    <Button
      type="button"
      size="icon-sm"
      variant="ghost"
      aria-label={`编辑${label}`}
      className={cn(
        "ml-1 inline-flex size-5 shrink-0 rounded-sm p-0 align-[-4px] text-gray-400 hover:bg-transparent hover:text-gray-600 focus-visible:ring-0 active:bg-transparent dark:text-gray-500 dark:hover:bg-transparent dark:hover:text-gray-300",
        className
      )}
      disabled={!backendReady || analyzing || Boolean(overviewSavingKey)}
      onClick={(event) => {
        event.stopPropagation()
        const displayElement = event.currentTarget.closest(
          "[data-overview-display-row]"
        ) as HTMLElement | null
        handleStartOverviewFieldEdit(key, displayElement)
      }}
    >
      {overviewSavingKey === key ? (
        <Loader2 className="size-3.5 animate-spin" />
      ) : (
        <Pencil className="size-3.5" />
      )}
    </Button>
  )

  const renderSourceFileColumn = (
    sourceGroup: SourceFileGroup,
    title: string,
    emptyText: string,
    rows: SourceFile[]
  ) => {
    const uploading = sourceUploadGroup === sourceGroup
    const inputRef =
      sourceGroup === "novel" ? novelSourceInputRef : supplementalSourceInputRef
    const isNovelColumn = sourceGroup === "novel"
    return (
      <section className="min-w-0 rounded-2xl border border-gray-200/70 bg-white/80 p-5 shadow-sm dark:border-white/10 dark:bg-white/[0.035]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <FileText className="size-4 shrink-0 text-indigo-500" />
              <h3 className="truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
                {title}
              </h3>
              <Badge
                variant="outline"
                className="shrink-0 rounded-full text-[11px]"
              >
                {rows.length} 个
              </Badge>
            </div>
            <p className="mt-1.5 max-w-[34rem] text-[11px] leading-5 text-gray-500 dark:text-gray-400">
              {SOURCE_FILE_COLUMN_DESCRIPTIONS[sourceGroup]}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8 gap-1.5 bg-white/55 text-[11px] dark:bg-white/5"
              disabled={!backendReady || Boolean(sourceUploadGroup)}
              onClick={() => inputRef.current?.click()}
            >
              {uploading ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Upload className="size-3.5" />
              )}
              添加
            </Button>
          </div>
        </div>

        {sourcesLoading ? (
          <div className="py-10 text-center text-sm text-gray-500 dark:text-gray-400">
            正在加载文件...
          </div>
        ) : rows.length === 0 ? (
          <div className="mt-4 border border-dashed border-gray-200/80 px-4 py-10 text-center text-sm text-gray-500 dark:border-white/10 dark:text-gray-400">
            {emptyText}
          </div>
        ) : (
          <div className="mt-4 max-h-[330px] space-y-2 overflow-y-auto pr-1">
            {rows.map((source) => {
              const path = sourceStoragePath(source)
              const openKey = sourceActionKey(source, "open")
              const deleting =
                sourceDeleteDraft?.id === source.id && sourceDeleteLoading
              const unsupportedSegmentDelete =
                isNovelColumn &&
                source.sourceKind === "segment" &&
                sourceSegmentKind(source) !== "append"
              const missingSegmentRecord =
                isNovelColumn && (!source.sourceId || !source.segmentId)
              const deleteOutOfOrder =
                isNovelColumn && source.id !== lastNovelFileRowId
              return (
                <div
                  key={source.id}
                  className="flex min-w-0 flex-col gap-3 rounded-lg border border-gray-200/70 bg-white/70 p-3 sm:flex-row sm:items-center sm:justify-between dark:border-white/10 dark:bg-white/[0.035]"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
                      {source.title || sourceFileNameForSort(source)}
                    </div>
                    <div
                      className="mt-1 truncate text-[11px] text-gray-500 dark:text-gray-400"
                      title={path}
                    >
                      {path}
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-col items-start gap-1.5 sm:items-end">
                    <div className="flex flex-wrap items-center gap-1.5 sm:justify-end">
                      {!isNovelColumn ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 gap-1 px-2 text-[11px] text-gray-500 dark:text-gray-400"
                          disabled={
                            !backendReady || Boolean(sourceActionLoading)
                          }
                          onClick={() => void handleOpenSourceLocation(source)}
                        >
                          {sourceActionLoading === openKey ? (
                            <Loader2 className="size-3.5 animate-spin" />
                          ) : (
                            <ArrowUpRight className="size-3.5" />
                          )}
                          文件位置
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 gap-1 px-2 text-[11px] text-rose-600 hover:bg-rose-50 hover:text-rose-700 dark:text-rose-300 dark:hover:bg-rose-950/30 dark:hover:text-rose-100"
                        disabled={
                          !backendReady ||
                          deleting ||
                          unsupportedSegmentDelete ||
                          missingSegmentRecord ||
                          deleteOutOfOrder ||
                          sourceDeleteLoading ||
                          Boolean(sourceUploadGroup)
                        }
                        title={
                          unsupportedSegmentDelete
                            ? "只能删除后续追加的原文件"
                            : missingSegmentRecord
                              ? "该原文件缺少可校验记录，不能删除"
                              : deleteOutOfOrder
                                ? "原文件只能按最后添加的顺序删除"
                                : undefined
                        }
                        onClick={() => setSourceDeleteDraft(source)}
                      >
                        {deleting ? (
                          <Loader2 className="size-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="size-3.5" />
                        )}
                        删除
                      </Button>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5 sm:justify-end">
                      <Badge
                        variant="outline"
                        className="rounded-full text-[11px]"
                      >
                        {source.wordCount.toLocaleString()} 字
                      </Badge>
                      <span className="text-[11px] text-gray-500 dark:text-gray-400">
                        {source.createdAt}
                      </span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </section>
    )
  }

  if (project.sourceCount <= 0 || !projectOverviewReady(project)) {
    return <NovelSourceGate project={project} onAnalyzed={onProjectChanged} />
  }

  return (
    <>
      <header className="flex items-end gap-3">
        <span className="mb-1 h-7 w-[3px] rounded-full bg-gradient-to-b from-indigo-500 via-sky-500 to-emerald-500" />
        <div className="min-w-0">
          <h2 className="truncate text-[28px] font-semibold tracking-tight text-gray-950 dark:text-gray-50">
            {project.name}
          </h2>
          <p className="mt-1 text-[11px] tracking-[0.16em] text-gray-400 uppercase dark:text-gray-500">
            {contentModeLabel(
              project.contentMode ?? project.content_mode ?? "drama"
            )}
          </p>
        </div>
      </header>

      <section className="rounded-2xl border border-gray-200/70 bg-white/80 p-5 shadow-sm dark:border-white/10 dark:bg-white/[0.035]">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-sm font-semibold text-gray-950 dark:text-gray-50">
              <Sparkles className="size-4 text-indigo-600 dark:text-indigo-300" />
              项目概述
            </div>
            <div className="mt-3 flex min-w-0 items-start gap-0 border-l-2 border-indigo-200 pl-3 text-xs leading-6 text-gray-500 dark:border-indigo-900/60 dark:text-gray-400">
              {overviewEditingKey === "theme_visual_context" ? (
                <>
                  {renderOverviewFieldTitle("theme_visual_context", "主题视觉")}
                  {renderOverviewEditInput(
                    "theme_visual_context",
                    "主题视觉",
                    "text-xs leading-6"
                  )}
                </>
              ) : (
                <p
                  className="min-w-0 flex-1 cursor-text break-words"
                  data-overview-display-row
                  onClick={(event) =>
                    handleStartOverviewFieldEdit(
                      "theme_visual_context",
                      event.currentTarget
                    )
                  }
                >
                  {renderOverviewFieldTitle("theme_visual_context", "主题视觉")}
                  <span>{overviewThemeVisual || "未设置"}</span>
                  {renderOverviewEditButton("theme_visual_context", "主题视觉")}
                </p>
              )}
            </div>
            <div className="mt-3 flex min-w-0 items-start gap-0 border-l-2 border-indigo-200 pl-3 text-xs leading-6 text-gray-500 dark:border-indigo-900/60 dark:text-gray-400">
              {overviewEditingKey === "genre_context" ? (
                <>
                  {renderOverviewFieldTitle("genre_context", "题材语境")}
                  {renderOverviewEditInput(
                    "genre_context",
                    "题材语境",
                    "text-xs leading-6"
                  )}
                </>
              ) : (
                <p
                  className="min-w-0 flex-1 cursor-text break-words"
                  data-overview-display-row
                  onClick={(event) =>
                    handleStartOverviewFieldEdit(
                      "genre_context",
                      event.currentTarget
                    )
                  }
                >
                  {renderOverviewFieldTitle("genre_context", "题材语境")}
                  <span>{overviewGenreContext || "未设置"}</span>
                  {renderOverviewEditButton("genre_context", "题材语境")}
                </p>
              )}
            </div>
            <div className="mt-3 flex min-w-0 items-center gap-0 border-l-2 border-emerald-200 pl-3 text-xs leading-6 text-gray-500 dark:border-emerald-900/60 dark:text-gray-400">
              {overviewEditingKey === "narrator_voice_design_prompt" ? (
                <>
                  {renderOverviewFieldTitle("narrator_voice_design_prompt", "旁白声音设计")}
                  {renderOverviewEditInput(
                    "narrator_voice_design_prompt",
                    "旁白声音设计提示词",
                    "text-xs leading-6"
                  )}
                </>
              ) : (
                <p
                  className="min-w-0 flex-1 cursor-text break-words"
                  data-overview-display-row
                  onClick={(event) =>
                    handleStartOverviewFieldEdit(
                      "narrator_voice_design_prompt",
                      event.currentTarget
                    )
                  }
                >
                  {renderOverviewFieldTitle("narrator_voice_design_prompt", "旁白声音设计")}
                  <span>{overviewNarratorVoiceDesign || "未设置"}</span>
                  {renderOverviewEditButton("narrator_voice_design_prompt", "旁白声音设计")}
                </p>
              )}
            </div>
            <div className="mt-3 flex min-w-0 items-center gap-0 border-l-2 border-emerald-200 pl-3 text-xs leading-6 text-gray-500 dark:border-emerald-900/60 dark:text-gray-400">
              {renderOverviewLabel(
                "旁白参考音频",
                "有参考音频时优先使用；没有时使用旁白声音设计。"
              )}
              {narratorReferenceAudio ? (
                <>
                  <ReferenceAudioPlayer
                    src={mediaPreviewSrc(narratorReferenceAudio) ?? undefined}
                    className="w-[240px] max-w-[40vw] flex-none"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 shrink-0 gap-1.5 rounded-sm px-1.5 text-[11px] font-medium text-indigo-600 hover:bg-indigo-50/80 hover:text-indigo-700 dark:text-indigo-300 dark:hover:bg-indigo-400/10 dark:hover:text-indigo-200"
                    disabled={!backendReady || analyzing || narratorAudioSaving}
                    onClick={() => void handlePickNarratorReferenceAudio()}
                  >
                    {narratorAudioSaving ? <Loader2 className="size-3" /> : <Upload className="size-3" />}
                    替换
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 shrink-0 gap-1.5 rounded-sm px-1.5 text-[11px] font-medium text-rose-600 hover:bg-rose-50/80 hover:text-rose-700 dark:text-rose-300 dark:hover:bg-rose-400/10 dark:hover:text-rose-200"
                    disabled={!backendReady || analyzing || narratorAudioSaving}
                    onClick={() => void handleRemoveNarratorReferenceAudio()}
                  >
                    <Trash2 className="size-3" />
                    移除
                  </Button>
                </>
              ) : (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 shrink-0 gap-1.5 rounded-sm px-1.5 text-[11px] font-medium text-indigo-600 hover:bg-indigo-50/80 hover:text-indigo-700 dark:text-indigo-300 dark:hover:bg-indigo-400/10 dark:hover:text-indigo-200"
                  disabled={!backendReady || analyzing || narratorAudioSaving}
                  onClick={() => void handlePickNarratorReferenceAudio()}
                >
                  {narratorAudioSaving ? <Loader2 className="size-3" /> : <Upload className="size-3" />}
                  上传
                </Button>
              )}
            </div>
          </div>
          <Button
            type="button"
            variant="gradient"
            size="sm"
            className="h-8 shrink-0 gap-1.5 self-start text-xs sm:self-start"
            disabled={!backendReady || analyzing}
            onClick={handleOpenRegenerateDialog}
          >
            {analyzing ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <RefreshCcw className="size-3.5" />
            )}
            重新生成
          </Button>
        </div>
        {overviewEditingKey === "excerpt_summary" ? (
          <div className="mt-3 flex min-w-0 items-center">
            {renderOverviewEditInput(
              "excerpt_summary",
              "项目概述",
              "text-sm leading-7"
            )}
          </div>
        ) : (
          <div className="mt-3 min-w-0">
            <p
              className="min-w-0 text-sm leading-7 text-gray-600 dark:text-gray-300"
              data-overview-display-row
            >
              <span>{overviewSynopsis || "未设置项目概述"}</span>
              {renderOverviewEditButton("excerpt_summary", "项目概述")}
            </p>
          </div>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-gray-200/70 pt-3 dark:border-white/10">
          <div className="min-w-0 flex-1">
            <p className="text-[11px] leading-5 text-gray-500 dark:text-gray-400">
              {TOTAL_SOURCE_DESCRIPTION}
            </p>
            <div className="mt-1.5 truncate text-xs text-gray-600 dark:text-gray-300">
              {primarySourcePath}
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 gap-1.5 bg-white/55 text-xs dark:bg-white/5"
            disabled={
              !backendReady || !primarySource || Boolean(sourceActionLoading)
            }
            onClick={() => {
              if (primarySource) void handleOpenSourceLocation(primarySource)
            }}
          >
            {sourceActionLoading === primarySourceOpenKey ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <ArrowUpRight className="size-3.5" />
            )}
            打开原文
          </Button>
        </div>
      </section>

      <input
        ref={novelSourceInputRef}
        type="file"
        multiple
        accept=".txt,text/plain"
        className="sr-only"
        disabled={!backendReady || Boolean(sourceUploadGroup)}
        onChange={(event) => {
          void handleAddSourceFiles(event.currentTarget.files, "novel")
        }}
      />
      <input
        ref={supplementalSourceInputRef}
        type="file"
        multiple
        accept=".txt,.md,text/plain,text/markdown"
        className="sr-only"
        disabled={!backendReady || Boolean(sourceUploadGroup)}
        onChange={(event) => {
          void handleAddSourceFiles(event.currentTarget.files, "supplemental")
        }}
      />
      <div className="grid gap-4 lg:grid-cols-2">
        {renderSourceFileColumn(
          "novel",
          "原文件",
          "暂无原文件。",
          novelSources
        )}
        {renderSourceFileColumn(
          "supplemental",
          "扩展资料",
          "暂无扩展资料。",
          supplementalSources
        )}
      </div>
      {regenerateConfig ? (
        <OverviewRegenerateDialog
          excerptChars={regenerateConfig.excerptChars}
          loading={analyzing}
          onClose={() => setRegenerateConfig(null)}
          onConfirm={(excerptChars) =>
            void handleRegenerateOverview(excerptChars)
          }
        />
      ) : null}
      <ConfirmDialog
        open={Boolean(sourceDeleteDraft)}
        title={
          sourceDeleteDraft && sourceGroupOf(sourceDeleteDraft) === "novel"
            ? "删除原文件"
            : "删除扩展资料"
        }
        description={
          sourceDeleteDraft
            ? sourceGroupOf(sourceDeleteDraft) === "novel"
              ? `将从总文件中移除「${sourceDeleteDraft.title || sourceFileNameForSort(sourceDeleteDraft)}」。`
              : `将删除「${sourceDeleteDraft.title || sourceFileNameForSort(sourceDeleteDraft)}」。`
            : ""
        }
        confirmLabel="删除"
        loadingLabel="删除中"
        loading={sourceDeleteLoading}
        onCancel={() => {
          if (!sourceDeleteLoading) setSourceDeleteDraft(null)
        }}
        onConfirm={() => void handleConfirmDeleteSource()}
      />

      <section className="rounded-2xl border border-gray-200/70 bg-white/80 p-5 shadow-sm dark:border-white/10 dark:bg-white/[0.035]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <Film className="size-4 shrink-0 text-indigo-500" />
            <h3 className="truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
              分集原文列表
            </h3>
          </div>
          <Badge variant="outline" className="rounded-full text-[11px]">
            {episodeSources.length} 集
          </Badge>
        </div>
        {sourcesLoading ? (
          <div className="py-12 text-center text-sm text-gray-500 dark:text-gray-400">
            正在加载分集原文...
          </div>
        ) : episodeSources.length === 0 ? (
          <div className="mt-5 border border-dashed border-gray-200/80 px-5 py-12 text-center text-sm text-gray-500 dark:border-white/10 dark:text-gray-400">
            暂无分集原文。
          </div>
        ) : (
          <div className="mt-4 flex flex-wrap gap-3">
            {episodeSources.map((source) => {
              const excerpt = episodeSourceExcerpt(source.excerpt)
              const path = episodeStoragePath(source)
              const viewKey = episodeActionKey(source, "view")
              const openKey = episodeActionKey(source, "open")
              return (
                <article
                  key={source.episodeId}
                  className="flex min-h-[146px] w-full max-w-[560px] flex-col justify-between rounded-lg border border-gray-200/70 bg-white/55 p-4 dark:border-white/10 dark:bg-white/[0.025]"
                >
                  <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-2">
                      <h4 className="min-w-0 flex-1 truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
                        {source.title || source.episodeId}
                      </h4>
                      <Badge
                        variant="outline"
                        className="shrink-0 rounded-full text-[11px]"
                      >
                        {source.episodeId}
                      </Badge>
                    </div>
                    <p className="mt-2 line-clamp-2 text-xs leading-6 text-gray-600 dark:text-gray-300">
                      {excerpt || "暂无简介。"}
                    </p>
                    <div className="mt-3 truncate text-xs text-gray-500 dark:text-gray-400">
                      {source.charCount.toLocaleString()} 字 · {path}
                    </div>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-8 gap-1.5 bg-white/55 text-[11px] dark:bg-white/5"
                      disabled={!backendReady || Boolean(episodeActionLoading)}
                      onClick={() => void handleViewEpisodeSource(source)}
                    >
                      {episodeActionLoading === viewKey ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        <FileText className="size-3.5" />
                      )}
                      查看原文
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8 gap-1.5 px-2 text-[11px] text-gray-500 dark:text-gray-400"
                      disabled={!backendReady || Boolean(episodeActionLoading)}
                      onClick={() =>
                        void handleOpenEpisodeSourceLocation(source)
                      }
                    >
                      {episodeActionLoading === openKey ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        <ArrowUpRight className="size-3.5" />
                      )}
                      打开
                    </Button>
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </section>
      {episodePreview ? (
        <ModalShell
          title={episodeTitleWithId(
            episodePreview.source,
            episodePreview.detail
          )}
          description={
            episodePreview.detail.relativePath ||
            episodePreview.source.relativePath ||
            "episodes/source.txt"
          }
          className="max-h-[calc(100dvh-4rem)] max-w-[960px] sm:max-h-[calc(100dvh-5rem)]"
          bodyClassName="flex min-h-0 flex-col gap-3"
          onClose={() => {
            if (!episodePreviewSaving) setEpisodePreview(null)
          }}
          footer={
            <>
              <Button
                type="button"
                variant="outline"
                disabled={episodePreviewSaving}
                onClick={() => {
                  if (episodePreviewEditing) {
                    setEpisodePreviewText(episodePreview.detail.text ?? "")
                    setEpisodePreviewEditing(false)
                  } else {
                    setEpisodePreview(null)
                  }
                }}
              >
                {episodePreviewEditing ? "取消编辑" : "关闭"}
              </Button>
              {episodePreviewEditing ? (
                <Button
                  type="button"
                  className="gap-1.5"
                  disabled={
                    episodePreviewSaving ||
                    episodePreviewText === (episodePreview.detail.text ?? "")
                  }
                  onClick={() => void handleSaveEpisodeSource()}
                >
                  {episodePreviewSaving ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Save className="size-4" />
                  )}
                  保存原文
                </Button>
              ) : (
                <Button
                  type="button"
                  className="gap-1.5"
                  onClick={() => setEpisodePreviewEditing(true)}
                >
                  <FileText className="size-4" />
                  编辑原文
                </Button>
              )}
            </>
          }
        >
          <div className="flex min-h-0 flex-col gap-3">
            <div className="flex shrink-0 flex-wrap gap-2">
              <Badge variant="outline" className="rounded-full text-[11px]">
                {episodePreviewCharCount.toLocaleString()} 字
              </Badge>
              <Badge variant="outline" className="rounded-full text-[11px]">
                {episodePreview.source.absoluteStart.toLocaleString()} -{" "}
                {episodePreview.source.absoluteEnd.toLocaleString()}
              </Badge>
            </div>
            {episodePreviewEditing ? (
              <textarea
                value={episodePreviewText}
                disabled={episodePreviewSaving}
                onChange={(event) => setEpisodePreviewText(event.target.value)}
                placeholder="本集原文为空。"
                className="min-h-[min(52dvh,520px)] resize-none rounded-xl border border-gray-200/70 bg-white/80 p-4 text-sm leading-6 text-gray-800 transition outline-none focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100 disabled:cursor-not-allowed disabled:opacity-70 dark:border-white/10 dark:bg-white/[0.04] dark:text-gray-100 dark:focus:border-indigo-400/60 dark:focus:ring-indigo-500/20"
              />
            ) : (
              <div className="max-h-[min(52dvh,520px)] min-h-[min(52dvh,520px)] overflow-y-auto rounded-xl border border-gray-200/70 bg-white/75 dark:border-white/10 dark:bg-white/[0.035]">
                <div className="p-4 text-sm leading-6 whitespace-pre-wrap text-gray-700 dark:text-gray-200">
                  {episodePreviewText || "本集原文为空。"}
                </div>
              </div>
            )}
          </div>
        </ModalShell>
      ) : null}
      <ReferenceAudioCropDialog
        open={narratorAudioCropOpen}
        sourceFile={narratorAudioCropSource}
        callBackend={callBackend}
        title="处理旁白参考音频"
        onClose={() => {
          setNarratorAudioCropOpen(false)
          setNarratorAudioCropSource(null)
        }}
        onConfirm={handleConfirmNarratorReferenceAudio}
      />
    </>
  )
}

function OverviewRegenerateDialog({
  excerptChars,
  loading,
  onClose,
  onConfirm,
}: {
  excerptChars: number
  loading: boolean
  onClose: () => void
  onConfirm: (excerptChars: number) => void
}) {
  const [draftExcerptChars, setDraftExcerptChars] = useState(
    normalizeOverviewExcerptChars(excerptChars)
  )
  const sourceLabel = "默认值"

  useEffect(() => {
    setDraftExcerptChars(normalizeOverviewExcerptChars(excerptChars))
  }, [excerptChars])

  return (
    <ModalShell
      title="重新生成项目概述"
      description="设置本次原文分割参数后，重新分析项目概述。"
      onClose={() => {
        if (!loading) onClose()
      }}
      footer={
        <>
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={loading}
          >
            取消
          </Button>
          <Button
            type="button"
            className="gap-1.5"
            onClick={() =>
              onConfirm(normalizeOverviewExcerptChars(draftExcerptChars))
            }
            disabled={loading}
          >
            {loading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCcw className="size-4" />
            )}
            {loading ? "正在生成" : "确认重新生成"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <section className="rounded-xl border border-gray-200/70 bg-white/70 p-4 dark:border-white/10 dark:bg-white/[0.035]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold text-gray-950 dark:text-gray-50">
                原文分割参数
              </div>
              <p className="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                默认使用 {DEFAULT_OVERVIEW_EXCERPT_CHARS} 字；本次确认后仅用于这次项目概述重新生成。
              </p>
            </div>
            <Badge variant="outline" className="rounded-full text-[11px]">
              {sourceLabel}
            </Badge>
          </div>
          <div className="mt-4 w-full">
            <OverviewExcerptCharsInput
              value={draftExcerptChars}
              onChange={setDraftExcerptChars}
            />
          </div>
        </section>
      </div>
    </ModalShell>
  )
}
