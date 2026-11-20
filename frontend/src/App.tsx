import { useCallback, useEffect, useRef, useState } from "react"
import { PluginSDK } from "xiaowo-sdk"
import { toast } from "sonner"

import { TitleBar } from "@/components/TitleBar"
import { useBackend } from "@/hooks/useBackend"
import { syncAssetRowsCacheFromBackendEvent } from "@/features/assets/asset-cache"
import { CreateProjectWizard } from "@/features/projects/creation-wizard"
import {
  DeleteProjectDialog,
  ExportProjectDialog,
  HomeArchiveTaskPanel,
  ImportProjectDialog,
} from "@/features/projects/lobby-dialogs"
import type { ProjectRow } from "@/features/projects/types"
import { ProjectsPage } from "@/pages/ProjectsPage"
import { QualitySettings, UsageSettings } from "@/features/settings/insights"
import { ProviderSettings } from "@/features/settings/providers"
import { DirectorRuleSettings } from "@/features/settings/director-rules"
import {ScriptAdaptationTemplateSettings} from '@/features/settings/script-adaptation-settings'
import {TextReplacementRuleSettings} from '@/features/settings/text-replacement-settings'
import { StoryboardTemplateSettings } from "@/features/settings/storyboard-templates"
import { ModelConfigSettings } from "@/features/settings/model-config"
import { NotFoundPage } from "@/pages/NotFoundPage"
import { AssetLibraryPage } from "@/pages/AssetLibraryPage"
import {
  markReloadSessionViewRestoreIntent,
  persistCurrentProjectId,
  persistReloadSessionView,
  readReloadSessionView,
  readPersistedCurrentProjectId,
  type AppView,
  type AssetReturnTarget,
} from "@/navigation"
import { SettingsPage } from "@/pages/SettingsPage"
import { ProjectSettingsPage } from "@/pages/ProjectSettingsPage"
import { WorkspacePage } from "@/pages/WorkspacePage"
import { backendFailureMessage, isBackendFailure } from "@/shared/backend-result"

type LobbyDialog = "create" | "import" | "export" | null

const LOCAL_SOURCE_PROJECT_CHANGE_ACTIONS = new Set([
  "novel_source_files_appended",
  "source_created",
  "source_deleted",
  "source_segment_deleted",
  "source_text_saved",
  "source_total_restored",
])

const LOCAL_ASSET_PROJECT_CHANGE_ACTIONS = new Set([
  "asset_created",
  "asset_updated",
  "asset_deleted",
  "asset_upserted",
  "asset_batch_saved",
  "latest_asset_range_deleted",
  "asset_range_analysis_retry_requested",
  "asset_media_generated",
  "asset_media_version_activated",
  "asset_media_version_updated",
  "asset_media_version_deleted",
  "project_assets_deleted_all",
])

const LOCAL_ASSET_SPLIT_PROJECT_CHANGE_ACTIONS = new Set([
  "asset_batch_saved",
  "latest_asset_range_deleted",
  "asset_range_analysis_retry_requested",
  "project_assets_deleted_all",
  "agent_split_completed",
])

const LOCAL_CANVAS_PROJECT_CHANGE_ACTIONS = new Set([
  "canvas_result_committed",
  "workflow_input_linked",
  "workflow_input_unlinked",
  "workflow_reference_usage_updated",
  "workflow_media_imported",
  "workflow_asset_nodes_added",
  "workflow_task_card_created",
  "workflow_item_upserted",
  "workflow_route_updated",
  "workflow_item_deleted",
  "workflow_node_layout_updated",
  "workflow_node_inline_saved",
  "node_edit_history_restored",
  "node_edit_history_deleted",
  "workflow_node_generated",
  "workflow_cinematic_script_generated",
  "canvas_asset_images_resolved",
  "workflow_batch_generated",
  "workflow_variant_selected",
  "workflow_node_preflight_checked",
  "storyboard_image_requested",
  "video_task_card_ready",
  "storyboard_image_edited",
  "storyboard_image_generated",
  "storyboard_image_edit_completed",
  "storyboard_image_edit_failed",
  "storyboard_result_version_activated",
  "storyboard_version_deleted",
  "visual_handoff_image_generated",
  "visual_handoff_cross_episode_imported",
  "visual_handoff_cross_episode_linked",
  "storyboard_video_requested",
  "storyboard_video_generated",
  "route_video_requested",
  "route_video_generated",
  "variant_quality_result_saved",
  "variant_quality_auto_reviewed",
  "shot_prompt_patched",
  "episode_production_status_updated",
  "agent_split_completed",
])

const LOCAL_CANVAS_CHANGED_RESOURCES = new Set([
  "canvas_document",
  "canvas_documents",
  "canvas_node",
  "canvas_nodes",
  "canvas_edge",
  "canvas_edges",
  "canvas_route",
  "canvas_routes",
  "canvas_work_chain",
  "canvas_work_chains",
  "canvas_version",
  "canvas_versions",
  "canvas_task",
  "canvas_tasks",
  "canvas_projection",
  "canvas_projections",
  "episode_production_status",
  "variant_quality_results",
  "visual_handoff",
  "node_edit_history",
])

const PROJECT_REFRESH_CHANGED_RESOURCES = new Set([
  "project",
  "episode",
  "episodes",
  "storyboard",
  "workChainPlan",
  "work_chain_plan",
  "sourceCoverage",
  "source_coverage",
  "source",
  "sources",
  "sourceText",
  "source_text",
  "source_splits",
  "episodeSource",
  "episode_source",
])

const LOCAL_ASSET_SPLIT_PROJECT_REFRESH_RESOURCES = new Set([
  "assetRanges",
  "asset_ranges",
  "sourceCoverage",
  "source_coverage",
])

function eventChangedResources(payload: unknown): string[] {
  const record = payload as any
  const resources: unknown[] = Array.isArray(record?.changedResources)
    ? record.changedResources
    : Array.isArray(record?.changed_resources)
      ? record.changed_resources
      : []
  return resources.map((item: unknown) => String(item || ""))
}

function eventProjectRefreshResources(payload: unknown) {
  return eventChangedResources(payload).filter((resource) =>
    PROJECT_REFRESH_CHANGED_RESOURCES.has(resource)
  )
}

function areAssetSplitProjectRefreshResources(resources: string[]) {
  return (
    resources.length > 0 &&
    resources.every((resource) =>
      LOCAL_ASSET_SPLIT_PROJECT_REFRESH_RESOURCES.has(resource)
    )
  )
}

function eventProjectId(payload: unknown) {
  const record = payload as any
  return (
    String(
      record?.projectId ??
        record?.project_id ??
        record?.project?.id ??
        record?.project?.project_id ??
        ""
    ).trim() || null
  )
}

function isLocalCanvasProjectChange(payload: unknown, action: string) {
  const resources = eventChangedResources(payload)
  const projectLevelResources = eventProjectRefreshResources(payload)
  const hasProjectLevelResource = projectLevelResources.length > 0
  const hasAssetSplitProjectRefreshResources =
    areAssetSplitProjectRefreshResources(projectLevelResources)
  const hasCanvasResource = resources.some((resource) =>
    LOCAL_CANVAS_CHANGED_RESOURCES.has(resource)
  )
  if (LOCAL_CANVAS_PROJECT_CHANGE_ACTIONS.has(action)) {
    return !hasProjectLevelResource || hasAssetSplitProjectRefreshResources
  }
  if (hasProjectLevelResource) return false
  return hasCanvasResource
}

function isLocalAssetProjectChange(payload: unknown, action: string) {
  if (
    !LOCAL_ASSET_PROJECT_CHANGE_ACTIONS.has(action) &&
    !LOCAL_ASSET_SPLIT_PROJECT_CHANGE_ACTIONS.has(action)
  ) {
    return false
  }
  const resources = eventChangedResources(payload)
  const projectLevelResources = eventProjectRefreshResources(payload)
  const hasProjectLevelResource = projectLevelResources.length > 0
  const hasAssetSplitProjectRefreshResources =
    areAssetSplitProjectRefreshResources(projectLevelResources)
  const hasCanvasResource = resources.some((resource) =>
    LOCAL_CANVAS_CHANGED_RESOURCES.has(resource)
  )
  if (hasProjectLevelResource && !hasCanvasResource) {
    return hasAssetSplitProjectRefreshResources
  }
  return true
}

function findProject(projectRows: ProjectRow[], projectId: string) {
  return projectRows.find((project) => project.id === projectId) ?? null
}

function resolveAssetReturnTarget(
  returnTo: AssetReturnTarget | undefined,
  projectRows: ProjectRow[]
): AssetReturnTarget {
  if (!returnTo || returnTo.kind === "projects") {
    return { kind: "projects" }
  }
  if (projectRows.length === 0) {
    return returnTo
  }
  return projectRows.some((project) => project.id === returnTo.projectId)
    ? returnTo
    : { kind: "projects" }
}

function ProjectLoadingPage() {
  return (
    <main className="flex min-h-0 flex-1 items-center justify-center px-6 text-sm text-gray-500 dark:text-gray-400">
      正在加载项目...
    </main>
  )
}

export default function App() {
  const { backendReady, callBackend, onBackendEvent } = useBackend()
  const [view, setView] = useState<AppView>(() => readReloadSessionView() ?? { kind: "projects" })
  const [projectRows, setProjectRows] = useState<ProjectRow[]>([])
  const [projectsLoaded, setProjectsLoaded] = useState(false)
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(() =>
    readPersistedCurrentProjectId()
  )
  const [lobbyDialog, setLobbyDialog] = useState<LobbyDialog>(null)
  const [deleteProjectTargets, setDeleteProjectTargets] =
    useState<ProjectRow[]>([])
  const [deletingProject, setDeletingProject] = useState(false)
  const projectRowsStaleRef = useRef(false)

  useEffect(() => {
    persistCurrentProjectId(currentProjectId)
    if (!backendReady || !projectsLoaded) return
    void callBackend<{ success?: boolean; message?: string }>("set_current_project", {
      projectId: currentProjectId ?? null,
    })
      .then((result) => {
        if (isBackendFailure(result)) {
          throw new Error(result.message || "同步当前项目失败")
        }
      })
      .catch((error) => {
        console.warn("同步当前项目失败:", error)
      })
  }, [backendReady, callBackend, currentProjectId, projectsLoaded])

  useEffect(() => {
    if (!backendReady) return
    void callBackend("initialize_plugin").catch(() => undefined)
  }, [backendReady, callBackend])

  useEffect(() => {
    persistReloadSessionView(view)
  }, [view])

  useEffect(() => {
    const markReloadIntent = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase()
      if (key === "f5" || ((event.ctrlKey || event.metaKey) && key === "r")) {
        markReloadSessionViewRestoreIntent()
      }
    }
    window.addEventListener("keydown", markReloadIntent)
    return () => window.removeEventListener("keydown", markReloadIntent)
  }, [])

  const refreshProjects = useCallback(async () => {
    if (!backendReady) return
    try {
      const result = await callBackend<
        | {
            projects: ProjectRow[]
            stats?: { total: number; running: number; completed: number }
            featuredProjectId?: string | null
          }
        | { success: false; message: string }
      >("get_dashboard", { check_extmodel: true })
      if (isBackendFailure(result)) {
        throw new Error(result.message || "加载项目列表失败")
      }
      const dashboard = result as {
        projects: ProjectRow[]
        stats?: { total: number; running: number; completed: number }
        featuredProjectId?: string | null
      }
      const nextProjects = dashboard.projects ?? []
      setProjectRows(nextProjects)
      setCurrentProjectId((current) => {
        if (!current || nextProjects.some((project) => project.id === current)) {
          return current
        }
        return dashboard.featuredProjectId ?? nextProjects[0]?.id ?? null
      })
      projectRowsStaleRef.current = false
    } catch (error) {
      console.warn("加载项目列表失败:", error)
    } finally {
      setProjectsLoaded(true)
    }
  }, [backendReady, callBackend])

  useEffect(() => {
    void refreshProjects()
  }, [refreshProjects])

  useEffect(() => {
    if (!backendReady) {
      setProjectsLoaded(false)
    }
  }, [backendReady])

  useEffect(() => {
    if (!backendReady) return
    const sync = (eventName: string) => (payload: unknown) => {
      syncAssetRowsCacheFromBackendEvent(eventName, payload)
    }
    const disposers = [
      onBackendEvent("task_completed", sync("task_completed")),
      onBackendEvent("project_changed", sync("project_changed")),
      onBackendEvent("agent_project_effect", sync("agent_project_effect")),
    ]
    return () => disposers.forEach((dispose) => dispose())
  }, [backendReady, onBackendEvent])

  useEffect(() => {
    if (!backendReady) return
    return onBackendEvent("project_changed", (payload) => {
      const projectId = eventProjectId(payload)
      const action = String(payload?.action ?? "")
      if (action === "agent_conversation_context_updated") return
      if (
        view.kind === "workspace" &&
        projectId &&
        currentProjectId === projectId &&
        (LOCAL_SOURCE_PROJECT_CHANGE_ACTIONS.has(action) ||
          isLocalAssetProjectChange(payload, action) ||
          isLocalCanvasProjectChange(payload, action))
      ) {
        projectRowsStaleRef.current = true
        return
      }
      if (!projectId || !currentProjectId || projectId === currentProjectId) {
        void refreshProjects()
      }
    })
  }, [backendReady, currentProjectId, onBackendEvent, refreshProjects, view.kind])

  useEffect(() => {
    if (!backendReady || view.kind !== "projects" || !projectRowsStaleRef.current) return
    void refreshProjects()
  }, [backendReady, refreshProjects, view.kind])

  useEffect(() => {
    if (!backendReady) return
    const completed = onBackendEvent("home_archive_completed", (payload) => {
      const type = String(payload?.type ?? "")
      toast.success(
        type === "home_archive_import"
          ? "首页 ZIP 导入完成"
          : payload?.message || "首页 ZIP 导出完成"
      )
      void refreshProjects()
    })
    const failed = onBackendEvent("home_archive_failed", (payload) => {
      toast.error(payload?.failureReason || payload?.message || "首页导入导出失败")
    })
    return () => {
      completed()
      failed()
    }
  }, [backendReady, onBackendEvent, refreshProjects])

  const openProject = useCallback(
    (projectId: string) => {
      setCurrentProjectId(projectId)
      void PluginSDK.maximize().catch((error) => {
        console.warn("打开项目时最大化窗口失败:", error)
      })
      const nextView: AppView = {
        kind: "workspace",
        projectId,
        section: "overview",
      }
      setView(nextView)
    },
    []
  )

  const handleRequestCreateProject = useCallback(async () => {
    if (!backendReady) {
      toast.error("后端正在启动，请稍后再创建项目")
      return
    }
    try {
      const result = await callBackend<{ success?: boolean; message?: string }>(
        "check_extmodel_ready",
        { check_extmodel: true }
      )
      if (isBackendFailure(result)) {
        throw new Error(backendFailureMessage(result, "创建项目前检查失败"))
      }
      setLobbyDialog("create")
    } catch (error) {
      console.warn("创建项目前检查失败:", error)
      toast.error(error instanceof Error ? error.message : "创建项目前检查失败")
    }
  }, [backendReady, callBackend])

  const handleProjectCreated = useCallback(
    (project: ProjectRow) => {
      setProjectRows((current) => [
        project,
        ...current.filter((item) => item.id !== project.id),
      ])
      openProject(project.id)
    },
    [openProject]
  )
  const handleProjectSaved = useCallback(
    (projectId: string, patch: Partial<ProjectRow>) => {
      setCurrentProjectId(projectId)
      setProjectRows((current) =>
        current.map((project) =>
          project.id === projectId ? { ...project, ...patch } : project
        )
      )
    },
    []
  )
  const handleProjectDeleted = useCallback((projectId: string) => {
    setCurrentProjectId((current) => (current === projectId ? null : current))
    setProjectRows((current) =>
      current.filter((project) => project.id !== projectId)
    )
  }, [])

  const handleDeleteProject = useCallback(async () => {
    if (deleteProjectTargets.length === 0 || deletingProject) return
    if (!backendReady) {
      toast.error("后端未就绪，暂时无法删除项目")
      return
    }
    setDeletingProject(true)
    try {
      const failed: ProjectRow[] = []
      const failureMessages: string[] = []
      let deletedCount = 0
      for (const project of deleteProjectTargets) {
        try {
          const result = await callBackend<
            | { success?: true; projectId?: string }
            | { success: false; message?: string }
          >("delete_project", { projectId: project.id })
          if (isBackendFailure(result)) {
            throw new Error(result.message || "删除项目失败")
          }
          handleProjectDeleted(project.id)
          deletedCount += 1
        } catch (error) {
          failed.push(project)
          failureMessages.push(error instanceof Error ? error.message : "删除项目失败")
          console.warn(`删除项目 ${project.name} 失败:`, error)
        }
      }
      setDeleteProjectTargets(failed)
      if (deletedCount > 0) toast.success(`已删除 ${deletedCount} 个项目`)
      if (failed.length > 0) {
        toast.error(`${failed.length} 个项目删除失败：${failureMessages[0]}`)
      }
    } finally {
      setDeletingProject(false)
    }
  }, [
    backendReady,
    callBackend,
    deleteProjectTargets,
    deletingProject,
    handleProjectDeleted,
  ])

  useEffect(() => {
    if (
      (view.kind !== "workspace" && view.kind !== "project-settings") ||
      projectRows.length === 0
    ) {
      return
    }
    const activeProjectId =
      "projectId" in view && typeof view.projectId === "string"
        ? view.projectId
        : null
    if (activeProjectId && projectRows.some((project) => project.id === activeProjectId)) {
      return
    }
    setView({ kind: "projects" })
  }, [projectRows, view])

  const renderView = () => {
    if (view.kind === "projects") {
      return (
        <>
          <ProjectsPage
            backendReady={backendReady}
            projects={projectRows}
            onNavigate={setView}
            onOpenProject={openProject}
            onCreateProject={handleRequestCreateProject}
            onImportProject={() => setLobbyDialog("import")}
            onExportProject={() => setLobbyDialog("export")}
            onRequestDeleteProject={(project) => setDeleteProjectTargets([project])}
            onRequestDeleteProjects={(projects) => setDeleteProjectTargets(projects.slice())}
            currentProjectId={currentProjectId}
          />
          {lobbyDialog === "create" ? (
            <CreateProjectWizard
              existingProjects={projectRows}
              onClose={() => setLobbyDialog(null)}
              onCreated={(project) => {
                setLobbyDialog(null)
                handleProjectCreated(project)
              }}
              onConfigurePrerequisite={(section, providerAction) => {
                setLobbyDialog(null)
                setView({ kind: "settings", section, providerAction })
              }}
            />
          ) : null}
          {lobbyDialog === "import" ? (
            <ImportProjectDialog onClose={() => setLobbyDialog(null)} />
          ) : null}
          {lobbyDialog === "export" ? (
            <ExportProjectDialog
              projects={projectRows}
              onClose={() => setLobbyDialog(null)}
            />
          ) : null}
          <DeleteProjectDialog
            projects={deleteProjectTargets}
            deleting={deletingProject}
            onClose={() => setDeleteProjectTargets([])}
            onConfirm={handleDeleteProject}
          />
          <HomeArchiveTaskPanel />
        </>
      )
    }

    if (view.kind === "settings") {
      return (
        <SettingsPage
          section={view.section}
          onSectionChange={(section) => setView({ kind: "settings", section })}
          onBack={() => setView({ kind: "projects" })}
        >
          {view.section === "providers" && (
            <ProviderSettings openAddOnMount={view.providerAction === "add"}
              onConfigureModels={() => setView({ kind: "settings", section: "media" })} />
          )}
          {view.section === "media" && <ModelConfigSettings
            onManageProviders={() => setView({ kind: "settings", section: "providers" })} />}
          {view.section === "script-adaptation-templates" && (
            <ScriptAdaptationTemplateSettings />
          )}
          {view.section === "director-rules" && <DirectorRuleSettings />}
          {view.section === "text-replacement-templates" && (
            <TextReplacementRuleSettings />
          )}
          {view.section === "storyboard-templates" && <StoryboardTemplateSettings />}
          {view.section === "quality" && <QualitySettings />}
          {view.section === "usage" && <UsageSettings />}
        </SettingsPage>
      )
    }

    if (view.kind === "assets") {
      const returnTo = resolveAssetReturnTarget(view.returnTo, projectRows)
      return (
        <AssetLibraryPage
          tab={view.tab}
          onTabChange={(tab) => setView({ kind: "assets", tab, returnTo })}
          onBack={() => setView(returnTo)}
        />
      )
    }

    if (view.kind === "project-settings") {
      const project = findProject(projectRows, view.projectId)
      if (!project) {
        if (!projectsLoaded) {
          return <ProjectLoadingPage />
        }
        return <NotFoundPage onBack={() => setView({ kind: "projects" })} />
      }
      return (
        <ProjectSettingsPage
          project={project}
          onBack={() =>
            setView({
              kind: "workspace",
              projectId: project.id,
              section: view.returnSection ?? "overview",
              episodeId: view.returnEpisodeId,
            })
          }
          onProjectSaved={handleProjectSaved}
        />
      )
    }

    if (view.kind === "workspace") {
      const project = findProject(projectRows, view.projectId)
      if (!project) {
        if (!projectsLoaded) {
          return <ProjectLoadingPage />
        }
        return <NotFoundPage onBack={() => setView({ kind: "projects" })} />
      }
      return (
        <WorkspacePage
          project={project}
          section={view.section}
          episodeId={view.episodeId}
          onNavigate={(section, episodeId) =>
            setView({
              kind: "workspace",
              projectId: project.id,
              section,
              episodeId,
            })
          }
          onBackHome={() => setView({ kind: "projects" })}
          onOpenAssetsLibrary={() =>
            setView({
              kind: "assets",
              tab: "characters",
              returnTo: {
                kind: "workspace",
                projectId: project.id,
                section: view.section,
                episodeId: view.episodeId,
              },
            })
          }
          onProjectSettings={() =>
            setView({
              kind: "project-settings",
              projectId: project.id,
              returnSection: view.section,
              returnEpisodeId: view.episodeId,
            })
          }
          onProjectChanged={refreshProjects}
        />
      )
    }

    return <NotFoundPage onBack={() => setView({ kind: "projects" })} />
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <TitleBar />
      {renderView()}
    </div>
  )
}
