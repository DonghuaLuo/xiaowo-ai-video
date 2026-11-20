import type { AssetTab, WorkspaceSection } from "@/navigation"

export type AgentProjectEffect = {
  action?: string
  changedResources?: string[]
  focusTarget?: {
    section?: WorkspaceSection
    episodeId?: string
    canvasKind?: "work_chain" | "custom" | string
    canvasId?: string
    canvasTitle?: string
    assetTab?: AssetTab
    nodeId?: string
    routeId?: string
    segmentId?: string
    assetId?: string
  }
  notice?: string
  projectId?: string
  episodeId?: string
  episodeIds?: string[]
  targets?: string[]
  sessionId?: string
  nonce?: number
}
