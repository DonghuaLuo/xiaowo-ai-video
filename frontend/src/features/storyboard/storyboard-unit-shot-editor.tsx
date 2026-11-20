import { useMemo, useState, type ComponentType } from "react"
import { useStoryboardEditorDraft } from "./use-storyboard-editor-draft"
import { toast } from "sonner"
import { errMsg } from "@/shared/backend-result"
import { DirectorPlanStructuredEditor, type DirectorPlanShotDraft, type DirectorPlanSpeakerRosterDraft } from "./director-plan-editor"
import { InlineGenerationControls } from "./workflow-inline-generation-controls"
import {
  directorPlanShotDraftsForNode,
  directorPlanShotsForSave,
  directorPlanSoundSourceOptionsForNode,
  directorPlanSpeakerRosterDraftForNode,
  normalizeDirectorPlanShotDraftsForSave,
  normalizeDirectorPlanSpeakerRosterForSave,
} from "./workflow-prompt-node-model"
import type { WorkflowNodeData } from "./workflow-canvas-model"

export function StoryboardUnitShotEditor({
  id, data, maximized, maxHeight, AssetLinks,
}: {
  id: string
  data: WorkflowNodeData
  maximized: boolean
  maxHeight?: number
  AssetLinks: ComponentType<{ id: string; data: WorkflowNodeData; compact?: boolean }>
}) {
  const savedKey = JSON.stringify([data.directorPlanShots ?? [], data.speakerRoster ?? []])
  const savedShots = useMemo(() => directorPlanShotDraftsForNode(data), [savedKey])
  const savedRoster = useMemo(() => directorPlanSpeakerRosterDraftForNode(data), [savedKey])
  const [shots, setShots] = useStoryboardEditorDraft<DirectorPlanShotDraft[]>(id, savedShots)
  const [speakerRoster, setSpeakerRoster] = useStoryboardEditorDraft<DirectorPlanSpeakerRosterDraft>(id, savedRoster)
  const [pendingEdit, setPendingEdit] = useState(false)

  const dirty = JSON.stringify(normalizeDirectorPlanShotDraftsForSave(shots)) !== JSON.stringify(normalizeDirectorPlanShotDraftsForSave(savedShots))
    || JSON.stringify(normalizeDirectorPlanSpeakerRosterForSave(speakerRoster)) !== JSON.stringify(normalizeDirectorPlanSpeakerRosterForSave(savedRoster))
    || pendingEdit || Boolean(data.storyboardSaveFailed)

  const restore = () => {
    const restored = data.storyboardSaveFailed ? data.onDiscardStoryboardSave?.(id) : undefined
    setShots(restored ? directorPlanShotDraftsForNode(restored) : savedShots)
    setSpeakerRoster(restored ? directorPlanSpeakerRosterDraftForNode(restored) : savedRoster)
    setPendingEdit(false)
  }
  const save = () => {
    if (!data.onSaveStoryboardUnitShots || !shots.length) return
    try {
      const savedShots = directorPlanShotsForSave(shots, data.directorPlanShots ?? [])
      data.onSaveStoryboardUnitShots(
        id,
        savedShots,
        normalizeDirectorPlanSpeakerRosterForSave(speakerRoster),
        data.directorPlanShots ?? [],
        data.speakerRoster ?? [],
        shots.map((shot) => shot.sourceShotNo ?? null),
      )
      setShots(directorPlanShotDraftsForNode({ ...data, directorPlanShots: savedShots }))
      setPendingEdit(false)
    } catch (error) {
      toast.error(errMsg(error, "保存分镜单元镜头失败"))
    }
  }

  return (
    <div
      className={maximized ? "flex h-full min-h-0 flex-col overflow-hidden" : "flex min-h-0 flex-col"}
      style={!maximized && typeof maxHeight === "number" ? { maxHeight: Math.max(180, maxHeight - 24) } : undefined}
    >
      {!maximized && shots.length ? <div className="flex min-h-6 shrink-0 items-center text-xs text-slate-500 dark:text-slate-400">共 {shots.length} 个镜头</div> : null}
      <div className={maximized ? "min-h-0 flex-1 overflow-y-auto pr-1" : "min-h-0 flex-1 space-y-3 overflow-y-auto"}>
        {shots.length ? (
          <DirectorPlanStructuredEditor
            shots={shots}
            speakerRoster={speakerRoster}
            onChange={setShots}
            onSpeakerRosterChange={setSpeakerRoster}
            onPendingChange={setPendingEdit}
            soundSourceOptions={directorPlanSoundSourceOptionsForNode(data)}
            maxHeight={maxHeight}
            maximized={maximized}
            flatRoot
            flatRootTitle=""
            scrollInParent={!maximized}
            shotNumberOffset={(data.shotNos?.[0] ?? 1) - 1}
            projectId={data.projectId}
            episodeId={data.episodeId}
            nodeId={id}
          />
        ) : <p className="text-sm text-gray-500">生成分镜脚本后显示对应镜头。</p>}
      </div>
      {!maximized ? <div className="mt-3 shrink-0 empty:hidden">
        <AssetLinks id={id} data={data} compact />
      </div> : null}
      <div className={maximized ? "absolute inset-x-0 bottom-0 z-20 border-t border-gray-200/80 bg-white dark:border-white/[0.07] dark:bg-[#18181b]" : "shrink-0"}>
        <div className={maximized ? "px-5 py-3" : "contents"}>
          <InlineGenerationControls
            id={id}
            data={data}
            maximized={maximized}
            extraEditDirty={dirty}
            onCancelExtraEdit={restore}
            onSaveExtraEdit={save}
          />
        </div>
      </div>
    </div>
  )
}
