import { Fragment, useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react"
import { Check, RotateCcw, X } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/shared/confirm-dialog"
import { cn } from "@/lib/utils"
import {
  addSegmentBoundary,
  editSourceSplitSegment,
  moveSegmentBoundary,
  removeSegmentBoundary,
  sourceSplitIsValid,
  type SourceSplitSegment,
} from "./source-split-model"

type SourceSplitEditorProps = {
  independent?: boolean
  needsApply?: boolean
  title: string
  sourceText: string
  segments: SourceSplitSegment[]
  originalSegments: SourceSplitSegment[]
  mode: "split" | "edit"
  onModeChange: (mode: "split" | "edit") => void
  onSaveSource: () => Promise<void>
  generatedCount: number
  onSegmentsChange: (segments: SourceSplitSegment[]) => void
  onClose: () => void
  onConfirm: () => Promise<void>
  saving?: boolean
}

function scrollToSegment(container: HTMLDivElement | null, target: HTMLElement | null | undefined) {
  if (!container || !target) return
  const top = container.scrollTop + target.getBoundingClientRect().top - container.getBoundingClientRect().top - 12
  container.scrollTo({ top: Math.max(0, top), behavior: "smooth" })
}

export function SourceSplitEditor({
  independent = false,
  needsApply = false,
  title,
  sourceText,
  segments,
  originalSegments,
  mode,
  onModeChange,
  onSaveSource,
  generatedCount,
  onSegmentsChange,
  onClose,
  onConfirm,
  saving = false,
}: SourceSplitEditorProps) {
  const [cursor, setCursor] = useState(0)
  const [activeSegment, setActiveSegment] = useState(0)
  const [draggingBoundary, setDraggingBoundary] = useState<number | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [discardCloseOpen, setDiscardCloseOpen] = useState(false)
  const textSurfaceRef = useRef<HTMLDivElement | null>(null)
  const sourceScrollRef = useRef<HTMLDivElement | null>(null)
  const resultScrollRef = useRef<HTMLDivElement | null>(null)
  const segmentRefs = useRef<Record<number, HTMLSpanElement | null>>({})
  const resultRefs = useRef<Record<number, HTMLButtonElement | null>>({})
  const dragPreviewRef = useRef<HTMLDivElement | null>(null)
  const textNodesRef = useRef<Array<{ node: Text; start: number }>>([])
  const dragSessionRef = useRef<{ index: number; offset: number; pointerId: number } | null>(null)
  const dragFrameRef = useRef<number | null>(null)
  const editRefs = useRef<Record<number, HTMLTextAreaElement | null>>({})
  const editing = mode === "edit"
  const visibleSegments = segments
  const visibleText = visibleSegments.map((segment) => segment.text).join("")
  const sourceDirty = visibleText !== sourceText
  const dirty = useMemo(
    () => JSON.stringify(segments.map(({ text, workChainId }) => ({ text, workChainId }))) !== JSON.stringify(originalSegments.map(({ text, workChainId }) => ({ text, workChainId }))),
    [originalSegments, segments]
  )
  const resetDirty = JSON.stringify(visibleSegments) !== JSON.stringify(originalSegments)
  const workChainDirty = dirty || needsApply
  const saveSourceOnly = !independent && (editing || sourceDirty)
  const canSubmit = independent ? workChainDirty : saveSourceOnly ? sourceDirty : dirty && generatedCount > 0
  const submitLabel = saveSourceOnly ? "保存分集原文" : independent && !generatedCount ? "应用并生成工作链" : "应用到工作链"
  const valid = sourceSplitIsValid(visibleSegments, visibleText)
  const changedCount = segments.length !== generatedCount
  const retainedCount = new Set(segments.map((segment) => segment.workChainId).filter(Boolean)).size
  const removedCount = Math.max(0, generatedCount - retainedCount)
  const addedCount = segments.filter((segment) => !segment.workChainId).length
  const confirmationDescription = [
    `按右侧结果保存 ${segments.length} 条工作链的片段剧本原文。`,
    addedCount ? `新增 ${addedCount} 条工作链。` : "",
    removedCount ? `移除被合并的 ${removedCount} 条工作链及其已有内容。` : "",
    "保留其他工作链的已有内容，并按当前顺序排列。",
    independent ? "新增工作链的资产需要手动关联。" : "",
  ].join("")

  useEffect(() => {
    if (activeSegment >= segments.length) setActiveSegment(Math.max(0, segments.length - 1))
  }, [activeSegment, segments.length])

  useEffect(() => {
    if (!editing) return
    for (const textarea of Object.values(editRefs.current)) {
      if (!textarea) continue
      textarea.style.height = "0px"
      textarea.style.height = `${Math.max(84, textarea.scrollHeight)}px`
    }
  }, [segments, editing])

  useEffect(() => {
    const root = textSurfaceRef.current
    if (!root || editing) return
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    const nodes: Array<{ node: Text; start: number }> = []
    let current: Node | null = null
    let start = 0
    while ((current = walker.nextNode())) {
      if (current.parentElement?.closest("[data-source-split-control]")) continue
      const textNode = current as Text
      nodes.push({ node: textNode, start })
      start += textNode.data.length
    }
    textNodesRef.current = nodes
  }, [segments, editing])

  const insertBoundary = () => {
    if (editing || saving) return
    const next = addSegmentBoundary(visibleText, segments, cursor)
    if (next !== segments) {
      onSegmentsChange(next)
      requestAnimationFrame(() => placeCaretAtOffset(cursor))
    }
  }

  const placeCaretAtOffset = (offset: number) => {
    const root = textSurfaceRef.current
    if (!root) return
    const sourceScroll = sourceScrollRef.current
    const sourceScrollTop = sourceScroll?.scrollTop ?? 0
    const targetOffset = Math.max(0, Math.min(visibleText.length, offset))
    let target: { node: Text; offset: number } | null = null
    for (const item of textNodesRef.current) {
      const end = item.start + item.node.data.length
      if (targetOffset <= end) {
        target = { node: item.node, offset: Math.max(0, targetOffset - item.start) }
        break
      }
    }
    if (!target) {
      const last = textNodesRef.current[textNodesRef.current.length - 1]
      if (!last) return
      target = { node: last.node, offset: last.node.data.length }
    }
    root.focus({ preventScroll: true })
    const selection = window.getSelection()
    if (!selection) return
    const range = document.createRange()
    range.setStart(target.node, target.offset)
    range.collapse(true)
    selection.removeAllRanges()
    selection.addRange(range)
    if (sourceScroll) {
      sourceScroll.scrollTop = sourceScrollTop
      requestAnimationFrame(() => {
        sourceScroll.scrollTop = sourceScrollTop
      })
    }
  }

  const locateResult = (index: number) => {
    const segment = segments[index]
    if (!segment) return
    setActiveSegment(index)
    // Clicking source text must leave its own scroll position unchanged.
    scrollToSegment(resultScrollRef.current, resultRefs.current[index])
  }

  const focusSegment = (index: number) => {
    if (editing) {
      setActiveSegment(index)
      const textarea = editRefs.current[index]
      textarea?.focus({ preventScroll: true })
      scrollToSegment(sourceScrollRef.current, textarea)
      return
    }
    const segment = segments[index]
    if (!segment) return
    setActiveSegment(index)
    setCursor(segment.start)
    placeCaretAtOffset(segment.start)
    scrollToSegment(sourceScrollRef.current, segmentRefs.current[index])
  }

  const offsetFromPoint = (clientX: number, clientY: number) => {
    const root = textSurfaceRef.current
    if (!root) return null
    const documentWithCaret = document as Document & {
      caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null
      caretRangeFromPoint?: (x: number, y: number) => Range | null
    }
    const caret = documentWithCaret.caretPositionFromPoint
      ? documentWithCaret.caretPositionFromPoint(clientX, clientY)
      : documentWithCaret.caretRangeFromPoint?.(clientX, clientY)
    if (!caret) return null
    const node = "offsetNode" in caret ? caret.offsetNode : caret.startContainer
    const localOffset = "offset" in caret ? caret.offset : caret.startOffset
    if (!root.contains(node) || node.nodeType !== Node.TEXT_NODE) return null
    const textNode = textNodesRef.current.find((item) => item.node === node)
    if (textNode) return textNode.start + localOffset
    return null
  }

  const handleTextKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (editing || saving || event.nativeEvent.isComposing) return
    if (event.key === "Enter") {
      event.preventDefault()
      insertBoundary()
      return
    }
    if (event.key === "Backspace") {
      const index = segments.findIndex((segment) => segment.end === cursor)
      if (index >= 0) {
        event.preventDefault()
        onSegmentsChange(removeSegmentBoundary(visibleText, segments, index))
      }
    }
  }

  useEffect(() => {
    if (draggingBoundary === null || editing || saving) return
    const handleMove = (event: globalThis.PointerEvent) => {
      const session = dragSessionRef.current
      if (!session || session.pointerId !== event.pointerId) return
      session.offset = offsetFromPoint(event.clientX, event.clientY) ?? session.offset
      if (dragFrameRef.current !== null) return
      dragFrameRef.current = window.requestAnimationFrame(() => {
        dragFrameRef.current = null
        const root = textSurfaceRef.current
        const preview = dragPreviewRef.current
        if (!root || !preview) return
        const rect = root.getBoundingClientRect()
        preview.style.transform = `translateY(${event.clientY - rect.top + root.scrollTop}px)`
      })
    }
    const handleUp = (event: globalThis.PointerEvent) => {
      const session = dragSessionRef.current
      if (!session || session.pointerId !== event.pointerId) return
      if (dragFrameRef.current !== null) {
        window.cancelAnimationFrame(dragFrameRef.current)
        dragFrameRef.current = null
      }
      onSegmentsChange(moveSegmentBoundary(visibleText, segments, session.index, session.offset))
      dragSessionRef.current = null
      if (dragPreviewRef.current) dragPreviewRef.current.style.display = "none"
      setDraggingBoundary(null)
    }
    window.addEventListener("pointermove", handleMove)
    window.addEventListener("pointerup", handleUp)
    window.addEventListener("pointercancel", handleUp)
    return () => {
      window.removeEventListener("pointermove", handleMove)
      window.removeEventListener("pointerup", handleUp)
      window.removeEventListener("pointercancel", handleUp)
      if (dragFrameRef.current !== null) window.cancelAnimationFrame(dragFrameRef.current)
    }
  }, [draggingBoundary, editing, saving, onSegmentsChange, segments, visibleText])

  const handleTextPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (editing || saving) return
    if (event.button !== 0) {
      event.preventDefault()
      event.stopPropagation()
      return
    }
    if ((event.target as HTMLElement).closest("[data-source-split-control]")) return
    const offset = offsetFromPoint(event.clientX, event.clientY)
    if (offset === null) return
    event.preventDefault()
    setCursor(offset)
    const segmentIndex = segments.findIndex((segment, index) =>
      offset >= segment.start && (offset < segment.end || index === segments.length - 1)
    )
    const sourceScrollTop = sourceScrollRef.current?.scrollTop ?? 0
    requestAnimationFrame(() => {
      placeCaretAtOffset(offset)
      if (sourceScrollRef.current) sourceScrollRef.current.scrollTop = sourceScrollTop
    })
    if (segmentIndex >= 0) locateResult(segmentIndex)
  }

  const handleBoundaryPointerDown = (index: number, event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.stopPropagation()
    if (event.button !== 0 || saving || editing) return
    setActiveSegment(index)
    dragSessionRef.current = {
      index,
      offset: segments[index]?.end ?? 0,
      pointerId: event.pointerId,
    }
    const root = textSurfaceRef.current
    const preview = dragPreviewRef.current
    if (root && preview) {
      const rect = root.getBoundingClientRect()
      preview.style.transform = `translateY(${event.clientY - rect.top + root.scrollTop}px)`
      preview.style.display = "block"
    }
    event.currentTarget.setPointerCapture?.(event.pointerId)
    setDraggingBoundary(index)
  }

  const reset = () => {
    const restored = originalSegments.map((segment) => ({ ...segment }))
    onSegmentsChange(restored)
    setCursor(0)
    setActiveSegment(0)
  }

  const close = () => {
    if (saving || draggingBoundary !== null) return
    if (sourceDirty || dirty) setDiscardCloseOpen(true)
    else onClose()
  }

  return (
    <div
      className="absolute inset-0 z-[260] flex min-h-0 flex-col bg-slate-50 text-gray-900 dark:bg-[#111113] dark:text-gray-100"
      onContextMenu={(event) => {
        event.preventDefault()
        event.stopPropagation()
        close()
      }}
    >
      <div className="flex shrink-0 items-center justify-between gap-4 border-b border-gray-200/80 bg-white px-5 py-3 shadow-none dark:border-white/[0.07] dark:bg-[#18181b]">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h2 className="truncate text-base font-semibold">{title || "当前分集"}</h2>
            <Badge variant="outline" className="shrink-0 border-indigo-200 bg-indigo-50 text-indigo-600 dark:border-indigo-400/20 dark:bg-indigo-400/10 dark:text-indigo-300">{editing ? "编辑模式" : "拆分模式"}</Badge>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Button type="button" variant="ghost" size="icon-sm" onClick={close} disabled={saving || draggingBoundary !== null} title="关闭" aria-label="关闭原文页面">
            <X className="size-4" />
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden bg-slate-50 p-4 lg:p-5 dark:bg-[#151517]">
        <div className="grid h-full min-h-0 gap-4 lg:grid-cols-2">
          <section className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-gray-200/80 bg-white/70 shadow-none dark:border-white/[0.07] dark:bg-[#18181b]">
            <div className="flex shrink-0 items-center justify-between gap-3 border-b border-gray-200/70 px-4 py-3 dark:border-white/[0.07]">
              <div>
                <div className="text-sm font-semibold">原文</div>
                <div className="mt-0.5 text-[11px] text-gray-500 dark:text-gray-400">{editing ? "直接编辑各块正文，Enter 换行；分割线固定" : "点击文字定位，按 Enter 添加断点"}</div>
              </div>
              <Badge variant="outline" className="rounded-full text-[10px]">{visibleText.length} 字</Badge>
            </div>
            <div ref={sourceScrollRef} className="min-h-0 flex-1 overflow-y-auto p-3">
              <div className="relative min-h-full">
                <div
                  ref={textSurfaceRef}
                  tabIndex={0}
                  role={editing ? "group" : "textbox"}
                  aria-label={editing ? "分集原文编辑区" : "原文断点编辑区"}
                  contentEditable={!editing}
                  suppressContentEditableWarning
                  onBeforeInput={(event) => { if (!editing) event.preventDefault() }}
                  onPointerDown={handleTextPointerDown}
                  onKeyDown={handleTextKeyDown}
                  className="relative min-h-full rounded-md border border-gray-200/80 bg-gray-50/70 p-4 text-sm leading-7 text-gray-800 outline-none focus:outline-none focus:ring-0 dark:border-white/[0.07] dark:bg-[#151517] dark:text-gray-100"
                >
                <div
                  ref={dragPreviewRef}
                  aria-hidden
                  className="pointer-events-none absolute top-0 right-[30px] left-[5px] z-20 hidden h-0.5 rounded-full bg-indigo-500 shadow-[0_0_0_2px_rgba(99,102,241,0.16)]"
                />
                {visibleSegments.map((segment, index) => (
                  <Fragment key={`${segment.id}-${index}`}>
                    {editing ? (
                      <textarea
                        ref={(element) => { editRefs.current[index] = element }}
                        aria-label={`第 ${index + 1} 块原文`}
                        value={segment.text}
                        disabled={saving}
                        onFocus={() => locateResult(index)}
                        onChange={(event) => onSegmentsChange(editSourceSplitSegment(visibleSegments, index, event.target.value))}
                        className="block min-h-[84px] w-full resize-none overflow-hidden border-0 bg-transparent px-0.5 text-sm leading-7 outline-none focus:ring-0"
                      />
                    ) : <span ref={(element) => { segmentRefs.current[index] = element }} className="whitespace-pre-wrap break-words px-0.5">{segment.text}</span>}
                    {index < segments.length - 1 ? (
                      <div
                        data-source-split-control
                        contentEditable={false}
                        role="separator"
                        aria-label={`第 ${index + 1} ${editing ? "条分割线" : "个断点"}`}
                        onPointerDown={editing ? undefined : (event) => handleBoundaryPointerDown(index, event)}
                        className={cn("group relative -mx-4 my-3 flex h-5 items-center gap-[5px] px-[5px]", !editing && "cursor-row-resize", draggingBoundary === index && "cursor-grabbing")}
                      >
                        <div className={cn("h-0.5 min-w-0 flex-1 rounded-full", editing ? "bg-gray-300 dark:bg-white/15" : "bg-indigo-400 transition-colors group-hover:bg-indigo-600 dark:bg-indigo-400/80 dark:group-hover:bg-indigo-300")} />
                        {!editing ? <button
                          type="button"
                          disabled={saving}
                          data-source-split-control
                          onPointerDown={(event) => event.stopPropagation()}
                          onClick={(event) => {
                            event.stopPropagation()
                            onSegmentsChange(removeSegmentBoundary(visibleText, segments, index))
                          }}
                          className="relative z-10 inline-flex size-5 shrink-0 items-center justify-center rounded-full border border-indigo-200 bg-white text-indigo-500 opacity-60 shadow-sm transition-opacity hover:border-indigo-400 hover:opacity-100 hover:text-indigo-700 dark:border-indigo-400/30 dark:bg-[#242429] dark:text-indigo-300 dark:hover:border-indigo-300 dark:hover:text-indigo-100"
                          aria-label={`删除第 ${index + 1} 个断点`}
                        >
                          <X className="size-3" />
                        </button> : null}
                      </div>
                    ) : null}
                  </Fragment>
                ))}
                </div>
              </div>
            </div>
          </section>

          <section className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-gray-200/80 bg-white/70 shadow-none dark:border-white/[0.07] dark:bg-[#18181b]">
            <div className="flex shrink-0 items-center justify-between gap-3 border-b border-gray-200/70 px-4 py-3 dark:border-white/[0.07]">
              <div>
                <div className="text-sm font-semibold">拆分结果</div>
                <div className="mt-0.5 text-[11px] text-gray-500 dark:text-gray-400">按顺序填充到工作链片段剧本</div>
              </div>
              <Badge variant="outline" className="rounded-full text-[10px]">当前 {segments.length} 条</Badge>
            </div>
            <div ref={resultScrollRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
              {visibleSegments.map((segment, index) => (
                <button ref={(element) => { resultRefs.current[index] = element }} key={`${segment.id}-${index}`} type="button" className={cn("w-full rounded-md border p-3 text-left transition-colors", activeSegment === index ? "border-indigo-300 bg-indigo-50/70 dark:border-indigo-500/50 dark:bg-indigo-500/10" : "border-gray-200 bg-gray-50/55 hover:border-indigo-200 dark:border-white/[0.07] dark:bg-[#151517] dark:hover:border-indigo-500/40")} onClick={() => focusSegment(index)}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold">第 {index + 1} 条</span>
                    <span className="text-[10px] tabular-nums text-gray-400">{segment.text.length} 字</span>
                  </div>
                  <div className="mt-2 whitespace-pre-wrap text-xs leading-6 text-gray-700 dark:text-gray-200">{segment.text || "（空内容）"}</div>
                  {!segment.text.trim() ? <div className="mt-2 text-[11px] text-rose-600 dark:text-rose-300">这一条不能为空</div> : null}
                </button>
              ))}
            </div>
          </section>
        </div>
      </div>

      <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-5 gap-y-3 border-t border-gray-200/80 bg-white px-5 py-3 dark:border-white/[0.07] dark:bg-[#18181b]">
        <div className="flex min-w-0 flex-wrap items-center gap-2" aria-label="保存与应用状态">
          <div role="group" aria-label="原文操作模式" className="mr-2 inline-flex shrink-0 items-center gap-1 rounded-lg border border-gray-200 bg-gray-100 p-1 dark:border-white/10 dark:bg-black/25">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-pressed={editing}
              disabled={saving || draggingBoundary !== null}
              onClick={() => onModeChange("edit")}
              className={cn("min-w-16 rounded-md px-4 transition-colors", editing ? "bg-indigo-600 font-semibold text-white shadow-sm hover:bg-indigo-700 hover:text-white dark:bg-indigo-500 dark:text-white dark:hover:bg-indigo-600" : "text-gray-500 hover:bg-white hover:text-gray-900 dark:text-gray-400 dark:hover:bg-white/10 dark:hover:text-white")}
            >编辑</Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-pressed={!editing}
              disabled={saving || draggingBoundary !== null}
              onClick={() => onModeChange("split")}
              className={cn("min-w-16 rounded-md px-4 transition-colors", !editing ? "bg-indigo-600 font-semibold text-white shadow-sm hover:bg-indigo-700 hover:text-white dark:bg-indigo-500 dark:text-white dark:hover:bg-indigo-600" : "text-gray-500 hover:bg-white hover:text-gray-900 dark:text-gray-400 dark:hover:bg-white/10 dark:hover:text-white")}
            >拆分</Button>
          </div>
          <Badge variant="outline" className={cn("gap-1.5 font-normal", sourceDirty ? "border-amber-300/60 bg-amber-50 text-amber-700 dark:border-amber-400/20 dark:bg-amber-400/5 dark:text-amber-300" : "border-gray-200 text-gray-500 dark:border-white/10 dark:text-gray-400")}>
            <span aria-hidden className={cn("size-1.5 rounded-full", sourceDirty ? "bg-amber-500" : "bg-emerald-500")} />
            {sourceDirty ? "原文待保存" : "原文已保存"}
          </Badge>
          <Badge variant="outline" className={cn("font-normal", workChainDirty ? "border-amber-300/60 bg-amber-50 text-amber-700 dark:border-amber-400/20 dark:bg-amber-400/5 dark:text-amber-300" : "border-gray-200 text-gray-500 dark:border-white/10 dark:text-gray-400")}>
            {workChainDirty ? "工作链待应用" : "工作链无改动"}
          </Badge>
          {dirty && (changedCount || addedCount > 0 || removedCount > 0) ? (
            <div className="ml-1 flex items-center gap-2 border-l border-gray-200 pl-3 text-xs tabular-nums dark:border-white/10">
              {changedCount ? <span className="text-gray-500 dark:text-gray-400">{generatedCount} → {segments.length} 条</span> : null}
              {addedCount > 0 ? <span className="text-indigo-600 dark:text-indigo-300">新增 {addedCount}</span> : null}
              {removedCount > 0 ? <span className="text-amber-700 dark:text-amber-300">合并移除 {removedCount}</span> : null}
            </div>
          ) : null}
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-3">
          <Button type="button" variant="ghost" size="sm" className="gap-1.5 bg-gray-100 text-gray-800 hover:bg-gray-200 hover:text-gray-950 disabled:bg-transparent disabled:text-gray-400 dark:bg-white/5 dark:text-gray-100 dark:hover:bg-white/10 dark:hover:text-white dark:disabled:bg-transparent dark:disabled:text-gray-500" title="恢复本次打开时的原文和分割位置" onClick={reset} disabled={!resetDirty || saving || draggingBoundary !== null}><RotateCcw className="size-3.5" />恢复初始</Button>
          {independent ? <Button type="button" variant="outline" disabled={!valid || !sourceDirty || saving} onClick={() => void onSaveSource()}>保存原文</Button> : null}
          <Button type="button" className="min-w-[132px] gap-1.5" onClick={() => saveSourceOnly ? void onSaveSource() : setConfirmOpen(true)} disabled={!valid || saving || draggingBoundary !== null || !canSubmit}>
            <Check className="size-3.5" />{saving ? "保存中..." : submitLabel}
          </Button>
        </div>
      </div>

      <ConfirmDialog
        open={discardCloseOpen}
        title="关闭并放弃未应用的修改？"
        description="未保存的原文修改和未应用的拆分调整将被放弃，已经保存的原文会保留。"
        confirmLabel="放弃修改"
        loadingLabel="退出中..."
        loading={false}
        overlayClassName="!z-[390]"
        contentClassName="!z-[400]"
        onCancel={() => setDiscardCloseOpen(false)}
        onConfirm={() => {
          onClose()
          setDiscardCloseOpen(false)
        }}
      />
      <ConfirmDialog
        open={confirmOpen}
        title="确认应用拆分结果？"
        description={confirmationDescription}
        confirmLabel="确认调整"
        loadingLabel="调整中..."
        loading={saving}
        overlayClassName="!z-[390]"
        contentClassName="!z-[400]"
        onCancel={() => setConfirmOpen(false)}
        onConfirm={async () => {
          try {
            await onConfirm()
            setConfirmOpen(false)
          } catch {
            // The save action displays the error; leave the dialog available for retry.
          }
        }}
      />
    </div>
  )
}
