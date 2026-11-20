import { type CustomCanvasEntry } from "@/backend"
import type { AgentProjectEffect } from "@/features/workspace/types"


const LOCAL_WORKSPACE_EFFECT_ACTIONS = new Set([
  "canvas_result_committed",
  "asset_created",
  "asset_updated",
  "asset_deleted",
  "asset_upserted",
  "asset_batch_saved",
  "asset_media_generated",
  "asset_media_version_activated",
  "asset_media_version_updated",
  "asset_media_version_deleted",
  "workflow_input_linked",
  "workflow_input_unlinked",
  "workflow_reference_usage_updated",
  "workflow_media_imported",
  "workflow_asset_nodes_added",
  "workflow_task_card_created",
  "workflow_item_upserted",
  "workflow_route_updated",
  "workflow_item_deleted",
  "workflow_node_layout_updated",
  "workflow_node_inline_saved",
  "node_edit_history_restored",
  "node_edit_history_deleted",
  "canvas_asset_images_resolved",
  "workflow_node_generated",
  "workflow_cinematic_script_generated",
  "workflow_batch_generated",
  "workflow_variant_selected",
  "workflow_node_preflight_checked",
  "storyboard_image_requested",
  "storyboard_image_generated",
  "storyboard_image_edited",
  "storyboard_image_edit_completed",
  "storyboard_image_edit_failed",
  "storyboard_result_version_activated",
  "storyboard_version_deleted",
  "visual_handoff_image_generated",
  "storyboard_video_requested",
  "storyboard_video_generated",
  "route_video_requested",
  "route_video_generated",
  "variant_quality_result_saved",
  "variant_quality_auto_reviewed",
  "shot_prompt_patched",
  "visual_handoff_cross_episode_imported",
  "visual_handoff_cross_episode_linked",
  "episode_production_status_updated",
  "agent_split_completed",
])

const LOCAL_ASSET_ROW_UPDATE_ACTIONS = new Set([
  "asset_created",
  "asset_updated",
  "asset_upserted",
  "asset_media_generated",
  "asset_media_version_activated",
  "asset_media_version_updated",
  "asset_media_version_deleted",
])

const LOCAL_WORKSPACE_EFFECT_RESOURCES = new Set([
  "asset",
  "assets",
  "characters",
  "creatures",
  "scenes",
  "props",
  "canvas_document",
  "canvas_documents",
  "canvas_node",
  "canvas_nodes",
  "canvas_edge",
  "canvas_edges",
  "canvas_route",
  "canvas_routes",
  "canvas_work_chain",
  "canvas_work_chains",
  "canvas_version",
  "canvas_versions",
  "canvas_task",
  "canvas_tasks",
  "canvas_projection",
  "canvas_projections",
  "episode_production_status",
  "variant_quality_results",
  "visual_handoff",
  "node_edit_history",
])

const WORKSPACE_PROJECT_REFRESH_RESOURCES = new Set([
  "project",
  "episode",
  "episodes",
  "storyboard",
  "workChainPlan",
  "work_chain_plan",
  "sourceCoverage",
  "source_coverage",
  "source",
  "sources",
  "sourceText",
  "source_text",
  "source_splits",
  "episodeSource",
  "episode_source",
  "canvas_catalog",
])

const WORKSPACE_CUSTOM_CANVAS_CATALOG_ACTIONS = new Set([
  "custom_canvas_created",
  "custom_canvas_renamed",
  "custom_canvas_deleted",
])

const WORKSPACE_CANVAS_DOCUMENT_RESOURCES = new Set([
  "canvas_document",
  "canvas_documents",
  "canvas_node",
  "canvas_nodes",
  "canvas_edge",
  "canvas_edges",
  "canvas_route",
  "canvas_routes",
  "canvas_work_chain",
  "canvas_work_chains",
  "canvas_version",
  "canvas_versions",
  "canvas_task",
  "canvas_tasks",
  "canvas_projection",
  "canvas_projections",
])

const WORKSPACE_ASSET_EFFECT_RESOURCES = new Set([
  "asset",
  "assets",
  "characters",
  "creatures",
  "scenes",
  "props",
])

const WORKSPACE_ASSET_SPLIT_RECORD_ACTIONS = new Set([
  "asset_batch_saved",
  "latest_asset_range_deleted",
  "asset_range_analysis_retry_requested",
  "project_assets_deleted_all",
])

const WORKSPACE_ASSET_SPLIT_RECORD_RESOURCES = new Set([
  "assetRanges",
  "asset_ranges",
  "sourceCoverage",
  "source_coverage",
])

const WORKSPACE_ASSET_EFFECT_FOCUS_SECTIONS = new Set([
  "assets",
  "asset-split-records",
  "characters",
  "creatures",
  "scenes",
  "props",
])

const WORKSPACE_TASK_EFFECT_RESOURCES = new Set([
  "task",
  "tasks",
  "canvas_task",
  "canvas_tasks",
  "workflow_task",
  "workflow_tasks",
])

const WORKSPACE_TASK_EFFECT_ACTIONS = new Set([
  "workflow_node_generated",
  "workflow_cinematic_script_generated",
  "workflow_batch_generated",
  "workflow_node_preflight_checked",
  "storyboard_image_requested",
  "storyboard_image_generated",
  "storyboard_image_edited",
  "storyboard_image_edit_completed",
  "storyboard_image_edit_failed",
  "visual_handoff_image_generated",
  "storyboard_video_requested",
  "storyboard_video_generated",
  "route_video_requested",
  "route_video_generated",
])

function workspaceEffectResources(effect: AgentProjectEffect): string[] {
  const record = effect as any
  const resources: unknown[] = Array.isArray(effect.changedResources)
    ? effect.changedResources
    : Array.isArray(record.changed_resources)
      ? record.changed_resources
      : []
  return resources.map((resource: unknown) => String(resource || ""))
}

export function workspaceEffectTouchesCustomCanvasList(
  effect: AgentProjectEffect,
  customCanvases: CustomCanvasEntry[]
) {
  const action = String(effect.action ?? "")
  const resources = workspaceEffectResources(effect)
  if (
    WORKSPACE_CUSTOM_CANVAS_CATALOG_ACTIONS.has(action) ||
    resources.includes("canvas_catalog")
  ) {
    return true
  }
  if (
    !resources.some((resource) =>
      WORKSPACE_CANVAS_DOCUMENT_RESOURCES.has(resource)
    )
  ) {
    return false
  }
  const customCanvasStorageKeys = new Set(
    customCanvases.flatMap((canvas) =>
      [canvas.storageKey, canvas.canvasId]
        .map((value) => String(value ?? "").trim())
        .filter(Boolean)
    )
  )
  if (customCanvasStorageKeys.size === 0) return false
  return workspaceEffectEpisodeIds(effect).some((episodeId) =>
    customCanvasStorageKeys.has(episodeId)
  )
}

export function workspaceEventProjectId(payload: unknown) {
  const record = payload as any
  return String(record?.projectId ?? record?.project_id ?? "").trim()
}

export function workspaceEffectEpisodeIds(effect: AgentProjectEffect): string[] {
  const record = effect as any
  const rawEpisodeIds =
    record.episodeIds ?? record.episode_ids ?? record.episodeId ?? record.episode_id
  const values = Array.isArray(rawEpisodeIds) ? rawEpisodeIds : [rawEpisodeIds]
  return values
    .map((value) => String(value ?? "").trim())
    .filter(Boolean)
}

function workspaceEffectTargets(effect: AgentProjectEffect): string[] {
  const record = effect as any
  const rawTargets = record.targets ?? record.target
  const values = Array.isArray(rawTargets) ? rawTargets : [rawTargets]
  return values
    .map((value) => String(value ?? "").trim())
    .filter(Boolean)
}

export function workspaceEffectDeletesPlanningOutputs(effect: AgentProjectEffect) {
  return String(effect.action ?? "") === "project_planning_outputs_deleted"
}

export function workspaceEffectDeletesEpisodeSource(effect: AgentProjectEffect) {
  return workspaceEffectTargets(effect).includes("source_splits")
}

export function workspacePlanningDeleteSignature(effect: AgentProjectEffect) {
  return [
    workspaceEffectEpisodeIds(effect).sort().join("|"),
    workspaceEffectTargets(effect).sort().join("|"),
  ].join("::")
}

function workspaceEffectFocusSection(effect: AgentProjectEffect) {
  const focusTarget = (effect as any).focusTarget ?? (effect as any).focus_target
  return String(focusTarget?.section ?? "").trim()
}

function workspaceEffectHasAssetSplitLocalSignal(
  effect: AgentProjectEffect,
  resources: string[]
) {
  if (resources.some((resource) => resource === "assetRanges" || resource === "asset_ranges")) {
    return true
  }
  if (
    resources.some((resource) =>
      WORKSPACE_ASSET_EFFECT_RESOURCES.has(resource)
    )
  ) {
    return true
  }
  return WORKSPACE_ASSET_EFFECT_FOCUS_SECTIONS.has(
    workspaceEffectFocusSection(effect)
  )
}

export function isLocalWorkspaceEffect(effect: AgentProjectEffect) {
  const action = String(effect.action ?? "")
  const resources = workspaceEffectResources(effect)
  const projectLevelResources = resources.filter((resource) =>
    WORKSPACE_PROJECT_REFRESH_RESOURCES.has(resource)
  )
  const hasProjectLevelResource = projectLevelResources.length > 0
  const projectLevelResourcesAreAssetSplitOnly =
    hasProjectLevelResource &&
    projectLevelResources.every((resource) =>
      WORKSPACE_ASSET_SPLIT_RECORD_RESOURCES.has(resource)
    )
  const hasOnlyAssetSplitProjectResources =
    !hasProjectLevelResource || projectLevelResourcesAreAssetSplitOnly
  const hasLocalResource = resources.some((resource) =>
    LOCAL_WORKSPACE_EFFECT_RESOURCES.has(resource)
  )
  const hasAssetSplitLocalSignal =
    hasOnlyAssetSplitProjectResources &&
    workspaceEffectHasAssetSplitLocalSignal(effect, resources)
  if (
    LOCAL_WORKSPACE_EFFECT_ACTIONS.has(action) ||
    WORKSPACE_ASSET_SPLIT_RECORD_ACTIONS.has(action)
  ) {
    return !hasProjectLevelResource || projectLevelResourcesAreAssetSplitOnly
  }
  if (hasAssetSplitLocalSignal) {
    return true
  }
  return !hasProjectLevelResource && hasLocalResource
}

function workspaceEffectTouchesAssets(effect: AgentProjectEffect) {
  const action = String(effect.action ?? "")
  return (
    action.startsWith("asset_") ||
    workspaceEffectResources(effect).some((resource) =>
      WORKSPACE_ASSET_EFFECT_RESOURCES.has(resource)
    )
  )
}

export function workspaceEffectMayChangeAssetCounts(effect: AgentProjectEffect) {
  const action = String(effect.action ?? "")
  if (action === "asset_updated") {
    const assetType = String(
      (effect as any).assetType ?? (effect as any).asset_type ?? ""
    )
    return ["characters", "creatures", "scenes", "props"].includes(assetType)
  }
  return (
    action === "asset_created" ||
    action === "asset_deleted" ||
    action === "asset_upserted" ||
    action === "asset_batch_saved" ||
    action === "latest_asset_range_deleted" ||
    action === "project_assets_deleted_all"
  )
}

export function workspaceEffectTouchesAssetSplitRecords(effect: AgentProjectEffect) {
  const action = String(effect.action ?? "")
  return (
    WORKSPACE_ASSET_SPLIT_RECORD_ACTIONS.has(action) ||
    workspaceEffectResources(effect).some((resource) =>
      WORKSPACE_ASSET_SPLIT_RECORD_RESOURCES.has(resource)
    )
  )
}

function workspaceEffectHasAssetRecord(effect: AgentProjectEffect) {
  const record = effect as any
  const asset = record.asset
  return Boolean(asset && typeof asset === "object" && typeof asset.id === "string")
}

export function workspaceEffectNeedsAssetGalleryReload(effect: AgentProjectEffect) {
  const action = String(effect.action ?? "")
  if (
    LOCAL_ASSET_ROW_UPDATE_ACTIONS.has(action) &&
    workspaceEffectHasAssetRecord(effect)
  ) {
    return false
  }
  return workspaceEffectTouchesAssets(effect)
}

export function workspaceEffectTouchesTasks(effect: AgentProjectEffect) {
  const action = String(effect.action ?? "")
  return (
    action.startsWith("task_") ||
    WORKSPACE_TASK_EFFECT_ACTIONS.has(action) ||
    workspaceEffectResources(effect).some((resource) =>
      WORKSPACE_TASK_EFFECT_RESOURCES.has(resource)
    )
  )
}
