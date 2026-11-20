import { useEffect, useMemo, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { Combine, Save, Scissors, Undo2, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { type StoryboardShotGroup } from "@/backend"
import type { DirectorSaveRequest } from "./storyboard-plan-saving"
import { useStoryboardEditorDraft } from "./use-storyboard-editor-draft"
import { errMsg } from "@/shared/backend-result"
import { ConfirmDialog } from "@/shared/confirm-dialog"
import { DirectorPlanStructuredEditor, type DirectorPlanShotDraft, type DirectorPlanSpeakerRosterDraft } from "./director-plan-editor"
import {
  directorPlanShotDraftsForNode,
  directorPlanSoundSourceOptionsForNode,
  directorPlanSpeakerRosterDraftForNode,
  directorPlanShotsForSave,
  directorRuleValueForNode,
  normalizeDirectorPlanShotDraftsForSave,
  normalizeDirectorPlanSpeakerRosterForSave,
  workflowDirectorRuleOptions,
} from "./workflow-prompt-node-model"
import { workflowCardHeaderLocator, type StoryboardNode } from "./workflow-canvas-model"
import { WorkflowCompactParameterMenu } from "./workflow-inline-controls"

function newGroupId() {
  return `group_${globalThis.crypto?.randomUUID?.().replace(/-/g, "") ?? Math.random().toString(36).slice(2)}`
}

function groupsForDirector(node: StoryboardNode): StoryboardShotGroup[] {
  const shots = node.data.directorPlanShots ?? []
  const saved = node.data.storyboardAllocation?.groups ?? []
  if (saved.length && saved.flatMap((group) => group.shotNos).every((number, index) => number === index + 1)
    && saved.reduce((count, group) => count + group.shotNos.length, 0) === shots.length) {
    return saved.map((group) => ({ id: group.id, shotNos: [...group.shotNos],
      ...(group.reason ? { reason: group.reason } : {}) }))
  }
  return shots.map((_, index) => ({ id: `group_${String(index + 1).padStart(3, "0")}`, shotNos: [index + 1] }))
}

function groupsAfterShotEdit(groups: StoryboardShotGroup[], previous: DirectorPlanShotDraft[], next: DirectorPlanShotDraft[]) {
  const nextBySource = new Map(next.flatMap((shot, index) => shot.sourceShotNo ? [[shot.sourceShotNo, index + 1] as const] : []))
  const assigned = new Set<number>()
  const updated = groups.flatMap((group) => {
    const members = group.shotNos.flatMap((number) => {
      const source = previous[number - 1]?.sourceShotNo
      const target = source ? nextBySource.get(source) : undefined
      return target ? [target] : []
    })
    const segments: number[][] = []
    for (const number of members) {
      const last = segments[segments.length - 1]
      if (!last || last[last.length - 1] !== number - 1) segments.push([number])
      else last.push(number)
      assigned.add(number)
    }
    return segments.map((shotNos) => ({ ...group,
      id: segments.length === 1 && members.length === group.shotNos.length ? group.id : newGroupId(), shotNos }))
  })
  next.forEach((_, index) => { if (!assigned.has(index + 1)) updated.push({ id: newGroupId(), shotNos: [index + 1] }) })
  return updated.sort((left, right) => left.shotNos[0] - right.shotNos[0])
}

export function DirectorWorkspaceDialog({ director, directorRuleOptions, projectId, episodeId, assetLinks, onSave, onDiscardFailed, onClose }: {
  director: StoryboardNode
  directorRuleOptions: NonNullable<StoryboardNode["data"]["directorRuleOptions"]>
  projectId: string
  episodeId: string
  assetLinks?: ReactNode
  onSave: (request: DirectorSaveRequest) => void
  onDiscardFailed?: (nodeId: string) => StoryboardNode["data"] | undefined
  onClose: () => void
}) {
  const data = director.data
  const persistedShotsKey = JSON.stringify(data.directorPlanShots ?? [])
  const persistedRosterKey = JSON.stringify(data.speakerRoster ?? [])
  const persistedGroupsKey = JSON.stringify(data.storyboardAllocation?.groups ?? [])
  const persistedRuleId = directorRuleValueForNode(data)
  const persistedRhythm = data.rhythmMultiplier == null ? "" : String(data.rhythmMultiplier)
  const savedShotDrafts = useMemo(() => directorPlanShotDraftsForNode(data), [persistedShotsKey])
  const savedRosterDraft = useMemo(() => directorPlanSpeakerRosterDraftForNode(data), [persistedRosterKey])
  const savedGroups = useMemo(() => groupsForDirector(director), [persistedGroupsKey, persistedShotsKey])
  const [shots, setShots] = useStoryboardEditorDraft<DirectorPlanShotDraft[]>(director.id, savedShotDrafts)
  const [speakerRoster, setSpeakerRoster] = useStoryboardEditorDraft<DirectorPlanSpeakerRosterDraft>(director.id, savedRosterDraft)
  const [pendingPlanEdit, setPendingPlanEdit] = useState(false)
  const [ruleId, setRuleId] = useStoryboardEditorDraft(director.id, persistedRuleId)
  const [rhythm, setRhythm] = useStoryboardEditorDraft(director.id, persistedRhythm)
  const [groups, setGroups] = useStoryboardEditorDraft<StoryboardShotGroup[]>(director.id, savedGroups)
  const [allocationNeedsSave, setAllocationNeedsSave] = useState(() => Boolean(
    data.directorPlanShots?.length && (!data.storyboardAllocation?.groups?.length || !data.storyboardAllocation?.directorPlanHash),
  ))
  const [selectedGroupIds, setSelectedGroupIds] = useState<string[]>([])
  const [confirmAllocation, setConfirmAllocation] = useState(false)
  useEffect(() => {
    setAllocationNeedsSave(Boolean(
      data.directorPlanShots?.length && (!data.storyboardAllocation?.groups?.length || !data.storyboardAllocation?.directorPlanHash),
    ))
  }, [director.id, persistedGroupsKey, persistedShotsKey, data.storyboardAllocation?.directorPlanHash])

  const ruleOptions = workflowDirectorRuleOptions({ ...data, directorRuleOptions })
  const planContentDirty = JSON.stringify(normalizeDirectorPlanShotDraftsForSave(shots)) !== JSON.stringify(normalizeDirectorPlanShotDraftsForSave(savedShotDrafts))
    || JSON.stringify(normalizeDirectorPlanSpeakerRosterForSave(speakerRoster)) !== JSON.stringify(normalizeDirectorPlanSpeakerRosterForSave(savedRosterDraft))
  const planDirty = planContentDirty
    || ruleId !== directorRuleValueForNode(data)
    || rhythm !== persistedRhythm
  const groupDirty = JSON.stringify(groups.map((group) => group.shotNos))
    !== JSON.stringify(groupsForDirector(director).map((group) => group.shotNos))
  const hasUnsavedChanges = planDirty || groupDirty || pendingPlanEdit || Boolean(data.storyboardSaveFailed)
  const savedRuleId = ruleId || (
    ruleId === persistedRuleId && data.directorRuleSelectionMode === "auto"
      ? String(data.directorRuleId || "")
      : ""
  )
  const selectedGroups = groups.filter((group) => selectedGroupIds.includes(group.id))
  const groupedShotNumbers = groups.flatMap((group) => group.shotNos)
  const visibleShotGroups = groupedShotNumbers.length === shots.length
    && groupedShotNumbers.every((number, index) => number === index + 1)
    ? groups : undefined
  const updateShots = (nextShots: DirectorPlanShotDraft[]) => {
    if (nextShots.length !== shots.length) {
      setGroups(groupsAfterShotEdit(groups, shots, nextShots))
      setSelectedGroupIds([])
    } else {
      const newBoundaries = nextShots.flatMap((shot, index) => index > 0
        && shot.groupBreakBefore && !shots[index]?.groupBreakBefore ? [index + 1] : [])
      if (newBoundaries.length) {
        setGroups((current) => newBoundaries.reduce((result, shotNo) => {
          const index = result.findIndex((group) => group.shotNos.includes(shotNo))
          const group = result[index]
          if (!group || group.shotNos[0] === shotNo) return result
          const splitAt = group.shotNos.indexOf(shotNo)
          return [...result.slice(0, index),
            { ...group, shotNos: group.shotNos.slice(0, splitAt) },
            { id: newGroupId(), shotNos: group.shotNos.slice(splitAt) },
            ...result.slice(index + 1)]
        }, current))
        setSelectedGroupIds([])
      }
    }
    setShots(nextShots)
  }

  const saveSettingsOnly = () => {
    if (!planDirty && !data.storyboardSaveFailed) return
    if (rhythm && (!Number.isFinite(Number(rhythm)) || Number(rhythm) <= 0)) return
    try {
      onSave({ director, patch: {
          directorRuleId: savedRuleId,
          directorRuleSelectionMode: ruleId ? "manual" : "auto",
          rhythmMultiplier: rhythm ? Number(rhythm) : null,
        } })
      setPendingPlanEdit(false)
    } catch (error) { toast.error(errMsg(error, "保存分镜脚本失败")) }
  }

  const mergeSelected = () => {
    if (selectedGroups.length < 2) {
      toast.info("请勾选至少两个相邻分组")
      return
    }
    const firstIndex = groups.indexOf(selectedGroups[0])
    const lastIndex = groups.indexOf(selectedGroups[selectedGroups.length - 1])
    if (lastIndex - firstIndex + 1 !== selectedGroups.length) {
      toast.info("请勾选相邻分组，保持镜头顺序")
      return
    }
    if (selectedGroups.slice(1).some((group) => shots[group.shotNos[0] - 1]?.groupBreakBefore)) {
      toast.info("所选分组之间设有必须另起视频段的镜头，请先关闭对应镜头的切分标记")
      return
    }
    setGroups([
      ...groups.slice(0, firstIndex),
      { id: selectedGroups[0].id, shotNos: selectedGroups.flatMap((group) => group.shotNos),
        ...(selectedGroups[0].reason ? { reason: selectedGroups[0].reason } : {}) },
      ...groups.slice(lastIndex + 1),
    ])
    setSelectedGroupIds([])
  }

  const splitGroup = (index: number) => {
    setGroups((current) => {
      const group = current[index]
      if (!group || group.shotNos.length < 2) return current
      return [...current.slice(0, index), ...group.shotNos.map((number, position) => ({
        id: position === 0 ? group.id : newGroupId(), shotNos: [number],
        ...(position === 0 && group.reason ? { reason: group.reason } : {}),
      })), ...current.slice(index + 1)]
    })
    setSelectedGroupIds([])
  }

  const savePlanAndGroups = () => {
    if (rhythm && (!Number.isFinite(Number(rhythm)) || Number(rhythm) <= 0)) return
    try {
      const savedShots = directorPlanShotsForSave(shots, data.directorPlanShots ?? [])
      onSave({ director,
        groups: groupDirty ? groups : groupsForDirector(director),
        patch: {
          ...(planContentDirty || data.storyboardSaveFailed ? {
            directorPlanShots: savedShots,
            speakerRoster: normalizeDirectorPlanSpeakerRosterForSave(speakerRoster),
          } : {}),
          directorRuleId: savedRuleId,
          directorRuleSelectionMode: ruleId ? "manual" : "auto",
          rhythmMultiplier: rhythm ? Number(rhythm) : null,
        },
        invalidateGenerated: groupDirty || allocationNeedsSave,
        ...(planContentDirty || data.storyboardSaveFailed ? { sourceShotNos: shots.map((shot) => shot.sourceShotNo ?? null) } : {}),
      })
      setShots(directorPlanShotDraftsForNode({ ...data, directorPlanShots: savedShots }))
      setAllocationNeedsSave(false)
      setConfirmAllocation(false)
      setPendingPlanEdit(false)
    } catch (error) { toast.error(errMsg(error, "保存分镜脚本失败")) }
  }

  const saveChanges = () => {
    if (groupDirty || allocationNeedsSave) { setConfirmAllocation(true); return }
    if (planContentDirty || (data.storyboardSaveFailed && data.storyboardFailedSaveKind !== "settings")) { savePlanAndGroups(); return }
    if (data.storyboardSaveFailed) { saveSettingsOnly(); return }
    if (planDirty) saveSettingsOnly()
  }

  const discard = () => {
    const saved = (data.storyboardSaveFailed ? onDiscardFailed?.(director.id) : undefined) ?? data
    setShots(directorPlanShotDraftsForNode(saved))
    setSpeakerRoster(directorPlanSpeakerRosterDraftForNode(saved))
    setPendingPlanEdit(false)
    setRuleId(directorRuleValueForNode(saved))
    setRhythm(saved.rhythmMultiplier == null ? "" : String(saved.rhythmMultiplier))
    setGroups(groupsForDirector({ ...director, data: saved }))
    setConfirmAllocation(false)
    setSelectedGroupIds([])
  }

  const close = () => {
    if (hasUnsavedChanges) { toast.info("请先保存或撤销当前修改"); return }
    onClose()
  }

  const canvasSurface = document.querySelector<HTMLElement>("[data-workflow-canvas-surface]")
  if (!canvasSurface) return null

  return createPortal(<><div
    className="nodrag nopan nowheel absolute inset-0 z-[300] flex flex-col bg-slate-100 text-slate-900 dark:bg-[#111113] dark:text-slate-100"
    role="dialog"
    aria-modal="true"
    aria-label="分镜脚本"
    onPointerDown={(event) => event.stopPropagation()}
    onClick={(event) => event.stopPropagation()}
    onWheel={(event) => {
      event.stopPropagation()
      event.nativeEvent.stopImmediatePropagation?.()
    }}
    onContextMenu={(event) => {
      event.preventDefault()
      event.stopPropagation()
      onClose()
    }}
  >
    <header className="flex shrink-0 items-center justify-between border-b bg-white px-5 py-3 dark:border-white/10 dark:bg-[#18181b]">
      <div><h2 className="text-base font-semibold">分镜脚本 · {workflowCardHeaderLocator(data)}</h2><p className="text-xs text-slate-500">编辑镜头、导演规则与镜头分组。</p></div>
      <button type="button" aria-label="关闭分镜脚本" onClick={close} className="rounded-md p-2 hover:bg-slate-100 dark:hover:bg-white/10"><X className="size-4" /></button>
    </header>
    <div className="flex min-h-0 flex-1 overflow-hidden p-3">
      <section className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-lg bg-white dark:bg-[#1c1c20]">
        <div className="min-h-0 flex-1 overflow-hidden px-4 py-3">
          <DirectorPlanStructuredEditor shots={shots} speakerRoster={speakerRoster} onChange={updateShots} onSpeakerRosterChange={setSpeakerRoster} onPendingChange={setPendingPlanEdit} soundSourceOptions={directorPlanSoundSourceOptionsForNode(data)} selectedShotGroupIds={selectedGroupIds} onToggleShotGroup={(id) => setSelectedGroupIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])} shotGroups={visibleShotGroups} maximized flatRoot projectId={projectId} episodeId={episodeId} nodeId={director.id} />
        </div>
        {assetLinks ? <div className="shrink-0 px-4 pb-2">{assetLinks}</div> : null}
        <div className="flex flex-wrap items-center gap-2 border-t px-4 py-3 text-xs dark:border-white/10">
          <WorkflowCompactParameterMenu
            label="导演规则"
            value={ruleId}
            options={ruleOptions.map((rule) => rule.value)}
            emptyLabel="自动选择"
            allowUnset
            unsetLabel="自动选择"
            formatLabel={(value) => ruleOptions.find((rule) => rule.value === value)?.label || value}
            formatDescription={(value) => ruleOptions.find((rule) => rule.value === value)?.description || ""}
            onChange={setRuleId}
          />
          <WorkflowCompactParameterMenu
            label="镜头节奏"
            value={rhythm}
            options={Array.from({ length: 10 }, (_, index) => (1.1 + index / 10).toFixed(1))}
            formatLabel={(value) => `${value} 倍`}
            emptyLabel="跟随项目设置"
            allowUnset
            unsetLabel="跟随项目设置"
            onChange={setRhythm}
          />
          <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
            {hasUnsavedChanges ? <span className="rounded bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700 dark:bg-amber-400/10 dark:text-amber-300">修改未保存</span> : null}
            <button type="button" onClick={mergeSelected} className="inline-flex h-[26px] w-[84px] shrink-0 items-center justify-center gap-1 rounded-md border px-2 py-1 text-xs disabled:opacity-40"><Combine className="size-3.5" />合并镜头</button>
            <button type="button" disabled={!selectedGroups.some((group) => group.shotNos.length > 1)} onClick={() => { const touched = groups.map((group, index) => ({ group, index })).filter(({ group }) => group.shotNos.length > 1 && selectedGroupIds.includes(group.id)).map(({ index }) => index); for (const index of touched.reverse()) splitGroup(index) }} className="inline-flex h-[26px] w-[84px] shrink-0 items-center justify-center gap-1 rounded-md border px-2 py-1 text-xs disabled:opacity-40"><Scissors className="size-3.5" />拆分镜头</button>
            <button type="button" disabled={!hasUnsavedChanges} onClick={discard} className="inline-flex h-[26px] w-[84px] shrink-0 items-center justify-center gap-1 rounded-md border px-2 py-1 text-xs disabled:opacity-40"><Undo2 className="size-3.5" />撤销修改</button>
            <Button type="button" disabled={(!hasUnsavedChanges && !allocationNeedsSave) || (rhythm !== "" && (!Number.isFinite(Number(rhythm)) || Number(rhythm) <= 0))} onClick={() => void saveChanges()} className="h-[26px] w-[84px] gap-1 rounded-md px-2 py-1 text-xs has-[>svg]:px-2"><Save className="size-3.5" />{hasUnsavedChanges || allocationNeedsSave ? "保存修改" : "已保存"}</Button>
          </div>
        </div>
      </section>
    </div>
  </div><ConfirmDialog
    open={confirmAllocation}
    title="保存镜头分组"
    description="仅更新调整过的分组。原分组的图片和视频将不再对应新分组，未调整分组的已有结果会保留。保存不会自动生成图片或视频。"
    confirmLabel="保存分组"
    loadingLabel="保存中…"
    loading={false}
    onConfirm={savePlanAndGroups}
    onCancel={() => setConfirmAllocation(false)}
    overlayClassName="!z-[390]"
    contentClassName="!z-[400]"
  /></>, canvasSurface)
}
