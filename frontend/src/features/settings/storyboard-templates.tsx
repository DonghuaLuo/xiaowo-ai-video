import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { Loader2, PencilLine, Save, Sparkles, Trash2 } from "lucide-react"

import {
  deleteStoryboardTemplate,
  getStoryboardTemplates,
  saveStoryboardTemplate,
  type StoryboardTemplateOption,
} from "@/backend"
import { Button } from "@/components/ui/button"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import { errMsg } from "@/shared/backend-result"
import { useAdaptivePaneScroll } from "@/features/settings/adaptive-pane-scroll"
import {AutoResizeTextarea} from '@/features/settings/auto-resize-textarea'
import {TEMPLATE_EDIT_ICON_BUTTON_CLS,normalizeTemplateName} from '@/features/settings/shared-template'

export type { StoryboardTemplateOption }

export function normalizeStoryboardTemplate(raw: any): StoryboardTemplateOption {
  const title = String(
    raw?.title ?? raw?.label ?? raw?.name ?? raw?.id ?? "分镜图版式"
  )
  const description = String(
    raw?.description ??
      raw?.desc ??
      raw?.summary ??
      raw?.shortDescription ??
      raw?.short_description ??
      ""
  )
  return {
    id: String(raw?.id ?? ""),
    title,
    label: title,
    name: title,
    desc: description,
    description,
    summary: description,
    badge: String(raw?.badge ?? (raw?.source === "builtin" ? "预设" : "自定义")),
    source: String(raw?.source ?? "builtin"),
    prompt: String(raw?.prompt ?? ""),
    effectivePrompt: String(raw?.effectivePrompt ?? ""),
    base_template_id: raw?.base_template_id,
    derived_from_template_id: raw?.derived_from_template_id,
    layoutSlots: raw?.layoutSlots ?? raw?.layout_slots,
    layout_slots: raw?.layout_slots ?? raw?.layoutSlots,
    fixedShotSlots: Number(raw?.fixedShotSlots ?? raw?.fixed_shot_slots ?? 0),
    fixed_shot_slots: Number(raw?.fixed_shot_slots ?? raw?.fixedShotSlots ?? 0),
    minShotSlots: Number(raw?.minShotSlots ?? raw?.min_shot_slots ?? 1),
    min_shot_slots: Number(raw?.min_shot_slots ?? raw?.minShotSlots ?? 1),
    maxShotSlots: Number(raw?.maxShotSlots ?? raw?.max_shot_slots ?? 5),
    max_shot_slots: Number(raw?.max_shot_slots ?? raw?.maxShotSlots ?? 5),
    layoutSpec: raw?.layoutSpec ?? raw?.layout_spec,
    layout_spec: raw?.layout_spec ?? raw?.layoutSpec,
    requiredSections: Array.isArray(raw?.requiredSections ?? raw?.required_sections)
      ? (raw?.requiredSections ?? raw?.required_sections).map(String)
      : [],
    required_sections: Array.isArray(raw?.required_sections ?? raw?.requiredSections)
      ? (raw?.required_sections ?? raw?.requiredSections).map(String)
      : [],
  }
}

export function storyboardTemplateDisplayName(
  template: StoryboardTemplateOption | undefined
) {
  return template?.title || template?.name || template?.label || template?.id || "分镜图版式"
}

export function storyboardTemplateDisplayDescription(
  template: StoryboardTemplateOption | undefined
) {
  return (
    template?.desc ||
    template?.description ||
    template?.summary ||
    "暂无描述。"
  )
}

export function storyboardTemplatePromptText(
  template: StoryboardTemplateOption | undefined
) {
  return template?.effectivePrompt?.trim() ?? ""
}

export function StoryboardTemplateSettings() {
  const { backendReady, callBackend } = useBackend()
  const {
    listScrollRef,
    detailScrollRef,
    listScrollStyle,
    detailScrollStyle,
  } = useAdaptivePaneScroll()
  const [templates, setTemplates] = useState<StoryboardTemplateOption[]>(
    []
  )
  const [selectedId, setSelectedId] = useState("")
  const [customTitle, setCustomTitle] = useState("")
  const [customDescription, setCustomDescription] = useState("")
  const [customPrompt, setCustomPrompt] = useState("")
  const [customEditingId, setCustomEditingId] = useState("")
  const [customBaseTemplateId, setCustomBaseTemplateId] = useState("")
  const [customFormOpen, setCustomFormOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [deletingTemplateId, setDeletingTemplateId] = useState("")
  const [error, setError] = useState<string | null>(null)

  const selected =
    templates.find((template) => template.id === selectedId) ?? templates[0]
  const presetTemplates = templates.filter((template) => template.source === "builtin")
  const duplicateTitle = templates.find(
    (template) =>
      template.id !== customEditingId &&
      normalizeTemplateName(storyboardTemplateDisplayName(template)) ===
        normalizeTemplateName(customTitle)
  )
  const canSaveCustom = Boolean(
    customTitle.trim() &&
      customDescription.trim() &&
      customPrompt.trim() &&
      customBaseTemplateId.trim() &&
      !duplicateTitle
  )

  const applyTemplates = useCallback(
    (rawTemplates: any[] | undefined, preferredId?: string) => {
      const nextTemplates = (rawTemplates ?? []).map(normalizeStoryboardTemplate)
      const fallbackId = nextTemplates[0]?.id ?? ""
      const nextSelectedId =
        preferredId && nextTemplates.some((template) => template.id === preferredId)
          ? preferredId
          : fallbackId
      setTemplates(nextTemplates)
      setSelectedId(nextSelectedId)
      return nextTemplates
    },
    []
  )

  const loadTemplates = useCallback(async () => {
    if (!backendReady) {
      applyTemplates([])
      setError("后端未就绪，无法加载分镜图版式")
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const nextTemplates = await getStoryboardTemplates(callBackend)
      applyTemplates(nextTemplates)
      setError(null)
    } catch (err: unknown) {
      applyTemplates([])
      setError(errMsg(err, "加载分镜图版式失败"))
    } finally {
      setLoading(false)
    }
  }, [applyTemplates, backendReady, callBackend])

  useEffect(() => {
    void loadTemplates()
  }, [loadTemplates])

  const resetCustomForm = () => {
    setCustomFormOpen(false)
    setCustomEditingId("")
    setCustomBaseTemplateId("")
    setCustomTitle("")
    setCustomDescription("")
    setCustomPrompt("")
  }

  const nextCopyName = (template: StoryboardTemplateOption | undefined) => {
    const baseName = template
      ? storyboardTemplateDisplayName(template)
      : "分镜图版式"
    let index = 1
    let nextName = `${baseName} · 自定义 ${index}`
    const exists = (name: string) =>
      templates.some(
        (item) =>
          normalizeTemplateName(storyboardTemplateDisplayName(item)) ===
          normalizeTemplateName(name)
      )
    while (exists(nextName)) {
      index += 1
      nextName = `${baseName} · 自定义 ${index}`
    }
    return nextName
  }

  const handleSelectTemplate = (template: StoryboardTemplateOption) => {
    setSelectedId(template.id)
    setCustomFormOpen(false)
  }

  const handleEditTemplate = (
    template: StoryboardTemplateOption | undefined
  ) => {
    if (!template) return
    const isBuiltin = template.source === "builtin"
    setCustomEditingId(isBuiltin ? "" : template.id)
    setCustomBaseTemplateId(
      template.base_template_id ||
        template.derived_from_template_id ||
        template.id ||
        presetTemplates[0]?.id ||
        ""
    )
    setCustomTitle(
      isBuiltin ? nextCopyName(template) : storyboardTemplateDisplayName(template)
    )
    setCustomDescription(storyboardTemplateDisplayDescription(template))
    setCustomPrompt(storyboardTemplatePromptText(template))
    setSelectedId(template.id)
    setCustomFormOpen(true)
    toast.info(isBuiltin ? "已复制到自定义编辑区" : "已载入自定义版式")
  }

  const handleSaveCustom = async () => {
    if (!backendReady) {
      toast.error("后端未就绪，暂时不能保存分镜图版式")
      return
    }
    if (!canSaveCustom) {
      toast.info(
        duplicateTitle
          ? "分镜图版式标题不能重复"
          : "请填写版式标题、简短描述、来源版式和具体版式规则"
      )
      return
    }
    setSaving(true)
    try {
      const nextTemplates = await saveStoryboardTemplate(callBackend, {
        id: customEditingId || null,
        title: customTitle.trim(),
        name: customTitle.trim(),
        label: customTitle.trim(),
        description: customDescription.trim(),
        prompt: customPrompt.trim(),
        base_template_id: customBaseTemplateId.trim(),
        derived_from_template_id: customBaseTemplateId.trim(),
        source: "user_generated",
      })
      const normalized = nextTemplates.map(normalizeStoryboardTemplate)
      const saved = normalized.find(
        (template) =>
          template.source !== "builtin" &&
          storyboardTemplateDisplayName(template) === customTitle.trim()
      )
      applyTemplates(normalized, saved?.id)
      resetCustomForm()
      toast.success("自定义分镜图版式已保存")
    } catch (err: unknown) {
      toast.error(errMsg(err, "保存分镜图版式失败"))
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteCustom = async (
    template: StoryboardTemplateOption | undefined
  ) => {
    if (!template) return
    if (template.source === "builtin") {
      toast.error("预设分镜图版式不能删除")
      return
    }
    if (!backendReady) {
      toast.error("后端未就绪，暂时不能删除分镜图版式")
      return
    }
    setDeletingTemplateId(template.id)
    try {
      const nextTemplates = await deleteStoryboardTemplate(callBackend, template.id)
      const normalized = nextTemplates.map(normalizeStoryboardTemplate)
      const nextCustom = normalized.find((item) => item.source !== "builtin")
      if (nextCustom) {
        applyTemplates(normalized, nextCustom.id)
      } else {
        const nextPreset = normalized.find((item) => item.source === "builtin")
        applyTemplates(normalized, nextPreset?.id)
      }
      if (customEditingId === template.id) {
        resetCustomForm()
      }
      toast.success("自定义分镜图版式已删除")
    } catch (err: unknown) {
      toast.error(errMsg(err, "删除分镜图版式失败"))
    } finally {
      setDeletingTemplateId("")
    }
  }

  return (
    <div className="grid gap-4 rounded-xl border border-gray-200/70 bg-white/65 p-4 shadow-sm dark:border-white/10 dark:bg-white/[0.045] lg:grid-cols-[minmax(240px,0.38fr)_minmax(0,1fr)]">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-xs font-semibold text-gray-900 dark:text-gray-100">
          <Sparkles className="size-3.5 text-indigo-500" />
          分镜图版式
        </div>
        <p className="mt-2 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
          分镜图版式只决定分镜图工作页的版面组织、辅助区和短标签呈现方式；右侧展示的是完整生效规则。
        </p>
        <div
          ref={listScrollRef}
          className="mt-3 overflow-y-auto overscroll-contain pr-1 [scrollbar-gutter:stable]"
          style={listScrollStyle}
        >
          <div className="space-y-2">
            {loading ? (
              <div className="flex items-center gap-2 rounded-lg border border-gray-200/70 bg-white/70 p-3 text-xs text-gray-500 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400">
                <Loader2 className="size-3.5 animate-spin text-indigo-500" />
                正在加载分镜图版式
              </div>
            ) : error ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-200">
                {error}
              </div>
            ) : templates.length ? (
              templates.map((template) => (
                <div
                  key={template.id}
                  className={cn(
                    "flex w-full items-start overflow-hidden rounded-lg border transition-colors",
                    selected?.id === template.id
                      ? "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
                      : "border-gray-200/70 bg-white/70 text-gray-600 hover:border-indigo-200 hover:text-gray-950 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400 dark:hover:text-gray-50"
                  )}
                >
                  <button
                    type="button"
                    className="min-w-0 flex-1 px-3 py-2 text-left"
                    onClick={() => handleSelectTemplate(template)}
                  >
                    <span className="block text-sm font-semibold">
                      {storyboardTemplateDisplayName(template)}
                    </span>
                    <span className="mt-1 block text-xs leading-relaxed opacity-75">
                      {storyboardTemplateDisplayDescription(template)}
                    </span>
                  </button>
                  <button
                    type="button"
                    className={TEMPLATE_EDIT_ICON_BUTTON_CLS}
                    title={
                      template.source === "builtin"
                        ? "复制为自定义版式"
                        : "编辑自定义版式"
                    }
                    aria-label={
                      template.source === "builtin"
                        ? "复制为自定义版式"
                        : "编辑自定义版式"
                    }
                    onClick={() => handleEditTemplate(template)}
                  >
                    <PencilLine className="size-3.5" />
                  </button>
                </div>
              ))
            ) : (
              <p className="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                暂无分镜图版式。
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="min-w-0">
        {customFormOpen ? (
          <div
            ref={detailScrollRef}
            className="grid min-w-0 gap-3 overflow-y-auto overscroll-contain pr-1 [scrollbar-gutter:stable]"
            style={detailScrollStyle}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="text-xs font-semibold text-gray-900 dark:text-gray-100">
                {customEditingId ? "编辑自定义版式" : "复制为自定义版式"}
              </div>
              {customEditingId ? (
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  className="h-8 gap-1.5"
                  onClick={() => {
                    const target = templates.find(
                      (item) => item.id === customEditingId
                    )
                    if (target) void handleDeleteCustom(target)
                  }}
                  disabled={Boolean(deletingTemplateId)}
                >
                  {deletingTemplateId === customEditingId ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="size-3.5" />
                  )}
                  删除
                </Button>
              ) : null}
            </div>
            <input
              value={customTitle}
              onChange={(event) => setCustomTitle(event.target.value)}
              placeholder="版式标题"
              className="h-9 min-w-0 rounded-lg border border-gray-200/70 bg-white/70 px-3 text-sm outline-none focus:border-indigo-400 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-100"
            />
            {duplicateTitle ? (
              <p className="-mt-2 text-[11px] text-rose-500 dark:text-rose-300">
                分镜图版式标题不能重复。
              </p>
            ) : null}
            <input
              value={customDescription}
              onChange={(event) => setCustomDescription(event.target.value)}
              placeholder="简短描述：精确总结版式特点，方便用户选择"
              className="h-9 min-w-0 rounded-lg border border-gray-200/70 bg-white/70 px-3 text-sm outline-none focus:border-indigo-400 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-100"
            />
            <AutoResizeTextarea
              value={customPrompt}
              onChange={(event) => setCustomPrompt(event.target.value)}
              placeholder="完整版式规则：说明分镜画格如何表达、是否包含辅助区域、辅助区域如何表达，以及整张分镜图如何排版。"
              className="min-h-40"
            />
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                className="h-9"
                onClick={resetCustomForm}
                disabled={saving}
              >
                取消
              </Button>
              <Button
                type="button"
                className="h-9 gap-1.5"
                onClick={() => void handleSaveCustom()}
                disabled={saving || !canSaveCustom}
              >
                {saving ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Save className="size-3.5" />
                )}
                保存版式
              </Button>
            </div>
          </div>
        ) : (
          <div className="min-w-0">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-gray-950 dark:text-gray-50">
                  {selected ? storyboardTemplateDisplayName(selected) : "未选择版式"}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-gray-600 dark:text-gray-300">
                  {selected ? storyboardTemplateDisplayDescription(selected) : ""}
                </p>
                {selected ? (
                  <p className="mt-2 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                    下方为该版式的完整生效规则；复制为自定义版式后可直接修改整份规则。
                  </p>
                ) : null}
              </div>
              {selected && selected.source !== "builtin" ? (
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  className="h-8 gap-1.5"
                  onClick={() => void handleDeleteCustom(selected)}
                  disabled={Boolean(deletingTemplateId)}
                >
                  {deletingTemplateId === selected.id ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="size-3.5" />
                  )}
                  删除
                </Button>
              ) : null}
            </div>
            <pre
              ref={detailScrollRef}
              className="mt-4 overflow-auto overscroll-contain rounded-lg border border-gray-200/70 bg-gray-50 p-3 text-[12px] leading-relaxed whitespace-pre-wrap text-gray-700 dark:border-white/10 dark:bg-black/20 dark:text-gray-300"
              style={detailScrollStyle}
            >
              {storyboardTemplatePromptText(selected) || "该版式暂无提示词。"}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
