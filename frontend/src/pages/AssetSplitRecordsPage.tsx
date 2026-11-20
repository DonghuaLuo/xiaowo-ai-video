import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  FileText,
  History,
  Layers3,
  Loader2,
  Package,
  PawPrint,
  RefreshCcw,
  Search,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react"

import {
  getAssetSplitBatchSourceText,
  listAssetSplitBatches,
  type AssetSplitBatch,
  type AssetSplitBatchAsset,
  type AssetSplitRecordType,
} from "@/backend"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { useBackend } from "@/hooks/useBackend"
import { countContentChars } from "@/lib/text-metrics"
import { cn } from "@/lib/utils"
import type { ProjectRow } from "@/features/projects/types"
import { errMsg } from "@/shared/backend-result"
import { mediaPreviewSrc } from "@/shared/media"
import { ModalShell } from "@/shared/page-shell"
import { TooltipWrap } from "@/shared/tooltip-wrap"

type AssetSplitRecordsPageProps = {
  project: ProjectRow
  projectVersion?: number
  refreshToken?: number
}

const ASSET_SPLIT_GROUPS: Array<{
  id: AssetSplitRecordType
  label: string
  Icon: LucideIcon
}> = [
  { id: "characters", label: "角色", Icon: Users },
  { id: "creatures", label: "生物", Icon: PawPrint },
  { id: "scenes", label: "场景", Icon: Layers3 },
  { id: "props", label: "道具", Icon: Package },
]

function formatCount(value?: number | string | null) {
  const numeric =
    typeof value === "number" ? value : Number.parseInt(String(value ?? ""), 10)
  return Number.isFinite(numeric) ? numeric.toLocaleString("zh-CN") : "0"
}

function formatRange(batch: AssetSplitBatch) {
  if (batch.rangeLabel) return batch.rangeLabel
  return `${formatCount(batch.absoluteStart)} - ${formatCount(batch.absoluteEnd)}`
}

function assetLifecycle(asset: AssetSplitBatchAsset) {
  return asset.lifecycleStatus ?? asset.lifecycle_status ?? "active"
}

function analysisStatusTone(status?: string) {
  const value = String(status ?? "")
    .trim()
    .toLocaleLowerCase()
  if (["failed", "cancelled", "canceled"].includes(value)) {
    return "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-400/25 dark:bg-rose-950/20 dark:text-rose-200"
  }
  if (["completed", "ready", "succeeded"].includes(value)) {
    return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-400/25 dark:bg-emerald-950/20 dark:text-emerald-200"
  }
  return "border-slate-200 bg-slate-50 text-slate-600 dark:border-white/10 dark:bg-white/[0.06] dark:text-slate-300"
}

function batchSearchText(batch: AssetSplitBatch) {
  const assetText = ASSET_SPLIT_GROUPS.flatMap((group) =>
    (batch.assets?.[group.id] ?? []).flatMap((asset) => [
      asset.name,
      asset.desc,
      asset.tag,
      assetFieldValue(asset, "usage"),
    ])
  )
  return [
    batch.batchLabel,
    batch.rangeId,
    batch.sourceTitle,
    batch.rangeLabel,
    batch.summary,
    batch.storyUnitSummary,
    batch.excerpt,
    batch.sourceText,
    ...assetText,
  ]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase()
}

export function AssetSplitRecordsPage({
  project,
  projectVersion,
  refreshToken,
}: AssetSplitRecordsPageProps) {
  const { backendReady, callBackend } = useBackend()
  const [batches, setBatches] = useState<AssetSplitBatch[]>([])
  const [loading, setLoading] = useState(false)
  const [errorText, setErrorText] = useState("")
  const [query, setQuery] = useState("")
  const [refreshNonce, setRefreshNonce] = useState(0)
  const [selectedRangeId, setSelectedRangeId] = useState("")
  const [readingBatch, setReadingBatch] = useState<AssetSplitBatch | null>(null)
  const [readingLoading, setReadingLoading] = useState(false)
  const [readingErrorText, setReadingErrorText] = useState("")
  const [detailAsset, setDetailAsset] = useState<AssetSplitBatchAsset | null>(
    null
  )
  const loadSeqRef = useRef(0)
  const sourceReaderSeqRef = useRef(0)

  useEffect(() => {
    loadSeqRef.current += 1
    sourceReaderSeqRef.current += 1
    setBatches([])
    setSelectedRangeId("")
    setReadingBatch(null)
    setReadingLoading(false)
    setReadingErrorText("")
    setDetailAsset(null)
  }, [project.id])

  const loadRecords = useCallback(async () => {
    if (!backendReady) return
    const requestSeq = ++loadSeqRef.current
    setLoading(true)
    setErrorText("")
    try {
      const result = await listAssetSplitBatches(callBackend, project.id, {
        sourceTextLimit: 720,
      })
      if (requestSeq !== loadSeqRef.current) return
      setBatches(result.batches)
    } catch (error) {
      if (requestSeq !== loadSeqRef.current) return
      setErrorText(errMsg(error, "加载资产拆分记录失败"))
      setBatches([])
    } finally {
      if (requestSeq === loadSeqRef.current) {
        setLoading(false)
      }
    }
  }, [backendReady, callBackend, project.id])

  const openSourceReader = useCallback(
    async (batch: AssetSplitBatch) => {
      setSelectedRangeId(batch.rangeId)
      setReadingBatch(batch)
      setReadingErrorText("")
      const requestSeq = ++sourceReaderSeqRef.current
      if (!backendReady) {
        setReadingLoading(false)
        setReadingErrorText("后端尚未就绪，暂时无法加载完整资产原文。")
        return
      }
      setReadingLoading(true)
      try {
        const result = await getAssetSplitBatchSourceText(
          callBackend,
          project.id,
          {
            rangeId: batch.rangeId,
            sourceId: batch.sourceId,
          }
        )
        if (requestSeq !== sourceReaderSeqRef.current) return
        setReadingBatch({
          ...batch,
          sourceId: result.sourceId ?? batch.sourceId,
          sourceTitle: result.sourceTitle ?? batch.sourceTitle,
          absoluteStart: result.absoluteStart ?? batch.absoluteStart,
          absoluteEnd: result.absoluteEnd ?? batch.absoluteEnd,
          rangeLabel: result.rangeLabel ?? batch.rangeLabel,
          actualUnits: result.actualUnits ?? batch.actualUnits,
          sourceText: result.sourceText,
          sourceTextCharCount:
            result.sourceTextCharCount ?? countContentChars(result.sourceText),
          sourceTextTruncated: Boolean(result.sourceTextTruncated),
        })
      } catch (error) {
        if (requestSeq !== sourceReaderSeqRef.current) return
        setReadingErrorText(errMsg(error, "加载完整资产原文失败"))
      } finally {
        if (requestSeq === sourceReaderSeqRef.current) {
          setReadingLoading(false)
        }
      }
    },
    [backendReady, callBackend, project.id]
  )

  const closeSourceReader = useCallback(() => {
    sourceReaderSeqRef.current += 1
    setReadingBatch(null)
    setReadingLoading(false)
    setReadingErrorText("")
  }, [])

  useEffect(() => {
    void loadRecords()
  }, [loadRecords, projectVersion, refreshNonce, refreshToken])

  const visibleBatches = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase()
    if (!keyword) return batches
    return batches.filter((batch) => batchSearchText(batch).includes(keyword))
  }, [batches, query])

  useEffect(() => {
    if (visibleBatches.length === 0) {
      if (selectedRangeId) setSelectedRangeId("")
      return
    }
    if (!visibleBatches.some((batch) => batch.rangeId === selectedRangeId)) {
      setSelectedRangeId(visibleBatches[0].rangeId)
    }
  }, [selectedRangeId, visibleBatches])

  const selectedBatch = useMemo(
    () =>
      visibleBatches.find((batch) => batch.rangeId === selectedRangeId) ??
      visibleBatches[0] ??
      null,
    [selectedRangeId, visibleBatches]
  )

  const totalAssetCount = useMemo(
    () =>
      batches.reduce(
        (total, batch) => total + Number(batch.totalAssetCount ?? 0),
        0
      ),
    [batches]
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-slate-50/35 dark:bg-[#14151b]">
      <div className="shrink-0 border-b border-gray-200/70 bg-white/70 px-5 py-4 backdrop-blur dark:border-white/10 dark:bg-white/[0.035]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="grid size-8 place-items-center rounded-md border border-indigo-200 bg-indigo-50 text-indigo-600 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300">
                <History className="size-4" />
              </span>
              <div className="min-w-0">
                <h2 className="truncate text-base font-semibold text-gray-950 dark:text-gray-50">
                  资产拆分记录
                </h2>
                <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                  <span>{batches.length.toLocaleString("zh-CN")} 个批次</span>
                  <span>
                    {totalAssetCount.toLocaleString("zh-CN")} 个资产记录
                  </span>
                </div>
              </div>
            </div>
          </div>
          <div className="flex min-w-[min(100%,340px)] items-center gap-2">
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-gray-400" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索批次、原文、资产"
                className="h-9 rounded-sm bg-white/70 pl-9 text-sm dark:bg-white/[0.055]"
              />
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 gap-1.5 bg-white/70 text-xs dark:bg-white/[0.055]"
              disabled={!backendReady || loading}
              onClick={() => setRefreshNonce((current) => current + 1)}
            >
              {loading ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <RefreshCcw className="size-3.5" />
              )}
              刷新
            </Button>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 p-5">
        {errorText ? (
          <div className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/25 dark:bg-rose-950/20 dark:text-rose-200">
            {errorText}
          </div>
        ) : null}
        {loading && batches.length === 0 ? (
          <div className="grid h-full min-h-[260px] place-items-center rounded-md border border-gray-200/70 bg-white/65 text-sm text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
            <span className="flex items-center gap-2">
              <Loader2 className="size-4 animate-spin" />
              正在加载资产拆分记录...
            </span>
          </div>
        ) : visibleBatches.length === 0 ? (
          <div className="grid h-full min-h-[260px] place-items-center rounded-md border border-gray-200/70 bg-white/65 px-4 text-center text-sm text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
            {query.trim() ? "没有匹配的拆分记录。" : "暂无资产拆分记录。"}
          </div>
        ) : (
          <div className="flex h-full min-h-0 flex-col gap-4 lg:flex-row">
            <aside className="flex max-h-[min(52dvh,560px)] min-h-[240px] shrink-0 flex-col overflow-hidden rounded-md border border-gray-200/70 bg-white/75 shadow-sm lg:max-h-none lg:min-h-0 lg:w-[520px] xl:w-[580px] dark:border-white/10 dark:bg-white/[0.04]">
              <div className="shrink-0 border-b border-gray-200/70 px-4 py-3 dark:border-white/10">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-gray-950 dark:text-gray-50">
                    资产原文
                  </span>
                  <Badge variant="outline" className="rounded-full text-[11px]">
                    {visibleBatches.length.toLocaleString("zh-CN")} 组
                  </Badge>
                </div>
              </div>
              <ScrollArea className="min-h-0 flex-1">
                <div className="space-y-2 p-3">
                  {visibleBatches.map((batch) => (
                    <AssetSplitSourceListItem
                      key={batch.rangeId}
                      batch={batch}
                      selected={batch.rangeId === selectedBatch?.rangeId}
                      onSelect={() => setSelectedRangeId(batch.rangeId)}
                      onRead={() => void openSourceReader(batch)}
                    />
                  ))}
                </div>
              </ScrollArea>
            </aside>
            <AssetSplitBatchAssetsPanel
              batch={selectedBatch}
              onOpenAsset={setDetailAsset}
            />
          </div>
        )}
      </div>
      {readingBatch ? (
        <AssetSplitSourceReaderDialog
          batch={readingBatch}
          loading={readingLoading}
          errorText={readingErrorText}
          onClose={closeSourceReader}
        />
      ) : null}
      {detailAsset ? (
        <AssetSplitAssetDetailDialog
          asset={detailAsset}
          onClose={() => setDetailAsset(null)}
        />
      ) : null}
    </div>
  )
}

function AssetSplitSourceListItem({
  batch,
  selected,
  onSelect,
  onRead,
}: {
  batch: AssetSplitBatch
  selected: boolean
  onSelect: () => void
  onRead: () => void
}) {
  const totalCount = batch.totalAssetCount ?? 0
  const sourcePreview = (batch.sourceText || batch.excerpt || "").trim()
  const summary = sourcePreview ? sourcePreview.slice(0, 360) : "暂无原文摘录"
  return (
    <article
      className={cn(
        "rounded-md border p-3 transition-colors",
        selected
          ? "border-indigo-200 bg-indigo-50/80 text-indigo-800 shadow-sm dark:border-indigo-400/30 dark:bg-indigo-400/10 dark:text-indigo-100"
          : "border-gray-200/70 bg-white/70 text-gray-700 hover:border-gray-300 hover:bg-white dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-300 dark:hover:border-white/15 dark:hover:bg-white/[0.055]"
      )}
    >
      <button
        type="button"
        className="block w-full text-left"
        onClick={onSelect}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-2">
              <FileText className="size-3.5 shrink-0 text-indigo-500 dark:text-indigo-300" />
              <span className="truncate text-sm font-semibold">
                {batch.batchLabel || `第 ${batch.index} 次拆分`}
              </span>
            </div>
          </div>
          <Badge
            variant="outline"
            className="rounded-full bg-white/60 text-[11px] dark:bg-white/[0.04]"
          >
            {formatCount(batch.sourceTextCharCount ?? batch.actualUnits)} 字
          </Badge>
        </div>
        <p className="mt-2 line-clamp-4 text-xs leading-6 text-gray-600 dark:text-gray-300">
          {summary}
        </p>
      </button>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline" className="rounded-full text-[11px]">
            阶段范围 {formatRange(batch)}
          </Badge>
          <Badge variant="outline" className="rounded-full text-[11px]">
            {totalCount.toLocaleString("zh-CN")} 资产
          </Badge>
          {batch.offlineAssetCount ? (
            <Badge
              variant="outline"
              className="rounded-full border-slate-200 bg-slate-50 text-[11px] text-slate-600 dark:border-white/10 dark:bg-white/[0.06] dark:text-slate-300"
            >
              下线 {batch.offlineAssetCount}
            </Badge>
          ) : null}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 gap-1.5 bg-white/60 text-[11px] dark:bg-white/[0.055]"
          onClick={onRead}
        >
          <FileText className="size-3.5" />
          阅读
        </Button>
      </div>
    </article>
  )
}

function AssetSplitSourceReaderDialog({
  batch,
  loading,
  errorText,
  onClose,
}: {
  batch: AssetSplitBatch
  loading: boolean
  errorText: string
  onClose: () => void
}) {
  const content = batch.sourceText || batch.excerpt || ""
  return (
    <ModalShell
      title={batch.batchLabel || `第 ${batch.index} 次资产原文`}
      description={`阶段范围 ${formatRange(batch)}`}
      className="max-h-[calc(100dvh-4rem)] max-w-[960px] sm:max-h-[calc(100dvh-5rem)]"
      bodyClassName="flex min-h-0 flex-col gap-3"
      onClose={onClose}
      footer={
        <Button type="button" variant="outline" onClick={onClose}>
          关闭
        </Button>
      }
    >
      <div className="flex min-h-0 flex-col gap-3">
        <div className="flex shrink-0 flex-wrap gap-2">
          <Badge variant="outline" className="rounded-full text-[11px]">
            {formatCount(batch.sourceTextCharCount ?? batch.actualUnits)} 字
          </Badge>
          <Badge variant="outline" className="rounded-full text-[11px]">
            {formatRange(batch)}
          </Badge>
          {batch.sourceTextTruncated ? (
            <Badge variant="outline" className="rounded-full text-[11px]">
              当前为截取内容
            </Badge>
          ) : null}
          {loading ? (
            <Badge variant="outline" className="rounded-full text-[11px]">
              <Loader2 className="size-3 animate-spin" />
              正在加载完整原文
            </Badge>
          ) : null}
        </div>
        {errorText ? (
          <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-700 dark:border-rose-400/25 dark:bg-rose-950/20 dark:text-rose-200">
            {errorText}
          </div>
        ) : null}
        <div className="max-h-[min(52dvh,520px)] min-h-[min(52dvh,520px)] overflow-y-auto rounded-xl border border-gray-200/70 bg-white/75 dark:border-white/10 dark:bg-white/[0.035]">
          <div className="p-4 text-sm leading-6 whitespace-pre-wrap text-gray-700 dark:text-gray-200">
            {loading && !content
              ? "正在加载完整资产原文..."
              : content || "没有可阅读的原文内容。"}
          </div>
        </div>
      </div>
    </ModalShell>
  )
}

function AssetSplitBatchAssetsPanel({
  batch,
  onOpenAsset,
}: {
  batch: AssetSplitBatch | null
  onOpenAsset: (asset: AssetSplitBatchAsset) => void
}) {
  if (!batch) {
    return (
      <section className="grid min-h-[260px] flex-1 place-items-center rounded-md border border-gray-200/70 bg-white/75 text-sm text-gray-500 shadow-sm dark:border-white/10 dark:bg-white/[0.04] dark:text-gray-400">
        请选择左侧资产原文
      </section>
    )
  }
  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-gray-200/70 bg-white/75 shadow-sm dark:border-white/10 dark:bg-white/[0.04]">
      <div className="shrink-0 border-b border-gray-200/70 px-4 py-3 dark:border-white/10">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
                对应资产
              </h3>
              <Badge variant="outline" className="rounded-full text-[11px]">
                {batch.totalAssetCount?.toLocaleString("zh-CN") ?? "0"} 个资产
              </Badge>
              {batch.newAssetCount ? (
                <TooltipWrap content="本阶段新增加的资产，不代表全部在线资产">
                  <Badge className="gap-1 rounded-full border-indigo-200 bg-indigo-50 text-[11px] text-indigo-700 hover:bg-indigo-50 dark:border-indigo-400/25 dark:bg-indigo-400/10 dark:text-indigo-200 dark:hover:bg-indigo-400/10">
                    <Sparkles className="size-3" />
                    本阶段新增 {batch.newAssetCount}
                  </Badge>
                </TooltipWrap>
              ) : null}
              {batch.orphanAssetIds?.length ? (
                <Badge
                  variant="outline"
                  className="rounded-full border-amber-200 bg-amber-50 text-[11px] text-amber-700 dark:border-amber-400/25 dark:bg-amber-950/25 dark:text-amber-200"
                >
                  缺失 {batch.orphanAssetIds.length}
                </Badge>
              ) : null}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
              <span>{batch.batchLabel || `第 ${batch.index} 次拆分`}</span>
              <span>阶段范围 {formatRange(batch)}</span>
              {batch.createdAt ? <span>{batch.createdAt}</span> : null}
            </div>
          </div>
          {batch.analysisStatus ? (
            <Badge
              variant="outline"
              className={cn(
                "rounded-full text-[11px]",
                analysisStatusTone(batch.analysisStatus)
              )}
            >
              {["failed", "cancelled", "canceled"].includes(
                batch.analysisStatus.trim().toLocaleLowerCase()
              ) ? (
                <AlertTriangle className="size-3" />
              ) : (
                <CheckCircle2 className="size-3" />
              )}
              {batch.analysisStatus}
            </Badge>
          ) : null}
        </div>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-4 p-4">
          {ASSET_SPLIT_GROUPS.map((group) => {
            const rows = batch.assets?.[group.id] ?? []
            return (
              <AssetGroupRows
                key={group.id}
                label={group.label}
                Icon={group.Icon}
                rows={rows}
                onOpenAsset={onOpenAsset}
              />
            )
          })}
        </div>
      </ScrollArea>
    </section>
  )
}

function AssetGroupRows({
  label,
  Icon,
  rows,
  onOpenAsset,
}: {
  label: string
  Icon: LucideIcon
  rows: AssetSplitBatchAsset[]
  onOpenAsset: (asset: AssetSplitBatchAsset) => void
}) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="grid size-6 place-items-center rounded-md border border-gray-200 bg-gray-50 text-gray-500 dark:border-white/10 dark:bg-white/[0.055] dark:text-gray-300">
          <Icon className="size-3.5" />
        </span>
        <span className="text-xs font-semibold text-gray-700 dark:text-gray-200">
          {label}
        </span>
        <span className="text-[11px] text-gray-400 dark:text-gray-500">
          {rows.length.toLocaleString("zh-CN")}
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="rounded-md border border-dashed border-gray-200/80 px-3 py-2 text-xs text-gray-400 dark:border-white/10 dark:text-gray-500">
          本批次未拆出{label}资产
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {rows.map((asset) => (
            <AssetRecordRow
              key={asset.id || asset.name}
              asset={asset}
              onOpen={() => onOpenAsset(asset)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function AssetRecordRow({
  asset,
  onOpen,
}: {
  asset: AssetSplitBatchAsset
  onOpen: () => void
}) {
  const thumbnailSrc = mediaPreviewSrc(asset.media)
  const offline = assetLifecycle(asset) === "offline"
  const createdInRange = asset.createdInRange === true
  return (
    <button
      type="button"
      className="flex w-full min-w-0 gap-3 rounded-md bg-slate-50/80 p-2.5 text-left transition-colors hover:bg-slate-100/80 focus-visible:ring-2 focus-visible:ring-indigo-300 focus-visible:outline-none dark:bg-white/[0.035] dark:hover:bg-white/[0.06]"
      onClick={onOpen}
    >
      <div
        className={cn(
          "grid aspect-video w-[104px] shrink-0 place-items-center overflow-hidden rounded-md border text-gray-400",
          offline
            ? "border-slate-200 bg-slate-100 dark:border-white/10 dark:bg-white/[0.06]"
            : "border-indigo-100 bg-indigo-50 dark:border-indigo-400/20 dark:bg-indigo-400/10"
        )}
      >
        {thumbnailSrc ? (
          <img
            src={thumbnailSrc}
            alt={asset.name}
            className="h-full w-full object-cover"
          />
        ) : offline ? (
          <Archive className="size-5" />
        ) : (
          <FileText className="size-5" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-gray-950 dark:text-gray-50">
            {asset.name || "未命名资产"}
          </span>
          {createdInRange ? (
            <TooltipWrap content="本阶段新增加的资产">
              <Badge
                variant="outline"
                aria-label="本阶段新增"
                className="h-5 shrink-0 gap-1 rounded-md border-indigo-200 bg-indigo-50 px-1.5 text-[10px] font-medium text-indigo-700 dark:border-indigo-400/30 dark:bg-indigo-400/10 dark:text-indigo-200"
              >
                <Sparkles className="size-2.5" />
                新增
              </Badge>
            </TooltipWrap>
          ) : null}
          {offline ? (
            <span
              aria-label="已下线"
              className="size-2 shrink-0 rounded-full bg-slate-400"
            />
          ) : (
            <span
              aria-label="在线"
              className="size-2 shrink-0 rounded-full bg-emerald-500"
            />
          )}
        </div>
        {asset.desc ? (
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-gray-500 dark:text-gray-400">
            {asset.desc}
          </p>
        ) : null}
      </div>
    </button>
  )
}

const ASSET_DETAIL_FIELD_LABELS: Record<string, string> = {
  offlineAt: "下线时间",
  offline_at: "下线时间",
  designRationale: "拆分理由",
  design_rationale: "拆分理由",
  assetImagePrompt: "设计图提示词",
  asset_image_prompt: "设计图提示词",
  "prompts.assetImagePrompt": "设计图提示词",
  voiceStyle: "声音提示词",
  voice_style: "声音提示词",
  sourceRefs: "原文证据",
  source_refs: "原文证据",
  visualSpec: "视觉规格",
  visual_spec: "视觉规格",
  continuity: "连续性",
  prompts: "其他提示词",
}

type AssetDetailValueTransform = (
  value: unknown,
  asset: AssetSplitBatchAsset
) => unknown

type AssetDetailEntryVariant = "text" | "prompt" | "evidence"

type AssetDetailFieldSpec = {
  key: string
  label?: string
  aliases?: string[]
  showFalse?: boolean
  variant?: AssetDetailEntryVariant
  transform?: AssetDetailValueTransform
}

const ASSET_DETAIL_VISUAL_FIELDS: AssetDetailFieldSpec[] = [
  { key: "visualSpec", aliases: ["visual_spec"], variant: "text" },
  { key: "continuity", variant: "text" },
]

const ASSET_DETAIL_RATIONALE_FIELDS: AssetDetailFieldSpec[] = [
  {
    key: "designRationale",
    aliases: ["design_rationale"],
    variant: "text",
  },
  {
    key: "sourceRefs",
    aliases: ["source_refs"],
    label: "原文证据",
    variant: "evidence",
    transform: sourceRefsDetailValue,
  },
]

const ASSET_DETAIL_TEXT_PREVIEW_LIMIT = 6000

function assetFieldValue(asset: AssetSplitBatchAsset, key: string) {
  return (asset as Record<string, unknown>)[key]
}

type AssetDetailEntry = {
  key: string
  label: string
  value: unknown
  variant: AssetDetailEntryVariant
}

type AssetDetailNotice = {
  key: string
  label: string
  value: unknown
  tone?: "neutral" | "warning" | "danger"
}

type AssetSourceEvidence = {
  key: string
  range?: string
  preview: string
}

function hasAssetField(asset: AssetSplitBatchAsset, key: string) {
  return Object.prototype.hasOwnProperty.call(asset, key)
}

function isRecordValue(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function hasMeaningfulValue(
  value: unknown,
  options: { showFalse?: boolean } = {}
): boolean {
  if (value === null || value === undefined) return false
  if (typeof value === "string") return value.trim().length > 0
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === "object") {
    return Object.values(value).some((item) =>
      hasMeaningfulValue(item, options)
    )
  }
  if (typeof value === "boolean") return value || Boolean(options.showFalse)
  return true
}

function sameDetailValue(left: unknown, right: unknown) {
  try {
    return JSON.stringify(left) === JSON.stringify(right)
  } catch {
    return String(left) === String(right)
  }
}

function firstMeaningfulRecordValue(
  record: Record<string, unknown>,
  keys: string[]
) {
  for (const key of keys) {
    const value = record[key]
    if (hasMeaningfulValue(value)) return value
  }
  return undefined
}

function currentAssetImagePrompt(asset: AssetSplitBatchAsset) {
  const topPrompt = assetFieldValue(asset, "assetImagePrompt")
  if (hasMeaningfulValue(topPrompt)) return topPrompt
  const snakePrompt = assetFieldValue(asset, "asset_image_prompt")
  if (hasMeaningfulValue(snakePrompt)) return snakePrompt
  const promptRecord = isRecordValue(asset.prompts) ? asset.prompts : null
  return promptRecord?.assetImagePrompt ?? promptRecord?.asset_image_prompt
}

function sourceRefsDetailValue(value: unknown) {
  if (!Array.isArray(value)) return value
  return value
    .map((item, index): AssetSourceEvidence | null => {
      if (!isRecordValue(item)) return null
      const explicitRange = firstMeaningfulRecordValue(item, [
        "rangeLabel",
        "sourceRangeLabel",
        "source_range_label",
      ])
      const start = firstMeaningfulRecordValue(item, [
        "absoluteStart",
        "startOffset",
        "start",
      ])
      const end = firstMeaningfulRecordValue(item, [
        "absoluteEnd",
        "endOffset",
        "end",
      ])
      const preview = firstMeaningfulRecordValue(item, [
        "sourcePreview",
        "preview",
        "text",
      ])
      const generatedRange =
        hasMeaningfulValue(start) || hasMeaningfulValue(end)
          ? `${start ?? "?"}-${end ?? "?"}`
          : ""
      const range = String(explicitRange ?? generatedRange).trim()
      const previewText = String(preview ?? "").trim()
      if (!previewText) return null
      return {
        key: `source-ref-${index}`,
        range,
        preview: previewText,
      }
    })
    .filter((item): item is AssetSourceEvidence => Boolean(item))
}

function assetStatusEntries(
  asset: AssetSplitBatchAsset,
  hasThumbnail: boolean
): AssetDetailNotice[] {
  const entries: AssetDetailNotice[] = []
  if (!hasThumbnail) {
    entries.push({
      key: "media.missing",
      label: "设计图状态",
      value: "未生成设计图",
      tone: "warning",
    })
  }
  const versions = Array.isArray(asset.mediaVersions) ? asset.mediaVersions : []
  if (versions.length > 1) {
    const activeVersionId = String(asset.activeMediaVersionId ?? "").trim()
    const activeIndex = versions.findIndex(
      (version) =>
        isRecordValue(version) && String(version.id ?? "") === activeVersionId
    )
    entries.push({
      key: "mediaVersions.summary",
      label: "设计图版本",
      value:
        activeIndex >= 0
          ? `共有 ${versions.length} 版，当前第 ${activeIndex + 1} 版`
          : `共有 ${versions.length} 版`,
      tone: "neutral",
    })
  }
  const offlineAt =
    assetFieldValue(asset, "offlineAt") || assetFieldValue(asset, "offline_at")
  if (assetLifecycle(asset) === "offline" && hasMeaningfulValue(offlineAt)) {
    entries.push({
      key: "offlineAt",
      label: "下线时间",
      value: offlineAt,
      tone: "neutral",
    })
  }
  const generation = assetFieldValue(asset, "generation")
  if (isRecordValue(generation)) {
    const status = firstMeaningfulRecordValue(generation, ["status", "state"])
    const error = firstMeaningfulRecordValue(generation, [
      "error",
      "errorText",
      "message",
      "reason",
    ])
    const statusText = String(status ?? "")
      .trim()
      .toLocaleLowerCase()
    const abnormal =
      ["failed", "error", "cancelled", "canceled"].includes(statusText) ||
      hasMeaningfulValue(error)
    if (abnormal) {
      entries.push({
        key: "generation.failure",
        label: "生成异常",
        value: [status, error]
          .filter((item) => hasMeaningfulValue(item))
          .join("："),
        tone: "danger",
      })
    }
  }
  return entries
}

function fieldLabel(key: string, label?: string) {
  return label || ASSET_DETAIL_FIELD_LABELS[key] || key
}

function assetDetailEntry(
  asset: AssetSplitBatchAsset,
  spec: AssetDetailFieldSpec
): AssetDetailEntry | null {
  const keys = [spec.key, ...(spec.aliases ?? [])]
  for (const key of keys) {
    if (!hasAssetField(asset, key)) continue
    const rawValue = assetFieldValue(asset, key)
    const value = spec.transform ? spec.transform(rawValue, asset) : rawValue
    if (hasMeaningfulValue(value, { showFalse: spec.showFalse })) {
      return {
        key,
        label: fieldLabel(spec.key, spec.label),
        value,
        variant: spec.variant ?? "text",
      }
    }
  }
  return null
}

function assetDetailEntries(
  asset: AssetSplitBatchAsset,
  specs: AssetDetailFieldSpec[]
): AssetDetailEntry[] {
  return specs.flatMap((spec) => {
    const entry = assetDetailEntry(asset, spec)
    return entry ? [entry] : []
  })
}

function assetPromptEntries(asset: AssetSplitBatchAsset) {
  const entries: AssetDetailEntry[] = []
  const promptRecord = isRecordValue(asset.prompts)
    ? { ...asset.prompts }
    : null
  const topImagePrompt = currentAssetImagePrompt(asset)
  const nestedImagePrompt = promptRecord?.assetImagePrompt
  const nestedSnakeImagePrompt = promptRecord?.asset_image_prompt
  const hasTopImagePrompt = hasMeaningfulValue(topImagePrompt)
  const hasNestedImagePrompt =
    hasMeaningfulValue(nestedImagePrompt) ||
    hasMeaningfulValue(nestedSnakeImagePrompt)
  if (hasTopImagePrompt) {
    entries.push({
      key: "assetImagePrompt",
      label: fieldLabel("assetImagePrompt"),
      value: topImagePrompt,
      variant: "prompt",
    })
  }
  if (
    hasNestedImagePrompt &&
    (!hasTopImagePrompt ||
      !sameDetailValue(
        topImagePrompt,
        nestedImagePrompt ?? nestedSnakeImagePrompt
      ))
  ) {
    entries.push({
      key: "prompts.assetImagePrompt",
      label: fieldLabel("prompts.assetImagePrompt"),
      value: nestedImagePrompt ?? nestedSnakeImagePrompt,
      variant: "prompt",
    })
  }
  if (promptRecord) {
    delete promptRecord.assetImagePrompt
    delete promptRecord.asset_image_prompt
  }
  const voiceStyle =
    assetFieldValue(asset, "voiceStyle") ||
    assetFieldValue(asset, "voice_style")
  const hasVoiceStyle = hasMeaningfulValue(voiceStyle)
  if (hasVoiceStyle) {
    entries.push({
      key: "voiceStyle",
      label: fieldLabel("voiceStyle"),
      value: voiceStyle,
      variant: "prompt",
    })
    if (promptRecord && sameDetailValue(promptRecord.voiceStyle, voiceStyle)) {
      delete promptRecord.voiceStyle
    }
    if (promptRecord && sameDetailValue(promptRecord.voice_style, voiceStyle)) {
      delete promptRecord.voice_style
    }
  }
  const canSpeak =
    assetFieldValue(asset, "canSpeak") ?? assetFieldValue(asset, "can_speak")
  if (promptRecord && sameDetailValue(promptRecord.canSpeak, canSpeak)) {
    delete promptRecord.canSpeak
  }
  if (promptRecord && sameDetailValue(promptRecord.can_speak, canSpeak)) {
    delete promptRecord.can_speak
  }
  if (promptRecord && hasMeaningfulValue(promptRecord)) {
    entries.push({
      key: "prompts",
      label: fieldLabel("prompts"),
      value: promptRecord,
      variant: "prompt",
    })
  }
  return entries
}

function detailStringPreview(value: string) {
  if (value.length <= ASSET_DETAIL_TEXT_PREVIEW_LIMIT) return value
  const hiddenCount = value.length - ASSET_DETAIL_TEXT_PREVIEW_LIMIT
  return `${value.slice(
    0,
    ASSET_DETAIL_TEXT_PREVIEW_LIMIT
  )}\n...（已截断 ${formatCount(hiddenCount)} 个字符）`
}

function scalarPreview(value: unknown) {
  if (value === undefined || value === null) return ""
  if (typeof value === "boolean") return value ? "是" : "否"
  if (typeof value === "string") {
    const text = value.trim()
    return text.length > 0 ? detailStringPreview(text) : ""
  }
  return String(value)
}

function readableInlineValue(value: unknown): string {
  if (!hasMeaningfulValue(value)) return ""
  if (Array.isArray(value)) {
    return value.map(readableInlineValue).filter(Boolean).join("、")
  }
  if (isRecordValue(value)) {
    return Object.entries(value)
      .filter(([, nestedValue]) => hasMeaningfulValue(nestedValue))
      .map(
        ([key, nestedValue]) =>
          `${fieldLabel(key)}：${readableInlineValue(nestedValue)}`
      )
      .filter(Boolean)
      .join("；")
  }
  return scalarPreview(value)
}

function readableDetailValue(value: unknown): string {
  if (!hasMeaningfulValue(value)) return ""
  if (Array.isArray(value)) {
    return value
      .map((item, index) => {
        const text = readableInlineValue(item)
        return text ? `${index + 1}. ${text}` : ""
      })
      .filter(Boolean)
      .join("\n")
  }
  if (isRecordValue(value)) {
    return Object.entries(value)
      .filter(([, nestedValue]) => hasMeaningfulValue(nestedValue))
      .map(
        ([key, nestedValue]) =>
          `${fieldLabel(key)}：${readableInlineValue(nestedValue)}`
      )
      .filter(Boolean)
      .join("\n")
  }
  return scalarPreview(value)
}

function fullAssetDataJson(asset: AssetSplitBatchAsset) {
  try {
    return JSON.stringify(asset, null, 2) || ""
  } catch {
    return String(asset)
  }
}

function isEvidenceList(value: unknown): value is AssetSourceEvidence[] {
  return (
    Array.isArray(value) &&
    value.every(
      (item) =>
        isRecordValue(item) &&
        typeof item.key === "string" &&
        typeof item.preview === "string"
    )
  )
}

function noticeToneClass(tone: AssetDetailNotice["tone"]) {
  if (tone === "danger") {
    return "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-400/25 dark:bg-rose-950/20 dark:text-rose-200"
  }
  if (tone === "warning") {
    return "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-400/25 dark:bg-amber-950/25 dark:text-amber-200"
  }
  return "border-slate-200 bg-slate-50 text-slate-600 dark:border-white/10 dark:bg-white/[0.06] dark:text-slate-300"
}

function AssetSplitAssetDetailDialog({
  asset,
  onClose,
}: {
  asset: AssetSplitBatchAsset
  onClose: () => void
}) {
  const promptEntries = assetPromptEntries(asset)
  const rationaleEntries = assetDetailEntries(
    asset,
    ASSET_DETAIL_RATIONALE_FIELDS
  )
  const visualEntries = assetDetailEntries(asset, ASSET_DETAIL_VISUAL_FIELDS)
  const thumbnailSrc = mediaPreviewSrc(asset.media)
  const statusEntries = assetStatusEntries(asset, Boolean(thumbnailSrc))
  const assetType = String(
    asset.assetType || assetFieldValue(asset, "asset_type") || "未知类型"
  )
  return (
    <ModalShell
      title={asset.name || "资产详情"}
      className="h-auto max-h-[calc(100dvh-1.5rem)] max-w-[1360px] sm:max-h-[calc(100dvh-3rem)]"
      scrollClassName="flex-none max-h-[calc(100dvh-11rem)]"
      bodyClassName="space-y-4"
      onClose={onClose}
      footer={
        <Button type="button" variant="outline" onClick={onClose}>
          关闭
        </Button>
      }
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
        <div className="min-w-0 space-y-4">
          <div
            className={cn(
              "grid gap-4 rounded-md border border-gray-200/70 bg-slate-50/70 p-3 dark:border-white/10 dark:bg-black/15",
              thumbnailSrc
                ? "sm:grid-cols-[260px_minmax(0,1fr)]"
                : "grid-cols-1"
            )}
          >
            {thumbnailSrc ? (
              <div className="aspect-video w-full overflow-hidden rounded-md border border-gray-200/70 bg-slate-50 dark:border-white/10 dark:bg-white/[0.035]">
                <img
                  src={thumbnailSrc}
                  alt={asset.name}
                  className="h-full w-full object-cover"
                />
              </div>
            ) : null}
            <div className="min-w-0">
              <div className="flex flex-wrap gap-2">
                <Badge variant="outline" className="rounded-full text-[11px]">
                  {assetType}
                </Badge>
                <Badge variant="outline" className="rounded-full text-[11px]">
                  {assetLifecycle(asset) === "offline" ? "下线" : "活跃"}
                </Badge>
              </div>
              {asset.desc ? (
                <div className="mt-3">
                  <div className="mb-1 text-xs font-semibold text-gray-700 dark:text-gray-200">
                    描述
                  </div>
                  <p className="text-sm leading-6 whitespace-pre-wrap text-gray-700 dark:text-gray-200">
                    {asset.desc}
                  </p>
                </div>
              ) : null}
            </div>
          </div>
          <AssetDetailNoticeBar entries={statusEntries} />
          <div className="space-y-4">
            <AssetDetailSection title="拆分依据" entries={rationaleEntries} />
            <AssetDetailSection title="生成提示词" entries={promptEntries} />
            <AssetDetailSection title="视觉与连续性" entries={visualEntries} />
          </div>
        </div>
        <AssetRawDataColumn asset={asset} />
      </div>
    </ModalShell>
  )
}

function AssetRawDataColumn({ asset }: { asset: AssetSplitBatchAsset }) {
  return (
    <aside className="min-w-0 self-start rounded-md border border-gray-200/70 bg-slate-950 text-slate-100 dark:border-white/10">
      <div className="border-b border-white/10 px-3 py-2">
        <div className="text-xs font-semibold">完整数据</div>
      </div>
      <pre className="max-h-[min(62dvh,680px)] overflow-auto p-3 font-mono text-[11px] leading-5 whitespace-pre text-slate-100">
        {fullAssetDataJson(asset)}
      </pre>
    </aside>
  )
}

function AssetDetailNoticeBar({ entries }: { entries: AssetDetailNotice[] }) {
  if (entries.length === 0) return null
  return (
    <div className="flex flex-wrap gap-2">
      {entries.map((entry) => (
        <span
          key={entry.key}
          className={cn(
            "inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px]",
            noticeToneClass(entry.tone)
          )}
        >
          <span className="shrink-0 font-medium">{entry.label}</span>
          <span className="min-w-0 truncate">{scalarPreview(entry.value)}</span>
        </span>
      ))}
    </div>
  )
}

function AssetDetailSection({
  title,
  entries,
}: {
  title: string
  entries: AssetDetailEntry[]
}) {
  if (entries.length === 0) return null
  return (
    <section>
      <h4 className="mb-2 text-xs font-semibold text-gray-700 dark:text-gray-200">
        {title}
      </h4>
      <div className="grid gap-2">
        {entries.map((entry) => {
          if (entry.variant === "evidence") {
            return (
              <AssetEvidenceField
                key={entry.key}
                label={entry.label}
                value={entry.value}
              />
            )
          }
          return <AssetDetailField key={entry.key} entry={entry} />
        })}
      </div>
    </section>
  )
}

function AssetEvidenceField({
  label,
  value,
}: {
  label: string
  value: unknown
}) {
  if (!isEvidenceList(value)) {
    return (
      <AssetDetailField entry={{ key: label, label, value, variant: "text" }} />
    )
  }
  return (
    <div className="rounded-md border border-gray-200/70 bg-white/70 p-3 dark:border-white/10 dark:bg-white/[0.035]">
      <div className="mb-2 text-xs font-semibold text-gray-700 dark:text-gray-200">
        {label}
      </div>
      <div className="space-y-2">
        {value.map((item, index) => (
          <div
            key={item.key}
            className="border-l-2 border-indigo-200 pl-2 dark:border-indigo-400/30"
          >
            <div className="mb-0.5 text-[11px] text-gray-400 dark:text-gray-500">
              {item.range || `证据 ${index + 1}`}
            </div>
            <p className="text-xs leading-5 break-words whitespace-pre-wrap text-gray-600 dark:text-gray-300">
              {item.preview}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}

function AssetDetailField({ entry }: { entry: AssetDetailEntry }) {
  const text = readableDetailValue(entry.value)
  if (!text) return null
  return (
    <div
      className={cn(
        "rounded-md border p-3",
        entry.variant === "prompt"
          ? "border-indigo-100 bg-indigo-50/45 dark:border-indigo-400/20 dark:bg-indigo-400/10"
          : "border-gray-200/70 bg-white/70 dark:border-white/10 dark:bg-white/[0.035]"
      )}
    >
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-gray-700 dark:text-gray-200">
          {entry.label}
        </span>
      </div>
      <div
        className="text-xs leading-5 break-words whitespace-pre-wrap text-gray-600 dark:text-gray-300"
        title={typeof entry.value === "string" ? entry.value : undefined}
      >
        {text}
      </div>
    </div>
  )
}
