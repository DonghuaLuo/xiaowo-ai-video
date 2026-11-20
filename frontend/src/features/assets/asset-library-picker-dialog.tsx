import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { CheckCircle2, Search } from "lucide-react"
import { createAsset, updateAsset, type AssetType } from "@/backend"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import type { AssetTab } from "@/navigation"
import {
  buildProjectAssetPayloadFromLibrary,
  getAssetMeta,
  normalizeAssetNameKey,
  type AssetItem,
} from "@/features/asset-model"
import { errMsg } from "@/shared/backend-result"
import { mediaPreviewSrc } from "@/shared/media"
import { ModalShell } from "@/shared/page-shell"
import { TooltipWrap } from "@/shared/tooltip-wrap"
import {
  UnifiedMediaFrame,
  mediaDownloadSource,
} from "@/shared/unified-media-frame"
import {
  getCachedAssetRows,
  loadCachedAssetRows,
  upsertCachedAssetRows,
} from "@/features/assets/asset-cache"
import {
  ASSET_PICKER_BATCH_SIZE,
  assetDesignPrompt,
} from "./asset-gallery-cards"

export function AssetLibraryPickerDialog({
  tab,
  projectId,
  existingRows,
  onImported,
  onClose,
}: {
  tab: AssetTab
  projectId?: string
  existingRows: AssetItem[]
  onImported: () => Promise<void>
  onClose: () => void
}) {
  const { backendReady, callBackend } = useBackend()
  const meta = getAssetMeta(tab)
  const [libraryRows, setLibraryRows] = useState<AssetItem[]>([])
  const [query, setQuery] = useState("")
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())
  const [visibleCount, setVisibleCount] = useState(ASSET_PICKER_BATCH_SIZE)
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const existingNames = useMemo(
    () => new Set(existingRows.map((item) => normalizeAssetNameKey(item.name))),
    [existingRows]
  )
  const existingByName = useMemo(() => {
    const rows = new Map<string, AssetItem>()
    for (const item of existingRows) {
      const key = normalizeAssetNameKey(item.name)
      if (key) rows.set(key, item)
    }
    return rows
  }, [existingRows])
  useEffect(() => {
    if (!backendReady) {
      setLibraryRows([])
      setSelectedIds(new Set())
      return
    }
    const cacheOptions = {
      scope: "global" as const,
      assetType: tab as AssetType,
    }
    const cachedRows = getCachedAssetRows(cacheOptions)
    if (cachedRows) {
      setLibraryRows(cachedRows)
      setSelectedIds(new Set())
      setVisibleCount(ASSET_PICKER_BATCH_SIZE)
      setLoading(false)
      return
    }
    setLoading(true)
    loadCachedAssetRows(callBackend, cacheOptions)
      .then((rows) => {
        setLibraryRows(rows)
        setSelectedIds(new Set())
        setVisibleCount(ASSET_PICKER_BATCH_SIZE)
      })
      .catch((error) => {
        console.warn("加载全局资产失败:", error)
        setLibraryRows([])
        setSelectedIds(new Set())
      })
      .finally(() => setLoading(false))
  }, [backendReady, callBackend, tab])
  const filteredRows = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase()
    if (!keyword) return libraryRows
    return libraryRows.filter((item) =>
      [item.name, assetDesignPrompt(item), item.tag]
        .join(" ")
        .toLocaleLowerCase()
        .includes(keyword)
    )
  }, [libraryRows, query])
  useEffect(() => {
    setVisibleCount(ASSET_PICKER_BATCH_SIZE)
  }, [query, tab])
  const visibleRows = filteredRows.slice(0, visibleCount)
  const hasMoreRows = filteredRows.length > visibleRows.length
  const toggle = (id: string) => {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  const handleImport = async () => {
    if (!backendReady || !projectId) {
      toast.error("请先进入具体项目后再导入资产")
      return
    }
    const selectedRows = libraryRows.filter((item) => selectedIds.has(item.id))
    if (selectedRows.length === 0) {
      toast.info("请先选择要导入的资产")
      return
    }
    const missingDesignRows = selectedRows.filter(
      (item) => !mediaPreviewSrc(item.media)
    )
    if (missingDesignRows.length > 0) {
      toast.error(
        `${missingDesignRows.length} 个${meta.noun}缺少设计图，不能导入`
      )
      return
    }
    setImporting(true)
    try {
      const occupiedNames = new Set(existingNames)
      let createdCount = 0
      let versionCount = 0
      for (const row of selectedRows) {
        const sourceKey = normalizeAssetNameKey(row.name)
        const existing = existingByName.get(sourceKey)
        const basePayload = buildProjectAssetPayloadFromLibrary(tab, row)
        if (existing) {
          const updated = await updateAsset(
            callBackend,
            tab as AssetType,
            existing.id,
            {
              desc: basePayload.desc,
              tag: existing.tag ?? basePayload.tag,
              canSpeak: basePayload.canSpeak,
              voiceStyle: basePayload.voiceStyle,
              voiceReferenceAudio: basePayload.voiceReferenceAudio,
              prompts: basePayload.prompts,
              media: basePayload.media,
            },
            "project",
            projectId
          )
          upsertCachedAssetRows(
            { scope: "project", projectId, assetType: tab as AssetType },
            updated
          )
          versionCount += 1
          continue
        }
        if (occupiedNames.has(sourceKey)) {
          toast.error(`项目中已存在同名${meta.noun}「${row.name}」`)
          return
        }
        const created = await createAsset(
          callBackend,
          tab as AssetType,
          basePayload,
          "project",
          projectId
        )
        upsertCachedAssetRows(
          { scope: "project", projectId, assetType: tab as AssetType },
          created
        )
        occupiedNames.add(sourceKey)
        createdCount += 1
      }
      toast.success(
        [
          createdCount ? `导入 ${createdCount} 个${meta.noun}` : "",
          versionCount ? `新增 ${versionCount} 个同名版本` : "",
        ]
          .filter(Boolean)
          .join("，") || `${meta.noun}已导入`
      )
      await onImported()
    } catch (error) {
      toast.error(errMsg(error, `导入${meta.noun}失败`))
    } finally {
      setImporting(false)
    }
  }
  return (
    <ModalShell
      title={`从全局资产选择${meta.noun}`}
      description={`从全局资产选择${meta.noun}加入当前项目；遇到同名时会为项目内已有${meta.noun}新增一个设计图版本并设为当前版本。`}
      className="max-w-[min(1180px,calc(100vw-1.5rem))]"
      bodyClassName="p-4 sm:p-5"
      onClose={onClose}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            onClick={() => void handleImport()}
            disabled={importing || loading}
          >
            {importing ? "导入中" : `导入所选${meta.noun}`}
          </Button>
        </>
      }
    >
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative min-w-[240px] flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-gray-400" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={`搜索${meta.noun}名称 / 设计图提示词`}
            className="h-9 rounded-md border-gray-200/80 bg-white/70 pl-9 text-[12px] dark:border-white/10 dark:bg-white/[0.035]"
          />
        </div>
        <Badge variant="outline" className="rounded-full text-[11px]">
          已选 {selectedIds.size}
        </Badge>
        <Badge variant="outline" className="rounded-full text-[11px]">
          已在项目 {existingRows.length}
        </Badge>
      </div>
      {loading ? (
        <div className="rounded-xl border border-gray-200/70 bg-white/70 px-4 py-12 text-center text-sm text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
          正在加载全局资产...
        </div>
      ) : filteredRows.length === 0 ? (
        <div className="rounded-xl border border-gray-200/70 bg-white/70 px-4 py-12 text-center text-sm text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
          没有匹配的资产，请修改搜索词。
        </div>
      ) : (
        <div className="max-h-[min(62dvh,620px)] [scrollbar-gutter:stable] overflow-y-auto pr-1">
          <div className="grid [grid-template-columns:repeat(auto-fill,minmax(198px,1fr))] gap-3">
            {visibleRows.map((item) => {
              const duplicate = existingNames.has(
                normalizeAssetNameKey(item.name)
              )
              const selected = selectedIds.has(item.id)
              const mediaSrc = mediaPreviewSrc(item.media)
              const hasDesign = Boolean(mediaSrc)
              return (
                <div
                  key={item.id}
                  role="button"
                  tabIndex={0}
                  aria-pressed={selected}
                  aria-disabled={!hasDesign}
                  className={cn(
                    "rounded-xl border p-3 text-left transition-colors",
                    !hasDesign
                      ? "cursor-not-allowed border-gray-200/70 bg-gray-50/80 opacity-75 dark:border-white/10 dark:bg-white/[0.025]"
                      : duplicate
                        ? selected
                          ? "cursor-pointer border-amber-300 bg-amber-50/80 dark:border-amber-800/70 dark:bg-amber-950/25"
                          : "cursor-pointer border-amber-200/80 bg-white/70 hover:border-amber-300 hover:bg-amber-50/60 dark:border-amber-900/50 dark:bg-white/[0.035] dark:hover:bg-amber-950/20"
                        : selected
                          ? "cursor-pointer border-indigo-200 bg-indigo-50/80 dark:border-indigo-900/60 dark:bg-indigo-950/25"
                          : "cursor-pointer border-gray-200/70 bg-white/70 hover:border-indigo-200 hover:bg-indigo-50/45 dark:border-white/10 dark:bg-white/[0.035] dark:hover:border-indigo-900/60 dark:hover:bg-indigo-950/20"
                  )}
                  onClick={() => {
                    if (!hasDesign) {
                      toast.info(`该${meta.noun}缺少设计图，不能导入`)
                      return
                    }
                    toggle(item.id)
                  }}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter" && event.key !== " ") return
                    event.preventDefault()
                    if (!hasDesign) {
                      toast.info(`该${meta.noun}缺少设计图，不能导入`)
                      return
                    }
                    toggle(item.id)
                  }}
                >
                  <div
                    className="overflow-hidden rounded-md border border-gray-200/70 dark:border-white/10"
                    onClick={(event) => event.stopPropagation()}
                    onKeyDown={(event) => event.stopPropagation()}
                  >
                    <UnifiedMediaFrame
                      src={mediaSrc}
                      alt={`${item.name}${meta.noun}图`}
                      title={item.name}
                      className="aspect-video rounded-none border-0"
                      downloadSource={mediaDownloadSource(item.media)}
                      fallbackClassName={item.accent}
                    />
                  </div>
                  <div className="mt-2 flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <TooltipWrap content={item.name}>
                        <div className="truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
                          {item.name}
                        </div>
                      </TooltipWrap>
                      <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                        {assetDesignPrompt(item) || "暂无设计图提示词"}
                      </div>
                    </div>
                    {selected ? (
                      <span
                        className="grid size-5 shrink-0 place-items-center rounded-full bg-indigo-600 text-white"
                        aria-hidden
                      >
                        <CheckCircle2 className="size-3" />
                      </span>
                    ) : null}
                  </div>
                  {duplicate || !hasDesign ? (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {duplicate ? (
                        <Badge
                          variant="outline"
                          className="rounded-full border-amber-200 bg-amber-50 text-[10px] text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-200"
                        >
                          同名，新增版本
                        </Badge>
                      ) : null}
                      {!hasDesign ? (
                        <Badge
                          variant="outline"
                          className="rounded-full border-rose-200 bg-rose-50 text-[10px] text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200"
                        >
                          缺少设计图
                        </Badge>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
          {hasMoreRows ? (
            <div className="mt-4 flex justify-center">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 gap-1.5 text-xs"
                onClick={() =>
                  setVisibleCount((current) =>
                    Math.min(
                      filteredRows.length,
                      current + ASSET_PICKER_BATCH_SIZE
                    )
                  )
                }
              >
                加载更多 {filteredRows.length - visibleRows.length} 个
              </Button>
            </div>
          ) : null}
        </div>
      )}
    </ModalShell>
  )
}
