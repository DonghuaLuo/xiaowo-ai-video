import { useCallback, useEffect, useMemo, useRef } from "react"
import type { VideoClipDialogSource } from "./video-clip-model"

/** Each source activation has a distinct lifetime, including A → B → A. */
export function useVideoClipActivation(
  projectId: string,
  episodeId: string,
  source: VideoClipDialogSource
) {
  const key = JSON.stringify([
    projectId,
    episodeId,
    source.nodeId,
    source.src,
    source.title,
    source.media.id,
    source.media.filePath,
    source.media.path,
    source.media.relativePath,
    source.media.relative_path,
  ])
  const current = useRef({ key, active: true })
  if (current.current.key !== key) {
    current.current.active = false
    current.current = { key, active: true }
  }
  const activation = current.current
  const isCurrent = useCallback(
    () => current.current === activation && activation.active,
    [activation]
  )
  useEffect(() => {
    activation.active = true
    return () => {
      activation.active = false
    }
  }, [activation])
  return useMemo(() => ({ isCurrent }), [isCurrent])
}
