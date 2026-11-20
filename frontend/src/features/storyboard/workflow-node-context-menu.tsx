import { cn } from "@/lib/utils"
import {
  ClipboardList,
  Copy,
  History,
  ImagePlus,
  Layers3,
  Loader2,
  Maximize2,
  Package,
  PencilLine,
  Play,
  Scissors,
  Search,
  Trash2,
  Video,
  WandSparkles,
} from "lucide-react"
import { toast } from "sonner"
import {
  workflowVideoTaskCardIsReady,
  writeCanvasAssetClipboard,
  type CanvasAssetClipboardItem,
  type NodeContextMenuState,
  type NodeDetailsState,
} from "./workflow-canvas-asset-model"
import { type StoryboardNode } from "./workflow-canvas-model"
import type { WorkflowNodeContextMenuModel } from "./workflow-context-menu-model"
import {
  workflowContextDeleteLabel,
  workflowContextRunLabel,
  workflowContextRunningLabel,
} from "./workflow-task-status"

export interface WorkflowNodeContextMenuActions {
  close: () => void
  showDetails: (details: NodeDetailsState) => void
  editImage: (nodeId: string) => void
  openEditHistory: (nodeId: string) => Promise<void>
  openVersionHistory: (node: StoryboardNode) => void
  clipVideo: (node: StoryboardNode) => Promise<void>
  renameAsset: (node: StoryboardNode) => void
  generateVideoPrompt: (nodeId: string) => Promise<void>
  runNode: (nodeId: string) => Promise<void>
  addToAssetLibrary: (nodeId: string) => Promise<void>
  assetCopied: (clipboard: CanvasAssetClipboardItem) => void
  focusNode: (nodeId: string) => void
  generateCinematicScript: (nodeId: string) => Promise<void>
  generateStoryboardImage: (nodeId: string) => Promise<void>
  generateVisualHandoff: (nodeId: string) => Promise<void>
  requestDeleteChain: (chainId: string) => void
  deleteNode: (nodeId: string) => Promise<void>
}
export interface WorkflowNodeContextMenuProps {
  model: WorkflowNodeContextMenuModel
  position: NodeContextMenuState | null
  actions: WorkflowNodeContextMenuActions
  projectId: string
  episodeId: string
}

export function WorkflowNodeContextMenu({
  model,
  position: nodeContextMenu,
  actions,
  projectId,
  episodeId,
}: WorkflowNodeContextMenuProps) {
  const {
    contextMenuAddAssetLibraryBusy,
    contextMenuAddAssetLibraryDisabled,
    contextMenuAddAssetLibraryDisabledTitle,
    contextMenuCinematicScriptDisabled,
    contextMenuCinematicScriptDisabledTitle,
    contextMenuCinematicScriptRunning,
    contextMenuDirectorPlanDisabled,
    contextMenuDirectorPlanDisabledTitle,
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
  } = model
  return (
    <>
      {nodeContextMenu && contextMenuNode ? (
        <div
          className="fixed z-[260] min-w-40 overflow-hidden rounded-lg border border-gray-200 bg-white p-1 text-[12px] text-gray-700 shadow-2xl shadow-gray-950/20 dark:border-white/10 dark:bg-[#18181b] dark:text-gray-100"
          style={{ left: nodeContextMenu.x, top: nodeContextMenu.y }}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => event.stopPropagation()}
        >
          <div className="max-w-56 truncate px-2.5 py-2 text-[11px] font-semibold text-gray-400 dark:text-gray-500">
            {contextMenuNode.data.title}
          </div>
          <button
            type="button"
            className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
            onClick={() => {
              actions.showDetails({
                nodeId: contextMenuNode.id,
                x: nodeContextMenu.x,
                y: nodeContextMenu.y,
              })
            }}
          >
            <Search className="size-3.5" />
            查看详细
          </button>
          {contextMenuNodeCanShowEditHistory ? (
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
              onClick={() => void actions.openEditHistory(contextMenuNode.id)}
            >
              <History className="size-3.5" />
              修改记录
            </button>
          ) : null}
          {contextMenuNodeCanShowVersionHistory ? (
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
              onClick={() => actions.openVersionHistory(contextMenuNode)}
            >
              <Layers3 className="size-3.5" />
              历史版本
            </button>
          ) : null}
          {contextMenuNodeCanClipVideo ? (
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
              onClick={() => {
                if (!contextMenuNode) return
                void actions.clipVideo(contextMenuNode)
              }}
            >
              <Scissors className="size-3.5" />
              视频剪辑
            </button>
          ) : null}
          {contextMenuNodeCanEditStoryboardImage ? (
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
              onClick={() => {
                actions.editImage(contextMenuNode.id)
              }}
            >
              <WandSparkles className="size-3.5" />
              修改分镜图
            </button>
          ) : null}
          {contextMenuNode.data.eyebrow === "storyboard.image" && contextMenuNode.data.shotGroupId ? (
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
              onClick={() => {
                actions.close()
                void actions.generateStoryboardImage(contextMenuNode.id)
              }}
            >
              <ImagePlus className="size-3.5" />
              生成此分镜图
            </button>
          ) : null}
          {contextMenuStoryboardCardResult && contextMenuNode.data.shotGroupId ? (
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
              onClick={() => {
                actions.close()
                void actions.generateStoryboardImage(contextMenuStoryboardCardResult.id)
              }}
            >
              <ImagePlus className="size-3.5" />
              生成分镜图
            </button>
          ) : null}
          {contextMenuNodeCanGenerateVisualHandoff ? (
            <button
              type="button"
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors",
                contextMenuVisualHandoffDisabled
                  ? "cursor-not-allowed text-gray-400"
                  : "hover:bg-gray-100 dark:hover:bg-white/10"
              )}
              disabled={contextMenuVisualHandoffDisabled}
              title={contextMenuVisualHandoffDisabledTitle}
              onClick={() => {
                if (contextMenuVisualHandoffDisabled || !contextMenuStoryboardCardResult || !contextMenuNode) return
                actions.close()
                void actions.generateVisualHandoff(contextMenuNode.id)
              }}
            >
              {contextMenuNodeRunningTask ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <ImagePlus className="size-3.5" />
              )}
              生成视觉交接图
            </button>
          ) : null}
          {contextMenuNodeCanEditImageAsset ? (
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
              onClick={() => {
                actions.editImage(contextMenuNode.id)
              }}
            >
              <WandSparkles className="size-3.5" />
              编辑图片
            </button>
          ) : null}
          {contextMenuNodeCanRenameAsset ? (
            <button
              type="button"
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors",
                contextMenuRenameAssetDisabled
                  ? "cursor-not-allowed text-gray-400"
                  : "hover:bg-gray-100 dark:hover:bg-white/10"
              )}
              disabled={contextMenuRenameAssetDisabled}
              title={contextMenuRenameAssetDisabledTitle}
              onClick={() => {
                if (contextMenuRenameAssetDisabled) return
                actions.renameAsset(contextMenuNode)
              }}
            >
              <PencilLine className="size-3.5" />
              重命名
            </button>
          ) : null}
          {contextMenuNodeIsVideoTask ? (
            <>
              {contextMenuNodeVideoTaskScope === "work_chain" ? (
                <button
                  type="button"
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors",
                    contextMenuGenerateFinalVideoPromptDisabled
                      ? "cursor-not-allowed text-gray-400"
                      : "hover:bg-gray-100 dark:hover:bg-white/10"
                  )}
                  disabled={contextMenuGenerateFinalVideoPromptDisabled}
                  title={contextMenuGenerateFinalVideoPromptDisabledTitle}
                  onClick={() => {
                    if (contextMenuGenerateFinalVideoPromptDisabled) return
                    actions.close()
                    void actions.generateVideoPrompt(contextMenuNode.id)
                  }}
                >
                  {contextMenuNodeVideoPromptSyncing ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : (
                    <WandSparkles className="size-3.5" />
                  )}
                  {contextMenuNodeVideoPromptSyncing
                    ? "正在生成视频提示词"
                    : contextMenuFinalVideoPromptExists
                      ? "重新生成提示词"
                      : "生成视频提示词"}
                </button>
              ) : null}
              <button
                type="button"
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors",
                  contextMenuFinalVideoDisabled
                    ? "cursor-not-allowed text-gray-400"
                    : "hover:bg-gray-100 dark:hover:bg-white/10"
                )}
                disabled={contextMenuFinalVideoDisabled}
                title={contextMenuFinalVideoDisabledTitle}
                onClick={() => {
                  if (contextMenuFinalVideoDisabled) return
                  actions.close()
                  void actions.runNode(contextMenuNode.id)
                }}
              >
                {contextMenuFinalVideoRunning ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Video className="size-3.5" />
                )}
                {contextMenuFinalVideoRunning
                  ? "正在生成视频片段"
                  : "生成视频片段"}
              </button>
            </>
          ) : null}
          {contextMenuNodeCanAddToAssetLibrary ? (
            <button
              type="button"
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors",
                contextMenuAddAssetLibraryDisabled
                  ? "cursor-not-allowed text-gray-400"
                  : "hover:bg-gray-100 dark:hover:bg-white/10"
              )}
              disabled={contextMenuAddAssetLibraryDisabled}
              title={contextMenuAddAssetLibraryDisabledTitle}
              onClick={() => {
                if (contextMenuAddAssetLibraryDisabled) return
                void actions.addToAssetLibrary(contextMenuNode.id)
              }}
            >
              {contextMenuAddAssetLibraryBusy ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Package className="size-3.5" />
              )}
              加入资产库
            </button>
          ) : null}
          {contextMenuNodeCanCopyAsset ? (
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
              onClick={() => {
                const clipboard: CanvasAssetClipboardItem = {
                  schemaVersion: 1,
                  kind: "ai_video_canvas_asset",
                  clipboardSource: "node",
                  sourceProjectId: contextMenuNode.data.projectId || projectId,
                  sourceEpisodeId: contextMenuNode.data.episodeId || episodeId,
                  sourceNodeId: contextMenuNode.id,
                  sourceNodeType: contextMenuNode.data.eyebrow,
                  title: contextMenuNode.data.title,
                  copiedAt: new Date().toISOString(),
                }
                actions.assetCopied(clipboard)
                writeCanvasAssetClipboard(clipboard)
                actions.close()
                toast.success("资产已复制，可在画布空白处右键粘贴")
              }}
            >
              <Copy className="size-3.5" />
              复制资产
            </button>
          ) : null}
          {!contextMenuNodeIsDirectorBoard ? (
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
              onClick={() => {
                actions.close()
                actions.focusNode(contextMenuNode.id)
              }}
            >
              <Maximize2 className="size-3.5" />
              定位节点
            </button>
          ) : null}
          {contextMenuNodeCanGenerateCinematicScript ? (
            <button
              type="button"
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors",
                contextMenuCinematicScriptDisabled
                  ? "cursor-not-allowed text-gray-400"
                  : "hover:bg-gray-100 dark:hover:bg-white/10"
              )}
              disabled={contextMenuCinematicScriptDisabled}
              title={contextMenuCinematicScriptDisabledTitle}
              onClick={() => {
                if (contextMenuCinematicScriptDisabled) return
                actions.close()
                void actions.generateCinematicScript(contextMenuNode.id)
              }}
            >
              {contextMenuCinematicScriptRunning ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <WandSparkles className="size-3.5" />
              )}
              {contextMenuCinematicScriptRunning ? "正在生成片段剧本" : "生成片段剧本"}
            </button>
          ) : null}
          {contextMenuNodeIsDirectorBoard ? (
            <>
              <button
                type="button"
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors",
                  contextMenuDirectorPlanDisabled
                    ? "cursor-not-allowed text-gray-400"
                    : "hover:bg-gray-100 dark:hover:bg-white/10"
                )}
                disabled={contextMenuDirectorPlanDisabled}
                title={contextMenuDirectorPlanDisabledTitle}
                onClick={() => {
                  if (contextMenuDirectorPlanDisabled) return
                  actions.close()
                  void actions.runNode(contextMenuNode.id)
                }}
              >
                {contextMenuNodeRunningTaskType === "storyboard_plan" ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <ClipboardList className="size-3.5" />
                )}
                {contextMenuNodeRunningTaskType === "storyboard_plan"
                  ? "正在生成分镜脚本"
                  : "生成分镜脚本"}
              </button>
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
                onClick={() => {
                  actions.close()
                  actions.focusNode(contextMenuNode.id)
                }}
              >
                <Maximize2 className="size-3.5" />
                定位节点
              </button>
            </>
          ) : null}
          {contextMenuNodeCanRun &&
          contextMenuNode.data.eyebrow !== "prompt.storyboard" &&
          !contextMenuNodeIsVideoTask &&
          !contextMenuNodeIsDirectorBoard ? (
            <button
              type="button"
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors",
                contextMenuNodeRunDisabled
                  ? "cursor-not-allowed text-gray-400"
                  : "hover:bg-gray-100 dark:hover:bg-white/10"
              )}
              disabled={contextMenuNodeRunDisabled}
              title={contextMenuNodeRunDisabledTitle}
              onClick={() => {
                if (contextMenuNodeRunDisabled) return
                actions.close()
                void actions.runNode(contextMenuNode.id)
              }}
            >
              {contextMenuNodeRunningTask ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Play className="size-3.5" />
              )}
              {contextMenuNodeRunningTask
                ? workflowContextRunningLabel(contextMenuNode.data.eyebrow, {
                    videoTaskReady:
                      workflowVideoTaskCardIsReady(contextMenuNode),
                    activeTaskType: contextMenuNodeRunningTaskType,
                  })
                : workflowContextRunLabel(contextMenuNode.data.eyebrow, {
                    videoTaskReady:
                      workflowVideoTaskCardIsReady(contextMenuNode),
                  })}
            </button>
          ) : null}
          {contextMenuIndependentChain ? (
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-rose-600 transition-colors hover:bg-rose-50 disabled:opacity-50 dark:text-rose-300 dark:hover:bg-rose-950/30"
              disabled={contextMenuNodeDeleteLocked || contextMenuNodeBusy}
              onClick={() => {
                actions.requestDeleteChain(contextMenuIndependentChain.id)
                actions.close()
              }}
            >
              <Trash2 className="size-3.5" />
              删除工作链
            </button>
          ) : null}
          {contextMenuNodeCanShowDelete ? (
            <button
              type="button"
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors",
                contextMenuNodeDeleteLocked
                  ? "cursor-not-allowed text-gray-400"
                  : "text-rose-600 hover:bg-rose-50 dark:text-rose-300 dark:hover:bg-rose-950/30"
              )}
              disabled={contextMenuNodeDeleteLocked}
              onClick={() => void actions.deleteNode(contextMenuNode.id)}
            >
              <Trash2 className="size-3.5" />
              {workflowContextDeleteLabel(contextMenuNode.data.eyebrow)}
            </button>
          ) : null}
        </div>
      ) : null}
    </>
  )
}
