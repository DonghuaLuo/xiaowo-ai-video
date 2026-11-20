import { assertWorkflowTaskAccepted } from "./workflow-task-status"
import { useCallback } from "react"
import {
  WORKFLOW_VIDEO_TASK_SCOPE_MISSING_MESSAGE,
  workflowVideoTaskCardIsReady,
} from "./workflow-canvas-asset-model"
import {
  isDirectorBoardNodeType,
  isWorkflowVideoTaskType,
  toBackendNode,
  workflowVideoTaskScope,
  type StoryboardEdge,
  type StoryboardNode,
} from "./workflow-canvas-model"
import {
  workflowVideoTaskStandaloneInputNotReadyMessage,
  workflowVideoTaskWorkChainPromptNotReadyMessage,
} from "./workflow-input-readiness"
import {
  storyboardSourceFactTextForNode,
} from "./workflow-prompt-node-model"
import {
  findBlockingWorkflowTaskForNode,
  localWorkflowLaunchTaskType,
} from "./workflow-task-status"
import { toast } from "sonner"
import { runNodeGeneration } from "@/backend"
import { errMsg } from "@/shared/backend-result"
import {
  workflowTaskHasGeneratedResult,
  workflowVideoTaskCanRunStandaloneVideo,
  orderedRunnableNodes,
  routeRunnableNodes,
} from "./workflow-node-generation-model"
import type { BackendCaller, EpisodeWorkflow, TaskRow } from "@/backend"
import type { WorkflowCanvasDocument } from "./workflow-canvas-document"
import type { WorkflowCanvasDetails } from "./use-workflow-canvas-details"
import type { WorkflowTaskLifecycle } from "./use-workflow-task-lifecycle"
import type { WorkflowGenerationPreflight } from "./use-workflow-generation-preflight"
export function useWorkflowNodeGeneration({
  projectId,
  episodeId,
  backendReady,
  callBackend,
  canvasDocument,
  canvasDetails,
  taskLifecycle,
  preflight,
  prepareWorkflow,
  onTaskAccepted,
  generateScript,
  generateDirectorPlan,
}: {
  projectId: string
  episodeId: string
  backendReady: boolean
  callBackend: BackendCaller
  canvasDocument: WorkflowCanvasDocument
  canvasDetails: WorkflowCanvasDetails
  taskLifecycle: WorkflowTaskLifecycle
  preflight: WorkflowGenerationPreflight
  prepareWorkflow: () => Promise<{
    workflow: EpisodeWorkflow
    nodes: StoryboardNode[]
    edges: StoryboardEdge[]
  }>
  onTaskAccepted: (task: TaskRow) => void
  generateScript: (nodeId: string) => Promise<void>
  generateDirectorPlan: (nodeId: string) => Promise<boolean>
}) {
  const canvasScopeKey = `${projectId}\u0000${episodeId}`
  const runNode = useCallback(
    async (nodeId: string) => {
      const requestScope = canvasDocument.scope
      const currentScope = () => canvasDocument.scope === requestScope
      if (requestScope.key !== canvasScopeKey) return
      const { nodes, edges } = canvasDocument.read()
      const fallbackNode = nodes.find((item) => item.id === nodeId)
      const launchingNodeIds = taskLifecycle.launching()
      if (!fallbackNode || launchingNodeIds.has(nodeId)) {
        return
      }
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const activeTask = findBlockingWorkflowTaskForNode(
        taskLifecycle.tasks,
        nodeId
      )
      if (activeTask) {
        return
      }
      if (fallbackNode.data.eyebrow === "prompt.storyboard") {
        await generateScript(nodeId)
        if (!currentScope()) return
        return
      }
      if (isDirectorBoardNodeType(fallbackNode.data.eyebrow)) {
        await generateDirectorPlan(nodeId)
        return
      }
      taskLifecycle.setLaunching(
        nodeId,
        true,
        localWorkflowLaunchTaskType(fallbackNode, nodes, edges)
      )
      let node = fallbackNode
      if (fallbackNode.data.eyebrow === "source.text") {
        let runNodes = nodes
        let runEdges = edges
        try {
          const fresh = await prepareWorkflow()
          if (!currentScope()) return
          runNodes = fresh.nodes
          runEdges = fresh.edges
          node = fresh.nodes.find((item) => item.id === nodeId) ?? fallbackNode
        } catch (error) {
          if (!currentScope()) return
          toast.error(errMsg(error, "刷新最新配置失败"))
          taskLifecycle.setLaunching(nodeId, false)
          return
        }
        const ordered =
          node.data.eyebrow === "source.text"
            ? orderedRunnableNodes(runNodes, runEdges)
            : routeRunnableNodes(
                String(node.data.routeId ?? ""),
                runNodes,
                runEdges
              )
        if (!ordered.length) {
          if (node.data.eyebrow === "source.text") {
            toast.info("请通过智能体对话生成当前集工作链计划")
            taskLifecycle.setLaunching(nodeId, false)
            return
          }
          toast.info(
            node.data.eyebrow === "source.text"
              ? "当前分集暂无可运行工作链节点"
              : "本条工作链暂无可运行节点"
          )
          taskLifecycle.setLaunching(nodeId, false)
          return
        }
        let nextNode = ordered.find(
          (item) => !workflowTaskHasGeneratedResult(item, runNodes, runEdges)
        )
        if (!nextNode) {
          toast.success(
            node.data.eyebrow === "source.text"
              ? "当前工作流已完成"
              : "这条工作链已完成"
          )
          taskLifecycle.setLaunching(nodeId, false)
          return
        }
        nextNode = await canvasDetails.hydrateForRun(nextNode)
        if (!currentScope()) return
        const nextNodeLaunchState = taskLifecycle.launching()
        if (nextNodeLaunchState.has(nextNode.id)) {
          taskLifecycle.setLaunching(nodeId, false)
          return
        }
        const nextNodeActiveTask = findBlockingWorkflowTaskForNode(
          taskLifecycle.tasks,
          nextNode.id
        )
        if (nextNodeActiveTask) {
          taskLifecycle.setLaunching(nodeId, false)
          return
        }
        if (nextNode.data.eyebrow === "prompt.storyboard") {
          try {
            await generateScript(nextNode.id)
          } finally {
            if (currentScope()) taskLifecycle.setLaunching(nodeId, false)
          }
          return
        }
        if (isDirectorBoardNodeType(nextNode.data.eyebrow)) {
          try {
            await generateDirectorPlan(nextNode.id)
          } finally {
            if (currentScope()) taskLifecycle.setLaunching(nodeId, false)
          }
          return
        }
        taskLifecycle.setLaunching(
          nextNode.id,
          true,
          localWorkflowLaunchTaskType(nextNode, runNodes, runEdges)
        )
        try {
          if (isWorkflowVideoTaskType(nextNode.data.eyebrow)) {
            const nextNodeVideoTaskScope = workflowVideoTaskScope(nextNode)
            if (!nextNodeVideoTaskScope) {
              toast.info(WORKFLOW_VIDEO_TASK_SCOPE_MISSING_MESSAGE)
              return
            }
            if (!workflowVideoTaskCardIsReady(nextNode)) {
              if (nextNodeVideoTaskScope === "standalone") {
                if (
                  !workflowVideoTaskCanRunStandaloneVideo(
                    nextNode,
                    runNodes,
                    runEdges
                  )
                ) {
                  toast.info(
                    workflowVideoTaskStandaloneInputNotReadyMessage(
                      nextNode,
                      runNodes
                    )
                  )
                  return
                }
              } else {
                toast.info(
                  workflowVideoTaskWorkChainPromptNotReadyMessage(
                    nextNode,
                    runNodes
                  )
                )
                return
              }
            }
          }
          const preflightPassed = await preflight.check(nextNode)
          if (!currentScope()) return
          if (!preflightPassed) {
            toast.info("已停止运行，请先处理预检问题")
            return
          }
          const task = await runNodeGeneration(
            callBackend,
            projectId,
            episodeId,
            {
              ...toBackendNode(nextNode),
            }
          )
          if (!currentScope()) return
          assertWorkflowTaskAccepted(task)
          taskLifecycle.mergeEvent(task)
          onTaskAccepted(task)
          void taskLifecycle.refresh()
        } catch (error) {
          if (!currentScope()) return
          toast.error(errMsg(error, "运行失败"))
          void taskLifecycle.refresh()
        } finally {
          if (!currentScope()) return
          taskLifecycle.setLaunching(nextNode.id, false)
          taskLifecycle.setLaunching(nodeId, false)
        }
        return
      }
      node = await canvasDetails.hydrateForRun(node)
      if (!currentScope()) return
      let runNodes = nodes
      let runEdges = edges
      if (
        isWorkflowVideoTaskType(node.data.eyebrow)
      ) {
        try {
          const fresh = await prepareWorkflow()
          if (!currentScope()) return
          runNodes = fresh.nodes
          runEdges = fresh.edges
          const freshNode = fresh.nodes.find((item) => item.id === nodeId)
          if (freshNode) {
            node = await canvasDetails.hydrateForRun(freshNode)
            if (!currentScope()) return
          }
        } catch (error) {
          if (!currentScope()) return
          toast.error(errMsg(error, "刷新最新配置失败"))
          taskLifecycle.setLaunching(nodeId, false)
          return
        }
      }
      if (isWorkflowVideoTaskType(node.data.eyebrow)) {
        const nodeVideoTaskScope = workflowVideoTaskScope(node)
        if (!nodeVideoTaskScope) {
          toast.info(WORKFLOW_VIDEO_TASK_SCOPE_MISSING_MESSAGE)
          taskLifecycle.setLaunching(nodeId, false)
          return
        }
        if (!workflowVideoTaskCardIsReady(node)) {
          if (nodeVideoTaskScope === "standalone") {
            if (
              !workflowVideoTaskCanRunStandaloneVideo(node, runNodes, runEdges)
            ) {
              toast.info(
                workflowVideoTaskStandaloneInputNotReadyMessage(node, runNodes)
              )
              taskLifecycle.setLaunching(nodeId, false)
              return
            }
          } else {
            toast.info(
              workflowVideoTaskWorkChainPromptNotReadyMessage(node, runNodes)
            )
            taskLifecycle.setLaunching(nodeId, false)
            return
          }
        }
      }
      if (
        node.data.eyebrow === "prompt.storyboard" &&
        !storyboardSourceFactTextForNode(node.data).trim()
      ) {
        toast.info("请先填写原文事实")
        taskLifecycle.setLaunching(nodeId, false)
        return
      }
      canvasDocument.updateNodes((current) =>
        current.map((item) =>
          item.id === nodeId
            ? { ...item, data: { ...item.data, status: "running" } }
            : item
        )
      )
      try {
        const preflightPassed = await preflight.check(node)
        if (!currentScope()) return
        if (!preflightPassed) {
          canvasDocument.updateNodes((current) =>
            current.map((item) =>
              item.id === node.id
                ? {
                    ...item,
                    data: {
                      ...item.data,
                      status:
                        item.data.status === "preflight_failed"
                          ? "preflight_failed"
                          : node.data.status,
                    },
                  }
                : item
            )
          )
          return
        }
        const task = await runNodeGeneration(
          callBackend,
          projectId,
          episodeId,
          {
            ...toBackendNode(node),
          }
        )
        if (!currentScope()) return
        assertWorkflowTaskAccepted(task)
        taskLifecycle.mergeEvent(task)
        onTaskAccepted(task)
        void taskLifecycle.refresh()
      } catch (error) {
        if (!currentScope()) return
        toast.error(errMsg(error, "运行节点失败"))
        void taskLifecycle.refresh()
      } finally {
        if (!currentScope()) return
        taskLifecycle.setLaunching(nodeId, false)
      }
    },
    [
      backendReady,
      callBackend,
      canvasDocument,
      canvasScopeKey,
      episodeId,
      projectId,
      canvasDetails.hydrateForRun,
      taskLifecycle.launching,
      taskLifecycle.setLaunching,
      taskLifecycle.tasks,
      taskLifecycle.mergeEvent,
      taskLifecycle.refresh,
      prepareWorkflow,
      preflight.check,
      onTaskAccepted,
      generateScript,
      generateDirectorPlan,
    ]
  )
  return { run: runNode }
}
