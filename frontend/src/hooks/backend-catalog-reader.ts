const catalogMethods = new Set([
  "list_models",
  "get_project_creation_options",
  "get_script_adaptation_templates",
  "get_text_replacement_rules",
  "get_storyboard_templates",
  "get_director_rules",
])

type BackendCall = <T = unknown>(method: string, params: any) => Promise<T>

export function createBackendCatalogReader(call: BackendCall) {
  const pending = new Map<string, Promise<unknown>>()
  const clear = () => pending.clear()

  const read: BackendCall = async <T>(method: string, params: any): Promise<T> => {
    if (!catalogMethods.has(method)) {
      if (method.startsWith("get_") || method.startsWith("list_")) return call<T>(method, params)
      // Unknown commands may change settings. Never join a pre-write read.
      clear()
      try {
        return await call<T>(method, params)
      } finally {
        clear()
      }
    }
    const key = JSON.stringify([method, params])
    let request = pending.get(key)
    if (!request) {
      request = call(method, params)
      pending.set(key, request)
    }
    try {
      // Callers may edit form defaults; they must not share mutable response objects.
      return structuredClone(await request) as T
    } finally {
      if (pending.get(key) === request) pending.delete(key)
    }
  }

  return { read, clear }
}
