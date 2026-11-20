import {
  listAssets,
  type AssetType,
  type BackendCaller,
} from "@/backend"
import type { AssetItem } from "@/features/asset-model"

export type AssetLifecycleStatus = "active" | "offline" | "all"

type AssetCacheEventRecord = Record<string, unknown>

export type AssetRowsCacheOptions = {
  scope: "global" | "project"
  projectId?: string
  assetType: AssetType
  lifecycleStatus?: AssetLifecycleStatus
  includeSourceMetadata?: boolean
}

export type AssetRowUpdate = {
  asset: AssetItem
  revision: number
}

type NormalizedAssetRowsCacheOptions = {
  scope: "global" | "project"
  projectId: string
  assetType: AssetType
  lifecycleStatus: AssetLifecycleStatus
  includeSourceMetadata: boolean
}

type AssetRowsCacheEntry = NormalizedAssetRowsCacheOptions & {
  rows: AssetItem[] | null
  inFlight?: Promise<AssetItem[]>
  updatedAt: number
}

const assetRowsCache = new Map<string, AssetRowsCacheEntry>()
const projectAssetTypes: AssetType[] = [
  "characters",
  "creatures",
  "scenes",
  "props",
]
const projectAssetActionNames = new Set([
  "asset_created",
  "asset_updated",
  "asset_deleted",
  "asset_upserted",
  "asset_batch_saved",
  "asset_media_generated",
  "asset_media_version_activated",
  "asset_media_version_updated",
  "asset_media_version_deleted",
  "project_assets_deleted_all",
  "agent_split_completed",
])
const projectAssetRowUpsertActionNames = new Set([
  "asset_created",
  "asset_updated",
  "asset_upserted",
  "asset_media_generated",
  "asset_media_version_activated",
  "asset_media_version_updated",
  "asset_media_version_deleted",
])
const projectAssetRowDeleteActionNames = new Set(["asset_deleted"])

function isEventRecord(value: unknown): value is AssetCacheEventRecord {
  return Boolean(value && typeof value === "object" && !Array.isArray(value))
}

function eventString(value: unknown) {
  return String(value ?? "").trim()
}

function eventStringFrom(
  row: AssetCacheEventRecord | null | undefined,
  keys: string[]
) {
  if (!row) return ""
  for (const key of keys) {
    const value = eventString(row[key])
    if (value) return value
  }
  return ""
}

function eventArrayStrings(value: unknown) {
  return Array.isArray(value)
    ? value.map((item) => eventString(item)).filter(Boolean)
    : []
}

function normalizeEventAssetType(value: unknown): AssetType | null {
  const raw = eventString(value)
  return projectAssetTypes.includes(raw as AssetType) ? (raw as AssetType) : null
}

function eventChangedResources(row: AssetCacheEventRecord) {
  return [
    ...eventArrayStrings(row.changedResources),
    ...eventArrayStrings(row.changed_resources),
  ]
}

function eventProjectEffect(row: AssetCacheEventRecord) {
  const effect = row.projectEffect ?? row.project_effect
  return isEventRecord(effect) ? effect : null
}

function assetFromBackendEventPayload(
  row: AssetCacheEventRecord
): AssetItem | null {
  const result = isEventRecord(row.result) ? row.result : null
  const resultAsset = result?.asset
  const asset = isEventRecord(row.asset)
    ? row.asset
    : isEventRecord(resultAsset)
      ? resultAsset
      : null
  if (!asset || typeof asset.id !== "string" || !asset.id.trim()) return null
  return asset as AssetItem
}

function assetTypeFromBackendEvent(
  row: AssetCacheEventRecord,
  effect: AssetCacheEventRecord | null
) {
  const result = isEventRecord(row.result) ? row.result : null
  return (
    normalizeEventAssetType(
      eventStringFrom(row, ["assetType", "asset_type"])
    ) ??
    normalizeEventAssetType(
      eventStringFrom(result, ["assetType", "asset_type"])
    ) ??
    normalizeEventAssetType(
      eventStringFrom(effect, ["assetType", "asset_type"])
    )
  )
}

function projectIdFromBackendEvent(
  row: AssetCacheEventRecord,
  effect: AssetCacheEventRecord | null
) {
  return (
    eventStringFrom(row, ["projectId", "project_id"]) ||
    eventStringFrom(effect, ["projectId", "project_id"])
  )
}

function normalizeAssetRowsCacheOptions(
  options: AssetRowsCacheOptions
): NormalizedAssetRowsCacheOptions {
  const lifecycleStatus =
    options.scope === "project" ? options.lifecycleStatus ?? "active" : "all"
  return {
    scope: options.scope,
    projectId: options.scope === "project" ? options.projectId ?? "" : "",
    assetType: options.assetType,
    lifecycleStatus,
    includeSourceMetadata:
      options.scope === "project" && Boolean(options.includeSourceMetadata),
  }
}

export function assetRowsCacheKey(options: AssetRowsCacheOptions) {
  const normalized = normalizeAssetRowsCacheOptions(options)
  return [
    normalized.scope,
    normalized.projectId,
    normalized.assetType,
    normalized.lifecycleStatus,
    normalized.includeSourceMetadata ? "source" : "lite",
  ].join(":")
}

export function getCachedAssetRows(options: AssetRowsCacheOptions) {
  const normalized = normalizeAssetRowsCacheOptions(options)
  const directRows = assetRowsCache.get(assetRowsCacheKey(normalized))?.rows
  if (directRows) return directRows
  if (normalized.scope === "project" && !normalized.includeSourceMetadata) {
    return (
      assetRowsCache.get(
        assetRowsCacheKey({ ...normalized, includeSourceMetadata: true })
      )?.rows ?? null
    )
  }
  return null
}

export function setCachedAssetRows(
  options: AssetRowsCacheOptions,
  rows: AssetItem[]
) {
  const normalized = normalizeAssetRowsCacheOptions(options)
  const key = assetRowsCacheKey(normalized)
  const current = assetRowsCache.get(key)
  assetRowsCache.set(key, {
    ...normalized,
    inFlight: current?.inFlight,
    rows,
    updatedAt: Date.now(),
  })
}

export async function loadCachedAssetRows(
  callBackend: BackendCaller,
  options: AssetRowsCacheOptions,
  requestOptions: { force?: boolean } = {}
) {
  const normalized = normalizeAssetRowsCacheOptions(options)
  const key = assetRowsCacheKey(normalized)
  const current = assetRowsCache.get(key)
  const readableCachedRows = getCachedAssetRows(normalized)
  if (!requestOptions.force && readableCachedRows) {
    if (!current?.rows) setCachedAssetRows(normalized, readableCachedRows)
    return readableCachedRows
  }
  if (current?.inFlight && !requestOptions.force) return current.inFlight

  let request: Promise<AssetItem[]>
  request = listAssets(
    callBackend,
    normalized.scope,
    normalized.projectId || undefined,
    {
      assetType: normalized.assetType,
      lifecycleStatus: normalized.lifecycleStatus,
      includeSourceMetadata: normalized.includeSourceMetadata,
    }
  )
    .then((library) => {
      const rows = (library[normalized.assetType] ?? []) as AssetItem[]
      const latest = assetRowsCache.get(key)
      if (latest?.inFlight === request) {
        assetRowsCache.set(key, {
          ...normalized,
          rows,
          updatedAt: Date.now(),
        })
      }
      return rows
    })
    .catch((error) => {
      const latest = assetRowsCache.get(key)
      if (latest?.inFlight === request) {
        if (latest.rows) {
          assetRowsCache.set(key, { ...latest, inFlight: undefined })
        } else {
          assetRowsCache.delete(key)
        }
      }
      throw error
    })

  assetRowsCache.set(key, {
    ...normalized,
    rows: current?.rows ?? null,
    inFlight: request,
    updatedAt: current?.updatedAt ?? 0,
  })
  return request
}

export function assetLifecycleStatus(asset: AssetItem): "active" | "offline" {
  return asset.lifecycleStatus ?? asset.lifecycle_status ?? "active"
}

export function assetMatchesLifecycleStatus(
  asset: AssetItem,
  lifecycleStatus: AssetLifecycleStatus
) {
  return (
    lifecycleStatus === "all" || assetLifecycleStatus(asset) === lifecycleStatus
  )
}

function assetBelongsToCacheEntry(
  entry: NormalizedAssetRowsCacheOptions,
  asset: AssetItem
) {
  if (entry.scope === "global") return true
  return assetMatchesLifecycleStatus(asset, entry.lifecycleStatus)
}

function mergeAssetRow(current: AssetItem, next: AssetItem): AssetItem {
  return {
    ...current,
    ...next,
    sourceRange: next.sourceRange ?? current.sourceRange,
    sourceRangeLabel: next.sourceRangeLabel ?? current.sourceRangeLabel,
    sourceRangeSummary: next.sourceRangeSummary ?? current.sourceRangeSummary,
    sourceRefs: next.sourceRefs ?? current.sourceRefs,
  }
}

export function upsertAssetRows(rows: AssetItem[], asset: AssetItem) {
  let matched = false
  const nextRows = rows.map((row) => {
    if (row.id !== asset.id) return row
    matched = true
    return mergeAssetRow(row, asset)
  })
  return matched ? nextRows : [asset, ...nextRows]
}

export function removeAssetRows(rows: AssetItem[], assetId: string) {
  return rows.filter((row) => row.id !== assetId)
}

export function mergeAssetRowsWithUpdates(
  rows: AssetItem[],
  updates: Map<string, AssetRowUpdate>,
  sinceRevision: number,
  lifecycleStatus: AssetLifecycleStatus = "all"
) {
  let nextRows = rows
  updates.forEach(({ asset, revision }) => {
    if (revision > sinceRevision) {
      nextRows = assetMatchesLifecycleStatus(asset, lifecycleStatus)
        ? upsertAssetRows(nextRows, asset)
        : removeAssetRows(nextRows, asset.id)
    }
  })
  return nextRows
}

function cacheEntryMatches(
  entry: NormalizedAssetRowsCacheOptions,
  options: Pick<AssetRowsCacheOptions, "scope" | "projectId" | "assetType">
) {
  const normalized = normalizeAssetRowsCacheOptions({
    ...options,
    lifecycleStatus: "all",
  })
  return (
    entry.scope === normalized.scope &&
    entry.projectId === normalized.projectId &&
    entry.assetType === normalized.assetType
  )
}

export function upsertCachedAssetRows(
  options: Pick<AssetRowsCacheOptions, "scope" | "projectId" | "assetType">,
  asset: AssetItem
) {
  assetRowsCache.forEach((entry, key) => {
    if (!entry.rows || !cacheEntryMatches(entry, options)) return
    const rows = assetBelongsToCacheEntry(entry, asset)
      ? upsertAssetRows(entry.rows, asset)
      : removeAssetRows(entry.rows, asset.id)
    assetRowsCache.set(key, { ...entry, rows, updatedAt: Date.now() })
  })
}

export function removeCachedAssetRows(
  options: Pick<AssetRowsCacheOptions, "scope" | "projectId" | "assetType">,
  assetId: string
) {
  assetRowsCache.forEach((entry, key) => {
    if (!entry.rows || !cacheEntryMatches(entry, options)) return
    assetRowsCache.set(key, {
      ...entry,
      rows: removeAssetRows(entry.rows, assetId),
      updatedAt: Date.now(),
    })
  })
}

export function invalidateCachedAssetRows(
  options?: Partial<AssetRowsCacheOptions>
) {
  if (!options) {
    assetRowsCache.clear()
    return
  }
  const normalizedProjectId =
    options.scope === "project" ? options.projectId ?? "" : undefined
  assetRowsCache.forEach((entry, key) => {
    if (options.scope && entry.scope !== options.scope) return
    if (
      normalizedProjectId !== undefined &&
      entry.projectId !== normalizedProjectId
    ) {
      return
    }
    if (options.assetType && entry.assetType !== options.assetType) return
    if (
      options.lifecycleStatus &&
      entry.lifecycleStatus !== options.lifecycleStatus
    ) {
      return
    }
    assetRowsCache.delete(key)
  })
}

export function syncAssetRowsCacheFromBackendEvent(
  eventName: string,
  payload: unknown
) {
  if (!isEventRecord(payload)) return false
  const normalizedEventName = eventString(eventName).toLowerCase()
  const effect = eventProjectEffect(payload)
  const projectId = projectIdFromBackendEvent(payload, effect)
  const assetType = assetTypeFromBackendEvent(payload, effect)
  const action =
    eventStringFrom(payload, ["action", "type"]) ||
    eventStringFrom(effect, ["action", "type"])
  const normalizedAction = action.toLowerCase()
  const taskType = eventStringFrom(payload, ["type", "taskType", "task_type"])
    .toLowerCase()
  const status = eventStringFrom(payload, ["status"]).toLowerCase()
  const asset = assetFromBackendEventPayload(payload)
  const changedResources = [
    ...eventChangedResources(payload),
    ...(effect ? eventChangedResources(effect) : []),
  ]
  const changedAssetTypes = Array.from(
    new Set(
      changedResources
        .map((resource) => normalizeEventAssetType(resource))
        .filter((resource): resource is AssetType => Boolean(resource))
    )
  )
  const allAssetsChanged = changedResources.some((resource) =>
    ["asset", "assets"].includes(resource.toLowerCase())
  )
  const isProjectScope = Boolean(projectId)
  let touched = false

  const upsertProjectAsset = (targetType: AssetType, targetAsset: AssetItem) => {
    if (!projectId) return
    upsertCachedAssetRows(
      { scope: "project", projectId, assetType: targetType },
      targetAsset
    )
    touched = true
  }
  const invalidateProjectAssetType = (targetType: AssetType) => {
    if (!projectId) return
    invalidateCachedAssetRows({
      scope: "project",
      projectId,
      assetType: targetType,
    })
    touched = true
  }
  const invalidateAllProjectAssets = () => {
    if (!projectId) return
    invalidateCachedAssetRows({ scope: "project", projectId })
    touched = true
  }

  if (asset && assetType && projectAssetRowUpsertActionNames.has(normalizedAction)) {
    upsertProjectAsset(assetType, asset)
    return touched
  }

  if (
    assetType &&
    projectAssetRowDeleteActionNames.has(normalizedAction)
  ) {
    const assetId = eventStringFrom(payload, ["assetId", "asset_id"])
    if (assetId) {
      removeCachedAssetRows(
        { scope: "project", projectId, assetType },
        assetId
      )
      touched = true
      return touched
    }
  }

  if (
    normalizedEventName === "task_completed" &&
    taskType === "asset_image" &&
    assetType &&
    projectId
  ) {
    if (asset) {
      upsertProjectAsset(assetType, asset)
      return touched
    } else if (["completed", "succeeded"].includes(status)) {
      invalidateProjectAssetType(assetType)
      return touched
    }
  }

  if (!isProjectScope) return touched

  if (changedAssetTypes.length) {
    changedAssetTypes.forEach(invalidateProjectAssetType)
    return touched
  }
  if (
    allAssetsChanged ||
    (assetType && projectAssetActionNames.has(normalizedAction)) ||
    (!assetType && projectAssetActionNames.has(normalizedAction))
  ) {
    if (assetType) invalidateProjectAssetType(assetType)
    else invalidateAllProjectAssets()
  }

  return touched
}
