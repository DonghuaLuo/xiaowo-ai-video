const ASSET_IMAGE_UPDATE_ACTIONS = new Set([
  "asset_created", "asset_updated", "asset_media_generated",
  "asset_upserted", "asset_batch_saved",
  "asset_media_version_activated", "asset_media_version_updated",
])

type AssetImageNode = {
  id: string
  data: {
    eyebrow?: unknown
    rootAssetProjectId?: unknown
    rootAssetType?: unknown
    rootAssetId?: unknown
    creationPending?: unknown
  }
}

export function unboundCanvasAssetImageIds<T extends AssetImageNode>(
  nodes: T[], projectId: string, hasImage: (node: T) => boolean, event?: unknown
): string[] {
  const update = event && typeof event === "object" ? event as Record<string, unknown> : undefined
  if (event !== undefined && (!update || update.projectId !== projectId || !ASSET_IMAGE_UPDATE_ACTIONS.has(String(update.action)))) return []
  return nodes.filter((node) => {
    const data = node.data
    return data.eyebrow === "asset.image" && !data.creationPending && data.rootAssetProjectId === projectId &&
      Boolean(data.rootAssetId) && (!update?.assetId || update.assetId === data.rootAssetId) &&
      (!update?.assetType || update.assetType === data.rootAssetType) && !hasImage(node)
  }).map(node => node.id)
}

export function createCanvasReferenceViewReader<T extends { revision: number }>(
  read: () => Promise<T>,
  apply: (result: T) => void,
  onError: (error: unknown) => void
) {
  let disposed = false
  let sequence = 0
  let invalidation = 0
  let requestedRevision = -1
  let appliedRevision = -1
  let running = false

  async function run() {
    if (running) return
    running = true
    try {
      let handled = -1
      while (!disposed && handled !== sequence) {
        await Promise.resolve()
        handled = sequence
        const readInvalidation = invalidation
        try {
          const result = await read()
          if (disposed) continue
          if (handled !== sequence) {
            if (readInvalidation !== invalidation || result.revision < requestedRevision) continue
            handled = sequence
          }
          if (result.revision < requestedRevision) throw new Error("资产预览版本落后，请重试")
          appliedRevision = result.revision
          apply(result)
        } catch (error) {
          if (!disposed && handled === sequence) onError(error)
        }
      }
    } finally {
      running = false
    }
  }

  return {
    refresh(revision: number, force: boolean | "missing" = false) {
      // Missing previews during an existing read are not a new invalidation.
      // Explicit force remains available for asset edits at the same canvas revision.
      if (force === "missing" && running && revision <= requestedRevision) return
      if (disposed || (!force && revision <= Math.max(appliedRevision, requestedRevision))) return
      requestedRevision = Math.max(requestedRevision, revision)
      if (force === true) invalidation++
      sequence++
      void run()
    },
    reset() {
      requestedRevision = -1
      appliedRevision = -1
      invalidation++
      sequence++
    },
    dispose() { disposed = true },
  }
}
