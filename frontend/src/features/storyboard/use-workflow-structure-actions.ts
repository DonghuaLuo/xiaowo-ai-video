import { isWorkflowVisualHandoffOutputEdge } from "./workflow-node-relations"
import type { WorkflowNodeActions } from "./workflow-canvas-model"
import {
  isWorkflowTaskResultEdge,
  canvasMutationRevision,
} from "./workflow-document-model"
import { useCallback, useEffect, useRef, useState } from "react"
import {
  CANVAS_TASK_NODE_OPTIONS,
  defaultWorkflowCardSize,
  removeInputLinksFromNode,
  upsertStoryboardEdgeLocally,
  workflowNodeId,
  workflowTaskResultNodeType,
  type NewWorkflowTaskType,
  type SourceSplitEditorState,
} from "./workflow-canvas-asset-model"
import {
  recordValue,
  toStoryboardEdgesFromBackend,
  toStoryboardNodesFromBackend,
  upsertStoryboardNodesLocally,
  type StoryboardNode,
} from "./workflow-canvas-model"
import { inputLinkMatchesAnyDirectId } from "./workflow-input-readiness"
import {
  isCopiedWorkflowAssetNode,
  isStandaloneWorkflowTaskNode,
  isWorkflowContextDeleteLocked,
  isWorkflowContextDeleteVisible,
} from "./workflow-node-relations"
import { sourceSplitSeedsForWorkflow } from "./workflow-prompt-node-model"
import { toast } from "sonner"
import {
  adjustSourceSplitWorkflow,
  applyIndependentSourceWorkflow,
  createIndependentSourceCard,
  getCanvasRecords,
  getEpisodeSourceText,
  createManualWorkflowChain,
  createWorkflowTaskCard,
  deleteWorkflowChain,
  deleteWorkflowNode,
  type WorkflowEdge,
  type WorkflowNode,
} from "@/backend"
import { errMsg } from "@/shared/backend-result"
import {
  adjustSegmentCount,
  initialSourceSplitSegments,
} from "./source-split-model"
import { createWorkChainDraft, type WorkChainDraft } from "./work-chain-draft"
import type { BackendCaller } from "@/backend"
import type { WorkflowCanvasDocument } from "./workflow-canvas-document"
import type { useWorkflowDocumentSync } from "./use-workflow-document-sync"
export function useWorkflowStructureActions({
  projectId,
  episodeId,
  backendReady,
  callBackend,
  canvasDocument,
  documentSync,
  workflowNodeActions,
  dismiss,
  centerViewport,
}: {
  projectId: string
  episodeId: string
  backendReady: boolean
  callBackend: BackendCaller
  canvasDocument: WorkflowCanvasDocument
  documentSync: ReturnType<typeof useWorkflowDocumentSync>
  workflowNodeActions: WorkflowNodeActions
  dismiss: (reason: "create" | "delete") => void
  centerViewport: (
    x: number,
    y: number,
    options: { zoom: number; duration: number }
  ) => unknown
}) {
  const { nodes, edges, routes } = canvasDocument.read()
  const canvasScopeKey = projectId + "\u0000" + episodeId
  const sourceOpenRequestRef = useRef(0)
  const [sourceSplitEditor, setSourceSplitEditorState] =
    useState<SourceSplitEditorState | null>(null)
  const setSourceSplitEditor = useCallback<typeof setSourceSplitEditorState>((value) => {
    sourceOpenRequestRef.current += 1
    setSourceSplitEditorState(value)
  }, [])

  const [sourceSplitSaving, setSourceSplitSaving] = useState(false)

  useEffect(() => {
    setSourceSplitEditor(null)
    setSourceSplitSaving(false)
  }, [canvasScopeKey])

  useEffect(() => {
    if (sourceSplitEditor && !nodes.some((node) => node.id === sourceSplitEditor.nodeId)) {
      setSourceSplitEditor(null)
    }
  }, [nodes, sourceSplitEditor, setSourceSplitEditor])

  const [deleteChainTarget, setDeleteChainTarget] = useState<string | null>(
    null
  )

  const [deletingChain, setDeletingChain] = useState(false)
  const [deleteSourceTarget, setDeleteSourceTarget] = useState<string | null>(null)
  const [deletingSource, setDeletingSource] = useState(false)

  useEffect(() => {
    setDeleteChainTarget(null)
    setDeletingChain(false)
    setDeleteSourceTarget(null)
    setDeletingSource(false)
  }, [canvasScopeKey])

  const workflowSaveQueueRef = useRef<Promise<void>>(Promise.resolve())

  const openSourceSplitEditor = useCallback(
    async (node: StoryboardNode) => {
      const requestScope = canvasDocument.scope
      const requestId = ++sourceOpenRequestRef.current
      const isCurrent = () => canvasDocument.scope === requestScope && sourceOpenRequestRef.current === requestId
      const current = canvasDocument.read()
      const chains = current.workflowRootExtras.workChains ?? []
      const chainIds = new Set(chains.filter((chain) => chain.origin?.sourceNodeId === node.id).map((chain) => chain.id))
      const nodeIds = [node.id, ...current.nodes.filter((item) => item.data.eyebrow === "prompt.storyboard" && chainIds.has(item.data.workChainId ?? "")).map((item) => item.id)]
      let editorNodes: StoryboardNode[]
      try {
        const result = await getCanvasRecords(callBackend, projectId, episodeId, { detail: "full", ids: { nodeIds } })
        if (!isCurrent()) return
        editorNodes = toStoryboardNodesFromBackend(result.records.nodes ?? [], workflowNodeActions, current.routes)
        const loadedNode = editorNodes.find((item) => item.id === node.id)
        if (!loadedNode) throw new Error("分集原文已不存在，请刷新画布")
        node = loadedNode
        if (node.data.sourceMode !== "independent") {
          const detail = await getEpisodeSourceText(callBackend, projectId, episodeId)
          if (!isCurrent()) return
          node = { ...node, data: { ...node.data, sourceText: detail.text } }
        }
      } catch (error) {
        if (isCurrent()) toast.error(errMsg(error, "加载原文失败"))
        return
      }
      const sourceText = String(node.data.sourceText ?? "")
      const independent = node.data.sourceMode === "independent"
      const seeds = sourceSplitSeedsForWorkflow(node.id, editorNodes, chains)
      const generatedCount = seeds.length
      const seededSegments = initialSourceSplitSegments(sourceText, seeds)
      const initialSegments =
        seeds.length > 0 && (seededSegments.length !== seeds.length || seededSegments.some((segment) => !segment.workChainId))
          ? adjustSegmentCount(sourceText, seededSegments, generatedCount).map((segment, index) => ({
              ...segment, workChainId: seeds[index]?.id, templateWorkChainId: seeds[index]?.id,
            }))
          : seededSegments
      const fallbackSegments = initialSegments.length
        ? initialSegments
        : [
            {
              id: "split-1",
              text: sourceText,
              start: 0,
              end: sourceText.length,
            },
          ]
      setSourceSplitEditor({
        independent,
        needsApply: independent && (generatedCount === 0 || seeds.map((seed) => seed.text).join("") !== sourceText),
        nodeId: node.id,
        sourceText,
        segments: fallbackSegments,
        // Immutable snapshot for this editor session, including exact source text.
        originalSegments: fallbackSegments.map((segment) => ({ ...segment })),
        mode: independent && !sourceText.trim() ? "edit" : "split",
        workChainIds: seeds.map((seed) => seed.id),
        generatedCount,
      })
    },
    [canvasDocument, callBackend, projectId, episodeId, workflowNodeActions]
  )

  const handleCreateIndependentSourceCard = useCallback(async (position: { x: number; y: number }) => {
    if (!backendReady) { toast.error("后端尚未就绪"); return }
    const requestScope = canvasDocument.scope
    dismiss("create")
    try {
      const result = await createIndependentSourceCard(callBackend, projectId, episodeId, position)
      if (canvasDocument.scope !== requestScope) return
      documentSync.applyMutation({ ...result, projectId, episodeId })
      canvasDocument.selectWorkChain("all")
      canvasDocument.selectNode(result.sourceNodeId)
      await documentSync.reconcile("independent_source_card_created")
      if (canvasDocument.scope !== requestScope) return
      const [node] = toStoryboardNodesFromBackend([result.node], workflowNodeActions, canvasDocument.read().routes)
      if (node) await openSourceSplitEditor(node)
    } catch (error) {
      if (canvasDocument.scope === requestScope) toast.error(errMsg(error, "创建独立原文失败"))
    }
  }, [backendReady, canvasDocument, dismiss, callBackend, projectId, episodeId, documentSync, workflowNodeActions, openSourceSplitEditor])

  const handleSourceSplitConfirm = useCallback(async () => {
    if (!sourceSplitEditor || sourceSplitSaving) return
    if (!backendReady) {
      toast.error("后端尚未就绪")
      throw new Error("后端尚未就绪")
    }
    const requestScope = canvasDocument.scope
    const currentScope = () => canvasDocument.scope === requestScope
    setSourceSplitSaving(true)
    try {
      const payload = {
        sourceNodeId: sourceSplitEditor.nodeId,
        segments: sourceSplitEditor.segments.map((segment) => ({
          text: segment.text,
          workChainId: segment.workChainId,
          templateWorkChainId: segment.templateWorkChainId,
        })),
        workChainIds: sourceSplitEditor.workChainIds,
      }
      const result = sourceSplitEditor.independent
        ? await applyIndependentSourceWorkflow(callBackend, projectId, episodeId, {
            ...payload,
            sourceText: sourceSplitEditor.segments.map((segment) => segment.text).join(""),
            expectedSourceText: sourceSplitEditor.sourceText,
          })
        : await adjustSourceSplitWorkflow(callBackend, projectId, episodeId, payload)
      if (!currentScope()) return
      await documentSync.sync({ ...result, projectId, episodeId })
      if (!currentScope()) return
      setSourceSplitEditor(null)
      toast.success(sourceSplitEditor.independent ? `已应用 ${sourceSplitEditor.segments.length} 条独立剧情工作链` : `原文拆分已调整为 ${sourceSplitEditor.segments.length} 条`)
    } catch (error) {
      if (!currentScope()) return
      toast.error(errMsg(error, "调整原文拆分失败"))
      throw error
    } finally {
      if (currentScope()) setSourceSplitSaving(false)
    }
  }, [
    documentSync.sync,
    backendReady,
    callBackend,
    episodeId,
    projectId,
    documentSync.reconcile,
    sourceSplitEditor,
    sourceSplitSaving,
  ])

  const handleSourceTextSave = useCallback(async () => {
    if (!sourceSplitEditor || sourceSplitSaving) return
    const editedSegments = sourceSplitEditor.segments
    const text = editedSegments.map((segment) => segment.text).join("")
    const requestScope = canvasDocument.scope
    setSourceSplitSaving(true)
    try {
      // The node action stores independent text on the card and episode text in its source file.
      await workflowNodeActions.onUpdateNodeData(
        sourceSplitEditor.nodeId,
        { sourceText: text, summary: "" },
        sourceSplitEditor.independent ? "independent_source_text_saved" : "inline_source_text_saved",
        { showSuccess: false }
      )
      if (canvasDocument.scope !== requestScope) return
      setSourceSplitEditor((current) => current ? {
        ...current,
        sourceText: text,
        segments: editedSegments,
      } : current)
      toast.success(sourceSplitEditor.independent ? "独立原文已保存" : "分集原文已保存")
    } catch {
      // The shared save action reports the error. Keep the draft for retry.
    } finally {
      if (canvasDocument.scope === requestScope) setSourceSplitSaving(false)
    }
  }, [canvasDocument, sourceSplitEditor, sourceSplitSaving, workflowNodeActions])

  const enqueueWorkflowNodeDelete = useCallback(
    (nodeId: string, reason: string) => {
      if (!backendReady) {
        return Promise.reject(new Error("后端尚未就绪"))
      }
      const requestScope = canvasDocument.scope
      const queuedDelete = deleteWorkflowNode(
        callBackend,
        projectId,
        episodeId,
        nodeId,
        {
          reason,
        }
      ).then(async (result) => {
        if (canvasDocument.scope !== requestScope) return
        if (result.skippedLocked) {
          toast.info(result.message ?? "节点已锁定，未删除")
          await documentSync.reconcile("delete_node_skipped_locked")
          return
        }
        documentSync.applyMutation({
          ...result,
          action: "workflow_item_deleted",
          projectId: projectId,
          episodeId,
          itemType: result.itemType ?? "node",
          itemId: result.itemId ?? nodeId,
        })
        if (
          result.workflowVersion !== undefined &&
          result.workflowVersion !== null
        ) {
          canvasDocument.confirmRevision(result.workflowVersion)
        } else {
          canvasDocument.invalidateRevision()
        }
      })
      workflowSaveQueueRef.current = queuedDelete.catch(() => undefined)
      return queuedDelete
    },
    [
      documentSync.applyMutation,
      backendReady,
      callBackend,
      episodeId,
      projectId,
      documentSync.reconcile,
      canvasDocument.confirmRevision,
    ]
  )

  const handleCreateCanvasTaskNode = useCallback(
    async (
      nodeType: NewWorkflowTaskType,
      position: { x: number; y: number }
    ) => {
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const requestScope = canvasDocument.scope
      const currentScope = () => canvasDocument.scope === requestScope
      const option = CANVAS_TASK_NODE_OPTIONS.find(
        (item) => item.type === nodeType
      )
      if (!option) return
      const nodeId = workflowNodeId(nodeType.replace(/\./g, "_"))
      const size = defaultWorkflowCardSize(nodeType)
      const resultNodeType = workflowTaskResultNodeType(nodeType)
      const resultNodeId = resultNodeType
        ? workflowNodeId(resultNodeType.replace(/\./g, "_"))
        : ""
      const resultPosition = {
        x: position.x + size.width + 120,
        y: position.y,
      }
      const createdAt = new Date().toISOString()
      const taskBackendNode: WorkflowNode = {
        id: nodeId,
        type: nodeType,
        strategy: option.strategy ?? "manual",
        position,
        data: {
          title: option.label.replace(/^新建/, ""),
          status: "draft",
          summary: option.summary,
          strategy: option.strategy ?? "manual",
          generationConfig: option.generationConfig ?? {},
          cardState: { size },
          videoTaskCard: {
            promptKind: "final_provider_prompt",
            videoPromptKind: "final_provider_prompt",
            sourceAdapter: "standalone_direct_prompt",
          },
          visibilityScope: "global",
          provenance: {
            source: "user",
            action: "canvas_task_node_created",
            createdAt,
          },
        },
      }
      const resultBackendNode: WorkflowNode | null = resultNodeType
        ? {
            id: resultNodeId,
            type: resultNodeType,
            position: resultPosition,
            data: {
              title: "视频片段",
              status: "waiting_upstream",
              summary: "等待视频节点生成并写入结果视频。",
              resultOfNodeId: nodeId,
              assetScope: "result",
              assetKind: "video",
              mediaPurpose: "video_result",
              visibilityScope: "global",
              cardState: { size: defaultWorkflowCardSize(resultNodeType) },
              provenance: {
                source: "user",
                action: "canvas_video_result_created",
                createdAt,
                resultOfNodeId: nodeId,
              },
            },
          }
        : null
      const resultBackendEdge: WorkflowEdge | null = resultBackendNode
        ? {
            id: `dependency-${nodeId}-${resultNodeId}-generates`,
            source: nodeId,
            target: resultNodeId,
            sourceHandle: "video",
            targetHandle: "generates",
            deletable: false,
            data: {
              kind: "dependency",
              role: "generates",
              sourceNodeType: nodeType,
              targetNodeType: resultNodeType,
              targetSlot: "generates",
              locked: true,
              preserveOnReplan: true,
              lockedReason: "任务节点的系统结果链接不可删除",
            },
          }
        : null
      const optimisticBackendNodes = [
        taskBackendNode,
        resultBackendNode,
      ].filter((node): node is WorkflowNode => Boolean(node))
      const optimisticStoryboardNodes = toStoryboardNodesFromBackend(
        optimisticBackendNodes,
        workflowNodeActions,
        routes
      )
      const optimisticBackendEdges = [resultBackendEdge].filter(
        (edge): edge is WorkflowEdge => Boolean(edge)
      )
      const optimisticStoryboardEdges = optimisticBackendEdges.length
        ? toStoryboardEdgesFromBackend(
            optimisticBackendEdges,
            nodes,
            optimisticBackendNodes,
            routes
          )
        : []
      const optimisticNodeIds = new Set(
        optimisticBackendNodes.map((node) => node.id)
      )
      const optimisticEdgeIds = new Set(
        optimisticStoryboardEdges.map((edge) => edge.id)
      )
      dismiss("create")
      canvasDocument.updateNodes((current) =>
        upsertStoryboardNodesLocally(current, optimisticStoryboardNodes)
      )
      canvasDocument.updateEdges((current) =>
        optimisticStoryboardEdges.reduce(
          (nextEdges, edge) => upsertStoryboardEdgeLocally(nextEdges, edge),
          current
        )
      )
      canvasDocument.selectNode(nodeId)
      window.setTimeout(() => {
        if (!currentScope()) return
        centerViewport(
          position.x + size.width / 2,
          position.y + size.height / 2,
          { zoom: 0.9, duration: 260 }
        )
      }, 0)
      try {
        const result = await createWorkflowTaskCard(
          callBackend,
          projectId,
          episodeId,
          {
            nodeType,
            nodeId,
            ...(resultNodeId ? { resultNodeId } : {}),
            position,
            resultPosition,
            title: option.label.replace(/^新建/, ""),
            summary: option.summary,
            status: "draft",
            data: {
              strategy: option.strategy ?? "manual",
            },
            generationConfig: option.generationConfig ?? {},
            size,
          }
        )
        if (!currentScope()) return
        const backendNodes = [result.node, result.resultNode].filter(
          (node): node is WorkflowNode => Boolean(node)
        )
        const storyboardNodes = toStoryboardNodesFromBackend(
          backendNodes,
          workflowNodeActions,
          routes
        )
        canvasDocument.updateNodes((current) =>
          upsertStoryboardNodesLocally(current, storyboardNodes)
        )
        const backendEdges = [result.edge].filter(
          (edge): edge is WorkflowEdge => Boolean(edge)
        )
        if (backendEdges.length) {
          const storyboardEdges = toStoryboardEdgesFromBackend(
            backendEdges,
            nodes,
            backendNodes,
            routes
          )
          canvasDocument.updateEdges((current) =>
            storyboardEdges.reduce(
              (nextEdges, edge) => upsertStoryboardEdgeLocally(nextEdges, edge),
              current
            )
          )
        }
        const workflowVersion = result.workflowVersion
        if (workflowVersion !== undefined && workflowVersion !== null) {
          canvasDocument.confirmRevision(workflowVersion)
        }
        const createdNodeId = result.node?.id ?? nodeId
        canvasDocument.selectNode(createdNodeId)
        toast.success(
          result.resultNode ? "任务节点与结果已创建" : "任务节点已创建"
        )
      } catch (error) {
        if (!currentScope()) return
        canvasDocument.updateNodes((current) =>
          current.filter((node) => !optimisticNodeIds.has(node.id))
        )
        canvasDocument.updateEdges((current) =>
          current.filter(
            (edge) =>
              !optimisticEdgeIds.has(edge.id) &&
              !optimisticNodeIds.has(edge.source) &&
              !optimisticNodeIds.has(edge.target)
          )
        )
        canvasDocument.selectNode((current) =>
          current && optimisticNodeIds.has(current) ? null : current
        )
        toast.error(errMsg(error, "创建任务节点失败"))
      }
    },
    [
      backendReady,
      canvasScopeKey,
      callBackend,
      episodeId,
      nodes,
      projectId,
      routes,
      canvasDocument.updateEdges,
      canvasDocument.updateNodes,
      canvasDocument.confirmRevision,
      workflowNodeActions,
    ]
  )

  const handleCreateCanvasWorkflowChain = useCallback(
    async (position: { x: number; y: number }) => {
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const workChainId = workflowNodeId("chain")
      const draft = createWorkChainDraft(workChainId, position)
      const nodeIds = new Set(draft.nodes.map((node) => node.id))
      const requestScope = canvasDocument.scope
      const currentScope = () => canvasDocument.scope === requestScope
      const finalizeLocalPendingCreation = () => {
        if (!canvasDocument.pendingCreation(workChainId)) return
        canvasDocument.finishCreation(workChainId)
        canvasDocument.updateNodes((current) =>
          current.map((node) =>
            node.data.workChainId === workChainId && node.data.creationPending
              ? { ...node, data: { ...node.data, creationPending: false } }
              : node
          )
        )
      }
      canvasDocument.stageCreation(workChainId, draft)
      const displayRecords = (records: WorkChainDraft) => {
        canvasDocument.updateNodes((current) =>
          upsertStoryboardNodesLocally(
            current,
            toStoryboardNodesFromBackend(
              records.nodes,
              workflowNodeActions,
              records.routes
            )
          )
        )
        const incomingEdges = toStoryboardEdgesFromBackend(
          records.edges,
          canvasDocument.read().nodes,
          records.nodes,
          records.routes
        )
        canvasDocument.updateEdges((current) =>
          incomingEdges.reduce(
            (edges, edge) => upsertStoryboardEdgeLocally(edges, edge),
            current
          )
        )
        canvasDocument.updateRoutes((current) => [
          ...current.filter((route) => route.workChainId !== workChainId),
          ...records.routes,
        ])
        canvasDocument.updateMetadata((current) => ({
          ...current,
          workChains: [
            ...(current.workChains ?? []).filter(
              (chain) => chain.id !== workChainId
            ),
            ...records.workChains,
          ],
        }))
      }
      dismiss("create")
      displayRecords(draft)
      canvasDocument.selectWorkChain("all")
      canvasDocument.selectNode(draft.nodes[0].id)
      try {
        const result = await createManualWorkflowChain(
          callBackend,
          projectId,
          episodeId,
          { workChainId, position }
        )
        if (!currentScope()) return
        if (!canvasDocument.isStaleRevision(canvasMutationRevision(result))) {
          const applied = documentSync.applyMutation({
            ...result,
            projectId: projectId,
            action: "manual_workflow_chain_created",
          })
          if (!applied)
            await documentSync.sync({ ...result, projectId: projectId })
        } else {
          finalizeLocalPendingCreation()
        }
        if (!currentScope()) return
        finalizeLocalPendingCreation()
        toast.success("工作链已创建")
      } catch (error) {
        if (!currentScope()) return
        if (!canvasDocument.pendingCreation(workChainId)) return
        canvasDocument.finishCreation(workChainId)
        canvasDocument.updateNodes((current) =>
          current.filter((node) => !nodeIds.has(node.id))
        )
        canvasDocument.updateEdges((current) =>
          current.filter(
            (edge) => !nodeIds.has(edge.source) && !nodeIds.has(edge.target)
          )
        )
        canvasDocument.updateRoutes((current) =>
          current.filter((route) => route.workChainId !== workChainId)
        )
        canvasDocument.updateMetadata((current) => ({
          ...current,
          workChains: (current.workChains ?? []).filter(
            (chain) => chain.id !== workChainId
          ),
        }))
        canvasDocument.selectNode((current) =>
          current && nodeIds.has(current) ? null : current
        )
        toast.error(errMsg(error, "创建工作链失败"))
        void documentSync.reconcile("create_work_chain_failed")
      }
    },
    [
      documentSync.sync,
      documentSync.applyMutation,
      backendReady,
      callBackend,
      canvasScopeKey,
      episodeId,
      canvasDocument,
      projectId,
      documentSync.reconcile,
      canvasDocument.updateEdges,
      canvasDocument.updateNodes,
      workflowNodeActions,
    ]
  )

  const handleDeleteWorkflowChain = useCallback(async () => {
    if (!deleteChainTarget || !backendReady || deletingChain) return
    const requestScope = canvasDocument.scope
    const currentScope = () => canvasDocument.scope === requestScope
    if (requestScope.key !== canvasScopeKey) return
    setDeletingChain(true)
    try {
      const result = await deleteWorkflowChain(
        callBackend,
        projectId,
        episodeId,
        deleteChainTarget
      )
      if (!currentScope()) return
      await documentSync.sync({ ...result, projectId: projectId })
      if (!currentScope()) return
      setDeleteChainTarget(null)
      dismiss("delete")
      canvasDocument.selectNode((current) =>
        result.deletedNodeIds?.includes(current ?? "") ? null : current
      )
      canvasDocument.selectWorkChain((current) =>
        current === deleteChainTarget ? "all" : current
      )
      toast.success("工作链已删除")
    } catch (error) {
      if (!currentScope()) return
      toast.error(errMsg(error, "删除工作链失败"))
    } finally {
      if (currentScope()) setDeletingChain(false)
    }
  }, [
    documentSync.sync,
    backendReady,
    callBackend,
    canvasScopeKey,
    deleteChainTarget,
    deletingChain,
    episodeId,
    projectId,
  ])

  const handleDeleteIndependentSource = useCallback(async () => {
    if (!deleteSourceTarget || !backendReady || deletingSource) return
    const requestScope = canvasDocument.scope
    const currentScope = () => canvasDocument.scope === requestScope
    if (requestScope.key !== canvasScopeKey) return
    setDeletingSource(true)
    const deletion = deleteWorkflowNode(callBackend, projectId, episodeId, deleteSourceTarget, { reason: "independent_source_deleted" })
    workflowSaveQueueRef.current = deletion.then(() => undefined, () => undefined)
    try {
      const result = await deletion
      if (!currentScope()) return
      if (result.skippedLocked) {
        toast.info(result.message ?? "独立原文已锁定，未删除")
        return
      }
      await documentSync.sync({ ...result, projectId, episodeId })
      if (!currentScope()) return
      setDeleteSourceTarget(null)
      setSourceSplitEditor((current) => current?.nodeId === deleteSourceTarget ? null : current)
      canvasDocument.selectNode((current) => result.deletedNodeIds?.includes(current ?? "") ? null : current)
      canvasDocument.selectWorkChain((current) => result.deletedWorkChainIds?.includes(current) ? "all" : current)
      toast.success("独立原文及关联工作链已删除")
    } catch (error) {
      if (currentScope()) toast.error(errMsg(error, "删除独立原文失败"))
    } finally {
      if (currentScope()) setDeletingSource(false)
    }
  }, [deleteSourceTarget, backendReady, deletingSource, canvasDocument, canvasScopeKey, callBackend, projectId, episodeId, documentSync, setSourceSplitEditor])

  const handleDeleteContextNode = useCallback(
    async (nodeId: string) => {
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const requestScope = canvasDocument.scope
      const target = nodes.find((node) => node.id === nodeId)
      if (!target) {
        return
      }
      if (!isWorkflowContextDeleteVisible(target)) {
        toast.info("该节点不能删除")
        return
      }
      if (isWorkflowContextDeleteLocked(target)) {
        toast.info("该节点已锁定，不能删除")
        return
      }
      if (target.data.eyebrow === "source.text" && target.data.sourceMode === "independent") {
        dismiss("delete")
        setDeleteSourceTarget(nodeId)
        return
      }
      const deleteUserTaskPair = isStandaloneWorkflowTaskNode(target)
      const pairedResultNodeIds = deleteUserTaskPair
        ? edges
            .filter(
              (edge) =>
                edge.source === nodeId && isWorkflowTaskResultEdge(edge, nodes)
            )
            .map((edge) => nodes.find((node) => node.id === edge.target))
            .filter((node): node is StoryboardNode =>
              Boolean(
                node &&
                node.data.resultOfNodeId === nodeId &&
                !isCopiedWorkflowAssetNode(node)
              )
            )
            .map((node) => node.id)
        : []
      const deleteNodeIds = new Set([nodeId, ...pairedResultNodeIds])
      if (
        edges.some((edge) => {
          if (
            !deleteNodeIds.has(edge.source) &&
            !deleteNodeIds.has(edge.target)
          ) {
            return false
          }
          if (!isWorkflowTaskResultEdge(edge, nodes)) return false
          if (
            isWorkflowVisualHandoffOutputEdge(edge, nodes) &&
            deleteNodeIds.has(edge.target)
          ) {
            return false
          }
          return !(
            deleteUserTaskPair &&
            edge.source === nodeId &&
            deleteNodeIds.has(edge.target)
          )
        })
      ) {
        toast.info("任务结果节点或其系统链接不能删除")
        return
      }
      const removedInputLinkIds = new Set(
        edges
          .filter(
            (edge) =>
              edge.data?.kind === "material" &&
              (deleteNodeIds.has(edge.source) ||
                deleteNodeIds.has(edge.target)) &&
              edge.data.inputLinkId
          )
          .map((edge) => String(edge.data?.inputLinkId ?? ""))
          .filter(Boolean)
      )
      const nextNodes = nodes
        .filter((node) => !deleteNodeIds.has(node.id))
        .map((node) => {
          if (!removedInputLinkIds.size) return node
          const inputLinks = Array.isArray(node.data.inputLinks)
            ? node.data.inputLinks
            : []
          const nextLinks = inputLinks.filter(
            (link) =>
              !inputLinkMatchesAnyDirectId(
                recordValue(link),
                removedInputLinkIds
              )
          )
          if (nextLinks.length === inputLinks.length) return node
          return removeInputLinksFromNode(
            node,
            removedInputLinkIds,
            "linked_item_deleted",
            new Date().toISOString()
          )
        })
      const nextEdges = edges.filter(
        (edge) =>
          !deleteNodeIds.has(edge.source) && !deleteNodeIds.has(edge.target)
      )
      dismiss("delete")
      canvasDocument.selectNode((current) =>
        current && deleteNodeIds.has(current) ? null : current
      )

      canvasDocument.updateNodes(nextNodes)
      canvasDocument.updateEdges(nextEdges)
      toast.success(deleteUserTaskPair ? "任务节点和结果已删除" : "节点已删除")
      void enqueueWorkflowNodeDelete(
        nodeId,
        deleteUserTaskPair ? "manual_task_pair_deleted" : "node_context_delete"
      ).catch(async (error) => {
        if (canvasDocument.scope !== requestScope) return
        toast.error(errMsg(error, "删除保存失败"))
        await documentSync.reconcile("delete_node_failed")
      })
    },
    [
      backendReady,
      edges,
      enqueueWorkflowNodeDelete,
      nodes,
      documentSync.reconcile,
      canvasDocument.updateEdges,
      canvasDocument.updateNodes,
    ]
  )
  useEffect(() => {
    workflowSaveQueueRef.current = Promise.resolve()
  }, [canvasScopeKey])
  const waitForWrites = useCallback(
    () => workflowSaveQueueRef.current.catch(() => undefined),
    []
  )

  return {
    waitForWrites,
    createTask: handleCreateCanvasTaskNode,
    createChain: handleCreateCanvasWorkflowChain,
    createIndependentSource: handleCreateIndependentSourceCard,
    deleteNode: handleDeleteContextNode,
    deleteChain: handleDeleteWorkflowChain,
    deleteTarget: deleteChainTarget,
    setDeleteTarget: setDeleteChainTarget,
    deleting: deletingChain,
    deleteSourceTarget,
    setDeleteSourceTarget,
    deletingSource,
    deleteIndependentSource: handleDeleteIndependentSource,
    sourceSplitEditor,
    setSourceSplitEditor,
    sourceSplitSaving,
    openSourceSplitEditor,
    confirmSourceSplit: handleSourceSplitConfirm,
    saveSourceText: handleSourceTextSave,
  }
}
