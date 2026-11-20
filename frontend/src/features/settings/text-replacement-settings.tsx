import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { Hash, Loader2, PencilLine, Plus, Save, Trash2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useBackend } from "@/hooks/useBackend"
import { errMsg } from "@/shared/backend-result"
import { useAdaptivePaneScroll } from "@/features/settings/adaptive-pane-scroll"

export type TextReplacementRuleOption = {
  from: string
  to: string
}

export function TextReplacementRuleSettings() {
  const { backendReady, callBackend } = useBackend()
  const { listScrollRef, listScrollStyle } = useAdaptivePaneScroll()
  const [rules, setRules] = useState<TextReplacementRuleOption[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [draftFrom, setDraftFrom] = useState("")
  const [draftTo, setDraftTo] = useState("")

  const loadRules = useCallback(async () => {
    if (!backendReady) return
    setLoading(true)
    try {
      const result = await callBackend<{
        success?: boolean
        message?: string
        rules?: TextReplacementRuleOption[]
      }>("get_text_replacement_rules")
      if (result.success === false) {
        throw new Error(result.message || "加载提示词替换规则失败")
      }
      const nextRules = result.rules ?? []
      setRules(nextRules)
    } catch (err: unknown) {
      toast.error(errMsg(err, "加载提示词替换规则失败"))
    } finally {
      setLoading(false)
    }
  }, [backendReady, callBackend])

  useEffect(() => {
    void loadRules()
  }, [loadRules])

  const resetForm = () => {
    setFormOpen(false)
    setEditingIndex(null)
    setDraftFrom("")
    setDraftTo("")
  }

  const persistRules = async (
    nextRules: TextReplacementRuleOption[],
    successMessage: string
  ) => {
    if (!backendReady) {
      toast.error("后端未就绪，暂时不能保存规则")
      return false
    }
    setSaving(true)
    try {
      const result = await callBackend<{
        success?: boolean
        message?: string
        rules?: TextReplacementRuleOption[]
      }>("save_text_replacement_rules", { rules: nextRules })
      if (result.success === false) {
        throw new Error(result.message || "保存提示词替换规则失败")
      }
      setRules(result.rules ?? nextRules)
      toast.success(successMessage)
      return true
    } catch (err: unknown) {
      toast.error(errMsg(err, "保存提示词替换规则失败"))
      return false
    } finally {
      setSaving(false)
    }
  }

  const handleOpenAdd = () => {
    setFormOpen(true)
    setEditingIndex(null)
    setDraftFrom("")
    setDraftTo("")
  }

  const handleEdit = (index: number) => {
    const rule = rules[index]
    if (!rule) return
    setFormOpen(false)
    setEditingIndex(index)
    setDraftFrom(rule.from)
    setDraftTo(rule.to)
  }

  const handleSaveDraft = async () => {
    const from = draftFrom.trim()
    const to = draftTo.trim()
    if (!from || !to) {
      toast.info("请填写原文和替换后的文字")
      return
    }
    const nextRule = { from, to }
    const nextRules =
      editingIndex !== null && editingIndex >= 0 && editingIndex < rules.length
        ? rules.map((rule, index) => (index === editingIndex ? nextRule : rule))
        : [...rules, nextRule]
    const saved = await persistRules(
      nextRules,
      editingIndex === null ? "提示词替换规则已添加" : "提示词替换规则已修改"
    )
    if (saved) resetForm()
  }

  const handleDelete = async (index: number) => {
    const nextRules = rules.filter((_, ruleIndex) => ruleIndex !== index)
    const saved = await persistRules(nextRules, "提示词替换规则已删除")
    if (saved) resetForm()
  }

  return (
    <div className="mx-auto w-full max-w-5xl rounded-xl border border-gray-200/70 bg-white/65 p-4 shadow-sm dark:border-white/10 dark:bg-white/[0.045]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold text-gray-900 dark:text-gray-100">
            <Hash className="size-3.5 text-indigo-500" />
            提示词替换规则
          </div>
          <p className="mt-2 max-w-2xl text-xs leading-relaxed text-gray-500 dark:text-gray-400">
            仅在视频片段生成前，对即将发送给视频模型的提示词做正则替换。
          </p>
        </div>
        <Button
          type="button"
          className="h-9 gap-1.5"
          onClick={handleOpenAdd}
          disabled={saving || loading}
        >
          <Plus className="size-3.5" />
          添加
        </Button>
      </div>

      <div className="mt-3 rounded-lg border border-gray-200/70 bg-gray-50/70 px-3 py-2.5 text-xs leading-relaxed text-gray-600 dark:border-white/10 dark:bg-black/20 dark:text-gray-300">
        {loading ? (
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <Loader2 className="size-3.5 animate-spin" />
            正在加载
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="rounded-md border border-indigo-100 bg-indigo-50 px-2 py-1 font-semibold text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300">
              当前 {rules.length} 条规则
            </span>
            <span>
              不参与原文拆分、片段剧本或分镜图生成；生成视频片段前，按列表顺序改写视频生成节点的最终提示词。
            </span>
          </div>
        )}
      </div>

      {formOpen && editingIndex === null ? (
        <div className="mt-4 rounded-lg border border-indigo-200 bg-indigo-50/70 p-3 dark:border-indigo-900/60 dark:bg-indigo-950/20">
          <div className="mb-3 text-xs font-semibold text-indigo-700 dark:text-indigo-300">
            {editingIndex === null ? "添加提示词替换规则" : "修改提示词替换规则"}
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-1.5 text-xs font-medium text-gray-600 dark:text-gray-300">
              原文
              <input
                value={draftFrom}
                onChange={(event) => setDraftFrom(event.target.value)}
                placeholder="例如：找死"
                className="h-9 rounded-lg border border-gray-200/70 bg-white px-3 text-sm font-normal text-gray-900 outline-none focus:border-indigo-400 dark:border-white/10 dark:bg-white/[0.055] dark:text-gray-100"
              />
            </label>
            <label className="grid gap-1.5 text-xs font-medium text-gray-600 dark:text-gray-300">
              替换后的文字
              <input
                value={draftTo}
                onChange={(event) => setDraftTo(event.target.value)}
                placeholder="例如：找嘎"
                className="h-9 rounded-lg border border-gray-200/70 bg-white px-3 text-sm font-normal text-gray-900 outline-none focus:border-indigo-400 dark:border-white/10 dark:bg-white/[0.055] dark:text-gray-100"
              />
            </label>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              className="h-8 gap-1.5"
              onClick={resetForm}
              disabled={saving}
            >
              <X className="size-3.5" />
              取消
            </Button>
            <Button
              type="button"
              className="h-8 gap-1.5"
              onClick={() => void handleSaveDraft()}
              disabled={saving || !draftFrom.trim() || !draftTo.trim()}
            >
              {saving ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Save className="size-3.5" />
              )}
              保存
            </Button>
          </div>
        </div>
      ) : null}

      <div
        ref={listScrollRef}
        className="mt-4 overflow-y-auto overscroll-contain pr-1 [scrollbar-gutter:stable]"
        style={listScrollStyle}
      >
        <div className="overflow-hidden rounded-lg border border-gray-200/70 bg-white/70 dark:border-white/10 dark:bg-white/[0.035]">
          {loading ? (
            <div className="flex items-center gap-2 px-3 py-4 text-xs text-gray-500">
              <Loader2 className="size-3.5 animate-spin" />
              正在加载
            </div>
          ) : rules.length ? (
            <div className="divide-y divide-gray-200/70 dark:divide-white/10">
              {rules.map((rule, index) => (
                <div
                  key={`${rule.from}-${rule.to}-${index}`}
                  className="grid gap-3 px-3 py-2.5 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto] md:items-center"
                >
                  <div className="min-w-0">
                    <div className="mb-1 text-[11px] font-semibold text-gray-400 dark:text-gray-500">
                      原文
                    </div>
                    {editingIndex === index ? (
                      <input
                        value={draftFrom}
                        onChange={(event) => setDraftFrom(event.target.value)}
                        className="h-8 w-full rounded-md border border-indigo-200 bg-white px-2 text-xs text-gray-900 outline-none focus:border-indigo-400 dark:border-indigo-900/60 dark:bg-white/[0.055] dark:text-gray-100"
                      />
                    ) : (
                      <div className="truncate rounded-md bg-gray-50 px-2 py-1.5 text-xs text-gray-800 dark:bg-black/20 dark:text-gray-200">
                        {rule.from}
                      </div>
                    )}
                  </div>
                  <div className="hidden text-xs text-gray-400 md:block">→</div>
                  <div className="min-w-0">
                    <div className="mb-1 text-[11px] font-semibold text-gray-400 dark:text-gray-500">
                      替换后的文字
                    </div>
                    {editingIndex === index ? (
                      <input
                        value={draftTo}
                        onChange={(event) => setDraftTo(event.target.value)}
                        className="h-8 w-full rounded-md border border-indigo-200 bg-white px-2 text-xs text-gray-900 outline-none focus:border-indigo-400 dark:border-indigo-900/60 dark:bg-white/[0.055] dark:text-gray-100"
                      />
                    ) : (
                      <div className="truncate rounded-md bg-gray-50 px-2 py-1.5 text-xs text-gray-800 dark:bg-black/20 dark:text-gray-200">
                        {rule.to}
                      </div>
                    )}
                  </div>
                  <div className="flex justify-end gap-1.5">
                    {editingIndex === index ? (
                      <>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-8 gap-1.5"
                          onClick={resetForm}
                          disabled={saving}
                        >
                          <X className="size-3.5" />
                          取消
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          className="h-8 gap-1.5"
                          onClick={() => void handleSaveDraft()}
                          disabled={saving || !draftFrom.trim() || !draftTo.trim()}
                        >
                          {saving ? (
                            <Loader2 className="size-3.5 animate-spin" />
                          ) : (
                            <Save className="size-3.5" />
                          )}
                          保存
                        </Button>
                      </>
                    ) : (
                      <>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-8 gap-1.5"
                          onClick={() => handleEdit(index)}
                          disabled={saving}
                        >
                          <PencilLine className="size-3.5" />
                          修改
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="destructive"
                          className="h-8 gap-1.5"
                          onClick={() => void handleDelete(index)}
                          disabled={saving}
                        >
                          <Trash2 className="size-3.5" />
                          删除
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="px-3 py-5 text-center text-xs text-gray-500 dark:text-gray-400">
              暂无提示词替换规则，点击添加创建第一条。
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
