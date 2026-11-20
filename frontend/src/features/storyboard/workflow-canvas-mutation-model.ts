// Shared parsing of canvas mutation envelopes and projection records.
export function canvasPlainObject(
  value: unknown
): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined
}

export function canvasProjectionRows(
  payload: unknown
): Array<Record<string, unknown>> {
  const rows: Array<Record<string, unknown>> = []
  const append = (value: unknown) => {
    if (Array.isArray(value)) {
      value.forEach(append)
      return
    }
    const row = canvasPlainObject(value)
    if (row) rows.push(row)
  }
  canvasMutationEnvelopeSources(payload).forEach((source) => {
    append(source.projection)
    append(source.projections)
    const records = canvasPlainObject(source.records)
    append(records?.projections)
  })
  return rows
}

export function canvasProjectionText(row: Record<string, unknown>) {
  return String(
    row.type ?? row.cacheType ?? row.cache_type ?? row.key ?? row.id ?? ""
  )
    .trim()
    .toLowerCase()
}

export function canvasMutationEnvelopeSources(
  payload: unknown
): Array<Record<string, unknown>> {
  const root = canvasPlainObject(payload)
  if (!root) return []
  const sources: Array<Record<string, unknown>> = []
  const seen = new Set<Record<string, unknown>>()
  const addSource = (source?: Record<string, unknown>) => {
    if (!source || seen.has(source)) return
    seen.add(source)
    sources.push(source)
  }
  const addBasicMutationSource = (source?: Record<string, unknown>) => {
    if (!source) return
    addSource(source)
    addSource(canvasPlainObject(source.result))
    addSource(canvasPlainObject(source.version))
  }
  const addMutationSource = (source?: Record<string, unknown>) => {
    if (!source) return
    addBasicMutationSource(source)
    const projectEffect = canvasPlainObject(source.projectEffect)
    if (projectEffect) {
      addBasicMutationSource(projectEffect)
    }
  }
  addMutationSource(root)
  addMutationSource(canvasPlainObject(root.task))
  if (Array.isArray(root.tasks)) {
    root.tasks.forEach((task) => addMutationSource(canvasPlainObject(task)))
  }
  return sources
}
