export function createCanvasInputMutationQueue() {
  const canvases = new Map<string, Map<string, Promise<void>>>()

  return {
    run<T>(canvasKey: string, nodeId: string, operation: () => Promise<T>): Promise<T> {
      const targets = canvases.get(canvasKey) ?? new Map<string, Promise<void>>()
      canvases.set(canvasKey, targets)
      const previous = targets.get(nodeId) ?? Promise.resolve()
      const result = previous.then(operation)
      const settled = result.then(() => undefined, () => undefined)
      targets.set(nodeId, settled)
      void settled.then(() => {
        if (targets.get(nodeId) === settled) targets.delete(nodeId)
        if (!targets.size) canvases.delete(canvasKey)
      })
      return result
    },

    async waitForCanvas(canvasKey: string) {
      // Generation must observe all input changes accepted before its snapshot.
      while (canvases.get(canvasKey)?.size) {
        await Promise.all(canvases.get(canvasKey)!.values())
      }
    },
  }
}

// Keep request ordering across canvas switches and component remounts.
export const canvasInputMutations = createCanvasInputMutationQueue()
