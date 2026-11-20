import { useCallback, useEffect, useRef } from "react"
import {
  directorPlanTextForNode,
  isDirectorBoardNodeType,
  isWorkflowVideoTaskType,
  toBackendNode,
} from "./workflow-canvas-model"
import {
  storyboardResultImageHasGeneratedMedia,
  workflowStoryboardResultsForCardNode,
  workflowStoryboardResultForScopeNode,
} from "./workflow-node-relations"
import {
  storyboardScriptTemplateValue,
  storyboardShootableContentReadyForNode,
  storyboardSourceFactTextForNode,
  workflowScriptCreationNodeForScope,
} from "./workflow-prompt-node-model"
import { findBlockingWorkflowTaskForNode } from "./workflow-task-status"
import { toast } from "sonner"
import {
  generateStoryboardImage,
  generateVisualHandoffImage,
} from "@/backend"
import { errMsg } from "@/shared/backend-result"
import { assertWorkflowTaskAccepted } from "./workflow-task-status"
import type { BackendCaller, EpisodeWorkflow, TaskRow } from "@/backend"
import type { StoryboardNode, StoryboardEdge } from "./workflow-canvas-model"
import type { WorkflowCanvasDetails } from "./use-workflow-canvas-details"
import type { WorkflowTaskLifecycle } from "./use-workflow-task-lifecycle"
import type { CanvasAgentTaskCanvasRequest } from "@/features/assistant/assistant-task-request"

export function useWorkflowStageGeneration({
  projectId,
  episodeId,
  backendReady,
  callBackend,
  readNodes,
  taskLifecycle,
  canvasDetails,
  prepareWorkflow,
  applyMutation,
  onTaskAccepted,
  onLaunch,
  onRequestCanvasAgentTask,
}: {
  projectId: string
  episodeId: string
  backendReady: boolean
  callBackend: BackendCaller
  readNodes: () => StoryboardNode[]
  taskLifecycle: WorkflowTaskLifecycle
  canvasDetails: WorkflowCanvasDetails
  prepareWorkflow: () => Promise<{
    workflow: EpisodeWorkflow
    nodes: StoryboardNode[]
    edges: StoryboardEdge[]
  }>
  applyMutation: (payload: Record<string, unknown>) => boolean
  onTaskAccepted: (task: TaskRow) => void
  onLaunch: () => void
  onRequestCanvasAgentTask?: (request: Omit<CanvasAgentTaskCanvasRequest, "canvasKind">) => boolean
}) {
  const canvasScopeKey = `${projectId}\u0000${episodeId}`
  const canvasRequestScopeRef = useRef({ key: canvasScopeKey })
  if (canvasRequestScopeRef.current.key !== canvasScopeKey)
    canvasRequestScopeRef.current = { key: canvasScopeKey }
  useEffect(() => {
    if (canvasRequestScopeRef.current.key !== canvasScopeKey)
      canvasRequestScopeRef.current = { key: canvasScopeKey }
    const scope = canvasRequestScopeRef.current
    return () => {
      if (canvasRequestScopeRef.current === scope)
        canvasRequestScopeRef.current = { key: "" }
    }
  }, [canvasScopeKey])
  const handleGenerateStoryboardImageFromDirector = useCallback(
    async (nodeId: string) => {
      const requestScope = canvasRequestScopeRef.current
      const currentScope = () => canvasRequestScopeRef.current === requestScope
      if (requestScope.key !== canvasScopeKey) return
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      let requestNode = readNodes().find((item) => item.id === nodeId)
      if (!requestNode || (
        !isDirectorBoardNodeType(requestNode.data.eyebrow) &&
        !(requestNode.data.eyebrow === "storyboard.image" && requestNode.data.shotGroupId)
      )) {
        toast.info("请选择分镜脚本或已分配的分镜图")
        return
      }
      let runNodes = readNodes()
      try {
        const fresh = await prepareWorkflow()
        if (!currentScope()) return
        runNodes = fresh.nodes
        requestNode =
          fresh.nodes.find((item) => item.id === nodeId) ?? requestNode
        requestNode = await canvasDetails.hydrateForRun(requestNode)
        if (!currentScope()) return
      } catch (error) {
        if (!currentScope()) return
        toast.error(errMsg(error, "刷新最新配置失败"))
        return
      }
      const isAssignedImage = requestNode.data.eyebrow === "storyboard.image" && Boolean(requestNode.data.shotGroupId)
      const directorNode = isAssignedImage
        ? runNodes.find((item) =>
            isDirectorBoardNodeType(item.data.eyebrow) &&
            item.data.workChainId === requestNode?.data.workChainId
          )
        : requestNode
      if (!directorNode || !directorPlanTextForNode(directorNode.data).trim()) {
        toast.info("请先填写或生成分镜脚本")
        return
      }
      if (!isAssignedImage && !directorNode.data.storyboardAllocation?.groups.length) {
        toast.info("请先在分镜脚本保存镜头分组")
        return
      }
      if (!isAssignedImage && directorNode.data.storyboardAllocation?.groups.length && directorNode.data.storyboardAllocation.groups.length > 1) {
        toast.info("请在各分镜图上逐张生成")
        return
      }
      const storyboardResultNode = isAssignedImage
        ? requestNode
        : workflowStoryboardResultForScopeNode(runNodes, requestNode)
      if (!storyboardResultNode) {
        toast.info("当前工作链缺少分镜图")
        return
      }
      if (
        taskLifecycle.launching().has(requestNode.id) ||
        taskLifecycle.launching().has(storyboardResultNode.id) ||
        Boolean(
          findBlockingWorkflowTaskForNode(
            taskLifecycle.tasks,
            storyboardResultNode.id
          )
        )
      ) {
        toast.info("当前工作链正在生成分镜图")
        return
      }
      onLaunch()
      taskLifecycle.setLaunching(requestNode.id, true, "storyboard_image")
      taskLifecycle.setLaunching(
        storyboardResultNode.id,
        true,
        "storyboard_image"
      )
      try {
        const task = await generateStoryboardImage(
          callBackend,
          projectId,
          episodeId,
          {
            ...toBackendNode(requestNode),
          }
        )
        if (!currentScope()) return
        assertWorkflowTaskAccepted(task)
        taskLifecycle.mergeEvent(task)
        onTaskAccepted(task)
        toast.success("分镜图生成任务已创建")
        void taskLifecycle.refresh()
      } catch (error) {
        if (!currentScope()) return
        toast.error(errMsg(error, "创建分镜图生成任务失败"))
        void taskLifecycle.refresh()
      } finally {
        if (!currentScope()) return
        taskLifecycle.setLaunching(requestNode.id, false)
        taskLifecycle.setLaunching(storyboardResultNode.id, false)
      }
    },
    [
      backendReady,
      callBackend,
      projectId,
      episodeId,
      canvasScopeKey,
      readNodes,
      prepareWorkflow,
      canvasDetails.hydrateForRun,
      taskLifecycle.setLaunching,
      taskLifecycle.launching,
      taskLifecycle.tasks,
      taskLifecycle.mergeEvent,
      taskLifecycle.refresh,
      onTaskAccepted,
      applyMutation,
      onLaunch,
    ]
  )

  const handleGenerateVisualHandoffImage = useCallback(
    async (nodeId: string) => {
      const requestScope = canvasRequestScopeRef.current
      const currentScope = () => canvasRequestScopeRef.current === requestScope
      if (requestScope.key !== canvasScopeKey) return
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      let requestNode = readNodes().find((item) => item.id === nodeId)
      if (!requestNode || requestNode.data.eyebrow !== "storyboard.card" || !requestNode.data.shotGroupId) {
        toast.info("请选择已分配的分镜单元")
        return
      }
      let resultImage: StoryboardNode | undefined
      try {
        const fresh = await prepareWorkflow()
        if (!currentScope()) return
        requestNode =
          fresh.nodes.find((item) => item.id === nodeId) ?? requestNode
        requestNode = await canvasDetails.hydrateForRun(requestNode)
        if (!currentScope()) return
        for (const candidate of workflowStoryboardResultsForCardNode(fresh.nodes, requestNode)) {
          const hydrated = await canvasDetails.hydrateForRun(candidate)
          if (!currentScope()) return
          if (storyboardResultImageHasGeneratedMedia(hydrated)) {
            resultImage = hydrated
            break
          }
        }
      } catch (error) {
        if (!currentScope()) return
        toast.error(errMsg(error, "刷新最新配置失败"))
        return
      }
      if (!resultImage || !storyboardResultImageHasGeneratedMedia(resultImage)) {
        toast.info("请先生成此分镜单元的分镜图")
        return
      }
      onLaunch()
      taskLifecycle.setLaunching(requestNode.id, true, "visual_handoff_image")
      try {
        const task = await generateVisualHandoffImage(
          callBackend,
          projectId,
          episodeId,
          {
            ...toBackendNode(requestNode),
          }
        )
        if (!currentScope()) return
        assertWorkflowTaskAccepted(task)
        applyMutation(task)
        taskLifecycle.mergeEvent(task)
        onTaskAccepted(task)
        toast.success("视觉交接图生成任务已创建")
        void taskLifecycle.refresh()
      } catch (error) {
        if (!currentScope()) return
        toast.error(errMsg(error, "创建视觉交接图生成任务失败"))
        void taskLifecycle.refresh()
      } finally {
        if (!currentScope()) return
        taskLifecycle.setLaunching(requestNode.id, false)
      }
    },
    [
      backendReady,
      callBackend,
      projectId,
      episodeId,
      canvasScopeKey,
      readNodes,
      prepareWorkflow,
      canvasDetails.hydrateForRun,
      taskLifecycle.setLaunching,
      taskLifecycle.launching,
      taskLifecycle.tasks,
      taskLifecycle.mergeEvent,
      taskLifecycle.refresh,
      onTaskAccepted,
      applyMutation,
      onLaunch,
    ]
  )

  const handleGenerateCinematicScript = useCallback(
    async (
      nodeId: string,
      options: {
        scriptTemplateId?: string
        userInstruction?: string
      } = {}
    ) => {
      const requestScope = canvasRequestScopeRef.current
      const currentScope = () => canvasRequestScopeRef.current === requestScope
      if (requestScope.key !== canvasScopeKey) return
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      let node = readNodes().find((item) => item.id === nodeId)
      if (!node || node.data.eyebrow !== "prompt.storyboard") {
        toast.info("请选择片段剧本")
        return
      }
      try {
        const fresh = await prepareWorkflow()
        if (!currentScope()) return
        node = fresh.nodes.find((item) => item.id === nodeId) ?? node
        node = await canvasDetails.hydrateForRun(node)
        if (!currentScope()) return
      } catch (error) {
        if (!currentScope()) return
        toast.error(errMsg(error, "刷新最新配置失败"))
        return
      }
      if (!storyboardSourceFactTextForNode(node.data).trim()) {
        toast.info("缺少原文事实")
        return
      }
      if (
        taskLifecycle.launching().has(node.id) ||
        Boolean(findBlockingWorkflowTaskForNode(taskLifecycle.tasks, node.id))
      ) {
        toast.info("当前片段剧本正在生成")
        return
      }
      const userInstruction = String(options.userInstruction ?? "")
      const routeId = String(node.data.routeId ?? "").trim()
      const workChainId = String(node.data.workChainId ?? "").trim()
      if (!routeId || !workChainId) {
        toast.info("当前片段剧本缺少工作链定位信息")
        return
      }
      if (!onRequestCanvasAgentTask) {
        toast.info("当前画布尚未连接智能体会话")
        return
      }
      onLaunch()
      onRequestCanvasAgentTask({
        taskType: "workflow_cinematic_script_generation",
        projectId,
        episodeId,
        nodeId,
        routeId,
        workChainId,
        scriptTemplateId: options.scriptTemplateId ?? storyboardScriptTemplateValue(node.data),
        userInstruction: userInstruction.trim(),
      })
    },
    [
      backendReady,
      callBackend,
      projectId,
      episodeId,
      canvasScopeKey,
      readNodes,
      prepareWorkflow,
      canvasDetails.hydrateForRun,
      taskLifecycle.setLaunching,
      taskLifecycle.launching,
      taskLifecycle.tasks,
      taskLifecycle.mergeEvent,
      taskLifecycle.refresh,
      onTaskAccepted,
      applyMutation,
      onLaunch,
      onRequestCanvasAgentTask,
    ]
  )

  const handleGenerateDirectorPlan = useCallback(
    async (nodeId: string, options: { userInstruction?: string; reworkRecordIds?: string[] } = {}) => {
      const requestScope = canvasRequestScopeRef.current
      const currentScope = () => canvasRequestScopeRef.current === requestScope
      if (requestScope.key !== canvasScopeKey) return false
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return false
      }
      let node = readNodes().find((item) => item.id === nodeId)
      if (!node || !isDirectorBoardNodeType(node.data.eyebrow)) {
        toast.info("请选择分镜脚本")
        return false
      }
      let runNodes: StoryboardNode[]
      try {
        const fresh = await prepareWorkflow()
        if (!currentScope()) return false
        runNodes = fresh.nodes
        node = fresh.nodes.find((item) => item.id === nodeId) ?? node
        node = await canvasDetails.hydrateForRun(node)
        if (!currentScope()) return false
      } catch (error) {
        if (!currentScope()) return false
        toast.error(errMsg(error, "刷新最新配置失败"))
        return false
      }
      const scriptNode = workflowScriptCreationNodeForScope(runNodes, node)
      if (!scriptNode || !storyboardShootableContentReadyForNode(scriptNode.data)) {
        toast.info(scriptNode ? "请先填写原文或剧本" : "当前工作链缺少片段剧本")
        return false
      }
      if (taskLifecycle.launching().has(node.id) ||
          findBlockingWorkflowTaskForNode(taskLifecycle.tasks, node.id)) {
        toast.info("当前分镜脚本正在执行")
        return false
      }
      const routeId = String(node.data.routeId ?? "").trim()
      const workChainId = String(node.data.workChainId ?? "").trim()
      if (!routeId || !workChainId) {
        toast.info("当前分镜脚本缺少工作链定位信息")
        return false
      }
      if (!onRequestCanvasAgentTask) {
        toast.info("当前画布尚未连接智能体会话")
        return false
      }
      onLaunch()
      return onRequestCanvasAgentTask({
        taskType: "director_plan_generation",
        projectId,
        episodeId,
        nodeId,
        routeId,
        workChainId,
        userInstruction: options.userInstruction?.trim() ?? "",
        reworkRecordIds: options.reworkRecordIds,
      })
    },
    [backendReady, canvasScopeKey, projectId, episodeId, readNodes, prepareWorkflow,
      canvasDetails.hydrateForRun, taskLifecycle.launching, taskLifecycle.tasks,
      onLaunch, onRequestCanvasAgentTask]
  )

  const handleGenerateFinalVideoPrompt = useCallback(
    async (nodeId: string) => {
      const normalizedNodeId = nodeId.trim()
      if (!normalizedNodeId) return
      const requestScope = canvasRequestScopeRef.current
      const currentScope = () => canvasRequestScopeRef.current === requestScope
      if (requestScope.key !== canvasScopeKey) return
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      let node = readNodes().find((item) => item.id === normalizedNodeId)
      if (!node || !isWorkflowVideoTaskType(node.data.eyebrow)) {
        toast.info("请先选择视频生成")
        return
      }
      if (
        taskLifecycle.launching().has(normalizedNodeId) ||
        findBlockingWorkflowTaskForNode(taskLifecycle.tasks, normalizedNodeId)
      ) {
        toast.info("当前视频生成正在执行任务")
        return
      }
      try {
        const fresh = await prepareWorkflow()
        if (!currentScope()) return
        node = fresh.nodes.find((item) => item.id === normalizedNodeId) ?? node
        node = await canvasDetails.hydrateForRun(node)
        if (!currentScope()) return
      } catch (error) {
        if (!currentScope()) return
        toast.error(errMsg(error, "刷新最新配置失败"))
        return
      }
      const workChainId = String(node.data.workChainId ?? "").trim()
      if (node.data.eyebrow === "video.storyboard" && workChainId) {
        const routeId = String(node.data.routeId ?? "").trim()
        if (!routeId) {
          toast.info("当前视频节点缺少工作链定位信息")
          return
        }
        if (!onRequestCanvasAgentTask) {
          toast.info("当前画布尚未连接智能体会话")
          return
        }
        onLaunch()
        onRequestCanvasAgentTask({
          taskType: "video_prompt_generation",
          projectId,
          episodeId,
          nodeId: normalizedNodeId,
          routeId,
          workChainId,
        })
        return
      }
      if (!onRequestCanvasAgentTask) {
        toast.info("当前画布尚未连接智能体会话")
        return
      }
      onLaunch()
      onRequestCanvasAgentTask({
        taskType: "video_prompt_standalone_generation",
        projectId,
        episodeId,
        nodeId: normalizedNodeId,
        nodeType: node.data.eyebrow as "video.storyboard" | "video.keyframe",
      })
    },
    [
      backendReady,
      callBackend,
      projectId,
      episodeId,
      canvasScopeKey,
      readNodes,
      prepareWorkflow,
      canvasDetails.hydrateForRun,
      onRequestCanvasAgentTask,
      taskLifecycle.setLaunching,
      taskLifecycle.launching,
      taskLifecycle.tasks,
      taskLifecycle.mergeEvent,
      taskLifecycle.refresh,
      onTaskAccepted,
      applyMutation,
      onLaunch,
    ]
  )

  return {
    generateStoryboardImage: handleGenerateStoryboardImageFromDirector,
    generateVisualHandoffImage: handleGenerateVisualHandoffImage,
    generateCinematicScript: handleGenerateCinematicScript,
    generateDirectorPlan: handleGenerateDirectorPlan,
    generateFinalVideoPrompt: handleGenerateFinalVideoPrompt,
  }
}
