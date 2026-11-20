import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { ImagePlus } from "lucide-react"
import { createAsset, type AssetType, type MediaAsset } from "@/backend"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useBackend } from "@/hooks/useBackend"
import type { AssetTab } from "@/navigation"
import {
  buildGlobalAssetPayload,
  getAssetMeta,
  normalizeAssetNameKey,
  type AssetItem,
} from "@/features/asset-model"
import { errMsg } from "@/shared/backend-result"
import { pickLocalImageFile } from "@/shared/image-picker"
import { mediaAssetFromImageFile, mediaPreviewSrc } from "@/shared/media"
import { ModalShell } from "@/shared/page-shell"
import { TooltipWrap } from "@/shared/tooltip-wrap"
import type { AssetTurnaroundHeadMode } from "./use-asset-gallery-actions"
import { FramedTextarea } from "@/shared/framed-fields"
import { UnifiedMediaFrame } from "@/shared/unified-media-frame"
import {
  getCachedAssetRows,
  loadCachedAssetRows,
  upsertCachedAssetRows,
} from "@/features/assets/asset-cache"
import {
  AssetInlineMediaThumbnail,
  assetCanUseVoiceStyle,
  assetDesignPrompt,
  assetVoiceStyleLabel,
} from "./asset-gallery-cards"

export function GenerateAllDesignsDialog({
  count,
  onClose,
  onGenerate,
}: {
  count: number
  onClose: () => void
  onGenerate: (mode: AssetTurnaroundHeadMode) => void
}) {
  const [mode, setMode] = useState<AssetTurnaroundHeadMode>("default")
  const choices = [
    { value: "default", label: "默认", description: "沿用每张角色卡片的头部开关设置" },
    { value: "with-heads", label: "三视图有头", description: "本次全部保留三视图的头部" },
    { value: "without-heads", label: "三视图无头", description: "本次仅隐藏三视图的头部，颈部及以下完整保留" },
  ] as const
  return (
    <ModalShell
      title="生成全部角色设计图"
      description={`将为当前列表中 ${count} 个尚无设计图的角色生成设计图，已有设计图及正在生成的卡片会跳过。`}
      className="max-w-[600px]"
      onClose={onClose}
      footer={
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>取消</Button>
          <Button type="button" disabled={!count} onClick={() => onGenerate(mode)}>开始生成</Button>
        </div>
      }
    >
      <div className="grid gap-3 sm:grid-cols-3" role="group" aria-label="三视图头部设置">
        {choices.map((choice) => (
          <button
            key={choice.value}
            type="button"
            aria-pressed={mode === choice.value}
            className={`rounded-lg border p-4 text-left transition-colors ${mode === choice.value
              ? "border-indigo-500 bg-indigo-50 text-indigo-700 dark:border-indigo-400 dark:bg-indigo-950/40 dark:text-indigo-200"
              : "border-gray-200 text-gray-700 hover:border-indigo-300 dark:border-white/10 dark:text-gray-300 dark:hover:border-indigo-500"}`}
            onClick={() => setMode(choice.value)}
          >
            <span className="block text-sm font-semibold">{choice.label}</span>
            <span className="mt-2 block text-xs leading-5 opacity-75">{choice.description}</span>
          </button>
        ))}
      </div>
      <p className="mt-4 text-xs text-gray-500 dark:text-gray-400">三种方式均保留左侧完整头像；本次选择不会修改卡片的开关设置。</p>
    </ModalShell>
  )
}

export function AssetFormDialog({
  tab,
  scope,
  projectId,
  existingRows,
  onClose,
  onCreated,
}: {
  tab: AssetTab
  scope: "global" | "project"
  projectId?: string
  existingRows?: AssetItem[]
  onClose: () => void
  onCreated: (asset: AssetItem) => void
}) {
  const { backendReady, callBackend } = useBackend()
  const meta = getAssetMeta(tab)
  const [name, setName] = useState("")
  const [designPrompt, setDesignPrompt] = useState("")
  const [voiceStyle, setVoiceStyle] = useState("")
  const [media, setMedia] = useState<MediaAsset | null>(null)
  const [saving, setSaving] = useState(false)
  const duplicateName = useMemo(() => {
    const target = normalizeAssetNameKey(name)
    if (!target) return false
    return (existingRows ?? []).some(
      (row) => normalizeAssetNameKey(row.name) === target
    )
  }, [existingRows, name])

  const handlePickFile = async () => {
    const file = await pickLocalImageFile(`上传${meta.noun}设计图`)
    if (file) setMedia(mediaAssetFromImageFile(file))
  }

  const handleSave = async () => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    if (!name.trim()) {
      toast.error(`${meta.noun}名称不能为空`)
      return
    }
    if (duplicateName) {
      toast.error(`项目中已存在同名${meta.noun}「${name.trim()}」`)
      return
    }
    if (!media) {
      toast.error(`请上传${meta.noun}设计图`)
      return
    }
    setSaving(true)
    try {
      const asset = await createAsset(
        callBackend,
        tab as AssetType,
        {
          name: name.trim(),
          desc: designPrompt.trim(),
          canSpeak:
            tab === "creatures" ? Boolean(voiceStyle.trim()) : undefined,
          prompts: { assetImagePrompt: designPrompt.trim() },
          voiceStyle: assetCanUseVoiceStyle(tab)
            ? voiceStyle.trim()
            : undefined,
          media,
        },
        scope,
        projectId
      )
      toast.success(`${meta.noun}已创建`)
      onCreated(asset as AssetItem)
    } catch (error) {
      toast.error(errMsg(error, `创建${meta.noun}失败`))
    } finally {
      setSaving(false)
    }
  }

  return (
    <ModalShell
      title={meta.addLabel}
      description={`创建新的${meta.noun}资产，左侧上传设计图，右侧填写展示信息。`}
      onClose={onClose}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            onClick={() => void handleSave()}
            disabled={saving || !name.trim() || duplicateName || !media}
          >
            {saving ? "保存中" : meta.addLabel}
          </Button>
        </>
      }
    >
      <div className="grid gap-5 md:grid-cols-[240px_minmax(0,1fr)]">
        <div className="space-y-3">
          <button
            type="button"
            className="relative block aspect-video w-full cursor-pointer overflow-hidden rounded-md border border-dashed border-indigo-300 bg-indigo-50/60 text-center text-indigo-700 transition-colors hover:border-indigo-400 hover:bg-indigo-50/80 focus-visible:ring-2 focus-visible:ring-indigo-400/60 focus-visible:outline-none dark:border-indigo-900/60 dark:bg-indigo-950/20 dark:text-indigo-300 dark:hover:border-indigo-700 dark:hover:bg-indigo-950/30"
            onClick={() => void handlePickFile()}
          >
            {media ? (
              <>
                <UnifiedMediaFrame
                  src={mediaPreviewSrc(media)}
                  alt={`${meta.noun}设计图`}
                  title={name || meta.noun}
                  className="h-full rounded-none border-0"
                  interactive={false}
                  showActions={false}
                />
                <span className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full bg-black/50 px-2.5 py-1 text-[10px] text-white backdrop-blur-sm">
                  替换设计图
                </span>
              </>
            ) : (
              <span className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-4">
                <ImagePlus className="size-6" />
                <span className="text-sm font-semibold">
                  上传{meta.noun}设计图
                </span>
                <span className="text-[11px] leading-relaxed text-indigo-600/75 dark:text-indigo-200/75">
                  必填，用作当前{meta.noun}图片
                </span>
              </span>
            )}
          </button>
        </div>
        <div className="space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
              {meta.noun}名称
            </span>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="h-9 bg-white/70"
              placeholder={`输入${meta.noun}名称`}
            />
            {duplicateName ? (
              <span className="mt-1 block text-[11px] text-amber-600 dark:text-amber-300">
                项目中已存在同名{meta.noun}，请更换名称。
              </span>
            ) : null}
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
              设计图提示词
            </span>
            <FramedTextarea
              value={designPrompt}
              onChange={(event) => setDesignPrompt(event.target.value)}
              containerClassName="min-h-[110px] rounded-xl"
              className="min-h-[106px] resize-y"
              placeholder={`填写${meta.noun}设计图生成提示词`}
            />
          </label>
          {assetCanUseVoiceStyle(tab) ? (
            <label className="block">
              <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
                {assetVoiceStyleLabel(tab)}
              </span>
              <FramedTextarea
                value={voiceStyle}
                onChange={(event) => setVoiceStyle(event.target.value)}
                containerClassName="min-h-[90px] rounded-xl"
                className="min-h-[86px] resize-y"
                placeholder="如：低沉、含混、语速缓慢。"
              />
            </label>
          ) : null}
        </div>
      </div>
    </ModalShell>
  )
}

export function BulkAssetDialog({
  tab,
  rows,
  scope,
  projectId,
  onClose,
}: {
  tab: AssetTab
  rows: AssetItem[]
  scope: "global" | "project"
  projectId?: string
  onClose: () => void
}) {
  const { backendReady, callBackend } = useBackend()
  const meta = getAssetMeta(tab)
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(scope === "project")
  const [readyRows, setReadyRows] = useState<AssetItem[]>([])
  const [missingDesignRows, setMissingDesignRows] = useState<AssetItem[]>([])
  const [duplicateCount, setDuplicateCount] = useState(0)

  useEffect(() => {
    if (scope !== "project") {
      setLoading(false)
      setReadyRows([])
      setMissingDesignRows([])
      setDuplicateCount(0)
      return
    }
    if (!backendReady) {
      setLoading(false)
      return
    }
    let cancelled = false
    const cacheOptions = {
      scope: "global" as const,
      assetType: tab as AssetType,
    }
    const applyGlobalRows = (globalRows: AssetItem[]) => {
      const existingNames = new Set(
        globalRows.map((item) => normalizeAssetNameKey(item.name))
      )
      const ready: AssetItem[] = []
      const missing: AssetItem[] = []
      let duplicated = 0
      for (const item of rows) {
        if (!item.media) {
          missing.push(item)
          continue
        }
        if (existingNames.has(normalizeAssetNameKey(item.name))) {
          duplicated += 1
          continue
        }
        ready.push(item)
      }
      setReadyRows(ready)
      setMissingDesignRows(missing)
      setDuplicateCount(duplicated)
    }
    const cachedRows = getCachedAssetRows(cacheOptions)
    if (cachedRows) {
      applyGlobalRows(cachedRows)
      setLoading(false)
      return
    }
    setLoading(true)
    loadCachedAssetRows(callBackend, cacheOptions)
      .then((globalRows) => {
        if (cancelled) return
        applyGlobalRows(globalRows)
      })
      .catch((error) => {
        console.warn("加载全局资产失败:", error)
        if (cancelled) return
        setReadyRows([])
        setMissingDesignRows(rows)
        setDuplicateCount(0)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [backendReady, callBackend, rows, scope, tab])
  const handleConfirm = async () => {
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    if (scope !== "project" || !projectId) {
      toast.info("请在具体项目内使用批量加入全局资产")
      return
    }
    if (readyRows.length === 0) {
      toast.info("没有可加入全局资产的设计图")
      return
    }
    setSaving(true)
    try {
      let createdCount = 0
      for (const row of readyRows) {
        const created = await createAsset(
          callBackend,
          tab as AssetType,
          buildGlobalAssetPayload(tab, row),
          "global"
        )
        upsertCachedAssetRows(
          { scope: "global", assetType: tab as AssetType },
          created
        )
        createdCount += 1
      }
      toast.success(`加入 ${createdCount} 个${meta.noun}`)
      onClose()
    } catch (error) {
      toast.error(errMsg(error, `批量加入${meta.noun}失败`))
    } finally {
      setSaving(false)
    }
  }
  return (
    <ModalShell
      title="批量加入全局资产"
      description={`${meta.title}会筛出有设计图且全局资产中不存在同名资产的条目。`}
      onClose={onClose}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            onClick={() => void handleConfirm()}
            disabled={saving || loading || readyRows.length === 0}
          >
            {saving ? "处理中" : `加入 ${readyRows.length} 个${meta.noun}`}
          </Button>
        </>
      }
    >
      {scope !== "project" ? (
        <div className="rounded-xl border border-gray-200/70 bg-white/70 px-4 py-10 text-center text-sm text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
          当前页面已经是全局资产，请在具体项目内使用“批量加入全局资产”。
        </div>
      ) : loading ? (
        <div className="rounded-xl border border-gray-200/70 bg-white/70 px-4 py-10 text-center text-sm text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
          正在检查哪些{meta.noun}可加入全局资产...
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-3 lg:grid-cols-2">
            <BulkAssetStatusSection
              title="可加入全局资产"
              rows={readyRows}
              emptyLabel="当前没有可直接加入全局资产的设计图。"
              noun={meta.noun}
            />
            <BulkAssetStatusSection
              title="缺少设计图"
              rows={missingDesignRows}
              emptyLabel="所有条目都已经有设计图。"
              noun={meta.noun}
            />
          </div>
          <div className="rounded-xl border border-gray-200/70 bg-white/70 px-4 py-3 text-xs leading-relaxed text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
            本次可加入 {readyRows.length} 个{meta.noun}
            {duplicateCount > 0
              ? `，${duplicateCount} 个同名资产已自动排除`
              : ""}
            {missingDesignRows.length > 0
              ? `，${missingDesignRows.length} 个条目因缺少设计图未加入`
              : ""}
            。
          </div>
        </div>
      )}
    </ModalShell>
  )
}

function BulkAssetStatusSection({
  title,
  rows,
  emptyLabel,
  noun,
}: {
  title: string
  rows: AssetItem[]
  emptyLabel: string
  noun: string
}) {
  return (
    <section className="flex min-h-[280px] flex-col rounded-xl border border-gray-200/70 bg-white/70 p-3 dark:border-white/10 dark:bg-white/[0.035]">
      <div className="flex items-center gap-2">
        <h3 className="display-serif min-w-0 flex-1 truncate text-[14px] font-semibold tracking-tight text-gray-950 dark:text-gray-50">
          {title}
        </h3>
        <Badge variant="outline" className="rounded-full text-[10px]">
          {rows.length}
        </Badge>
      </div>
      {rows.length === 0 ? (
        <div className="flex flex-1 items-center justify-center px-3 text-center text-[12px] text-gray-500 dark:text-gray-400">
          {emptyLabel}
        </div>
      ) : (
        <div className="mt-3 flex-1 space-y-2 overflow-y-auto pr-1">
          {rows.map((item) => (
            <div
              key={item.id}
              className="flex items-stretch gap-2 rounded-lg border border-gray-200/70 bg-white/75 px-3 py-2 dark:border-white/10 dark:bg-white/[0.035]"
            >
              <AssetInlineMediaThumbnail
                src={mediaPreviewSrc(item.media)}
                alt={`${item.name}${noun}图`}
                title={item.name}
                media={item.media}
                fallbackClassName={item.accent}
                className="w-32 shrink-0"
              />
              <div className="min-w-0 flex-1">
                <TooltipWrap content={item.name}>
                  <div className="truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
                    {item.name}
                  </div>
                </TooltipWrap>
                <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                  {assetDesignPrompt(item) || "暂无设计图提示词"}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
