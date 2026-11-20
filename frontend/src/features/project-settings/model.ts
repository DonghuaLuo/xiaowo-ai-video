import type { ContentMode } from "@/features/projects/types"
import type {
  StyleCategory,
  StyleFilePayload,
  StyleMode,
  StyleTemplateOption,
} from "@/features/styles/types"
import { filenameFromPath, inferImageMimeFromPath } from "@/shared/media"
import type { ProjectThumbnailRef } from "@/utils/style-thumbnails"

export type PhaseVisualStyle = {
  id: string
  name: string
  prompt: string
}

export type ProjectSettingsSavePayload = {
  name: string
  sourceLanguage: string
  episodeTargetUnits: number
  assetExtractionTargetUnits: number
  storyboardRhythmMultiplier: number
  storyboardClipMaxSeconds: number
  styleMode: StyleMode
  styleCategory: StyleCategory
  styleTemplateId: string | null
  stylePrompt: string
  styleAssetPrompt?: string
  styleVisualTypeTag?: string
  characterAssetPrompt: string
  creatureAssetPrompt: string
  phaseVisuals: PhaseVisualStyle[]
  activePhaseVisualId: string | null
  videoGenerationDebugBlockEnabled: boolean
  storyboardConsistencyReportEnabled: boolean
  styleFile: StyleFilePayload | null
  coverFile: StyleFilePayload | null
  clearCoverImage: boolean
}

export type ProjectSettingsSnapshot = {
  name: string
  sourceLanguage: string
  episodeTargetUnits: string
  assetExtractionTargetUnits: string
  storyboardRhythmMultiplier: string
  storyboardClipMaxSeconds: string
  styleMode: StyleMode
  styleCategory: StyleCategory
  styleTemplateId: string | null
  stylePrompt: string
  styleVisualTypeTag: string
  characterAssetPrompt: string
  creatureAssetPrompt: string
  phaseVisuals: PhaseVisualStyle[]
  activePhaseVisualId: string | null
  videoGenerationDebugBlockEnabled: boolean
  storyboardConsistencyReportEnabled: boolean
  styleFileKey: string | null
  coverKey: string
  styleReference?: ProjectThumbnailRef | null
  coverImage?: ProjectThumbnailRef | null
}

export type ProjectSettingsResponse = {
  contentMode?: ContentMode
  aspectRatio?: string
  sourceLanguage?: string
  source_language?: string
  episodeTargetUnits?: number
  episode_target_units?: number
  assetExtractionTargetUnits?: number
  asset_extraction_target_units?: number
  storyboardRhythmMultiplier?: number
  storyboardClipMaxSeconds?: number
  agentModelId?: string
  agentReasoningEffort?: "" | "low" | "medium" | "high" | "xhigh" | "max"
  projectConfigRevision?: number
  styleMode?: StyleMode
  style_mode?: StyleMode
  styleCategory?: StyleCategory
  style_category?: StyleCategory
  styleTemplateId?: string | null
  style_template_id?: string | null
  stylePrompt?: string
  style_prompt?: string
  styleAssetPrompt?: string
  style_asset_prompt?: string
  styleVisualTypeTag?: string
  style_visual_type_tag?: string
  characterAssetPrompt?: string
  character_asset_prompt?: string
  creatureAssetPrompt?: string
  creature_asset_prompt?: string
  phaseVisuals?: PhaseVisualStyle[]
  phase_visuals?: PhaseVisualStyle[]
  activePhaseVisualId?: string | null
  active_phase_visual_id?: string | null
  videoGenerationDebugBlockEnabled?: boolean
  storyboardConsistencyReportEnabled?: boolean
  video_generation_debug_block_enabled?: boolean
  styleReference?: ProjectThumbnailRef | null
  style_reference?: ProjectThumbnailRef | null
  coverImage?: ProjectThumbnailRef | null
  cover_image?: ProjectThumbnailRef | null
  thumbnail?: ProjectThumbnailRef | null
}

export function styleFilePayloadFromProjectImage(
  image?: ProjectThumbnailRef | null
): StyleFilePayload | null {
  if (!image) return null
  const raw = image as ProjectThumbnailRef & {
    file?: string | null
    filePath?: string | null
    file_path?: string | null
    mimeType?: string | null
    mime_type?: string | null
  }
  const path = raw.filePath ?? raw.file_path ?? raw.path ?? undefined
  const relativePath = raw.relativePath ?? raw.relative_path ?? raw.file ?? undefined
  const name =
    raw.name ??
    filenameFromPath(path) ??
    filenameFromPath(relativePath) ??
    "style-reference.png"
  const mimeType =
    raw.mimeType ??
    raw.mime_type ??
    inferImageMimeFromPath(path ?? relativePath ?? name)
  return {
    name,
    mimeType,
    path,
    filePath: path,
    file_path: path,
    relativePath,
    relative_path: relativePath,
    file: raw.file ?? relativePath,
    preview: raw.url ?? undefined,
  }
}

export function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left.localeCompare(right))
    return `{${entries
      .map(([key, item]) => `${JSON.stringify(key)}:${stableStringify(item)}`)
      .join(",")}}`
  }
  return JSON.stringify(value)
}

export function projectSettingsSnapshotKey(snapshot: ProjectSettingsSnapshot | null) {
  return snapshot ? stableStringify(snapshot) : ""
}

export function styleFileKey(file: StyleFilePayload | null) {
  if (!file) return null
  const path =
    file.filePath ??
    file.path ??
    file.relativePath ??
    file.relative_path ??
    file.file ??
    file.styleThumbnailFile ??
    file.style_thumbnail_file ??
    file.thumbnailFile ??
    file.thumbnail_file
  return path ? `${path}:${file.size ?? ""}` : `${file.name}:${file.mimeType}:${file.size ?? ""}`
}

export function normalizePhaseVisuals(value: unknown): PhaseVisualStyle[] {
  if (!Array.isArray(value)) return []
  const rows: PhaseVisualStyle[] = []
  const seen = new Set<string>()
  value.forEach((item, index) => {
    if (!item || typeof item !== "object") return
    const raw = item as {
      id?: unknown
      name?: unknown
      title?: unknown
      label?: unknown
      prompt?: unknown
      phasePrompt?: unknown
      phase_prompt?: unknown
    }
    const prompt = String(raw.prompt ?? raw.phasePrompt ?? raw.phase_prompt ?? "").trim()
    if (!prompt) return
    const fallbackId = `phase-visual-${index + 1}`
    let id = String(raw.id ?? fallbackId).trim() || fallbackId
    if (seen.has(id)) {
      id = `${id}-${index + 1}`
    }
    seen.add(id)
    rows.push({
      id,
      name:
        String(raw.name ?? raw.title ?? raw.label ?? "").trim() ||
        `第${rows.length + 1}阶段`,
      prompt,
    })
  })
  return rows
}

export function normalizeActivePhaseVisualId(
  value: unknown,
  phaseVisuals: PhaseVisualStyle[]
): string | null {
  const id = String(value ?? "").trim()
  if (!id) return null
  return phaseVisuals.some((item) => item.id === id) ? id : null
}

export function projectImageKey(image?: ProjectThumbnailRef | null) {
  if (!image) return ""
  return (
    image.url ??
    image.relativePath ??
    image.relative_path ??
    image.file ??
    image.path ??
    image.filePath ??
    image.file_path ??
    image.styleThumbnailFile ??
    image.style_thumbnail_file ??
    ""
  )
}

export function normalizeStyleMode(value?: string | null): StyleMode {
  if (value === "favorite" || value === "custom" || value === "template") {
    return value
  }
  return "template"
}

export function normalizeStyleCategory(value?: string | null): StyleCategory {
  if (
    value === "all" ||
    value === "general" ||
    value === "live_action" ||
    value === "two_d" ||
    value === "three_d" ||
    value === "favorite"
  ) {
    return value
  }
  if (
    value === "urban_live_drama" ||
    value === "costume_wuxia" ||
    value === "folk_suspense" ||
    value === "cyber_fantasy"
  ) {
    return "live_action"
  }
  if (value === "xianxia_guofeng" || value === "comic_2d") {
    return "two_d"
  }
  if (value === "scifi_mecha" || value === "guoman_3d") {
    return "three_d"
  }
  return "all"
}

export function resolveStyleCategoryFromTemplate(
  templates: StyleTemplateOption[],
  templateId: string | null | undefined,
  fallback: StyleCategory = "all"
) {
  const category = templates.find(
    (template) => template.id === templateId
  )?.category
  return normalizeStyleCategory(category ?? fallback)
}

export function resolveAppliedStyleCategory(
  mode: StyleMode,
  templates: StyleTemplateOption[],
  templateId: string | null | undefined,
  fallback: StyleCategory
) {
  if (mode === "favorite") return "favorite"
  if (mode === "template") {
    const category = resolveStyleCategoryFromTemplate(
      templates,
      templateId,
      fallback
    )
    return category === "favorite" ? "all" : category
  }
  return normalizeStyleCategory(fallback)
}

export function styleBrowseCategoryFromApplied(category: StyleCategory) {
  return category === "favorite" ? "all" : category
}

