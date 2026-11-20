import { useCallback, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { PluginSDK } from "xiaowo-sdk"
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FolderArchive,
  Loader2,
  Upload,
} from "lucide-react"

import {
  cancelTask,
  listTasks,
  startHomeArchiveExport,
  startHomeArchiveImport,
  type HomeAssetExportScope,
  type HomeGlobalExportScope,
  type TaskRow,
} from "@/backend"
import type { ProjectRow } from "@/features/projects/types"
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import { ModalShell } from "@/shared/page-shell"
import { errMsg } from "@/shared/backend-result"

const HOME_ARCHIVE_TASK_TYPES = new Set([
  "home_archive_export",
  "home_archive_import",
])
const HOME_ARCHIVE_ACTIVE_STATUSES = new Set([
  "created",
  "queued",
  "waiting",
  "waiting_upstream",
  "ready",
  "running",
  "processing",
  "paused",
])

export function HomeArchiveTaskPanel() {
  const { backendReady, callBackend, onBackendEvent } = useBackend()
  const [tasks, setTasks] = useState<TaskRow[]>([])
  const [cancellingTaskIds, setCancellingTaskIds] = useState<Set<string>>(
    () => new Set()
  )
  const activeTasks = tasks.filter(
    (task) =>
      HOME_ARCHIVE_TASK_TYPES.has(task.type) &&
      HOME_ARCHIVE_ACTIVE_STATUSES.has(String(task.status || ""))
  )
  const hasActiveArchiveTasks = activeTasks.length > 0

  const refreshTasks = useCallback(async () => {
    if (!backendReady) return
    try {
      setTasks(
        await listTasks(callBackend, {
          types: Array.from(HOME_ARCHIVE_TASK_TYPES),
          globalOnly: true,
          limit: 20,
        })
      )
    } catch (error) {
      console.warn("加载首页导入导出任务失败:", error)
    }
  }, [backendReady, callBackend])

  useEffect(() => {
    void refreshTasks()
  }, [refreshTasks])

  useEffect(() => {
    if (!backendReady) return
    const update = (payload: unknown) => {
      const task = payload as TaskRow
      if (!task?.id || !HOME_ARCHIVE_TASK_TYPES.has(String(task.type || ""))) {
        return
      }
      setTasks((current) => [
        task,
        ...current.filter((item) => item.id !== task.id),
      ])
    }
    const unsubscribe = [
      onBackendEvent("task_created", update),
      onBackendEvent("task_progress", update),
      onBackendEvent("task_completed", update),
      onBackendEvent("task_failed", update),
      onBackendEvent("task_cancelled", update),
    ]
    return () => unsubscribe.forEach((dispose) => dispose())
  }, [backendReady, onBackendEvent])

  useEffect(() => {
    if (!backendReady) return
    const refreshVisibleTasks = () => {
      if (document.visibilityState !== "hidden") void refreshTasks()
    }
    const timer = window.setInterval(refreshVisibleTasks, hasActiveArchiveTasks ? 2000 : 30000)
    document.addEventListener("visibilitychange", refreshVisibleTasks)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener("visibilitychange", refreshVisibleTasks)
    }
  }, [backendReady, hasActiveArchiveTasks, refreshTasks])

  const handleCancel = async (taskId: string) => {
    if (!backendReady || cancellingTaskIds.has(taskId)) return
    setCancellingTaskIds((current) => new Set(current).add(taskId))
    try {
      const task = await cancelTask(callBackend, taskId)
      setTasks((current) => [
        task,
        ...current.filter((item) => item.id !== task.id),
      ])
      toast.success("任务已取消")
    } catch (error) {
      toast.error(errMsg(error, "取消任务失败"))
    } finally {
      setCancellingTaskIds((current) => {
        const next = new Set(current)
        next.delete(taskId)
        return next
      })
    }
  }

  if (!activeTasks.length) return null

  return (
    <aside
      aria-live="polite"
      className="fixed top-16 right-4 z-40 w-80 rounded-xl border border-gray-200/80 bg-white/95 p-3 shadow-xl backdrop-blur dark:border-white/10 dark:bg-[#202025]/95"
    >
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-950 dark:text-gray-50">
        <FolderArchive className="size-4 text-indigo-500" />
        首页导入导出任务
      </div>
      <div className="space-y-2">
        {activeTasks.slice(0, 4).map((task) => {
          const progress = Math.max(
            0,
            Math.min(100, Number(task.progress || 0))
          )
          const cancelling = cancellingTaskIds.has(task.id)
          return (
            <div
              key={task.id}
              className="rounded-lg border border-gray-200/70 bg-gray-50/80 p-2.5 dark:border-white/10 dark:bg-white/[0.035]"
            >
              <div className="flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-semibold text-gray-900 dark:text-gray-100">
                    {task.type === "home_archive_import"
                      ? "导入首页备份"
                      : "导出首页备份"}
                  </div>
                  <div className="mt-0.5 truncate text-[11px] text-gray-500 dark:text-gray-400">
                    {task.message || "后台处理中"}
                  </div>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 shrink-0 px-2 text-xs"
                  disabled={cancelling}
                  onClick={() => void handleCancel(task.id)}
                >
                  {cancelling ? (
                    <Loader2 className="size-3 animate-spin" />
                  ) : null}
                  取消
                </Button>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-200 dark:bg-white/10">
                <div
                  className="h-full rounded-full bg-indigo-500 transition-[width] duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </aside>
  )
}

export function ImportProjectDialog({ onClose }: { onClose: () => void }) {
  const { backendReady, callBackend } = useBackend()
  const [archivePath, setArchivePath] = useState("")
  const [conflictPolicy, setConflictPolicy] = useState<
    "rename" | "skip" | "overwrite"
  >("rename")
  const [submitting, setSubmitting] = useState(false)

  const handlePickArchive = async () => {
    try {
      const selected = await PluginSDK.dialog.open({
        title: "选择 ai-video 首页导出包",
        multiple: false,
        directory: false,
        filters: [{ name: "ZIP", extensions: ["zip"] }],
      })
      const path = Array.isArray(selected) ? selected[0] : selected
      if (typeof path === "string" && path.trim()) setArchivePath(path.trim())
    } catch (error) {
      toast.error(errMsg(error, "选择压缩包失败"))
    }
  }

  const handleImport = async () => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    if (!archivePath) {
      toast.info("请先选择首页导出的 ZIP 压缩包")
      return
    }
    setSubmitting(true)
    try {
      await startHomeArchiveImport(callBackend, { archivePath, conflictPolicy })
      toast.success("导入任务已创建，可继续使用界面")
      onClose()
    } catch (error) {
      toast.error(errMsg(error, "创建导入任务失败"))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ModalShell
      title="导入首页备份"
      description="导入首页导出的 ZIP；剪映草稿不属于此处导入范围。"
      onClose={onClose}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button
            onClick={() => void handleImport()}
            disabled={submitting || !archivePath}
          >
            {submitting ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Upload className="size-4" />
            )}
            {submitting ? "正在创建任务" : "开始导入"}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <button
          type="button"
          className="w-full rounded-xl border border-dashed border-indigo-300 bg-indigo-50/60 p-8 text-center transition-colors hover:bg-indigo-50 dark:border-indigo-900/60 dark:bg-indigo-950/20 dark:hover:bg-indigo-950/30"
          onClick={() => void handlePickArchive()}
          disabled={submitting}
        >
          <FolderArchive className="mx-auto size-6 text-indigo-600 dark:text-indigo-300" />
          <p className="mt-3 text-sm font-semibold text-gray-950 dark:text-gray-50">
            {archivePath ? "已选择压缩包" : "选择 ZIP 压缩包"}
          </p>
          <p className="mt-1 text-xs break-all text-gray-500 dark:text-gray-400">
            {archivePath ||
              "前端只传递文件路径，由 Python 后台解压并恢复数据。"}
          </p>
        </button>
        <div>
          <div className="mb-2 text-xs font-medium text-gray-500 dark:text-gray-400">
            项目重复策略（按项目 ID 判断）
          </div>
          <div className="grid gap-2 md:grid-cols-3">
            {[
              ["skip", "跳过重复"],
              ["rename", "重命名导入"],
              ["overwrite", "覆盖重复"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={cn(
                  "rounded-lg border px-3 py-2 text-xs font-semibold",
                  conflictPolicy === value
                    ? "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
                    : "border-gray-200/70 bg-white/70 text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400"
                )}
                onClick={() =>
                  setConflictPolicy(value as "rename" | "skip" | "overwrite")
                }
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50/70 px-3 py-2 text-xs text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/20 dark:text-emerald-300">
          <CheckCircle2 className="mt-0.5 size-3.5 shrink-0" />
          ZIP
          路径校验、解压、项目移动和全局设置合并均在后台线程执行，不阻塞界面。
        </div>
      </div>
    </ModalShell>
  )
}

export function ExportProjectDialog({
  projects,
  onClose,
}: {
  projects: ProjectRow[]
  onClose: () => void
}) {
  const { backendReady, callBackend } = useBackend()
  const [selectedProjectIds, setSelectedProjectIds] = useState<Set<string>>(
    () => new Set(projects.map((project) => project.id))
  )
  const [selectedScopes, setSelectedScopes] = useState<
    Set<HomeGlobalExportScope>
  >(
    () =>
      new Set([
        "providers",
        "models",
        "scriptAdaptationTemplates",
        "directorRules",
        "textReplacementRules",
        "storyboardTemplates",
      ])
  )
  const [selectedAssetScopes, setSelectedAssetScopes] = useState<
    Set<HomeAssetExportScope>
  >(() => new Set(["characters", "creatures", "scenes", "props", "styles"]))
  const [submitting, setSubmitting] = useState(false)
  const allProjectsSelected = useMemo(
    () =>
      projects.length > 0 &&
      projects.every((project) => selectedProjectIds.has(project.id)),
    [projects, selectedProjectIds]
  )

  const toggleProject = (projectId: string) => {
    setSelectedProjectIds((current) => {
      const next = new Set(current)
      if (next.has(projectId)) next.delete(projectId)
      else next.add(projectId)
      return next
    })
  }

  const toggleScope = (scope: HomeGlobalExportScope) => {
    setSelectedScopes((current) => {
      const next = new Set(current)
      if (next.has(scope)) next.delete(scope)
      else next.add(scope)
      return next
    })
  }

  const toggleAssetScope = (scope: HomeAssetExportScope) => {
    setSelectedAssetScopes((current) => {
      const next = new Set(current)
      if (next.has(scope)) next.delete(scope)
      else next.add(scope)
      return next
    })
  }

  const handleExport = async () => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    if (
      !selectedProjectIds.size &&
      !selectedScopes.size &&
      !selectedAssetScopes.size
    ) {
      toast.info("请至少选择一个项目、一项全局设置或一项全局资产内容")
      return
    }
    try {
      const date = new Date().toISOString().slice(0, 10)
      const selectedPath = await PluginSDK.dialog.save({
        title: "导出 ai-video 首页备份",
        defaultPath: `ai-video-backup-${date}.zip`,
        filters: [{ name: "ZIP", extensions: ["zip"] }],
      })
      if (typeof selectedPath !== "string" || !selectedPath.trim()) return
      setSubmitting(true)
      await startHomeArchiveExport(callBackend, {
        projectIds: Array.from(selectedProjectIds),
        globalScopes: Array.from(selectedScopes),
        assetScopes: Array.from(selectedAssetScopes),
        exportPath: selectedPath.trim(),
      })
      toast.success("导出任务已创建，可继续使用界面")
      onClose()
    } catch (error) {
      toast.error(errMsg(error, "创建导出任务失败"))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ModalShell
      title="导出首页项目、全局设置与全局资产"
      description="选择项目、全局配置和全局资产内容，后台打包成可再次导入 ai-video 的 ZIP。"
      className="!max-h-[90dvh]"
      bodyClassName="flex h-full min-h-0 flex-col overflow-hidden"
      onClose={onClose}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button onClick={() => void handleExport()} disabled={submitting}>
            {submitting ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Download className="size-4" />
            )}
            {submitting ? "正在创建任务" : "选择路径并导出"}
          </Button>
        </>
      }
    >
      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-hidden">
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="mb-2 flex items-center justify-between gap-3">
            <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">
              项目导出
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={() =>
                setSelectedProjectIds(
                  allProjectsSelected
                    ? new Set()
                    : new Set(projects.map((project) => project.id))
                )
              }
            >
              {allProjectsSelected ? "取消全选" : "全选"}
            </Button>
          </div>
          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
            {projects.length ? (
              projects.map((project) => (
                <label
                  key={project.id}
                  className="flex items-center gap-3 rounded-lg border border-gray-200/70 bg-white/70 px-3 py-2 text-sm dark:border-white/10 dark:bg-white/[0.035]"
                >
                  <input
                    type="checkbox"
                    checked={selectedProjectIds.has(project.id)}
                    onChange={() => toggleProject(project.id)}
                  />
                  <span className="min-w-0 flex-1 truncate font-medium">
                    {project.name}
                  </span>
                  <span className="text-xs text-gray-400">
                    {project.episodeCount} 集
                  </span>
                </label>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-gray-300 p-4 text-center text-xs text-gray-500 dark:border-white/10 dark:text-gray-400">
                暂无项目
              </div>
            )}
          </div>
        </div>
        <div className="shrink-0">
          <div className="mb-2 text-xs font-semibold text-gray-700 dark:text-gray-300">
            全局设置导出
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {[
              ["providers", "供应商配置", "完整配置，包含已保存密钥"],
              ["models", "模型配置", "当前模型选择与参数"],
              ["scriptAdaptationTemplates", "片段剧本策略", "仅自定义策略"],
              ["directorRules", "导演规则", "仅用户修改的规则"],
              ["textReplacementRules", "提示词替换规则", "仅自定义修改或新增规则"],
              ["storyboardTemplates", "故事版模板", "仅自定义模板"],
            ].map(([scope, label, description]) => (
              <label
                key={scope}
                className="flex items-start gap-3 rounded-xl border border-gray-200/70 bg-white/70 p-3 text-sm dark:border-white/10 dark:bg-white/[0.035]"
              >
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={selectedScopes.has(scope as HomeGlobalExportScope)}
                  onChange={() => toggleScope(scope as HomeGlobalExportScope)}
                />
                <span>
                  <span className="block font-semibold text-gray-950 dark:text-gray-50">
                    {label}
                  </span>
                  <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
                    {description}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </div>
        <div className="shrink-0">
          <div className="mb-2 flex items-center justify-between gap-3">
            <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">
              全局资产导出
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={() => {
                const allAssetScopes: HomeAssetExportScope[] = [
                  "characters",
                  "creatures",
                  "scenes",
                  "props",
                  "styles",
                ]
                const allSelected = allAssetScopes.every((scope) =>
                  selectedAssetScopes.has(scope)
                )
                setSelectedAssetScopes(
                  new Set(allSelected ? [] : allAssetScopes)
                )
              }}
            >
              {(
                [
                  "characters",
                  "creatures",
                  "scenes",
                  "props",
                  "styles",
                ] as HomeAssetExportScope[]
              ).every((scope) => selectedAssetScopes.has(scope))
                ? "取消全选"
                : "全选"}
            </Button>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {[
              ["characters", "角色", "全局角色资产及角色设计图"],
              ["creatures", "生物", "全局生物资产及生物设计图"],
              ["scenes", "场景", "全局场景资产及场景参考图"],
              ["props", "道具", "全局道具资产及道具参考图"],
              ["styles", "收藏风格", "全局收藏风格及风格参考图"],
            ].map(([scope, label, description]) => (
              <label
                key={scope}
                className="flex items-start gap-3 rounded-xl border border-gray-200/70 bg-white/70 p-3 text-sm dark:border-white/10 dark:bg-white/[0.035]"
              >
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={selectedAssetScopes.has(
                    scope as HomeAssetExportScope
                  )}
                  onChange={() =>
                    toggleAssetScope(scope as HomeAssetExportScope)
                  }
                />
                <span>
                  <span className="block font-semibold text-gray-950 dark:text-gray-50">
                    {label}
                  </span>
                  <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
                    {description}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </div>
      </div>
    </ModalShell>
  )
}

export function DeleteProjectDialog({
  projects,
  deleting,
  onClose,
  onConfirm,
}: {
  projects: ProjectRow[]
  deleting: boolean
  onClose: () => void
  onConfirm: () => void | Promise<void>
}) {
  return (
    <AlertDialog
      open={projects.length > 0}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !deleting) onClose()
      }}
    >
      <AlertDialogContent className="border-gray-200/70 bg-white text-gray-950 dark:border-white/10 dark:bg-[#202025] dark:text-gray-50">
        <AlertDialogHeader>
          <AlertDialogTitle>{projects.length > 1 ? "批量删除项目" : "删除项目"}</AlertDialogTitle>
          <AlertDialogDescription className="text-gray-500 dark:text-gray-400">
            删除将移除整个项目的分镜、角色、场景以及所有视频。此操作不可撤销。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50/80 p-4 text-red-800 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-200">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <div className="min-w-0 text-sm leading-relaxed">
            <p className="font-medium">
              {projects.length === 1
                ? "确认彻底删除该项目？"
                : `确认彻底删除以下 ${projects.length} 个项目？`}
            </p>
            <ul className="mt-2 max-h-32 space-y-1 overflow-y-auto text-red-700/85 dark:text-red-200/85">
              {projects.map((project) => (
                <li key={project.id} className="break-all">{project.name}</li>
              ))}
            </ul>
          </div>
        </div>
        <AlertDialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={deleting}
            onClick={onClose}
          >
            取消
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={deleting || projects.length === 0}
            onClick={() => void onConfirm()}
          >
            {deleting ? (
              <Loader2
                className="h-3.5 w-3.5 motion-safe:animate-spin"
                aria-hidden
              />
            ) : null}
            {deleting ? "删除中" : projects.length === 1 ? "确认删除" : `确认删除 ${projects.length} 个项目`}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
