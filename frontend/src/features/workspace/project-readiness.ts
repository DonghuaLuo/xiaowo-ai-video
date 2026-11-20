import type { ProjectRow } from "@/features/projects/types"

export function hasOverviewText(value: unknown) {
  return typeof value === "string" && value.trim().length > 0
}

export function projectOverviewReady(project?: ProjectRow | null) {
  const overview = project?.overview
  if (!overview || hasOverviewText(overview.error)) return false

  const hasAnalysisMetadata =
    hasOverviewText(overview.source) ||
    hasOverviewText(overview.modelId) ||
    hasOverviewText(overview.modelLabel) ||
    hasOverviewText(overview.providerId) ||
    hasOverviewText(overview.sourceId) ||
    hasOverviewText(overview.sourceTitle) ||
    hasOverviewText(overview.contentPath) ||
    hasOverviewText(overview.relativePath) ||
    typeof overview.excerptChars === "number"

  if (!hasAnalysisMetadata) return false

  const hasExcerptSummary =
    hasOverviewText(overview.excerptSummary) ||
    hasOverviewText(overview.excerpt_summary)
  const hasGenreContext =
    hasOverviewText(overview.genreContext) ||
    hasOverviewText(overview.genre_context)
  const hasThemeVisualContext =
    hasOverviewText(overview.themeVisualContext) ||
    hasOverviewText(overview.theme_visual_context)

  return hasExcerptSummary && hasGenreContext && hasThemeVisualContext
}

export function assertProjectOverviewReady(project?: ProjectRow | null) {
  if (!projectOverviewReady(project)) {
    throw new Error("小说概述分析结果不完整，请重新分析")
  }
}
