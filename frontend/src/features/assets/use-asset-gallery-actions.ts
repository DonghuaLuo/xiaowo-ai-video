import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import {
  createAsset,
  deleteAsset,
  deleteAssetMediaVersion,
  generateAssetMedia,
  setActiveAssetMediaVersion,
  updateAsset,
  updateAssetMediaVersion,
  type AgentTargetContext,
  type AssetType,
  type InputImageFile,
} from "@/backend"
import type { useBackend } from "@/hooks/useBackend"
import {
  ASSET_NAME_DUPLICATE_MESSAGE,
  AssetLibraryDuplicateError,
  AssetLibraryMissingMediaError,
  buildGlobalAssetPayload,
  getAssetMeta,
  isAssetLibraryDuplicateError,
  isAssetLibraryMissingMediaError,
  normalizeAssetNameKey,
  type AssetDialogMode,
  type AssetEditPatch,
  type AssetItem,
} from "@/features/asset-model"
import { errMsg } from "@/shared/backend-result"
import { mediaAssetFromImageFile, mediaPreviewSrc } from "@/shared/media"
import {
  loadCachedAssetRows,
  upsertCachedAssetRows,
} from "@/features/assets/asset-cache"
import { type AssetLifecycleView } from "./asset-gallery-cards"
import type {
  AssetGalleryRecords,
  AssetGalleryRecordsOptions,
} from "./use-asset-gallery-records"

export type AssetTurnaroundHeadMode = "default" | "with-heads" | "without-heads"
type AssetGalleryActionsOptions = Pick<
  AssetGalleryRecordsOptions,
  "tab" | "scope" | "projectId"
> & {
  backend: Pick<ReturnType<typeof useBackend>, "backendReady" | "callBackend">
  records: Pick<
    AssetGalleryRecords,
    | "isCurrentView"
    | "addCreatedAsset"
    | "upsertAssetRow"
    | "removeAssetRow"
    | "sourceRows"
    | "selectAsset"
    | "setAssetGenerating"
    | "rows"
    | "generatingAssetIds"
  >
  publishAssetAgentTarget: (
    item: AssetItem,
    intent?: AgentTargetContext["intent"],
    field?: string
  ) => void
  onAgentTargetChange?: (target: AgentTargetContext | null) => void
}
/** Owns edit dialogs and mutations; a response may only affect its originating view. */
export function useAssetGalleryActions({
  backend,
  tab,
  scope,
  projectId,
  records,
  publishAssetAgentTarget,
  onAgentTargetChange,
}: AssetGalleryActionsOptions) {
  const { backendReady, callBackend } = backend
  const meta = getAssetMeta(tab)
  const {
    upsertAssetRow,
    removeAssetRow,
    sourceRows,
    selectAsset,
    setAssetGenerating,
  } = records
  const [dialog, setDialogState] = useState<AssetDialogMode>(null)
  const setDialog = useCallback(
    (value: AssetDialogMode) => {
      if (records.isCurrentView()) setDialogState(value)
    },
    [records.isCurrentView]
  )

  const [lifecycleUpdatingAssetIds, setLifecycleUpdatingAssetIds] = useState<
    Set<string>
  >(() => new Set())

  const [deleteTarget, setDeleteTarget] = useState<AssetItem | null>(null)

  const [deletingAssetId, setDeletingAssetId] = useState<string | null>(null)
  const [generatingAll, setGeneratingAll] = useState(false)
  const [savingHeadSettings, setSavingHeadSettings] = useState(0)
  const generationRequestsRef = useRef(new Set<string>())
  const bulkGenerationRef = useRef<object | null>(null)
  const pendingDesignRows = records.rows.filter(
    (item) => !mediaPreviewSrc(item.media) && !records.generatingAssetIds.has(item.id)
  )

  const handleCreated = (asset: AssetItem) => {
    if (!records.isCurrentView()) return
    records.addCreatedAsset(asset)
    publishAssetAgentTarget(asset, "create")
    setDialog(null)
  }

  const setAssetLifecycleUpdating = useCallback(
    (assetId: string, active: boolean) => {
      if (!assetId) return
      setLifecycleUpdatingAssetIds((current) => {
        const next = new Set(current)
        if (active) next.add(assetId)
        else next.delete(assetId)
        return next
      })
    },
    []
  )

  const handleRequestDelete = (item: AssetItem) => {
    setDeleteTarget(item)
  }

  const handleConfirmDelete = async () => {
    const item = deleteTarget
    if (!item) return
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    setDeletingAssetId(item.id)
    try {
      await deleteAsset(
        callBackend,
        tab as AssetType,
        item.id,
        scope,
        projectId
      )
      if (!records.isCurrentView()) return
      toast.success(`${meta.noun}已删除`)
      setDeleteTarget(null)
      removeAssetRow(item.id)
    } catch (error) {
      if (!records.isCurrentView()) return
      toast.error(errMsg(error, `删除${meta.noun}失败`))
    } finally {
      if (records.isCurrentView()) {
        setDeletingAssetId(null)
      }
    }
  }

  const handleUploadMedia = async (item: AssetItem, file: InputImageFile) => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    try {
      const media = mediaAssetFromImageFile(file)
      const updated = await updateAsset(
        callBackend,
        tab as AssetType,
        item.id,
        { media },
        scope,
        projectId
      )
      if (!records.isCurrentView()) return
      upsertAssetRow(updated)
      toast.success(`${meta.noun}图片已更新`)
    } catch (error) {
      if (!records.isCurrentView()) return
      toast.error(errMsg(error, `上传${meta.noun}图片失败`))
    }
  }

  const handleUploadReferenceMedia = async (
    item: AssetItem,
    file: InputImageFile
  ) => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    try {
      const referenceMedia = mediaAssetFromImageFile(file)
      const updated = await updateAsset(
        callBackend,
        tab as AssetType,
        item.id,
        { referenceMedia, referenceMediaRole: "reference" },
        scope,
        projectId
      )
      if (!records.isCurrentView()) return
      upsertAssetRow(updated)
      toast.success(`${meta.noun}参考图已更新`)
    } catch (error) {
      if (!records.isCurrentView()) return
      toast.error(errMsg(error, `上传${meta.noun}参考图失败`))
    }
  }

  const handleUploadVoiceReferenceAudio = async (
    item: AssetItem,
    file: InputImageFile
  ) => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      throw new Error("后端尚未就绪")
    }
    try {
      const voiceReferenceAudio = mediaAssetFromImageFile(file)
      const updated = await updateAsset(
        callBackend,
        tab as AssetType,
        item.id,
        { voiceReferenceAudio },
        scope,
        projectId
      )
      if (!records.isCurrentView()) return
      upsertAssetRow(updated)
      toast.success(`${meta.noun}参考音频已保存`)
    } catch (error) {
      if (!records.isCurrentView()) return
      toast.error(errMsg(error, `上传${meta.noun}参考音频失败`))
      throw error
    }
  }

  const handleSelectOriginalReference = async (item: AssetItem) => {
    if (!backendReady || !item.media) return
    try {
      const updated = await updateAsset(
        callBackend,
        tab as AssetType,
        item.id,
        { referenceMediaRole: "original" },
        scope,
        projectId
      )
      if (records.isCurrentView()) upsertAssetRow(updated)
    } catch (error) {
      if (records.isCurrentView()) toast.error(errMsg(error, "使用原图失败"))
    }
  }

  const handleClearReferenceMedia = async (item: AssetItem) => {
    if (!backendReady) return
    try {
      const updated = await updateAsset(
        callBackend,
        tab as AssetType,
        item.id,
        { referenceMedia: null },
        scope,
        projectId
      )
      if (records.isCurrentView()) upsertAssetRow(updated)
    } catch (error) {
      if (records.isCurrentView()) toast.error(errMsg(error, "移除参考图失败"))
    }
  }

  const checkGenerationReady = () => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return false
    }
    if (scope !== "project" || !projectId) {
      toast.error("请先进入具体项目后再生成设计图")
      return false
    }
    return records.isCurrentView()
  }

  const requestAssetMedia = async (
    item: AssetItem,
    headMode: AssetTurnaroundHeadMode = "default"
  ) => {
    const pending = generationRequestsRef.current
    const requestKey = `${projectId}:${tab}:${item.id}`
    if (pending.has(requestKey)) return false
    pending.add(requestKey)
    if (records.isCurrentView()) setAssetGenerating(item.id, true)
    let keepGenerating = false
    try {
      const result = await generateAssetMedia(
        callBackend,
        tab as AssetType,
        item.id,
        scope,
        projectId,
        tab === "characters" ? {
          hideTurnaroundHeads: headMode === "default"
            ? item.hideTurnaroundHeads === true
            : headMode === "without-heads",
        } : undefined
      )
      keepGenerating = Boolean(
        result.task &&
        (result.task.status === "running" || result.task.status === "created")
      )
      if (records.isCurrentView() && result.asset) upsertAssetRow(result.asset)
      return true
    } finally {
      pending.delete(requestKey)
      if (records.isCurrentView()) {
        if (!keepGenerating) setAssetGenerating(item.id, false)
      }
    }
  }

  const handleGenerateAssetMedia = async (item: AssetItem) => {
    if (!checkGenerationReady()) return
    try {
      if (await requestAssetMedia(item) && records.isCurrentView()) {
        toast.success(`${meta.noun}设计图生成任务已提交`)
      }
    } catch (error) {
      if (records.isCurrentView()) toast.error(errMsg(error, `生成${meta.noun}设计图失败`))
    }
  }

  const handleGenerateAllAssetMedia = async (headMode: AssetTurnaroundHeadMode = "default") => {
    if (bulkGenerationRef.current || savingHeadSettings || !checkGenerationReady()) return
    const items = [...new Map(pendingDesignRows.map((item) => [item.id, item])).values()]
    if (!items.length) {
      toast.info("当前列表没有待生成的设计图")
      return
    }
    const run = {}
    bulkGenerationRef.current = run
    setGeneratingAll(true)
    let nextIndex = 0
    let submitted = 0
    let failed = 0
    let firstError = ""
    const submitNext = async () => {
      while (nextIndex < items.length) {
        const item = items[nextIndex++]
        try {
          if (await requestAssetMedia(item, headMode)) submitted += 1
        } catch (error) {
          failed += 1
          if (!firstError) firstError = errMsg(error, "生成任务提交失败")
        }
      }
    }
    try {
      await Promise.all(Array.from({ length: Math.min(3, items.length) }, submitNext))
      if (!records.isCurrentView()) return
      if (failed) toast.error(`已提交 ${submitted} 张，${failed} 张提交失败：${firstError}`)
      else toast.success(`已提交 ${submitted} 张${meta.noun}设计图生成任务`)
    } finally {
      if (bulkGenerationRef.current === run) {
        bulkGenerationRef.current = null
        if (records.isCurrentView()) setGeneratingAll(false)
      }
    }
  }

  const handleSetTurnaroundHeads = async (item: AssetItem, showHeads: boolean) => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    if (scope !== "project" || tab !== "characters" || !projectId) return
    setSavingHeadSettings((current) => current + 1)
    try {
      const updated = await updateAsset(
        callBackend, "characters", item.id,
        { hideTurnaroundHeads: !showHeads }, scope, projectId
      )
      if (records.isCurrentView()) upsertAssetRow(updated)
    } catch (error) {
      if (records.isCurrentView()) toast.error(errMsg(error, "保存三视图头部设置失败"))
      throw error
    } finally {
      if (records.isCurrentView()) setSavingHeadSettings((current) => current - 1)
    }
  }

  const handleSetAssetLifecycle = async (
    item: AssetItem,
    status: AssetLifecycleView
  ) => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    if (scope !== "project" || !projectId) {
      toast.error("请先进入具体项目后再调整资产状态")
      return
    }
    setAssetLifecycleUpdating(item.id, true)
    try {
      const updated = await updateAsset(
        callBackend,
        tab as AssetType,
        item.id,
        { lifecycleStatus: status },
        scope,
        projectId
      )
      if (!records.isCurrentView()) return
      const updatedWithLifecycle = { ...updated, lifecycleStatus: status }
      upsertAssetRow(updatedWithLifecycle)
      if (status === "offline") {
        onAgentTargetChange?.(null)
      } else {
        publishAssetAgentTarget(updatedWithLifecycle, "focus")
      }
      toast.success(
        status === "offline"
          ? `${meta.noun}已移到下线组`
          : `${meta.noun}已恢复到活跃组`
      )
    } catch (error) {
      if (!records.isCurrentView()) return
      toast.error(
        errMsg(
          error,
          status === "offline" ? `下线${meta.noun}失败` : `恢复${meta.noun}失败`
        )
      )
    } finally {
      if (records.isCurrentView()) {
        setAssetLifecycleUpdating(item.id, false)
      }
    }
  }

  const handleUpdateAssetFields = async (
    item: AssetItem,
    patch: Partial<AssetEditPatch>
  ) => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    try {
      const nextPatch =
        scope === "global"
          ? {
              ...buildGlobalAssetPayload(tab, item, patch),
              referenceMedia: null,
              // Editing other fields must not overwrite audio with a stale
              // value from the card. Undefined preserves it; null removes it.
              voiceReferenceAudio: patch.voiceReferenceAudio,
            }
          : patch
      if (scope === "global") {
        const nextName = normalizeAssetNameKey(nextPatch.name ?? item.name)
        const duplicate = sourceRows.find(
          (row) =>
            row.id !== item.id && normalizeAssetNameKey(row.name) === nextName
        )
        if (duplicate) throw new Error(ASSET_NAME_DUPLICATE_MESSAGE)
      }
      const updated = await updateAsset(
        callBackend,
        tab as AssetType,
        item.id,
        nextPatch,
        scope,
        projectId
      )
      if (!records.isCurrentView()) return
      // The backend removes optional media fields when clearing them. Keep an
      // explicit null in the row update so the cache merge does not retain the
      // previous reference audio from the current row.
      const normalizedUpdated =
        patch.voiceReferenceAudio === null &&
        updated.voiceReferenceAudio == null
          ? { ...updated, voiceReferenceAudio: null }
          : updated
      upsertAssetRow(normalizedUpdated)
      toast.success(`${meta.noun}已保存`)
    } catch (error) {
      if (!records.isCurrentView()) return
      toast.error(errMsg(error, `保存${meta.noun}失败`))
      throw error
    }
  }

  const handleCopyToLibrary = (item: AssetItem) => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    if (scope !== "project") {
      toast.info("该资产已在全局资产")
      return
    }
    selectAsset(item)
    setDialog("copy")
  }

  const handleConfirmCopyToLibrary = async (
    item: AssetItem,
    patch: AssetEditPatch
  ) => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    if (scope !== "project") {
      toast.info("该资产已在全局资产")
      return
    }
    try {
      const payload = buildGlobalAssetPayload(tab, item, patch)
      if (!payload.media || !mediaPreviewSrc(payload.media)) {
        const message = `${meta.noun}设计图不存在，不能加入全局资产`
        toast.error(message)
        throw new AssetLibraryMissingMediaError(message)
      }
      const globalRows = await loadCachedAssetRows(callBackend, {
        scope: "global",
        assetType: tab,
      })
      if (!records.isCurrentView()) return
      const duplicate = globalRows.find(
        (existing) =>
          normalizeAssetNameKey(existing.name) ===
          normalizeAssetNameKey(payload.name)
      )
      if (duplicate && !patch.overwrite) {
        throw new AssetLibraryDuplicateError(duplicate)
      }
      if (duplicate && patch.overwrite) {
        const updated = await updateAsset(
          callBackend,
          tab as AssetType,
          duplicate.id,
          payload,
          "global"
        )
        if (!records.isCurrentView()) return
        upsertCachedAssetRows(
          { scope: "global", assetType: tab as AssetType },
          updated
        )
        toast.success(`已覆盖全局资产中的${meta.noun}`)
      } else {
        const created = await createAsset(
          callBackend,
          tab as AssetType,
          payload,
          "global"
        )
        if (!records.isCurrentView()) return
        upsertCachedAssetRows(
          { scope: "global", assetType: tab as AssetType },
          created
        )
        toast.success(`${meta.noun}已加入全局资产`)
      }
      setDialog(null)
      selectAsset(null)
    } catch (error) {
      if (!records.isCurrentView()) return
      if (
        !isAssetLibraryDuplicateError(error) &&
        !isAssetLibraryMissingMediaError(error)
      ) {
        toast.error(errMsg(error, `加入全局资产失败`))
      }
      throw error
    }
  }

  const handleUseMediaVersion = async (item: AssetItem, versionId: string) => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    try {
      const updated = await setActiveAssetMediaVersion(
        callBackend,
        tab as AssetType,
        item.id,
        versionId,
        scope,
        projectId
      )
      if (!records.isCurrentView()) return
      upsertAssetRow(updated)
      toast.success("已切换设计图版本")
    } catch (error) {
      if (!records.isCurrentView()) return
      toast.error(errMsg(error, "切换设计图版本失败"))
    }
  }

  const handleUpdateMediaVersionTag = async (
    item: AssetItem,
    versionId: string,
    stateTag: string
  ) => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    try {
      const updated = await updateAssetMediaVersion(
        callBackend,
        tab as AssetType,
        item.id,
        versionId,
        { stateTag: stateTag.trim() },
        scope,
        projectId
      )
      if (!records.isCurrentView()) return
      upsertAssetRow(updated)
      toast.success("版本标签已保存")
    } catch (error) {
      if (!records.isCurrentView()) return
      toast.error(errMsg(error, "保存版本标签失败"))
      throw error
    }
  }

  const handleDeleteMediaVersion = async (
    item: AssetItem,
    versionId: string
  ) => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    try {
      const updated = await deleteAssetMediaVersion(
        callBackend,
        tab as AssetType,
        item.id,
        versionId,
        scope,
        projectId
      )
      if (!records.isCurrentView()) return
      upsertAssetRow(updated)
      toast.success("设计图版本已删除")
    } catch (error) {
      if (!records.isCurrentView()) return
      toast.error(errMsg(error, "删除设计图版本失败"))
    }
  }
  useEffect(() => {
    setDialog(null)
    setDeleteTarget(null)
    setDeletingAssetId(null)
    setLifecycleUpdatingAssetIds(new Set())
    setGeneratingAll(false)
    setSavingHeadSettings(0)
    generationRequestsRef.current = new Set()
    bulkGenerationRef.current = null
  }, [records.isCurrentView])
  return {
    dialog,
    setDialog,
    deleteTarget,
    deletingAssetId,
    lifecycleUpdatingAssetIds,
    generatingAll,
    headSettingsSaving: savingHeadSettings > 0,
    pendingDesignCount: pendingDesignRows.length,
    setDeleteTarget,
    handleCreated,
    handleRequestDelete,
    handleConfirmDelete,
    handleUploadMedia,
    handleUploadReferenceMedia,
    handleUploadVoiceReferenceAudio,
    handleSelectOriginalReference,
    handleClearReferenceMedia,
    handleGenerateAssetMedia,
    handleGenerateAllAssetMedia,
    handleSetTurnaroundHeads,
    handleSetAssetLifecycle,
    handleUpdateAssetFields,
    handleCopyToLibrary,
    handleConfirmCopyToLibrary,
    handleUseMediaVersion,
    handleUpdateMediaVersionTag,
    handleDeleteMediaVersion,
  }
}
