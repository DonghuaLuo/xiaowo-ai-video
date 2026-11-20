import { useEffect, useState } from "react"
import {
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  FileText,
  Landmark,
  Package,
  PawPrint,
  Plus,
  Search,
  Trash2,
  Users,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import { TooltipWrap } from "@/shared/tooltip-wrap"
import { UnifiedMediaFrame } from "@/shared/unified-media-frame"
import {
  resolveProjectThumbnailUrl,
  type ProjectThumbnailRef,
} from "@/utils/style-thumbnails"

import type { ProjectRow, ProjectStatus } from "./types"

const statusStyles: Record<ProjectStatus, string> = {
  running:
    "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-300",
  completed:
    "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300",
  draft:
    "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300",
}

function StoryboardPoster({
  accent,
  large = false,
  projectId,
  thumbnail,
}: {
  accent: string
  large?: boolean
  projectId?: string
  thumbnail?: ProjectThumbnailRef | null
}) {
  const [thumbnailSrc, setThumbnailSrc] = useState<string | null>(
    thumbnail?.url ?? null
  )

  useEffect(() => {
    let cancelled = false
    if (!projectId || !thumbnail) {
      setThumbnailSrc(null)
      return
    }
    void resolveProjectThumbnailUrl(projectId, thumbnail).then((url) => {
      if (!cancelled) setThumbnailSrc(url)
    })
    return () => {
      cancelled = true
    }
  }, [
    projectId,
    thumbnail,
    thumbnail?.path,
    thumbnail?.relativePath,
    thumbnail?.relative_path,
    thumbnail?.styleThumbnailFile,
    thumbnail?.style_thumbnail_file,
    thumbnail?.url,
  ])

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-md bg-gradient-to-br",
        large ? "h-[360px]" : "aspect-[16/10]",
        accent
      )}
    >
      {thumbnailSrc ? (
        <UnifiedMediaFrame
          src={thumbnailSrc}
          alt="项目缩略图"
          title="项目缩略图"
          className="absolute inset-0 rounded-none border-0"
          interactive={false}
          showActions={false}
        />
      ) : null}
      <div
        className={cn(
          "absolute inset-0",
          large
            ? "bg-[radial-gradient(circle_at_28%_24%,rgba(255,255,255,0.28),transparent_24%),linear-gradient(145deg,transparent,rgba(0,0,0,0.34))]"
            : "bg-[linear-gradient(145deg,transparent,rgba(0,0,0,0.28))]"
        )}
      />
      {!thumbnailSrc ? (
        <div
          className={cn(
            "absolute grid gap-2",
            large
              ? "bottom-7 left-7 w-[62%] max-w-[450px] grid-cols-3"
              : "right-4 bottom-4 left-4 grid-cols-3"
          )}
        >
          {Array.from({ length: 6 }).map((_, index) => (
            <div
              key={index}
              className="aspect-[4/3] rounded-sm border border-white/45 bg-white/25 shadow-sm backdrop-blur-sm"
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function StatusBadge({ project }: { project: ProjectRow }) {
  const Icon =
    project.statusType === "running"
      ? Clock3
      : project.statusType === "completed"
        ? CheckCircle2
        : FileText

  return (
    <Badge
      variant="outline"
      className={cn(
        "h-6 rounded-full px-2.5 text-[11px]",
        statusStyles[project.statusType]
      )}
    >
      <Icon className="size-3" />
      {project.status}
    </Badge>
  )
}

function projectTextValue(value: unknown) {
  return typeof value === "string" ? value.trim() : ""
}

function projectNumericValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value !== "string") return null
  const normalized = value.replace(/[,，]/g, "").trim()
  if (!normalized) return null
  const wanMatch = normalized.match(/([\d.]+)\s*万/)
  if (wanMatch?.[1]) {
    const parsedWan = Number(wanMatch[1])
    return Number.isFinite(parsedWan) ? parsedWan * 10000 : null
  }
  const numericMatch = normalized.match(/(\d+(?:\.\d+)?)/)
  const parsed = Number(numericMatch?.[1] ?? normalized)
  return Number.isFinite(parsed) ? parsed : null
}

function formatProjectWordCount(project: ProjectRow) {
  const formatWan = (value: number) => {
    const wan = value / 10000
    const rounded = wan >= 10 ? Math.round(wan) : Math.round(wan * 10) / 10
    return `${rounded.toLocaleString()} 万字`
  }

  const explicit = [
    project.wordCount,
    project.word_count,
    project.sourceFile?.wordCount,
    project.sourceFile?.word_count,
    project.sourceFile?.charCount,
    project.sourceFile?.char_count,
  ]
    .map(projectNumericValue)
    .find((value): value is number => typeof value === "number" && value > 0)

  if (explicit) return formatWan(explicit)

  const summary = projectTextValue(project.summary).replace(/[,，]/g, "")
  const wanMatch = summary.match(/约?\s*([\d.]+)\s*万\s*字/)
  if (wanMatch?.[1]) return `${wanMatch[1]} 万字`

  const charMatch = summary.match(/约?\s*(\d+)\s*字/)
  if (charMatch?.[1]) return formatWan(Number(charMatch[1]))

  return "未统计"
}

export function cleanProjectOverview(project: ProjectRow) {
  const analyzed =
    projectTextValue(project.overview?.excerptSummary) ||
    projectTextValue(project.overview?.excerpt_summary)
  if (analyzed) return analyzed

  const fallback = projectTextValue(project.summary)
  const cleaned = fallback
    .replace(/^已(?:导入|添加|上传)[^，,。；;\n]*(?:[，,。；;]\s*)?/, "")
    .replace(/^约?\s*[\d.,，]+\s*(?:万)?\s*字[，,。；;。\s]*/, "")
    .replace(/^概述[：:]\s*/, "")
    .trim()

  return cleaned || "等待生成项目概述。"
}

function getCurrentProjectDetails(project: ProjectRow) {
  return {
    wordCount: formatProjectWordCount(project),
    overview: cleanProjectOverview(project),
  }
}

export function CurrentProject({
  project,
  onOpen,
}: {
  project: ProjectRow
  onOpen: (projectId: string) => void
}) {
  const details = getCurrentProjectDetails(project)
  const assetStats = [
    {
      label: "角色",
      value: project.characterCount ?? 0,
      Icon: Users,
      className: "text-indigo-500 dark:text-indigo-300",
    },
    {
      label: "生物",
      value: project.creatureCount ?? 0,
      Icon: PawPrint,
      className: "text-fuchsia-500 dark:text-fuchsia-300",
    },
    {
      label: "场景",
      value: project.sceneCount ?? 0,
      Icon: Landmark,
      className: "text-sky-500 dark:text-sky-300",
    },
    {
      label: "道具",
      value: project.propCount ?? 0,
      Icon: Package,
      className: "text-emerald-500 dark:text-emerald-300",
    },
  ]

  return (
    <section aria-labelledby="current-project-heading" className="space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2
          id="current-project-heading"
          className="text-xs font-semibold tracking-[0.08em] text-gray-500 uppercase dark:text-gray-400"
        >
          当前项目
        </h2>
      </div>

      <article className="grid h-[360px] min-h-0 grid-cols-[minmax(0,1.2fr)_minmax(300px,0.8fr)] overflow-hidden rounded-lg border border-white/60 bg-white/65 shadow-sm backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.055]">
        <StoryboardPoster
          accent={project.accent}
          projectId={project.id}
          thumbnail={project.thumbnail}
          large
        />
        <div className="flex h-full min-h-0 flex-col overflow-hidden p-6">
          <div className="flex shrink-0 items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <h3 className="line-clamp-2 text-[28px] leading-tight font-semibold text-gray-950 dark:text-gray-50">
                {project.name}
              </h3>
            </div>
            <div className="shrink-0 text-right">
              <StatusBadge project={project} />
              <p className="mt-1 text-xs font-medium text-gray-500 dark:text-gray-400">
                {details.wordCount}
              </p>
            </div>
          </div>

          <div className="mt-3 grid max-w-[520px] shrink-0 grid-cols-3 gap-2">
            {assetStats.map(({ label, value, Icon, className }) => (
              <div
                key={label}
                className="flex min-w-0 items-center justify-center gap-2 rounded-md bg-indigo-50/80 px-2.5 py-2 shadow-sm shadow-indigo-950/[0.03] dark:bg-white/[0.035] dark:shadow-none"
              >
                <Icon className={cn("size-3.5 shrink-0", className)} />
                <span className="min-w-0 truncate text-xs text-gray-500 dark:text-gray-400">
                  <span className="mr-1 font-semibold text-gray-950 dark:text-gray-50">
                    {value}
                  </span>
                  {label}
                </span>
              </div>
            ))}
          </div>

          <div className="mt-4 min-h-0 max-w-[520px] flex-1 overflow-hidden">
            <p className="line-clamp-7 text-sm leading-6 text-gray-600 dark:text-gray-300">
              {details.overview}
            </p>
          </div>

          <div className="mt-4 flex shrink-0 flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
              <span>{project.episodeCount} 集</span>
              <span>·</span>
              <span>更新于 {project.updatedAt}</span>
            </div>
            <Button
              type="button"
              className="h-9 gap-2 bg-gradient-to-r from-indigo-600 via-sky-600 to-emerald-500 px-4 text-white shadow-lg shadow-indigo-500/15 hover:opacity-95"
              onClick={() => onOpen(project.id)}
            >
              继续制作
              <ArrowUpRight className="size-4" />
            </Button>
          </div>
        </div>
      </article>
    </section>
  )
}

export function ProjectCard({
  project,
  onOpen,
  onDelete,
  selecting = false,
  selected = false,
  onSelect,
}: {
  project: ProjectRow
  onOpen: (projectId: string) => void
  onDelete: (projectId: string) => void
  selecting?: boolean
  selected?: boolean
  onSelect?: (projectId: string, selected: boolean) => void
}) {
  return (
    <Card
      className={cn(
        "group gap-0 overflow-hidden border-white/60 bg-white/70 p-0 shadow-sm backdrop-blur-xl transition-all hover:-translate-y-0.5 hover:border-white hover:shadow-xl dark:border-white/10 dark:bg-white/[0.055] dark:hover:border-white/20",
        selecting && "cursor-pointer",
        selected && "border-indigo-400 ring-2 ring-indigo-400/40 dark:border-indigo-400"
      )}
      onClick={selecting ? () => onSelect?.(project.id, !selected) : undefined}
    >
      <button
        type="button"
        className="block w-full p-2.5 pb-0 text-left"
        onClick={() => {
          if (!selecting) onOpen(project.id)
        }}
        aria-label={selecting ? `${selected ? "取消选择" : "选择"}项目 ${project.name}` : `打开项目 ${project.name}`}
        aria-pressed={selecting ? selected : undefined}
      >
        <StoryboardPoster
          accent={project.accent}
          projectId={project.id}
          thumbnail={project.thumbnail}
        />
      </button>
      <div className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="truncate text-[15px] font-semibold text-gray-950 dark:text-gray-50">
              {project.name}
            </h3>
            <p className="mt-1 truncate text-xs text-gray-500 dark:text-gray-400">
              {project.episodeCount} 集 · {project.updatedAt}
            </p>
          </div>
        </div>

        <div className="mt-4 flex items-center justify-between gap-3">
          <StatusBadge project={project} />
          {!selecting ? <div className="flex items-center gap-2">
            <TooltipWrap content="删除项目">
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className="text-gray-400 hover:bg-red-50 hover:text-red-600 dark:text-gray-500 dark:hover:bg-red-950/30 dark:hover:text-red-300"
                onClick={() => onDelete(project.id)}
                aria-label={`删除项目 ${project.name}`}
              >
                <Trash2 className="size-4" />
              </Button>
            </TooltipWrap>
          </div> : null}
        </div>
      </div>
    </Card>
  )
}

export function NewProjectTile({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      className="group flex min-h-[248px] flex-col items-center justify-center rounded-2xl border border-dashed border-indigo-300/80 bg-white/45 p-6 text-center shadow-sm backdrop-blur-xl transition-all hover:-translate-y-0.5 hover:border-indigo-400 hover:bg-white/70 hover:shadow-xl dark:border-indigo-800/60 dark:bg-white/[0.035] dark:hover:border-indigo-600 dark:hover:bg-white/[0.06]"
      onClick={onClick}
    >
      <span className="flex size-12 items-center justify-center rounded-2xl bg-gradient-to-r from-indigo-600 via-sky-600 to-emerald-500 text-white shadow-lg shadow-indigo-500/15">
        <Plus className="size-5" />
      </span>
      <span className="mt-4 text-sm font-semibold text-gray-950 dark:text-gray-50">
        新建项目
      </span>
      <span className="mt-1 max-w-[220px] text-xs leading-relaxed text-gray-500 dark:text-gray-400">
        两步向导：基础信息、视觉风格。
      </span>
    </button>
  )
}

export function EmptyProjectState() {
  return (
    <div className="flex min-h-[260px] flex-col items-center justify-center rounded-2xl border border-dashed border-gray-300/80 bg-white/45 p-8 text-center dark:border-white/15 dark:bg-white/[0.035]">
      <div className="flex size-12 items-center justify-center rounded-2xl bg-indigo-500/10 text-indigo-600 dark:text-indigo-300">
        <Search className="size-5" />
      </div>
      <h3 className="mt-4 text-sm font-semibold text-gray-900 dark:text-gray-100">
        没有匹配的项目
      </h3>
      <p className="mt-1 max-w-[320px] text-xs leading-relaxed text-gray-500 dark:text-gray-400">
        换个关键词，或从创建项目开始新的故事版视频。
      </p>
    </div>
  )
}
