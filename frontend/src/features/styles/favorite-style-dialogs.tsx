import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { AlertTriangle, Image, Upload } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ASSET_NAME_DUPLICATE_MESSAGE } from "@/features/asset-model"
import { normalizeFavoriteStyleName } from "@/features/styles/naming"
import type {
  FavoriteStyleConfirmDraft,
  StyleFilePayload,
  StyleTemplateOption,
} from "@/features/styles/types"
import { useBackend } from "@/hooks/useBackend"
import { FramedTextarea } from "@/shared/framed-fields"
import { pickLocalImageFile } from "@/shared/image-picker"
import { imagePayloadPreviewSrc } from "@/shared/media"
import { ModalShell } from "@/shared/page-shell"
import { UnifiedMediaFrame } from "@/shared/unified-media-frame"
import { resolveStyleTemplateThumbnailUrl } from "@/utils/style-thumbnails"

function styleAssetPrompt(
  template: StyleTemplateOption | null | undefined,
  kind: "character" | "creature"
) {
  if (!template) return ""
  if (kind === "character") {
    return (
      template.characterAssetPrompt ?? template.character_asset_prompt ?? ""
    )
  }
  return template.creatureAssetPrompt ?? template.creature_asset_prompt ?? ""
}

export function FavoriteStyleEditDialog({
  template,
  existingTemplates,
  onClose,
  onSaved,
}: {
  template: StyleTemplateOption
  existingTemplates: StyleTemplateOption[]
  onClose: () => void
  onSaved: (template: StyleTemplateOption) => void
}) {
  const { callBackend } = useBackend()
  const [name, setName] = useState(template.name)
  const [prompt, setPrompt] = useState(template.prompt ?? "")
  const [characterAssetPrompt, setCharacterAssetPrompt] = useState(
    styleAssetPrompt(template, "character")
  )
  const [creatureAssetPrompt, setCreatureAssetPrompt] = useState(
    styleAssetPrompt(template, "creature")
  )
  const [styleFile, setStyleFile] = useState<StyleFilePayload | null>(null)
  const [thumbnailSrc, setThumbnailSrc] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const src = await resolveStyleTemplateThumbnailUrl(template)
      if (!cancelled) setThumbnailSrc(src)
    })()
    return () => {
      cancelled = true
    }
  }, [
    template.thumbnailFile,
    template.thumbnailUrl,
    template.thumbnail_file,
    template.thumbnailPath,
    template.thumbnail_path,
    template.filePath,
    template.file_path,
    template.path,
    template.relativePath,
    template.relative_path,
    template.source,
  ])

  const preview = imagePayloadPreviewSrc(styleFile) ?? thumbnailSrc

  const handlePickFile = async () => {
    const file = await pickLocalImageFile("上传风格图")
    if (file) setStyleFile(file)
  }

  const handleSave = async () => {
    const nextName = name.trim()
    const nextPrompt = prompt.trim()
    if (!nextName) {
      toast.error("收藏风格名称不能为空")
      return
    }
    if (!nextPrompt) {
      toast.error("收藏风格提示词不能为空")
      return
    }
    const nextKey = normalizeFavoriteStyleName(nextName)
    const duplicate = existingTemplates.find(
      (item) =>
        item.id !== template.id &&
        normalizeFavoriteStyleName(item.name) === nextKey
    )
    if (duplicate) {
      toast.error(ASSET_NAME_DUPLICATE_MESSAGE)
      return
    }
    setSaving(true)
    try {
      const result = await callBackend<{
        success?: boolean
        message?: string
        template?: StyleTemplateOption
      }>("update_favorite_style_template", {
        templateId: template.id,
        name: nextName,
        desc: "",
        prompt: nextPrompt,
        characterAssetPrompt: characterAssetPrompt.trim(),
        creatureAssetPrompt: creatureAssetPrompt.trim(),
        styleFile,
      })
      if (result.success === false || !result.template) {
        throw new Error(result.message || "保存收藏风格失败")
      }
      toast.success("收藏风格已保存")
      onSaved(result.template)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存收藏风格失败")
    } finally {
      setSaving(false)
    }
  }

  return (
    <ModalShell
      title="编辑收藏风格"
      onClose={onClose}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            取消
          </Button>
          <Button onClick={() => void handleSave()} disabled={saving}>
            {saving ? "保存中" : "保存"}
          </Button>
        </>
      }
    >
      <div className="grid gap-5 md:grid-cols-[260px_minmax(0,1fr)]">
        <div className="space-y-3">
          <UnifiedMediaFrame
            src={preview}
            alt={name || "收藏风格图"}
            title={name || "收藏风格图"}
            className="aspect-[4/3]"
            interactive={Boolean(preview)}
            showActions={Boolean(preview)}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 w-full gap-1.5 text-xs"
            onClick={() => void handlePickFile()}
          >
            <Upload className="size-3.5" />
            上传风格图
          </Button>
        </div>
        <div className="space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
              风格名称
            </span>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="h-9 bg-white/70"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
              提示词
            </span>
            <FramedTextarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              containerClassName="min-h-[180px] rounded-xl"
              className="min-h-[176px] resize-y"
            />
          </label>
          <div className="grid gap-3">
            {[
              {
                label: "角色视觉",
                value: characterAssetPrompt,
                onChange: setCharacterAssetPrompt,
              },
              {
                label: "生物视觉",
                value: creatureAssetPrompt,
                onChange: setCreatureAssetPrompt,
              },
            ].map((field) => (
              <label className="block" key={field.label}>
                <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
                  {field.label}
                </span>
                <FramedTextarea
                  value={field.value}
                  onChange={(event) => field.onChange(event.target.value)}
                  placeholder="为空时使用全局视觉风格。"
                  containerClassName="min-h-[92px] rounded-xl"
                  className="min-h-[88px] resize-y"
                />
              </label>
            ))}
          </div>
        </div>
      </div>
    </ModalShell>
  )
}

export function FavoriteStyleConfirmDialog({
  draft,
  onClose,
  onSaved,
}: {
  draft: FavoriteStyleConfirmDraft
  onClose: () => void
  onSaved: (template: StyleTemplateOption) => void
}) {
  const { callBackend } = useBackend()
  const [name, setName] = useState(draft.name)
  const [duplicateTemplate, setDuplicateTemplate] =
    useState<StyleTemplateOption | null>(null)
  const [saving, setSaving] = useState(false)
  const preview = draft.preview ?? imagePayloadPreviewSrc(draft.styleFile)

  const matchingTemplate = useMemo(() => {
    const key = normalizeFavoriteStyleName(name)
    if (!key) return null
    return (
      draft.existingTemplates.find(
        (template) => normalizeFavoriteStyleName(template.name) === key
      ) ?? null
    )
  }, [draft.existingTemplates, name])

  useEffect(() => {
    setDuplicateTemplate(null)
  }, [name])

  const saveFavoriteStyle = async (overwrite = false) => {
    const nextName = name.trim()
    const nextPrompt = draft.prompt.trim()
    if (!nextName) {
      toast.error("收藏风格标题不能为空")
      return
    }
    if (!nextPrompt) {
      toast.error("收藏风格提示词不能为空")
      return
    }
    setSaving(true)
    try {
      const result = await callBackend<{
        success?: boolean
        code?: string
        message?: string
        template?: StyleTemplateOption
        duplicate?: StyleTemplateOption
      }>("create_favorite_style_template", {
        name: nextName,
        desc: "",
        prompt: nextPrompt,
        characterAssetPrompt: draft.characterAssetPrompt.trim(),
        creatureAssetPrompt: draft.creatureAssetPrompt.trim(),
        styleFile: draft.styleFile,
        overwrite,
      })
      if (result.success === false) {
        if (result.code === "duplicate_name") {
          setDuplicateTemplate(result.duplicate ?? matchingTemplate)
          return
        }
        throw new Error(result.message || "收藏当前风格失败")
      }
      if (!result.template) {
        throw new Error(result.message || "收藏当前风格失败")
      }
      toast.success(overwrite ? "收藏风格已覆盖" : "已收藏当前风格")
      onSaved(result.template)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "收藏当前风格失败")
    } finally {
      setSaving(false)
    }
  }

  const handleConfirm = () => {
    if (matchingTemplate) {
      setDuplicateTemplate(matchingTemplate)
      return
    }
    void saveFavoriteStyle(false)
  }

  return (
    <ModalShell
      title="收藏风格"
      description="确认后会加入全局资产的收藏风格列表。"
      onClose={onClose}
      footer={
        <>
          {duplicateTemplate ? (
            <>
              <Button
                variant="outline"
                onClick={() => setDuplicateTemplate(null)}
                disabled={saving}
              >
                取消
              </Button>
              <Button
                className="bg-amber-600 text-white hover:bg-amber-500"
                onClick={() => void saveFavoriteStyle(true)}
                disabled={saving}
              >
                {saving ? "覆盖中" : "覆盖"}
              </Button>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={onClose} disabled={saving}>
                取消
              </Button>
              <Button onClick={handleConfirm} disabled={saving}>
                {saving ? "收藏中" : "确认收藏"}
              </Button>
            </>
          )}
        </>
      }
    >
      <div className="grid gap-5 md:grid-cols-[260px_minmax(0,1fr)]">
        <div className="relative aspect-[4/3] overflow-hidden rounded-md border border-gray-200/80 bg-gray-100 dark:border-white/10 dark:bg-white/[0.04]">
          {preview ? (
            <UnifiedMediaFrame
              src={preview}
              alt={name}
              title={name}
              className="absolute inset-0 rounded-none border-0"
              interactive={false}
              showActions={false}
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-gray-400">
              <Image className="size-6" />
              <span className="text-xs">未读取到风格图片</span>
            </div>
          )}
        </div>
        <div className="space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
              标题
            </span>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="h-9 bg-white/70"
              placeholder="输入收藏风格标题"
            />
          </label>
          <div className="block">
            <span className="mb-1.5 block text-xs text-gray-500 dark:text-gray-400">
              提示词
            </span>
            <div className="max-h-[240px] overflow-auto rounded-xl border border-gray-200/70 bg-white/70 p-3 text-xs leading-relaxed text-gray-700 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-300">
              {draft.prompt}
            </div>
          </div>
          {duplicateTemplate ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs leading-relaxed text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                <span>
                  {`已存在同名收藏风格「${duplicateTemplate.name}」，是否覆盖？选择覆盖会用当前图片和提示词替换原收藏；取消后可继续修改标题。`}
                </span>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </ModalShell>
  )
}
