import { useCallback, useEffect, useRef, useState } from "react"
import type { Dispatch, SetStateAction } from "react"
import { updateWorkflowNodeLayout, updateWorkflowNodesLayout, type BackendCaller } from "@/backend"
import { toast } from "sonner"
import { errMsg } from "@/shared/backend-result"
import type { StoryboardNode } from "./workflow-canvas-model"

/** Per-node persistence queues, creation-time drag deferral and rollback. */
export function useWorkflowNodeLayout({
  backendReady,
  callBackend,
  projectId,
  episodeId,
  setNodes,
  onVersionConfirmed,
}: {
  backendReady: boolean
  callBackend: BackendCaller
  projectId: string
  episodeId: string
  setNodes: Dispatch<SetStateAction<StoryboardNode[]>>
  onVersionConfirmed: (version: unknown) => void
}) {
  const nodeLayoutSaveQueuesRef = useRef<Map<string, Promise<void>>>(new Map())
  const [batchSaving, setBatchSaving] = useState(false)
  const nodeLayoutPendingPositionsRef = useRef<
    Map<string, { x: number; y: number }>
  >(new Map())
  const nodeLayoutConfirmedPositionsRef = useRef<
    Map<string, { x: number; y: number }>
  >(new Map())
  const nodeLayoutCreatingNodeIdsRef = useRef<Set<string>>(new Set())
  const nodeLayoutDeferredPositionsRef = useRef<
    Map<string, { position: { x: number; y: number }; reason: string }>
  >(new Map())
  const nodeLayoutScopeKey = `${projectId}\u0000${episodeId}`
  const nodeLayoutScopeRef = useRef({ key: nodeLayoutScopeKey })
  if (nodeLayoutScopeRef.current.key !== nodeLayoutScopeKey)
    nodeLayoutScopeRef.current = { key: nodeLayoutScopeKey }
  const persistNodePosition = useCallback(
    (nodeId: string, position: { x: number; y: number }, reason: string) => {
      if (!backendReady) return
      if (nodeLayoutCreatingNodeIdsRef.current.has(nodeId)) {
        nodeLayoutDeferredPositionsRef.current.set(nodeId, {
          position: { ...position },
          reason,
        })
        return
      }
      const requestScope = nodeLayoutScopeRef.current
      const previous =
        nodeLayoutSaveQueuesRef.current.get(nodeId) ?? Promise.resolve()
      const next = previous
        .catch(() => undefined)
        .then(async () => {
          if (nodeLayoutScopeRef.current !== requestScope) return
          const result = await updateWorkflowNodeLayout(
            callBackend,
            projectId,
            episodeId,
            {
              nodeId,
              position,
              reason,
            }
          )
          if (result.skippedLocked) {
            const savedPosition = result.node?.position
            if (
              savedPosition &&
              Number.isFinite(savedPosition.x) &&
              Number.isFinite(savedPosition.y) &&
              nodeLayoutScopeRef.current === requestScope
            ) {
              nodeLayoutConfirmedPositionsRef.current.set(nodeId, {
                x: savedPosition.x,
                y: savedPosition.y,
              })
              setNodes((current) =>
                current.map((item) =>
                  item.id === nodeId
                    ? {
                        ...item,
                        position: { x: savedPosition.x, y: savedPosition.y },
                      }
                    : item
                )
              )
            }
            if (nodeLayoutScopeRef.current === requestScope) {
              toast.info(result.message ?? "节点已锁定，未保存")
            }
            return
          }
          if (nodeLayoutScopeRef.current === requestScope) {
            nodeLayoutConfirmedPositionsRef.current.set(nodeId, { ...position })
            if (
              result.workflowVersion !== undefined &&
              result.workflowVersion !== null
            ) {
              onVersionConfirmed(result.workflowVersion)
            }
          }
        })
        .catch((error) => {
          if (nodeLayoutScopeRef.current !== requestScope) return
          const isLatestRequest =
            nodeLayoutSaveQueuesRef.current.get(nodeId) === next
          const hasNewerPosition =
            nodeLayoutPendingPositionsRef.current.has(nodeId)
          if (!isLatestRequest || hasNewerPosition) return
          const confirmedPosition =
            nodeLayoutConfirmedPositionsRef.current.get(nodeId)
          if (confirmedPosition) {
            setNodes((current) =>
              current.map((item) =>
                item.id === nodeId
                  ? { ...item, position: { ...confirmedPosition } }
                  : item
              )
            )
          }
          toast.error(errMsg(error, "保存节点位置失败"))
        })
      nodeLayoutSaveQueuesRef.current.set(nodeId, next)
      void next.finally(() => {
        if (nodeLayoutSaveQueuesRef.current.get(nodeId) === next) {
          nodeLayoutSaveQueuesRef.current.delete(nodeId)
        }
      })
    },
    [
      backendReady,
      callBackend,
      episodeId,
      projectId,
      setNodes,
      onVersionConfirmed,
    ]
  )

  const flushDeferredCreatedNodePosition = useCallback(
    (nodeId: string) => {
      const deferred = nodeLayoutDeferredPositionsRef.current.get(nodeId)
      if (!deferred) return
      nodeLayoutDeferredPositionsRef.current.delete(nodeId)
      persistNodePosition(nodeId, deferred.position, deferred.reason)
    },
    [persistNodePosition]
  )

  const handleNodeDrag = useCallback(
    (_event: globalThis.MouseEvent | TouchEvent, node: StoryboardNode, draggedNodes?: StoryboardNode[]) => {
      for (const item of draggedNodes?.length ? draggedNodes : [node]) {
        nodeLayoutPendingPositionsRef.current.set(item.id, { ...item.position })
      }
    },
    []
  )

  const handleNodeDragStart = useCallback(
    (_event: globalThis.MouseEvent | TouchEvent, node: StoryboardNode, draggedNodes?: StoryboardNode[]) => {
      for (const item of draggedNodes?.length ? draggedNodes : [node]) {
        // A previous save may still fail; the visible position is not confirmed yet.
        if (!nodeLayoutSaveQueuesRef.current.has(item.id)) {
          nodeLayoutConfirmedPositionsRef.current.set(item.id, { ...item.position })
        }
      }
    },
    []
  )

  const handleNodeDragStop = useCallback(
    (_event: globalThis.MouseEvent | TouchEvent, node: StoryboardNode, draggedNodes?: StoryboardNode[]) => {
      if (draggedNodes && draggedNodes.length > 1) {
        const requestScope = nodeLayoutScopeRef.current
        const positions = draggedNodes.map(item => ({ nodeId: item.id, position: { ...item.position } }))
        const previous = positions.map(({ nodeId }) => nodeLayoutSaveQueuesRef.current.get(nodeId) ?? Promise.resolve())
        const baseline = new Map(positions.map(({ nodeId }) => [nodeId, nodeLayoutConfirmedPositionsRef.current.get(nodeId)]))
        setBatchSaving(true)
        const next = Promise.all(previous.map(promise => promise.catch(() => undefined))).then(async () => {
          if (nodeLayoutScopeRef.current !== requestScope) return
          // Earlier writes may have succeeded or returned a locked card's saved position.
          positions.forEach(({ nodeId }) => baseline.set(nodeId, nodeLayoutConfirmedPositionsRef.current.get(nodeId)))
          if (!backendReady) throw new Error("后端尚未就绪")
          const result = await updateWorkflowNodesLayout(callBackend, projectId, episodeId, positions)
          if (nodeLayoutScopeRef.current !== requestScope) return
          positions.forEach(({ nodeId, position }) => nodeLayoutConfirmedPositionsRef.current.set(nodeId, position))
          if (result.workflowVersion !== undefined) onVersionConfirmed(result.workflowVersion)
        }).catch(error => {
          if (nodeLayoutScopeRef.current !== requestScope) return
          setNodes(current => current.map(item => baseline.get(item.id) ? { ...item, position: { ...baseline.get(item.id)! } } : item))
          toast.error(errMsg(error, "保存整组位置失败，已恢复原位置"))
        }).finally(() => {
          if (nodeLayoutScopeRef.current !== requestScope) return
          for (const { nodeId } of positions) {
            nodeLayoutPendingPositionsRef.current.delete(nodeId)
            if (nodeLayoutSaveQueuesRef.current.get(nodeId) === next) nodeLayoutSaveQueuesRef.current.delete(nodeId)
          }
          setBatchSaving(false)
        })
        positions.forEach(({ nodeId }) => nodeLayoutSaveQueuesRef.current.set(nodeId, next))
        return
      }
      nodeLayoutPendingPositionsRef.current.delete(node.id)
      persistNodePosition(
        node.id,
        { ...node.position },
        "node_position_changed"
      )
    },
    [backendReady, callBackend, episodeId, onVersionConfirmed, persistNodePosition, projectId, setNodes]
  )

  useEffect(() => {
    setBatchSaving(false)
    if (nodeLayoutScopeRef.current.key !== nodeLayoutScopeKey) {
      nodeLayoutScopeRef.current = { key: nodeLayoutScopeKey }
    }
    return () => {
      nodeLayoutScopeRef.current = { key: "" }
      nodeLayoutPendingPositionsRef.current.clear()
      nodeLayoutConfirmedPositionsRef.current.clear()
      nodeLayoutSaveQueuesRef.current.clear()
      nodeLayoutCreatingNodeIdsRef.current.clear()
      nodeLayoutDeferredPositionsRef.current.clear()
    }
  }, [episodeId, projectId])

  const beginCreation = useCallback((nodeId: string) => {
    nodeLayoutCreatingNodeIdsRef.current.add(nodeId)
  }, [])
  const completeCreation = useCallback(
    (nodeId: string) => {
      nodeLayoutCreatingNodeIdsRef.current.delete(nodeId)
      flushDeferredCreatedNodePosition(nodeId)
    },
    [flushDeferredCreatedNodePosition]
  )
  const cancelCreation = useCallback((nodeId: string) => {
    nodeLayoutCreatingNodeIdsRef.current.delete(nodeId)
    nodeLayoutDeferredPositionsRef.current.delete(nodeId)
  }, [])
  const pendingPosition = useCallback(
    (nodeId: string) =>
      nodeLayoutDeferredPositionsRef.current.get(nodeId)?.position ??
      nodeLayoutPendingPositionsRef.current.get(nodeId),
    []
  )
  return {
    batchSaving,
    waitForWrites: () => Promise.all([...nodeLayoutSaveQueuesRef.current.values()]).then(() => undefined),
    beginCreation,
    completeCreation,
    cancelCreation,
    pendingPosition,
    onDrag: handleNodeDrag,
    onDragStart: handleNodeDragStart,
    onDragStop: handleNodeDragStop,
  }
}
