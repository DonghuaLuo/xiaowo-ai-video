import { useCallback, useEffect, useRef } from "react"
import { AlertTriangle, Archive, Loader2, RefreshCcw } from "lucide-react"
import { type AgentTargetContext, type TaskRow } from "@/backend"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { useBackend } from "@/hooks/useBackend"
import type { AssetTab } from "@/navigation"
import { getAssetMeta, type AssetItem } from "@/features/asset-model"
import { ConfirmDialog } from "@/shared/confirm-dialog"
import { AssetDesignCard } from "./asset-gallery-cards"
import {
  AssetDetailDialog,
  AssetMediaVersionDialog,
} from "./asset-detail-dialogs"
import { AssetFormDialog, BulkAssetDialog, GenerateAllDesignsDialog } from "./asset-form-dialogs"
import { AssetGalleryToolbar } from "./asset-gallery-toolbar"
import { AssetLibraryPickerDialog } from "./asset-library-picker-dialog"
import { FavoriteStyleAssetGallery } from "./favorite-style-gallery"
import { useAssetGalleryRecords } from "./use-asset-gallery-records"
import { useAssetGalleryActions } from "./use-asset-gallery-actions"
export function AssetGalleryPage({
  tab,
  scope,
  projectId,
  projectVersion,
  agentRefreshToken,
  focusAssetId,
  focusToken,
  taskRows,
  onAgentTargetChange,
}: {
  tab: AssetTab
  scope: "global" | "project"
  projectId?: string
  projectVersion?: number
  agentRefreshToken?: number
  focusAssetId?: string
  focusToken?: number
  taskRows?: TaskRow[]
  onAgentTargetChange?: (target: AgentTargetContext | null) => void
}) {
  const backend = useBackend()
  const { backendReady } = backend
  const records = useAssetGalleryRecords({
    backend,
    tab,
    scope,
    projectId,
    projectVersion,
    agentRefreshToken,
    focusAssetId,
    taskRows,
  })
  const {
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
    changeLifecycleView,
    showMore,
    selectAsset,
    viewAssetVersions,
  } = records
  const meta = getAssetMeta(tab)

  const title = scope === "project" ? meta.projectTitle : meta.title

  const EmptyIcon = meta.icon

  const publishedDefaultAgentTargetKeyRef = useRef("")

  const publishedFocusAgentTargetKeyRef = useRef("")

  const publishCreateAgentTarget = useCallback(
    (intent: AgentTargetContext["intent"] = "focus") => {
      onAgentTargetChange?.({
        source: "asset_gallery",
        intent,
        section: tab,
        assetTab: tab,
        assetType: tab,
      })
    },
    [onAgentTargetChange, tab]
  )

  const publishAssetAgentTarget = useCallback(
    (
      item: AssetItem,
      intent: AgentTargetContext["intent"] = "focus",
      field?: string
    ) => {
      onAgentTargetChange?.({
        source: "asset_gallery",
        intent,
        section: tab,
        assetTab: tab,
        assetType: tab,
        assetId: item.id,
        assetName: item.name,
        cardTitle: item.name,
        field,
      })
    },
    [onAgentTargetChange, tab]
  )

  useEffect(() => {
    publishedDefaultAgentTargetKeyRef.current = ""
    publishedFocusAgentTargetKeyRef.current = ""
  }, [projectId, scope, tab])

  useEffect(() => {
    if (scope !== "project") return
    const key = `${projectId ?? ""}:${scope}:${tab}`
    if (publishedDefaultAgentTargetKeyRef.current === key) return
    publishedDefaultAgentTargetKeyRef.current = key
    if (focusAssetId) return
    publishCreateAgentTarget("focus")
  }, [focusAssetId, projectId, publishCreateAgentTarget, scope, tab])

  const emptyHint =
    scope === "project" && lifecycleView === "offline"
      ? `暂无下线${meta.noun}资产。`
      : scope === "project"
        ? meta.emptyHint
        : `还没有${meta.noun}资产，可在项目${meta.projectTitle}页把已生成设计图加入全局资产。`

  useEffect(() => {
    if (scope !== "project" || !focusAssetId) return
    const item = rows.find((row) => row.id === focusAssetId)
    if (!item) return
    const key = `${focusToken ?? ""}:${focusAssetId}:${item.name}`
    if (publishedFocusAgentTargetKeyRef.current === key) return
    publishedFocusAgentTargetKeyRef.current = key
    publishAssetAgentTarget(item, "focus")
  }, [focusAssetId, focusToken, publishAssetAgentTarget, rows, scope])

  const actions = useAssetGalleryActions({
    backend,
    tab,
    scope,
    projectId,
    records,
    publishAssetAgentTarget,
    onAgentTargetChange,
  })
  const {
    dialog,
    setDialog,
    deleteTarget,
    deletingAssetId,
    lifecycleUpdatingAssetIds,
    generatingAll,
    headSettingsSaving,
    pendingDesignCount,
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
  } = actions
  if (tab === "styles") {
    return <FavoriteStyleAssetGallery title={title} />
  }

  return (
    <div
      className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
      aria-busy={loading || refreshing}
    >
      <AssetGalleryToolbar
        title={title}
        count={rows.length}
        query={query}
        onQueryChange={setQuery}
        onAdd={() => {
          publishCreateAgentTarget("create")
          setDialog("create")
        }}
        onPick={() => setDialog("library")}
        onBulk={() => setDialog("bulk")}
        onGenerateAll={() => {
          if (tab === "characters") setDialog("generate-all")
          else void handleGenerateAllAssetMedia()
        }}
        generatingAll={generatingAll}
        canGenerateAll={backendReady && !loading && !refreshing && !headSettingsSaving && pendingDesignCount > 0}
        addLabel={meta.addLabel}
        scope={scope}
        lifecycleView={lifecycleView}
        onLifecycleViewChange={changeLifecycleView}
      />
      {loadError && remoteRows !== null ? (
        <div
          role="alert"
          className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-5 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
        >
          <AlertTriangle className="size-4 shrink-0" />
          <span className="min-w-0 flex-1 break-words">
            刷新资产失败：{loadError}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!backendReady}
            onClick={() => void loadAssetsForTab({ force: true })}
          >
            <RefreshCcw className="size-3.5" />
            重试
          </Button>
        </div>
      ) : refreshing ? (
        <div
          role="status"
          className="text-muted-foreground flex items-center gap-2 px-5 py-2 text-xs"
        >
          <Loader2 className="size-3.5 animate-spin" />
          正在更新资产...
        </div>
      ) : null}
      <ScrollArea className="min-h-0 flex-1">
        <div className="px-5 py-5">
          {loading ? (
            <div
              role="status"
              className="text-muted-foreground flex min-h-[280px] flex-col items-center justify-center gap-3 text-sm"
            >
              <Loader2 className="size-7 animate-spin text-indigo-600 dark:text-indigo-300" />
              <span>
                {backendReady
                  ? `正在加载${scope === "project" ? "项目" : "全局"}${meta.noun}资产...`
                  : "正在连接后端..."}
              </span>
            </div>
          ) : loadError && remoteRows === null ? (
            <div
              role="alert"
              className="flex min-h-[280px] flex-col items-center justify-center gap-3 p-8 text-center"
            >
              <AlertTriangle className="size-7 text-amber-600" />
              <p className="text-sm font-semibold">加载资产失败</p>
              <p className="text-muted-foreground max-w-xl text-sm break-words">
                {loadError}
              </p>
              <Button
                type="button"
                variant="outline"
                disabled={!backendReady}
                onClick={() => void loadAssetsForTab({ force: true })}
              >
                <RefreshCcw className="size-4" />
                重试
              </Button>
            </div>
          ) : sourceRows.length === 0 ? (
            scope === "project" && lifecycleView === "active" ? (
              <button
                type="button"
                className="flex min-h-[280px] w-full flex-col items-center justify-center rounded-xl border border-dashed border-gray-300/80 bg-white/45 p-8 text-center dark:border-white/15 dark:bg-white/[0.035]"
                onClick={() => {
                  publishCreateAgentTarget("create")
                  setDialog("create")
                }}
              >
                <EmptyIcon className="size-7 text-indigo-600 dark:text-indigo-300" />
                <span className="mt-3 text-sm font-semibold text-gray-950 dark:text-gray-50">
                  {emptyHint}
                </span>
              </button>
            ) : (
              <div className="flex min-h-[280px] w-full flex-col items-center justify-center rounded-xl border border-dashed border-gray-300/80 bg-white/45 p-8 text-center dark:border-white/15 dark:bg-white/[0.035]">
                {scope === "project" ? (
                  <Archive className="size-7 text-indigo-600 dark:text-indigo-300" />
                ) : (
                  <EmptyIcon className="size-7 text-indigo-600 dark:text-indigo-300" />
                )}
                <span className="mt-3 text-sm font-semibold text-gray-950 dark:text-gray-50">
                  {emptyHint}
                </span>
              </div>
            )
          ) : rows.length === 0 ? (
            <div className="rounded-xl border border-gray-200/70 bg-white/70 px-6 py-14 text-center text-[13px] text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
              没有匹配的{meta.noun}结果，请修改搜索词。
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid [grid-template-columns:repeat(auto-fill,344px)] justify-evenly gap-4">
                {visibleRows.map((item) => (
                  <AssetDesignCard
                    key={item.id}
                    item={item}
                    tab={tab}
                    scope={scope}
                    lifecycleView={lifecycleView}
                    onActivate={() => {
                      if (lifecycleView === "active")
                        publishAssetAgentTarget(item, "focus")
                    }}
                    onSetLifecycle={(status) => {
                      void handleSetAssetLifecycle(item, status)
                    }}
                    onDelete={() => {
                      if (lifecycleView === "active")
                        publishAssetAgentTarget(item, "delete")
                      handleRequestDelete(item)
                    }}
                    onUploadMedia={(file) => {
                      publishAssetAgentTarget(item, "update", "media")
                      void handleUploadMedia(item, file)
                    }}
                    onUploadReferenceMedia={(file) => {
                      publishAssetAgentTarget(item, "update", "referenceMedia")
                      return handleUploadReferenceMedia(item, file)
                    }}
                    onUploadVoiceReferenceAudio={(file) => {
                      publishAssetAgentTarget(item, "update", "voiceReferenceAudio")
                      return handleUploadVoiceReferenceAudio(item, file)
                    }}
                    onRemoveVoiceReferenceAudio={() => {
                      publishAssetAgentTarget(item, "update", "voiceReferenceAudio")
                      return handleUpdateAssetFields(item, { voiceReferenceAudio: null })
                    }}
                    callBackend={backend.callBackend}
                    onUseOriginalReference={() => handleSelectOriginalReference(item)}
                    onClearReferenceMedia={() => handleClearReferenceMedia(item)}
                    onGenerateMedia={() => {
                      publishAssetAgentTarget(item, "generate", "designImage")
                      void handleGenerateAssetMedia(item)
                    }}
                    onTurnaroundHeadsChange={(showHeads) => handleSetTurnaroundHeads(item, showHeads)}
                    generatingMedia={generatingAssetIds.has(item.id)}
                    onSave={(patch) => {
                      if (lifecycleView === "active")
                        publishAssetAgentTarget(item, "update", "designPrompt")
                      void handleUpdateAssetFields(item, patch).catch(() => {})
                    }}
                    onEdit={() => {
                      if (lifecycleView === "active")
                        publishAssetAgentTarget(item, "update")
                      selectAsset(item)
                      setDialog("detail")
                    }}
                    onCopyToLibrary={() => {
                      publishAssetAgentTarget(item, "update")
                      void handleCopyToLibrary(item)
                    }}
                    onOpenVersions={() => {
                      if (lifecycleView === "active")
                        publishAssetAgentTarget(item, "focus", "versions")
                      viewAssetVersions(item)
                    }}
                    updatingLifecycle={lifecycleUpdatingAssetIds.has(item.id)}
                    focusToken={
                      focusAssetId && item.id === focusAssetId
                        ? focusToken
                        : undefined
                    }
                  />
                ))}
              </div>
              {hasMoreRows ? (
                <div className="flex justify-center pt-1">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={showMore}
                  >
                    加载更多 {rows.length - visibleRows.length} 个
                  </Button>
                </div>
              ) : null}
            </div>
          )}
        </div>
      </ScrollArea>

      {scope === "project" && tab === "characters" && dialog === "generate-all" ? (
        <GenerateAllDesignsDialog
          count={pendingDesignCount}
          onClose={() => setDialog(null)}
          onGenerate={(mode) => {
            setDialog(null)
            void handleGenerateAllAssetMedia(mode)
          }}
        />
      ) : null}

      {scope === "project" && dialog === "create" ? (
        <AssetFormDialog
          tab={tab}
          scope={scope}
          projectId={projectId}
          existingRows={sourceRows}
          onClose={() => setDialog(null)}
          onCreated={handleCreated}
        />
      ) : null}
      {scope === "project" && dialog === "library" ? (
        <AssetLibraryPickerDialog
          tab={tab}
          projectId={projectId}
          existingRows={sourceRows}
          onImported={async () => {
            await loadAssetsForTab()
            if (!records.isCurrentView()) return
            setDialog(null)
          }}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {scope === "project" && dialog === "bulk" ? (
        <BulkAssetDialog
          tab={tab}
          rows={sourceRows}
          scope={scope}
          projectId={projectId}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {scope === "project" && dialog === "copy" && selectedAsset ? (
        <AssetDetailDialog
          tab={tab}
          item={selectedAsset}
          mode="copy"
          scope="global"
          onSave={(item, patch) => handleConfirmCopyToLibrary(item, patch)}
          onClose={() => {
            setDialog(null)
            selectAsset(null)
          }}
        />
      ) : null}
      {dialog === "detail" && selectedAsset ? (
        <AssetDetailDialog
          tab={tab}
          item={selectedAsset}
          mode="edit"
          scope={scope}
          onSave={(item, patch) => handleUpdateAssetFields(item, patch)}
          onClose={() => {
            setDialog(null)
            selectAsset(null)
          }}
        />
      ) : null}
      {scope === "project" && versionAsset ? (
        <AssetMediaVersionDialog
          tab={tab}
          item={versionAsset}
          onClose={() => viewAssetVersions(null)}
          onUse={(versionId) =>
            void handleUseMediaVersion(versionAsset, versionId)
          }
          onUpdateVersionTag={(versionId, stateTag) =>
            handleUpdateMediaVersionTag(versionAsset, versionId, stateTag)
          }
          onDelete={(versionId) =>
            void handleDeleteMediaVersion(versionAsset, versionId)
          }
        />
      ) : null}
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title={`删除${meta.noun}`}
        description={
          deleteTarget
            ? `确认删除「${deleteTarget.name}」？删除后会从当前${scope === "project" ? "项目" : "全局资产"}移除，并保留已有生成文件记录。`
            : undefined
        }
        confirmLabel="删除"
        loadingLabel="删除中"
        loading={Boolean(deletingAssetId)}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
