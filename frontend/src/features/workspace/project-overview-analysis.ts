import { useEffect, useState } from "react"
import { analyzeProjectOverview } from "@/backend"
import { assertProjectOverviewReady } from "@/features/workspace/project-readiness"
import { DEFAULT_OVERVIEW_EXCERPT_CHARS } from "@/features/settings/model-config-model"
import { errMsg } from "@/shared/backend-result"


type ProjectOverviewAnalysisState =
  | { status: "idle" }
  | { status: "running"; startedAt: number }
  | { status: "failed"; errorText: string; finishedAt: number }

type ProjectOverviewAnalysisResult = Awaited<
  ReturnType<typeof analyzeProjectOverview>
>

type ProjectOverviewAnalysisOptions = {
  sourceId?: string
  excerptChars?: number
}

const PROJECT_OVERVIEW_ANALYSIS_IDLE: ProjectOverviewAnalysisState = {
  status: "idle",
}

const projectOverviewAnalysisStates = new Map<
  string,
  ProjectOverviewAnalysisState
>()

const projectOverviewAnalysisPromises = new Map<
  string,
  Promise<ProjectOverviewAnalysisResult>
>()

const projectOverviewAnalysisListeners = new Map<string, Set<() => void>>()

export function getProjectOverviewAnalysisState(projectId: string) {
  return (
    projectOverviewAnalysisStates.get(projectId) ??
    PROJECT_OVERVIEW_ANALYSIS_IDLE
  )
}

function emitProjectOverviewAnalysisState(projectId: string) {
  projectOverviewAnalysisListeners.get(projectId)?.forEach((listener) => {
    listener()
  })
}

function setProjectOverviewAnalysisState(
  projectId: string,
  state: ProjectOverviewAnalysisState
) {
  if (state.status === "idle") {
    projectOverviewAnalysisStates.delete(projectId)
  } else {
    projectOverviewAnalysisStates.set(projectId, state)
  }
  emitProjectOverviewAnalysisState(projectId)
}

function subscribeProjectOverviewAnalysisState(
  projectId: string,
  listener: () => void
) {
  const listeners =
    projectOverviewAnalysisListeners.get(projectId) ?? new Set<() => void>()
  listeners.add(listener)
  projectOverviewAnalysisListeners.set(projectId, listeners)

  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) {
      projectOverviewAnalysisListeners.delete(projectId)
    }
  }
}

export function useProjectOverviewAnalysisState(projectId: string) {
  const [state, setState] = useState(() =>
    getProjectOverviewAnalysisState(projectId)
  )

  useEffect(() => {
    setState(getProjectOverviewAnalysisState(projectId))
    return subscribeProjectOverviewAnalysisState(projectId, () => {
      setState(getProjectOverviewAnalysisState(projectId))
    })
  }, [projectId])

  return state
}

export function runProjectOverviewAnalysis(
  callBackend: Parameters<typeof analyzeProjectOverview>[0],
  projectId: string,
  options: ProjectOverviewAnalysisOptions = {}
) {
  const current = projectOverviewAnalysisPromises.get(projectId)
  if (current) return current

  setProjectOverviewAnalysisState(projectId, {
    status: "running",
    startedAt: Date.now(),
  })

  const promise = analyzeProjectOverview(
    callBackend,
    projectId,
    options.sourceId,
    { excerptChars: options.excerptChars }
  )
    .then((result) => {
      assertProjectOverviewReady(result.project)
      setProjectOverviewAnalysisState(projectId, PROJECT_OVERVIEW_ANALYSIS_IDLE)
      return result
    })
    .catch((error) => {
      setProjectOverviewAnalysisState(projectId, {
        status: "failed",
        errorText: errMsg(error, "小说概述分析失败"),
        finishedAt: Date.now(),
      })
      throw error
    })
    .finally(() => {
      projectOverviewAnalysisPromises.delete(projectId)
    })

  projectOverviewAnalysisPromises.set(projectId, promise)
  return promise
}

export function loadOverviewAnalysisConfig() {
  return {
    excerptChars: DEFAULT_OVERVIEW_EXCERPT_CHARS,
  } as const
}
