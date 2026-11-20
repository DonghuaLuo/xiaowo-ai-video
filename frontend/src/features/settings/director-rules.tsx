import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { Clapperboard, Loader2, PencilLine, RotateCcw, Save } from "lucide-react"

import {
  getDirectorRules,
  resetDirectorRule,
  saveDirectorRule,
  type DirectorRuleOption,
} from "@/backend"
import { Button } from "@/components/ui/button"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import { errMsg } from "@/shared/backend-result"
import { TooltipWrap } from "@/shared/tooltip-wrap"
import { useAdaptivePaneScroll } from "@/features/settings/adaptive-pane-scroll"
import {AutoResizeTextarea} from '@/features/settings/auto-resize-textarea'
import {TEMPLATE_EDIT_ICON_BUTTON_CLS} from '@/features/settings/shared-template'

function normalizeDirectorRule(raw: any): DirectorRuleOption {
  const id = String(raw?.id ?? "").trim()
  const title = String(raw?.title ?? id).trim()
  const description = String(raw?.description ?? "").trim()
  const content = String(raw?.content ?? "").trim()
  return {
    id,
    title,
    description,
    content,
    defaultDescription: String(raw?.defaultDescription ?? "").trim(),
    defaultContent: String(raw?.defaultContent ?? "").trim(),
    source: String(raw?.source ?? "builtin"),
    customized: Boolean(raw?.customized),
    updatedAt: String(raw?.updatedAt ?? "").trim(),
  }
}

export function DirectorRuleSettings() {
  const { backendReady, callBackend } = useBackend()
  const {
    listScrollRef,
    detailScrollRef,
    listScrollStyle,
    detailScrollStyle,
  } = useAdaptivePaneScroll()
  const [rules, setRules] = useState<DirectorRuleOption[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [resettingId, setResettingId] = useState("")
  const [description, setDescription] = useState("")
  const [content, setContent] = useState("")

  const selected =
    rules.find((rule) => rule.id === selectedId) ?? rules[0] ?? null

  const applyRules = useCallback(
    (nextRules: DirectorRuleOption[], preferredId?: string) => {
      const normalized = nextRules
        .map(normalizeDirectorRule)
        .filter((rule) => rule.id)
      setRules(normalized)
      setSelectedId((current) => {
        const target = preferredId || current
        if (target && normalized.some((rule) => rule.id === target)) {
          return target
        }
        return normalized[0]?.id ?? ""
      })
    },
    []
  )

  const loadRules = useCallback(async () => {
    if (!backendReady) return
    setLoading(true)
    try {
      const nextRules = await getDirectorRules(callBackend)
      applyRules(nextRules)
      setError(null)
    } catch (err: unknown) {
      setError(errMsg(err, "加载导演规则失败"))
    } finally {
      setLoading(false)
    }
  }, [applyRules, backendReady, callBackend])

  useEffect(() => {
    void loadRules()
  }, [loadRules])

  const startEdit = (rule: DirectorRuleOption) => {
    setSelectedId(rule.id)
    setDescription(rule.description)
    setContent(rule.content)
    setEditing(true)
  }

  const cancelEdit = () => {
    if (selected) {
      setDescription(selected.description)
      setContent(selected.content)
    }
    setEditing(false)
  }

  const handleSelectRule = (rule: DirectorRuleOption) => {
    setSelectedId(rule.id)
    setEditing(false)
    setDescription(rule.description)
    setContent(rule.content)
  }

  const handleSave = async () => {
    if (!selected) return
    const nextDescription = description.trim()
    const nextContent = content.trim()
    if (!nextDescription || !nextContent) {
      toast.info("简介和规则内容不能为空")
      return
    }
    setSaving(true)
    try {
      const nextRules = await saveDirectorRule(callBackend, {
        id: selected.id,
        description: nextDescription,
        content: nextContent,
      })
      applyRules(nextRules, selected.id)
      setEditing(false)
      toast.success("导演规则已保存")
    } catch (err: unknown) {
      toast.error(errMsg(err, "保存导演规则失败"))
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async (rule: DirectorRuleOption) => {
    setResettingId(rule.id)
    try {
      const nextRules = await resetDirectorRule(callBackend, rule.id)
      applyRules(nextRules, rule.id)
      setEditing(false)
      toast.success("已恢复默认导演规则")
    } catch (err: unknown) {
      toast.error(errMsg(err, "恢复默认导演规则失败"))
    } finally {
      setResettingId("")
    }
  }

  const canSave = Boolean(
    selected &&
      description.trim() &&
      content.trim() &&
      (description.trim() !== selected.description.trim() ||
        content.trim() !== selected.content.trim())
  )

  return (
    <div className="grid gap-4 rounded-xl border border-gray-200/70 bg-white/65 p-4 shadow-sm dark:border-white/10 dark:bg-white/[0.045] lg:grid-cols-[minmax(260px,0.38fr)_minmax(0,1fr)]">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-xs font-semibold text-gray-900 dark:text-gray-100">
          <Clapperboard className="size-3.5 text-indigo-500" />
          导演规则
        </div>
        <div
          ref={listScrollRef}
          className="mt-3 overflow-y-auto overscroll-contain pr-1 [scrollbar-gutter:stable]"
          style={listScrollStyle}
        >
          <div className="space-y-2">
            {loading ? (
              <div className="flex items-center gap-2 rounded-lg border border-gray-200/70 bg-white/70 p-3 text-xs text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
                <Loader2 className="size-3.5 animate-spin text-indigo-500" />
                正在加载导演规则
              </div>
            ) : error ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-200">
                {error}
              </div>
            ) : rules.length ? (
              rules.map((rule) => (
                <div
                  key={rule.id}
                  className={cn(
                    "flex w-full items-start overflow-hidden rounded-lg border transition-colors",
                    selected?.id === rule.id
                      ? "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
                      : "border-gray-200/70 bg-white/70 text-gray-600 hover:border-indigo-200 hover:text-gray-950 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400 dark:hover:text-gray-50"
                  )}
                >
                  <button
                    type="button"
                    className="min-w-0 flex-1 px-3 py-2 text-left"
                    onClick={() => handleSelectRule(rule)}
                  >
                    <span className="block text-sm font-semibold">
                      {rule.title}
                    </span>
                    <span className="mt-1 block text-xs leading-relaxed opacity-75">
                      {rule.description}
                    </span>
                  </button>
                  {rule.customized ? (
                    <TooltipWrap content="恢复默认">
                      <button
                        type="button"
                        className={TEMPLATE_EDIT_ICON_BUTTON_CLS}
                        title="恢复默认"
                        aria-label="恢复默认"
                        onClick={() => void handleReset(rule)}
                        disabled={Boolean(resettingId)}
                      >
                        {resettingId === rule.id ? (
                          <Loader2 className="size-3.5 animate-spin" />
                        ) : (
                          <RotateCcw className="size-3.5" />
                        )}
                      </button>
                    </TooltipWrap>
                  ) : null}
                  <button
                    type="button"
                    className={TEMPLATE_EDIT_ICON_BUTTON_CLS}
                    title="编辑导演规则"
                    aria-label="编辑导演规则"
                    onClick={() => startEdit(rule)}
                  >
                    <PencilLine className="size-3.5" />
                  </button>
                </div>
              ))
            ) : (
              <p className="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                暂无导演规则。
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="min-w-0">
        {editing && selected ? (
          <div
            ref={detailScrollRef}
            className="grid min-w-0 gap-3 overflow-y-auto overscroll-contain pr-1 [scrollbar-gutter:stable]"
            style={detailScrollStyle}
          >
            <div>
              <div className="text-xs font-semibold text-gray-900 dark:text-gray-100">
                {selected.title}
              </div>
              <div className="mt-1 font-mono text-[11px] text-gray-400 dark:text-gray-500">
                {selected.id}
              </div>
            </div>
            <input
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="简短简介"
              className="h-9 min-w-0 rounded-lg border border-gray-200/70 bg-white/70 px-3 text-sm outline-none focus:border-indigo-400 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-100"
            />
            <AutoResizeTextarea
              value={content}
              onChange={(event) => setContent(event.target.value)}
              placeholder="具体导演规则"
              className="min-h-72"
            />
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                className="h-9"
                onClick={cancelEdit}
                disabled={saving}
              >
                取消
              </Button>
              <Button
                type="button"
                className="h-9 gap-1.5"
                onClick={() => void handleSave()}
                disabled={saving || !canSave}
              >
                {saving ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Save className="size-3.5" />
                )}
                保存规则
              </Button>
            </div>
          </div>
        ) : selected ? (
          <div
            ref={detailScrollRef}
            className="min-w-0 overflow-y-auto overscroll-contain pr-1 [scrollbar-gutter:stable]"
            style={detailScrollStyle}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-gray-950 dark:text-gray-50">
                  {selected.title}
                </h3>
                <div className="mt-1 font-mono text-[11px] text-gray-400 dark:text-gray-500">
                  {selected.id}
                </div>
              </div>
              {selected.customized ? (
                <span className="shrink-0 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-medium text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/20 dark:text-emerald-300">
                  已微调
                </span>
              ) : null}
            </div>
            <p className="mt-3 text-sm leading-relaxed text-gray-600 dark:text-gray-300">
              {selected.description}
            </p>
            <div className="mt-4 whitespace-pre-wrap rounded-lg border border-gray-200/70 bg-white/70 p-3 text-xs leading-relaxed text-gray-600 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-300">
              {selected.content}
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-gray-200/70 bg-white/70 p-4 text-xs text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
            请选择导演规则。
          </div>
        )}
      </div>
    </div>
  )
}
