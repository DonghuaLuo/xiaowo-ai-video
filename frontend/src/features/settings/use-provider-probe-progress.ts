import { useCallback, useEffect, useRef, useState } from "react"
import { PluginSDK } from "xiaowo-sdk"
import { providerCapabilityGroupOptions } from "./provider-model"

export type ProviderProbeProgress = Record<string, {
  status: "pending" | "testing" | "ok" | "failed" | "unsupported" | "unknown"
  modelCount?: number
}>

type ProbeEvent = {
  requestId: string
  group: string
  status: "testing" | "ok" | "failed" | "unsupported" | "unknown"
  modelCount?: number
}

export function useProviderProbeProgress(fingerprint: string) {
  const [progress, setProgress] = useState<ProviderProbeProgress>({})
  const active = useRef<{ requestId: string; fingerprint: string } | null>(null)
  const currentFingerprint = useRef(fingerprint)
  currentFingerprint.current = fingerprint

  useEffect(() => {
    active.current = null
    setProgress({})
  }, [fingerprint])

  useEffect(() => {
    const handleProgress = (event: ProbeEvent) => {
      if (
        !event || !active.current ||
        event.requestId !== active.current.requestId ||
        active.current.fingerprint !== currentFingerprint.current ||
        !providerCapabilityGroupOptions.some((option) => option.id === event.group) ||
        !["testing", "ok", "failed", "unsupported", "unknown"].includes(event.status)
      ) return
      setProgress((current) => ({
        ...current,
        [event.group]: { status: event.status, modelCount: event.modelCount },
      }))
    }
    PluginSDK.onBackendEvent("provider_probe_progress", handleProgress)
    return () => {
      active.current = null
      PluginSDK.offBackendEvent("provider_probe_progress", handleProgress)
    }
  }, [])

  const begin = useCallback((capabilities: string[]) => {
    const requestId = crypto.randomUUID()
    active.current = { requestId, fingerprint }
    const pending: ProviderProbeProgress = {}
    for (const option of providerCapabilityGroupOptions) {
      if (option.capabilities.some((capability) => capabilities.includes(capability))) {
        pending[option.id] = { status: "pending" }
      }
    }
    setProgress(pending)
    return requestId
  }, [fingerprint])

  const finish = useCallback((requestId: string) => {
    if (active.current?.requestId !== requestId) return
    active.current = null
    setProgress({})
  }, [])

  return {
    progress: active.current?.fingerprint === fingerprint ? progress : {},
    begin,
    finish,
  }
}
