import { PluginSDK } from "xiaowo-sdk"
import {
  AlertCircle,
  BadgeCheck,
  ArrowUpRight,
  ChevronRight,
  ClipboardList,
  Paperclip,
  Plug,
  Send,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { UnifiedMediaFrame } from "@/shared/unified-media-frame"
import {
  AssistantContentBlock,
  AssistantConfirmableCandidateBlock,
  AssistantRecommendationSelect,
  assistantActionFooterText,
  assistantToolDisplayName,
  assistantToolInputSummary,
} from "./assistant-session-normalization"
import { AssistantTaskProgressBlock } from "./assistant-activity"
import {
  AssistantActionFooterBlock,
  AssistantFormattedText,
} from "./assistant-formatted-text"

export function AssistantToolBlock({
  block,
  openNestedCards,
}: {
  block: Extract<AssistantContentBlock, { type: "tool_use" }>
  openNestedCards: boolean
}) {
  if (
    block.name === "TodoWrite" &&
    Array.isArray((block.input as { todos?: unknown[] } | undefined)?.todos) &&
    !block.is_error
  ) {
    const todos = (block.input as { todos: Array<{ status?: string }> }).todos
    const doneCount = todos.filter((todo) => todo.status === "completed").length
    return (
      <div className="overflow-hidden rounded-lg bg-emerald-50/55 px-2 py-1.5 text-[11.5px] text-emerald-800 dark:bg-emerald-950/18 dark:text-emerald-100">
        <div className="flex items-center justify-between gap-2">
          <span className="font-semibold">TodoWrite</span>
          <span className="font-mono text-[10px] text-emerald-600 dark:text-emerald-300">
            {doneCount}/{todos.length}
          </span>
        </div>
      </div>
    )
  }
  const inputText =
    block.input && Object.keys(block.input).length
      ? JSON.stringify(block.input, null, 2)
      : ""
  const displayName = assistantToolDisplayName(block.name)
  const summary = assistantToolInputSummary(block)
  const hasResult = block.result !== undefined
  return (
    <details
      key={openNestedCards ? "open" : "closed"}
      open={openNestedCards || undefined}
      className="group overflow-hidden rounded-lg border border-slate-200/70 bg-slate-50/80 px-2 py-1.5 shadow-sm shadow-slate-950/[0.025] dark:border-white/10 dark:bg-white/[0.055] dark:shadow-none"
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 py-0.5 text-[11px] font-semibold text-slate-500 marker:hidden dark:text-slate-300 [&::-webkit-details-marker]:hidden">
        <span className="flex min-w-0 flex-1 items-center gap-1.5">
          <Plug className="size-3 shrink-0 text-indigo-400 dark:text-indigo-300" />
          <span className="shrink-0 text-[10px] font-semibold tracking-[0.12em] text-indigo-600 uppercase dark:text-indigo-300">
            {displayName}
          </span>
          {summary ? (
            <span className="min-w-0 truncate font-normal text-slate-500 dark:text-slate-400">
              {summary}
            </span>
          ) : null}
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          <span
            className={cn(
              "font-mono text-[11px]",
              block.is_error
                ? "text-rose-500 dark:text-rose-300"
                : hasResult
                  ? "text-emerald-500"
                  : "text-gray-400"
            )}
          >
            {block.is_error ? "x" : hasResult ? "✓" : "..."}
          </span>
          <ChevronRight className="size-3 text-slate-300 transition-transform group-open:rotate-90 dark:text-slate-500" />
        </span>
        {block.is_error ? (
          <span className="rounded-full bg-rose-100 px-1.5 py-0 text-[10px] text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">
            失败
          </span>
        ) : null}
      </summary>
      {inputText ? (
        <pre className="max-h-32 overflow-auto py-1.5 text-[10.5px] leading-relaxed break-all whitespace-pre-wrap text-slate-500 dark:text-slate-400">
          {inputText}
        </pre>
      ) : null}
      {block.skill_content ? (
        <p className="py-1.5 text-[11px] leading-relaxed whitespace-pre-wrap text-slate-500 dark:text-slate-400">
          {block.skill_content}
        </p>
      ) : null}
      {block.result ? (
        <p className="mt-1.5 py-1.5 text-[11.5px] leading-relaxed whitespace-pre-wrap text-slate-600 dark:text-slate-200">
          {block.result}
        </p>
      ) : null}
    </details>
  )
}

export function AssistantToolResultBlock({
  block,
  openNestedCards,
}: {
  block: Extract<AssistantContentBlock, { type: "tool_result" }>
  openNestedCards: boolean
}) {
  return (
    <details
      key={openNestedCards ? "open" : "closed"}
      open={block.is_error || openNestedCards || undefined}
      className={cn(
        "overflow-hidden rounded-lg px-2 py-1.5",
        block.is_error
          ? "border border-rose-200/80 bg-rose-50/70 dark:border-rose-900/50 dark:bg-rose-950/18"
          : "bg-sky-50/55 dark:bg-sky-950/16"
      )}
    >
      <summary
        className={cn(
          "cursor-pointer py-0.5 text-[11px] font-semibold",
          block.is_error
            ? "text-rose-700 dark:text-rose-100"
            : "text-gray-500 dark:text-gray-400"
        )}
      >
        {block.is_error ? "原始错误详情" : "工具结果"}
      </summary>
      <p
        className={cn(
          "mt-1.5 max-h-80 overflow-auto py-1.5 text-[11.5px] leading-relaxed whitespace-pre-wrap",
          block.is_error
            ? "text-rose-800 dark:text-rose-100"
            : "text-gray-500 dark:text-gray-400"
        )}
      >
        {block.content}
      </p>
    </details>
  )
}

export function AssistantRecommendationsBlock({
  block,
  disabled,
  onSelect,
}: {
  block: Extract<AssistantContentBlock, { type: "recommendations" }>
  disabled: boolean
  onSelect: AssistantRecommendationSelect
}) {
  const blockTitle =
    block.title && block.title !== "推荐操作" ? block.title : "下一步操作"

  return (
    <div className="space-y-3 pt-0.5">
      {block.summary ? (
        <div className="space-y-1.5">
          <div className="text-[11px] font-semibold text-gray-500 dark:text-gray-400">当前进度</div>
          <p className="text-[11.5px] leading-relaxed whitespace-pre-wrap text-gray-700 dark:text-gray-200">
            {block.summary}
          </p>
        </div>
      ) : null}
      <div className={cn("space-y-1", block.summary && "border-t border-gray-200/80 pt-2.5 dark:border-white/10")}>
        <div className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-500 dark:text-gray-400">
          <ClipboardList className="size-3.5 shrink-0" />
          <span>{blockTitle}</span>
        </div>
        <div className="space-y-1.5">
          {block.items.map((item) => {
            const isRecommended = Boolean(item.recommended)

            return (
              <button
                key={item.id}
                type="button"
                disabled={disabled}
                className={cn(
                  "group flex w-full min-w-0 items-start gap-2 rounded-md border px-2.5 py-2 text-left transition focus-visible:ring-2 focus-visible:ring-indigo-400/50 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-55",
                  isRecommended
                    ? "border-indigo-200 bg-white text-indigo-700 shadow-sm shadow-indigo-950/[0.035] hover:border-indigo-300 hover:bg-white dark:border-indigo-300/25 dark:bg-white/[0.085] dark:text-indigo-200 dark:shadow-none dark:hover:border-indigo-300/40"
                    : "border-white/70 bg-white/65 text-gray-600 hover:border-gray-200 hover:bg-white/80 dark:border-white/10 dark:bg-white/[0.045] dark:text-gray-300 dark:hover:border-white/15 dark:hover:bg-white/[0.06]"
                )}
                onClick={() => onSelect(item)}
              >
                <span
                  className={cn(
                    "mt-0.5 grid size-5 shrink-0 place-items-center rounded-md",
                    isRecommended
                      ? "bg-indigo-600 text-white dark:bg-indigo-400 dark:text-indigo-950"
                      : "bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-300"
                  )}
                >
                  {item.mode === "action" || item.mode === "navigation" ? (
                    <ArrowUpRight className="size-3.5" />
                  ) : (
                    <Send className="size-3.5" />
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex min-w-0 flex-wrap items-center gap-1.5">
                    <span className="min-w-0 text-[12px] font-semibold text-gray-800 dark:text-gray-100">
                      {item.label}
                    </span>
                    <span
                      className={cn(
                        "shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                        isRecommended
                          ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-300/15 dark:text-indigo-100"
                          : "bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-300"
                      )}
                    >
                      {isRecommended ? "推荐" : "可选"}
                    </span>
                  </span>
                  {item.description ? (
                    <span className="mt-0.5 block text-[11px] leading-relaxed text-gray-500 dark:text-gray-400">
                      {item.description}
                    </span>
                  ) : null}
                </span>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export function UserContentBlockRenderer({ block }: { block: AssistantContentBlock }) {
  const text =
    block.type === "text"
      ? block.text
      : "content" in block && typeof block.content === "string"
        ? block.content
        : "text" in block && typeof block.text === "string"
          ? block.text
          : ""
  if (!text.trim()) return null
  return <p className="font-normal break-words whitespace-pre-wrap">{text}</p>
}

export function AssistantSourceTextBlock({
  block,
}: {
  block: Extract<AssistantContentBlock, { type: "source_text" }>
}) {
  return (
    <section className="rounded-lg border border-indigo-100/80 bg-indigo-50/55 px-3 py-2.5 text-gray-800 shadow-sm shadow-indigo-950/[0.025] dark:border-indigo-300/15 dark:bg-indigo-400/[0.08] dark:text-gray-100 dark:shadow-none">
      <div className="flex min-w-0 items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-1.5 text-xs font-semibold">
          <ClipboardList className="size-3.5 shrink-0" />
          <span className="truncate">{block.title || "本集原文"}</span>
        </div>
        {block.meta ? (
          <span className="shrink-0 text-[11px] font-medium text-indigo-700/80 dark:text-indigo-100/70">
            {block.meta}
          </span>
        ) : null}
      </div>
      <pre className="mt-2 max-h-[28rem] overflow-y-auto whitespace-pre-wrap break-words font-sans text-[12px] leading-5">
        {block.text}
      </pre>
    </section>
  )
}

export function AssistantPlotSplitPreviewBlock({
  block,
}: {
  block: Extract<AssistantContentBlock, { type: "plot_split_preview" }>
}) {
  const statusLabel = {
    pending_confirmation: "待确认",
    superseded: "已被新版替换",
    committed: "已确认并写入",
    cancelled: "已取消",
  }[block.status]
  return (
    <section className="rounded-lg border border-gray-200/80 bg-white/70 px-3 py-3 text-gray-800 dark:border-white/10 dark:bg-white/[0.04] dark:text-gray-100">
      <div className="flex min-w-0 items-center justify-between gap-2 text-[12px] font-semibold">
        <span>剧情拆分候选 · 第 {block.candidateVersion} 版</span>
        <span className="shrink-0 text-[11px] font-medium text-indigo-600 dark:text-indigo-200">{statusLabel}</span>
      </div>
      {block.episodeTitle ? <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">分集标题：{block.episodeTitle}</div> : null}
      <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">剧情段落：{block.segments.length} 段</div>
      <div className="mt-3 divide-y divide-gray-200/80 dark:divide-white/10">
        {block.segments.map((segment, index) => (
          <section key={`${segment.index}-${index}`} className="py-3 first:pt-0 last:pb-0">
            <div className="flex min-w-0 items-start gap-2.5">
              <span className="grid size-5 shrink-0 place-items-center rounded bg-indigo-50 font-mono text-[10.5px] font-semibold text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-200">{segment.index}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[12.5px] font-semibold break-words text-indigo-600 dark:text-indigo-200">
                  {segment.title}<span className="ml-1 font-normal">（约 {segment.charCount} 字）</span>
                </div>
                <div className="mt-2 whitespace-pre-wrap break-words text-[12px] leading-[1.65] text-gray-700 dark:text-gray-200">{segment.text}</div>
                {segment.splitReason ? <div className="mt-2 break-words text-[12px] leading-[1.65]"><span className="text-indigo-600 dark:text-indigo-200">分段理由：</span>{segment.splitReason}</div> : null}
                {segment.assets.length ? segment.assets.map((asset, assetIndex) => (
                  <div key={`${asset.label}-${assetIndex}`} className="mt-1.5 break-words text-[12px] leading-[1.65]">
                    <span className="text-indigo-600 dark:text-indigo-200">{asset.label}：</span>{asset.names.join("、")}
                  </div>
                )) : <div className="mt-1.5 text-[12px] text-gray-500 dark:text-gray-400">暂无关联资产</div>}
              </div>
            </div>
          </section>
        ))}
      </div>
    </section>
  )
}

export function AssistantEpisodeBoundaryCandidateBlock({
  block,
  disabled,
  onConfirm,
  onCancel,
}: {
  block: Extract<AssistantContentBlock, { type: "episode_boundary_candidate" }>
  disabled: boolean
  onConfirm: (block: Extract<AssistantContentBlock, { type: "episode_boundary_candidate" }>) => void
  onCancel: (block: Extract<AssistantContentBlock, { type: "episode_boundary_candidate" }>) => void
}) {
  const committed = block.status === "committed"
  const pending = block.status === "pending_confirmation"
  const statusLabel = committed ? "已写入" : pending ? "待确认" : block.status === "cancelled" ? "已取消" : block.status === "stale" ? "已过期" : block.status === "committing" ? "正在写入" : block.status === "commit_unknown" ? "待核实" : "已替换"
  return (
    <section className="rounded-lg border border-indigo-200/80 bg-indigo-50/60 p-3 text-[12px] leading-relaxed text-gray-700 dark:border-indigo-300/20 dark:bg-indigo-400/[0.08] dark:text-gray-200">
      <div className="flex items-start justify-between gap-2">
        <div className="font-semibold text-gray-900 dark:text-gray-100">
          {block.episodeId} · {block.title || "分集断点候选"}
        </div>
        <span className={cn("flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium", committed ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-200" : pending ? "bg-amber-100 text-amber-700 dark:bg-amber-400/15 dark:text-amber-200" : "bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-300")}>
          {committed ? <BadgeCheck className="size-3" /> : null}
          {statusLabel}
        </span>
      </div>
      <div className="mt-2 text-gray-600 dark:text-gray-300">
        原文范围 {block.startOffset}–{block.endOffset} · 实际约 {block.actualUnits ?? "—"} 字
        {block.targetUnits ? ` · 目标约 ${block.targetUnits} 字` : ""}
      </div>
      {block.boundaryEndText ? <div className="mt-2 rounded-md bg-white/65 px-2 py-1.5 dark:bg-white/[0.06]">断点末尾：{block.boundaryEndText}</div> : null}
      {block.reason ? <p className="mt-2">{block.reason}</p> : null}
      {block.riskNotes.length ? <p className="mt-1.5 text-amber-700 dark:text-amber-200">风险：{block.riskNotes.join("；")}</p> : null}
      {pending ? (
        <div className="mt-3 flex gap-2">
          <button type="button" disabled={disabled}
            onClick={() => onConfirm(block)}
            className="rounded-md bg-indigo-600 px-3 py-1.5 text-[11px] font-medium text-white disabled:cursor-not-allowed disabled:opacity-50">
            确认此候选
          </button>
          <button type="button" disabled={disabled}
            onClick={() => onCancel(block)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-[11px] font-medium text-gray-600 disabled:cursor-not-allowed disabled:opacity-50 dark:border-white/20 dark:text-gray-300">
            取消此候选
          </button>
        </div>
      ) : null}
    </section>
  )
}

export function AssistantAssetRangeCandidateBlock({
  block,
  disabled,
  onConfirm,
  onCancel,
}: {
  block: Extract<AssistantContentBlock, { type: "asset_range_candidate" }>
  disabled: boolean
  onConfirm: (block: AssistantConfirmableCandidateBlock) => void
  onCancel: (block: AssistantConfirmableCandidateBlock) => void
}) {
  const committed = block.status === "committed"
  const pending = block.status === "pending_confirmation"
  const statusLabel = committed ? "已写入" : pending ? "待确认" : block.status === "cancelled" ? "已取消" : block.status === "stale" ? "已过期" : block.status === "committing" ? "正在写入" : block.status === "commit_unknown" ? "待核实" : "已替换"
  return (
    <section className="rounded-lg border border-indigo-200/80 bg-indigo-50/60 p-3 text-[12px] leading-relaxed text-gray-700 dark:border-indigo-300/20 dark:bg-indigo-400/[0.08] dark:text-gray-200">
      <div className="flex items-start justify-between gap-2">
        <div className="font-semibold text-gray-900 dark:text-gray-100">资产范围 · {block.rangeId}</div>
        <span className={cn("flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium", committed ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-200" : pending ? "bg-amber-100 text-amber-700 dark:bg-amber-400/15 dark:text-amber-200" : "bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-300")}>
          {committed ? <BadgeCheck className="size-3" /> : null}
          {statusLabel}
        </span>
      </div>
      <div className="mt-2 text-gray-600 dark:text-gray-300">
        原文范围 {block.absoluteStart}–{block.absoluteEnd} · 实际约 {block.actualUnits ?? "—"} 字
        {block.targetUnits ? ` · 目标约 ${block.targetUnits} 字` : ""}
      </div>
      {block.boundaryEndText ? <div className="mt-2 rounded-md bg-white/65 px-2 py-1.5 dark:bg-white/[0.06]">断点末尾：{block.boundaryEndText}</div> : null}
      {block.reason ? <p className="mt-2">{block.reason}</p> : null}
      {block.phaseVisualContexts.length ? (
        <div className="mt-2">新增阶段视觉：{block.phaseVisualContexts.map((item) => item.name).join("、")}</div>
      ) : <div className="mt-2">阶段视觉：沿用已有设定</div>}
      {block.riskNotes.length ? <p className="mt-1.5 text-amber-700 dark:text-amber-200">风险：{block.riskNotes.join("；")}</p> : null}
      {pending ? (
        <div className="mt-3 flex gap-2">
          <button type="button" disabled={disabled}
            onClick={() => onConfirm(block)}
            className="rounded-md bg-indigo-600 px-3 py-1.5 text-[11px] font-medium text-white disabled:cursor-not-allowed disabled:opacity-50">
            确认此范围
          </button>
          <button type="button" disabled={disabled}
            onClick={() => onCancel(block)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-[11px] font-medium text-gray-600 disabled:cursor-not-allowed disabled:opacity-50 dark:border-white/20 dark:text-gray-300">
            取消此范围
          </button>
        </div>
      ) : null}
    </section>
  )
}

export function AssistantContentBlockRenderer({
  block,
  expanded,
  recommendationsDisabled,
  candidateDisabled,
  onRecommendationSelect,
  onCandidateConfirm,
  onCandidateCancel,
}: {
  block: AssistantContentBlock
  expanded: boolean
  recommendationsDisabled: boolean
  candidateDisabled: boolean
  onRecommendationSelect: AssistantRecommendationSelect
  onCandidateConfirm: (block: AssistantConfirmableCandidateBlock) => void
  onCandidateCancel: (block: AssistantConfirmableCandidateBlock) => void
}) {
  if (block.type === "text") {
    const text = block.text
    const actionFooter = block.actionFooter
    const actionFooterText = assistantActionFooterText(actionFooter)
    return text.trim() || actionFooterText ? (
      <div className="space-y-2">
        {text.trim() ? <AssistantFormattedText text={text} expanded={expanded} /> : null}
        {actionFooter ? <AssistantActionFooterBlock footer={actionFooter} /> : null}
      </div>
    ) : null
  }
  if (block.type === "task_progress") {
    return <AssistantTaskProgressBlock block={block} />
  }
  if (block.type === "tool_use") {
    return <AssistantToolBlock block={block} openNestedCards={expanded} />
  }
  if (block.type === "tool_result") {
    return <AssistantToolResultBlock block={block} openNestedCards={expanded} />
  }
  if (block.type === "source_text") {
    return <AssistantSourceTextBlock block={block} />
  }
  if (block.type === "plot_split_preview") {
    return <AssistantPlotSplitPreviewBlock block={block} />
  }
  if (block.type === "episode_boundary_candidate") {
    return <AssistantEpisodeBoundaryCandidateBlock block={block} disabled={candidateDisabled} onConfirm={onCandidateConfirm} onCancel={onCandidateCancel} />
  }
  if (block.type === "asset_range_candidate") {
    return <AssistantAssetRangeCandidateBlock block={block} disabled={candidateDisabled} onConfirm={onCandidateConfirm} onCancel={onCandidateCancel} />
  }
  if (block.type === "recommendations") {
    return (
      <AssistantRecommendationsBlock
        block={block}
        disabled={recommendationsDisabled}
        onSelect={onRecommendationSelect}
      />
    )
  }
  if (block.type === "interrupt_notice") {
    return (
      <div className="rounded-lg bg-amber-50/60 px-2 py-1.5 text-[11.5px] leading-relaxed text-amber-800 dark:bg-amber-950/18 dark:text-amber-100">
        {block.text}
      </div>
    )
  }
  if (block.type === "attachment_error") {
    return (
      <div className="flex min-w-0 items-start gap-2 rounded-lg border border-amber-200 bg-amber-50/70 px-2.5 py-2 text-[11.5px] leading-relaxed text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-100">
        <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
        <div className="min-w-0">
          <div>{block.text}</div>
          {block.name || block.mimeType || block.media_type ? (
            <div className="mt-1 truncate text-[10.5px] text-amber-700/75 dark:text-amber-100/70">
              {[block.name, block.mimeType ?? block.media_type]
                .filter(Boolean)
                .join(" · ")}
            </div>
          ) : null}
        </div>
      </div>
    )
  }
  if (block.type === "image") {
    const source = block.source
    const localPath = source?.filePath ?? source?.path
    const src = localPath ? PluginSDK.convertFileSrc(localPath) : ""
    return src ? (
      <UnifiedMediaFrame
        src={src}
        alt={source?.name || "智能体图片"}
        title={source?.name || "智能体图片"}
        className="h-52 w-full max-w-sm"
        downloadSource={
          localPath
            ? {
                path: localPath,
                name: source?.name,
                mimeType: source?.mimeType ?? source?.media_type,
              }
            : undefined
        }
      />
    ) : null
  }
  if (block.type === "file") {
    const source = block.source
    const localPath = source?.filePath ?? source?.path
    const href = localPath ? PluginSDK.convertFileSrc(localPath) : ""
    return href ? (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="inline-flex max-w-full items-center gap-2 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 shadow-sm transition hover:border-sky-300 hover:text-sky-700 dark:border-white/10 dark:bg-white/5 dark:text-gray-200 dark:hover:border-sky-400/60 dark:hover:text-sky-100"
      >
        <Paperclip className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{source?.name || "附件文件"}</span>
        <span className="shrink-0 text-[11px] font-normal text-gray-400">
          {source?.mimeType ?? source?.media_type ?? "file"}
        </span>
      </a>
    ) : null
  }
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold text-gray-500 dark:text-gray-400">
        {block.title || (block.type === "thinking" ? "思考过程" : "技能输出")}
      </div>
      <AssistantFormattedText text={block.text} expanded={expanded} compact />
    </div>
  )
}
