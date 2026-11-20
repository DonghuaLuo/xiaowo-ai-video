import { Library, Loader2, Package, Plus, Search, WandSparkles } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { type AssetLifecycleView } from "./asset-gallery-cards"

export function AssetGalleryToolbar({
  title,
  count,
  query,
  onQueryChange,
  onAdd,
  onPick,
  onBulk,
  onGenerateAll,
  generatingAll,
  canGenerateAll,
  addLabel,
  scope,
  lifecycleView,
  onLifecycleViewChange,
}: {
  title: string
  count: number
  query: string
  onQueryChange: (value: string) => void
  onAdd: () => void
  onPick: () => void
  onBulk: () => void
  onGenerateAll: () => void
  generatingAll: boolean
  canGenerateAll: boolean
  addLabel: string
  scope: "global" | "project"
  lifecycleView: AssetLifecycleView
  onLifecycleViewChange: (value: AssetLifecycleView) => void
}) {
  const isProjectScope = scope === "project"
  const canAddAssets = isProjectScope && lifecycleView === "active"

  return (
    <div
      className={cn(
        "ai-video-toolbar-surface z-10 flex flex-wrap items-center gap-3 border-b border-gray-200/70 shadow-sm backdrop-blur-xl dark:border-white/10",
        isProjectScope
          ? "ai-video-edge-b min-h-14 shrink-0 px-4 py-2"
          : "sticky top-0 px-5 py-3"
      )}
    >
      <span className="h-3 w-[3px] rounded-full bg-gradient-to-b from-indigo-500 via-sky-500 to-emerald-400" />
      <div className="flex items-center gap-2 self-center">
        <h2 className="display-serif text-[15px] font-semibold tracking-tight text-gray-950 dark:text-gray-50">
          {title}
        </h2>
        <Badge
          variant="outline"
          className="flex h-5 items-center rounded-md border-indigo-200 bg-indigo-50/75 px-1.5 py-0 text-[10.5px] leading-none text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-200"
        >
          {String(count).padStart(2, "0")}
        </Badge>
      </div>
      {isProjectScope ? (
        <div className="flex h-8 items-center rounded-md border border-gray-200/80 bg-white/60 p-0.5 dark:border-white/10 dark:bg-white/[0.035]">
          {(["active", "offline"] as const).map((value) => {
            const selected = lifecycleView === value
            return (
              <button
                key={value}
                type="button"
                className={cn(
                  "h-7 rounded px-3 text-xs font-medium transition-colors",
                  selected
                    ? "bg-indigo-600 text-white shadow-sm dark:bg-indigo-500"
                    : "text-gray-500 hover:bg-gray-100/80 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-white/[0.07] dark:hover:text-white"
                )}
                onClick={() => onLifecycleViewChange(value)}
              >
                {value === "active" ? "活跃" : "下线"}
              </button>
            )
          })}
        </div>
      ) : null}
      <div className="relative w-[278px] min-w-[214px] shrink">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-gray-400" />
        <Input
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={`搜索${title}`}
          className="h-9 rounded-md border-gray-200/80 bg-white/70 pl-9 text-[12px] dark:border-white/10 dark:bg-white/[0.035]"
        />
      </div>
      <div className="flex-1" />
      {canAddAssets ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-9 gap-1.5 rounded-md bg-white/60 text-xs dark:bg-white/[0.035]"
          disabled={!canGenerateAll || generatingAll}
          onClick={onGenerateAll}
          title="生成当前列表中尚无设计图的资产，跳过已有设计图和正在生成的卡片"
        >
          {generatingAll ? <Loader2 className="size-3.5 animate-spin" /> : <WandSparkles className="size-3.5" />}
          {generatingAll ? "正在提交生成任务…" : "生成全部设计图"}
        </Button>
      ) : null}
      {canAddAssets ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-9 gap-1.5 rounded-md bg-white/60 text-xs dark:bg-white/[0.035]"
          onClick={onBulk}
        >
          <Package className="size-3.5" />
          批量加入全局资产
        </Button>
      ) : null}
      {canAddAssets ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-9 gap-1.5 rounded-md bg-white/60 text-xs dark:bg-white/[0.035]"
          onClick={onPick}
        >
          <Library className="size-3.5" />
          从全局资产选择
        </Button>
      ) : null}
      {canAddAssets ? (
        <Button
          type="button"
          size="sm"
          className="h-9 gap-1.5 rounded-md bg-gradient-to-r from-indigo-600 via-sky-600 to-emerald-500 px-4 text-xs text-white shadow-sm"
          onClick={onAdd}
        >
          <Plus className="size-3.5" />
          {addLabel}
        </Button>
      ) : null}
    </div>
  )
}
