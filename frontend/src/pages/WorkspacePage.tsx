import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import {
  createCustomCanvas,
  deleteCustomCanvas,
  deleteProjectPlanningOutputs,
  getProjectAssetCounts,
  getSourceCoverage,
  listProjectCustomCanvases,
  renameCustomCanvas,
  type AgentTargetContext,
  type CustomCanvasEntry,
  type TaskRow,
} from "@/backend"
import { useBackend } from "@/hooks/useBackend"
import { AssistantPanel } from "@/features/assistant/assistant-panel"
import type {
  CanvasAgentTaskRequest,
  CanvasAgentTaskCanvasRequest,
} from "@/features/assistant/assistant-task-request"
import type { ProjectRow } from "@/features/projects/types"
import { AssetGalleryPage } from "@/features/assets/asset-gallery"
import { AssetSplitRecordsPage } from "./AssetSplitRecordsPage"
import { StoryboardWorkflowCanvas } from "@/features/storyboard/storyboard-workflow"
import { buildProjectEpisodes } from "@/features/workspace/episodes"
import { ConfirmDialog } from "@/shared/confirm-dialog"
import {
  isWorkspaceDockTaskActive as isWorkspaceTaskActive,
  useWorkspaceDockStore,
} from "@/features/workspace/workspace-dock-store"
import { useWorkspaceDockSync } from "@/features/workspace/use-workspace-dock-sync"
import type { AgentProjectEffect } from "@/features/workspace/types"
import { errMsg } from "@/shared/backend-result"
import {
  WORKSPACE_SECTIONS,
  type AssetTab,
  type WorkspaceSection,
} from "@/navigation"
import {
  isLocalWorkspaceEffect,
  workspaceEffectDeletesEpisodeSource,
  workspaceEffectDeletesPlanningOutputs,
  workspaceEffectEpisodeIds,
  workspaceEffectMayChangeAssetCounts,
  workspaceEffectNeedsAssetGalleryReload,
  workspaceEffectTouchesAssetSplitRecords,
  workspaceEffectTouchesCustomCanvasList,
  workspaceEffectTouchesTasks,
  workspaceEventProjectId,
  workspacePlanningDeleteSignature,
} from "../features/workspace/workspace-events"
import {
  CustomCanvasWorkspaceEmptyState,
  WorkspaceHeader,
  WorkspaceScroll,
} from "../features/workspace/workspace-layout"
import {
  isAssetWorkspaceSection,
  normalizeWorkspaceCanvasMode,
  normalizeWorkspaceSection,
  persistWorkspaceAssistantEnabled,
  persistWorkspaceCanvasMode,
  readWorkspaceAssistantEnabled,
  readWorkspaceCanvasMode,
  type WorkspaceCanvasMode,
  type WorkspaceEpisodeDeleteDraft,
} from "../features/workspace/workspace-navigation"
import { OverviewPage } from "../features/workspace/workspace-overview"
import {
  WorkspaceSidebar,
  episodeDisplayTitle,
  sortEpisodesByLatestFirst,
} from "../features/workspace/workspace-sidebar"
import { WorkspaceDockPanel } from "../features/workspace/workspace-task-dock"
import {
  WORKSPACE_FAILED_TASK_STATUSES,
  isTaskVisibleInProjectDock,
  isWorkspaceTaskNotification,
  type ActiveWorkspaceDock,
  type WorkspaceAssistantScope,
  type WorkspaceFocusTargetState,
  workspaceDockAnchorFromElement,
  workspaceTaskNotificationFocusTarget,
} from "../features/workspace/workspace-task-model"


export function WorkspacePage({
  project,
  section,
  episodeId,
  onNavigate,
  onBackHome,
  onOpenAssetsLibrary,
  onProjectSettings,
  onProjectChanged,
}: {
  project: ProjectRow
  section: WorkspaceSection
  episodeId?: string
  onNavigate: (section: WorkspaceSection, episodeId?: string) => void
  onBackHome: () => void
  onOpenAssetsLibrary: () => void
  onProjectSettings: () => void
  onProjectChanged: () => Promise<void>
}) {
  const { backendReady, callBackend, onBackendEvent } = useBackend()
  const activeEpisode = episodeId ?? project.currentEpisodeId
  const normalizedSection = normalizeWorkspaceSection(section)
  const initialCanvasMode = useMemo(
    () => readWorkspaceCanvasMode(project.id),
    [project.id]
  )
  const [assistantScope, setAssistantScope] = useState<WorkspaceAssistantScope>(
    () =>
      normalizedSection === "episode" && initialCanvasMode !== "custom"
        ? "episode"
        : "project"
  )
  const [activeDock, setActiveDock] = useState<ActiveWorkspaceDock | null>(null)
  const [assistantEnabled, setAssistantEnabled] = useState(readWorkspaceAssistantEnabled)
  const [projectConversationSelected, setProjectConversationSelected] = useState(false)
  const workspaceTasks = useWorkspaceDockStore((state) => state.tasks)
  const { refreshTasks: loadWorkspaceTasks, refreshUsage: loadWorkspaceUsage } =
    useWorkspaceDockSync({
      projectId: project.id,
      projectUpdatedAtRank: project.updatedAtRank,
      usageDockActive: activeDock?.dock === "usage",
    })
  const [workspaceFocusTarget, setWorkspaceFocusTarget] =
    useState<WorkspaceFocusTargetState | null>(null)
  const [agentActiveTarget, setAgentActiveTarget] =
    useState<AgentTargetContext | null>(null)
  const [canvasAgentTaskRequest, setCanvasAgentTaskRequest] =
    useState<CanvasAgentTaskRequest | null>(null)
  const canvasAgentTaskRequestRef = useRef<CanvasAgentTaskRequest | null>(null)
  const nextCanvasAgentTaskRequestIdRef = useRef(Date.now())
  const [episodeDeleteDraft, setEpisodeDeleteDraft] =
    useState<WorkspaceEpisodeDeleteDraft | null>(null)
  const [episodeDeleteLoading, setEpisodeDeleteLoading] = useState(false)
  const [canvasMode, setCanvasMode] = useState<WorkspaceCanvasMode>(() =>
    initialCanvasMode
  )
  const [customCanvases, setCustomCanvases] = useState<CustomCanvasEntry[]>([])
  const [customCanvasesLoading, setCustomCanvasesLoading] = useState(false)
  const [activeCustomCanvasId, setActiveCustomCanvasId] = useState("")
  const [customAgentCanvasId, setCustomAgentCanvasId] = useState("")
  const [customCanvasActionLoading, setCustomCanvasActionLoading] = useState("")
  const [customCanvasDeleteDraft, setCustomCanvasDeleteDraft] =
    useState<CustomCanvasEntry | null>(null)
  const activeCustomCanvas = useMemo(
    () =>
      customCanvases.find((canvas) => canvas.canvasId === activeCustomCanvasId) ??
      null,
    [activeCustomCanvasId, customCanvases]
  )
  const customAssistantEnabled =
    canvasMode === "custom" && Boolean(activeCustomCanvasId) && customAgentCanvasId === activeCustomCanvasId
  const assistantDisabled =
    normalizedSection === "episode" && canvasMode === "custom" &&
    !customAssistantEnabled && !projectConversationSelected
  const assistantOpen = assistantEnabled && !assistantDisabled
  const activeCanvasRuntimeEpisodeId =
    canvasMode === "custom"
      ? activeCustomCanvas?.storageKey ?? null
      : activeEpisode
  const [workspaceAssetCounts, setWorkspaceAssetCounts] = useState({
    characters: project.characterCount ?? 0,
    creatures: project.creatureCount ?? 0,
    scenes: project.sceneCount ?? 0,
    props: project.propCount ?? 0,
  })
  const handledPlanningDeleteEventRef = useRef<string | null>(null)
  const [workspaceEpisodeRows, setWorkspaceEpisodeRows] = useState<
    Record<string, { title: string; status: string }>
  >({})
  const [assetGalleryRefreshToken, setAssetGalleryRefreshToken] = useState<
    number | undefined
  >(undefined)
  const [assetSplitRecordsRefreshToken, setAssetSplitRecordsRefreshToken] =
    useState<number | undefined>(undefined)

  useEffect(() => {
    setAssetGalleryRefreshToken(undefined)
    setAssetSplitRecordsRefreshToken(undefined)
  }, [project.id])

  useEffect(() => {
    setCanvasMode(initialCanvasMode)
    setCustomAgentCanvasId("")
    setProjectConversationSelected(false)
    setWorkspaceFocusTarget(null)
    setAgentActiveTarget(null)
  }, [initialCanvasMode, project.id])

  useEffect(() => {
    if (normalizedSection !== "episode") return
    if (canvasMode === "custom" && !customAssistantEnabled) {
      setAssistantScope("project")
      return
    }
    setAssistantScope("episode")
  }, [canvasMode, customAssistantEnabled, normalizedSection, project.id])

  useEffect(() => {
    setAgentActiveTarget(null)
  }, [activeCustomCanvasId, activeEpisode, canvasMode, normalizedSection, project.id])

  const workspacePageAgentTarget = useMemo<AgentTargetContext>(() => {
    const baseTarget: AgentTargetContext = {
      source: "workspace_page",
      intent: "focus",
      section: normalizedSection,
    }
    if (normalizedSection === "episode") {
      baseTarget.episodeId = activeCanvasRuntimeEpisodeId
      baseTarget.canvasKind = canvasMode
      if (canvasMode === "custom" && activeCustomCanvas) {
        baseTarget.canvasId = activeCustomCanvas.canvasId
        baseTarget.canvasTitle = activeCustomCanvas.title
      }
    }
    if (isAssetWorkspaceSection(normalizedSection)) {
      return {
        ...baseTarget,
        assetTab: normalizedSection,
        assetType: normalizedSection,
      }
    }
    return baseTarget
  }, [
    activeCanvasRuntimeEpisodeId,
    activeCustomCanvas,
    activeEpisode,
    canvasMode,
    normalizedSection,
  ])

  const assistantActiveTarget = agentActiveTarget ?? workspacePageAgentTarget

  const updateAssistantEnabled = useCallback((enabled: boolean) => {
    persistWorkspaceAssistantEnabled(enabled)
    setAssistantEnabled(enabled)
  }, [])

  const handleAssistantCollapsedChange = useCallback(
    (collapsed: boolean) => updateAssistantEnabled(!collapsed),
    [updateAssistantEnabled]
  )

  const handleRequestCanvasAgentTask = useCallback((request: CanvasAgentTaskCanvasRequest) => {
    if (request.canvasKind !== "work_chain" &&
      !(request.canvasKind === "custom" &&
        ["video_prompt_standalone_generation", "video_prompt_optimization"].includes(request.taskType))) {
      toast.info("当前画布不支持此智能体任务")
      return false
    }
    if (request.canvasKind === "custom" &&
      (!activeCustomCanvas || !["video.storyboard", "video.keyframe"].includes(request.nodeType ?? ""))) {
      toast.info("请在当前自定义画布选择视频提示词卡片")
      return false
    }
    if (normalizedSection !== "episode" || request.projectId !== project.id ||
      request.episodeId !== activeCanvasRuntimeEpisodeId || canvasMode !== request.canvasKind) {
      toast.info("画布已切换，请在当前分集重新发起任务")
      return false
    }
    if (canvasAgentTaskRequestRef.current) {
      toast.info("正在打开智能体会话，请稍候")
      return false
    }
    const nextRequest: CanvasAgentTaskRequest = {
      ...request,
      ...(request.canvasKind === "custom" && activeCustomCanvas ? {
        canvasId: activeCustomCanvas.canvasId,
        canvasTitle: activeCustomCanvas.title,
      } : {}),
      requestId: ++nextCanvasAgentTaskRequestIdRef.current,
    }
    canvasAgentTaskRequestRef.current = nextRequest
    setCanvasAgentTaskRequest(nextRequest)
    setProjectConversationSelected(false)
    if (request.canvasKind === "custom") setCustomAgentCanvasId(activeCustomCanvasId)
    setAgentActiveTarget({
      source: "storyboard_canvas",
      intent: "generate",
      section: "episode",
      episodeId: request.episodeId,
      canvasKind: request.canvasKind,
      ...(request.canvasKind === "custom" && activeCustomCanvas ? {
        canvasId: activeCustomCanvas.canvasId,
        canvasTitle: activeCustomCanvas.title,
      } : {}),
      nodeId: request.nodeId,
      nodeType: request.taskType === "director_plan_generation"
        ? "director.board"
        : ["video_prompt_generation", "video_prompt_standalone_generation", "video_prompt_optimization"].includes(request.taskType)
          ? request.nodeType ?? "video.storyboard"
          : "prompt.storyboard",
      routeId: request.routeId,
      workChainId: request.workChainId,
    })
    setAssistantScope("episode")
    updateAssistantEnabled(true)
    return true
  }, [activeCanvasRuntimeEpisodeId, activeCustomCanvas, activeCustomCanvasId, canvasMode, normalizedSection, project.id, updateAssistantEnabled])

  const handleCanvasAgentTaskRequestHandled = useCallback((requestId: number) => {
    if (canvasAgentTaskRequestRef.current?.requestId !== requestId) return
    canvasAgentTaskRequestRef.current = null
    setCanvasAgentTaskRequest(null)
  }, [])

  useEffect(() => {
    const request = canvasAgentTaskRequestRef.current
    if (!request) return
    if (request.projectId === project.id && request.episodeId === activeCanvasRuntimeEpisodeId &&
      normalizedSection === "episode" && canvasMode === request.canvasKind &&
      assistantScope === "episode" && assistantOpen) return
    canvasAgentTaskRequestRef.current = null
    setCanvasAgentTaskRequest(null)
  }, [activeCanvasRuntimeEpisodeId, assistantOpen, assistantScope, canvasMode, normalizedSection, project.id])

  const updateCanvasMode = useCallback(
    (mode: WorkspaceCanvasMode) => {
      setCanvasMode(mode)
      persistWorkspaceCanvasMode(project.id, mode)
    },
    [project.id]
  )

  const loadWorkspaceAssetCounts = useCallback(async () => {
    if (!backendReady) return
    try {
      const counts = await getProjectAssetCounts(callBackend, project.id)
      setWorkspaceAssetCounts({
        characters: counts.characters,
        creatures: counts.creatures,
        scenes: counts.scenes,
        props: counts.props,
      })
    } catch (error) {
      console.warn("加载工作区资产计数失败:", error)
    }
  }, [backendReady, callBackend, project.id])

  const loadWorkspaceEpisodeTitles = useCallback(async () => {
    if (!backendReady) return
    try {
      const result = await getSourceCoverage(callBackend, project.id)
      const rows: Record<string, { title: string; status: string }> = {}
      for (const source of result.episodeSources ?? []) {
        const title = episodeDisplayTitle({
          id: source.episodeId,
          title: source.title ?? "",
          status: source.status ?? "",
        })
        if (source.episodeId) {
          rows[source.episodeId] = {
            title,
            status: String(source.status ?? "").trim(),
          }
        }
      }
      setWorkspaceEpisodeRows(rows)
    } catch (error) {
      setWorkspaceEpisodeRows({})
      console.warn("加载分集标题失败:", error)
    }
  }, [backendReady, callBackend, project.id])

  const loadCustomCanvases = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!backendReady) return
      const silent = Boolean(options?.silent)
      if (!silent) setCustomCanvasesLoading(true)
      try {
        const rows = await listProjectCustomCanvases(callBackend, project.id)
        setCustomCanvases(rows)
      } catch (error) {
        if (!silent) setCustomCanvases([])
        console.warn("加载自定义画布失败:", error)
      } finally {
        if (!silent) setCustomCanvasesLoading(false)
      }
    },
    [backendReady, callBackend, project.id]
  )

  useEffect(() => {
    setWorkspaceAssetCounts({
      characters: project.characterCount ?? 0,
      creatures: project.creatureCount ?? 0,
      scenes: project.sceneCount ?? 0,
      props: project.propCount ?? 0,
    })
  }, [
    project.characterCount,
    project.creatureCount,
    project.id,
    project.propCount,
    project.sceneCount,
  ])

  useEffect(() => {
    void loadWorkspaceAssetCounts()
  }, [loadWorkspaceAssetCounts, project.updatedAtRank])

  useEffect(() => {
    void loadWorkspaceEpisodeTitles()
  }, [loadWorkspaceEpisodeTitles, project.updatedAtRank])

  useEffect(() => {
    void loadCustomCanvases()
  }, [loadCustomCanvases])

  useEffect(() => {
    setActiveCustomCanvasId((current) =>
      current && customCanvases.some((canvas) => canvas.canvasId === current)
        ? current
        : customCanvases[0]?.canvasId ?? ""
    )
  }, [customCanvases])

  const workspaceProjectTasks = useMemo(
    () =>
      workspaceTasks.filter((task) => task.projectId === project.id),
    [project.id, workspaceTasks]
  )

  const workspaceTaskSummary = useMemo(() => {
    const dockTasks = workspaceTasks.filter((task) =>
      isTaskVisibleInProjectDock(task, project.id)
    )
    const notificationTasks = dockTasks.filter(
      isWorkspaceTaskNotification
    )
    return {
      total: dockTasks.length,
      running: dockTasks.filter(isWorkspaceTaskActive).length,
      failed: notificationTasks.filter((task) =>
        WORKSPACE_FAILED_TASK_STATUSES.has(String(task.status ?? "").trim())
      ).length,
      finished: notificationTasks.length,
    }
  }, [project.id, workspaceTasks])

  const workspaceProject = useMemo(() => {
    const episodeMap = new Map(
      (project.episodes ?? []).map((episode) => [episode.id, { ...episode }])
    )
    for (const [episodeId, row] of Object.entries(workspaceEpisodeRows)) {
      const existing = episodeMap.get(episodeId)
      episodeMap.set(
        episodeId,
        existing
          ? {
              ...existing,
              title: row.title || existing.title,
              status: row.status || existing.status,
            }
          : {
              id: episodeId,
              title: row.title,
              status: row.status || "已拆分原文",
            }
      )
    }
    return {
      ...project,
      episodes: Array.from(episodeMap.values()),
      characterCount: workspaceAssetCounts.characters,
      creatureCount: workspaceAssetCounts.creatures,
      sceneCount: workspaceAssetCounts.scenes,
      propCount: workspaceAssetCounts.props,
    }
  }, [project, workspaceAssetCounts, workspaceEpisodeRows])
  const latestWorkspaceEpisodeId = useMemo(
    () =>
      sortEpisodesByLatestFirst(buildProjectEpisodes(workspaceProject))[0]?.id,
    [workspaceProject]
  )
  const handleWorkspaceProjectChanged = useCallback(async () => {
    await onProjectChanged()
    await loadWorkspaceAssetCounts()
    await loadWorkspaceEpisodeTitles()
    await loadCustomCanvases()
  }, [
    loadCustomCanvases,
    loadWorkspaceAssetCounts,
    loadWorkspaceEpisodeTitles,
    onProjectChanged,
  ])

  const applyPlanningOutputsDeletedEffect = useCallback(
    (effect: AgentProjectEffect, fallbackEpisodeTitle?: string) => {
      if (!workspaceEffectDeletesPlanningOutputs(effect)) return
      const episodeIds = workspaceEffectEpisodeIds(effect)
      if (episodeIds.length === 0) {
        void loadWorkspaceEpisodeTitles()
        return
      }
      if (workspaceEffectDeletesEpisodeSource(effect)) {
        setWorkspaceEpisodeRows((rows) => {
          const nextRows = { ...rows }
          for (const episodeId of episodeIds) {
            delete nextRows[episodeId]
          }
          return nextRows
        })
        return
      }
      setWorkspaceEpisodeRows((rows) => {
        const nextRows = { ...rows }
        for (const episodeId of episodeIds) {
          const projectEpisode = project.episodes?.find(
            (episode) => episode.id === episodeId
          )
          nextRows[episodeId] = {
            title:
              rows[episodeId]?.title ||
              projectEpisode?.title ||
              fallbackEpisodeTitle ||
              episodeId,
            status: "原文已保留，等待重新规划分镜",
          }
        }
        return nextRows
      })
    },
    [loadWorkspaceEpisodeTitles, project.episodes]
  )

  const handleWorkspaceNavigate = useCallback(
    (nextSection: WorkspaceSection, nextEpisodeId?: string) => {
      const normalizedNextSection = normalizeWorkspaceSection(nextSection)
      if (normalizedNextSection === "episode") {
        updateCanvasMode("work_chain")
      }
      setWorkspaceFocusTarget(null)
      setAgentActiveTarget(null)
      setProjectConversationSelected(false)
      setAssistantScope(
        normalizedNextSection === "episode" ? "episode" : "project"
      )
      onNavigate(normalizedNextSection, nextEpisodeId)
    },
    [onNavigate, updateCanvasMode]
  )

  const handleSelectCanvasMode = useCallback(
    (mode: WorkspaceCanvasMode) => {
      updateCanvasMode(mode)
      setCustomAgentCanvasId("")
      setProjectConversationSelected(false)
      setWorkspaceFocusTarget(null)
      setAgentActiveTarget(null)
      if (mode === "work_chain") {
        setAssistantScope("episode")
      } else {
        setAssistantScope("project")
      }
      onNavigate("episode", activeEpisode)
    },
    [activeEpisode, onNavigate, updateCanvasMode]
  )

  const handleSelectCustomCanvas = useCallback(
    (canvasId: string) => {
      updateCanvasMode("custom")
      setActiveCustomCanvasId(canvasId)
      setCustomAgentCanvasId("")
      setProjectConversationSelected(false)
      setWorkspaceFocusTarget(null)
      setAgentActiveTarget(null)
      setAssistantScope("project")
      onNavigate("episode", activeEpisode)
    },
    [activeEpisode, onNavigate, updateCanvasMode]
  )

  const handleCreateCustomCanvas = useCallback(async () => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    if (customCanvasActionLoading) return
    setCustomCanvasActionLoading("create")
    try {
      const canvas = await createCustomCanvas(callBackend, project.id)
      setCustomCanvases((current) =>
        [...current.filter((item) => item.canvasId !== canvas.canvasId), canvas]
          .sort((left, right) => right.sortIndex - left.sortIndex)
      )
      updateCanvasMode("custom")
      setActiveCustomCanvasId(canvas.canvasId)
      setCustomAgentCanvasId("")
      setProjectConversationSelected(false)
      setWorkspaceFocusTarget(null)
      setAgentActiveTarget(null)
      setAssistantScope("project")
      onNavigate("episode", activeEpisode)
      toast.success("自定义画布已创建")
    } catch (error) {
      toast.error(errMsg(error, "创建自定义画布失败"))
    } finally {
      setCustomCanvasActionLoading("")
    }
  }, [
    activeEpisode,
    backendReady,
    callBackend,
    customCanvasActionLoading,
    onNavigate,
    project.id,
    updateCanvasMode,
  ])

  const handleRenameCustomCanvas = useCallback(
    async (canvas: CustomCanvasEntry, title: string) => {
      const nextTitle = title.trim()
      if (!nextTitle || nextTitle === canvas.title) return
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const actionKey = `rename:${canvas.canvasId}`
      if (customCanvasActionLoading) return
      setCustomCanvasActionLoading(actionKey)
      try {
        const updated = await renameCustomCanvas(
          callBackend,
          project.id,
          canvas.canvasId,
          nextTitle
        )
        setCustomCanvases((current) =>
          current.map((item) =>
            item.canvasId === updated.canvasId ? updated : item
          )
        )
        toast.success("画布名称已更新")
      } catch (error) {
        toast.error(errMsg(error, "重命名自定义画布失败"))
      } finally {
        setCustomCanvasActionLoading("")
      }
    },
    [backendReady, callBackend, customCanvasActionLoading, project.id]
  )

  const handleConfirmDeleteCustomCanvas = useCallback(async () => {
    if (!customCanvasDeleteDraft) return
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    const canvas = customCanvasDeleteDraft
    const actionKey = `delete:${canvas.canvasId}`
    setCustomCanvasActionLoading(actionKey)
    try {
      await deleteCustomCanvas(callBackend, project.id, canvas.canvasId)
      setCustomCanvases((current) =>
        current.filter((item) => item.canvasId !== canvas.canvasId)
      )
      setActiveCustomCanvasId((current) =>
        current === canvas.canvasId ? "" : current
      )
      setCustomCanvasDeleteDraft(null)
      toast.success("自定义画布已删除")
    } catch (error) {
      toast.error(errMsg(error, "删除自定义画布失败"))
    } finally {
      setCustomCanvasActionLoading("")
    }
  }, [backendReady, callBackend, customCanvasDeleteDraft, project.id])

  const handleConfirmDeleteEpisode = useCallback(async () => {
    if (!episodeDeleteDraft) return
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    const { episode, mode } = episodeDeleteDraft
    const deleteEpisodeSource = mode === "episode"
    const requestedTargets = deleteEpisodeSource
      ? ["source_splits", "storyboards"]
      : ["storyboards"]
    const requestedDeleteEffect: AgentProjectEffect = {
      action: "project_planning_outputs_deleted",
      projectId: project.id,
      episodeIds: [episode.id],
      targets: requestedTargets,
    }
    if (deleteEpisodeSource && episode.id !== latestWorkspaceEpisodeId) {
      toast.error("只能删除最新一集")
      setEpisodeDeleteDraft(null)
      return
    }
    const requestedDeleteSignature =
      workspacePlanningDeleteSignature(requestedDeleteEffect)
    handledPlanningDeleteEventRef.current = requestedDeleteSignature
    window.setTimeout(() => {
      if (handledPlanningDeleteEventRef.current === requestedDeleteSignature) {
        handledPlanningDeleteEventRef.current = null
      }
    }, 5000)
    setEpisodeDeleteLoading(true)
    try {
      const result = await deleteProjectPlanningOutputs(
        callBackend,
        project.id,
        {
          episodeIds: [episode.id],
          targets: requestedTargets,
          confirmDeleteAll: true,
          userInstruction: deleteEpisodeSource
            ? `删除 ${episode.id} 这一集分集原文和对应工作链画布数据`
            : `删除 ${episode.id} 这一集画布和工作链数据，保留分集原文`,
          reason: deleteEpisodeSource
            ? "workspace_sidebar_episode_deleted"
            : "workspace_sidebar_episode_canvas_deleted",
        }
      )
      const affectedEpisodeIds =
        result.episodeIds && result.episodeIds.length > 0
          ? result.episodeIds
          : [episode.id]
      const deleteEffect: AgentProjectEffect = {
        ...requestedDeleteEffect,
        episodeIds: affectedEpisodeIds,
        targets: result.targets ?? requestedTargets,
        changedResources: result.changedResources ?? [],
      }
      const affectedEpisodeIdSet = new Set(affectedEpisodeIds)
      applyPlanningOutputsDeletedEffect(deleteEffect, episode.title || episode.id)
      if (deleteEpisodeSource) {
        if (
          normalizedSection === "episode" &&
          activeEpisode &&
          affectedEpisodeIdSet.has(activeEpisode)
        ) {
          handleWorkspaceNavigate("overview")
        }
      }
      setEpisodeDeleteDraft(null)
      toast.success(
        deleteEpisodeSource && affectedEpisodeIds.length > 1
          ? `本集已删除，已同步清理 ${affectedEpisodeIds.join("、")}`
          : `${deleteEpisodeSource ? "本集已删除" : "本集画布已删除"}：${episode.id}`
      )
      if (deleteEpisodeSource) {
        await handleWorkspaceProjectChanged()
      }
    } catch (error) {
      handledPlanningDeleteEventRef.current = null
      toast.error(
        errMsg(
          error,
          deleteEpisodeSource ? "删除本集失败" : "删除本集画布失败"
        )
      )
    } finally {
      setEpisodeDeleteLoading(false)
    }
  }, [
    activeEpisode,
    backendReady,
    callBackend,
    episodeDeleteDraft,
    applyPlanningOutputsDeletedEffect,
    handleWorkspaceNavigate,
    handleWorkspaceProjectChanged,
    latestWorkspaceEpisodeId,
    normalizedSection,
    project.id,
  ])

  const handleOpenProjectConversation = useCallback(() => {
    setWorkspaceFocusTarget(null)
    setAgentActiveTarget(null)
    setProjectConversationSelected(true)
    setAssistantScope("project")
  }, [])

  const focusWorkspaceTarget = useCallback(
    (
      focusTarget:
        | AgentProjectEffect["focusTarget"]
        | TaskRow["focusTarget"]
        | null
        | undefined,
      fallbackEpisodeId?: string | null
    ) => {
      const section = focusTarget?.section
      if (
        !section ||
        !WORKSPACE_SECTIONS.includes(section as WorkspaceSection)
      ) {
        return false
      }
      const normalizedTargetSection = normalizeWorkspaceSection(
        section as WorkspaceSection
      )
      const effectTarget = focusTarget as AgentProjectEffect["focusTarget"]
      const targetCanvasKind = normalizeWorkspaceCanvasMode(
        effectTarget?.canvasKind
      )
      const targetCanvasId = String(effectTarget?.canvasId ?? "").trim()
      const rawEpisodeId =
        focusTarget?.episodeId ?? fallbackEpisodeId ?? activeEpisode
      const targetCustomCanvas =
        targetCanvasKind === "custom"
          ? customCanvases.find(
              (canvas) =>
                canvas.canvasId === targetCanvasId ||
                canvas.storageKey === rawEpisodeId ||
                canvas.canvasId === rawEpisodeId
            ) ?? null
          : null
      const shouldFocusCustomCanvas =
        normalizedTargetSection === "episode" &&
        targetCanvasKind === "custom" &&
        Boolean(targetCanvasId || targetCustomCanvas)
      const requestId = Date.now()
      const nextTarget: WorkspaceFocusTargetState = {
        section: normalizedTargetSection,
        episodeId: shouldFocusCustomCanvas
          ? targetCustomCanvas?.storageKey ?? rawEpisodeId
          : rawEpisodeId,
        assetTab: focusTarget?.assetTab,
        nodeId: focusTarget?.nodeId ?? effectTarget?.assetId,
        assetId: effectTarget?.assetId,
        requestId,
      }
      const nextAgentTarget: AgentTargetContext = {
        source: "workspace_focus",
        intent: "focus",
        section: normalizedTargetSection,
        episodeId: nextTarget.episodeId,
        nodeId: nextTarget.nodeId,
      }
      if (nextTarget.section === "episode") {
        if (shouldFocusCustomCanvas) {
          updateCanvasMode("custom")
          setCustomAgentCanvasId("")
          if (targetCustomCanvas) {
            setActiveCustomCanvasId(targetCustomCanvas.canvasId)
            nextAgentTarget.canvasId = targetCustomCanvas.canvasId
            nextAgentTarget.canvasTitle = targetCustomCanvas.title
          } else if (targetCanvasId) {
            setActiveCustomCanvasId(targetCanvasId)
            nextAgentTarget.canvasId = targetCanvasId
          }
          nextAgentTarget.canvasKind = "custom"
        } else {
          updateCanvasMode("work_chain")
          nextAgentTarget.canvasKind = "work_chain"
        }
      }
      if (isAssetWorkspaceSection(normalizedTargetSection)) {
        nextAgentTarget.assetTab =
          nextTarget.assetTab ?? normalizedTargetSection
        nextAgentTarget.assetType =
          nextTarget.assetTab ?? normalizedTargetSection
        nextAgentTarget.assetId = nextTarget.assetId ?? nextTarget.nodeId
      }
      setWorkspaceFocusTarget(nextTarget)
      setAgentActiveTarget(nextAgentTarget)
      setProjectConversationSelected(false)
      setAssistantScope(
        nextTarget.section === "episode" && !shouldFocusCustomCanvas
          ? "episode"
          : "project"
      )
      onNavigate(
        nextTarget.section,
        shouldFocusCustomCanvas ? activeEpisode : nextTarget.episodeId
      )
      window.setTimeout(() => {
        setWorkspaceFocusTarget((current) =>
          current?.requestId === requestId ? null : current
        )
      }, 3600)
      return true
    },
    [activeEpisode, customCanvases, onNavigate, updateCanvasMode]
  )

  const handleLocateTask = useCallback(
    (task: TaskRow) =>
      focusWorkspaceTarget(
        workspaceTaskNotificationFocusTarget(task),
        task.episodeId ?? project.currentEpisodeId
      ),
    [focusWorkspaceTarget, project.currentEpisodeId]
  )

  useEffect(() => {
    if (!backendReady) return
    const changed = onBackendEvent("project_changed", (payload: any) => {
      if (!payload || workspaceEventProjectId(payload) !== project.id) return
      const effect = payload as AgentProjectEffect
      if (workspaceEffectDeletesPlanningOutputs(effect)) {
        const signature = workspacePlanningDeleteSignature(effect)
        if (handledPlanningDeleteEventRef.current === signature) {
          handledPlanningDeleteEventRef.current = null
        } else if (workspaceEffectDeletesEpisodeSource(effect)) {
          void handleWorkspaceProjectChanged()
        } else {
          applyPlanningOutputsDeletedEffect(effect)
        }
      }
      if (workspaceEffectMayChangeAssetCounts(effect)) {
        void loadWorkspaceAssetCounts()
      }
      if (workspaceEffectTouchesAssetSplitRecords(effect)) {
        setAssetSplitRecordsRefreshToken(Date.now())
      }
      if (workspaceEffectTouchesCustomCanvasList(effect, customCanvases)) {
        void loadCustomCanvases({ silent: true })
      }
    })
    const effected = onBackendEvent(
      "agent_project_effect",
      (payload: AgentProjectEffect) => {
        if (!payload || workspaceEventProjectId(payload) !== project.id) return
        const effect = { ...payload, nonce: Date.now() }
        if (isLocalWorkspaceEffect(effect)) {
          if (workspaceEffectNeedsAssetGalleryReload(effect)) {
            setAssetGalleryRefreshToken(effect.nonce)
          }
          if (workspaceEffectMayChangeAssetCounts(effect)) {
            void loadWorkspaceAssetCounts()
          }
          if (workspaceEffectTouchesAssetSplitRecords(effect)) {
            setAssetSplitRecordsRefreshToken(effect.nonce)
          }
          if (workspaceEffectTouchesTasks(effect)) {
            void loadWorkspaceTasks({ showLoading: false })
          }
        } else {
          setAssetGalleryRefreshToken(effect.nonce)
          if (workspaceEffectTouchesAssetSplitRecords(effect)) {
            setAssetSplitRecordsRefreshToken(effect.nonce)
          }
          void handleWorkspaceProjectChanged()
          void loadWorkspaceTasks()
        }
        if (effect.notice) {
          toast.success(effect.notice)
        }
      }
    )
    return () => {
      changed()
      effected()
    }
  }, [
    applyPlanningOutputsDeletedEffect,
    backendReady,
    customCanvases,
    handleWorkspaceProjectChanged,
    loadCustomCanvases,
    loadWorkspaceAssetCounts,
    loadWorkspaceTasks,
    onBackendEvent,
    project.id,
  ])

  useEffect(() => {
    if (!backendReady) return
    const completed = onBackendEvent("jianying_export_completed", (payload) => {
      if (workspaceEventProjectId(payload) !== project.id) return
      toast.success(payload?.message || "剪映草稿导出完成")
      void loadWorkspaceTasks()
    })
    const failed = onBackendEvent("jianying_export_failed", (payload) => {
      if (workspaceEventProjectId(payload) !== project.id) return
      toast.error(
        payload?.failureReason || payload?.message || "剪映草稿导出失败"
      )
      void loadWorkspaceTasks()
    })
    return () => {
      completed()
      failed()
    }
  }, [backendReady, loadWorkspaceTasks, onBackendEvent, project.id])

  return (
    <main className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
      <WorkspaceHeader
        project={workspaceProject}
        onBackHome={onBackHome}
        onOpenAssetsLibrary={onOpenAssetsLibrary}
        onProjectSettings={onProjectSettings}
        onOpenDock={(dock, trigger) => {
          const anchor = workspaceDockAnchorFromElement(trigger)
          setActiveDock((current) =>
            current?.dock === dock ? null : { dock, anchor }
          )
        }}
        assistantOpen={assistantOpen}
        assistantDisabled={assistantDisabled}
        onToggleAssistant={() => {
          if (assistantDisabled) return
          updateAssistantEnabled(!assistantEnabled)
        }}
        taskSummary={workspaceTaskSummary}
      />
      {activeDock ? (
        <WorkspaceDockPanel
          dock={activeDock.dock}
          anchor={activeDock.anchor}
          project={workspaceProject}
          onRefreshTasks={loadWorkspaceTasks}
          onRefreshUsage={loadWorkspaceUsage}
          onLocateTask={handleLocateTask}
          onClose={() => setActiveDock(null)}
        />
      ) : null}
      <ConfirmDialog
        open={Boolean(episodeDeleteDraft)}
        title={
          episodeDeleteDraft?.mode === "episode"
            ? "删除本集"
            : "删除本集画布"
        }
        description={
          episodeDeleteDraft
            ? episodeDeleteDraft.mode === "episode"
              ? `将删除「${episodeDeleteDraft.episode.title || episodeDeleteDraft.episode.id}」的分集原文，并清理该集工作链和画布数据。`
              : `将删除「${episodeDeleteDraft.episode.title || episodeDeleteDraft.episode.id}」的工作链和画布数据，保留本集原文。`
            : ""
        }
        confirmLabel="删除"
        loadingLabel="删除中"
        loading={episodeDeleteLoading}
        onCancel={() => {
          if (!episodeDeleteLoading) setEpisodeDeleteDraft(null)
        }}
        onConfirm={() => void handleConfirmDeleteEpisode()}
      />
      <ConfirmDialog
        open={Boolean(customCanvasDeleteDraft)}
        title="删除自定义画布"
        description={
          customCanvasDeleteDraft
            ? `将删除「${customCanvasDeleteDraft.title}」和画布内的所有节点、连线与任务记录。`
            : ""
        }
        confirmLabel="删除"
        loadingLabel="删除中"
        loading={customCanvasActionLoading.startsWith("delete:")}
        onCancel={() => {
          if (!customCanvasActionLoading.startsWith("delete:")) {
            setCustomCanvasDeleteDraft(null)
          }
        }}
        onConfirm={() => void handleConfirmDeleteCustomCanvas()}
      />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <WorkspaceSidebar
          project={workspaceProject}
          section={normalizedSection}
          episodeId={activeEpisode}
          assistantOpen={assistantOpen}
          assistantScope={assistantScope}
          projectConversationSelected={projectConversationSelected}
          canvasMode={canvasMode}
          customCanvases={customCanvases}
          activeCustomCanvasId={activeCustomCanvasId}
          customCanvasesLoading={customCanvasesLoading}
          customCanvasActionLoading={customCanvasActionLoading}
          onNavigate={handleWorkspaceNavigate}
          onOpenProjectConversation={handleOpenProjectConversation}
          onSelectCanvasMode={handleSelectCanvasMode}
          onCreateCustomCanvas={() => void handleCreateCustomCanvas()}
          onSelectCustomCanvas={handleSelectCustomCanvas}
          onRenameCustomCanvas={(canvas, title) =>
            void handleRenameCustomCanvas(canvas, title)
          }
          onRequestDeleteCustomCanvas={setCustomCanvasDeleteDraft}
          onRequestDeleteEpisode={(episode, mode) => {
            if (mode === "episode" && episode.id !== latestWorkspaceEpisodeId) {
              toast.error("只能删除最新一集")
              return
            }
            setEpisodeDeleteDraft({ episode, mode })
          }}
        />
        <section className="flex min-w-0 flex-1 overflow-hidden">
          {normalizedSection === "overview" && (
            <WorkspaceScroll
              focusToken={
                workspaceFocusTarget?.section === "overview"
                  ? workspaceFocusTarget.requestId
                  : undefined
              }
            >
              <OverviewPage
                project={workspaceProject}
                onProjectChanged={handleWorkspaceProjectChanged}
              />
            </WorkspaceScroll>
          )}
          {normalizedSection === "asset-split-records" && (
            <AssetSplitRecordsPage
              project={workspaceProject}
              projectVersion={workspaceProject.updatedAtRank}
              refreshToken={assetSplitRecordsRefreshToken}
            />
          )}
          {normalizedSection === "characters" && (
            <ProjectAssetPage
              project={workspaceProject}
              tab="characters"
              taskRows={workspaceProjectTasks}
              agentRefreshToken={assetGalleryRefreshToken}
              onAgentTargetChange={setAgentActiveTarget}
              focusTarget={
                workspaceFocusTarget?.section === "characters"
                  ? workspaceFocusTarget
                  : null
              }
            />
          )}
          {normalizedSection === "creatures" && (
            <ProjectAssetPage
              project={workspaceProject}
              tab="creatures"
              taskRows={workspaceProjectTasks}
              agentRefreshToken={assetGalleryRefreshToken}
              onAgentTargetChange={setAgentActiveTarget}
              focusTarget={
                workspaceFocusTarget?.section === "creatures"
                  ? workspaceFocusTarget
                  : null
              }
            />
          )}
          {normalizedSection === "scenes" && (
            <ProjectAssetPage
              project={workspaceProject}
              tab="scenes"
              taskRows={workspaceProjectTasks}
              agentRefreshToken={assetGalleryRefreshToken}
              onAgentTargetChange={setAgentActiveTarget}
              focusTarget={
                workspaceFocusTarget?.section === "scenes"
                  ? workspaceFocusTarget
                  : null
              }
            />
          )}
          {normalizedSection === "props" && (
            <ProjectAssetPage
              project={workspaceProject}
              tab="props"
              taskRows={workspaceProjectTasks}
              agentRefreshToken={assetGalleryRefreshToken}
              onAgentTargetChange={setAgentActiveTarget}
              focusTarget={
                workspaceFocusTarget?.section === "props"
                  ? workspaceFocusTarget
                  : null
              }
            />
          )}
          {normalizedSection === "episode" && canvasMode === "work_chain" && (
            <StoryboardWorkflowCanvas
              project={workspaceProject}
              episodeId={activeEpisode}
              canvasKind="work_chain"
              workspaceTasks={workspaceProjectTasks}
              agentFocusNodeId={
                workspaceFocusTarget?.section === "episode"
                  ? workspaceFocusTarget.nodeId
                  : undefined
              }
              agentFocusEpisodeId={
                workspaceFocusTarget?.section === "episode"
                  ? workspaceFocusTarget.episodeId
                  : undefined
              }
              agentFocusToken={
                workspaceFocusTarget?.section === "episode"
                  ? workspaceFocusTarget.requestId
                  : undefined
              }
              onAgentTargetChange={setAgentActiveTarget}
              onRequestCanvasAgentTask={handleRequestCanvasAgentTask}
            />
          )}
          {normalizedSection === "episode" && canvasMode === "custom" ? (
            activeCustomCanvas ? (
              <StoryboardWorkflowCanvas
                project={workspaceProject}
                episodeId={activeCustomCanvas.storageKey}
                canvasKind="custom"
                canvasTitle={activeCustomCanvas.title}
                workspaceTasks={workspaceProjectTasks}
                agentFocusNodeId={
                  workspaceFocusTarget?.section === "episode" &&
                  workspaceFocusTarget.episodeId === activeCustomCanvas.storageKey
                    ? workspaceFocusTarget.nodeId
                    : undefined
                }
                agentFocusEpisodeId={
                  workspaceFocusTarget?.section === "episode" &&
                  workspaceFocusTarget.episodeId === activeCustomCanvas.storageKey
                    ? workspaceFocusTarget.episodeId
                    : undefined
                }
                agentFocusToken={
                  workspaceFocusTarget?.section === "episode" &&
                  workspaceFocusTarget.episodeId === activeCustomCanvas.storageKey
                    ? workspaceFocusTarget.requestId
                    : undefined
                }
                onAgentTargetChange={setAgentActiveTarget}
                onRequestCanvasAgentTask={handleRequestCanvasAgentTask}
              />
            ) : (
              <CustomCanvasWorkspaceEmptyState
                loading={customCanvasesLoading}
                creating={customCanvasActionLoading === "create"}
                onCreate={() => void handleCreateCustomCanvas()}
              />
            )
          ) : null}
        </section>
        {!assistantDisabled ? (
          <AssistantPanel
            project={workspaceProject}
            episodeId={activeCanvasRuntimeEpisodeId ?? activeEpisode}
            canvasTitle={canvasMode === "custom" ? activeCustomCanvas?.title : undefined}
            scope={assistantScope}
            collapsed={!assistantEnabled}
            onCollapsedChange={handleAssistantCollapsedChange}
            activeTarget={assistantActiveTarget}
            canvasAgentTaskRequest={canvasAgentTaskRequest}
            onCanvasAgentTaskRequestHandled={handleCanvasAgentTaskRequestHandled}
            onNavigate={handleWorkspaceNavigate}
            onOpenProjectConversation={handleOpenProjectConversation}
            onProjectChanged={handleWorkspaceProjectChanged}
          />
        ) : null}
      </div>
    </main>
  )
}

function ProjectAssetPage({
  project,
  tab,
  taskRows,
  agentRefreshToken,
  focusTarget,
  onAgentTargetChange,
}: {
  project: ProjectRow
  tab: AssetTab
  taskRows?: TaskRow[]
  agentRefreshToken?: number
  focusTarget?: WorkspaceFocusTargetState | null
  onAgentTargetChange?: (target: AgentTargetContext | null) => void
}) {
  return (
    <div className="flex min-h-0 flex-1 overflow-hidden">
      <AssetGalleryPage
        tab={tab}
        scope="project"
        projectId={project.id}
        projectVersion={project.updatedAtRank}
        taskRows={taskRows}
        agentRefreshToken={agentRefreshToken}
        focusAssetId={
          focusTarget?.assetTab === tab || focusTarget?.section === tab
            ? (focusTarget.nodeId ?? focusTarget.assetId)
            : undefined
        }
        focusToken={focusTarget?.requestId}
        onAgentTargetChange={onAgentTargetChange}
      />
    </div>
  )
}
