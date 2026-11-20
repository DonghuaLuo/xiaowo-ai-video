import type { ReactNode } from "react"
import {
  BarChart3,
  Clapperboard,
  Film,
  Hash,
  LineChart,
  Plug,
  Sparkles,
} from "lucide-react"

import { ScrollArea } from "@/components/ui/scroll-area"
import type { SettingsSection } from "@/navigation"
import { cn } from "@/lib/utils"
import { PageHeader } from "@/shared/page-shell"

const settingsGroups: Array<{
  title: string
  items: Array<{
    id: SettingsSection
    label: string
    icon: typeof Plug
  }>
}> = [
  {
    title: "Configuration",
    items: [
      { id: "providers", label: "供应商", icon: Plug },
      { id: "media", label: "模型配置", icon: Film },
      { id: "script-adaptation-templates", label: "片段剧本策略", icon: Sparkles },
      { id: "director-rules", label: "导演规则", icon: Clapperboard },
      { id: "text-replacement-templates", label: "提示词替换规则", icon: Hash },
      { id: "storyboard-templates", label: "分镜图版式", icon: Film },
    ],
  },
  {
    title: "Insight",
    items: [
      { id: "quality", label: "质量分析", icon: LineChart },
      { id: "usage", label: "用量统计", icon: BarChart3 },
    ],
  },
]

export function SettingsPage({
  section,
  onSectionChange,
  onBack,
  children,
}: {
  section: SettingsSection
  onSectionChange: (section: SettingsSection) => void
  onBack: () => void
  children: ReactNode
}) {
  return (
    <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <PageHeader
        eyebrow="Control Booth"
        title="全局设置"
        description="管理供应商、模型配置、片段剧本策略、导演规则、提示词替换规则、分镜图版式、质量和用量。"
        onBack={onBack}
      />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <SettingsSidebar section={section} onSectionChange={onSectionChange} />
        <ScrollArea className="min-w-0 flex-1">
          <div className="w-full space-y-5 px-7 py-6">{children}</div>
        </ScrollArea>
      </div>
    </main>
  )
}

function SettingsSidebar({
  section,
  onSectionChange,
}: {
  section: SettingsSection
  onSectionChange: (section: SettingsSection) => void
}) {
  return (
    <nav className="h-full w-[230px] shrink-0 border-x border-white/60 bg-white/45 px-3 py-5 dark:border-white/10 dark:bg-white/[0.035]">
      {settingsGroups.map((group, groupIndex) => (
        <div key={group.title} className={groupIndex > 0 ? "mt-6" : undefined}>
          <div className="mb-2 px-3 font-mono text-[10px] font-bold tracking-[0.16em] text-gray-400 uppercase dark:text-gray-500">
            {group.title}
          </div>
          <div className="space-y-1">
            {group.items.map((item) => {
              const Icon = item.icon
              const active = section === item.id
              return (
                <button
                  key={item.id}
                  type="button"
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                    active
                      ? "border-indigo-200 bg-indigo-50/80 text-indigo-700 shadow-sm dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
                      : "border-transparent text-gray-500 hover:border-gray-200 hover:bg-white/65 hover:text-gray-950 dark:text-gray-400 dark:hover:border-white/10 dark:hover:bg-white/[0.05] dark:hover:text-gray-50"
                  )}
                  onClick={() => onSectionChange(item.id)}
                >
                  <Icon className="size-4" />
                  <span className="min-w-0 flex-1 truncate">{item.label}</span>
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </nav>
  )
}
