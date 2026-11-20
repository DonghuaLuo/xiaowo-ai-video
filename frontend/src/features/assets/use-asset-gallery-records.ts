import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { listTasks, type AssetType, type TaskRow } from "@/backend"
import type { useBackend } from "@/hooks/useBackend"
import type { AssetTab } from "@/navigation"
import { type AssetItem } from "@/features/asset-model"
import { errMsg } from "@/shared/backend-result"
import {
  assetMatchesLifecycleStatus,
  assetRowsCacheKey,
  getCachedAssetRows,
  loadCachedAssetRows,
  mergeAssetRowsWithUpdates,
  removeAssetRows,
  removeCachedAssetRows,
  setCachedAssetRows,
  upsertAssetRows,
  upsertCachedAssetRows,
  type AssetLifecycleStatus,
  type AssetRowUpdate,
} from "@/features/assets/asset-cache"
import {
  assetDesignPrompt,
  type AssetLifecycleView,
} from "./asset-gallery-cards"
const ASSET_GRID_BATCH_SIZE = 48

type AssetRowsViewState = {
  key: string
  rows: AssetItem[] | null
}

type AssetRowsRequestState = {
  key: string
  loading: boolean
  error: string
}

type AssetLifecycleViewState = {
  key: string
  value: AssetLifecycleView
}

function isRunningAssetImageTask(
  task: TaskRow,
  projectId: string,
  tab: AssetTab
) {
  return (
    task.projectId === projectId &&
    task.type === "asset_image" &&
    task.assetType === tab &&
    (task.status === "running" || task.status === "created")
  )
}

function taskAssetId(task: TaskRow) {
  return String(task.assetId || task.nodeId || "")
}

function runningAssetImageIds(
  tasks: TaskRow[],
  projectId: string,
  tab: AssetTab
) {
  return new Set(
    tasks
      .filter((task) => isRunningAssetImageTask(task, projectId, tab))
      .map(taskAssetId)
      .filter(Boolean)
  )
}

function assetFromTaskPayload(payload: any): AssetItem | null {
  const directAsset = payload?.asset
  const result =
    payload?.result &&
    typeof payload.result === "object" &&
    !Array.isArray(payload.result)
      ? payload.result
      : null
  const asset = directAsset ?? result?.asset
  if (!asset || typeof asset !== "object" || typeof asset.id !== "string") {
    return null
  }
  return asset as AssetItem
}

function assetIdFromEventPayload(payload: any) {
  return String(payload?.assetId || payload?.asset_id || payload?.nodeId || "")
}

export type AssetGalleryRecordsOptions = {
  tab: AssetTab
  scope: "global" | "project"
  projectId?: string
  projectVersion?: number
  agentRefreshToken?: number
  focusAssetId?: string
  taskRows?: TaskRow[]
}

/** Owns asset rows, cache reconciliation, task subscriptions and the current view. */
export function useAssetGalleryRecords({
  backend,
  tab,
  scope,
  projectId,
  projectVersion,
  agentRefreshToken,
  focusAssetId,
  taskRows,
}: AssetGalleryRecordsOptions & {
  backend: Pick<ReturnType<typeof useBackend>, "backendReady" | "backendError" | "callBackend" | "onBackendEvent">
}) {
  const { backendReady, backendError, callBackend, onBackendEvent } = backend
  const [query, setQuery] = useState("")

  const [selectedAsset, setSelectedAsset] = useState<AssetItem | null>(null)

  const [versionAsset, setVersionAsset] = useState<AssetItem | null>(null)

  const [remoteRowsState, setRemoteRowsState] = useState<AssetRowsViewState>({
    key: "",
    rows: null,
  })

  const [assetRowsRequestState, setAssetRowsRequestState] =
    useState<AssetRowsRequestState | null>(null)

  const lifecycleViewScopeKey = `${projectId ?? ""}:${scope}:${tab}`

  const [lifecycleViewState, setLifecycleViewState] =
    useState<AssetLifecycleViewState>({
      key: "",
      value: "active",
    })

  const lifecycleView =
    lifecycleViewState.key === lifecycleViewScopeKey
      ? lifecycleViewState.value
      : "active"

  const setLifecycleViewForCurrent = useCallback(
    (value: AssetLifecycleView) => {
      setLifecycleViewState({ key: lifecycleViewScopeKey, value })
    },
    [lifecycleViewScopeKey]
  )

  const [generatingAssetIds, setGeneratingAssetIds] = useState<Set<string>>(
    () => new Set()
  )

  const [visibleCount, setVisibleCount] = useState(ASSET_GRID_BATCH_SIZE)

  const assetUpdateRevisionRef = useRef(0)

  const assetUpdatesRef = useRef<Map<string, AssetRowUpdate>>(new Map())

  const assetDeletedRevisionsRef = useRef<Map<string, number>>(new Map())

  const assetRowsRequestSeqRef = useRef(0)

  const assetRowsReloadKeyRef = useRef<Map<string, string>>(new Map())

  const lifecycleFilter =
    scope === "project" && tab !== "styles"
      ? lifecycleView
      : ("all" as AssetLifecycleStatus)

  const viewKey = JSON.stringify([projectId, scope, tab, lifecycleFilter])
  const viewRef = useRef({ key: viewKey, active: true })
  if (viewRef.current.key !== viewKey) {
    viewRef.current.active = false
    viewRef.current = { key: viewKey, active: true }
    assetRowsRequestSeqRef.current += 1
  }
  const view = viewRef.current
  const isCurrentView = useCallback(
    () => viewRef.current === view && view.active,
    [view]
  )
  useEffect(() => {
    view.active = true
    setSelectedAsset(null)
    setVersionAsset(null)
    return () => {
      view.active = false
    }
  }, [view])

  const assetRowsCacheOptions = useMemo(
    () => ({
      scope,
      projectId,
      assetType: tab as AssetType,
      lifecycleStatus: lifecycleFilter,
      includeSourceMetadata: scope === "project",
    }),
    [lifecycleFilter, projectId, scope, tab]
  )

  const currentAssetRowsCacheKey = useMemo(
    () => assetRowsCacheKey(assetRowsCacheOptions),
    [assetRowsCacheOptions]
  )

  const setRemoteRowsForCache = useCallback(
    (
      cacheKey: string,
      nextRows:
        | AssetItem[]
        | null
        | ((currentRows: AssetItem[] | null) => AssetItem[] | null)
    ) => {
      setRemoteRowsState((current) => {
        const currentRows = current.key === cacheKey ? current.rows : null
        return {
          key: cacheKey,
          rows:
            typeof nextRows === "function" ? nextRows(currentRows) : nextRows,
        }
      })
    },
    []
  )

  const cachedRowsForCurrentView = getCachedAssetRows(assetRowsCacheOptions)

  const remoteRows =
    remoteRowsState.key === currentAssetRowsCacheKey
      ? (remoteRowsState.rows ?? cachedRowsForCurrentView)
      : cachedRowsForCurrentView

  const currentRequest =
    assetRowsRequestState?.key === currentAssetRowsCacheKey
      ? assetRowsRequestState
      : null

  const loadError =
    (!backendReady && backendError) || currentRequest?.error || ""

  const loading = remoteRows === null && !loadError

  const refreshing = remoteRows !== null && Boolean(currentRequest?.loading)

  useEffect(() => {
    return () => {
      assetRowsRequestSeqRef.current += 1
    }
  }, [backendReady, currentAssetRowsCacheKey])

  useEffect(() => {
    assetUpdateRevisionRef.current = 0
    assetUpdatesRef.current.clear()
    assetDeletedRevisionsRef.current.clear()
  }, [projectId, scope, tab])

  const rememberAssetUpdate = useCallback((asset: AssetItem) => {
    assetUpdateRevisionRef.current += 1
    assetDeletedRevisionsRef.current.delete(asset.id)
    assetUpdatesRef.current.set(asset.id, {
      asset,
      revision: assetUpdateRevisionRef.current,
    })
  }, [])

  const rememberAssetDelete = useCallback((assetId: string) => {
    assetUpdateRevisionRef.current += 1
    assetUpdatesRef.current.delete(assetId)
    assetDeletedRevisionsRef.current.set(
      assetId,
      assetUpdateRevisionRef.current
    )
  }, [])

  const mergeRowsWithRecentUpdates = useCallback(
    (rows: AssetItem[], sinceRevision: number) => {
      let nextRows = mergeAssetRowsWithUpdates(
        rows,
        assetUpdatesRef.current,
        sinceRevision,
        lifecycleFilter
      )
      assetDeletedRevisionsRef.current.forEach((revision, assetId) => {
        if (revision > sinceRevision) {
          nextRows = removeAssetRows(nextRows, assetId)
        }
      })
      return nextRows
    },
    [lifecycleFilter]
  )

  const pruneAssetUpdatesThrough = useCallback((revision: number) => {
    assetUpdatesRef.current.forEach((entry, assetId) => {
      if (entry.revision <= revision) {
        assetUpdatesRef.current.delete(assetId)
      }
    })
    assetDeletedRevisionsRef.current.forEach((entryRevision, assetId) => {
      if (entryRevision <= revision) {
        assetDeletedRevisionsRef.current.delete(assetId)
      }
    })
  }, [])

  const loadAssetsForTab = useCallback(
    async (options: { force?: boolean } = {}) => {
      if (!isCurrentView()) return
      if (tab === "styles") return
      const cacheOptions = assetRowsCacheOptions
      const cacheKey = assetRowsCacheKey(cacheOptions)
      const requestSeq = ++assetRowsRequestSeqRef.current
      if (!backendReady) {
        setAssetRowsRequestState({ key: cacheKey, loading: false, error: "" })
        return
      }
      const cachedRows = getCachedAssetRows(cacheOptions)
      const loadStartedAtRevision = assetUpdateRevisionRef.current
      if (cachedRows) {
        const nextRows = mergeRowsWithRecentUpdates(
          cachedRows,
          loadStartedAtRevision
        )
        setCachedAssetRows(cacheOptions, nextRows)
        setRemoteRowsForCache(cacheKey, nextRows)
        if (!options.force) {
          setAssetRowsRequestState({ key: cacheKey, loading: false, error: "" })
          return nextRows
        }
      }
      setAssetRowsRequestState({ key: cacheKey, loading: true, error: "" })
      try {
        const loadedRows = await loadCachedAssetRows(
          callBackend,
          cacheOptions,
          {
            force: options.force,
          }
        )
        // The cache owns off-screen responses; only the current request may merge page edits.
        if (!isCurrentView() || requestSeq !== assetRowsRequestSeqRef.current)
          return loadedRows
        const nextRows = mergeRowsWithRecentUpdates(
          loadedRows,
          loadStartedAtRevision
        )
        pruneAssetUpdatesThrough(loadStartedAtRevision)
        setCachedAssetRows(cacheOptions, nextRows)
        setRemoteRowsForCache(cacheKey, nextRows)
        return nextRows
      } catch (error) {
        console.warn("加载资产失败:", error)
        if (isCurrentView() && requestSeq === assetRowsRequestSeqRef.current) {
          setAssetRowsRequestState({
            key: cacheKey,
            loading: false,
            error: errMsg(error, "加载资产失败"),
          })
        }
      } finally {
        if (isCurrentView() && requestSeq === assetRowsRequestSeqRef.current) {
          setAssetRowsRequestState((current) =>
            current?.key === cacheKey ? { ...current, loading: false } : current
          )
        }
      }
    },
    [
      assetRowsCacheOptions,
      isCurrentView,
      backendReady,
      callBackend,
      mergeRowsWithRecentUpdates,
      pruneAssetUpdatesThrough,
      setRemoteRowsForCache,
      tab,
    ]
  )

  useEffect(() => {
    if (tab === "styles") return
    const cacheKey = currentAssetRowsCacheKey
    const reloadKey = `${projectVersion ?? ""}:${agentRefreshToken ?? ""}`
    const previousReloadKey = assetRowsReloadKeyRef.current.get(cacheKey)
    assetRowsReloadKeyRef.current.set(cacheKey, reloadKey)
    void loadAssetsForTab({
      force: previousReloadKey !== undefined && previousReloadKey !== reloadKey,
    })
  }, [
    agentRefreshToken,
    assetRowsCacheOptions,
    currentAssetRowsCacheKey,
    loadAssetsForTab,
    projectVersion,
    tab,
  ])

  const sourceRows = remoteRows ?? []

  const rows = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    if (!keyword) return sourceRows
    return sourceRows.filter((item) =>
      [item.name, assetDesignPrompt(item), item.tag]
        .join(" ")
        .toLowerCase()
        .includes(keyword)
    )
  }, [query, sourceRows])

  const visibleRows = useMemo(
    () => rows.slice(0, visibleCount),
    [rows, visibleCount]
  )

  const hasMoreRows = rows.length > visibleRows.length

  useEffect(() => {
    setVisibleCount(ASSET_GRID_BATCH_SIZE)
  }, [lifecycleView, projectId, query, scope, tab])

  useEffect(() => {
    if (!focusAssetId) return
    const targetIndex = rows.findIndex((item) => item.id === focusAssetId)
    if (targetIndex < 0) return
    setVisibleCount((current) => {
      if (targetIndex < current) return current
      const nextBatch =
        Math.ceil((targetIndex + 1) / ASSET_GRID_BATCH_SIZE) *
        ASSET_GRID_BATCH_SIZE
      return Math.min(rows.length, nextBatch)
    })
  }, [focusAssetId, rows])

  const upsertAssetRow = useCallback(
    (asset: AssetItem) => {
      if (!isCurrentView()) return
      rememberAssetUpdate(asset)
      upsertCachedAssetRows(assetRowsCacheOptions, asset)
      setRemoteRowsForCache(currentAssetRowsCacheKey, (current) => {
        const baseRows =
          current ?? getCachedAssetRows(assetRowsCacheOptions) ?? rows
        return assetMatchesLifecycleStatus(asset, lifecycleFilter)
          ? upsertAssetRows(baseRows, asset)
          : removeAssetRows(baseRows, asset.id)
      })
      setSelectedAsset((current) =>
        current?.id === asset.id ? asset : current
      )
      setVersionAsset((current) => (current?.id === asset.id ? asset : current))
    },
    [
      assetRowsCacheOptions,
      currentAssetRowsCacheKey,
      isCurrentView,
      lifecycleFilter,
      rememberAssetUpdate,
      rows,
      setRemoteRowsForCache,
    ]
  )

  const removeAssetRow = useCallback(
    (assetId: string) => {
      if (!isCurrentView()) return
      rememberAssetDelete(assetId)
      removeCachedAssetRows(assetRowsCacheOptions, assetId)
      setRemoteRowsForCache(currentAssetRowsCacheKey, (current) =>
        (current ?? rows).filter((row) => row.id !== assetId)
      )
      setSelectedAsset((current) => (current?.id === assetId ? null : current))
      setVersionAsset((current) => (current?.id === assetId ? null : current))
    },
    [
      assetRowsCacheOptions,
      currentAssetRowsCacheKey,
      isCurrentView,
      rememberAssetDelete,
      rows,
      setRemoteRowsForCache,
    ]
  )

  const setAssetGenerating = useCallback(
    (assetId: string, active: boolean) => {
      if (!assetId || !isCurrentView()) return
      setGeneratingAssetIds((current) => {
        const next = new Set(current)
        if (active) next.add(assetId)
        else next.delete(assetId)
        return next
      })
    },
    [isCurrentView]
  )

  useEffect(() => {
    let cancelled = false
    if (
      tab === "styles" ||
      scope !== "project" ||
      !projectId ||
      !backendReady
    ) {
      setGeneratingAssetIds(new Set())
      return
    }
    if (taskRows) {
      setGeneratingAssetIds(runningAssetImageIds(taskRows, projectId, tab))
      return
    }
    listTasks(callBackend, {
      projectId,
      type: "asset_image",
      assetType: tab,
      limit: 80,
    })
      .then((tasks) => {
        if (cancelled || !isCurrentView()) return
        setGeneratingAssetIds(runningAssetImageIds(tasks, projectId, tab))
      })
      .catch((error) => {
        console.warn("恢复资产设计图任务状态失败:", error)
      })
    return () => {
      cancelled = true
    }
  }, [
    backendReady,
    callBackend,
    projectId,
    scope,
    tab,
    taskRows,
    isCurrentView,
  ])

  useEffect(() => {
    if (
      tab === "styles" ||
      scope !== "project" ||
      !projectId ||
      !backendReady
    ) {
      return
    }
    const handleAssetTaskUpdate = (payload: any) => {
      if (!isCurrentView() || !payload || payload.projectId !== projectId)
        return
      if (payload.type !== "asset_image") return
      const payloadAssetType = String(payload.assetType || "")
      if (payloadAssetType && payloadAssetType !== tab) return
      const assetId = String(payload.assetId || payload.nodeId || "")
      if (!assetId) return
      const active =
        payload.status === "running" || payload.status === "created"
      setAssetGenerating(assetId, active)
      if (payload.status === "completed") {
        const updatedAsset = assetFromTaskPayload(payload)
        if (updatedAsset) {
          upsertAssetRow(updatedAsset)
        } else {
          void loadAssetsForTab({ force: true })
        }
      }
    }
    const disposers = [
      onBackendEvent("task_created", handleAssetTaskUpdate),
      onBackendEvent("task_progress", handleAssetTaskUpdate),
      onBackendEvent("task_completed", handleAssetTaskUpdate),
      onBackendEvent("task_failed", handleAssetTaskUpdate),
      onBackendEvent("task_cancelled", handleAssetTaskUpdate),
    ]
    return () => disposers.forEach((dispose) => dispose())
  }, [
    backendReady,
    isCurrentView,
    loadAssetsForTab,
    onBackendEvent,
    projectId,
    scope,
    setAssetGenerating,
    tab,
    upsertAssetRow,
  ])

  useEffect(() => {
    if (
      tab === "styles" ||
      scope !== "project" ||
      !projectId ||
      !backendReady
    ) {
      return
    }
    const handleProjectChanged = (payload: any) => {
      if (!isCurrentView() || !payload || payload.projectId !== projectId)
        return
      const action = String(payload.action || payload.type || "")
      const assetType = String(payload.assetType || payload.asset_type || "")
      const changedResources = Array.isArray(payload.changedResources)
        ? payload.changedResources.map((item: unknown) => String(item))
        : []
      if (assetType && assetType !== tab) return
      const touchesCurrentTab =
        assetType === tab || changedResources.includes(tab)
      const genericAssetChange =
        changedResources.includes("asset") ||
        changedResources.includes("assets") ||
        action.includes("asset")
      if (!touchesCurrentTab) {
        if (genericAssetChange) {
          void loadAssetsForTab({ force: true })
        }
        return
      }
      const updatedAsset = assetFromTaskPayload(payload)
      if (updatedAsset) {
        upsertAssetRow(updatedAsset)
        return
      }
      if (action === "asset_deleted") {
        const assetId = assetIdFromEventPayload(payload)
        if (assetId) {
          removeAssetRow(assetId)
          return
        }
      }
      void loadAssetsForTab({ force: true })
    }
    const dispose = onBackendEvent("project_changed", handleProjectChanged)
    return () => dispose()
  }, [
    backendReady,
    isCurrentView,
    loadAssetsForTab,
    onBackendEvent,
    projectId,
    removeAssetRow,
    scope,
    tab,
    upsertAssetRow,
  ])

  const addCreatedAsset = (asset: AssetItem) => {
    if (!isCurrentView()) return
    rememberAssetUpdate(asset)
    upsertCachedAssetRows(assetRowsCacheOptions, asset)
    setRemoteRowsForCache(currentAssetRowsCacheKey, (current) =>
      upsertAssetRows(current ?? [], asset)
    )
  }
  const changeLifecycleView = (value: AssetLifecycleView) => {
    const options = {
      ...assetRowsCacheOptions,
      lifecycleStatus: value as AssetLifecycleStatus,
    }
    setRemoteRowsForCache(
      assetRowsCacheKey(options),
      getCachedAssetRows(options)
    )
    setVisibleCount(ASSET_GRID_BATCH_SIZE)
    setLifecycleViewForCurrent(value)
  }
  const showMore = () =>
    setVisibleCount((current) =>
      Math.min(rows.length, current + ASSET_GRID_BATCH_SIZE)
    )

  const selectAsset = useCallback(
    (asset: AssetItem | null) => {
      if (isCurrentView()) setSelectedAsset(asset)
    },
    [isCurrentView]
  )
  const viewAssetVersions = useCallback(
    (asset: AssetItem | null) => {
      if (isCurrentView()) setVersionAsset(asset)
    },
    [isCurrentView]
  )

  return {
    query,
    setQuery,
    selectedAsset,
    versionAsset,
    lifecycleView,
    generatingAssetIds,
    loadError,
    loading,
    refreshing,
    remoteRows,
    sourceRows,
    rows,
    visibleRows,
    hasMoreRows,
    loadAssetsForTab,
    upsertAssetRow,
    removeAssetRow,
    setAssetGenerating,
    addCreatedAsset,
    changeLifecycleView,
    showMore,
    isCurrentView,
    selectAsset,
    viewAssetVersions,
  }
}
export type AssetGalleryRecords = ReturnType<typeof useAssetGalleryRecords>
