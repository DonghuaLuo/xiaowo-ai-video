import { useEffect, useMemo, useState } from "react"
import {
  CheckCircle2,
  ImagePlus,
  PencilLine,
  SlidersHorizontal,
  Sparkles,
  Star,
  Trash2,
  X,
} from "lucide-react"
import type { InputImageFile } from "@/backend"
import { Button } from "@/components/ui/button"
import type {
  StyleCategory,
  StyleModeTabOption,
  StyleTemplateOption,
} from "@/features/styles/types"
import { styleTemplateVisualTypeTags } from "@/features/styles/general-style"
import { cn } from "@/lib/utils"
import { pickLocalImageFile } from "@/shared/image-picker"
import { UnifiedMediaFrame } from "@/shared/unified-media-frame"
import { resolveStyleTemplateThumbnailUrl } from "@/utils/style-thumbnails"

export function StyleModeTabs<TMode extends string>({
  value,
  onChange,
  modes,
}: {
  value: TMode
  onChange: (next: TMode) => void
  modes: StyleModeTabOption<TMode>[]
}) {
  return (
    <div className="flex w-fit gap-1 rounded-lg border border-gray-200/70 bg-white/70 p-1 dark:border-white/10 dark:bg-white/[0.035]">
      {modes.map(({ id, label }) => (
        <button
          key={id}
          type="button"
          className={cn(
            "rounded-md px-3 py-1.5 text-xs font-semibold transition-colors",
            value === id
              ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-300"
              : "text-gray-500 hover:text-gray-950 dark:text-gray-400 dark:hover:text-gray-50"
          )}
          onClick={() => onChange(id)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

export function StyleCategoryTabs({
  value,
  onChange,
  categories = [],
  templates = [],
}: {
  value: StyleCategory
  onChange: (next: StyleCategory) => void
  categories?: Array<{ id: StyleCategory; label: string }>
  templates?: StyleTemplateOption[]
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {categories.map((category) => {
        const count =
          category.id === "all"
            ? templates.length
            : templates.filter((template) => template.category === category.id).length
        return (
          <button
            key={category.id}
            type="button"
            className={cn(
              "rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors",
              value === category.id
                ? "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
                : "border-gray-200/70 bg-white/60 text-gray-500 hover:border-indigo-200 hover:text-gray-950 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400 dark:hover:text-gray-50"
            )}
            onClick={() => onChange(category.id)}
          >
            {category.label}
            <span className="ml-1 font-mono text-[10px] opacity-70">{count}</span>
          </button>
        )
      })}
    </div>
  )
}

export function StyleTemplateGrid({
  category,
  value,
  onChange,
  templates: allTemplates = [],
  compact = false,
  bounded = false,
  showFavoriteDelete = true,
}: {
  category: StyleCategory
  value: string
  onChange: (next: string) => void
  templates?: StyleTemplateOption[]
  compact?: boolean
  bounded?: boolean
  showFavoriteDelete?: boolean
}) {
  const templates = useMemo(
    () =>
      category === "all"
        ? allTemplates
        : allTemplates.filter((template) => template.category === category),
    [allTemplates, category]
  )
  const [thumbnailUrls, setThumbnailUrls] = useState<Record<string, string | null>>({})

  useEffect(() => {
    let cancelled = false
    void Promise.all(
      templates.map(async (template) => {
        return [template.id, await resolveStyleTemplateThumbnailUrl(template)] as const
      })
    ).then((entries) => {
      if (cancelled) return
      setThumbnailUrls((current) => {
        const next = { ...current }
        for (const [id, url] of entries) next[id] = url
        return next
      })
    })

    return () => {
      cancelled = true
    }
  }, [templates])

  return (
    <div
      className={cn(
        "grid gap-3 overflow-y-auto pr-1",
        bounded
          ? compact
            ? "max-h-[min(42dvh,430px)] sm:grid-cols-2 xl:grid-cols-3"
            : "max-h-[min(38dvh,420px)] md:grid-cols-3"
          : compact
            ? "max-h-[640px] sm:grid-cols-2 xl:grid-cols-3"
            : "max-h-[720px] md:grid-cols-3"
      )}
    >
      {templates.map((template) => {
        const thumbnailSrc = thumbnailUrls[template.id] ?? null
        const isFavorite = template.category === "favorite"
        const descriptionText = isFavorite
          ? template.prompt || template.desc
          : template.desc
        return (
          <button
            key={template.id}
            type="button"
            className={cn(
              "group overflow-hidden rounded-md border bg-white/70 text-left shadow-sm transition-colors dark:bg-white/[0.035]",
              value === template.id
                ? "border-indigo-300 ring-2 ring-indigo-200/70 dark:border-indigo-700 dark:ring-indigo-900/40"
                : "border-gray-200/70 dark:border-white/10"
            )}
            onClick={() => onChange(template.id)}
          >
            <div
              className={cn(
                "relative overflow-hidden bg-gradient-to-br",
                compact ? "h-52" : "h-64",
                template.accent
              )}
            >
              {thumbnailSrc ? (
                <UnifiedMediaFrame
                  src={thumbnailSrc}
                  alt={template.name}
                  title={template.name}
                  className="absolute inset-0 rounded-none border-0 transition-transform duration-200 group-hover:scale-[1.025]"
                  interactive={false}
                  showActions={false}
                />
              ) : (
                <div className="absolute inset-x-3 bottom-3 grid grid-cols-3 gap-1.5">
                  {Array.from({ length: 6 }).map((_, index) => (
                    <div
                      key={index}
                      className="aspect-[4/3] rounded border border-white/45 bg-white/25 backdrop-blur-sm"
                    />
                  ))}
                </div>
              )}
              <div className="absolute inset-0 bg-gradient-to-t from-black/65 via-black/10 to-black/20" />
              {showFavoriteDelete && template.category === "favorite" ? (
                <span className="absolute right-2 bottom-2 grid size-6 place-items-center rounded-full bg-black/45 text-white backdrop-blur-sm">
                  <Trash2 className="size-3.5" />
                </span>
              ) : null}
              {value === template.id ? (
                <span className="absolute top-2 right-2 grid size-6 place-items-center rounded-full bg-white text-indigo-600">
                  <CheckCircle2 className="size-3.5" />
                </span>
              ) : null}
            </div>
            <div className={cn(compact ? "p-2.5" : "p-3")}>
              <div className="truncate text-sm font-semibold text-gray-950 dark:text-gray-50">
                {template.name}
              </div>
              <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                {descriptionText || (isFavorite ? "暂无提示词" : "")}
              </p>
            </div>
          </button>
        )
      })}
    </div>
  )
}

export function GeneralStyleTagGroup({
  value,
  options,
  onChange,
}: {
  value: string
  options: string[]
  onChange: (next: string) => void
}) {
  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            className={cn(
              "rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors",
              value === option
                ? "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
                : "border-gray-200/70 bg-white/60 text-gray-500 hover:border-indigo-200 hover:text-gray-950 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400 dark:hover:text-gray-50"
            )}
            onClick={(event) => {
              event.stopPropagation()
              onChange(option)
            }}
          >
            {option}
          </button>
        ))}
      </div>
    </div>
  )
}

export function GeneralStyleTemplatePanel({
  template,
  value,
  onChange,
  visualTypeTag,
  onVisualTypeTagChange,
  compact = false,
}: {
  template?: StyleTemplateOption | null
  value: string
  onChange: (next: string) => void
  visualTypeTag: string
  onVisualTypeTagChange: (next: string) => void
  compact?: boolean
}) {
  const [thumbnailSrc, setThumbnailSrc] = useState<string | null>(null)

  useEffect(() => {
    if (!template) {
      setThumbnailSrc(null)
      return
    }
    let cancelled = false
    void resolveStyleTemplateThumbnailUrl(template).then((url) => {
      if (!cancelled) setThumbnailSrc(url)
    })
    return () => {
      cancelled = true
    }
  }, [
    template?.thumbnailFile,
    template?.thumbnailUrl,
    template?.thumbnail_file,
    template?.thumbnailPath,
    template?.thumbnail_path,
    template?.filePath,
    template?.file_path,
    template?.path,
    template?.relativePath,
    template?.relative_path,
    template?.source,
  ])

  if (!template) return null

  const selected = value === template.id
  const selectTemplate = () => {
    if (!selected) onChange(template.id)
  }

  return (
    <div
      className={cn(
        "grid gap-4 rounded-md border bg-white/70 p-3 shadow-sm dark:bg-white/[0.035]",
        selected
          ? "border-indigo-300 ring-2 ring-indigo-200/70 dark:border-indigo-700 dark:ring-indigo-900/40"
          : "border-gray-200/70 dark:border-white/10",
        compact
          ? "md:grid-cols-[220px_minmax(0,1fr)]"
          : "md:grid-cols-[260px_minmax(0,1fr)]"
      )}
      onClick={selectTemplate}
    >
      <div
        className={cn(
          "relative overflow-hidden rounded-md bg-gradient-to-br",
          compact ? "min-h-56" : "min-h-72",
          template.accent
        )}
      >
        {thumbnailSrc ? (
          <UnifiedMediaFrame
            src={thumbnailSrc}
            alt={template.name}
            title={template.name}
            className="absolute inset-0 rounded-none border-0"
            interactive={false}
            showActions={false}
          />
        ) : null}
        <div className="absolute inset-0 bg-gradient-to-t from-black/45 via-transparent to-black/10" />
        {selected ? (
          <span className="absolute top-2 right-2 grid size-6 place-items-center rounded-full bg-white text-indigo-600">
            <CheckCircle2 className="size-3.5" />
          </span>
        ) : null}
      </div>
      <div className="flex min-w-0 flex-col justify-start gap-5">
        <GeneralStyleTagGroup
          value={visualTypeTag}
          options={styleTemplateVisualTypeTags(template)}
          onChange={(next) => {
            selectTemplate()
            onVisualTypeTagChange(next)
          }}
        />
      </div>
    </div>
  )
}

export function StylePromptPreview({
  prompt,
  onEdit,
}: {
  prompt?: string | null
  onEdit?: () => void | Promise<void>
}) {
  const text = prompt?.trim()
  if (!text) return null

  return (
    <div className="rounded-xl border border-gray-200/70 bg-white/70 p-3 dark:border-white/10 dark:bg-white/[0.035]">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="text-xs font-semibold text-gray-700 dark:text-gray-200">
          当前风格提示词
        </div>
        {onEdit ? (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="修改为自定义风格"
            title="修改为自定义风格"
            className="size-6 text-gray-500 hover:text-indigo-600 dark:text-gray-400 dark:hover:text-indigo-300"
            onClick={() => void onEdit()}
          >
            <PencilLine className="size-3.5" />
          </Button>
        ) : null}
      </div>
      <p className="text-xs leading-relaxed text-gray-500 dark:text-gray-400">{text}</p>
    </div>
  )
}

export function CustomStyleEditor({
  stylePrompt = "精致国风3D美型设定图风格，高端国漫与游戏CG审美，角色、场景、道具保持统一东方幻想视觉语言。",
  characterStylePrompt = "",
  creatureStylePrompt = "",
  uploadedName,
  uploadedPreview,
  onStylePromptChange = () => {},
  onCharacterStylePromptChange = () => {},
  onCreatureStylePromptChange = () => {},
  onFileSelected = () => {},
  onClearFile,
  onFavorite,
  onAnalyze,
  analyzing = false,
  uploadLabel = "上传风格参考图",
}: {
  stylePrompt?: string
  characterStylePrompt?: string
  creatureStylePrompt?: string
  uploadedName?: string | null
  uploadedPreview?: string | null
  onStylePromptChange?: (value: string) => void
  onCharacterStylePromptChange?: (value: string) => void
  onCreatureStylePromptChange?: (value: string) => void
  onFileSelected?: (file: InputImageFile) => void
  onClearFile?: () => void
  onFavorite?: () => void
  onAnalyze?: () => void
  analyzing?: boolean
  uploadLabel?: string
}) {
  const imageActionLabel = uploadedPreview ? "替换风格图片" : "上传风格图片"
  const hasAssetStylePrompt = Boolean(
    characterStylePrompt.trim() || creatureStylePrompt.trim()
  )
  const [advancedOpen, setAdvancedOpen] = useState(hasAssetStylePrompt)
  useEffect(() => {
    if (hasAssetStylePrompt) setAdvancedOpen(true)
  }, [hasAssetStylePrompt])
  const handlePickImage = async () => {
    const file = await pickLocalImageFile(uploadLabel)
    if (file) onFileSelected(file)
  }

  return (
    <div className="grid gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
      <div
        role="button"
        tabIndex={0}
        aria-label={imageActionLabel}
        className="group relative flex min-h-[260px] cursor-pointer flex-col items-center justify-center gap-3 overflow-hidden rounded-md border border-dashed border-indigo-300 bg-indigo-50/35 p-5 text-center text-indigo-700 transition-colors hover:bg-indigo-50/45 focus-visible:ring-2 focus-visible:ring-indigo-400/60 focus-visible:outline-none dark:border-indigo-900/60 dark:bg-indigo-950/10 dark:text-indigo-300 dark:hover:bg-indigo-950/15"
        onClick={() => void handlePickImage()}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault()
            void handlePickImage()
          }
        }}
      >
        {uploadedPreview ? (
          <>
            <UnifiedMediaFrame
              src={uploadedPreview}
              alt={uploadedName ?? "风格参考图"}
              title={uploadedName ?? "风格参考图"}
              className="absolute inset-0 rounded-none border-0"
              interactive={false}
              showActions={false}
            />
            <span className="absolute inset-0 bg-gradient-to-t from-black/10 via-transparent to-black/10" />
            <span className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition-all group-hover:bg-black/15 group-hover:opacity-100 group-focus-visible:bg-black/15 group-focus-visible:opacity-100">
              <span className="grid min-h-16 min-w-32 place-items-center rounded-md border border-dashed border-white/60 bg-white/10 px-4 text-xs font-semibold text-white shadow-sm backdrop-blur-md">
                {imageActionLabel}
              </span>
            </span>
            {onClearFile ? (
              <button
                type="button"
                aria-label="移除风格参考图"
                className="absolute top-2 right-2 grid size-7 place-items-center rounded-full bg-black/55 text-white backdrop-blur-sm transition-colors hover:bg-black/70"
                onClick={(event) => {
                  event.preventDefault()
                  event.stopPropagation()
                  onClearFile()
                }}
              >
                <X className="size-3.5" />
              </button>
            ) : null}
          </>
        ) : (
          <>
            <ImagePlus className="size-6" />
            <span className="text-sm font-semibold">{uploadLabel}</span>
            <span className="max-w-[180px] truncate text-xs opacity-75">
              支持 png / jpg / webp
            </span>
          </>
        )}
      </div>
      <div className="block">
        <div className="flex min-h-[260px] flex-col overflow-hidden rounded-xl border border-gray-200/70 bg-white/70 shadow-sm transition-colors focus-within:border-indigo-400 dark:border-white/10 dark:bg-[#24252d] dark:shadow-black/20 dark:focus-within:border-indigo-500">
          <div className="flex min-h-0 flex-1 flex-col">
            <label className="flex min-h-[170px] flex-1 flex-col">
              <span className="px-3 pt-2 text-xs font-medium text-gray-500 dark:text-gray-400">
                全局视觉
              </span>
              <textarea
                aria-label="全局视觉提示词"
                value={stylePrompt}
                onChange={(event) => onStylePromptChange(event.target.value)}
                placeholder="可直接输入整体美术风格描述。"
                className="min-h-0 flex-1 resize-none border-0 bg-transparent px-3 pt-1 pb-3 text-sm leading-6 text-gray-700 outline-none placeholder:text-gray-400 focus:ring-0 dark:text-gray-300 dark:placeholder:text-gray-500"
              />
            </label>
            {advancedOpen ? (
              <div className="grid gap-0 border-t border-gray-200/70 dark:border-white/10">
                {[
                  {
                    label: "角色视觉",
                    value: characterStylePrompt,
                    onChange: onCharacterStylePromptChange,
                    placeholder: "为空时使用全局视觉风格。",
                  },
                  {
                    label: "生物视觉",
                    value: creatureStylePrompt,
                    onChange: onCreatureStylePromptChange,
                    placeholder: "为空时使用全局视觉风格，避免和角色美型逻辑混用。",
                  },
                ].map((field, index) => (
                  <label
                    key={field.label}
                    className={cn(
                      "flex min-h-[96px] flex-col",
                      index > 0 ? "border-t border-gray-200/70 dark:border-white/10" : ""
                    )}
                  >
                    <span className="px-3 pt-2 text-xs font-medium text-gray-500 dark:text-gray-400">
                      {field.label}
                    </span>
                    <textarea
                      aria-label={`${field.label}提示词`}
                      value={field.value}
                      onChange={(event) => field.onChange(event.target.value)}
                      placeholder={field.placeholder}
                      className="min-h-0 flex-1 resize-y border-0 bg-transparent px-3 pt-1 pb-3 text-sm leading-6 text-gray-700 outline-none placeholder:text-gray-400 focus:ring-0 dark:text-gray-300 dark:placeholder:text-gray-500"
                    />
                  </label>
                ))}
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-200/70 bg-white/80 px-3 py-2 dark:border-white/10 dark:bg-[#24252d]">
            <div className="min-w-[180px] flex-1">
              <div className="text-xs font-medium text-gray-500 dark:text-gray-400">
                自定义风格提示词
              </div>
              <div className="mt-0.5 truncate text-[11px] text-gray-400 dark:text-gray-500">
                可分析参考图风格或直接输入风格描述。
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 gap-1.5 border-gray-200/70 bg-white/65 text-[11px] hover:bg-white/90 dark:border-white/10 dark:bg-[#292a33] dark:hover:bg-[#30313b]"
                onClick={() => setAdvancedOpen((open) => !open)}
              >
                <SlidersHorizontal className="size-3.5" />
                {advancedOpen ? "收起高级" : "高级设置"}
              </Button>
              {onFavorite ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1.5 border-gray-200/70 bg-white/65 text-[11px] hover:bg-white/90 dark:border-white/10 dark:bg-[#292a33] dark:hover:bg-[#30313b]"
                  onClick={onFavorite}
                >
                  <Star className="size-3.5" />
                  收藏风格
                </Button>
              ) : null}
              {onAnalyze ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1.5 border-gray-200/70 bg-white/65 text-[11px] !text-gray-700 hover:!border-gray-300 hover:!bg-white/90 hover:!text-gray-900 dark:border-white/10 dark:bg-[#292a33] dark:!text-gray-200 dark:hover:!border-white/15 dark:hover:!bg-[#30313b] dark:hover:!text-gray-50"
                  onClick={onAnalyze}
                  disabled={analyzing || !uploadedName}
                >
                  <Sparkles className="size-3.5" />
                  {analyzing ? "分析中" : "分析风格"}
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
