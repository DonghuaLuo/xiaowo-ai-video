import type { EpisodeWorkflow, WorkflowRoute } from "@/backend"
import type { StoryboardEdge, StoryboardNode } from "./workflow-canvas-model"
import { normalizeWorkflowVersion } from "./workflow-canvas-model"
import type { WorkChainDraft } from "./work-chain-draft"
import { applyNodeChanges, type NodeChange } from "@xyflow/react"

type Update<T> = T | ((current: T) => T)
type CanvasTransaction = { txId?: unknown; tx_id?: unknown }
type DocumentEvent =
  | { type: "backfill"; payload?: unknown }
  | { type: "reference-reset" }

export type WorkflowCanvasDocumentState = {
  nodes: StoryboardNode[]
  edges: StoryboardEdge[]
  routes: WorkflowRoute[]
  selectedNodeId: string | null
  selectedWorkChainId: string
  loading: boolean
  loadedCanvasScopeKey: string | null
  snapshotLoading: boolean
  workflowVersion: number
  workflowState: EpisodeWorkflow["state"] | null
  workflowRootExtras: Partial<EpisodeWorkflow>
}

/** One canvas owns its graph, document revision, selection and transaction ledger. */
export function createWorkflowCanvasDocument(scopeKey: string) {
  let scope = { key: scopeKey }
  let state: WorkflowCanvasDocumentState = {
    nodes: [],
    edges: [],
    routes: [],
    selectedNodeId: null,
    selectedWorkChainId: "all",
    loading: true,
    loadedCanvasScopeKey: null,
    snapshotLoading: false,
    workflowVersion: 0,
    workflowState: null,
    workflowRootExtras: {},
  }
  const listeners = new Set<() => void>()
  const eventListeners = new Set<(event: DocumentEvent) => void>()
  const transactions = new Set<string>()
  const pendingCreations = new Map<string, WorkChainDraft>()
  // Keep pending edits above backend snapshots/events until their write settles.
  type NodeDataPatches = Map<string, Partial<StoryboardNode["data"]>>
  const nodeDataOverlays = new Map<string, NodeDataPatches | ((nodes: StoryboardNode[]) => NodeDataPatches)>()
  let baseNodes = state.nodes
  const overlayNodes = () => {
    if (!nodeDataOverlays.size) return baseNodes
    let nodes = baseNodes
    for (const overlay of nodeDataOverlays.values()) {
      const patches = typeof overlay === "function" ? overlay(nodes) : overlay
      nodes = nodes.map((node) => {
        const patch = patches.get(node.id)
        return patch ? { ...node, data: { ...node.data, ...patch } } : node
      })
    }
    return nodes
  }
  let batchDepth = 0
  let dirty = false
  const flush = () => {
    if (!dirty || batchDepth) return
    dirty = false
    listeners.forEach((listener) => listener())
  }
  const patch = (value: Partial<WorkflowCanvasDocumentState>) => {
    if (!scope.key) return
    if (value.nodes && value.nodes !== state.nodes) {
      baseNodes = value.nodes
      value = { ...value, nodes: overlayNodes() }
    }
    if (
      !scope.key ||
      !Object.entries(value).some(
        ([key, next]) =>
          state[key as keyof WorkflowCanvasDocumentState] !== next
      )
    )
      return
    state = { ...state, ...value }
    dirty = true
    flush()
  }
  const update = <K extends keyof WorkflowCanvasDocumentState>(
    key: K,
    value: Update<WorkflowCanvasDocumentState[K]>
  ) => {
    const next =
      typeof value === "function"
        ? (
            value as (
              current: WorkflowCanvasDocumentState[K]
            ) => WorkflowCanvasDocumentState[K]
          )(key === "nodes" ? baseNodes as WorkflowCanvasDocumentState[K] : state[key])
        : value
    // A pending overlay differs from the confirmed graph. Reapplying it after
    // an unchanged node update would publish a fresh snapshot on every render.
    if (key === "nodes" && next === baseNodes) return
    patch({ [key]: next })
  }
  const emit = (event: DocumentEvent) =>
    eventListeners.forEach((listener) => listener(event))
  const transactionId = (item: CanvasTransaction) =>
    String(item.txId ?? item.tx_id ?? "").trim()
  return {
    get scope() {
      return scope
    },
    read: () => state,
    readConfirmedNodes: () => baseNodes,
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    subscribeEvents(listener: (event: DocumentEvent) => void) {
      eventListeners.add(listener)
      return () => {
        eventListeners.delete(listener)
      }
    },
    activate(key = scopeKey) {
      if (scope.key === key) return
      scope = { key }
      pendingCreations.clear()
      transactions.clear()
      nodeDataOverlays.clear()
      if (state.nodes !== baseNodes || state.snapshotLoading) {
        state = { ...state, nodes: baseNodes, snapshotLoading: false }
        dirty = true
        flush()
      }
    },
    dispose(expectedScope = scope) {
      if (scope !== expectedScope) return
      scope = { key: "" }
      pendingCreations.clear()
      nodeDataOverlays.clear()
    },
    transaction<T>(operation: () => T): T {
      batchDepth++
      try {
        return operation()
      } finally {
        batchDepth--
        flush()
      }
    },
    patchGraph(
      value: Partial<
        Pick<WorkflowCanvasDocumentState, "nodes" | "edges" | "routes">
      >
    ) {
      patch(value)
    },
    updateNodes: (value: Update<StoryboardNode[]>) => update("nodes", value),
    stageNodeData(key: string, patches: NodeDataPatches | ((nodes: StoryboardNode[]) => NodeDataPatches)) {
      if (!scope.key) return
      nodeDataOverlays.set(key, patches)
      state = { ...state, nodes: overlayNodes() }
      dirty = true
      flush()
    },
    finishNodeData(key: string) {
      if (!nodeDataOverlays.delete(key)) return
      // Publish from the backend state, without copying an overlay into it.
      const nodes = overlayNodes()
      state = { ...state, nodes }
      dirty = true
      flush()
    },
    applyNodeChanges: (changes: NodeChange<StoryboardNode>[]) =>
      update("nodes", applyNodeChanges(changes, baseNodes)),
    updateEdges: (value: Update<StoryboardEdge[]>) => update("edges", value),
    updateRoutes: (value: Update<WorkflowRoute[]>) => update("routes", value),
    updateMetadata: (value: Update<Partial<EpisodeWorkflow>>) =>
      update("workflowRootExtras", value),
    updateProductionState: (value: Update<EpisodeWorkflow["state"] | null>) =>
      update("workflowState", value),
    selectNode: (value: Update<string | null>) =>
      update("selectedNodeId", value),
    selectWorkChain: (value: Update<string>) =>
      update("selectedWorkChainId", value),
    setLoading: (value: Update<boolean>) => update("loading", value),
    markLoaded: (key: string | null) => update("loadedCanvasScopeKey", key),
    // Snapshot ordering is independent of whether the displayed canvas can be edited.
    setSnapshotLoading: (value: boolean) => update("snapshotLoading", value),
    confirmRevision(
      value: unknown,
      options: { mode?: "trusted" | "mutation"; payload?: unknown } = {}
    ) {
      const next = normalizeWorkflowVersion(value),
        current = state.workflowVersion
      if (options.mode === "trusted" && next < current)
        emit({ type: "reference-reset" })
      if (options.mode !== "trusted") {
        if ((next <= 0 && current > 0) || (next > 0 && next < current))
          return false
        if (next > current + 1) {
          emit({ type: "backfill", payload: options.payload })
          return false
        }
      }
      patch({ workflowVersion: next })
      return true
    },
    invalidateRevision() {
      patch({
        workflowVersion: normalizeWorkflowVersion(state.workflowVersion) + 1,
      })
    },
    isStaleRevision(value: unknown) {
      const incoming = normalizeWorkflowVersion(value)
      return incoming > 0 && incoming < state.workflowVersion
    },
    requestBackfill(payload?: Record<string, unknown>) {
      emit({ type: "backfill", payload })
    },
    markTransactions(items: CanvasTransaction[]) {
      items
        .map(transactionId)
        .filter(Boolean)
        .forEach((id) => transactions.add(id))
      if (transactions.size > 600) {
        const keep = [...transactions].slice(-400)
        transactions.clear()
        keep.forEach((id) => transactions.add(id))
      }
    },
    hasTransaction(item: CanvasTransaction) {
      const id = transactionId(item)
      return Boolean(id && transactions.has(id))
    },
    clearTransactions() {
      transactions.clear()
    },
    stageCreation(id: string, draft: WorkChainDraft) {
      pendingCreations.set(id, draft)
    },
    pendingCreation: (id: string) => pendingCreations.get(id),
    finishCreation: (id: string) => pendingCreations.delete(id),
    pendingCreationDrafts: () => pendingCreations.values(),
    clearPendingCreations() {
      pendingCreations.clear()
    },
  }
}

export type WorkflowCanvasDocument = ReturnType<
  typeof createWorkflowCanvasDocument
>
