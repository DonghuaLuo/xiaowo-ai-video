import { AssetGalleryPage } from "@/features/assets/asset-gallery"
import { assetTabs } from "@/features/asset-model"
import { cn } from "@/lib/utils"
import type { AssetTab } from "@/navigation"
import { PageHeader } from "@/shared/page-shell"

export function AssetLibraryPage({
  tab,
  onTabChange,
  onBack,
}: {
  tab: AssetTab
  onTabChange: (tab: AssetTab) => void
  onBack: () => void
}) {
  return (
    <main className="min-h-0 flex-1 overflow-hidden">
      <PageHeader
        eyebrow="Global Assets"
        title="全局资产"
        description="人物、场景、道具和收藏风格只提供故事版生成约束，不直接触发视频生成。"
        onBack={onBack}
      />
      <div className="flex h-full min-h-0">
        <nav className="ai-video-edge-r w-[230px] shrink-0 border-r border-gray-200/70 bg-white/45 px-3 py-5 dark:border-white/10 dark:bg-white/[0.035]">
          {assetTabs.map((item) => {
            const Icon = item.icon
            const active = item.id === tab
            return (
              <button
                key={item.id}
                type="button"
                className={cn(
                  "mb-1 flex w-full items-center gap-2.5 rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                  active
                    ? "border-indigo-200 bg-indigo-50/80 text-indigo-700 shadow-sm dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
                    : "border-transparent text-gray-500 hover:border-gray-200 hover:bg-white/65 hover:text-gray-950 dark:text-gray-400 dark:hover:border-white/10 dark:hover:bg-white/[0.05] dark:hover:text-gray-50"
                )}
                onClick={() => onTabChange(item.id)}
              >
                <Icon className="size-4" />
                {item.label}
              </button>
            )
          })}
        </nav>
        <AssetGalleryPage tab={tab} scope="global" />
      </div>
    </main>
  )
}
