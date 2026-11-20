import { useCallback, useEffect, useRef, useState } from "react"
import type { MouseEvent as ReactMouseEvent } from "react"
import { toast } from "sonner"
import { deleteWorkflowNodes, type BackendCaller } from "@/backend"
import { errMsg } from "@/shared/backend-result"
import type { WorkflowCanvasDocument } from "./workflow-canvas-document"
import type { useWorkflowDocumentSync } from "./use-workflow-document-sync"
import { canvasSelectionDeleteState, isCanvasTextInput } from "./workflow-selection-model"

export function useWorkflowCanvasSelection({
  projectId, episodeId, backendReady, callBackend, canvasDocument, documentSync, waitForWrites,
  disabled, viewKey,
}: {
  projectId: string; episodeId: string; backendReady: boolean; callBackend: BackendCaller
  canvasDocument: WorkflowCanvasDocument
  documentSync: Pick<ReturnType<typeof useWorkflowDocumentSync>, "applyMutation" | "reconcile">
  waitForWrites: () => Promise<void>
  disabled: boolean; viewKey: string
}) {
  const surfaceRef = useRef<HTMLDivElement>(null)
  const [active, setActive] = useState(false)
  const [ctrlPressed, setCtrlPressed] = useState(false)
  const [selecting, setSelecting] = useState(false)
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const [deleteIds, setDeleteIds] = useState<string[] | null>(null)
  const [deleting, setDeleting] = useState(false)
  const ctrlRef = useRef(false)
  const deletingRef = useRef(false)
  const gestureRef = useRef<{ target: Element; pointerId: number } | null>(null)
  const session = useRef({ scope: canvasDocument.scope, viewKey })
  if (session.current.scope !== canvasDocument.scope || session.current.viewKey !== viewKey) {
    session.current = { scope: canvasDocument.scope, viewKey }
  }
  const selected = active ? canvasDocument.read().nodes.filter(node => node.selected && !node.hidden) : []
  const latest = useRef({ active, disabled, menu, deleteIds, selected })
  latest.current = { active, disabled, menu, deleteIds, selected }

  const cancelNativeSelection = useCallback(() => {
    const gesture = gestureRef.current
    gestureRef.current = null
    if (gesture?.target.isConnected) {
      // React Flow owns the pointer capture and auto-pan loop. Resetting its
      // visible selection state alone does not stop that loop.
      gesture.target.dispatchEvent(new PointerEvent("pointercancel", {
        bubbles: true, pointerId: gesture.pointerId,
      }))
    }
  }, [])

  const clear = useCallback(() => {
    cancelNativeSelection()
    setSelecting(false)
    setActive(false)
    setMenu(null)
    canvasDocument.transaction(() => {
      canvasDocument.selectNode(null)
      canvasDocument.updateNodes(nodes => nodes.map(node => node.selected ? { ...node, selected: false } : node))
      canvasDocument.updateEdges(edges => edges.map(edge => edge.selected ? { ...edge, selected: false } : edge))
    })
  }, [canvasDocument, cancelNativeSelection])

  useEffect(() => {
    ctrlRef.current = false
    deletingRef.current = false
    setCtrlPressed(false)
    setSelecting(false)
    setDeleting(false)
    setDeleteIds(null)
    clear()
  }, [projectId, episodeId, viewKey, clear])

  useEffect(() => {
    const release = () => { ctrlRef.current = false; setCtrlPressed(false) }
    const keyDown = (event: KeyboardEvent) => {
      const state = latest.current
      if (event.isComposing || isCanvasTextInput(event.target) || state.disabled || state.deleteIds || deletingRef.current) return
      if (event.code === "ControlLeft" && !event.repeat) {
        // A portal dialog or another editor must keep its own keyboard behavior.
        if (document.querySelector('[role="dialog"], [role="alertdialog"]') || canvasDocument.read().nodes.some(node => node.dragging)) return
        ctrlRef.current = true
        setCtrlPressed(true)
      }
      if (event.key === "Escape" && state.active) {
        if (state.menu) setMenu(null)
        else {
          release()
          setSelecting(false)
          clear()
        }
      }
    }
    const keyUp = (event: KeyboardEvent) => { if (event.code === "ControlLeft") release() }
    const focus = (event: FocusEvent) => { if (isCanvasTextInput(event.target)) release() }
    const pointerDown = (event: PointerEvent) => {
      const state = latest.current
      if (!(event.target instanceof Element)) return
      if (event.target.closest("[data-canvas-selection-ui]")) return
      setMenu(null)
      if (!state.active || ctrlRef.current || state.deleteIds || deletingRef.current) return
      const card = event.target.closest(".react-flow__node")
      if (card && surfaceRef.current?.contains(card) && state.selected.some(node => node.id === card.getAttribute("data-id"))) return
      clear()
    }
    const cancelPointer = () => { cancelNativeSelection(); release(); setSelecting(false) }
    const pointerCancelled = () => { gestureRef.current = null; release(); setSelecting(false) }
    const visibility = () => { if (document.hidden) cancelPointer() }
    window.addEventListener("keydown", keyDown, true)
    window.addEventListener("keyup", keyUp, true)
    window.addEventListener("blur", cancelPointer)
    window.addEventListener("pointercancel", pointerCancelled)
    document.addEventListener("visibilitychange", visibility)
    document.addEventListener("focusin", focus)
    document.addEventListener("pointerdown", pointerDown, true)
    return () => {
      window.removeEventListener("keydown", keyDown, true)
      window.removeEventListener("keyup", keyUp, true)
      window.removeEventListener("blur", cancelPointer)
      window.removeEventListener("pointercancel", pointerCancelled)
      document.removeEventListener("visibilitychange", visibility)
      document.removeEventListener("focusin", focus)
      document.removeEventListener("pointerdown", pointerDown, true)
      cancelNativeSelection()
    }
  }, [canvasDocument, clear, cancelNativeSelection])

  useEffect(() => {
    if (!disabled) return
    cancelNativeSelection()
    ctrlRef.current = false
    setCtrlPressed(false)
    setSelecting(false)
  }, [disabled, cancelNativeSelection])

  const openMenu = (event: ReactMouseEvent, nodeId?: string) => {
    if (!active || !selected.length || (nodeId && !selected.some(node => node.id === nodeId))) return false
    event.preventDefault()
    event.stopPropagation()
    setMenu({ x: Math.max(8, Math.min(event.clientX, window.innerWidth - 290)), y: Math.max(8, Math.min(event.clientY, window.innerHeight - 155)) })
    return true
  }

  const confirmDelete = async () => {
    if (!deleteIds?.length || deletingRef.current) return
    const scope = canvasDocument.scope
    const requestSession = session.current
    const current = () => canvasDocument.scope === scope && session.current === requestSession
    deletingRef.current = true
    setDeleting(true)
    try {
      if (!backendReady) throw new Error("后端尚未就绪")
      await waitForWrites()
      if (!current()) return
      const graph = canvasDocument.read()
      const requested = graph.nodes.filter(node => deleteIds.includes(node.id))
      if (requested.length !== deleteIds.length) throw new Error("选中的卡片已变化，请重新选择")
      const check = canvasSelectionDeleteState(requested, graph.nodes, graph.edges)
      if (check.reason) throw new Error(check.reason)
      const result = await deleteWorkflowNodes(callBackend, projectId, episodeId, deleteIds, graph.workflowVersion)
      if (!current()) return
      documentSync.applyMutation({ ...result, action: "workflow_item_deleted", projectId, episodeId })
      setDeleteIds(null)
      clear()
      toast.success(`已删除 ${result.deletedNodeIds?.length ?? deleteIds.length} 张卡片`)
    } catch (error) {
      if (!current()) return
      toast.error(errMsg(error, "批量删除失败"))
      await documentSync.reconcile("selection_delete_failed").catch(() => undefined)
    } finally {
      if (current()) { deletingRef.current = false; setDeleting(false) }
    }
  }

  return {
    surfaceRef, active, ctrlPressed, selecting, selected, menu, deleting, deleteIds,
    clear, openMenu, confirmDelete,
    startSelection: (event?: ReactMouseEvent) => {
      const pointerId = (event?.nativeEvent as PointerEvent | undefined)?.pointerId
      if (event && typeof pointerId === "number") gestureRef.current = { target: event.currentTarget, pointerId }
      setActive(true); setSelecting(true); setMenu(null); canvasDocument.selectNode(null)
    },
    endSelection: () => { gestureRef.current = null; setSelecting(false) },
    requestDelete: () => { setDeleteIds(selected.map(node => node.id)); setMenu(null) },
    cancelDelete: () => { if (!deletingRef.current) setDeleteIds(null) },
    interceptClick: (nodeId: string) => {
      if (ctrlRef.current) { setActive(true); canvasDocument.selectNode(null); return true }
      return active && selected.some(node => node.id === nodeId)
    },
  }
}
