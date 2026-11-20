import { useProjectSettingsLifetime } from "./use-project-settings-lifetime"
import { useCallback, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"

import { analyzeStyleImage, type InputImageFile } from "@/backend"
import {
  normalizeStyleCategory,
  normalizeStyleMode,
  normalizeActivePhaseVisualId,
  normalizePhaseVisuals,
  projectImageKey,
  resolveAppliedStyleCategory,
  styleBrowseCategoryFromApplied,
  styleFileKey,
  styleFilePayloadFromProjectImage,
  type ProjectSettingsResponse,
  type ProjectSettingsSavePayload,
  type ProjectSettingsSnapshot,
  type PhaseVisualStyle,
} from "@/features/project-settings/model"
import { styleFilePayloadFromStyleTemplate } from "@/features/styles/media"

import { nextFavoriteStyleName } from "@/features/styles/naming"
import type {
  FavoriteStyleConfirmDraft,
  StyleCategory,
  StyleFilePayload,
  StyleMode,
  StyleTemplateOption,
} from "@/features/styles/types"
import { styleTemplateOptions } from "@/features/styles/catalog"

import {
  defaultVisualTypeTag,
  isGeneralStyleTemplate,
  normalizeVisualTypeTag,
  styleTemplatePrompt,
} from "@/features/styles/general-style"

import {
  fallbackCreationOptions,
  normalizeCreationOptions,
  type ProjectCreationOptions,
} from "@/features/projects/creation-options"
import type { ProjectRow } from "@/features/projects/types"
import type { useBackend } from "@/hooks/useBackend"

import { backendFailureMessage, isBackendFailure } from "@/shared/backend-result"

import { imagePayloadPreviewSrc } from "@/shared/media"

import {
  resolveStyleTemplateThumbnailUrl,
  resolveProjectThumbnailUrl,
  type ProjectThumbnailRef,
} from "@/utils/style-thumbnails"
export type ProjectStyleSnapshot = Pick<
  ProjectSettingsSnapshot,
  | "styleMode"
  | "styleCategory"
  | "styleTemplateId"
  | "stylePrompt"
  | "styleVisualTypeTag"
  | "characterAssetPrompt"
  | "creatureAssetPrompt"
  | "phaseVisuals"
  | "activePhaseVisualId"
  | "styleFileKey"
  | "styleReference"
>
export type ProjectStyleSavePayload = Pick<
  ProjectSettingsSavePayload,
  | "styleMode"
  | "styleCategory"
  | "styleTemplateId"
  | "stylePrompt"
  | "styleAssetPrompt"
  | "styleVisualTypeTag"
  | "characterAssetPrompt"
  | "creatureAssetPrompt"
  | "phaseVisuals"
  | "activePhaseVisualId"
  | "styleFile"
>
function createPhaseVisualId() {
  return `phase-visual-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`
}
function nextPhaseVisualName(items: PhaseVisualStyle[]) {
  return `第${items.length + 1}阶段`
}
export function useProjectStyleEditor({
  backend,
  project,
  projectTitleDraft,
}: {
  backend: Pick<ReturnType<typeof useBackend>, "backendReady" | "callBackend">
  project: ProjectRow
  projectTitleDraft: string
}) {
  const { backendReady, callBackend } = backend
  const isCurrent = useProjectSettingsLifetime(project.id)
  const [catalogReadyFor, setCatalogReadyFor] = useState<string | null>(null)
  const catalogReady = catalogReadyFor === project.id
  const [projectStyleOptions, setProjectStyleOptions] = useState<ProjectCreationOptions>(
    fallbackCreationOptions
  )

  const [styleMode, setStyleMode] = useState<StyleMode>("template")

  const [styleCategory, setStyleCategory] = useState<StyleCategory>("all")

  const [styleBrowseMode, setStyleBrowseMode] = useState<StyleMode>("template")

  const [styleBrowseCategory, setStyleBrowseCategory] = useState<StyleCategory>("all")

  const [styleTemplate, setStyleTemplate] = useState(styleTemplateOptions[0]?.id ?? "")

  const [styleVisualTypeTag, setStyleVisualTypeTag] = useState(defaultVisualTypeTag())

  const [customProjectStylePrompt, setCustomProjectStylePrompt] = useState(
    "精致国风3D美型设定图风格，高端国漫与游戏CG审美，角色、场景、道具保持统一东方幻想视觉语言。"
  )

  const [customProjectCharacterStylePrompt, setCustomProjectCharacterStylePrompt] =
    useState("")

  const [customProjectCreatureStylePrompt, setCustomProjectCreatureStylePrompt] =
    useState("")

  const [phaseVisuals, setPhaseVisuals] = useState<PhaseVisualStyle[]>([])

  const [activePhaseVisualId, setActivePhaseVisualId] = useState<string | null>(null)

  const [phaseVisualEditorOpen, setPhaseVisualEditorOpen] = useState(false)

  const [editingPhaseVisualId, setEditingPhaseVisualId] = useState<string | null>(null)

  const [phaseVisualDraftName, setPhaseVisualDraftName] = useState("")

  const [phaseVisualDraftPrompt, setPhaseVisualDraftPrompt] = useState("")

  const [hasCustomProjectStyleDraft, setHasCustomProjectStyleDraft] = useState(false)

  const [customProjectStyleFile, setCustomProjectStyleFile] =
    useState<StyleFilePayload | null>(null)

  const [customProjectStyleImage, setCustomProjectStyleImage] =
    useState<ProjectThumbnailRef | null>(null)

  const [customProjectStylePreview, setCustomProjectStylePreview] = useState<
    string | null
  >(null)

  const [favoriteStyleConfirmDraft, setFavoriteStyleConfirmDraft] =
    useState<FavoriteStyleConfirmDraft | null>(null)

  const [analyzingProjectStyle, setAnalyzingProjectStyle] = useState(false)

  const isCurrentPreview = useProjectSettingsLifetime(
    JSON.stringify([
      project.id,
      styleFileKey(customProjectStyleFile),
      projectImageKey(customProjectStyleImage),
    ])
  )
  const projectStyleTemplates = projectStyleOptions.styleTemplates

  const presetStyleTemplates = useMemo(
    () => projectStyleTemplates.filter((template) => template.category !== "favorite"),
    [projectStyleTemplates]
  )

  const favoriteStyleTemplates = useMemo(
    () => projectStyleTemplates.filter((template) => template.category === "favorite"),
    [projectStyleTemplates]
  )

  const currentProjectStyleTemplate = (
    styleMode === "favorite" ? favoriteStyleTemplates : presetStyleTemplates
  ).find((template) => template.id === styleTemplate)

  const generalProjectStyleTemplate = presetStyleTemplates.find(isGeneralStyleTemplate)

  const visibleProjectStyleTemplate =
    styleBrowseMode === "favorite"
      ? favoriteStyleTemplates.find((template) => template.id === styleTemplate)
      : styleBrowseMode === "template"
        ? styleBrowseCategory === "general"
          ? generalProjectStyleTemplate
          : presetStyleTemplates.find((template) => template.id === styleTemplate)
        : currentProjectStyleTemplate

  const visibleProjectStylePrompt =
    styleBrowseMode === "custom"
      ? ""
      : styleTemplatePrompt(
          visibleProjectStyleTemplate,
          "global",
          normalizeVisualTypeTag(styleVisualTypeTag, visibleProjectStyleTemplate)
        )

  const projectPresetStyleCategories = useMemo(
    () => [
      { id: "all" as const, label: "全部" },
      ...projectStyleOptions.styleCategories.filter(
        (category) => category.id !== "all" && category.id !== "favorite"
      ),
    ],
    [projectStyleOptions.styleCategories]
  )

  useEffect(() => {
    const localPreview = imagePayloadPreviewSrc(customProjectStyleFile)
    if (localPreview) {
      setCustomProjectStylePreview(localPreview)
      return
    }
    if (!customProjectStyleImage) {
      setCustomProjectStylePreview(null)
      return
    }
    let cancelled = false
    void resolveProjectThumbnailUrl(project.id, customProjectStyleImage).then((url) => {
      if (!cancelled && isCurrentPreview()) setCustomProjectStylePreview(url)
    })
    return () => {
      cancelled = true
    }
  }, [project.id, customProjectStyleFile, customProjectStyleImage, isCurrentPreview])

  const loadProjectStyleOptions = useCallback(async () => {
    const result = await callBackend<
      ProjectCreationOptions | { success: false; message: string }
    >("get_project_creation_options", { projectId: project.id })
    if (isBackendFailure(result)) {
      throw new Error(backendFailureMessage(result, "加载风格选项失败"))
    }
    const normalized = normalizeCreationOptions(result as ProjectCreationOptions)
    if (isCurrent()) setProjectStyleOptions(normalized)
    return normalized
  }, [callBackend, project.id, isCurrent])

  useEffect(() => {
    if (!backendReady) return
    let cancelled = false
    void (async () => {
      try {
        const normalized = await loadProjectStyleOptions()
        if (cancelled || !isCurrent()) return
        setStyleTemplate((current) =>
          normalized.styleTemplates.some((template) => template.id === current)
            ? current
            : (normalized.styleTemplates.find(
                (template) => template.category !== "favorite"
              )?.id ??
              normalized.styleTemplates[0]?.id ??
              "")
        )
      } catch (error) {
        if (!cancelled && isCurrent()) {
          console.warn("加载项目设置风格选项失败，使用本地默认选项:", error)
        }
      } finally {
        if (!cancelled && isCurrent()) setCatalogReadyFor(project.id)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [backendReady, loadProjectStyleOptions])

  const changeProjectStyleCategory = (category: StyleCategory) => {
    setStyleBrowseMode("template")
    setStyleBrowseCategory(category)
  }

  const changeProjectStyleMode = (nextMode: StyleMode) => {
    setStyleBrowseMode(nextMode)
    if (nextMode === "template") {
      setStyleBrowseCategory(styleBrowseCategoryFromApplied(styleCategory))
      return
    }
    if (nextMode === "custom" && hasCustomProjectStyleDraft) {
      const hasPrompt = Boolean(customProjectStylePrompt.trim())
      if (hasPrompt) {
        setStyleMode("custom")
        setStyleCategory("all")
      }
    }
  }

  const applyProjectPresetStyle = (templateId: string) => {
    const template = presetStyleTemplates.find((item) => item.id === templateId)
    if (!template) return
    setStyleBrowseMode("template")
    setStyleBrowseCategory(template.category)
    setStyleMode("template")
    setStyleCategory(template.category)
    setStyleTemplate(template.id)
    setStyleVisualTypeTag(defaultVisualTypeTag(template))
  }

  const applyProjectFavoriteStyle = (templateId: string) => {
    const template = favoriteStyleTemplates.find((item) => item.id === templateId)
    if (!template) return
    setStyleBrowseMode("favorite")
    setStyleMode("favorite")
    setStyleCategory("favorite")
    setStyleTemplate(template.id)
  }

  const applyProjectCustomStylePrompt = (prompt: string) => {
    setStyleBrowseMode("custom")
    setStyleMode("custom")
    setStyleCategory("all")
    setHasCustomProjectStyleDraft(true)
    setCustomProjectStylePrompt(prompt)
  }

  const applyProjectCustomCharacterStylePrompt = (prompt: string) => {
    setStyleBrowseMode("custom")
    setStyleMode("custom")
    setStyleCategory("all")
    setHasCustomProjectStyleDraft(true)
    setCustomProjectCharacterStylePrompt(prompt)
  }

  const applyProjectCustomCreatureStylePrompt = (prompt: string) => {
    setStyleBrowseMode("custom")
    setStyleMode("custom")
    setStyleCategory("all")
    setHasCustomProjectStyleDraft(true)
    setCustomProjectCreatureStylePrompt(prompt)
  }

  const openAddPhaseVisual = () => {
    setEditingPhaseVisualId(null)
    setPhaseVisualDraftName(nextPhaseVisualName(phaseVisuals))
    setPhaseVisualDraftPrompt("")
    setPhaseVisualEditorOpen(true)
  }

  const openEditPhaseVisual = (item: PhaseVisualStyle) => {
    setEditingPhaseVisualId(item.id)
    setPhaseVisualDraftName(item.name)
    setPhaseVisualDraftPrompt(item.prompt)
    setPhaseVisualEditorOpen(true)
  }

  const resetPhaseVisualEditor = () => {
    setPhaseVisualEditorOpen(false)
    setEditingPhaseVisualId(null)
    setPhaseVisualDraftName("")
    setPhaseVisualDraftPrompt("")
  }

  const savePhaseVisualDraft = () => {
    const prompt = phaseVisualDraftPrompt.trim()
    if (!prompt) {
      toast.error("请先输入阶段视觉语境")
      return
    }
    const name = phaseVisualDraftName.trim()
    if (editingPhaseVisualId) {
      setPhaseVisuals((current) =>
        current.map((item) =>
          item.id === editingPhaseVisualId
            ? {
                ...item,
                name: name || item.name || "阶段视觉",
                prompt,
              }
            : item
        )
      )
      resetPhaseVisualEditor()
      return
    }
    const id = createPhaseVisualId()
    setPhaseVisuals((current) => [
      ...current,
      {
        id,
        name: name || nextPhaseVisualName(current),
        prompt,
      },
    ])
    setActivePhaseVisualId(id)
    resetPhaseVisualEditor()
  }

  const deletePhaseVisual = (itemId: string) => {
    setPhaseVisuals((current) => current.filter((item) => item.id !== itemId))
    setActivePhaseVisualId((current) => (current === itemId ? null : current))
    if (editingPhaseVisualId === itemId) {
      resetPhaseVisualEditor()
    }
  }

  const copyProjectStyleToCustom = async (
    templateOverride?: StyleTemplateOption | null
  ) => {
    const template = templateOverride ?? visibleProjectStyleTemplate
    if (!template) {
      toast.error("请先选择一个视觉风格")
      return
    }
    let preview: string | null = null
    try {
      preview = await resolveStyleTemplateThumbnailUrl(template)
    } catch (error) {
      console.warn("解析风格缩略图失败，继续复制风格引用:", error)
    }
    if (!isCurrent()) return
    const styleFile = styleFilePayloadFromStyleTemplate(template, preview)
    if (!styleFile) {
      toast.error("当前风格没有可复制的参考图")
      return
    }
    setStyleBrowseMode("custom")
    setStyleMode("custom")
    setStyleCategory("all")
    setHasCustomProjectStyleDraft(true)
    const nextVisualTypeTag = normalizeVisualTypeTag(styleVisualTypeTag, template)
    setCustomProjectStylePrompt(
      styleTemplatePrompt(template, "global", nextVisualTypeTag).trim()
    )
    setCustomProjectCharacterStylePrompt(
      styleTemplatePrompt(template, "character", nextVisualTypeTag).trim()
    )
    setCustomProjectCreatureStylePrompt(
      styleTemplatePrompt(template, "creature", nextVisualTypeTag).trim()
    )
    setCustomProjectStyleImage(null)
    setCustomProjectStyleFile(styleFile)
    setCustomProjectStylePreview(preview ?? imagePayloadPreviewSrc(styleFile))
    toast.success("已复制为自定义风格，可继续编辑")
  }

  const customProjectStylePayload =
    customProjectStyleFile ?? styleFilePayloadFromProjectImage(customProjectStyleImage)

  const customProjectStyleUploadedName =
    customProjectStylePayload?.name ?? (customProjectStylePreview ? "风格参考图" : null)

  const handleProjectStyleFileSelected = (file: InputImageFile) => {
    if (!isCurrent()) return
    setStyleBrowseMode("custom")
    setStyleMode("custom")
    setStyleCategory("all")
    setHasCustomProjectStyleDraft(true)
    setCustomProjectStyleFile(file)
  }

  const handleAnalyzeProjectStyle = async () => {
    const styleFile = customProjectStylePayload
    if (!styleFile) {
      toast.error("请先上传风格参考图")
      return
    }
    setAnalyzingProjectStyle(true)
    try {
      const result = await analyzeStyleImage(callBackend, styleFile, project.id)
      if (!isCurrent()) return
      const description = result.style_description ?? ""
      setStyleBrowseMode("custom")
      if (description.trim()) {
        setStyleMode("custom")
        setStyleCategory("all")
        setHasCustomProjectStyleDraft(true)
      }
      setCustomProjectStylePrompt(description)
      setCustomProjectCharacterStylePrompt("")
      setCustomProjectCreatureStylePrompt("")
      toast.success("风格分析完成")
    } catch (error) {
      if (!isCurrent()) return
      toast.error(error instanceof Error ? error.message : "风格分析失败")
    } finally {
      if (isCurrent()) setAnalyzingProjectStyle(false)
    }
  }

  const handleFavoriteProjectStyle = async () => {
    const prompt = customProjectStylePrompt.trim()
    const styleFile = customProjectStylePayload
    if (!styleFile) {
      toast.error("请先上传风格图片")
      return
    }
    if (!prompt) {
      toast.error("请先输入或分析风格提示词")
      return
    }
    if (!backendReady) {
      toast.error("后端未就绪，暂时无法收藏")
      return
    }
    let latestFavoriteStyles = favoriteStyleTemplates
    try {
      const latestOptions = await loadProjectStyleOptions()
      latestFavoriteStyles = latestOptions.styleTemplates.filter(
        (template) => template.category === "favorite"
      )
    } catch (error) {
      console.warn("刷新收藏风格列表失败，使用当前列表生成标题:", error)
    }
    if (!isCurrent()) return
    const defaultFavoriteStyleName =
      projectTitleDraft.trim() ||
      project.name.trim() ||
      nextFavoriteStyleName(latestFavoriteStyles)
    setFavoriteStyleConfirmDraft({
      name: defaultFavoriteStyleName,
      prompt,
      characterAssetPrompt: customProjectCharacterStylePrompt.trim(),
      creatureAssetPrompt: customProjectCreatureStylePrompt.trim(),
      styleFile,
      preview: customProjectStylePreview ?? imagePayloadPreviewSrc(styleFile),
      existingTemplates: latestFavoriteStyles,
    })
  }

  const handleFavoriteStyleSaved = async (savedTemplate: StyleTemplateOption) => {
    if (!isCurrent()) return
    setProjectStyleOptions((current) =>
      normalizeCreationOptions({
        ...current,
        styleTemplates: [
          ...current.styleTemplates.filter(
            (template) => template.id !== savedTemplate.id
          ),
          savedTemplate,
        ],
      })
    )
    try {
      await loadProjectStyleOptions()
    } catch (refreshError) {
      console.warn("刷新收藏风格列表失败:", refreshError)
    }
    if (!isCurrent()) return
    setStyleBrowseMode("favorite")
    setStyleMode("favorite")
    setStyleCategory("favorite")
    setStyleTemplate(savedTemplate.id)
    setFavoriteStyleConfirmDraft(null)
  }
  const hydrate = useCallback(
    (settings: ProjectSettingsResponse): ProjectStyleSnapshot => {
      const nextStyleMode = normalizeStyleMode(settings.styleMode ?? settings.style_mode)
      const nextStyleCategory = normalizeStyleCategory(
        settings.styleCategory ??
          settings.style_category ??
          (nextStyleMode === "favorite" ? "favorite" : "all")
      )
      const nextStyleTemplateId =
        settings.styleTemplateId ?? settings.style_template_id ?? ""
      const resolvedStyleTemplateId =
        nextStyleMode === "custom"
          ? null
          : nextStyleTemplateId ||
            projectStyleOptions.styleTemplates[0]?.id ||
            styleTemplateOptions[0]?.id ||
            ""
      const appliedStyleCategory = resolveAppliedStyleCategory(
        nextStyleMode,
        projectStyleOptions.styleTemplates,
        resolvedStyleTemplateId,
        nextStyleCategory
      )
      const nextStylePrompt = settings.stylePrompt ?? settings.style_prompt ?? ""
      const nextCharacterAssetPrompt =
        settings.characterAssetPrompt ?? settings.character_asset_prompt ?? ""
      const nextCreatureAssetPrompt =
        settings.creatureAssetPrompt ?? settings.creature_asset_prompt ?? ""
      const nextPhaseVisuals = normalizePhaseVisuals(
        settings.phaseVisuals ?? settings.phase_visuals ?? []
      )
      const nextActivePhaseVisualId = normalizeActivePhaseVisualId(
        settings.activePhaseVisualId ?? settings.active_phase_visual_id,
        nextPhaseVisuals
      )
      const appliedStyleTemplate = projectStyleOptions.styleTemplates.find(
        (template) => template.id === resolvedStyleTemplateId
      )
      const nextStyleVisualTypeTag =
        settings.styleVisualTypeTag ?? settings.style_visual_type_tag ?? ""
      setStyleMode(nextStyleMode)
      setStyleCategory(appliedStyleCategory)
      setStyleBrowseMode(nextStyleMode)
      setStyleBrowseCategory(styleBrowseCategoryFromApplied(appliedStyleCategory))
      setStyleTemplate(resolvedStyleTemplateId ?? "")
      setStyleVisualTypeTag(
        nextStyleMode === "template" && isGeneralStyleTemplate(appliedStyleTemplate)
          ? normalizeVisualTypeTag(nextStyleVisualTypeTag, appliedStyleTemplate)
          : defaultVisualTypeTag(appliedStyleTemplate)
      )
      setCustomProjectStylePrompt(nextStyleMode === "custom" ? nextStylePrompt : "")
      setCustomProjectCharacterStylePrompt(
        nextStyleMode === "custom" ? nextCharacterAssetPrompt : ""
      )
      setCustomProjectCreatureStylePrompt(
        nextStyleMode === "custom" ? nextCreatureAssetPrompt : ""
      )
      setPhaseVisuals(nextPhaseVisuals)
      setActivePhaseVisualId(nextActivePhaseVisualId)
      setPhaseVisualEditorOpen(false)
      setEditingPhaseVisualId(null)
      setPhaseVisualDraftName("")
      setPhaseVisualDraftPrompt("")
      setHasCustomProjectStyleDraft(
        nextStyleMode === "custom" && Boolean(nextStylePrompt.trim())
      )
      setCustomProjectStyleFile(null)
      const nextStyleReference =
        settings.styleReference ?? settings.style_reference ?? null
      setCustomProjectStyleImage(nextStyleReference)
      return {
        styleMode: nextStyleMode,
        styleCategory: appliedStyleCategory,
        styleTemplateId: resolvedStyleTemplateId,
        stylePrompt: nextStyleMode === "custom" ? nextStylePrompt.trim() : "",
        styleVisualTypeTag:
          nextStyleMode === "template" && isGeneralStyleTemplate(appliedStyleTemplate)
            ? normalizeVisualTypeTag(nextStyleVisualTypeTag, appliedStyleTemplate)
            : "",
        characterAssetPrompt:
          nextStyleMode === "custom" ? nextCharacterAssetPrompt.trim() : "",
        creatureAssetPrompt:
          nextStyleMode === "custom" ? nextCreatureAssetPrompt.trim() : "",
        phaseVisuals: nextPhaseVisuals,
        activePhaseVisualId: nextActivePhaseVisualId,
        styleFileKey: null,
        styleReference: nextStyleMode === "custom" ? nextStyleReference : null,
      }
    },
    [projectStyleOptions.styleTemplates]
  )

  const snapshot = useMemo<ProjectStyleSnapshot>(
    () => ({
      styleMode,
      styleCategory,
      styleTemplateId: styleMode === "custom" ? null : styleTemplate,
      stylePrompt: styleMode === "custom" ? customProjectStylePrompt.trim() : "",
      styleVisualTypeTag:
        styleMode === "template" && isGeneralStyleTemplate(currentProjectStyleTemplate)
          ? normalizeVisualTypeTag(styleVisualTypeTag, currentProjectStyleTemplate)
          : "",
      characterAssetPrompt:
        styleMode === "custom" ? customProjectCharacterStylePrompt.trim() : "",
      creatureAssetPrompt:
        styleMode === "custom" ? customProjectCreatureStylePrompt.trim() : "",
      phaseVisuals: normalizePhaseVisuals(phaseVisuals),
      activePhaseVisualId: normalizeActivePhaseVisualId(
        activePhaseVisualId,
        phaseVisuals
      ),
      styleFileKey: styleMode === "custom" ? styleFileKey(customProjectStyleFile) : null,
      styleReference: styleMode === "custom" ? customProjectStyleImage : null,
    }),
    [
      customProjectCharacterStylePrompt,
      customProjectCreatureStylePrompt,
      customProjectStyleFile,
      customProjectStyleImage,
      customProjectStylePrompt,
      currentProjectStyleTemplate,
      activePhaseVisualId,
      phaseVisuals,
      styleCategory,
      styleMode,
      styleTemplate,
      styleVisualTypeTag,
    ]
  )

  const prepareSave = (): {
    payload: ProjectStyleSavePayload
    snapshot: ProjectStyleSnapshot
  } | null => {
    const intendsCustomStyle = styleMode === "custom" || styleBrowseMode === "custom"
    const nextStyleMode = intendsCustomStyle ? "custom" : styleMode
    const selectedProjectStyleTemplate =
      nextStyleMode === "custom" ? null : currentProjectStyleTemplate
    const nextStyleVisualTypeTag =
      nextStyleMode === "template" && isGeneralStyleTemplate(selectedProjectStyleTemplate)
        ? normalizeVisualTypeTag(styleVisualTypeTag, selectedProjectStyleTemplate)
        : ""
    const nextStylePrompt =
      nextStyleMode === "custom"
        ? customProjectStylePrompt.trim()
        : styleTemplatePrompt(
            selectedProjectStyleTemplate,
            "global",
            nextStyleVisualTypeTag
          ).trim()
    const nextCharacterAssetPrompt =
      nextStyleMode === "custom"
        ? customProjectCharacterStylePrompt.trim()
        : styleTemplatePrompt(
            selectedProjectStyleTemplate,
            "character",
            nextStyleVisualTypeTag
          ).trim()
    const nextCreatureAssetPrompt =
      nextStyleMode === "custom"
        ? customProjectCreatureStylePrompt.trim()
        : styleTemplatePrompt(
            selectedProjectStyleTemplate,
            "creature",
            nextStyleVisualTypeTag
          ).trim()
    const nextCustomStyleFile = customProjectStylePayload
    if (nextStyleMode === "custom" && (!nextStylePrompt || !nextCustomStyleFile)) {
      toast.error("自定义视觉风格需要同时上传参考图并填写提示词")
      return null
    }
    const nextPhaseVisuals = normalizePhaseVisuals(phaseVisuals)
    const nextActivePhaseVisualId = normalizeActivePhaseVisualId(
      activePhaseVisualId,
      nextPhaseVisuals
    )
    const nextStyleTemplateId = nextStyleMode === "custom" ? null : styleTemplate
    return {
      payload: {
        styleMode: nextStyleMode,
        styleCategory: nextStyleMode === "custom" ? "all" : styleCategory,
        styleTemplateId: nextStyleTemplateId,
        stylePrompt: nextStylePrompt,
        styleAssetPrompt: nextStylePrompt,
        styleVisualTypeTag: nextStyleVisualTypeTag,
        characterAssetPrompt: nextCharacterAssetPrompt,
        creatureAssetPrompt: nextCreatureAssetPrompt,
        phaseVisuals: nextPhaseVisuals,
        activePhaseVisualId: nextActivePhaseVisualId,
        styleFile: nextStyleMode === "custom" ? customProjectStyleFile : null,
      },
      snapshot: {
        styleMode: nextStyleMode,
        styleCategory: nextStyleMode === "custom" ? "all" : styleCategory,
        styleTemplateId: nextStyleTemplateId,
        stylePrompt: nextStyleMode === "custom" ? nextStylePrompt : "",
        styleVisualTypeTag: nextStyleVisualTypeTag,
        characterAssetPrompt: nextStyleMode === "custom" ? nextCharacterAssetPrompt : "",
        creatureAssetPrompt: nextStyleMode === "custom" ? nextCreatureAssetPrompt : "",
        phaseVisuals: nextPhaseVisuals,
        activePhaseVisualId: nextActivePhaseVisualId,
        styleFileKey:
          nextStyleMode === "custom"
            ? (styleFileKey(customProjectStyleFile) ??
              projectImageKey(customProjectStyleImage))
            : null,
        styleReference: nextStyleMode === "custom" ? customProjectStyleImage : null,
      },
    }
  }

  const acceptSaved = (
    savedSettings: ProjectSettingsResponse | null,
    next: { payload: ProjectStyleSavePayload; snapshot: ProjectStyleSnapshot }
  ) => {
    const nextStyleReference =
      savedSettings?.styleReference ??
      savedSettings?.style_reference ??
      (next.payload.styleMode === "custom" ? customProjectStyleImage : null)
    const savedPhaseVisuals = normalizePhaseVisuals(
      savedSettings?.phaseVisuals ??
        savedSettings?.phase_visuals ??
        next.payload.phaseVisuals
    )
    const savedActivePhaseVisualId = normalizeActivePhaseVisualId(
      savedSettings?.activePhaseVisualId ??
        savedSettings?.active_phase_visual_id ??
        next.payload.activePhaseVisualId,
      savedPhaseVisuals
    )
    setCustomProjectStyleFile(null)
    setCustomProjectStyleImage(
      next.payload.styleMode === "custom" ? nextStyleReference : null
    )
    setPhaseVisuals(savedPhaseVisuals)
    setActivePhaseVisualId(savedActivePhaseVisualId)
    resetPhaseVisualEditor()
    return {
      phaseVisuals: savedPhaseVisuals,
      activePhaseVisualId: savedActivePhaseVisualId,
      styleFileKey: null,
      styleReference: next.payload.styleMode === "custom" ? nextStyleReference : null,
    }
  }

  const restore = (savedProjectSettings: ProjectStyleSnapshot) => {
    setStyleMode(savedProjectSettings.styleMode)
    setStyleCategory(savedProjectSettings.styleCategory)
    setStyleBrowseMode(savedProjectSettings.styleMode)
    setStyleBrowseCategory(
      styleBrowseCategoryFromApplied(savedProjectSettings.styleCategory)
    )
    if (savedProjectSettings.styleTemplateId) {
      setStyleTemplate(savedProjectSettings.styleTemplateId)
    }
    setStyleVisualTypeTag(savedProjectSettings.styleVisualTypeTag)
    setCustomProjectStylePrompt(savedProjectSettings.stylePrompt)
    setCustomProjectCharacterStylePrompt(savedProjectSettings.characterAssetPrompt)
    setCustomProjectCreatureStylePrompt(savedProjectSettings.creatureAssetPrompt)
    setPhaseVisuals(savedProjectSettings.phaseVisuals)
    setActivePhaseVisualId(savedProjectSettings.activePhaseVisualId)
    resetPhaseVisualEditor()
    setHasCustomProjectStyleDraft(
      savedProjectSettings.styleMode === "custom" &&
        Boolean(savedProjectSettings.stylePrompt.trim())
    )
    setCustomProjectStyleFile(null)
    setCustomProjectStyleImage(savedProjectSettings.styleReference ?? null)
  }

  useEffect(() => {
    setCustomProjectStyleFile(null)
    setCustomProjectStyleImage(null)
    setCustomProjectStylePreview(null)
    setFavoriteStyleConfirmDraft(null)
    setHasCustomProjectStyleDraft(false)
    setPhaseVisuals([])
    setActivePhaseVisualId(null)
    setPhaseVisualEditorOpen(false)
    setEditingPhaseVisualId(null)
    setPhaseVisualDraftName("")
    setPhaseVisualDraftPrompt("")
    setStyleBrowseMode("template")
    setStyleBrowseCategory("all")
    setAnalyzingProjectStyle(false)
  }, [project.id])
  return {
    catalogReady,
    styleMode,
    styleBrowseMode,
    styleBrowseCategory,
    styleTemplate,
    styleVisualTypeTag,
    customProjectStylePrompt,
    customProjectCharacterStylePrompt,
    customProjectCreatureStylePrompt,
    phaseVisuals,
    activePhaseVisualId,
    phaseVisualEditorOpen,
    editingPhaseVisualId,
    phaseVisualDraftName,
    phaseVisualDraftPrompt,
    customProjectStyleFile,
    customProjectStylePreview,
    favoriteStyleConfirmDraft,
    analyzingProjectStyle,
    setStyleMode,
    setStyleCategory,
    setStyleBrowseMode,
    setStyleTemplate,
    setStyleVisualTypeTag,
    setActivePhaseVisualId,
    setPhaseVisualDraftName,
    setPhaseVisualDraftPrompt,
    setCustomProjectStyleFile,
    setFavoriteStyleConfirmDraft,
    presetStyleTemplates,
    favoriteStyleTemplates,
    generalProjectStyleTemplate,
    visibleProjectStylePrompt,
    projectPresetStyleCategories,
    changeProjectStyleCategory,
    changeProjectStyleMode,
    applyProjectPresetStyle,
    applyProjectFavoriteStyle,
    applyProjectCustomStylePrompt,
    applyProjectCustomCharacterStylePrompt,
    applyProjectCustomCreatureStylePrompt,
    openAddPhaseVisual,
    openEditPhaseVisual,
    resetPhaseVisualEditor,
    savePhaseVisualDraft,
    deletePhaseVisual,
    copyProjectStyleToCustom,
    customProjectStyleUploadedName,
    handleProjectStyleFileSelected,
    handleAnalyzeProjectStyle,
    handleFavoriteProjectStyle,
    handleFavoriteStyleSaved,
    projectStyleOptions,
    hydrate,
    snapshot,
    prepareSave,
    acceptSaved,
    restore,
  }
}
export type ProjectStyleEditor = ReturnType<typeof useProjectStyleEditor>
