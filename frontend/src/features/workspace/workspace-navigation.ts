import { Gauge, History, Layers3, Package, PawPrint, Users } from "lucide-react"
import { type AssetTab, type WorkspaceSection } from "@/navigation"


export type WorkspaceEpisodeDeleteMode = "episode" | "canvas"

export type WorkspaceCanvasMode = "work_chain" | "custom"

export type WorkspaceEpisodeDeleteDraft = {
  episode: {
    id: string
    title?: string
    status?: string
  }
  mode: WorkspaceEpisodeDeleteMode
}

const WORKSPACE_SIDEBAR_COLLAPSED_STORAGE_KEY =
  "ai_video_workspace_sidebar_collapsed_v1"

const WORKSPACE_ASSISTANT_ENABLED_STORAGE_KEY =
  "ai_video_workspace_assistant_enabled_v1"

const WORKSPACE_CANVAS_MODE_STORAGE_KEY_PREFIX =
  "ai_video_workspace_canvas_mode_v1:"

export function readWorkspaceSidebarCollapsed() {
  if (typeof window === "undefined") return false
  try {
    const stored = window.localStorage.getItem(
      WORKSPACE_SIDEBAR_COLLAPSED_STORAGE_KEY
    )
    return stored === "true"
  } catch {
    return false
  }
}

export function persistWorkspaceSidebarCollapsed(collapsed: boolean) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(
      WORKSPACE_SIDEBAR_COLLAPSED_STORAGE_KEY,
      collapsed ? "true" : "false"
    )
  } catch {
    // localStorage can be unavailable in restricted webviews.
  }
}

export function readWorkspaceAssistantEnabled() {
  if (typeof window === "undefined") return true
  try {
    return window.localStorage.getItem(WORKSPACE_ASSISTANT_ENABLED_STORAGE_KEY) !== "false"
  } catch {
    return true
  }
}

export function persistWorkspaceAssistantEnabled(enabled: boolean) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(
      WORKSPACE_ASSISTANT_ENABLED_STORAGE_KEY,
      enabled ? "true" : "false"
    )
  } catch {
    // localStorage can be unavailable in restricted webviews.
  }
}

export function normalizeWorkspaceCanvasMode(value: unknown): WorkspaceCanvasMode | null {
  return value === "custom" || value === "work_chain" ? value : null
}

function workspaceCanvasModeStorageKey(projectId: string) {
  return `${WORKSPACE_CANVAS_MODE_STORAGE_KEY_PREFIX}${projectId || "default"}`
}

export function readWorkspaceCanvasMode(projectId: string): WorkspaceCanvasMode {
  if (typeof window === "undefined") return "work_chain"
  try {
    return (
      normalizeWorkspaceCanvasMode(
        window.localStorage.getItem(workspaceCanvasModeStorageKey(projectId))
      ) ?? "work_chain"
    )
  } catch {
    return "work_chain"
  }
}

export function persistWorkspaceCanvasMode(
  projectId: string,
  mode: WorkspaceCanvasMode
) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(workspaceCanvasModeStorageKey(projectId), mode)
  } catch {
    // localStorage can be unavailable in restricted webviews.
  }
}

export const workspaceNav: Array<{
  id: WorkspaceSection
  label: string
  icon: typeof Gauge
}> = [
  { id: "overview", label: "项目概览", icon: Gauge },
  { id: "asset-split-records", label: "拆分记录", icon: History },
  { id: "characters", label: "角色", icon: Users },
  { id: "creatures", label: "生物", icon: PawPrint },
  { id: "scenes", label: "场景", icon: Layers3 },
  { id: "props", label: "道具", icon: Package },
]

export function normalizeWorkspaceSection(
  section: WorkspaceSection
): WorkspaceSection {
  return section === "sources" ? "overview" : section
}

type WorkspaceAssetSection = Extract<WorkspaceSection, AssetTab>

export function isAssetWorkspaceSection(
  section: WorkspaceSection
): section is WorkspaceAssetSection {
  return (
    section === "characters" ||
    section === "creatures" ||
    section === "scenes" ||
    section === "props"
  )
}
