import { PencilLine, Plus, Star, Trash2 } from "lucide-react"

import { type PhaseVisualStyle } from "@/features/project-settings/model"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import { FavoriteStyleConfirmDialog } from "@/features/styles/favorite-style-dialogs"

import { projectStyleModeTabs } from "@/features/styles/catalog"

import {
  CustomStyleEditor,
  GeneralStyleTemplatePanel,
  StyleCategoryTabs,
  StyleModeTabs,
  StylePromptPreview,
  StyleTemplateGrid,
} from "@/features/settings/style-editors"

import { cn } from "@/lib/utils"

import { SectionPanel } from "@/shared/page-shell"

import type { ProjectStyleEditor } from "./use-project-style-editor"
function PhaseVisualSettings({
  items,
  activeId,
  editorOpen,
  editingId,
  draftName,
  draftPrompt,
  onActiveChange,
  onAdd,
  onEdit,
  onDelete,
  onDraftNameChange,
  onDraftPromptChange,
  onSave,
  onCancel,
}: {
  items: PhaseVisualStyle[]
  activeId: string | null
  editorOpen: boolean
  editingId: string | null
  draftName: string
  draftPrompt: string
  onActiveChange: (id: string | null) => void
  onAdd: () => void
  onEdit: (item: PhaseVisualStyle) => void
  onDelete: (id: string) => void
  onDraftNameChange: (value: string) => void
  onDraftPromptChange: (value: string) => void
  onSave: () => void
  onCancel: () => void
}) {
  const selectedItem = items.find((item) => item.id === activeId)
  return (
    <div className="rounded-xl border border-gray-200/70 bg-white/70 p-3 dark:border-white/10 dark:bg-white/[0.035]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold text-gray-700 dark:text-gray-200">
            阶段视觉语境
          </div>
          <div className="mt-1 text-[11px] leading-relaxed text-gray-500 dark:text-gray-400">
            当前选中项会叠加到图片生成提示词；不影响视频生成。
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-7 gap-1.5 border-gray-200/70 bg-white/65 text-[11px] hover:bg-white/90 dark:border-white/10 dark:bg-[#292a33] dark:hover:bg-[#30313b]"
          onClick={onAdd}
        >
          <Plus className="size-3.5" />
          添加阶段
        </Button>
      </div>

      <div className="mt-3 grid gap-2">
        <button
          type="button"
          aria-pressed={!activeId}
          className={cn(
            "min-h-10 rounded-lg border px-3 py-2 text-left text-xs transition-colors",
            !activeId
              ? "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-300"
              : "border-gray-200/70 bg-white/65 text-gray-500 hover:border-indigo-200 hover:text-gray-950 dark:border-white/10 dark:bg-white/[0.035] dark:text-gray-400 dark:hover:text-gray-50"
          )}
          onClick={() => onActiveChange(null)}
        >
          <span className="font-semibold">不使用阶段视觉语境</span>
        </button>
        {items.map((item) => {
          const selected = item.id === activeId
          return (
            <div
              key={item.id}
              className={cn(
                "grid gap-2 rounded-lg border p-2 transition-colors sm:grid-cols-[minmax(0,1fr)_auto]",
                selected
                  ? "border-indigo-200 bg-indigo-50/75 dark:border-indigo-900/60 dark:bg-indigo-950/25"
                  : "border-gray-200/70 bg-white/65 dark:border-white/10 dark:bg-white/[0.035]"
              )}
            >
              <button
                type="button"
                aria-pressed={selected}
                className="min-w-0 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-white/70 dark:hover:bg-white/[0.045]"
                onClick={() => onActiveChange(item.id)}
              >
                <span
                  className={cn(
                    "block text-xs font-semibold",
                    selected
                      ? "text-indigo-700 dark:text-indigo-300"
                      : "text-gray-800 dark:text-gray-100"
                  )}
                >
                  {item.name}
                </span>
                <span className="mt-1 line-clamp-2 block text-[11px] leading-relaxed text-gray-500 dark:text-gray-400">
                  {item.prompt}
                </span>
              </button>
              <div className="flex items-center justify-end gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`编辑${item.name}`}
                  title="编辑阶段视觉语境"
                  className="size-7 text-gray-500 hover:text-indigo-600 dark:text-gray-400 dark:hover:text-indigo-300"
                  onClick={() => onEdit(item)}
                >
                  <PencilLine className="size-3.5" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`删除${item.name}`}
                  title="删除阶段视觉语境"
                  className="size-7 text-gray-500 hover:text-rose-600 dark:text-gray-400 dark:hover:text-rose-300"
                  onClick={() => onDelete(item.id)}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            </div>
          )
        })}
        {!items.length ? (
          <div className="rounded-lg border border-dashed border-gray-200/80 bg-white/45 px-3 py-4 text-xs text-gray-500 dark:border-white/10 dark:bg-white/[0.025] dark:text-gray-400">
            暂无阶段视觉语境。
          </div>
        ) : null}
      </div>

      {editorOpen ? (
        <div className="mt-3 rounded-lg border border-indigo-100 bg-indigo-50/40 p-3 dark:border-indigo-900/40 dark:bg-indigo-950/15">
          <div className="grid gap-2 md:grid-cols-[180px_minmax(0,1fr)]">
            <Input
              value={draftName}
              onChange={(event) => onDraftNameChange(event.target.value)}
              placeholder="阶段名称"
              className="h-9 bg-white/80 text-sm dark:bg-white/[0.04]"
            />
            <textarea
              value={draftPrompt}
              onChange={(event) => onDraftPromptChange(event.target.value)}
              placeholder="如：边境战场破碎硝烟阶段语境"
              className="min-h-24 resize-y rounded-md border border-gray-200/70 bg-white/80 px-3 py-2 text-sm leading-6 text-gray-700 outline-none transition-colors placeholder:text-gray-400 focus:border-indigo-400 focus:ring-0 dark:border-white/10 dark:bg-white/[0.04] dark:text-gray-300 dark:placeholder:text-gray-500 dark:focus:border-indigo-500"
            />
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8"
              onClick={onCancel}
            >
              取消
            </Button>
            <Button type="button" size="sm" className="h-8" onClick={onSave}>
              {editingId ? "保存修改" : "保存阶段"}
            </Button>
          </div>
        </div>
      ) : selectedItem ? (
        <div className="mt-3 rounded-lg border border-gray-200/70 bg-white/55 px-3 py-2 text-[11px] leading-relaxed text-gray-500 dark:border-white/10 dark:bg-white/[0.025] dark:text-gray-400">
          当前阶段：{selectedItem.name}
        </div>
      ) : null}
    </div>
  )
}
export function ProjectStyleSettings({
  style,
}: {
  style: Pick<
    ProjectStyleEditor,
    | "styleMode"
    | "styleBrowseMode"
    | "styleBrowseCategory"
    | "styleTemplate"
    | "styleVisualTypeTag"
    | "customProjectStylePrompt"
    | "customProjectCharacterStylePrompt"
    | "customProjectCreatureStylePrompt"
    | "phaseVisuals"
    | "activePhaseVisualId"
    | "phaseVisualEditorOpen"
    | "editingPhaseVisualId"
    | "phaseVisualDraftName"
    | "phaseVisualDraftPrompt"
    | "customProjectStyleFile"
    | "customProjectStylePreview"
    | "favoriteStyleConfirmDraft"
    | "analyzingProjectStyle"
    | "setStyleMode"
    | "setStyleCategory"
    | "setStyleBrowseMode"
    | "setStyleTemplate"
    | "setStyleVisualTypeTag"
    | "setActivePhaseVisualId"
    | "setPhaseVisualDraftName"
    | "setPhaseVisualDraftPrompt"
    | "setCustomProjectStyleFile"
    | "setFavoriteStyleConfirmDraft"
    | "presetStyleTemplates"
    | "favoriteStyleTemplates"
    | "generalProjectStyleTemplate"
    | "visibleProjectStylePrompt"
    | "projectPresetStyleCategories"
    | "changeProjectStyleCategory"
    | "changeProjectStyleMode"
    | "applyProjectPresetStyle"
    | "applyProjectFavoriteStyle"
    | "applyProjectCustomStylePrompt"
    | "applyProjectCustomCharacterStylePrompt"
    | "applyProjectCustomCreatureStylePrompt"
    | "openAddPhaseVisual"
    | "openEditPhaseVisual"
    | "resetPhaseVisualEditor"
    | "savePhaseVisualDraft"
    | "deletePhaseVisual"
    | "copyProjectStyleToCustom"
    | "customProjectStyleUploadedName"
    | "handleProjectStyleFileSelected"
    | "handleAnalyzeProjectStyle"
    | "handleFavoriteProjectStyle"
    | "handleFavoriteStyleSaved"
  >
}) {
  const {
    styleMode,
    styleBrowseMode,
    styleBrowseCategory,
    styleTemplate,
    styleVisualTypeTag,
    customProjectStylePrompt,
    customProjectCharacterStylePrompt,
    customProjectCreatureStylePrompt,
    phaseVisuals,
    activePhaseVisualId,
    phaseVisualEditorOpen,
    editingPhaseVisualId,
    phaseVisualDraftName,
    phaseVisualDraftPrompt,
    customProjectStyleFile,
    customProjectStylePreview,
    favoriteStyleConfirmDraft,
    analyzingProjectStyle,
    setStyleMode,
    setStyleCategory,
    setStyleBrowseMode,
    setStyleTemplate,
    setStyleVisualTypeTag,
    setActivePhaseVisualId,
    setPhaseVisualDraftName,
    setPhaseVisualDraftPrompt,
    setCustomProjectStyleFile,
    setFavoriteStyleConfirmDraft,
    presetStyleTemplates,
    favoriteStyleTemplates,
    generalProjectStyleTemplate,
    visibleProjectStylePrompt,
    projectPresetStyleCategories,
    changeProjectStyleCategory,
    changeProjectStyleMode,
    applyProjectPresetStyle,
    applyProjectFavoriteStyle,
    applyProjectCustomStylePrompt,
    applyProjectCustomCharacterStylePrompt,
    applyProjectCustomCreatureStylePrompt,
    openAddPhaseVisual,
    openEditPhaseVisual,
    resetPhaseVisualEditor,
    savePhaseVisualDraft,
    deletePhaseVisual,
    copyProjectStyleToCustom,
    customProjectStyleUploadedName,
    handleProjectStyleFileSelected,
    handleAnalyzeProjectStyle,
    handleFavoriteProjectStyle,
    handleFavoriteStyleSaved,
  } = style
  return (
    <>
      <SectionPanel eyebrow="Visual Style" title="视觉风格">
        <div className="space-y-4">
          <StyleModeTabs
            value={styleBrowseMode}
            onChange={changeProjectStyleMode}
            modes={projectStyleModeTabs}
          />
          {styleBrowseMode === "template" ? (
            <div className="space-y-3">
              <StyleCategoryTabs
                value={styleBrowseCategory}
                onChange={changeProjectStyleCategory}
                categories={projectPresetStyleCategories}
                templates={presetStyleTemplates}
              />
              {styleBrowseCategory === "general" ? (
                <GeneralStyleTemplatePanel
                  template={generalProjectStyleTemplate}
                  value={styleMode === "template" ? styleTemplate : ""}
                  onChange={applyProjectPresetStyle}
                  visualTypeTag={styleVisualTypeTag}
                  onVisualTypeTagChange={(next) => {
                    setStyleBrowseMode("template")
                    setStyleMode("template")
                    setStyleCategory("general")
                    if (generalProjectStyleTemplate) {
                      setStyleTemplate(generalProjectStyleTemplate.id)
                    }
                    setStyleVisualTypeTag(next)
                  }}
                  compact
                />
              ) : (
                <StyleTemplateGrid
                  category={styleBrowseCategory}
                  value={styleMode === "template" ? styleTemplate : ""}
                  onChange={applyProjectPresetStyle}
                  templates={presetStyleTemplates}
                  compact
                  bounded
                  showFavoriteDelete={false}
                />
              )}
            </div>
          ) : styleBrowseMode === "favorite" ? (
            favoriteStyleTemplates.length > 0 ? (
              <StyleTemplateGrid
                category="favorite"
                value={styleMode === "favorite" ? styleTemplate : ""}
                onChange={applyProjectFavoriteStyle}
                templates={favoriteStyleTemplates}
                compact
                bounded
                showFavoriteDelete={false}
              />
            ) : (
              <div className="flex min-h-[260px] flex-col items-center justify-center rounded-xl border border-dashed border-gray-300/80 bg-white/45 p-8 text-center dark:border-white/15 dark:bg-white/[0.035]">
                <Star className="size-7 text-indigo-600 dark:text-indigo-300" />
                <div className="mt-3 text-sm font-semibold text-gray-950 dark:text-gray-50">
                  暂无收藏风格
                </div>
                <p className="mt-1 max-w-[360px] text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                  在自定义风格中输入描述或分析参考图后，可收藏为常用风格。
                </p>
              </div>
            )
          ) : (
            <CustomStyleEditor
              stylePrompt={customProjectStylePrompt}
              characterStylePrompt={customProjectCharacterStylePrompt}
              creatureStylePrompt={customProjectCreatureStylePrompt}
              uploadedName={customProjectStyleUploadedName}
              uploadedPreview={customProjectStylePreview}
              onStylePromptChange={applyProjectCustomStylePrompt}
              onCharacterStylePromptChange={applyProjectCustomCharacterStylePrompt}
              onCreatureStylePromptChange={applyProjectCustomCreatureStylePrompt}
              onFileSelected={(file) => void handleProjectStyleFileSelected(file)}
              onClearFile={
                customProjectStyleFile ? () => setCustomProjectStyleFile(null) : undefined
              }
              onFavorite={() => void handleFavoriteProjectStyle()}
              onAnalyze={() => void handleAnalyzeProjectStyle()}
              analyzing={analyzingProjectStyle}
              uploadLabel="上传自定义风格图"
            />
          )}
          {styleBrowseMode !== "custom" ? (
            <StylePromptPreview
              prompt={visibleProjectStylePrompt}
              onEdit={copyProjectStyleToCustom}
            />
          ) : null}
          <PhaseVisualSettings
            items={phaseVisuals}
            activeId={activePhaseVisualId}
            editorOpen={phaseVisualEditorOpen}
            editingId={editingPhaseVisualId}
            draftName={phaseVisualDraftName}
            draftPrompt={phaseVisualDraftPrompt}
            onActiveChange={setActivePhaseVisualId}
            onAdd={openAddPhaseVisual}
            onEdit={openEditPhaseVisual}
            onDelete={deletePhaseVisual}
            onDraftNameChange={setPhaseVisualDraftName}
            onDraftPromptChange={setPhaseVisualDraftPrompt}
            onSave={savePhaseVisualDraft}
            onCancel={resetPhaseVisualEditor}
          />
        </div>
      </SectionPanel>
      {favoriteStyleConfirmDraft ? (
        <FavoriteStyleConfirmDialog
          draft={favoriteStyleConfirmDraft}
          onClose={() => setFavoriteStyleConfirmDraft(null)}
          onSaved={(template) => void handleFavoriteStyleSaved(template)}
        />
      ) : null}
    </>
  )
}
