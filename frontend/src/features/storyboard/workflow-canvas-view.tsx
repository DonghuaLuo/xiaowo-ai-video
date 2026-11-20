import type { useWorkflowNodeEditing } from "./use-workflow-node-editing"
import type { useWorkflowStructureActions } from "./use-workflow-structure-actions"
import type { useWorkflowCanvasSelection } from "./use-workflow-canvas-selection"
import { canvasSelectionDeleteState } from "./workflow-selection-model"
import type { useWorkflowProjectAssets } from "./use-workflow-project-assets"
import type { useWorkflowGenerationPreflight } from "./use-workflow-generation-preflight"
import type { useWorkflowMediaExchange } from "./use-workflow-media-exchange"
import type { useWorkflowCanvasDetails } from "./use-workflow-canvas-details"
import type { useWorkflowDocumentSync } from "./use-workflow-document-sync"
import type { WorkflowCanvasDocument } from "./workflow-canvas-document"
import type {
  AgentTargetContext,
  EpisodeWorkflow,
  InputImageFile,
} from "@/backend"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import type { ProjectRow } from "@/features/projects/types"
import { cn } from "@/lib/utils"
import { ConfirmDialog } from "@/shared/confirm-dialog"
import type {
  Connection,
  EdgeChange,
  NodeChange,
  NodeTypes,
  ReactFlowInstance,
} from "@xyflow/react"
import {
  Background,
  BackgroundVariant,
  ReactFlow,
  ReactFlowProvider,
  SelectionMode,
  useStoreApi,
} from "@xyflow/react"
import {
  AlertTriangle,
  ClipboardList,
  FilePlus2,
  GitBranch,
  ImagePlus,
  Keyboard,
  Loader2,
  Lock,
  Maximize2,
  Package,
  Save,
  Trash2,
} from "lucide-react"
import type { MouseEvent } from "react"
import { useEffect, useState } from "react"
import type {
  ProductionStatusPopoverRow,
  WorkChainProgressStep,
} from "./production-status-popover"
import { ProductionStatusPopover } from "./production-status-popover"
import { SourceSplitEditor } from "./source-split-editor"
import { StoryboardVersionPanel } from "./storyboard-version-panel"
import type { WorkflowAssetDialogProps } from "./workflow-asset-dialog"
import { WorkflowAssetDialog } from "./workflow-asset-dialog"
import type {
  AddAssetKind,
  CanvasContextMenuState,
  EdgeContextMenuState,
  ExternalMediaPurpose,
  NodeContextMenuState,
  NodeDetailsState,
} from "./workflow-canvas-asset-model"
import {
  CANVAS_TASK_NODE_OPTIONS,
  RENAME_IMAGE_MEDIA_PURPOSE_OPTIONS,
  isWorkflowTaskCardType,
  mediaPurposeUsesVoiceStyle,
  mediaPurposeVoiceStyleLabel,
  workflowCanDragVersionToCanvas,
  workflowNodeCurrentVersionId,
  workflowNodeVersionActivationMode,
  workflowNodeVersionDeleteMode,
} from "./workflow-canvas-asset-model"
import type { StoryboardEdge, StoryboardNode } from "./workflow-canvas-model"
import { hasInlineTaskParameterPanel } from "./workflow-canvas-model"
import type { WorkflowNodeContextMenuModel } from "./workflow-context-menu-model"
import { WorkflowEditHistoryDialog } from "./workflow-edit-history-dialog"
import {
  WorkflowNodeContextMenu,
  type WorkflowNodeContextMenuActions,
} from "./workflow-node-context-menu"
import { stopCardWheel } from "./workflow-prompt-node-model"
import { StoryboardImageEditFloatingPanel } from "./workflow-storyboard-image-edit-panel"

import { VideoClipDialog } from "./workflow-video-clip"

function CanvasSelectionGestureState({ active, ctrlPressed, selecting }: {
  active: boolean; ctrlPressed: boolean; selecting: boolean
}) {
  const store = useStoreApi()
  useEffect(() => {
    if (ctrlPressed || selecting) return
    // Pointer cancellation/window blur must also release React Flow's gesture.
    store.setState({ userSelectionActive: false, userSelectionRect: null, ...(!active ? { nodesSelectionActive: false } : {}) })
  }, [active, ctrlPressed, selecting, store])
  return null
}

function WorkflowEmptyState({
  state,
  loading,
  onContextMenu,
}: {
  state?: EpisodeWorkflow["state"] | null
  loading: boolean
  onContextMenu?: (event: MouseEvent<HTMLDivElement>) => void
}) {
  if (loading) {
    return (
      <div
        className="absolute inset-0 z-20 flex items-center justify-center bg-slate-100/60 backdrop-blur-sm dark:bg-black/20"
        onContextMenu={onContextMenu}
      >
        <div className="flex items-center gap-2 rounded-lg border border-white/70 bg-white/90 px-4 py-3 text-sm font-medium text-gray-700 shadow-xl shadow-gray-950/10 dark:border-white/10 dark:bg-[#202025]/90 dark:text-gray-200">
          <Loader2 className="size-4 animate-spin text-indigo-500" />
          正在加载画布
        </div>
      </div>
    )
  }

  const sourceReady = Boolean(state?.sourceReady)
  const title = sourceReady
    ? "当前集等待剧情拆分确认"
    : "当前集尚未提交源文"
  const message = sourceReady
    ? "请在分集会话中拆分剧情；确认候选后，工作链会显示在画布中。"
    : "提交分集源文后，画布会等待真实工作链数据。"
  const badgeText = sourceReady
    ? "原文已保存"
    : state?.nextAction === "commit_episode_source"
      ? "等待分集源文"
      : "等待工作链计划"

  return (
    <div
      className="absolute inset-0 z-20 flex items-center justify-center bg-slate-100/70 p-6 backdrop-blur-sm dark:bg-black/25"
      onContextMenu={onContextMenu}
    >
      <div className="w-full max-w-md rounded-xl border border-white/80 bg-white/95 p-6 text-center shadow-xl shadow-gray-950/10 dark:border-white/10 dark:bg-[#202025]/95">
        <div className="mx-auto flex size-11 items-center justify-center rounded-full bg-indigo-50 text-indigo-600 dark:bg-indigo-400/10 dark:text-indigo-300">
          <ClipboardList className="size-5" />
        </div>
        <h3 className="mt-4 text-base font-semibold text-gray-950 dark:text-gray-50">
          {title}
        </h3>
        <p className="mt-2 text-sm leading-relaxed text-gray-500 dark:text-gray-400">
          {message}
        </p>
        <div className="mt-5 flex justify-center">
          <Badge variant="outline" className="rounded-full">
            {badgeText}
          </Badge>
        </div>
      </div>
    </div>
  )
}

function CustomCanvasEmptyHint() {
  return (
    <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center p-6">
      <div className="w-full max-w-xs rounded-lg border border-dashed border-gray-200/90 bg-white/80 px-5 py-4 text-center shadow-lg shadow-gray-950/5 backdrop-blur-sm dark:border-white/10 dark:bg-[#18181c]/80 dark:shadow-black/20">
        <div className="text-base font-normal text-gray-700 dark:text-gray-200">
          右键画布添卡片
        </div>
        <div className="mt-2 flex items-center justify-center gap-1.5 text-[11px] text-gray-500 dark:text-gray-400">
          <ImagePlus className="size-3.5 text-gray-400 dark:text-gray-500" />
          <kbd className="rounded border border-gray-200 bg-white/80 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-gray-600 shadow-sm dark:border-white/10 dark:bg-white/[0.06] dark:text-gray-300">
            Ctrl
          </kbd>
          <span>+</span>
          <kbd className="rounded border border-gray-200 bg-white/80 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-gray-600 shadow-sm dark:border-white/10 dark:bg-white/[0.06] dark:text-gray-300">
            V
          </kbd>
          <span>可粘贴图片</span>
        </div>
      </div>
    </div>
  )
}

export type WorkflowCanvasViewProps = {
  canvasSelection: ReturnType<typeof useWorkflowCanvasSelection>
  selectionMovementBlocked: boolean
  layoutSaving: boolean
  nodeEditing: Pick<
    ReturnType<typeof useWorkflowNodeEditing>,
    | "editHistory"
    | "editHistoryNodeTitle"
    | "editHistoryNodeType"
    | "imageEditNode"
    | "setImageEdit"
    | "versionDialog"
    | "setVersionDialog"
    | "versionNode"
    | "versionDescription"
    | "versionChanged"
    | "versionRevisionChanged"
    | "versionMutationCommitted"
  >
  structureActions: Pick<
    ReturnType<typeof useWorkflowStructureActions>,
    | "createTask"
    | "createChain"
    | "createIndependentSource"
    | "deleteChain"
    | "deleteTarget"
    | "setDeleteTarget"
    | "deleting"
    | "deleteSourceTarget"
    | "setDeleteSourceTarget"
    | "deletingSource"
    | "deleteIndependentSource"
    | "sourceSplitEditor"
    | "setSourceSplitEditor"
    | "sourceSplitSaving"
    | "openSourceSplitEditor"
    | "confirmSourceSplit"
    | "saveSourceText"
  >
  projectAssets: Pick<
    ReturnType<typeof useWorkflowProjectAssets>,
    "renameDraft" | "setRenameDraft" | "savingRename" | "saveRename"
  >
  generationPreflight: Pick<
    ReturnType<typeof useWorkflowGenerationPreflight>,
    "dialog" | "setDialog"
  >
  mediaExchange: Pick<
    ReturnType<typeof useWorkflowMediaExchange>,
    | "clipboard"
    | "clipSource"
    | "setClipSource"
    | "createVersionAsset"
    | "copyVersion"
    | "paste"
    | "copyClipResult"
    | "dropClipResult"
  >
  canvasDetails: Pick<
    ReturnType<typeof useWorkflowCanvasDetails>,
    "hydrate" | "isLoaded"
  >
  documentSync: Pick<
    ReturnType<typeof useWorkflowDocumentSync>,
    "applyMutation" | "scheduleBackfill"
  >
  canvasDocument: Pick<WorkflowCanvasDocument, "selectNode" | "confirmRevision">

  nodeContextMenuModel: WorkflowNodeContextMenuModel
  nodeContextMenuActions: WorkflowNodeContextMenuActions

  STORYBOARD_NODE_TYPES: NodeTypes
  assetDialogProps: WorkflowAssetDialogProps
  canvasContextMenu: CanvasContextMenuState | null
  canvasLoading: boolean
  canvasViewportDragging: boolean
  contextMenuEdge: StoryboardEdge | undefined
  contextMenuEdgeLocked: boolean
  detailNode: StoryboardNode | undefined
  detailRows: [string, string][]
  edgeContextMenu: EdgeContextMenuState | null
  episodeId: string
  flowInstanceRef: React.MutableRefObject<ReactFlowInstance<
    StoryboardNode,
    StoryboardEdge
  > | null>
  handleEdgesChange: (changes: EdgeChange<StoryboardEdge>[]) => void
  handleFitView: () => void
  handleFocusWorkChain: (workChainId: string) => void
  handleFocusWorkChainStep: (_workChainId: string, nodeId?: string) => void
  handleNodeDrag: (
    _event: globalThis.MouseEvent | TouchEvent,
    node: StoryboardNode,
    nodes?: StoryboardNode[]
  ) => void
  handleNodeDragStart: (
    _event: globalThis.MouseEvent | TouchEvent,
    node: StoryboardNode,
    nodes?: StoryboardNode[]
  ) => void
  handleNodeDragStop: (
    _event: globalThis.MouseEvent | TouchEvent,
    node: StoryboardNode,
    nodes?: StoryboardNode[]
  ) => void
  handleNodesChange: (changes: NodeChange<StoryboardNode>[]) => void
  handleRemoveContextEdge: (edgeId: string) => void
  handleRunWorkChainStep: (
    _workChainId: string,
    step: WorkChainProgressStep
  ) => void
  handleRelayoutWorkChains: () => Promise<void>
  handleShowAllWorkChains: () => void
  hasRealWorkflow: boolean
  lastAddAssetKind: AddAssetKind
  nodeContextMenu: NodeContextMenuState | null
  nodeDetails: NodeDetailsState | null
  nodeDetailsPanelStyle:
    | { left: number; top: number; width: number; maxHeight: number }
    | undefined
  openDirectorWorkspace: (nodeId: string) => void
  onConnect: (connection: Connection) => void
  openAddAssetDialog: (
    kind?: AddAssetKind,
    placementPosition?: { x: number; y: number },
    options?: {
      mediaFile?: InputImageFile | null
      mediaPurpose?: ExternalMediaPurpose
      title?: string
    }
  ) => void
  openCanvasContextMenu: (
    event: MouseEvent<Element> | globalThis.MouseEvent
  ) => void
  productionStatusRows: ProductionStatusPopoverRow[]
  project: ProjectRow
  publishCanvasAgentTarget: (
    nodeId?: string | null,
    intent?: AgentTargetContext["intent"]
  ) => void
  setCanvasContextMenu: React.Dispatch<
    React.SetStateAction<CanvasContextMenuState | null>
  >
  setCanvasViewportDragging: React.Dispatch<React.SetStateAction<boolean>>
  setEdgeContextMenu: React.Dispatch<
    React.SetStateAction<EdgeContextMenuState | null>
  >
  setNodeContextMenu: React.Dispatch<
    React.SetStateAction<NodeContextMenuState | null>
  >
  setNodeDetails: React.Dispatch<React.SetStateAction<NodeDetailsState | null>>
  setStatusPopoverOpen: React.Dispatch<React.SetStateAction<boolean>>
  showCustomCanvasEmptyHint: boolean
  showWorkflowEmptyState: boolean
  sourceSplitEditorNode: StoryboardNode | undefined
  statusPopoverOpen: boolean
  visibleEdges: StoryboardEdge[]
  visibleFlowNodes: StoryboardNode[]
  workflowState: EpisodeWorkflow["state"] | null
}

export function WorkflowCanvasView(props: WorkflowCanvasViewProps) {
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const selection = props.canvasSelection
  const {
    STORYBOARD_NODE_TYPES,
    assetDialogProps,
    canvasContextMenu,
    canvasLoading,
    canvasViewportDragging,
    contextMenuEdge,
    contextMenuEdgeLocked,
    detailNode,
    detailRows,
    edgeContextMenu,
    episodeId,
    flowInstanceRef,
    handleEdgesChange,
    handleFitView,
    handleFocusWorkChain,
    handleFocusWorkChainStep,
    handleNodeDrag,
    handleNodeDragStart,
    handleNodeDragStop,
    handleNodesChange,
    handleRemoveContextEdge,
    handleRunWorkChainStep,
    handleRelayoutWorkChains,
    handleShowAllWorkChains,
    hasRealWorkflow,
    lastAddAssetKind,
    nodeContextMenu,
    nodeDetails,
    nodeDetailsPanelStyle,
    openDirectorWorkspace,
    onConnect,
    openAddAssetDialog,
    openCanvasContextMenu,
    productionStatusRows,
    project,
    publishCanvasAgentTarget,
    setCanvasContextMenu,
    setCanvasViewportDragging,
    setEdgeContextMenu,
    setNodeContextMenu,
    setNodeDetails,
    setStatusPopoverOpen,
    showCustomCanvasEmptyHint,
    showWorkflowEmptyState,
    sourceSplitEditorNode,
    statusPopoverOpen,
    visibleEdges,
    visibleFlowNodes,
    workflowState,
    nodeContextMenuModel,
    nodeContextMenuActions,
  } = props
  const {
    editHistory,
    editHistoryNodeTitle,
    editHistoryNodeType,
    imageEditNode: storyboardImageEditNode,
    setImageEdit: setStoryboardImageEdit,
    versionDialog: nodeVersionHistoryDialog,
    setVersionDialog: setNodeVersionHistoryDialog,
    versionNode: nodeVersionHistoryNode,
    versionDescription: nodeVersionHistoryDescription,
    versionChanged: handleNodeVersionHistoryChanged,
    versionRevisionChanged: handleVersionRevisionChanged,
    versionMutationCommitted: handleVersionMutationCommitted,
  } = props.nodeEditing
  const imageEditSourceNodeId = storyboardImageEditNode?.data.resultOfNodeId || storyboardImageEditNode?.data.sourceNodeId
  const imageEditSourceModelId = String(
    visibleFlowNodes.find((node) => node.id === imageEditSourceNodeId)?.data.generationConfig?.modelId || ""
  ).trim()
  const {
    createTask: handleCreateCanvasTaskNode,
    createChain: handleCreateCanvasWorkflowChain,
    createIndependentSource: handleCreateIndependentSourceCard,
    deleteChain: handleDeleteWorkflowChain,
    deleteTarget: deleteChainTarget,
    setDeleteTarget: setDeleteChainTarget,
    deleting: deletingChain,
    deleteSourceTarget,
    setDeleteSourceTarget,
    deletingSource,
    deleteIndependentSource,
    sourceSplitEditor,
    setSourceSplitEditor,
    sourceSplitSaving,
    openSourceSplitEditor,
    confirmSourceSplit: handleSourceSplitConfirm,
    saveSourceText: handleSourceTextSave,
  } = props.structureActions
  const {
    renameDraft: renameAssetDraft,
    setRenameDraft: setRenameAssetDraft,
    savingRename: savingRenameAsset,
    saveRename: handleSaveRenameAsset,
  } = props.projectAssets
  const {
    dialog: generationPreflightDialog,
    setDialog: setGenerationPreflightDialog,
  } = props.generationPreflight
  const {
    clipboard: availableCopiedAssetClipboard,
    clipSource: videoClipDialogSource,
    setClipSource: setVideoClipDialogSource,
    createVersionAsset: handleCreateStoryboardVersionCanvasAsset,
    copyVersion: handleCopyStoryboardVersionCanvasAsset,
    paste: handlePasteCanvasAssetNode,
    copyClipResult: handleCopyVideoClipResultAsset,
    dropClipResult: handleDropVideoClipResultToCanvas,
  } = props.mediaExchange
  const { hydrate: hydrateWorkflowCard, isLoaded: isWorkflowCardLoaded } =
    props.canvasDetails
  const {
    selectNode: setSelectedNodeId,
  } = props.canvasDocument
  const selectedCards = visibleFlowNodes.filter(node => selection.selected.some(selected => selected.id === node.id))
  const selectionDelete = canvasSelectionDeleteState(selectedCards, visibleFlowNodes, visibleEdges)
  const closeCanvasMenus = () => {
    setNodeContextMenu(null)
    setCanvasContextMenu(null)
    setEdgeContextMenu(null)
    setNodeDetails(null)
    setStatusPopoverOpen(false)
  }
  return (
    <>
      <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
        <div
          data-workflow-canvas-surface
          ref={selection.surfaceRef}
          data-selection-active={selection.active || undefined}
          data-box-selecting={selection.ctrlPressed || selection.selecting || undefined}
          className="relative min-h-0 flex-1 bg-slate-100/80 dark:bg-black/10"
        >
          <>
            <ReactFlowProvider>
              <ReactFlow<StoryboardNode, StoryboardEdge>
                nodes={hasRealWorkflow ? visibleFlowNodes : []}
                edges={hasRealWorkflow ? visibleEdges : []}
                nodeTypes={STORYBOARD_NODE_TYPES}
                selectionKeyCode={null}
                multiSelectionKeyCode="ControlLeft"
                selectionOnDrag={selection.ctrlPressed}
                selectionMode={SelectionMode.Full}
                panOnDrag={selection.ctrlPressed || selection.selecting ? false : [0, 1]}
                panActivationKeyCode={selection.ctrlPressed || selection.selecting ? null : "Space"}
                deleteKeyCode={null}
                disableKeyboardA11y={selection.active}
                onSelectionStart={(event) => { closeCanvasMenus(); selection.startSelection(event) }}
                onSelectionEnd={selection.endSelection}
                onSelectionContextMenu={(event) => { if (selection.openMenu(event)) closeCanvasMenus() }}
                onNodesChange={handleNodesChange}
                onEdgesChange={(changes) => handleEdgesChange(
                  selection.active || selection.ctrlPressed || selection.selecting
                    ? changes.filter(change => change.type !== "select" || !change.selected)
                    : changes
                )}
                onConnect={onConnect}
                onNodeDragStart={handleNodeDragStart}
                onNodeDrag={handleNodeDrag}
                onNodeDragStop={handleNodeDragStop}
                onEdgeContextMenu={(event, edge) => {
                  event.preventDefault()
                  event.stopPropagation()
                  setSourceSplitEditor(null)
                  setNodeContextMenu(null)
                  setCanvasContextMenu(null)
                  setNodeDetails(null)
                  setStatusPopoverOpen(false)
                  setEdgeContextMenu({
                    edgeId: edge.id,
                    x: event.clientX,
                    y: event.clientY,
                  })
                }}
                onMoveStart={() => setCanvasViewportDragging(true)}
                onMoveEnd={() => setCanvasViewportDragging(false)}
                onNodeClick={(event, node) => {
                  if (event.button !== 0) return
                  if (selection.interceptClick(node.id)) return
                  if (node.data.eyebrow === "director.board") {
                    setSelectedNodeId(node.id)
                    setNodeContextMenu(null)
                    setCanvasContextMenu(null)
                    setEdgeContextMenu(null)
                    void openDirectorWorkspace(node.id)
                    return
                  }
                  const isSourceTextNode = node.data.eyebrow === "source.text"
                  const isTaskCardNode = isWorkflowTaskCardType(
                    node.data.eyebrow
                  )
                  const shouldHydrateBeforeOpen =
                    isSourceTextNode ||
                    hasInlineTaskParameterPanel(node.data.eyebrow)
                  const taskCardNeedsHydration =
                    isTaskCardNode && !isWorkflowCardLoaded(node.id)
                  if (
                    shouldHydrateBeforeOpen &&
                    (!isTaskCardNode || taskCardNeedsHydration)
                  ) {
                    void hydrateWorkflowCard(node.id, {
                      force: taskCardNeedsHydration,
                    })
                  }
                  setSelectedNodeId(node.id)
                  if (isSourceTextNode) {
                    if (sourceSplitEditor?.nodeId !== node.id) {
                      openSourceSplitEditor(node)
                    }
                  } else {
                    setSourceSplitEditor(null)
                  }
                  publishCanvasAgentTarget(node.id, "focus")
                  setNodeContextMenu(null)
                  setCanvasContextMenu(null)
                  setEdgeContextMenu(null)
                  setNodeDetails(null)
                  setStoryboardImageEdit((current) =>
                    current?.nodeId === node.id ? current : null
                  )
                  setStatusPopoverOpen(false)
                }}
                onNodeContextMenu={(event, node) => {
                  if (selection.openMenu(event, node.id)) { closeCanvasMenus(); return }
                  event.preventDefault()
                  event.stopPropagation()
                  setSelectedNodeId(null)
                  setSourceSplitEditor(null)
                  publishCanvasAgentTarget(node.id, "focus")
                  setCanvasContextMenu(null)
                  setEdgeContextMenu(null)
                  setNodeDetails(null)
                  setStoryboardImageEdit(null)
                  setStatusPopoverOpen(false)
                  void hydrateWorkflowCard(node.id)
                  setNodeContextMenu({
                    nodeId: node.id,
                    x: event.clientX,
                    y: event.clientY,
                  })
                }}
                onPaneClick={() => {
                  selection.clear()
                  setSelectedNodeId(null)
                  setSourceSplitEditor(null)
                  publishCanvasAgentTarget(null, "focus")
                  setNodeContextMenu(null)
                  setEdgeContextMenu(null)
                  setNodeDetails(null)
                  setStoryboardImageEdit(null)
                  setCanvasContextMenu(null)
                  setStatusPopoverOpen(false)
                }}
                onPaneContextMenu={openCanvasContextMenu}
                onInit={(instance) => {
                  flowInstanceRef.current = instance
                }}
                fitView
                minZoom={0.08}
                maxZoom={1.4}
                onlyRenderVisibleElements
                elevateNodesOnSelect={false}
                proOptions={{ hideAttribution: true }}
              >
                <CanvasSelectionGestureState active={selection.active} ctrlPressed={selection.ctrlPressed} selecting={selection.selecting} />
                <Background
                  variant={BackgroundVariant.Dots}
                  gap={20}
                  size={1.2}
                  color="rgba(99,102,241,0.25)"
                />
              </ReactFlow>
            </ReactFlowProvider>
            {selection.menu ? (
              <div
                data-canvas-selection-ui
                role="menu"
                aria-label="选中卡片操作"
                className="fixed z-[280] w-[280px] rounded-lg border border-gray-200 bg-white p-1 text-xs text-gray-700 shadow-2xl dark:border-white/10 dark:bg-[#18181b] dark:text-gray-200"
                style={{ left: selection.menu.x, top: selection.menu.y }}
                onPointerDown={event => event.stopPropagation()}
                onContextMenu={event => event.preventDefault()}
              >
                <div className="px-3 py-2 text-gray-500 dark:text-gray-400">已选 {selectedCards.length} 张卡片</div>
                <button
                  type="button" role="menuitem"
                  className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-rose-600 hover:bg-rose-50 disabled:cursor-not-allowed disabled:text-gray-400 disabled:hover:bg-transparent dark:text-rose-300 dark:hover:bg-rose-950/30 dark:disabled:text-gray-500"
                  disabled={Boolean(selectionDelete.reason) || selection.deleting || props.layoutSaving}
                  onClick={selection.requestDelete}
                ><Trash2 className="size-4" />删除选中的 {selectedCards.length} 张卡片</button>
                {selectionDelete.reason ? <p className="px-3 py-2 text-[11px] leading-5 text-gray-500 dark:text-gray-400">{selectionDelete.reason}</p> : null}
              </div>
            ) : null}
            <ConfirmDialog
              open={Boolean(selection.deleteIds)}
              title={`删除选中的 ${selection.deleteIds?.length ?? 0} 张卡片？`}
              description={selectedCards.some((node) => node.data.eyebrow === "source.text" && node.data.sourceMode === "independent")
                ? "将删除所选卡片及相关链接，包括独立原文生成的全部工作链和链内结果。资产库文件会保留。"
                : `将删除所选画布卡片及相关链接${selectionDelete.totalCount > selectedCards.length ? `，包含关联结果共 ${selectionDelete.totalCount} 张卡片` : ""}。资产库文件会保留。`}
              confirmLabel="删除卡片" loadingLabel="删除中..." loading={selection.deleting}
              onCancel={selection.cancelDelete} onConfirm={selection.confirmDelete}
            />
            {showWorkflowEmptyState ? (
              <WorkflowEmptyState
                state={workflowState}
                loading={canvasLoading && !hasRealWorkflow}
                onContextMenu={openCanvasContextMenu}
              />
            ) : null}
            {showCustomCanvasEmptyHint ? <CustomCanvasEmptyHint /> : null}
            {hasRealWorkflow ? (
              <div className="pointer-events-none absolute bottom-5 left-1/2 z-40 flex -translate-x-1/2 flex-col items-center gap-3">
                {hasRealWorkflow && statusPopoverOpen ? (
                  <ProductionStatusPopover
                    rows={productionStatusRows}
                    onShowAllWorkChains={handleShowAllWorkChains}
                    onRelayout={handleRelayoutWorkChains}
                    onFocusWorkChain={handleFocusWorkChain}
                    onFocusStep={handleFocusWorkChainStep}
                    onRunStep={handleRunWorkChainStep}
                  />
                ) : null}
                <div className="flex items-center gap-2">
                  {props.layoutSaving || selectedCards.length > 0 ? (
                    <div className="pointer-events-none rounded-full border border-gray-200/80 bg-white/90 px-3 py-2 text-[11px] text-gray-600 dark:border-white/10 dark:bg-[#18181b]/90 dark:text-gray-300">
                      {props.layoutSaving ? "正在保存整组位置…"
                        : `已选 ${selectedCards.length} 张 · ${props.selectionMovementBlocked ? "含锁定卡片，不能整体移动" : "拖动整体移动 · 右键操作"}`}
                    </div>
                  ) : null}
                  {hasRealWorkflow ? (
                    <div className="pointer-events-auto flex items-center gap-1 rounded-full border border-gray-200/80 bg-white/88 p-1 text-xs shadow-xl shadow-gray-950/10 backdrop-blur-xl dark:border-white/10 dark:bg-[#18181b]/90">
                      <Button
                        type="button"
                        variant={statusPopoverOpen ? "secondary" : "ghost"}
                        size="sm"
                        className="h-8 gap-1.5 rounded-full px-3 text-xs"
                        onClick={() => {
                          setNodeContextMenu(null)
                          setCanvasContextMenu(null)
                          setNodeDetails(null)
                          setStatusPopoverOpen((open) => !open)
                        }}
                      >
                        <GitBranch className="size-3.5" />
                        工作链
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-8 gap-1.5 rounded-full px-3 text-xs"
                        onClick={() => {
                          setStatusPopoverOpen(false)
                          handleFitView()
                        }}
                      >
                        <Maximize2 className="size-3.5" />
                        适应
                      </Button>
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}
            {edgeContextMenu && contextMenuEdge ? (
              <div
                className="fixed z-[260] min-w-44 overflow-hidden rounded-lg border border-gray-200 bg-white p-1 text-[12px] text-gray-700 shadow-2xl shadow-gray-950/20 dark:border-white/10 dark:bg-[#18181b] dark:text-gray-100"
                style={{ left: edgeContextMenu.x, top: edgeContextMenu.y }}
                onPointerDown={(event) => event.stopPropagation()}
                onClick={(event) => event.stopPropagation()}
              >
                <button
                  type="button"
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors",
                    contextMenuEdgeLocked
                      ? "cursor-not-allowed text-gray-400"
                      : "text-rose-600 hover:bg-rose-50 dark:text-rose-300 dark:hover:bg-rose-950/30"
                  )}
                  disabled={contextMenuEdgeLocked}
                  onClick={() => handleRemoveContextEdge(contextMenuEdge.id)}
                >
                  {contextMenuEdgeLocked ? (
                    <Lock className="size-3.5" />
                  ) : (
                    <Trash2 className="size-3.5" />
                  )}
                  {contextMenuEdgeLocked
                    ? "锁定链接"
                    : contextMenuEdge.data?.kind === "material"
                      ? "取消链接"
                      : "删除依赖线"}
                </button>
              </div>
            ) : null}
            <WorkflowNodeContextMenu
              model={nodeContextMenuModel}
              position={nodeContextMenu}
              actions={nodeContextMenuActions}
              projectId={project.id}
              episodeId={episodeId}
            />
            {canvasContextMenu ? (
              <div
                className="fixed z-[260] min-w-44 overflow-hidden rounded-lg border border-gray-200 bg-white p-1 text-[12px] text-gray-700 shadow-2xl shadow-gray-950/20 dark:border-white/10 dark:bg-[#18181b] dark:text-gray-100"
                style={{
                  left: canvasContextMenu.x,
                  top: canvasContextMenu.y,
                }}
                onPointerDown={(event) => event.stopPropagation()}
                onClick={(event) => event.stopPropagation()}
              >
                <div className="px-2.5 py-2 text-[11px] font-semibold text-gray-400 dark:text-gray-500">
                  画布操作
                </div>
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
                  onClick={() => void handleCreateIndependentSourceCard(canvasContextMenu.flowPosition)}
                >
                  <FilePlus2 className="size-3.5" />
                  创建独立原文
                </button>
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
                  onClick={() =>
                    void handleCreateCanvasWorkflowChain(
                      canvasContextMenu.flowPosition
                    )
                  }
                >
                  <GitBranch className="size-3.5" />
                  创建工作链
                </button>
                {CANVAS_TASK_NODE_OPTIONS.map((option) => (
                  <button
                    key={option.type}
                    type="button"
                    className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
                    onClick={() =>
                      void handleCreateCanvasTaskNode(
                        option.type,
                        canvasContextMenu.flowPosition
                      )
                    }
                  >
                    <ImagePlus className="size-3.5" />
                    {option.label}
                  </button>
                ))}
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
                  onClick={() => {
                    const placementPosition = canvasContextMenu.flowPosition
                    setCanvasContextMenu(null)
                    openAddAssetDialog(lastAddAssetKind, placementPosition)
                  }}
                >
                  <Package className="size-3.5" />
                  添加资产/上传媒体
                </button>
                {availableCopiedAssetClipboard ? (
                  <>
                    <div className="my-1 h-px bg-gray-200 dark:bg-white/10" />
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
                      onClick={() =>
                        void handlePasteCanvasAssetNode(
                          canvasContextMenu.flowPosition
                        )
                      }
                    >
                      <ClipboardList className="size-3.5" />
                      粘贴资产
                    </button>
                  </>
                ) : null}
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
                  onClick={() => {
                    closeCanvasMenus()
                    setShortcutsOpen(true)
                  }}
                >
                  <Keyboard className="size-3.5" />
                  快捷键
                </button>
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-gray-100 dark:hover:bg-white/10"
                  onClick={() => {
                    setCanvasContextMenu(null)
                    handleFitView()
                  }}
                >
                  <Maximize2 className="size-3.5" />
                  适应视图
                </button>
              </div>
            ) : null}
            <StoryboardImageEditFloatingPanel
              node={storyboardImageEditNode}
              sourceModelId={imageEditSourceModelId}
              hidden={canvasViewportDragging}
            />
            {sourceSplitEditor ? (
              <SourceSplitEditor
                independent={sourceSplitEditor.independent}
                needsApply={sourceSplitEditor.needsApply}
                title={
                  sourceSplitEditorNode?.data.episodeTitle ||
                  sourceSplitEditorNode?.data.title ||
                  "当前分集原文"
                }
                sourceText={sourceSplitEditor.sourceText}
                segments={sourceSplitEditor.segments}
                originalSegments={sourceSplitEditor.originalSegments}
                mode={sourceSplitEditor.mode}
                onModeChange={(mode) =>
                  setSourceSplitEditor((current) => current ? { ...current, mode } : current)
                }
                onSaveSource={handleSourceTextSave}
                generatedCount={sourceSplitEditor.generatedCount}
                saving={sourceSplitSaving}
                onSegmentsChange={(segments) =>
                  setSourceSplitEditor((current) =>
                    current ? { ...current, segments } : current
                  )
                }
                onConfirm={handleSourceSplitConfirm}
                onClose={() => setSourceSplitEditor(null)}
              />
            ) : null}
            {videoClipDialogSource ? (
              <VideoClipDialog
                projectId={project.id}
                episodeId={episodeId}
                source={videoClipDialogSource}
                onClose={() => setVideoClipDialogSource(null)}
                onCopyAsset={handleCopyVideoClipResultAsset}
                onDropToCanvas={handleDropVideoClipResultToCanvas}
              />
            ) : null}
            {nodeDetails && detailNode ? (
              <div
                className="nodrag nopan nowheel fixed z-[130] overflow-y-auto rounded-lg border border-gray-200 bg-white p-3 text-xs text-gray-700 shadow-2xl shadow-gray-950/20 dark:border-white/10 dark:bg-[#18181b] dark:text-gray-100"
                style={nodeDetailsPanelStyle}
                onPointerDown={(event) => event.stopPropagation()}
                onClick={(event) => event.stopPropagation()}
                onWheel={stopCardWheel}
                onWheelCapture={stopCardWheel}
              >
                <div className="mb-3 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-mono text-[10px] font-semibold text-gray-400 uppercase dark:text-gray-500">
                      {detailNode.data.eyebrow}
                    </div>
                    <div className="mt-1 truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
                      {detailNode.data.title}
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-[11px]"
                    onClick={() => setNodeDetails(null)}
                  >
                    关闭
                  </Button>
                </div>
                <div className="mb-3 grid gap-1.5">
                  {detailRows.map(([label, value]) => (
                    <div
                      key={label}
                      className="grid grid-cols-[4rem_1fr] gap-2"
                    >
                      <span className="text-gray-400 dark:text-gray-500">
                        {label}
                      </span>
                      <span className="truncate text-gray-700 dark:text-gray-200">
                        {value}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            <WorkflowEditHistoryDialog
              controller={editHistory}
              nodeTitle={editHistoryNodeTitle}
              nodeType={editHistoryNodeType}
            />

            <ConfirmDialog
              open={Boolean(deleteChainTarget)}
              title="删除工作链"
              description="确认删除这条独立工作链及其卡片和结果记录？共享素材和其他工作链会保留。"
              confirmLabel="删除整条工作链"
              loadingLabel="删除中..."
              loading={deletingChain}
              onCancel={() => setDeleteChainTarget(null)}
              onConfirm={handleDeleteWorkflowChain}
            />
            <ConfirmDialog
              open={Boolean(deleteSourceTarget)}
              title="删除独立原文"
              description="确认删除这张独立原文，以及它生成的全部工作链、链内卡片和结果记录？共享素材和其他工作链会保留。"
              confirmLabel="删除分集原文及工作链"
              loadingLabel="删除中..."
              loading={deletingSource}
              onCancel={() => setDeleteSourceTarget(null)}
              onConfirm={deleteIndependentSource}
            />
            <Dialog
              open={Boolean(nodeVersionHistoryDialog)}
              onOpenChange={(open) => {
                if (!open) {
                  setNodeVersionHistoryDialog(null)
                }
              }}
            >
              <DialogContent
                className="grid max-h-[min(84dvh,760px)] !w-[min(920px,calc(100vw-1.5rem))] !max-w-none grid-rows-[auto,minmax(0,1fr)] overflow-hidden"
                onInteractOutside={(event) => {
                  const target = event.target
                  if (
                    target instanceof Element &&
                    (target.closest("[data-media-lightbox='true']") ||
                      target.closest("[data-version-context-menu='true']"))
                  ) {
                    event.preventDefault()
                  }
                }}
                onPointerDownOutside={(event) => {
                  const target = event.target
                  if (
                    target instanceof Element &&
                    (target.closest("[data-media-lightbox='true']") ||
                      target.closest("[data-version-context-menu='true']"))
                  ) {
                    event.preventDefault()
                  }
                }}
              >
                <DialogHeader className="border-b border-gray-200/80 pb-3 dark:border-white/10">
                  <DialogTitle>历史版本</DialogTitle>
                  <DialogDescription>
                    {nodeVersionHistoryDescription}
                  </DialogDescription>
                </DialogHeader>
                <div className="min-h-0">
                  {nodeVersionHistoryNode ? (
                    <StoryboardVersionPanel
                      projectId={project.id}
                      episodeId={episodeId}
                      node={nodeVersionHistoryNode}
                      onChanged={handleNodeVersionHistoryChanged}
                      onWorkflowVersionChanged={handleVersionRevisionChanged}
                      onWorkflowMutationCommitted={handleVersionMutationCommitted}
                      activationMode={workflowNodeVersionActivationMode(
                        nodeVersionHistoryNode
                      )}
                      deleteMode={workflowNodeVersionDeleteMode(
                        nodeVersionHistoryNode
                      )}
                      activeVersionIdOverride={
                        workflowNodeVersionActivationMode(
                          nodeVersionHistoryNode
                        ) === "local"
                          ? workflowNodeCurrentVersionId(nodeVersionHistoryNode)
                          : undefined
                      }
                      versionNodeIdOverride={
                        workflowNodeVersionActivationMode(
                          nodeVersionHistoryNode
                        ) === "local"
                          ? nodeVersionHistoryNode.id
                          : undefined
                      }
                      onCreateCanvasAsset={
                        workflowCanDragVersionToCanvas(nodeVersionHistoryNode)
                          ? handleCreateStoryboardVersionCanvasAsset
                          : undefined
                      }
                      onCopyCanvasAsset={
                        workflowCanDragVersionToCanvas(nodeVersionHistoryNode)
                          ? handleCopyStoryboardVersionCanvasAsset
                          : undefined
                      }
                    />
                  ) : (
                    <div className="rounded-md border border-dashed border-gray-300/80 px-3 py-6 text-center text-xs text-gray-500 dark:border-white/15 dark:text-gray-400">
                      版本节点不在当前画布中
                    </div>
                  )}
                </div>
              </DialogContent>
            </Dialog>
          </>
        </div>
      </div>
      <Dialog open={shortcutsOpen} onOpenChange={setShortcutsOpen}>
        <DialogContent
          className="!w-[min(480px,calc(100vw-1.5rem))] !max-w-none"
          onPaste={(event) => event.stopPropagation()}
        >
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Keyboard className="size-4" />
              画布快捷键
            </DialogTitle>
            <DialogDescription>在画布中使用，输入文字时不生效。</DialogDescription>
          </DialogHeader>
          <dl className="max-h-[60vh] divide-y divide-border overflow-y-auto">
            {[
              { action: "范围选择", keys: ["左 Ctrl", "鼠标左键范围选取"] },
              { action: "追加 / 取消选择", keys: ["左 Ctrl", "单击卡片"] },
              { action: "平移画布", keys: ["鼠标左键拖动"] },
              { action: "缩放画布", keys: ["鼠标滚轮"] },
              { action: "粘贴图片", keys: ["Ctrl", "V"] },
              { action: "退出范围选择 / 关闭弹窗", keys: ["Esc"] },
            ].map(({ action, keys }) => (
              <div key={action} className="flex items-center justify-between gap-4 py-3">
                <dt className="text-sm">{action}</dt>
                <dd className="flex shrink-0 items-center gap-1.5 text-xs">
                  {keys.map((key, index) => (
                    <span key={key} className="flex items-center gap-1.5">
                      {index > 0 ? <span className="text-muted-foreground">+</span> : null}
                      <kbd className="rounded border border-border bg-muted/50 px-2 py-1 font-mono text-xs shadow-sm">
                        {key}
                      </kbd>
                    </span>
                  ))}
                </dd>
              </div>
            ))}
          </dl>
        </DialogContent>
      </Dialog>
      <Dialog
        open={Boolean(generationPreflightDialog)}
        onOpenChange={(open) => {
          if (!open) setGenerationPreflightDialog(null)
        }}
      >
        <DialogContent className="!w-[min(480px,calc(100vw-1.5rem))] !max-w-none">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="size-5 text-amber-500" />
              参考图超出模型上限
            </DialogTitle>
            <DialogDescription className="leading-6">
              {generationPreflightDialog?.message ||
                "参考图数量超过当前模型上限，请调整后再生成。"}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              onClick={() => setGenerationPreflightDialog(null)}
            >
              知道了
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={Boolean(renameAssetDraft)}
        onOpenChange={(open) => {
          if (!open && !savingRenameAsset) setRenameAssetDraft(null)
        }}
      >
        {renameAssetDraft ? (
          <DialogContent className="!w-[min(520px,calc(100vw-1.5rem))] !max-w-none">
            <DialogHeader>
              <DialogTitle>重命名资产</DialogTitle>
              <DialogDescription>
                {renameAssetDraft.kind === "video"
                  ? "修改视频资产名称。"
                  : "修改图片资产的名称和类别。"}
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-1">
              {renameAssetDraft.kind === "image" &&
              renameAssetDraft.mediaPurpose !== "frame_image" ? (
                <div className="grid gap-2">
                  <div className="text-xs font-semibold text-gray-600 dark:text-gray-300">
                    类别
                  </div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                    {RENAME_IMAGE_MEDIA_PURPOSE_OPTIONS.map((option) => {
                      const selected =
                        renameAssetDraft.mediaPurpose === option.value
                      return (
                        <button
                          key={option.value}
                          type="button"
                          className={cn(
                            "rounded-md border px-3 py-2 text-center text-xs font-semibold transition-colors",
                            selected
                              ? "border-indigo-300 bg-indigo-50 text-indigo-800 dark:border-indigo-800 dark:bg-indigo-950/35 dark:text-indigo-200"
                              : "border-gray-200/70 bg-white/70 text-gray-600 hover:border-indigo-200 hover:bg-indigo-50/50 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-300 dark:hover:border-indigo-900/60 dark:hover:bg-indigo-950/20"
                          )}
                          onClick={() =>
                            setRenameAssetDraft((current) =>
                              current
                                ? {
                                    ...current,
                                    mediaPurpose: option.value,
                                    voiceStyle: mediaPurposeUsesVoiceStyle(
                                      option.value
                                    )
                                      ? current.voiceStyle
                                      : "",
                                  }
                                : current
                            )
                          }
                          disabled={savingRenameAsset}
                        >
                          {option.label}
                        </button>
                      )
                    })}
                  </div>
                </div>
              ) : null}
              <div className="grid gap-1.5">
                <div className="text-xs font-semibold text-gray-600 dark:text-gray-300">
                  {renameAssetDraft.kind === "video"
                    ? "视频名称"
                    : `${
                        RENAME_IMAGE_MEDIA_PURPOSE_OPTIONS.find(
                          (option) =>
                            option.value === renameAssetDraft.mediaPurpose
                        )?.label ?? "图片"
                      }名称`}
                </div>
                <Input
                  value={renameAssetDraft.title}
                  onChange={(event) =>
                    setRenameAssetDraft((current) =>
                      current
                        ? { ...current, title: event.target.value }
                        : current
                    )
                  }
                  placeholder="输入名称"
                  className="h-9 rounded-md border-gray-200/80 bg-white/70 text-[12px] dark:border-white/10 dark:bg-white/[0.035]"
                  disabled={savingRenameAsset}
                  autoFocus
                />
              </div>
              {renameAssetDraft.kind === "image" &&
              mediaPurposeUsesVoiceStyle(renameAssetDraft.mediaPurpose) ? (
                <div className="grid gap-1.5">
                  <div className="text-xs font-semibold text-gray-600 dark:text-gray-300">
                    {mediaPurposeVoiceStyleLabel(renameAssetDraft.mediaPurpose)}
                  </div>
                  <Textarea
                    value={renameAssetDraft.voiceStyle}
                    onChange={(event) =>
                      setRenameAssetDraft((current) =>
                        current
                          ? { ...current, voiceStyle: event.target.value }
                          : current
                      )
                    }
                    placeholder={`${mediaPurposeVoiceStyleLabel(
                      renameAssetDraft.mediaPurpose
                    )} / 音色提示`}
                    className="min-h-20 resize-none rounded-md border-gray-200/80 bg-white/70 text-[12px] dark:border-white/10 dark:bg-white/[0.035]"
                    disabled={savingRenameAsset}
                  />
                </div>
              ) : null}
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setRenameAssetDraft(null)}
                disabled={savingRenameAsset}
              >
                取消
              </Button>
              <Button
                type="button"
                onClick={() => void handleSaveRenameAsset()}
                disabled={savingRenameAsset}
                className="gap-2"
              >
                {savingRenameAsset ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Save className="size-4" />
                )}
                保存
              </Button>
            </DialogFooter>
          </DialogContent>
        ) : null}
      </Dialog>
      <WorkflowAssetDialog {...assetDialogProps} />
    </>
  )
}
