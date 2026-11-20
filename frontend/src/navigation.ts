export type SettingsSection =
  | "providers"
  | "media"
  | "script-adaptation-templates"
  | "director-rules"
  | "text-replacement-templates"
  | "storyboard-templates"
  | "quality"
  | "usage"

export type AssetTab =
  | "characters"
  | "creatures"
  | "scenes"
  | "props"
  | "styles"

export type WorkspaceSection =
  | "overview"
  | "sources"
  | "asset-split-records"
  | "characters"
  | "creatures"
  | "scenes"
  | "props"
  | "episode"

export type WorkspaceDock = "notifications" | "tasks" | "usage" | "export"

const SETTINGS_SECTIONS: SettingsSection[] = [
  "providers",
  "media",
  "script-adaptation-templates",
  "director-rules",
  "text-replacement-templates",
  "storyboard-templates",
  "quality",
  "usage",
]
const ASSET_TABS: AssetTab[] = [
  "characters",
  "creatures",
  "scenes",
  "props",
  "styles",
]
export const WORKSPACE_SECTIONS: WorkspaceSection[] = [
  "overview",
  "sources",
  "asset-split-records",
  "characters",
  "creatures",
  "scenes",
  "props",
  "episode",
]

const CURRENT_PROJECT_STORAGE_KEY = "ai_video_current_project_id"
const SESSION_VIEW_STORAGE_KEY = "ai_video_reload_session_view"
const SESSION_VIEW_RESTORE_INTENT_KEY = "ai_video_reload_session_view_restore"

export type AssetReturnTarget =
  | { kind: "projects" }
  | {
      kind: "workspace"
      projectId: string
      section: WorkspaceSection
      episodeId?: string
    }

export type AppView =
  | { kind: "projects" }
  | { kind: "settings"; section: SettingsSection; providerAction?: "add" }
  | { kind: "assets"; tab: AssetTab; returnTo?: AssetReturnTarget }
  | {
      kind: "project-settings"
      projectId: string
      returnSection?: WorkspaceSection
      returnEpisodeId?: string
    }
  | {
      kind: "workspace"
      projectId: string
      section: WorkspaceSection
      episodeId?: string
    }

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value))
}

function includesString<T extends string>(
  values: readonly T[],
  value: unknown
): value is T {
  return typeof value === "string" && values.includes(value as T)
}

function optionalString(value: unknown) {
  return typeof value === "string" && value.trim() ? value : undefined
}

function parseAssetReturnTarget(value: unknown): AssetReturnTarget | undefined {
  if (!isRecord(value)) return undefined
  if (value.kind === "projects") return { kind: "projects" }
  const section = value.section
  if (
    value.kind === "workspace" &&
    typeof value.projectId === "string" &&
    value.projectId.trim() &&
    includesString(WORKSPACE_SECTIONS, section)
  ) {
    return {
      kind: "workspace",
      projectId: value.projectId,
      section,
      episodeId: optionalString(value.episodeId),
    }
  }
  return undefined
}

function parseSessionView(value: unknown): AppView | null {
  if (!isRecord(value)) return null
  if (value.kind === "projects") return { kind: "projects" }
  const section = value.section
  const tab = value.tab
  if (value.kind === "settings" && includesString(SETTINGS_SECTIONS, section)) {
    const view: AppView = { kind: "settings", section }
    if (value.providerAction === "add") view.providerAction = "add"
    return view
  }
  if (value.kind === "assets" && includesString(ASSET_TABS, tab)) {
    return {
      kind: "assets",
      tab,
      returnTo: parseAssetReturnTarget(value.returnTo),
    }
  }
  if (
    value.kind === "project-settings" &&
    typeof value.projectId === "string" &&
    value.projectId.trim()
  ) {
    const view: AppView = {
      kind: "project-settings",
      projectId: value.projectId,
    }
    const returnSection = value.returnSection
    if (includesString(WORKSPACE_SECTIONS, returnSection)) {
      view.returnSection = returnSection
    }
    view.returnEpisodeId = optionalString(value.returnEpisodeId)
    return view
  }
  if (
    value.kind === "workspace" &&
    typeof value.projectId === "string" &&
    value.projectId.trim() &&
    includesString(WORKSPACE_SECTIONS, section)
  ) {
    const view: AppView = {
      kind: "workspace",
      projectId: value.projectId,
      section,
      episodeId: optionalString(value.episodeId),
    }
    return view
  }
  return null
}

function isReloadNavigation() {
  if (typeof window === "undefined") return false
  const navigationEntry = window.performance
    ?.getEntriesByType?.("navigation")
    ?.find((entry): entry is PerformanceNavigationTiming => "type" in entry)
  if (navigationEntry?.type) return navigationEntry.type === "reload"
  return window.performance?.navigation?.type === 1
}

export function readReloadSessionView() {
  if (typeof window === "undefined") return null
  try {
    const hasRestoreIntent =
      window.sessionStorage.getItem(SESSION_VIEW_RESTORE_INTENT_KEY) === "1"
    window.sessionStorage.removeItem(SESSION_VIEW_RESTORE_INTENT_KEY)
    if (!isReloadNavigation() && !hasRestoreIntent) {
      window.sessionStorage.removeItem(SESSION_VIEW_STORAGE_KEY)
      return null
    }
    const raw = window.sessionStorage.getItem(SESSION_VIEW_STORAGE_KEY)
    return raw ? parseSessionView(JSON.parse(raw)) : null
  } catch {
    return null
  }
}

export function markReloadSessionViewRestoreIntent() {
  if (typeof window === "undefined") return
  try {
    window.sessionStorage.setItem(SESSION_VIEW_RESTORE_INTENT_KEY, "1")
  } catch {
    // sessionStorage may be unavailable.
  }
}

export function persistReloadSessionView(view: AppView | null) {
  if (typeof window === "undefined") return
  try {
    if (view) {
      window.sessionStorage.setItem(SESSION_VIEW_STORAGE_KEY, JSON.stringify(view))
    } else {
      window.sessionStorage.removeItem(SESSION_VIEW_STORAGE_KEY)
    }
  } catch {
    // sessionStorage may be unavailable.
  }
}

export function readPersistedCurrentProjectId() {
  if (typeof window === "undefined") return null
  try {
    const raw = window.localStorage.getItem(CURRENT_PROJECT_STORAGE_KEY)
    return raw && raw.trim() ? raw : null
  } catch {
    return null
  }
}

export function persistCurrentProjectId(projectId: string | null) {
  if (typeof window === "undefined") return
  try {
    if (projectId) {
      window.localStorage.setItem(CURRENT_PROJECT_STORAGE_KEY, projectId)
    } else {
      window.localStorage.removeItem(CURRENT_PROJECT_STORAGE_KEY)
    }
  } catch {
    // localStorage may be unavailable.
  }
}
