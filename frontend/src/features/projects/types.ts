import type { ProjectThumbnailRef } from "@/utils/style-thumbnails"

export type ProjectStatus = "running" | "completed" | "draft"

export type ContentMode = "drama"

export type ProjectRow = {
  id: string
  name: string
  updatedAt: string
  updatedAtRank: number
  episodeCount: number
  episodes?: Array<{
    id: string
    title: string
    status: string
  }>
  sourceCount: number
  characterCount?: number
  creatureCount?: number
  sceneCount?: number
  propCount?: number
  status: string
  statusType: ProjectStatus
  contentMode?: ContentMode
  content_mode?: ContentMode
  aspectRatio: string
  summary: string
  author?: string | null
  sourceAuthor?: string | null
  source_author?: string | null
  wordCount?: number | string | null
  word_count?: number | string | null
  overview?: {
    excerptSummary?: string
    excerpt_summary?: string
    genreContext?: string
    genre_context?: string
    themeVisualContext?: string
    theme_visual_context?: string
    narratorVoiceDesignPrompt?: string
    narrator_voice_design_prompt?: string
    narratorReferenceAudio?: import("@/backend").MediaAsset | null
    narrator_reference_audio?: import("@/backend").MediaAsset | null
    source?: string
    modelId?: string
    modelLabel?: string
    providerId?: string
    sourceId?: string
    sourceTitle?: string
    contentPath?: string
    relativePath?: string
    excerptChars?: number
    error?: string
  } | null
  sourceFile?: {
    id?: string
    title?: string
    contentPath?: string
    relativePath?: string
    rawFilename?: string
    wordCount?: number | string
    word_count?: number | string
    charCount?: number | string
    char_count?: number | string
  } | null
  accent: string
  currentEpisodeId: string
  thumbnail?: ProjectThumbnailRef | null
  thumbnailUrl?: string | null
  thumbnailPath?: string | null
  thumbnailRelativePath?: string | null
  thumbnailStyleFile?: string | null
  thumbnailSource?: string | null
}
