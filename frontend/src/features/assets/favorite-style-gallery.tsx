import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { RefreshCcw, Search, Sparkles } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { useBackend } from "@/hooks/useBackend"
import { cn } from "@/lib/utils"
import { FavoriteStyleEditDialog } from "@/features/styles/favorite-style-dialogs"
import type {
  FavoriteStyleDialogMode,
  StyleTemplateOption,
} from "@/features/styles/types"
import { ConfirmDialog } from "@/shared/confirm-dialog"
import { isBackendFailure } from "@/shared/backend-result"
import { FavoriteStyleAssetCard } from "./asset-gallery-cards"

type FavoriteStyleOptionsResponse = {
  styleTemplates?: StyleTemplateOption[]
}

export function FavoriteStyleAssetGallery({ title }: { title: string }) {
  const { backendReady, callBackend } = useBackend()
  const [query, setQuery] = useState("")
  const [templates, setTemplates] = useState<StyleTemplateOption[]>([])
  const [loading, setLoading] = useState(false)
  const [dialog, setDialog] = useState<FavoriteStyleDialogMode>(null)
  const [editingTemplate, setEditingTemplate] =
    useState<StyleTemplateOption | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<StyleTemplateOption | null>(
    null
  )
  const [deletingTemplateId, setDeletingTemplateId] = useState<string | null>(
    null
  )
  const loadFavorites = useCallback(async () => {
    if (!backendReady) {
      setTemplates([])
      return
    }
    setLoading(true)
    try {
      const result = await callBackend<
        FavoriteStyleOptionsResponse | { success: false; message?: string }
      >("get_project_creation_options")
      if (isBackendFailure(result)) {
        throw new Error(result.message || "加载收藏风格失败")
      }
      setTemplates(
        ((result as FavoriteStyleOptionsResponse).styleTemplates ?? []).filter(
          (template) => template.category === "favorite"
        )
      )
    } catch (error) {
      console.warn("加载收藏风格失败:", error)
      toast.error(error instanceof Error ? error.message : "加载收藏风格失败")
    } finally {
      setLoading(false)
    }
  }, [backendReady, callBackend])

  useEffect(() => {
    void loadFavorites()
  }, [loadFavorites])

  const rows = templates.filter((template) => {
    const keyword = query.trim().toLowerCase()
    if (!keyword) return true
    return [template.name, template.prompt]
      .join(" ")
      .toLowerCase()
      .includes(keyword)
  })

  const handleRequestDelete = (template: StyleTemplateOption) => {
    setDeleteTarget(template)
  }

  const handleConfirmDelete = async () => {
    const template = deleteTarget
    if (!template) return
    if (!backendReady) {
      toast.error("后端尚未就绪")
      return
    }
    setDeletingTemplateId(template.id)
    try {
      const result = await callBackend<
        | { success?: boolean; message?: string }
        | { success: false; message?: string }
      >("delete_favorite_style_template", { templateId: template.id })
      if (isBackendFailure(result)) {
        throw new Error(result.message || "删除收藏风格失败")
      }
      setTemplates((current) =>
        current.filter((item) => item.id !== template.id)
      )
      setDeleteTarget(null)
      toast.success("收藏风格已删除")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除收藏风格失败")
    } finally {
      setDeletingTemplateId(null)
    }
  }

  const openEditDialog = (template: StyleTemplateOption) => {
    setEditingTemplate(template)
    setDialog("edit")
  }

  const handleSaved = (template: StyleTemplateOption) => {
    setTemplates((current) =>
      current.map((item) => (item.id === template.id ? template : item))
    )
    setDialog(null)
    setEditingTemplate(null)
  }

  return (
    <div className="min-w-0 flex-1 overflow-hidden">
      <div className="sticky top-0 z-10 flex flex-wrap items-center gap-3 border-b border-gray-200/70 bg-white/70 px-5 py-3 shadow-sm backdrop-blur-xl dark:border-white/10 dark:bg-[#202025]/80">
        <span className="h-4 w-1 rounded-full bg-gradient-to-b from-indigo-500 to-emerald-400" />
        <h2 className="text-[16px] font-semibold text-gray-950 dark:text-gray-50">
          {title}
        </h2>
        <Badge variant="outline" className="rounded-full text-[11px]">
          {String(rows.length).padStart(2, "0")}
        </Badge>
        <div className="flex-1" />
        <div className="relative max-w-[320px] min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-gray-400" />
          <Input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索收藏风格"
            className="h-9 rounded-sm bg-white/65 pl-9"
          />
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-9 gap-1.5 bg-white/55 text-xs dark:bg-white/5"
          onClick={() => void loadFavorites()}
          disabled={loading}
        >
          <RefreshCcw className={cn("size-3.5", loading && "animate-spin")} />
          刷新
        </Button>
      </div>
      <ScrollArea className="h-full">
        <div className="px-5 py-5">
          {rows.length === 0 ? (
            <div className="flex min-h-[280px] w-full flex-col items-center justify-center rounded-xl border border-dashed border-gray-300/80 bg-white/45 p-8 text-center dark:border-white/15 dark:bg-white/[0.035]">
              <Sparkles className="size-7 text-indigo-600 dark:text-indigo-300" />
              <span className="mt-3 text-sm font-semibold text-gray-950 dark:text-gray-50">
                {loading
                  ? "正在加载收藏风格"
                  : "还没有收藏风格，可在项目设置中上传风格图片和提示词后收藏。"}
              </span>
            </div>
          ) : (
            <div className="grid [grid-template-columns:repeat(auto-fill,320px)] justify-start gap-4">
              {rows.map((template) => (
                <FavoriteStyleAssetCard
                  key={template.id}
                  template={template}
                  onEdit={() => openEditDialog(template)}
                  onDelete={() => handleRequestDelete(template)}
                />
              ))}
            </div>
          )}
        </div>
      </ScrollArea>
      {dialog === "edit" && editingTemplate ? (
        <FavoriteStyleEditDialog
          template={editingTemplate}
          existingTemplates={templates}
          onClose={() => {
            setDialog(null)
            setEditingTemplate(null)
          }}
          onSaved={handleSaved}
        />
      ) : null}
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="删除收藏风格"
        description={
          deleteTarget
            ? `确认删除「${deleteTarget.name}」？删除后会从全局资产移除该收藏风格。`
            : undefined
        }
        confirmLabel="删除"
        loadingLabel="删除中"
        loading={Boolean(deletingTemplateId)}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
