import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { Loader2, PencilLine, Save, Sparkles, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import { errMsg } from "@/shared/backend-result"
import { useAdaptivePaneScroll } from "@/features/settings/adaptive-pane-scroll"
import { TEMPLATE_EDIT_ICON_BUTTON_CLS, normalizeTemplateName } from "./shared-template"
import { AutoResizeTextarea } from "./auto-resize-textarea"

export type ScriptAdaptationTemplateOption = {
  id: string
  name: string
  desc?: string
  description?: string
  badge?: string
  source?: string
  prompt?: string
  rules?: string[]
  base_template_id?: string
  derived_from_template_id?: string
}

export function libraryTemplateDescription(
  template?: Pick<ScriptAdaptationTemplateOption, "desc" | "description">
) {
  return String(template?.desc || template?.description || "").trim()
}

export function ScriptAdaptationTemplateSettings() {
  const { backendReady, callBackend } = useBackend()
  const { listScrollRef, detailScrollRef, listScrollStyle, detailScrollStyle } =
    useAdaptivePaneScroll()
  const [templates, setTemplates] = useState<ScriptAdaptationTemplateOption[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deletingId, setDeletingId] = useState("")
  const [formOpen, setFormOpen] = useState(false)
  const [editingId, setEditingId] = useState("")
  const [baseTemplateId, setBaseTemplateId] = useState("")
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [prompt, setPrompt] = useState("")

  const selected =
    templates.find((template) => template.id === selectedId) ?? templates[0]
  const customTemplates = templates.filter((template) => template.source !== "builtin")
  const duplicateName = templates.find(
    (template) =>
      template.id !== editingId &&
      normalizeTemplateName(template.name) === normalizeTemplateName(name)
  )
  const canSave = Boolean(name.trim() && prompt.trim() && !duplicateName)

  const templatePromptText = (template: ScriptAdaptationTemplateOption | undefined) =>
    String(template?.prompt || template?.rules?.join("\n") || "").trim()

  const nextCopyName = (template: ScriptAdaptationTemplateOption | undefined) => {
    const baseName = template?.name || "片段剧本策略"
    let index = 1
    let nextName = `${baseName} · 自定义 ${index}`
    const exists = (value: string) =>
      templates.some(
        (item) => normalizeTemplateName(item.name) === normalizeTemplateName(value)
      )
    while (exists(nextName)) {
      index += 1
      nextName = `${baseName} · 自定义 ${index}`
    }
    return nextName
  }

  const loadTemplates = useCallback(async () => {
    if (!backendReady) return
    setLoading(true)
    try {
      const result = await callBackend<{
        success?: boolean
        message?: string
        templates?: ScriptAdaptationTemplateOption[]
      }>("get_script_adaptation_templates")
      if (result.success === false) {
        throw new Error(result.message || "加载片段剧本策略失败")
      }
      const nextTemplates = result.templates ?? []
      setTemplates(nextTemplates)
      setSelectedId((current) =>
        nextTemplates.some((item) => item.id === current)
          ? current
          : (nextTemplates[0]?.id ?? "")
      )
    } catch (err: unknown) {
      toast.error(errMsg(err, "加载片段剧本策略失败"))
    } finally {
      setLoading(false)
    }
  }, [backendReady, callBackend])

  useEffect(() => {
    void loadTemplates()
  }, [loadTemplates])

  const resetForm = () => {
    setFormOpen(false)
    setEditingId("")
    setBaseTemplateId("")
    setName("")
    setDescription("")
    setPrompt("")
  }

  const handleSelectTemplate = (template: ScriptAdaptationTemplateOption) => {
    setSelectedId(template.id)
    setFormOpen(false)
  }

  const handleEditTemplate = (template: ScriptAdaptationTemplateOption | undefined) => {
    if (!template) return
    const isBuiltin = template.source === "builtin"
    setEditingId(isBuiltin ? "" : template.id)
    setBaseTemplateId(
      String(
        template.base_template_id ||
          template.derived_from_template_id ||
          template.id ||
          ""
      )
    )
    setName(isBuiltin ? nextCopyName(template) : template.name)
    setDescription(libraryTemplateDescription(template))
    setPrompt(templatePromptText(template))
    setSelectedId(template.id)
    setFormOpen(true)
    toast.info(isBuiltin ? "已复制到自定义编辑区" : "已载入自定义策略")
  }

  const handleSave = async () => {
    if (!backendReady) {
      toast.error("后端未就绪，暂时不能保存策略")
      return
    }
    if (!canSave) {
      toast.info(duplicateName ? "策略标题不能重复" : "请填写策略标题和创作指导")
      return
    }
    setSaving(true)
    try {
      const result = await callBackend<{
        success?: boolean
        message?: string
        template?: ScriptAdaptationTemplateOption
        templates?: ScriptAdaptationTemplateOption[]
      }>("save_script_adaptation_template", {
        template: {
          id: editingId || null,
          base_template_id: baseTemplateId || undefined,
          derived_from_template_id: baseTemplateId || undefined,
          name: name.trim(),
          description: description.trim() || name.trim(),
          prompt: prompt.trim(),
          source: "user_generated",
        },
      })
      if (result.success === false) {
        throw new Error(result.message || "保存片段剧本策略失败")
      }
      const nextTemplates = result.templates ?? templates
      setTemplates(nextTemplates)
      const savedId =
        result.template?.id ??
        nextTemplates.find(
          (template) =>
            template.source !== "builtin" &&
            normalizeTemplateName(template.name) === normalizeTemplateName(name)
        )?.id ??
        nextTemplates[0]?.id ??
        ""
      setSelectedId(savedId)
      resetForm()
      toast.success("片段剧本策略已保存")
    } catch (err: unknown) {
      toast.error(errMsg(err, "保存片段剧本策略失败"))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (template: ScriptAdaptationTemplateOption) => {
    if (template.source === "builtin") {
      toast.error("内置策略不能删除")
      return
    }
    setDeletingId(template.id)
    try {
      const result = await callBackend<{
        success?: boolean
        message?: string
        templates?: ScriptAdaptationTemplateOption[]
      }>("delete_script_adaptation_template", { templateId: template.id })
      if (result.success === false) {
        throw new Error(result.message || "删除片段剧本策略失败")
      }
      const nextTemplates = result.templates ?? []
      setTemplates(nextTemplates)
      setSelectedId(nextTemplates[0]?.id ?? "")
      if (editingId === template.id) {
        resetForm()
      }
      toast.success("片段剧本策略已删除")
    } catch (err: unknown) {
      toast.error(errMsg(err, "删除片段剧本策略失败"))
    } finally {
      setDeletingId("")
    }
  }

  return (
    <div className="grid gap-4 rounded-xl border border-gray-200/70 bg-white/65 p-4 shadow-sm dark:border-white/10 dark:bg-white/[0.045] lg:grid-cols-[minmax(240px,0.38fr)_minmax(0,1fr)]">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-xs font-semibold text-gray-900 dark:text-gray-100">
          <Sparkles className="size-3.5 text-indigo-500" />
          片段剧本策略
        </div>
        <div
          ref={listScrollRef}
          className="mt-3 overflow-y-auto overscroll-contain pr-1 [scrollbar-gutter:stable]"
          style={listScrollStyle}
        >
          <div className="space-y-2">
            {loading ? (
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <Loader2 className="size-3.5 animate-spin" />
                正在加载
              </div>
            ) : templates.length ? (
              templates.map((template) => (
                <div
                  key={template.id}
                  className={cn(
                    "flex w-full items-start overflow-hidden rounded-lg border text-xs transition-colors",
                    selected?.id === template.id
                      ? "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
                      : "border-gray-200/70 bg-white/70 text-gray-600 hover:border-indigo-200 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400"
                  )}
                >
                  <button
                    type="button"
                    className="min-w-0 flex-1 px-3 py-2 text-left"
                    onClick={() => handleSelectTemplate(template)}
                  >
                    <span className="font-semibold">{template.name}</span>
                    <span className="ml-2 opacity-60">{template.badge}</span>
                  </button>
                  <button
                    type="button"
                    className={TEMPLATE_EDIT_ICON_BUTTON_CLS}
                    title={
                      template.source === "builtin"
                        ? "复制为自定义策略"
                        : "编辑自定义策略"
                    }
                    aria-label={
                      template.source === "builtin"
                        ? "复制为自定义策略"
                        : "编辑自定义策略"
                    }
                    onClick={() => handleEditTemplate(template)}
                  >
                    <PencilLine className="size-3.5" />
                  </button>
                </div>
              ))
            ) : (
              <p className="text-xs text-gray-500">暂无策略。</p>
            )}
          </div>
        </div>
      </div>
      <div className="min-w-0">
        {formOpen ? (
          <div
            ref={detailScrollRef}
            className="grid gap-3 overflow-y-auto overscroll-contain pr-1 [scrollbar-gutter:stable]"
            style={detailScrollStyle}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-gray-950 dark:text-gray-50">
                  {editingId ? "编辑自定义策略" : "复制为自定义策略"}
                </h3>
              </div>
              {editingId ? (
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  className="h-8 gap-1.5"
                  onClick={() => {
                    const target = templates.find((item) => item.id === editingId)
                    if (target) void handleDelete(target)
                  }}
                  disabled={Boolean(deletingId)}
                >
                  {deletingId === editingId ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="size-3.5" />
                  )}
                  删除
                </Button>
              ) : null}
            </div>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="自定义策略标题"
              className="h-9 rounded-lg border border-gray-200/70 bg-white/70 px-3 text-sm outline-none focus:border-indigo-400 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-100"
            />
            {duplicateName ? (
              <p className="-mt-2 text-[11px] text-rose-500 dark:text-rose-300">
                策略标题不能重复。
              </p>
            ) : null}
            <input
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="简短描述"
              className="h-9 rounded-lg border border-gray-200/70 bg-white/70 px-3 text-sm outline-none focus:border-indigo-400 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-100"
            />
            <label className="grid gap-1.5 text-xs font-medium text-gray-600 dark:text-gray-300">
              编剧创作指导
              <AutoResizeTextarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="描述节奏、表演、对白和情绪应该怎样表达。"
                className="min-h-32"
              />
            </label>
            <div className="flex items-center justify-between gap-3">
              {customTemplates.length ? (
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  已保存 {customTemplates.length} 个自定义策略
                </span>
              ) : (
                <span />
              )}
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="h-9"
                  onClick={resetForm}
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
                  保存策略
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <div className="min-w-0">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-gray-950 dark:text-gray-50">
                  {selected?.name ?? "未选择策略"}
                </h3>
                <p className="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                  {libraryTemplateDescription(selected)}
                </p>
              </div>
              {selected && selected.source !== "builtin" ? (
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  className="h-8 gap-1.5"
                  onClick={() => void handleDelete(selected)}
                  disabled={Boolean(deletingId)}
                >
                  {deletingId === selected.id ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="size-3.5" />
                  )}
                  删除
                </Button>
              ) : null}
            </div>
            <div className="mt-3 grid gap-3">
              <div>
                <p className="text-[11px] font-semibold text-gray-500 dark:text-gray-400">
                  编剧创作指导
                </p>
                <pre
                  ref={detailScrollRef}
                  className="mt-1 overflow-auto overscroll-contain rounded-lg border border-gray-200/70 bg-gray-50 p-3 text-[12px] leading-relaxed whitespace-pre-wrap text-gray-700 dark:border-white/10 dark:bg-black/20 dark:text-gray-300"
                  style={detailScrollStyle}
                >
                  {templatePromptText(selected) || "该策略暂无创作指导。"}
                </pre>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
