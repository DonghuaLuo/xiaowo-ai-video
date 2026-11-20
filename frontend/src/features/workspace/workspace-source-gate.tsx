import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  Loader2,
  Upload,
  WandSparkles,
} from "lucide-react"
import { listSources, replaceSources } from "@/backend"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import type { ProjectRow } from "@/features/projects/types"
import { projectOverviewReady } from "@/features/workspace/project-readiness"
import { SectionPanel } from "@/shared/page-shell"
import { errMsg } from "@/shared/backend-result"
import {
  getProjectOverviewAnalysisState,
  runProjectOverviewAnalysis,
  useProjectOverviewAnalysisState,
} from "./project-overview-analysis"
import {
  readNovelTextFiles,
  sourceCollectionName,
  type SourceFile,
} from "./workspace-source-model"


type NovelGatePhase =
  | "loading"
  | "idle"
  | "has_source"
  | "uploading"
  | "analyzing"

export function NovelSourceGate({
  project,
  onAnalyzed,
}: {
  project: ProjectRow
  onAnalyzed: () => Promise<void>
}) {
  const { backendReady, callBackend } = useBackend()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const overviewAnalysisState = useProjectOverviewAnalysisState(project.id)
  const overviewAnalysisRunning = overviewAnalysisState.status === "running"
  const [phase, setPhase] = useState<NovelGatePhase>("loading")
  const [sourceName, setSourceName] = useState("")
  const [sourceCount, setSourceCount] = useState(0)
  const [sources, setSources] = useState<SourceFile[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [errorText, setErrorText] = useState("")

  useEffect(() => {
    let cancelled = false
    if (!backendReady) return
    setPhase("loading")
    void listSources(callBackend, project.id)
      .then((sources) => {
        if (cancelled) return
        setSources(sources)
        setSourceCount(sources.length)
        setSourceName(sourceCollectionName(sources))
        const nextPhase: NovelGatePhase =
          getProjectOverviewAnalysisState(project.id).status === "running"
            ? "analyzing"
            : sources.length > 0 && projectOverviewReady(project)
              ? "has_source"
              : "idle"
        setPhase(nextPhase)
        setErrorText("")
      })
      .catch((error) => {
        if (cancelled) return
        console.warn("加载源文件失败:", error)
        setErrorText(errMsg(error, "加载源文件失败"))
        setPhase("idle")
      })
    return () => {
      cancelled = true
    }
  }, [backendReady, callBackend, project.id])

  useEffect(() => {
    if (overviewAnalysisRunning) {
      setPhase("analyzing")
      setErrorText("")
      return
    }
    setPhase((current) =>
      current === "analyzing"
        ? sourceCount > 0 && projectOverviewReady(project)
          ? "has_source"
          : "idle"
        : current
    )
  }, [overviewAnalysisRunning, project, sourceCount])

  const handleAnalyze = useCallback(
    async (nextSources: SourceFile[] = sources) => {
      if (nextSources.length === 0) {
        const message = "请先添加小说文本"
        setErrorText(message)
        toast.error(message)
        return
      }
      setPhase("analyzing")
      setErrorText("")
      try {
        await runProjectOverviewAnalysis(callBackend, project.id)
        setSources(nextSources)
        setSourceName(sourceCollectionName(nextSources))
        setSourceCount(nextSources.length)
        setPhase("has_source")
        toast.success("小说概述分析完成")
        await onAnalyzed()
      } catch (error) {
        setSources(nextSources)
        setSourceName(sourceCollectionName(nextSources))
        setSourceCount(nextSources.length)
        setPhase("idle")
        const message = errMsg(error, "小说概述分析失败")
        setErrorText(message)
        toast.error(message)
      }
    },
    [callBackend, onAnalyzed, project.id, sources]
  )

  const handleSelectFiles = useCallback(
    async (files: FileList | File[] | null) => {
      const selectedFiles = Array.from(files ?? [])
      if (selectedFiles.length === 0) return
      if (selectedFiles.length > 1) {
        const message =
          "初次导入阶段只能选择一个小说总文件，后续章节请进入项目概览后从原文件列表追加"
        setErrorText(message)
        toast.error(message)
        return
      }
      setPhase("uploading")
      setErrorText("")
      try {
        const payloads = await readNovelTextFiles(selectedFiles)
        const nextSources = await replaceSources(
          callBackend,
          project.id,
          payloads
        )
        setSources(nextSources)
        setSourceName(sourceCollectionName(nextSources))
        setSourceCount(nextSources.length)
        toast.success("已添加小说总文件，开始自动分析")
        await handleAnalyze(nextSources)
      } catch (error) {
        setPhase(
          sourceCount > 0 && projectOverviewReady(project)
            ? "has_source"
            : "idle"
        )
        const message = errMsg(error, "添加小说文本失败")
        setErrorText(message)
        toast.error(message)
      } finally {
        if (inputRef.current) inputRef.current.value = ""
      }
    },
    [callBackend, handleAnalyze, project.id, sourceCount]
  )

  const busy =
    phase === "loading" || phase === "uploading" || phase === "analyzing"
  const hasSource = phase === "has_source" || sourceCount > 0
  const phaseView = {
    loading: {
      title: "正在检查源文件",
      desc: "读取当前项目中已上传的小说文本。",
      icon: Loader2,
    },
    idle: {
      title: "拖入或选择小说 .txt",
      desc: "初次导入只选择一个小说总文件。后续章节进入项目概览后从原文件列表追加。",
      icon: Upload,
    },
    has_source: {
      title: sourceName || "小说文本已就绪",
      desc: "小说总文件已就绪，可重新添加或开始分析概述。",
      icon: CheckCircle2,
    },
    uploading: {
      title: "正在保存小说文本",
      desc: "本次选择会替换项目中的小说总文件，并保留原始文本预览。",
      icon: Loader2,
    },
    analyzing: {
      title: "正在分析小说概述",
      desc: "正在合并小说文本、按配置截取正文，并生成项目概述。",
      icon: Loader2,
    },
  }[phase]
  const PhaseIcon = phaseView.icon
  const handleDropFiles = (files: FileList | File[]) => {
    setIsDragging(false)
    const txtFiles = Array.from(files).filter(
      (item) =>
        item.type === "text/plain" || item.name.toLowerCase().endsWith(".txt")
    )
    if (txtFiles.length === 0) {
      const message = "请拖入 .txt 小说文本"
      setErrorText(message)
      toast.error(message)
      return
    }
    void handleSelectFiles(txtFiles)
  }

  return (
    <SectionPanel
      eyebrow="Novel Source"
      title="选择小说文本"
      description="创建项目后先导入 .txt 小说正文，分析完成后进入完整项目概览。"
    >
      <div className="mx-auto max-w-4xl space-y-4">
        <div
          className={cn(
            "relative overflow-hidden rounded-2xl border border-dashed bg-white/70 p-8 text-center transition-colors dark:bg-white/[0.035]",
            isDragging
              ? "border-indigo-400 bg-indigo-50/80 shadow-[0_0_0_3px_rgb(99_102_241_/_0.14)] dark:border-indigo-700/70 dark:bg-indigo-950/25"
              : hasSource
                ? "border-emerald-200 dark:border-emerald-900/60"
                : "border-indigo-200 hover:border-indigo-300 dark:border-indigo-900/60"
          )}
          onDragOver={(event) => {
            if (busy) return
            event.preventDefault()
            setIsDragging(true)
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(event) => {
            event.preventDefault()
            if (busy) return
            handleDropFiles(event.dataTransfer.files)
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".txt,text/plain"
            className="sr-only"
            disabled={!backendReady || busy}
            onChange={(event) => {
              void handleSelectFiles(event.currentTarget.files)
            }}
          />
          <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-indigo-500/10 text-indigo-600 dark:text-indigo-300">
            <PhaseIcon
              className={cn(
                "size-6",
                (phase === "uploading" ||
                  phase === "loading" ||
                  phase === "analyzing") &&
                  "animate-spin"
              )}
            />
          </span>
          <span className="mt-4 block text-base font-semibold text-gray-950 dark:text-gray-50">
            {phaseView.title}
          </span>
          <span className="mx-auto mt-2 block max-w-xl text-sm leading-relaxed text-gray-500 dark:text-gray-400">
            {phaseView.desc}
          </span>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <Button
              variant="outline"
              className="h-10 gap-2 bg-white/55 dark:bg-white/5"
              disabled={!backendReady || busy}
              onClick={() => inputRef.current?.click()}
            >
              <Upload className="size-4" />
              添加小说文本
            </Button>
            <Button
              className="h-10 gap-2"
              disabled={!backendReady || !hasSource || busy}
              onClick={() => void handleAnalyze()}
            >
              {phase === "analyzing" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <WandSparkles className="size-4" />
              )}
              分析小说概述
            </Button>
          </div>
        </div>

        {errorText ? (
          <div className="rounded-2xl border border-amber-200/80 bg-amber-50/80 p-4 dark:border-amber-900/60 dark:bg-amber-950/25">
            <div className="flex items-start gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-200">
                <AlertTriangle className="size-4" />
              </span>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-amber-700 dark:text-amber-200">
                  自动分析失败
                </div>
                <p className="mt-1 text-sm leading-relaxed text-amber-700/85 dark:text-amber-200/85">
                  {errorText}
                </p>
              </div>
            </div>
          </div>
        ) : null}

        {sources.length > 0 ? (
          <div className="rounded-2xl border border-gray-200/70 bg-white/70 p-4 dark:border-white/10 dark:bg-white/[0.035]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-gray-950 dark:text-gray-50">
                  已上传源文件
                </div>
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  每次添加都会替换当前集合；概述分析会合并全部文本并同步项目状态。
                </p>
              </div>
              <Badge variant="outline" className="rounded-full text-[11px]">
                {sources.length} 个文本
              </Badge>
            </div>
            <div className="mt-3 grid gap-2">
              {sources.slice(0, 5).map((source) => (
                <div
                  key={source.id}
                  className="flex items-center gap-3 rounded-xl border border-gray-200/70 bg-white/75 px-3 py-2.5 text-sm dark:border-white/10 dark:bg-white/[0.035]"
                >
                  <FileText className="size-4 shrink-0 text-indigo-500" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold text-gray-950 dark:text-gray-50">
                      {source.title}
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-gray-500 dark:text-gray-400">
                      {source.wordCount.toLocaleString()} 字 ·{" "}
                      {source.createdAt}
                    </div>
                  </div>
                  <Badge variant="outline" className="rounded-full text-[11px]">
                    {source.status}
                  </Badge>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </SectionPanel>
  )
}
