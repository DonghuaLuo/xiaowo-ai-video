import { useCallback, useEffect, useState } from "react"
import { CircleDollarSign, RefreshCcw } from "lucide-react"
import { toast } from "sonner"

import { getUsageSummary, type UsageSummary } from "@/backend"
import { Button } from "@/components/ui/button"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import { formatCurrency } from "@/shared/format"
import { SectionPanel } from "@/shared/page-shell"

type StatItem = {
  label: string
  value: string | number
  caption?: string
  className: string
}

function MiniStatGrid({
  stats,
  className,
}: {
  stats: StatItem[]
  className?: string
}) {
  return (
    <div className={cn("grid grid-cols-2 gap-3 lg:grid-cols-4", className)}>
      {stats.map((item) => (
        <div
          key={item.label}
          className="rounded-xl border border-gray-200/70 bg-white/70 px-4 py-3 shadow-sm dark:border-white/10 dark:bg-white/[0.045]"
        >
          <div
            className={cn(
              "font-mono text-[26px] leading-none font-semibold tabular-nums",
              item.className
            )}
          >
            {item.value}
          </div>
          <div className="mt-1 text-xs font-semibold text-gray-950 dark:text-gray-50">
            {item.label}
          </div>
          {item.caption ? (
            <div className="mt-1 truncate text-[11px] text-gray-500 dark:text-gray-400">
              {item.caption}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  )
}

export function QualitySettings() {
  return (
    <SectionPanel
      eyebrow="Quality"
      title="质量分析"
      description="统计故事版计划、大图、视频三段成功率，并记录失败跳转目标。"
    >
      <MiniStatGrid
        stats={[
          {
            label: "计划成功率",
            value: "96%",
            caption: "近 30 天",
            className: "text-emerald-600 dark:text-emerald-300",
          },
          {
            label: "大图成功率",
            value: "91%",
            caption: "OpenAI gpt-image-2",
            className: "text-sky-600 dark:text-sky-300",
          },
          {
            label: "视频成功率",
            value: "88%",
            caption: "Seedance 2.0",
            className: "text-violet-600 dark:text-violet-300",
          },
          {
            label: "失败跳转",
            value: "12",
            caption: "可定位节点",
            className: "text-amber-600 dark:text-amber-300",
          },
        ]}
      />
    </SectionPanel>
  )
}

export function UsageSettings() {
  const { backendReady, callBackend } = useBackend()
  const [usage, setUsage] = useState<UsageSummary | null>(null)
  const [loading, setLoading] = useState(false)

  const loadUsage = useCallback(async () => {
    if (!backendReady) return
    setLoading(true)
    try {
      setUsage(await getUsageSummary(callBackend))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "用量统计加载失败")
    } finally {
      setLoading(false)
    }
  }, [backendReady, callBackend])

  useEffect(() => {
    void loadUsage()
  }, [loadUsage])

  const rows = [
    ["本月成本", formatCurrency(usage?.monthCost ?? 0), "全局模型用量统计"],
    [
      "资产设计图",
      String(usage?.assetImages ?? 0),
      "角色/生物/场景/道具图片生成次数",
    ],
    ["故事版大图", String(usage?.storyboardImages ?? 0), "图片生成任务次数"],
    ["故事版视频", String(usage?.storyboardVideos ?? 0), "视频生成任务次数"],
    ["失败任务", String(usage?.failedTasks ?? 0), "需要诊断的任务数"],
  ] as const

  return (
    <SectionPanel
      eyebrow="Usage"
      title="用量统计"
      description="按项目、供应商、模型和任务类型统计成本，突出故事版大图与 Seedance 视频成本。"
    >
      <div className="mb-4 flex justify-end">
        <Button
          variant="outline"
          size="sm"
          onClick={loadUsage}
          disabled={loading}
        >
          <RefreshCcw
            className={cn("mr-2 size-4", loading && "animate-spin")}
          />
          刷新
        </Button>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {rows.map(([title, value, desc]) => (
          <div
            key={title}
            className="rounded-xl border border-gray-200/70 bg-white/70 p-4 dark:border-white/10 dark:bg-white/[0.035]"
          >
            <CircleDollarSign className="size-5 text-emerald-600 dark:text-emerald-300" />
            <div className="mt-3 font-mono text-[28px] leading-none font-semibold text-gray-950 dark:text-gray-50">
              {loading ? "..." : value}
            </div>
            <h3 className="mt-2 text-sm font-semibold text-gray-950 dark:text-gray-50">
              {title}
            </h3>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              {desc}
            </p>
          </div>
        ))}
      </div>
    </SectionPanel>
  )
}
