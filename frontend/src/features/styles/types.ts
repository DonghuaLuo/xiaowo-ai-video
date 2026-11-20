import type { ProjectThumbnailRef } from "@/utils/style-thumbnails"

export type FavoriteStyleDialogMode = "edit" | null

export type StyleCategory =
  | "all"
  | "general"
  | "live_action"
  | "two_d"
  | "three_d"
  | "favorite"

export type StyleFilePayload = {
  id?: string
  name: string
  originalName?: string
  mimeType: string
  size?: number
  source?: string
  path?: string
  filePath?: string
  file_path?: string
  relativePath?: string
  relative_path?: string
  file?: string
  thumbnailFile?: string
  thumbnail_file?: string
  thumbnailPath?: string
  thumbnail_path?: string
  styleThumbnailFile?: string
  style_thumbnail_file?: string
  preview?: string
  dataUrl?: string
}

export type StyleMode = "template" | "favorite" | "custom"
export type CreationStyleMode = StyleMode

export type AssetStylePrompts = {
  assetPrompt?: string
  asset_prompt?: string
  characterAssetPrompt?: string
  character_asset_prompt?: string
  creatureAssetPrompt?: string
  creature_asset_prompt?: string
}

export type VisualTypeStylePromptMap = Record<string, AssetStylePrompts>

export type StyleModeTabOption<TMode extends string> = {
  id: TMode
  label: string
}

export type StyleTemplateOption = AssetStylePrompts & {
  id: string
  name: string
  desc: string
  category: StyleCategory
  categoryLabel: string
  accent: string
  thumbnailFile?: string
  thumbnail_file?: string
  thumbnailUrl?: string | null
  thumbnailPath?: string | null
  thumbnail_path?: string | null
  filePath?: string | null
  file_path?: string | null
  path?: string | null
  relativePath?: string | null
  relative_path?: string | null
  file?: string | null
  prompt?: string
  visualTypeTags?: string[]
  visual_type_tags?: string[]
  defaultVisualTypeTag?: string
  default_visual_type_tag?: string
  visualTypeStylePrompts?: VisualTypeStylePromptMap
  visual_type_style_prompts?: VisualTypeStylePromptMap
  source?: string
  createdAt?: string
  updatedAt?: string
}

export type FavoriteStyleConfirmDraft = {
  name: string
  prompt: string
  characterAssetPrompt: string
  creatureAssetPrompt: string
  styleFile: StyleFilePayload
  preview: string | null
  existingTemplates: StyleTemplateOption[]
}

export type StyleReference = ProjectThumbnailRef
