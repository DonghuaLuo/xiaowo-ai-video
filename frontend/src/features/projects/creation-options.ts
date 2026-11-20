import type { ContentMode } from "@/features/projects/types"
import type { StyleCategory, StyleTemplateOption } from "@/features/styles/types"
import { aspectOptions, styleCategories, styleTemplateOptions } from "@/features/styles/catalog"
import { contentModeOptions } from '@/features/settings/shared-template'

export type ProjectCreationOptions = {
  contentModes?: Array<{
    id: ContentMode
    name: string
    description: string
  }>
  aspectRatios: string[]
  styleCategories: Array<{ id: StyleCategory; label: string }>
  styleTemplates: StyleTemplateOption[]
  modelReadiness?: {
    ready?: boolean
    providerCount?: number
    missing?: string[]
    message?: string
    required?: Array<{
      key: "image" | "agent" | "text" | "video" | string
      label: string
      modelId?: string
      configured?: boolean
    }>
  }
  defaults?: {
    content_mode?: ContentMode
    aspect_ratio?: string
    source_language?: string
    style_template_id?: string
  }
}

export const MODEL_CONFIG_REQUIRED_MESSAGE = "请先在全局设置中添加供应商并配置模型"

export const fallbackCreationOptions: ProjectCreationOptions = {
  contentModes: contentModeOptions,
  aspectRatios: aspectOptions,
  styleCategories,
  styleTemplates: styleTemplateOptions,
  modelReadiness: {
    ready: false,
    providerCount: 0,
    missing: ["图片模型", "智能体模型", "文本模型", "视频模型"],
    message: MODEL_CONFIG_REQUIRED_MESSAGE,
    required: [
      { key: "image", label: "图片模型", configured: false },
      { key: "agent", label: "智能体模型", configured: false },
      { key: "text", label: "文本模型", configured: false },
      { key: "video", label: "视频模型", configured: false },
    ],
  },
  defaults: {
    content_mode: "drama",
    aspect_ratio: "16:9",
    source_language: "zh-CN",
    style_template_id: "urban_boss_romance_drama",
  },
}

export function creationModelReadinessMessage(options: ProjectCreationOptions) {
  const readiness = options.modelReadiness
  if (readiness?.ready) return ""
  return readiness?.message || MODEL_CONFIG_REQUIRED_MESSAGE
}

export function normalizeCreationOptions(raw: Partial<ProjectCreationOptions>) {
  const styleTemplates =
    raw.styleTemplates ?? fallbackCreationOptions.styleTemplates
  const rawDefaultStyleTemplateId =
    raw.defaults?.style_template_id ??
    fallbackCreationOptions.defaults?.style_template_id
  const defaultStyleTemplateId = styleTemplates.some(
    (template) => template.id === rawDefaultStyleTemplateId
  )
    ? rawDefaultStyleTemplateId
    : styleTemplates[0]?.id
  const presetStyleCategories =
    raw.styleCategories?.filter(
      (category) => category.id !== "all" && category.id !== "favorite"
    ) ??
    fallbackCreationOptions.styleCategories.filter(
      (category) => category.id !== "all" && category.id !== "favorite"
    )
  const options = {
    ...fallbackCreationOptions,
    ...raw,
    styleCategories: [
      { id: "all" as const, label: "全部" },
      ...presetStyleCategories,
      ...(styleTemplates.some((template) => template.category === "favorite")
        ? [{ id: "favorite" as const, label: "收藏风格" }]
        : []),
    ],
    styleTemplates,
    modelReadiness:
      raw.modelReadiness ?? fallbackCreationOptions.modelReadiness,
    defaults: {
      ...fallbackCreationOptions.defaults,
      ...(raw.defaults ?? {}),
      style_template_id: defaultStyleTemplateId,
    },
  }
  return options as ProjectCreationOptions
}
