import { isWorkflowLockedSystemEdge } from "./workflow-node-relations"
import { useCallback } from "react"
import {
  isFrameImage,
  type FrameReferenceOptions,
} from "./frame-reference-menu"
import {
  collectInlineAssetTags,
  inlineAssetDisplayRows,
} from "./inline-asset-tags"
import {
  isWorkflowAssetNodeType,
  isWorkflowImageNodeType,
  materialConnectionAllowed,
  materialConnectionError,
  materialSourceType,
  materialTargetHandleAllowedForConnection,
  materialTargetHandleConnectionError,
  materialTargetHandleForDisplay,
  materialTargetSlotForConnection,
  workflowMaterialSourceHandle,
} from "./workflow-canvas-asset-model"
import {
  isWorkflowItemLocked,
  recordValue,
  type StoryboardEdge,
  type WorkflowNodeData,
} from "./workflow-canvas-model"
import { inputLinkMatchesDirectId } from "./workflow-input-readiness"
import { type Connection, type EdgeChange } from "@xyflow/react"
import { toast } from "sonner"
import {
  linkWorkflowInput,
  setWorkflowReferenceUsage,
  unlinkWorkflowInput,
  type WorkflowInputLinkPayload,
} from "@/backend"
import { errMsg } from "@/shared/backend-result"
import { canvasInputMutations } from "./canvas-input-mutations"
import { useEffect, useRef, useState } from "react"
import type { BackendCaller } from "@/backend"
import type { StoryboardNode } from "./workflow-canvas-model"

type ReferenceDraft<T> = T & { token: symbol; saving: boolean; confirmed?: T & { revision?: number } }
type FrameReferenceDraft = ReferenceDraft<{ options: FrameReferenceOptions }>
type ReferenceUsageDraft = ReferenceDraft<{ enabled: boolean }>
type CanvasInputSaveResult = { applied: boolean; revision?: number }

function pruneConfirmedReferenceDrafts<T>(
  byNode: Map<string, Map<string, ReferenceDraft<T>>>,
  graph: { nodes: StoryboardNode[]; workflowVersion?: number },
  matches: (row: ReturnType<typeof inlineAssetDisplayRows>[number], confirmed: T) => boolean,
) {
  let changed = false
  for (const [nodeId, drafts] of byNode) {
    const node = graph.nodes.find(item => item.id === nodeId)
    const rows = node ? inlineAssetDisplayRows(node.data) : []
    for (const [sourceNodeId, draft] of drafts) {
      const confirmed = draft.confirmed
      if (!confirmed) continue
      const row = rows.find(item => String(item.sourceNodeId ?? item.source_node_id ?? "") === sourceNodeId)
      const caughtUp = !node || (confirmed.revision !== undefined && graph.workflowVersion !== undefined
        ? graph.workflowVersion >= confirmed.revision
        : Boolean(row && matches(row, confirmed)))
      if (!caughtUp) continue
      draft.confirmed = undefined
      if (!draft.saving) drafts.delete(sourceNodeId)
      changed = true
    }
    if (!drafts.size) byNode.delete(nodeId)
  }
  return changed
}

function withReferenceDrafts(
  data: WorkflowNodeData,
  drafts?: Map<string, FrameReferenceDraft>,
  usageDrafts?: Map<string, ReferenceUsageDraft>
): WorkflowNodeData {
  if (!drafts?.size && !usageDrafts?.size) return data
  const patchRows = <T extends Record<string, unknown>>(
    rows: T[] | undefined
  ): T[] | undefined =>
    rows?.map((row) => {
      const sourceNodeId = String(row.sourceNodeId ?? row.source_node_id ?? "")
      const draft = drafts?.get(sourceNodeId)
      const usage = usageDrafts?.get(sourceNodeId)
      const next = draft && isFrameImage(row) ? { ...row, ...draft.options } : row
      return usage ? { ...next, enabled: usage.enabled } : next
    })
  return {
    ...data,
    referenceDisplayRows: patchRows(data.referenceDisplayRows),
    inputLinks: patchRows(data.inputLinks),
    referenceVideoThumbnails: patchRows(data.referenceVideoThumbnails),
    referenceThumbnails: patchRows(data.referenceThumbnails),
    assetThumbnails: patchRows(data.assetThumbnails),
  }
}

export function useWorkflowCanvasInputs({
  projectId,
  episodeId,
  backendReady,
  canvasLoaded,
  callBackend,
  readGraph,
  applyMutation,
  reconcile,
  onUnlinked,
  onPresentationEdgesChange,
}: {
  projectId: string
  episodeId: string
  backendReady: boolean
  canvasLoaded: boolean
  callBackend: BackendCaller
  readGraph: () => { nodes: StoryboardNode[]; edges: StoryboardEdge[]; workflowVersion?: number }
  applyMutation: (payload: Record<string, unknown>) => boolean
  reconcile: (reason: string) => Promise<boolean>
  onUnlinked: (nodeId: string) => void
  onPresentationEdgesChange: (changes: EdgeChange<StoryboardEdge>[]) => void
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
  const frameReferenceDraftsRef = useRef(
    new Map<string, Map<string, FrameReferenceDraft>>()
  )
  const referenceUsageDraftsRef = useRef(
    new Map<string, Map<string, ReferenceUsageDraft>>()
  )
  const [referenceDraftVersion, setReferenceDraftVersion] =
    useState(0)
  useEffect(() => {
    frameReferenceDraftsRef.current.clear()
    referenceUsageDraftsRef.current.clear()
    setReferenceDraftVersion((version) => version + 1)
  }, [canvasScopeKey])
  const { nodes: graphNodes, workflowVersion: graphRevision } = readGraph()
  useEffect(() => {
    // A saved input stays visible until the confirmed graph covers its revision.
    const graph = { nodes: graphNodes, workflowVersion: graphRevision }
    const framesChanged = pruneConfirmedReferenceDrafts(frameReferenceDraftsRef.current, graph,
      (row, saved) => (row.frameRole ?? "first_frame") === saved.options.frameRole &&
        (row.useNativeFrame !== false) === saved.options.useNativeFrame)
    const usageChanged = pruneConfirmedReferenceDrafts(referenceUsageDraftsRef.current, graph,
      (row, saved) => (row.enabled !== false) === saved.enabled)
    if (framesChanged || usageChanged) setReferenceDraftVersion(version => version + 1)
  }, [graphNodes, graphRevision, referenceDraftVersion, canvasScopeKey])
  const mutateCanvasInput = useCallback(
    (
      operation: "link" | "unlink" | "usage",
      nodeId: string,
      payload: WorkflowInputLinkPayload & { enabled?: boolean },
      feedback?: { success: string; isLatest: () => boolean }
    ): Promise<CanvasInputSaveResult | false> => {
      const requestScope = canvasRequestScopeRef.current
      if (requestScope.key !== canvasScopeKey || !canvasLoaded) {
        toast.info("画布正在切换，请稍后再试")
        return Promise.resolve(false)
      }
      const isCurrent = () => canvasRequestScopeRef.current === requestScope
      return canvasInputMutations.run(canvasScopeKey, nodeId, async () => {
        const toastId =
          isCurrent() && !feedback
            ? toast.loading("正在保存资产关联…")
            : undefined
        try {
          const mutate =
            operation === "usage" ? setWorkflowReferenceUsage : operation === "link" ? linkWorkflowInput : unlinkWorkflowInput
          const result = await mutate(callBackend, projectId, episodeId, {
            ...payload,
            nodeId,
            scope: "node",
          })
          if (!isCurrent()) return false
          const applied = applyMutation({
            ...result,
            action:
              operation === "usage" ? "workflow_reference_usage_updated" : operation === "link"
                ? "workflow_input_linked"
                : "workflow_input_unlinked",
            projectId: projectId,
            episodeId,
            targetNodeId: result.targetNodeId ?? nodeId,
          })
          if (result.skippedLocked) {
            if (!feedback || feedback.isLatest())
              toast.info(result.message || "该链接已锁定，未修改", {
                id: toastId,
              })
            return false
          } else {
            if (!feedback || feedback.isLatest())
              toast.success(
                feedback?.success ??
                  (operation === "usage" ? (payload.enabled ? "已启用参考资产" : "已禁用参考资产") : operation === "link" ? "素材关联已保存" : "链接已取消"),
                { id: toastId }
              )
            if (operation === "unlink") {
              onUnlinked(nodeId)
            }
            const revision = Number(result.workflowVersion)
            return { applied, revision: Number.isSafeInteger(revision) && revision > 0 ? revision : undefined }
          }
        } catch (error) {
          if (!isCurrent()) return false
          if (!feedback || feedback.isLatest())
            toast.error(
              feedback
                ? `${operation === "usage" ? "参考资产" : "帧画面"}设置保存失败，已恢复：${errMsg(error, "请重试")}`
                : errMsg(error, "保存资产关联失败"),
              { id: toastId }
            )
          if (!feedback) await reconcile("input_mutation_failed")
          return false
        } finally {
          if (!isCurrent() && toastId !== undefined) toast.dismiss(toastId)
        }
      })
    },
    [
      applyMutation,
      callBackend,
      canvasLoaded,
      canvasScopeKey,
      episodeId,
      projectId,
      reconcile,
      onUnlinked,
    ]
  )

  const updateReferenceUsage = useCallback(
    async (nodeId: string, sourceNodeId: string, enabled: boolean) => {
      const requestScope = canvasRequestScopeRef.current
      const node = readGraph().nodes.find((item) => item.id === nodeId)
      if (!node || requestScope.key !== canvasScopeKey) return
      const drafts = referenceUsageDraftsRef.current.get(nodeId) ??
        new Map<string, ReferenceUsageDraft>()
      const previous = inlineAssetDisplayRows(withReferenceDrafts(node.data, undefined, drafts))
        .find((row) => String(row.sourceNodeId ?? row.source_node_id ?? "") === sourceNodeId)
      if (!previous || (previous.enabled !== false) === enabled) return
      const token = Symbol("reference-usage")
      drafts.set(sourceNodeId, { enabled, token, saving: true, confirmed: drafts.get(sourceNodeId)?.confirmed })
      referenceUsageDraftsRef.current.set(nodeId, drafts)
      setReferenceDraftVersion((version) => version + 1)
      const isLatest = () => canvasRequestScopeRef.current === requestScope &&
        referenceUsageDraftsRef.current.get(nodeId)?.get(sourceNodeId)?.token === token
      try {
        const saved = await mutateCanvasInput("usage", nodeId, { sourceNodeId, enabled }, {
          success: enabled ? "已启用参考资产" : "已禁用参考资产",
          isLatest,
        })
        const latest = drafts.get(sourceNodeId)
        if (saved && latest && canvasRequestScopeRef.current === requestScope)
          latest.confirmed = saved.applied ? undefined : { enabled, revision: saved.revision }
      } finally {
        // On failure retain the last successful save, even if its replay is pending.
        if (isLatest()) {
          const latest = drafts.get(sourceNodeId)!
          if (latest.confirmed) { latest.enabled = latest.confirmed.enabled; latest.saving = false }
          else drafts.delete(sourceNodeId)
          if (!drafts.size) referenceUsageDraftsRef.current.delete(nodeId)
          setReferenceDraftVersion((version) => version + 1)
        }
      }
    },
    [canvasScopeKey, mutateCanvasInput, readGraph]
  )

  const updateFrameReference = useCallback(
    async (
      nodeId: string,
      sourceNodeId: string,
      options: FrameReferenceOptions
    ) => {
      const requestScope = canvasRequestScopeRef.current
      const node = readGraph().nodes.find((item) => item.id === nodeId)
      if (!node || requestScope.key !== canvasScopeKey) return
      const drafts =
        frameReferenceDraftsRef.current.get(nodeId) ??
        new Map<string, FrameReferenceDraft>()
      const previous = collectInlineAssetTags(
        inlineAssetDisplayRows(withReferenceDrafts(node.data, drafts)),
        {}
      ).tags.find(
        (tag) => tag.kind === "frame" && tag.sourceNodeId === sourceNodeId
      )
      if (!previous) return
      if (
        (previous.frameRole ?? "first_frame") === options.frameRole &&
        (previous.useNativeFrame !== false) === options.useNativeFrame
      )
        return
      const roleLabel = options.frameRole === "last_frame" ? "尾帧" : "首帧"
      const success =
        previous.frameRole !== options.frameRole
          ? `已设为${roleLabel}`
          : `已${options.useNativeFrame ? "开启" : "关闭"}原生${roleLabel}约束`
      const token = Symbol("frame-settings")
      drafts.set(sourceNodeId, { options, token, saving: true, confirmed: drafts.get(sourceNodeId)?.confirmed })
      frameReferenceDraftsRef.current.set(nodeId, drafts)
      setReferenceDraftVersion((version) => version + 1)
      const isLatest = () =>
        canvasRequestScopeRef.current === requestScope &&
        frameReferenceDraftsRef.current.get(nodeId)?.get(sourceNodeId)
          ?.token === token
      try {
        const saved = await mutateCanvasInput(
          "link",
          nodeId,
          { sourceNodeId, slot: "frame_reference", ...options },
          { success, isLatest }
        )
        const latest = drafts.get(sourceNodeId)
        if (saved && latest && canvasRequestScopeRef.current === requestScope)
          latest.confirmed = saved.applied ? undefined : { options, revision: saved.revision }
      } finally {
        // Older replies cannot remove a newer edit or its last confirmed fallback.
        if (isLatest()) {
          const latest = drafts.get(sourceNodeId)!
          if (latest.confirmed) { latest.options = latest.confirmed.options; latest.saving = false }
          else drafts.delete(sourceNodeId)
          if (!drafts.size) frameReferenceDraftsRef.current.delete(nodeId)
          setReferenceDraftVersion((version) => version + 1)
        }
      }
    },
    [canvasScopeKey, mutateCanvasInput, readGraph]
  )

  const handleRemoveInputLink = useCallback(
    async (nodeId: string, inputLinkId: string) => {
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const node = readGraph().nodes.find((item) => item.id === nodeId)
      const inputLink = node?.data.inputLinks?.find(
        (link) => link.id === inputLinkId
      )
      if (!inputLink) return
      if (isWorkflowItemLocked(inputLink)) {
        toast.info("该链接已锁定，不能取消")
        return
      }
      const sourceNodeId = String(inputLink.sourceNodeId ?? "").trim()
      const slot = String(inputLink.targetSlot ?? "").trim()
      if (!sourceNodeId || !slot) {
        toast.error("资产关联缺少来源或用途，请刷新画布")
        return
      }
      await mutateCanvasInput("unlink", nodeId, { sourceNodeId, slot })
    },
    [backendReady, mutateCanvasInput, readGraph]
  )

  const handleEdgesChange = useCallback(
    (changes: EdgeChange<StoryboardEdge>[]) => {
      const { nodes, edges } = readGraph()
      const removeChanges = changes.filter((change) => change.type === "remove")
      const removedEdges = removeChanges
        .map((change) => edges.find((edge) => edge.id === change.id))
        .filter((edge): edge is StoryboardEdge => Boolean(edge))
      const removedLockedSystemEdge = removedEdges.find((edge) =>
        isWorkflowLockedSystemEdge(edge, nodes)
      )
      if (removedLockedSystemEdge) {
        toast.info("锁定链接不能删除")
        return
      }
      const lockedRemovedSystemEdge = removedEdges.find(
        (edge) =>
          edge.data?.kind !== "material" &&
          (isWorkflowItemLocked(edge) || isWorkflowItemLocked(edge.data))
      )
      if (lockedRemovedSystemEdge) {
        toast.info("该系统链接已锁定，不能删除")
        return
      }
      const removedMaterialEdges = removeChanges
        .map((change) => edges.find((edge) => edge.id === change.id))
        .filter((edge): edge is StoryboardEdge =>
          Boolean(edge?.data?.kind === "material" && edge.data.inputLinkId)
        )
      if (removedEdges.length !== removedMaterialEdges.length) {
        toast.info("工作链主干链接由系统维护，不能单独删除")
        return
      }
      const lockedRemovedEdge = removedMaterialEdges.find((edge) => {
        const targetNode = nodes.find((node) => node.id === edge.target)
        const inputLinks =
          targetNode && Array.isArray(targetNode.data.inputLinks)
            ? targetNode.data.inputLinks
            : []
        const inputLink = inputLinks.find((link) =>
          inputLinkMatchesDirectId(
            recordValue(link),
            String(edge.data?.inputLinkId ?? "")
          )
        )
        return isWorkflowItemLocked(inputLink)
      })
      if (lockedRemovedEdge) {
        toast.info("该链接已锁定，不能取消")
        return
      }
      if (
        removedMaterialEdges.length > 0 &&
        removedMaterialEdges.length === removeChanges.length
      ) {
        void (async () => {
          const seen = new Set<string>()
          for (const edge of removedMaterialEdges) {
            const nextInputLinkId = String(edge.data?.inputLinkId ?? "").trim()
            if (!nextInputLinkId || seen.has(nextInputLinkId)) continue
            seen.add(nextInputLinkId)
            await handleRemoveInputLink(edge.target, nextInputLinkId)
          }
        })()
        return
      }
      if (!removeChanges.length) onPresentationEdgesChange(changes)
    },
    [handleRemoveInputLink, readGraph, onPresentationEdgesChange]
  )

  const onConnect = useCallback(
    (connection: Connection) => {
      const sourceNode = readGraph().nodes.find(
        (node) => node.id === connection.source
      )
      const targetNode = readGraph().nodes.find(
        (node) => node.id === connection.target
      )
      if (!sourceNode || !targetNode) return
      const sourceType = sourceNode.data.eyebrow
      const targetType = targetNode.data.eyebrow
      if (sourceNode.id === targetNode.id) {
        toast.error("不能把节点连接到自身")
        return
      }
      if (
        isWorkflowImageNodeType(sourceType) &&
        isWorkflowImageNodeType(targetType)
      ) {
        toast.error("资产只能连接任务卡")
        return
      }
      if (!isWorkflowAssetNodeType(sourceType)) {
        toast.error("工作链主干链接由系统生成和维护，不能手动创建")
        return
      }
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      if (
        !materialTargetHandleAllowedForConnection(
          targetNode,
          connection.targetHandle
        )
      ) {
        toast.error(materialTargetHandleConnectionError(targetNode))
        return
      }
      const slot = materialTargetSlotForConnection(
        sourceNode,
        targetNode,
        connection.targetHandle
      )
      if (!materialConnectionAllowed(sourceNode, targetNode, slot)) {
        toast.error(materialConnectionError(sourceNode, targetNode, slot))
        return
      }
      const existing = readGraph().edges.find(
        (edge) =>
          edge.data?.kind === "material" &&
          edge.source === sourceNode.id &&
          edge.target === targetNode.id &&
          edge.data.targetSlot === slot
      )
      if (
        existing &&
        (isWorkflowLockedSystemEdge(existing, readGraph().nodes) ||
          isWorkflowItemLocked(existing) ||
          isWorkflowItemLocked(existing.data))
      ) {
        toast.info("该链接已锁定，不能修改")
        return
      }
      void mutateCanvasInput("link", targetNode.id, {
        sourceNodeId: sourceNode.id,
        sourceType: materialSourceType(sourceNode),
        label: sourceNode.data.title,
        slot,
        sourceHandle: workflowMaterialSourceHandle(
          sourceNode,
          connection.sourceHandle
        ),
        targetHandle: materialTargetHandleForDisplay(
          targetNode,
          slot,
          connection.targetHandle
        ),
        action: "append",
      })
    },
    [backendReady, mutateCanvasInput]
  )

  const decorateNode = useCallback(
    (node: StoryboardNode) =>
      withReferenceDrafts(
        node.data,
        frameReferenceDraftsRef.current.get(node.id),
        referenceUsageDraftsRef.current.get(node.id)
      ),
    [referenceDraftVersion]
  )
  return {
    connect: onConnect,
    removeLink: handleRemoveInputLink,
    edgesChanged: handleEdgesChange,
    updateReferenceUsage,
    updateFrameReference,
    decorateNode,
  }
}
