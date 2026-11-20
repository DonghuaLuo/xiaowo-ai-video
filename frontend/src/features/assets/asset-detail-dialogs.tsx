import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Pencil,
  Trash2,
  Upload,
} from "lucide-react"
import { type AssetMediaVersion, type MediaAsset } from "@/backend"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import type { AssetTab } from "@/navigation"
import {
  getAssetMeta,
  isAssetLibraryDuplicateError,
  isAssetLibraryMissingMediaError,
  type AssetEditPatch,
  type AssetItem,
} from "@/features/asset-model"
import { ConfirmDialog } from "@/shared/confirm-dialog"
import { ICON_GHOST_BTN_CLS } from "@/shared/button-styles"
import { pickLocalImageFile } from "@/shared/image-picker"
import { mediaAssetFromImageFile, mediaPreviewSrc } from "@/shared/media"
import { ReferenceAudioPlayer } from "@/shared/reference-audio-player"
import { ModalShell } from "@/shared/page-shell"
import { TooltipWrap } from "@/shared/tooltip-wrap"
import { FramedTextarea } from "@/shared/framed-fields"
import {
  UnifiedMediaFrame,
  mediaDownloadSource,
} from "@/shared/unified-media-frame"
import {
  AssetInlineMediaThumbnail,
  assetCanUseVoiceStyle,
  assetDesignPrompt,
  assetVersionDisplayTitle,
  assetVersionLabel,
  assetVersionPromptText,
  assetVoiceStyleLabel,
} from "./asset-gallery-cards"

export function AssetDetailDialog({
  tab,
  item,
  mode = "edit",
  scope = "project",
  onSave,
  onClose,
}: {
  tab: AssetTab
  item: AssetItem | null
  mode?: "edit" | "copy"
  scope?: "global" | "project"
  onSave: (item: AssetItem, patch: AssetEditPatch) => void | Promise<void>
  onClose: () => void
}) {
  const meta = getAssetMeta(tab)
  const [nameDraft, setNameDraft] = useState(item?.name ?? "")
  const [designPromptDraft, setDesignPromptDraft] = useState(
    item ? assetDesignPrompt(item) : ""
  )
  const [voiceStyleDraft, setVoiceStyleDraft] = useState(item?.voiceStyle ?? "")
  const [mediaDraft, setMediaDraft] = useState<MediaAsset | null>(
    item?.media ?? null
  )
  const [mediaChanged, setMediaChanged] = useState(false)
  const [conflictAsset, setConflictAsset] = useState<AssetItem | null>(null)
  const [missingMediaMessage, setMissingMediaMessage] = useState<string | null>(
    null
  )
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    setNameDraft(item?.name ?? "")
    setDesignPromptDraft(item ? assetDesignPrompt(item) : "")
    setVoiceStyleDraft(item?.voiceStyle ?? "")
    setMediaDraft(item?.media ?? null)
    setMediaChanged(false)
    setConflictAsset(null)
    setMissingMediaMessage(null)
  }, [item])
  const isCopyMode = mode === "copy"
  const isGlobalFields = scope === "global" || isCopyMode
  const showReference = !isGlobalFields
  const mediaSrc = mediaPreviewSrc(mediaDraft)
  const referenceSrc = showReference
    ? mediaPreviewSrc(item?.referenceMedia)
    : null
  const canUseVoiceStyle = assetCanUseVoiceStyle(tab)
  const voiceReferenceAudio = canUseVoiceStyle ? item?.voiceReferenceAudio : null
  const handlePickFile = async () => {
    const file = await pickLocalImageFile("上传设计图")
    if (!file) return
    setMediaDraft(mediaAssetFromImageFile(file))
    setMediaChanged(true)
    setConflictAsset(null)
    setMissingMediaMessage(null)
  }
  const handleSave = async (overwrite = false) => {
    if (!item) return
    if (!nameDraft.trim()) {
      toast.error(`${meta.noun}名称不能为空`)
      return
    }
    setSaving(true)
    setMissingMediaMessage(null)
    try {
      await onSave(item, {
        name: nameDraft.trim() || item.name,
        desc: designPromptDraft.trim(),
        tag: item.tag,
        canSpeak:
          tab === "creatures" ? Boolean(voiceStyleDraft.trim()) : undefined,
        prompts: {
          ...(item.prompts ?? {}),
          assetImagePrompt: designPromptDraft.trim(),
        },
        voiceStyle: canUseVoiceStyle ? voiceStyleDraft.trim() : undefined,
        media: mediaChanged ? mediaDraft : undefined,
        referenceMedia: isGlobalFields ? null : undefined,
        ...(isCopyMode && voiceReferenceAudio
          ? { voiceReferenceAudio }
          : {}),
        overwrite,
      })
      onClose()
    } catch (error) {
      if (isAssetLibraryDuplicateError(error)) {
        setConflictAsset(error.asset)
      } else if (isAssetLibraryMissingMediaError(error)) {
        setMissingMediaMessage(error.message)
      }
      // Save handlers surface their own toast and keep the dialog open.
    } finally {
      setSaving(false)
    }
  }
  return (
    <ModalShell
      title={isCopyMode ? `加入全局资产` : `编辑${meta.noun}`}
      description={
        isCopyMode
          ? `确认${meta.noun}设计图和展示文案后，再加入全局资产。`
          : `修改${meta.noun}最终展示数据。`
      }
      onClose={onClose}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            取消
          </Button>
          {isCopyMode && conflictAsset ? (
            <Button
              variant="outline"
              className="border-amber-200 bg-amber-50 text-amber-700 hover:border-amber-300 hover:bg-amber-100 hover:text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-200 dark:hover:bg-amber-950/40"
              onClick={() => void handleSave(true)}
              disabled={!item || saving}
            >
              覆盖已有
            </Button>
          ) : null}
          <Button onClick={() => void handleSave()} disabled={!item || saving}>
            {saving ? "保存中" : isCopyMode ? "确认加入" : "保存"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {isCopyMode && conflictAsset ? (
          <div className="flex items-start gap-2 rounded-lg border border-amber-200/80 bg-amber-50/80 px-3 py-2.5 text-xs leading-relaxed text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-200">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <span>
              {`全局资产里已有同名${meta.noun}「${conflictAsset.name}」。你可以改名后确认加入，或点击“覆盖已有”。`}
              {conflictAsset.voiceReferenceAudio && !voiceReferenceAudio
                ? "未携带参考音频时，将保留全局资产已有的音频。"
                : ""}
            </span>
          </div>
        ) : null}
        {isCopyMode && missingMediaMessage ? (
          <div className="flex items-start gap-2 rounded-lg border border-rose-200/80 bg-rose-50/85 px-3 py-2.5 text-xs leading-relaxed text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <span>{missingMediaMessage}</span>
          </div>
        ) : null}
        <div className="grid gap-5 md:grid-cols-[260px_minmax(0,1fr)]">
          <div className="space-y-3">
            <UnifiedMediaFrame
              src={mediaSrc}
              alt={item ? `${item.name}${meta.noun}图` : `${meta.noun}图`}
              title={item?.name ?? meta.noun}
              className="aspect-video"
              interactive={Boolean(mediaSrc)}
              showActions={Boolean(mediaSrc)}
              downloadSource={mediaDownloadSource(mediaDraft)}
              fallbackClassName={item?.accent}
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 w-full gap-1.5 text-xs"
              onClick={() => void handlePickFile()}
            >
              <Upload className="size-3.5" />
              {mediaDraft ? "替换设计图" : "上传设计图"}
            </Button>
            {showReference ? (
              <UnifiedMediaFrame
                src={referenceSrc}
                alt={item ? `${item.name}参考图` : `${meta.noun}参考图`}
                title={item ? `${item.name}参考图` : `${meta.noun}参考图`}
                className="aspect-square"
                downloadSource={mediaDownloadSource(item?.referenceMedia)}
              />
            ) : null}
          </div>
          <div className="space-y-3">
            <Input
              value={nameDraft}
              onChange={(event) => {
                setNameDraft(event.target.value)
                setConflictAsset(null)
                setMissingMediaMessage(null)
              }}
              className="h-9 bg-white/70"
              placeholder={`${meta.noun}名称`}
            />
            <FramedTextarea
              value={designPromptDraft}
              onChange={(event) => setDesignPromptDraft(event.target.value)}
              containerClassName="min-h-[130px] rounded-xl"
              className="min-h-[126px] resize-y"
              placeholder={`${meta.noun}设计图提示词`}
            />
            {canUseVoiceStyle ? (
              <div>
                <div className="mb-1.5 flex items-center justify-between gap-2 text-[11px] text-gray-500">
                  <span>{assetVoiceStyleLabel(tab)} / 音色提示</span>
                </div>
                <FramedTextarea
                  value={voiceStyleDraft}
                  onChange={(event) => setVoiceStyleDraft(event.target.value)}
                  placeholder={`${assetVoiceStyleLabel(tab)} / 音色提示`}
                  containerClassName="min-h-[96px] rounded-xl"
                  className="min-h-[92px] resize-y"
                />
                {voiceReferenceAudio ? (
                  <div className="mt-3 space-y-1.5">
                    <div className="text-[11px] text-gray-500 dark:text-gray-400">
                      参考音频
                    </div>
                    <ReferenceAudioPlayer
                      src={mediaPreviewSrc(voiceReferenceAudio) ?? undefined}
                      className="w-full"
                    />
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </ModalShell>
  )
}

export function AssetMediaVersionDialog({
  tab,
  item,
  onUse,
  onUpdateVersionTag,
  onDelete,
  onClose,
}: {
  tab: AssetTab
  item: AssetItem
  onUse: (versionId: string) => void | Promise<void>
  onUpdateVersionTag: (
    versionId: string,
    stateTag: string
  ) => void | Promise<void>
  onDelete: (versionId: string) => void | Promise<void>
  onClose: () => void
}) {
  const meta = getAssetMeta(tab)
  const versions = useMemo(() => {
    const source =
      item.mediaVersions && item.mediaVersions.length
        ? item.mediaVersions
        : item.media
          ? [
              {
                id: item.activeMediaVersionId ?? item.media.id ?? "current",
                title: "当前设计图",
                createdAt: "当前",
                status: "ready",
                media: item.media,
                voiceStyle: item.voiceStyle,
                canSpeak: item.canSpeak,
              },
            ]
          : []
    return [...source].reverse()
  }, [
    item.activeMediaVersionId,
    item.canSpeak,
    item.media,
    item.mediaVersions,
    item.voiceStyle,
  ])
  const [usingVersionId, setUsingVersionId] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<AssetMediaVersion | null>(
    null
  )
  const [deletingVersionId, setDeletingVersionId] = useState<string | null>(
    null
  )
  const [editingTagVersionId, setEditingTagVersionId] = useState<string | null>(
    null
  )
  const [versionStateTagDraft, setVersionStateTagDraft] = useState("")
  const editingTagRef = useRef({
    versionId: "",
    draft: "",
    original: "",
  })
  const [savingTagVersionId, setSavingTagVersionId] = useState<string | null>(
    null
  )
  const activeId = item.activeMediaVersionId ?? null
  const handleUseVersion = async (versionId: string) => {
    setUsingVersionId(versionId)
    try {
      await onUse(versionId)
    } finally {
      setUsingVersionId(null)
    }
  }
  const handleConfirmDeleteVersion = async () => {
    if (!deleteTarget) return
    setDeletingVersionId(deleteTarget.id)
    try {
      await onDelete(deleteTarget.id)
      setDeleteTarget(null)
    } finally {
      setDeletingVersionId(null)
    }
  }
  const handleEditVersionTag = (versionId: string, currentStateTag: string) => {
    setEditingTagVersionId(versionId)
    setVersionStateTagDraft(currentStateTag)
    editingTagRef.current = {
      versionId,
      draft: currentStateTag,
      original: currentStateTag,
    }
  }
  const handleVersionTagDraftChange = (value: string) => {
    editingTagRef.current = {
      ...editingTagRef.current,
      draft: value,
    }
    setVersionStateTagDraft(value)
  }
  const takePendingVersionTagCommit = () => {
    const versionId =
      editingTagRef.current.versionId || editingTagVersionId || ""
    if (!versionId) return null
    const draft =
      editingTagRef.current.versionId === versionId
        ? editingTagRef.current.draft
        : versionStateTagDraft
    const original =
      editingTagRef.current.versionId === versionId
        ? editingTagRef.current.original
        : ""
    editingTagRef.current = { versionId: "", draft: "", original: "" }
    setEditingTagVersionId(null)
    setVersionStateTagDraft("")
    const stateTag = draft.trim()
    return stateTag === original.trim() ? null : { versionId, stateTag }
  }
  const handleCommitVersionTag = async () => {
    const pending = takePendingVersionTagCommit()
    if (!pending) return
    setSavingTagVersionId(pending.versionId)
    try {
      await onUpdateVersionTag(pending.versionId, pending.stateTag)
    } catch {
      // Parent handler already shows the failure toast.
    } finally {
      setSavingTagVersionId(null)
    }
  }
  const handleDialogClose = () => {
    const pending = takePendingVersionTagCommit()
    if (pending) {
      void Promise.resolve(
        onUpdateVersionTag(pending.versionId, pending.stateTag)
      ).catch(() => undefined)
    }
    onClose()
  }
  return (
    <ModalShell
      title={`${item.name}${meta.noun}设计图版本`}
      description={`当前使用 ${activeId ? "已激活版本" : "暂无激活版本"}；切换后所有引用该${meta.noun}资产的分镜会自动读取新的当前设计图。`}
      className="max-w-[min(880px,calc(100vw-1.5rem))]"
      bodyClassName="p-4 sm:p-5"
      onClose={handleDialogClose}
      footer={
        <Button variant="outline" onClick={handleDialogClose}>
          关闭
        </Button>
      }
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[11px] text-gray-500 dark:text-gray-400">
            点击缩略图可预览，点击切换版本才会设为当前版本。
          </p>
          <Badge variant="outline" className="rounded-full text-[10px]">
            {versions.length} 个版本
          </Badge>
        </div>
        <div className="max-h-[min(58dvh,560px)] [scrollbar-gutter:stable] overflow-y-auto pr-1">
          <div className="space-y-2">
            {versions.length === 0 ? (
              <div className="rounded-lg border border-dashed border-gray-300/80 px-4 py-10 text-center text-sm text-gray-400 dark:border-white/15">
                暂无设计图版本，上传或生成后会自动记录。
              </div>
            ) : (
              versions.map((version, index) => {
                const active = version.id === activeId
                const versionMediaSrc = mediaPreviewSrc(version.media)
                const versionLabel = assetVersionLabel(
                  version,
                  index,
                  versions.length
                )
                const promptText = assetVersionPromptText(item, version)
                const voiceStyleText =
                  version.voiceStyle ?? item.voiceStyle ?? ""
                const versionStateTag = (
                  version.stateTag ?? version.stateTags?.[0] ?? ""
                ).trim()
                const editingStateTag = editingTagVersionId === version.id
                const savingStateTag = savingTagVersionId === version.id
                const versionTagEditDisabled =
                  usingVersionId !== null ||
                  deletingVersionId !== null ||
                  savingTagVersionId !== null
                return (
                  <article
                    key={version.id}
                    className={cn(
                      "rounded-lg border p-3 transition-colors",
                      active
                        ? "border-emerald-200 bg-emerald-50/70 dark:border-emerald-900/60 dark:bg-emerald-950/20"
                        : "border-gray-200/70 bg-white/70 dark:border-white/10 dark:bg-white/[0.035]"
                    )}
                  >
                    <div className="flex items-stretch gap-3 sm:gap-4">
                      <AssetInlineMediaThumbnail
                        src={versionMediaSrc}
                        alt={`${item.name}${meta.noun} ${versionLabel}`}
                        title={assetVersionDisplayTitle(item, meta.noun)}
                        media={version.media}
                        fallbackClassName={item.accent}
                        className="w-36 shrink-0 sm:w-44"
                      />
                      <div className="relative flex min-w-0 flex-1 flex-col">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Badge className="rounded-full bg-indigo-600 text-[10px] text-white">
                            {versionLabel}
                          </Badge>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            className={cn(
                              "h-7 min-w-[52px] rounded-full border px-2.5 text-[11px] font-medium shadow-none transition-colors",
                              active
                                ? "border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-50 disabled:opacity-100 dark:border-emerald-400/30 dark:bg-emerald-400/10 dark:text-emerald-200 dark:hover:bg-emerald-400/10"
                                : "border-indigo-200 bg-white text-indigo-700 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-800 disabled:opacity-55 dark:border-indigo-400/25 dark:bg-indigo-400/10 dark:text-indigo-200 dark:hover:border-indigo-300/45 dark:hover:bg-indigo-400/15 dark:hover:text-indigo-100",
                              usingVersionId === version.id &&
                                "border-indigo-300 bg-indigo-50 text-indigo-800 dark:border-indigo-300/45 dark:bg-indigo-400/15 dark:text-indigo-100"
                            )}
                            disabled={
                              active ||
                              usingVersionId !== null ||
                              deletingVersionId !== null ||
                              savingTagVersionId !== null
                            }
                            onClick={(event) => {
                              event.stopPropagation()
                              void handleUseVersion(version.id)
                            }}
                          >
                            {usingVersionId === version.id ? (
                              <Loader2 className="size-3 animate-spin" />
                            ) : active ? (
                              <CheckCircle2 className="size-3" />
                            ) : null}
                            {active
                              ? "当前"
                              : usingVersionId === version.id
                                ? "切换中"
                                : "切换"}
                          </Button>
                          <div className="min-w-[160px] flex-1 px-1">
                            {editingStateTag ? (
                              <div className="flex min-w-0 items-center">
                                <input
                                  value={versionStateTagDraft}
                                  onChange={(event) =>
                                    handleVersionTagDraftChange(
                                      event.target.value
                                    )
                                  }
                                  onBlur={() => void handleCommitVersionTag()}
                                  onKeyDown={(event) => {
                                    if (
                                      event.key === "Enter" ||
                                      event.key === "Escape"
                                    ) {
                                      event.preventDefault()
                                      event.currentTarget.blur()
                                    }
                                  }}
                                  className="h-7 min-w-0 flex-1 border-0 bg-transparent px-0 text-xs text-gray-700 shadow-none outline-none placeholder:text-gray-400 focus:border-0 focus:ring-0 dark:bg-transparent dark:text-gray-200 dark:placeholder:text-gray-500"
                                  placeholder="状态标签，用于模型选择版本图"
                                  disabled={savingStateTag}
                                  autoFocus
                                />
                              </div>
                            ) : (
                              <div
                                className="flex min-w-0 cursor-text items-center gap-1 text-xs leading-7 text-gray-500 dark:text-gray-400"
                                onClick={() => {
                                  if (versionTagEditDisabled) return
                                  handleEditVersionTag(
                                    version.id,
                                    versionStateTag
                                  )
                                }}
                              >
                                <span className="min-w-0 truncate">
                                  {versionStateTag
                                    ? `状态标签：${versionStateTag}`
                                    : "未设置状态标签"}
                                </span>
                                <Button
                                  type="button"
                                  size="icon-sm"
                                  variant="ghost"
                                  aria-label="编辑状态标签"
                                  className={cn(ICON_GHOST_BTN_CLS, "size-7")}
                                  disabled={versionTagEditDisabled}
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    handleEditVersionTag(
                                      version.id,
                                      versionStateTag
                                    )
                                  }}
                                >
                                  <Pencil className="size-3.5" />
                                </Button>
                              </div>
                            )}
                          </div>
                          <div className="ml-auto flex shrink-0 items-center gap-1.5">
                            <span className="text-[11px] text-gray-400 dark:text-gray-500">
                              {version.createdAt ?? "未知时间"}
                            </span>
                          </div>
                        </div>
                        <div className="mt-2 min-w-0 pr-10">
                          <div className="line-clamp-2 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                            提示词：{promptText}
                          </div>
                          {assetCanUseVoiceStyle(tab) && voiceStyleText ? (
                            <div className="mt-1 line-clamp-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                              {assetVoiceStyleLabel(tab)}：{voiceStyleText}
                            </div>
                          ) : null}
                        </div>
                        <div className="absolute right-0 bottom-0">
                          <TooltipWrap
                            content={
                              active
                                ? "当前版本不能删除"
                                : versions.length <= 1
                                  ? "至少保留一个版本"
                                  : "删除版本"
                            }
                          >
                            <Button
                              type="button"
                              size="icon-sm"
                              variant="ghost"
                              aria-label="删除版本"
                              className={cn(
                                "size-8 rounded-full text-rose-600 hover:bg-rose-50 hover:text-rose-700 dark:text-rose-300 dark:hover:bg-rose-950/30 dark:hover:text-rose-200",
                                active || versions.length <= 1
                                  ? "text-gray-400 hover:bg-transparent hover:text-gray-400 disabled:opacity-60 dark:text-gray-500 dark:hover:text-gray-500"
                                  : ""
                              )}
                              disabled={
                                active ||
                                versions.length <= 1 ||
                                usingVersionId !== null ||
                                deletingVersionId !== null ||
                                savingTagVersionId !== null
                              }
                              onClick={(event) => {
                                event.stopPropagation()
                                setDeleteTarget(version)
                              }}
                            >
                              {deletingVersionId === version.id ? (
                                <Loader2 className="size-4 animate-spin" />
                              ) : (
                                <Trash2 className="size-4" />
                              )}
                            </Button>
                          </TooltipWrap>
                        </div>
                      </div>
                    </div>
                  </article>
                )
              })
            )}
          </div>
        </div>
      </div>
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="删除设计图版本"
        description={
          deleteTarget
            ? `确认删除 ${assetVersionDisplayTitle(item, meta.noun)} 的这个版本？当前版本和最后一个版本会被保护。`
            : undefined
        }
        confirmLabel="删除版本"
        loadingLabel="删除中"
        loading={Boolean(deletingVersionId)}
        onConfirm={handleConfirmDeleteVersion}
        onCancel={() => setDeleteTarget(null)}
      />
    </ModalShell>
  )
}
