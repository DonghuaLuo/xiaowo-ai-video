import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
} from "react"
import type { AssetMediaVersion, BackendCaller, InputImageFile, MediaAsset } from "@/backend"
import type { AssetTab } from "@/navigation"
import type { StyleTemplateOption } from "@/features/styles/types"
import { AssetItem, AssetEditPatch, getAssetMeta } from "@/features/asset-model"
import { resolveStyleTemplateThumbnailUrl } from "@/utils/style-thumbnails"
import { cn } from "@/lib/utils"
import {
  UnifiedMediaFrame,
  mediaDownloadSource,
} from "@/shared/unified-media-frame"
import { TooltipWrap } from "@/shared/tooltip-wrap"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu"
import {
  AlertTriangle,
  Archive,
  FolderPlus,
  History,
  ImagePlus,
  Loader2,
  MoreVertical,
  Pencil,
  RefreshCcw,
  Save,
  Trash2,
  Upload,
  WandSparkles,
} from "lucide-react"
import { mediaPreviewSrc } from "@/shared/media"
import { pickLocalImageFile, pickLocalMediaFile } from "@/shared/image-picker"
import { ReferenceAudioCropDialog } from "@/shared/reference-audio-crop-dialog"
import { ReferenceAudioPlayer } from "@/shared/reference-audio-player"
import { ICON_GHOST_BTN_CLS } from "@/shared/button-styles"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { FramedTextBlock, FramedTextarea } from "@/shared/framed-fields"

export type AssetLifecycleView = "active" | "offline"
export type AssetCardMenuAction = {
  key: string
  title: string
  ToolIcon: ComponentType<{ className?: string }>
  disabled?: boolean
  destructive?: boolean
  separatorBefore?: boolean
  onSelect: () => void
}

export function FavoriteStyleAssetCard({
  template,
  onEdit,
  onDelete,
}: {
  template: StyleTemplateOption
  onEdit: () => void
  onDelete: () => void
}) {
  const [thumbnailSrc, setThumbnailSrc] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    void (async () => {
      const src = await resolveStyleTemplateThumbnailUrl(template)
      if (!cancelled) setThumbnailSrc(src)
    })()
    return () => {
      cancelled = true
    }
  }, [
    template.thumbnailFile,
    template.thumbnailUrl,
    template.thumbnail_file,
    template.thumbnailPath,
    template.thumbnail_path,
    template.filePath,
    template.file_path,
    template.path,
    template.relativePath,
    template.relative_path,
    template.source,
  ])

  return (
    <article className="relative flex h-full min-h-[420px] flex-col overflow-hidden rounded-md border border-white/60 bg-white/70 shadow-sm dark:border-white/10 dark:bg-white/[0.055]">
      <div
        className={cn(
          "relative h-56 overflow-hidden bg-gradient-to-br",
          template.accent
        )}
      >
        {thumbnailSrc ? (
          <UnifiedMediaFrame
            src={thumbnailSrc}
            alt={template.name}
            title={template.name}
            className="absolute inset-0 rounded-none border-0"
            interactive={Boolean(thumbnailSrc)}
            showActions={Boolean(thumbnailSrc)}
          />
        ) : (
          <div className="absolute inset-x-4 bottom-4 grid grid-cols-3 gap-2">
            {Array.from({ length: 6 }).map((_, index) => (
              <div
                key={index}
                className="aspect-[4/3] rounded-md border border-white/45 bg-white/25 backdrop-blur-sm"
              />
            ))}
          </div>
        )}
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-black/20" />
        <div className="absolute top-2 right-2 z-10 flex gap-1">
          <TooltipWrap content="编辑收藏风格">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="size-7 bg-black/45 text-white backdrop-blur-sm hover:bg-black/60 hover:text-white"
              aria-label="编辑收藏风格"
              onClick={onEdit}
            >
              <Pencil className="size-3.5" />
            </Button>
          </TooltipWrap>
          <TooltipWrap content="删除收藏风格">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="size-7 bg-black/45 text-white backdrop-blur-sm hover:bg-black/60 hover:text-white"
              aria-label="删除收藏风格"
              onClick={onDelete}
            >
              <Trash2 className="size-3.5" />
            </Button>
          </TooltipWrap>
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col p-4">
        <h3 className="truncate text-[16px] font-semibold text-gray-950 dark:text-gray-50">
          {template.name}
        </h3>
        <div className="mt-3 flex min-h-0 flex-1 flex-col rounded-lg border border-gray-200/70 bg-white/70 p-3 dark:border-white/10 dark:bg-white/[0.035]">
          <div className="mb-1 shrink-0 text-[10px] font-semibold tracking-[0.12em] text-gray-400 uppercase">
            提示词
          </div>
          <p className="line-clamp-7 text-xs leading-relaxed text-gray-600 dark:text-gray-300">
            {template.prompt || "未设置提示词"}
          </p>
        </div>
      </div>
    </article>
  )
}

export function CapsLabel({
  children,
  htmlFor,
}: {
  children: ReactNode
  htmlFor?: string
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="text-[10px] font-semibold tracking-[0.12em] uppercase"
      style={{ color: "var(--color-text-4)" }}
    >
      {children}
    </label>
  )
}

export const ASSET_IMAGE_PROMPT_KEYS = [
  "assetImagePrompt",
  "asset_image_prompt",
  "designPrompt",
  "design_prompt",
  "imagePrompt",
  "image_prompt",
  "image",
  "visualPrompt",
  "visual_prompt",
  "closeupPrompt",
  "closeup_prompt",
  "prompt",
]

export function assetTextFromRecord(
  source: Record<string, unknown> | undefined,
  keys: string[]
) {
  if (!source) return ""
  for (const key of keys) {
    const value = source[key]
    if (typeof value === "string" && value.trim()) return value.trim()
    if (typeof value === "number" || typeof value === "boolean") {
      return String(value)
    }
  }
  return ""
}

export function assetDesignPrompt(item: AssetItem) {
  return (
    assetTextFromRecord(item.prompts, ASSET_IMAGE_PROMPT_KEYS) ||
    assetTextFromRecord(
      item as unknown as Record<string, unknown>,
      ASSET_IMAGE_PROMPT_KEYS
    )
  )
}

export function assetCanUseVoiceStyle(tab: AssetTab) {
  return tab === "characters" || tab === "creatures"
}

export function assetVoiceStyleLabel(tab: AssetTab) {
  return tab === "creatures" ? "生物语气" : "角色语气"
}

export function assetVersionLabel(
  version: AssetMediaVersion,
  index: number,
  count: number
) {
  const titledVersion = String(version.title || "").match(/^v\d+/i)?.[0]
  return titledVersion || `v${count - index}`
}

export function assetVersionPromptText(
  item: AssetItem,
  version?: AssetMediaVersion
) {
  const versionPrompts = version?.prompts
  const versionPrompt =
    versionPrompts && typeof versionPrompts === "object"
      ? assetTextFromRecord(versionPrompts, ASSET_IMAGE_PROMPT_KEYS)
      : ""
  return (
    versionPrompt ||
    version?.desc ||
    assetDesignPrompt(item) ||
    item.desc ||
    "暂无描述提示词"
  )
}

export const ASSET_PICKER_BATCH_SIZE = 72

export function assetVersionDisplayTitle(item: AssetItem, noun: string) {
  return `${item.name}${noun}设计图`
}

export function AssetInlineMediaThumbnail({
  src,
  alt,
  title,
  media,
  fallbackClassName,
  className,
}: {
  src?: string | null
  alt: string
  title: string
  media?: MediaAsset | null
  fallbackClassName?: string
  className?: string
}) {
  return (
    <UnifiedMediaFrame
      src={src}
      alt={alt}
      title={title}
      className={cn(
        src
          ? "h-auto self-stretch rounded-md !border-0 !bg-transparent [&_img]:rounded-md [&_video]:rounded-md"
          : "aspect-video rounded-md",
        className
      )}
      fit="cover"
      interactive={Boolean(src)}
      showActions={Boolean(src)}
      downloadSource={mediaDownloadSource(media)}
      fallbackClassName={fallbackClassName}
      fallbackMinHeight={false}
    />
  )
}

export function AssetCardDropdownMenuItems({
  actions,
}: {
  actions: AssetCardMenuAction[]
}) {
  return (
    <>
      {actions.map((action) => {
        const ToolIcon = action.ToolIcon
        return (
          <Fragment key={action.key}>
            {action.separatorBefore ? <DropdownMenuSeparator /> : null}
            <DropdownMenuItem
              disabled={action.disabled}
              variant={action.destructive ? "destructive" : "default"}
              onSelect={action.onSelect}
            >
              <ToolIcon className="size-4" />
              {action.title}
            </DropdownMenuItem>
          </Fragment>
        )
      })}
    </>
  )
}

export function AssetCardContextMenuItems({
  actions,
}: {
  actions: AssetCardMenuAction[]
}) {
  return (
    <>
      {actions.map((action) => {
        const ToolIcon = action.ToolIcon
        return (
          <Fragment key={action.key}>
            {action.separatorBefore ? <ContextMenuSeparator /> : null}
            <ContextMenuItem
              disabled={action.disabled}
              variant={action.destructive ? "destructive" : "default"}
              onSelect={action.onSelect}
            >
              <ToolIcon className="size-4" />
              {action.title}
            </ContextMenuItem>
          </Fragment>
        )
      })}
    </>
  )
}

export function AssetDesignCard({
  item,
  tab,
  scope,
  lifecycleView,
  onActivate,
  onSetLifecycle,
  onDelete,
  onUploadMedia,
  onUploadReferenceMedia,
  onUploadVoiceReferenceAudio,
  onRemoveVoiceReferenceAudio,
  callBackend,
  onUseOriginalReference,
  onClearReferenceMedia,
  onGenerateMedia,
  onTurnaroundHeadsChange,
  generatingMedia,
  onSave,
  onEdit,
  onCopyToLibrary,
  onOpenVersions,
  updatingLifecycle,
  focusToken,
}: {
  item: AssetItem
  tab: AssetTab
  scope: "global" | "project"
  lifecycleView: AssetLifecycleView
  onActivate: () => void
  onSetLifecycle: (status: AssetLifecycleView) => void
  onDelete: () => void
  onUploadMedia: (file: InputImageFile) => void
  onUploadReferenceMedia: (file: InputImageFile) => Promise<void>
  onUploadVoiceReferenceAudio: (file: InputImageFile) => Promise<void>
  onRemoveVoiceReferenceAudio: () => Promise<void>
  callBackend: BackendCaller
  onUseOriginalReference: () => Promise<void>
  onClearReferenceMedia: () => Promise<void>
  onGenerateMedia: () => void
  onTurnaroundHeadsChange: (showHeads: boolean) => Promise<void>
  generatingMedia?: boolean
  onSave: (patch: AssetEditPatch) => void
  onEdit: () => void
  onCopyToLibrary: () => void
  onOpenVersions: () => void
  updatingLifecycle?: boolean
  focusToken?: number
}) {
  const meta = getAssetMeta(tab)
  const Icon = meta.icon
  const isProjectScope = scope === "project"
  const canEditAssetMedia = isProjectScope && lifecycleView === "active"
  const mediaSrc = mediaPreviewSrc(item.media)
  const rawReferenceSrc = mediaPreviewSrc(item.referenceMedia)
  const [referenceUpdating, setReferenceUpdating] = useState(false)
  const [headSettingsUpdating, setHeadSettingsUpdating] = useState(false)
  const [voiceReferenceAudioCropOpen, setVoiceReferenceAudioCropOpen] = useState(false)
  const [voiceReferenceAudioCropSource, setVoiceReferenceAudioCropSource] = useState<InputImageFile | null>(null)
  const referenceBusy = referenceUpdating || Boolean(generatingMedia)
  const showReferenceSection =
    isProjectScope && (lifecycleView === "active" || Boolean(rawReferenceSrc))
  const referenceSrc = showReferenceSection ? rawReferenceSrc : null
  const canUseVoiceStyle = assetCanUseVoiceStyle(tab)
  const canEditVoiceReferenceAudio =
    canUseVoiceStyle && (!isProjectScope || lifecycleView === "active")
  const voiceReferenceAudioSrc = mediaPreviewSrc(item.voiceReferenceAudio)
  const [voiceStyleDraft, setVoiceStyleDraft] = useState(item.voiceStyle ?? "")
  const designPrompt = assetDesignPrompt(item)
  const [designPromptDraft, setDesignPromptDraft] = useState(designPrompt)
  const cardRef = useRef<HTMLElement | null>(null)
  const [activeFocusToken, setActiveFocusToken] = useState<number | null>(null)
  useEffect(() => {
    setVoiceStyleDraft(item.voiceStyle ?? "")
    setDesignPromptDraft(designPrompt)
  }, [designPrompt, item.voiceStyle])
  useEffect(() => {
    if (!focusToken) return
    setActiveFocusToken(focusToken)
    window.setTimeout(() => {
      cardRef.current?.scrollIntoView({ behavior: "smooth", block: "center" })
    }, 30)
    const timer = window.setTimeout(() => {
      setActiveFocusToken((current) =>
        current === focusToken ? null : current
      )
    }, 2600)
    return () => window.clearTimeout(timer)
  }, [focusToken])
  const resetDraft = () => {
    setVoiceStyleDraft(item.voiceStyle ?? "")
    setDesignPromptDraft(designPrompt)
  }
  const dirty =
    isProjectScope &&
    (designPromptDraft !== designPrompt ||
      (canUseVoiceStyle && voiceStyleDraft !== (item.voiceStyle ?? "")))

  const handlePickMedia = async () => {
    if (!canEditAssetMedia) return
    onActivate()
    const file = await pickLocalImageFile("上传设计图")
    if (file) onUploadMedia(file)
  }

  const handlePickReferenceMedia = async () => {
    if (!canEditAssetMedia || referenceBusy) return
    onActivate()
    const file = await pickLocalImageFile(`上传${meta.noun}参考图`)
    if (file) await updateReference(() => onUploadReferenceMedia(file))
  }

  const handlePickVoiceReferenceAudio = async () => {
    if (!canEditVoiceReferenceAudio || referenceBusy) return
    onActivate()
    const file = await pickLocalMediaFile(`上传${meta.noun}参考音频`, "audio")
    if (!file) return
    setVoiceReferenceAudioCropSource(file)
    setVoiceReferenceAudioCropOpen(true)
  }

  const handleRemoveVoiceReferenceAudio = async () => {
    if (!canEditVoiceReferenceAudio || referenceBusy || !voiceReferenceAudioSrc) return
    onActivate()
    await updateReference(onRemoveVoiceReferenceAudio)
  }

  const updateReference = async (action: () => Promise<void>) => {
    if (referenceBusy) return
    setReferenceUpdating(true)
    try {
      await action()
    } finally {
      setReferenceUpdating(false)
    }
  }

  const menuActions: AssetCardMenuAction[] = isProjectScope
    ? lifecycleView === "offline"
      ? [
          {
            key: "restore",
            title: "恢复到活跃",
            ToolIcon: RefreshCcw,
            disabled: Boolean(updatingLifecycle),
            onSelect: () => {
              onActivate()
              onSetLifecycle("active")
            },
          },
          {
            key: "versions",
            title: "历史版本",
            ToolIcon: History,
            onSelect: () => {
              onActivate()
              onOpenVersions()
            },
          },
          {
            key: "delete",
            title: "删除资产",
            ToolIcon: Trash2,
            destructive: true,
            separatorBefore: true,
            onSelect: () => {
              onActivate()
              onDelete()
            },
          },
        ]
      : [
          {
            key: "upload",
            title: mediaSrc ? "替换设计图" : "上传设计图",
            ToolIcon: Upload,
            onSelect: () => void handlePickMedia(),
          },
          {
            key: "copy-to-library",
            title: "加入全局",
            ToolIcon: FolderPlus,
            onSelect: () => {
              onActivate()
              onCopyToLibrary()
            },
          },
          {
            key: "versions",
            title: "历史版本",
            ToolIcon: History,
            onSelect: () => {
              onActivate()
              onOpenVersions()
            },
          },
          {
            key: "offline",
            title: "资产下线",
            ToolIcon: Archive,
            disabled: Boolean(updatingLifecycle),
            onSelect: () => {
              onActivate()
              onSetLifecycle("offline")
            },
          },
          {
            key: "delete",
            title: "删除资产",
            ToolIcon: Trash2,
            destructive: true,
            separatorBefore: true,
            onSelect: () => {
              onActivate()
              onDelete()
            },
          },
        ]
    : [
        {
          key: "edit",
          title: "编辑资产",
          ToolIcon: Pencil,
          onSelect: () => {
            onActivate()
            onEdit()
          },
        },
        {
          key: "delete",
          title: "删除资产",
          ToolIcon: Trash2,
          destructive: true,
          separatorBefore: true,
          onSelect: () => {
            onActivate()
            onDelete()
          },
        },
      ]

  const cardContent = (
    <article
      ref={cardRef}
      data-workspace-focus-surface
      onMouseDown={onActivate}
      onFocusCapture={onActivate}
      className={cn(
        "relative flex h-full flex-col overflow-hidden rounded-md border border-white/60 bg-white/70 p-5 shadow-sm transition-[background-color,border-color,box-shadow] dark:border-white/10 dark:bg-white/[0.055]",
        activeFocusToken
          ? "border-emerald-300/80 bg-gradient-to-br from-emerald-500/14 via-teal-400/8 to-white/80 shadow-[0_0_0_4px_rgba(16,185,129,0.14),0_18px_38px_rgba(15,23,42,0.10)] dark:border-emerald-400/55 dark:from-emerald-400/14 dark:via-teal-300/8 dark:to-white/[0.055]"
          : ""
      )}
    >
      <span className="pointer-events-none absolute inset-x-5 top-0 h-px bg-gradient-to-r from-transparent via-indigo-300 to-transparent" />
      <div className="mb-4 flex items-center gap-2.5">
        <span
          className={cn(
            "grid size-8 shrink-0 place-items-center rounded-lg border",
            isProjectScope && lifecycleView === "offline"
              ? "border-slate-200 bg-slate-100 text-slate-500 dark:border-white/10 dark:bg-white/[0.075] dark:text-slate-300"
              : "border-indigo-200 bg-indigo-50 text-indigo-600 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
          )}
        >
          <Icon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <TooltipWrap content={item.name}>
            <h3 className="truncate text-[16px] font-semibold text-gray-950 dark:text-gray-50">
              {item.name}
            </h3>
          </TooltipWrap>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {canEditAssetMedia ? (
            <TooltipWrap content={mediaSrc ? "替换设计图" : "上传设计图"}>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className={cn(ICON_GHOST_BTN_CLS, "size-7")}
                aria-label={mediaSrc ? "替换设计图" : "上传设计图"}
                onClick={() => void handlePickMedia()}
              >
                <Upload className="size-3.5" />
              </Button>
            </TooltipWrap>
          ) : null}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className={cn(ICON_GHOST_BTN_CLS, "size-7")}
                aria-label="更多操作"
                title="更多操作"
                onClick={onActivate}
              >
                {updatingLifecycle ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <MoreVertical className="size-3.5" />
                )}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <AssetCardDropdownMenuItems actions={menuActions} />
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <div className="mb-4 space-y-3">
        <div>
          <div className="flex items-center justify-between gap-2">
            <CapsLabel>{meta.noun}设计图</CapsLabel>
            {isProjectScope && tab === "characters" ? (
              <TooltipWrap
                content={item.hideTurnaroundHeads
                  ? "关闭：三视图仅隐藏头部，保留颈部及以下，左侧主图不变。"
                  : "开启：生成三视图时保留头部。"}
              >
                <span className="inline-flex items-center">
                  <Switch
                    aria-label="三视图显示头部"
                    className="h-4 w-7 shadow-none data-[state=checked]:border-indigo-300 data-[state=checked]:bg-indigo-50 data-[state=unchecked]:border-gray-200 data-[state=unchecked]:bg-gray-100 dark:data-[state=checked]:border-indigo-400/60 dark:data-[state=checked]:bg-indigo-950/25 dark:data-[state=unchecked]:border-white/10 dark:data-[state=unchecked]:bg-white/5"
                    thumbClassName="size-2.5 bg-gray-400 shadow-none data-[state=checked]:translate-x-3 data-[state=checked]:bg-indigo-600 dark:bg-gray-500 dark:data-[state=checked]:bg-indigo-300"
                    checked={!item.hideTurnaroundHeads}
                    disabled={referenceBusy || headSettingsUpdating || lifecycleView !== "active"}
                    onCheckedChange={async (checked) => {
                      setHeadSettingsUpdating(true)
                      try {
                        await onTurnaroundHeadsChange(checked)
                      } catch {
                        // The mutation handler displays the save error.
                      } finally {
                        setHeadSettingsUpdating(false)
                      }
                    }}
                  />
                </span>
              </TooltipWrap>
            ) : null}
          </div>
          <div className="mt-1.5 overflow-hidden rounded-md border border-gray-200/70 dark:border-white/10">
            <UnifiedMediaFrame
              src={mediaSrc}
              alt={`${item.name}${meta.noun}图`}
              title={item.name}
              className="aspect-video rounded-none border-0"
              interactive={Boolean(mediaSrc)}
              showActions={Boolean(mediaSrc)}
              downloadSource={mediaDownloadSource(item.media)}
              fallbackClassName={cn(
                "from-indigo-600 via-sky-600 to-emerald-500",
                item.accent
              )}
            />
          </div>
        </div>

        {showReferenceSection ? (
          <div>
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <CapsLabel>参考图</CapsLabel>
              {referenceSrc && canEditAssetMedia ? (
                <button type="button" className="text-[11px] text-gray-400 hover:text-red-500"
                  disabled={referenceBusy} onClick={() => void updateReference(onClearReferenceMedia)}>移除</button>
              ) : null}
            </div>
            {referenceSrc ? (
              <div className="relative h-28 overflow-hidden rounded-md border border-gray-200/70 dark:border-white/10">
                <UnifiedMediaFrame
                  src={referenceSrc}
                  alt={`${item.name}参考图`}
                  title={`${item.name}参考图`}
                  className="h-full rounded-none border-0"
                  interactive={Boolean(referenceSrc)}
                  showActions={Boolean(referenceSrc)}
                  downloadSource={mediaDownloadSource(item.referenceMedia)}
                />
                <Badge className="absolute bottom-2 left-2 rounded-full bg-black/45 text-[10px] text-white">
                  {item.referenceMediaRole === "original" ? "原图 · 按描述修改" : "参考图 · 按固定版式生成"}
                </Badge>
                {canEditAssetMedia ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="absolute right-2 bottom-2 h-7 gap-1.5 border-white/60 bg-white/85 px-2 text-[11px] text-gray-700 shadow-sm hover:bg-white dark:border-white/20 dark:bg-[#202025]/85 dark:text-gray-100 dark:hover:bg-[#202025]"
                    onClick={() => void handlePickReferenceMedia()}
                    disabled={referenceBusy}
                  >
                    <Upload className="size-3" />
                    替换
                  </Button>
                ) : null}
              </div>
            ) : canEditAssetMedia ? (
              <div className="grid h-24 grid-cols-2 overflow-hidden rounded-lg border border-dashed border-indigo-200 bg-indigo-50/45 text-xs text-indigo-700 dark:border-indigo-900/50 dark:bg-indigo-950/20 dark:text-indigo-200">
                <button type="button" disabled={referenceBusy}
                  className="flex flex-col items-center justify-center gap-2 transition-colors hover:bg-indigo-100/50 disabled:opacity-40 dark:hover:bg-white/5"
                  onClick={() => void handlePickReferenceMedia()}>
                  <ImagePlus className="size-5" />
                  <span>上传参考图</span>
                </button>
                <button type="button" disabled={!mediaSrc || referenceBusy}
                  title={mediaSrc ? "将当前设计图作为原图修改" : "暂无原图"}
                  className="flex flex-col items-center justify-center gap-2 border-l border-dashed border-indigo-200 transition-colors hover:bg-indigo-100/50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-indigo-900/50 dark:hover:bg-white/5"
                  onClick={() => void updateReference(onUseOriginalReference)}>
                  <ImagePlus className="size-5" />
                  <span>使用原图</span>
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      <label className="block">
        <span className="mb-1.5 block text-[10px] font-semibold tracking-[0.12em] text-gray-400 uppercase">
          设计图提示词
        </span>
        {isProjectScope ? (
          <FramedTextarea
            value={designPromptDraft}
            onChange={(event) => setDesignPromptDraft(event.target.value)}
            rows={4}
            placeholder="填写用于生成设计图的提示词"
            containerClassName="rounded-lg"
            className="resize-y text-[13px] leading-5"
          />
        ) : (
          <FramedTextBlock
            value={designPrompt}
            placeholder="暂无设计图提示词"
            containerClassName="rounded-lg"
            className="text-[13px] leading-5"
          />
        )}
      </label>
      {canUseVoiceStyle ? (
        <div className="mt-3 block">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-[10px] font-semibold tracking-[0.12em] text-gray-400 uppercase">
              {assetVoiceStyleLabel(tab)}
            </span>
            {canEditVoiceReferenceAudio ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-6 gap-1 px-1.5 text-[11px] text-indigo-600 hover:bg-indigo-50 dark:text-indigo-300 dark:hover:bg-indigo-950/30"
                disabled={referenceBusy}
                onClick={() => void handlePickVoiceReferenceAudio()}
              >
                <Upload className="size-3" />
                {voiceReferenceAudioSrc ? "替换参考音频" : "上传参考音频"}
              </Button>
            ) : null}
          </div>
          {isProjectScope ? (
            <FramedTextarea
              value={voiceStyleDraft}
              onChange={(event) => setVoiceStyleDraft(event.target.value)}
              rows={3}
              containerClassName="rounded-lg"
              placeholder={`暂无${assetVoiceStyleLabel(tab)}`}
              className="resize-none text-[13px] leading-5"
            />
          ) : (
            <FramedTextBlock
              value={voiceStyleDraft}
              placeholder={`暂无${assetVoiceStyleLabel(tab)}`}
              containerClassName="rounded-lg"
              className="text-[13px] leading-5"
            />
          )}
          {voiceReferenceAudioSrc ? (
            <div className="mt-2 flex items-center gap-2 rounded-md border border-indigo-100 bg-indigo-50/40 px-2 py-1.5 dark:border-indigo-900/40 dark:bg-indigo-950/20">
              <ReferenceAudioPlayer src={voiceReferenceAudioSrc} className="min-w-0 flex-1" />
              {canEditVoiceReferenceAudio ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  className="size-7 shrink-0 rounded-sm text-rose-600 hover:bg-rose-50/80 hover:text-rose-700 dark:text-rose-300 dark:hover:bg-rose-400/10 dark:hover:text-rose-200"
                  disabled={referenceBusy}
                  onClick={() => void handleRemoveVoiceReferenceAudio()}
                  title="移除参考音频"
                  aria-label="移除参考音频"
                >
                  <Trash2 className="size-3" />
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {isProjectScope ? (
        <div className="mt-3">
          {dirty ? (
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 rounded-md border border-indigo-100/80 bg-white/90 px-2.5 py-1.5 text-[11px] text-gray-700 shadow-sm shadow-indigo-950/[0.04] backdrop-blur-xl dark:border-white/10 dark:bg-[#202025]/90 dark:text-gray-200">
              <div className="flex items-center gap-1.5 font-medium">
                <AlertTriangle className="size-3 shrink-0 text-indigo-500 dark:text-indigo-300" />
                <span>是否保存修改？</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-6 gap-1 border-gray-200/80 bg-white/70 px-2 text-[11px] text-gray-600 hover:border-gray-300 hover:bg-white/90 hover:text-gray-900 dark:border-white/10 dark:bg-white/[0.04] dark:text-gray-300 dark:hover:border-white/15 dark:hover:bg-white/[0.08] dark:hover:text-white"
                  onClick={resetDraft}
                >
                  取消
                </Button>
                <Button
                  type="button"
                  size="sm"
                  className="h-6 gap-1 bg-indigo-600 px-2 text-[11px] text-white shadow-sm shadow-indigo-950/10 hover:bg-indigo-500 dark:bg-indigo-500 dark:text-white dark:hover:bg-indigo-400"
                  onClick={() => {
                    onActivate()
                    onSave({
                      name: item.name,
                      desc: designPromptDraft.trim(),
                      tag: item.tag ?? "",
                      prompts: {
                        ...(item.prompts ?? {}),
                        assetImagePrompt: designPromptDraft.trim(),
                      },
                      canSpeak:
                        tab === "creatures"
                          ? Boolean(voiceStyleDraft.trim())
                          : undefined,
                      voiceStyle: canUseVoiceStyle
                        ? voiceStyleDraft.trim()
                        : undefined,
                    })
                  }}
                >
                  <Save className="size-3" />
                  保存
                </Button>
              </div>
            </div>
          ) : null}
          {lifecycleView === "active" ? (
            <Button
              type="button"
              size="sm"
              className="h-9 w-full gap-1.5 bg-indigo-600 text-xs text-white hover:bg-indigo-500 dark:bg-indigo-500 dark:text-white dark:hover:bg-indigo-400"
              disabled={referenceBusy || dirty}
              aria-disabled={headSettingsUpdating || undefined}
              title={headSettingsUpdating ? "正在保存三视图设置" : dirty ? "请先保存提示词修改" : undefined}
              onClick={() => {
                if (headSettingsUpdating) return
                onActivate()
                onGenerateMedia()
              }}
            >
              {generatingMedia ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <WandSparkles className="size-3.5" />
              )}
              {referenceSrc && item.referenceMediaRole === "original" ? "修改设计图" : "生成设计图"}
            </Button>
          ) : null}
        </div>
      ) : null}
    </article>
  )

  return (
    <>
      <ContextMenu>
        <ContextMenuTrigger asChild>{cardContent}</ContextMenuTrigger>
        <ContextMenuContent className="w-44">
          <AssetCardContextMenuItems actions={menuActions} />
        </ContextMenuContent>
      </ContextMenu>
      <ReferenceAudioCropDialog
        open={voiceReferenceAudioCropOpen}
        sourceFile={voiceReferenceAudioCropSource}
        callBackend={callBackend}
        title={`处理${meta.noun}参考音频`}
        onClose={() => {
          setVoiceReferenceAudioCropOpen(false)
          setVoiceReferenceAudioCropSource(null)
        }}
        onConfirm={(file) => updateReference(() => onUploadVoiceReferenceAudio(file))}
      />
    </>
  )
}
