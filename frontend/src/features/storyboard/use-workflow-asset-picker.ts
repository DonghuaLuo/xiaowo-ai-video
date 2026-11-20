import { useCallback, useEffect, useMemo, useState } from "react"
import type { UIEvent } from "react"
import type {
  AssetItem,
  AssetType,
  BackendCaller,
  InputImageFile,
} from "@/backend"
import {
  getCachedAssetRows,
  loadCachedAssetRows,
} from "@/features/assets/asset-cache"
import { pickLocalMediaFile } from "@/shared/image-picker"
import { mediaAssetFromImageFile, mediaPreviewSrc } from "@/shared/media"
import {
  ADD_ASSET_KIND_CONFIG,
  CANVAS_ASSET_PICKER_BATCH_SIZE,
  assetDesignPromptForCanvas,
  defaultAssetMediaVersionId,
  defaultMediaPurposeForAddAssetKind,
  externalMediaPurposeRequiresFile,
  rememberAddAssetKind,
  storedAddAssetKind,
  type AddAssetDraft,
  type AddAssetKind,
  type AddAssetKindConfig,
  type ExternalMediaPurpose,
} from "./workflow-canvas-asset-model"
import {
  canvasProjectAssetNameExists,
  mediaPurposeProjectAssetType,
} from "./workflow-canvas-assets"

/** Owns the import dialog draft, project catalogue reads, selection and paging. */
export function useWorkflowAssetPicker({
  projectId,
  backendReady,
  callBackend,
}: {
  projectId: string
  backendReady: boolean
  callBackend: BackendCaller
}) {
  const [lastAddAssetKind, setLastAddAssetKind] =
    useState<AddAssetKind>(storedAddAssetKind)
  const [assetDraft, setAssetDraft] = useState<AddAssetDraft | null>(null)
  const [assetQuery, setAssetQuery] = useState("")
  const [assetRows, setAssetRows] = useState<AssetItem[]>([])
  const [assetVisibleCount, setAssetVisibleCount] = useState(
    CANVAS_ASSET_PICKER_BATCH_SIZE
  )
  const [assetPickerLoading, setAssetPickerLoading] = useState(false)
  const openAddAssetDialog = useCallback(
    (
      kind: AddAssetKind = lastAddAssetKind,
      placementPosition?: { x: number; y: number },
      options: {
        mediaFile?: InputImageFile | null
        mediaPurpose?: ExternalMediaPurpose
        title?: string
      } = {}
    ) => {
      setLastAddAssetKind(kind)
      rememberAddAssetKind(kind)
      setAssetQuery("")
      setAssetVisibleCount(CANVAS_ASSET_PICKER_BATCH_SIZE)
      setAssetDraft({
        kind,
        selectedAssetId: "",
        selectedAssetIds: [],
        selectedMediaVersionId: "",
        selectedMediaVersionIds: {},
        mediaFile: options.mediaFile ?? null,
        mediaPurpose:
          options.mediaPurpose ?? defaultMediaPurposeForAddAssetKind(kind),
        title:
          options.title ??
          (options.mediaFile?.name ?? "").replace(/\.[a-z0-9]+$/i, "").trim(),
        note: "",
        voiceStyle: "",
        placementPosition,
      })
    },
    [lastAddAssetKind]
  )
  const activeAddAssetConfig = assetDraft
    ? ADD_ASSET_KIND_CONFIG[assetDraft.kind]
    : undefined
  const activeAssetRowsType =
    activeAddAssetConfig?.assetType ??
    (activeAddAssetConfig?.sourceType === "media"
      ? mediaPurposeProjectAssetType(assetDraft?.mediaPurpose)
      : "")

  useEffect(() => {
    if (!assetDraft || !activeAssetRowsType) {
      setAssetRows([])
      setAssetPickerLoading(false)
      return
    }
    if (!backendReady) {
      setAssetRows([])
      setAssetPickerLoading(false)
      return
    }

    const assetType = activeAssetRowsType as AssetType
    const cacheOptions = {
      scope: "project" as const,
      projectId: projectId,
      assetType,
      lifecycleStatus: "active" as const,
    }
    const cachedRows = getCachedAssetRows(cacheOptions) as AssetItem[] | null
    if (cachedRows) {
      setAssetRows(cachedRows)
      setAssetPickerLoading(false)
      setAssetVisibleCount(CANVAS_ASSET_PICKER_BATCH_SIZE)
      return
    } else {
      setAssetRows([])
      setAssetPickerLoading(true)
    }
    let cancelled = false
    loadCachedAssetRows(callBackend, cacheOptions)
      .then((rows) => {
        if (cancelled) return
        setAssetRows(rows)
        setAssetVisibleCount(CANVAS_ASSET_PICKER_BATCH_SIZE)
      })
      .catch((error) => {
        if (cancelled) return
        console.warn("加载项目资产失败:", error)
        setAssetRows([])
      })
      .finally(() => {
        if (!cancelled) setAssetPickerLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [
    activeAssetRowsType,
    assetDraft?.kind,
    assetDraft?.mediaPurpose,
    backendReady,
    callBackend,
    projectId,
  ])

  const filteredAssetRows = useMemo(() => {
    const keyword = assetQuery.trim().toLocaleLowerCase()
    if (!keyword) return assetRows
    return assetRows.filter((item) =>
      [item.name, item.tag, item.desc, assetDesignPromptForCanvas(item)]
        .join(" ")
        .toLocaleLowerCase()
        .includes(keyword)
    )
  }, [assetQuery, assetRows])
  const visibleAssetRows = filteredAssetRows.slice(0, assetVisibleCount)
  const selectedAssetIds = useMemo(() => {
    if (!assetDraft) return []
    const ids = Array.isArray(assetDraft.selectedAssetIds)
      ? assetDraft.selectedAssetIds
      : []
    if (
      assetDraft.selectedAssetId &&
      !ids.includes(assetDraft.selectedAssetId)
    ) {
      return [...ids, assetDraft.selectedAssetId]
    }
    return ids
  }, [assetDraft])
  const selectedAssetIdSet = useMemo(
    () => new Set(selectedAssetIds),
    [selectedAssetIds]
  )
  const selectedAssetRows = useMemo(
    () =>
      selectedAssetIds
        .map((id) => assetRows.find((item) => item.id === id))
        .filter((item): item is AssetItem => Boolean(item)),
    [assetRows, selectedAssetIds]
  )
  const handleAssetPickerScroll = useCallback(
    (event: UIEvent<HTMLDivElement>) => {
      const target = event.currentTarget
      const distanceToBottom =
        target.scrollHeight - target.scrollTop - target.clientHeight
      if (distanceToBottom > 280) return
      setAssetVisibleCount((current) =>
        Math.min(
          filteredAssetRows.length,
          current + CANVAS_ASSET_PICKER_BATCH_SIZE
        )
      )
    },
    [filteredAssetRows.length]
  )
  const handlePickExternalMediaFile = useCallback(async () => {
    const purpose = assetDraft?.mediaPurpose
    const isVideo = purpose === "video"
    const file = await pickLocalMediaFile(
      isVideo ? "导入视频" : "导入图片",
      isVideo ? "video" : "image"
    )
    if (!file) return
    setAssetDraft((current) =>
      current && current.mediaPurpose === purpose
        ? {
            ...current,
            mediaFile: file,
            title: file.name.replace(/\.[a-z0-9]+$/i, "").trim(),
          }
        : current
    )
  }, [assetDraft?.mediaPurpose])
  const toggleAssetSelection = useCallback((item: AssetItem) => {
    const mediaVersionId = defaultAssetMediaVersionId(item)
    setAssetDraft((current) => {
      if (!current) return current
      const currentIds = Array.isArray(current.selectedAssetIds)
        ? current.selectedAssetIds
        : []
      const baseIds =
        current.selectedAssetId && !currentIds.includes(current.selectedAssetId)
          ? [...currentIds, current.selectedAssetId]
          : currentIds
      const isSelected = baseIds.includes(item.id)
      const nextIds = isSelected
        ? baseIds.filter((id) => id !== item.id)
        : [...baseIds, item.id]
      const nextVersionIds = { ...(current.selectedMediaVersionIds ?? {}) }
      if (isSelected) {
        delete nextVersionIds[item.id]
      } else {
        nextVersionIds[item.id] = mediaVersionId
      }
      const lastSelectedId = nextIds[nextIds.length - 1] ?? ""
      return {
        ...current,
        selectedAssetId: lastSelectedId,
        selectedAssetIds: nextIds,
        selectedMediaVersionId: lastSelectedId
          ? nextVersionIds[lastSelectedId] || ""
          : "",
        selectedMediaVersionIds: nextVersionIds,
      }
    })
  }, [])

  const addAssetKinds = Object.entries(ADD_ASSET_KIND_CONFIG) as Array<
    [AddAssetKind, AddAssetKindConfig]
  >
  const hasMoreAssetRows = filteredAssetRows.length > visibleAssetRows.length
  const assetDraftMedia = assetDraft?.mediaFile
    ? mediaAssetFromImageFile(assetDraft.mediaFile)
    : null
  const assetDraftMediaKind = assetDraftMedia?.kind ?? "image"
  const assetDraftMediaPreview = assetDraftMedia
    ? mediaPreviewSrc(assetDraftMedia)
    : null
  const assetDraftRequiresMediaFile = Boolean(
    assetDraft &&
    activeAddAssetConfig?.sourceType === "media" &&
    externalMediaPurposeRequiresFile(assetDraft.mediaPurpose)
  )
  const assetDraftDuplicateNameType =
    assetDraft && activeAddAssetConfig?.sourceType === "media"
      ? mediaPurposeProjectAssetType(assetDraft.mediaPurpose)
      : ""
  const assetDraftHasDuplicateProjectName = Boolean(
    assetDraftDuplicateNameType &&
    assetDraft?.title.trim() &&
    canvasProjectAssetNameExists(assetRows, assetDraft.title)
  )

  const selectKind = useCallback((kind: AddAssetKind) => {
    const config = ADD_ASSET_KIND_CONFIG[kind]
    setLastAddAssetKind(kind)
    rememberAddAssetKind(kind)
    setAssetQuery("")
    setAssetVisibleCount(CANVAS_ASSET_PICKER_BATCH_SIZE)
    setAssetDraft((current) =>
      current
        ? {
            ...current,
            kind,
            selectedAssetId: "",
            selectedAssetIds: [],
            selectedMediaVersionId: "",
            selectedMediaVersionIds: {},
            mediaPurpose:
              config.sourceType === "media"
                ? current.mediaPurpose
                : defaultMediaPurposeForAddAssetKind(kind),
            mediaFile: config.sourceType === "media" ? current.mediaFile : null,
            voiceStyle: config.sourceType === "media" ? current.voiceStyle : "",
          }
        : current
    )
  }, [])
  const selectPurpose = useCallback((purpose: ExternalMediaPurpose) => {
    setAssetDraft((current) => {
      if (!current || current.mediaPurpose === purpose) return current
      const mediaKind = current.mediaFile
        ? mediaAssetFromImageFile(current.mediaFile).kind
        : current.mediaPurpose === "video"
          ? "video"
          : "image"
      const keepMedia = mediaKind === (purpose === "video" ? "video" : "image")
      return {
        ...current,
        mediaPurpose: purpose,
        mediaFile: keepMedia ? current.mediaFile : null,
        title: keepMedia ? current.title : "",
        note: keepMedia ? current.note : "",
        voiceStyle: "",
      }
    })
  }, [])
  const close = useCallback(() => setAssetDraft(null), [])
  const setQuery = useCallback((query: string) => {
    setAssetQuery(query)
    setAssetVisibleCount(CANVAS_ASSET_PICKER_BATCH_SIZE)
  }, [])
  return {
    assetDraft,
    activeAddAssetConfig,
    addAssetKinds,
    setQuery,
    setAssetDraft,
    lastAddAssetKind,
    handlePickExternalMediaFile,
    assetDraftMediaPreview,
    assetDraftMediaKind,
    assetDraftHasDuplicateProjectName,
    assetDraftDuplicateNameType,
    assetQuery,
    assetRows,
    selectedAssetIds,
    assetPickerLoading,
    filteredAssetRows,
    handleAssetPickerScroll,
    visibleAssetRows,
    selectedAssetIdSet,
    selectedAssetRows,
    toggleAssetSelection,
    hasMoreAssetRows,
    assetDraftRequiresMediaFile,
    open: openAddAssetDialog,
    close,
    selectKind,
    selectPurpose,
  }
}
export type WorkflowAssetPicker = ReturnType<typeof useWorkflowAssetPicker>
