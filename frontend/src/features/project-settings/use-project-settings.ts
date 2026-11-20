import { useProjectSettingsLifetime } from "./use-project-settings-lifetime"

import { useProjectStyleEditor } from "@/features/project-settings/use-project-style-editor"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"

import { type InputImageFile } from "@/backend"
import {
  projectImageKey,
  projectSettingsSnapshotKey,
  styleFileKey,
  type ProjectSettingsResponse,
  type ProjectSettingsSavePayload,
  type ProjectSettingsSnapshot,
} from "@/features/project-settings/model"

import type { StyleFilePayload } from "@/features/styles/types"
import {
  defaultAssetExtractionTargetUnits,
  defaultEpisodeTargetUnits,
  videoRatioOptions,
} from "@/features/styles/catalog"

import type { ProjectRow } from "@/features/projects/types"
import { useBackend } from "@/hooks/useBackend"

import { backendFailureMessage, isBackendFailure } from "@/shared/backend-result"

import { imagePayloadPreviewSrc } from "@/shared/media"

import {
  resolveProjectThumbnailUrl,
  type ProjectThumbnailRef,
} from "@/utils/style-thumbnails"
export function useProjectSettings({
  project,
  onProjectSaved,
}: {
  project: ProjectRow
  onProjectSaved: (projectId: string, patch: Partial<ProjectRow>) => void
}) {
  const backend = useBackend()
  const { backendReady, callBackend } = backend
  const isCurrent = useProjectSettingsLifetime(project.id)

  const [projectTitleDraft, setProjectTitleDraft] = useState(project.name)

  const style = useProjectStyleEditor({ project, projectTitleDraft, backend })


  const [sourceLanguage, setSourceLanguage] = useState("zh-CN")

  const [episodeTargetUnits, setEpisodeTargetUnits] = useState(
    String(defaultEpisodeTargetUnits)
  )

  const [assetExtractionTargetUnits, setAssetExtractionTargetUnits] = useState(
    String(defaultAssetExtractionTargetUnits)
  )
  const [storyboardRhythmMultiplier, setStoryboardRhythmMultiplier] = useState("1.0")
  const [storyboardClipMaxSeconds, setStoryboardClipMaxSeconds] = useState("15")



  const [projectCoverImage, setProjectCoverImage] = useState<ProjectThumbnailRef | null>(
    null
  )

  const [projectCoverPreview, setProjectCoverPreview] = useState<string | null>(null)

  const [projectCoverFile, setProjectCoverFile] = useState<StyleFilePayload | null>(null)

  const [clearProjectCoverImage, setClearProjectCoverImage] = useState(false)

  const [videoGenerationDebugBlockEnabled, setVideoGenerationDebugBlockEnabled] =
    useState(false)
  const [storyboardConsistencyReportEnabled, setStoryboardConsistencyReportEnabled] = useState(true)

  const saveInFlightRef = useRef(false)
  const [savingProjectSettings, setSavingProjectSettings] = useState(false)

  const [savedProjectSettings, setSavedProjectSettings] =
    useState<ProjectSettingsSnapshot | null>(null)


  const currentProjectSettingsSnapshot = useMemo<ProjectSettingsSnapshot>(
    () => ({
      name: projectTitleDraft.trim(),
      sourceLanguage,
      episodeTargetUnits: episodeTargetUnits.trim(),
      assetExtractionTargetUnits: assetExtractionTargetUnits.trim(),
      storyboardRhythmMultiplier,
      storyboardClipMaxSeconds,
      ...style.snapshot,

      videoGenerationDebugBlockEnabled,
      storyboardConsistencyReportEnabled,

      coverKey: projectCoverFile
        ? (styleFileKey(projectCoverFile) ?? "")
        : clearProjectCoverImage
          ? ""
          : projectImageKey(projectCoverImage),
      coverImage: projectCoverImage,
    }),
    [
      clearProjectCoverImage,
      assetExtractionTargetUnits,
      storyboardRhythmMultiplier,
      storyboardClipMaxSeconds,
      episodeTargetUnits,
      projectCoverFile,
      projectCoverImage,
      projectTitleDraft,
      sourceLanguage,
      videoGenerationDebugBlockEnabled,
      storyboardConsistencyReportEnabled,
      style.snapshot,
    ]
  )

  const hasUnsavedProjectSettings =
    savedProjectSettings !== null &&
    projectSettingsSnapshotKey(savedProjectSettings) !==
      projectSettingsSnapshotKey(currentProjectSettingsSnapshot)

  const isCurrentPreview = useProjectSettingsLifetime(
    JSON.stringify([
      project.id,
      styleFileKey(projectCoverFile),
      projectImageKey(projectCoverImage),
    ])
  )
  useEffect(() => {
    const localPreview = imagePayloadPreviewSrc(projectCoverFile)
    if (localPreview) {
      setProjectCoverPreview(localPreview)
      return
    }
    if (!projectCoverImage) {
      setProjectCoverPreview(null)
      return
    }
    let cancelled = false
    void resolveProjectThumbnailUrl(project.id, projectCoverImage).then((url) => {
      if (!cancelled && isCurrentPreview()) setProjectCoverPreview(url)
    })
    return () => {
      cancelled = true
    }
  }, [project.id, projectCoverFile, projectCoverImage, isCurrentPreview])

  useEffect(() => {
    saveInFlightRef.current = false
    setSavingProjectSettings(false)
    setSavedProjectSettings(null)
    setProjectTitleDraft(project.name)

    setProjectCoverImage(null)
    setProjectCoverFile(null)
    setProjectCoverPreview(null)
    setClearProjectCoverImage(false)
    setStoryboardRhythmMultiplier("1.0")
    setStoryboardClipMaxSeconds("15")

    setVideoGenerationDebugBlockEnabled(false)
    setStoryboardConsistencyReportEnabled(true)
  }, [project.id])

  // Only activate persisted settings after the initial catalog settles. Favorites refresh choices without discarding drafts.
  useEffect(() => {
    if (!backendReady || !style.catalogReady) return
    let cancelled = false
    void (async () => {
      try {
        const rawSettings = await callBackend<ProjectSettingsResponse | { success: false; message?: string }>(
          "get_project_settings",
          { projectId: project.id }
        )
        if (cancelled || !isCurrent()) return
        if (isBackendFailure(rawSettings)) {
          throw new Error(backendFailureMessage(rawSettings, "加载项目设置失败"))
        }
        const settings = rawSettings as ProjectSettingsResponse
        const nextLanguage =
          settings.sourceLanguage ?? settings.source_language ?? "zh-CN"
        setSourceLanguage(nextLanguage)
        const nextEpisodeTargetUnits = String(
          settings.episodeTargetUnits ??
            settings.episode_target_units ??
            defaultEpisodeTargetUnits
        )
        setEpisodeTargetUnits(nextEpisodeTargetUnits)
        const nextAssetExtractionTargetUnits = String(
          settings.assetExtractionTargetUnits ??
            settings.asset_extraction_target_units ??
            defaultAssetExtractionTargetUnits
        )
        setAssetExtractionTargetUnits(nextAssetExtractionTargetUnits)
        const nextStoryboardRhythm = Number(settings.storyboardRhythmMultiplier ?? 1.0).toFixed(1)
        const nextStoryboardClipMax = String(settings.storyboardClipMaxSeconds ?? 15)
        setStoryboardRhythmMultiplier(nextStoryboardRhythm)
        setStoryboardClipMaxSeconds(nextStoryboardClipMax)
        const nextStyleSnapshot = style.hydrate(settings)

        const nextVideoGenerationDebugBlockEnabled = Boolean(
          settings.videoGenerationDebugBlockEnabled ??
          settings.video_generation_debug_block_enabled ??
          false
        )

        setVideoGenerationDebugBlockEnabled(nextVideoGenerationDebugBlockEnabled)
        const nextStoryboardConsistencyReportEnabled = (settings.storyboardConsistencyReportEnabled ?? true) === true
        setStoryboardConsistencyReportEnabled(nextStoryboardConsistencyReportEnabled)

        const nextCoverImage = settings.coverImage ?? settings.cover_image ?? null
        setProjectCoverImage(nextCoverImage)
        setProjectCoverFile(null)
        setClearProjectCoverImage(false)
        setSavedProjectSettings({
          name: project.name.trim(),
          sourceLanguage: nextLanguage,
          episodeTargetUnits: nextEpisodeTargetUnits,
          assetExtractionTargetUnits: nextAssetExtractionTargetUnits,
          storyboardRhythmMultiplier: nextStoryboardRhythm,
          storyboardClipMaxSeconds: nextStoryboardClipMax,
          ...nextStyleSnapshot,

          videoGenerationDebugBlockEnabled: nextVideoGenerationDebugBlockEnabled,
          storyboardConsistencyReportEnabled: nextStoryboardConsistencyReportEnabled,

          coverKey: projectImageKey(nextCoverImage),
          coverImage: nextCoverImage,
        })
      } catch (error) {
        if (!cancelled && isCurrent()) {
          console.warn("加载项目设置失败:", error)
          toast.error(error instanceof Error ? error.message : "加载项目设置失败")
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [
    backendReady,
    callBackend,
    project.id,
    style.catalogReady,
    isCurrent,
  ])

  const projectVideoRatioOption =
    videoRatioOptions.find((option) => option.id === project.aspectRatio) ??
    videoRatioOptions[0]

  const handleProjectCoverSelected = (file: InputImageFile) => {
    if (!isCurrent()) return
    setProjectCoverFile(file)
    setProjectCoverImage(null)
    setClearProjectCoverImage(false)
  }

  const handleClearProjectCover = () => {
    setProjectCoverImage(null)
    setProjectCoverFile(null)
    setProjectCoverPreview(null)
    setClearProjectCoverImage(true)
  }

  const buildProjectSettingsSavePayload = (): {
    payload: ProjectSettingsSavePayload
    snapshot: ProjectSettingsSnapshot
  } | null => {
    const name = projectTitleDraft.trim()
    if (!name) {
      toast.error("项目名称不能为空")
      return null
    }
    const nextEpisodeTargetUnits = Number.parseInt(episodeTargetUnits, 10)
    if (!Number.isFinite(nextEpisodeTargetUnits) || nextEpisodeTargetUnits <= 0) {
      toast.error("每集分割字数必须大于 0")
      return null
    }
    const nextAssetExtractionTargetUnits = Number.parseInt(assetExtractionTargetUnits, 10)
    if (
      !Number.isFinite(nextAssetExtractionTargetUnits) ||
      nextAssetExtractionTargetUnits <= 0
    ) {
      toast.error("资产拆分字数必须大于 0")
      return null
    }
    const styleSave = style.prepareSave()
    if (!styleSave) return null
    const clipMaxSeconds = Number(storyboardClipMaxSeconds)
    if (!Number.isInteger(clipMaxSeconds) || clipMaxSeconds < 5 || clipMaxSeconds > 30) {
      toast.error("镜头组时长上限须为 5～30 秒")
      return null
    }

    const payload: ProjectSettingsSavePayload = {
      name,
      sourceLanguage,
      episodeTargetUnits: nextEpisodeTargetUnits,
      assetExtractionTargetUnits: nextAssetExtractionTargetUnits,
      storyboardRhythmMultiplier: Number(storyboardRhythmMultiplier),
      storyboardClipMaxSeconds: clipMaxSeconds,
      ...styleSave.payload,

      videoGenerationDebugBlockEnabled,
      storyboardConsistencyReportEnabled,

      coverFile: projectCoverFile,
      clearCoverImage: clearProjectCoverImage,
    }
    return {
      payload,
      snapshot: {
        name,
        sourceLanguage,
        episodeTargetUnits: String(nextEpisodeTargetUnits),
        assetExtractionTargetUnits: String(nextAssetExtractionTargetUnits),
        storyboardRhythmMultiplier,
        storyboardClipMaxSeconds,
        ...styleSave.snapshot,

        videoGenerationDebugBlockEnabled,
        storyboardConsistencyReportEnabled,

        coverKey: projectCoverFile
          ? (styleFileKey(projectCoverFile) ?? "")
          : clearProjectCoverImage
            ? ""
            : projectImageKey(projectCoverImage),
        coverImage: projectCoverFile || clearProjectCoverImage ? null : projectCoverImage,
      },
    }
  }

  const handleSaveProjectSettings = async () => {
    if (!isCurrent() || saveInFlightRef.current) return
    const next = buildProjectSettingsSavePayload()
    if (!next) return
    if (!backendReady) {
      toast.error("后端未就绪，暂时无法保存")
      return
    }
    saveInFlightRef.current = true
    setSavingProjectSettings(true)
    try {
      const result = await callBackend<
        | { success?: true; settings?: ProjectSettingsResponse }
        | { success: false; message?: string }
      >("save_project_settings", {
        projectId: project.id,
        settings: next.payload,
      })
      if (!isCurrent()) return
      if (isBackendFailure(result)) {
        throw new Error(backendFailureMessage(result, "保存项目设置失败"))
      }
      const savedSettings =
        (result as { success?: true; settings?: ProjectSettingsResponse }).settings ??
        null
      const nextCoverImage =
        savedSettings?.coverImage ??
        savedSettings?.cover_image ??
        (next.payload.clearCoverImage ? null : projectCoverImage)
      const savedStyle = style.acceptSaved(savedSettings, next)

      const nextThumbnail = savedSettings?.thumbnail ?? nextCoverImage ?? null
      const thumbnailMeta = nextThumbnail as
        | (ProjectThumbnailRef & { source?: string | null })
        | null
      const savedSnapshot = {
        ...next.snapshot,
        ...savedStyle,

        coverKey: projectImageKey(nextCoverImage),
        coverImage: nextCoverImage,
      }
      setProjectTitleDraft(next.payload.name)
      setEpisodeTargetUnits(String(next.payload.episodeTargetUnits))
      setAssetExtractionTargetUnits(String(next.payload.assetExtractionTargetUnits))
      setStoryboardRhythmMultiplier(next.payload.storyboardRhythmMultiplier.toFixed(1))
      setStoryboardClipMaxSeconds(String(next.payload.storyboardClipMaxSeconds))

      setVideoGenerationDebugBlockEnabled(next.payload.videoGenerationDebugBlockEnabled)
      setStoryboardConsistencyReportEnabled(next.payload.storyboardConsistencyReportEnabled)

      setProjectCoverImage(nextCoverImage)
      setProjectCoverFile(null)
      setClearProjectCoverImage(false)
      setSavedProjectSettings(savedSnapshot)
      onProjectSaved(project.id, {
        name: next.payload.name,
        updatedAt: "刚刚",
        updatedAtRank: Math.floor(Date.now() / 1000),
        thumbnail: nextThumbnail,
        thumbnailUrl: thumbnailMeta?.url ?? null,
        thumbnailPath: thumbnailMeta?.path ?? null,
        thumbnailRelativePath:
          thumbnailMeta?.relativePath ?? thumbnailMeta?.relative_path ?? null,
        thumbnailStyleFile:
          thumbnailMeta?.styleThumbnailFile ??
          thumbnailMeta?.style_thumbnail_file ??
          null,
        thumbnailSource: thumbnailMeta?.source ?? null,
      })
      toast.success("项目设置已保存")
    } catch (error) {
      if (!isCurrent()) return
      console.warn("保存项目设置失败:", error)
      toast.error(error instanceof Error ? error.message : "保存项目设置失败")
    } finally {
      if (isCurrent()) {
        saveInFlightRef.current = false
        setSavingProjectSettings(false)
      }
    }
  }

  const handleDiscardProjectSettings = () => {
    if (!savedProjectSettings) return
    setProjectTitleDraft(savedProjectSettings.name)
    setSourceLanguage(savedProjectSettings.sourceLanguage)
    setEpisodeTargetUnits(savedProjectSettings.episodeTargetUnits)
    setAssetExtractionTargetUnits(savedProjectSettings.assetExtractionTargetUnits)
    setStoryboardRhythmMultiplier(savedProjectSettings.storyboardRhythmMultiplier)
    setStoryboardClipMaxSeconds(savedProjectSettings.storyboardClipMaxSeconds)
    style.restore(savedProjectSettings)

    setVideoGenerationDebugBlockEnabled(
      savedProjectSettings.videoGenerationDebugBlockEnabled
    )
    setStoryboardConsistencyReportEnabled(savedProjectSettings.storyboardConsistencyReportEnabled)

    setProjectCoverImage(savedProjectSettings.coverImage ?? null)
    setProjectCoverFile(null)
    setClearProjectCoverImage(false)
  }
  return {
    projectTitleDraft,
    setProjectTitleDraft,
    style,
    sourceLanguage,
    setSourceLanguage,
    episodeTargetUnits,
    setEpisodeTargetUnits,
    assetExtractionTargetUnits,
    setAssetExtractionTargetUnits,
    storyboardRhythmMultiplier,
    setStoryboardRhythmMultiplier,
    storyboardClipMaxSeconds,
    setStoryboardClipMaxSeconds,
    projectCoverPreview,
    videoGenerationDebugBlockEnabled,
    setVideoGenerationDebugBlockEnabled,
    storyboardConsistencyReportEnabled,
    setStoryboardConsistencyReportEnabled,
    savingProjectSettings,
    hasUnsavedProjectSettings,
    projectVideoRatioOption,
    handleProjectCoverSelected,
    handleClearProjectCover,
    handleSaveProjectSettings,
    handleDiscardProjectSettings,
  }
}
export type ProjectSettingsEditor = ReturnType<typeof useProjectSettings>
