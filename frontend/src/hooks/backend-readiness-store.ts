type BackendState = { isReady: boolean; backendReady: boolean; backendError: string }
type BackendStateSource = {
  waitReady: () => Promise<unknown>
  getBackendState: () => Promise<{ is_ready: boolean }>
  onBackendReady: (callback: () => void) => (() => void) | undefined
  onBackendExit: (callback: (info: { reason?: string } | null | undefined) => void) => (() => void) | undefined
}

const initialState: BackendState = { isReady: false, backendReady: false, backendError: "" }

export function createBackendReadinessStore(source: BackendStateSource) {
  let state = initialState
  let generation = 0
  let eventRevision = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let disposers: Array<(() => void) | undefined> = []
  const listeners = new Set<() => void>()

  function publish(next: Partial<BackendState>) {
    const merged = { ...state, ...next }
    if (merged.isReady === state.isReady && merged.backendReady === state.backendReady && merged.backendError === state.backendError) return
    state = merged
    listeners.forEach(listener => listener())
  }

  function clearTimer() {
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
  }

  function start() {
    const current = ++generation
    const active = () => current === generation && listeners.size > 0
    const schedule = () => {
      if (!active() || timer !== undefined) return
      timer = setTimeout(() => { timer = undefined; void sync() }, 1500)
    }
    const sync = async () => {
      const revision = eventRevision
      try {
        const result = await source.getBackendState()
        if (!active() || revision !== eventRevision) return
        publish({ backendReady: Boolean(result.is_ready), ...(result.is_ready ? { backendError: "" } : {}) })
        if (result.is_ready) clearTimer()
        else schedule()
      } catch (error) {
        if (!active() || revision !== eventRevision) return
        publish({ backendReady: false, backendError: error instanceof Error ? error.message : "查询后端状态失败" })
        schedule()
      }
    }
    disposers = [
      source.onBackendReady(() => {
        if (!active()) return
        eventRevision++
        clearTimer()
        publish({ isReady: true, backendReady: true, backendError: "" })
      }),
      source.onBackendExit(info => {
        if (!active()) return
        eventRevision++
        publish({ backendReady: false, backendError: info?.reason || "后端进程已退出" })
        schedule()
      }),
    ]
    void source.waitReady().then(() => {
      if (!active()) return
      publish({ isReady: true })
      void sync()
    }).catch(error => {
      if (active()) publish({ backendError: error instanceof Error ? error.message : "SDK 初始化失败" })
    })
  }

  function stop() {
    generation++
    clearTimer()
    disposers.forEach(dispose => dispose?.())
    disposers = []
    state = initialState
  }

  return {
    getSnapshot: () => state,
    subscribe(listener: () => void) {
      listeners.add(listener)
      if (listeners.size === 1) start()
      return () => {
        listeners.delete(listener)
        if (!listeners.size) stop()
      }
    },
  }
}
