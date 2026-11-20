import { useCallback, useEffect, useRef, useState } from "react"
import { CheckCircle2, CircleHelp, Loader2, XCircle } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import { backendFailureMessage, errMsg } from "@/shared/backend-result"
import { StoryboardCorrectionDialog, type StoryboardReportScope } from "./storyboard-correction-dialog"

type ShotCheck = {
  shotNo: number
  present?: boolean
  matchesDirectorPlan?: boolean
  note?: string
}

type ConsistencyState = {
  enabled: boolean
  checking: boolean
  report: ConsistencyReport | null
  error?: string
  loadError?: string
  correction?: { id: string; status: "running" | "completed" | "failed"; baseVersionId: string; versionId?: string; message?: string } | null
}

const tones = {
  passed: { card: "border-emerald-200 bg-emerald-50/40 dark:border-emerald-800/60 dark:bg-emerald-950/15", text: "text-emerald-700 dark:text-emerald-400", badge: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300" },
  failed: { card: "border-red-200 bg-red-50/40 dark:border-red-900/70 dark:bg-red-950/15", text: "text-red-700 dark:text-red-400", badge: "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300" },
  incomplete: { card: "border-gray-200/70 dark:border-white/10", text: "text-gray-500 dark:text-gray-400", badge: "bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-300" },
}

function shotState(shot: ShotCheck) {
  if (shot.present === false) return { tone: "failed" as const, label: "缺少画格", Icon: XCircle }
  if (shot.present === true && shot.matchesDirectorPlan === false) return { tone: "failed" as const, label: "不一致", Icon: XCircle }
  if (shot.present === true && shot.matchesDirectorPlan === true) return { tone: "passed" as const, label: "一致", Icon: CheckCircle2 }
  return { tone: "incomplete" as const, label: "未完成", Icon: CircleHelp }
}

type ConsistencyReport = {
  versionId: string
  status: string
  createdAt?: string
  blockers?: string[]
  warnings?: string[]
  visualInspection?: {
    expectedPanelCount: number
    observedPanelCount: number
    shotChecks?: ShotCheck[]
  }
}

export function useStoryboardConsistencyReport(
  projectId: string,
  episodeId: string,
  nodeId: string,
  versionId: string,
) {
  const { backendReady, callBackend, onBackendEvent } = useBackend()
  const scope = JSON.stringify([projectId, episodeId, nodeId, versionId])
  const [loaded, setLoaded] = useState<{ scope: string; state: ConsistencyState } | null>(null)
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => setRevision((value) => value + 1), [])

  useEffect(() => {
    if (!backendReady || !projectId || !episodeId || !nodeId || !versionId) return
    let cancelled = false
    let request = 0
    const load = async () => {
      const currentRequest = ++request
      try {
        const result = await callBackend<ConsistencyState & { success: boolean; message?: string }>(
          "get_storyboard_consistency_report", { projectId, episodeId, nodeId, versionId },
        )
        if (result.success === false) throw new Error(backendFailureMessage(result, "读取检查报告失败"))
        const report = result.report?.versionId === versionId ? result.report : null
        if (!cancelled && currentRequest === request) {
          setLoaded({ scope, state: { enabled: result.enabled, checking: result.checking, report, error: result.error, correction: result.correction } })
        }
      } catch (error) {
        if (!cancelled && currentRequest === request) {
          console.warn("读取分镜图一致性检查报告失败", error)
          setLoaded({ scope, state: { enabled: false, checking: false, report: null, loadError: "读取检查报告失败，请刷新报告重试。" } })
        }
      }
    }
    const unsubscribe = onBackendEvent("project_changed", (event) => {
      if (event?.projectId === projectId && (
        (event?.episodeId === episodeId && event?.nodeId === nodeId) || event?.action === "settings_saved"
      )) {
        void load()
      }
    })
    void load()
    return () => { cancelled = true; unsubscribe() }
  }, [backendReady, callBackend, onBackendEvent, projectId, episodeId, nodeId, versionId, scope, revision])

  return loaded?.scope === scope ? { ...loaded.state, refresh } : null
}

export function StoryboardConsistencyReportPanel({ state, scope }: { state: ConsistencyState & { refresh: () => void }; scope: StoryboardReportScope }) {
  const { callBackend } = useBackend()
  const [correctionOpen, setCorrectionOpen] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const retryingRef = useRef(false)
  const correctionRunning = state.correction?.status === "running"
  const { report, checking, error, loadError } = state
  const inspection = report?.visualInspection
  const passed = report?.status === "passed"
  const shotsByNumber = new Map((inspection?.shotChecks ?? []).map((shot) => [shot.shotNo, shot]))
  const shots = inspection ? Array.from({ length: Math.max(0, inspection.expectedPanelCount) }, (_, index): ShotCheck =>
    shotsByNumber.get(index + 1) ?? { shotNo: index + 1, note: "模型未返回此镜头的核验结果。" },
  ) : []
  const shotStates = shots.map(shotState)
  const inconclusive = report?.status === "inconclusive" || !inspection || shotStates.some((item) => item.tone === "incomplete")
  const label = loadError ? "读取失败" : checking || retrying ? "正在检查" : error ? "检查未完成" : !report ? "尚未检查" : inconclusive ? "检查未完成" : passed ? "检查通过" : "发现不一致"
  const tone = checking || retrying || !report || inconclusive || error ? "incomplete" : passed ? "passed" : "failed"
  const checkedNotes = new Set(shots.map((shot) => shot.note?.trim()).filter(Boolean))
  const blockers = [...new Set(report?.blockers ?? [])].filter((item) => !checkedNotes.has(item.trim()))
  const warnings = [...new Set(report?.warnings ?? [])].filter((item) => !checkedNotes.has(item.trim()) && !blockers.includes(item))
  const hasShotIssues = shotStates.some((item) => item.tone !== "passed")
  const matchingPanelCount = inspection?.expectedPanelCount === inspection?.observedPanelCount
  const checkedAt = report?.createdAt ? new Date(report.createdAt) : null
  const timeLabel = checkedAt && Number.isFinite(checkedAt.getTime()) ? checkedAt.toLocaleString("zh-CN", { hour12: false }) : ""
  const retry = async () => {
    if (retryingRef.current || checking || correctionRunning) return
    retryingRef.current = true
    setRetrying(true)
    try {
      const result = await callBackend<{ success: boolean }>("start_storyboard_consistency_check", scope)
      if (result.success === false) throw new Error(backendFailureMessage(result, "无法启动检查"))
    } catch (reason) {
      toast.error(errMsg(reason, "无法启动检查"))
    } finally {
      retryingRef.current = false
      setRetrying(false)
      state.refresh()
    }
  }

  return (
    <section aria-label="分镜脚本与分镜图一致性检查报告" className="flex min-h-0 flex-[0_1_42%] flex-col border-t border-gray-200/80 bg-white dark:border-white/10 dark:bg-[#18181b]">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 px-3 py-2">
        <h3 className="text-xs font-semibold text-gray-800 dark:text-gray-100">分镜脚本与分镜图一致性检查报告</h3>
        <div className="flex items-center gap-2">
          <span role="status" className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium", tones[tone].badge)}>{(checking || retrying) && <Loader2 className="size-3 animate-spin" />}{label}</span>
          {loadError ? <Button variant="outline" size="sm" className="h-6 px-2 text-xs" onClick={state.refresh}>刷新报告</Button>
            : correctionRunning ? <span role="status" className="flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400"><Loader2 className="size-3 animate-spin" />正在生成修正版</span>
            : !checking && !retrying && (error || !report || inconclusive) ? <Button variant="outline" size="sm" className="h-6 px-2 text-xs" onClick={() => void retry()}>{!report && !error ? "开始检查" : "重新检查"}</Button>
              : !checking && report?.status === "failed" && !inconclusive && !error && <Button variant="outline" size="sm" className="h-6 px-2 text-xs" onClick={() => setCorrectionOpen(true)}>修正分镜图</Button>}
        </div>
      </div>
      <div className="min-h-0 overflow-y-auto overscroll-contain px-3 pb-3 text-xs leading-relaxed text-gray-600 dark:text-gray-300">
        {state.correction?.status === "failed" && state.correction.baseVersionId === scope.versionId && <p role="alert" className="mb-2 text-red-600 dark:text-red-400">{state.correction.message}</p>}
        {loadError ? <p className="py-3">{loadError}</p> : checking || retrying ? (
          <p className="py-3" aria-live="polite">正在读取分镜图，并逐镜头核对分镜脚本……</p>
        ) : error ? <p className="py-3">{error}</p> : !report ? <p className="py-3">此版本暂无检查报告，可点击“开始检查”核对分镜脚本。开启自动检查后，新生成的分镜图会自动检查。</p> : <>
          <p className="text-[11px] text-gray-400 dark:text-gray-500">依据生成时的分镜脚本{timeLabel && ` · ${timeLabel}`}</p>
          {inspection && <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
            <span className={matchingPanelCount ? "" : tones.failed.text}>{matchingPanelCount ? `${inspection.observedPanelCount} 个画格` : `计划 ${inspection.expectedPanelCount} 格 · 识别 ${inspection.observedPanelCount} 格`}</span>
            <span className={tones.passed.text}>一致 {shotStates.filter((item) => item.tone === "passed").length}</span>
            {shotStates.some((item) => item.tone === "failed") && <span className={tones.failed.text}>不一致或缺失 {shotStates.filter((item) => item.tone === "failed").length}</span>}
            {shotStates.some((item) => item.tone === "incomplete") && <span className={tones.incomplete.text}>未完成 {shotStates.filter((item) => item.tone === "incomplete").length}</span>}
          </div>}
          {!!shots.length && <div className="mt-3 space-y-2">
            {shots.map((shot, index) => {
              const { tone: shotTone, label: shotLabel, Icon } = shotStates[index]
              return <div key={shot.shotNo} className={cn("rounded-md border px-2.5 py-2", tones[shotTone].card)}>
                <p className={cn("flex items-center gap-1.5 font-medium", tones[shotTone].text)}><Icon className="size-3.5 shrink-0" />镜头 {shot.shotNo} · {shotLabel}</p>
                {shot.note && <p className="mt-1 whitespace-pre-wrap break-words">{shot.note}</p>}
              </div>
            })}
          </div>}
          {blockers.length > 0 && <details className="mt-3" open={inconclusive || (!hasShotIssues && matchingPanelCount) ? true : undefined}>
            <summary className="cursor-pointer text-[11px] text-gray-500 dark:text-gray-400">{inconclusive ? "未完成原因" : "完整问题记录"}</summary>
            <ul className="mt-1 list-disc space-y-1 pl-4">{blockers.map((item, index) => <li key={index}>{item}</li>)}</ul>
          </details>}
          {warnings.length > 0 && (
            <div className="mt-3">
              <p className="font-medium">补充说明</p>
              <ul className="mt-1 list-disc space-y-1 pl-4">{warnings.map((item, index) => <li key={index}>{item}</li>)}</ul>
            </div>
          )}
        </>}
      </div>
      {correctionOpen && <StoryboardCorrectionDialog scope={scope} onClose={() => setCorrectionOpen(false)} onSubmitted={() => { setCorrectionOpen(false); state.refresh() }} />}
    </section>
  )
}
