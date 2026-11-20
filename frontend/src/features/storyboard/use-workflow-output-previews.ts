import { useEffect, useMemo, useState } from "react"
import { useStore } from "@xyflow/react"
import { listStoryboardVersions, type MediaAsset } from "@/backend"
import { useBackend } from "@/hooks/useBackend"
import { localMediaFileSrc, mediaPreviewSrc, mediaThumbnailSrc } from "@/shared/media"
import { resolveProjectMediaUrl } from "@/utils/style-thumbnails"
import {
  isStoryboardCardNodeType,
  workflowCardTitleSuffix,
  workflowNodeDataCurrentVersionId,
  type WorkflowNodeData,
} from "./workflow-canvas-model"
import { workflowNodeDataIsVisualHandoffAsset } from "./workflow-canvas-asset-model"

export type WorkflowOutputPreview = {
  key: string
  label: string
  kind: "image" | "video"
  media: MediaAsset | null
  src: string
  thumbnail: string
  versionId: string
  nodeType: string
  category: "storyboard" | "handoff" | "video"
}

export function useWorkflowOutputPreviews(data: WorkflowNodeData) {
  const { backendReady, callBackend } = useBackend()
  const projectId = String(data.projectId ?? "")
  const episodeId = String(data.episodeId ?? "")
  // Subscribe to result media changes, not canvas positions or selection.
  const snapshot = useStore((state) => {
    const storyboardUnit = isStoryboardCardNodeType(data.eyebrow)
    const nodeId = String(data.nodeId ?? "")
    const targets = new Set(state.edges.filter((edge) => edge.source === nodeId).map((edge) => edge.target))
    return JSON.stringify(state.nodes.flatMap((node): WorkflowOutputPreview[] => {
      const resultData = node.data as WorkflowNodeData
      const handoff = workflowNodeDataIsVisualHandoffAsset(resultData)
      const output = storyboardUnit
        ? resultData.eyebrow === "storyboard.image" || handoff
        : resultData.eyebrow === "video.result"
      if (!nodeId || !output || !(
        targets.has(node.id) || resultData.resultOfNodeId === nodeId || resultData.sourceNodeId === nodeId
      )) return []
      const media = resultData.media ?? resultData.storage ?? null
      const kind = resultData.eyebrow === "video.result" ? "video" : "image"
      return [{
        key: node.id,
        label: workflowCardTitleSuffix(resultData) || (handoff ? "视觉交接图" : kind === "video" ? "视频" : "分镜图"),
        kind,
        media,
        src: mediaPreviewSrc(media) || "",
        thumbnail: mediaThumbnailSrc(media ? { ...media, kind } : null) || "",
        versionId: workflowNodeDataCurrentVersionId(resultData) ?? "",
        nodeType: resultData.eyebrow ?? "",
        category: kind === "video" ? "video" : handoff ? "handoff" : "storyboard",
      }]
    }))
  })
  const candidates = useMemo(() => JSON.parse(snapshot) as WorkflowOutputPreview[], [snapshot])
  const scope = JSON.stringify([projectId, episodeId, data.nodeId, snapshot, backendReady])
  const [resolved, setResolved] = useState<{ scope: string; items: WorkflowOutputPreview[] } | null>(null)

  useEffect(() => {
    let cancelled = false
    void Promise.all(candidates.map(async (candidate) => {
      let media = candidate.media
      try {
        if (!candidate.src && candidate.versionId && backendReady && projectId && episodeId) {
          const versions = await listStoryboardVersions(callBackend, projectId, episodeId, candidate.key)
          const version = versions.find((item) => item.id === candidate.versionId)
          if (version) media = { ...version.media, preview: version.preview ?? version.media?.preview }
        }
        const src = localMediaFileSrc(media) || await resolveProjectMediaUrl(projectId, media) || mediaPreviewSrc(media) || ""
        return { ...candidate, media, src, thumbnail: mediaThumbnailSrc(media ? { ...media, kind: candidate.kind } : null) || "" }
      } catch {
        return candidate
      }
    })).then((items) => {
      if (!cancelled) setResolved({ scope, items })
    })
    return () => { cancelled = true }
  }, [backendReady, callBackend, candidates, episodeId, projectId, scope])

  return {
    // Resolve placeholder versions first; expose only results with preview media.
    items: (resolved?.scope === scope ? resolved.items : candidates)
      .filter((item) => Boolean(item.src.trim())),
    loading: candidates.length > 0 && resolved?.scope !== scope,
  }
}
