import { type AssetItem, type TaskRow, type WorkflowWorkChain } from "@/backend"
import {
  WORKFLOW_VIDEO_TASK_SCOPE_MISSING_MESSAGE,
  canOpenCanvasImageEditor,
  isEditableCanvasImageNode,
  isWorkChainStoryboardResultImageNode,
  isWorkflowVersionHistoryVisible,
  workflowAssetRenameKind,
  workflowVideoTaskCardIsReady,
} from "./workflow-canvas-asset-model"
import {
  type CanvasProjectAssetType,
  canvasAssetNodeInProjectLibrary,
  canvasAssetNodeReferencesSplitAsset,
  canvasProjectAssetTypeFromNode,
} from "./workflow-canvas-assets"
import {
  type StoryboardNode,
  directorPlanTextForNode,
  isDirectorBoardNodeType,
  isWorkflowItemLocked,
  isWorkflowVideoTaskType,
  promptTextForNode,
  workflowNodeWorkChainId,
  workflowVideoTaskScope,
} from "./workflow-canvas-model"
import {
  workflowVideoTaskFinalPromptNotReadyMessage,
  workflowVideoTaskHasDurationSetting,
  workflowVideoTaskHasManualImageReference,
  workflowVideoTaskHasManualPrompt,
  workflowVideoTaskStandaloneInputNotReadyMessage,
} from "./workflow-input-readiness"
import {
  isContextRunnableWorkflowNode,
  isWorkflowContextCopyVisible,
  isWorkflowContextDeleteLocked,
  isWorkflowContextDeleteVisible,
  isWorkflowEditHistoryVisible,
  isWorkflowVideoClipSourceNode,
  storyboardResultImageHasGeneratedMedia,
  workflowStoryboardResultsForCardNode,
  workflowStoryboardResultForScopeNode,
} from "./workflow-node-relations"
import {
  storyboardShootableContentReadyForNode,
  storyboardSourceFactTextForNode,
} from "./workflow-prompt-node-model"
import {
  findBlockingWorkflowTaskForNode,
  workflowStatusTaskType,
} from "./workflow-task-status"

export interface WorkflowNodeContextMenuInput {
  node?: StoryboardNode
  nodes: StoryboardNode[]
  tasks: TaskRow[]
  launchingNodeIds: ReadonlySet<string>
  backendReady: boolean
  assetRowsByType: Partial<Record<CanvasProjectAssetType, AssetItem[]>>
  addingAssetLibraryNodeId: string | null
  workChains?: WorkflowWorkChain[]
}

export function buildWorkflowNodeContextMenu({
  node: contextMenuNode,
  nodes,
  tasks: workflowStatusTasks,
  launchingNodeIds: runningNodeIds,
  backendReady,
  assetRowsByType: contextAssetRowsByType,
  addingAssetLibraryNodeId,
  workChains,
}: WorkflowNodeContextMenuInput) {
  const contextMenuNodeLocked = isWorkflowItemLocked(contextMenuNode?.data)
  const contextMenuNodeDeleteLocked =
    isWorkflowContextDeleteLocked(contextMenuNode)
  const contextMenuNodeCanRun = contextMenuNode
    ? isContextRunnableWorkflowNode(contextMenuNode)
    : false
  const contextMenuNodeRunningTask = contextMenuNode
    ? findBlockingWorkflowTaskForNode(workflowStatusTasks, contextMenuNode.id)
    : undefined
  const contextMenuNodeRunLaunching = contextMenuNode
    ? runningNodeIds.has(contextMenuNode.id)
    : false
  const contextMenuNodeBusy =
    contextMenuNodeRunLaunching || Boolean(contextMenuNodeRunningTask)
  const contextMenuNodeIsDirectorBoard = Boolean(
    contextMenuNode && isDirectorBoardNodeType(contextMenuNode.data.eyebrow)
  )
  const contextMenuStoryboardCardResult = contextMenuNode?.data.eyebrow === "storyboard.card"
    ? (() => {
        const results = workflowStoryboardResultsForCardNode(nodes, contextMenuNode)
        return results.find(storyboardResultImageHasGeneratedMedia) ?? results[0]
      })()
    : undefined
  const contextMenuSameScopeNode = (
    predicate: (node: StoryboardNode) => boolean
  ) => {
    if (!contextMenuNode) return undefined
    const routeId = String(contextMenuNode.data.routeId ?? "")
    const workChainId = String(contextMenuNode.data.workChainId ?? "")
    return nodes.find((node) => {
      if (!predicate(node)) return false
      if (routeId && String(node.data.routeId ?? "") === routeId) return true
      return Boolean(
        workChainId && String(node.data.workChainId ?? "") === workChainId
      )
    })
  }
  const contextMenuDirectorStoryboardTask = contextMenuNodeIsDirectorBoard
    ? contextMenuSameScopeNode(
        (node) => node.data.eyebrow === "prompt.storyboard"
      )
    : undefined
  const contextMenuNodeRunningTaskType = String(
    contextMenuNodeRunningTask?.generationTaskType ||
      contextMenuNodeRunningTask?.type ||
      ""
  ).trim()
  const contextMenuStoryboardMissingShootableContent = Boolean(
    contextMenuNode?.data.eyebrow === "prompt.storyboard" &&
    !storyboardShootableContentReadyForNode(contextMenuNode.data)
  )
  const contextMenuNodeRunDisabled =
    contextMenuNodeBusy || contextMenuStoryboardMissingShootableContent
  const contextMenuNodeRunDisabledTitle = (() => {
    if (contextMenuNodeBusy) return "当前任务正在执行"
    if (contextMenuStoryboardMissingShootableContent)
      return "请先填写原文或剧本"
    return undefined
  })()
  const contextMenuNodeCanGenerateCinematicScript = Boolean(
    contextMenuNode?.data.eyebrow === "prompt.storyboard" &&
    contextMenuNode.data.onGenerateCinematicScript
  )
  const contextMenuNodeSourceFactReady = Boolean(
    contextMenuNodeCanGenerateCinematicScript &&
    contextMenuNode &&
    storyboardSourceFactTextForNode(contextMenuNode.data).trim()
  )
  const contextMenuCinematicScriptDisabled =
    !backendReady || contextMenuNodeBusy || !contextMenuNodeSourceFactReady
  const contextMenuCinematicScriptDisabledTitle = (() => {
    if (!contextMenuNodeCanGenerateCinematicScript) return undefined
    if (!backendReady) return "后端尚未就绪"
    if (contextMenuNodeBusy) return "当前任务正在执行"
    if (!contextMenuNodeSourceFactReady) return "缺少原文事实"
    return undefined
  })()
  const contextMenuCinematicScriptRunning = Boolean(
    contextMenuNodeCanGenerateCinematicScript &&
    (contextMenuNodeRunLaunching ||
      contextMenuNodeRunningTaskType === "workflow_cinematic_script")
  )
  const contextMenuNodeCanGenerateVisualHandoff = Boolean(
    contextMenuNode?.data.eyebrow === "storyboard.card" && contextMenuNode.data.shotGroupId
  )
  const contextMenuDirectorStoryboardResult =
    contextMenuNodeIsDirectorBoard && contextMenuNode
      ? workflowStoryboardResultForScopeNode(nodes, contextMenuNode)
      : undefined
  const contextMenuDirectorStoryboardResultTask =
    contextMenuDirectorStoryboardResult
      ? findBlockingWorkflowTaskForNode(
          workflowStatusTasks,
          contextMenuDirectorStoryboardResult.id
        )
      : undefined
  const contextMenuDirectorStoryboardResultTaskType = workflowStatusTaskType(
    contextMenuDirectorStoryboardResultTask
  )
  const contextMenuDirectorStoryboardRunning = Boolean(
    contextMenuDirectorStoryboardResult &&
    (runningNodeIds.has(contextMenuDirectorStoryboardResult.id) ||
      contextMenuDirectorStoryboardResultTaskType === "storyboard_image" ||
      contextMenuDirectorStoryboardResultTaskType ===
        "storyboard_image_generation")
  )
  const contextMenuVisualHandoffStoryboardImageReady = Boolean(
    contextMenuNodeCanGenerateVisualHandoff &&
    storyboardResultImageHasGeneratedMedia(contextMenuStoryboardCardResult)
  )
  const contextMenuStoryboardCardResultBusy = Boolean(
    contextMenuStoryboardCardResult &&
    (runningNodeIds.has(contextMenuStoryboardCardResult.id) ||
      findBlockingWorkflowTaskForNode(workflowStatusTasks, contextMenuStoryboardCardResult.id))
  )
  const contextMenuVisualHandoffDisabled =
    !backendReady ||
    contextMenuNodeBusy ||
    contextMenuStoryboardCardResultBusy ||
    !contextMenuVisualHandoffStoryboardImageReady
  const contextMenuVisualHandoffDisabledTitle = (() => {
    if (!contextMenuNodeCanGenerateVisualHandoff) return undefined
    if (!backendReady) return "后端尚未就绪"
    if (contextMenuNodeBusy || contextMenuStoryboardCardResultBusy) return "当前任务正在执行"
    if (!contextMenuVisualHandoffStoryboardImageReady)
      return "请先生成此分镜单元的分镜图"
    return undefined
  })()
  const contextMenuNodeCanCopyAsset = contextMenuNode
    ? isWorkflowContextCopyVisible(contextMenuNode)
    : false
  const contextMenuNodeCanShowEditHistory = contextMenuNode
    ? isWorkflowEditHistoryVisible(contextMenuNode)
    : false
  const contextMenuNodeCanShowVersionHistory = contextMenuNode
    ? isWorkflowVersionHistoryVisible(contextMenuNode)
    : false
  const contextMenuNodeCanEditStoryboardImage =
    isWorkChainStoryboardResultImageNode(contextMenuNode) && canOpenCanvasImageEditor(contextMenuNode)
  const contextMenuNodeCanEditImageAsset = Boolean(
    contextMenuNode &&
    canOpenCanvasImageEditor(contextMenuNode) &&
    !contextMenuNodeCanEditStoryboardImage
  )
  const contextMenuNodeProjectAssetType =
    canvasProjectAssetTypeFromNode(contextMenuNode)
  const contextMenuNodeProjectAssetRows = contextMenuNodeProjectAssetType
    ? contextAssetRowsByType[contextMenuNodeProjectAssetType]
    : undefined
  const contextMenuNodeCanAddToAssetLibrary = Boolean(
    contextMenuNode &&
    isEditableCanvasImageNode(contextMenuNode) &&
    contextMenuNodeProjectAssetType
  )
  const contextMenuNodeAssetInLibrary = canvasAssetNodeInProjectLibrary(
    contextMenuNode,
    contextMenuNodeProjectAssetRows
  )
  const contextMenuAssetRowsReady =
    !contextMenuNodeProjectAssetType ||
    Array.isArray(contextMenuNodeProjectAssetRows)
  const contextMenuNodeRenameKind = workflowAssetRenameKind(contextMenuNode)
  const contextMenuNodeCanRenameAsset = Boolean(contextMenuNodeRenameKind)
  const contextMenuNodeProjectAssetSource =
    contextMenuNode?.data.sourceType === "asset"
  const contextMenuNodeProjectAssetId = String(
    contextMenuNode?.data.assetId ?? ""
  ).trim()
  const contextMenuNodeProjectAssetIdentityMissing = Boolean(
    contextMenuNodeProjectAssetSource &&
    (!contextMenuNodeProjectAssetId || !contextMenuNodeProjectAssetType)
  )
  const contextMenuNodeDirectProjectAsset = Boolean(
    contextMenuNodeProjectAssetSource && contextMenuNodeProjectAssetId
  )
  const contextMenuRenameAssetRowsReady =
    !contextMenuNodeDirectProjectAsset ||
    !contextMenuNodeProjectAssetType ||
    Array.isArray(contextMenuNodeProjectAssetRows)
  const contextMenuNodeSplitAssetProtected =
    canvasAssetNodeReferencesSplitAsset(
      contextMenuNode,
      contextMenuNodeProjectAssetRows
    )
  const contextMenuRenameAssetDisabled =
    !backendReady ||
    contextMenuNodeLocked ||
    contextMenuNodeProjectAssetIdentityMissing ||
    !contextMenuRenameAssetRowsReady ||
    contextMenuNodeSplitAssetProtected
  const contextMenuRenameAssetDisabledTitle = (() => {
    if (!contextMenuNodeCanRenameAsset) return undefined
    if (!backendReady) return "后端尚未就绪"
    if (contextMenuNodeLocked) return "该节点已锁定"
    if (contextMenuNodeProjectAssetIdentityMissing) {
      return "资产来源信息不完整，不能重命名"
    }
    if (!contextMenuRenameAssetRowsReady) return "正在校验资产来源"
    if (contextMenuNodeSplitAssetProtected) {
      return "拆分资产参与自动关联，不能重命名"
    }
    return undefined
  })()
  const contextMenuAddAssetLibraryBusy = Boolean(
    contextMenuNode && addingAssetLibraryNodeId === contextMenuNode.id
  )
  const contextMenuAddAssetLibraryDisabled =
    !backendReady ||
    contextMenuNodeLocked ||
    contextMenuNodeAssetInLibrary ||
    !contextMenuAssetRowsReady ||
    contextMenuAddAssetLibraryBusy
  const contextMenuAddAssetLibraryDisabledTitle = (() => {
    if (!contextMenuNodeCanAddToAssetLibrary) return undefined
    if (!backendReady) return "后端尚未就绪"
    if (contextMenuNodeLocked) return "该节点已锁定"
    if (contextMenuNodeAssetInLibrary) return "当前项目资产库已存在该资产"
    if (!contextMenuAssetRowsReady) return "正在校验资产库"
    if (contextMenuAddAssetLibraryBusy) return "正在加入资产库"
    return undefined
  })()
  const contextMenuNodeIsVideoTask = contextMenuNode
    ? isWorkflowVideoTaskType(contextMenuNode.data.eyebrow)
    : false
  const contextMenuNodeCanClipVideo = contextMenuNode
    ? isWorkflowVideoClipSourceNode(contextMenuNode)
    : false
  const contextMenuNodeVideoTaskScope =
    contextMenuNodeIsVideoTask && contextMenuNode
      ? workflowVideoTaskScope(contextMenuNode)
      : ""
  const contextMenuNodeManualImageReady = Boolean(
    contextMenuNodeIsVideoTask &&
    contextMenuNodeVideoTaskScope === "standalone" &&
    workflowVideoTaskHasManualImageReference(contextMenuNode, nodes)
  )
  const contextMenuNodeManualPromptReady = Boolean(
    contextMenuNodeIsVideoTask &&
    workflowVideoTaskHasManualPrompt(contextMenuNode)
  )
  const contextMenuNodeManualDurationReady = Boolean(
    contextMenuNodeIsVideoTask &&
    workflowVideoTaskHasDurationSetting(contextMenuNode)
  )
  const contextMenuNodeManualVideoReady = Boolean(
    contextMenuNodeIsVideoTask &&
    contextMenuNodeVideoTaskScope === "standalone" &&
    contextMenuNodeManualImageReady &&
    contextMenuNodeManualPromptReady &&
    contextMenuNodeManualDurationReady
  )
  const contextMenuNodeVideoPromptSyncing = Boolean(
    contextMenuNodeIsVideoTask && contextMenuNode?.data.videoPromptSyncing
  )
  const contextMenuFinalVideoRunning = Boolean(
    contextMenuNodeIsVideoTask &&
    contextMenuNodeRunningTask &&
    ["storyboard_video", "route_video", "storyboard_video_generation"].includes(
      contextMenuNodeRunningTaskType
    )
  )
  const contextMenuVideoTaskBusy =
    contextMenuNodeRunLaunching || Boolean(contextMenuNodeRunningTask)
  const contextMenuNodeCanGenerateFinalVideoPrompt = Boolean(
    contextMenuNodeIsVideoTask &&
    contextMenuNodeVideoTaskScope === "work_chain" &&
    contextMenuNode?.data.onGenerateFinalVideoPrompt
  )
  const contextMenuFinalVideoPromptExists = Boolean(
    contextMenuNodeIsVideoTask &&
    contextMenuNode &&
    promptTextForNode(contextMenuNode.data).trim()
  )
  const contextMenuGenerateFinalVideoPromptDisabled =
    !contextMenuNodeCanGenerateFinalVideoPrompt ||
    !backendReady ||
    contextMenuVideoTaskBusy ||
    contextMenuNodeVideoPromptSyncing ||
    !contextMenuNodeVideoTaskScope
  const contextMenuGenerateFinalVideoPromptDisabledTitle = (() => {
    if (!contextMenuNodeIsVideoTask) return undefined
    if (contextMenuNodeVideoTaskScope === "standalone") {
      return "独立视频生成直接使用用户填写的提示词"
    }
    if (!contextMenuNodeCanGenerateFinalVideoPrompt) {
      return "当前节点不支持生成视频提示词"
    }
    if (!backendReady) return "后端尚未就绪"
    if (contextMenuVideoTaskBusy) return "当前任务正在执行"
    if (contextMenuNodeVideoPromptSyncing) return "视频提示词正在生成"
    if (!contextMenuNodeVideoTaskScope) {
      return WORKFLOW_VIDEO_TASK_SCOPE_MISSING_MESSAGE
    }
    return contextMenuFinalVideoPromptExists
      ? "根据当前来源重新生成视频提示词"
      : "根据当前来源生成视频提示词"
  })()
  const contextMenuWorkChainVideoReady = Boolean(
    contextMenuNodeIsVideoTask &&
    contextMenuNodeVideoTaskScope === "work_chain" &&
    workflowVideoTaskCardIsReady(contextMenuNode) &&
    !contextMenuNodeVideoPromptSyncing
  )
  const contextMenuFinalVideoDisabled =
    !contextMenuNodeIsVideoTask ||
    contextMenuVideoTaskBusy ||
    contextMenuNodeVideoPromptSyncing ||
    !contextMenuNodeVideoTaskScope ||
    (!contextMenuWorkChainVideoReady &&
      !contextMenuNodeManualVideoReady)
  const contextMenuFinalVideoDisabledTitle = (() => {
    if (!contextMenuNodeIsVideoTask || contextMenuVideoTaskBusy)
      return undefined
    if (contextMenuNodeVideoPromptSyncing) {
      return "视频生成最终提示词正在更新，请稍后再生成"
    }
    if (!contextMenuNodeVideoTaskScope) {
      return WORKFLOW_VIDEO_TASK_SCOPE_MISSING_MESSAGE
    }
    if (contextMenuNodeVideoTaskScope === "work_chain") {
      if (!workflowVideoTaskCardIsReady(contextMenuNode)) {
        return workflowVideoTaskFinalPromptNotReadyMessage(contextMenuNode)
      }
      return undefined
    }
    return contextMenuNodeManualVideoReady
      ? undefined
      : workflowVideoTaskStandaloneInputNotReadyMessage(contextMenuNode, nodes)
  })()
  const contextMenuDirectorMissingShootableContent = Boolean(
    contextMenuNodeIsDirectorBoard &&
    (!contextMenuDirectorStoryboardTask ||
      !storyboardShootableContentReadyForNode(
        contextMenuDirectorStoryboardTask.data
      ))
  )
  const contextMenuDirectorPlanReady = Boolean(
    contextMenuNodeIsDirectorBoard &&
    contextMenuNode &&
    directorPlanTextForNode(contextMenuNode.data).trim()
  )
  const contextMenuDirectorPlanDisabled =
    !backendReady ||
    !contextMenuNodeIsDirectorBoard ||
    contextMenuNodeBusy ||
    contextMenuDirectorMissingShootableContent
  const contextMenuDirectorStoryboardDisabled =
    !backendReady ||
    !contextMenuNodeIsDirectorBoard ||
    contextMenuNodeBusy ||
    !contextMenuDirectorPlanReady ||
    contextMenuDirectorStoryboardRunning
  const contextMenuDirectorStoryboardDisabledTitle = (() => {
    if (!contextMenuNodeIsDirectorBoard) return undefined
    if (!backendReady) return "后端尚未就绪"
    if (contextMenuNodeBusy) return "当前任务正在执行"
    if (!contextMenuDirectorPlanReady) return "请先填写或生成分镜脚本"
    if (contextMenuDirectorStoryboardRunning) return "分镜图正在生成"
    return undefined
  })()
  const contextMenuDirectorPlanDisabledTitle = (() => {
    if (!contextMenuNodeIsDirectorBoard) return undefined
    if (!backendReady) return "后端尚未就绪"
    if (contextMenuNodeBusy) return "当前任务正在执行"
    if (!contextMenuDirectorStoryboardTask) return "当前工作链缺少片段剧本"
    if (
      !storyboardShootableContentReadyForNode(
        contextMenuDirectorStoryboardTask.data
      )
    ) {
      return "请先填写原文或剧本"
    }
    return undefined
  })()
  const contextMenuIndependentChain =
    contextMenuNode?.data.eyebrow === "prompt.storyboard"
      ? workChains?.find(
          (chain) =>
            chain.id === workflowNodeWorkChainId(contextMenuNode) &&
            (chain.origin?.kind === "independent" || chain.origin?.kind === "independent_source")
        )
      : undefined
  const contextMenuNodeCanShowDelete = contextMenuNode
    ? isWorkflowContextDeleteVisible(contextMenuNode)
    : false
  return {
    contextMenuAddAssetLibraryBusy,
    contextMenuAddAssetLibraryDisabled,
    contextMenuAddAssetLibraryDisabledTitle,
    contextMenuCinematicScriptDisabled,
    contextMenuCinematicScriptDisabledTitle,
    contextMenuCinematicScriptRunning,
    contextMenuDirectorPlanDisabled,
    contextMenuDirectorPlanDisabledTitle,
    contextMenuDirectorStoryboardDisabled,
    contextMenuDirectorStoryboardDisabledTitle,
    contextMenuDirectorStoryboardRunning,
    contextMenuFinalVideoDisabled,
    contextMenuFinalVideoDisabledTitle,
    contextMenuFinalVideoPromptExists,
    contextMenuFinalVideoRunning,
    contextMenuGenerateFinalVideoPromptDisabled,
    contextMenuGenerateFinalVideoPromptDisabledTitle,
    contextMenuIndependentChain,
    contextMenuNode,
    contextMenuNodeBusy,
    contextMenuNodeCanAddToAssetLibrary,
    contextMenuNodeCanClipVideo,
    contextMenuNodeCanCopyAsset,
    contextMenuNodeCanEditImageAsset,
    contextMenuNodeCanEditStoryboardImage,
    contextMenuNodeCanGenerateCinematicScript,
    contextMenuNodeCanRenameAsset,
    contextMenuNodeCanRun,
    contextMenuNodeCanShowDelete,
    contextMenuNodeCanShowEditHistory,
    contextMenuNodeCanShowVersionHistory,
    contextMenuNodeDeleteLocked,
    contextMenuNodeIsDirectorBoard,
    contextMenuNodeCanGenerateVisualHandoff,
    contextMenuStoryboardCardResult,
    contextMenuNodeIsVideoTask,
    contextMenuNodeRunDisabled,
    contextMenuNodeRunDisabledTitle,
    contextMenuNodeRunningTask,
    contextMenuNodeRunningTaskType,
    contextMenuNodeVideoPromptSyncing,
    contextMenuNodeVideoTaskScope,
    contextMenuRenameAssetDisabled,
    contextMenuRenameAssetDisabledTitle,
    contextMenuVisualHandoffDisabled,
    contextMenuVisualHandoffDisabledTitle,
    contextMenuNodeProjectAssetType,
  }
}

export type WorkflowNodeContextMenuModel = ReturnType<
  typeof buildWorkflowNodeContextMenu
>
