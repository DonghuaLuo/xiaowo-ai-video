import { useCallback, useRef, useState, useEffect } from "react"
import { type GenerationPreflightDialogState } from "./workflow-canvas-asset-model"
import { type StoryboardNode } from "./workflow-canvas-model"
import {
  isReferenceLimitPreflightIssue,
  preflightIssueText,
} from "./workflow-edit-history-model"
import { workflowNodeMediaType } from "./workflow-node-relations"
import { toast } from "sonner"
import {
  preflightWorkflowNode,
  type ModelCapabilitiesSnapshot,
} from "@/backend"
import type { BackendCaller } from "@/backend"
import type { WorkflowCanvasDocument } from "./workflow-canvas-document"
export function useWorkflowGenerationPreflight({
  projectId,
  episodeId,
  callBackend,
  canvasDocument,
}: {
  projectId: string
  episodeId: string
  callBackend: BackendCaller
  canvasDocument: WorkflowCanvasDocument
}) {
  const [generationPreflightDialog, setGenerationPreflightDialog] =
    useState<GenerationPreflightDialogState | null>(null)

  const modelCapabilitiesSnapshotRef = useRef<ModelCapabilitiesSnapshot | null>(
    null
  )

  const cacheCapabilities = useCallback(
    (snapshot: ModelCapabilitiesSnapshot | null) => {
      modelCapabilitiesSnapshotRef.current = snapshot
    },
    []
  )

  const preflightNodeGeneration = useCallback(
    async (node: StoryboardNode) => {
      const requestScope = canvasDocument.scope
      const mediaType = workflowNodeMediaType(node)
      if (!mediaType) return true
      const check = await preflightWorkflowNode(
        callBackend,
        projectId,
        episodeId,
        {
          routeId: node.data.routeId,
          nodeId: node.id,
          nodeType: node.data.eyebrow,
          mediaType,
          strategy: node.data.strategy,
          referenceMediaIds: node.data.referenceMediaIds,
          reason: "run_node_preflight",
          writeBack: false,
          returnProductionStatus: false,
        }
      )
      if (canvasDocument.scope !== requestScope) return false
      const blockingIssues = check.blockingIssues ?? []
      const warnings = check.warnings ?? []
      const capabilityCheck = {
        success: check.success,
        warnings,
        blockingIssues,
        model: check.model ?? null,
        qualityGates: check.qualityGates,
        preflight: check.preflight,
      }
      const applyPreflightResult = (item: StoryboardNode): StoryboardNode => {
        if (item.id !== node.id) return item
        let nextStatus = item.data.status
        if (blockingIssues.length) {
          nextStatus = "preflight_failed"
        } else if (nextStatus === "preflight_failed") {
          nextStatus = "ready"
        }
        return {
          ...item,
          data: {
            ...item.data,
            status: nextStatus,
            resolvedConfig: check.resolvedConfig,
            capabilityCheck,
            quality: {
              ...(item.data.quality ?? {}),
              modelPreflight: {
                success: check.success,
                warnings,
                blockingIssues,
              },
            },
          },
        }
      }
      if (
        check.workflowVersion !== undefined &&
        check.workflowVersion !== null
      ) {
        canvasDocument.confirmRevision(check.workflowVersion)
      }
      canvasDocument.updateNodes((current) =>
        current.map((item) => applyPreflightResult(item))
      )
      if (blockingIssues.length) {
        const referenceLimitIssue = blockingIssues.find(
          isReferenceLimitPreflightIssue
        )
        const blockingIssue = referenceLimitIssue ?? blockingIssues[0]
        const blockingText =
          preflightIssueText(blockingIssue) || "生成预检未通过"
        if (referenceLimitIssue) {
          setGenerationPreflightDialog({ message: blockingText })
        } else {
          toast.error(`生成预检未通过：${blockingText}`)
        }
        return false
      }
      const visibleWarnings = warnings.filter(
        (warning) => !isReferenceLimitPreflightIssue(warning)
      )
      if (visibleWarnings.length) {
        toast.warning(`生成预检提醒：${preflightIssueText(visibleWarnings[0])}`)
      }
      return true
    },
    [
      callBackend,
      episodeId,
      projectId,
      canvasDocument.updateNodes,
      canvasDocument.confirmRevision,
    ]
  )
  useEffect(() => {
    setGenerationPreflightDialog(null)
    modelCapabilitiesSnapshotRef.current = null
  }, [projectId, episodeId])
  const readCapabilities = useCallback(
    () => modelCapabilitiesSnapshotRef.current,
    []
  )
  return {
    check: preflightNodeGeneration,
    dialog: generationPreflightDialog,
    setDialog: setGenerationPreflightDialog,
    cacheCapabilities,
    readCapabilities,
  }
}
export type WorkflowGenerationPreflight = ReturnType<
  typeof useWorkflowGenerationPreflight
>
