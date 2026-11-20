import type { WorkflowCanvasDocument } from "./workflow-canvas-document"
import { useCallback, useEffect, useRef, useState } from "react"

import {
  getCanvasRecords,
  getEpisodeSourceText,
  type BackendCaller,
  type EpisodeSourceText,
  type WorkflowNode,
  type WorkflowRoute,
} from "@/backend"
import { toast } from "sonner"
import { errMsg } from "@/shared/backend-result"
import {
  normalizeWorkflowVersion,
  toStoryboardNodesFromBackend,
  upsertStoryboardNodesLocally,
  type StoryboardNode,
  type WorkflowNodeActions,
} from "./workflow-canvas-model"
import { withBackendReadTimeout } from "./workflow-task-status"

/** Owns detailed card/source reads, deduplication, loaded state and invalidation. */
export function useWorkflowCanvasDetails({
  backendReady,
  callBackend,
  projectId,
  episodeId,
  document,
  workflowNodeActions,
  routes,
}: {
  backendReady: boolean
  callBackend: BackendCaller
  projectId: string
  episodeId: string
  document: WorkflowCanvasDocument
  workflowNodeActions: WorkflowNodeActions
  routes: WorkflowRoute[]
}) {
  const [hydratingWorkflowCardIds, setHydratingWorkflowCardIds] = useState<
    Set<string>
  >(() => new Set())
  const hydratedWorkflowCardIdsRef = useRef<Set<string>>(new Set())
  const hydratingWorkflowCardPromisesRef = useRef<
    Map<string, Promise<WorkflowNode | null>>
  >(new Map())
  const workflowCardHydrationGenerationRef = useRef(0)
  const workflowCardHydrationScopeKey = `${projectId}\u0000${episodeId}`
  const workflowCardHydrationScopeRef = useRef(workflowCardHydrationScopeKey)
  workflowCardHydrationScopeRef.current = workflowCardHydrationScopeKey
  const episodeSourceTextScopeKey = `${projectId}\u0000${episodeId}`
  const episodeSourceTextCacheRef = useRef<
    Map<string, EpisodeSourceText | null>
  >(new Map())
  const episodeSourceTextInFlightRef = useRef<
    Map<string, Promise<EpisodeSourceText | null>>
  >(new Map())
  const resetWorkflowCardHydration = useCallback(() => {
    workflowCardHydrationGenerationRef.current += 1
    hydratedWorkflowCardIdsRef.current = new Set()
    hydratingWorkflowCardPromisesRef.current = new Map()
    setHydratingWorkflowCardIds(new Set())
  }, [])
  const cacheEpisodeSourceText = useCallback(
    (detail: EpisodeSourceText | null) => {
      const targetEpisodeId = String(detail?.episodeId || episodeId)
      const key = `${projectId}\u0000${targetEpisodeId}`
      episodeSourceTextCacheRef.current.set(key, detail)
      episodeSourceTextInFlightRef.current.delete(key)
    },
    [episodeId, projectId]
  )
  const invalidateEpisodeSourceTextCache = useCallback(() => {
    episodeSourceTextCacheRef.current.delete(episodeSourceTextScopeKey)
    episodeSourceTextInFlightRef.current.delete(episodeSourceTextScopeKey)
  }, [episodeSourceTextScopeKey])
  const requestScopeRef = useRef({ key: workflowCardHydrationScopeKey })
  if (requestScopeRef.current.key !== workflowCardHydrationScopeKey) {
    requestScopeRef.current = { key: workflowCardHydrationScopeKey }
  }
  useEffect(() => {
    if (requestScopeRef.current.key !== workflowCardHydrationScopeKey) {
      requestScopeRef.current = { key: workflowCardHydrationScopeKey }
    }
    resetWorkflowCardHydration()
    return () => {
      requestScopeRef.current = { key: "" }
      hydratingWorkflowCardPromisesRef.current.clear()
    }
  }, [workflowCardHydrationScopeKey, resetWorkflowCardHydration])
  useEffect(
    () => () => {
      episodeSourceTextInFlightRef.current.clear()
    },
    []
  )
  const getCachedEpisodeSourceText = useCallback(async () => {
    if (!backendReady) return null
    if (episodeSourceTextCacheRef.current.has(episodeSourceTextScopeKey)) {
      return (
        episodeSourceTextCacheRef.current.get(episodeSourceTextScopeKey) ?? null
      )
    }
    const activeRequest = episodeSourceTextInFlightRef.current.get(
      episodeSourceTextScopeKey
    )
    if (activeRequest) return activeRequest
    let requestPromise: Promise<EpisodeSourceText | null> | null = null
    requestPromise = (async () => {
      try {
        const detail = await withBackendReadTimeout(
          getEpisodeSourceText(callBackend, projectId, episodeId),
          "加载分集原文超时"
        )
        if (
          episodeSourceTextInFlightRef.current.get(
            episodeSourceTextScopeKey
          ) === requestPromise
        ) {
          cacheEpisodeSourceText(detail)
        }
        return detail
      } catch {
        return null
      } finally {
        if (
          episodeSourceTextInFlightRef.current.get(
            episodeSourceTextScopeKey
          ) === requestPromise
        ) {
          episodeSourceTextInFlightRef.current.delete(episodeSourceTextScopeKey)
        }
      }
    })()
    episodeSourceTextInFlightRef.current.set(
      episodeSourceTextScopeKey,
      requestPromise
    )
    return requestPromise
  }, [
    backendReady,
    cacheEpisodeSourceText,
    callBackend,
    episodeId,
    episodeSourceTextScopeKey,
    projectId,
  ])

  const applyEpisodeSourceTextToCurrentNodes = useCallback(
    (
      sourceTextDetail: EpisodeSourceText | null | undefined,
      requestCanvasScopeKey: string,
      requestWorkflowVersion: unknown
    ) => {
      if (!sourceTextDetail) return
      if (workflowCardHydrationScopeRef.current !== requestCanvasScopeKey)
        return
      const expectedVersion = normalizeWorkflowVersion(requestWorkflowVersion)
      if (
        expectedVersion > 0 &&
        document.read().workflowVersion !== expectedVersion
      ) {
        return
      }
      document.updateNodes((current) => {
        let changed = false
        const next = current.map((node) => {
          const data = node.data
          if (data.eyebrow !== "source.text" || data.sourceMode === "independent") return node
          const nextData = {
            ...data,
            episodeId: sourceTextDetail.episodeId,
            title: sourceTextDetail.title || data.title,
            sourceText: sourceTextDetail.text,
            summary: "",
          }
          if (
            data.episodeId === nextData.episodeId &&
            data.title === nextData.title &&
            data.sourceText === nextData.sourceText &&
            data.summary === nextData.summary
          ) {
            return node
          }
          changed = true
          return { ...node, data: nextData }
        })
        return changed ? next : current
      })
    },
    [document.updateNodes]
  )

  const hydrateWorkflowCard = useCallback(
    async (nodeId: string, options: { force?: boolean } = {}) => {
      const targetNodeId = String(nodeId || "").trim()
      if (!backendReady || !targetNodeId) return null
      if (
        !options.force &&
        hydratedWorkflowCardIdsRef.current.has(targetNodeId)
      ) {
        return null
      }
      const activePromise =
        hydratingWorkflowCardPromisesRef.current.get(targetNodeId)
      if (activePromise) return activePromise
      const requestScope = requestScopeRef.current
      const requestGeneration = workflowCardHydrationGenerationRef.current
      const requestIsCurrent = () =>
        requestScopeRef.current === requestScope &&
        workflowCardHydrationGenerationRef.current === requestGeneration &&
        document.read().nodes.some((node) => node.id === targetNodeId)
      if (!requestIsCurrent()) return null
      let requestPromise: Promise<WorkflowNode | null> | null = null
      setHydratingWorkflowCardIds((current) => {
        if (current.has(targetNodeId)) return current
        const next = new Set(current)
        next.add(targetNodeId)
        return next
      })
      const loadPromise = (async () => {
        try {
          for (let attempt = 0; attempt < 3; attempt++) {
            const requestedData = document.readConfirmedNodes().find(
              (node) => node.id === targetNodeId
            )?.data
            const result = await withBackendReadTimeout(
              getCanvasRecords(callBackend, projectId, episodeId, {
                detail: "full",
                ids: { nodeIds: [targetNodeId] },
              }),
              "加载工作流卡片详情超时"
            )
            if (!requestIsCurrent()) return null
            // A partial mutation can update the card before the canvas revision catches up.
            const canApplyDetail = (current: StoryboardNode[]) =>
              requestIsCurrent() &&
              result.currentRevision >= document.read().workflowVersion &&
              current.find((node) => node.id === targetNodeId)?.data ===
                requestedData
            if (!canApplyDetail(document.readConfirmedNodes())) continue
            const backendNode = result.records.nodes?.find(
              (node) => node.id === targetNodeId
            )
            if (!backendNode) return null
            const [storyboardNode] = toStoryboardNodesFromBackend(
              [backendNode],
              workflowNodeActions,
              routes
            )
            if (!storyboardNode) return null
            hydratedWorkflowCardIdsRef.current.add(targetNodeId)
            document.updateNodes((current) =>
              canApplyDetail(current)
                ? upsertStoryboardNodesLocally(current, [storyboardNode])
                : current
            )
            return backendNode
          }
          throw new Error("画布数据持续更新，请重新加载卡片详情")
        } catch (error) {
          console.warn("加载工作流卡片详情失败:", error)
          if (requestIsCurrent()) {
            toast.warning(errMsg(error, "加载工作流卡片详情失败"))
          }
          return null
        } finally {
          if (
            hydratingWorkflowCardPromisesRef.current.get(targetNodeId) ===
            requestPromise
          ) {
            hydratingWorkflowCardPromisesRef.current.delete(targetNodeId)
            setHydratingWorkflowCardIds((current) => {
              if (!current.has(targetNodeId)) return current
              const next = new Set(current)
              next.delete(targetNodeId)
              return next
            })
          }
        }
      })()
      requestPromise = loadPromise
      hydratingWorkflowCardPromisesRef.current.set(targetNodeId, loadPromise)
      return loadPromise
    },
    [
      backendReady,
      callBackend,
      episodeId,
      projectId,
      routes,
      document.updateNodes,
      workflowNodeActions,
    ]
  )

  const refreshWorkflowCardsAfterInputMutation = useCallback(
    (nodeIds: string[]) => {
      const targetNodeIds = Array.from(
        new Set(
          nodeIds.map((nodeId) => String(nodeId || "").trim()).filter(Boolean)
        )
      )
      if (!targetNodeIds.length) return
      workflowCardHydrationGenerationRef.current += 1
      targetNodeIds.forEach((nodeId) => {
        hydratedWorkflowCardIdsRef.current.delete(nodeId)
        hydratingWorkflowCardPromisesRef.current.delete(nodeId)
      })
      setHydratingWorkflowCardIds((current) => {
        let changed = false
        const next = new Set(current)
        targetNodeIds.forEach((nodeId) => {
          if (next.delete(nodeId)) changed = true
        })
        return changed ? next : current
      })
      targetNodeIds.forEach((nodeId) => {
        void hydrateWorkflowCard(nodeId, { force: true })
      })
    },
    [hydrateWorkflowCard]
  )

  const hydrateStoryboardNodeForRun = useCallback(
    async (node: StoryboardNode) => {
      const hydratedBackendNode = await hydrateWorkflowCard(node.id, {
        force: true,
      })
      if (!hydratedBackendNode) return node
      const [hydratedNode] = toStoryboardNodesFromBackend(
        [hydratedBackendNode],
        workflowNodeActions,
        routes
      )
      return hydratedNode ?? node
    },
    [hydrateWorkflowCard, routes, workflowNodeActions]
  )

  const isLoaded = useCallback(
    (nodeId: string) => hydratedWorkflowCardIdsRef.current.has(nodeId),
    []
  )
  const markLoaded = useCallback((nodeIds: string[]) => {
    nodeIds.forEach((nodeId) => {
      hydratedWorkflowCardIdsRef.current.add(nodeId)
      hydratingWorkflowCardPromisesRef.current.delete(nodeId)
    })
    setHydratingWorkflowCardIds((current) => {
      const next = new Set(current)
      let changed = false
      nodeIds.forEach((id) => {
        if (next.delete(id)) changed = true
      })
      return changed ? next : current
    })
  }, [])
  const peekSourceText = useCallback(
    () =>
      episodeSourceTextCacheRef.current.get(episodeSourceTextScopeKey) ?? null,
    [episodeSourceTextScopeKey]
  )
  return {
    loadingIds: hydratingWorkflowCardIds,
    isLoaded,
    markLoaded,
    reset: resetWorkflowCardHydration,
    hydrate: hydrateWorkflowCard,
    refresh: refreshWorkflowCardsAfterInputMutation,
    hydrateForRun: hydrateStoryboardNodeForRun,
    readSourceText: getCachedEpisodeSourceText,
    cacheSourceText: cacheEpisodeSourceText,
    invalidateSourceText: invalidateEpisodeSourceTextCache,
    peekSourceText,
    applySourceText: applyEpisodeSourceTextToCurrentNodes,
  }
}
export type WorkflowCanvasDetails = ReturnType<typeof useWorkflowCanvasDetails>
