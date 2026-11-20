import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import type { BackendCaller } from "@/backend"
import {
  fallbackModelConfig,
  getModelDisplayName,
  mergeModelConfigResponse,
  type ModelConfigResponse,
} from "@/features/settings/model-config-model"
import { backendFailureMessage, isBackendFailure } from "@/shared/backend-result"

export type AssistantReasoningEffort = "low" | "medium" | "high" | "xhigh" | "max"
type ProjectAgentSettings = {
  agentModelId?: string
  agentReasoningEffort?: AssistantReasoningEffort | ""
  projectConfigRevision: number
  success?: false
  message?: string
}

export function useAssistantModelSelection({
  projectId,
  backendReady,
  callBackend,
  onBackendEvent,
}: {
  projectId: string
  backendReady: boolean
  callBackend: BackendCaller
  onBackendEvent: (eventName: string, callback: (payload: unknown) => void) => () => void
}) {
  const [modelState, setModelState] = useState<ModelConfigResponse>(fallbackModelConfig)
  const [selectedModelId, setSelectedModelId] = useState("")
  const [selectedReasoningEffort, setSelectedReasoningEffort] = useState<AssistantReasoningEffort | "">("")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const projectIdentityRef = useRef({ projectId })
  const savingIdentityRef = useRef<typeof projectIdentityRef.current | null>(null)
  const revisionRef = useRef<{ identity: typeof projectIdentityRef.current; value: number } | null>(null)
  if (projectIdentityRef.current.projectId !== projectId) projectIdentityRef.current = { projectId }

  useEffect(() => {
    let cancelled = false
    let requestId = 0
    const effectIdentity = projectIdentityRef.current
    const invalidate = () => {
      cancelled = true
      if (projectIdentityRef.current === effectIdentity) {
        projectIdentityRef.current = { projectId }
        if (savingIdentityRef.current === effectIdentity) savingIdentityRef.current = null
      }
    }
    setSelectedModelId("")
    setSelectedReasoningEffort("")
    revisionRef.current = null
    setLoading(true)
    setSaving(false)
    if (!backendReady) return invalidate

    const reload = () => {
      const currentRequestId = ++requestId
      setLoading(true)
      void Promise.all([
        callBackend<ModelConfigResponse & { success?: false; message?: string }>(
          "list_models", { status: "adapted" }
        ),
        callBackend<ProjectAgentSettings>(
          "get_project_settings", { projectId }
        ),
      ]).then(([models, projectSettings]) => {
        if (cancelled || requestId !== currentRequestId) return
        if (isBackendFailure(models)) throw new Error(backendFailureMessage(models, "加载智能体模型失败"))
        if (isBackendFailure(projectSettings)) throw new Error(backendFailureMessage(projectSettings, "加载项目智能体模型失败"))
        setModelState(mergeModelConfigResponse(models))
        setSelectedModelId(String(projectSettings.agentModelId || "").trim())
        setSelectedReasoningEffort(projectSettings.agentReasoningEffort || "")
        revisionRef.current = { identity: effectIdentity, value: projectSettings.projectConfigRevision }
      }).catch((error) => {
        if (!cancelled && requestId === currentRequestId) {
          toast.error(error instanceof Error ? error.message : "加载智能体模型失败")
        }
      }).finally(() => {
        if (!cancelled && requestId === currentRequestId) setLoading(false)
      })
    }
    reload()
    const unsubscribeModelConfig = onBackendEvent("model_config_changed", reload)
    const unsubscribeProject = onBackendEvent("project_changed", (payload) => {
      const event = payload as { projectId?: string; action?: string } | null
      if (event?.projectId === projectId && event.action === "settings_saved") reload()
    })
    return () => { invalidate(); unsubscribeModelConfig(); unsubscribeProject() }
  }, [backendReady, callBackend, onBackendEvent, projectId])

  const saveSelection = useCallback(async (
    requestIdentity: typeof projectIdentityRef.current,
    settings: { agentModelId?: string; agentReasoningEffort?: AssistantReasoningEffort | "" }
  ) => {
    const readCurrentRevision = async () => {
      const current = await callBackend<ProjectAgentSettings>("get_project_settings", { projectId })
      if (isBackendFailure(current)) throw new Error(backendFailureMessage(current, "加载项目配置版本失败"))
      if (!Number.isInteger(current.projectConfigRevision) || current.projectConfigRevision < 0)
        throw new Error("项目配置版本无效，请重新加载")
      return current.projectConfigRevision
    }
    let revision = revisionRef.current?.identity === requestIdentity
      ? revisionRef.current.value
      : await readCurrentRevision()
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const result = await callBackend<{ success?: true; message?: string; settings?: ProjectAgentSettings }>(
        "save_project_settings",
        { projectId, settings: { ...settings, expectedRevision: revision } }
      )
      if (!isBackendFailure(result)) {
        if (projectIdentityRef.current === requestIdentity && Number.isInteger(result.settings?.projectConfigRevision)) {
          revisionRef.current = { identity: requestIdentity, value: result.settings!.projectConfigRevision }
        }
        return
      }
      const message = backendFailureMessage(result, "保存项目智能体设置失败")
      if (attempt === 0 && message.includes("资源版本已变化") && projectIdentityRef.current === requestIdentity) {
        revision = await readCurrentRevision()
        continue
      }
      throw new Error(message)
    }
  }, [callBackend, projectId])

  const selectModel = useCallback(async (modelId: string) => {
    if (saving || loading || modelId === selectedModelId || savingIdentityRef.current === projectIdentityRef.current) return
    const requestIdentity = projectIdentityRef.current
    savingIdentityRef.current = requestIdentity
    setSaving(true)
    try {
      await saveSelection(requestIdentity, { agentModelId: modelId, agentReasoningEffort: "" })
      if (projectIdentityRef.current === requestIdentity) {
        setSelectedModelId(modelId)
        setSelectedReasoningEffort("")
      }
    } catch (error) {
      if (projectIdentityRef.current === requestIdentity) {
        toast.error(error instanceof Error ? error.message : "保存智能体模型失败")
      }
    } finally {
      if (projectIdentityRef.current === requestIdentity) {
        savingIdentityRef.current = null
        setSaving(false)
      }
    }
  }, [loading, saving, saveSelection, selectedModelId])

  const selectReasoningEffort = useCallback(async (effort: AssistantReasoningEffort | "") => {
    if (saving || loading || effort === selectedReasoningEffort || savingIdentityRef.current === projectIdentityRef.current) return
    const requestIdentity = projectIdentityRef.current
    savingIdentityRef.current = requestIdentity
    setSaving(true)
    try {
      await saveSelection(requestIdentity, { agentReasoningEffort: effort })
      if (projectIdentityRef.current === requestIdentity) setSelectedReasoningEffort(effort)
    } catch (error) {
      if (projectIdentityRef.current === requestIdentity) {
        toast.error(error instanceof Error ? error.message : "保存推理能力失败")
      }
    } finally {
      if (projectIdentityRef.current === requestIdentity) {
        savingIdentityRef.current = null
        setSaving(false)
      }
    }
  }, [loading, saving, saveSelection, selectedReasoningEffort])

  const globalModelId = modelState.config.agent.model_id
  const globalModel = modelState.capabilities.agent.find((model) => model.id === globalModelId)
  const effectiveModelId = selectedModelId || globalModelId
  const effectiveModel = modelState.capabilities.agent.find((model) => model.id === effectiveModelId)
  const availableReasoningEfforts: AssistantReasoningEffort[] = effectiveModel?.reasoning_levels ??
    ["low", "medium", "high"]
  const effectiveReasoningEffort = selectedReasoningEffort && availableReasoningEfforts.includes(selectedReasoningEffort)
    ? selectedReasoningEffort
    : effectiveModel?.reasoning_default_mode || "medium"

  return {
    selectedModelId,
    selectedReasoningEffort,
    effectiveModelId,
    effectiveModelName: effectiveModel ? getModelDisplayName(effectiveModel) : effectiveModelId,
    effectiveReasoningEffort,
    availableReasoningEfforts,
    reasoningSupported: Boolean(effectiveModel?.reasoning_supported),
    globalModelId,
    globalModelName: globalModel ? getModelDisplayName(globalModel) : globalModelId,
    models: modelState.capabilities.agent,
    providers: modelState.providers,
    loading,
    saving,
    selectModel,
    selectReasoningEffort,
  }
}

export type AssistantModelSelectionController = ReturnType<typeof useAssistantModelSelection>
