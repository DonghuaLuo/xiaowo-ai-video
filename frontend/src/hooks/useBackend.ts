import { useSyncExternalStore, useCallback } from "react"
import { PluginSDK } from "xiaowo-sdk"
import { createBackendReadinessStore } from "./backend-readiness-store"
import { createBackendCatalogReader } from "./backend-catalog-reader"

const catalogs = createBackendCatalogReader((method, params) => PluginSDK.callBackend(method, params))

const readiness = createBackendReadinessStore({
  waitReady: () => PluginSDK.waitReady(),
  getBackendState: () => PluginSDK.getBackendState(),
  onBackendReady: callback => PluginSDK.onBackendReady(() => { catalogs.clear(); callback() }),
  onBackendExit: callback => PluginSDK.onBackendExit((...args) => { catalogs.clear(); callback(...args) }),
})

export function useBackend() {
  const state = useSyncExternalStore(readiness.subscribe, readiness.getSnapshot)

  const callBackend = useCallback(
    async <T = any>(method: string, params: any = {}): Promise<T> => {
      const { isReady, backendReady } = readiness.getSnapshot()
      if (!isReady) throw new Error("SDK 未就绪")
      if (!backendReady) console.warn("后端尚未就绪，但仍尝试调用:", method)
      return catalogs.read<T>(method, params)
    },
    []
  )

  const onBackendEvent = useCallback(
    (eventName: string, callback: (data: any) => void) => {
      const handleEvent = (data: any) => { catalogs.clear(); callback(data) }
      PluginSDK.onBackendEvent(eventName, handleEvent)
      return () => PluginSDK.offBackendEvent(eventName, handleEvent)
    },
    []
  )

  return { ...state, callBackend, onBackendEvent }
}
