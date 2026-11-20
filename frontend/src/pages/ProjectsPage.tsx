import { useEffect, useMemo, useState } from "react"
import { PluginSDK } from "xiaowo-sdk"
import {
  ArrowDownUp,
  ArrowRight,
  BarChart3,
  Download,
  ExternalLink,
  FileText,
  Image,
  Library,
  LineChart,
  ListChecks,
  Plus,
  Search,
  Settings,
  Trash2,
  Upload,
  Video,
  X,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { AppView, SettingsSection } from "@/navigation"
import {
  CurrentProject,
  EmptyProjectState,
  NewProjectTile,
  ProjectCard,
} from "@/features/projects/project-cards"
import type { ProjectRow, ProjectStatus } from "@/features/projects/types"
import { cn } from "@/lib/utils"
import { TooltipWrap } from "@/shared/tooltip-wrap"

type SortMode = "updated" | "running" | "completed" | "draft"

type ProjectStatItem = {
  label: string
  value: string | number
  className: string
}

const ICON_GHOST_BTN_CLS =
  "text-gray-500 hover:bg-indigo-500 hover:text-white dark:text-gray-400 dark:hover:bg-white/10 dark:hover:text-gray-100"

const TUTORIAL_VIDEO_URL =
  "https://www.bilibili.com/video/BV1TJNR62E21/?vd_source=cd85bc0c651564254dc4036d698f4a6a"

const workflowSteps = [
  {
    title: "创作剧本",
    caption: "完整剧情与资产",
    icon: FileText,
    surface: "bg-gradient-to-br from-[#3f7df4] to-[#4f46e5]",
  },
  {
    title: "分镜脚本",
    caption: "灵活规划镜头",
    icon: Library,
    surface: "bg-gradient-to-br from-[#7c3aed] to-[#5b21b6]",
  },
  {
    title: "分镜图",
    caption: "按单元生成画面",
    icon: Image,
    surface: "bg-gradient-to-br from-[#0891b2] to-[#0284c7]",
  },
  {
    title: "视频片段",
    caption: "批量生成视频",
    icon: Video,
    surface: "bg-gradient-to-br from-[#0d9488] to-[#0f766e]",
  },
  {
    title: "导出剪辑",
    caption: "导出素材供剪辑",
    icon: Download,
    surface: "bg-gradient-to-br from-[#059669] to-[#0f766e]",
  },
]

const sortLabels: Record<SortMode, string> = {
  updated: "最近更新",
  running: "创作中优先",
  completed: "已完成优先",
  draft: "未完成优先",
}

const statusSortOrder: Record<
  Exclude<SortMode, "updated">,
  Record<ProjectStatus, number>
> = {
  running: { running: 0, draft: 1, completed: 2 },
  completed: { completed: 0, running: 1, draft: 2 },
  draft: { draft: 0, running: 1, completed: 2 },
}

function TutorialLinkCard() {
  const handleOpenTutorial = async () => {
    try {
      await PluginSDK.shell.open(TUTORIAL_VIDEO_URL)
    } catch (error) {
      console.error("打开视频教程失败:", error)
    }
  }

  return (
    <button
      type="button"
      aria-label="打开视频教程"
      onClick={handleOpenTutorial}
      className="group flex w-full items-center justify-between gap-3 rounded-lg border border-sky-200/80 bg-gradient-to-r from-sky-50 via-white to-indigo-50 px-3 py-2.5 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-md dark:border-sky-900/50 dark:from-sky-950/25 dark:via-white/[0.035] dark:to-indigo-950/20"
    >
      <span className="flex min-w-0 items-center gap-2.5">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-sky-500 text-white shadow-sm shadow-sky-500/20 dark:bg-sky-500/80">
          <Video className="size-4 stroke-[1.8]" />
        </span>
        <span className="min-w-0">
          <span className="block text-xs font-semibold text-gray-950 dark:text-gray-50">
            视频教程
          </span>
          <span className="mt-0.5 block truncate text-[11px] text-gray-500 dark:text-gray-400">
            从创建项目到生成视频
          </span>
        </span>
      </span>
      <ExternalLink className="size-3.5 shrink-0 text-sky-500 transition group-hover:translate-x-0.5 group-hover:-translate-y-0.5 dark:text-sky-300" />
    </button>
  )
}

function WorkflowOverview({ stats }: { stats: ProjectStatItem[] }) {
  return (
    <section className="relative">
      <h1 className="sr-only">AI Video 项目大厅</h1>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {workflowSteps.map((step, index) => {
              const Icon = step.icon
              return (
                <div
                  key={step.title}
                  className="relative min-w-0"
                >
                  <div
                    className={cn(
                      "relative flex min-h-[116px] min-w-0 flex-col justify-between overflow-hidden rounded-lg px-3.5 py-3.5 text-white shadow-[0_10px_22px_rgba(15,23,42,0.08)] transition hover:brightness-105 dark:shadow-none",
                      step.surface
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="relative flex size-8 shrink-0 items-center justify-center rounded-md bg-white/[0.18] text-white">
                        <Icon className="size-[18px] shrink-0 stroke-[1.8]" />
                      </span>
                      <span className="relative font-mono text-[10px] font-semibold text-white/65">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                    </div>
                    <div className="relative min-w-0">
                      <h2 className="truncate text-sm font-semibold text-white">
                        {step.title}
                      </h2>
                      <p className="mt-1 truncate text-xs text-white/75">
                        {step.caption}
                      </p>
                    </div>
                  </div>
                  {index < workflowSteps.length - 1 ? (
                    <div className="absolute top-1/2 right-[-15px] z-10 hidden size-7 -translate-y-1/2 items-center justify-center rounded-full bg-white/80 text-gray-400 shadow-sm ring-1 ring-black/5 backdrop-blur xl:flex dark:bg-[#17171c]/90 dark:text-gray-500 dark:shadow-none dark:ring-white/10">
                      <ArrowRight className="size-3.5" />
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        </div>

        <div className="flex h-full min-h-0 flex-col gap-2 lg:justify-between">
          <div className="grid grid-cols-3 overflow-hidden rounded-lg border border-gray-200/70 bg-white/75 shadow-sm dark:border-white/10 dark:bg-white/[0.035]">
            {stats.map((item, index) => (
              <div
                key={item.label}
                className={cn(
                  "flex min-w-0 items-center justify-center gap-1.5 px-2 py-2 text-center",
                  index > 0 &&
                    "border-l border-gray-200/70 dark:border-white/10"
                )}
              >
                <span
                  className={cn(
                    "font-mono text-[20px] leading-none font-normal tabular-nums",
                    item.className
                  )}
                >
                  {item.value}
                </span>
                <span className="truncate text-xs font-semibold text-gray-950 dark:text-gray-50">
                  {item.label}
                </span>
              </div>
            ))}
          </div>
          <TutorialLinkCard />
        </div>
      </div>
    </section>
  )
}

function TopBar({
  backendReady,
  onSettings,
  onAssets,
  onImport,
  onExport,
  onCreateProject,
}: {
  backendReady: boolean
  onSettings: (section: SettingsSection) => void
  onAssets: () => void
  onImport: () => void
  onExport: () => void
  onCreateProject: () => void
}) {
  const handleOpenGlobalSettings = () => {
    onSettings("providers")
  }

  return (
    <div className="sticky top-0 z-20 -mx-1 rounded-xl border border-white/60 bg-white/70 p-3 shadow-sm backdrop-blur-xl dark:border-white/10 dark:bg-[#202025]/80">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex shrink-0 items-center">
          <Badge
            variant="outline"
            className={cn(
              "h-8 shrink-0 rounded-full px-3 text-[11px]",
              backendReady
                ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300"
                : "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300"
            )}
          >
            {backendReady ? "后端已就绪" : "后端连接中"}
          </Badge>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2.5">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 gap-1.5 bg-white/55 text-xs dark:bg-white/5"
            onClick={() => onSettings("quality")}
          >
            <LineChart className="size-3.5" />
            质量分析
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 gap-1.5 bg-white/55 text-xs dark:bg-white/5"
            onClick={() => onSettings("usage")}
          >
            <BarChart3 className="size-3.5" />
            用量分析
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 gap-1.5 border-indigo-200 bg-indigo-50/70 text-xs text-indigo-700 hover:bg-indigo-100 hover:text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/20 dark:text-indigo-300 dark:hover:text-indigo-200"
            onClick={onAssets}
          >
            <Library className="size-3.5" />
            全局资产
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 gap-1.5 bg-white/55 text-xs dark:bg-white/5"
            onClick={onImport}
          >
            <Upload className="size-3.5" />
            导入项目
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 gap-1.5 bg-white/55 text-xs dark:bg-white/5"
            onClick={onExport}
          >
            <Download className="size-3.5" />
            导出资产
          </Button>
          <Button
            type="button"
            size="sm"
            className="h-9 gap-1.5 bg-gradient-to-r from-indigo-600 via-sky-600 to-emerald-500 px-4 text-xs text-white shadow-lg shadow-indigo-500/15 hover:opacity-95"
            onClick={onCreateProject}
          >
            <Plus className="size-3.5" />
            创建项目
          </Button>
          <TooltipWrap content="全局设置">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className={cn(
                ICON_GHOST_BTN_CLS,
                "h-9 w-9 dark:hover:bg-white/10 dark:hover:text-gray-100"
              )}
              aria-label="打开全局设置"
              onClick={handleOpenGlobalSettings}
            >
              <Settings className="size-4" />
            </Button>
          </TooltipWrap>
        </div>
      </div>
    </div>
  )
}

export function ProjectsPage({
  backendReady,
  projects: projectRows,
  onNavigate,
  onOpenProject,
  onCreateProject,
  onImportProject,
  onExportProject,
  onRequestDeleteProject,
  onRequestDeleteProjects,
  currentProjectId,
}: {
  backendReady: boolean
  projects: ProjectRow[]
  onNavigate: (view: AppView) => void
  onOpenProject: (projectId: string) => void
  onCreateProject: () => void
  onImportProject: () => void
  onExportProject: () => void
  onRequestDeleteProject: (project: ProjectRow) => void
  onRequestDeleteProjects: (projects: ProjectRow[]) => void
  currentProjectId?: string | null
}) {
  const [query, setQuery] = useState("")
  const [sortMode, setSortMode] = useState<SortMode>("updated")
  const [selecting, setSelecting] = useState(false)
  const [selectedProjectIds, setSelectedProjectIds] = useState<Set<string>>(() => new Set())
  useEffect(() => {
    if (selecting && selectedProjectIds.size > 0 &&
      !projectRows.some((project) => selectedProjectIds.has(project.id))) {
      setSelecting(false)
      setSelectedProjectIds(new Set())
    }
  }, [projectRows, selectedProjectIds, selecting])
  const currentProject =
    projectRows.find((project) => project.id === currentProjectId) ??
    projectRows[0] ??
    null

  const projectStats = useMemo<ProjectStatItem[]>(
    () => [
      {
        label: "项目",
        value: projectRows.length,
        className: "text-gray-950 dark:text-gray-50",
      },
      {
        label: "创作中",
        value: projectRows.filter((project) => project.statusType === "running")
          .length,
        className: "text-sky-600 dark:text-sky-300",
      },
      {
        label: "已完成",
        value: projectRows.filter(
          (project) => project.statusType === "completed"
        ).length,
        className: "text-emerald-600 dark:text-emerald-300",
      },
    ],
    [projectRows]
  )
  const libraryProjects = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    const filteredRows = keyword
      ? projectRows.filter((project) => {
          return [project.name, project.status, project.summary]
            .join(" ")
            .toLowerCase()
            .includes(keyword)
        })
      : projectRows

    return filteredRows.slice().sort((left, right) => {
      if (sortMode === "updated") {
        return right.updatedAtRank - left.updatedAtRank
      }

      const order = statusSortOrder[sortMode]
      const statusRank = order[left.statusType] - order[right.statusType]
      if (statusRank !== 0) return statusRank
      return right.updatedAtRank - left.updatedAtRank
    })
  }, [query, sortMode, projectRows])

  const requestDeleteProject = (projectId: string) => {
    const project = projectRows.find((item) => item.id === projectId)
    if (project) onRequestDeleteProject(project)
  }
  const selectedProjects = libraryProjects.filter((project) => selectedProjectIds.has(project.id))
  const allVisibleSelected = libraryProjects.length > 0 &&
    libraryProjects.every((project) => selectedProjectIds.has(project.id))
  const someVisibleSelected = libraryProjects.some((project) => selectedProjectIds.has(project.id))
  const selectProject = (projectId: string, selected: boolean) => {
    setSelectedProjectIds((current) => {
      const next = new Set(current)
      if (selected) next.add(projectId)
      else next.delete(projectId)
      return next
    })
  }
  const exitSelection = () => {
    setSelecting(false)
    setSelectedProjectIds(new Set())
  }

  return (
    <main className="min-h-0 flex-1 px-5 pt-2 pb-5">
      <ScrollArea className="h-full">
        <div className="mx-auto w-full max-w-[1320px] space-y-7 pr-3">
          <TopBar
            backendReady={backendReady}
            onSettings={(section) => onNavigate({ kind: "settings", section })}
            onAssets={() =>
              onNavigate({
                kind: "assets",
                tab: "characters",
                returnTo: { kind: "projects" },
              })
            }
            onImport={onImportProject}
            onExport={onExportProject}
            onCreateProject={onCreateProject}
          />

          <WorkflowOverview stats={projectStats} />

          {currentProject ? (
            <CurrentProject project={currentProject} onOpen={onOpenProject} />
          ) : null}

          <section
            aria-labelledby="project-library-heading"
            className="space-y-3"
          >
            <div className="flex min-h-9 flex-wrap items-center gap-x-4 gap-y-3">
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-2">
                <div className="flex shrink-0 items-center gap-2">
                  <h2
                    id="project-library-heading"
                    className="text-sm font-semibold text-gray-900 dark:text-gray-100"
                  >
                    项目库
                  </h2>
                  <span
                    className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-md bg-gray-200/60 px-1.5 text-[11px] font-medium text-gray-500 tabular-nums dark:bg-white/[0.07] dark:text-gray-400"
                    title={query.trim() ? "当前筛选结果 / 全部项目" : "项目总数"}
                  >
                    {query.trim() ? `${libraryProjects.length} / ${projectRows.length}` : projectRows.length}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-1.5 border-l border-gray-200/80 pl-3 dark:border-white/10">
                  {selecting ? (
                    <>
                      <label className="flex h-8 cursor-pointer items-center gap-2 pr-2 text-xs text-gray-600 dark:text-gray-300">
                        <Checkbox
                          checked={allVisibleSelected ? true : someVisibleSelected ? "indeterminate" : false}
                          disabled={libraryProjects.length === 0}
                          onCheckedChange={(checked) => {
                            setSelectedProjectIds((current) => {
                              const next = new Set(current)
                              for (const project of libraryProjects) {
                                if (checked === true) next.add(project.id)
                                else next.delete(project.id)
                              }
                              return next
                            })
                          }}
                          aria-label="全选当前项目列表"
                        />
                        全选
                      </label>
                      <span className="mr-1 whitespace-nowrap text-xs text-gray-500 dark:text-gray-400" aria-live="polite">
                        已选 <span className="font-medium text-indigo-600 tabular-nums dark:text-indigo-300">{selectedProjects.length}</span> 项
                      </span>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-8 gap-1.5 rounded-md px-2.5 text-xs text-red-600 hover:bg-red-50 hover:text-red-700 disabled:text-gray-400 dark:text-red-400 dark:hover:bg-red-500/10 dark:hover:text-red-300 dark:disabled:text-gray-500"
                        disabled={selectedProjects.length === 0}
                        onClick={() => onRequestDeleteProjects(selectedProjects)}
                      >
                        <Trash2 className="size-3.5" />
                        删除所选
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-8 rounded-md px-2.5 text-xs text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-white/[0.06]"
                        onClick={exitSelection}
                      >
                        退出多选
                      </Button>
                    </>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-8 gap-1.5 rounded-md px-2.5 text-xs text-gray-500 hover:bg-indigo-50 hover:text-indigo-600 dark:text-gray-400 dark:hover:bg-indigo-500/10 dark:hover:text-indigo-300"
                      disabled={libraryProjects.length === 0}
                      onClick={() => setSelecting(true)}
                    >
                      <ListChecks className="size-3.5" />
                      多选
                    </Button>
                  )}
                </div>
              </div>
              <div className="ml-auto flex max-w-full items-center gap-2">
                <div className="relative w-[200px] min-w-0 lg:w-[220px]">
                  <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-gray-400" />
                  <Input
                    value={query}
                    onChange={(event) => {
                      setQuery(event.target.value)
                      setSelectedProjectIds(new Set())
                    }}
                    aria-label="搜索项目"
                    placeholder="搜索项目"
                    className="h-8 rounded-lg border-gray-200/80 bg-white/55 pr-8 pl-8 text-xs shadow-none transition-colors focus-visible:border-indigo-400 focus-visible:ring-0 dark:border-white/10 dark:bg-white/[0.04] dark:focus-visible:border-indigo-500"
                  />
                  {query.length > 0 ? (
                    <button
                      type="button"
                      className="absolute top-1/2 right-1 flex size-6 -translate-y-1/2 items-center justify-center rounded-md text-gray-400 transition-colors hover:text-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 dark:hover:text-gray-200"
                      aria-label="清空搜索"
                      onClick={() => {
                        setQuery("")
                        setSelectedProjectIds(new Set())
                      }}
                    >
                      <X className="size-3.5" />
                    </button>
                  ) : null}
                </div>
                <Select
                  value={sortMode}
                  onValueChange={(value) => setSortMode(value as SortMode)}
                >
                  <SelectTrigger
                    size="sm"
                    aria-label="项目排序"
                    className="h-8 w-[136px] rounded-lg border-gray-200/80 bg-white/55 text-xs shadow-none focus-visible:border-indigo-400 focus-visible:ring-0 dark:border-white/10 dark:bg-white/[0.04] dark:focus-visible:border-indigo-500"
                  >
                    <ArrowDownUp className="size-3.5 text-gray-500 dark:text-gray-400" />
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="rounded-lg">
                    {(
                      [
                        "updated",
                        "running",
                        "completed",
                        "draft",
                      ] satisfies SortMode[]
                    ).map((mode) => (
                      <SelectItem key={mode} value={mode}>
                        {sortLabels[mode]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {query.trim() && libraryProjects.length === 0 ? (
              <EmptyProjectState />
            ) : (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {libraryProjects.map((project) => (
                  <ProjectCard
                    key={project.id}
                    project={project}
                    onOpen={onOpenProject}
                    onDelete={requestDeleteProject}
                    selecting={selecting}
                    selected={selectedProjectIds.has(project.id)}
                    onSelect={selectProject}
                  />
                ))}
                {!selecting ? <NewProjectTile onClick={onCreateProject} /> : null}
              </div>
            )}
          </section>
        </div>
      </ScrollArea>
    </main>
  )
}
