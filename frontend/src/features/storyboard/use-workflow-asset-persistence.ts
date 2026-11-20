import { useCallback, useEffect, useRef } from "react"
import {
  addWorkflowAssetNodes,
  importWorkflowMedia,
  pasteWorkflowAssetNode,
  type BackendCaller,
  type WorkflowNode,
} from "@/backend"
import { toast } from "sonner"
import { errMsg } from "@/shared/backend-result"
import { toBackendNode, type StoryboardNode } from "./workflow-canvas-model"
import type { useWorkflowNodeLayout } from "./use-workflow-node-layout"

export type WorkflowAssetWriteback =
  | {
      type: "upsert"
      nodes: StoryboardNode[]
      selectedNodeId?: string | null
      revision?: unknown
    }
  | { type: "rollback"; nodeIds: string[] }

type SaveOptions = {
  successMessage: string
  errorMessage: string
  selectOnConfirmation?: boolean
}

/** One owner for optimistic insertion, backend confirmation, layout preservation and rollback. */
export function useWorkflowAssetPersistence({
  projectId,
  episodeId,
  callBackend,
  layout,
  adaptNodes,
  onWriteback,
}: {
  projectId: string
  episodeId: string
  callBackend: BackendCaller
  layout: ReturnType<typeof useWorkflowNodeLayout>
  adaptNodes: (nodes: WorkflowNode[]) => StoryboardNode[]
  onWriteback: (event: WorkflowAssetWriteback) => void
}) {
  const scopeKey = `${projectId}\u0000${episodeId}`
  const scopeRef = useRef({ key: scopeKey })
  if (scopeRef.current.key !== scopeKey) scopeRef.current = { key: scopeKey }
  useEffect(() => {
    if (scopeRef.current.key !== scopeKey) scopeRef.current = { key: scopeKey }
    return () => {
      scopeRef.current = { key: "" }
    }
  }, [scopeKey])

  const save = useCallback(
    async (
      pendingNodes: StoryboardNode[],
      request: () => Promise<{
        nodes: WorkflowNode[]
        workflowVersion?: unknown
      }>,
      options: SaveOptions & { fallbackSelection?: string }
    ) => {
      const scope = scopeRef.current
      const current = () => scopeRef.current === scope
      const pendingIds = pendingNodes.map((node) => node.id)
      pendingIds.forEach(layout.beginCreation)
      if (pendingNodes.length) {
        onWriteback({
          type: "upsert",
          nodes: pendingNodes,
          selectedNodeId: pendingIds.at(-1),
        })
      }
      try {
        const result = await request()
        if (!current()) return false
        const nodes = adaptNodes(
          result.nodes.map((node) => {
            const latest = layout.pendingPosition(node.id)
            return latest ? { ...node, position: { ...latest } } : node
          })
        )
        onWriteback({
          type: "upsert",
          nodes,
          revision: result.workflowVersion,
          ...(options.selectOnConfirmation
            ? {
                selectedNodeId:
                  nodes[0]?.id ?? options.fallbackSelection ?? null,
              }
            : {}),
        })
        pendingIds.forEach(layout.completeCreation)
        toast.success(options.successMessage)
        return true
      } catch (error) {
        if (!current()) return false
        pendingIds.forEach(layout.cancelCreation)
        if (pendingIds.length)
          onWriteback({ type: "rollback", nodeIds: pendingIds })
        toast.error(errMsg(error, options.errorMessage))
        return false
      }
    },
    [
      adaptNodes,
      layout.beginCreation,
      layout.cancelCreation,
      layout.completeCreation,
      layout.pendingPosition,
      onWriteback,
    ]
  )

  const addNodes = useCallback(
    (nodes: StoryboardNode[], reason: string, options: SaveOptions) =>
      save(
        nodes,
        () =>
          addWorkflowAssetNodes(callBackend, projectId, episodeId, {
            nodes: nodes.map(toBackendNode),
            reason,
          }),
        options
      ),
    [callBackend, episodeId, projectId, save]
  )

  const importMedia = useCallback(
    (
      payload: Parameters<typeof importWorkflowMedia>[3],
      options: SaveOptions & {
        pendingNode?: StoryboardNode
        onImported?: () => void
      }
    ) =>
      save(
        options.pendingNode ? [options.pendingNode] : [],
        async () => {
          const result = await importWorkflowMedia(
            callBackend,
            projectId,
            episodeId,
            payload
          )
          // Cache invalidation belongs to the completed backend write even if the UI switched canvases.
          options.onImported?.()
          return {
            nodes: result.mediaNode ? [result.mediaNode as WorkflowNode] : [],
            workflowVersion: result.workflowVersion,
          }
        },
        {
          ...options,
          selectOnConfirmation: true,
          fallbackSelection: payload.mediaNodeId,
        }
      ),
    [callBackend, episodeId, projectId, save]
  )

  const pasteNode = useCallback(
    (payload: Parameters<typeof pasteWorkflowAssetNode>[3]) =>
      save(
        [],
        () =>
          pasteWorkflowAssetNode(callBackend, projectId, episodeId, payload),
        { successMessage: "资产已粘贴", errorMessage: "粘贴资产失败" }
      ),
    [callBackend, episodeId, projectId, save]
  )

  return { addNodes, importMedia, pasteNode }
}

export type WorkflowAssetPersistence = ReturnType<
  typeof useWorkflowAssetPersistence
>
