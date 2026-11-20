import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import {
  deleteNodeEditHistory,
  listNodeEditHistory,
  restoreNodeEditHistory,
  type BackendCaller,
  type NodeEditHistoryItem,
  type NodeEditHistoryRestoreResult,
} from "@/backend"
import { errMsg } from "@/shared/backend-result"
import {
  canvasNodeEditHistoryProjectionRows,
  mergeNodeEditHistoryItems,
  nodeEditHistoryItemsFromPayload,
  nodeEditHistorySortValue,
} from "./workflow-edit-history-model"

export type WorkflowEditHistoryRestoredEvent = {
  nodeId: string
  result: NodeEditHistoryRestoreResult
}

type HistoryState = {
  nodeId: string
  items: NodeEditHistoryItem[]
  loading: boolean
  selectedId: string
  activeId: string | null
  restoringId: string
  deleteTarget: NodeEditHistoryItem | null
  deletingId: string
}

const emptyHistory = (): HistoryState => ({
  nodeId: "",
  items: [],
  loading: false,
  selectedId: "",
  activeId: null,
  restoringId: "",
  deleteTarget: null,
  deletingId: "",
})

export function useWorkflowEditHistory({
  callBackend,
  backendReady,
  projectId,
  episodeId,
  onRestored,
}: {
  callBackend: BackendCaller
  backendReady: boolean
  projectId: string
  episodeId: string
  onRestored: (event: WorkflowEditHistoryRestoredEvent) => void
}) {
  const [state, setState] = useState<HistoryState>(emptyHistory)
  const stateRef = useRef(state)
  const sessionRef = useRef(0)
  const revisionRef = useRef(0)
  const receivedProjectionRef = useRef(false)
  const deletedIdsRef = useRef(new Set<string>())
  const scope = JSON.stringify([projectId, episodeId])
  const scopeRef = useRef(scope)
  const scopeGenerationRef = useRef(0)
  if (scopeRef.current !== scope) scopeGenerationRef.current += 1
  scopeRef.current = scope
  const mountedRef = useRef(false)
  const restoreRequestsRef = useRef(new Map<string, number>())
  const restoredRef = useRef(onRestored)
  restoredRef.current = onRestored

  // Keep the event consumer and asynchronous requests on the same current state.
  const update = useCallback(
    (change: (current: HistoryState) => HistoryState) => {
      const next = change(stateRef.current)
      stateRef.current = next
      setState(next)
    },
    []
  )

  const close = useCallback(() => {
    sessionRef.current += 1
    revisionRef.current = 0
    receivedProjectionRef.current = false
    deletedIdsRef.current.clear()
    update(emptyHistory)
  }, [update])

  useEffect(() => {
    mountedRef.current = true
    close()
    return () => {
      mountedRef.current = false
      sessionRef.current += 1
    }
  }, [scope, close])

  const open = useCallback(
    async (nodeId: string) => {
      if (!nodeId || scopeRef.current !== scope) return
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const session = ++sessionRef.current
      revisionRef.current = 0
      receivedProjectionRef.current = false
      deletedIdsRef.current.clear()
      update(() => ({ ...emptyHistory(), nodeId, loading: true }))
      const isCurrent = () =>
        scopeRef.current === scope && sessionRef.current === session
      try {
        const result = await listNodeEditHistory(
          callBackend,
          projectId,
          episodeId,
          nodeId
        )
        if (!isCurrent()) return
        // A projection received while loading is newer than this list request.
        if (revisionRef.current === 0) {
          const items = result.items ?? []
          update((current) => ({
            ...current,
            items,
            selectedId: items[0]?.id ?? "",
            activeId: result.activeId ?? items[0]?.id ?? "",
          }))
        } else if (!receivedProjectionRef.current) {
          // Direct mutation events contain only changed items. Keep the older
          // list entries without overwriting the newer event or its selection.
          update((current) => ({
            ...current,
            items: mergeNodeEditHistoryItems(
              (result.items ?? []).filter(
                (item) => !deletedIdsRef.current.has(item.id)
              ),
              current.items
            ),
          }))
        }
      } catch (error) {
        if (isCurrent()) toast.error(errMsg(error, "读取修改记录失败"))
      } finally {
        if (isCurrent()) update((current) => ({ ...current, loading: false }))
      }
    },
    [backendReady, callBackend, episodeId, projectId, scope, update]
  )

  const select = useCallback(
    (id: string) => {
      update((current) =>
        current.items.some((item) => item.id === id)
          ? { ...current, selectedId: id }
          : current
      )
    },
    [update]
  )

  const mergeItems = useCallback(
    (items: NodeEditHistoryItem[]) => {
      if (scopeRef.current !== scope) return false
      const nodeId = stateRef.current.nodeId
      if (!nodeId) return false
      const incoming = items
        .filter((item) => String(item.nodeId ?? "").trim() === nodeId)
        .sort(
          (a, b) => nodeEditHistorySortValue(b) - nodeEditHistorySortValue(a)
        )
      if (!incoming.length) return false
      revisionRef.current += 1
      update((current) => ({
        ...current,
        items: mergeNodeEditHistoryItems(current.items, incoming),
        selectedId: incoming[0].id,
        activeId: incoming[0].id,
      }))
      return true
    },
    [scope, update]
  )

  const consumeMutation = useCallback(
    (payload: unknown) => {
      if (scopeRef.current !== scope || !stateRef.current.nodeId) return false
      const patch = canvasNodeEditHistoryProjectionRows(payload).find(
        (row) => row.nodeId === stateRef.current.nodeId
      )
      if (patch) {
        revisionRef.current += 1
        receivedProjectionRef.current = true
        update((current) => ({
          ...current,
          items: patch.items,
          selectedId: patch.items.some((item) => item.id === current.selectedId)
            ? current.selectedId
            : (patch.items[0]?.id ?? ""),
          activeId: current.activeId === "" || patch.items.some((item) => item.id === current.activeId)
            ? current.activeId
            : (patch.items[0]?.id ?? ""),
          deleteTarget:
            current.deleteTarget &&
            patch.items.some((item) => item.id === current.deleteTarget?.id)
              ? current.deleteTarget
              : null,
        }))
      }
      return (
        mergeItems(nodeEditHistoryItemsFromPayload(payload)) || Boolean(patch)
      )
    },
    [mergeItems, scope, update]
  )

  const restore = useCallback(
    async (item?: NodeEditHistoryItem) => {
      const { nodeId, restoringId, deletingId, selectedId } = stateRef.current
      if (
        !item?.id ||
        item.nodeId !== nodeId ||
        !nodeId ||
        restoringId ||
        deletingId ||
        scopeRef.current !== scope
      )
        return
      if (!backendReady) {
        toast.error("后端尚未就绪")
        return
      }
      const session = sessionRef.current
      const scopeGeneration = scopeGenerationRef.current
      const request = (restoreRequestsRef.current.get(nodeId) ?? 0) + 1
      restoreRequestsRef.current.set(nodeId, request)
      const isCurrent = () =>
        scopeRef.current === scope && sessionRef.current === session
      update((current) => ({ ...current, restoringId: item.id }))
      try {
        const result = await restoreNodeEditHistory(
          callBackend,
          projectId,
          episodeId,
          { nodeId, versionId: item.id }
        )
        // The backend may finish after this dialog closes or opens another
        // node. Apply the successful node update to the same live canvas,
        // while keeping a newer dialog's history state untouched.
        if (
          !mountedRef.current ||
          scopeRef.current !== scope ||
          scopeGenerationRef.current !== scopeGeneration ||
          restoreRequestsRef.current.get(nodeId) !== request
        )
          return
        restoredRef.current({ nodeId, result })
        if (!isCurrent()) return
        update((current) => ({
          ...current,
          selectedId:
            current.selectedId === selectedId ? item.id : current.selectedId,
          activeId: item.id,
        }))
        toast.success("已切换到所选版本")
      } catch (error) {
        if (isCurrent()) toast.error(errMsg(error, "切换版本失败"))
      } finally {
        if (isCurrent()) update((current) => ({ ...current, restoringId: "" }))
      }
    },
    [backendReady, callBackend, episodeId, projectId, scope, update]
  )

  const requestDelete = useCallback(
    (item: NodeEditHistoryItem) => {
      update((current) =>
        item.nodeId === current.nodeId &&
        item.id !== (current.activeId ?? current.items[0]?.id)
          ? { ...current, deleteTarget: item }
          : current
      )
    },
    [update]
  )

  const cancelDelete = useCallback(() => {
    update((current) => ({ ...current, deleteTarget: null }))
  }, [update])

  const deleteSelected = useCallback(async () => {
    const {
      deleteTarget: item,
      nodeId,
      restoringId,
      deletingId,
    } = stateRef.current
    if (
      !item?.id ||
      !nodeId ||
      restoringId ||
      deletingId ||
      scopeRef.current !== scope
    )
      return
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    const session = sessionRef.current
    const isCurrent = () =>
      scopeRef.current === scope && sessionRef.current === session
    update((current) => ({ ...current, deletingId: item.id }))
    try {
      await deleteNodeEditHistory(callBackend, projectId, episodeId, {
        nodeId,
        versionId: item.id,
      })
      if (!isCurrent()) return
      revisionRef.current += 1
      deletedIdsRef.current.add(item.id)
      update((current) => {
        const items = current.items.filter((row) => row.id !== item.id)
        return {
          ...current,
          items,
          deleteTarget: null,
          selectedId:
            current.selectedId === item.id
              ? (items[0]?.id ?? "")
              : current.selectedId,
          activeId:
            current.activeId === item.id
              ? (items[0]?.id ?? "")
              : current.activeId,
        }
      })
      toast.success("修改记录已删除")
    } catch (error) {
      if (isCurrent()) toast.error(errMsg(error, "删除修改记录失败"))
    } finally {
      if (isCurrent()) update((current) => ({ ...current, deletingId: "" }))
    }
  }, [backendReady, callBackend, episodeId, projectId, scope, update])

  const selectedItem =
    state.items.find((item) => item.id === state.selectedId) ?? state.items[0]
  const currentId = state.activeId ?? state.items[0]?.id ?? ""
  return {
    ...state,
    selectedItem,
    currentId,
    selectedIsCurrent:
      Boolean(selectedItem?.id) && selectedItem.id === currentId,
    open,
    close,
    select,
    restore,
    requestDelete,
    cancelDelete,
    deleteSelected,
    consumeMutation,
    mergeItems,
  }
}

export type WorkflowEditHistoryController = ReturnType<
  typeof useWorkflowEditHistory
>
