import { applyStoryboardAllocation, saveWorkflowNodeInlineEdit, type BackendCaller, type StoryboardShotGroup } from "@/backend"
import { isDirectorBoardNodeType, isStoryboardCardNodeType, recordValue, type StoryboardNode, type WorkflowNodeData } from "./workflow-canvas-model"
import type { WorkflowCanvasDocument } from "./workflow-canvas-document"

type Rows = Array<Record<string, unknown>>
type PlanPatch = NonNullable<Parameters<typeof applyStoryboardAllocation>[3]["directorPlanPatch"]>
type UnitEdit = Omit<Parameters<typeof applyStoryboardAllocation>[3], "directorPlanPatch"> & {
  directorPlanPatch: PlanPatch & { directorPlanShots: Rows; speakerRoster: Rows }
}
type Snapshot = { shots: Rows; roster: Rows; groups: StoryboardShotGroup[] }
export type DirectorSaveRequest = { director: StoryboardNode; patch: PlanPatch; groups?: StoryboardShotGroup[]; invalidateGenerated?: boolean; sourceShotNos?: Array<number | null> }
const equal = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right)
const groupShape = (groups: StoryboardShotGroup[]) => groups.map(({ id, shotNos }) => ({ id, shotNos }))
const snapshot = (data: Partial<WorkflowNodeData>): Snapshot => ({
  shots: data.directorPlanShots ?? [], roster: data.speakerRoster ?? [], groups: groupShape(data.storyboardAllocation?.groups ?? []),
})
const speakerIds = (shots: Rows) => new Set(shots.flatMap((shot) =>
  (Array.isArray(shot.soundEvents) ? shot.soundEvents : []).flatMap((event) => {
    const row = recordValue(event)
    return row.kind === "voice" ? [String(row.speakerId || "")] : []
  }),
))
const rosterForShots = (shots: Rows, roster: Rows) => {
  const ids = speakerIds(shots)
  return roster.filter((speaker) => ids.has(String(speaker.speakerId)))
}

export function storyboardUnitEdit(currentUnit: StoryboardNode, currentDirector: StoryboardNode,
  editedShots: Rows, speakerRoster: Rows, expectedUnitShots: Rows, expectedSpeakerRoster: Rows,
  sourceShotNos?: Array<number | null>): UnitEdit {
  const originalShots = currentDirector.data.directorPlanShots ?? []
  const groups = currentDirector.data.storyboardAllocation?.groups ?? []
  const group = groups.find((item) => item.id === currentUnit.data.shotGroupId)
  const shotNos = group?.shotNos ?? []
  if (!shotNos.length || !equal(shotNos, currentUnit.data.shotNos ?? [])) throw new Error("镜头分组已变化，请重新打开分镜单元")
  const start = shotNos[0] - 1, end = shotNos[shotNos.length - 1]
  const currentSpeakerRoster = currentDirector.data.speakerRoster ?? []
  if (!equal(originalShots.slice(start, end), expectedUnitShots)
    || !equal(currentUnit.data.directorPlanShots ?? [], expectedUnitShots)
    || !equal(currentUnit.data.speakerRoster ?? [], expectedSpeakerRoster)
    || !equal(rosterForShots(originalShots.slice(start, end), currentSpeakerRoster), expectedSpeakerRoster)) {
    throw new Error("分镜脚本已变化，请重新打开分镜单元")
  }
  if (!editedShots.length) throw new Error("分镜单元至少保留一个镜头")
  const delta = editedShots.length - shotNos.length
  const nextShots = [...originalShots.slice(0, start), ...editedShots, ...originalShots.slice(end)]
    .map((shot, index) => ({ ...shot, shotNo: index + 1 }))
  const nextRoster = new Map(currentSpeakerRoster.map((speaker) => [String(speaker.speakerId), speaker]))
  const editedSpeakerIds = new Set(speakerRoster.map((speaker) => String(speaker.speakerId)))
  const nextSpeakerIds = speakerIds(nextShots)
  for (const speaker of expectedSpeakerRoster) {
    const id = String(speaker.speakerId)
    if (!editedSpeakerIds.has(id) && !nextSpeakerIds.has(id)) nextRoster.delete(id)
  }
  for (const speaker of speakerRoster) nextRoster.set(String(speaker.speakerId), speaker)
  const groupBoundariesChanged = delta !== 0 || editedShots.some((shot, index) =>
    Boolean(shot.groupBreakBefore) !== Boolean(expectedUnitShots[index]?.groupBreakBefore))
  const nextGroups = groupBoundariesChanged ? groups.flatMap((item) => {
    if (item.id !== group?.id) return [{ ...item, shotNos: item.shotNos.map((number) => number > end ? number + delta : number) }]
    const segments: number[][] = []
    editedShots.forEach((shot, index) => {
      if (index === 0 || shot.groupBreakBefore) segments.push([])
      segments[segments.length - 1].push(start + index + 1)
    })
    return segments.map((shotNos, index) => ({
      id: index === 0 ? item.id : `group_${globalThis.crypto?.randomUUID?.().replace(/-/g, "") ?? Math.random().toString(36).slice(2)}`,
      shotNos, ...(index === 0 && item.reason ? { reason: item.reason } : {}),
    }))
  }) : groups
  return {
    directorNodeId: currentDirector.id, directorPlanShots: originalShots,
    expectedSpeakerRoster: currentSpeakerRoster, expectedGroups: groups, groups: nextGroups,
    directorPlanPatch: { directorPlanShots: nextShots, speakerRoster: [...nextRoster.values()] },
    ...(sourceShotNos ? { sourceShotNos: [
      ...originalShots.slice(0, start).map((_, index) => index + 1),
      ...sourceShotNos.map((number) => number == null ? null : shotNos[number - 1] ?? null),
      ...originalShots.slice(end).map((_, index) => end + index + 1),
    ] } : {}),
    invalidateGenerated: groupBoundariesChanged,
  }
}

type SaveIntent = {
  sequence: number
  originId: string
  director: StoryboardNode
  failed: boolean
  baseData?: WorkflowNodeData
  // Draft row -> position in baseData; null identifies an unsaved new shot.
  sourceShotNos?: Array<number | null>
  request: DirectorSaveRequest | {
    unit: StoryboardNode; shots: Rows; roster: Rows; expectedShots: Rows; expectedRoster: Rows; sourceShotNos?: Array<number | null>
  }
}

const settingDefaults: Record<string, unknown> = { directorRuleId: "", directorRuleSelectionMode: "auto", rhythmMultiplier: null }
function changedPlanPatch(patch: PlanPatch, base: WorkflowNodeData): PlanPatch {
  return Object.fromEntries(Object.entries(patch).filter(([key, value]) =>
    !equal(value ?? settingDefaults[key], base[key as keyof WorkflowNodeData] ?? settingDefaults[key])))
}

/** Keep only the draft's field changes when the confirmed record advances. */
function rebaseRecord(before: Record<string, unknown>, draft: Record<string, unknown>, confirmed: Record<string, unknown>) {
  const result = { ...confirmed }
  for (const key of new Set([...Object.keys(before), ...Object.keys(draft)])) {
    if (equal(before[key], draft[key])) continue
    if (key in draft) result[key] = draft[key]
    else delete result[key]
  }
  return result
}

/** Accepted writes outlive the view. Failed drafts remain local to their owner. */
export function createStoryboardPlanSaver({ document, callBackend, projectId, episodeId, readNodes, beforeWrite, applyMutation, onFailure, onWarning }: {
  document: WorkflowCanvasDocument
  callBackend: BackendCaller
  projectId: string
  episodeId: string
  readNodes: (ids: string[]) => Promise<StoryboardNode[]>
  beforeWrite?: () => Promise<void>
  applyMutation: (result: unknown) => void | Promise<void>
  onFailure: (error: unknown) => void
  onWarning: (message: string) => void
}) {
  const scope = document.scope
  let tail = Promise.resolve(), sequence = 0
  const intents = new Map<string, SaveIntent>()
  const aliases = new Map<string, Snapshot>()
  const shotSources = new Map<string, Array<number | null>>()
  const current = () => document.scope === scope && Boolean(scope.key)
  const chainKey = (director: StoryboardNode) => `storyboard:${director.data.workChainId || director.id}`
  const keyFor = (id: string, value: Snapshot) => JSON.stringify([id, value])
  const resolve = (id: string, value: Snapshot) => aliases.get(keyFor(id, value)) ?? value
  const sourcesFor = (id: string, value: Snapshot) => shotSources.get(keyFor(id, value)) ?? value.shots.map((_, index) => index + 1)
  const remapSources = (id: string, before: Snapshot, sources: Array<number | null>) => {
    const prior = sourcesFor(id, before)
    return sources.map((number) => number == null ? null : prior[number - 1] ?? null)
  }
  const remember = (id: string, before: Snapshot, submitted: Snapshot, confirmed: Snapshot, committed = true) => {
    aliases.set(keyFor(id, before), confirmed)
    aliases.set(keyFor(id, submitted), confirmed)
    if (committed) {
      const sources = confirmed.shots.map((_, index) => index + 1)
      shotSources.set(keyFor(id, before), sources)
      shotSources.set(keyFor(id, submitted), sources)
    }
    while (aliases.size > 200) aliases.delete(aliases.keys().next().value!)
    while (shotSources.size > 200) shotSources.delete(shotSources.keys().next().value!)
  }
  const unitView = (plan: Snapshot, groupId: unknown): Snapshot | undefined => {
    const group = plan.groups.find((group) => group.id === groupId)
    if (!group) return
    const shots = group.shotNos.map((number) => plan.shots[number - 1])
    if (shots.some((shot) => !shot)) return
    return { shots, roster: rosterForShots(shots, plan.roster), groups: [] }
  }
  const rememberPlan = (director: StoryboardNode, before: Snapshot, submitted: Snapshot, confirmed: Snapshot, committed = true) => {
    remember(director.id, before, submitted, confirmed, committed)
    for (const unit of document.read().nodes) {
      if (!isStoryboardCardNodeType(unit.data.eyebrow) || unit.data.workChainId !== director.data.workChainId) continue
      const views = [before, submitted, confirmed].map((plan) => unitView(plan, unit.data.shotGroupId))
      if (views.every(Boolean)) remember(unit.id, views[0]!, views[1]!, views[2]!, committed)
    }
  }
  const previewUnitEdit = (director: StoryboardNode, unit: StoryboardNode, request: Extract<SaveIntent["request"], { unit: StoryboardNode }>) => {
    const group = director.data.storyboardAllocation?.groups.find((group) => group.id === unit.data.shotGroupId)
    const view = unitView(snapshot(director.data), unit.data.shotGroupId)
    if (!view || !equal(group?.shotNos, unit.data.shotNos)) return
    const localUnit = { ...unit, data: { ...unit.data, directorPlanShots: view.shots, speakerRoster: view.roster } }
    return storyboardUnitEdit(localUnit, director, request.shots, request.roster, view.shots, view.roster, request.sourceShotNos)
  }
  const rememberDraftSources = (director: StoryboardNode, visible: Snapshot) => {
    if (shotSources.has(keyFor(director.id, visible))) return
    let plan = document.readConfirmedNodes().find((node) => node.id === director.id)
    if (!plan?.data.directorPlanShots) return
    let sources: Array<number | null> = plan.data.directorPlanShots.map((_, index) => index + 1)
    // A read may fail before a unit draft can be materialized. Once the script
    // is hydrated, derive that draft's lineage from its scope, not shot text.
    for (const intent of [...intents.values()].sort((left, right) => left.sequence - right.sequence)) {
      if (!intent.failed || intent.director.id !== director.id || !("unit" in intent.request)) continue
      const edit = previewUnitEdit(plan, intent.request.unit, intent.request)
      if (!edit) return
      if (edit.sourceShotNos) sources = edit.sourceShotNos.map((number) => number == null ? null : sources[number - 1] ?? null)
      plan = { ...plan, data: { ...plan.data, ...edit.directorPlanPatch,
        storyboardAllocation: { schemaVersion: 1, directorPlanHash: "pending",
          groups: edit.groups.map((group, index) => ({ ...group, order: group.order ?? index + 1 })) } } }
    }
    if (equal(snapshot(plan.data), visible)) shotSources.set(keyFor(director.id, visible), sources)
  }
  const settleFailedScript = (director: StoryboardNode, confirmed: WorkflowNodeData, savedShotNos: number[], savedSpeakerIds: Set<string>, confirmedSources?: Array<number | null>) => {
    const failed = intents.get(director.id)
    if (!failed?.failed || "unit" in failed.request) return
    const request = failed.request, base = failed.baseData ?? failed.director.data
    const patch = { ...request.patch }
    const saved = new Set(savedShotNos)
    let groups = request.groups
    const draft = patch.directorPlanShots ?? (groups ? base.directorPlanShots : undefined)
    const sources = failed.sourceShotNos ?? (draft?.length === base.directorPlanShots?.length
      ? draft?.map((_, index) => index + 1) : undefined)
    if (draft && sources && confirmed.directorPlanShots) {
      const currentShots = confirmed.directorPlanShots
      const currentSources = confirmedSources ?? currentShots.map((_, index) => index + 1)
      const positions = new Map(currentSources.flatMap((source, index) => source == null ? [] : [[source, index + 1] as const]))
      const rows: Array<{ shot: Record<string, unknown>; source: number | null; draftNo?: number }> = []
      draft.forEach((shot, index) => {
        const source = sources[index]
        if (source == null) { rows.push({ shot, source: null, draftNo: index + 1 }); return }
        const position = positions.get(source)
        if (!position) return // A later successful unit edit deleted this shot.
        rows.push({ source: position, draftNo: index + 1, shot: saved.has(position) ? currentShots[position - 1]
          : rebaseRecord(base.directorPlanShots?.[source - 1] ?? {}, shot, currentShots[position - 1]) })
      })
      // Successful unit insertions belong to the confirmed plan, even while
      // the script still carries its own unpersisted insertions/deletions.
      currentSources.forEach((source, index) => {
        if (source != null) return
        const next = rows.findIndex((row) => row.source != null && row.source > index + 1)
        const previous = rows.reduce((last, row, position) => row.source != null && row.source < index + 1 ? position : last, -1)
        rows.splice(next >= 0 ? next : previous >= 0 ? previous + 1 : rows.length, 0,
          { shot: currentShots[index], source: index + 1 })
      })
      const draftGroups = groups ?? base.storyboardAllocation?.groups ?? []
      const currentGroups = confirmed.storyboardAllocation?.groups ?? []
      const allocationChanged = !equal(groupShape(base.storyboardAllocation?.groups ?? []), groupShape(currentGroups))
      if (allocationChanged || rows.length !== draft.length || rows.some((row, index) => row.draftNo !== index + 1)) {
        const groupForRow = (row: typeof rows[number]) => draftGroups.find((group) => group.shotNos.includes(row.draftNo ?? 0))
        groups = []
        const usedIds = new Set<string>()
        let previousGroup: string | undefined
        rows.forEach((row, index) => {
          const currentGroup = currentGroups.find((group) => group.shotNos.includes(row.source ?? 0))
          const group = (allocationChanged && saved.has(row.source ?? 0) ? currentGroup : undefined)
            ?? groupForRow(row) ?? draftGroups.find((group) => group.id === currentGroup?.id)
            ?? groupForRow(rows.find((item) => currentGroup?.shotNos.includes(item.source ?? 0) && item.draftNo) ?? row)
            ?? currentGroup
          if (!group) return
          if (previousGroup === group.id) groups!.at(-1)!.shotNos.push(index + 1)
          else {
            const id = usedIds.has(group.id) ? `group_${globalThis.crypto?.randomUUID?.().replace(/-/g, "") ?? Math.random().toString(36).slice(2)}` : group.id
            groups!.push({ ...group, id, shotNos: [index + 1] })
            usedIds.add(id)
          }
          previousGroup = group.id
        })
      }
      patch.directorPlanShots = rows.map(({ shot }, index) => ({ ...shot, shotNo: index + 1 }))
      failed.sourceShotNos = rows.map((row) => row.source)
    }
    if (patch.speakerRoster) {
      const before = new Map((base.speakerRoster ?? []).map((row) => [String(row.speakerId), row]))
      const draft = new Map(patch.speakerRoster.map((row) => [String(row.speakerId), row]))
      const next = new Map((confirmed.speakerRoster ?? []).map((row) => [String(row.speakerId), row]))
      for (const id of new Set([...before.keys(), ...draft.keys()])) {
        if (savedSpeakerIds.has(id) || equal(before.get(id), draft.get(id))) continue
        const row = draft.get(id)
        if (row) next.set(id, rebaseRecord(before.get(id) ?? {}, row, next.get(id) ?? {}))
        else next.delete(id)
      }
      patch.speakerRoster = [...next.values()]
    }
    if (groups && equal(groupShape(groups), groupShape(confirmed.storyboardAllocation?.groups ?? []))) groups = undefined
    failed.baseData = confirmed
    failed.request = { ...request, patch: changedPlanPatch(patch, confirmed), groups }
    if (failed.sourceShotNos) shotSources.set(keyFor(director.id, {
      shots: patch.directorPlanShots ?? confirmed.directorPlanShots ?? [],
      roster: patch.speakerRoster ?? confirmed.speakerRoster ?? [],
      groups: groupShape(groups ?? confirmed.storyboardAllocation?.groups ?? []),
    }), failed.sourceShotNos)
    if (!Object.keys(failed.request.patch).length && !groups) intents.delete(director.id)
  }
  const planPatches = (nodes: StoryboardNode[], director: StoryboardNode, patch: Partial<WorkflowNodeData>,
    groups?: StoryboardShotGroup[], allocation: { schemaVersion: number; directorPlanHash: string; groups: StoryboardShotGroup[] } | undefined = director.data.storyboardAllocation) => {
    const data = { ...director.data, ...patch,
      ...(groups ? { storyboardAllocation: { schemaVersion: 1, directorPlanHash: "pending", groups } } : {}),
    } as WorkflowNodeData
    const patches = new Map<string, Partial<WorkflowNodeData>>([[director.id, { ...patch,
      ...(groups ? { storyboardAllocation: { ...(allocation ?? data.storyboardAllocation!),
        groups: (allocation?.groups ?? groups).map((group, index) => ({ ...group, order: group.order ?? index + 1 })) } } : {}) }]])
    if (patch.directorPlanShots || patch.speakerRoster) {
      for (const unit of nodes) {
        if (!isStoryboardCardNodeType(unit.data.eyebrow) || unit.data.workChainId !== director.data.workChainId) continue
        const view = unitView(snapshot(data), unit.data.shotGroupId)
        const group = data.storyboardAllocation?.groups.find((item) => item.id === unit.data.shotGroupId)
        if (!view || !equal(group?.shotNos, unit.data.shotNos)) continue
        if (!equal(view.shots, unit.data.directorPlanShots) || !equal(view.roster, unit.data.speakerRoster)) {
          patches.set(unit.id, { directorPlanShots: view.shots, speakerRoster: view.roster })
        }
      }
    }
    return patches
  }
  const refreshDrafts = (director: StoryboardNode) => {
    if (!current()) return
    const key = chainKey(director)
    const edits = [...intents.values()].filter((intent) => chainKey(intent.director) === key)
      .sort((left, right) => left.sequence - right.sequence)
    if (!edits.length) { document.finishNodeData(key); return }
    document.stageNodeData(key, (base) => {
      let nodes = base
      const combined = new Map<string, Partial<WorkflowNodeData>>()
      for (const intent of edits) {
        const activeDirector = nodes.find((node) => node.id === intent.director.id) ?? intent.director
        let patches: Map<string, Partial<WorkflowNodeData>>
        if ("unit" in intent.request) {
          const request = intent.request
          const unit = nodes.find((node) => node.id === request.unit.id) ?? request.unit
          const edit = previewUnitEdit(activeDirector, unit, request)
          patches = new Map()
          if (edit) {
            patches = planPatches(nodes, activeDirector, edit.directorPlanPatch, edit.groups,
              { schemaVersion: 1, directorPlanHash: "pending", groups: edit.groups })
          }
          patches.set(unit.id, { ...patches.get(unit.id), directorPlanShots: request.shots, speakerRoster: request.roster })
        } else {
          patches = planPatches(nodes, activeDirector, intent.request.patch, intent.request.groups,
            intent.request.groups ? { schemaVersion: 1, directorPlanHash: "pending", groups: intent.request.groups } : undefined)
        }
        if (intent.failed) {
          patches.set(intent.originId, { ...patches.get(intent.originId), storyboardSaveFailed: true })
          patches.set(activeDirector.id, { ...patches.get(activeDirector.id), storyboardSaveFailed: true,
            storyboardFailedSaveKind: "unit" in intent.request || intent.request.patch.directorPlanShots || intent.request.patch.speakerRoster || intent.request.groups ? "plan" : "settings" })
        }
        for (const [id, patch] of patches) combined.set(id, { ...combined.get(id), ...patch })
        nodes = nodes.map((node) => patches.has(node.id) ? { ...node, data: { ...node.data, ...patches.get(node.id) } } : node)
      }
      return combined
    })
  }
  const commitView = (director: StoryboardNode, data: WorkflowNodeData, groups?: StoryboardShotGroup[], revision?: number) => {
    if (!current() || document.isStaleRevision(revision)) return
    document.updateNodes((nodes) => {
      const canonical = { ...director, data: { ...director.data, ...data } }
      const patches = planPatches(nodes, canonical, data, groups, data.storyboardAllocation)
      return nodes.map((node) => patches.has(node.id) ? { ...node, data: { ...node.data, ...patches.get(node.id) } } : node)
    })
  }
  const finishCommit = async (intent: SaveIntent, result: Awaited<ReturnType<typeof applyStoryboardAllocation>>) => {
    if (!current()) return
    try {
      await applyMutation(result)
    } catch (error) {
      // Persistence has succeeded. A failed refresh must not become a failed write.
      console.warn("分镜已保存，画布等待后台刷新:", error)
      if (current()) document.requestBackfill()
    }
    if (!current()) return
    const data = result.node?.data as WorkflowNodeData | undefined
    if (data) commitView(intent.director, data, result.groups, result.workflowVersion)
    if (result.editHistoryWarning) onWarning(result.editHistoryWarning)
    for (const warning of result.productionWarnings ?? []) onWarning(warning.message)
  }
  const enqueue = (intent: SaveIntent, run: () => Promise<void>) => {
    intents.set(intent.originId, intent)
    refreshDrafts(intent.director)
    tail = tail.then(async () => {
      try {
        await beforeWrite?.()
        await run()
        if (intents.get(intent.originId) === intent) intents.delete(intent.originId)
        refreshDrafts(intent.director)
      } catch (error) {
        if (intents.get(intent.originId) === intent) {
          intent.failed = true
          if (!("unit" in intent.request) && intent.baseData) {
            const request = intent.request
            intent.request = { ...request, patch: changedPlanPatch(request.patch, intent.baseData),
              groups: request.groups && !equal(groupShape(request.groups), groupShape(intent.baseData.storyboardAllocation?.groups ?? []))
                ? request.groups : undefined }
          }
        }
        refreshDrafts(intent.director)
        onFailure(error)
      }
    })
  }
  return {
    waitForWrites: () => tail,
    discardFailed(nodeId: string) {
      const node = document.read().nodes.find((node) => node.id === nodeId)
      if (!node) return
      const affected = [...intents.values()].filter((intent) => intent.failed && (intent.originId === nodeId
        || (intent.director.id === nodeId)))
      for (const intent of affected) {
        intents.delete(intent.originId)
        refreshDrafts(intent.director)
      }
      return document.read().nodes.find((node) => node.id === nodeId)?.data
    },
    saveDirector(request: DirectorSaveRequest) {
      if (!current()) return
      const { director, patch, groups, invalidateGenerated, sourceShotNos } = request
      const before = snapshot(director.data)
      if (sourceShotNos) rememberDraftSources(director, before)
      // The visible plan can contain failed drafts from either editor. CAS is
      // against the confirmed plan, never against that optimistic projection.
      const confirmedDirector = document.readConfirmedNodes().find((node) => node.id === director.id)
      const expected = snapshot(confirmedDirector?.data.directorPlanShots ? confirmedDirector.data : director.data)
      const submitted = { shots: patch.directorPlanShots ?? before.shots, roster: patch.speakerRoster ?? before.roster, groups: groupShape(groups ?? before.groups) }
      const sourceBasis = sourcesFor(director.id, before)
      if (sourceShotNos) shotSources.set(keyFor(director.id, submitted), sourceShotNos.map((number) => number == null ? null : sourceBasis[number - 1] ?? null))
      if (!equal(before, submitted)) aliases.set(keyFor(director.id, submitted), resolve(director.id, before))
      const represented = [...intents.values()].filter((intent) => intent.failed && intent.director.id === director.id
        && (patch.directorPlanShots || patch.speakerRoster || groups))
      const intent: SaveIntent = { sequence: ++sequence, originId: director.id, director, failed: false, request,
        baseData: confirmedDirector?.data.directorPlanShots ? confirmedDirector.data : director.data,
        sourceShotNos: sourceShotNos?.map((number) => number == null ? null : sourceBasis[number - 1] ?? null) }
      enqueue(intent, async () => {
        const authoritative = (await readNodes([director.id])).find((node) => node.id === director.id)
        if (!authoritative) throw new Error("找不到对应的分镜脚本")
        const actual = snapshot(authoritative.data)
        if (!equal(actual, resolve(director.id, expected))) throw new Error("分镜脚本已变化，请重新打开后保存")
        intent.baseData = authoritative.data
        const settingsOnly = !groups && !patch.directorPlanShots && !patch.speakerRoster
        let result: Awaited<ReturnType<typeof applyStoryboardAllocation>>
        try {
          if (settingsOnly) {
            const saved = await saveWorkflowNodeInlineEdit(callBackend, projectId, episodeId, {
              nodeId: director.id, data: patch, reason: "director_generation_settings_saved", source: "user",
            })
            if (saved.skippedLocked) throw new Error(saved.message || "分镜脚本已锁定，请先解锁")
            result = { ...saved, success: true, directorNodeId: director.id, episodeId,
              groups: authoritative.data.storyboardAllocation?.groups ?? [] }
          } else {
            intent.sourceShotNos = sourceShotNos && remapSources(director.id, before, sourceShotNos)
            result = await applyStoryboardAllocation(callBackend, projectId, episodeId, {
              directorNodeId: director.id, directorPlanShots: actual.shots, expectedSpeakerRoster: actual.roster, expectedGroups: actual.groups,
              directorPlanPatch: patch, groups: (groups ?? authoritative.data.storyboardAllocation?.groups ?? []).map((group) => ({
                ...group, id: actual.groups.find((saved) => equal(saved.shotNos, group.shotNos))?.id ?? group.id,
              })), invalidateGenerated, sourceShotNos: intent.sourceShotNos,
            })
          }
        } catch (error) { rememberPlan(director, before, submitted, actual, false); throw error }
        rememberPlan(director, before, submitted, snapshot(result.node?.data as Partial<WorkflowNodeData> ?? { ...authoritative.data, ...patch }))
        for (const failed of represented) if (intents.get(failed.originId) === failed) intents.delete(failed.originId)
        await finishCommit(intent, result)
      })
    },
    saveUnit(nodeId: string, shots: Rows, roster: Rows, expectedShots: Rows, expectedRoster: Rows, sourceShotNos?: Array<number | null>) {
      if (!current()) return
      const nodes = document.read().nodes
      const unit = nodes.find((node) => node.id === nodeId && isStoryboardCardNodeType(node.data.eyebrow))
      const director = nodes.find((node) => isDirectorBoardNodeType(node.data.eyebrow) && node.data.workChainId === unit?.data.workChainId)
      if (!unit || !director) throw new Error("找不到分镜单元对应的分镜脚本")
      if (!shots.length) throw new Error("分镜单元至少保留一个镜头")
      const before: Snapshot = { shots: expectedShots, roster: expectedRoster, groups: [] }
      const submitted: Snapshot = { shots, roster, groups: [] }
      const sourceBasis = sourcesFor(nodeId, before)
      if (sourceShotNos) shotSources.set(keyFor(nodeId, submitted), sourceShotNos.map((number) => number == null ? null : sourceBasis[number - 1] ?? null))
      if (!equal(before, submitted)) aliases.set(keyFor(nodeId, submitted), resolve(nodeId, before))
      const beforeDirector = snapshot(director.data)
      const intent: SaveIntent = { sequence: ++sequence, originId: nodeId, director, failed: false,
        request: { unit, shots, roster, expectedShots, expectedRoster, sourceShotNos } }
      enqueue(intent, async () => {
        const fresh = await readNodes([director.id, nodeId])
        const canonical = fresh.find((node) => node.id === director.id), currentUnit = fresh.find((node) => node.id === nodeId)
        if (!canonical || !currentUnit) throw new Error("分镜单元已变化，请重新打开")
        if (!equal(unit.data.shotNos, currentUnit.data.shotNos)) throw new Error("镜头分组已变化，请重新打开分镜单元")
        const expected = resolve(nodeId, before)
        const edit = storyboardUnitEdit(currentUnit, canonical, shots, roster, expected.shots, expected.roster,
          sourceShotNos && remapSources(nodeId, before, sourceShotNos))
        const actualUnit: Snapshot = { shots: currentUnit.data.directorPlanShots ?? [], roster: currentUnit.data.speakerRoster ?? [], groups: [] }
        const actual = snapshot(canonical.data)
        const submittedPlan = { shots: edit.directorPlanPatch.directorPlanShots, roster: edit.directorPlanPatch.speakerRoster, groups: groupShape(edit.groups) }
        if (edit.sourceShotNos) shotSources.set(keyFor(director.id, submittedPlan), edit.sourceShotNos)
        if (current()) commitView(director, canonical.data)
        let result: Awaited<ReturnType<typeof applyStoryboardAllocation>>
        try { result = await applyStoryboardAllocation(callBackend, projectId, episodeId, edit) }
        catch (error) {
          remember(nodeId, before, submitted, actualUnit, false)
          rememberPlan(director, actual, submittedPlan, actual, false)
          throw error
        }
        const confirmed = snapshot(result.node?.data as Partial<WorkflowNodeData> ?? { ...canonical.data, ...edit.directorPlanPatch })
        const confirmedUnit = unitView(confirmed, currentUnit.data.shotGroupId)
        if (confirmedUnit) remember(nodeId, before, submitted, confirmedUnit)
        rememberPlan(director, beforeDirector, { shots: edit.directorPlanPatch.directorPlanShots,
          roster: edit.directorPlanPatch.speakerRoster, groups: groupShape(edit.groups) }, confirmed)
        settleFailedScript(director, result.node?.data as WorkflowNodeData ?? { ...canonical.data, ...edit.directorPlanPatch },
          Array.from({ length: shots.length }, (_, index) => currentUnit.data.shotNos![0] + index),
          new Set([...expectedRoster, ...roster].map((row) => String(row.speakerId))), edit.sourceShotNos)
        await finishCommit(intent, result)
      })
    },
  }
}
