import type { ProjectRow } from "@/features/projects/types"

export type ProjectEpisodeEntry = {
  id: string
  title: string
  status: string
}

export function episodeStatusLabel(status?: string) {
  const value = status?.trim()
  return value === "committed" ? "已保存分集原文" : value || "待处理"
}

export function buildProjectEpisodes(
  project: Pick<ProjectRow, "episodes">
): ProjectEpisodeEntry[] {
  if (project.episodes?.length) return project.episodes
  return []
}
