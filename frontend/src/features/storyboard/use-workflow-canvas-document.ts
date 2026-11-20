import { useEffect, useRef, useSyncExternalStore } from "react"
import { createWorkflowCanvasDocument } from "./workflow-canvas-document"

export function useWorkflowCanvasDocument(scopeKey: string) {
  const documentRef = useRef<ReturnType<
    typeof createWorkflowCanvasDocument
  > | null>(null)
  documentRef.current ??= createWorkflowCanvasDocument(scopeKey)
  const document = documentRef.current
  document.activate(scopeKey)
  useSyncExternalStore(document.subscribe, document.read, document.read)
  useEffect(() => {
    document.activate(scopeKey)
    const scope = document.scope
    return () => document.dispose(scope)
  }, [document, scopeKey])
  return document
}
